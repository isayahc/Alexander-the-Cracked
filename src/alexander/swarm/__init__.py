"""swarm subpackage: run many Alexander builds concurrently without collisions.

The claim registry (`ClaimRegistry`) is the only shared mutable state between
instances: claiming an event is an atomic test-and-set, and every terminal
build outcome is recorded back on the claim row. The runner (`run_swarm`)
drives N asyncio workers that claim an event before building it.
"""

from alexander.swarm.registry import ClaimRegistry, ClaimRow
from alexander.swarm.swarm import (
    DEFAULT_REGISTRY_PATH,
    EventPool,
    SwarmOutcome,
    run_swarm,
)

__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "ClaimRegistry",
    "ClaimRow",
    "EventPool",
    "SwarmOutcome",
    "run_swarm",
]
