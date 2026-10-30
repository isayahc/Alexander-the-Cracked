"""Data models for the sourced requirement/rubric ledger.

The ledger records what is *known* about one event's requirements and what is
*unknown* — every confirmed entry carries the source it came from, and every
gap becomes an explicit open question instead of a silent assumption. Judges
and eligibility rules are only ever recorded when a feed actually documents
them; these feeds do not, so those entries surface as unknowns by design.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class RequirementCategory(StrEnum):
    DEADLINE = "deadline"
    PRIZE = "prize"
    FORMAT = "format"
    ELIGIBILITY = "eligibility"
    RUBRIC = "rubric"
    THEME = "theme"


class RequirementStatus(StrEnum):
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"


class RequirementEntry(BaseModel):
    """One requirement claim: what it says, where it came from, how sure we are."""

    requirement: str = Field(min_length=1)
    category: RequirementCategory
    status: RequirementStatus
    source_url: str | None = Field(
        default=None,
        description="Feed or event URL the claim came from; None only for unknowns.",
    )
    source: str | None = Field(
        default=None, description="Which discovery feed documented it (e.g. 'devpost')."
    )
    detail: str | None = Field(
        default=None,
        description="Caveats — e.g. a feed timestamp with no timezone information.",
    )


class RequirementLedger(BaseModel):
    """The sourced requirement/rubric ledger for one canonical event."""

    event_name: str = Field(min_length=1)
    event_url: str
    sources: list[str] = Field(default_factory=list)
    entries: list[RequirementEntry] = Field(default_factory=list)
    # Unresolved gaps and cross-source contradictions, phrased as questions an
    # operator must resolve against the official event page before building.
    open_questions: list[str] = Field(default_factory=list)
