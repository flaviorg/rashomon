# Contributing

Thanks for taking a look. Issues and pull requests are welcome.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
make check        # ruff, format check, tests, graph drift check
```

Everything runs offline: the tests use the scripted fake model in `src/rashomon/llm/`.

## Ground rules

- **Decisions stay in code.** What diverges (`diff.py`), how much (`score.py`), what to ask
  (`questions.py`), what a plan may claim (`guard.py`) and when to stop (`graph.score_convergence`)
  are pure functions with unit tests. The model writes plans and phrases questions, nothing else.
- **Keep the fake deterministic.** Fake-model rules match prompt text, not call order, so the
  five parallel lens calls and resumed runs stay reproducible.
- **Nothing writes to a tracker without an approval interrupt.** Keep it that way.
- **If you change the graph,** run `python scripts/gen_graph.py` so the README and
  `docs/architecture.md` show the new diagram (CI checks this).
- **If you change terminal output,** run `python scripts/gen_demo_svg.py` to re-record the demo.
- Keep pull requests focused, and add a line to `CHANGELOG.md` under an `Unreleased` heading.
