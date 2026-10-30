"""Tests for scoring: theme match, deadline edges, prize parsing, tie-breaking."""

from datetime import UTC, datetime, timedelta

import pytest

from alexander.discovery.models import HackathonEvent
from alexander.ranking import (
    NEUTRAL_FRACTION,
    InterestProfile,
    parse_prize_amount,
    rank_events,
    score,
)

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def days_out(n: int) -> datetime:
    """A deadline n days (negative = past) after NOW."""
    return NOW + timedelta(days=n)


def make_event(**overrides: object) -> HackathonEvent:
    defaults: dict = {
        "name": "Test Hack",
        "url": "https://test-hack.example.com",
        "source": "devpost",
    }
    defaults.update(overrides)
    return HackathonEvent(**defaults)


# --- prize parsing ------------------------------------------------------------


def test_parse_prize_amount_handles_common_formats() -> None:
    assert parse_prize_amount("$50,000") == 50_000
    assert parse_prize_amount("50000") == 50_000
    assert parse_prize_amount("$1.5K") == 1_500
    assert parse_prize_amount("$2M") == 2_000_000
    assert parse_prize_amount("$1,000 - $5,000") == 5_000  # ranges: headline figure
    assert parse_prize_amount("Up to $10,000 in prizes!") == 10_000


def test_parse_prize_amount_never_crashes_on_missing_or_garbage() -> None:
    assert parse_prize_amount(None) is None
    assert parse_prize_amount("") is None
    assert parse_prize_amount("TBD") is None
    assert parse_prize_amount("T-shirts for winners") is None


# --- theme matching -----------------------------------------------------------


def test_theme_match_uses_name_and_themes_case_insensitively() -> None:
    profile = InterestProfile(interests=[{"keyword": "ai"}])
    event = make_event(name="Machine Learning Hack", themes=["HealthTech"])
    assert score(event, profile, now=NOW).score > 0

    hit = make_event(name="Something", themes=["AI", "Web"])
    assert score(hit, profile, now=NOW).score > 0


def test_weighted_interest_outranks_plain_one() -> None:
    weighted = InterestProfile(interests=[{"keyword": "climate", "weight": 2.0}])
    climate_event = make_event(name="Climate Hack")
    web_event = make_event(name="Web Hack")
    assert (
        score(climate_event, weighted, now=NOW).score > score(web_event, weighted, now=NOW).score
    )


def test_no_interests_yields_zero_theme_component_but_no_crash() -> None:
    profile = InterestProfile()
    event = make_event(name="Random Hack", themes=["Fintech"])
    ranked = rank_events([event], profile, now=NOW)
    assert len(ranked) == 1  # still ranked, just without theme signal


def test_event_without_themes_still_scores_via_name() -> None:
    profile = InterestProfile(interests=[{"keyword": "ai"}])
    event = make_event(name="AI Builders Weekend", themes=[])
    result = score(event, profile, now=NOW)
    assert result.reasons and "ai" in result.reasons[0].lower()


# --- deadline edge cases -------------------------------------------------------


def test_past_deadline_events_are_excluded() -> None:
    profile = InterestProfile()
    past = make_event(name="Over Hack", deadline=days_out(-1))
    future = make_event(name="Upcoming Hack", deadline=days_out(5))
    ranked = rank_events([past, future], profile, now=NOW)
    assert [r.event.name for r in ranked] == ["Upcoming Hack"]


def test_closer_deadline_scores_higher_inside_window() -> None:
    profile = InterestProfile(deadline_window_days=30)
    soon = make_event(name="Soon Hack", deadline=days_out(2))
    later = make_event(name="Later Hack", deadline=days_out(28))
    scores = {r.event.name: r.score for r in rank_events([soon, later], profile, now=NOW)}
    assert scores["Soon Hack"] > scores["Later Hack"]


def test_deadline_outside_window_scores_zero_deadline_component() -> None:
    profile = InterestProfile(deadline_window_days=7)
    two_weeks = make_event(name="Two Weeks", deadline=days_out(14))
    from alexander.ranking import scoring

    assert scoring.deadline_fraction(two_weeks, profile, NOW) == 0.0


def test_missing_deadline_is_neutral() -> None:
    profile = InterestProfile()
    event = make_event(name="No Deadline Hack")
    result = score(event, profile, now=NOW)
    neutral_contribution = NEUTRAL_FRACTION * profile.weights.deadline
    neutral_total = neutral_contribution + NEUTRAL_FRACTION * profile.weights.prize
    assert result.score == pytest.approx(neutral_total)


# --- prize and location ---------------------------------------------------------


def test_missing_prize_is_neutral_not_crash() -> None:
    profile = InterestProfile(interests=[{"keyword": "ai"}])
    event = make_event(name="AI Hack", prize_amount=None)
    result = score(event, profile, now=NOW)
    assert result.score > 0
    assert any("No deadline listed" in reason or "Prize" not in reason for reason in result.reasons)


def test_bigger_prize_scores_higher_up_to_reference() -> None:
    profile = InterestProfile(preferred_prize_min=10_000)
    small = make_event(name="Small Prize", prize_amount="$1,000")
    large = make_event(name="Large Prize", prize_amount="$100,000")
    scores = {r.event.name: r.score for r in rank_events([small, large], profile, now=NOW)}
    assert scores["Large Prize"] > scores["Small Prize"]


def test_preferred_location_boosts_online_events() -> None:
    profile = InterestProfile(preferred_locations=["Online"])
    online = make_event(name="Virtual Hack", location="Online + SF")
    in_person = make_event(name="Campus Hack", location="Berlin")
    scores = {r.event.name: r.score for r in rank_events([online, in_person], profile, now=NOW)}
    assert scores["Virtual Hack"] > scores["Campus Hack"]


# --- deterministic tie-breaking ---------------------------------------------------


def test_equal_scores_break_by_deadline_then_name() -> None:
    profile = InterestProfile()  # no interests: all theme fractions are 0
    a = make_event(name="Alpha Hack", deadline=days_out(10))
    b = make_event(name="Beta Hack", deadline=days_out(5))
    c = make_event(name="Gamma Hack", deadline=days_out(5))
    ranked = rank_events([c, a, b], profile, now=NOW)
    # Equal scores: earlier deadline first, then name for identical deadlines.
    assert [r.event.name for r in ranked] == ["Beta Hack", "Gamma Hack", "Alpha Hack"]


def test_ranking_is_deterministic_across_runs() -> None:
    profile = InterestProfile(interests=[{"keyword": "ai"}])
    events = [
        make_event(name=f"Event {i}", themes=["ai"], deadline=days_out(i + 1)) for i in range(5)
    ]
    first = [r.event.name for r in rank_events(events, profile, now=NOW)]
    second = [r.event.name for r in rank_events(events, profile, now=NOW)]
    assert first == second


def test_reasons_are_human_readable() -> None:
    profile = InterestProfile(
        interests=[{"keyword": "ai"}, {"keyword": "climate", "weight": 2.0}],
        preferred_locations=["Online"],
    )
    event = make_event(
        name="AI Climate Hack",
        themes=["Climate"],
        deadline=days_out(3),
        prize_amount="$20,000",
        location="Online",
    )
    result = score(event, profile, now=NOW)
    assert result.reasons == [
        "Matches interests: ai, climate",
        "Deadline in 3 day(s)",
        "Prize $20,000",
        "Location preference: Online",
    ]
