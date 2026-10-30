"""Guardrail tests: the checks that keep money from moving by accident."""

from decimal import Decimal

from app.planner import PlannedAction
from app.safety import requires_confirm, violations


def test_create_order_requires_an_amount():
    issues = violations(PlannedAction(action="create_order"))
    assert issues == ["amount is required"]


def test_zero_amount_is_rejected():
    issues = violations(PlannedAction(action="create_order", amount=Decimal("0")))
    assert issues == ["amount must be positive"]


def test_negative_amount_is_rejected():
    issues = violations(PlannedAction(action="create_order", amount=Decimal("-5")))
    assert issues == ["amount must be positive"]


def test_amount_over_limit_is_rejected():
    issues = violations(PlannedAction(action="create_order", amount=Decimal("10000.01")))
    assert issues == ["amount exceeds the 10000.00 per-action limit"]


def test_three_decimals_are_rejected():
    issues = violations(PlannedAction(action="create_order", amount=Decimal("5.123")))
    assert issues == ["amount must have at most 2 decimal places"]


def test_refund_without_amount_is_a_full_refund_and_allowed():
    issues = violations(PlannedAction(action="refund", capture_id="9XY01234AB"))
    assert issues == []


def test_unsupported_currency_is_rejected():
    issues = violations(PlannedAction(action="create_order", amount=Decimal("50"), currency="JPY"))
    assert any("JPY" in issue for issue in issues)


def test_valid_plan_has_no_violations():
    plan = PlannedAction(action="create_order", amount=Decimal("49.99"), currency="USD")
    assert violations(plan) == []


def test_money_moving_actions_need_confirmation():
    assert requires_confirm(PlannedAction(action="capture_order", order_id="X"))
    assert requires_confirm(PlannedAction(action="refund", capture_id="Y"))
    assert not requires_confirm(PlannedAction(action="create_order", amount=Decimal("1")))
    assert not requires_confirm(PlannedAction(action="list_transactions"))
    assert not requires_confirm(PlannedAction(action="insight_request"))
    assert not requires_confirm(PlannedAction(action="help"))
