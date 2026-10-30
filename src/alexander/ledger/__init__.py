"""ledger subpackage: sourced requirement/rubric ledgers for canonical events.

Every confirmed requirement is cited to the feed that documented it; gaps
(eligibility, judging, entry fees) surface as explicit open questions rather
than assumptions. The renderer emits reviewable markdown for the operator.
"""

from alexander.ledger.ledger import build_ledger, render_ledger_markdown
from alexander.ledger.models import (
    RequirementCategory,
    RequirementEntry,
    RequirementLedger,
    RequirementStatus,
)

__all__ = [
    "RequirementCategory",
    "RequirementEntry",
    "RequirementLedger",
    "RequirementStatus",
    "build_ledger",
    "render_ledger_markdown",
]
