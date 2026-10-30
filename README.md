# Alexander the Cracked

An agent that searches for hackathons and competitions, ranks them against your
interests, then builds project codebases for them.

## Architecture

```
            ┌──────────────────────────────────────────────────────────┐
            │                     alexander run                        │
            └──────────────────────────────────────────────────────────┘

  ┌───────────┐    events    ┌──────────┐   ranked    ┌────────────────┐
  │ discovery │ ───────────► │ ranking  │ ──────────► │    builder     │
  └───────────┘              └──────────┘  top pick   └────────────────┘
   Devpost API                YAML profile                │
   Hack Club API              weighted scoring            │ ObviousBackend (default)
   dedupe + 1h cache          deterministic order         │ or Claude Agent SDK
                                                          ▼
                                                 builds/<event-slug>/
                                                 SPEC.md + code + tests
                                                      + README pitch
```

- **Discovery** fetches the Devpost and Hack Club hackathon feeds, normalizes
  both into one `HackathonEvent` model, deduplicates cross-source listings,
  and caches raw responses on disk for an hour. A down feed is logged and
  skipped — one dead source never blocks a run.
- **Ranking** scores every upcoming event against your interest profile:
  theme keyword matches, deadline proximity, prize size, and location
  preference, each with configurable weights. Past-deadline events are
  excluded; ties break deterministically (score desc, deadline asc, name).
- **Builder** turns the top pick into a brief, then runs a bounded
  agent loop — scaffold, implement, test, repair — until the generated
  project's tests pass or the budget runs out.

## Quickstart

Requires Python 3.12+.

```bash
pip install -e ".[dev]"        # or: uv pip install -e ".[dev]"
cp .env.example .env           # only needed for the optional Claude backend
```

Tune `profile.yaml` (a documented example ships with the repo) — every field
is optional:

```yaml
interests:
  - ai                      # plain keyword, weight 1.0
  - keyword: climate        # weighted keyword
    weight: 2.0
preferred_prize_min: 10000   # prizes at or above this score full marks
deadline_window_days: 30     # closer deadlines score higher inside this window
preferred_locations:
  - Online                   # location boost (substring match, case-insensitive)
weights:                     # component weights — documented defaults
  theme: 3.0
  deadline: 2.0
  prize: 1.5
  location: 1.0
```

Profile lookup order: `--profile <path>`, then `profile.yaml` in the working
directory, then `~/.config/alexander/profile.yaml`.

Then run the full pipeline:

```bash
alexander run --dry-run       # see what it would build, spend nothing
alexander run                 # discover → rank → build for the top event
```

The first real run builds into `./builds/<event-slug>/` with `SPEC.md`, the
implementation, its test suite, and a README pitch.

## CLI reference

### `alexander discover`

```bash
alexander discover            # list events from all feeds
alexander discover --no-cache # bypass the 1-hour response cache
```

Fetches and parses both feeds, dedupes, and prints `name [source] url` per
event. Exits 0 even if one feed is down (the failure is logged and skipped).

### `alexander rank`

```bash
alexander rank                # ranked table: rank, score, name, deadline, prize, top reason
alexander rank --json         # machine-readable output (rank, score, reasons, event)
alexander rank --no-cache     # skip the discovery response cache
alexander rank --profile other.yaml
```

Scoring rules worth knowing: keywords match case-insensitively against the
event name and theme list; missing prizes and missing deadlines score neutral
rather than zero; events whose deadline has already passed are **excluded**
from the ranked output (they cannot be entered).

### `alexander run`

```bash
alexander run                              # build for the top-ranked event
alexander run --dry-run                    # stop before the build; print the plan
alexander run --top 3                      # build for the top 3 events, in rank order
alexander run --pick 2                     # build for the event at rank 2 (1-based)
alexander run --out my-builds              # change the output root (default: ./builds)
alexander run --backend claude             # override ALEXANDER_BUILD_BACKEND
alexander run --max-attempts 1 --minutes 10
```

Pipeline: discover (cache-aware) → rank against the profile → select the top
event (or `--top N` / `--pick <index>`) → build each selection into
`<out-root>/<event-slug>/`. A failing build reports the error and moves on to
the next selection; the command exits 1 if any build failed.

### `alexander swarm`

```bash
alexander swarm                          # 3 workers, one per top-ranked event
alexander swarm --instances 5            # 5 concurrent workers
alexander swarm --instances 3 --events 10  # 3 workers churn through the top 10 events
alexander swarm --dry-run                # print the plan + registry state; build nothing
alexander swarm --registry /path/swarm.db
alexander swarm --out builds --backend claude --max-attempts 2 --minutes 15
```

