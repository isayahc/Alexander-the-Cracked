"""Tests for the SQLite claim registry: exclusivity, owner-checked results, release."""

import os
import socket
from pathlib import Path

import pytest

from alexander.builder import BuildStatus
from alexander.swarm import ClaimRegistry, ClaimRow


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "swarm.db"


def test_claim_is_exclusive(db_path: Path) -> None:
    # Two claimants (fresh connections) racing on one slug: exactly one wins.
    first = ClaimRegistry(db_path, owner="host-a:1")
    second = ClaimRegistry(db_path, owner="host-b:2")
    assert first.claim("neurips-hack-2026", "NeurIPS Hack 2026", 1) is True
    assert second.claim("neurips-hack-2026", "NeurIPS Hack 2026", 1) is False
    # Exactly one row exists, still owned by the first claimant.
    rows = second.results()
    assert len(rows) == 1
    assert rows[0].owner == "host-a:1"
    assert rows[0].status == "claimed"


def test_claim_succeeds_for_distinct_slugs(db_path: Path) -> None:
    registry = ClaimRegistry(db_path, owner="host-a:1")
    assert registry.claim("event-a", "Event A", 1) is True
    assert registry.claim("event-b", "Event B", 2) is True


def test_record_result_visible(db_path: Path) -> None:
    registry = ClaimRegistry(db_path, owner="host-a:1")
    registry.claim("neurips-hack-2026", "NeurIPS Hack 2026", 1)
    registry.record_result(
        "neurips-hack-2026",
        BuildStatus.SUCCESS,
        artifact_path=Path("builds/neurips-hack-2026"),
        test_summary="18 passed",
        error=None,
        attempts_used=2,
    )
    rows = ClaimRegistry(db_path, owner="host-b:2").results()
    assert len(rows) == 1
    assert rows[0] == ClaimRow(
        event_slug="neurips-hack-2026",
        event_name="NeurIPS Hack 2026",
        rank=1,
        owner="host-a:1",
        claimed_at=rows[0].claimed_at,
        status="success",
        artifact_path="builds/neurips-hack-2026",
        test_summary="18 passed",
        error=None,
        attempts_used=2,
    )
    assert rows[0].status == BuildStatus.SUCCESS.value


def test_record_result_visible_after_failure(db_path: Path) -> None:
    registry = ClaimRegistry(db_path, owner="host-a:1")
    registry.claim("climatehack-q4", "ClimateHack Q4", 2)
    registry.record_result(
        "climatehack-q4",
        BuildStatus.BUDGET_EXHAUSTED,
        artifact_path=None,
        test_summary=None,
        error="budget exhausted after 5 attempts",
        attempts_used=5,
    )
    (row,) = registry.results()
    assert row.status == BuildStatus.BUDGET_EXHAUSTED.value
    assert row.artifact_path is None
    assert row.error == "budget exhausted after 5 attempts"
    assert row.attempts_used == 5


def test_result_rejected_for_non_owner(db_path: Path) -> None:
    ClaimRegistry(db_path, owner="host-a:1").claim("neurips-hack-2026", "NeurIPS Hack 2026", 1)
    outsider = ClaimRegistry(db_path, owner="host-b:2")
    with pytest.raises(ValueError, match="no claim on 'neurips-hack-2026' owned by 'host-b:2'"):
        outsider.record_result(
            "neurips-hack-2026",
            BuildStatus.SUCCESS,
            artifact_path=None,
            test_summary=None,
            error=None,
            attempts_used=1,
        )
    # The owner's claim and state are untouched by the rejected write.
    (row,) = outsider.results()
    assert row.owner == "host-a:1"
    assert row.status == "claimed"


def test_record_result_rejected_for_unclaimed_event(db_path: Path) -> None:
    registry = ClaimRegistry(db_path, owner="host-a:1")
    with pytest.raises(ValueError, match="no claim on 'ghost-event'"):
        registry.record_result(
            "ghost-event",
            BuildStatus.SUCCESS,
            artifact_path=None,
            test_summary=None,
            error=None,
            attempts_used=1,
        )


def test_release_returns_unfinished_claim_to_pool(db_path: Path) -> None:
    owner = ClaimRegistry(db_path, owner="host-a:1")
    owner.claim("web3-jam", "Web3 Jam", 3)
    owner.release("web3-jam")
    assert owner.pending() == []
    # The slug is claimable again, by either claimant.
    assert owner.claim("web3-jam", "Web3 Jam", 3) is True
    assert ClaimRegistry(db_path, owner="host-b:2").claim("web3-jam", "Web3 Jam", 3) is False


def test_release_ignores_terminal_results(db_path: Path) -> None:
    registry = ClaimRegistry(db_path, owner="host-a:1")
    registry.claim("web3-jam", "Web3 Jam", 3)
    registry.record_result(
        "web3-jam",
        BuildStatus.SUCCESS,
        artifact_path=Path("builds/web3-jam"),
        test_summary="7 passed",
        error=None,
        attempts_used=1,
    )
    registry.release("web3-jam")
    assert registry.pending() == []
    assert len(registry.results()) == 1
    assert registry.results()[0].status == "success"


def test_pending_lists_only_unfinished_claims(db_path: Path) -> None:
    registry = ClaimRegistry(db_path, owner="host-a:1")
    registry.claim("event-a", "Event A", 1)
    registry.claim("event-b", "Event B", 2)
    registry.record_result(
        "event-a",
        BuildStatus.SUCCESS,
        artifact_path=None,
        test_summary=None,
        error=None,
        attempts_used=1,
    )
    assert registry.pending() == ["event-b"]


def test_default_owner_is_hostname_and_pid(db_path: Path) -> None:
    registry = ClaimRegistry(db_path)
    assert registry.owner == f"{socket.gethostname()}:{os.getpid()}"


def test_injectable_clock_stamps_claims(db_path: Path) -> None:
    ticks = iter([100.0, 200.0])
    registry = ClaimRegistry(db_path, owner="host-a:1", clock=lambda: next(ticks))
    registry.claim("event-a", "Event A", 1)
    registry.claim("event-b", "Event B", 2)
    assert [row.claimed_at for row in registry.results()] == [100.0, 200.0]
