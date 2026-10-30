"""Discovery subpackage: fetch, parse, normalize, and dedupe hackathon feeds."""

from alexander.discovery.cache import ResponseCache
from alexander.discovery.devpost import fetch_devpost, parse_devpost
from alexander.discovery.discover import discover_events
from alexander.discovery.hackclub import fetch_hackclub, parse_hackclub
from alexander.discovery.models import HackathonEvent
from alexander.discovery.normalize import dedupe, normalize_name, normalize_url

__all__ = [
    "HackathonEvent",
    "ResponseCache",
    "dedupe",
    "discover_events",
    "fetch_devpost",
    "fetch_hackclub",
    "normalize_name",
    "normalize_url",
    "parse_devpost",
    "parse_hackclub",
]
