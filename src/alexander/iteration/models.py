"""Data models for the bounded build-evaluate-iterate loop.

Every recorded quantity here is *observed*, never self-reported: evaluations
come from probes that actually ran (a test subprocess, a file existence check),
and costs are counted attempts and measured wall-clock seconds. There is no
field an agent backend could fill with a claimed score — that is the
"cannot fabricate evaluation results" guarantee, enforced by shape.
"""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class StopReason(StrEnum):
    """Why the iteration loop stopped. Every stop is explicit."""

    PASS_CONDITION = "pass_condition"
    BUDGET_ITERATIONS = "budget_iterations"
    BUDGET_WALL_CLOCK = "budget_wall_clock"
    BUILDER_ERROR = "builder_error"


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class CheckRecord(BaseModel):
    """One evaluation check with the evidence that produced its verdict."""

    name: str = Field(min_length=1)
    status: CheckStatus
    evidence: str = Field(min_length=1, description="Output of the probe that decided this check.")


class IterationRecord(BaseModel):
    """What one build-evaluate round cost and produced."""

    iteration: int = Field(ge=1)
    passed: bool
    attempts_used: int = Field(ge=0)
    duration_s: float = Field(ge=0)
    test_summary: str | None = None
    checks: list[CheckRecord] = Field(default_factory=list)
    error: str | None = None
    restored_best: bool = Field(
        default=False,
        description="True when a failed round ended with the best-known result restored over it.",
    )


class IterationManifest(BaseModel):
    """Durable record of one bounded iterate run, written next to the build dir.

    Persisted as JSON; reload it for review with
    `IterationManifest.model_validate_json(path.read_text())`.
    """

    event_name: str = Field(min_length=1)
    out_dir: str
    best_known_dir: str | None = None
    best_iteration: int | None = None
    stop_reason: StopReason
    iterations: list[IterationRecord] = Field(default_factory=list)

    @property
    def total_attempts(self) -> int:
        return sum(record.attempts_used for record in self.iterations)

    @property
    def total_duration_s(self) -> float:
        return sum(record.duration_s for record in self.iterations)

    def best_record(self) -> IterationRecord | None:
        if self.best_iteration is None:
            return None
        for record in self.iterations:
            if record.iteration == self.best_iteration:
                return record
        return None


def best_known_dir_for(out_dir: Path) -> Path:
    """Sibling snapshot directory holding the best-known (last passing) result."""
    return out_dir.parent / f"{out_dir.name}-best-known"


def manifest_path_for(out_dir: Path) -> Path:
    """Sibling JSON file the iteration manifest is persisted to."""
    return out_dir.parent / f"{out_dir.name}-iterations.json"
