"""Tests for the `alexander ledger` command (no network)."""

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
"""


def make_event(**overrides: object) -> HackathonEvent:
    defaults: dict = {
        "name": "AI Hackathon",
        "url": "https://ai.example.com",
        "source": "devpost",
    }
    defaults.update(overrides)
    return HackathonEvent(**defaults)


@pytest.fixture(name="profile_file")
def profile_file_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "profile.yaml"
    path.write_text(PROFILE_YAML, encoding="utf-8")
    return path


def stub_discover(events: list[HackathonEvent]) -> object:
    def fake_discover(use_cache: bool = True) -> list[HackathonEvent]:
        return events

    return fake_discover


def ranked_events() -> list[HackathonEvent]:
    return [
        make_event(
            url="https://ai.example.com",
            deadline=datetime.now(UTC) + timedelta(days=3),
            prize_amount="$10,000",
            themes=["ai"],
            location="Online",
        ),
        make_event(name="Web Jam", url="https://web.example.com"),
    ]


def run_ledger(
    profile_file: Path, monkeypatch: pytest.MonkeyPatch, *args: str
) -> object:
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover(ranked_events()))
    return CliRunner().invoke(cli, ["ledger", "--profile", str(profile_file), *args])


def test_ledger_prints_sourced_markdown(
    profile_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_ledger(profile_file, monkeypatch)
    assert result.exit_code == 0
    assert "# Requirement ledger — AI Hackathon" in result.output
    assert "https://ai.example.com" in result.output
    # Open questions always surface (eligibility/judging are never in the feeds).
    assert "open question(s)" in result.output


def test_ledger_json_is_machine_readable(
    profile_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alexander.cli.discover_events", stub_discover(ranked_events()))
    # Click >= 8.2 keeps stderr separate: the open-questions warning never
    # pollutes the JSON on stdout.
    result = CliRunner().invoke(cli, ["ledger", "--profile", str(profile_file), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["event_name"] == "AI Hackathon"
    assert payload["entries"]
    assert payload["open_questions"]


def test_ledger_writes_to_out_file(
    profile_file: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "nested" / "ledger.md"
    result = run_ledger(profile_file, monkeypatch, "--out", str(out))
    assert result.exit_code == 0
    assert "Ledger written to" in result.output
    assert out.exists()
    assert "Requirement ledger" in out.read_text(encoding="utf-8")


def test_ledger_pick_selects_the_ranked_event(
    profile_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_ledger(profile_file, monkeypatch, "--pick", "2")
    assert result.exit_code == 0
    assert "# Requirement ledger — Web Jam" in result.output


def test_ledger_rejects_out_of_range_pick(
    profile_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = run_ledger(profile_file, monkeypatch, "--pick", "9")
    assert result.exit_code != 0
    assert "out of range" in result.output
