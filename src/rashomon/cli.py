"""Command line: run, demo, answer, resume, backtest, decisions, graph."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.prompt import Prompt

from rashomon import __version__
from rashomon.graph import DEFAULT_MAX_ROUNDS, Deps
from rashomon.ground import fingerprint
from rashomon.lenses import LENSES
from rashomon.llm import LLMError, make_llm, resolve_model
from rashomon.llm.demo_script import demo_answer
from rashomon.runtime import Outcome, drive, open_graph, pending_interrupt, repo_key
from rashomon.score import DEFAULT_THRESHOLD
from rashomon.spec import apply_to_speckit
from rashomon.text import slug
from rashomon.ticket import TicketError, load_ticket, ticket_hash
from rashomon.tracker import GhTracker, TrackerError
from rashomon.ui import Renderer

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Run a vague ticket through five independent, repo-grounded readings. Their disagreements are your questions.",
)

EXIT_CONVERGED, EXIT_NOT_CONVERGED, EXIT_ERROR, EXIT_WAITING = 0, 1, 2, 3
PACKAGE = Path(__file__).resolve().parent


def find_example(name: str) -> Path:
    """Bundled sample files: the source tree when running from a checkout, else the installed copy."""
    for base in (PACKAGE.parents[1] / "examples", PACKAGE / "_examples"):
        if (base / name).exists():
            return base / name
    raise FileNotFoundError(name)


def _console(json_out: bool) -> Console:
    return Console(stderr=json_out, highlight=False)


class Session:
    """Glue between the graph stream and the renderer."""

    def __init__(self, renderer: Renderer, threshold: float) -> None:
        self.r = renderer
        self.threshold = threshold
        self._settled = 0
        self._plans: list[tuple[dict, list[dict]]] = []

    def on_update(self, node: str, update: dict, meta: dict) -> None:
        if node == "ground":
            self.r.ground(update, bool(meta.get("cached")))
        elif node == "dispatch":
            self.r.round_start(update["round"], self._settled)
        elif node == "interpret":
            # the five lenses run in parallel; print them in lens order once all are in
            for record in update.get("plans", []):
                self._plans.append((record, update.get("notes", [])))
        elif node == "diff_plans":
            order = {lens.id: i for i, lens in enumerate(LENSES)}
            for record, notes in sorted(self._plans, key=lambda x: order.get(x[0]["lens"], 99)):
                self.r.plan(record, notes)
            self._plans = []
            self.r.matrix(update["analysis"])
        elif node == "score_convergence":
            self.r.score(update["history"][-1], self.threshold, update["decision"])
        elif node == "draft_questions":
            self.r.question_notes(update.get("notes", []))
        elif node == "ask":
            self._settled = len(update.get("settled", {}))


def parse_answers(pending: dict, raw: list[str]) -> dict:
    """``q1=2`` (option number) or ``q1=the filtered view`` (exact value); ``approve=yes|no`` for posting."""
    if pending["kind"] == "approve_post":
        for item in raw:
            key, _, value = item.partition("=")
            if key.strip() == "approve":
                return {"approve": value.strip().lower() in {"y", "yes", "true", "1"}}
        raise typer.BadParameter("answer with approve=yes or approve=no")
    out: dict[str, str] = {}
    by_id = {q["id"]: q for q in pending["questions"]}
    for item in raw:
        key, _, value = item.partition("=")
        q = by_id.get(key.strip())
        if q is None:
            raise typer.BadParameter(f"unknown question {key!r}; pending: {', '.join(by_id)}")
        values = [o["value"] for o in q["options"]]
        value = value.strip()
        if value.isdigit() and 1 <= int(value) <= len(values):
            out[q["id"]] = values[int(value) - 1]
        elif value in values:
            out[q["id"]] = value
        else:
            raise typer.BadParameter(f"{key}: {value!r} is not one of the options (1-{len(values)} or exact text)")
    missing = [qid for qid in by_id if qid not in out]
    if missing:
        raise typer.BadParameter(f"missing answers for {', '.join(missing)}")
    return out


def interactive_answerer(console: Console, renderer: Renderer):
    def answer(pending: dict) -> dict:
        if pending["kind"] == "approve_post":
            renderer.approval(pending)
            console.print(pending["preview"][:400] + " …", style="dim")
            ok = Prompt.ask("  post it?", choices=["y", "n"], default="n", console=console)
            return {"approve": ok == "y"}
        renderer.questions(pending)
        out = {}
        for q in pending["questions"]:
            values = [o["value"] for o in q["options"]]
            default = str(values.index(q["recommended"]) + 1)
            pick = Prompt.ask(
                f"  {q['id']}", choices=[str(i) for i in range(1, len(values) + 1)], default=default, console=console
            )
            out[q["id"]] = values[int(pick) - 1]
        return out

    return answer


def demo_answerer(renderer: Renderer):
    def answer(pending: dict) -> dict:
        if pending["kind"] == "approve_post":
            return {"approve": False}
        renderer.questions(pending)
        out = {q["id"]: demo_answer(q) for q in pending["questions"]}
        renderer.c.print()
        renderer.answers(out, "scripted demo answer")
        return out

    return answer


def waiting_answerer(renderer: Renderer):
    def answer(pending: dict) -> None:
        if pending["kind"] == "questions":
            renderer.questions(pending)
        else:
            renderer.approval(pending)
        return None

    return answer


def finish(
    outcome: Outcome,
    renderer: Renderer,
    state_dir: Path,
    thread: str,
    out: Path | None,
    speckit: Path | None,
    json_out: bool,
) -> int:
    state = outcome.state
    if outcome.status == "waiting":
        renderer.waiting(thread)
        code = EXIT_WAITING
        spec_path = None
    else:
        spec_path = None
        if state.get("spec"):
            run_dir = state_dir / "runs" / thread
            run_dir.mkdir(parents=True, exist_ok=True)
            spec_path = run_dir / "spec.md"
            spec_path.write_text(state["spec"])
            out = out or (Path(state["out"]) if state.get("out") else None)
            speckit = speckit or (Path(state["speckit"]) if state.get("speckit") else None)
            if out:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(state["spec"])
                spec_path = out
            if speckit and state.get("answered"):
                apply_to_speckit(speckit, state["answered"])
        renderer.final(state, str(spec_path) if spec_path else None)
        code = {"converged": EXIT_CONVERGED, "error": EXIT_ERROR}.get(state.get("outcome", ""), EXIT_NOT_CONVERGED)
    if json_out:
        sys.stdout.write(
            json.dumps(
                {
                    "thread": thread,
                    "status": outcome.status,
                    "outcome": state.get("outcome"),
                    "rounds": state.get("round"),
                    "convergence": [h["score"] for h in state.get("history", [])],
                    "settled": list(state.get("settled", {}).values()),
                    "pending": outcome.pending,
                    "spec_path": str(spec_path) if spec_path else None,
                    "guard_notes": state.get("notes", []),
                },
                indent=2,
            )
            + "\n"
        )
    return code


def start_run(
    ticket: dict,
    repo: Path,
    model: str,
    state_dir: Path,
    thread: str | None,
    threshold: float,
    max_rounds: int,
    post: bool,
    console: Console,
    answerer_kind: str,
    out: Path | None = None,
    speckit: Path | None = None,
    json_out: bool = False,
) -> int:
    renderer = Renderer(console)
    thread = thread or f"{slug(ticket['id'])}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    try:
        llm = make_llm(model)
    except LLMError as exc:
        console.print(f"[red]error:[/red] {exc}")
        return EXIT_ERROR
    deps = Deps(llm=llm, tracker=GhTracker(cwd=repo))
    renderer.header(ticket, repo.name, model, thread)
    session = Session(renderer, threshold)
    answerer = {
        "interactive": interactive_answerer(console, renderer),
        "demo": demo_answerer(renderer),
        "none": waiting_answerer(renderer),
    }[answerer_kind]
    state: dict[str, Any] = {
        "ticket": ticket,
        "ticket_hash": ticket_hash(ticket),
        "fingerprint": fingerprint(repo),
        "repo_path": str(repo),
        "repo_key": repo_key(repo),
        "threshold": threshold,
        "max_rounds": max_rounds,
        "post": post,
        "mode": "ask",
        "model": model,
        "out": str(out.resolve()) if out else "",
        "speckit": str(speckit.resolve()) if speckit else "",
    }
    with open_graph(state_dir, deps) as graph:
        outcome = drive(graph, state, {"configurable": {"thread_id": thread}}, session.on_update, answerer)
    return finish(outcome, renderer, state_dir, thread, out, speckit, json_out)


StateDir = Annotated[Path, typer.Option("--state-dir", help="Checkpoints, Store and cache live here.")]


@app.command()
def run(
    ticket: Annotated[str, typer.Argument(help="GH-123, owner/repo#123, or a text/Markdown file.")],
    repo: Annotated[Path, typer.Option(help="Repository to ground the ticket in.")] = Path("."),
    model: Annotated[str | None, typer.Option(help="provider:model, or 'fake'.")] = None,
    threshold: Annotated[float, typer.Option(help="Convergence needed to stop asking.")] = DEFAULT_THRESHOLD,
    max_rounds: Annotated[int, typer.Option(help="Interpretation rounds before giving up.")] = DEFAULT_MAX_ROUNDS,
    no_input: Annotated[
        bool, typer.Option("--no-input", help="Do not prompt: pause and exit 3 with questions.")
    ] = False,
    out: Annotated[Path | None, typer.Option(help="Also write the spec here.")] = None,
    post: Annotated[bool, typer.Option(help="Offer to post the spec on the GitHub issue (asks for approval).")] = False,
    gh_repo: Annotated[str | None, typer.Option(help="owner/name for GH-123 refs outside the repo's remote.")] = None,
    speckit: Annotated[
        Path | None, typer.Option(help="Append the answers to this spec-kit spec.md as Clarifications.")
    ] = None,
    thread: Annotated[str | None, typer.Option(help="Thread id (default: ticket + timestamp).")] = None,
    state_dir: StateDir = Path(".rashomon"),
    json_out: Annotated[bool, typer.Option("--json", help="Summary as JSON on stdout.")] = False,
) -> None:
    """Interpret a ticket five ways, ask about the disagreements, write a spec."""
    console = _console(json_out)
    repo = repo.resolve()
    try:
        loaded = load_ticket(ticket, repo, GhTracker(cwd=repo), gh_repo)
    except TicketError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_ERROR) from exc
    interactive = not no_input and sys.stdin.isatty() and not json_out
    code = start_run(
        loaded, repo, resolve_model(model), state_dir, thread, threshold, max_rounds, post, console,
        "interactive" if interactive else "none", out, speckit, json_out,
    )  # fmt: skip
    raise typer.Exit(code)


@app.command()
def demo(
    interactive: Annotated[bool, typer.Option(help="Answer the questions yourself.")] = False,
    state_dir: StateDir = Path(".rashomon"),
    json_out: Annotated[bool, typer.Option("--json", help="Summary as JSON on stdout.")] = False,
) -> None:
    """Run the bundled ticket against the bundled sample repo with the scripted offline model."""
    console = _console(json_out)
    repo = find_example("invoice_app")
    ticket = load_ticket(str(find_example("tickets/export-invoices.md")), repo)
    code = start_run(
        ticket, repo, "fake", state_dir, None, DEFAULT_THRESHOLD, DEFAULT_MAX_ROUNDS, False, console,
        "interactive" if interactive else "demo", None, None, json_out,
    )  # fmt: skip
    raise typer.Exit(code)


def _continue(thread: str, state_dir: Path, raw: list[str] | None, model: str | None, json_out: bool) -> int:
    console = _console(json_out)
    renderer = Renderer(console)
    probe = Deps(llm=make_llm("fake"))
    with open_graph(state_dir, probe) as graph:
        config = {"configurable": {"thread_id": thread}}
        values = graph.get_state(config).values
        pending = pending_interrupt(graph, config)
    if not values:
        console.print(f"[red]error:[/red] no run {thread!r} in {state_dir}")
        return EXIT_ERROR
    if pending is None:
        console.print(f"[yellow]{thread} is not waiting for anything[/yellow] (outcome: {values.get('outcome')})")
        return EXIT_ERROR
    chosen = model or values.get("model") or resolve_model(None)
    deps = Deps(llm=make_llm(chosen), tracker=GhTracker(cwd=Path(values["repo_path"])))
    session = Session(renderer, values.get("threshold", DEFAULT_THRESHOLD))
    session._settled = len(values.get("settled", {}))
    if raw is not None:
        try:
            first = parse_answers(pending, raw)
        except typer.BadParameter as exc:
            console.print(f"[red]error:[/red] {exc}")
            return EXIT_ERROR
        renderer.answers(first, "given") if pending["kind"] == "questions" else None
        answerer = (
            waiting_answerer(renderer)
            if not sys.stdin.isatty() or json_out
            else interactive_answerer(console, renderer)
        )
    else:
        first = None
        answerer = interactive_answerer(console, renderer)
    from langgraph.types import Command

    with open_graph(state_dir, deps) as graph:
        try:
            if first is None:
                first = answerer(pending)
            outcome = drive(graph, Command(resume=first), config, session.on_update, answerer)
        except ValidationError as exc:
            console.print(f"[red]error:[/red] answer rejected by the response schema: {exc.errors()[0]['msg']}")
            return EXIT_ERROR
    return finish(outcome, renderer, state_dir, thread, None, None, json_out)  # out/speckit come from the run state


@app.command()
def answer(
    thread: Annotated[str, typer.Argument(help="Thread id printed when the run paused.")],
    answers: Annotated[list[str], typer.Argument(help="q1=2 (option number) or q1='exact value'; approve=yes|no.")],
    model: Annotated[str | None, typer.Option(help="Override the model recorded with the run.")] = None,
    state_dir: StateDir = Path(".rashomon"),
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Answer a paused run's questions (minutes or days later) and continue it."""
    raise typer.Exit(_continue(thread, state_dir, answers, model, json_out))


