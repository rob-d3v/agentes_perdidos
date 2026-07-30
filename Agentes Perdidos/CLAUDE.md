---
brain: agentes_perdidos
maintained-by: second-brain agent (agentes_perdidos)
confidential: false
---

# agentes_perdidos — brain schema

This folder is an **LLM-wiki second brain**, maintained by the `second-brain` agent.
It's an Obsidian vault: open it in Obsidian to browse pages, links, and the graph.

## Layout

- `index.md` — catalog of every page. Read FIRST on a query. Regenerate via reindex.
- `log.md`   — append-only dated history (`## [YYYY-MM-DD] <op> | <title>`).
- `wiki/`    — LLM-owned pages: `overview/ entities/ concepts/ comparisons/ decisions/ sources/`.
- `raw/`     — immutable source documents. Read from, never edit.

## Conventions

- One page per entity/concept/source. Filename = kebab-case slug.
- Every page opens with YAML frontmatter (`title, type, created, updated, sources, tags`).
- Cross-link liberally with `[[slug]]`. Cite sources inline: `(per [[source-slug]])`.
- Contradictions are flagged inline (`> ⚠️ Contradiction: ...`), never silently overwritten.

## Generic knowledge → shared base (don't duplicate)

Generic, non-confidential topics (Claude Code best practices, uv/PEP-723, the LLM-wiki
pattern, the agentes_perdidos agents) live ONCE in the shared base at:

    E:/backup_2026/Repositórios/agentes_perdidos/agents/second-brain/shared/

Reference those pages instead of re-ingesting them here. Keep this brain project-specific.

## How to drive

Point an LLM at `agents/second-brain/SKILL.md` (in agentes_perdidos) and this vault, then:
`ingest <raw/...>`, `query <question>`, `lint`, `onboard`.
