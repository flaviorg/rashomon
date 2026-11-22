"""The docs show the real graph: fail if README or architecture.md drifted from the code."""

import re

from rashomon.graph import render_mermaid
from tests.conftest import REPO

BLOCK = re.compile(r"<!-- graph:start -->\n```mermaid\n(.*?)\n```\n<!-- graph:end -->", re.DOTALL)


def test_readme_and_architecture_embed_the_current_graph():
    expected = render_mermaid().strip()
    for name in ("README.md", "docs/architecture.md"):
        match = BLOCK.search((REPO / name).read_text())
        assert match, f"{name} has no generated graph block"
        assert match.group(1) == expected, f"{name} is stale: run python scripts/gen_graph.py"


def test_graph_has_the_loop_and_the_deferred_fan_in():
    mermaid = render_mermaid()
    assert "ask --> dispatch" in mermaid  # the clarify loop
    assert "dispatch -.-> interpret" in mermaid  # Send fan-out
    assert "defer = True" in mermaid  # diff_plans waits for all five lenses
    assert "approve_post -.-> post_comment" in mermaid  # the only path to the tracker
