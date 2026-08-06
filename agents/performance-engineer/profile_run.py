#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
profile_run.py — MEASURE-FIRST profiler orchestrator for the performance-engineer agent.

Detects the stack, runs the right profiler, and normalizes the result into a hotspot-ranked
JSON the agent reads to pick the SINGLE highest own-time (self-time / tottime) offender. Never
guesses where the time goes — it measures.

Two classes of profiler:
  * Auto-run (this script shells to them): Python cProfile / py-spy / scalene; Node clinic / 0x.
  * Emit-only (need a running app, a browser, or an IDE): React DevTools Profiler;
    JVM async-profiler / Java Flight Recorder. For these it PRINTS the exact command/UI set to
    run by hand, then ingests the artifact you point it at.

Missing tools are SKIPPED with a logged note — like secreview.py, the run never hard-fails on
one absent binary; it tells you the install line and moves on.

Usage:
  # Python — cProfile by cumtime, but the agent reads tottime (own time) to find the real hotspot
  uv run profile_run.py python --cmd "python app/main.py --bench" [--sort tottime] [--top 25]
  # Python — live/attach sampling profiler (no code change, attach by PID)
  uv run profile_run.py py-spy   --pid 12345 [--duration 30]
  uv run profile_run.py scalene  --cmd "python app/main.py"     # CPU + GPU + memory

  # Node — clinic doctor (triage), then flame (0x) for CPU
  uv run profile_run.py node --tool doctor --cmd "node server.js"
  uv run profile_run.py node --tool flame  --cmd "node server.js"

  # Emit-only (prints instructions + commands; ingest the artifact afterwards)
  uv run profile_run.py react                                   # React DevTools Profiler steps
  uv run profile_run.py jvm --pid 4567                          # async-profiler + JFR commands
  uv run profile_run.py ingest --kind cprofile --file prof.out  # normalize an existing artifact

