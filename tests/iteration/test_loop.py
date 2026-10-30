"""Bounded loop behaviour with scripted builders and real test verification."""

from datetime import timedelta
from pathlib import Path

from conftest import (
    FailingBackendBuilder,
    ScriptedBuilder,
    write_failing_project,
    write_passing_project,
    write_tests_passing_no_readme,
)

from alexander.builder.models import BuildBudgets
from alexander.iteration import IterationBudgets, run_iteration_loop
from alexander.iteration.models import (
    IterationManifest,
    StopReason,
    best_known_dir_for,
    manifest_path_for,
)


def fast_budgets(max_iterations: int) -> IterationBudgets:
    return IterationBudgets(
        max_iterations=max_iterations,
        wall_clock=timedelta(minutes=5),
        build=BuildBudgets(max_attempts=3, wall_clock=timedelta(minutes=2)),
    )


async def test_pass_condition_stops_after_first_passing_round(tmp_path, brief) -> None:
    out_dir = tmp_path / "build"
    builder = ScriptedBuilder([write_passing_project])

    manifest = await run_iteration_loop(builder, brief, out_dir, fast_budgets(max_iterations=3))

    assert manifest.stop_reason is StopReason.PASS_CONDITION
    assert [r.iteration for r in manifest.iterations] == [1]
    assert manifest.iterations[0].passed is True
    assert manifest.best_iteration == 1
    assert manifest.best_known_dir == str(best_known_dir_for(out_dir))
    assert builder.calls == 1
    # One full loop = one recorded evaluation with per-check evidence.
    checks = manifest.iterations[0].checks
    assert [c.name for c in checks] == ["tests", "spec", "readme"]
    assert "1 passed" in checks[0].evidence


async def test_one_iteration_applied_after_a_failed_round(tmp_path, brief) -> None:
    """Fail first, pass second: the original epic's one-loop-with-one-iteration shape."""
    out_dir = tmp_path / "build"
    builder = ScriptedBuilder([write_failing_project, write_passing_project])

    manifest = await run_iteration_loop(builder, brief, out_dir, fast_budgets(max_iterations=3))

    assert manifest.stop_reason is StopReason.PASS_CONDITION
    assert [r.passed for r in manifest.iterations] == [False, True]
    assert manifest.best_iteration == 2
    assert manifest.iterations[0].restored_best is False  # nothing passing yet to restore
    assert "tests failed" in (manifest.iterations[0].test_summary or "")
    assert "1 passed" in (manifest.iterations[1].test_summary or "")
    assert builder.calls == 2


async def test_regression_after_a_tests_passing_round_is_rolled_back(tmp_path, brief) -> None:
    out_dir = tmp_path / "build"
    # Round 1: tests pass, artifacts missing (baseline snapshot, loop continues).
    # Round 2: breaks the tests → must be rolled back to round 1's behavior.
    builder = ScriptedBuilder([write_tests_passing_no_readme, write_failing_project])

    manifest = await run_iteration_loop(builder, brief, out_dir, fast_budgets(max_iterations=2))

    assert manifest.stop_reason is StopReason.BUDGET_ITERATIONS
    assert manifest.best_iteration == 1
    assert manifest.iterations[0].passed is False
    assert manifest.iterations[0].restored_best is False
    assert manifest.iterations[1].passed is False
    assert manifest.iterations[1].restored_best is True
    # The tests-passing behavior survives the regressed round, on disk, in
    # both the build dir and the best-known snapshot.
    assert (out_dir / "counter.py").read_text() == "def count() -> int:\n    return 1\n"
    assert (best_known_dir_for(out_dir) / "counter.py").read_text() == (
        "def count() -> int:\n    return 1\n"
    )
    assert not (out_dir / "README.md").exists()  # rollback, not the broken round's state


async def test_all_rounds_fail_leaves_no_best_known(tmp_path, brief) -> None:
    out_dir = tmp_path / "build"
    builder = ScriptedBuilder([write_failing_project])

    manifest = await run_iteration_loop(builder, brief, out_dir, fast_budgets(max_iterations=2))

    assert manifest.stop_reason is StopReason.BUDGET_ITERATIONS
    assert manifest.best_iteration is None
    assert manifest.best_known_dir is None
    assert not best_known_dir_for(out_dir).exists()
    assert [r.iteration for r in manifest.iterations] == [1, 2]


