---
title: social-auth agent
type: entity
created: 2026-06-27
updated: 2026-06-27
sources: [agents/social-auth/SKILL.md, MANUAL-ACTIONS-social-auth-captcha.md]
tags: [agent, auth, oauth, social-login, google, facebook, security]
---

Implements **and validates** "Sign in with Google / Facebook" wired into a project's **existing** user system — so a user logs in with an account they already have instead of (or alongside) email+password, landing on the **same** user account. Equal parts integrator and QA engineer; it never weakens the app's existing auth (social login is an *additional* path into the *same* user system).

## What it does
- Detects the stack (Spring Boot / FastAPI / React-Vite / Next / React-Native-Expo / JavaFX desktop) and the existing auth mechanism (JWT, session, file-store).
- Adds a backend **token verifier** (verify Google ID token; exchange Facebook code → verify), a **find-or-LINK-or-create** user step keyed on the **provider-verified email** (link only on a verified email → **no account-takeover**, modelled in a `user_oauth_identities`-style table), and the provider buttons on the existing login/signup UI.
- Two-lane validation: headless token-verify + a real **browser login via [[navigator]]**. Emits a **per-app PDF** marking each provider × surface ✅ functional / ⚠️ pending / ❌ broken.
- **X (Twitter)** has an adapter but ships **flag-off** (`X_LOGIN_ENABLED=false`) — its free API tier ended Feb 2026 (pay-per-use).

## How it's invoked
Point an LLM at `agents/social-auth/SKILL.md` + the project, give a task ("add Google/Facebook login", "wire social OAuth into our auth", "is social login working"). Helper scripts:
- `uv run agents/social-auth/verify_token.py --config <app>.social.json [--id-token <jwt>]` — backend token-verify lane (config shape in `example.social.json`).
- `uv run agents/social-auth/oauth_env.py check --env <project>/.env` — confirms required OAuth env vars present.
- `uv run agents/social-auth/report.py --results results.json --shots ./shots --out <app>-social-auth.pdf`.

## Env keys (names only — never values)
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (backend-only); Facebook app id + app secret; `X_LOGIN_ENABLED` (default false).
- > ⚠️ Client secrets are backend-only — never in a `VITE_`/`EXPO_PUBLIC_`/`NEXT_PUBLIC_` var, the wiki, the PDF, this repo, or chat.

## Division of labor with navigator
social-auth = the **code + linking-model + security + validation + PDF** brain. It hands [[navigator]] the exact **redirect URIs / client types** it needs; navigator **creates the Google/Facebook OAuth apps** in their consoles and **harvests** the client ids/secrets into the **target project's** `.env`. Same pairing as [[captcha]] and [[stripe]]. The shared manual checklist is [[manual-actions-social-auth-captcha]].

Per [[lost-agent-rule]]: per-app state goes in the **target project's** brain, never here. See [[agentes-perdidos]]. Runs via [[uv]].
