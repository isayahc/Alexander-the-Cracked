"""Live-run leg for epic #15, unit (d): one permitted live build + evaluation.

Execution-context finding (verbatim errors in dispatch-blockers.md): this
run's ambient credentials belong to a delegated Obvious coder agent, and
coder agents cannot dispatch further workers — 'coder'/'agent' assignees are
off-roster (422), independent tasks are forbidden (403), and explicit
parenting is depth-restricted (422). The platform's guidance in every error
is "do the work yourself", so the builder stage here is this agent building
the project directly into the build directory (a real, tested project — not a
scripted fixture).

Everything else is the untouched production path: the bounded iteration loop
runs with its explicit budgets and its INDEPENDENT evaluation re-runs the
real pytest subprocess against what landed on disk, snapshots the best-known
result, and writes the reloadable manifest. Because the builder was the
agent itself rather than a dispatched worker, attempts_used is 0 and the
dispatch blockers are recorded in dispatch-blockers.md.

Run from the repo root: python evidence/live-run/run_live_iteration.py
"""

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

from alexander.builder.models import BuildBudgets, BuildResult, BuildStatus, HackathonBrief
from alexander.iteration import IterationBudgets, run_iteration_loop
from alexander.iteration.models import manifest_path_for

OUT = Path("evidence/live-run")


class PreparedBuilder:
    """Reports the agent-built directory; the loop evaluates it independently."""

    async def build(
        self, brief: HackathonBrief, out_dir: Path, budgets: BuildBudgets
    ) -> BuildResult:
        return BuildResult(
            status=BuildStatus.SUCCESS,
            artifact_path=out_dir,
            attempts_used=0,
        )


def main() -> None:
    brief = HackathonBrief.model_validate_json(
        (OUT / "brief.json").read_text(encoding="utf-8")
    )
    budgets = IterationBudgets(
        max_iterations=1,
        wall_clock=timedelta(minutes=20),
        build=BuildBudgets(max_attempts=1, wall_clock=timedelta(minutes=20)),
    )
    manifest = asyncio.run(
        run_iteration_loop(
            PreparedBuilder(), brief=brief, out_dir=OUT / "build", budgets=budgets
        )
    )
    for record in manifest.iterations:
        verdict = "passed" if record.passed else "FAILED"
        print(f"iteration {record.iteration}: {verdict} ({record.test_summary or ''})")
        if record.error:
            print(f"  error: {record.error}")
    print(f"stopped: {manifest.stop_reason.value}")
    print(f"manifest: {manifest_path_for(OUT / 'build')}")
    if manifest.stop_reason.value != "pass_condition":
        sys.exit(1)


if __name__ == "__main__":
    main()
