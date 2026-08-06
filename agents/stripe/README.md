# stripe agent — implement, homologate, validate, prove

Takes any project from "has some Stripe code" (or none) to **"the payment system is proven, in a
real TEST environment, with documented evidence and a PDF the owner can act on."** Homologation =
Stripe **TEST mode** — no real money is ever touched to validate.

The brain is [`SKILL.md`](SKILL.md). Point an LLM session at it inside a target project:

> Read `…/agentes_perdidos/agents/stripe/SKILL.md` and validate Stripe on this project — set up a
> homologation environment with test keys, prove every payment flow, and give me the PDF.

## What it does

1. **Operator gate** — asks (per app): which Stripe account, what catalog/prices, the business
   model, and the go-live criteria. Nothing runs before you answer.
2. **Provision** — confirms/creates the Stripe account; gets a **test** key; optionally wires the
   Stripe MCP. Baseline is Stripe CLI + REST (portable across LLM agents).
3. **Homologation env** — a TEST profile *separate from production*: test keys, the live catalog
   **mirrored into test mode**, and `stripe listen` forwarding webhooks. Prod config untouched.
4. **Implement/repair** — fixes the integration to `stripe-best-practices` (idempotency, webhook
   signature + dedup, the right surface, a clear customer UI).
5. **Validate two ways** — Lane A (headless API: test PM tokens, `stripe trigger`, Test Clocks,
   asserting app/DB end-state + idempotency + signature rejection) and Lane B (real browser
   checkout with the test-card matrix, screenshotting every step).
6. **Document + PDF** — writes a homologation runbook into the project's LLM-wiki and emits a
   per-app PDF: each flow ✅ functional / ⚠️ pending / ❌ broken, with evidence.

## Scripts (run via `uv`)

```bash
uv run agents/stripe/stripe_env.py check --key sk_test_xxx                       # refuse live keys, confirm test mode
uv run agents/stripe/mirror_catalog.py --live-key rk_live_ro --test-key sk_test  # live catalog → test (idempotent)
uv run agents/stripe/validate.py --config app.stripe.json --test-key sk_test --out results.json   # Lane A
uv run agents/stripe/report.py --results results.json --shots ./shots --out app-stripe.pdf         # PDF
```

`example.stripe.json` is the `validate.py` config schema (copy per app, edit, keep in the project
brain). Needs the [Stripe CLI](https://docs.stripe.com/stripe-cli) (`stripe login`, `listen`,
`trigger`) for webhook/event testing.

## Keys

Test keys live **only in the target project's gitignored env** — never in this repo, never in the
wiki/PDF (refer to keys by name + last 4). The agent uses a TEST secret/restricted key for
everything; a LIVE **read-only restricted** key is used solely for the one-way catalog read in
`mirror_catalog.py`. `stripe_env.py` hard-refuses any live secret.

See the repo [`.env.example`](../../.env.example) for the documented variables.
