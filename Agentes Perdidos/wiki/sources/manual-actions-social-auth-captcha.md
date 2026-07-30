---
title: Manual actions — social-auth + captcha
type: source
created: 2026-06-27
updated: 2026-06-27
sources: [MANUAL-ACTIONS-social-auth-captcha.md]
tags: [source, manual, social-auth, captcha, oauth, recaptcha, owner-todo]
---

The single owner-facing checklist of things **only the human can do** to ship Google + Facebook login + Google reCAPTCHA across the operator's apps (diário-de-obra, House Studio / mae-app1, tio-marco, Ania = theAPIAniaAPP web + hey-ania mobile + AnimatedAvatar desktop, My Lost Paradise, PostPop / market-machine). Everything else (the code, the console clicks) is done by the [[social-auth]] + [[captcha]] + [[navigator]] agents.

## What it records
- **Code rollout status: already done.** All code is written and committed to branch `feat/social-auth-captcha` per repo (NOT pushed, NOT deployed, NOT merged — review then merge). Each repo also has a runbook in its project brain. Notably **fixed a pre-existing broken Google flow** in diário-de-obra (auth-code → GIS ID-token) plus a `userId` bug.
- **The manual leftovers** (legend: 🔑 one-time login · 🖱️ console click/decision · ⏳ propagation/review delay · 🤖 navigator can click once you're logged in): interactive provider logins, provider-side decisions, and store/verification steps that can't be automated.
- **X/Twitter is intentionally NOT wired** — free tier ended Feb 2026 (pay-per-use); the adapter sits behind `X_LOGIN_ENABLED=false`.

## What it changes in the brain
Backs the [[social-auth]] and [[captcha]] entity pages (the agents' division of labor with [[navigator]]) and the per-app rollout state. Source doc: `MANUAL-ACTIONS-social-auth-captcha.md` at the repo root. No secret values appear in it. See [[agentes-perdidos]].
