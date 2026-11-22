"""The five readings. Each lens is a stance, not a persona costume: it changes what the plan optimizes for."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Lens:
    id: str
    letter: str
    name: str
    focus: str


LENSES: tuple[Lens, ...] = (
    Lens(
        "literal-pm",
        "A",
        "Literal PM",
        "Read the ticket exactly as written. Build what it says, no more. Where it is silent, pick what the "
        "requester most plausibly meant from the words they used.",
    ),
    Lens(
        "minimal-diff",
        "B",
        "Minimal diff",
        "Smallest change that satisfies the ticket. Reuse existing routes, services and components. No new "
        "tables, no new dependencies unless unavoidable.",
    ),
    Lens(
        "defensive",
        "C",
        "Defensive",
        "Assume the unhappy paths happen: empty results, huge inputs, bad data, permissions, concurrent "
        "edits, escaping. Make behaviour explicit for each.",
    ),
    Lens(
        "performance",
        "D",
        "Performance",
        "Assume production scale. Think about query cost, memory, streaming, timeouts and background work. "
        "Prefer designs that stay fast at 100x today's data.",
    ),
    Lens(
        "ux",
        "E",
        "UX",
        "Think about the person using it: where the control lives, what they see while waiting, what the "
        "output looks like when they open it, and what would surprise them.",
    ),
)

BY_ID = {lens.id: lens for lens in LENSES}
BY_LETTER = {lens.letter: lens for lens in LENSES}


def letters(lens_ids: list[str]) -> str:
    return ",".join(BY_ID[i].letter for i in lens_ids if i in BY_ID)
