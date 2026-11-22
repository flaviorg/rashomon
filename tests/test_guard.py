from rashomon.guard import enforce_settled, guard_plan, normalize_path
from tests.helpers import plan

TRACKED = {"app/routes/invoices.py", "db/schema.sql"}


def _codes(notes):
    return [n["code"] for n in notes]


def test_normalize_path_rejects_escapes():
    assert normalize_path("./app/x.py") == "app/x.py"
    assert normalize_path("a/app/x.py") == "app/x.py"
    assert normalize_path("../etc/passwd") is None
    assert normalize_path("/etc/passwd") is None
    assert normalize_path("C:/win") is None


def test_untracked_modify_is_marked_new_and_escape_dropped():
    p = plan()
    p["files"] = [
        {"path": "app/routes/invoices.py", "change": "modify"},
        {"path": "app/utils/csv_helpers.py", "change": "modify"},
        {"path": "db/schema.sql", "change": "new"},
        {"path": "../secrets.py", "change": "modify"},
        {"path": "app/routes/invoices.py", "change": "modify"},
    ]
    out, notes = guard_plan(p, TRACKED, {})
    assert [(f["path"], f["change"]) for f in out["files"]] == [
        ("app/routes/invoices.py", "modify"),
        ("app/utils/csv_helpers.py", "new"),
        ("db/schema.sql", "modify"),
    ]
    assert _codes(notes) == ["untracked", "exists", "path_escape"]


def test_settled_assumption_overrides_contradiction():
    p = plan({"scope of the export": "all rows"})
    settled = {
        "assumption:export-scope": {"dimension": "assumption", "topic": "export scope", "value": "the filtered view"}
    }
    notes = enforce_settled(p, settled)
    assert p["assumptions"] == [{"topic": "export scope", "choice": "the filtered view"}]
    assert _codes(notes) == ["overrode"]


def test_settled_assumption_added_when_missing_and_agreement_is_silent():
    settled = {"x": {"dimension": "assumption", "topic": "export scope", "value": "all rows"}}
    p = plan()
    assert enforce_settled(p, settled) == []
    assert p["assumptions"] == [{"topic": "export scope", "choice": "all rows"}]
    p2 = plan({"export scope": "All rows"})
    assert enforce_settled(p2, settled) == []


def test_settled_api_and_schema_sets_are_enforced():
    p = plan(api=["POST /invoices/exports"], schema=["add table export_jobs"])
    settled = {
        "api:changes": {"dimension": "api", "topic": "API changes", "value": "GET /x", "items": ["GET /x"]},
        "schema:changes": {"dimension": "schema", "topic": "schema changes", "value": "none", "items": []},
    }
    notes = enforce_settled(p, settled)
    assert p["api_changes"] == ["GET /x"] and p["schema_changes"] == []
    assert _codes(notes) == ["overrode", "overrode"]


def test_long_text_and_long_lists_are_capped():
    p = plan(api=["x" * 1000] * 50)
    out, _ = guard_plan(p, set(), {})
    assert len(out["api_changes"]) == 30 and len(out["api_changes"][0]) == 300
