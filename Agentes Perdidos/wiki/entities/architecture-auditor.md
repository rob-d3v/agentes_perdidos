---
title: architecture-auditor agent
type: entity
created: 2026-07-30
updated: 2026-07-30
sources: [agents/architecture-auditor/SKILL.md]
tags: [agent, architecture, clean-architecture, metrics, refactoring, read-only]
---

Senior-engineer **read-only architecture diagnosis** for any unfamiliar codebase: reverse-engineers the real structure, measures it with hard metrics, and emits a prioritized refactoring roadmap — it **proposes, never edits**.

## Diagnostic lenses
Uncle Bob concentric layers + the **Dependency Rule** (dependencies point inward only), SOLID, Mark Richards cohesion/coupling, DDD bounded-context alignment. A violation looks like: domain importing Spring/axios/DB drivers, god classes, one "shared" god-module.

## Hard metrics (every claim backed by a number)
`archmetrics.py` + `depgraph.py` wrap **lizard, radon, jscpd, dependency-cruiser** (skipping absent tools) into a JSON digest: cyclomatic CC (flag > 10, hotspot > 20), cognitive complexity (> 15), Maintainability Index, afferent/efferent coupling Ca/Ce, Instability I = Ce/(Ce+Ca), Abstractness A, distance-from-main-sequence D (> 0.5 = Zone of Pain/Uselessness), duplication %, dependency cycles.

## Deliverable
A phased roadmap of **Strangler Fig / Branch-by-Abstraction slices** ranked by blast-radius (Ca) × severity — handed to [[clean-refactorer]], which executes the moves behind a behavior-preservation net. [[security-reviewer]] owns vulns; this agent owns structure; [[performance-engineer]] owns speed.

Read-only: scripts write only a metrics digest to a gitignored out-dir. Per [[lost-agent-rule]], per-repo findings live in the target project's own brain. Key files: `agents/architecture-auditor/{SKILL.md,archmetrics.py,depgraph.py}` (run via [[uv]]). See [[agentes-perdidos]].
