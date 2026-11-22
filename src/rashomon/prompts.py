"""Prompt text. Kept in one place so the scripted fake model and the real one see the same thing."""

from __future__ import annotations

from rashomon.lenses import Lens

INTERPRET_SYSTEM = """You are one of five engineers reading the same ticket independently, each through a
different lens. You will not see the others' plans. Do not hedge between options: commit to one concrete plan.

Rules:
- Ground every file in the context pack. Use paths from the tracked file list; anything else must be change="new".
- Record every judgement call on a point the ticket leaves open as an assumption {topic, choice}.
  Topics are short noun phrases (2 to 4 words, e.g. "export scope", "amount format"). Choices are short values.
- Behaviours are observable, written as Given / When / Then.
- Settled decisions are binding. Follow them exactly and do not re-litigate them.
- Size is XS, S, M, L or XL for one engineer."""

QUESTIONS_SYSTEM = """You turn disagreements between five plans into questions for a product owner.
For each divergence, write one plain question. Options must be copied from the allowed values given for that
divergence. Do not invent options, merge them, or add "other". Keep the divergence id exactly as given."""


def interpret_prompt(
    lens: Lens,
    ticket: dict,
    context: str,
    settled: dict[str, dict],
    precedent: list[dict],
    round_no: int,
) -> str:
    parts = [
        f"Lens: {lens.id} ({lens.name})",
        f"Focus: {lens.focus}",
        f"Round: {round_no}",
        "",
        f"Ticket {ticket.get('id', '')}: {ticket.get('title', '')}",
        ticket.get("body", "").strip(),
        "",
        "Context pack:",
        context,
    ]
    if settled:
        parts += ["", "Settled decisions (binding):"]
        parts += [f"- {d['topic']} = {d['value']}" for d in settled.values()]
    if precedent:
        parts += ["", "Decisions made on earlier tickets in this repo (precedent, not binding):"]
        parts += [f"- {p['topic']} = {p['value']} (on {p.get('ticket', '?')})" for p in precedent]
    return "\n".join(parts)


def questions_prompt(ticket: dict, divergences: list[dict]) -> str:
    lines = [f"Ticket {ticket.get('id', '')}: {ticket.get('title', '')}", "", "Divergences:"]
    for d in divergences:
        allowed = " | ".join(g["value"] for g in d["groups"])
        lines.append(f"- id: {d['id']} | topic: {d['topic']} | allowed: {allowed}")
    return "\n".join(lines)
