"""Insight heuristic tests against fixed ledgers (fully deterministic)."""

from app.insights import analyze
from app.paypal import Transaction, demo_transactions


def tx(transaction_id: str, amount: str, date: str, counterparty: str = "Acme") -> Transaction:
    return Transaction(
        transaction_id=transaction_id,
        date=date,
        counterparty=counterparty,
        amount=amount,
        currency="USD",
        status="COMPLETED",
        type="T0006",
    )


def demo_ledger() -> list[Transaction]:
    return [Transaction.model_validate(entry) for entry in demo_transactions()]


def test_demo_ledger_flags_the_planted_anomalies():
    report = analyze(demo_ledger())
    flagged_ids = {flag.transaction_id for flag in report.flagged}
    assert "DEMOTX006" in flagged_ids  # $1,299 outlier
    assert {"DEMOTX002", "DEMOTX003"} <= flagged_ids  # duplicate Acme charges
    assert "DEMOTX005" in flagged_ids  # 03:47 charge


def test_demo_ledger_summary_names_the_flags():
    report = analyze(demo_ledger())
    assert report.total == 8
    assert "worth a review" in report.summary
    assert "Global Freight Ltd" in report.summary


def test_empty_ledger():
    report = analyze([])
    assert report.total == 0
    assert report.summary.startswith("No transactions")


def test_clean_ledger_flags_nothing():
    clean = [
        tx("T1", "15.00", "2026-10-20T10:00:00Z", "Figma"),
        tx("T2", "82.40", "2026-10-21T11:00:00Z", "Linode"),
        tx("T3", "40.00", "2026-10-22T12:00:00Z", "Fastly"),
        tx("T4", "54.10", "2026-10-23T13:00:00Z", "Vercel"),
        tx("T5", "10.99", "2026-10-24T14:00:00Z", "Spotify"),
    ]
    report = analyze(clean)
    assert report.flagged == []
    assert "Nothing looks unusual" in report.summary


def test_duplicate_charges_within_24h_are_flagged():
    ledger = [
        tx("T1", "82.40", "2026-10-20T10:00:00Z"),
        tx("T2", "82.40", "2026-10-21T09:00:00Z"),
    ]
    report = analyze(ledger)
    assert {flag.transaction_id for flag in report.flagged} == {"T1", "T2"}
    assert "duplicate charge" in report.flagged[0].reasons[0]


def test_same_amount_after_24h_is_not_a_duplicate():
    ledger = [
        tx("T1", "82.40", "2026-10-20T10:00:00Z"),
        tx("T2", "82.40", "2026-10-22T10:00:00Z"),
    ]
    report = analyze(ledger)
    assert report.flagged == []


def test_large_refund_is_flagged():
    report = analyze([tx("T1", "-600.00", "2026-10-20T10:00:00Z")])
    assert len(report.flagged) == 1
    assert "large refund" in report.flagged[0].reasons[0]
