---
title: LLM-wiki pattern
type: concept
created: 2026-06-14
updated: 2026-06-14
sources: [agents/second-brain/SKILL.md]
tags: [llm-wiki, second-brain, shared]
---

The Karpathy "LLM Wiki" pattern: instead of re-deriving answers from raw files on every query (RAG), compile knowledge **once** into an interlinked markdown wiki that lives inside the project's Obsidian vault and keep it current as sources arrive. The [[second-brain]] agent productizes this.

The generic explainer and its origin source live in the shared base (`agents/second-brain/shared/wiki/concepts/llm-wiki-pattern.md` and `.../sources/karpathy-llm-wiki.md`) — linked here, not duplicated (see [[shared-base-model]]).
