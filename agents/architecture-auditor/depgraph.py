#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
depgraph.py — produce the dependency graph + circular-dep + orphan-module report as JSON.

Two backends, auto-selected by stack:
  * JS / TS  → drives `dependency-cruiser` (npx depcruise) for a precise module graph, then folds
               file-level edges up to a package/directory graph. Reports cycles + orphans natively.
  * Java     → stdlib scan of `import` statements -> Java package graph (ArchUnit/JDepend-style),
               no JVM tooling required.
  * Python   → stdlib scan of `import` / `from x import` -> module/package graph.

Emits a normalized graph archmetrics.py consumes to compute Ca/Ce/Instability/Abstractness/Distance:
  {
    "nodes": { "<package>": {"total_types": N, "abstract_types": M, "files": K} },
    "edges": [ {"from": "<pkg>", "to": "<pkg>"} ],
    "cycles": [ ["a","b"], ... ],          # 2+-node strongly-connected components
    "orphans": [ "<module with no in/out edges>" ]
  }

READ-ONLY on source: only writes <repo>/arch-reports/_depgraph.json. If dependency-cruiser is
absent for a JS/TS repo it falls back to the stdlib import-scan (logged), never hard-fails.

Usage:
  uv run depgraph.py <repo> [--out arch-reports]
