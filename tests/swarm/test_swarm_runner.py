"""Direct tests for run_swarm's claim lifecycle (no network, no live agents)."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from alexander.builder import BuildResult, BuildStatus
from alexander.builder.models import BuildBudgets
from alexander.discovery.models import HackathonEvent
from alexander.orchestrator import RunPlan, build_brief, event_slug
from alexander.swarm import ClaimRegistry, run_swarm


def make_event(**overrides: object) -> HackathonEvent:
    defaults: dict = {
        "name": "Test Hack",
        "url": "https://test-hack.example.com",
        "source": "devpost",
        "deadline": datetime.now(UTC) + timedelta(days=3),
    }
    defaults.update(overrides)
    return HackathonEvent(**defaults)


def make_plans(events: list[HackathonEvent], tmp_path: Path) -> list[RunPlan]:
    return [
        RunPlan(event=event, brief=build_brief(event), out_dir=tmp_path / event_slug(event))
        for event in events
    ]


class CancellingBuilder:
    """A builder interrupted mid-build: CancelledError on every call."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def build(
        self, brief: object, out_dir: Path, budgets: BuildBudgets
    ) -> BuildResult:
        self.calls.append(brief.event_name)  # type: ignore[attr-defined]
        raise asyncio.CancelledError()


class FakeBuilder:
    """Builds everything successfully, recording the events it built."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def build(
        self, brief: object, out_dir: Path, budgets: BuildBudgets
    ) -> BuildResult:
        self.calls.append(brief.event_name)  # type: ignore[attr-defined]
        return BuildResult(status=BuildStatus.SUCCESS, artifact_path=out_dir)


async def test_cancelled_build_releases_its_claim(tmp_path: Path) -> None:
    """A cancelled worker must not strand its claim row as forever-pending."""
    registry = ClaimRegistry(tmp_path / "swarm.db")
    event = make_event(name="Cancelled Hack", url="https://cancelled.example.com")
    plans = make_plans([event], tmp_path)

    with pytest.raises(asyncio.CancelledError):
        await run_swarm(
            plans,
            registry=registry,
            builder=CancellingBuilder(),
            instances=1,
            budgets_factory=BuildBudgets,
        )

    # The claim was released, not stranded: nothing pending, nothing claimed.
    assert registry.results() == []
    assert registry.pending() == []

    # Because the claim was released, another worker (here: a later swarm run,
    # the way a recovered process would see it) can claim and build the event.
    success_builder = FakeBuilder()
    outcomes = await run_swarm(
        plans,
        registry=registry,
        builder=success_builder,
        instances=1,
        budgets_factory=BuildBudgets,
    )
    assert success_builder.calls == ["Cancelled Hack"]
    assert [outcome.result.status for outcome in outcomes] == [BuildStatus.SUCCESS]
    assert registry.pending() == []
