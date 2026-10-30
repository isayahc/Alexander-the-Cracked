"""Tests for the sourced requirement/rubric ledger (pure derivation, no network)."""

from datetime import UTC, datetime

from alexander.discovery.models import HackathonEvent
from alexander.ledger import (
    RequirementCategory,
    RequirementStatus,
    build_ledger,
    render_ledger_markdown,
)


def make_event(**overrides: object) -> HackathonEvent:
    defaults: dict = {
        "name": "Test Hack",
        "url": "https://test-hack.example.com",
        "source": "devpost",
    }
    defaults.update(overrides)
    return HackathonEvent(**defaults)


def test_full_event_yields_confirmed_sourced_entries() -> None:
    event = make_event(
        url="https://devpost.example.com",
        deadline=datetime(2026, 11, 15, tzinfo=UTC),
        prize_amount="$10,000",
        themes=["ai", "climate"],
        location="Online",
        raw_submission_period="Oct 01 - Nov 12, 2026",
    )
    ledger = build_ledger(event)

    by_category = {entry.category: entry for entry in ledger.entries}
    deadline = by_category[RequirementCategory.DEADLINE]
    assert deadline.status is RequirementStatus.CONFIRMED
    assert deadline.source_url == "https://devpost.example.com"
    assert deadline.source == "devpost"
    # Devpost display strings carry no timezone: the caveat must say so.
    assert deadline.detail is not None
    assert "timezone" in deadline.detail.lower()

    assert by_category[RequirementCategory.PRIZE].requirement == "Advertised prize: $10,000"
    assert by_category[RequirementCategory.THEME].requirement == "Themes: ai, climate"
    assert by_category[RequirementCategory.FORMAT].requirement == (
        "Participation format: online/virtual"
    )
    # Eligibility and rubric are never documented in these feeds: recorded as
    # unknowns with open questions, never as invented claims.
    assert by_category[RequirementCategory.ELIGIBILITY].status is RequirementStatus.UNKNOWN
    assert by_category[RequirementCategory.RUBRIC].status is RequirementStatus.UNKNOWN
    assert by_category[RequirementCategory.ELIGIBILITY].source_url is None


def test_missing_data_becomes_open_questions_not_assumptions() -> None:
    ledger = build_ledger(make_event())
    questions = " ".join(ledger.open_questions).lower()
    assert "deadline" in questions
    assert "prize" in questions
    assert "eligibility" in questions
    assert "judging" in questions
    categories = {entry.category for entry in ledger.entries}
    assert RequirementCategory.DEADLINE not in categories
    assert RequirementCategory.PRIZE not in categories


def test_cross_source_conflicts_surface_as_open_questions() -> None:
    event = make_event(
        deadline=datetime(2026, 11, 15, tzinfo=UTC),
        conflicts={
            "deadline": [
                "devpost: 2026-11-15T00:00:00+00:00",
                "hackclub: 2026-11-17T00:00:00+00:00",
            ]
        },
    )
    ledger = build_ledger(event)
    contradiction = [q for q in ledger.open_questions if "disagree on deadline" in q]
    assert len(contradiction) == 1
    assert "devpost: 2026-11-15T00:00:00+00:00" in contradiction[0]
    assert "hackclub: 2026-11-17T00:00:00+00:00" in contradiction[0]


def test_ledger_carries_multi_source_attribution() -> None:
    event = make_event(sources=["devpost", "hackclub"])
    assert build_ledger(event).sources == ["devpost", "hackclub"]


def test_markdown_render_includes_sourcing_and_open_questions() -> None:
    event = make_event(
        url="https://devpost.example.com",
        deadline=datetime(2026, 11, 15, tzinfo=UTC),
        prize_amount="$10,000",
        location="Online",
    )
    rendered = render_ledger_markdown(build_ledger(event))
    assert "# Requirement ledger — Test Hack" in rendered
    assert "https://devpost.example.com" in rendered
    assert "| [devpost](https://devpost.example.com) |" in rendered
    assert "## Open questions" in rendered
    assert rendered.endswith("\n")


def test_markdown_render_handles_a_fully_unknown_event() -> None:
    rendered = render_ledger_markdown(build_ledger(make_event()))
    assert "Open questions" in rendered
    assert "None — all requirements confirmed" not in rendered  # there are gaps
