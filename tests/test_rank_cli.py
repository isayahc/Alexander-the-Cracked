"""Tests for the `alexander rank` command (no network, no live feeds)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from alexander.cli import cli
from alexander.discovery.models import HackathonEvent

PROFILE_YAML = """\
interests:
  - ai
deadline_window_days: 30
preferred_locations:
  - Online
"""


@pytest.fixture(name="profile_file")
def profile_file_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(PROFILE_YAML, encoding="utf-8")
    return path


def stub_discover(events: list[HackathonEvent]) -> object:
    """Patch alexander.cli.discover_events (cli.py binds it by name)."""

    def fake_discover(use_cache: bool = True) -> list[HackathonEvent]:
        return events

    return fake_discover


def make_event(**overrides: object) -> HackathonEvent:
    defaults: dict = {
        "name": "Test Hack",
        "url": "https://test-hack.example.com",
        "source": "devpost",
    }
    defaults.update(overrides)
    return HackathonEvent(**defaults)


def test_rank_requires_a_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # no profile.yaml anywhere resolvable
    result = CliRunner().invoke(cli, ["rank"])
    assert result.exit_code != 0
    assert "No profile found" in result.output


def test_rank_prints_ranked_table(
    profile_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 10, 30, tzinfo=UTC)
    events = [
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
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover(events))

    result = CliRunner().invoke(cli, ["rank", "--profile", str(profile_file)])
    assert result.exit_code == 0, result.output
    lines = result.output.strip().splitlines()
    assert lines[0].startswith("Rank")
    assert "AI Hackathon" in lines[1]  # top rank
    assert "Web Jam" in lines[2]
    assert "Matches interest: ai" in result.output


def test_rank_json_output_is_machine_readable(
    profile_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 10, 30, tzinfo=UTC)
    events = [
        make_event(
            name="AI Hackathon",
            url="https://ai.example.com",
            deadline=now + timedelta(days=3),
            themes=["AI"],
        )
    ]
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover(events))

    result = CliRunner().invoke(cli, ["rank", "--profile", str(profile_file), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload[0]["rank"] == 1
    assert payload[0]["event"]["name"] == "AI Hackathon"
    assert payload[0]["reasons"]


def test_rank_empty_discovery_shows_actionable_message(
    profile_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover([]))
    result = CliRunner().invoke(cli, ["rank", "--profile", str(profile_file)])
    assert result.exit_code == 0, result.output
    assert "No upcoming events" in result.output


def test_rank_invalid_profile_fails_cleanly(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- not\n- a mapping\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["rank", "--profile", str(bad)])
    assert result.exit_code != 0


def test_shipped_example_profile_loads() -> None:
    from alexander.ranking import load_profile, resolve_profile_path

    resolved = resolve_profile_path()
    assert resolved is not None  # repo root ships profile.yaml
    profile = load_profile(resolved)
    assert profile.deadline_window_days > 0
