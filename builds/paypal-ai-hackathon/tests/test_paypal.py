"""PayPal client tests: request shapes, token caching, error mapping - all offline.

httpx.MockTransport stands in for the wire; the client code under test is the
real production client, not a stub. Tests drive the async client through
asyncio.run so the suite needs no async pytest plugin.
"""

import asyncio

import httpx
import pytest

from app.paypal import (
    DemoPayPalClient,
    PayPalAuthError,
    PayPalClient,
    PayPalError,
    Transaction,
)


def run(coro):
    return asyncio.run(coro)


def _fake_paypal(calls: list):
    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization")
        calls.append((request.method, request.url.path, auth))
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
        if request.url.path == "/v2/checkout/orders":
            return httpx.Response(201, json={"id": "8MC03208TH516050S", "status": "CREATED"})
        if request.url.path.endswith("/capture"):
            return httpx.Response(
                201,
                json={
                    "id": "8MC03208TH516050S",
                    "status": "COMPLETED",
                    "purchase_units": [
                        {
                            "payments": {
                                "captures": [
                                    {
                                        "id": "9XY01234AB",
                                        "amount": {"value": "49.99", "currency_code": "USD"},
                                    }
                                ]
                            }
                        }
                    ],
                },
            )
        if "/refund" in request.url.path:
            return httpx.Response(
                201,
                json={
                    "id": "REF123",
                    "status": "COMPLETED",
                    "amount": {"value": "25.00", "currency_code": "USD"},
                },
            )
        if request.url.path == "/v1/reporting/transactions":
            return httpx.Response(
                200,
                json={
                    "transaction_details": [
                        {
                            "transaction_info": {
                                "transaction_id": "TX001",
                                "transaction_initiation_date": "2026-10-28T14:03:00Z",
                                "transaction_amount": {"currency_code": "USD", "value": "82.40"},
                                "counterparty": {"business_name": "Acme Retail Co"},
                                "transaction_status": "COMPLETED",
                                "transaction_event_code": "T0006",
                            }
                        }
                    ]
                },
            )
        return httpx.Response(404, json={"message": "unexpected path"})

    return handler


def _client(calls: list) -> PayPalClient:
    return PayPalClient("cid", "csecret", transport=httpx.MockTransport(_fake_paypal(calls)))


def test_create_order_sends_oauth_and_payload():
    calls: list = []
    client = _client(calls)
    result = run(client.create_order("49.99", "USD", description="lunch"))
    run(client.aclose())

    assert result.order_id == "8MC03208TH516050S"
    assert result.status == "CREATED"
    token_calls = [c for c in calls if c[1] == "/v1/oauth2/token"]
    order_calls = [c for c in calls if c[1] == "/v2/checkout/orders"]
    assert len(token_calls) == 1
    assert order_calls[0][2] == "Bearer test-token"


def test_token_is_cached_across_calls():
    calls: list = []
    client = _client(calls)
    run(client.create_order("1.00", "USD"))
    run(client.create_order("2.00", "USD"))
    run(client.aclose())

    token_calls = [c for c in calls if c[1] == "/v1/oauth2/token"]
    assert len(token_calls) == 1


def test_capture_returns_capture_details():
    calls: list = []
    client = _client(calls)
    result = run(client.capture_order("8MC03208TH516050S"))
    run(client.aclose())

    assert result.capture_id == "9XY01234AB"
    assert result.status == "COMPLETED"
    assert result.amount == "49.99"
    assert result.currency == "USD"


def test_refund_passes_partial_amount():
    calls: list = []
    client = _client(calls)
    result = run(client.refund_capture("9XY01234AB", amount="25.00"))
    run(client.aclose())

    assert result.refund_id == "REF123"
    assert result.amount == "25.00"


def test_list_transactions_normalizes_entries():
    calls: list = []
    client = _client(calls)
    transactions = run(client.list_transactions(days=30))
    run(client.aclose())

    assert len(transactions) == 1
    tx = transactions[0]
    assert isinstance(tx, Transaction)
    assert tx.transaction_id == "TX001"
    assert tx.counterparty == "Acme Retail Co"
    assert tx.amount == "82.40"
    reporting_calls = [c for c in calls if c[1] == "/v1/reporting/transactions"]
    assert reporting_calls == [("GET", "/v1/reporting/transactions", "Bearer test-token")]


def test_api_error_carries_status_and_detail():
    def failing(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        return httpx.Response(400, json={"message": "INVALID_AMOUNT"})

    client = PayPalClient("cid", "csecret", transport=httpx.MockTransport(failing))
    with pytest.raises(PayPalError) as exc_info:
        run(client.create_order("0", "USD"))
    run(client.aclose())

    assert exc_info.value.status == 400
    assert "INVALID_AMOUNT" in (exc_info.value.detail or "")


def test_bad_credentials_raise_auth_error():
    def refusing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client"})

    client = PayPalClient("cid", "csecret", transport=httpx.MockTransport(refusing))
    with pytest.raises(PayPalAuthError):
        run(client.create_order("1.00", "USD"))
    run(client.aclose())


def test_demo_client_roundtrip_without_credentials():
    demo = DemoPayPalClient()
    order = run(demo.create_order("40.00", "USD"))
    capture = run(demo.capture_order(order.order_id))
    refund = run(demo.refund_capture(capture.capture_id, amount="10.00"))

    assert order.status == "CREATED"
    assert capture.status == "COMPLETED"
    assert refund.status == "COMPLETED"
    with pytest.raises(PayPalError):
        run(demo.capture_order("NOPE1234567"))


def test_demo_ledger_filters_by_window():
    demo = DemoPayPalClient()
    transactions = run(demo.list_transactions(days=30))
    assert transactions, "demo ledger should have entries within 30 days"
