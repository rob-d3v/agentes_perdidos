---
name: ai-visibility
description: >
  Makes a project's content citable by AI answer engines (ChatGPT, Claude, Perplexity,
  Gemini, Google AI Overviews) — i.e. GEO/AEO, not classic SEO. Audits any page (blog
  article, SPA landing, product/marketing page) against a 23-element framework, scores it
  0-100, and emits a prioritized, content-type-aware action plan. Auto-applies the safe,
  mechanical wins (JSON-LD schema, "last updated", tables, meta, Q&A headings) and flags the
  human-judgment items. KNOWS that a JS-only SPA is invisible to most AI crawlers and treats
  prerender/SSR as the gate before anything else matters. Use when asked to "optimize for AI",
  "AI visibility", "get cited by ChatGPT/Perplexity", "GEO/AEO", "LLM/answer-engine
  optimization", or to audit why content isn't being cited. Seam with `habitar`: **this agent
  asks whether the crawler can read it; `habitar` asks whether there is anything there to read.**
  If the page is extractable but empty, that's `habitar`'s job, not this one's.
---

# AI Visibility (GEO / AEO)

Classic SEO optimizes for *blue links*. This agent optimizes for *citations* — being the
source an LLM quotes and links when it answers a question. Different game: the winners are
content that is **extractable** (parseable without running JS), **answer-shaped** (direct
answer up top, scannable, tabular), **trustworthy** (named expert author, primary-source
citations, original data), and **technically clean** (schema markup, fast, indexable).

Framework adapted from Anna York's 23-element AI Visibility study (439 articles / 11
industries). This agent extends it with the thing the original misses: **crawler
extractability for SPAs**, which gates everything else.

---

## Element 0 — Extractability (THE GATE, check this first)

> If the AI crawler can't read your content, the other 23 elements score zero. Always evaluate
> this before scoring anything else.

Most AI crawlers fetch raw HTML and **do not execute JavaScript**:

| Crawler | Runs JS? | UA token |
|---|---|---|
| GPTBot (OpenAI) | No | `GPTBot` |
| OAI-SearchBot (ChatGPT search) | No | `OAI-SearchBot` |
| ChatGPT-User (live fetch) | No | `ChatGPT-User` |
| PerplexityBot | No | `PerplexityBot` |
| ClaudeBot / Claude-Web | No | `ClaudeBot`, `Claude-Web` |
| Google-Extended (Gemini/AIO) | Partial (Googlebot render budget) | `Google-Extended` |

**Decision matrix — how does the content reach the crawler?**

| Render mode | Crawler sees | Verdict |
|---|---|---|
| Static HTML / MPA / Markdown blog | Full content | ✅ extractable — proceed |
| SSR (Next.js, Nuxt, Remix, Astro SSR) | Full content | ✅ extractable — proceed |
| SSG / prerender (Astro, `react-snap`, `vite-plugin-ssr`, `prerender.io`) | Full content | ✅ extractable — proceed |
| **Pure CSR SPA** (Vite/CRA, content only after `fetch`+render) | **empty `<div id="root">`** | 🔴 **BLOCKED — fix this first** |

**How to test extractability (do this, don't assume):**

```bash
# What an AI crawler actually sees — no JS execution:
curl -sL -A "GPTBot" "https://the-url/" | python -c "import sys,re; h=sys.stdin.read(); \
  print('chars in body:', len(re.sub(r'<[^>]+>','',h)))"
# Compare with the JS-rendered DOM (what a human sees). If the curl body is near-empty
# but the page is full of content in a browser → CSR SPA → Element 0 FAILS.
```

**Fix paths for a blocked SPA (pick by stack, cheapest first):**
0. **Static SEO shell inside `#root`** (cheapest; works when the app uses
   `createRoot(el).render()`, NOT `hydrateRoot`). Hand-write the first-class content — direct
   answer, a table, FAQ, semantic `<main>/<section>`, internal links — *inside* the mount
   container in `index.html`. A no-JS crawler reads it as real body content; on mount React
   **replaces** those children, so there's no hydration and no mismatch. One static file serves
   all routes, so this makes the **homepage** strong and gives every route a content floor, but
   it's the *same* content everywhere — pair it with per-route prerender (below) for
   route-specific pages. Verify it's `render` not `hydrate` first (a hydrate app will throw on a
   markup mismatch). Proven on theAPIAniaAPP: 0 → 65/100.
1. **Template-swap per-route prerender (no headless browser)** — post-build Node script that
   takes the built `dist/index.html` as template and emits `dist/<route>/index.html` per public
   route, swapping title/meta/canonical/OG and the `#root` shell between HTML marker comments
   (`<!-- prerender:shell:start/end -->`). Source route facts from the app's i18n files so the
   static content can't drift. Zero new deps, works in any Docker build, and nginx
   `try_files $uri $uri/ /index.html` serves the per-route files with no config change
   (expect a harmless `/route` → `/route/` 301). Proven on theAPIAniaAPP: all 7 public routes
   got route-specific crawler content (homepage 67, /faq 65/100 live). Combine with fix 0.
