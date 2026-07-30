---
title: agentes_perdidos — repo overview
type: overview
created: 2026-06-14
updated: 2026-07-30
sources: [README.md, AGENTS.md, MANUAL-ACTIONS-social-auth-captcha.md, STRIPE-HOMOLOGACAO-O-QUE-FAZER.md, GUIA-RESEND-passos-manuais.pdf, SKILLS-OPORTUNIDADES.md]
tags: [agentes-perdidos, overview, agents]
---

A public collection of self-contained **AI agents**, each a folder under `agents/<name>/` with a `SKILL.md` (its brain) plus any code it needs. You drive one by opening an LLM coding session (Claude Code, Codex, OpenCode, …) **in any target project**, pointing it at the agent's `SKILL.md`, and giving it a task — the agent reads its instructions and executes against that project.

This brain is the repo documenting *itself* as a project. For the generic shared catalog of the agents (kept once, linked by every project brain) see the shared base page `agentes-perdidos-agents` (path: `agents/second-brain/shared/wiki/overview/agentes-perdidos-agents.md`).

## What the repo is
- **Purpose**: reusable agents for real recurring tasks (asset generation, CDN offload, design review, lost-file recovery, i18n, identity remodeling, knowledge management). Public — anyone with access can run them.
- **Stack**: Python scripts run via [[uv]] with PEP-723 inline metadata (no venv setup). Markdown-driven brains. No build system; the "code" is mostly per-agent helper scripts.
- **Secrets**: keys live in `.env` only (gitignored), templated by `.env.example`. Key names by area (values never recorded): assets `OPENAI_API_KEY`, `GEMINI_API_KEY`, `KLING_ACCESS_KEY`, `KLING_SECRET_KEY`; storage `R2_*` (public CDN) + `B2_*` / `B2_PRIVATE_*` (archival, [[guardian]] backups); payments `STRIPE_TEST_*` + `STRIPE_LIVE_READONLY_KEY` ([[stripe]]); social login `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` + Facebook app creds + `X_LOGIN_ENABLED` ([[social-auth]]); captcha site/secret keys + `RECAPTCHA_ENABLED` ([[captcha]]); browser backends `CHROME_REMOTE_DEBUG_URL`, `BROWSER_CDP_URL`, `CAMOFOX_URL`, `HERMES_VPS_HOST` ([[navigator]]); Cloudflare account `ACCOUNT_ID_CLOUDFLARE`, `TOKEN_API_CLOUDFRARE` (typo intentional), `ACCESS_KEY_CLOUDFLARE`/`SECRET_ACCESS_KEY_CLOUDFLARE`, `S3_API_ENDPOINT_CLOUDFLARE` ([[cloudflare]]).

## Layout
```
agentes_perdidos/
├── .env.example      # copy to .env, never commit .env
├── README.md         # agent table + how-to-use
├── AGENTS.md         # contract for adding an agent
└── agents/<name>/    # SKILL.md (+ code) per agent
```

## The agents (one entity page each — 19 as of 2026-07-30)
[[image-creator]] · [[bucket]] · [[cloudflare]] · [[design-reviewer]] · [[lost-finder]] · [[i18n]] · [[remodeling]] · [[second-brain]] · [[stripe]] · [[social-auth]] · [[captcha]] · [[navigator]] · [[ai-visibility]] · [[guardian]] · [[security-reviewer]] · [[architecture-auditor]] · [[performance-engineer]] · [[clean-refactorer]] · [[branch-consolidator]]

The **payments + auth trio** ([[stripe]], [[social-auth]], [[captcha]]) are all "code + validation + PDF" brains that pair with [[navigator]] — the browser/GUI hands that create accounts/apps/keys in dashboards and harvest credentials into the *target* project's `.env` (navigator now ships an `auth_playbook.json` for the Google/Facebook/reCAPTCHA consoles alongside its Stripe playbook). The **quality/security quartet** ([[security-reviewer]], [[architecture-auditor]], [[performance-engineer]], [[clean-refactorer]]) splits diagnose-vs-execute: the first two are read-only diagnostics, clean-refactorer executes the auditor's roadmap behind a golden-master net, performance-engineer optimizes with a behavior oracle. [[branch-consolidator]] ("MAIN") cleans branch sprawl without touching the deploy branch. [[cloudflare]] drives the owner's whole Cloudflare account. [[guardian]] is the only agent that runs *on a server* (cron, not [[uv]]).

> Working-tree note (2026-07-30): the six newest agents (cloudflare + the quartet + branch-consolidator), the navigator auth playbooks, and the README/AGENTS updates are **uncommitted** on branch `feat/social-auth-captcha-agents` — last commit is fa68a9a (2026-06-23).

Quick operating contract: [[agentes-perdidos-quickref]].

## Core concepts
- [[lost-agent-rule]] — every agent treats the *target* project as its workspace.
- [[shared-base-model]] — generic knowledge kept once, linked not duplicated.

## Owner-action source docs (manual steps only the human can do)
- [[stripe-homologacao]] — grab a Stripe TEST key per app so [[stripe]] can validate.
- [[manual-actions-social-auth-captcha]] — provider logins/console clicks for [[social-auth]] + [[captcha]].
- [[guia-resend-passos-manuais]] — transactional-email (Resend) deploy + a flagged urgent secret-rotation.
- [[skills-oportunidades]] — survey of public skills.sh catalog vs the 19 agents (nothing installed; two official Cloudflare skills worth watching).

## How to add an agent
Make `agents/<kebab-name>/`, write a `SKILL.md` (frontmatter `name` matching the folder + a `description` saying when to use it and how it decides, then decision logic / commands / workflow / gotchas), add any code (`uv` + PEP-723), list new env vars in `.env.example`, and register a row in the README table. Full contract in `AGENTS.md`.

Related shared pages: agentes-perdidos-agents · [[llm-wiki-pattern]] · [[uv]] · claude-code-best-practices.
