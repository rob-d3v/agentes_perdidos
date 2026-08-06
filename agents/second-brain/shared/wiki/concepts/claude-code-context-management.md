---
title: Claude Code — Context Management
type: concept
created: 2026-06-14
updated: 2026-06-14
sources: [claude-code-best-practices]
tags: [claude-code, context, subagents, shared]
---

# Claude Code — Context Management

The context window holds the entire conversation: every message, every file read, every command
output. It fills fast (a single debugging session can burn tens of thousands of tokens) and
**model performance degrades as it fills** — Claude starts forgetting earlier instructions and
making mistakes. Treat context as the scarce resource.

## Levers
- **`/clear`** between unrelated tasks — the single highest-value habit.
- **Subagents** for read-heavy investigation: they explore in a *separate* context window and
  return only a summary, so the main thread stays lean. This is why the second-brain agent
  fans out onboarding/ingest to subagents. (per [[claude-code-best-practices]])
- **`/compact <focus>`** and rewind summarize-from/up-to for partial condensation.
- **Scope investigations** narrowly — open-ended "investigate X" reads hundreds of files.
- **CLAUDE.md bloat** silently eats context every session and drowns real rules — keep it short.

## Why it matters for the second brain
The whole LLM-wiki premise is a context play: compile knowledge **once** into the wiki, then
answer from a small set of relevant pages instead of re-reading raw sources every query. The
wiki is durable context that survives `/clear` and new sessions. See [[llm-wiki-pattern]].

Related: [[claude-code-best-practices]] · [[llm-wiki-pattern]]
