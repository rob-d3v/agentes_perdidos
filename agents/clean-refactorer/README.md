# clean-refactorer

A **behavior-preserving** structural refactorer. It rebuilds a messy production codebase with
clean-architecture principles — separating concerns into `domain` / `application` / `infrastructure`
/ `interfaces` (ports & adapters), increasing modularity, reducing coupling — **without changing one
bit of observable behavior**, and only behind a green behavior-preservation net.

> **Behavior is sacred.** It changes structure & quality, never inputs→outputs / public API / error
> messages / ordering / side-effects. A behavior change and a refactor NEVER share a commit.

## How it works

1. **Net first.** Detect test coverage. If it's absent/weak, generate + commit **characterization
   (golden-master) tests** that pin the code's ACTUAL current I/O — a standalone first commit, GREEN,
   before any restructuring (`characterize.py`).
2. **Move in tiny reversible slices.** Branch-by-Abstraction inside the code, Strangler Fig at
   boundaries. One atomic `git revert`-able commit per slice, on a **feature branch (never main)**.
3. **Re-run the net after every micro-step.** Green ⇒ keep. Red ⇒ revert immediately.
4. **Lock the boundaries.** Emit a CI **fitness function** so the new structure can't rot
   (`fitness_init.py`): dependency-cruiser for JS/TS, ArchUnit for Java, import-linter for Python.
5. **Done only when** the net stays GREEN **and** metrics improve (CC ≤ 10, 0 new duplication, no new
   cycles) with none regressing — reported as before/after deltas, with the architecture write-up.

## Scripts (run with [`uv`](https://docs.astral.sh/uv/) — deps auto-install via PEP-723)

```bash
# 1) Scaffold the behavior-preservation net for the detected stack (pytest+approvaltests /
#    vitest snapshot / JUnit+approvaltests). Fill inputs, record golden snapshots, commit GREEN.
uv run agents/clean-refactorer/characterize.py <repo>

# 2) Emit the CI fitness function that locks the new layering (after restructuring).
uv run agents/clean-refactorer/fitness_init.py <repo> [--src src] [--base-package com.example]
```

Both detect the stack, **skip cleanly** when a tool/stack is absent, never overwrite without
`--force`, and write only into the target repo. They scaffold; they don't run the target's build.

## Stacks

Concrete folder structures + fitness functions for **Spring Boot (Java 17/21)**, **React 18/19 +
Vite + TS**, and **FastAPI** — see [`structure.md`](structure.md).

## Driving it

Open an LLM session in the project to refactor and point it at this agent:

> Read `path/to/agentes_perdidos/agents/clean-refactorer/SKILL.md`. Refactor `<area>` to clean
> architecture WITHOUT changing behavior: build the characterization net first, then move in tiny
> reversible slices behind it, then lock the boundaries with a fitness function.

## Relationship to sibling agents

- **`../architecture-auditor/`** (read-only) produces the refactoring **roadmap** this agent
  consumes — what to decouple, in what order.
- **`../performance-engineer/behavior_diff.py`** is an optional extra golden-output oracle you can
  wire in alongside the characterization net.

The full decision logic, workflow, per-stack cheat-sheet, and gotchas live in
[`SKILL.md`](SKILL.md). Per-project plans/baselines/slice-logs go in the **target project's own
brain** (lost-agent rule), never here.
