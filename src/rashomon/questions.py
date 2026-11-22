"""Turn the top divergences into multiple-choice questions.

Code picks which divergences to ask about (by impact) and what the options are (the values the
plans actually took). The model only phrases the question. Any option it returns that no plan
proposed is dropped, and every value a plan proposed is offered, so the human always chooses
between real interpretations.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, create_model

from rashomon.lenses import letters
from rashomon.llm.port import LLM, LLMError
from rashomon.models import QuestionDrafts
from rashomon.prompts import QUESTIONS_SYSTEM, questions_prompt
from rashomon.text import jaccard, tokens

MAX_QUESTIONS = 3
OPTION_MATCH = 0.8
PRECEDENT_MATCH = 0.5


def is_settled(divergence: dict, settled: dict[str, dict]) -> bool:
    if divergence["id"] in settled:
        return True
    topic = tokens(divergence["topic"])
    return any(
        d["dimension"] == divergence["dimension"] and jaccard(tokens(d["topic"]), topic) >= 0.5
        for d in settled.values()
    )


def select(analysis: dict, settled: dict[str, dict], limit: int = MAX_QUESTIONS) -> list[dict]:
    open_rows = [d for d in analysis["divergences"] if d["askable"] and d["impact"] > 0 and not is_settled(d, settled)]
    return open_rows[:limit]


def _precedent_for(divergence: dict, precedent: list[dict]) -> dict | None:
    topic = tokens(divergence["topic"])
    for p in precedent:
        if p.get("dimension") != divergence["dimension"]:
            continue
        if jaccard(tokens(p["topic"]), topic) < PRECEDENT_MATCH:
            continue
        for g in divergence["groups"]:
            if jaccard(tokens(g["value"]), tokens(p["value"])) >= OPTION_MATCH:
                return {**p, "value": g["value"]}
    return None


def template_question(divergence: dict) -> str:
    if divergence["kind"] == "set":
        return f"Which {divergence['topic']} should this ticket make?"
    return f"{divergence['topic'].capitalize()}: which one did you mean?"


def validate(
    drafts: list[dict], selected: list[dict], precedent: list[dict] | None = None
) -> tuple[list[dict], list[dict]]:
    """Merge model drafts into code-built questions. Returns (questions, guard notes)."""
    notes: list[dict] = []
    by_id = {d["divergence_id"]: d for d in drafts}
    for extra in sorted(set(by_id) - {d["id"] for d in selected}):
        notes.append({"code": "unknown_divergence", "detail": f"ignored a question for {extra!r}"})
    questions = []
    for i, div in enumerate(selected, 1):
        allowed = [g["value"] for g in div["groups"]]
        draft = by_id.get(div["id"])
        ordered: list[str] = []
        if draft:
            for opt in draft.get("options", []):
                match = next((a for a in allowed if a == opt or jaccard(tokens(a), tokens(opt)) >= OPTION_MATCH), None)
                if match is None:
                    notes.append(
                        {"code": "invented_option", "detail": f"{div['topic']}: dropped {opt!r} (no plan said it)"}
                    )
                elif match not in ordered:
                    ordered.append(match)
        missing = [a for a in allowed if a not in ordered]
        if draft and missing:
            notes.append(
                {
                    "code": "missing_option",
                    "detail": f"{div['topic']}: restored {len(missing)} option(s) a plan proposed",
                }
            )
        ordered += missing
        text = (draft or {}).get("question", "").strip() or template_question(div)
        groups = {g["value"]: g for g in div["groups"]}
        prec = _precedent_for(div, precedent or [])
        majority = div["groups"][0]["value"]
        questions.append(
            {
                "id": f"q{i}",
                "divergence_id": div["id"],
                "dimension": div["dimension"],
                "topic": div["topic"],
                "question": text,
                "options": [
                    {"value": v, "lenses": groups[v]["lenses"], "items": groups[v].get("items", [])} for v in ordered
                ],
                "recommended": prec["value"] if prec else majority,
                "recommended_because": (
                    f"decided on {prec.get('ticket', 'an earlier ticket')}"
                    if prec
                    else f"majority ({letters(groups[majority]['lenses'])})"
                ),
                "impact": div["impact"],
            }
        )
    return questions, notes


def draft(llm: LLM, ticket: dict, selected: list[dict], precedent: list[dict]) -> tuple[list[dict], list[dict], int]:
    """Ask the model to phrase questions; fall back to templates if it fails."""
    if not selected:
        return [], [], 0
    try:
        reply = llm.structured(QUESTIONS_SYSTEM, questions_prompt(ticket, selected), QuestionDrafts)
        drafts = [q.model_dump() for q in reply.value.questions]
        tokens_used = reply.tokens
        notes: list[dict] = []
    except LLMError as exc:
        drafts, tokens_used = [], 0
        notes = [{"code": "llm_error", "detail": f"question phrasing failed, used templates: {exc}"}]
    questions, more = validate(drafts, selected, precedent)
    return questions, notes + more, tokens_used


def answer_schema(questions: list[dict]) -> type[BaseModel]:
    """A Pydantic model whose fields only accept the offered values. Passed to ``interrupt(response_schema=...)``."""
    fields = {q["id"]: (Literal[tuple(o["value"] for o in q["options"])], ...) for q in questions}
    return create_model("Answers", __config__=ConfigDict(extra="forbid"), **fields)
