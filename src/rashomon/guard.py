"""Code-side checks on every plan the model returns. The model proposes; this decides what stands.

* File paths are checked against ``git ls-files``: an untracked path the plan wants to modify is
  relabelled ``new`` (and noted), a path that escapes the repo is dropped.
* Settled decisions are enforced: a plan that contradicts an answer the human already gave is
  corrected, and the correction is recorded, so a lens cannot reopen a closed question.
* Lists and strings are capped so one verbose plan cannot dominate the diff.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from rashomon.text import jaccard, tokens

MAX_FILES = 40
MAX_ITEMS = 30
MAX_TEXT = 300
TOPIC_MATCH = 0.5
VALUE_MATCH = 0.6


def _note(code: str, detail: str) -> dict:
    return {"code": code, "detail": detail}


def normalize_path(raw: str) -> str | None:
    """Repo-relative posix path, or None when it points outside the repo."""
    p = (raw or "").strip().strip("`").replace("\\", "/")
    for prefix in ("./", "a/", "b/"):
        if p.startswith(prefix):
            p = p[len(prefix) :]
    if not p or p.startswith("/") or (len(p) > 1 and p[1] == ":"):
        return None
    parts = PurePosixPath(p).parts
    if ".." in parts:
        return None
    return str(PurePosixPath(*parts))


def _clip(text: str) -> str:
    text = (text or "").strip()
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def check_paths(plan: dict, tracked: set[str]) -> list[dict]:
    notes: list[dict] = []
    seen: set[str] = set()
    kept: list[dict] = []
    for f in plan.get("files", [])[: MAX_FILES * 2]:
        path = normalize_path(f.get("path", ""))
        if path is None:
            notes.append(_note("path_escape", f"dropped {f.get('path')!r}: outside the repo"))
            continue
        if path in seen:
            continue
        seen.add(path)
        change = f.get("change", "modify")
        if change in ("modify", "delete") and path not in tracked:
            notes.append(_note("untracked", f"{path} is not in git ls-files: marked new"))
            change = "new"
        elif change == "new" and path in tracked:
            notes.append(_note("exists", f"{path} already exists: marked modify"))
            change = "modify"
        kept.append({"path": path, "change": change, "why": _clip(f.get("why", ""))})
    if len(kept) > MAX_FILES:
        notes.append(_note("too_many_files", f"kept the first {MAX_FILES} of {len(kept)} files"))
        kept = kept[:MAX_FILES]
    plan["files"] = kept
    return notes


def enforce_settled(plan: dict, settled: dict[str, dict]) -> list[dict]:
    notes: list[dict] = []
    for decision in settled.values():
        dim = decision["dimension"]
        if dim == "assumption":
            topic_tok = tokens(decision["topic"])
            value_tok = tokens(decision["value"])
            hits = [a for a in plan["assumptions"] if jaccard(tokens(a["topic"]), topic_tok) >= TOPIC_MATCH]
            if not hits:
                plan["assumptions"].append({"topic": decision["topic"], "choice": decision["value"]})
                continue
            for a in hits:
                if jaccard(tokens(a["choice"]), value_tok) < VALUE_MATCH:
                    notes.append(
                        _note("overrode", f"{a['topic']}: {a['choice']!r} contradicts settled {decision['value']!r}")
                    )
                # canonical wording, so the diff sees one topic and one value
                a["topic"], a["choice"] = decision["topic"], decision["value"]
        elif dim in ("api", "schema"):
            key = "api_changes" if dim == "api" else "schema_changes"
            want = list(decision.get("items", []))
            have = plan.get(key, [])
            if sorted(tokens(x) for x in have) != sorted(tokens(x) for x in want):
                notes.append(_note("overrode", f"{key}: replaced with the settled answer"))
            plan[key] = want
    return notes


def guard_plan(plan: dict, tracked: set[str], settled: dict[str, dict]) -> tuple[dict, list[dict]]:
    """Return a corrected copy of ``plan`` and the notes describing every correction."""
    plan = {
        "summary": _clip(plan.get("summary", "")),
        "files": [dict(f) for f in plan.get("files", [])],
        "api_changes": [_clip(x) for x in plan.get("api_changes", [])][:MAX_ITEMS],
        "schema_changes": [_clip(x) for x in plan.get("schema_changes", [])][:MAX_ITEMS],
        "behaviours": [{k: _clip(b.get(k, "")) for k in ("given", "when", "then")} for b in plan.get("behaviours", [])][
            :MAX_ITEMS
        ],
        "out_of_scope": [_clip(x) for x in plan.get("out_of_scope", [])][:MAX_ITEMS],
        "assumptions": [
            {"topic": _clip(a.get("topic", "")), "choice": _clip(a.get("choice", ""))}
            for a in plan.get("assumptions", [])
            if a.get("topic") and a.get("choice")
        ][:MAX_ITEMS],
        "size": plan.get("size", "M"),
    }
    notes = check_paths(plan, tracked)
    notes += enforce_settled(plan, settled)
    return plan, notes