async def test_wall_clock_budget_stops_before_a_round_starts(tmp_path, brief) -> None:
    out_dir = tmp_path / "build"
    builder = ScriptedBuilder([write_passing_project])
    # First call sets the deadline (300s); by the second it is long gone.
    ticks = iter([0.0, 301.0])

    manifest = await run_iteration_loop(
        builder, brief, out_dir, fast_budgets(max_iterations=2), clock=lambda: next(ticks)
    )

    assert manifest.stop_reason is StopReason.BUDGET_WALL_CLOCK
    assert manifest.iterations == []
    assert builder.calls == 0


async def test_builder_error_stops_immediately(tmp_path, brief) -> None:
    out_dir = tmp_path / "build"
    builder = FailingBackendBuilder([write_passing_project])

    manifest = await run_iteration_loop(builder, brief, out_dir, fast_budgets(max_iterations=3))

    assert manifest.stop_reason is StopReason.BUILDER_ERROR
    assert [r.iteration for r in manifest.iterations] == [1]
    assert "sdk exploded" in manifest.iterations[0].error
    assert builder.calls == 1  # not retried


async def test_costs_are_recorded_per_round_and_in_totals(tmp_path, brief) -> None:
    out_dir = tmp_path / "build"
    builder = ScriptedBuilder([write_failing_project, write_passing_project])
    # Fake clock: call 1 sets the deadline, then 4 calls per round (pre-round
    # check, build start, evaluate-timeout floor, round end) — deterministic,
    # nonzero durations.
    ticks = iter([0.0, 10.0, 15.0, 20.0, 30.0, 35.0, 40.0, 50.0, 55.0])
    budget_sets = IterationBudgets(
        max_iterations=3,
        wall_clock=timedelta(minutes=5),
        build=BuildBudgets(max_attempts=3, wall_clock=timedelta(minutes=2)),
    )

    manifest = await run_iteration_loop(
        builder, brief, out_dir, budget_sets, clock=lambda: next(ticks)
    )

    assert [r.duration_s for r in manifest.iterations] == [15.0, 15.0]
    assert [r.attempts_used for r in manifest.iterations] == [1, 1]
    assert manifest.total_attempts == 2
    assert manifest.total_duration_s == 30.0


async def test_each_round_cannot_exceed_the_loop_remaining_wall_clock(tmp_path, brief) -> None:
    out_dir = tmp_path / "build"
    builder = ScriptedBuilder([write_failing_project, write_passing_project])

    manifest = await run_iteration_loop(builder, brief, out_dir, fast_budgets(max_iterations=3))

    # Loop wall clock 5 min, build budget 2 min: first round gets 2 min; the
    # second round's cap is min(2 min, whatever remains) — never more than 2.
    for received in builder.received_budgets:
        assert received.wall_clock <= timedelta(minutes=2)
    assert manifest is not None


async def test_manifest_is_persisted_and_reloadable(tmp_path, brief) -> None:
    out_dir = tmp_path / "build"
    builder = ScriptedBuilder([write_passing_project])

    await run_iteration_loop(builder, brief, out_dir, fast_budgets(max_iterations=1))

    path = manifest_path_for(out_dir)
    assert path.exists()

    reloaded = IterationManifest.model_validate_json(path.read_text(encoding="utf-8"))
    assert reloaded.stop_reason is StopReason.PASS_CONDITION
    assert reloaded.best_iteration == 1
    assert reloaded.iterations[0].passed is True
    assert reloaded.event_name == brief.event_name
    assert reloaded.out_dir == str(out_dir)


async def test_full_pass_replaces_the_baseline_snapshot(tmp_path, brief) -> None:
    out_dir = tmp_path / "build"

    # Round 1: tests pass, artifacts missing → tests-only baseline snapshot.
    # Round 2: fully passes evaluation → the snapshot must hold round 2.
    def write_v3(cwd: Path) -> None:
        write_passing_project(cwd)
        (cwd / "VERSION.md").write_text("v3\n", encoding="utf-8")

    builder = ScriptedBuilder([write_tests_passing_no_readme, write_v3])

    manifest = await run_iteration_loop(builder, brief, out_dir, fast_budgets(max_iterations=3))

    assert manifest.stop_reason is StopReason.PASS_CONDITION
    assert manifest.best_iteration == 2
    assert (best_known_dir_for(out_dir) / "VERSION.md").read_text() == "v3\n"
    assert (out_dir / "VERSION.md").read_text() == "v3\n"
    # The loop's verdict came from its own evaluation, not the builder's
    # internal summary.
    assert builder.received_budgets[0].max_attempts == 3
