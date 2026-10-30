"""Tests for the shared HackathonEvent model."""

from datetime import UTC, datetime

from alexander.discovery.models import HackathonEvent


def make_event(**overrides: object) -> HackathonEvent:
    defaults: dict = {
        "name": "Test Hack",
        "url": "https://test-hack.example.com",
        "source": "devpost",
    }
    defaults.update(overrides)
    return HackathonEvent(**defaults)


def test_required_fields_only() -> None:
    event = make_event()
    assert event.name == "Test Hack"
    assert event.themes == []
    assert event.deadline is None
    assert event.filled_field_count == 0


def test_filled_field_counts_themes_and_dates() -> None:
    event = make_event(
        deadline=datetime(2026, 11, 12, tzinfo=UTC),
        prize_amount="$1,000",
        themes=["AI", "Web"],
        location="Online",
    )
    assert event.filled_field_count == 4


def test_raw_keeps_original_feed_item() -> None:
    raw = {"id": 31302, "open_state": "open"}
    event = make_event(raw=raw)
    assert event.raw["id"] == 31302
