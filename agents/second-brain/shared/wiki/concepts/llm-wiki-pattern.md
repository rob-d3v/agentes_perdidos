---
title: The LLM-Wiki (second-brain) pattern
type: concept
created: 2026-06-14
updated: 2026-06-14
sources: [karpathy-llm-wiki]
tags: [knowledge-base, second-brain, pattern, shared]
---

# The LLM-Wiki (second-brain) pattern

A way to build a personal/project knowledge base with an LLM (Karpathy's "LLM Wiki" idea, per
[[karpathy-llm-wiki]]). The
contrast is with plain **RAG**: RAG retrieves raw chunks at query time and re-derives the answer
from scratch every time — nothing accumulates. The LLM-wiki instead has the LLM **incrementally
build and maintain a persistent, interlinked markdown wiki** that sits between you and the raw
sources. Knowledge is **compiled once and kept current**, not re-derived per query.

The wiki is a **compounding artifact**: cross-references already exist, contradictions are
already flagged, the synthesis already reflects everything read. It gets richer with every source
and every question. The human curates sources and asks questions; the LLM does all the
bookkeeping (summarizing, cross-referencing, filing, consistency) that makes humans abandon wikis.

## Three layers
1. **Raw sources** — immutable; the LLM reads, never edits. Source of truth.
2. **The wiki** — LLM-generated, interlinked markdown pages (entities, concepts, sources,
   comparisons, overview, synthesis). The LLM owns this entirely.
3. **The schema** (`CLAUDE.md`/`AGENTS.md`) — how the wiki is structured + the workflows.

## Operations
- **Ingest** — read a source, write a summary page, update every page it touches (10–15), update
  the index, append the log.
- **Query** — read the index, drill into relevant pages, synthesize **with citations**, and
  **file good answers back** as new pages so explorations compound.
- **Lint** — periodic health check: contradictions, stale claims, orphans, missing pages/links,
  gaps fillable by search.

## Navigation files
- **`index.md`** — content catalog; read first on a query (avoids needing embedding RAG at small
  scale, ~hundreds of pages).
- **`log.md`** — append-only timeline, greppable prefix `## [YYYY-MM-DD] <op> | <title>`.

## Tooling
- Obsidian as the browser/IDE (graph view, `[[wikilinks]]`, Dataview on frontmatter, Marp slides).
- Optional on-device search (e.g. `qmd`, BM25+vector) once the index file isn't enough.
- It's just a git repo of markdown → free version history.

In `agentes_perdidos` this pattern is operationalized by the **second-brain** agent (see
[[agentes-perdidos-agents]]), which stores each project's brain inside that project's Obsidian
vault and keeps generic pages like this one in the shared base.

Related: [[claude-code-context-management]] · [[agentes-perdidos-agents]]
