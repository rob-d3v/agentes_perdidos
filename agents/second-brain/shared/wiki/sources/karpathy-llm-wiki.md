---
title: "Source: Karpathy — LLM Wiki idea file"
type: source
created: 2026-06-14
updated: 2026-06-14
sources: [karpathy-llm-wiki]
tags: [knowledge-base, second-brain, source, shared]
---

# Source: Karpathy — "LLM Wiki"

The idea file that seeds the second-brain agent. An LLM **incrementally builds and maintains** a
persistent, interlinked markdown wiki between you and raw sources, instead of re-deriving answers
via RAG every query. Knowledge is compiled once and kept current; the wiki compounds.

Key points captured into [[llm-wiki-pattern]]: three layers (raw / wiki / schema), the
ingest–query–lint operations, `index.md` (content catalog) + `log.md` (chronological, greppable),
Obsidian as the IDE, and the framing "Obsidian is the IDE, the LLM is the programmer, the wiki is
the codebase." Related in spirit to Vannevar Bush's Memex (1945) — the missing piece Bush couldn't
solve (who maintains the trails) is exactly what the LLM now does.

The document is intentionally abstract — it communicates the pattern; the concrete directory
structure, schema, and tooling are instantiated per use. In this repo that instantiation is the
**second-brain** agent. (per [[agentes-perdidos-agents]])

Related: [[llm-wiki-pattern]]
