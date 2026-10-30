# Live-run dispatch blockers — verbatim platform responses

The live build leg first attempted the production dispatch path
(`ObviousBackend` → `obvious tasks create --assignee=coder --start=true`).
Every route was rejected by the platform for this execution context. All
attempts created no task (validation rejected before creation), and each
failed cleanly through the production loop as `builder_error` with exit 1 —
the unavailable-backend state surfaced, never swallowed.

| # | Attempt (UTC 2026-10-30) | Response |
|---|---|---|
| 1 | `tasks create --assignee=coder --start=true` (no parent), 22:08:5x | `✗ VALIDATION_FAILED (422)` — `coder does not delegate — "coder" is not on its roster. Do the work yourself, or hand off independently (usr_* / agent_* / autobuild without parentId).` |
| 2 | `tasks create --assignee=obvious` (no start, no parent), 22:09:50 | `✗ FORBIDDEN (403)` — `Delegated agents cannot create independent tasks. Do the work yourself, track it with a subtask under your own task (parentId), or surface the need to your orchestrator via obvious tasks report --status=needs_input.` |
| 3 | `tasks create --assignee=coder --start=true` → `--parentId=todo_E5nBvsKh`, 22:10:32 | `✗ VALIDATION_FAILED (422)` — `Parent task "todo_E5nBvsKh" is not your root task — delegated subtasks must be direct children of your root (depth 1). Omit --parentId to plan under your root.` |
| 4 | `tasks create --assignee=agent` (no start, no parent), 22:11:0x | `✗ VALIDATION_FAILED (422)` — `coder does not delegate — "agent" is not on its roster. Do the work yourself, or hand off independently (usr_* / agent_* / autobuild without parentId).` |

The guidance is circular for this context: attempt 3 points back to the
omitted-parent form (attempt 1), which is off-roster. Conclusion: **worker
dispatch does not exist from a delegated coder context**; the platform's
repeated instruction is "do the work yourself". The live build was therefore
performed by the agent directly (a real implementation and test suite, not a
scripted fixture), and the production iteration loop evaluated it
independently.

## Implication for the repo (finding, not fixed here)

`ObviousBackend` (the default backend, `src/alexander/builder/obvious.py`)
assumes its ambient credentials can delegate to a `coder` worker. Under a
delegated-agent context it always fails fast with `builder_error` — correct,
clean behavior, but the backend cannot be used from inside an Obvious worker.
Options for a future PR: document the credential-context requirement in the
backends table, or fall back to direct-agent execution when dispatch is
rejected.
