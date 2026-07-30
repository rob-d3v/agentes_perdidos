---
title: agentes_perdidos — quickref / operating contract
type: overview
created: 2026-07-30
updated: 2026-07-30
sources: [README.md, AGENTS.md]
tags: [quickref, operating-contract, agents]
---

One-page operating contract for working in this repo — read this first, follow links for depth. State as of **2026-07-30** (branch `feat/social-auth-captcha-agents`; the 6 newest agents + navigator auth playbooks are still **uncommitted** working-tree).

## The 19 agents, by family
- **Assets/UI:** [[image-creator]] (3-API routing; repeatable `--ref` = face-swap) · [[bucket]] (R2/B2 offload + private B2 backup primitive) · [[design-reviewer]] (plan-only redesign)
- **Infra/ops:** [[cloudflare]] (whole CF account; CORS GET-merge-PUT rule) · [[guardian]] (VPS backup daemon, 3d/3w B2 retention) · [[navigator]] (4-tier browser GUI hands; harvests creds into target `.env`)
- **Payments/auth trio:** [[stripe]] · [[social-auth]] · [[captcha]] — all "code + validation + PDF" brains; navigator is their hands (`stripe_playbook.json` / `auth_playbook.json`)
- **Quality/security quartet (new 2026-06-27):** [[security-reviewer]] (2-layer SAST+AI, read-only) · [[architecture-auditor]] (metrics + roadmap, read-only) · [[clean-refactorer]] (executes the roadmap behind a golden-master net) · [[performance-engineer]] (measure→fix-one→re-measure)
- **Repo hygiene:** [[branch-consolidator]] ("MAIN"; deploy branch sacred, only provably-merged deleted)
- **Content/knowledge:** [[i18n]] (pt-BR+en AI base + ~190 free langs; `merge_keys.py` now does i18next JSON too) · [[ai-visibility]] (GEO/AEO; Element 0 = SPA extractability) · [[remodeling]] (real-identity remodel, anti-fake rule) · [[second-brain]] (this wiki's maintainer) · [[lost-finder]] (content-based file hunt; presets `esquadro` + `escritores`, new `docs` stage)

## Inviolables (full text in AGENTS.md + each SKILL.md)
1. [[lost-agent-rule]] — the *target* project is the workspace; state goes in the **target's brain** (Obsidian-vault second-brain → `.llm-wiki/`/`wiki/` → `./.<agent>/`), never in this repo.
2. **Secrets:** values only in gitignored `.env`; names documented in `.env.example`; this repo is PUBLIC — never a value in any committed file, wiki page, or PDF. Navigator's GUARD-5 refuses secrets in `VITE_/EXPO_PUBLIC_`-style public vars.
3. [[shared-base-model]] — generic knowledge once in `agents/second-brain/shared/`, linked not duplicated; confidential brains never leave their project.
4. Read-only diagnostics ([[security-reviewer]], [[architecture-auditor]]) never edit source; behavior-changing agents work in revertible slices on feature branches, never main.
5. Python helpers run via [[uv]] + PEP-723 — no venv. Exception: [[guardian]] runs on-server via cron.

## Adding an agent
`agents/<kebab-name>/SKILL.md` (frontmatter `name` + when-to-use `description`), code via uv, env names in `.env.example`, row in README table — contract in `AGENTS.md`.

## Owner-action docs
[[stripe-homologacao]] · [[manual-actions-social-auth-captcha]] · [[guia-resend-passos-manuais]] · [[skills-oportunidades]] (survey of public catalog skills — nothing installed).

Front door with more depth: [[agentes-perdidos]].
