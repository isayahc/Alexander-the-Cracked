"""Hack Club hackathon feed fetcher and parser.

Endpoint: GET https://hackathons.hackclub.com/api/events/upcoming — returns a
JSON array of upcoming events. Any output built on this data must credit Hack
Club (see README attribution section).

Field coverage varies per event, so every optional field is read defensively.
"""

import logging
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from alexander.discovery.http import http_get_json
from alexander.discovery.models import HackathonEvent

# Candidate keys for prize data, in case the feed gains them.
_PRIZE_KEYS = ("prize_amount", "prizes", "prize")

HACKCLUB_API_URL = "https://hackathons.hackclub.com/api/events/upcoming"

logger = logging.getLogger(__name__)



def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _first_str(item: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _join_location(item: dict[str, Any]) -> str | None:
    if item.get("virtual"):
        return "Online"
    parts = [
        str(item[key])
        for key in ("city", "state", "country")
        if isinstance(item.get(key), str) and item[key].strip()
    ]
    return ", ".join(parts) or None


def _read_themes(item: dict[str, Any]) -> list[str]:
    """Read theme strings from whatever shape the feed uses; tolerate missing data."""
    raw = item.get("themes")
    if not isinstance(raw, list):
        return []
    themes: list[str] = []
    for theme in raw:
        if isinstance(theme, str) and theme.strip():
            themes.append(theme.strip())
        elif (
            isinstance(theme, dict)
            and isinstance(theme.get("name"), str)
            and theme["name"].strip()
        ):
            themes.append(theme["name"].strip())
    return themes


def parse_hackclub_event(item: Any) -> HackathonEvent | None:
    """Map one Hack Club event to a HackathonEvent; None for unusable items."""
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    url = item.get("website")
    if not isinstance(name, str) or not name.strip() or not isinstance(url, str):
        logger.warning("Skipping malformed Hack Club item: %r", item.get("id"))
        return None

    starts_at = _parse_iso(item.get("start"))
    ends_at = _parse_iso(item.get("end"))

    try:
        return HackathonEvent(
            name=name.strip(),
            url=url,
            source="hackclub",
            deadline=ends_at,
            prize_amount=_first_str(item, _PRIZE_KEYS),
            themes=_read_themes(item),
            location=_join_location(item),
            starts_at=starts_at,
            ends_at=ends_at,
            raw=item,
        )
    except ValidationError as exc:
        logger.warning("Skipping invalid Hack Club item %r: %s", item.get("id"), exc)
        return None


def parse_hackclub(payload: object) -> list[HackathonEvent]:
    """Parse a full Hack Club response body into events, skipping bad items."""
    items = payload if isinstance(payload, list) else None
    events: list[HackathonEvent] = []
    for item in items or []:
        event = parse_hackclub_event(item)
        if event is not None:
            events.append(event)
    return events


def fetch_hackclub(url: str = HACKCLUB_API_URL) -> list[HackathonEvent]:
    """Fetch (uncached) and parse the Hack Club upcoming-events feed."""
    return parse_hackclub(http_get_json(url))
