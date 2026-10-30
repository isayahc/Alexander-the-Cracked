"""Data models for the builder: briefs, budgets, statuses, and build results."""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class HackathonBrief(BaseModel):
    """Everything the builder needs to know about the event and what to build.

    Later stages feed this from discovery; for now callers construct it directly.
    """

    event_name: str = Field(min_length=1)
    description: str = Field(min_length=1, description="Short description of what to build")
    themes: list[str] = Field(default_factory=list)
    deadline: str | None = None
    prize: str | None = None


class BuildStatus(StrEnum):
    SUCCESS = "success"
    BUDGET_EXHAUSTED = "budget_exhausted"
    ERROR = "error"


class BuildResult(BaseModel):
    """Outcome of one builder run."""

    status: BuildStatus
    artifact_path: Path
    test_summary: str | None = None
    attempts_used: int = 0
    error: str | None = None


@dataclass(frozen=True)
class BuildBudgets:
    """Limits on one build run: agent attempts and wall-clock time."""

    max_attempts: int = 5
    wall_clock: timedelta = timedelta(minutes=30)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.wall_clock.total_seconds() <= 0:
            raise ValueError("wall_clock must be positive")
