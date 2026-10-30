"""PayFlow fee assistant — a small CLI for sellers pricing a PayPal checkout.

Estimates the processing fee for a transaction, compares the merchant's
pricing tiers to recommend the cheapest one, and buckets an order note into a
category with a transparent keyword scorer. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass


def estimate_fee(amount: float, rate: float = 0.0349, fixed: float = 0.49) -> float:
    """The standard US fee model: percentage of the amount plus a fixed cut."""
    if amount < 0:
        raise ValueError("amount must be non-negative")
    return round(amount * rate + fixed, 2)


@dataclass(frozen=True)
class Tier:
    """One pricing tier: a rate with a monthly plan cost amortized to zero."""

    name: str
    rate: float
    monthly_cost: float = 0.0

    def total_cost(self, monthly_volume: float, transactions: int) -> float:
        return self.monthly_cost + monthly_volume * self.rate + fixed_fee_share(self, transactions)


def fixed_fee_share(tier: Tier, transactions: int) -> float:
    """The per-transaction fixed cut across the month's transactions."""
    return tier.rate * 0 if transactions == 0 else transactions * 0.49


def best_tier(amount: float, tiers: list[Tier], transactions: int = 1) -> Tier:
    """The tier with the lowest per-transaction cost for this sale."""
    if not tiers:
        raise ValueError("at least one tier is required")
    costs = [
        (tier.monthly_cost / max(transactions, 1)) + amount * tier.rate + 0.49
        for tier in tiers
    ]
    return tiers[costs.index(min(costs))]


# The AI-flavored layer is deliberately transparent: a scored keyword match
# over a small rule table, so every category decision is explainable.
RULES: dict[str, list[str]] = {
    "services": ["consulting", "freelance", "design", "development"],
    "goods": ["shirt", "poster", "mug", "sticker", "print"],
    "donation": ["donate", "sponsor", "support", "charity"],
    "digital": ["license", "ebook", "template", "subscription"],
}


def categorize(description: str) -> tuple[str, float]:
    """Classify an order note; ties prefer the earliest category."""
    words = description.lower().split()
    scores = {
        category: sum(1 for word in words if word.strip(".,!") in keywords)
        for category, keywords in RULES.items()
    }
    best = max(scores, key=lambda category: (scores[category], -list(scores).index(category)))
    total = sum(scores.values())
    confidence = scores[best] / total if total else 0.0
    return best, round(confidence, 2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PayFlow fee assistant")
    parser.add_argument("--amount", type=float, required=True, help="transaction amount")
    parser.add_argument("--note", default="", help="order note to categorize")
    args = parser.parse_args(argv)

    fee = estimate_fee(args.amount)
    tier = best_tier(args.amount, [Tier("standard", 0.0349), Tier("micro", 0.0499)])
    result = {
        "amount": args.amount,
        "estimated_fee": fee,
        "net": round(args.amount - fee, 2),
        "recommended_tier": tier.name,
    }
    if args.note:
        category, confidence = categorize(args.note)
        result["category"] = category
        result["confidence"] = confidence
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
