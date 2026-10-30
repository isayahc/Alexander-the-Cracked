"""Guardrails — the heart of the product: PayPilot never moves money silently.

Pure checks, no I/O. `violations` returns hard policy breaches (blocked always);
`requires_confirm` says whether a plan moves money and therefore needs a human "confirm".
"""

from decimal import Decimal

from app.paypal import ALLOWED_CURRENCIES
from app.planner import PlannedAction

MAX_SINGLE_AMOUNT = Decimal("10000.00")
MONEY_MOVING_ACTIONS = frozenset({"capture_order", "refund"})


def requires_confirm(plan: PlannedAction) -> bool:
    """True when the plan moves money and must be explicitly confirmed first."""
    return plan.action in MONEY_MOVING_ACTIONS


def violations(plan: PlannedAction) -> list[str]:
    """Hard policy violations for this plan; empty list means the plan is policy-legal."""
    issues: list[str] = []
    if plan.action == "create_order":
        issues += _amount_issues(plan.amount, required=True)
    elif plan.action == "refund":
        issues += _amount_issues(plan.amount, required=False)
    if plan.currency is not None and plan.currency.upper() not in ALLOWED_CURRENCIES:
        allowed = ", ".join(ALLOWED_CURRENCIES)
        issues.append(f"currency {plan.currency} is not supported (allowed: {allowed})")
    return issues


def _amount_issues(amount: Decimal | None, required: bool) -> list[str]:
    if amount is None:
        return ["amount is required"] if required else []
    if amount <= 0:
        return ["amount must be positive"]
    if amount > MAX_SINGLE_AMOUNT:
        return [f"amount exceeds the {MAX_SINGLE_AMOUNT} per-action limit"]
    if amount != amount.quantize(Decimal("0.01")):
        return ["amount must have at most 2 decimal places"]
    return []
