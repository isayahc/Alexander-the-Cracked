"""Tests for name/URL normalization and cross-source dedupe."""

from datetime import UTC, datetime

from alexander.discovery.models import HackathonEvent
from alexander.discovery.normalize import dedupe, normalize_name, normalize_url


def make_event(**overrides: object) -> HackathonEvent:
    defaults: dict = {
        "name": "Test Hack",
        "url": "https://test-hack.example.com",
        "source": "devpost",
    }
    defaults.update(overrides)
    return HackathonEvent(**defaults)


def july(day: int) -> datetime:
    return datetime(2026, 7, day, tzinfo=UTC)


def test_normalize_url_strips_noise() -> None:
    assert (
        normalize_url("HTTPS://www.Test-Hack.example.com/?utm=x#top")
        == "test-hack.example.com"
    )
    assert normalize_url("https://a.devpost.com/") == normalize_url("http://a.devpost.com")


def test_normalize_name_ignores_case_and_punctuation() -> None:
    assert normalize_name("Kiroween 2026!") == normalize_name("kiroween 2026")


def test_dedupe_merges_same_url_different_names() -> None:
    a = make_event(name="Event A", url="https://same.example.com")
    b = make_event(name="Event B", source="hackclub", url="https://www.same.example.com/")
    assert dedupe([a, b]) == [a]


def test_dedupe_merges_same_name_with_overlapping_dates() -> None:
    a = make_event(
        name="Summer Hack", url="https://devpost.example.com", starts_at=july(1), ends_at=july(10)
    )
    b = make_event(
        name="summer hack",
        source="hackclub",
        url="https://hackclub.example.com",
        starts_at=july(5),
        ends_at=july(15),
    )
    assert dedupe([a, b]) == [a]


def test_dedupe_keeps_same_name_without_date_overlap() -> None:
    a = make_event(
        name="Winter Hack", url="https://a.example.com", starts_at=july(1), ends_at=july(5)
    )
    b = make_event(
        name="Winter Hack",
        source="hackclub",
        url="https://b.example.com",
        starts_at=july(20),
        ends_at=july(25),
    )
    assert dedupe([a, b]) == [a, b]


def test_dedupe_same_name_no_dates_falls_back_to_name_match() -> None:
    a = make_event(name="Mystery Hack", url="https://a.example.com")
    b = make_event(name="Mystery Hack!", source="hackclub", url="https://b.example.com")
    assert len(dedupe([a, b])) == 1


def test_dedupe_keeps_more_complete_event() -> None:
    bare = make_event(name="Rich Hack", url="https://r.example.com")
    rich = make_event(
        name="rich hack",
        source="hackclub",
        url="https://rich.example.com",
        deadline=july(10),
        prize_amount="$1,000",
        themes=["AI"],
        location="Online",
        starts_at=july(1),
        ends_at=july(10),
    )
    assert dedupe([bare, rich]) == [rich]


def test_dedupe_preserves_first_seen_order() -> None:
    a = make_event(name="Alpha", url="https://a.example.com")
    b = make_event(name="Beta", url="https://b.example.com")
    assert [e.name for e in dedupe([a, b])] == ["Alpha", "Beta"]


def test_dedupe_empty_input() -> None:
    assert dedupe([]) == []
