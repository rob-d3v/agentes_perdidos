---
title: Stripe homologação — owner steps
type: source
created: 2026-06-27
updated: 2026-06-27
sources: [STRIPE-HOMOLOGACAO-O-QUE-FAZER.md]
tags: [source, manual, stripe, homologation, owner-todo]
---

Owner-facing, step-by-step guide (Portuguese) for the exactly-two things only the human can do so the [[stripe]] agent can unblock and validate everything automatically in **homologation (TEST mode)**.

## The golden rules it states
1. **Only TEST keys** (`sk_test_…` / `pk_test_…` / `rk_test_…`) — test mode moves no real money (cards are fictitious, e.g. `4242 4242 4242 4242`).
2. **Never pass or paste a LIVE key** (`sk_live_…`). If an app already has a live key in its local `.env`, **swap it for a test key locally** — this affects only your machine; the VPS (Coolify) prod env is **untouched**.
3. **Why these two are yours, not the agent's:** by security rule the agent does **not create accounts** nor **handle secret keys via the browser** (protects against hijacked-agent attacks; Stripe domains also block browser automation). So: **create account + grab the test key = you; everything else = the agent.**
4. **Where the key goes:** the project's gitignored `.env` (or `.env.test`), then tell the agent "the key for app X is in `.env`".

## What it covers
- **Part 0** — how to grab a TEST key in both Stripe dashboard formats (Sandboxes vs Test-mode toggle), incl. the shortcut `dashboard.stripe.com/test/apikeys`, and the optional restricted-key path.
- **Part 1** — per-app instructions (🟢 SUA PARTE / 🔵 MINHA PARTE) for Ania (theAPIAniaAPP + hey-ania, same account), diário-de-obra (ObraVision), and the others; which accounts already exist vs need creating (PostPop, tio-marco).

## What it changes in the brain
Backs the [[stripe]] entity page (the homologation workflow + TEST-only discipline) and the [[stripe]] ↔ [[navigator]] division of labor (navigator does the `checkout.stripe.com` + live-setup GUI work the owner doesn't). No secret values appear. Source: `STRIPE-HOMOLOGACAO-O-QUE-FAZER.md` at the repo root. See [[agentes-perdidos]].
