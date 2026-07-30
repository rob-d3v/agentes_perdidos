---
title: clean-refactorer agent
type: entity
created: 2026-07-30
updated: 2026-07-30
sources: [agents/clean-refactorer/SKILL.md]
tags: [agent, refactoring, clean-architecture, characterization-tests, behavior-preserving]
---

Executes **behavior-preserving structural refactors** on messy production code — separates concerns into clean-architecture layers (domain / application / infrastructure / interfaces, ports & adapters) without changing one bit of observable behavior.

## Hard contracts
- **Behavior is sacred.** Anything that alters inputs→outputs, public API, error messages, ordering, or side-effects is NOT a refactor — it ships in its own labeled commit, never riding along.
- **No net, no refactor.** If test coverage is absent/weak, the FIRST deliverable is **characterization (golden-master) tests** that pin the ACTUAL current I/O and run green — committed standalone BEFORE any restructuring (Feathers, *Working Effectively with Legacy Code*). `characterize.py` scaffolds the oracle per stack.
- **Tiny reversible slices.** Branch-by-Abstraction inside the code, Strangler Fig at boundaries; one atomic `git revert`-able commit per slice on a feature branch (never main); re-run the suite after every micro-step, revert on red.
- **Done** only when golden tests stay green AND target metrics improve (CC ≤ 10, cognitive caps, 0 new duplication, no new cycles), reported as before/after deltas.

## Locking the boundaries
`fitness_init.py` emits CI **fitness functions** (dependency-cruiser for JS/TS, ArchUnit for Java) so the new layer boundaries can't silently rot. Concrete for Spring Boot (Java 17/21), React 18/19 + Vite + TS, and FastAPI.

## Pairings
Consumes the roadmap from [[architecture-auditor]] (which diagnoses but never edits); can use [[performance-engineer]]'s `behavior_diff.py` as an extra oracle; [[security-reviewer]] completes the quartet. Per [[lost-agent-rule]], per-repo state goes in the target project's brain.

Key files: `agents/clean-refactorer/{SKILL.md,characterize.py,fitness_init.py,structure.md}` (run via [[uv]]). See [[agentes-perdidos]].
