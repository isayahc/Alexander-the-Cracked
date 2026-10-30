"""Normalization and dedupe across discovery sources.

Two events collapse into one when they share the same normalized URL, or
share a very similar normalized name AND their date ranges overlap. When a
group collapses we keep the event with more optional fields filled.
"""

import re
from datetime import datetime

from alexander.discovery.models import HackathonEvent

_URL_STRIP_RE = re.compile(r"^(https?://)?(www\.)?")
_NAME_KEEP_RE = re.compile(r"[a-z0-9]+")


def normalize_url(url: str) -> str:
    """Reduce a URL to a comparable form: no scheme, www, query, fragment, or trailing slash."""
    return _URL_STRIP_RE.sub("", url.strip().lower()).split("?", 1)[0].split("#", 1)[0].rstrip("/")


def normalize_name(name: str) -> str:
    """Reduce an event name to lowercase alphanumeric tokens for fuzzy comparison."""
    return " ".join(_NAME_KEEP_RE.findall(name.lower()))


def _date_range(event: HackathonEvent) -> tuple[datetime, datetime] | None:
    """Return (start, end) for overlap checks, or None when the event has no dates."""
    start = event.starts_at or event.deadline
    end = event.ends_at or event.deadline
    if start is None or end is None:
        return None
    return min(start, end), max(start, end)


def _dates_overlap(a: HackathonEvent, b: HackathonEvent) -> bool:
    """True when the events' date ranges overlap, or when either lacks dates."""
    range_a, range_b = _date_range(a), _date_range(b)
    if range_a is None or range_b is None:
        return True
    return max(range_a[0], range_b[0]) <= min(range_a[1], range_b[1])


def _is_duplicate(a: HackathonEvent, b: HackathonEvent) -> bool:
    if normalize_url(a.url) == normalize_url(b.url):
        return True
    if normalize_name(a.name) != normalize_name(b.name):
        return False
    return _dates_overlap(a, b)


def _winner(a: HackathonEvent, b: HackathonEvent) -> HackathonEvent:
    """Pick the survivor of a duplicate pair: more filled fields, then first seen."""
    count_a, count_b = a.filled_field_count, b.filled_field_count
    if count_b > count_a:
        return b
    return a


def dedupe(events: list[HackathonEvent]) -> list[HackathonEvent]:
    """Collapse duplicate events across sources, preserving first-seen order."""
    kept: list[HackathonEvent] = []
    for event in events:
        match = next((existing for existing in kept if _is_duplicate(existing, event)), None)
        if match is None:
            kept.append(event)
        else:
            merged = _winner(match, event)
            kept[kept.index(match)] = merged
    return kept
