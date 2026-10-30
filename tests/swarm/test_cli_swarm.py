"""Tests for the `alexander swarm` command (no network, no live agents)."""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from alexander.builder import BuildResult, BuildStatus, HackathonBrief
from alexander.builder.models import BuildBudgets
from alexander.cli import cli
from alexander.discovery.models import HackathonEvent
from alexander.swarm import ClaimRegistry

PROFILE_YAML = """\
interests:
  - ai
deadline_window_days: 30
preferred_locations:
  - Online
"""


def make_event(**overrides: object) -> HackathonEvent:
    defaults: dict = {
        "name": "Test Hack",
        "url": "https://test-hack.example.com",
        "source": "devpost",
    }
    defaults.update(overrides)
    return HackathonEvent(**defaults)


def ranked_events(count: int) -> list[HackathonEvent]:
    """`count` upcoming events named "Event 1".."Event N" in rank order."""
    now = datetime.now(UTC)
    return [
        make_event(
            name=f"Event {position}",
            url=f"https://event-{position}.example.com",
            deadline=now + timedelta(days=position),
        )
        for position in range(1, count + 1)
    ]


class FakeSwarmBuilder:
    """Records build calls with timing and returns scripted results."""

    def __init__(self, results: list[BuildResult] | None = None) -> None:
        self.calls: list[tuple[HackathonBrief, Path, BuildBudgets]] = []
        self.results = results or []
        self.intervals: dict[str, tuple[float, float]] = {}
        self.active = 0
        self.peak_concurrency = 0

    async def build(
        self, brief: HackathonBrief, out_dir: Path, budgets: BuildBudgets
    ) -> BuildResult:
        self.calls.append((brief, out_dir, budgets))
        started = time.monotonic()
        self.active += 1
        self.peak_concurrency = max(self.peak_concurrency, self.active)
        try:
            # Long enough that a concurrent builder overlaps, a serial one does not.
            await asyncio.sleep(0.05)
        finally:
            self.active -= 1
            self.intervals[brief.event_name] = (started, time.monotonic())
        if self.results:
            result = self.results.pop(0)
            return result.model_copy(update={"artifact_path": out_dir})
        return BuildResult(status=BuildStatus.SUCCESS, artifact_path=out_dir)


class ExplodingBuilder:
    """A builder whose backend raises instead of returning a result."""

    async def build(
        self, brief: HackathonBrief, out_dir: Path, budgets: BuildBudgets
    ) -> BuildResult:
        raise RuntimeError("backend exploded")


@pytest.fixture(name="profile_file")
def profile_file_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(PROFILE_YAML, encoding="utf-8")
    return path


@pytest.fixture(name="registry_path")
def registry_path_fixture(tmp_path: Path) -> Path:
    return tmp_path / "swarm.db"


def make_fake_builder(monkeypatch: pytest.MonkeyPatch) -> FakeSwarmBuilder:
    builder = FakeSwarmBuilder()
    monkeypatch.setattr("alexander.cli.create_builder", lambda backend=None: builder)
    return builder


def invoke_swarm(*args: str) -> object:
    return CliRunner().invoke(cli, ["swarm", *args])


def test_dry_run_claims_nothing(
    profile_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_path: Path,
) -> None:
    builder = make_fake_builder(monkeypatch)
    monkeypatch.setattr(
        "alexander.cli.discover_events", stub_discover(ranked_events(2))
    )

    result = invoke_swarm(
        "--profile", str(profile_file), "--registry", str(registry_path), "--dry-run"
    )

    assert result.exit_code == 0, result.output
    assert builder.calls == []
    registry = ClaimRegistry(registry_path)
    assert registry.results() == []
    assert "Event 1" in result.output
    assert "Dry run: nothing claimed, nothing built." in result.output


