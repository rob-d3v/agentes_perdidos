---
title: Guia Resend — transactional email owner steps
type: source
created: 2026-06-27
updated: 2026-06-27
sources: [GUIA-RESEND-passos-manuais.pdf]
tags: [source, manual, resend, email, owner-todo, security]
---

Owner-facing guide (Portuguese, PDF, updated 2026-06-14) for the **Resend transactional-email** rollout: what was already done and the deploy/VPS/secret steps that depend on the human. No keys/passwords appear in it.

## Already done (don't redo)
- **6 apps** wired with transactional email (confirm account, reset password, welcome) — code complete, compiles.
- Domain **housestudio.online VERIFIED** in Resend + production proven (real send → delivered). **5/5 backends validated live**; hey-ania is the mobile client.
- **Cost decision:** all apps (incl. Ania) send from the **same** `housestudio.online` — no 2nd domain, no paid plan (Resend free, R$0).
- Boot alert: if the key is empty in production, the startup log shouts (fallback). Restricted **sending-only** keys minted and written to each app's **local** gitignored `.env`. The 6 feature branches merged **locally** (not pushed). 6 homologation PDFs in each worktree's `.resend/`.

## What's left (owner, in order)
1. Review the diffs + **push + deploy** (coolify-vps), app by app.
2. **Set VPS env vars per app**: `RESEND_API_KEY` (restricted key; empty = email off), the webhook secret (`RESEND_WEBHOOK_SECRET`; in theAPIAniaAPP = `ANIA_RESEND_WEBHOOK_SECRET`), `FRONTEND_BASE_URL`, and theAPIAniaAPP's `ANIA_MOBILE_DEEPLINK_BASE` (= `hey-ania://auth/`).
3. **Register the webhook per app** (needs the app live + a public URL) via `uv run agents/resend/resend_admin.py webhooks create …` — the signing secret (`whsec_…`) shows once.
4. **🔴 Security (urgent): rotate 2 committed secrets** — diário-de-obra (Google OAuth `client_secret` in docs/ + plaintext default in `application.properties`, plus the JWT secret) and theAPIAniaAPP (`VITE_AVATAR_PASSWORD`, an n8n webhook URL + API key in `GUIDE.md`). Rotate, move to env, purge from git history (filter-repo/BFG).
5. (Optional) translate ~190 languages via the [[i18n]] agent. 6. Final production check (signup email arrives, reset link works, Resend logs show webhook events, bounces/complaints enter suppression).

## What it changes in the brain
Documents a **resend** agent / workflow not yet in the README agent table (only env-var names + ops referenced; no secret values). Flags an **owner security action** (rotate committed secrets) and confirms env-var **names** for the transactional-email surface. Source: `GUIA-RESEND-passos-manuais.pdf` at the repo root. See [[agentes-perdidos]] · [[i18n]].

> ⚠️ Note: this guide references an `agents/resend/resend_admin.py` helper and a "resend" agent that are **not present** in the current `agents/` tree or the README table — likely a separate/forthcoming agent. Recorded here for the owner; no resend entity page created (no agent folder to back it).
