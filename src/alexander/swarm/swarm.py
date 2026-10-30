"""The concurrent swarm runner: N workers claim events, build, and record outcomes.

The coordinator discovers and ranks once (the caller passes ready plans), then
workers run as asyncio tasks inside this process — the expensive work is
external (coding-agent tasks), so one event loop drives all of them without
contention. Claim-before-build through the :class:`ClaimRegistry` is the only
coordination between workers, and between swarm processes.
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from alexander.builder import BuildBudgets, BuildResult, BuildStatus, ProjectBuilder
from alexander.orchestrator import RunPlan, event_slug
from alexander.swarm.registry import ClaimRegistry

# Shared across terminals on one machine (like the response cache), so two
# `alexander swarm` processes coordinate through the same claim registry.
DEFAULT_REGISTRY_PATH = Path.home() / ".cache" / "alexander" / "swarm.db"


@dataclass(frozen=True)
class SwarmOutcome:
    """What one swarm build did: which event, which worker, and the result."""

    rank: int
    plan: RunPlan
    worker_id: int
    result: BuildResult


class EventPool:
    """Hand build plans to workers in rank order, one claimant per plan.

    Handout is synchronous between awaits on the coordinator's single event
    loop, so a popped plan belongs to exactly one worker here; across swarm
    processes the registry's atomic claim is the arbiter.
    """

    def __init__(self, plans: Sequence[RunPlan]) -> None:
        self._ranked: list[tuple[int, RunPlan]] = list(enumerate(plans, start=1))
        self._cursor = 0

    def next_unclaimed(self) -> tuple[int, RunPlan] | None:
        """Return the next ``(rank, plan)``, or ``None`` once the pool is drained."""
        if self._cursor >= len(self._ranked):
            return None
        entry = self._ranked[self._cursor]
        self._cursor += 1
        return entry


async def run_swarm(
    plans: Sequence[RunPlan],
    *,
    registry: ClaimRegistry,
    builder: ProjectBuilder,
    instances: int,
    budgets_factory: Callable[[], BuildBudgets],
    on_result: Callable[[SwarmOutcome], None] | None = None,
) -> list[SwarmOutcome]:
    """Drive ``instances`` concurrent workers over the ranked plan list.

    Each worker claims an event before building it (the only coordination
    invariant), records the terminal :class:`BuildResult` on the claim row,
    and repeats until the pool is drained. Returns the outcomes sorted by
    rank. A build that raises is recorded as an ``ERROR`` result so sibling
    builds still land in the registry; the first such exception is re-raised
    after all workers join. Cancellation (or any ``BaseException``) releases
    the claim — the event stays buildable — and propagates to the caller.
    """
    if instances < 1:
        raise ValueError("instances must be at least 1")

    pool = EventPool(plans)
    outcomes: list[SwarmOutcome] = []
    build_errors: list[BaseException] = []

    async def worker(worker_id: int) -> None:
        while (entry := pool.next_unclaimed()) is not None:
            rank, plan = entry
            slug = event_slug(plan.event)
            if not registry.claim(slug, plan.event.name, rank):
                # Another swarm process won this event; it is not ours to build.
                continue
            try:
                result = await builder.build(plan.brief, plan.out_dir, budgets_factory())
            except Exception as exc:
                # Keep sibling builds running; the registry stays truthful.
                build_errors.append(exc)
                result = BuildResult(
                    status=BuildStatus.ERROR, artifact_path=plan.out_dir, error=str(exc)
                )
            except BaseException:
                # CancelledError / KeyboardInterrupt: no terminal result was
                # recorded, so release the claim instead of stranding the event
                # as a forever-pending row; the cancellation still propagates.
                registry.release(slug)
                raise
            registry.record_result(
                slug,
                result.status,
                result.artifact_path,
                result.test_summary,
                result.error,
                result.attempts_used,
            )
            outcome = SwarmOutcome(rank=rank, plan=plan, worker_id=worker_id, result=result)
            outcomes.append(outcome)
            if on_result is not None:
                on_result(outcome)

    # Appends to `outcomes` and `build_errors` happen synchronously between
    # awaits on this one event loop, so no locking is needed.
    worker_results = await asyncio.gather(
        *(worker(worker_id) for worker_id in range(1, instances + 1)),
        return_exceptions=True,
    )
    worker_crashes = [r for r in worker_results if isinstance(r, BaseException)]
    if worker_crashes:
        raise worker_crashes[0]
    if build_errors:
        raise build_errors[0]
    return sorted(outcomes, key=lambda outcome: outcome.rank)
