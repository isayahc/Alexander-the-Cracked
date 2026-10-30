"""ObviousBackend flow with a fake CLI command runner (never spawns real tasks)."""

import json
from datetime import timedelta
from pathlib import Path

from alexander.builder import BuildBudgets, BuildStatus, ObviousBackend

PYPROJECT = '[project]\nname = "counter"\nversion = "0.1.0"\n'


def write_passing_project(cwd: Path) -> None:
    (cwd / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (cwd / "counter.py").write_text("def count() -> int:\n    return 1\n", encoding="utf-8")
    (cwd / "test_counter.py").write_text(
        "from counter import count\n\n\ndef test_count():\n    assert count() == 1\n",
        encoding="utf-8",
    )


def fake_cli(out_dir: Path, *, statuses: list[str], write_on_first_poll: bool = True):
    """Command runner faking `obvious tasks create`/`get` with scripted statuses."""
    calls: list[list[str]] = []
    polls = 0

    def runner(argv: list[str]) -> str:
        calls.append(argv)
        nonlocal polls
        joined = " ".join(argv)
        if "tasks create" in joined:
            assert "--assignee=coder" in joined
            assert "--start=true" in joined
            assert "--title=Build Testathon project" in joined
            return json.dumps({"id": "todo_fake123"})
        if "tasks get" in joined:
            status = statuses[min(polls, len(statuses) - 1)]
            polls += 1
            if status == "completed" and write_on_first_poll and polls == 1:
                write_passing_project(out_dir)
            payload: dict[str, str | None] = {"id": "todo_fake123", "status": status}
            payload["completionNote"] = "worker done" if status == "completed" else None
            return json.dumps(payload)
        raise AssertionError(f"unexpected command: {joined}")

    return runner, calls


def brief_event(joined: str) -> str:
    # The title is derived from the brief's event name rendered into the prompt.
    return "Testathon"


def obvious_budgets(max_attempts: int) -> BuildBudgets:
    return BuildBudgets(max_attempts=max_attempts, wall_clock=timedelta(minutes=5))


async def test_dispatches_task_and_succeeds(tmp_path, brief) -> None:
    runner, calls = fake_cli(tmp_path, statuses=["completed"])
    backend = ObviousBackend(runner=runner, poll_interval_s=0.0)

    result = await backend.build(brief, tmp_path, obvious_budgets(max_attempts=1))

    assert result.status is BuildStatus.SUCCESS
    assert result.attempts_used == 1
    assert result.test_summary is not None and "passed" in result.test_summary
    create_argv = " ".join(calls[0])
    assert "tasks create" in create_argv
    assert str(tmp_path) in create_argv  # worker told exactly where to write
    get_argv = " ".join(calls[1])
    assert "tasks get" in get_argv and "todo_fake123" in get_argv


async def test_worker_failure_retries_with_new_task(tmp_path, brief) -> None:
    runner, calls = fake_cli(tmp_path, statuses=["failed"], write_on_first_poll=False)
    backend = ObviousBackend(runner=runner, poll_interval_s=0.0)

    result = await backend.build(brief, tmp_path, obvious_budgets(max_attempts=2))

    assert result.status is BuildStatus.BUDGET_EXHAUSTED
    assert result.attempts_used == 2
    assert result.error is not None and "failed" in result.error
    creates = [" ".join(call) for call in calls if "tasks create" in " ".join(call)]
    assert len(creates) == 2  # each attempt dispatches a fresh task


async def test_missing_cli_is_a_backend_error(tmp_path, brief) -> None:
    def missing_cli(argv: list[str]) -> str:
        raise FileNotFoundError("obvious")

    backend = ObviousBackend(runner=missing_cli)
    result = await backend.build(brief, tmp_path, obvious_budgets(max_attempts=3))

    assert result.status is BuildStatus.ERROR
    assert result.error is not None and "not found on PATH" in result.error


async def test_worker_polling_until_deadline(tmp_path, brief) -> None:
    runner, _ = fake_cli(tmp_path, statuses=["in_progress"], write_on_first_poll=False)
    ticks = iter([0.0, 0.0, 0.0, 100.0])  # outer loop twice, then past the 10s poll budget
    backend = ObviousBackend(runner=runner, poll_interval_s=0.0, clock=lambda: next(ticks, 1e9))

    result = await backend.build(
        brief, tmp_path, BuildBudgets(max_attempts=1, wall_clock=timedelta(seconds=10))
    )

    assert result.status is BuildStatus.BUDGET_EXHAUSTED
    assert result.error is not None and "did not finish within the build budget" in result.error


def test_title_from_prompt() -> None:
    from alexander.builder.obvious import title_from_prompt

    assert (
        title_from_prompt("You are Alexander...\n\nEvent: Sample City Hack 2026\n")
        == "Build Sample City Hack 2026 project"
    )
    assert title_from_prompt("no event line") == "Alexander project build"


def test_task_id_parsing() -> None:
    from alexander.builder.obvious import ObviousCliError, _task_id_from_output

    assert _task_id_from_output('{"id": "todo_abc", "status": "pending"}') == "todo_abc"
    assert _task_id_from_output('{"task": {"id": "todo_nested"}}') == "todo_nested"
    assert _task_id_from_output("created task todo_plainxyz ok") == "todo_plainxyz"
    try:
        _task_id_from_output("no id here")
    except ObviousCliError as exc:
        assert "could not find a task id" in str(exc)
    else:
        raise AssertionError("expected ObviousCliError")
