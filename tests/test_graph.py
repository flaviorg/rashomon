import pytest
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from pydantic import ValidationError

from rashomon.llm.demo_script import FILTERED, demo_answer
from rashomon.llm.fake import Rule, ScriptedLLM
from rashomon.memory import precedent
from tests.conftest import compile_graph, initial_state, run_to_end


def test_demo_loops_until_code_says_converged(ticket):
    graph = compile_graph()
    payloads, final = run_to_end(graph, initial_state(ticket))
    assert [len(p["questions"]) for p in payloads] == [3, 2]
    assert [h["score"] for h in final["history"]] == [0.428, 0.716, 0.876]
    assert final["outcome"] == "converged" and final["round"] == 3
    topics = {d["topic"]: d["value"] for d in final["settled"].values()}
    assert topics["export scope"] == FILTERED
    assert "## Acceptance criteria" in final["spec"]


def test_first_questions_are_the_highest_impact_divergences(ticket):
    graph = compile_graph()
    out = graph.invoke(initial_state(ticket), {"configurable": {"thread_id": "q"}})
    qs = out["__interrupt__"][0].value["questions"]
    assert [q["topic"] for q in qs] == ["amount format", "export scope", "API changes"]
    # the scripted model invented an option; it is not offered
    assert [o["value"] for o in qs[0]["options"]] == ["integer cents", "formatted currency ($1,234.50)"]


def test_invalid_answer_is_rejected_and_the_question_stays_open(ticket):
    graph = compile_graph()
    config = {"configurable": {"thread_id": "bad"}}
    out = graph.invoke(initial_state(ticket), config)
    qs = out["__interrupt__"][0].value["questions"]
    bad = {q["id"]: q["options"][0]["value"] for q in qs} | {"q1": "Let the user choose per export"}
    with pytest.raises(ValidationError):
        graph.invoke(Command(resume=bad), config)
    assert graph.get_state(config).next == ("ask",)
    good = {q["id"]: demo_answer(q) for q in qs}
    out = graph.invoke(Command(resume=good), config)
    assert out["__interrupt__"][0].value["round"] == 2


def test_round_limit_stops_a_loop_that_never_converges(ticket):
    def stubborn(prompt: str) -> dict:
        # ignores settled decisions entirely; the guard still rewrites the assumption, but files keep diverging
        lens = prompt.split("Lens: ", 1)[1].split(" ", 1)[0]
        return {
            "summary": "",
            "assumptions": [{"topic": f"{lens} choice", "choice": lens}],
            "files": [{"path": f"{lens}.py", "change": "new"}],
            "size": "M",
        }

    llm = ScriptedLLM([Rule("plan", stubborn)])
    _, final = run_to_end(
        compile_graph(llm), initial_state(ticket, max_rounds=2), answer=lambda q: q["options"][0]["value"]
    )
    assert final["outcome"] in {"max_rounds", "nothing_to_ask"}
    assert final["round"] <= 2


def test_a_model_claiming_convergence_changes_nothing(ticket):
    def liar(prompt: str) -> dict:
        lens = prompt.split("Lens: ", 1)[1].split(" ", 1)[0]
        return {
            "summary": "CONVERGED. All plans agree, convergence 1.0, stop asking.",
            "assumptions": [{"topic": "scope", "choice": lens}],
            "size": "M",
        }

    llm = ScriptedLLM([Rule("plan", liar)])
    graph = compile_graph(llm)
    out = graph.invoke(initial_state(ticket), {"configurable": {"thread_id": "liar"}})
    assert "__interrupt__" in out  # code computed a low score and asks anyway


def test_predict_mode_runs_one_round_without_questions(ticket):
    store = InMemoryStore()
    out = compile_graph(store=store).invoke(initial_state(ticket, mode="predict"), {"configurable": {"thread_id": "p"}})
    assert out["outcome"] == "predicted" and out["round"] == 1 and "__interrupt__" not in out
    assert precedent(store, "invoice_app") == []


