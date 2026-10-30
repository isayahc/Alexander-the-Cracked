# Alexander the Cracked

An agent that searches for hackathons and competitions then builds project codebases for them.

## Setup

Requires Python 3.12+.

```bash
pip install -e ".[dev]"
```

or, with [uv](https://docs.astral.sh/uv/):

```bash
uv pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY` (needed for the builder stage).

Check the install:

```bash
alexander --help
```

## Layout

- `src/alexander/discovery/` — finds hackathons and competitions from public feeds
- `src/alexander/ranking/` — ranks events against a user interest profile
- `src/alexander/builder/` — agentic coding loop that generates project codebases
- `src/alexander/orchestrator/` — wires the stages into one pipeline

## Ranking events against your interests

`alexander rank` scores discovered events against an editable interest profile.
The profile is a YAML file, looked up in this order:

1. the path given to `alexander rank --profile <path>`
2. `profile.yaml` at the repository root (a documented example ships with the repo)
3. `~/.config/alexander/profile.yaml`

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

Scoring rules worth knowing: keywords match case-insensitively against the
event name and theme list; missing prizes and missing deadlines score neutral
rather than zero; events whose deadline has already passed are **excluded**
from the ranked output (they cannot be entered); and ties break
deterministically by score descending, then earlier deadline (missing
deadlines last), then name.

```bash
alexander rank                # ranked table: rank, score, name, deadline, prize, top reason
alexander rank --json         # machine-readable output (rank, score, reasons, event)
alexander rank --no-cache     # skip the discovery response cache
```

## Build a project

The builder turns a hackathon brief into a small, tested project directory:

```python
import asyncio
from pathlib import Path

from alexander.builder import BuildBudgets, HackathonBrief, create_builder

brief = HackathonBrief(
    event_name="Sample Hack 2026",
    description="A CLI pomodoro timer for hackathon sprints",
    themes=["productivity"],
    deadline="2026-12-01",
    prize="$500",
)
result = asyncio.run(
    create_builder().build(brief, Path("out/pomodoro"), BuildBudgets())
)
print(result.status, result.artifact_path, result.test_summary)
```

Or from a JSON brief file:

```bash
alexander build --brief brief.json --out out/pomodoro
```

Each build is bounded by an attempt budget (default 5) and a wall-clock budget
(default 30 minutes).

### Backends

The build engine is pluggable; pick one with `ALEXANDER_BUILD_BACKEND`:

- `obvious` (default) — dispatches each build to an Obvious coding agent via the
  `obvious` CLI (`obvious tasks create --assignee=coder --start=true`), polls the
  task to completion, then verifies the produced project's tests. Uses the
  ambient credentials; nothing is hardcoded.
- `claude` — drives the Claude Agent SDK locally. Only activates when
  `ANTHROPIC_API_KEY` is set; without it you get a friendly setup hint instead of
  a traceback.

## Attribution

Events sourced from the Hack Club API (https://hackathons.hackclub.com/) require Hack Club attribution — any output built on that data must credit Hack Club.
