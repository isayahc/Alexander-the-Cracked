# PayPilot — an AI copilot for PayPal

**Chat with your money.** PayPilot turns plain English into PayPal payments and
transaction insights: draft orders, capture and refund with an explicit human "confirm"
before anything moves, review recent history, and flag suspicious charges — all from one
chat box.

Built for the **PayPal AI Hackathon** (Devpost, deadline 2026-11-12): PayPal integration
is central (REST API v2 orders + refunds, v1 transaction reporting, OAuth2), and AI is
the experience (an intent planner that maps natural language to payment operations, with
an OpenAI-compatible LLM provider or a deterministic local planner).

## Why it wins

- **Payments-grade safety as the feature, not an afterthought.** A rogue or hallucinating
  planner physically cannot move money: capture/refund plans require `confirm: true`,
  enforced in a pure guardrail layer independent of the AI — tested with a deliberately
  rogue scripted planner.
- **Real PayPal integration, honestly tested.** OAuth2 client-credentials with token
  caching, order create/capture, refunds, transaction reporting with response
  normalization — exercised through mocked HTTP transport, so tests are fast, offline,
  and deterministic.
- **Runs for judges with zero credentials.** No API keys? PayPilot runs in a clearly
  labeled DEMO mode with a scripted ledger (with planted anomalies for the insights
  demo). Add sandbox credentials and the same code path goes live on the PayPal sandbox.
- **Explainable AI.** Anomaly detection is auditable math (statistical outliers,
  duplicate charges within 24h, odd-hours charges, large refunds), not a black box.

## How to run it

```bash
cd builds/paypal-ai-hackathon
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
pytest              # 58 tests, all offline
paypilot            # serves the chat UI at http://127.0.0.1:8000
```

Then open http://127.0.0.1:8000 and try:

- `create an order for $49.99 to Alice for lunch`
- `capture order <ORDER_ID>` → PayPilot asks → you confirm
- `refund $25 from capture <CAPTURE_ID>` → same gate
- `show my transactions from the last 14 days`
- `anything suspicious lately?`

Optional environment (see `.env.example`): `PAYPAL_CLIENT_ID`/`PAYPAL_CLIENT_SECRET` for
the PayPal sandbox (free developer account), `AI_PROVIDER=openai` + `OPENAI_API_KEY` for
an LLM planner, `OPENAI_BASE_URL`/`OPENAI_MODEL` for any OpenAI-compatible endpoint.

See `SPEC.md` for the full spec and the deliberate cuts, and `LICENSE` (MIT).
