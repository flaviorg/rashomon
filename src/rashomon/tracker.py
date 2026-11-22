"""The only code that talks to the issue tracker. Reads freely; writes only when the graph says so.

Writes (``comment``) are reachable from exactly one node, ``post_comment``, which runs after
an approval interrupt and refuses to post if the approval is missing.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any


class TrackerError(RuntimeError):
    pass


Runner = Callable[..., Any]


class GhTracker:
    def __init__(self, cwd: Path | None = None, runner: Runner = subprocess.run) -> None:
        self.cwd = cwd
        self._run = runner

    def _gh(self, args: list[str], stdin: str | None = None) -> str:
        try:
            proc = self._run(
                ["gh", *args], cwd=self.cwd, input=stdin, capture_output=True, text=True, timeout=60, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TrackerError(f"gh failed: {exc}") from exc
        if proc.returncode != 0:
            raise TrackerError(f"gh {' '.join(args[:2])} failed: {(proc.stderr or '').strip()[:300]}")
        return proc.stdout

    @staticmethod
    def _repo_args(repo: str | None) -> list[str]:
        return ["--repo", repo] if repo else []

    def fetch_issue(self, number: int, repo: str | None = None) -> dict:
        out = self._gh(["issue", "view", str(number), "--json", "number,title,body,url", *self._repo_args(repo)])
        return json.loads(out)

    def list_closed(self, repo: str | None, limit: int) -> list[dict]:
        out = self._gh(
            [
                "issue", "list", "--state", "closed", "--limit", str(limit),
                "--json", "number,title,body,comments,url", *self._repo_args(repo),
            ]
        )  # fmt: skip
        return json.loads(out)

    def comment(self, number: int, body: str, repo: str | None = None) -> str:
        out = self._gh(["issue", "comment", str(number), "--body-file", "-", *self._repo_args(repo)], stdin=body)
        return out.strip()
