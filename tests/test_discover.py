"""Tests for the discovery orchestration and CLI wiring (no network)."""

import json
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from alexander.cli import cli
from alexander.discovery import discover, discover_events
from alexander.discovery.cache import ResponseCache
from alexander.discovery.devpost import DEBPOST_API_URL, parse_devpost
from alexander.discovery.hackclub import HACKCLUB_API_URL, parse_hackclub
from alexander.discovery.models import HackathonEvent

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(name="feed_payloads")
def feed_payloads_fixture() -> dict[str, object]:
    return {
        DEBPOST_API_URL: json.loads((FIXTURES / "devpost_hackathons.json").read_text()),
        HACKCLUB_API_URL: json.loads((FIXTURES / "hackclub_upcoming.json").read_text()),
    }


def test_discover_events_parses_and_dedupes_both_feeds(
    feed_payloads: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache = ResponseCache(cache_dir=tmp_path)
    for url, payload in feed_payloads.items():
        cache.save(url, payload)

    fetched: list[str] = []

    def fake_http_get_json(url: str) -> object:
        fetched.append(url)
        return feed_payloads[url]

    monkeypatch.setattr(discover, "http_get_json", fake_http_get_json)

    events = discover_events(cache_dir=cache.cache_dir)

    assert fetched == []  # both feeds served from cache — no network
    assert all(isinstance(event, HackathonEvent) for event in events)
    assert {event.source for event in events} == {"devpost", "hackclub"}


def test_discover_events_fetches_and_caches_on_cache_miss(
    feed_payloads: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_http_get_json(url: str) -> object:
        return feed_payloads[url]

    monkeypatch.setattr(discover, "http_get_json", fake_http_get_json)

    events = discover_events(cache_dir=tmp_path)

    assert {event.source for event in events} == {"devpost", "hackclub"}
    # A second run must be served entirely from the cache written by the first.
    monkeypatch.setattr(
        discover, "http_get_json", lambda url: (_ for _ in ()).throw(AssertionError("network hit"))
    )
    assert discover_events(cache_dir=tmp_path) == events


def test_discover_events_survives_one_feed_down(
    feed_payloads: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def flaky_get_json(url: str) -> object:
        if DEBPOST_API_URL in url:
            raise httpx.ConnectError("feed down")
        return feed_payloads[url]

    monkeypatch.setattr(discover, "http_get_json", flaky_get_json)

    with caplog.at_level("WARNING"):
        events = discover_events(use_cache=False)

    assert {event.source for event in events} == {"hackclub"}
    assert DEBPOST_API_URL in caplog.text


def test_cli_discover_lists_events(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.loads((FIXTURES / "devpost_hackathons.json").read_text())
    events = parse_devpost(payload)

    monkeypatch.setattr("alexander.cli.discover_events", lambda **_: events)
    result = CliRunner().invoke(cli, ["discover"])

    assert result.exit_code == 0
    assert f"Found {len(events)} events:" in result.output
    assert "[devpost]" in result.output


def test_parse_hackclub_fixture_direct() -> None:
    payload = json.loads((FIXTURES / "hackclub_upcoming.json").read_text())
    assert len(parse_hackclub(payload)) == 8
