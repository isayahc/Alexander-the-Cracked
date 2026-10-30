"""Manifest behavior: atomic writes, durable hits, loud corruption."""

import json

import pytest

from alexander.repos.manifest import ManifestCorruptError, RepoManifest, RepoRecord


def make_record(slug: str = "demo-event", **overrides) -> RepoRecord:
    defaults = {
        "slug": slug,
        "name": slug,
        "url": f"https://example.com/o/{slug}",
        "backend": "fixture",
    }
    return RepoRecord(**{**defaults, **overrides})


def test_roundtrip(tmp_path):
    manifest = RepoManifest(tmp_path / "manifest.json")
    assert manifest.get("demo-event") is None  # fresh: no record, no file

    manifest.put(make_record())

    reloaded = RepoManifest(tmp_path / "manifest.json")
    record = reloaded.get("demo-event")
    assert record is not None
    assert record.url == "https://example.com/o/demo-event"
    assert record.state == "created"


def test_second_slug_coexists(tmp_path):
    manifest = RepoManifest(tmp_path / "manifest.json")
    manifest.put(make_record("a"))
    manifest.put(make_record("b"))
    assert manifest.get("a") is not None
    assert manifest.get("b") is not None


def test_write_is_atomic_no_temp_litter(tmp_path):
    path = tmp_path / "nested" / "manifest.json"
    RepoManifest(path).put(make_record())
    leftovers = list(path.parent.glob("*.tmp"))
    assert leftovers == []
    payload = json.loads(path.read_text())
    assert payload["version"] == 1


def test_corrupt_manifest_is_loud(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{not json")
    with pytest.raises(ManifestCorruptError):
        RepoManifest(path).get("demo-event")


def test_mark_seeded_advances_state(tmp_path):
    manifest = RepoManifest(tmp_path / "manifest.json")
    record = make_record()
    manifest.put(record)
    manifest.put(record.mark_seeded())
    reloaded = RepoManifest(tmp_path / "manifest.json")
    assert reloaded.get("demo-event").state == "seeded"
    assert reloaded.get("demo-event").seeded_at is not None
