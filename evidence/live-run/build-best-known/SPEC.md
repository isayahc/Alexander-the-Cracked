# SPEC — PayFlow fee assistant

**Event:** PayPal AI Hackathon (themes: Low/No Code, Machine Learning/AI, Web)
**Deadline:** 2026-11-12 · **Prize:** $67,500 · **Location:** Online

## Problem

Small sellers on PayPal checkout guess at fees: they do not know what a sale
nets until the money lands, cannot tell which pricing tier is cheapest for
their volume, and manually triage order notes.

## Scope

A standard-library-only CLI that, for one transaction:

1. estimates the processing fee (percentage plus fixed cut) and the net payout;
2. recommends the cheapest of two pricing tiers for the sale;
3. buckets a free-text order note into services / goods / donation / digital
   with a transparent keyword score — every classification is explainable by
   the matched words, which is the "AI" the hackathon theme asks for without
   an unexplainable model.

## Success criteria

- `python payflow.py --amount 100 --note "consulting design work"` prints
  JSON with `estimated_fee`, `net`, `recommended_tier`, `category`,
  `confidence`, and exits 0.
- Negative amounts are rejected with a clear error, not a confusing fee.
- The test suite passes with plain `pytest` and no network or services.

## Limitations (explicit)

- The fee model is the documented standard US model (3.49% + $0.49) hard-coded
  for demonstration; real fees vary by country and currency.
- The categorizer is a scored keyword table, not a trained model.
- No persistence, no network calls, no PayPal API integration.
