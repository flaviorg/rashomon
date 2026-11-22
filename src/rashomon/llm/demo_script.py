"""The scripted model behind ``rashomon demo``: five plausible readings of "Export invoices to CSV".

Each lens has default choices on four open points. A plan is built from those choices plus the
consequences each choice implies (a background job needs a table, a worker and a status
endpoint). Settled decisions found in the prompt replace the defaults, so whatever the human
answers, the next round's plans follow it, exactly as a real model is asked to.
"""

from __future__ import annotations

import re
from typing import Any

from rashomon.llm.fake import Rule, ScriptedLLM
from rashomon.text import jaccard, tokens

DEMO_TITLE = "Export invoices to CSV"

FILTERED = "the filtered view"
ALL_ROWS = "all rows"
FORMATTED = "formatted currency ($1,234.50)"
CENTS = "integer cents"
SYNC = "synchronous download"
ASYNC = "background job, emailed link"
EXPORT_CSV = "GET /invoices/export.csv"
FORMAT_PARAM = "GET /invoices?format=csv"
JOB_API = ["POST /invoices/exports", "GET /invoices/exports/{job_id}"]
JOB_TABLE = "add table export_jobs (id, status, file_path, requested_by, created_at)"

DOWNLOAD = {
    "given": "invoices exist",
    "when": "the user clicks Export on the invoices page",
    "then": "a CSV file downloads with a header row and one row per invoice",
}

LENSES: dict[str, dict[str, Any]] = {
    "literal-pm": {
        "summary": "Add an Export button to the invoices page that downloads what the page shows as CSV.",
        "size": "S",
        "topics": {"export scope": FILTERED, "amount format": FORMATTED, "delivery method": SYNC},
        "api": [EXPORT_CSV],
        "files": [("app/export/csv.py", "new", "CSV writer for invoice rows")],
        "out_of_scope": ["PDF export", "scheduled exports"],
        "behaviours": [
            {
                "given": "an export on 2026-11-21",
                "when": "the file downloads",
                "then": "it is named invoices-2026-11-21.csv",
            }
        ],
    },
    "minimal-diff": {
        "summary": "Reuse GET /invoices with format=csv; same filters, no new route, no new table.",
        "size": "XS",
        "topics": {"export scope": FILTERED, "amount format": CENTS, "delivery method": SYNC},
        "api": [FORMAT_PARAM],
        "files": [],
        "out_of_scope": ["PDF export", "UI redesign"],
        "behaviours": [],
    },
    "defensive": {
        "summary": (
            "A dedicated export route that writes every invoice, escapes spreadsheet formulas "
            "and handles empty results."
        ),
        "size": "M",
        "topics": {"export scope": ALL_ROWS, "amount format": CENTS, "delivery method": SYNC},
        "api": [EXPORT_CSV],
        "files": [
            ("app/export/csv.py", "new", "CSV writer for invoice rows"),
            ("app/utils/csv_helpers.py", "modify", "escape cells that start with = + - @"),
        ],
        "out_of_scope": ["PDF export"],
        "behaviours": [
            {
                "given": "no invoices exist",
                "when": "the user exports",
                "then": "the CSV contains only the header row",
            },
            {
                "given": "a customer name starts with =",
                "when": "the user exports",
                "then": "the cell is prefixed with a single quote so Excel does not run it as a formula",
            },
        ],
    },
    "performance": {
        "summary": "Exports run as a background job that streams rows to a file and emails a link.",
        "size": "L",
        "topics": {"scope of the export": ALL_ROWS, "amount format": CENTS, "delivery method": ASYNC},
        "api": [EXPORT_CSV],
        "files": [],
        "out_of_scope": ["PDF export", "real-time progress"],
        "behaviours": [
            {
                "given": "100,000 invoices",
                "when": "the export runs",
                "then": "rows are streamed in batches of 1,000 and memory stays flat",
            }
        ],
    },
    "ux": {
        "summary": "An Export button next to the filters with a clear busy state; amounts look like they do on screen.",
        "size": "S",
        "topics": {"export scope": ALL_ROWS, "amount format": FORMATTED, "delivery method": SYNC},
        "api": [EXPORT_CSV],
        "files": [
            ("app/export/csv.py", "new", "CSV writer for invoice rows"),
            ("web/src/components/ExportButton.tsx", "new", "button with a busy state"),
        ],
        "out_of_scope": ["PDF export", "Excel .xlsx format"],
        "behaviours": [
            {
                "given": "an export is in progress",
                "when": "the user looks at the Export button",
                "then": "it is disabled and shows a spinner",
            }
        ],
    },
}

_SETTLED = re.compile(r"^- (?P<topic>.+?) = (?P<value>.+)$", re.MULTILINE)
_LENS = re.compile(r"^Lens: (?P<id>[\w-]+)", re.MULTILINE)
_DIVERGENCE = re.compile(r"^- id: (?P<id>\S+) \| topic: (?P<topic>.+?) \| allowed: (?P<allowed>.+)$", re.MULTILINE)


