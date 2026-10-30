"""Tests for Hack Club parsing against recorded fixtures (no network)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alexander.discovery.hackclub import parse_hackclub, parse_hackclub_event

FIXTURE = Path(__file__).parent / "fixtures" / "hackclub_upcoming.json"


@pytest.fixture(name="hackclub_payload")
def hackclub_payload_fixture() -> list:
    return json.loads(FIXTURE.read_text())


def test_fixture_parses_into_events(hackclub_payload: list) -> None:
    events = parse_hackclub(hackclub_payload)
    assert len(events) == len(hackclub_payload)
    beacon = events[0]
    assert beacon.name == "Beacon Hacks"
    assert beacon.source == "hackclub"
    assert beacon.url == "https://beaconhacks.com"


def test_dates_and_location_mapped(hackclub_payload: list) -> None:
    beacon = parse_hackclub(hackclub_payload)[0]
    assert beacon.starts_at == datetime(2027, 1, 30, 16, 30, tzinfo=UTC)
    assert beacon.ends_at == datetime(2027, 1, 31, 7, 0, tzinfo=UTC)
    assert beacon.deadline == beacon.ends_at
    assert beacon.location == "Belmont, California, United States"


def test_virtual_event_location_is_online() -> None:
    event = parse_hackclub_event(
        {"name": "V Hack", "website": "https://vhack.example.com", "virtual": True}
    )
    assert event is not None
    assert event.location == "Online"


def test_missing_optional_fields_tolerated() -> None:
    event = parse_hackclub_event({"name": "Bare Event", "website": "https://bare.example.com"})
    assert event is not None
    assert event.deadline is None
    assert event.location is None
    assert event.prize_amount is None
    assert event.themes == []


def test_prize_and_theme_fields_read_when_present() -> None:
    event = parse_hackclub_event(
        {
            "name": "Fancy Hack",
            "website": "https://fancy.example.com",
            "prize_amount": "$5,000",
            "themes": ["AI", {"name": "Web"}],
        }
    )
    assert event is not None
    assert event.prize_amount == "$5,000"
    assert event.themes == ["AI", "Web"]


def test_malformed_items_are_skipped_not_fatal() -> None:
    payload = [
        None,
        {"name": "", "website": "https://x.example.com"},
        {"name": "No URL"},
        {"name": 42, "website": "https://x.example.com"},
        {"name": "Good Event", "website": "https://good.example.com"},
        {"start": "not a date", "end": None, "name": "Weird Dates", "website": "https://w.example.com"},
    ]
    events = parse_hackclub(payload)
    assert [e.name for e in events] == ["Good Event", "Weird Dates"]
    weird = events[1]
    assert weird.starts_at is None
    assert weird.ends_at is None


def test_parse_hackclub_event_rejects_non_dicts() -> None:
    assert parse_hackclub_event("not a dict") is None
