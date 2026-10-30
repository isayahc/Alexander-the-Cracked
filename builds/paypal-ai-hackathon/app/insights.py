"""Transaction insight heuristics: deterministic anomaly flags + a plain-English summary.

Deliberately not an LLM call: the detection must be explainable and repeatable.
The LLM (when configured) narrates on top; the flags themselves are auditable math.
"""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

from app.paypal import Transaction

NIGHT_START_HOUR = 1
NIGHT_END_HOUR = 5  # UTC hours treated as unusual for business charges
LARGE_REFUND_AMOUNT = Decimal("500.00")
_OUTLIER_MIN_SAMPLES = 5
_OUTLIER_SIGMA = 2.5
_OUTLIER_MEDIAN_FACTOR = 2


class Flag(BaseModel):
    transaction_id: str
    counterparty: str
    amount: str
    currency: str
    reasons: list[str]


class InsightReport(BaseModel):
    total: int
    flagged: list[Flag]
    summary: str


def analyze(transactions: list[Transaction]) -> InsightReport:
    """Run every heuristic over the ledger and render one readable summary."""
    reasons: dict[str, list[str]] = {tx.transaction_id: [] for tx in transactions}

    _flag_amount_outliers(transactions, reasons)
    _flag_duplicates(transactions, reasons)
    _flag_night_activity(transactions, reasons)
    _flag_large_refunds(transactions, reasons)

    flagged = [
        Flag(
            transaction_id=tx.transaction_id,
            counterparty=tx.counterparty,
            amount=tx.amount,
            currency=tx.currency,
            reasons=reasons[tx.transaction_id],
        )
        for tx in transactions
        if reasons[tx.transaction_id]
    ]
    summary = _summarize(transactions, flagged)
    return InsightReport(total=len(transactions), flagged=flagged, summary=summary)


def _flag_amount_outliers(transactions: list[Transaction], reasons: dict[str, list[str]]) -> None:
    positive = [tx for tx in transactions if _amount(tx) is not None and _amount(tx) > 0]
    amounts = [float(_amount(tx)) for tx in positive]
    if len(amounts) < 3:
        return
    median = _median(amounts)
    if median <= 0:
        return
    threshold = _outlier_threshold(amounts, median)
    for tx in positive:
        if float(_amount(tx)) > threshold:
            reasons[tx.transaction_id].append(
                f"amount {_amount(tx)} is far above the typical range (threshold {threshold:.2f})"
            )


def _outlier_threshold(amounts: list[float], median: float) -> float:
    if len(amounts) < _OUTLIER_MIN_SAMPLES:
        return median * 5
    mean = sum(amounts) / len(amounts)
    variance = sum((value - mean) ** 2 for value in amounts) / len(amounts)
    std = variance**0.5
    return max(mean + _OUTLIER_SIGMA * std, median * _OUTLIER_MEDIAN_FACTOR)


def _flag_duplicates(transactions: list[Transaction], reasons: dict[str, list[str]]) -> None:
    seen: dict[tuple[str, str, datetime], Transaction] = {}
    for tx in transactions:
        when = _parse_date(tx)
        if when is None or _amount(tx) is None or _amount(tx) <= 0:
            continue
        key = (tx.counterparty, str(_amount(tx)), when)
        for (other_party, other_amount, other_when), other in seen.items():
            if (
                other_party == key[0]
                and other_amount == key[1]
                and (when - other_when).total_seconds() <= 86400
            ):
                for tx_id in (tx.transaction_id, other.transaction_id):
                    reasons[tx_id].append(
                        f"duplicate charge: same amount to {tx.counterparty} within 24 hours"
                    )
        seen[key] = tx


def _flag_night_activity(transactions: list[Transaction], reasons: dict[str, list[str]]) -> None:
    for tx in transactions:
        when = _parse_date(tx)
        if when is not None and NIGHT_START_HOUR <= when.hour < NIGHT_END_HOUR:
            reasons[tx.transaction_id].append(
                f"charged at {when.strftime('%H:%M')} UTC, inside the {NIGHT_START_HOUR:02d}:00-"
                f"{NIGHT_END_HOUR:02d}:00 window unusual for business payments"
            )


def _flag_large_refunds(transactions: list[Transaction], reasons: dict[str, list[str]]) -> None:
    for tx in transactions:
        amount = _amount(tx)
        if amount is not None and amount <= -LARGE_REFUND_AMOUNT:
            reasons[tx.transaction_id].append(
                f"large refund of {amount} (over {LARGE_REFUND_AMOUNT})"
            )


def _summarize(transactions: list[Transaction], flagged: list[Flag]) -> str:
    if not transactions:
        return "No transactions found in the requested window."
    if not flagged:
        return f"Nothing looks unusual across {len(transactions)} transactions."
    lines = [f"{len(flagged)} of {len(transactions)} transactions look worth a review:"]
    for flag in flagged:
        lines.append(
            f"- {flag.transaction_id} ({flag.counterparty}, {flag.currency} {flag.amount}): "
            + "; ".join(flag.reasons)
        )
    return "\n".join(lines)


def _amount(tx: Transaction) -> Decimal | None:
    try:
        return Decimal(tx.amount)
    except InvalidOperation:
        return None


def _parse_date(tx: Transaction) -> datetime | None:
    try:
        return datetime.fromisoformat(tx.date.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2
