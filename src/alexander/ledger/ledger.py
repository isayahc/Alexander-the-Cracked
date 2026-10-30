"""Build a sourced requirement/rubric ledger from one canonical event.

Pure derivation: everything confirmed comes from what discovery actually
recorded, cited to the feed; everything the feeds do not document (entry fees,
eligibility rules, judging criteria) becomes an explicit open question. No
entry in this module is ever invented to fill a gap.
"""

from alexander.discovery.models import HackathonEvent
from alexander.ledger.models import (
    RequirementCategory,
    RequirementEntry,
    RequirementLedger,
    RequirementStatus,
)

_CONFIRMED = RequirementStatus.CONFIRMED
_UNKNOWN = RequirementStatus.UNKNOWN


def build_ledger(event: HackathonEvent) -> RequirementLedger:
    """Derive the ledger for one canonical (deduped) event.

    Cross-source conflicts recorded by dedupe surface as open questions —
    contradictory requirements must be resolved against the official event
    page before a build is committed to this target.
    """
    entries: list[RequirementEntry] = []
    open_questions: list[str] = []

    if event.deadline is not None:
        entries.append(
            RequirementEntry(
                requirement=f"Submissions close by {event.deadline.isoformat()}",
                category=RequirementCategory.DEADLINE,
                status=_CONFIRMED,
                source_url=event.url,
                source=event.source,
                detail=(
                    "Feed timestamp carries no timezone and was pinned to UTC; "
                    "verify the official deadline timezone on the event page."
                    if event.source == "devpost" and event.raw_submission_period
                    else None
                ),
            )
        )
    else:
        open_questions.append(
            "Deadline is not listed in any feed — confirm it on the event page before building."
        )

    if event.prize_amount:
        entries.append(
            RequirementEntry(
                requirement=f"Advertised prize: {event.prize_amount}",
                category=RequirementCategory.PRIZE,
                status=_CONFIRMED,
                source_url=event.url,
                source=event.source,
            )
        )
    else:
        open_questions.append("Prize is not listed in any feed — confirm on the event page.")

    format_requirement, format_detail = _format_claim(event)
    if format_requirement is not None:
        entries.append(
            RequirementEntry(
                requirement=format_requirement,
                category=RequirementCategory.FORMAT,
                status=_CONFIRMED,
                source_url=event.url,
                source=event.source,
                detail=format_detail,
            )
        )
    else:
        open_questions.append(
            "Location/format (online vs in person) is unknown — confirm on the event page."
        )

    if event.themes:
        entries.append(
            RequirementEntry(
                requirement=f"Themes: {', '.join(event.themes)}",
                category=RequirementCategory.THEME,
                status=_CONFIRMED,
                source_url=event.url,
                source=event.source,
            )
        )

    # Neither feed documents eligibility or judging; record the gap honestly.
    entries.append(
        RequirementEntry(
            requirement="Eligibility restrictions",
            category=RequirementCategory.ELIGIBILITY,
            status=_UNKNOWN,
        )
    )
    open_questions.append(
        "Eligibility restrictions are not documented in the feeds — verify who may enter "
        "on the official event page before building."
    )
    entries.append(
        RequirementEntry(
            requirement="Judging criteria / rubric",
            category=RequirementCategory.RUBRIC,
            status=_UNKNOWN,
        )
    )
    open_questions.append(
        "Judging criteria are not documented in the feeds — only publicly documented "
        "criteria may be used; capture them from the event page before building."
    )

    for field, claims in sorted(event.conflicts.items()):
        joined = "; ".join(claims)
        open_questions.append(
            f"Sources disagree on {field} ({joined}) — resolve against the official event page."
        )

    return RequirementLedger(
        event_name=event.name,
        event_url=event.url,
        sources=list(dict.fromkeys(event.sources or [event.source])),
        entries=entries,
        open_questions=open_questions,
    )


def _format_claim(event: HackathonEvent) -> tuple[str | None, str | None]:
    """Read the participation format from the location field, if recorded."""
    location = event.location
    if not location:
        return None, None
    lowered = location.lower()
    if "online" in lowered or "virtual" in lowered:
        return "Participation format: online/virtual", None
    return f"Location listed: {location}", (
        "May be in person or hybrid — confirm the participation format on the event page."
    )


def render_ledger_markdown(ledger: RequirementLedger) -> str:
    """Render the ledger as reviewable markdown with sourcing and open questions."""
    lines = [
        f"# Requirement ledger — {ledger.event_name}",
        "",
        f"Event page: {ledger.event_url}",
        f"Sources: {', '.join(ledger.sources) if ledger.sources else 'none'}",
        "",
        "## Requirements",
        "",
        "| Requirement | Category | Status | Source | Detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for entry in ledger.entries:
        source = entry.source or "—"
        if entry.source_url:
            source = f"[{entry.source or 'source'}]({entry.source_url})"
        detail = entry.detail or "—"
        lines.append(
            f"| {entry.requirement} | {entry.category.value} | {entry.status.value} | "
            f"{source} | {detail} |"
        )
    lines += ["", "## Open questions", ""]
    if ledger.open_questions:
        lines += [f"- {question}" for question in ledger.open_questions]
    else:
        lines.append("- None — all requirements confirmed from sourced claims.")
    return "\n".join(lines) + "\n"