2. **Rendered per-route prerender** — `vite-plugin-ssr`/`vike`/`react-snap` for Vite-React, or a
   build-time Puppeteer crawl. Gives each route its *real rendered* content. Best when route
   content is dynamic (e.g. product listings) and a hand-written shell would go stale.
3. **Migrate marketing pages to SSR/SSG** (Astro or Next for the public site, keep the app
   SPA). Best long-term for a content-heavy public site.

> Copywriting gotcha for `score.py` [2]: the first-100-words "no links" check matches anchor
> *text as a substring* of the opening block — a bare generic anchor label like `marketplace`
> trips it when the same word appears in the opening paragraph. Use distinctive anchor labels
> and keep the opening block link-free.

> **`<noscript>` is NOT a fix.** Content in `<noscript>` is a *weak, discounted* signal (it
> exists for script-disabled browsers and reads as cloaking-adjacent to crawlers). If you find
> the only static content is inside `<noscript>`, **promote it into the live DOM** via fix-path
> 0 — that's strictly stronger. `score.py` grades noscript-only content as extractable-but-weak
> and caps the score at 40 to reflect this.

Also confirm crawlers are **allowed**: `robots.txt` must not `Disallow` GPTBot / PerplexityBot
/ ClaudeBot / Google-Extended on public content. Add an `llms.txt` (plain-text index of your
best content) at site root — emerging convention, low cost.

---

## Content-type adapter (apply only the elements that fit)

Not every element applies to every page. Pick the column before scoring.

| Element group | Blog / article | SPA landing / marketing | Product / pricing page |
|---|---|---|---|
| 0 Extractability | ✅ | ✅ (usually the failing one) | ✅ |
| 1 Intent match | ✅ | ✅ | ✅ |
| 2 Direct answer / value prop first 100w | ✅ | ✅ (as hero value prop) | ✅ |
| 3 Freshness "last updated" | ✅ | optional | ✅ (price/version date) |
| 4 Scannability / tables | ✅ | ✅ | ✅ (feature/price tables) |
| 5 Comprehensive coverage / FAQ | ✅ | ✅ | ✅ |
| 6 Expert author E-E-A-T | ✅ | org-level (About/team) | org-level |
| 7 Original data | ✅ | ◑ if available | ◑ |
| 8 Authoritative citations | ✅ | ◑ | ◑ |
| 9 Transparent methodology | ✅ | — | — |
| 10 Q&A format / FAQPage schema | ✅ | ✅ | ✅ |
| 11 Hero resource | ✅ | ◑ | ◑ |
| 12 Semantic HTML5 | ✅ | ✅ | ✅ |
| 13 Factual precision | ✅ | ✅ | ✅ |
| 14 Social proof | ◑ | ✅ | ✅ |
| 15 Problem-solution framing | ✅ | ✅ | ✅ |
| 16 Value anchoring / ROI | ◑ | ✅ | ✅ |
| 17 Conversion elements | — | ✅ | ✅ |
| 18 Schema markup | Article + FAQPage | Organization + WebSite + FAQPage | Product/Offer + FAQPage |
| 19 Page speed (CWV) | ✅ | ✅ | ✅ |
| 20 Mobile responsive | ✅ | ✅ | ✅ |
| 21 HTTPS | ✅ | ✅ | ✅ |
| 22 Clean URLs | ✅ | ✅ | ✅ |
| 23 Meta + sitemap | ✅ | ✅ | ✅ |

