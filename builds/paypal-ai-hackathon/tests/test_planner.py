"""LocalPlanner behaviour: intents, amounts, currencies, ids, windows, confirmation."""

import asyncio
from decimal import Decimal

from app.planner import LocalPlanner, PlannedAction, PlannerContext


def plan(text: str, pending: PlannedAction | None = None) -> PlannedAction:
    return asyncio.run(LocalPlanner().plan(text, PlannerContext(pending=pending)))


def test_create_order_with_dollar_symbol():
    parsed = plan("create an order for $49.99 to Alice")
    assert parsed.action == "create_order"
    assert parsed.amount == Decimal("49.99")
    assert parsed.currency == "USD"
    assert parsed.target == "Alice"


def test_create_order_with_currency_word():
    parsed = plan("invoice 25 EUR to Bob")
    assert parsed.action == "create_order"
    assert parsed.amount == Decimal("25")
    assert parsed.currency == "EUR"


def test_create_order_with_comma_amount():
    parsed = plan("charge 1,299.50 USD to Acme")
    assert parsed.amount == Decimal("1299.50")
    assert parsed.currency == "USD"


def test_create_order_without_amount_is_left_to_the_copilot():
    parsed = plan("pay Carol")
    assert parsed.action == "create_order"
    assert parsed.amount is None


def test_capture_parses_order_id():
    parsed = plan("capture order 8MC03208TH516050S")
    assert parsed.action == "capture_order"
    assert parsed.order_id == "8MC03208TH516050S"
    assert parsed.confirm is False


def test_capture_ignores_digitless_words():
    parsed = plan("capture the outstanding invoice")
    assert parsed.action == "capture_order"
    assert parsed.order_id is None


def test_refund_parses_amount_and_capture_id():
    parsed = plan("refund $25 from capture 9XY01234AB")
    assert parsed.action == "refund"
    assert parsed.amount == Decimal("25")
    assert parsed.currency == "USD"
    assert parsed.capture_id == "9XY01234AB"


def test_confirm_applies_to_pending_action():
    pending = PlannedAction(action="capture_order", order_id="DEMOORD0001")
    parsed = plan("confirm", pending=pending)
    assert parsed.confirm is True
    assert parsed.order_id == "DEMOORD0001"


def test_inline_confirmation_counts_as_consent():
    parsed = plan("yes, refund $25 from capture 9XY01234AB")
    assert parsed.action == "refund"
    assert parsed.confirm is True


def test_transaction_history_window_in_days():
    parsed = plan("show my transactions from the last 14 days")
    assert parsed.action == "list_transactions"
    assert parsed.days == 14


def test_transaction_history_window_in_weeks():
    parsed = plan("show me my payment history from the last 2 weeks")
    assert parsed.action == "list_transactions"
    assert parsed.days == 14


def test_insight_request_keywords():
    parsed = plan("anything suspicious lately?")
    assert parsed.action == "insight_request"


def test_unknown_text_falls_back_to_help():
    parsed = plan("hello there")
    assert parsed.action == "help"


def test_bare_confirm_without_pending_is_help():
    parsed = plan("confirm")
    assert parsed.action == "help"
