---
brain: shared-base
maintained-by: second-brain agent (agentes_perdidos)
confidential: false
---

# Shared generic base — second-brain

Generic, **non-confidential** knowledge that is identical across every project, kept ONCE here
instead of re-ingested per project. Project brains (which live inside each project's Obsidian
vault) **reference** these pages by path rather than duplicating them. Saves tokens, single
source of truth.

This base is git-tracked in the **public** `agentes_perdidos` repo. **Never** put anything
confidential here — no secrets, IPs, infra configs, or client-private facts. Those live only in
the relevant project's own brain.

## Layout

- `index.md` — catalog (regenerate via `secondbrain.py reindex agents/second-brain/shared`).
- `wiki/` — `overview/ concepts/ sources/ comparisons/ decisions/`.

## What belongs here

- Tooling docs every project uses (Claude Code, `uv`/PEP-723, Obsidian, git workflow).
- Reusable patterns (the LLM-wiki pattern, the lost-agent rule).
- The `agentes_perdidos` agents catalog (so any project brain can link an agent).

## What does NOT belong here

Anything project-specific or confidential. If unsure, it goes in the project brain, not here.
