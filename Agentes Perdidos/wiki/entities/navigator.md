---
title: navigator agent
type: entity
created: 2026-06-27
updated: 2026-06-27
sources: [agents/navigator/SKILL.md]
tags: [agent, browser, gui, credentials, stripe, oauth, env]
---

Browser-driving **GUI agent** that does the web-dashboard work code-only agents can't — because Claude-in-Chrome refuses financial surfaces like `dashboard.stripe.com` / `checkout.stripe.com` ("This site is blocked"). navigator logs into dashboards, fills forms, completes hosted-checkout card entry, and **harvests** credentials/IDs which it writes into the **target project's** gitignored `.env` — **never** into `agentes_perdidos`.

## What it is / is NOT
- **Is:** a GUI operator + credential harvester + env writer. Creates Stripe structure where missing and harvests from accounts already set up, in both TEST and LIVE mode (live setup is a *configuration* act, never a payment).
- **Is NOT:** a code integrator (that's [[stripe]]), and **NOT a money-mover** — never places an order, sends money, or runs a real charge. Only Stripe TEST cards on TEST-mode sessions.

## The 4-tier browser backend ladder
Always run `backend_check.py` first — it reports which tier is actually up. Tier is a **routing signal, not a bug** — if Tier 1 refuses a surface, switch tier, don't debug.

| Tier | Backend | When |
|---|---|---|
| **1** | Claude-in-Chrome MCP | non-financial: Coolify / Dokploy env panels, OAuth consoles |
| **2** | chrome-devtools-mcp (Puppeteer) | `dashboard.stripe.com` — products, keys, webhooks, portal, harvest (Tier 1 refuses Stripe) |
| **3** | hermes Camofox / CDP / VPS stealth | anti-detection, bot-walled login, local Chrome blocked |
| **4** | computer-use | last resort |

## How it's invoked
Point an LLM at `agents/navigator/SKILL.md` + the target project, give a GUI task ("log into Stripe and harvest the keys", "create the live products + restricted key + webhook", "create the Google + Facebook OAuth apps", "create the reCAPTCHA keys", "set the env vars in Coolify/Dokploy"). Helper scripts:
- `uv run agents/navigator/backend_check.py` — probe which tier is up (run FIRST).
- `uv run agents/navigator/playbook_run.py --playbook auth|stripe --surface <key> --mode test|live` — execute a playbook surface (data in `auth_playbook.json` / `stripe_playbook.json` / `app_playbook.json`).
- `uv run agents/navigator/secrets_writer.py ...` — write harvested keys/IDs into `<project>/.env` (GUARD-5 refuses a secret in a public var).

## Env keys (names only — never values)
Per-tier backend config: `CHROME_REMOTE_DEBUG_URL`, `BROWSER_CDP_URL`, `CAMOFOX_URL`, `HERMES_VPS_HOST`. The keys it *harvests* (Stripe `sk_`/`rk_`/`pk_`/`whsec_`, OAuth client ids/secrets, captcha site/secret keys) are written to the **target** `.env`, never stored here.

## Division of labor (it is the hands; the others are brains)
- **[[stripe]] ↔ navigator:** stripe owns SDK code + Lane A/B validation + PDF; navigator writes real keys/IDs into the target `.env`, completes `checkout.stripe.com` (the surface stripe marks PENDING), hands back a key-map (IDs + last-4) + screenshots.
- **[[social-auth]] / [[captcha]] ↔ navigator:** those agents own the integration + server verification + validation; navigator creates the Google/Facebook OAuth apps and reCAPTCHA/Turnstile keys in their consoles and harvests them into the target `.env`.

Per [[lost-agent-rule]]: runbook + key-map (IDs + **last-4 only**) live in the **target project's** brain, never here. See [[agentes-perdidos]]. Runs via [[uv]].
