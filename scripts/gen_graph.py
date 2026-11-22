"""Render the Mermaid diagram from the real compiled graph and paste it into the docs.

python scripts/gen_graph.py          # rewrite docs/graph.mmd, README.md, docs/architecture.md
python scripts/gen_graph.py --check  # exit 1 if any of them drifted from the code
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from rashomon.graph import render_mermaid

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "README.md", ROOT / "docs" / "architecture.md"]
BLOCK = re.compile(r"(<!-- graph:start -->)\n?.*?\n?(<!-- graph:end -->)", re.DOTALL)


def block(mermaid: str) -> str:
    return f"```mermaid\n{mermaid.strip()}\n```"


def main(check: bool) -> int:
    mermaid = render_mermaid()
    drifted: list[str] = []
    mmd = ROOT / "docs" / "graph.mmd"
    if not mmd.exists() or mmd.read_text() != mermaid.strip() + "\n":
        drifted.append(str(mmd.relative_to(ROOT)))
        if not check:
            mmd.write_text(mermaid.strip() + "\n")
    for path in TARGETS:
        text = path.read_text()
        if not BLOCK.search(text):
            print(f"{path.name}: missing <!-- graph:start --> / <!-- graph:end --> markers", file=sys.stderr)
            return 1
        updated = BLOCK.sub(lambda m: m.group(1) + "\n" + block(mermaid) + "\n" + m.group(2), text)
        if updated != text:
            drifted.append(str(path.relative_to(ROOT)))
            if not check:
                path.write_text(updated)
    if check and drifted:
        print("graph diagram out of date in: " + ", ".join(drifted) + " (run scripts/gen_graph.py)", file=sys.stderr)
        return 1
    print("graph diagram " + ("up to date" if not drifted else "updated: " + ", ".join(drifted)))
    return 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))
