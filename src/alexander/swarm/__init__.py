"""swarm subpackage: run many Alexander builds concurrently without collisions.

The claim registry (`ClaimRegistry`) is the only shared mutable state between
instances: claiming an event is an atomic test-and-set, and every terminal
build outcome is recorded back on the claim row.
"""

from alexander.swarm.registry import ClaimRegistry, ClaimRow

__all__ = [
    "ClaimRegistry",
    "ClaimRow",
]
