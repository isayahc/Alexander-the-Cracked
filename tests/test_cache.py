"""Tests for the on-disk response cache."""

import json
import time
from pathlib import Path

import pytest

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


# Untrusted shared state: any on-disk payload must degrade to a cache miss.
CORRUPT_ENTRIES = [
    [],
    "text",
    42,
    None,
    {"fetched_at": "yesterday", "data": {"a": 1}},
    {"fetched_at": None, "data": {"a": 1}},
]


@pytest.mark.parametrize("corrupt_entry", CORRUPT_ENTRIES)
def test_malformed_entry_is_a_miss_not_a_crash(
    tmp_path: Path, corrupt_entry: object
) -> None:
    cache = ResponseCache(cache_dir=tmp_path)
    (tmp_path / "junk.json").write_text(json.dumps(corrupt_entry))
    assert cache.load("junk") is None


def test_nan_timestamp_is_a_miss_not_stale_data(tmp_path: Path) -> None:
    # json.dumps refuses to emit NaN as bare text, so write the JSON literal by
    # hand: every comparison against NaN is false, which would serve this
    # entry forever without the isfinite check.
    cache = ResponseCache(cache_dir=tmp_path)
    (tmp_path / "junk.json").write_text('{"fetched_at": NaN, "data": {"a": 1}}')
    assert cache.load("junk") is None


def test_entry_without_data_key_is_a_miss(tmp_path: Path) -> None:
    cache = ResponseCache(cache_dir=tmp_path)
    (tmp_path / "junk.json").write_text(json.dumps({"fetched_at": time.time()}))
    assert cache.load("junk") is None


def test_bool_timestamp_is_a_miss(tmp_path: Path) -> None:
    # bool is an int subclass; a True/False stamp is corrupt, not a timestamp.
    cache = ResponseCache(cache_dir=tmp_path)
    (tmp_path / "junk.json").write_text(json.dumps({"fetched_at": True, "data": 1}))
    assert cache.load("junk") is None


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