@app.command()
def resume(
    thread: Annotated[str, typer.Argument()],
    model: Annotated[str | None, typer.Option()] = None,
    state_dir: StateDir = Path(".rashomon"),
) -> None:
    """Show a paused run's questions and answer them interactively."""
    raise typer.Exit(_continue(thread, state_dir, None, model, False))


@app.command()
def backtest(
    dataset: Annotated[Path | None, typer.Argument(help="JSONL of closed issues: id, title, body, changes[].")] = None,
    repo: Annotated[Path, typer.Option(help="Repository to ground the tickets in.")] = Path("."),
    gh: Annotated[str | None, typer.Option(help="owner/name: use closed GitHub issues (comments as changes).")] = None,
    limit: Annotated[int, typer.Option(help="With --gh, how many closed issues.")] = 20,
    model: Annotated[str | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Measure whether round-1 divergences predicted later requirement changes."""
    from rashomon.backtest import backtest as run_backtest
    from rashomon.backtest import from_github, load_dataset

    console = _console(json_out)
    repo = repo.resolve()
    chosen = resolve_model(model)
    if dataset is None and gh is None:
        dataset = find_example("backtest/closed_issues.jsonl")
        repo = find_example("invoice_app")
        console.print("[dim]no dataset given: using the bundled sample (scripted model, mechanics only)[/dim]")
    try:
        cases = load_dataset(dataset) if dataset else from_github(GhTracker(cwd=repo), gh, limit)
        report = run_backtest(cases, repo, Deps(llm=make_llm(chosen)), repo_key(repo))
    except (TrackerError, LLMError, OSError, ValueError) as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(EXIT_ERROR) from exc
    if json_out:
        sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
        raise typer.Exit(0)
    for case in report.cases:
        console.print(f"\n[bold]{case.id}[/bold] {case.title}  [dim]round-1 convergence {case.score:.2f}[/dim]")
        for p in case.predicted:
            mark = "[green]hit[/green] " if p["hit"] else "[dim]miss[/dim]"
            console.print(f"  {mark} predicted {p['topic']}: [dim]{p['split']}[/dim]")
        for c in case.changes:
            where = f"[green]→ {c['matched']}[/green]" if c["matched"] else "[dim]→ not predicted[/dim]"
            console.print(f"  change: {c['text'][:90]}  {where}")
    console.print(
        f"\n[bold]{len(report.cases)} issues · {report.changes} later changes · "
        f"change recall {report.change_recall:.0%} · question precision {report.question_precision:.0%}[/bold]"
    )
    if chosen == "fake":
        console.print("[dim]scripted model: these numbers test the mechanics, they are not a measurement[/dim]")
    raise typer.Exit(0)


@app.command()
def decisions(
    repo: Annotated[Path, typer.Option()] = Path("."),
    state_dir: StateDir = Path(".rashomon"),
    demo_repo: Annotated[bool, typer.Option("--demo", help="Show decisions stored for the bundled demo repo.")] = False,
) -> None:
    """List past decisions stored for a repo (used as precedent by later runs)."""
    from rashomon.memory import precedent

    console = Console(highlight=False)
    target = find_example("invoice_app") if demo_repo else repo.resolve()
    with open_graph(state_dir, Deps(llm=make_llm("fake"))) as graph:
        rows = precedent(graph.store, repo_key(target), limit=200)
    if not rows:
        console.print(f"[dim]no stored decisions for {repo_key(target)}[/dim]")
    for r in rows:
        console.print(f"{r['decided_on']}  [bold]{r['topic']}[/bold] = {r['value']}  [dim]({r['ticket']})[/dim]")


@app.command()
def graph() -> None:
    """Print the Mermaid diagram of the compiled graph."""
    from rashomon.graph import render_mermaid

    print(render_mermaid())


@app.command()
def version() -> None:
    """Print the version."""
    print(__version__)
