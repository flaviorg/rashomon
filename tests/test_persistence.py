"""Answers can arrive days later, from a different process: the run lives in SQLite."""

from langgraph.types import Command

from rashomon.graph import Deps
from rashomon.llm.demo_script import demo_answer, demo_llm
from rashomon.runtime import drive, open_graph, pending_interrupt
from tests.conftest import initial_state


def test_pause_close_reopen_and_answer(tmp_path, ticket):
    config = {"configurable": {"thread_id": "later"}}
    with open_graph(tmp_path, Deps(llm=demo_llm())) as graph:
        first = drive(graph, initial_state(ticket), config)
    assert first.status == "waiting" and first.pending["round"] == 1

    # a new process: fresh connections, fresh model object
    with open_graph(tmp_path, Deps(llm=demo_llm())) as graph:
        pending = pending_interrupt(graph, config)
        assert pending["questions"] == first.pending["questions"]
        resume = {q["id"]: demo_answer(q) for q in pending["questions"]}
        outcome = drive(
            graph, Command(resume=resume), config, answerer=lambda p: {q["id"]: demo_answer(q) for q in p["questions"]}
        )
    assert outcome.status == "done" and outcome.state["outcome"] == "converged"
    assert {"checkpoints.sqlite", "store.sqlite", "cache.sqlite"} <= {p.name for p in tmp_path.iterdir()}


def test_store_survives_between_runs(tmp_path, ticket):
    from rashomon.memory import precedent

    answer_all = lambda p: {q["id"]: demo_answer(q) for q in p["questions"]}  # noqa: E731
    with open_graph(tmp_path, Deps(llm=demo_llm())) as graph:
        drive(graph, initial_state(ticket), {"configurable": {"thread_id": "a"}}, answerer=answer_all)
    with open_graph(tmp_path, Deps(llm=demo_llm())) as graph:
        assert len(precedent(graph.store, "invoice_app")) == 5
