"""Devpost hackathon feed fetcher and parser.

Endpoint: GET https://devpost.com/api/hackathons — returns a JSON object with
a ``hackathons`` array of summary cards.
"""

import logging
import re
from datetime import UTC, datetime
from html import unescape
from typing import Any

from pydantic import ValidationError

from alexander.discovery.http import http_get_json
from alexander.discovery.models import HackathonEvent

DEBPOST_API_URL = "https://devpost.com/api/hackathons"

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
# Display strings look like "Oct 01 - Nov 12, 2026"; tolerate en dashes and
# a fully-qualified start date ("Dec 30, 2026 - Jan 03, 2027").
_PERIOD_RE = re.compile(r"^(.+?)\s*[-\u2013]\s*(.+)$")
_YEAR_RE = re.compile(r"\b(\d{4})\b")
_DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y")


def strip_html(text: str) -> str:
    """Remove tags and entities from a display string and collapse whitespace."""
    stripped = _TAG_RE.sub("", unescape(text))
    return " ".join(stripped.split())


def parse_period_dates(display: str) -> tuple[datetime | None, datetime | None]:
    """Best-effort parse of a Devpost submission-period display string.

    Returns (start, end) as UTC datetimes (Devpost dates carry no zone, so we
    pin UTC for consistency with Hack Club's ISO timestamps). Unparseable
    input yields (None, None) — a display string we cannot read must not
    crash a run.
    """
    match = _PERIOD_RE.match(display.strip())
    if not match:
        return None, None
    start_part, end_part = (part.strip() for part in match.groups())
    return _parse_date(start_part, display), _parse_date(end_part, display)


def _parse_date(date_part: str, full_display: str) -> datetime | None:
    """Parse one date in UTC, borrowing a year from the display string if it lacks one."""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(date_part, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    years = _YEAR_RE.findall(full_display)
    if len(years) == 1:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(f"{date_part}, {years[0]}", fmt).replace(
                    tzinfo=UTC
                )
            except ValueError:
                continue
    return None


def parse_devpost_event(item: Any) -> HackathonEvent | None:
    """Map one Devpost card to a HackathonEvent; None for open-state or unusable items."""
    if not isinstance(item, dict):
        return None
    if item.get("open_state") != "open":
        return None

    name = item.get("title")
    url = item.get("url")
    if not isinstance(name, str) or not name.strip() or not isinstance(url, str):
        logger.warning("Skipping malformed Devpost item: %r", item.get("id"))
        return None

    raw_period = item.get("submission_period_dates")
    start, end = parse_period_dates(raw_period) if isinstance(raw_period, str) else (None, None)

    prize = item.get("prize_amount")
    prize_amount = strip_html(prize) if isinstance(prize, str) else None
    themes = [
        theme["name"]
        for theme in item.get("themes") or []
        if isinstance(theme, dict) and isinstance(theme.get("name"), str)
    ]
    displayed_location = item.get("displayed_location") or {}
    location = displayed_location.get("location")
    location = location if isinstance(location, str) else None

    try:
        return HackathonEvent(
            name=name.strip(),
            url=url,
            source="devpost",
            deadline=end,
            prize_amount=prize_amount or None,
            themes=themes,
            location=location,
            starts_at=start,
            ends_at=end,
            raw_submission_period=raw_period if isinstance(raw_period, str) else None,
            raw=item,
        )
    except ValidationError as exc:
        logger.warning("Skipping invalid Devpost item %r: %s", item.get("id"), exc)
        return None


def parse_devpost(payload: object) -> list[HackathonEvent]:
    """Parse a full Devpost response body into events, skipping bad items."""
    items = payload.get("hackathons") if isinstance(payload, dict) else None
    events: list[HackathonEvent] = []
    for item in items or []:
        event = parse_devpost_event(item)
        if event is not None:
            events.append(event)
    return events


def fetch_devpost(url: str = DEBPOST_API_URL) -> list[HackathonEvent]:
    """Fetch (uncached) and parse the Devpost hackathon feed."""
    return parse_devpost(http_get_json(url))
