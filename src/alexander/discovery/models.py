"""Shared data model for discovered hackathon and competition events."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

EventSource = Literal["devpost", "hackclub"]

# Fields consulted when deciding which duplicate event survives dedupe.
_FILLED_FIELDS = ("deadline", "prize_amount", "location", "starts_at", "ends_at")

# Fields whose diverging values are recorded as cross-source conflicts on the
# canonical (merged) event instead of being silently dropped.
_CONFLICT_FIELDS = ("deadline", "prize_amount", "location")


class HackathonEvent(BaseModel):
    """A single hackathon or competition discovered from a public feed.

    All feed-specific fields are optional: feeds vary per event and the
    normalizer must tolerate missing data. ``raw`` keeps the original feed
    item so later stages (ranking, builder) can use fields we do not model.
    """

    name: str
    url: str
    source: EventSource
    deadline: datetime | None = None
    prize_amount: str | None = None
    themes: list[str] = Field(default_factory=list)
    location: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    raw_submission_period: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    # Canonical-event bookkeeping (filled by dedupe, not by the feeds):
    # every source that reported this event, and the diverging values each
    # source claimed for a field, so attribution and contradictions survive
    # merging instead of being dropped with the discarded duplicate.
    sources: list[EventSource] = Field(default_factory=list)
    conflicts: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _default_sources(self) -> "HackathonEvent":
        """Treat a bare feed item as attributed to its own source."""
        if not self.sources:
            self.sources = [self.source]
        return self

    @property
    def filled_field_count(self) -> int:
        """How many optional fields carry data — used to pick a dedupe winner."""
        count = sum(1 for name in _FILLED_FIELDS if getattr(self, name) is not None)
        return count + (1 if self.themes else 0)
