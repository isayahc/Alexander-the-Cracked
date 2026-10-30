"""Fixture evidence run for epic #15, unit (c): bounded build-evaluate-iterate.

Scenario A — one full loop: round 1 fails its real test suite, round 2 passes;
the loop records both evaluations and stops on the pass condition.
Scenario B — regression protection: round 1's tests pass (artifacts missing),
round 2 breaks the tests, and the loop rolls the build dir back to round 1.

Both use a scripted ProjectBuilder (no agent, no network) with the REAL
run_tests subprocess deciding every evaluation. Run: python evidence_run.py
"""

import asyncio
import json
import shutil
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, "tests/iteration")
from conftest import ScriptedBuilder, write_failing_project, write_passing_project  # noqa: E402

from alexander.builder.models import (
    BuildBudgets,  # noqa: E402
    HackathonBrief,  # noqa: E402
)
from alexander.iteration import IterationBudgets, run_iteration_loop  # noqa: E402
from alexander.iteration.models import best_known_dir_for, manifest_path_for  # noqa: E402

BRIEF = HackathonBrief(
    event_name="Fixture Hack 2026",
    description="Demonstrates the bounded build-evaluate-iterate loop (fixture, no agents).",
    themes=["evidence"],
    deadline="2026-12-31",
    prize="none (fixture)",
)


def scenario_a(root: Path) -> None:
    out_dir = root / "loop-full"
    builder = ScriptedBuilder([write_failing_project, write_passing_project])
    budgets = IterationBudgets(
        max_iterations=3,
        wall_clock=timedelta(minutes=5),
        build=BuildBudgets(max_attempts=3, wall_clock=timedelta(minutes=2)),
    )
    manifest = asyncio.run(
        run_iteration_loop(builder, brief=BRIEF, out_dir=out_dir, budgets=budgets)
    )
    print(f"scenario A: stop={manifest.stop_reason.value} best_iteration={manifest.best_iteration}")
    for record in manifest.iterations:
        print(
            f"  iteration {record.iteration}: passed={record.passed} "
            f"attempts={record.attempts_used} duration_s={record.duration_s:.1f}"
        )
        for check in record.checks:
            print(f"    {check.name}: {check.status.value} — {check.evidence[:80]}")
    print(
        f"  totals: attempts={manifest.total_attempts} duration_s={manifest.total_duration_s:.1f}"
    )
    print(f"  manifest: {manifest_path_for(out_dir)}")
    print(f"  best-known: {best_known_dir_for(out_dir)}")


def scenario_b(root: Path) -> None:
    from conftest import write_tests_passing_no_readme

    out_dir = root / "loop-rollback"
    builder = ScriptedBuilder([write_tests_passing_no_readme, write_failing_project])
    budgets = IterationBudgets(
        max_iterations=2,
        wall_clock=timedelta(minutes=5),
        build=BuildBudgets(max_attempts=3, wall_clock=timedelta(minutes=2)),
    )
    manifest = asyncio.run(
        run_iteration_loop(builder, brief=BRIEF, out_dir=out_dir, budgets=budgets)
    )
    print(f"scenario B: stop={manifest.stop_reason.value} best_iteration={manifest.best_iteration}")
    for record in manifest.iterations:
        print(
            f"  iteration {record.iteration}: passed={record.passed} "
            f"restored_best={record.restored_best}"
        )
    print(
        f"  build dir counter.py after rollback: {(out_dir / 'counter.py').read_text().strip()!r}"
    )
    print(f"  manifest: {manifest_path_for(out_dir)}")


def main() -> None:
    root = Path("evidence/iterate-fixture")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    scenario_a(root)
    print()
    scenario_b(root)
    print()
    for path in sorted(root.rglob("*-iterations.json")):
        print(f"--- {path} ---")
        print(json.dumps(json.loads(path.read_text()), indent=2)[:1200])


if __name__ == "__main__":
    main()
