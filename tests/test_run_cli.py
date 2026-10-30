"""Tests for the `alexander run` command (no network, no live agents)."""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from alexander.builder import BuildResult, BuildStatus, HackathonBrief
from alexander.builder.models import BuildBudgets
from alexander.cli import cli
from alexander.discovery.models import HackathonEvent

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


class FakeBuilder:
    """Records build calls and returns scripted results (success by default)."""

    def __init__(self, results: list[BuildResult] | None = None) -> None:
        self.calls: list[tuple[HackathonBrief, Path, BuildBudgets]] = []
        self.results = results or []

    async def build(
        self, brief: HackathonBrief, out_dir: Path, budgets: BuildBudgets
    ) -> BuildResult:
        self.calls.append((brief, out_dir, budgets))
        if self.results:
            result = self.results.pop(0)
            return result.model_copy(update={"artifact_path": out_dir})
        return BuildResult(status=BuildStatus.SUCCESS, artifact_path=out_dir)


@pytest.fixture(name="profile_file")
def profile_file_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(PROFILE_YAML, encoding="utf-8")
    return path


@pytest.fixture(name="fake_builder")
def fake_builder_fixture(monkeypatch: pytest.MonkeyPatch) -> FakeBuilder:
    builder = FakeBuilder()
    monkeypatch.setattr("alexander.cli.create_builder", lambda backend=None: builder)
    return builder


def stub_discover(events: list[HackathonEvent]) -> object:
    """Patch alexander.cli.discover_events (cli.py binds it by name)."""

    def fake_discover(use_cache: bool = True) -> list[HackathonEvent]:
        return events

    return fake_discover


def url_digest(url: str) -> str:
    """The 8-hex URL digest event_slug appends (see pipeline.event_slug)."""
    return hashlib.sha256(url.encode()).hexdigest()[:8]


def ranked_events() -> list[HackathonEvent]:
    """Two events: 'AI Hackathon' ranks first, 'Web Jam' second."""
    now = datetime.now(UTC)
    return [
        make_event(
            name="AI Hackathon",
            url="https://ai.example.com",
            deadline=now + timedelta(days=3),
            prize_amount="$50,000",
            themes=["AI"],
            location="Online",
        ),
        make_event(
            name="Web Jam", url="https://web.example.com", deadline=now + timedelta(days=10)
        ),
    ]


def invoke_run(*args: str) -> object:
    return CliRunner().invoke(cli, ["run", *args])


def test_run_dry_run_stops_before_build(
    profile_file: Path, fake_builder: FakeBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover(ranked_events()))

    result = invoke_run("--profile", str(profile_file), "--dry-run")

    assert result.exit_code == 0, result.output
    assert fake_builder.calls == []
    assert "Would build" not in result.output
    assert "Dry run: no builds executed." in result.output
    assert "AI Hackathon" in result.output
    assert str(Path("builds") / "ai-hackathon") in result.output


def test_run_builds_the_top_event(
    profile_file: Path, fake_builder: FakeBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover(ranked_events()))

    result = invoke_run("--profile", str(profile_file))

    assert result.exit_code == 0, result.output
    assert len(fake_builder.calls) == 1
    brief, out_dir, budgets = fake_builder.calls[0]
    assert brief.event_name == "AI Hackathon"
    assert Path("builds") / f"ai-hackathon-{url_digest('https://ai.example.com')}" == out_dir
    # Budget defaults come from the builder: 5 attempts / 30 minutes.
    assert budgets.max_attempts == 5
    assert budgets.wall_clock == timedelta(minutes=30)
    assert "build success" in result.output


def test_run_respects_pick_top_and_budget_flags(
    profile_file: Path, fake_builder: FakeBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover(ranked_events()))

    result = invoke_run(
        "--profile", str(profile_file), "--pick", "2", "--max-attempts", "1", "--minutes", "10"
    )

    assert result.exit_code == 0, result.output
    assert len(fake_builder.calls) == 1
    brief, out_dir, budgets = fake_builder.calls[0]
    assert brief.event_name == "Web Jam"
    assert Path("builds") / f"web-jam-{url_digest('https://web.example.com')}" == out_dir
    assert budgets.max_attempts == 1
    assert budgets.wall_clock == timedelta(minutes=10)


def test_run_top_n_builds_in_rank_order(
    profile_file: Path, fake_builder: FakeBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover(ranked_events()))

    result = invoke_run("--profile", str(profile_file), "--top", "2")

    assert result.exit_code == 0, result.output
    assert [call[0].event_name for call in fake_builder.calls] == ["AI Hackathon", "Web Jam"]


def test_run_continues_after_a_failed_build(
    profile_file: Path, fake_builder: FakeBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = BuildResult(status=BuildStatus.BUDGET_EXHAUSTED, artifact_path=Path("builds/x"))
    fake_builder.results = [failure]
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover(ranked_events()))

    result = invoke_run("--profile", str(profile_file), "--top", "2")

    assert result.exit_code == 1
    assert len(fake_builder.calls) == 2  # second event still attempted
    assert "budget_exhausted" in result.output


def test_run_with_no_upcoming_events_is_a_clean_no_op(
    profile_file: Path, fake_builder: FakeBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover([]))

    result = invoke_run("--profile", str(profile_file))

    assert result.exit_code == 0, result.output
    assert fake_builder.calls == []
    assert "No upcoming events" in result.output


def test_run_rejects_out_of_range_pick(
    profile_file: Path, fake_builder: FakeBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover(ranked_events()))

    result = invoke_run("--profile", str(profile_file), "--pick", "9")

    assert result.exit_code != 0
    assert "out of range" in result.output
    assert fake_builder.calls == []


def test_run_rejects_pick_and_top_together(
    profile_file: Path, fake_builder: FakeBuilder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover(ranked_events()))

    result = invoke_run("--profile", str(profile_file), "--pick", "1", "--top", "1")

    assert result.exit_code != 0
    assert "not both" in result.output


def test_run_requires_a_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)  # no profile.yaml anywhere resolvable
    result = invoke_run()
    assert result.exit_code != 0
    assert "No profile found" in result.output