def test_no_duplicate_builds(
    profile_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_path: Path,
) -> None:
    builder = make_fake_builder(monkeypatch)
    monkeypatch.setattr(
        "alexander.cli.discover_events", stub_discover(ranked_events(5))
    )

    result = invoke_swarm(
        "--profile",
        str(profile_file),
        "--registry",
        str(registry_path),
        "--instances",
        "2",
        "--events",
        "5",
    )

    assert result.exit_code == 0, result.output
    built = [call[0].event_name for call in builder.calls]
    assert sorted(built) == [f"Event {position}" for position in range(1, 6)]
    assert len(built) == len(set(built))  # no event built twice
    registry = ClaimRegistry(registry_path)
    rows = registry.results()
    assert len(rows) == 5  # every event reached a terminal state
    assert {row.status for row in rows} == {BuildStatus.SUCCESS.value}
    assert all(row.owner == registry.owner for row in rows)
    assert registry.pending() == []


def test_workers_run_concurrently(
    profile_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_path: Path,
) -> None:
    builder = make_fake_builder(monkeypatch)
    monkeypatch.setattr(
        "alexander.cli.discover_events", stub_discover(ranked_events(5))
    )

    result = invoke_swarm(
        "--profile",
        str(profile_file),
        "--registry",
        str(registry_path),
        "--instances",
        "2",
        "--events",
        "5",
    )

    assert result.exit_code == 0, result.output
    # Serialized workers would peak at 1 and leave every interval disjoint.
    assert builder.peak_concurrency > 1
    by_start = sorted(builder.intervals.values())
    assert any(
        next_start < end
        for (_, end), (next_start, _) in zip(by_start, by_start[1:], strict=False)
    )


def test_swarm_exits_nonzero_when_a_build_fails(
    profile_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_path: Path,
) -> None:
    builder = make_fake_builder(monkeypatch)
    builder.results = [
        BuildResult(
            status=BuildStatus.BUDGET_EXHAUSTED,
            artifact_path=Path("builds/event-1"),
            error="budget exhausted after 5 attempts",
        )
    ]
    monkeypatch.setattr(
        "alexander.cli.discover_events", stub_discover(ranked_events(2))
    )

    result = invoke_swarm(
        "--profile",
        str(profile_file),
        "--registry",
        str(registry_path),
        "--instances",
        "1",
        "--events",
        "2",
    )

    assert result.exit_code == 1
    assert "budget_exhausted" in result.output
    registry = ClaimRegistry(registry_path)
    statuses = {row.event_slug: row.status for row in registry.results()}
    assert statuses == {
        "event-1": BuildStatus.BUDGET_EXHAUSTED.value,
        "event-2": BuildStatus.SUCCESS.value,
    }


def test_swarm_surfaces_builder_crashes(
    profile_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_path: Path,
) -> None:
    monkeypatch.setattr("alexander.cli.create_builder", lambda backend=None: ExplodingBuilder())
    monkeypatch.setattr(
        "alexander.cli.discover_events", stub_discover(ranked_events(2))
    )

    result = invoke_swarm(
        "--profile",
        str(profile_file),
        "--registry",
        str(registry_path),
        "--instances",
        "1",
        "--events",
        "2",
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    registry = ClaimRegistry(registry_path)
    rows = registry.results()
    assert [row.status for row in rows] == [BuildStatus.ERROR.value] * 2
    assert rows[0].error == "backend exploded"


def test_events_defaults_to_one_per_worker(
    profile_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_path: Path,
) -> None:
    builder = make_fake_builder(monkeypatch)
    monkeypatch.setattr(
        "alexander.cli.discover_events", stub_discover(ranked_events(5))
    )

    result = invoke_swarm(
        "--profile", str(profile_file), "--registry", str(registry_path), "--instances", "2"
    )

    assert result.exit_code == 0, result.output
    assert len(builder.calls) == 2


def test_swarm_with_no_upcoming_events_is_a_clean_no_op(
    profile_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    registry_path: Path,
) -> None:
    builder = make_fake_builder(monkeypatch)
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover([]))

    result = invoke_swarm("--profile", str(profile_file), "--registry", str(registry_path))

    assert result.exit_code == 0, result.output
    assert builder.calls == []
    assert "No upcoming events" in result.output


def stub_discover(events: list[HackathonEvent]) -> object:
    """Patch alexander.cli.discover_events (cli.py binds it by name)."""

    def fake_discover(use_cache: bool = True) -> list[HackathonEvent]:
        return events

    return fake_discover
