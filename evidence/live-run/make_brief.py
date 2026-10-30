"""Write the live-run brief for the top-ranked event plus feed cache provenance.

Uses the same default response cache the CLI just populated, so the brief and
the live build see exactly the feed payload this run discovered. Run from the
repo root: python evidence/live-run/make_brief.py
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from alexander.discovery.cache import ResponseCache
from alexander.discovery.devpost import DEBPOST_API_URL
from alexander.discovery.discover import discover_events
from alexander.discovery.hackclub import HACKCLUB_API_URL
from alexander.orchestrator.pipeline import build_brief, event_slug
from alexander.ranking import load_profile, rank_events

OUT = Path("evidence/live-run")


def feed_provenance(cache: ResponseCache) -> dict:
    """Fetch stamp + payload digest per feed, from the live cache entries."""
    feeds = {}
    for url in (DEBPOST_API_URL, HACKCLUB_API_URL):
        entry = json.loads(cache._path_for(url).read_text(encoding="utf-8"))
        payload = entry.get("data")
        feeds[url] = {
            "fetched_at_epoch": entry.get("fetched_at"),
            "fetched_at_utc": datetime.fromtimestamp(
                entry["fetched_at"], tz=UTC
            ).isoformat(),
            "payload_sha256": hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest(),
        }
    return feeds


def main() -> None:
    events = discover_events(use_cache=True)
    ranked = rank_events(events, load_profile(Path("profile.yaml")))
    top = ranked[0]
    brief = build_brief(top.event)
    (OUT / "brief.json").write_text(brief.model_dump_json(indent=2), encoding="utf-8")
    cache = ResponseCache()
    provenance = {
        "traced_event_slug": event_slug(top.event),
        "ranked_upcoming": len(ranked),
        "feeds": feed_provenance(cache),
    }
    (OUT / "feed-provenance.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8"
    )
    print(f"brief for {brief.event_name}: {OUT / 'brief.json'}")
    print(f"slug: {event_slug(top.event)}")


if __name__ == "__main__":
    main()
