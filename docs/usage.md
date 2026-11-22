# Usage

## Running on a ticket

```bash
rashomon run GH-123                      # issue in the repo's own GitHub remote (via gh)
rashomon run octo/app#123 --repo ../app  # issue in another repository
rashomon run ticket.md --repo ../app     # a text or Markdown file (first # heading is the title)
```

In a terminal, rashomon asks the questions as they come. The recommended option is the
precedent from an earlier ticket if there is one, otherwise the majority; press Enter to take it.

Without a terminal (`--no-input`, `--json`, CI), it pauses and exits with code 3:

```text
paused waiting for answers. Answer any time, the run is checkpointed:
  rashomon answer export-20261121-101500 q1=1 q2=2 ...   or   rashomon resume export-20261121-101500
```

Answers are option numbers (`q1=2`) or exact option text (`q1="the filtered view"`). Every
question must be answered. The run can wait for days: everything is in `.rashomon/`.

## Output

- `.rashomon/runs/<thread>/spec.md` (and `--out PATH`): the spec.
- `--speckit specs/<feature>/spec.md`: answers appended as a spec-kit Clarifications session.
- `--post`: on a GitHub ticket, after the spec is written, rashomon asks whether to post it as an
  issue comment. Nothing is posted without a yes (`approve=yes` with `rashomon answer`).
- `--json`: a summary on stdout (thread, outcome, convergence per round, settled decisions,
  pending questions, spec path, guard notes); progress goes to stderr.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Converged; spec written. |
| 1 | Finished without converging (round limit or nothing askable); spec written with "Still open". |
| 2 | Error (ticket not found, model error, bad answer). |
| 3 | Paused, waiting for answers. |

## Using a real model

| Model id | Needs |
| --- | --- |
| `anthropic:claude-sonnet-5-5` (default with a key) | `ANTHROPIC_API_KEY` |
| `openai:<id>` | `OPENAI_API_KEY`, optional `OPENAI_BASE_URL` for compatible endpoints |
| `openrouter:<vendor>/<model>` | `OPENROUTER_API_KEY` |
| any other `provider:model` | the matching `langchain-<provider>` package |

The lenses run at temperature 0.7 so that five calls with different stances do not collapse
into one answer; question phrasing uses the same model. A full run is 5 plan calls per round
plus one phrasing call per asking round: at most 18 calls with the defaults.

## State directory

`--state-dir` (default `.rashomon`) holds `checkpoints.sqlite`, `store.sqlite`,
`cache.sqlite` and `runs/`. Add it to `.gitignore`. Delete `cache.sqlite` to force re-grounding,
or `store.sqlite` to forget past decisions. `rashomon decisions --repo .` lists them.

## Backtest dataset format

One JSON object per line:

```json
{"id": "#41", "title": "Export invoices", "body": "original ticket text", "changes": ["later change 1", "later change 2"]}
```

Use the body as it was *when the issue was opened*; later edits leak the answer.

The divergence matrix needs a terminal about 110 columns wide; narrower terminals truncate the cells (the spec always has the full values).
