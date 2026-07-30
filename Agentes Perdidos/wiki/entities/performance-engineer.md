---
title: performance-engineer agent
type: entity
created: 2026-07-30
updated: 2026-07-30
sources: [agents/performance-engineer/SKILL.md]
tags: [agent, performance, profiling, optimization, behavior-preserving]
---

**Measure-first performance agent**: profiles to find the SINGLE real hotspot, applies the one highest own-time fix, re-profiles to prove the win AND proves output is byte-identical — reverts on no gain or any drift. Never speculative optimization, never blind memoization.

## The loop (mandatory)
```
PROFILE (profile_run.py → hotspots ranked by SELF time) → PICK ONE →
GOLDEN (behavior_diff.py capture, representative + edge inputs) →
FIX (one atomic commit on a feature branch) → RE-PROFILE + RE-DIFF → keep or REVERT
```
Key doctrine: **cumtime tells you where to look; tottime (own/self time) tells you what to fix** — a function with huge cumtime but tiny tottime is just a caller.

## Per-stack profiler matrix
React DevTools Profiler (+ React Compiler over manual memo) · Node clinic.js doctor → 0x flame → V8 heap-snapshot diff · Python cProfile → py-spy / scalene / line_profiler / tracemalloc · JVM async-profiler + Java Flight Recorder + Eclipse MAT Leak Suspects. Ships smell catalogs: memory leaks (unbounded caches, dangling listeners, big-object closures, growing globals) and CPU (sync I/O on the event loop, regex backtracking, N+1, huge JSON, render thrash).

## Contracts & pairings
Observable behavior is sacred — `behavior_diff.py` is the equivalence oracle (stdlib-only, same idea [[clean-refactorer]] uses). One-CL-does-one-thing: every fix git-revertible, never on main. Per [[lost-agent-rule]], per-app hotspots and before/after numbers go in the target project's brain; the profiler matrix lives once in the [[shared-base-model|shared base]]. Quartet with [[security-reviewer]], [[architecture-auditor]], [[clean-refactorer]].

Key files: `agents/performance-engineer/{SKILL.md,profile_run.py,behavior_diff.py}` (run via [[uv]]). See [[agentes-perdidos]].
