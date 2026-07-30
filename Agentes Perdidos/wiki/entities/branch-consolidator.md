---
title: branch-consolidator agent
type: entity
created: 2026-07-30
updated: 2026-07-30
sources: [agents/branch-consolidator/SKILL.md]
tags: [agent, git, branches, cleanup, deploy-safety]
---

The **"MAIN" agent** — consolidates a repo's history onto its **real main line** and prunes the dead branches AI coding sessions leave behind, without losing work or breaking the deploy.

## Two unbreakable rules
1. **The deploy branch is sacred.** Whatever branch the VPS/PaaS actually deploys from IS the real main — never deleted, renamed, force-pushed, or merged into unreviewed.
2. **Never destroy unmerged work blind.** A branch with unique commits is *surfaced* (its unique commits summarized) for a human merge decision — never auto-deleted. Only **provably-merged** branches get deleted, and only after a full backup.

## How it finds the real main (priority order)
Explicit `--deploy-branch` / `.branch-policy` file → fleet-brain deploy-branch map → **the PaaS itself** (Coolify/Dokploy config — most authoritative) → `origin/HEAD` remote default → name heuristic (`main` > `master` > `production` > `deploy` > `release`) → **ask**. No deletions until the deploy branch is known.

## Safety design
Read-only `audit` mode by default (`branchaudit.py`); before any deletion `consolidate.py` writes a `git bundle --all` backup + per-branch recovery tags + sha map; deletions use safe `git branch -d` on provably-merged branches only. Reversible by design (bundle + backup refs + reflog).

Motivating cases (per the owner's fleet): diario-de-obra with ~45 branches, dduo with 25 stranded commits. Per [[lost-agent-rule]], per-repo branch maps and decisions go in the target project's brain. Key files: `agents/branch-consolidator/{SKILL.md,branchaudit.py,consolidate.py}` (run via [[uv]]). See [[agentes-perdidos]].
