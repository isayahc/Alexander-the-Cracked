"""Ranking orchestration: filter, score, and sort events deterministically."""

from datetime import UTC, datetime

from alexander.discovery.models import HackathonEvent
from alexander.ranking.profile import InterestProfile
from alexander.ranking.scoring import RankedEvent, score

_MISSING_DEADLINE_SORT_KEY = datetime.max.replace(tzinfo=UTC)


def rank_events(
    events: list[HackathonEvent],
    profile: InterestProfile,
    *,
    now: datetime | None = None,
) -> list[RankedEvent]:
    """Rank events against the profile.

    Past-deadline events are excluded (documented in scoring.py): a deadline
    in the past cannot be entered. Sort order is deterministic — score desc,
    then deadline asc with missing deadlines last, then name.
    """
    current = now or datetime.now(UTC)
    upcoming = [
        event for event in events if event.deadline is None or event.deadline > current
    ]
    ranked = [score(event, profile, now=current) for event in upcoming]
    ranked.sort(
        key=lambda ranked_event: (
            -ranked_event.score,
            ranked_event.event.deadline or _MISSING_DEADLINE_SORT_KEY,
            ranked_event.event.name,
        )
    )
    return ranked