def settled_from_prompt(prompt: str) -> dict[str, str]:
    if "Settled decisions (binding):" not in prompt:
        return {}
    block = prompt.split("Settled decisions (binding):", 1)[1].split("\n\n", 1)[0]
    return {m.group("topic"): m.group("value") for m in _SETTLED.finditer(block)}


def _settled_choice(topic: str, settled: dict[str, str]) -> str | None:
    for t, v in settled.items():
        if jaccard(tokens(t), tokens(topic)) >= 0.5:
            return v
    return None


def build_plan(lens_id: str, settled: dict[str, str]) -> dict[str, Any]:
    spec = LENSES[lens_id]
    choices = {topic: _settled_choice(topic, settled) or default for topic, default in spec["topics"].items()}
    scope = next(v for t, v in choices.items() if "scope" in t)
    amount = choices["amount format"]
    delivery = choices["delivery method"]

    files = [
        ("app/routes/invoices.py", "modify", "export route"),
        ("web/src/components/InvoiceTable.tsx", "modify", "Export button"),
    ]
    files += spec["files"]
    api = list(spec["api"])
    schema: list[str] = []
    behaviours = [dict(b) for b in spec["behaviours"]]

    if scope == FILTERED:
        files.append(("app/services/invoice_query.py", "modify", "reuse filter_invoices without pagination"))
        behaviours.append(
            {
                "given": "the list is filtered to status paid",
                "when": "the user exports",
                "then": "the CSV contains only the paid invoices that match the filters",
            }
        )
    else:
        behaviours.append(
            {
                "given": "filters are set on the page",
                "when": "the user exports",
                "then": "the CSV contains every invoice, ignoring the filters",
            }
        )
    if amount == FORMATTED:
        behaviours.append(
            {
                "given": "an invoice of 123450 cents",
                "when": "it is exported",
                "then": "the amount column reads $1,234.50",
            }
        )
    else:
        behaviours.append(
            {
                "given": "an invoice of 123450 cents",
                "when": "it is exported",
                "then": "the amount_cents column reads 123450",
            }
        )
    if delivery == ASYNC:
        api = list(JOB_API)
        schema = [JOB_TABLE]
        files += [
            ("app/jobs/export_invoices.py", "new", "background export job"),
            ("db/schema.sql", "modify", "export_jobs table"),
        ]
        behaviours.append(
            {
                "given": "invoices exist",
                "when": "the user clicks Export on the invoices page",
                "then": "an export job is queued and the user is emailed a download link when it finishes",
            }
        )
    else:
        behaviours.append(dict(DOWNLOAD))

    api_settled = _settled_choice("API changes", settled)
    if api_settled:
        api = [x.strip() for x in api_settled.split(";")]
    schema_settled = _settled_choice("schema changes", settled)
    if schema_settled:
        schema = [] if schema_settled == "none" else [x.strip() for x in schema_settled.split(";")]

    return {
        "summary": spec["summary"],
        "size": "M"
        if (lens_id == "performance" and delivery == SYNC)
        else ("L" if delivery == ASYNC else spec["size"]),
        "files": [{"path": p, "change": c, "why": w} for p, c, w in files],
        "api_changes": api,
        "schema_changes": schema,
        "behaviours": behaviours,
        "out_of_scope": spec["out_of_scope"],
        "assumptions": [{"topic": t, "choice": v} for t, v in choices.items()],
    }


def _plan(prompt: str) -> dict[str, Any]:
    m = _LENS.search(prompt)
    lens_id = m.group("id") if m else "literal-pm"
    return build_plan(lens_id, settled_from_prompt(prompt))


PHRASING = {
    "scope": "When finance clicks Export, which invoices should end up in the file?",
    "amount": "How should amounts appear in the CSV?",
    "api": "Which endpoint should serve the export?",
    "delivery": "Should the export download right away, or run as a background job?",
    "schema": "Does this ticket need a database change?",
}


def _questions(prompt: str) -> dict[str, Any]:
    out = []
    for m in _DIVERGENCE.finditer(prompt):
        topic = m.group("topic").lower()
        allowed = [a.strip() for a in m.group("allowed").split(" | ")]
        key = next((k for k in PHRASING if k in topic), None)
        options = list(allowed)
        if key == "amount":
            # the scripted model "helpfully" invents an option no plan proposed; the validator drops it
            options.append("Let the user choose per export")
        out.append({"divergence_id": m.group("id"), "question": PHRASING.get(key or "", ""), "options": options})
    return {"questions": out}


# What `rashomon demo` answers when it runs unattended (pick by topic keyword).
DEMO_ANSWERS = {"scope": FILTERED, "amount": FORMATTED, "api": EXPORT_CSV, "delivery": SYNC, "schema": "none"}


def demo_answer(question: dict) -> str:
    topic = question["topic"].lower()
    values = [o["value"] for o in question["options"]]
    for key, value in DEMO_ANSWERS.items():
        if key in topic and value in values:
            return value
    return question["recommended"]


def demo_llm() -> ScriptedLLM:
    return ScriptedLLM(
        rules=[
            Rule("plan", _plan, when=(DEMO_TITLE,)),
            Rule("questions", _questions, when=(DEMO_TITLE,)),
        ]
    )
