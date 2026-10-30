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

Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY` (needed once the builder stage lands).

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

## Attribution

Events sourced from the Hack Club API (https://hackathons.hackclub.com/) require Hack Club attribution — any output built on that data must credit Hack Club.
