"""Load a ticket from GitHub (via ``gh``) or from a text/Markdown file."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from rashomon.tracker import GhTracker, TrackerError

GH_REF = re.compile(r"^(?:(?P<repo>[\w.-]+/[\w.-]+)#|GH-|gh-|#)(?P<num>\d+)$")


class TicketError(RuntimeError):
    pass


def parse_ref(ref: str) -> tuple[str, str | None, int | None]:
    """``GH-123`` / ``#123`` / ``owner/repo#123`` -> ("github", repo, n); anything else is a file path."""
    m = GH_REF.match(ref.strip())
    if m:
        return "github", m.group("repo"), int(m.group("num"))
    return "file", None, None


def from_text(text: str, ticket_id: str) -> dict:
    lines = text.strip().splitlines()
    title = ticket_id
    if lines and lines[0].lstrip().startswith("#"):
        title = lines[0].lstrip("# ").strip()
        lines = lines[1:]
    elif lines:
        title = lines[0].strip()[:80]
    return {"id": ticket_id, "title": title, "body": "\n".join(lines).strip(), "source": "file", "url": ""}


def load_ticket(ref: str, cwd: Path, tracker: GhTracker | None = None, gh_repo: str | None = None) -> dict:
    kind, repo, number = parse_ref(ref)
    if kind == "github":
        tracker = tracker or GhTracker(cwd=cwd)
        try:
            issue = tracker.fetch_issue(number, repo or gh_repo)
        except TrackerError as exc:
            raise TicketError(str(exc)) from exc
        return {
            "id": f"{repo + '#' if repo else 'GH-'}{issue['number']}",
            "title": issue.get("title", ""),
            "body": issue.get("body") or "",
            "source": "github",
            "url": issue.get("url", ""),
            "number": issue["number"],
            "repo": repo or gh_repo,
        }
    path = Path(ref)
    if not path.is_file():
        raise TicketError(f"{ref!r} is neither a GitHub reference (GH-123, owner/repo#123) nor a readable file")
    return from_text(path.read_text(errors="replace"), path.stem)


def ticket_hash(ticket: dict) -> str:
    return hashlib.sha256(f"{ticket.get('title', '')}\n{ticket.get('body', '')}".encode()).hexdigest()[:16]
