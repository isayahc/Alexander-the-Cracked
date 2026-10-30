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

## Attribution

Events sourced from the Hack Club API (https://hackathons.hackclub.com/) require Hack Club attribution — any output built on that data must credit Hack Club.
