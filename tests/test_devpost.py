"""Tests for Devpost parsing against recorded fixtures (no network)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alexander.discovery.devpost import (
    parse_devpost,
    parse_devpost_event,
    parse_period_dates,
    strip_html,
)

FIXTURE = Path(__file__).parent / "fixtures" / "devpost_hackathons.json"


@pytest.fixture(name="devpost_payload")
def devpost_payload_fixture() -> dict:
    return json.loads(FIXTURE.read_text())


def test_fixture_parses_into_events(devpost_payload: dict) -> None:
    events = parse_devpost(devpost_payload)
    assert len(events) == len(devpost_payload["hackathons"])
    paypal = next(e for e in events if "PayPal" in e.name)
    assert paypal.source == "devpost"
    assert paypal.url == "https://paypalaihackathon.devpost.com/"


def test_deadline_is_period_end_date(devpost_payload: dict) -> None:
    paypal = next(e for e in parse_devpost(devpost_payload) if "PayPal" in e.name)
    assert paypal.raw_submission_period == "Oct 01 - Nov 12, 2026"
    assert paypal.deadline == datetime(2026, 11, 12, tzinfo=UTC)
    assert paypal.starts_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert paypal.ends_at == paypal.deadline


def test_prize_amount_is_html_free(devpost_payload: dict) -> None:
    paypal = next(e for e in parse_devpost(devpost_payload) if "PayPal" in e.name)
    assert paypal.prize_amount == "$67,500"


def test_themes_and_location_mapped(devpost_payload: dict) -> None:
    paypal = next(e for e in parse_devpost(devpost_payload) if "PayPal" in e.name)
    assert "Machine Learning/AI" in paypal.themes
    assert paypal.location == "Online"


def test_non_open_events_are_filtered(devpost_payload: dict) -> None:
    payload = dict(devpost_payload)
    payload["hackathons"] = [
        {**payload["hackathons"][0], "open_state": "closed"},
        *payload["hackathons"][1:],
    ]
    names = [e.name for e in parse_devpost(payload)]
    assert payload["hackathons"][0]["title"] not in names


def test_malformed_items_are_skipped_not_fatal() -> None:
    payload = {
        "hackathons": [
            None,
            {"open_state": "open", "title": "", "url": "https://x.devpost.com/"},
            {"open_state": "open", "title": "No URL"},
            {"open_state": "open", "title": 42, "url": "https://x.devpost.com/"},
            {"open_state": "open", "title": "Good One", "url": "https://good.devpost.com/"},
        ],
    }
    events = parse_devpost(payload)
    assert [e.name for e in events] == ["Good One"]


@pytest.mark.parametrize(
    ("display", "expected"),
    [
        ("Oct 01 - Nov 12, 2026", datetime(2026, 11, 12, tzinfo=UTC)),
        ("August 26 - September 5, 2026", datetime(2026, 9, 5, tzinfo=UTC)),
        ("Dec 30, 2026 - Jan 03, 2027", datetime(2027, 1, 3, tzinfo=UTC)),
        ("Nov 12", None),  # no year anywhere to borrow
        ("who knows", None),
        ("", None),
    ],
)
def test_parse_period_dates_best_effort(display: str, expected: datetime | None) -> None:
    _start, end = parse_period_dates(display)
    assert end == expected


def test_parse_period_dates_borrows_year_from_start() -> None:
    _start, end = parse_period_dates("Dec 30 - Jan 03, 2027")
    assert end == datetime(2027, 1, 3, tzinfo=UTC)


def test_strip_html() -> None:
    assert strip_html("$<span data-currency-value>67,500</span>") == "$67,500"
    assert strip_html("$<b>1,000&nbsp;</b>") == "$1,000"


def test_parse_devpost_event_returns_none_for_closed_or_weird() -> None:
    assert parse_devpost_event({"open_state": "draft"}) is None
    assert parse_devpost_event("not a dict") is None