Output: prints a hotspot-ranked JSON to stdout and (when a run produced an artifact) writes
<out>/hotspots.json. One run = one ranked table the agent uses to choose ONE fix.
"""
from __future__ import annotations
import argparse, json, pstats, shutil, subprocess, sys, tempfile
from pathlib import Path


def log(msg: str) -> None:
    print(f"[profile_run] {msg}", file=sys.stderr)


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    log("$ " + " ".join(cmd))
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=3600)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def emit_hotspots(hotspots: list[dict], meta: dict, out_dir: Path | None) -> int:
    # Rank is ALWAYS by self-time (own time), because that is the only thing optimizing a single
    # function can actually shrink. cumtime tells you where to look; tottime tells you what to fix.
    hotspots.sort(key=lambda h: h.get("self", 0.0), reverse=True)
    for i, h in enumerate(hotspots):
        h["rank"] = i + 1
    doc = {**meta, "ranked_by": "self_time", "hotspots": hotspots[: meta.get("top", 25)]}
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "hotspots.json").write_text(json.dumps(doc, indent=2), "utf-8")
        log(f"wrote {out_dir / 'hotspots.json'}")
    print(json.dumps(doc, indent=2))
    if doc["hotspots"]:
        top = doc["hotspots"][0]
        log(f"TOP self-time offender: {top.get('symbol')}  self={top.get('self')}  "
            f"({top.get('pct_self', '?')}% of measured time) -> fix THIS one, then re-profile.")
    return 0


# --- Python -------------------------------------------------------------------
def prof_python_cprofile(cmd: str, sort: str, top: int, out_dir: Path) -> int:
    """Run a Python command under cProfile, then normalize the pstats dump to hotspots."""
    out_dir.mkdir(parents=True, exist_ok=True)
    dump = out_dir / "cprofile.pstats"
    parts = cmd.split()
    # python -m cProfile -o <dump> <script...>  — wrap the user's command after the python exe.
    if parts and parts[0] in ("python", "python3", sys.executable):
        wrapped = [parts[0], "-m", "cProfile", "-o", str(dump), *parts[1:]]
    else:
        wrapped = [sys.executable, "-m", "cProfile", "-o", str(dump), *parts]
    rc, _, err = run(wrapped)
    if not dump.exists():
        log(f"cProfile produced no dump (rc={rc}): {err[:300]}")
        return 1
    return ingest_cprofile(dump, sort, top, out_dir)


def ingest_cprofile(dump: Path, sort: str, top: int, out_dir: Path | None) -> int:
    st = pstats.Stats(str(dump))
    hotspots: list[dict] = []
    total_tt = 0.0
    # pstats stats dict: key=(file,line,func) -> (cc, nc, tt, ct, callers)
    for (fn, ln, func), (cc, nc, tt, ct, _callers) in st.stats.items():  # type: ignore[attr-defined]
        total_tt += tt
        hotspots.append({
            "symbol": f"{func} ({Path(fn).name}:{ln})",
            "file": fn,
            "line": ln,
            "ncalls": nc,
            "self": round(tt, 6),       # tottime — own time (the hotspot signal)
            "cumulative": round(ct, 6), # cumtime — own + callees
        })
    for h in hotspots:
        h["pct_self"] = round(100.0 * h["self"] / total_tt, 2) if total_tt else 0.0
    meta = {"stack": "python", "profiler": "cProfile", "sort_hint": sort,
            "total_self_seconds": round(total_tt, 6), "top": top, "artifact": str(dump)}
    return emit_hotspots(hotspots, meta, out_dir)


def prof_pyspy(pid: int | None, cmd: str | None, duration: int, out_dir: Path) -> int:
    if not have("py-spy"):
        log("SKIP py-spy (not installed). Install: pipx install py-spy / uv tool install py-spy")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / "pyspy.json"  # speedscope-compatible; agent reads self time per frame
    base = ["py-spy", "record", "-f", "speedscope", "-o", str(raw), "-d", str(duration)]
    if pid is not None:
        rc, _, err = run([*base, "--pid", str(pid)])
    elif cmd:
        rc, _, err = run([*base, "--", *cmd.split()])
    else:
        log("py-spy needs --pid or --cmd")
        return 2
    if not raw.exists():
        log(f"py-spy produced nothing (rc={rc}): {err[:300]}  (Linux needs sudo/ptrace_scope)")
        return 1
    log(f"py-spy speedscope at {raw} — open at https://speedscope.app and read SELF time per frame.")
    print(json.dumps({"stack": "python", "profiler": "py-spy", "artifact": str(raw),
                      "note": "speedscope file; rank frames by self time"}, indent=2))
    return 0


def prof_scalene(cmd: str, out_dir: Path) -> int:
    if not have("scalene"):
        log("SKIP scalene (not installed). Install: pipx install scalene")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    rep = out_dir / "scalene.json"
    rc, _, err = run(["scalene", "--json", "--outfile", str(rep), "--cli", "---", *cmd.split()])
    if not rep.exists():
        # scalene's CLI separator differs across versions; fall back to the simple form.
        rc, _, err = run(["scalene", "--json", "--outfile", str(rep), *cmd.split()])
    if not rep.exists():
        log(f"scalene produced no report (rc={rc}): {err[:300]}")
        return 1
    log(f"scalene CPU+GPU+mem report at {rep} — flags memory growth + CPU self time per line.")
    print(json.dumps({"stack": "python", "profiler": "scalene", "artifact": str(rep)}, indent=2))
    return 0


# --- Node ---------------------------------------------------------------------
def prof_node(tool: str, cmd: str, out_dir: Path) -> int:
    """clinic doctor = triage (event-loop / GC / CPU); flame (0x) = CPU flamegraph."""
    if tool in ("doctor", "bubbleprof", "heapprofiler"):
        if not have("clinic"):
            log("SKIP clinic (not installed). Install: npm i -g clinic")
            return 0
        rc, out, err = run(["clinic", tool, "--", *cmd.split()], cwd=out_dir if out_dir.exists() else None)
        log("clinic wrote a .clinic-* dir + HTML report — open it; doctor's recommendation "
            "names the bottleneck class (event loop / GC / I/O / CPU).")
        print(json.dumps({"stack": "node", "profiler": f"clinic {tool}",
                          "note": "open the generated HTML; read the recommendation banner"}, indent=2))
        return 0
    if tool == "flame":
        if not have("0x"):
            log("SKIP 0x (not installed). Install: npm i -g 0x")
            return 0
        run(["0x", "--", *cmd.split()])
        log("0x wrote a flamegraph HTML — WIDE frames = high self time. Click to isolate the hot stack.")
        print(json.dumps({"stack": "node", "profiler": "0x",
                          "note": "open the flamegraph HTML; widest self frame = the fix target"}, indent=2))
        return 0
    log(f"unknown node tool: {tool} (use doctor|flame|bubbleprof|heapprofiler)")
    return 2


# --- Emit-only (need app/browser/IDE) ----------------------------------------
REACT_STEPS = """\
# React DevTools Profiler — measure, don't guess which component re-renders.
1. Run the app in a profileable build (dev build, or prod with profiling:
     vite:  build keeps it; for CRA `npm run build -- --profile`).
2. Open React DevTools -> Profiler tab -> gear -> enable
     "Record why each component rendered while profiling".
3. Click record, perform the slow interaction once, stop.
4. Read the FLAMEGRAPH (commit-by-commit): a bar's width = that commit's render time.
   Compare actualDuration (this render) vs baseDuration (no-memo cost). A component whose
   actualDuration ~= baseDuration on every commit is doing FULL work each time = the hotspot.
