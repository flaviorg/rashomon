---
description: Clarify the current feature spec by running five independent readings and asking only where they disagree (rashomon).
---

Use rashomon instead of the built-in clarify step for the feature spec at `$ARGUMENTS`
(or the current feature's `spec.md` if no argument is given).

1. Run, without prompting:

   ```bash
   rashomon run "$SPEC" --repo . --speckit "$SPEC" --no-input --json
   ```

2. If the exit code is 3, the JSON has `pending.questions`. Show each question with its
   numbered options and the recommended one, and ask the user to choose. Do not add options.

3. Continue with the answers (repeat while the exit code is 3):

   ```bash
   rashomon answer <thread> q1=<n> q2=<n> ... --json
   ```

4. When it exits 0 or 1, the spec's `## Clarifications` section has a new dated session.
   Report the settled decisions and anything listed under "Still open" in the rashomon spec
   (`spec_path` in the JSON), then suggest the next step (`/speckit.plan`).
