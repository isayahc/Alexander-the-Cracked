"""Tests for the on-disk response cache."""

import json
import time
from pathlib import Path

from alexander.discovery.cache import ResponseCache


def test_roundtrip(tmp_path: Path) -> None:
    cache = ResponseCache(cache_dir=tmp_path)
    cache.save("https://example.com/api", {"hackathons": [1, 2]})
    assert cache.load("https://example.com/api") == {"hackathons": [1, 2]}


def test_expired_entry_returns_none(tmp_path: Path) -> None:
    cache = ResponseCache(cache_dir=tmp_path, ttl_seconds=3600)
    cache.save("key", {"a": 1})
    # Backdate the fetched_at stamp beyond the TTL.
    cache_file = next(tmp_path.glob("*.json"))
    entry = json.loads(cache_file.read_text())
    entry["fetched_at"] = time.time() - 3601
    cache_file.write_text(json.dumps(entry))
    assert cache.load("key") is None


def test_missing_entry_returns_none(tmp_path: Path) -> None:
    cache = ResponseCache(cache_dir=tmp_path)
    assert cache.load("never-saved") is None


def test_corrupt_entry_returns_none(tmp_path: Path) -> None:
    cache = ResponseCache(cache_dir=tmp_path)
    cache_file = tmp_path / "junk.json"
    cache_file.write_text("{not json")
    entry = cache.load("junk")
    assert entry is None


def test_save_is_best_effort(tmp_path: Path) -> None:
    # A read-only cache dir must not raise on save.
    read_only = tmp_path / "ro"
    read_only.mkdir()
    read_only.chmod(0o555)
    cache = ResponseCache(cache_dir=read_only / "sub")
    cache.save("key", {"a": 1})
    assert cache.load("key") is None


def test_concurrent_save_atomic(tmp_path: Path) -> None:
    # Two threads racing on the same key must leave one parseable entry
    # whose data matches one of the writers' payloads.
    import threading

    cache = ResponseCache(cache_dir=tmp_path)
    payloads = [{"writer": "a", "i": i} for i in range(200)]
    payloads += [{"writer": "b", "i": i} for i in range(200)]

    def save_all(writer: str) -> None:
        for i in range(200):
            cache.save("key", {"writer": writer, "i": i})

    threads = [
        threading.Thread(target=save_all, args=("a",)),
        threading.Thread(target=save_all, args=("b",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    data = cache.load("key")
    assert data in payloads
    # No temp files left behind.
    assert not list(tmp_path.glob("*.tmp"))