5. "Ranked" view lists components by time spent in the selected commit (self-time analog).
6. Use the "why did this render?" reason to see if it was props/state/parent/hook.

FIX PREFERENCE: enable the React Compiler (auto-memoization) over hand-written useMemo/
useCallback/React.memo. Reach for manual memo ONLY when the profiler proves a specific
component re-renders with unchanged props AND the compiler can't cover it. Never memoize blind.
"""

JVM_TEMPLATE = """\
# JVM — async-profiler (wall+alloc, low overhead) + Java Flight Recorder + Eclipse MAT for leaks.
# async-profiler (sampling; safe in prod). PID = {pid}
asprof -d 30 -e cpu   -f cpu.html   {pid}     # CPU flamegraph (wide self frame = hotspot)
asprof -d 30 -e alloc -f alloc.html {pid}     # allocation flamegraph (memory pressure source)
asprof -d 30 -e lock  -f lock.html  {pid}     # lock contention (scalability ceiling)

# Java Flight Recorder (built into the JDK; richest timeline)
jcmd {pid} JFR.start name=perf settings=profile duration=60s filename=rec.jfr
jcmd {pid} JFR.dump  name=perf filename=rec.jfr
#   open rec.jfr in JDK Mission Control -> "Method Profiling" = self-time hot methods,
#   "Memory" -> "Allocation" = who allocates, "Garbage Collections" = GC pause cost.

# Memory leak: take a heap dump, open in Eclipse MAT, run "Leak Suspects".
jcmd {pid} GC.heap_dump /tmp/heap.hprof
#   MAT -> Leak Suspects report -> dominator tree: the object retaining the most heap is the leak root.
"""


def emit_react() -> int:
    print(REACT_STEPS)
    log("React profiling is interactive — run the steps, then `ingest` the Ranked-view timings if exported.")
    return 0


def emit_jvm(pid: int | None) -> int:
    print(JVM_TEMPLATE.format(pid=pid if pid is not None else "<PID>"))
    if not have("asprof"):
        log("note: async-profiler (asprof) not on PATH — download from the async-profiler releases.")
    log("Run these against the live JVM, then read self-time in the flamegraph / JMC method profiler.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Measure-first profiler orchestrator.")
    sub = ap.add_subparsers(dest="stack", required=True)

    py = sub.add_parser("python", help="cProfile a Python command")
    py.add_argument("--cmd", required=True)
    py.add_argument("--sort", default="tottime", help="hint only; output is always self-time ranked")
    py.add_argument("--top", type=int, default=25)
    py.add_argument("--out", default=".perf")

    sp = sub.add_parser("py-spy", help="live/attach sampling profiler")
    sp.add_argument("--pid", type=int)
    sp.add_argument("--cmd")
    sp.add_argument("--duration", type=int, default=30)
    sp.add_argument("--out", default=".perf")

    sc = sub.add_parser("scalene", help="CPU+GPU+memory profiler")
    sc.add_argument("--cmd", required=True)
    sc.add_argument("--out", default=".perf")

    nd = sub.add_parser("node", help="clinic doctor / 0x flame")
    nd.add_argument("--tool", default="doctor", help="doctor|flame|bubbleprof|heapprofiler")
    nd.add_argument("--cmd", required=True)
    nd.add_argument("--out", default=".perf")

    sub.add_parser("react", help="emit React DevTools Profiler steps")

    jv = sub.add_parser("jvm", help="emit async-profiler + JFR commands")
    jv.add_argument("--pid", type=int)

    ing = sub.add_parser("ingest", help="normalize an existing profiler artifact to hotspots.json")
    ing.add_argument("--kind", required=True, choices=["cprofile"], help="artifact kind")
    ing.add_argument("--file", required=True)
    ing.add_argument("--sort", default="tottime")
    ing.add_argument("--top", type=int, default=25)
    ing.add_argument("--out", default=".perf")

    args = ap.parse_args()

    if args.stack == "python":
        return prof_python_cprofile(args.cmd, args.sort, args.top, Path(args.out))
    if args.stack == "py-spy":
        return prof_pyspy(args.pid, args.cmd, args.duration, Path(args.out))
    if args.stack == "scalene":
        return prof_scalene(args.cmd, Path(args.out))
    if args.stack == "node":
        return prof_node(args.tool, args.cmd, Path(args.out))
    if args.stack == "react":
        return emit_react()
    if args.stack == "jvm":
        return emit_jvm(args.pid)
    if args.stack == "ingest":
        if args.kind == "cprofile":
            return ingest_cprofile(Path(args.file), args.sort, args.top, Path(args.out))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
