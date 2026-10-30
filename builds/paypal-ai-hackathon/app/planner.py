"""The AI layer: turn plain English into a `PlannedAction`.

Two providers sit behind one protocol:
- `OpenAIPlanner`: a real LLM call (OpenAI-compatible chat completions, JSON mode).
- `LocalPlanner`: a deterministic intent parser, so the product still works with no key.

Neither provider ever talks to PayPal directly — planning and execution are separate,
which is what makes the safety guardrails enforceable.
"""

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ValidationError

Action = Literal[
    "create_order", "capture_order", "refund", "list_transactions", "insight_request", "help"
]

_CURRENCY_WORDS = {
    "usd": "USD",
    "dollar": "USD",
    "dollars": "USD",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
    "cad": "CAD",
    "aud": "AUD",
}
_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP"}

_AMOUNT_RE = re.compile(r"([$€£])?\s*(\d[\d,]*(?:\.\d{1,2})?)")
_ORDER_ID_RE = re.compile(r"\b[A-Z0-9]{9,22}\b")
_DAYS_RE = re.compile(r"last\s+(\d+)\s+(day|week)s?", re.IGNORECASE)
_TARGET_RE = re.compile(r"\bto\s+([A-Za-z][\w.' -]{0,39})")
_CONFIRM_RE = re.compile(r"^\s*(confirm|yes|yeah|yep|yup|do it|go ahead|proceed|ok|okay)\b", re.I)


class PlannerError(RuntimeError):
    """The planner could not produce a valid plan."""


class PlannedAction(BaseModel):
    """One step the copilot may take; the guardrails inspect this before anything runs."""

    action: Action
    amount: Decimal | None = None
    currency: str | None = None
    target: str | None = None
    order_id: str | None = None
    capture_id: str | None = None
    days: int | None = None
    confirm: bool = False


class PlannerContext(BaseModel):
    """What the planner knows about the conversation (the pending action awaiting confirm)."""

    pending: PlannedAction | None = None


class LLMProvider(Protocol):
    """A planning strategy; `name` shows up in /health so demos are honest about the AI."""

    @property
    def name(self) -> str: ...

    async def plan(self, user_text: str, context: PlannerContext) -> PlannedAction: ...


class LocalPlanner:
    """Deterministic intent parser — the credential-free fallback brain."""

    @property
    def name(self) -> str:
        return "local"

    async def plan(self, user_text: str, context: PlannerContext) -> PlannedAction:
        text = user_text.strip()
        lowered = text.lower()

        # A bare confirmation only maps to the pending action; otherwise fall through so
        # inline confirmations ("yes, refund $25 from capture X") parse normally.
        if _CONFIRM_RE.match(text) and context.pending is not None:
            return context.pending.model_copy(update={"confirm": True})

        if "refund" in lowered:
            return self._parse_refund(text)
        if "capture" in lowered:
            return self._parse_capture(text)
        if any(
            word in lowered
            for word in ("suspicious", "fraud", "unusual", "anomal", "weird", "insight", "audit")
        ):
            return PlannedAction(action="insight_request", days=self._parse_days(lowered))
        if any(
            word in lowered for word in ("transaction", "history", "recent payment", "activity")
        ):
            return PlannedAction(action="list_transactions", days=self._parse_days(lowered))
        if any(word in lowered for word in ("create", "charge", "pay", "order", "invoice", "send")):
            return self._parse_create(text)
        return self._fallback(text)

    def _fallback(self, text: str) -> PlannedAction:
        return PlannedAction(action="help", target=text if text else None)

    def _parse_create(self, text: str) -> PlannedAction:
        amount, currency = self._parse_amount(text)
        target_match = _TARGET_RE.search(text)
        target = target_match.group(1).strip(" .") if target_match else None
        return PlannedAction(
            action="create_order",
            amount=amount,
            currency=currency,
            target=target,
        )

    def _parse_capture(self, text: str) -> PlannedAction:
        return PlannedAction(
            action="capture_order",
            order_id=self._parse_id(text),
            confirm=self._inline_confirm(text),
        )

    def _parse_refund(self, text: str) -> PlannedAction:
        amount, currency = self._parse_amount(text)
        return PlannedAction(
            action="refund",
            amount=amount,
            currency=currency,
            capture_id=self._parse_id(text),
            confirm=self._inline_confirm(text),
        )

    @staticmethod
    def _inline_confirm(text: str) -> bool:
        return bool(_CONFIRM_RE.search(text)) or "confirm" in text.lower()

    @staticmethod
    def _parse_amount(text: str) -> tuple[Decimal | None, str | None]:
        match = _AMOUNT_RE.search(text)
        if match is None:
            return None, None
        currency = _SYMBOLS.get(match.group(1) or "", None) or _CURRENCY_WORDS.get(
            match.group(1) or "", None
        )
        if currency is None:
            lowered = text.lower()
            currency = next(
                (code for word, code in _CURRENCY_WORDS.items() if f" {word}" in f" {lowered}"),
                None,
            )
        try:
            return Decimal(match.group(2).replace(",", "")), currency
        except InvalidOperation as exc:  # pragma: no cover - regex guarantees digits
            raise PlannerError(f"could not parse amount from {text!r}") from exc

    @staticmethod
    def _parse_id(text: str) -> str | None:
        """Pick the first token shaped like a PayPal id: 9-22 alnum chars, digits and letters."""
        for match in _ORDER_ID_RE.finditer(text.upper()):
            token = match.group(0)
            if any(char.isdigit() for char in token) and any(char.isalpha() for char in token):
                return token
        return None

    @staticmethod
    def _parse_days(lowered: str) -> int | None:
        match = _DAYS_RE.search(lowered)
        if match is None:
            return None
        days = int(match.group(1))
        return days * 7 if match.group(2) == "week" else days


class OpenAIPlanner:
    """Plans via an OpenAI-compatible chat completion in JSON mode."""

    SYSTEM_PROMPT = (
        "You are PayPilot's planner. Map the user's message to exactly one action, "
        "replied as a JSON object with these fields:\n"
        '{"action": "create_order|capture_order|refund|list_transactions|'
        'insight_request|help",\n'
        ' "amount": "decimal string or null", "currency": "ISO code or null",\n'
        ' "target": "payee name or null", "order_id": "...", "capture_id": "...",\n'
        ' "days": "int window for history/insights or null",\n'
        ' "confirm": "true ONLY if the user explicitly confirms a proposed action"}\n'
        "Rules: capture_order and refund move real money — set confirm=true only when the "
        "user is confirming that exact proposed step. If the message matches no action, "
        "use action=help."
    )

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    @property
    def name(self) -> str:
        return f"openai:{self._model}"

    async def plan(self, user_text: str, context: PlannerContext) -> PlannedAction:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": self._user_prompt(user_text, context)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        try:
            response = await self._http.post("/chat/completions", json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return PlannedAction.model_validate(json.loads(content))
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            raise PlannerError(f"LLM call failed: {exc}") from exc
        except (json.JSONDecodeError, ValidationError) as exc:
            raise PlannerError(f"LLM returned an invalid plan: {exc}") from exc

    @staticmethod
    def _user_prompt(user_text: str, context: PlannerContext) -> str:
        pending = context.pending.model_dump_json() if context.pending else "none"
        return f"conversation state: pending action = {pending}\nuser message: {user_text}"

    async def aclose(self) -> None:
        await self._http.aclose()
