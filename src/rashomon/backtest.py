"""Backtest: did the divergences predict how the requirements later changed?

For each closed issue: run one round on the *original* ticket text (``mode="predict"``: no
questions, no Store writes), take the top divergences rashomon would have asked about, and
check each later requirement change (a comment, an edit, a follow-up) against them.

* **change recall**: share of later changes that land on a predicted divergence.
* **question precision**: share of predicted questions that some later change landed on.

Matching is token containment (code, not a model), so it is conservative and noisy in the same
direction every time. A dataset is JSONL: ``{"id", "title", "body", "changes": [str, ...]}``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from rashomon import questions
from rashomon.graph import Deps, build_graph
from rashomon.ground import fingerprint
from rashomon.lenses import letters
from rashomon.text import containment, tokens
from rashomon.ticket import ticket_hash
from rashomon.tracker import GhTracker

MATCH = 0.5


@dataclass
class CaseResult:
    id: str
    title: str
    predicted: list[dict]
    changes: list[dict]
    score: float

    @property
    def hits(self) -> int:
        return sum(1 for c in self.changes if c["matched"])


@dataclass
class Report:
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def changes(self) -> int:
        return sum(len(c.changes) for c in self.cases)

    @property
    def change_recall(self) -> float:
        return sum(c.hits for c in self.cases) / self.changes if self.changes else 0.0

    @property
    def question_precision(self) -> float:
        asked = sum(len(c.predicted) for c in self.cases)
        used = sum(1 for c in self.cases for p in c.predicted if p["hit"])
        return used / asked if asked else 0.0

    def to_dict(self) -> dict:
        return {
            "cases": len(self.cases),
            "changes": self.changes,
            "change_recall": round(self.change_recall, 3),
            "question_precision": round(self.question_precision, 3),
            "results": [
                {
                    "id": c.id,
                    "title": c.title,
                    "round1_convergence": c.score,
                    "predicted": c.predicted,
                    "changes": c.changes,
                }
                for c in self.cases
            ],
        }


def match_change(change: str, divergences: list[dict]) -> tuple[str | None, float]:
    """Best divergence for a later change, by how much of its topic or one of its values the change mentions."""
    ctok = tokens(change)
    best, best_score = None, 0.0
    for d in divergences:
        candidates = [tokens(d["topic"])] + [tokens(g["value"]) for g in d["groups"]]
        s = max(containment(c, ctok) for c in candidates)
        if s > best_score:
            best, best_score = d["id"], s
    return (best, round(best_score, 2)) if best_score >= MATCH else (None, round(best_score, 2))


def load_dataset(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def from_github(tracker: GhTracker, repo: str | None, limit: int) -> list[dict]:
    """Closed issues as cases. Later changes are approximated by the issue's comments."""
    out = []
    for issue in tracker.list_closed(repo, limit):
        comments = [c.get("body", "") for c in issue.get("comments") or [] if c.get("body")]
        if not comments:
            continue
        out.append(
            {
                "id": f"#{issue['number']}",
                "title": issue.get("title", ""),
                "body": issue.get("body") or "",
                "changes": comments,
            }
        )
    return out


def run_case(graph, case: dict, repo: Path, key: str) -> CaseResult:
    ticket = {"id": case["id"], "title": case["title"], "body": case.get("body", ""), "source": "backtest", "url": ""}
    state = {
        "ticket": ticket,
        "ticket_hash": ticket_hash(ticket),
        "fingerprint": fingerprint(repo),
        "repo_path": str(repo),
        "repo_key": key,
        "mode": "predict",
    }
    final = graph.invoke(state, {"configurable": {"thread_id": f"backtest-{case['id']}"}})
    analysis = final["analysis"]
    top = questions.select(analysis, {})
    predicted = [
        {
            "id": d["id"],
            "topic": d["topic"],
            "split": "; ".join(f"{letters(g['lenses'])}: {g['value']}" for g in d["groups"]),
            "hit": False,
        }
        for d in top
    ]
    changes = []
    for text in case.get("changes", []):
        matched, score = match_change(text, top)
        changes.append({"text": text[:200], "matched": matched, "score": score})
        for p in predicted:
            if p["id"] == matched:
                p["hit"] = True
    return CaseResult(case["id"], case["title"], predicted, changes, final["history"][-1]["score"])


def backtest(cases: list[dict], repo: Path, deps: Deps, key: str) -> Report:
    graph = build_graph(deps).compile(checkpointer=InMemorySaver())
    return Report([run_case(graph, case, repo, key) for case in cases])
