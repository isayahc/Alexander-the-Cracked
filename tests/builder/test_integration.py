"""End-to-end flow with a scripted (fake) agent loop.

The real build loop, prompt rendering, budget accounting, and test verification
all run; only the LLM agent is faked. No Anthropic API calls, no network.
"""

from datetime import timedelta
from pathlib import Path

from alexander.builder import (
    AttemptOutcome,
    BuildBudgets,
    BuildStatus,
    ClaudeAgentBuilder,
    HackathonBrief,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_brief.json"

TOY_PYPROJECT = (
    "[project]\n"
    'name = "sprint-timer"\n'
    'version = "0.1.0"\n'
    'description = "A tiny sprint timer CLI for hackathon teams."\n'
)

TOY_TIMER = '''"""Sprint timer toy: count down hackathon sprint minutes."""


def format_remaining(minutes: int) -> str:
    if minutes < 0:
        raise ValueError("minutes must be non-negative")
    return f"{minutes} min left"


if __name__ == "__main__":
    print(format_remaining(25))
'''

TOY_TESTS = '''from sprint_timer import format_remaining


def test_format_remaining():
    assert format_remaining(25) == "25 min left"


def test_negative_minutes_rejected():
    try:
        format_remaining(-1)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
'''

TOY_README = """# Sprint timer

A tiny pitch: count down hackathon sprints and cheer when they end.
"""


class ScriptedBuildAgent:
    """Fake agent attempt fn: writes a recorded toy project, ignoring the prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def __call__(self, prompt: str, cwd: Path, timeout_s: float) -> AttemptOutcome:
        self.prompts.append(prompt)
        (cwd / "SPEC.md").write_text(
            "# Sprint timer spec\n\nCount down sprint minutes; cheer at zero.\n",
            encoding="utf-8",
        )
        (cwd / "pyproject.toml").write_text(TOY_PYPROJECT, encoding="utf-8")
        (cwd / "sprint_timer.py").write_text(TOY_TIMER, encoding="utf-8")
        (cwd / "test_timer.py").write_text(TOY_TESTS, encoding="utf-8")
        (cwd / "README.md").write_text(TOY_README, encoding="utf-8")
        return AttemptOutcome(text="sprint timer ready", num_turns=4, duration_ms=1_000)


async def test_recorded_sample_brief_builds_project_end_to_end(tmp_path) -> None:
    brief = HackathonBrief.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    out_dir = tmp_path / "sample-build"
    agent = ScriptedBuildAgent()
    builder = ClaudeAgentBuilder(attempt_fn=agent)

    result = await builder.build(
        brief, out_dir, BuildBudgets(max_attempts=2, wall_clock=timedelta(minutes=5))
    )

    assert result.status is BuildStatus.SUCCESS
    assert result.attempts_used == 1
    assert result.artifact_path == out_dir
    assert result.test_summary is not None and "passed" in result.test_summary

    names = {entry.name for entry in out_dir.iterdir()}
    assert {"SPEC.md", "README.md", "pyproject.toml", "sprint_timer.py", "test_timer.py"} <= names

    readme = (out_dir / "README.md").read_text(encoding="utf-8")
    assert "pitch" in readme.lower()

    # The brief fed through to the agent prompt, and the result serializes cleanly.
    assert brief.event_name in agent.prompts[0]
    payload = result.model_dump()
    assert payload["status"] == "success"
