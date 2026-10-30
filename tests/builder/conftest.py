"""Shared fixtures for the builder tests: a representative brief, no network."""

from pathlib import Path

import pytest

from alexander.builder import HackathonBrief

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def brief() -> HackathonBrief:
    return HackathonBrief(
        event_name="Testathon",
        description="A CLI that cheers on hackathon teams",
        themes=["fun"],
        deadline="2026-12-31",
        prize="bragging rights",
    )
