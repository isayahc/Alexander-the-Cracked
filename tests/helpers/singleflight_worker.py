"""Subprocess worker for the interprocess single-flight contention test.

Fetches one URL through ``_fetch_cached_source`` with a fake
``http_get_json`` that appends a line to a shared counter file, so the
parent test can count real fetches across processes. Run directly:

    python singleflight_worker.py <cache_dir> <counter_file> <url> <payload_file>
"""

import json
import sys
from pathlib import Path

import alexander.discovery.discover as discover


def main() -> None:
    cache_dir, counter_file, url, payload_file = sys.argv[1:5]
    payload = json.loads(Path(payload_file).read_text())

    def fake_http_get_json(fetched_url: str) -> object:
        with open(counter_file, "a", encoding="utf-8") as counter:
            counter.write(f"fetch {fetched_url}\n")
        return payload

    discover.http_get_json = fake_http_get_json

    cache = discover.ResponseCache(cache_dir=Path(cache_dir))
    events = discover._fetch_cached_source(url, lambda parsed: parsed, cache)
    with open(counter_file, "a", encoding="utf-8") as counter:
        counter.write(f"parsed {len(events)}\n")


if __name__ == "__main__":
    main()
