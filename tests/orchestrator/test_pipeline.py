"""Pure orchestrator planning logic: slugs, briefs, and run plans."""

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alexander.discovery.models import HackathonEvent
from alexander.orchestrator import RunPlan, build_brief, event_slug, plan_run
from alexander.ranking import RankedEvent


def make_event(**overrides: object) -> HackathonEvent:
    defaults: dict = {
        "name": "Test Hack",
        "url": "https://test-hack.example.com",
        "source": "devpost",
    }
    defaults.update(overrides)
    return HackathonEvent(**defaults)


def url_digest(url: str) -> str:
    """The 8-hex URL digest event_slug appends."""
    return hashlib.sha256(url.encode()).hexdigest()[:8]


def ranked(*events: HackathonEvent, score: float = 10.0) -> list[RankedEvent]:
    return [RankedEvent(event=event, score=score, reasons=[]) for event in events]


def test_slug_lowercases_and_dashes_punctuation() -> None:
    url = "https://test-hack.example.com"
    assert event_slug(make_event(name="AI Hack 2026!", url=url)) == (
        f"ai-hack-2026-{url_digest(url)}"
    )


def test_slug_collapses_whitespace_and_caps_length() -> None:
    long_name = "A" * 100 + "   Extra"
    slug = event_slug(make_event(name=long_name))
    assert len(slug) <= 60 + 9  # name-derived part + '-' + 8-hex digest
    assert not slug.startswith("-")


def test_slug_falls_back_when_name_has_no_word_characters() -> None:
    url = "https://test-hack.example.com"
    assert event_slug(make_event(name="!!!", url=url)) == f"event-{url_digest(url)}"


def test_same_name_different_urls_get_different_slugs() -> None:
    # Two Devpost events named identically (dedupe keys on URL) must not share
    # a build directory or a claim row.
    first = event_slug(make_event(name="AI Hackathon 2026", url="https://a.example.com"))
    second = event_slug(make_event(name="AI Hackathon 2026", url="https://b.example.com"))
    assert first != second


def test_same_name_and_url_get_identical_slugs() -> None:
    url = "https://a.example.com"
    assert event_slug(make_event(name="AI Hackathon 2026", url=url)) == event_slug(
        make_event(name="AI Hackathon 2026", url=url)
    )


def test_slug_is_filesystem_safe_and_bounded() -> None:
    slug = event_slug(
        make_event(name="Weird / Name: *?\"<>| ~2026!", url="https://w.example.com/x?y=z")
    )
    assert re.fullmatch(r"[a-z0-9-]+-[0-9a-f]{8}", slug)
    assert len(slug) <= 70


def test_brief_maps_event_fields() -> None:
    event = make_event(
        name="Climate Hack",
        url="https://climate.example.com",
        themes=["climate", "sustainability"],
        deadline=datetime(2026, 11, 15, tzinfo=UTC),
        prize_amount="$10,000",
    )
    brief = build_brief(event)
    assert brief.event_name == "Climate Hack"
    assert brief.themes == ["climate", "sustainability"]
    assert brief.deadline == "2026-11-15"
    assert brief.prize == "$10,000"
    assert "Climate Hack" in brief.description
    assert "https://climate.example.com" in brief.description


def test_brief_tolerates_missing_fields() -> None:
    brief = build_brief(make_event())
    assert brief.deadline is None
    assert brief.prize is None
    assert brief.themes == []


def test_plan_defaults_to_the_top_event(tmp_path: Path) -> None:
    plans = plan_run(ranked(make_event(name="First"), make_event(name="Second")), tmp_path)
    assert len(plans) == 1
    assert plans[0].event.name == "First"
    assert plans[0].out_dir == tmp_path / f"first-{url_digest('https://test-hack.example.com')}"
    assert isinstance(plans[0], RunPlan)


def test_plan_top_n_and_pick(tmp_path: Path) -> None:
    events = ranked(make_event(name="First"), make_event(name="Second"), make_event(name="Third"))
    assert [p.event.name for p in plan_run(events, tmp_path, top=2)] == ["First", "Second"]
    picked = plan_run(events, tmp_path, pick=3)
    assert [p.event.name for p in picked] == ["Third"]
    assert picked[0].out_dir == tmp_path / f"third-{url_digest('https://test-hack.example.com')}"


def test_plan_rejects_bad_selections(tmp_path: Path) -> None:
    events = ranked(make_event(name="Only"))
    with pytest.raises(ValueError, match="only 1 event"):
        plan_run(events, tmp_path, pick=2)
    with pytest.raises(ValueError, match="at least 1"):
        plan_run(events, tmp_path, top=0)
    with pytest.raises(ValueError, match="not both"):
        plan_run(events, tmp_path, top=1, pick=1)
