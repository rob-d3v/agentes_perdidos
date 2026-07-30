---
title: Skills públicas — oportunidades para os agentes
type: source
created: 2026-07-30
updated: 2026-07-30
sources: [SKILLS-OPORTUNIDADES.md]
tags: [source, skills, catalog, comparison]
---

Survey (Portuguese, repo-root `SKILLS-OPORTUNIDADES.md`) comparing all 19 agents against public skills from the skills.sh catalog — read via `find-skills` + WebFetch, **nothing installed, no SKILL.md edited**.

## Headline conclusions
- Most catalog skills are **strictly weaker** than the in-house agents: no backup-before-delete ([[branch-consolidator]]), no golden-master net ([[clean-refactorer]]), no behavior oracle ([[performance-engineer]]), no Element-0 SPA-extractability gate ([[ai-visibility]]), no fail-closed siteverify emphasis ([[captcha]]). Reported gain: low/none for those.
- Genuinely worth watching: **`cloudflare/skills@wrangler`** (official, 39.4K installs) as an always-current wrangler syntax reference for [[cloudflare]]; **`cloudflare/skills@turnstile-spin`** (official) covering the full Turnstile flow that today is split between [[cloudflare]] (widget) and [[captcha]] (code + verify); a possible optional **auto-fix mode** for [[design-reviewer]] inspired by `nexu-io/open-design@design-review` (atomic commits + before/after screenshots for trivial low-risk items).
- [[stripe]] already defers API choice to the installed `stripe-best-practices` skill; catalog Stripe skills add nothing over its homologation harness.

Honest-reporting rule followed: skills whose page didn't confirm details are marked "não confirmado" rather than assumed. See [[agentes-perdidos]].
