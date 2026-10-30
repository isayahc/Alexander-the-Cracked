"""Copilot orchestration tests: the guardrail pipeline end-to-end, offline."""

import asyncio
from decimal import Decimal

from app.copilot import Copilot, Session
from app.paypal import DemoPayPalClient
from app.planner import LocalPlanner, PlannedAction, PlannerContext, PlannerError


class ScriptedProvider:
    """Returns one canned plan — used to drive plans the local parser can't produce."""

    def __init__(self, plan: PlannedAction) -> None:
        self._plan = plan

    @property
    def name(self) -> str:
        return "scripted"

    async def plan(self, user_text: str, context: PlannerContext) -> PlannedAction:
        return self._plan


class ExplodingProvider:
    @property
    def name(self) -> str:
        return "exploding"

    async def plan(self, user_text: str, context: PlannerContext) -> PlannedAction:
        raise PlannerError("no brain today")


def turn(copilot: Copilot, text: str, session: Session):
    return asyncio.run(copilot.handle_turn(text, session))


def copilot() -> Copilot:
    return Copilot(gateway=DemoPayPalClient(), provider=LocalPlanner())


def test_create_order_executes_and_reports():
    session = Session()
    result = turn(copilot(), "create an order for $40 to Alice", session)

    assert result.status == "executed"
    assert "Created order" in result.message
    assert result.data["order"]["amount"] == "40"
    assert result.data["order"]["order_id"].startswith("ORDDEMO")


def test_create_order_without_amount_asks():
    result = turn(copilot(), "pay Carol", Session())
    assert result.status == "needs_info"


def test_capture_requires_confirmation_then_executes():
    session = Session()
    pilot = copilot()
    created = turn(pilot, "create an order for $40 to Alice", session)
    order_id = created.data["order"]["order_id"]

    asked = turn(pilot, f"capture order {order_id}", session)
    assert asked.status == "needs_confirmation"
    assert "moves real money" in asked.message
    assert session.pending is not None

    done = turn(pilot, "confirm", session)
    assert done.status == "executed"
    assert "moved" in done.message
    assert session.pending is None


def test_refund_flow_with_confirmation():
    session = Session()
    pilot = copilot()
    asked = turn(pilot, "refund $10 from capture DEMOCAP0001", session)
    assert asked.status == "needs_confirmation"

    done = turn(pilot, "confirm", session)
    assert done.status == "executed"
    assert "Refunded 10 USD" in done.message


def test_refund_without_capture_id_asks():
    result = turn(copilot(), "refund $25", Session())
    assert result.status == "needs_info"
    assert "capture" in result.message.lower()


def test_over_limit_amount_is_blocked():
    result = turn(copilot(), "create an order for $20000", Session())
    assert result.status == "blocked"
    assert "Blocked by policy" in result.message


def test_scripted_rogue_planner_cannot_skip_confirmation():
    rogue = ScriptedProvider(PlannedAction(action="capture_order", order_id="DEMOORD0001"))
    session = Session()
    result = asyncio.run(Copilot(DemoPayPalClient(), rogue).handle_turn("do it all", session))

    assert result.status == "needs_confirmation"  # guardrail is planner-independent


def test_scripted_bad_currency_is_blocked():
    rogue = ScriptedProvider(
        PlannedAction(action="create_order", amount=Decimal("50"), currency="JPY")
    )
    result = asyncio.run(Copilot(DemoPayPalClient(), rogue).handle_turn("pay", Session()))
    assert result.status == "blocked"
    assert "JPY" in result.message


def test_insight_turn_reports_flags():
    session = Session()
    result = turn(copilot(), "anything suspicious lately?", session)

    assert result.status == "answer"
    assert "worth a review" in result.message
    flagged_ids = [flag["transaction_id"] for flag in result.data["insights"]["flagged"]]
    assert "DEMOTX006" in flagged_ids


def test_transaction_history_turn():
    result = turn(copilot(), "show my transactions from the last 30 days", Session())
    assert result.status == "answer"
    assert result.message.startswith("8 transactions")


def test_unknown_text_returns_help():
    result = turn(copilot(), "what time is it on the moon?", Session())
    assert result.status == "answer"
    assert "PayPal copilot" in result.message


def test_paypal_failure_becomes_error_turn():
    session = Session()
    pilot = copilot()
    asked = turn(pilot, "capture order MISSING00001", session)
    assert asked.status == "needs_confirmation"

    done = turn(pilot, "confirm", session)
    assert done.status == "error"
    assert "PayPal" in done.message


def test_planner_failure_becomes_error_turn():
    result = asyncio.run(
        Copilot(DemoPayPalClient(), ExplodingProvider()).handle_turn("x", Session())
    )
    assert result.status == "error"
    assert "couldn't plan that turn" in result.message
