# ai-visibility

Makes a project's content **citable by AI answer engines** (ChatGPT, Claude, Perplexity,
Gemini, Google AI Overviews) — GEO/AEO, not classic SEO. The win condition is being the
*source an LLM quotes*, not ranking a blue link.

It audits a page against a 23-element framework, scores it 0-100, and emits a prioritized,
content-type-aware action plan. It auto-applies the safe mechanical wins (JSON-LD schema,
"last updated", tables, meta, Q&A headings) and flags the human-judgment items.

**The thing it gets right that checklists miss:** a JS-only SPA is invisible to most AI
crawlers (they don't run JavaScript). Element 0 — *extractability* — gates everything else, so
the agent tests it first and won't waste effort polishing content a crawler can't read.

## Quickstart

```bash
# Score a live page exactly as an AI crawler sees it (no JS):
uv run agents/ai-visibility/score.py --url https://example.com/blog/post --type blog

# Score a local/prerendered HTML file:
uv run agents/ai-visibility/score.py --file dist/index.html --type spa-landing

# Just the extractability gate (Element 0):
uv run agents/ai-visibility/score.py --url https://example.com --extractability-only

# JSON for a report pipeline:
uv run agents/ai-visibility/score.py --url ... --type product --json
```

`--type` ∈ `blog | spa-landing | product` — drives which elements are scored vs skipped
(N/A elements don't penalize the score).

## How to drive it

Point an LLM session at [`SKILL.md`](SKILL.md) and a target project / URL. The script gives
the structural score; the LLM handles the judgment elements (intent match, original-data
quality, methodology, social-proof authenticity) and writes the audit into the **target
project's** brain (lost-agent rule), not this repo.

No API keys required — `score.py` only does an unauthenticated HTTP GET as a crawler UA.
