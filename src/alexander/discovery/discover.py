"""Discovery orchestration: fetch both feeds (cached), parse, dedupe."""

import logging
from collections.abc import Callable
from pathlib import Path

import httpx

from alexander.discovery.cache import ResponseCache
from alexander.discovery.devpost import DEBPOST_API_URL, parse_devpost
from alexander.discovery.hackclub import HACKCLUB_API_URL, parse_hackclub
from alexander.discovery.http import http_get_json
from alexander.discovery.models import HackathonEvent
from alexander.discovery.normalize import dedupe

logger = logging.getLogger(__name__)


def _fetch_cached_source(
    url: str,
    parse: Callable[[object], list[HackathonEvent]],
    cache: ResponseCache | None,
) -> list[HackathonEvent]:
    """Fetch one feed through the cache when available and parse it."""
    payload = cache.load(url) if cache is not None else None
    if payload is None:
        payload = http_get_json(url)
        if cache is not None:
            cache.save(url, payload)
    return parse(payload)


def discover_events(
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> list[HackathonEvent]:
    """Run the full discovery pipeline and return deduplicated events.

    A failing source is logged and skipped so one down feed never blocks the
    other — discovery is best-effort by design.
    """
    cache = ResponseCache(cache_dir) if use_cache else None

    sources: list[tuple[str, Callable[[object], list[HackathonEvent]]]] = [
        (DEBPOST_API_URL, parse_devpost),
        (HACKCLUB_API_URL, parse_hackclub),
    ]
    events: list[HackathonEvent] = []
    for url, parse in sources:
        try:
            events.extend(_fetch_cached_source(url, parse, cache))
        except (httpx.HTTPError, ValueError):
            logger.warning("Failed to fetch or parse %s", url, exc_info=True)
    return dedupe(events)