Swarm mode builds several events **concurrently**: discovery and ranking run
once (through the shared, atomically-written response cache — N instances
cause exactly one feed fetch per URL per hour), the top M events are planned,
and then that many asyncio workers pull events in rank order. Before building,
each worker *claims* the event in a shared SQLite registry; if another
instance already claimed it, the worker moves on. The command exits 1 if any
build failed.

### `alexander swarm-report`

```bash
alexander swarm-report                       # read the default registry
alexander swarm-report --registry /path/swarm.db --out my-builds
```

Prints the swarm leaderboard (rank, event, worker, status, attempts, tests,
build directory) and writes `<out-root>/swarm-report.json` with the full rows.
It reads any registry — including one written by a crashed coordinator — and
exits 1 if any recorded build failed, with pending claims listed as a warning.

### `alexander build`

```bash
alexander build --brief brief.json --out out/pomodoro
```

Builds one project from a JSON brief (as produced by `alexander rank --json`)
without running discovery or ranking:

```json
{
  "event_name": "Sample Hack 2026",
  "description": "A CLI pomodoro timer for hackathon sprints",
  "themes": ["productivity"],
  "deadline": "2026-12-01",
  "prize": "$500"
}
```

The same stage is available as a library:

```python
import asyncio
from pathlib import Path

from alexander.builder import BuildBudgets, HackathonBrief, create_builder

brief = HackathonBrief(
    event_name="Sample Hack 2026",
    description="A CLI pomodoro timer for hackathon sprints",
    themes=["productivity"],
)
result = asyncio.run(
    create_builder().build(brief, Path("out/pomodoro"), BuildBudgets())
)
print(result.status, result.artifact_path, result.test_summary)
```

## Claim registry

The swarm's only shared state is a SQLite claim registry (stdlib `sqlite3`,
WAL mode; default `~/.cache/alexander/swarm.db`, override with `--registry`).
Every event gets one row keyed by its slug, and claiming is a single
`INSERT OR IGNORE` — so even two processes racing on the same event cannot
both win. The claim owner defaults to `hostname:pid`, making two terminals on
one machine distinct claimants.

| State | Meaning | Set by | Exits |
| --- | --- | --- | --- |
| *(absent)* | Unclaimed — any worker may take it | — | `claim()` wins |
| `claimed` | Owned, build in flight | `claim()` | `record_result()` or `release()` |
| `success` | Built, tests verified | `record_result()` | terminal |
| `failed` | Budget exhausted or errored | `record_result()` | terminal |

Results are recorded on the same row (owner-checked), which makes the registry
the single source for `swarm-report`. If a worker dies between claiming and
recording, the row stays `claimed`: `swarm-report` lists it as **pending**
for a human decision rather than auto-reclaiming. Multiple coordinators can
run at once without harm — claiming stays atomic, and the registry file is
created on first use.

## Backends

The build engine is pluggable; pick one with `ALEXANDER_BUILD_BACKEND`
(or `alexander run/build --backend`):

| Backend | Value | Requirements | Notes |
|---|---|---|---|
| Obvious (default) | `obvious` or unset | `obvious` CLI on PATH with ambient credentials | Dispatches each attempt to an Obvious coding agent (`obvious tasks create --assignee=coder --start=true`), polls the task to completion, then verifies the produced project's tests locally |
| Claude Agent SDK | `claude` | `ANTHROPIC_API_KEY` | Drives the agent locally inside the build directory. Without the key you get a friendly setup hint instead of a traceback |

`ANTHROPIC_API_KEY` is **optional** — it is only needed for the `claude`
backend. Get a key at [console.anthropic.com](https://console.anthropic.com/settings/keys)
and export it or put it in `.env` (see `.env.example`).

## Cost and budget notes

Every build is bounded two ways, overridable per invocation:

- `--max-attempts` (default **5**) — agent attempts. The Obvious backend
  dispatches one coding-agent task per attempt; a failed or unverified attempt
  consumes one budget unit and retries with the failure appended to the prompt.
- `--minutes` (default **30**) — wall-clock budget per build. When it runs
  out, remaining attempts are skipped and the build reports
  `budget_exhausted`.

Each attempt is a real agent run, so a `run --top 3` with defaults can spawn
up to 15 coding-agent tasks. Swarm mode multiplies this further: worst-case
spend is **events × max attempts** (with `--instances 3` that is 3 events × 5
attempts = up to 15 tasks by default), so the default `--instances` stays
modest (3). For a first contact, keep it cheap:

```bash
alexander run --max-attempts 1 --minutes 10
alexander swarm --instances 2 --max-attempts 1 --minutes 10
```

and graduate to bigger budgets once the output quality is where you want it.
`--dry-run` costs nothing — use it before any real spend.

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

## Attribution

Event data comes from [Hack Club Hackathons](https://hackathons.hackclub.com/).
Hack Club requires attribution for any output built on that data — keep this
credit intact when redistributing results.
