# PayFlow fee assistant — pitch

Built for the **PayPal AI Hackathon** (online, submissions close 2026-11-12).

Sellers lose money to guesswork: fees surprise, tiers confuse, order notes
pile up unsorted. PayFlow is a zero-dependency CLI that prices a sale before
it happens — fee, net, and the cheaper tier — and sorts the order note into a
category with a fully transparent keyword score. Every output is explainable:
you can see exactly which words drove each decision, which is our answer to
the hackathon's AI theme without shipping a black box.

```
$ python payflow.py --amount 250 --note "consulting design work"
{
  "amount": 250.0,
  "estimated_fee": 9.21,
  "net": 240.79,
  "recommended_tier": "standard",
  "category": "services",
  "confidence": 1.0
}
```

Run it with `python payflow.py --amount <sale> [--note "..."]`. Python 3.12+,
standard library only — nothing to install.
