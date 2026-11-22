from __future__ import annotations

from pathlib import Path

import pytest
from langgraph.cache.memory import InMemoryCache
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command

from rashomon.graph import Deps, build_graph
from rashomon.llm.demo_script import demo_answer, demo_llm
from rashomon.ticket import load_ticket, ticket_hash

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "invoice_app"
TICKET_FILE = REPO / "examples" / "tickets" / "export-invoices.md"


@pytest.fixture
def ticket() -> dict:
    return load_ticket(str(TICKET_FILE), REPO)


def initial_state(ticket: dict, **extra) -> dict:
    return {
        "ticket": ticket,
        "ticket_hash": ticket_hash(ticket),
        "fingerprint": "test",
        "repo_path": str(EXAMPLE),
        "repo_key": "invoice_app",
        "threshold": 0.8,
        "max_rounds": 3,
        **extra,
    }


def compile_graph(llm=None, tracker=None, store=None, cache=None):
    deps = Deps(llm=llm or demo_llm(), tracker=tracker)
    return build_graph(deps).compile(
        checkpointer=InMemorySaver(),
        store=store if store is not None else InMemoryStore(),
        cache=cache if cache is not None else InMemoryCache(),
    )


def run_to_end(graph, state: dict, thread: str = "t", answer=demo_answer, max_steps: int = 10):
    """Drive a run, answering every question with ``answer``. Returns (interrupt payloads, final values)."""
    config = {"configurable": {"thread_id": thread}}
    payloads = []
    out = graph.invoke(state, config)
    for _ in range(max_steps):
        if "__interrupt__" not in out:
            break
        payload = out["__interrupt__"][0].value
        payloads.append(payload)
        if payload["kind"] == "approve_post":
            resume = answer(payload)
        else:
            resume = {q["id"]: answer(q) for q in payload["questions"]}
        out = graph.invoke(Command(resume=resume), config)
    return payloads, graph.get_state(config).values
