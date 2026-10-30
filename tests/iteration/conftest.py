"""Shared fixtures for iteration tests: a brief, project writers, a scripted builder."""

import shutil
from pathlib import Path

import pytest

from alexander.builder.models import BuildBudgets, BuildResult, BuildStatus, HackathonBrief

PYPROJECT = '[project]\nname = "counter"\nversion = "0.1.0"\n'


@pytest.fixture
def brief() -> HackathonBrief:
    return HackathonBrief(
        event_name="Testathon",
        description="A CLI that cheers on hackathon teams",
        themes=["fun"],
        deadline="2026-12-31",
        prize="bragging rights",
    )


def write_passing_project(cwd: Path) -> None:
    """A minimal project whose real pytest suite passes, with all artifacts."""
    (cwd / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (cwd / "SPEC.md").write_text("# Spec\n", encoding="utf-8")
    (cwd / "README.md").write_text("# Pitch\n", encoding="utf-8")
    (cwd / "counter.py").write_text("def count() -> int:\n    return 1\n", encoding="utf-8")
    (cwd / "test_counter.py").write_text(
        "from counter import count\n\n\ndef test_count():\n    assert count() == 1\n",
        encoding="utf-8",
    )


def write_failing_project(cwd: Path) -> None:
    """Same shape, but the test suite genuinely fails."""
    write_passing_project(cwd)
    (cwd / "test_counter.py").write_text(
        "from counter import count\n\n\ndef test_count():\n    assert count() == 2\n",
        encoding="utf-8",
    )


def write_tests_passing_no_readme(cwd: Path) -> None:
    """Tests pass but the README artifact is missing: tests baseline, evaluation fails."""
    write_passing_project(cwd)
    (cwd / "README.md").unlink()


def wipe_dir(cwd: Path) -> None:
    for child in cwd.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


class ScriptedBuilder:
    """ProjectBuilder double: writes a scripted project per build, records budgets.

    The builder's own internal verdict is always SUCCESS (like a backend whose
    agent ran fine) — the iteration loop's evaluation must judge the project
    independently via the real test run.
    """

    def __init__(self, writers: list) -> None:
        self.writers = writers
        self.calls = 0
        self.received_budgets: list[BuildBudgets] = []

    async def build(
        self, brief: HackathonBrief, out_dir: Path, budgets: BuildBudgets
    ) -> BuildResult:
        self.received_budgets.append(budgets)
        out_dir.mkdir(parents=True, exist_ok=True)
        wipe_dir(out_dir)
        self.writers[min(self.calls, len(self.writers) - 1)](out_dir)
        self.calls += 1
        return BuildResult(
            status=BuildStatus.SUCCESS,
            artifact_path=out_dir,
            attempts_used=1,
            test_summary="tests passed: 1 passed (builder-internal)",
        )


class FailingBackendBuilder(ScriptedBuilder):
    """ScriptedBuilder that reports an environment-level backend failure."""

    async def build(
        self, brief: HackathonBrief, out_dir: Path, budgets: BuildBudgets
    ) -> BuildResult:
        self.received_budgets.append(budgets)
        self.calls += 1
        return BuildResult(
            status=BuildStatus.ERROR,
            artifact_path=out_dir,
            attempts_used=1,
            error="agent backend failed: sdk exploded",
        )
