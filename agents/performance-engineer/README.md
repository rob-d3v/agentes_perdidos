# performance-engineer agent — measure, fix one thing, prove it

A senior performance engineer for any app in this fleet (React/Vite + Node sidecars +
FastAPI/Python + Spring/JVM). It **profiles to find the single real hotspot, applies the ONE
highest own-time fix, then re-profiles to prove the win** — and proves the app's observable output
is **byte-identical** before and after. No speculative optimization, no blind memoization, no
"looks faster". Speed and memory are the goals; **behavior never changes.**

The brain is [`SKILL.md`](SKILL.md). Point an LLM session at it inside a target project:

> Read `…/agentes_perdidos/agents/performance-engineer/SKILL.md` and make this app faster — profile
> it, fix the single biggest hotspot, and prove the output didn't change.

## The loop (the whole agent)

```
PROFILE → pick the rank-1 self-time hotspot → capture golden I/O (before)
        → fix that ONE thing → RE-PROFILE → capture golden I/O (after) → assert byte-identical
        → identical + faster? keep (atomic commit on a feature branch). else REVERT.
```

- **Self-time, not cumulative.** `cumtime` shows *where to look*; `tottime` (own time) shows *what
  to fix* — the only thing optimizing one function can shrink.
- **One fix per pass**, then re-profile — the #2 hotspot often reorders or vanishes once #1 is gone.
- **Prefer the React Compiler over manual `useMemo`/`React.memo`**; bound every cache you add (an
  unbounded cache is a memory leak you chose).
- Findings go in the **target project's own brain** (`.perf/` or its vault), never in this repo.

## Scripts (run via `uv`)

```bash
# PROFILE — detect stack, run the right profiler, emit a self-time-ranked hotspots.json
uv run agents/performance-engineer/profile_run.py python --cmd "python app/main.py --bench"
uv run agents/performance-engineer/profile_run.py py-spy  --pid 12345 --duration 30   # live attach
uv run agents/performance-engineer/profile_run.py node   --tool flame --cmd "node server.js"
uv run agents/performance-engineer/profile_run.py react                # emits DevTools Profiler steps
uv run agents/performance-engineer/profile_run.py jvm    --pid 4567    # emits async-profiler/JFR cmds

# PROVE — capture observable output before/after a fix and assert it's byte-identical
uv run agents/performance-engineer/behavior_diff.py capture cases.json --label before --out goldens
uv run agents/performance-engineer/behavior_diff.py capture cases.json --label after  --out goldens
uv run agents/performance-engineer/behavior_diff.py assert goldens/before.json goldens/after.json
#   exit 0 = identical + faster (keep) · 1 = output DRIFT (revert) · 2 = identical, no speedup (revert)
```

`profile_run.py` auto-runs cProfile / py-spy / scalene / clinic / 0x and normalizes each into a
hotspot-ranked JSON. React DevTools and JVM async-profiler/JFR need a live app/browser/IDE, so it
**emits the exact commands/steps** instead of auto-running them. `behavior_diff.py` is the
behavior-preservation **oracle** — stdlib-only and self-contained (the `clean-refactorer` agent
reuses the same idea). See [`SKILL.md`](SKILL.md) for the `cases.json` schema, the per-stack
profiler matrix, the memory-leak/CPU smell catalog, and the decision rules.

## Tools

`profile_run.py` shells out to external profilers; a missing one is logged and **skipped** (the run
never hard-fails). Install what your stack needs:

```bash
pipx install py-spy scalene          # Python
npm i -g clinic 0x                   # Node
# JVM: async-profiler (asprof) + JDK's Flight Recorder/jcmd + Eclipse MAT; React: DevTools extension
```