"""
from __future__ import annotations
import argparse, json, re, shutil, subprocess, sys
from pathlib import Path

OUT_DIR = "arch-reports"
IGNORE_DIRS = {
    ".git", "node_modules", "dist", "build", "target", ".next", "out", "venv", ".venv",
    "__pycache__", ".mvn", ".gradle", "coverage", "vendor", "migrations", ".idea", ".vscode",
}


def log(msg: str) -> None:
    print(f"[depgraph] {msg}", file=sys.stderr)


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


def _ignored(p: Path, repo: Path) -> bool:
    try:
        rel = p.relative_to(repo)
    except ValueError:
        return True
    return any(part in IGNORE_DIRS for part in rel.parts)


def detect_stack(repo: Path) -> set[str]:
    s: set[str] = set()
    if any(repo.rglob("pom.xml")) or any(repo.rglob("build.gradle*")):
        s.add("java")
    if any(repo.rglob("package.json")):
        s.add("node")
        if any(repo.rglob("tsconfig.json")):
            s.add("ts")
    if any(repo.rglob("requirements.txt")) or any(repo.rglob("pyproject.toml")):
        s.add("python")
    return s


# ── JS/TS via dependency-cruiser ────────────────────────────────────────────────────────────────
def graph_js(repo: Path) -> dict | None:
    """Run dependency-cruiser; fold module edges up to top-level src directories (the 'packages')."""
    runner = None
    if have("depcruise"):
        runner = ["depcruise"]
    elif have("npx"):
        runner = ["npx", "--no-install", "depcruise"]
    if not runner:
        log("dependency-cruiser not available (no depcruise / npx) — falling back to import-scan")
        return None
    src = "src" if (repo / "src").exists() else "."
    rc, out, err = run([*runner, "--include-only", f"^{src}", "--no-config",
                        "--output-type", "json", src], repo)
    if rc not in (0, 1) or not out.strip():
        log(f"depcruise produced no usable output (rc={rc}): {err.strip()[:200]} — using import-scan")
        return None
    try:
        doc = json.loads(out)
    except Exception as e:
        log(f"depcruise json parse error: {e} — using import-scan")
        return None

    def pkg_of(module_path: str) -> str:
        parts = [p for p in module_path.split("/") if p not in (".", "")]
        # group by the directory just under src/, e.g. src/auth/login.ts -> src/auth
        if len(parts) >= 2:
            return "/".join(parts[:2])
        return parts[0] if parts else module_path

    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str]] = set()
    orphans: list[str] = []
    for mod in doc.get("modules", []):
        src_path = mod.get("source", "")
        if not src_path or any(d in src_path for d in IGNORE_DIRS):
            continue
        a = pkg_of(src_path)
        node = nodes.setdefault(a, {"total_types": 0, "abstract_types": 0, "files": 0})
        node["files"] += 1
        node["total_types"] += 1   # 1 module ≈ 1 type for the abstractness heuristic
        if mod.get("orphan"):
            orphans.append(src_path)
        for dep in mod.get("dependencies", []):
            tgt = dep.get("resolved", "")
            if not tgt or dep.get("coreModule") or "node_modules" in tgt:
                continue
            b = pkg_of(tgt)
            if a != b:
                edges.add((a, b))
    return {
        "backend": "dependency-cruiser",
        "nodes": nodes,
        "edges": [{"from": a, "to": b} for a, b in sorted(edges)],
        "orphans": sorted(set(orphans)),
    }


# ── Java via stdlib import scan ─────────────────────────────────────────────────────────────────
JAVA_PKG = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
JAVA_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.M)
JAVA_ABSTRACT = re.compile(r"\b(interface\s+\w+|abstract\s+class\s+\w+|@interface\s+\w+)")
JAVA_TYPE = re.compile(r"\b(class|interface|enum|record)\s+\w+")


def graph_java(repo: Path) -> dict:
    files = [p for p in repo.rglob("*.java") if not _ignored(p, repo)]
    pkg_files: dict[str, list[Path]] = {}
    for f in files:
        try:
            text = f.read_text("utf-8", errors="ignore")
        except Exception:
            continue
        m = JAVA_PKG.search(text)
        pkg = m.group(1) if m else "(default)"
        pkg_files.setdefault(pkg, []).append(f)

    own_pkgs = set(pkg_files)
    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str]] = set()
    for pkg, fl in pkg_files.items():
        total = abstract = 0
        for f in fl:
            text = f.read_text("utf-8", errors="ignore")
            total += len(JAVA_TYPE.findall(text))
            abstract += len(JAVA_ABSTRACT.findall(text))
            for imp in JAVA_IMPORT.findall(text):
                target_pkg = imp.rsplit(".", 1)[0]      # drop the class name
                # only edges to packages that exist in THIS project (internal coupling)
                hit = next((op for op in own_pkgs if target_pkg == op or target_pkg.startswith(op + ".")), None)
                if hit and hit != pkg:
                    edges.add((pkg, hit))
        nodes[pkg] = {"total_types": total, "abstract_types": abstract, "files": len(fl)}
    return {"backend": "java-import-scan", "nodes": nodes,
            "edges": [{"from": a, "to": b} for a, b in sorted(edges)], "orphans": []}


# ── Python via stdlib import scan ───────────────────────────────────────────────────────────────
PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)
PY_ABSTRACT = re.compile(r"(\bclass\s+\w+\([^)]*\bABC\b|@abstractmethod|\bProtocol\b|\(Protocol\))")
PY_CLASS = re.compile(r"^\s*class\s+\w+", re.M)


def _py_module(f: Path, repo: Path) -> str:
    rel = f.relative_to(repo).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else rel.name


def graph_python(repo: Path) -> dict:
    files = [p for p in repo.rglob("*.py") if not _ignored(p, repo)]
    modules = {_py_module(f, repo): f for f in files}
    top_pkgs = {m.split(".")[0] for m in modules}

    def pkg_of(mod: str) -> str:
        parts = mod.split(".")
        return ".".join(parts[:2]) if len(parts) >= 2 else parts[0]

    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str]] = set()
    for mod, f in modules.items():
        a = pkg_of(mod)
        text = f.read_text("utf-8", errors="ignore")
        node = nodes.setdefault(a, {"total_types": 0, "abstract_types": 0, "files": 0})
        node["files"] += 1
        node["total_types"] += len(PY_CLASS.findall(text))
        node["abstract_types"] += len(PY_ABSTRACT.findall(text))
        for frm, plain in PY_IMPORT.findall(text):
            target = frm or plain
            root = target.split(".")[0]
            if root in top_pkgs:                # internal import only
                b = pkg_of(target)
                if b in {pkg_of(m) for m in modules} and a != b:
                    edges.add((a, b))
    # a module with 0 in and 0 out edges is an orphan
    touched = {x for e in edges for x in e}
    orphans = sorted(n for n in nodes if n not in touched and len(nodes) > 1)
    return {"backend": "python-import-scan", "nodes": nodes,
            "edges": [{"from": a, "to": b} for a, b in sorted(edges)], "orphans": orphans}


# ── cycles (Tarjan SCC) ─────────────────────────────────────────────────────────────────────────
def find_cycles(nodes: dict, edges: list[dict]) -> list[list[str]]:
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for e in edges:
        a, b = e["from"], e["to"]
        if a in adj and b in adj and a != b:
            adj[a].append(b)
    index = 0
    idx, low, on_stack, stack, sccs = {}, {}, {}, [], []

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
            comp = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                sccs.append(sorted(comp))

    sys.setrecursionlimit(10000)
    for v in list(adj):
        if v not in idx:
            strongconnect(v)
    sccs.sort(key=len, reverse=True)
    return sccs


def main() -> int:
    ap = argparse.ArgumentParser(description="Dependency graph + cycles + orphans (read-only).")
    ap.add_argument("repo")
    ap.add_argument("--out", default=OUT_DIR, help="output dir (relative to repo)")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.exists():
        log(f"no such repo: {repo}")
        return 2
    out_dir = repo / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    stacks = detect_stack(repo)
    log(f"stacks: {sorted(stacks) or ['?']}")

    graph: dict | None = None
    if {"node", "ts"} & stacks:
        graph = graph_js(repo)
    if graph is None and "java" in stacks:
        graph = graph_java(repo)
    if graph is None and "python" in stacks:
        graph = graph_python(repo)
    if graph is None:
        # last resort: try whatever sources exist
        if any(repo.rglob("*.java")):
            graph = graph_java(repo)
        elif any(repo.rglob("*.py")):
            graph = graph_python(repo)
        else:
            log("no supported sources found — emitting empty graph")
            graph = {"backend": "none", "nodes": {}, "edges": [], "orphans": []}

    cycles = find_cycles(graph["nodes"], graph["edges"])
    result = {
        "repo": repo.name,
        "backend": graph.get("backend"),
        "stacks": sorted(stacks),
        "nodes": graph["nodes"],
        "edges": graph["edges"],
        "cycles": cycles,
        "orphans": graph.get("orphans", []),
        "summary": {
            "packages": len(graph["nodes"]),
            "edges": len(graph["edges"]),
            "cycles": len(cycles),
            "orphans": len(graph.get("orphans", [])),
        },
    }
    (out_dir / "_depgraph.json").write_text(json.dumps(result, indent=2), "utf-8")
    print(json.dumps({"repo": repo.name, "backend": result["backend"],
                      "summary": result["summary"], "report": str(out_dir / "_depgraph.json")},
                     indent=2))
    if cycles:
        log(f"{len(cycles)} dependency cycle(s) found — every SCC is a finding. Largest: {cycles[0]}")
    log("Done. archmetrics.py reads _depgraph.json to compute Ca/Ce/Instability/Abstractness/Distance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
