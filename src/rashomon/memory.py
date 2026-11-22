"""Past decisions, kept in the LangGraph ``Store`` so later tickets in the same repo can cite them."""

from __future__ import annotations

from datetime import date

from langgraph.store.base import BaseStore

from rashomon.text import slug


def namespace(repo_key: str) -> tuple[str, ...]:
    return ("rashomon", slug(repo_key), "decisions")


def precedent(store: BaseStore | None, repo_key: str, limit: int = 50) -> list[dict]:
    if store is None:
        return []
    items = store.search(namespace(repo_key), limit=limit)
    return sorted((item.value for item in items), key=lambda v: (v.get("decided_on", ""), v.get("topic", "")))


def remember(
    store: BaseStore | None, repo_key: str, ticket: dict, answered: list[dict], today: str | None = None
) -> int:
    if store is None:
        return 0
    today = today or date.today().isoformat()
    for a in answered:
        store.put(
            namespace(repo_key),
            f"{a['dimension']}-{slug(a['topic'])}",
            {
                "dimension": a["dimension"],
                "topic": a["topic"],
                "value": a["value"],
                "question": a["question"],
                "ticket": ticket.get("id", ""),
                "decided_on": today,
            },
        )
    return len(answered)
