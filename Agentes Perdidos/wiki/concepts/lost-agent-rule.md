---
title: Lost-agent rule
type: concept
created: 2026-06-14
updated: 2026-06-14
sources: [AGENTS.md, README.md]
tags: [convention, agents, lost-agent]
---

Every agent in [[agentes-perdidos]] treats the **target project as its workspace** — it is "lost" in someone else's codebase and works *on* that project, not on `agentes_perdidos`.

Three rules (from `AGENTS.md`):

1. **Target project is the workspace.** The agent operates on whatever project it's pointed at.
2. **Persist project state in the target project's own brain, not here.** Notes, tasklists, key-maps, decisions, progress go into the target project's knowledge store — the [[second-brain]] LLM-wiki inside that project's Obsidian vault if present, else an existing `.llm-wiki/`/`wiki/` dir, else a `./.<agent-name>/` dir at the target root (e.g. `./.i18n/`). This keeps `agentes_perdidos` clean and makes the agent resumable. Never commit secrets or large generated artifacts to the target.
3. **Self-improvement flows back here.** Only *generalizable* learnings — a new stack adapter, a better heuristic, a recurring gotcha — flow back into the agent's own `SKILL.md` in this repo. Project-specific facts stay in the project's brain.

Generic non-confidential knowledge shared across projects lives once in the [[shared-base-model|shared base]] and is linked, not duplicated.

See also: [[agentes-perdidos]] · [[shared-base-model]].
