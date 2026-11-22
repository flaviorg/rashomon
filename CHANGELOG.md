# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.1] - 2026-11-22

### Fixed

- Generated test stubs no longer end with a blank line inside the code block, so `ruff format`
  (which also formats Python blocks in Markdown) leaves the spec and `docs/sample-spec.md` alone.
  This made CI fail on v0.1.0.

## [0.1.0] - 2026-11-21

### Added

- LangGraph graph: `ground → dispatch → Send(interpret) ×5 → diff_plans (defer) →
  score_convergence → draft_questions → ask (interrupt) → dispatch …`, ending in
  `write_spec → remember → approve_post? → post_comment?`.
- Repo grounding with `file:line` evidence: `git ls-files`, Python `ast` (functions, classes,
  routes, `__tablename__`), SQL tables and columns, JS/TS components and `fetch` routes, ripgrep
  or a Python fallback for text hits. Cached with `CachePolicy` on HEAD sha + ticket hash
  (`SqliteCache`).
- Five lenses (literal PM, minimal diff, defensive, performance, UX) producing typed plans:
  files, API and schema changes, Given/When/Then behaviours, out of scope, size, assumptions.
- Plan guard: paths checked against `git ls-files` (untracked → `new`, escapes dropped),
  settled decisions enforced, size caps.
- Divergence matrix in pure code (token-Jaccard clustering of topics, choices and items),
  impact scoring, and weighted-Jaccard convergence across seven dimensions.
- Multiple-choice questions for the top three divergences: options validated against plan
  values, answers validated with `interrupt(..., response_schema=...)`, loop until convergence
  ≥ threshold or three rounds.
- Markdown spec with settled assumptions, acceptance criteria, edge cases, changes and pytest
  stubs; `--speckit` writes spec-kit compatible Clarifications.
- `SqliteSaver` checkpoints (`answer` / `resume` days later), `SqliteStore` decisions reused as
  precedent, `--post` to a GitHub issue behind an approval interrupt.
- `rashomon backtest` over closed issues (JSONL or `--gh`), with change recall and question
  precision.
- Scripted offline model, `examples/invoice_app` sample repo and ticket, `rashomon demo`,
  generated Mermaid diagram and demo SVG, CI on Python 3.11 to 3.13.

[0.1.1]: https://github.com/flaviorg/rashomon/releases/tag/v0.1.1
[0.1.0]: https://github.com/flaviorg/rashomon/releases/tag/v0.1.0