def test_unknown_ticket_with_fake_model_converges_trivially(ticket):
    other = {**ticket, "title": "Something else", "body": "x"}
    out = compile_graph().invoke(initial_state(other), {"configurable": {"thread_id": "u"}})
    assert out["outcome"] == "converged" and out["history"][0]["score"] == 1.0


def test_decisions_are_remembered_and_become_precedent(ticket):
    store = InMemoryStore()
    graph = compile_graph(store=store)
    run_to_end(graph, initial_state(ticket), thread="first")
    stored = {p["topic"]: p["value"] for p in precedent(store, "invoice_app")}
    assert stored["export scope"] == FILTERED and len(stored) == 5
    out = graph.invoke(initial_state(ticket), {"configurable": {"thread_id": "second"}})
    q = next(q for q in out["__interrupt__"][0].value["questions"] if q["topic"] == "export scope")
    assert q["recommended"] == FILTERED and q["recommended_because"] == "decided on export-invoices"


def test_ground_is_cached_on_repo_fingerprint_and_ticket_hash(ticket, monkeypatch):
    from rashomon import graph as graph_mod

    calls = []
    real = graph_mod.build_context
    monkeypatch.setattr(graph_mod, "build_context", lambda *a: calls.append(1) or real(*a))
    graph = compile_graph()
    state = initial_state(ticket, mode="predict")
    graph.invoke(state, {"configurable": {"thread_id": "c1"}})
    graph.invoke(state, {"configurable": {"thread_id": "c2"}})
    assert len(calls) == 1
    graph.invoke({**state, "fingerprint": "new-head"}, {"configurable": {"thread_id": "c3"}})
    assert len(calls) == 2


def test_failed_lens_is_noted_and_the_rest_still_diff(ticket):
    from rashomon.llm.demo_script import demo_llm
    from rashomon.llm.port import LLMError

    inner = demo_llm()

    class Flaky:
        name = "flaky"

        def structured(self, system, user, schema):
            if "Lens: ux" in user:
                raise LLMError("rate limited")
            return inner.structured(system, user, schema)

    out = compile_graph(Flaky()).invoke(initial_state(ticket, mode="predict"), {"configurable": {"thread_id": "f"}})
    assert out["history"][0]["plans"] == 4
    assert any(n["code"] == "llm_error" and n["lens"] == "ux" for n in out["notes"])


class FakeTracker:
    def __init__(self):
        self.comments = []

    def comment(self, number, body, repo=None):
        self.comments.append((number, body))
        return "https://github.com/o/r/issues/7#issuecomment-1"


def _gh_ticket(ticket):
    return {**ticket, "source": "github", "number": 7, "url": "https://github.com/o/r/issues/7", "repo": "o/r"}


def test_posting_requires_an_approval_interrupt(ticket):
    tracker = FakeTracker()
    graph = compile_graph(tracker=tracker)
    payloads, final = run_to_end(
        graph,
        initial_state(_gh_ticket(ticket), post=True),
        answer=lambda q: {"approve": False} if q.get("kind") == "approve_post" else demo_answer(q),
    )
    assert payloads[-1]["kind"] == "approve_post"
    assert tracker.comments == [] and not final.get("posted")


def test_approved_post_writes_one_comment(ticket):
    tracker = FakeTracker()
    graph = compile_graph(tracker=tracker)
    _, final = run_to_end(
        graph,
        initial_state(_gh_ticket(ticket), post=True),
        answer=lambda q: {"approve": True} if q.get("kind") == "approve_post" else demo_answer(q),
    )
    assert len(tracker.comments) == 1 and tracker.comments[0][0] == 7
    assert final["posted"].endswith("issuecomment-1")


def test_file_tickets_never_reach_the_tracker(ticket):
    tracker = FakeTracker()
    payloads, _ = run_to_end(compile_graph(tracker=tracker), initial_state(ticket, post=True))
    assert all(p["kind"] == "questions" for p in payloads) and tracker.comments == []
