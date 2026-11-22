"""Terminal rendering. Pure presentation: nothing here decides anything."""

from __future__ import annotations

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from rashomon.diff import lens_value
from rashomon.lenses import BY_ID, LENSES, letters

GROUP_STYLES = ("cyan", "magenta", "yellow", "green", "blue")
MAX_PRESENCE_ROWS = 4
CELL = 13


def _short(text: str, width: int = CELL) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def bar(score: float, threshold: float, width: int = 24) -> Text:
    filled = round(score * width)
    mark = min(width - 1, round(threshold * width))
    out = Text()
    for i in range(width):
        ch = "█" if i < filled else "░"
        style = "green" if score >= threshold else "yellow"
        if i == mark:
            out.append("│", style="bold white")
        else:
            out.append(ch, style=style if i < filled else "dim")
    return out


class Renderer:
    def __init__(self, console: Console) -> None:
        self.c = console

    # ------------------------------------------------------------------ progress
    def header(self, ticket: dict, repo: str, model: str, thread: str) -> None:
        self.c.print(Text.assemble(("rashomon", "bold"), "  ", (ticket.get("title", ""), "bold cyan")))
        self.c.print(f"[dim]ticket {ticket.get('id')} · repo {repo} · model {model} · thread {thread}[/dim]")

    def ground(self, update: dict, cached: bool) -> None:
        pack = update["context"]
        kinds: dict[str, int] = {}
        for e in pack["entities"]:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        summary = ", ".join(
            f"{n} {k}{'es' if k == 'class' and n > 1 else 's' if n > 1 else ''}"
            for k, n in sorted(kinds.items(), key=lambda x: -x[1])
        )
        tag = " [green](cached)[/green]" if cached else ""
        self.c.print(
            f"\n[bold]● ground[/bold]{tag}  {len(pack['files'])} files · {summary or 'no entities'} · "
            f"{len(pack['hits'])} text hits ({pack['search_backend']})"
        )
        for e in pack["entities"][:5]:
            self.c.print(f"  [dim]{e['kind']:<9}[/dim] {e['name']:<28} [dim]{e['path']}:{e['line']}[/dim]")
        if len(pack["entities"]) > 5:
            self.c.print(f"  [dim]… {len(pack['entities']) - 5} more[/dim]")

    def round_start(self, rnd: int, settled: int) -> None:
        extra = f" · {settled} settled decision{'s' if settled != 1 else ''} in the prompt" if settled else ""
        self.c.print(f"\n[bold]● round {rnd}[/bold]  five lenses read the ticket independently{extra}")

    def plan(self, record: dict, notes: list[dict]) -> None:
        lens = BY_ID[record["lens"]]
        plan = record["plan"]
        if plan is None:
            self.c.print(f"  [red]{lens.letter} {lens.name:<13} failed[/red]")
            return
        new = sum(1 for f in plan["files"] if f["change"] == "new")
        line = Text.assemble(
            (f"  {lens.letter} ", "bold"),
            (f"{lens.name:<13}", ""),
            (f" {plan['size']:<3}", "bold"),
            (
                f"{len(plan['files'])} files ({new} new) · {len(plan['assumptions'])} assumptions · "
                f"{len(plan['behaviours'])} behaviours",
                "dim",
            ),
        )
        self.c.print(line)
        for n in notes:
            self.c.print(f"      [yellow]guard[/yellow] [dim]{n['code']}:[/dim] {n['detail']}")

    def matrix(self, analysis: dict) -> None:
        divs = analysis["divergences"]
        if not divs:
            self.c.print("\n  [green]no divergences: the five plans agree[/green]")
            return
        askable = [d for d in divs if d["askable"]]
        presence = [d for d in divs if not d["askable"]]
        table = Table(
            title="divergence matrix", title_style="bold", title_justify="left", box=box.SIMPLE_HEAD, pad_edge=False
        )
        table.add_column("open point", style="bold", no_wrap=True, max_width=20)
        table.add_column("impact", justify="right", min_width=6, no_wrap=True)
        for lens in LENSES:
            table.add_column(f"{lens.letter} {lens.name.split()[0].lower()}", no_wrap=True, max_width=CELL)
        for d in askable + presence[:MAX_PRESENCE_ROWS]:
            styles = {g["value"]: GROUP_STYLES[i % len(GROUP_STYLES)] for i, g in enumerate(d["groups"])}
            cells = []
            for lens in LENSES:
                v = lens_value(d, lens.id)
                if v is None:
                    cells.append(Text("·", style="dim"))
                elif d["kind"] == "presence":
                    cells.append(Text("yes" if v != "leaves it out" else "-", style=styles[v]))
                else:
                    cells.append(Text(_short(v), style=styles[v]))
            topic = _short(d["topic"], 20)
            table.add_row(Text(topic, style="bold" if d["askable"] else "dim"), f"{d['impact']:.1f}", *cells)
        self.c.print()
        self.c.print(table)
        hidden = len(presence) - MAX_PRESENCE_ROWS
        if hidden > 0:
            self.c.print(f"  [dim]+ {hidden} more file / behaviour / scope differences (in the spec)[/dim]")
        for d in askable:
            split = " · ".join(f"[bold]{letters(g['lenses'])}[/bold] {g['value']}" for g in d["groups"])
            self.c.print(f"  [dim]{d['topic']}:[/dim] {split}")

    def score(self, entry: dict, threshold: float, decision: str) -> None:
        verdict = {
            "ask": "[yellow]below threshold: asking[/yellow]",
            "converged": "[green]converged[/green]",
            "max_rounds": "[red]round limit reached[/red]",
            "nothing_to_ask": "[yellow]nothing askable left[/yellow]",
            "predicted": "[dim]prediction only[/dim]",
            "error": "[red]not enough plans[/red]",
        }[decision]
        line = Text.assemble("\n  convergence ", (f"{entry['score']:.2f} ", "bold"))
        line.append_text(bar(entry["score"], threshold))
        line.append(f" threshold {threshold:.2f}  ")
        self.c.print(line, end="")
        self.c.print(verdict)

    def question_notes(self, notes: list[dict]) -> None:
        for n in notes:
            self.c.print(f"  [yellow]guard[/yellow] [dim]{n['code']}:[/dim] {n['detail']}")

    def questions(self, payload: dict) -> None:
        self.c.print(
            f"\n[bold]● ask[/bold]  {len(payload['questions'])} question(s), options are values the plans took"
        )
        for q in payload["questions"]:
            self.c.print(f"\n  [bold]{q['id']}[/bold] {q['question']}  [dim](impact {q['impact']:.1f})[/dim]")
            for i, o in enumerate(q["options"], 1):
                rec = (
                    "  [green]← recommended: " + q["recommended_because"] + "[/green]"
                    if o["value"] == q["recommended"]
                    else ""
                )
                self.c.print(f"     {i}. {o['value']}  [dim]{letters(o['lenses'])}[/dim]{rec}")

    def answers(self, answers: dict[str, str], source: str) -> None:
        for qid, value in answers.items():
            self.c.print(f"  [dim]{qid} →[/dim] {value}  [dim]({source})[/dim]")

    def waiting(self, thread: str) -> None:
        self.c.print(
            f"\n[yellow]paused[/yellow] waiting for answers. Answer any time, the run is checkpointed:\n"
            f"  rashomon answer {thread} q1=1 q2=2 ...   or   rashomon resume {thread}"
        )

    def approval(self, payload: dict) -> None:
        self.c.print(f"\n[bold]● approve_post[/bold]  post the spec as a comment on {payload['target']}?")

    def final(self, state: dict, spec_path: str | None) -> None:
        hist = state.get("history", [])
        trail = " → ".join(f"{h['score']:.2f}" for h in hist)
        outcome = state.get("outcome", "?")
        color = "green" if outcome == "converged" else "yellow"
        self.c.print(
            f"\n[bold]● spec[/bold]  [{color}]{outcome}[/{color}] after {state.get('round', 0)} round(s) · "
            f"convergence {trail} · {len(state.get('answered', []))} answer(s) · "
            f"{len(state.get('notes', []))} guard correction(s)"
        )
        if spec_path:
            self.c.print(f"  [dim]written to[/dim] {spec_path}")
        if state.get("posted"):
            self.c.print(f"  [dim]posted to[/dim] {state['posted']}")
