---
title: design-reviewer agent
type: entity
created: 2026-06-14
updated: 2026-06-14
sources: [agents/design-reviewer/SKILL.md]
tags: [agent, design-reviewer, ui]
---

Senior product-designer agent. Reviews an app's UI, diagnoses what looks amateurish and **why**, and produces a professional, implementation-ready redesign/refactor plan that preserves all existing functionality. Covers layout, visual hierarchy, spacing, type, color, motion, window/chrome, branding/mascot ideas, plus a concrete **AI-asset list** (prompts + target paths) routed to [[image-creator]]. Also audits which generated assets are actually used.

## Core principles
- **Function is sacred** — visual + structural work only, never a behavior change.
- **Diagnose before prescribing** — name specific problems (misalignment, weak hierarchy, cramped/empty space, flat color) and why they read as amateurish.
- **Hierarchy first**, then **system not one-offs** (reuse existing design tokens: spacing/type scale, tight palette, consistent radii/shadows/motion).
- **Theme & emotion** match the product's vibe; taste guardrails (whitespace, grid, one focal point, subtle depth).

## Key files
- `agents/design-reviewer/SKILL.md` — brain + workflow (audit → plan → asset spec).
- Pairs with [[image-creator]] for generating new art.

See [[agentes-perdidos]].
