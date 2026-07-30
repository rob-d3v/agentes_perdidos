---
title: captcha agent
type: entity
created: 2026-06-27
updated: 2026-06-27
sources: [agents/captcha/SKILL.md, MANUAL-ACTIONS-social-auth-captcha.md]
tags: [agent, captcha, security, bot-protection, recaptcha, turnstile]
---

Implements **and validates** bot-protection (CAPTCHA) on a project's auth + abuse-prone forms (login, register, forgot-password, contact, waitlist) end-to-end. The headline rule: the **server is the gate, not the widget** — the #1 real-world captcha bug is a widget rendered on the page but **never verified on the backend** (or verified fail-open).

## What it does
- **Default provider: Google reCAPTCHA** — v3 invisible score on login/register + a v2 checkbox fallback for low-scoring users. **Cloudflare Turnstile** is a drop-in alternative adapter (same two-leg shape).
- Detects the stack (Spring Boot / FastAPI / React-Vite / Next / React-Native-Expo), renders the widget on existing forms with the **PUBLIC site key**, and adds the **mandatory server-side `siteverify`** that **fails closed** and runs *before* the form's action (credential check / account create).
- Validates deterministically with the provider's **TEST KEYS** (always-pass / always-block) so the harness needs no human solving, plus a real browser pass. Emits a **per-app PDF** marking each form ✅ enforced / ⚠️ widget-only / ❌ missing.

## How it's invoked
Point an LLM at `agents/captcha/SKILL.md` + the target project, give a task ("add a captcha", "stop bot signups", "is the captcha actually verified server-side"). Helper scripts:
- `uv run agents/captcha/captcha_check.py --config <app>.captcha.json` — static + live check that verification is wired and fails closed (config shape in `example.captcha.json`).
- `uv run agents/captcha/report.py ...` — emits the per-app PDF.

## Env keys (names only — never values)
- Frontend (PUBLIC, ships in bundle): the reCAPTCHA/Turnstile **site key** (e.g. `*_SITE_KEY`).
- Backend (secret, never in a `VITE_`/`REACT_APP_`/`EXPO_PUBLIC_`/`NEXT_PUBLIC_` var): the **secret key** + `RECAPTCHA_ENABLED`.
- Validation uses provider TEST keys (`RECAPTCHA_TEST_SECRET`, `RECAPTCHA_TEST_RESPONSE`).
- > ⚠️ Site key is PUBLIC; secret key is backend-only — never in the wiki, PDF, this repo, or chat. [[navigator]]'s `secrets_writer.py` GUARD-5 refuses a secret written into a public var.

## Division of labor with navigator
captcha = the **code + server-verification + validation + PDF** brain. It does **not** click the provider console or harvest keys — [[navigator]] creates the reCAPTCHA/Turnstile keys in their consoles and writes site/secret keys into the **target project's** `.env`. Pairs the same way as [[social-auth]] and [[stripe]].

Per [[lost-agent-rule]]: persists per-app state (protected forms, site-key id, secret-key name+last-4, score threshold, validation matrix) in the **target project's** brain (`.obsidian/` vault → `.llm-wiki/` → `./.captcha/`), never here. See [[agentes-perdidos]]. Runs via [[uv]].
