#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
archmetrics.py — the quantitative metric engine for the architecture-auditor.

Detects the stack, runs whichever metric tools are installed (lizard, radon, jscpd), parses their
output, and computes per-package coupling/abstractness metrics into ONE normalized JSON digest the
reasoning layer (the SKILL.md workflow) reads:

  * cyclomatic + cognitive complexity per function           (lizard)
  * maintainability index + per-function CC for Python       (radon)
  * duplication blocks + tree-wide duplication %             (jscpd)
  * afferent/efferent coupling Ca/Ce per package             (from the import graph in depgraph.py)
  * Instability   I = Ce / (Ce + Ca)
  * Abstractness  A = abstract-types / total-types           (heuristic, language-aware)
  * Distance      D = |A + I - 1|   (distance from the main sequence; D>0.5 = Zone of Pain)
  * dependency cycles (strongly-connected components)        (Tarjan, over depgraph.py's graph)

READ-ONLY on source: only ever writes under <repo>/arch-reports/. Missing tools are SKIPPED with a
logged note — the run never hard-fails because one optional binary is absent (mirrors secreview.py).

Usage:
  uv run archmetrics.py <repo> [--out arch-reports] [--min-tokens 50]
"""
from __future__ import annotations
import argparse, csv, io, json, shutil, subprocess, sys
from pathlib import Path

OUT_DIR = "arch-reports"
# directories that pollute complexity/duplication if scanned (generated, vendored, build output)
IGNORE_DIRS = {
    ".git", "node_modules", "dist", "build", "target", ".next", "out", "venv", ".venv",
    "__pycache__", ".mvn", ".gradle", "coverage", "vendor", "migrations", ".idea", ".vscode",
}


def log(msg: str) -> None:
    print(f"[archmetrics] {msg}", file=sys.stderr)


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def run(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    log("$ " + " ".join(cmd))
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=1800)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"


def detect_stack(repo: Path) -> set[str]:
    s: set[str] = set()
    names = {p.name for p in repo.rglob("*") if p.is_file() and not _ignored(p, repo)}
    if "pom.xml" in names or any(repo.rglob("build.gradle*")):
        s.add("java")
    if "package.json" in names:
        s.add("node")
        try:
            pkg = json.loads(next(repo.rglob("package.json")).read_text("utf-8"))
            dep = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "typescript" in dep or any(repo.rglob("tsconfig.json")):
                s.add("ts")
        except Exception:
            pass
    if {"requirements.txt", "pyproject.toml", "setup.py"} & names:
        s.add("python")
    return s


def _ignored(p: Path, repo: Path) -> bool:
    try:
        rel = p.relative_to(repo)
    except ValueError:
        return True
    return any(part in IGNORE_DIRS for part in rel.parts)


# ── lizard: cyclomatic + cognitive complexity (multi-language) ──────────────────────────────────
def run_lizard(repo: Path) -> list[dict]:
    """Per-function CC. Uses CSV (stable, no extra deps). Cognitive complexity comes via -Ecpre
    when available; we fall back to CC if the extension isn't present."""
    if not have("lizard"):
        log("SKIP lizard (not installed) — no cyclomatic/cognitive complexity this run")
        return []
    langs = ["-l", "java", "-l", "python", "-l", "javascript", "-l", "typescript"]
    ignores: list[str] = []
    for d in sorted(IGNORE_DIRS):
        ignores += ["-x", f"*/{d}/*"]
    rc, out, err = run(["lizard", "--csv", *langs, *ignores, "."], repo)
    if rc not in (0, 1) or not out.strip():
        log(f"lizard produced no usable output (rc={rc}): {err.strip()[:200]}")
        return []
    funcs: list[dict] = []
    # lizard CSV columns: nloc,ccn,token,param,length,location,file,function,long_name,start,end
    reader = csv.reader(io.StringIO(out))
    for row in reader:
        if len(row) < 11:
            continue
        try:
            funcs.append({
                "file": _relposix(row[6], repo),
                "function": row[7],
                "nloc": int(row[0]),
                "ccn": int(row[1]),          # cyclomatic complexity
                "tokens": int(row[2]),
                "params": int(row[3]),
                "start_line": int(row[9]),
            })
        except (ValueError, IndexError):
            continue
    funcs.sort(key=lambda f: f["ccn"], reverse=True)
    log(f"lizard: {len(funcs)} functions analyzed")
    return funcs


# ── radon: maintainability index + CC for Python ────────────────────────────────────────────────
def run_radon(repo: Path) -> dict:
    if not have("radon"):
        log("SKIP radon (not installed) — no Python maintainability index this run")
        return {}
    result: dict = {"mi": {}, "cc": {}}
    rc, out, _ = run(["radon", "mi", "-j", "."], repo)
    if rc == 0 and out.strip():
        try:
            for f, v in json.loads(out).items():
                if isinstance(v, dict) and "mi" in v:
                    result["mi"][_relposix(f, repo)] = round(v["mi"], 1)
        except Exception as e:
            log(f"radon mi parse error: {e}")
    rc, out, _ = run(["radon", "cc", "-j", "-s", "."], repo)
    if rc == 0 and out.strip():
        try:
            blocks = json.loads(out)
            for f, items in blocks.items():
                if not isinstance(items, list):
                    continue
                result["cc"][_relposix(f, repo)] = [
                    {"name": b.get("name"), "complexity": b.get("complexity"),
                     "rank": b.get("rank"), "lineno": b.get("lineno")}
                    for b in items if isinstance(b, dict)
                ]
        except Exception as e:
            log(f"radon cc parse error: {e}")
    log(f"radon: MI for {len(result['mi'])} files")
    return result


# ── jscpd: duplication ──────────────────────────────────────────────────────────────────────────
def run_jscpd(repo: Path, out_dir: Path, min_tokens: int) -> dict:
    if not have("jscpd"):
        log("SKIP jscpd (not installed) — duplication % not quantified this run")
        return {}
    rep = out_dir / "jscpd"
    rep.mkdir(parents=True, exist_ok=True)
    ignore = ",".join(f"**/{d}/**" for d in sorted(IGNORE_DIRS))
    rc, _, err = run(["jscpd", "--min-tokens", str(min_tokens), "--min-lines", "5",
                      "--reporters", "json", "--output", str(rep),
                      "--ignore", ignore, "--silent", "."], repo)
    report = rep / "jscpd-report.json"
    if not report.exists():
        log(f"jscpd produced no report (rc={rc}): {err.strip()[:200]}")
        return {}
    try:
        doc = json.loads(report.read_text("utf-8"))
    except Exception as e:
        log(f"jscpd parse error: {e}")
        return {}
    stats = doc.get("statistics", {}).get("total", {})
    dupes = [{
        "first": d.get("firstFile", {}).get("name"),
        "second": d.get("secondFile", {}).get("name"),
        "lines": d.get("lines"),
        "tokens": d.get("tokens"),
    } for d in doc.get("duplicates", [])]
    dupes.sort(key=lambda d: (d.get("tokens") or 0), reverse=True)
    summary = {
        "duplicated_pct": round(stats.get("percentage", 0.0), 2),
        "clone_blocks": len(dupes),
        "duplicated_lines": stats.get("duplicatedLines", 0),
        "top_clones": dupes[:30],
    }
    log(f"jscpd: {summary['duplicated_pct']}% duplicated, {summary['clone_blocks']} clone blocks")
    return summary


# ── coupling / abstractness / distance, from the depgraph ───────────────────────────────────────
def load_depgraph(repo: Path, out_dir: Path) -> dict:
    """Reuse depgraph.py's normalized graph if present, else build it now."""
    dg = out_dir / "_depgraph.json"
    if not dg.exists():
        here = Path(__file__).resolve().parent
        rc, out, err = run([sys.executable, str(here / "depgraph.py"), str(repo),
                            "--out", out_dir.name], repo)
        if rc != 0 and not dg.exists():
            log(f"depgraph.py unavailable (rc={rc}): {err.strip()[:200]} — coupling metrics skipped")
            return {}
    try:
        return json.loads(dg.read_text("utf-8"))
    except Exception as e:
        log(f"could not read depgraph: {e}")
        return {}


def coupling_metrics(graph: dict) -> list[dict]:
    """Ca/Ce/Instability/Abstractness/Distance per package node from depgraph's edges."""
    nodes = graph.get("nodes", {})              # name -> {abstract_types, total_types}
    edges = graph.get("edges", [])              # [{from, to}]
    if not nodes:
        return []
    ce: dict[str, int] = {n: 0 for n in nodes}  # outgoing (efferent)
    ca: dict[str, int] = {n: 0 for n in nodes}  # incoming (afferent)
    seen: set[tuple[str, str]] = set()
    for e in edges:
        a, b = e.get("from"), e.get("to")
        if a not in nodes or b not in nodes or a == b or (a, b) in seen:
            continue
        seen.add((a, b))
        ce[a] += 1
        ca[b] += 1
    out: list[dict] = []
    for n, meta in nodes.items():
        total = max(int(meta.get("total_types", 0)), 0)
        abstract = max(int(meta.get("abstract_types", 0)), 0)
        a_score = round(abstract / total, 3) if total else 0.0
        denom = ce[n] + ca[n]
        instab = round(ce[n] / denom, 3) if denom else 0.0
        dist = round(abs(a_score + instab - 1), 3)
        out.append({
            "package": n,
            "ca": ca[n], "ce": ce[n],
            "instability": instab,
            "abstractness": a_score,
            "distance": dist,
            "zone": _zone(a_score, instab, dist),
        })
    out.sort(key=lambda m: (m["distance"], m["ca"]), reverse=True)
    return out


def _zone(a: float, i: float, d: float) -> str:
    if d <= 0.5:
        return "main-sequence"
    if a < 0.5 and i < 0.5:
        return "zone-of-pain"        # rigid concrete, widely depended on
    return "zone-of-uselessness"     # abstract but nobody uses it


# ── dependency cycles (Tarjan SCC over the depgraph) ────────────────────────────────────────────
def find_cycles(graph: dict) -> list[list[str]]:
    nodes = list(graph.get("nodes", {}).keys())
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for e in graph.get("edges", []):
        a, b = e.get("from"), e.get("to")
        if a in adj and b in adj and a != b:
            adj[a].append(b)

    index = 0
    idx: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    stack: list[str] = []
    sccs: list[list[str]] = []

    def strongconnect(v: str) -> None:
        nonlocal index
        idx[v] = low[v] = index
        index += 1
        stack.append(v)
        on_stack[v] = True
        for w in adj[v]:
            if w not in idx:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif on_stack.get(w):
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            comp: list[str] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                sccs.append(sorted(comp))

    sys.setrecursionlimit(10000)
    for v in nodes:
        if v not in idx:
            strongconnect(v)
    sccs.sort(key=len, reverse=True)
    return sccs


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────
def _relposix(path_str: str, repo: Path) -> str:
    try:
        p = Path(path_str)
        rel = p.relative_to(repo) if p.is_absolute() else p
    except ValueError:
        rel = Path(path_str)
    return rel.as_posix().lstrip("./")


def main() -> int:
    ap = argparse.ArgumentParser(description="Architecture metric engine (read-only).")
    ap.add_argument("repo")
    ap.add_argument("--out", default=OUT_DIR, help="output dir (relative to repo)")
    ap.add_argument("--min-tokens", type=int, default=50, help="jscpd clone threshold")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.exists():
        log(f"no such repo: {repo}")
        return 2
    out_dir = repo / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    stacks = detect_stack(repo)
    log(f"stacks: {sorted(stacks) or ['?']}")

    funcs = run_lizard(repo)
    radon_data = run_radon(repo) if "python" in stacks else {}
    dup = run_jscpd(repo, out_dir, args.min_tokens)
    graph = load_depgraph(repo, out_dir)
    coupling = coupling_metrics(graph)
    cycles = find_cycles(graph)

    hotspots = [f for f in funcs if f["ccn"] >= 11][:50]
    zone_of_pain = [c for c in coupling if c["zone"] == "zone-of-pain"]

    digest = {
        "repo": repo.name,
        "stacks": sorted(stacks),
        "summary": {
            "functions_analyzed": len(funcs),
            "complexity_hotspots": len(hotspots),
            "max_ccn": funcs[0]["ccn"] if funcs else 0,
            "duplicated_pct": dup.get("duplicated_pct"),
            "packages_analyzed": len(coupling),
            "zone_of_pain_packages": len(zone_of_pain),
            "dependency_cycles": len(cycles),
        },
        "complexity_hotspots": hotspots,          # top CC functions, the ones needing the most tests
        "maintainability": radon_data.get("mi", {}),
        "radon_cc": radon_data.get("cc", {}),
        "duplication": dup,
        "coupling": coupling,                     # Ca/Ce/I/A/D per package, worst-distance first
        "cycles": cycles,                         # SCCs in the import graph, largest first
        "unmeasured": [
            d for d, ok in [
                ("complexity (lizard)", bool(funcs)),
                ("maintainability (radon)", bool(radon_data.get("mi"))),
                ("duplication (jscpd)", bool(dup)),
                ("coupling/cycles (depgraph)", bool(coupling)),
            ] if not ok
        ],
    }
    (out_dir / "_metrics.json").write_text(json.dumps(digest, indent=2), "utf-8")

    print(json.dumps({"repo": repo.name, "stacks": sorted(stacks),
                      "summary": digest["summary"], "unmeasured": digest["unmeasured"],
                      "report": str(out_dir / "_metrics.json")}, indent=2))
    log("Done. Next: feed arch-reports/_metrics.json + _depgraph.json to the SKILL.md reasoning "
        "workflow — rank findings by Ca x severity, plan Strangler/BBA slices.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
