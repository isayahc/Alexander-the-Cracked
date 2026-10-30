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
    """Fetch one feed through the cache when available and parse it.

    On a miss, the fetch happens under a per-key interprocess lock with a
    re-check, so N concurrent processes sharing the cache cause exactly one
    HTTP fetch per URL; the rest pick up the fresh entry.
    """
    if cache is None:
        return parse(http_get_json(url))
    payload = cache.load(url)
    if payload is None:
        with cache.locked(url):
            # Re-check: another process may have fetched while we waited.
            payload = cache.load(url)
            if payload is None:
                payload = http_get_json(url)
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
