"""Budget-loop behaviour with scripted agent attempts (no SDK, no network)."""

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from alexander.builder import (
    AgentBackendError,
    AttemptOutcome,
    BuildBudgets,
    BuildStatus,
    ClaudeAgentBuilder,
)

PYPROJECT = '[project]\nname = "counter"\nversion = "0.1.0"\n'


def write_passing_project(cwd: Path) -> None:
    (cwd / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (cwd / "counter.py").write_text("def count() -> int:\n    return 1\n", encoding="utf-8")
    (cwd / "test_counter.py").write_text(
        "from counter import count\n\n\ndef test_count():\n    assert count() == 1\n",
        encoding="utf-8",
    )


def write_failing_project(cwd: Path) -> None:
    write_passing_project(cwd)
    (cwd / "test_counter.py").write_text(
        "from counter import count\n\n\ndef test_count():\n    assert count() == 2\n",
        encoding="utf-8",
    )


def scripted_attempt(
    writers: list[Callable[[Path], None]],
    prompts: list[str],
):
    """Attempt fn that writes a per-attempt project into cwd and records prompts."""
    calls = 0

    async def attempt(prompt: str, cwd: Path, timeout_s: float) -> AttemptOutcome:
        nonlocal calls
        prompts.append(prompt)
        writers[min(calls, len(writers) - 1)](cwd)
        calls += 1
        return AttemptOutcome(text=f"attempt {calls} done", num_turns=2, duration_ms=10)

    return attempt


def fast_budgets(max_attempts: int) -> BuildBudgets:
    return BuildBudgets(max_attempts=max_attempts, wall_clock=timedelta(minutes=5))


async def test_success_on_first_attempt(tmp_path, brief) -> None:
    prompts: list[str] = []
    builder = ClaudeAgentBuilder(
        attempt_fn=scripted_attempt([write_passing_project], prompts), clock=lambda: 0.0
    )
    result = await builder.build(brief, tmp_path, fast_budgets(max_attempts=3))

    assert result.status is BuildStatus.SUCCESS
    assert result.attempts_used == 1
    assert result.test_summary is not None and "passed" in result.test_summary
    assert result.artifact_path == tmp_path
    assert "attempt 1 of 3" in prompts[0]
    assert brief.description in prompts[0]
    assert "Testathon" in prompts[0]


async def test_second_attempt_repairs_failing_tests(tmp_path, brief) -> None:
    prompts: list[str] = []
    builder = ClaudeAgentBuilder(
        attempt_fn=scripted_attempt([write_failing_project, write_passing_project], prompts),
        clock=lambda: 0.0,
    )
    result = await builder.build(brief, tmp_path, fast_budgets(max_attempts=3))

    assert result.status is BuildStatus.SUCCESS
    assert result.attempts_used == 2
    assert "tests failed on attempt 1" in prompts[1]


async def test_attempt_budget_exhaustion(tmp_path, brief) -> None:
    builder = ClaudeAgentBuilder(
        attempt_fn=scripted_attempt([write_failing_project], []), clock=lambda: 0.0
    )
    result = await builder.build(brief, tmp_path, fast_budgets(max_attempts=2))

    assert result.status is BuildStatus.BUDGET_EXHAUSTED
    assert result.attempts_used == 2
    assert result.test_summary is not None and "tests failed" in result.test_summary


async def test_wall_clock_stops_before_first_attempt(tmp_path, brief) -> None:
    ticks = iter([0.0, 100.0])  # deadline computed at 0, first budget check at 100
    builder = ClaudeAgentBuilder(
        attempt_fn=scripted_attempt([write_passing_project], []),
        clock=lambda: next(ticks, 1e9),
    )
    result = await builder.build(brief, tmp_path, BuildBudgets(max_attempts=3, wall_clock=_wall()))

    assert result.status is BuildStatus.BUDGET_EXHAUSTED
    assert result.attempts_used == 0
    assert result.test_summary is None


async def test_wall_clock_stops_between_attempt_and_tests(tmp_path, brief) -> None:
    ticks = iter([0.0, 0.0, 100.0])  # out of time right after the agent attempt
    builder = ClaudeAgentBuilder(
        attempt_fn=scripted_attempt([write_passing_project], []),
        clock=lambda: next(ticks, 1e9),
    )
    result = await builder.build(brief, tmp_path, BuildBudgets(max_attempts=3, wall_clock=_wall()))

    assert result.status is BuildStatus.BUDGET_EXHAUSTED
    assert result.attempts_used == 1
    assert result.test_summary is None


async def test_backend_error_returns_error_result(tmp_path, brief) -> None:
    async def broken(prompt: str, cwd: Path, timeout_s: float) -> AttemptOutcome:
        raise AgentBackendError("claude CLI not found")

    result = await ClaudeAgentBuilder(attempt_fn=broken).build(brief, tmp_path, fast_budgets(3))

    assert result.status is BuildStatus.ERROR
    assert result.error is not None and "claude CLI not found" in result.error
    assert result.attempts_used == 1


async def test_success_without_agent_readme_gets_fallback(tmp_path, brief) -> None:
    def write_project_no_readme(cwd: Path) -> None:
        write_passing_project(cwd)

    builder = ClaudeAgentBuilder(
        attempt_fn=scripted_attempt([write_project_no_readme], []), clock=lambda: 0.0
    )
    result = await builder.build(brief, tmp_path, fast_budgets(max_attempts=1))

    assert result.status is BuildStatus.SUCCESS
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert brief.event_name in readme
    assert result.test_summary in readme


def _wall() -> timedelta:
    return timedelta(seconds=10)
