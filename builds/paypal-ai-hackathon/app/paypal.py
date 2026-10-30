"""PayPal integration: a thin async client over the PayPal REST API (v2 orders, v1 reporting).

Every call is bounded and typed; failures surface as `PayPalError` with the API's own
detail attached. A `DemoPayPalClient` stand-in satisfies the same `PayPalGateway`
protocol so the product runs end-to-end without credentials.
"""

import time
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel

SANDBOX_BASE_URL = "https://api-m.sandbox.paypal.com"
ALLOWED_CURRENCIES: tuple[str, ...] = ("USD", "EUR", "GBP", "CAD", "AUD")
_TOKEN_SKEW_S = 60.0


class PayPalError(RuntimeError):
    """A PayPal API call failed; carries the HTTP status and the API's detail."""

    def __init__(self, message: str, status: int | None = None, detail: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


class PayPalAuthError(PayPalError):
    """OAuth failed or was refused (bad credentials, expired grant)."""


class Transaction(BaseModel):
    """A normalized PayPal transaction, flattened out of the reporting API's shape."""

    transaction_id: str
    date: str  # ISO-8601 timestamp as returned by PayPal
    counterparty: str
    amount: str  # decimal string, signed: payments positive, refunds negative
    currency: str
    status: str
    type: str


class OrderResult(BaseModel):
    order_id: str
    status: str
    amount: str
    currency: str


class CaptureResult(BaseModel):
    order_id: str
    capture_id: str
    status: str
    amount: str
    currency: str


class RefundResult(BaseModel):
    refund_id: str
    capture_id: str
    status: str
    amount: str
    currency: str


class PayPalGateway(Protocol):
    """What the copilot can do with PayPal; implemented by the live client and the demo."""

    async def create_order(
        self,
        amount: str,
        currency: str,
        *,
        intent: Literal["CAPTURE", "AUTHORIZE"] = "CAPTURE",
        description: str | None = None,
        custom_id: str | None = None,
    ) -> OrderResult: ...

    async def capture_order(self, order_id: str) -> CaptureResult: ...

    async def refund_capture(self, capture_id: str, amount: str | None = None) -> RefundResult: ...

    async def list_transactions(self, days: int) -> list[Transaction]: ...


class PayPalClient:
    """Async PayPal REST client: OAuth2 client-credentials with token caching."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = SANDBOX_BASE_URL,
        timeout_s: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self._base_url, timeout=timeout_s, transport=transport
        )
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        try:
            response = await self._http.post(
                "/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
            )
        except httpx.HTTPError as exc:
            raise PayPalError(f"could not reach PayPal auth: {exc}") from exc
        if response.status_code in (401, 403):
            raise PayPalAuthError(
                "PayPal rejected the credentials (check PAYPAL_CLIENT_ID/SECRET)",
                status=response.status_code,
                detail=response.text,
            )
        if response.status_code != 200:
            raise PayPalError(
                "PayPal token endpoint failed", status=response.status_code, detail=response.text
            )
        payload = response.json()
        self._token = payload["access_token"]
        self._token_expires_at = (
            time.monotonic() + float(payload.get("expires_in", 0)) - _TOKEN_SKEW_S
        )
        return self._token

    async def _request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
        token = await self._access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            response = await self._http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise PayPalError(f"could not reach PayPal: {exc}") from exc
        if response.status_code >= 400:
            raise PayPalError(
                f"PayPal API call failed ({method} {path})",
                status=response.status_code,
                detail=response.text,
            )
        return response

    async def create_order(
        self,
        amount: str,
        currency: str,
        *,
        intent: Literal["CAPTURE", "AUTHORIZE"] = "CAPTURE",
        description: str | None = None,
        custom_id: str | None = None,
    ) -> OrderResult:
        """Create a checkout order (drafts intent; money does not move until capture)."""
        purchase_unit: dict[str, object] = {
            "amount": {"currency_code": currency, "value": amount},
            "custom_id": custom_id or "paypilot-copilot",
        }
        if description:
            purchase_unit["description"] = description[:127]
        response = await self._request(
            "POST",
            "/v2/checkout/orders",
            json={"intent": intent, "purchase_units": [purchase_unit]},
        )
        body = response.json()
        return OrderResult(
            order_id=body["id"], status=body["status"], amount=amount, currency=currency
        )

    async def capture_order(self, order_id: str) -> CaptureResult:
        """Capture a created order — this is the point where money actually moves."""
        response = await self._request("POST", f"/v2/checkout/orders/{order_id}/capture")
        body = response.json()
        capture_id, capture = _capture_fields(body)
        return CaptureResult(
            order_id=order_id,
            capture_id=capture_id,
            status=body.get("status", "UNKNOWN"),
            amount=_amount_value(capture, "0.00"),
            currency=_amount_currency(capture, "USD"),
        )

    async def refund_capture(self, capture_id: str, amount: str | None = None) -> RefundResult:
        """Refund a captured payment; pass an amount for a partial refund."""
        body = {"amount": {"value": amount}} if amount is not None else None
        response = await self._request(
            "POST", f"/v2/payments/captures/{capture_id}/refund", json=body
        )
        payload = response.json()
        refund_amount = payload.get("amount") or {}
        return RefundResult(
            refund_id=payload["id"],
            capture_id=capture_id,
            status=payload.get("status", "UNKNOWN"),
            amount=amount or str(refund_amount.get("value", "")),
            currency=str(refund_amount.get("currency_code", "")),
        )

    async def list_transactions(self, days: int) -> list[Transaction]:
        """List transactions from the last `days` days via the reporting API."""
        end = datetime.now(tz=UTC)
        start = end - timedelta(days=days)
        response = await self._request(
            "GET",
            "/v1/reporting/transactions",
            params={
                "start_date": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end_date": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "fields": "transaction_info",
                "page_size": 100,
            },
        )
        raw = response.json()
        return [_normalize_transaction(entry) for entry in raw.get("transaction_details", [])]

    async def aclose(self) -> None:
        await self._http.aclose()


class DemoPayPalClient:
    """Scripted in-memory PayPal stand-in for credential-free demos. No network, no money.

    Clearly labeled DEMO everywhere it surfaces; the fixed dataset includes an outlier
    and a duplicate charge so the insight heuristics have something real to find.
    """

    def __init__(self) -> None:
        self._orders: dict[str, dict[str, str]] = {}
        self._seq = 0

    def _id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}DEMO{self._seq:04d}"

    async def create_order(
        self,
        amount: str,
        currency: str,
        *,
        intent: Literal["CAPTURE", "AUTHORIZE"] = "CAPTURE",
        description: str | None = None,
        custom_id: str | None = None,
    ) -> OrderResult:
        order_id = self._id("ORD")
        self._orders[order_id] = {"amount": amount, "currency": currency}
        return OrderResult(order_id=order_id, status="CREATED", amount=amount, currency=currency)

    async def capture_order(self, order_id: str) -> CaptureResult:
        order = self._orders.get(order_id)
        if order is None:
            raise PayPalError(
                f"order {order_id} not found", status=404, detail="demo ledger has no such order"
            )
        return CaptureResult(
            order_id=order_id,
            capture_id=f"CAP{order_id[3:]}",
            status="COMPLETED",
            amount=order["amount"],
            currency=order["currency"],
        )

    async def refund_capture(self, capture_id: str, amount: str | None = None) -> RefundResult:
        return RefundResult(
            refund_id=f"REF{capture_id[3:]}",
            capture_id=capture_id,
            status="COMPLETED",
            amount=amount or "0.00",
            currency="USD",
        )

    async def list_transactions(self, days: int) -> list[Transaction]:
        return [
            Transaction.model_validate(tx)
            for tx in demo_transactions()
            if _within_days(tx["date"], days)
        ]

    async def aclose(self) -> None:
        return None  # protocol parity with PayPalClient


def _amount_value(purchase_unit: dict, default: str) -> str:
    amount = purchase_unit.get("amount", {})
    return str(amount.get("value", default)) if isinstance(amount, dict) else default


def _amount_currency(purchase_unit: dict, default: str) -> str:
    amount = purchase_unit.get("amount", {})
    return str(amount.get("currency_code", default)) if isinstance(amount, dict) else default


def _capture_fields(capture_body: dict) -> tuple[str, dict]:
    """Extract (capture_id, capture object) from an order-capture response.

    The captured amount lives on payments.captures[0], not on the purchase unit.
    """
    units = capture_body.get("purchase_units") or [{}]
    unit = units[0] if isinstance(units, list) and units else {}
    if not isinstance(unit, dict):
        unit = {}
    payments = unit.get("payments", {}) or {}
    captures = payments.get("captures") or [{}]
    capture = captures[0] if isinstance(captures, list) and captures else {}
    if not isinstance(capture, dict):
        capture = {}
    return str(capture.get("id", "")), capture


def _normalize_transaction(entry: dict) -> Transaction:
    """Flatten one PayPal reporting `transaction_details` entry into a Transaction."""
    info = entry.get("transaction_info", {}) or {}
    amount = info.get("transaction_amount", {}) or {}
    if not isinstance(amount, dict):
        amount = {}
    counterparty_info = info.get("counterparty", {}) or {}
    counterparty = (
        counterparty_info.get("business_name")
        or counterparty_info.get("email_address")
        or info.get("transaction_note")
        or "unknown counterparty"
    )
    return Transaction(
        transaction_id=str(info.get("transaction_id", "unknown")),
        date=str(info.get("transaction_initiation_date", "")),
        counterparty=str(counterparty),
        amount=str(amount.get("value", "0")),
        currency=str(amount.get("currency_code", "USD")),
        status=str(info.get("transaction_status", "UNKNOWN")),
        type=str(info.get("transaction_event_code", "UNKNOWN")),
    )


def _within_days(date_iso: str, days: int) -> bool:
    when = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
    return datetime.now(tz=UTC) - when <= timedelta(days=days)


def demo_transactions() -> list[dict]:
    """Fixed demo ledger: mostly ordinary charges, plus one outlier and one duplicate pair."""
    return [
        {
            "transaction_id": "DEMOTX001",
            "date": "2026-10-28T14:03:00Z",
            "counterparty": "Figma",
            "amount": "15.00",
            "currency": "USD",
            "status": "COMPLETED",
            "type": "T0006",
        },
        {
            "transaction_id": "DEMOTX002",
            "date": "2026-10-27T09:41:00Z",
            "counterparty": "Acme Retail Co",
            "amount": "82.40",
            "currency": "USD",
            "status": "COMPLETED",
            "type": "T0006",
        },
        {
            "transaction_id": "DEMOTX003",
            "date": "2026-10-26T18:22:00Z",
            "counterparty": "Acme Retail Co",
            "amount": "82.40",
            "currency": "USD",
            "status": "COMPLETED",
            "type": "T0006",
        },
        {
            "transaction_id": "DEMOTX004",
            "date": "2026-10-25T11:15:00Z",
            "counterparty": "Linode",
            "amount": "40.00",
            "currency": "USD",
            "status": "COMPLETED",
            "type": "T0006",
        },
        {
            "transaction_id": "DEMOTX005",
            "date": "2026-10-24T03:47:00Z",
            "counterparty": "QuickMart Gas",
            "amount": "54.10",
            "currency": "USD",
            "status": "COMPLETED",
            "type": "T0006",
        },
        {
            "transaction_id": "DEMOTX006",
            "date": "2026-10-23T16:05:00Z",
            "counterparty": "Global Freight Ltd",
            "amount": "1299.00",
            "currency": "USD",
            "status": "COMPLETED",
            "type": "T0006",
        },
        {
            "transaction_id": "DEMOTX007",
            "date": "2026-10-22T10:30:00Z",
            "counterparty": "Spotify",
            "amount": "10.99",
            "currency": "USD",
            "status": "COMPLETED",
            "type": "T0006",
        },
        {
            "transaction_id": "DEMOTX008",
            "date": "2026-10-21T12:00:00Z",
            "counterparty": "Coffee Collective",
            "amount": "6.50",
            "currency": "USD",
            "status": "COMPLETED",
            "type": "T0006",
        },
    ]
