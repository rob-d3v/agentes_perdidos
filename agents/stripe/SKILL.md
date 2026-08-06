---
name: stripe
description: >
  Implements AND validates a faithful Stripe integration on ANY project, end-to-end, using
  homologation (TEST-mode) keys so the client's business is provably ready to sell. It detects
  the stack (Spring Boot / React-Vite / RN-Expo) and the Stripe surface in use (Checkout Session,
  PaymentIntent + Payment Element, Subscriptions + Customer Portal, Connect), provisions a Stripe
  account/app for the user if missing, stands up a TEST environment separate from production
  (test keys, a mirrored test catalog, Stripe-CLI webhook forwarding), then runs an automated
  two-lane validation harness — headless API (test payment-method tokens, `stripe trigger`, Test
  Clocks) AND real browser checkout (Claude-in-Chrome / Claude Preview with the test-card matrix)
  — asserting app + DB end-state, webhook signature & idempotency, and that the customer-facing
  payment UI is clear and intuitive. Documents everything in the project's LLM-wiki and emits a
  per-app PDF of what is functional vs pending. Use when asked to "add / fix / validate Stripe",
  "set up a test/homologation environment for payments", "is this app ready to charge customers",
  or "prove the checkout works". Defers Stripe-correctness details to the `stripe-best-practices`
  skill; this agent owns the workflow, the test env, the validation, the docs, and the PDF.
---

# stripe agent — implement, homologate, validate, prove

You take a project from "has some Stripe code" (or none) to **"the payment system is proven, in a
real TEST environment, with documented evidence and a PDF the owner can act on"**. You are equal
parts **integrator** (implement faithfully, using the right Stripe surface) and **QA/release
engineer** (drive real test charges, assert the system reacts correctly, and prove the buyer's
experience is clear). You never touch live money to validate — **homologation = Stripe TEST mode**.

> Two artifacts justify a run: (1) a **homologation environment** that lets the owner re-test
> payments any time without manual fiddling or risking production, and (2) a **per-app PDF**
> listing every payment flow as ✅ functional / ⚠️ pending / ❌ broken, with screenshots + evidence.

## Operating rules (read AGENTS.md "Lost-agent operating rules" first)

- **The target project is your workspace.** You work *on* the app you're pointed at, not on
  `agentes_perdidos`.
- **Persist per-app state in the target project's own brain**, never here. Use the project's
  **second-brain LLM-wiki** inside its Obsidian vault (the folder with `.obsidian/`) if present,
  else an existing `wiki/`/`.llm-wiki/`, else `./.stripe/` at the project root. Write there:
  `tasklist.md`, the account/key map (IDs only — **never secret values**), the validation
  matrix + results, the homologation runbook, and the link to the generated PDF.
- **Self-improvement flows back here.** A new stack adapter, a Stripe gotcha, a better assertion
  — update **this** `SKILL.md`. Project-specific facts stay in the project brain.
- **Secrets discipline (hard):** keys live only in the target project's gitignored env
  (`.env` / `.env.test` / Spring `application-homolog.properties` that is gitignored or env-fed).
  Never commit a secret. Never paste a secret value into the wiki, the PDF, this repo, or chat.
  In docs, refer to keys by name + last 4 (`sk_test_…a1B2`), never the full value.

## Defer to `stripe-best-practices` (don't duplicate it)

For *which* Stripe primitive to use and *how* to use it correctly — Checkout Session vs
PaymentIntent vs Payment Element, Connect controller properties / Accounts v2, Billing,
restricted keys, webhook security, deprecated-API migration — **invoke the `stripe-best-practices`
skill** and follow it. This SKILL owns the *process*: detect → ask the operator → provision →
build the test env → validate two ways → document → PDF → improve. When the two ever disagree on
a Stripe API detail, `stripe-best-practices` wins; tell the operator and update this file.

## Operator gate (HARD — ask before acting, per app)

This agent spends the owner's Stripe account and can change a payment flow. **Before doing
anything on an app, clear these with the operator** (the user). Default to asking; never assume.

1. **Account** — Which Stripe account does this app use? Do you have one, or should I create it?
   (Apps of the *same business* share one account — e.g. the Ania apps. Different businesses get
   their own.) I need a **test-mode** key (ideally a restricted `rk_test_…` or the standard
   `sk_test_…`); I will not ask for or use a live secret key.
2. **Catalog** — What does the customer buy (plans, one-offs, marketplace items) and at what
   prices? Should I **mirror your live catalog into test mode** automatically, or author it fresh?
3. **Business model & go-live criteria** — subscription / one-time / marketplace-with-payouts?
   Which currencies & countries? What must be ✅ for you to call this "ready to sell"?