✅ applies · ◑ applies if you have the asset · — skip (don't penalize the score).

---

## The 23 elements (what "pass" looks like)

### 🔴 CRITICAL (1-4) — without these, citation probability < 5%
1. **Intent match** — content answers the *real* query (mine Reddit, People-Also-Ask, support
   tickets), not an assumed one. *Manual.*
2. **Direct answer in first 100 words** — 90-110w block: answer (20-30w) + context (40-50w) +
   preview (20-30w). **Zero links** in that block. *Auto: rewrite opening.*
3. **Freshness** — visible "Last updated: <date>"; substantive refresh every ≤6 months (≤3 for
   ChatGPT recency bias). *Auto: insert date. Manual: actually update stale content.*
4. **Scannability** — H2/H3 hierarchy, 2-4 sentence paragraphs, **all comparison/pricing/list
   data in `<table>`** (+~40% citation). *Auto: prose→table, fix heading structure.*

### 🟠 HIGH PRIORITY (5-11) — each ≈ +8-12% citation
5. **Comprehensive coverage** — answers logical follow-ups; FAQ of 5-10 Qs. *Manual.*
6. **Expert author (E-E-A-T)** — named author (not "staff"), photo, credentialed bio, author
   page, linked About. *Auto: detect presence. Manual: author page + creds.*
7. **Original data** — proprietary survey/analysis in tables w/ methodology (52% of cited posts
   have it). *Manual.*
8. **Authoritative citations** — primary sources (gov/academic/original), descriptive anchor
   text, avoid aggregators. *Auto: flag weak. Manual: replace.*
9. **Transparent methodology** — process, sample size, limitations stated. *Manual.*
10. **Q&A format** — questions as H2/H3 + FAQPage schema. *Auto: headings→questions + schema.*
11. **Hero resource** — one original asset (chart/diagram/template/calculator) w/ alt text.
    *Manual.*

### 🔵 ENHANCEMENT (12-17)
12. **Semantic HTML5** — `<article>/<section>/<header>`, clear attribution. *Auto.*
13. **Factual precision** — "many"→exact figures, "recently"→dates. *Auto: flag vague. Manual.*
14. **Social proof** — named testimonials/photos, quantified case studies. *Manual.*
15. **Problem-solution framing** — H2 = user problem, immediate solution. *Auto where logical.*
16. **Value anchoring** — quantified ROI/outcomes. *Manual.*
17. **Conversion elements** — CTA above fold, transparent pricing, lead magnet, human support.
    *Landing/product only.*

### 🟢 TECHNICAL (18-23)
18. **Schema markup** — Article / FAQPage / HowTo / Organization / Product as fits. *Auto:
    inject. Validate at Rich Results Test.*
19. **Page speed** — LCP < 2.5s, INP & CLS passing; WebP, CDN, caching, minify. *Auto: measure.*
20. **Mobile responsive** — passes mobile-friendly. *Auto: detect.*
21. **HTTPS** — SSL + HTTP→HTTPS redirect. *Auto: verify.*
22. **Clean URLs** — `/blog/seo-cost/` not `/p?id=12345`. *Auto: detect.*
23. **Meta + sitemap** — title 55-60c, description 150-160c, XML sitemap, internal links. *Auto.*

---

## Platform bias (tune the priority order to the target engine)
- **ChatGPT/OAI** — recency bias → refresh ≤3mo, "last updated" prominent.
- **Perplexity** — original data + source diversity → invest in Elements 7, 8.
- **Claude** — methodology + E-E-A-T → invest in Elements 6, 9.
- **Gemini / Google AI Overviews** — Google-property bias → Google Scholar / Google-indexed
  citations, strong schema, allow `Google-Extended`.

---

## Workflow when handed a task

1. **Detect content type & stack** — blog vs SPA-landing vs product page; render mode (CSR /
   SSR / SSG / static). Read `package.json`, `vite/next/astro` config, the HTML.
2. **Element 0 first** — run the `curl -A GPTBot` extractability test. If a CSR SPA leaks an
   empty body, **report Element 0 as the top blocker** and propose the cheapest fix path before
   anything else. Don't waste effort polishing content a crawler can't see.
3. **Score** — run `score.py` (below) on the URL or HTML file to get a 0-100 score + per-element
   JSON. Use the content-type adapter to skip N/A elements (don't penalize them).
4. **Auto-apply safe wins** (only the mechanical, low-risk ones, and only with the operator's
   go-ahead if it edits files): JSON-LD schema, "last updated", prose→table, meta tags, Q&A
   headings, semantic HTML. Validate schema at the Rich Results Test.
5. **Emit the action plan** — prioritized by impact × effort, split Auto-done / Manual-needed,
   with a 30/60/90-day roadmap and the platform-bias tuning for the target engine.
6. **Persist state in the TARGET project's brain** (lost-agent rule) — write the audit, score,
   and action plan into the target's second-brain LLM-wiki (Obsidian vault) if present, else a
   `./.ai-visibility/` dir at the target root. Never into `agentes_perdidos`.

## Commands

```bash
# Score a live URL (fetches as an AI crawler — no JS):
uv run agents/ai-visibility/score.py --url https://example.com/blog/post --type blog

# Score local built HTML (e.g. a prerendered dist/ file or index.html):
uv run agents/ai-visibility/score.py --file path/to/index.html --type spa-landing

# Extractability check only (Element 0) — compares raw-HTML text vs a JS-rendered baseline:
uv run agents/ai-visibility/score.py --url https://example.com --extractability-only

# JSON output for piping into a report:
uv run agents/ai-visibility/score.py --url ... --type product --json > audit.json
```

`--type` ∈ `blog | spa-landing | product` (drives which elements are scored vs skipped).

## Gotchas
- **Don't optimize content a crawler can't see.** Element 0 gates everything; a beautiful CSR
  SPA scores ~0 with GPTBot regardless of content quality. Test, don't assume.
- **`aggregateRating` schema without real reviews is a manipulation flag** and can get
  structured data ignored or penalized. Only emit ratings you can substantiate.
- **`robots.txt` blocking AI bots is a choice, not a bug** — some owners *want* to block GPTBot.
  Confirm intent before "fixing" a disallow.
- **Score is a heuristic, not a guarantee.** AI citation is probabilistic; the framework
  maximizes odds. Report it as a probability estimate, never a promise.
- **N/A ≠ fail.** Use the content-type adapter; scoring a landing page on "transparent
  methodology" is noise.

## Self-improvement (flows back here)
New render-mode adapter, crawler UA, or schema recipe that generalizes → update this `SKILL.md`.
Project-specific findings stay in the target project's brain.
