"""Small plan builders for unit tests."""

from __future__ import annotations


def plan(
    assumptions: dict[str, str] | None = None,
    api: list[str] | None = None,
    schema: list[str] | None = None,
    files: list[str] | None = None,
    behaviours: list[tuple[str, str, str]] | None = None,
    out_of_scope: list[str] | None = None,
    size: str = "S",
) -> dict:
    return {
        "summary": "",
        "assumptions": [{"topic": t, "choice": c} for t, c in (assumptions or {}).items()],
        "api_changes": api or [],
        "schema_changes": schema or [],
        "files": [{"path": p, "change": "modify", "why": ""} for p in files or []],
        "behaviours": [{"given": g, "when": w, "then": t} for g, w, t in behaviours or []],
        "out_of_scope": out_of_scope or [],
        "size": size,
    }


LENS_IDS = ["literal-pm", "minimal-diff", "defensive", "performance", "ux"]


def records(*plans: dict) -> list[dict]:
    return [{"lens": lens, "round": 1, "plan": p} for lens, p in zip(LENS_IDS, plans, strict=False)]
