# SPEC.md — PayPilot

**Event:** PayPal AI Hackathon — Build what's next with PayPal and AI (Devpost)
**Deadline:** 2026-11-12, 12:00pm PST · **Prize pool:** $67,500 in cash · **Themes:** ai, web

## Verified event brief

Taken from the Devpost listing (paypalaihackathon.devpost.com), retrieved 2026-10-30:

- "Build or update an application that integrates the PayPal developer platform (using the
  free sandbox environment) along with an AI tool, model, or platform of your choice."
- "The only fundamental requirement: your project must meaningfully use both PayPal and AI."
- No prescribed problem statements or tracks — agents, apps, automations all welcome.
- A submission needs: a working prototype judges can actually run (clear setup/run
  instructions in a public repo, or a hosted demo), a text description, a list of the AI
  tools used, and a public YouTube demo video under 3 minutes.
- Judging: Technological Implementation, Design, Potential Impact, Innovation/Idea,
  Presentation.

No assumptions had to be substituted: the brief above is from the live listing.

## What it does

**PayPilot** is an AI copilot for PayPal: a chat web app where a small merchant types
plain English and PayPilot plans and performs PayPal operations, with a hard safety
rule — **money never moves without an explicit human confirmation**.

- "create an order for $49.99 to Alice" → drafts a PayPal checkout order (nothing captured).
- "capture order 8MC03208TH516050S" → PayPilot asks, the human confirms, money moves.
- "refund $25 from capture 9XY01234AB" → same confirmation gate, then a refund.
- "show my transactions from the last 14 days" → reporting API, normalized ledger.
- "anything suspicious lately?" → deterministic anomaly heuristics (statistical outliers,
  duplicate charges within 24h, charges in unusual hours, large refunds) with a
  plain-English summary.

## Architecture

```
user text ──> Planner (AI) ──> PlannedAction ──> Safety guardrails ──> Executor ──> PayPal
              (local or LLM)                    (confirm + policy)     (copilot)   (sandbox/demo)
```

- `app/planner.py` — the AI layer. `LocalPlanner` (deterministic intent parser, no key
  needed) and `OpenAIPlanner` (OpenAI-compatible chat completions in JSON mode) behind one
  protocol. Planning never touches PayPal directly.
- `app/safety.py` — pure guardrails: capture/refund require `confirm: true` in the plan;
  amount bounds ($0 < amount ≤ 10,000, ≤ 2 decimals); currency whitelist.
- `app/paypal.py` — PayPal REST client (OAuth2 client-credentials with token caching,
  v2 orders create/capture, refunds, v1 reporting/transactions with response
  normalization). `DemoPayPalClient` is a scripted in-memory stand-in with a fixed ledger
  (including planted anomalies) so the product demos with zero credentials.
- `app/copilot.py` — turn orchestration: plan → guardrail → (confirm?) → execute →
  narrate. Every turn returns a `CopilotTurn`; errors become honest error replies.
- `app/web.py` + `app/static/index.html` — FastAPI chat API (`POST /api/chat`), health
  probe with a mode badge (`demo` vs `sandbox`), and a chat UI.

## How to run it

```bash
cd builds/paypal-ai-hackathon
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
pytest          # run the test suite
paypilot        # serve the chat UI on http://127.0.0.1:8000
```

With no environment variables set, PayPilot runs in **DEMO mode** (scripted PayPal data,
clearly labeled in the UI and `/health`). Set `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`
(see `.env.example`) to switch the same code to the **PayPal sandbox**, and
`AI_PROVIDER=openai` + `OPENAI_API_KEY` to swap the local planner for an LLM planner.

## What was cut (deliberately)

- **No persistence** — sessions live in memory; there is no database.
- **No auth/multi-user** — single-tenant demo; session id is client-chosen.
- **No streaming/voice** — plain request/response chat.
- **No live-mode PayPal** — sandbox base URL only; refunds/orders tested against mocked
  transport, so CI never touches the network.
- **Local planner is English-only and heuristic** — it covers the demo phrase book; the
  LLM planner handles the long tail when a key is configured.
- **No background jobs** — insights are computed on request.
