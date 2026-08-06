# architecture-auditor

A **senior architect who just joined your codebase**. It reverse-engineers any repo into
Clean-Architecture concentric layers, checks the **Dependency Rule** (dependencies must point
inward, toward the domain), scores modules on **SOLID + Mark Richards coupling/cohesion + DDD
bounded contexts**, and backs every claim with **hard metrics** — cyclomatic & cognitive complexity,
afferent/efferent coupling (Ca/Ce), Instability, abstractness, distance-from-main-sequence,
duplication %, and dependency cycles.

The output is an objective architecture health report plus a **phased Strangler Fig /
Branch-by-Abstraction refactoring roadmap**, ranked by **blast radius (Ca) × severity** so you fix
the highest-leverage hotspots first.

**READ-ONLY / diagnostic.** It PROPOSES, never edits. It hands the roadmap to the **clean-refactorer**
agent, which makes the actual moves behind a behavior-preserving net. Function is never changed.

**The thing it gets right that folder-tree audits miss:** a repo can have tidy
`domain/ application/ infrastructure/` folders and *still* have the domain importing JPA or axios.
This agent validates the **import direction**, not the layout — that's the whole point.

## Quickstart

```bash
# 1. Metric engine: CC/cognitive/MI/duplication + Ca/Ce/Instability/Abstractness/Distance + cycles
uv run agents/architecture-auditor/archmetrics.py /path/to/repo

# 2. Dependency graph + circular deps + orphan modules (auto-selects backend by stack)
uv run agents/architecture-auditor/depgraph.py /path/to/repo

# archmetrics.py auto-invokes depgraph.py if the graph isn't there yet, so step 1 alone is enough
# for a full digest. Both write JSON to <repo>/arch-reports/ (add that to the repo's .gitignore).
```

Outputs:
- `arch-reports/_metrics.json` — complexity hotspots, maintainability, duplication, per-package
  coupling/abstractness/distance, dependency cycles.
- `arch-reports/_depgraph.json` — the normalized dependency graph, cycles (SCCs), and orphans.

## Tools it wraps (all optional — missing ones are skipped with a log, never fatal)

| Tool | Provides | Install |
|---|---|---|
| `lizard` | cyclomatic + cognitive complexity + clones, 15+ langs | `pip install lizard` |
| `radon` | Python maintainability index + per-function CC | `pip install radon` |
| `jscpd` | cross-language duplication % | `npm i -g jscpd` |
| `dependency-cruiser` | JS/TS module graph + cycles + orphans | `npm i -g dependency-cruiser` |
| (stdlib) | Java / Python import-scan package graph (no extra tool) | built in |

## How to drive it

Point an LLM session at [`SKILL.md`](SKILL.md) and a target repo. The scripts give the numbers;
the LLM applies the architectural lenses (Dependency Rule, SOLID, DDD), ranks findings by Ca ×
severity, and writes the **as-built architecture + roadmap** into the **target project's own brain**
(its Obsidian vault under `decisions/` + `concepts/`, else `./.architecture/`) — never into
`agentes_perdidos` (lost-agent rule).

No API keys required — the scripts only read source and shell out to local metric tools.
