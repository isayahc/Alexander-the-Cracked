"""Objective project evaluation: probes that actually run, evidence you can read.

A project passes evaluation only when its real test suite passes and the
artifacts the builder promised (SPEC.md, README.md) exist. Every check records
the probe output that decided it, so an evaluation result is always traceable
to something that executed — the loop never accepts a backend's claim that
things are fine.
"""

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from alexander.builder.verify import TestRun, run_tests
from alexander.iteration.models import CheckRecord, CheckStatus

type TestRunner = Callable[[Path, float], TestRun]


class Evaluation(BaseModel):
    """Verdict on one built project, with per-check evidence."""

    passed: bool
    checks: list[CheckRecord]

    @property
    def test_summary(self) -> str | None:
        for check in self.checks:
            if check.name == "tests":
                return check.evidence
        return None


def evaluate_project(
    out_dir: Path,
    timeout_s: float,
    run_test_suite: TestRunner = run_tests,
) -> Evaluation:
    """Evaluate one built project with observable probes.

    `run_test_suite` is the injected seam (defaults to the real, bounded
    `run_tests`); artifact checks are plain file-existence probes. Checks run
    even after a failure so the record shows the full state, not a short-circuit.
    """
    checks: list[CheckRecord] = []

    test: TestRun = run_test_suite(out_dir, timeout_s)
    checks.append(CheckRecord(name="tests", status=_status(test.passed), evidence=test.summary))
    checks.append(_artifact_check(out_dir, "spec", "SPEC.md"))
    checks.append(_artifact_check(out_dir, "readme", "README.md"))

    return Evaluation(passed=all(c.status is CheckStatus.PASSED for c in checks), checks=checks)


def _artifact_check(out_dir: Path, name: str, filename: str) -> CheckRecord:
    path = out_dir / filename
    exists = path.is_file()
    evidence = (
        f"{filename} present ({path.stat().st_size} bytes)" if exists else f"{filename} missing"
    )
    return CheckRecord(name=name, status=_status(exists), evidence=evidence)


def _status(ok: bool) -> CheckStatus:
    return CheckStatus.PASSED if ok else CheckStatus.FAILED
