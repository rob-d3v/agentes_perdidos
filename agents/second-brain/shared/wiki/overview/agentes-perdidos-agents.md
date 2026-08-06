---
title: agentes_perdidos — agents catalog
type: overview
created: 2026-06-14
updated: 2026-06-14
sources: []
tags: [agentes-perdidos, agents, shared]
---

# agentes_perdidos — agents catalog

Public collection of self-contained AI agents. Each is a folder under `agents/<name>/` with a
`SKILL.md` (the brain — what it does + how it decides) plus any code. You drive one by opening an
LLM session **in any project**, pointing it at the agent's `SKILL.md`, and giving a task.

## Lost-agent rule
Every agent treats the **target project as its workspace** (it's "lost" in someone else's repo).
Project-specific state lives in the **target project's own brain** (its `second-brain`/Obsidian
vault, else a `./.<agent>/` dir) — never in `agentes_perdidos`. Only **generalizable** learnings
flow back into the agent's `SKILL.md`. Never commit secrets.

## Agents
- **image-creator** — generates missing image/video assets across 3 APIs with fallback:
  transparent → OpenAI `gpt-image-1.5`, photographic → Gemini "Nano Banana", video → Kling AI.
- **bucket** — offloads static browser-served assets to R2 (hot/CDN) / B2 (archival) and rewrites
  code to bucket URLs. Reversible.
- **design-reviewer** — senior product-designer agent; diagnoses amateur UI and produces a
  buildable redesign plan + AI-asset spec (routed to image-creator).
- **lost-finder** — forensic hunter for lost files by content (image color signature, PDF text);
  local-only secrets mode for recovering one's own wallet creds.
- **remodeling** — rewrites an app to reflect the real, verified identity of its true owner
  (deep-research + anti-fake rule + face-swap), content-only.
- **i18n** — internationalizes a project end-to-end: extracts strings, authors pt-BR+en by AI,
  auto-generates ~190 more languages keyless, wires a language switcher.
- **second-brain** — builds/maintains an LLM-wiki [[llm-wiki-pattern]] per project inside its
  Obsidian vault; ingest/query/lint/onboard. Keeps generic pages in the shared base. **(this one)**

## Conventions
- `SKILL.md` frontmatter: `name` (matches folder) + `description` (when to use + how it decides).
- Python via [[uv-pep723-pattern]]. Secrets in `.env` only (gitignored), documented in `.env.example`.
- Register a new agent in the root `README.md` table. See `AGENTS.md` for the full contract.

Related: [[llm-wiki-pattern]] · [[claude-code-best-practices]] · [[uv-pep723-pattern]]
