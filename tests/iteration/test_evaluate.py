"""Evaluation checks against real test runs and real files (no mocks for the probes)."""

from pathlib import Path

from conftest import write_failing_project, write_passing_project

from alexander.builder.verify import run_tests
from alexander.iteration.evaluate import evaluate_project
from alexander.iteration.models import CheckStatus


def test_passing_project_passes_all_checks(tmp_path: Path) -> None:
    write_passing_project(tmp_path)

    evaluation = evaluate_project(tmp_path, timeout_s=60, run_test_suite=run_tests)

    assert evaluation.passed is True
    assert [check.name for check in evaluation.checks] == ["tests", "spec", "readme"]
    assert all(check.status is CheckStatus.PASSED for check in evaluation.checks)
    tests_check = evaluation.checks[0]
    assert "1 passed" in tests_check.evidence
    assert evaluation.test_summary == tests_check.evidence


def test_failing_tests_fail_the_evaluation_with_evidence(tmp_path: Path) -> None:
    write_failing_project(tmp_path)

    evaluation = evaluate_project(tmp_path, timeout_s=60, run_test_suite=run_tests)

    assert evaluation.passed is False
    tests_check = evaluation.checks[0]
    assert tests_check.status is CheckStatus.FAILED
    assert "tests failed" in tests_check.evidence
    # Artifact checks still ran and report the full state.
    assert evaluation.checks[1].status is CheckStatus.PASSED


def test_missing_artifacts_fail_even_with_passing_tests(tmp_path: Path) -> None:
    write_passing_project(tmp_path)
    (tmp_path / "SPEC.md").unlink()
    (tmp_path / "README.md").unlink()

    evaluation = evaluate_project(tmp_path, timeout_s=60, run_test_suite=run_tests)

    assert evaluation.passed is False
    assert evaluation.checks[0].status is CheckStatus.PASSED
    assert evaluation.checks[1].evidence == "SPEC.md missing"
    assert evaluation.checks[2].evidence == "README.md missing"


def test_artifact_check_evidence_carries_file_size(tmp_path: Path) -> None:
    write_passing_project(tmp_path)

    evaluation = evaluate_project(tmp_path, timeout_s=60, run_test_suite=run_tests)

    spec = evaluation.checks[1]
    assert spec.evidence.startswith("SPEC.md present (")
    assert "bytes" in spec.evidence
