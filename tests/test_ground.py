import subprocess
from pathlib import Path

from rashomon import ground
from rashomon.ground import build_context, fingerprint, render_context, ticket_terms, tracked_files
from tests.conftest import EXAMPLE, TICKET_FILE


def _pack(monkeypatch=None):
    return build_context(EXAMPLE, TICKET_FILE.read_text())


def test_terms_are_stemmed_content_words():
    terms = ticket_terms(TICKET_FILE.read_text())
    assert terms[:2] == ["export", "invoice"]
    assert "the" not in terms and "csv" in terms


def test_entities_carry_path_and_line():
    pack = _pack()
    where = {(e["kind"], e["name"]): f"{e['path']}:{e['line']}" for e in pack.entities}
    assert where[("route", "GET /invoices")] == "app/routes/invoices.py:5"
    assert where[("table", "invoices")] in {"db/schema.sql:7", "app/models.py:16"}
    assert where[("component", "InvoiceTable")] == "web/src/components/InvoiceTable.tsx:4"
    assert ("column", "invoices.amount_cents") in where


def test_python_search_fallback_without_ripgrep(monkeypatch):
    monkeypatch.setattr(ground.shutil, "which", lambda name: None)
    pack = _pack()
    assert pack.search_backend == "python"
    assert any(h["path"] == "app/routes/invoices.py" and h["line"] == 5 for h in pack.hits)


def test_render_context_lists_evidence_and_files():
    text = render_context(_pack().to_dict())
    assert "- route `GET /invoices` at app/routes/invoices.py:5" in text
    assert "- db/schema.sql" in text


def test_walk_fallback_when_not_a_git_repo(tmp_path: Path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("def f():\n    pass\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("")
    assert tracked_files(tmp_path) == ["pkg/a.py"]
    assert fingerprint(tmp_path).startswith("nogit-")


def test_fingerprint_is_head_sha_when_clean(tmp_path: Path):
    git = [
        "git",
        "-C",
        str(tmp_path),
        "-c",
        "user.email=t@example.com",
        "-c",
        "user.name=t",
        "-c",
        "commit.gpgsign=false",
    ]
    subprocess.run([*git, "init", "-q"], check=True)
    (tmp_path / "a.py").write_text("x = 1\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    head = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    assert fingerprint(tmp_path) == head
    (tmp_path / "a.py").write_text("x = 2\n")
    assert fingerprint(tmp_path).startswith("dirty-")
    assert tracked_files(tmp_path) == ["a.py"]
