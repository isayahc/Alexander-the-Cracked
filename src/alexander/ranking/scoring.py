"""Pure scoring logic: event × profile → score plus human-readable reasons.

Design notes (also surfaced in the README):

- **Past deadlines are excluded** from ranked output entirely — a deadline in
  the past cannot be entered, so showing it is noise. ``rank_events`` filters
  them and says so.
- A **missing prize is neutral** (0.5 of the prize component): it neither
  boosts nor buries an event.
- A **missing deadline is neutral** too (0.5 of the deadline component).
- Ties break deterministically: score desc, then deadline asc (missing
  deadline last), then name.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from alexander.discovery.models import HackathonEvent
from alexander.ranking.profile import InterestProfile

# Neutral fraction credited to a component when its data is absent.
NEUTRAL_FRACTION = 0.5

# Prize reference (USD) used to normalize prize size when the profile does
# not set ``preferred_prize_min``.
DEFAULT_PRIZE_REFERENCE = 10_000

_PRIZE_PATTERN = re.compile(
    r"""
    (?P<value>\d+(?:,\d{3})*(?:\.\d+)?)\s*
    (?P<suffix>[kKmM])?
    """,
    re.VERBOSE,
)

_SUFFIX_MULTIPLIER = {"k": 1_000, "m": 1_000_000}


def parse_prize_amount(prize: str | None) -> int | None:
    """Parse a human prize string to USD, or None when unparseable.

    Handles ``$50,000``, ``50000``, ``$1.5K``, ``$2M``, and ranges like
    ``$1,000 - $5,000`` (returns the largest amount — the realistic
    headline figure). Anything without a number returns None.
    """
    if prize is None:
        return None
    amounts: list[int] = []
    for match in _PRIZE_PATTERN.finditer(prize):
        value = float(match.group("value").replace(",", ""))
        suffix = match.group("suffix")
        if suffix:
            value *= _SUFFIX_MULTIPLIER[suffix.lower()]
        amounts.append(int(value))
    return max(amounts) if amounts else None


def theme_fraction(event: HackathonEvent, profile: InterestProfile) -> float:
    """Fraction of interest weight satisfied by event name + themes (0..1)."""
    total_weight = sum(interest.weight for interest in profile.interests)
    if total_weight == 0:
        return 0.0
    haystack = " ".join([event.name, *event.themes]).lower()
    matched = sum(
        interest.weight
        for interest in profile.interests
        if interest.keyword.lower() in haystack
    )
    return matched / total_weight


def deadline_fraction(
    event: HackathonEvent, profile: InterestProfile, now: datetime
) -> float:
    """The sooner the deadline, the higher the fraction (0..1).

    Urgent deadlines (about to close) approach 1.0 and decay linearly to 0.0
    at the edge of ``deadline_window_days``. Missing deadlines are neutral.
    """
    if event.deadline is None:
        return NEUTRAL_FRACTION
    remaining = (event.deadline - now).total_seconds()
    if remaining <= 0:
        return 0.0
    window_seconds = profile.deadline_window_days * 24 * 60 * 60
    return max(0.0, 1.0 - remaining / window_seconds)


def prize_fraction(event: HackathonEvent, profile: InterestProfile) -> float:
    """Larger prize scores higher, capped at the reference amount (0..1)."""
    prize = parse_prize_amount(event.prize_amount)
    if prize is None:
        return NEUTRAL_FRACTION
    reference = profile.preferred_prize_min or DEFAULT_PRIZE_REFERENCE
    return min(1.0, prize / reference)


def location_fraction(event: HackathonEvent, profile: InterestProfile) -> float:
    """1.0 when the event location matches a preferred one, else 0.0.

    Matching is a case-insensitive substring check in either direction so
    ``Online`` matches ``Online + San Francisco`` and ``Virtual``.
    """
    if event.location is None:
        return 0.0
    location = event.location.lower()
    for preferred in profile.preferred_locations:
        needle = preferred.lower()
        if needle in location or location in needle:
            return 1.0
    return 0.0


@dataclass(frozen=True)
class RankedEvent:
    """A scored event plus the reasons behind its ranking decision."""

    event: HackathonEvent
    score: float
    reasons: list[str]


def score(
    event: HackathonEvent, profile: InterestProfile, *, now: datetime | None = None
) -> RankedEvent:
    """Score one event against the profile; never raises on missing data."""
    current = now or datetime.now(UTC)
    w = profile.weights

    components: list[tuple[float, float, str | None]] = [
        (w.theme, theme_fraction(event, profile), _theme_reason(event, profile)),
        (
            w.deadline,
            deadline_fraction(event, profile, current),
            _deadline_reason(event, profile, current),
        ),
        (w.prize, prize_fraction(event, profile), _prize_reason(event)),
        (w.location, location_fraction(event, profile), _location_reason(event, profile)),
    ]
    total = sum(weight * fraction for weight, fraction, _ in components)
    reasons = [reason for _, fraction, reason in components if fraction > 0 and reason]
    return RankedEvent(event=event, score=round(total, 4), reasons=reasons)


def _theme_reason(event: HackathonEvent, profile: InterestProfile) -> str | None:
    haystack = " ".join([event.name, *event.themes]).lower()
    matched = [
        interest.keyword
        for interest in profile.interests
        if interest.keyword.lower() in haystack
    ]
    if not matched:
        return None
    return f"Matches interest{'s' if len(matched) > 1 else ''}: {', '.join(matched)}"


def _deadline_reason(
    event: HackathonEvent, profile: InterestProfile, now: datetime
) -> str | None:
    if event.deadline is None:
        return "No deadline listed"
    days = (event.deadline - now).total_seconds() / (24 * 60 * 60)
    if days <= 0:
        return None
    if days <= profile.deadline_window_days:
        return f"Deadline in {max(days, 1):.0f} day(s)"
    return None


def _prize_reason(event: HackathonEvent) -> str | None:
    prize = parse_prize_amount(event.prize_amount)
    if prize is None:
        return None if event.prize_amount is None else "Prize format unrecognized"
    return f"Prize {event.prize_amount}"


def _location_reason(event: HackathonEvent, profile: InterestProfile) -> str | None:
    if location_fraction(event, profile) > 0:
        return f"Location preference: {event.location}"
    return None
