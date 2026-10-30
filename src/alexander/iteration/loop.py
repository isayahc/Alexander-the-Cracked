"""The bounded build-evaluate-iterate loop.

One iteration = one full `ProjectBuilder.build` (itself attempt-budgeted)
followed by an independent evaluation of what actually landed on disk. The
loop stops only on explicit conditions — the pass condition or an exhausted
budget — and never on an agent's self-assessment.

Best-known-result preservation: the best-known snapshot (`<out>-best-known`,
next to the build dir) holds the latest round whose test suite passed — the
regression baseline — and is upgraded to the full best-known result when a
round passes evaluation outright (tests plus required artifacts). A later
round that breaks those tests is rolled back to the snapshot, so what remains
on disk is never worse than the last verified-passing state.
"""

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from alexander.builder.agent import ProjectBuilder
from alexander.builder.models import BuildBudgets, BuildResult, BuildStatus, HackathonBrief
from alexander.builder.verify import run_tests
from alexander.iteration.evaluate import Evaluation, TestRunner, evaluate_project
from alexander.iteration.models import (
    CheckStatus,
    IterationManifest,
    IterationRecord,
    StopReason,
    best_known_dir_for,
    manifest_path_for,
)


@dataclass(frozen=True)
class IterationBudgets:
    """Explicit stop conditions for the loop: pass condition, or these budgets."""

    max_iterations: int = 2
    wall_clock: timedelta = timedelta(minutes=60)
    # Budgets handed to each builder round; its wall clock is capped at the
    # loop's remaining time so one build cannot blow the whole budget.
    build: BuildBudgets = BuildBudgets()

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        if self.wall_clock.total_seconds() <= 0:
            raise ValueError("wall_clock must be positive")


async def run_iteration_loop(
    builder: ProjectBuilder,
    brief: HackathonBrief,
    out_dir: Path,
    budgets: IterationBudgets,
    clock: Callable[[], float] = time.monotonic,
    run_test_suite: TestRunner = run_tests,
) -> IterationManifest:
    """Build, evaluate, and iterate until the pass condition or a budget stops it.

    Setup errors (missing API key, invalid budgets) propagate to the caller.
    """
    best_dir = best_known_dir_for(out_dir)
    deadline = clock() + budgets.wall_clock.total_seconds()
    manifest = IterationManifest(
        event_name=brief.event_name, out_dir=str(out_dir), stop_reason=StopReason.BUDGET_ITERATIONS
    )

    for iteration in range(1, budgets.max_iterations + 1):
        remaining = deadline - clock()
        if remaining <= 0:
            manifest.stop_reason = StopReason.BUDGET_WALL_CLOCK
            break
        build_budgets = BuildBudgets(
            max_attempts=budgets.build.max_attempts,
            wall_clock=timedelta(seconds=min(budgets.build.wall_clock.total_seconds(), remaining)),
        )
        result, evaluation, duration = await _build_and_evaluate(
            builder, brief, out_dir, build_budgets, clock, run_test_suite
        )
        record = IterationRecord(
            iteration=iteration,
            passed=evaluation.passed,
            attempts_used=result.attempts_used,
            duration_s=duration,
            test_summary=evaluation.test_summary,
            checks=evaluation.checks,
            error=result.error,
        )
        if evaluation.passed:
            _snapshot(out_dir, best_dir)
            manifest.best_iteration = iteration
            manifest.best_known_dir = str(best_dir)
            manifest.stop_reason = StopReason.PASS_CONDITION
            manifest.iterations.append(record)
            break
        if result.status is BuildStatus.ERROR:
            # An environment-level builder failure is not something another
            # identical round can fix — stop and say so instead of burning budget.
            manifest.stop_reason = StopReason.BUILDER_ERROR
            manifest.iterations.append(record)
            break
        if _tests_passed(evaluation):
            # Tests are the regression baseline: a round whose suite passed but
            # which failed on artifacts is still the best-known behavior — keep
            # it so a later round cannot destroy what already worked.
            _snapshot(out_dir, best_dir)
            manifest.best_iteration = iteration
            manifest.best_known_dir = str(best_dir)
        elif best_dir.exists():
            # This round broke tests that a previous round had passing —
            # roll back to that verified state instead of leaving the regression.
            _restore(best_dir, out_dir)
            record.restored_best = True
        manifest.iterations.append(record)

    _write_manifest(manifest, manifest_path_for(out_dir))
    return manifest


async def _build_and_evaluate(
    builder: ProjectBuilder,
    brief: HackathonBrief,
    out_dir: Path,
    build_budgets: BuildBudgets,
    clock: Callable[[], float],
    run_test_suite: TestRunner,
) -> tuple[BuildResult, Evaluation, float]:
    """One round: build, then independently evaluate what landed on disk."""
    started = clock()
    result = await builder.build(brief, out_dir, build_budgets)
    remaining = max(build_budgets.wall_clock.total_seconds() - (clock() - started), 1.0)
    # Independent re-verification: the evaluation runs the suite itself rather
    # than trusting the builder's internal verdict.
    evaluation = evaluate_project(out_dir, timeout_s=remaining, run_test_suite=run_test_suite)
    return result, evaluation, clock() - started


def _tests_passed(evaluation: Evaluation) -> bool:
    """Whether the evaluation's test-suite check (the regression baseline) passed."""
    for check in evaluation.checks:
        if check.name == "tests":
            return check.status is CheckStatus.PASSED
    return False


def _snapshot(out_dir: Path, best_dir: Path) -> None:
    """Replace the best-known snapshot with the current passing project."""
    if best_dir.exists():
        shutil.rmtree(best_dir)
    shutil.copytree(out_dir, best_dir)


def _restore(best_dir: Path, out_dir: Path) -> None:
    """Copy the best-known snapshot back over a failed iteration's output."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(best_dir, out_dir)


def _write_manifest(manifest: IterationManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
