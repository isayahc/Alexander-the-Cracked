"""Wire discovery, ranking, and the builder into one `alexander run`.

The pure planning logic lives here (slug derivation, brief construction,
event selection) so the CLI command stays a thin I/O shell and every rule is
unit-testable without network or agents.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from alexander.builder import HackathonBrief
from alexander.discovery.models import HackathonEvent
from alexander.ranking import RankedEvent

# Long event names should not create absurd directory names.
_SLUG_MAX_LEN = 60


def event_slug(event: HackathonEvent) -> str:
    """Filesystem-safe, deterministic, collision-resistant name for one event."""
    slug = re.sub(r"[^a-z0-9]+", "-", event.name.lower()).strip("-")
    base = (slug[:_SLUG_MAX_LEN].strip("-")) or "event"
    # Distinct events can share a name (dedupe() keys on URL, not name); the
    # URL digest keeps their build directories and claim rows apart.
    return f"{base}-{hashlib.sha256(event.url.encode()).hexdigest()[:8]}"


def build_brief(event: HackathonEvent) -> HackathonBrief:
    """Derive the hackathon brief the builder receives for a discovered event."""
    themes = ", ".join(event.themes) if event.themes else "none listed"
    description = (
        f"Build a small, working project suitable for submission to {event.name} "
        f"(themes: {themes}). Event page: {event.url}."
    )
    return HackathonBrief(
        event_name=event.name,
        description=description,
        themes=list(event.themes),
        deadline=event.deadline.date().isoformat() if event.deadline else None,
        prize=event.prize_amount,
    )


@dataclass(frozen=True)
class RunPlan:
    """What one run will build: the chosen event, its brief, and where it lands."""

    event: HackathonEvent
    brief: HackathonBrief
    out_dir: Path


def plan_run(
    ranked: list[RankedEvent],
    out_root: Path,
    *,
    top: int | None = None,
    pick: int | None = None,
) -> list[RunPlan]:
    """Choose which ranked events to build and lay out their plans.

    ``pick`` is the 1-based rank (the Rank column printed by ``alexander
    rank``); ``top`` takes the first N ranked events; the default is the
    single top-ranked event. Raises ValueError for an out-of-range pick,
    a non-positive top, or both given at once.
    """
    if pick is not None and top is not None:
        raise ValueError("choose either a single rank (pick) or a count (top), not both")
    if pick is not None:
        if not 1 <= pick <= len(ranked):
            raise ValueError(
                f"pick {pick} is out of range: only {len(ranked)} event(s) ranked"
            )
        chosen = [ranked[pick - 1]]
    elif top is not None:
        if top < 1:
            raise ValueError("top must be at least 1")
        chosen = ranked[:top]
    else:
        chosen = ranked[:1]
    return [
        RunPlan(
            event=entry.event,
            brief=build_brief(entry.event),
            out_dir=out_root / event_slug(entry.event),
        )
        for entry in chosen
    ]
