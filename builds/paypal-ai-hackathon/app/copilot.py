"""Turn orchestration: plan -> guardrail -> execute -> narrate.

The copilot is the only place that may touch the gateway, and it only does so
after the safety checks pass. Every turn ends in a `CopilotTurn` — never an
exception — so the web layer can always answer.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.insights import analyze
from app.paypal import PayPalError, PayPalGateway
from app.planner import LLMProvider, PlannedAction, PlannerContext, PlannerError
from app.safety import requires_confirm, violations

TurnStatus = Literal["executed", "needs_confirmation", "blocked", "needs_info", "answer", "error"]

HELP_TEXT = (
    "I'm PayPilot, your PayPal copilot. Try:\n"
    '- "create an order for $49.99 to Alice for lunch" - draft a payment\n'
    '- "capture order <ORDER_ID>" - take the money (I\'ll ask you to confirm)\n'
    '- "refund $25 from capture <CAPTURE_ID>" - give money back (confirmed too)\n'
    '- "show my transactions from the last 14 days" - recent history\n'
    '- "anything suspicious lately?" - anomaly review of your ledger\n'
    "I never capture or refund without an explicit confirmation from you."
)


class Session(BaseModel):
    """Per-conversation state: the one action currently awaiting confirmation."""

    pending: PlannedAction | None = None


class CopilotTurn(BaseModel):
    status: TurnStatus
    message: str
    data: dict | None = Field(default=None)


def _missing_info(plan: PlannedAction) -> str | None:
    """Missing identifiers/amounts are coached, not blocked - checked before policy."""
    if plan.action == "create_order" and plan.amount is None:
        return 'How much should I ask for? (e.g. "create an order for $49.99 to Alice")'
    if plan.action == "capture_order" and plan.order_id is None:
        return (
            "Which order should I capture? Include the order ID "
            '(e.g. "capture order 8MC03208TH516050S").'
        )
    if plan.action == "refund" and plan.capture_id is None:
        return (
            "Which payment should I refund? Include the capture ID "
            '(e.g. "refund $25 from capture 9XY01234AB567890C").'
        )
    return None


class Copilot:
    """One brain, one gateway; every turn passes the guardrails before execution."""

    def __init__(self, gateway: PayPalGateway, provider: LLMProvider) -> None:
        self._gateway = gateway
        self._provider = provider

    async def handle_turn(self, text: str, session: Session) -> CopilotTurn:
        try:
            plan = await self._provider.plan(text, PlannerContext(pending=session.pending))
        except PlannerError as exc:
            session.pending = None
            return CopilotTurn(status="error", message=f"I couldn't plan that turn: {exc}")

        missing = _missing_info(plan)
        if missing is not None:
            session.pending = None
            return CopilotTurn(status="needs_info", message=missing)

        hard_issues = violations(plan)
        if hard_issues:
            session.pending = None
            return self._turn("blocked", "Blocked by policy: " + "; ".join(hard_issues), plan)

        if requires_confirm(plan) and not plan.confirm:
            session.pending = plan
            return self._turn("needs_confirmation", _confirmation_prompt(plan), plan)

        try:
            return await self._execute(plan, session)
        except PayPalError as exc:
            session.pending = None
            detail = f" (PayPal said: {exc.detail})" if exc.detail else ""
            return CopilotTurn(status="error", message=f"PayPal call failed: {exc}{detail}")

    async def _execute(self, plan: PlannedAction, session: Session) -> CopilotTurn:
        session.pending = None
        if plan.action == "create_order":
            return await self._create_order(plan)
        if plan.action == "capture_order":
            return await self._capture_order(plan)
        if plan.action == "refund":
            return await self._refund(plan)
        if plan.action == "list_transactions":
            return await self._list_transactions(plan)
        if plan.action == "insight_request":
            return await self._insights(plan)
        return CopilotTurn(status="answer", message=HELP_TEXT)

    async def _create_order(self, plan: PlannedAction) -> CopilotTurn:
        if plan.amount is None:
            return CopilotTurn(
                status="needs_info", message="How much, and in what currency? (e.g. $49.99 USD)"
            )
        currency = (plan.currency or "USD").upper()
        result = await self._gateway.create_order(
            str(plan.amount), currency, description=plan.target
        )
        return CopilotTurn(
            status="executed",
            message=(
                f"Created order {result.order_id} for {result.amount} {result.currency}"
                + (f" to {plan.target}" if plan.target else "")
                + ". This drafts the payment - nothing is captured yet. "
                f'Say "capture order {result.order_id}" when you\'re ready.'
            ),
            data={"order": result.model_dump(mode="json")},
        )

    async def _capture_order(self, plan: PlannedAction) -> CopilotTurn:
        result = await self._gateway.capture_order(plan.order_id)
        return CopilotTurn(
            status="executed",
            message=(
                f"Captured order {result.order_id}: {result.amount} {result.currency} moved "
                f"(capture {result.capture_id}, status {result.status})."
            ),
            data={"capture": result.model_dump(mode="json")},
        )

    async def _refund(self, plan: PlannedAction) -> CopilotTurn:
        result = await self._gateway.refund_capture(
            plan.capture_id, str(plan.amount) if plan.amount is not None else None
        )
        return CopilotTurn(
            status="executed",
            message=(
                f"Refunded {result.amount} {result.currency} from capture "
                f"{result.capture_id} (refund {result.refund_id}, status {result.status})."
            ),
            data={"refund": result.model_dump(mode="json")},
        )

    async def _list_transactions(self, plan: PlannedAction) -> CopilotTurn:
        days = plan.days or 30
        transactions = await self._gateway.list_transactions(days)
        lines = [
            f"- {tx.date[:10]} {tx.counterparty}: {tx.currency} {tx.amount} ({tx.status})"
            for tx in transactions
        ]
        message = (
            f"{len(transactions)} transactions in the last {days} days:\n" + "\n".join(lines)
            if transactions
            else f"No transactions in the last {days} days."
        )
        return CopilotTurn(
            status="answer",
            message=message,
            data={
                "transactions": [tx.model_dump(mode="json") for tx in transactions],
            },
        )

    async def _insights(self, plan: PlannedAction) -> CopilotTurn:
        days = plan.days or 30
        transactions = await self._gateway.list_transactions(days)
        report = analyze(transactions)
        return CopilotTurn(
            status="answer",
            message=report.summary,
            data={"insights": report.model_dump(mode="json")},
        )

    @staticmethod
    def _turn(status: TurnStatus, message: str, plan: PlannedAction) -> CopilotTurn:
        return CopilotTurn(
            status=status,
            message=message,
            data={"plan": plan.model_dump(mode="json", exclude_none=True)},
        )


def _confirmation_prompt(plan: PlannedAction) -> str:
    if plan.action == "capture_order":
        return (
            f"About to capture order {plan.order_id} - this moves real money. "
            'Reply "confirm" to proceed, or just ignore me to cancel.'
        )
    amount = f"{plan.amount} {plan.currency or 'USD'}" if plan.amount else "the payment"
    return (
        f"About to refund {amount} from capture {plan.capture_id} - this moves real money. "
        'Reply "confirm" to proceed, or just ignore me to cancel.'
    )
