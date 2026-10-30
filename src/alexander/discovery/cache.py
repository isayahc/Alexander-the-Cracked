"""Simple on-disk JSON response cache with a time-to-live.

Keeps repeat CLI runs and CI from refetching the same public feed. Content
is cached verbatim per URL key; parsing always happens on read.
"""

import hashlib
import json
import time
from pathlib import Path

DEFAULT_TTL_SECONDS = 3600
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "alexander"


class ResponseCache:
    """JSON file cache: one file per URL key, expired by fetched_at + TTL."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.cache_dir = cache_dir if cache_dir is not None else DEFAULT_CACHE_DIR
        self.ttl_seconds = ttl_seconds

    def _path_for(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def load(self, key: str) -> object | None:
        """Return the cached payload for ``key``, or None if missing/expired/corrupt."""
        try:
            entry = json.loads(self._path_for(key).read_text())
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        fetched_at = entry.get("fetched_at", 0)
        if time.time() - fetched_at > self.ttl_seconds:
            return None
        return entry.get("data")

    def save(self, key: str, data: object) -> None:
        """Persist ``data`` under ``key``; a failed cache write is never fatal."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            entry = {"fetched_at": time.time(), "data": data}
            self._path_for(key).write_text(json.dumps(entry))
        except OSError:
            return
