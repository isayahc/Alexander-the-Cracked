"""Tests for `alexander swarm-report` and the report rendering (no agents, no network)."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from alexander.builder import BuildStatus
from alexander.cli import cli
from alexander.swarm import CLAIMED, ClaimRegistry, render_leaderboard


@pytest.fixture(name="registry_path")
def registry_path_fixture(tmp_path: Path) -> Path:
    return tmp_path / "swarm.db"


@pytest.fixture(name="out_root")
def out_root_fixture(tmp_path: Path) -> Path:
    return tmp_path / "builds"


def claim_as(
    registry_path: Path, owner: str, slug: str, name: str, rank: int
) -> ClaimRegistry:
    """Open a registry as one claimant and claim a single event."""
    registry = ClaimRegistry(registry_path, owner=owner)
    assert registry.claim(slug, name, rank)
    return registry


def record(
    registry: ClaimRegistry,
    slug: str,
    status: BuildStatus,
    **overrides: object,
) -> None:
    registry.record_result(
        slug,
        status,
        overrides.get("artifact_path"),
        overrides.get("test_summary"),
        overrides.get("error"),
        overrides.get("attempts_used", 1),
    )


def test_report_table_and_json(
    registry_path: Path, out_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterion 6: the leaderboard shows rank/event/worker/status/attempts/tests/dir,
    pending rows appear explicitly, and swarm-report.json carries the full rows."""
    # One success (owner w1), one failure (owner w2), one still pending.
    w1 = claim_as(registry_path, "w1", "neurips-hack-2026", "NeurIPS Hack 2026", 1)
    record(
        w1,
        "neurips-hack-2026",
        BuildStatus.SUCCESS,
        artifact_path=Path("builds/neurips-hack-2026"),
        test_summary="18 passed",
    )
    w2 = claim_as(registry_path, "w2", "climatehack-q4", "ClimateHack Q4", 2)
    record(
        w2,
        "climatehack-q4",
        BuildStatus.ERROR,
        error="backend exploded",
        attempts_used=5,
    )
    claim_as(registry_path, "w3", "web3-jam", "Web3 Jam", 3)
    for registry in (w1, w2):
        registry.close()

    result = CliRunner().invoke(
        cli,
        ["swarm-report", "--registry", str(registry_path), "--out", str(out_root)],
    )

    # A failed build in the registry means exit 1 (criterion 6), even though
    # this table also shows a success and a pending row.
    assert result.exit_code == 1
    for fragment in (
        "Rank",
        "Event",
        "Worker",
        "Status",
        "Attempts",
        "Tests",
        "Build dir",
        "NeurIPS Hack 2026",
        "w1",
        "✅ success",
        "18 passed",
        "builds/neurips-hack-2026",
        "ClimateHack Q4",
        "w2",
        "❌ error",
        "Web3 Jam",
        "⚠️ pending",
    ):
        assert fragment in result.output, fragment

    report = json.loads((out_root / "swarm-report.json").read_text(encoding="utf-8"))
    assert [row["event_slug"] for row in report["rows"]] == [
        "neurips-hack-2026",
        "climatehack-q4",
        "web3-jam",
    ]
    assert [row["status"] for row in report["rows"]] == [
        BuildStatus.SUCCESS.value,
        BuildStatus.ERROR.value,
        CLAIMED,
    ]
    assert [row["owner"] for row in report["rows"]] == ["w1", "w2", "w3"]
    assert report["rows"][0]["test_summary"] == "18 passed"
    assert report["rows"][0]["attempts_used"] == 1
    assert report["rows"][1]["error"] == "backend exploded"
    assert report["pending"] == ["web3-jam"]


def test_exit_code_on_failure(registry_path: Path, out_root: Path) -> None:
    """Any failed build exits 1; all-pending and empty registries exit 0."""
    registry = claim_as(registry_path, "w1", "climatehack-q4", "ClimateHack Q4", 2)
    record(
        registry,
        "climatehack-q4",
        BuildStatus.BUDGET_EXHAUSTED,
        error="budget exhausted after 5 attempts",
    )
    registry.close()

    failed = CliRunner().invoke(
        cli,
        ["swarm-report", "--registry", str(registry_path), "--out", str(out_root)],
    )
    assert failed.exit_code == 1
    assert "❌ budget_exhausted" in failed.output

    # All pending, in a fresh registry: nothing failed, so exit 0 with the
    # pending rows visible.
    pending_path = registry_path.with_name("pending.db")
    pending_registry = claim_as(pending_path, "w2", "web3-jam", "Web3 Jam", 3)
    pending_registry.close()
    all_pending = CliRunner().invoke(
        cli,
        ["swarm-report", "--registry", str(pending_path), "--out", str(out_root)],
    )
    assert all_pending.exit_code == 0
    assert "⚠️ pending" in all_pending.output


def test_report_on_missing_registry_is_an_empty_table(tmp_path: Path) -> None:
    """A fresh machine reports an empty table rather than crashing."""
    result = CliRunner().invoke(
        cli,
        [
            "swarm-report",
            "--registry",
            str(tmp_path / "fresh" / "swarm.db"),
            "--out",
            str(tmp_path / "builds"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "No claims recorded yet." in result.output
    report = json.loads((tmp_path / "builds" / "swarm-report.json").read_text("utf-8"))
    assert report == {"rows": [], "pending": []}


def test_render_leaderboard_empty() -> None:
    assert render_leaderboard([]) == "No claims recorded yet."
