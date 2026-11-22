"""Persistence and the drive loop shared by the CLI, the demo and backtest.

One state directory (default ``.rashomon``) holds three SQLite files:

* ``checkpoints.sqlite``: the ``SqliteSaver`` checkpointer, so a run paused on questions can be
  answered days later from a different process;
* ``store.sqlite``: the ``SqliteStore`` with past decisions per repo (precedent);
* ``cache.sqlite``: the ``SqliteCache`` behind ``ground``'s ``CachePolicy``.
"""

from __future__ import annotations

import sqlite3
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langgraph.cache.sqlite import SqliteCache
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.store.sqlite import SqliteStore
from langgraph.types import Command

from rashomon.graph import Deps, build_graph

Answerer = Callable[[dict], dict | None]


@dataclass
class Outcome:
    status: str  # "done" | "waiting" | "error"
    state: dict = field(default_factory=dict)
    pending: dict | None = None
    error: str = ""


@contextmanager
def open_graph(state_dir: Path, deps: Deps) -> Iterator[Any]:
    state_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(state_dir / "checkpoints.sqlite", check_same_thread=False)
    store_conn = sqlite3.connect(state_dir / "store.sqlite", check_same_thread=False, isolation_level=None)
    try:
        store = SqliteStore(store_conn)
        store.setup()
        graph = build_graph(deps).compile(
            checkpointer=SqliteSaver(conn),
            store=store,
            cache=SqliteCache(path=str(state_dir / "cache.sqlite")),
        )
        yield graph
    finally:
        conn.close()
        store_conn.close()


def repo_key(repo: Path) -> str:
    """Stable id for the Store namespace: the origin remote if there is one, else the folder name."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10
        )
        if out.returncode == 0 and out.stdout.strip():
            url = out.stdout.strip().removesuffix(".git")
            return url.rsplit(":", 1)[-1].split("github.com/")[-1]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return repo.resolve().name


def drive(
    graph: Any,
    first: dict | Command,
    config: dict,
    on_update: Callable[[str, dict, dict], None] | None = None,
    answerer: Answerer | None = None,
) -> Outcome:
    """Stream the graph. At each interrupt, ask ``answerer``; ``None`` from it means: stop and wait."""
    payload: dict | Command = first
    while True:
        pending = None
        for chunk in graph.stream(payload, config, stream_mode="updates"):
            meta = chunk.get("__metadata__") or {}
            for node, update in chunk.items():
                if node == "__interrupt__":
                    pending = update[0].value
                elif node != "__metadata__" and on_update is not None:
                    on_update(node, update or {}, meta)
        state = graph.get_state(config).values
        if pending is None:
            return Outcome("done", state)
        answer = answerer(pending) if answerer else None
        if answer is None:
            return Outcome("waiting", state, pending)
        payload = Command(resume=answer)


def pending_interrupt(graph: Any, config: dict) -> dict | None:
    snap = graph.get_state(config)
    for task in snap.tasks:
        for intr in task.interrupts:
            return intr.value
    return None
