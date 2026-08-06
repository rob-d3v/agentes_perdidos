---
title: Webhook signature verification + idempotency
type: concept
created: 2026-06-27
updated: 2026-06-27
sources: []
tags: [security, webhooks, a08, integrity, shared]
---

# Webhook signature verification + idempotency

Every public / `permitAll` webhook endpoint MUST **verify the provider's signature and enforce
idempotency BEFORE acting** on the payload — an unauthenticated webhook is an attacker-callable
endpoint, and the #1 real webhook bug in the wild is an endpoint that simply never verifies. Maps to
[[owasp-top-10-2021-mapping|A08 Software & Data Integrity Failures]] (trusting unverified data).

## Why it's dangerous
Webhook routes are public by necessity (the provider calls them, not a logged-in user), so the
provider's signature is the **only** authentication. Skip it and anyone who knows the URL can POST a
fake `payment.succeeded`, `order.paid`, or `message.received` and drive your business logic. Skip
idempotency and a legitimate **retry** (providers retry on timeout) double-processes — double-ships,
double-credits.

## The rule
1. Read the **raw request body** (signature is computed over raw bytes — a JSON re-serialize breaks
   it; e.g. Express needs `express.raw`, Spring a raw-body filter).
2. **Verify the signature** with the provider's library/secret before any parsing-driven action.
3. **Enforce idempotency**: persist the provider event id; if seen, ack `200` and no-op.
4. Then process. Return `2xx` only after durably recording, so retries are safe.

## Per-provider verification
- **Stripe** — `stripe.webhooks.constructEvent(rawBody, sig, endpointSecret)`; throws on bad sig. For **Connect**, verify against the **connected-account's** signing secret, not the platform's.
- **Efí / PIX (BR)** — validate the configured mTLS client cert / HMAC per Efí's webhook setup before trusting a PIX confirmation.
- **Resend** — Svix-style signature headers (`svix-id`, `svix-timestamp`, `svix-signature`); verify with the signing secret.
- **WhatsApp Cloud / Evolution API** — verify `X-Hub-Signature-256` (HMAC-SHA256 over raw body with the app secret).
- **GitHub** — verify `X-Hub-Signature-256` against the webhook secret.

## Detection
`rg -n "express\.raw|bodyParser\.raw|@RequestBody.*byte\[\]"` near webhook routes, then confirm a
`constructEvent` / HMAC compare exists **before** the side effect. A `permitAll` route with no verify
call is the bug.

Related: [[per-stack-owasp-checklist]] · [[owasp-top-10-2021-mapping]] · [[two-layer-security-review]]
