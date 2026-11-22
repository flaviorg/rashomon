import json
import subprocess
from pathlib import Path

import pytest

from rashomon.ticket import TicketError, from_text, load_ticket, parse_ref, ticket_hash
from rashomon.tracker import GhTracker, TrackerError


def test_parse_ref():
    assert parse_ref("GH-123") == ("github", None, 123)
    assert parse_ref("#7") == ("github", None, 7)
    assert parse_ref("octo/app#42") == ("github", "octo/app", 42)
    assert parse_ref("tickets/x.md") == ("file", None, None)


def test_from_text_uses_heading_as_title():
    t = from_text("# Export CSV\n\nPlease add it.", "x")
    assert t["title"] == "Export CSV" and t["body"] == "Please add it." and t["id"] == "x"


def _runner(calls, stdout="", code=0):
    def run(args, **kw):
        calls.append((args, kw.get("input")))
        return subprocess.CompletedProcess(args, code, stdout=stdout, stderr="boom")

    return run


def test_load_github_issue_via_gh():
    calls = []
    issue = {"number": 5, "title": "T", "body": "B", "url": "https://github.com/o/r/issues/5"}
    t = load_ticket("o/r#5", Path("."), GhTracker(runner=_runner(calls, json.dumps(issue))))
    assert t["source"] == "github" and t["id"] == "o/r#5" and t["number"] == 5
    assert calls[0][0][:4] == ["gh", "issue", "view", "5"] and calls[0][0][-2:] == ["--repo", "o/r"]


def test_gh_failure_is_a_ticket_error():
    with pytest.raises(TicketError):
        load_ticket("GH-1", Path("."), GhTracker(runner=_runner([], code=1)))


def test_comment_sends_body_on_stdin():
    calls = []
    GhTracker(runner=_runner(calls, "url\n")).comment(3, "hello", "o/r")
    args, stdin = calls[0]
    assert args[:4] == ["gh", "issue", "comment", "3"] and stdin == "hello"
    with pytest.raises(TrackerError):
        GhTracker(runner=_runner([], code=1)).comment(3, "x")


def test_ticket_hash_changes_with_body():
    assert ticket_hash({"title": "a", "body": "b"}) != ticket_hash({"title": "a", "body": "c"})
