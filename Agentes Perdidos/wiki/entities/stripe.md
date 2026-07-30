---
title: stripe agent
type: entity
created: 2026-06-27
updated: 2026-06-27
sources: [agents/stripe/SKILL.md, STRIPE-HOMOLOGACAO-O-QUE-FAZER.md]
tags: [agent, stripe, payments, homologation, validation, qa]
---

Implements **and validates** a faithful Stripe integration on any project end-to-end using **homologation (TEST-mode) keys**, so a client's business is provably ready to sell — without ever touching live money to validate (**homologation = Stripe TEST mode**).

## What it does
- Detects the stack (Spring Boot / React-Vite / RN-Expo) and the **Stripe surface** in use: Checkout Session, PaymentIntent + Payment Element, Subscriptions + Customer Portal, or Connect.
- Provisions a Stripe account/app if missing (via [[navigator]]), stands up a **TEST environment separate from production** (test keys, a **mirrored test catalog**, Stripe-CLI webhook forwarding).
- Runs a **two-lane validation harness**: Lane A headless API (test PM tokens, `stripe trigger`, Test Clocks) + Lane B real **browser checkout** (test-card matrix, screenshots) — asserting app + DB end-state, **webhook signature & idempotency**, and a clear customer payment UI.
- Documents it in the project's LLM-wiki and emits a **per-app PDF** of functional vs pending. Defers Stripe-correctness details to the `stripe-best-practices` skill.

## How it's invoked
Point an LLM at `agents/stripe/SKILL.md` + the project, give a task ("add / fix / validate Stripe", "set up a homologation env", "is this app ready to charge customers"). Helper scripts:
- `uv run agents/stripe/stripe_env.py check --key <rk_or_sk_test>` — verify a TEST key works.
- `uv run agents/stripe/mirror_catalog.py --live-key <rk_live_readonly> --test-key <sk_test> [--write-env <file>]` — mirror prod catalog into TEST.
- `uv run agents/stripe/validate.py --config <app>.stripe.json --test-key <sk_test> --out results.json` (config shape in `example.stripe.json`).
- `uv run agents/stripe/report.py --results results.json --shots ./shots --out <app>-stripe-homologation.pdf`.

## Env keys (names only — never values)
`STRIPE_TEST_SECRET_KEY`, `STRIPE_TEST_PUBLISHABLE_KEY`, `STRIPE_TEST_WEBHOOK_SECRET`, `STRIPE_LIVE_READONLY_KEY` (read-only, only to mirror the catalog).
- > ⚠️ **Never** pass or paste a LIVE secret key (`sk_live_…`). Only TEST keys validate. If an app has a live key in its local `.env`, swap it for a test key **locally only** — the VPS prod env is never touched.

## Division of labor with navigator
stripe = the **code + test-env + validation + docs + PDF** brain. It hands [[navigator]] its blocker work — `checkout.stripe.com` card entry (Claude-in-Chrome refuses Stripe surfaces), creating live products / live restricted keys / enabling the live portal — and navigator **harvests** keys/IDs into the **target project's** `.env`, returning a key-map (IDs + last-4) + screenshots so stripe can wire + validate. Same pairing as [[captcha]] and [[social-auth]]. The owner's manual checklist is [[stripe-homologacao]].

Per [[lost-agent-rule]]: per-app state (account/key map as IDs only, validation matrix, runbook, PDF link) goes in the **target project's** brain, never here — no secret values in `agentes_perdidos`. See [[agentes-perdidos]]. Runs via [[uv]].
