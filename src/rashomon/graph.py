"""The LangGraph graph.

    ground ─► dispatch ─(Send x5)─► interpret ─► diff_plans (defer) ─► score_convergence
                 ▲                                                        │
                 └──────── ask (interrupt) ◄── draft_questions ◄──────────┤ below threshold
                                                                          ▼
                       write_spec ─► remember ─► [approve_post (interrupt) ─► post_comment]

Model calls happen in exactly two nodes: ``interpret`` (one per lens) and ``draft_questions``.
Everything that decides anything (what diverges, how much, what to ask, when to stop, whether
to write to the tracker) is code.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import CachePolicy, Send, interrupt
from pydantic import BaseModel

from rashomon import memory, questions
from rashomon.diff import analyse
from rashomon.ground import build_context, render_context
from rashomon.guard import guard_plan
from rashomon.lenses import BY_ID, LENSES
from rashomon.llm.port import LLM, LLMError
from rashomon.models import Plan
from rashomon.prompts import INTERPRET_SYSTEM, interpret_prompt
from rashomon.score import DEFAULT_THRESHOLD, convergence
from rashomon.spec import build_spec, current_records
from rashomon.tracker import GhTracker, TrackerError

DEFAULT_MAX_ROUNDS = 3


class State(TypedDict, total=False):
    # inputs
    ticket: dict
    ticket_hash: str
    fingerprint: str
    repo_path: str
    repo_key: str
    threshold: float
    max_rounds: int
    mode: str  # "ask" (default) | "predict" (one round, no questions: used by backtest)
    post: bool
    model: str
    out: str  # also write the spec here (CLI)
    speckit: str  # spec-kit spec.md to append Clarifications to (CLI)
    # working state
    context: dict
    round: int
    settled: dict
    precedent: list
    plans: Annotated[list, operator.add]
    analysis: dict
    history: Annotated[list, operator.add]
    pending: list
    answered: Annotated[list, operator.add]
    notes: Annotated[list, operator.add]
    tokens: Annotated[int, operator.add]
    decision: str
    outcome: str
    spec: str
    approved_post: bool
    posted: str


class LensTask(TypedDict):
    lens: str
    round: int
    ticket: dict
    context: dict
    settled: dict
    precedent: list


class PostApproval(BaseModel):
    approve: bool


@dataclass
class Deps:
    llm: LLM
    tracker: GhTracker | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def ground_cache_key(state: dict) -> str:
    """Grounding is reused while the repo (HEAD sha, or a content hash when dirty) and the ticket are unchanged."""
    return f"{state.get('fingerprint', '')}:{state.get('ticket_hash', '')}:{state.get('repo_path', '')}"


def build_graph(deps: Deps) -> StateGraph:
    def ground(state: State) -> dict:
        from pathlib import Path

        ticket = state["ticket"]
        pack = build_context(Path(state["repo_path"]), f"{ticket.get('title', '')}\n{ticket.get('body', '')}")
        return {"context": pack.to_dict(), "round": 0, "settled": state.get("settled") or {}}

    def dispatch(state: State, runtime: Runtime) -> dict:
        return {
            "round": state.get("round", 0) + 1,
            "precedent": memory.precedent(runtime.store, state.get("repo_key", "")),
            "pending": [],
        }

    def fan_out(state: State) -> list[Send]:
        return [
            Send(
                "interpret",
                {
                    "lens": lens.id,
                    "round": state["round"],
                    "ticket": state["ticket"],
                    "context": state["context"],
                    "settled": state.get("settled", {}),
                    "precedent": state.get("precedent", []),
                },
            )
            for lens in LENSES
        ]

    def interpret(task: LensTask) -> dict:
        lens = BY_ID[task["lens"]]
        prompt = interpret_prompt(
            lens, task["ticket"], render_context(task["context"]), task["settled"], task["precedent"], task["round"]
        )
        try:
            reply = deps.llm.structured(INTERPRET_SYSTEM, prompt, Plan)
        except LLMError as exc:
            note = {"round": task["round"], "lens": lens.id, "code": "llm_error", "detail": str(exc)[:300]}
            return {"plans": [{"lens": lens.id, "round": task["round"], "plan": None}], "notes": [note]}
        plan, notes = guard_plan(reply.value.model_dump(), set(task["context"]["files"]), task["settled"])
        return {
            "plans": [{"lens": lens.id, "round": task["round"], "plan": plan}],
            "notes": [{"round": task["round"], "lens": lens.id, **n} for n in notes],
            "tokens": reply.tokens,
        }

    def diff_plans(state: State) -> dict:
        return {"analysis": analyse(current_records(state))}

    def score_convergence(state: State) -> dict:
        records = current_records(state)
        conv = convergence(state["analysis"])
        threshold = state.get("threshold", DEFAULT_THRESHOLD)
        rnd = state["round"]
        to_ask = questions.select(state["analysis"], state.get("settled", {}))
        if len(records) < 2:
            decision = "error"
        elif conv["score"] >= threshold:
            decision = "converged"
        elif state.get("mode") == "predict":
            decision = "predicted"
        elif rnd >= state.get("max_rounds", DEFAULT_MAX_ROUNDS):
            decision = "max_rounds"
        elif not to_ask:
            decision = "nothing_to_ask"
        else:
            decision = "ask"
        entry = {
            "round": rnd,
            "score": conv["score"],
            "by_dimension": conv["by_dimension"],
            "divergences": len(state["analysis"]["divergences"]),
            "askable": len([d for d in state["analysis"]["divergences"] if d["askable"]]),
            "plans": len(records),
        }
        update: dict = {"history": [entry], "decision": decision, "pending": to_ask if decision == "ask" else []}
        if decision != "ask":
            update["outcome"] = decision
        return update

    def route_after_score(state: State) -> str:
        return "draft_questions" if state["decision"] == "ask" else "write_spec"

    def draft_questions(state: State) -> dict:
        qs, notes, used = questions.draft(deps.llm, state["ticket"], state["pending"], state.get("precedent", []))
        return {
            "pending": qs,
            "notes": [{"round": state["round"], "lens": "questions", **n} for n in notes],
            "tokens": used,
        }

    def ask(state: State) -> dict:
        qs = state["pending"]
        schema = questions.answer_schema(qs)
        payload = {
            "kind": "questions",
            "round": state["round"],
            "convergence": state["history"][-1]["score"],
            "threshold": state.get("threshold", DEFAULT_THRESHOLD),
            "questions": qs,
        }
        answers = interrupt(payload, response_schema=schema).model_dump()
        settled = dict(state.get("settled", {}))
        answered = []
        for q in qs:
            value = answers[q["id"]]
            option = next(o for o in q["options"] if o["value"] == value)
            settled[q["divergence_id"]] = {
                "dimension": q["dimension"],
                "topic": q["topic"],
                "value": value,
                "items": option.get("items", []),
                "lenses": option["lenses"],
                "question": q["question"],
                "round": state["round"],
            }
            answered.append({**settled[q["divergence_id"]], "id": q["id"]})
        return {"settled": settled, "answered": answered, "pending": []}

    def write_spec(state: State) -> dict:
        return {"spec": build_spec(state)}

    def remember(state: State, runtime: Runtime) -> dict:
        if state.get("mode") != "predict":
            memory.remember(runtime.store, state.get("repo_key", ""), state["ticket"], state.get("answered", []))
        return {}

    def route_after_remember(state: State) -> str:
        if state.get("post") and state["ticket"].get("source") == "github" and state.get("mode") != "predict":
            return "approve_post"
        return END

    def approve_post(state: State) -> dict:
        ticket = state["ticket"]
        answer = interrupt(
            {
                "kind": "approve_post",
                "target": ticket.get("url") or ticket.get("id"),
                "preview": state["spec"][:800],
            },
            response_schema=PostApproval,
        )
        return {"approved_post": bool(answer.approve)}

    def route_after_approval(state: State) -> str:
        return "post_comment" if state.get("approved_post") else END

    def post_comment(state: State) -> dict:
        # second, independent check: never write to the tracker without a recorded approval
        if state.get("approved_post") is not True or deps.tracker is None:
            return {"posted": ""}
        ticket = state["ticket"]
        try:
            url = deps.tracker.comment(int(ticket["number"]), state["spec"], ticket.get("repo"))
        except (TrackerError, KeyError, ValueError) as exc:
            return {
                "posted": "",
                "notes": [{"round": state["round"], "lens": "tracker", "code": "post_failed", "detail": str(exc)}],
            }
        return {"posted": url or "posted"}

    g = StateGraph(State)
    g.add_node("ground", ground, cache_policy=CachePolicy(key_func=ground_cache_key))
    g.add_node("dispatch", dispatch)
    g.add_node("interpret", interpret, input_schema=LensTask)
    g.add_node("diff_plans", diff_plans, defer=True)
    g.add_node("score_convergence", score_convergence)
    g.add_node("draft_questions", draft_questions)
    g.add_node("ask", ask)
    g.add_node("write_spec", write_spec)
    g.add_node("remember", remember)
    g.add_node("approve_post", approve_post)
    g.add_node("post_comment", post_comment)

    g.add_edge(START, "ground")
    g.add_edge("ground", "dispatch")
    g.add_conditional_edges("dispatch", fan_out, ["interpret"])
    g.add_edge("interpret", "diff_plans")
    g.add_edge("diff_plans", "score_convergence")
    g.add_conditional_edges("score_convergence", route_after_score, ["draft_questions", "write_spec"])
    g.add_edge("draft_questions", "ask")
    g.add_edge("ask", "dispatch")
    g.add_edge("write_spec", "remember")
    g.add_conditional_edges("remember", route_after_remember, ["approve_post", END])
    g.add_conditional_edges("approve_post", route_after_approval, ["post_comment", END])
    g.add_edge("post_comment", END)
    return g


def render_mermaid() -> str:
    from rashomon.llm.fake import ScriptedLLM

    return build_graph(Deps(llm=ScriptedLLM())).compile().get_graph().draw_mermaid()
