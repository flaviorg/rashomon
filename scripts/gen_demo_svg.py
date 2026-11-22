"""Record a real offline demo run and save it as docs/media/demo.svg.

Nothing is staged: this calls the same ``start_run`` the CLI uses, on examples/invoice_app with
the scripted fake model, inside a temporary directory (so no machine paths end up in the
output), and saves what the terminal showed. It also writes the plain-text transcript
(docs/media/demo.txt), an excerpt SVG (docs/media/demo-short.svg) and the spec the run produced
(docs/sample-spec.md).
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

from rich.console import Console
from rich.text import Text

from rashomon.cli import find_example, start_run
from rashomon.graph import DEFAULT_MAX_ROUNDS
from rashomon.score import DEFAULT_THRESHOLD
from rashomon.ticket import load_ticket

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "docs" / "media"
WIDTH = 110
THREAD = "export-invoices-demo"


def excerpt(ansi: str) -> str:
    """Round 1's matrix and questions, then the final convergence and spec lines (gaps are marked)."""
    lines = ansi.split("\n")
    plain = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in lines]
    start = next(i for i, line in enumerate(plain) if line.startswith("divergence matrix"))
    stop = next(i for i, line in enumerate(plain) if "q3 →" in line)
    tail = max(i for i, line in enumerate(plain) if line.strip().startswith("convergence "))
    end = next(i for i, line in enumerate(plain) if line.startswith("● spec"))
    gap = "\x1b[2m  ⋮\x1b[0m"
    return "\n".join([*lines[start : stop + 1], gap, *lines[tail : end + 1]])


def main() -> int:
    console = Console(record=True, width=WIDTH, force_terminal=True, color_system="truecolor", highlight=False)
    repo = find_example("invoice_app")
    ticket = load_ticket(str(find_example("tickets/export-invoices.md")), repo)
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            code = start_run(
                ticket, repo, "fake", Path(".rashomon"), THREAD, DEFAULT_THRESHOLD, DEFAULT_MAX_ROUNDS, False,
                console, "demo",
            )  # fmt: skip
            spec = (Path(".rashomon") / "runs" / THREAD / "spec.md").read_text()
        finally:
            os.chdir(cwd)
    MEDIA.mkdir(parents=True, exist_ok=True)
    text = console.export_text(clear=False)
    ansi = console.export_text(clear=False, styles=True)
    for leak in (str(ROOT), str(Path.home())):
        if leak in text or leak in spec:
            print(f"refusing to save: output contains a local path ({leak})", file=sys.stderr)
            return 1
    console.save_svg(str(MEDIA / "demo.svg"), title="rashomon demo (offline, scripted fake model)")
    (MEDIA / "demo.txt").write_text(text)
    (ROOT / "docs" / "sample-spec.md").write_text(spec)
    short = Console(record=True, width=WIDTH, force_terminal=True, color_system="truecolor", highlight=False)
    short.print(Text.from_ansi(excerpt(ansi)))
    short.save_svg(str(MEDIA / "demo-short.svg"), title="rashomon demo (excerpt)")
    print(f"saved docs/media/demo.svg (exit {code})", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