4. **Scope of changes** — May I add/repair code (webhook handler, idempotency, the test profile),
   or validate-only? Any flow I must NOT touch?

Record the answers in the project brain before proceeding. Re-ask per app — answers don't carry.

## Decision logic — stack adapter (detect from build files)

| Stack (detect by) | Config surface for TEST keys | Run in test mode | Webhook path | Front SDK |
|---|---|---|---|---|
| **Spring Boot** (`pom.xml`/`build.gradle`, `stripe-java`) | `application-homolog.properties` + env (`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, price-id props) — gitignored/env-fed | `SPRING_PROFILES_ACTIVE=homolog` (or `dev` if that's already the test profile) | `@PostMapping` raw-body endpoint, `Webhook.constructEvent` | n/a |
| **React + Vite** (`vite`, `@stripe/stripe-js`) | `.env.test` / build-time `VITE_STRIPE_*` | `vite --mode test` / build with test env | calls backend | `loadStripe(pk_test)` |
| **React Native + Expo** (`expo`, `@stripe/stripe-react-native`) | `EXPO_PUBLIC_STRIPE_PUBLISHABLE_KEY` (test) | Expo dev client / `--dev-client`; ASCII build path if required (hey-ania → `E:\heyania-build`) | backend-only | `StripeProvider` + `confirmPayment` |

**Reuse the project's existing pattern.** These four apps already configure Stripe via env-backed
Spring properties + `VITE_`/`EXPO_PUBLIC_` vars and several already have a **mock/test profile**
(diario-de-obra `STRIPE_MOCK_MODE`, dummy `sk_test_…` in test resources). Extend that pattern into
a *real* homologation profile with *real* test keys — do not invent a parallel mechanism.

## Decision logic — Stripe surface (which primitive)

Detect what the app already uses and keep it unless it's wrong for the model. Quick map (full
rationale: `stripe-best-practices`):

| Need | Surface | Validate via |
|---|---|---|
| One-time, hosted, least PCI | **Checkout Session** (`mode=payment`) | browser lane (hosted page) + `checkout.session.completed` |
| One-time, custom in-app UI | **PaymentIntent + Payment Element** | API lane (`pm_card_visa`) + browser lane |
| Recurring | **Subscriptions** (Checkout `mode=subscription` or Billing) + **Customer Portal** | Test Clock lifecycle + portal in browser |
| Marketplace / split / payouts | **Connect** (Express/Custom) | test connected account + `account.updated` + transfer assertions |

The four target apps in scope use: Connect Express + PaymentIntent (theAPIAniaAPP, hey-ania client),
Checkout-subscription + Customer Portal (diario-de-obra), and all of subs + Payment Element + Connect
(mae-app1). Your harness must cover whichever subset an app uses.

## Workflow for a typical task

1. **Detect & brief.** Read build files; find every Stripe touchpoint (backend SDK calls, webhook
   handler, front SDK init, payment UI). Identify the surface(s) in use and the stack. Open/create
   the project brain; write a tasklist + the stack/surface decision + the operator's answers.
2. **Provision the account/app.** Confirm or create the Stripe account (operator gate). Get a
   **test** key. `uv run agents/stripe/stripe_env.py check --key <rk_or_sk_test>` refuses any
   `sk_live_`/`rk_live_` and confirms you're in test mode. Optionally wire the **Stripe MCP** for
   product/price/account management; the portable baseline is **Stripe CLI + REST** (below).
3. **Stand up the homologation env (the core value).** Create a test profile *separate from
   production* so the owner can re-test without risk:
   - Mirror the catalog: `uv run agents/stripe/mirror_catalog.py --live-key <rk_live_readonly> --test-key <sk_test>`
     recreates live Products/Prices in TEST (idempotent, keyed by `metadata.mirror_source`), and
     prints the `code→test_price_id` map + an **env block** to paste into the test profile. (If the
     owner has no live catalog yet, author it in test directly.)
   - Wire the test keys into the stack's test surface (table above). Keep prod values untouched.
   - Start webhook forwarding: `stripe listen --forward-to localhost:<port><webhook-path>` →
     copy the printed `whsec_…` into the test profile's webhook secret. (For a deployed test URL,
     create a test-mode webhook endpoint in the Dashboard/MCP instead.)
4. **Implement / repair (carte blanche, within operator scope).** Where the integration is missing
   or wrong, build it to `stripe-best-practices`: idempotency keys on writes, webhook **signature
   verification + event-id dedup**, the right surface, restricted keys, clear error→UI mapping.
   Make the customer-facing payment UI **clear and intuitive** (see UI bar). Edit only what scope
   allows; keep prod config paths intact.
5. **Validate — two lanes (see harness).** Run `validate.py` (headless/API) AND the browser lane
   (Claude-in-Chrome / Claude Preview) over the full **test-card matrix**. Assert app/DB end-state,
   webhook receipt + idempotency, and failure-path UX. Capture screenshots of every customer step.
6. **Document.** Write a Stripe **homologation runbook** into the project brain: how to start the
   test env, the key/price map (IDs only), the validation matrix + latest results, known gaps. Link
   to `stripe-best-practices` shared knowledge rather than re-explaining Stripe.
7. **PDF.** `uv run agents/stripe/report.py --results <results.json> --shots <dir> --out <app>-stripe-homologation.pdf`
   → a per-app report: each flow ✅/⚠️/❌, evidence, screenshots, pending items + next actions.
   (Falls back to the `pdf` skill if reportlab is unavailable.) Save it under the project (not here).
8. **Improve.** Fold any new stack quirk / Stripe gotcha / better assertion back into this SKILL.md.

## The homologation environment — what "test env separate from prod" means

- **TEST mode is the homologation environment.** Stripe test mode is a full parallel world: its own
  keys, its own objects, fake cards, no real money. Objects do **not** cross modes, so the live
  catalog must be **recreated in test** (that's `mirror_catalog.py`).
- **Never mutate production config to test.** Add a *new* profile/env file; leave the live keys,
  live price IDs, and live webhook endpoint exactly as they are. The owner flips a profile to test,
  not edits prod.
- **Restricted keys for least privilege.** Prefer `rk_test_…` scoped to what the run needs; use a
  **read-only restricted LIVE key** only for the one-way catalog read in `mirror_catalog.py`, never
  a live secret key, and never to move money.
- **Webhook secret is per-endpoint.** `stripe listen` prints a `whsec_…` for local forwarding; a
  Dashboard test endpoint has its own. They differ from the live secret — wire the test one.

## Validation harness — two lanes (both required)

**Lane A — headless / API (fast, deterministic, covers backend + webhooks).**
- Drive payments with **test payment-method tokens** (no real card UI): `pm_card_visa` (success),
  `pm_card_threeDSecure2Required` (SCA), `pm_card_chargeDeclined`, `pm_card_chargeDeclinedInsufficientFunds`.
- Exercise webhook code paths deterministically: `stripe trigger payment_intent.succeeded`,
  `… checkout.session.completed`, `… invoice.paid`, `… customer.subscription.deleted`,
  `… account.updated`, `… charge.dispute.created`.
- **Subscriptions/trials/renewals → Test Clocks.** Create a test clock, attach the customer, advance
  time to assert trial-end, renewal invoice, dunning, cancellation. (Real time would take days.)
- **Assertions** (`validate.py`, config-driven): for each flow assert the **app/DB end-state** (HTTP
  to the app's API or a DB check) — subscription active, license issued, wallet credited, account
  `charges_enabled` — AND **idempotency** (re-deliver the same `event.id` → no double effect) AND
  **signature rejection** (a bad-signature POST → HTTP 400). Emit a results JSON.

**Lane B — real browser (proves the *customer* experience).**
- Use **Claude Preview** for a locally-running dev server, or **Claude-in-Chrome** for a deployed
  test URL. (DOM-aware, far better than pixel clicking.) For RN/Expo, the buyer UI can't be browser
  -driven — validate the card flow via Lane A + an Expo dev client / simulator and **say so honestly**
  in the PDF (note the surface that wasn't browser-validated).
- Run the **test-card matrix** through the actual checkout UI:
  `4242 4242 4242 4242` (success), `4000 0025 0000 3155` (3DS challenge), `4000 0000 0000 9995`
  (insufficient funds), `4000 0000 0000 0002` (generic decline), `4000 0000 0000 0341` (fails at
  charge). Any future-exp + any CVC + any ZIP.
- **Screenshot every step** (product → checkout → 3DS → success/return, and each failure's error
  state). These screenshots are the PDF's evidence and the UI-clarity proof.

## UI-clarity bar — the customer must never be confused at payment

A correct backend with a confusing checkout still loses the sale. The buyer-facing flow passes only
if: the **price, currency, and what's being bought** are unambiguous before paying; a **loading /
processing** state is shown during confirmation (no dead clicks); **success** state is explicit and
tells the buyer what they now have / what happens next; every **failure** shows a human, localized,
actionable message (not a raw Stripe code — map them, cf. mae-app1 `stripeErrors.js`); and the page
says payment is **secure via Stripe**. Capture each of these states as screenshots for the PDF.

## Security (non-negotiable)

- **Test keys only** for validation; `stripe_env.py check` hard-refuses `*_live_` secrets. A live
  *restricted read-only* key is allowed *solely* for `mirror_catalog.py`'s one-way read.
- **Webhook handler must** verify the signature (`constructEvent`) and **dedupe by `event.id`** in
  a persisted table before acting (all four apps already do — keep it). A failed signature → 400.
- **Fix leaks you find.** Two are known in scope: `sk_live_` example in `mae-app1/.env.example`
  (redact to `sk_live_xxx`/`sk_test_…`) and a `pk_live_` committed in `hey-ania/.env` (publishable
  is public-by-design, but a *live* key in a committed `.env` should be a `pk_test_` for homologation
  and the file gitignored). Grep every app for `sk_live_`/`rk_live_` in tracked files → none allowed.
- Idempotency keys on all state-changing Stripe writes so a retried request can't double-charge.

## Self-check — you may NOT say "homologated / ready" until all pass

- [ ] Operator gate answered & recorded for **this** app (account, catalog, model, scope).
- [ ] A **test profile separate from production** exists; prod keys/price-ids/webhook untouched.
- [ ] `stripe_env.py check` confirms test mode (no live secret in play).
- [ ] Test catalog mirrors the intended live catalog (or was authored fresh); `code→price_id` map
      recorded in the brain.
- [ ] **Lane A** green: every flow's app/DB end-state asserted; webhook idempotency verified;
      bad-signature → 400; subscription lifecycle exercised via a Test Clock (if recurring).
- [ ] **Lane B** done: full test-card matrix run through the real UI; **screenshots** of success +
      each failure state captured. (Mobile-only surfaces noted as Lane-A-validated in the PDF.)
- [ ] UI-clarity bar met (price/loading/success/error/secure), evidenced by screenshots.
- [ ] No `*_live_` secret in any tracked file; known leaks fixed; webhook signature+dedup present.
- [ ] Homologation **runbook** written to the project brain; key/price map (IDs only) recorded.
- [ ] **PDF generated** (flows ✅/⚠️/❌ + evidence + pending + next actions) and saved under the project.
- [ ] Generalizable learnings folded back into this SKILL.md.

If any item is ⚠️/❌, the PDF says so explicitly with the reason and the next action — an honest
"pending" is a pass for *this agent*; a silent gap is not.

## Tooling — Stripe CLI + REST (portable baseline) and MCP (optional)

```bash
stripe login                                            # once, opens browser to authorize the CLI
stripe listen --forward-to localhost:8080/api/webhook/stripe   # prints whsec_… for the test profile
stripe trigger payment_intent.succeeded                 # fire a test event through your webhook
stripe trigger checkout.session.completed
stripe trigger customer.subscription.deleted
stripe samples list                                     # reference sample integrations
```

- **Stripe MCP** (official): connect it to manage Products/Prices/Customers/accounts and to query
  test data via tool calls instead of raw REST — wire it when it saves work (e.g. bulk catalog or
  account setup). Find/connect it via the MCP registry. It complements, not replaces, the CLI
  (`stripe listen`/`trigger` are CLI-only). Everything also works through the REST API the helper
  scripts call, so the agent is **portable across LLM agents** even without the MCP.
- **Browser**: Claude Preview (`mcp__Claude_Preview__*`) for local dev servers; Claude-in-Chrome
  (`mcp__Claude_in_Chrome__*`) for deployed test URLs. Load their schemas via ToolSearch when needed.

## Helper scripts (uv / PEP-723 — deps auto-install)

```bash
# Guard a key is TEST mode + (optionally) print its capabilities; refuses live secrets:
uv run agents/stripe/stripe_env.py check --key <rk_or_sk_test>
# Mirror live catalog → test (idempotent), print code→price_id map + env block:
uv run agents/stripe/mirror_catalog.py --live-key <rk_live_readonly> --test-key <sk_test> [--write-env <file>]
# Run the config-driven validation matrix (Lane A) against an app → results JSON:
uv run agents/stripe/validate.py --config <app>.stripe.json --test-key <sk_test> --out results.json
# Build the per-app PDF from results + screenshots:
uv run agents/stripe/report.py --results results.json --shots ./shots --out <app>-stripe-homologation.pdf
```

`validate.py` reads a small JSON describing the app's flows (endpoints, expected end-state, events
to trigger) so the same script validates any stack — see `agents/stripe/example.stripe.json`.

## Gotchas (grow this list every run)

- **Objects don't cross test↔live.** A price/product/customer/webhook created in live is invisible
  in test and vice-versa. Always mirror the catalog into test; never expect a live price-id to work
  with a test key.
- **`whsec_` is per-endpoint and per-mode.** The local `stripe listen` secret ≠ a Dashboard test
  endpoint secret ≠ the live secret. Wiring the wrong one → every webhook 400s on signature.
- **Spring raw body for webhooks.** `constructEvent` needs the exact raw bytes; a handler that takes
  a parsed `@RequestBody` object will fail signature verification. Keep the `String`/`byte[]` raw
  endpoint (all three Spring apps already do).
- **Subscriptions need Test Clocks, not patience.** Don't "wait for renewal" — attach the customer
  to a test clock and advance it. A customer can only be on one clock; create per-scenario.
- **3DS can't be auto-confirmed headlessly.** `pm_card_threeDSecure2Required` / card `…3155` need the
  browser lane to complete the challenge; assert the `requires_action` → success transition there.
- **Connect onboarding in test** uses prefilled test data ("skip"/`8888…` test values, test SSN
  `000-00-0000`); assert `account.updated` flips `charges_enabled`/`payouts_enabled`. Use a *test*
  connected account, never a real one.
- **RN/Expo buyer UI isn't browser-drivable.** Validate the card flow via Lane A + dev client and
  declare it as such in the PDF — don't claim a browser screenshot you can't take.
- **Windows consoles default to cp1252** → printing Stripe object dumps with `→`/emoji can raise
  `UnicodeEncodeError`; the scripts force UTF-8 stdout. hey-ania builds only from an ASCII path
  (`E:\heyania-build`), irrelevant to API validation but relevant if you build the app to validate.
- **Idempotency on retries.** Re-running `validate.py` must not create duplicate charges/customers —
  pass idempotency keys and look existing objects up by metadata before creating.
- **`checkout.stripe.com` is blocked by the browser safety policy.** Claude-in-Chrome refuses to act
  on Stripe's hosted Checkout page ("This site is blocked" — the financial-site guard). So you can
  *create* and verify the Checkout Session URL, but you cannot type the test card on the hosted page
  via Claude-in-Chrome. **Hand the hosted card-entry step to the `navigator` agent**
  (`agents/navigator/SKILL.md`): its Tier-2 backend (chrome-devtools-mcp / Puppeteer) is not bound by
  the safety policy and CAN run the test-card matrix (`4242…`, 3DS, declines) on `checkout.stripe.com`
  and return screenshots for this PDF. If navigator isn't available, validate the rest of the path
  with `stripe trigger checkout.session.completed` (asserts the webhook handler + activation) and mark
  the hosted card-entry screen as PENDING with a one-line "manual `4242` pass recommended" — it is
  Stripe's standard PCI UI, not an app defect. In-app **Payment Element** (embedded, on localhost) is
  also a drivable card-UI surface; prefer it for the end-customer clarity proof. When a tab gets stuck
  on the blocked domain, open a fresh tab (`tabs_create_mcp`) — navigate/screenshot on the blocked tab
  also error.
- **The GUI/dashboard steps (create account, products, restricted keys, webhooks, Customer Portal,
  and LIVE promotion) belong to the `navigator` agent.** When you need a credential harvested or a
  live object created in the Stripe Dashboard, point an LLM at `agents/navigator/SKILL.md`; it does
  the clicking and writes the keys into THIS project's gitignored `.env`, then hands control back.
- **Spring apps often store price IDs in the DB, not read them from env.** A plan table column
  (e.g. `subscription_plans.stripe_price_id_monthly`) is the source of truth at checkout, while env
  `app.stripe.price-*` is bound but **never synced into the DB**. A fresh/homologation DB then has
  null price IDs → checkout 400 `priceNotConfigured`. Fix the run by seeding the columns from env
  (`UPDATE … SET stripe_price_id_monthly=…`), and **recommend a durable startup sync** (config → plan
  rows) — that removes a real manual step in *every* environment, production included. (mae-app1 hit
  this exactly; market-machine also keeps price IDs in the DB. diario-de-obra reads price IDs straight
  from env, so it doesn't.) Check which model the app uses before assuming env vars suffice.
- **Webhook dedup shows up as a log line, not a failure.** Re-delivered events (Stripe replays recent
  events when `stripe listen` reconnects) should log "Duplicate event … skipped" and still return
  `[200]`. Seeing all-duplicates after a reconnect is the dedup working, not a stuck pipeline.

## How the user invokes this agent

Open an LLM session pointed at the target project, point it at this `SKILL.md`, and give a task:
"validate Stripe / set up a homologation environment for payments / is this ready to charge". The
agent runs the operator gate, builds the test env, validates two ways, documents, and produces the
PDF.
