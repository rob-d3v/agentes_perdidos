---
title: ai-visibility agent
type: entity
created: 2026-06-27
updated: 2026-06-27
sources: [agents/ai-visibility/SKILL.md, agents/ai-visibility/score.py]
tags: [agent, geo, aeo, seo, ai-crawlers, content]
---

Makes a project's content **citable by AI answer engines** (ChatGPT, Claude, Perplexity, Gemini, Google AI Overviews) — i.e. **GEO/AEO, not classic SEO**. Classic SEO optimizes for blue links; this agent optimizes for *citations* — being the source an LLM quotes. It audits any page (blog article, SPA landing, product/marketing page) against a **23-element framework** (adapted from Anna York's AI Visibility study), scores it **0-100**, and emits a prioritized, content-type-aware action plan.

## What it does
- Auto-applies the **safe, mechanical wins**: JSON-LD schema, "last updated", tables, meta, Q&A headings. Flags the human-judgment items (named-expert author, primary-source citations, original data).
- **Element 0 = Extractability (THE GATE):** most AI crawlers (GPTBot, OAI-SearchBot, ChatGPT-User, etc.) fetch raw HTML and **do not execute JavaScript** — so a JS-only SPA is **invisible**. The agent checks this first and gates everything on prerender/SSR before any content polish. `score.py` fetches **as an AI crawler with no JS execution**, exactly mimicking the blindness.

## How it's invoked
Point an LLM at `agents/ai-visibility/SKILL.md` + the page/project, give a task ("optimize for AI", "get cited by ChatGPT/Perplexity", "GEO/AEO audit", "why isn't this content cited"). Helper script `score.py` (run via [[uv]]):
- `uv run agents/ai-visibility/score.py --url https://example.com --extractability-only` — Element-0 gate check first.
- `uv run agents/ai-visibility/score.py --file path/to/index.html --type spa-landing` (or `--url ... --type blog|product`).
- `... --json > audit.json` for a machine-readable score + action plan.

## Env keys
None required for scoring (it is an HTTP fetch + static analyzer). Auto-applied schema/meta edits are local file rewrites.

## Division of labor with navigator
None — ai-visibility is a content/crawler agent, not a browser-dashboard agent. It can route generated AI-asset needs to other agents, but does not pair with [[navigator]]. Per [[lost-agent-rule]], audit results + the action plan persist in the **target project's** brain. See [[agentes-perdidos]].
