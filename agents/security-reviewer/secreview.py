#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
secreview.py — deterministic Layer-1 security gate orchestrator.

Detects the stack, runs whichever scanners are installed (Semgrep, Gitleaks, language-native
SAST, dependency scanners), normalizes everything to SARIF, merges + dedupes into one digest,
and prints a summary. The AI reasoning layer (Layer 2) then reads reports/_digest.json + the
git diff. READ-ONLY on source: only ever writes under <repo>/reports/ (add it to .gitignore).

Missing tools are SKIPPED with a logged note — the run never hard-fails on one absent binary.

Usage:
  uv run secreview.py full    <repo> [--deep] [--native]
  uv run secreview.py diff    <repo> [--base origin/main]
  uv run secreview.py secrets <repo>
  uv run secreview.py deps    <repo>
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path

REPORTS = "reports"


def log(msg: str) -> None:
    print(f"[secreview] {msg}", file=sys.stderr)


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
    f = {p.name for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}
    if "pom.xml" in f or any(repo.rglob("build.gradle*")):
        s.add("java")
    if "package.json" in f:
        s.add("node")
        try:
            pkg = json.loads((next(repo.rglob("package.json"))).read_text("utf-8"))
            dep = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "next" in dep:
                s.add("next")
            if "vite" in dep or "@vitejs/plugin-react" in dep:
                s.add("vite")
            if "expo" in dep or "react-native" in dep:
                s.add("rn")
        except Exception:
            pass
    if "requirements.txt" in f or "pyproject.toml" in f or "setup.py" in f:
        s.add("python")
    if any(repo.rglob("*.go")):
        s.add("go")
    return s


def sarif_findings(path: Path) -> list[dict]:
    try:
        doc = json.loads(path.read_text("utf-8"))
    except Exception:
        return []
    out = []
    for run_ in doc.get("runs", []):
        tool = run_.get("tool", {}).get("driver", {}).get("name", "?")
        for r in run_.get("results", []):
            loc = (r.get("locations") or [{}])[0].get("physicalLocation", {})
            art = loc.get("artifactLocation", {}).get("uri", "?")
            line = loc.get("region", {}).get("startLine", 0)
            out.append({
                "tool": tool,
                "ruleId": r.get("ruleId", "?"),
                "level": r.get("level", "warning"),
                "message": (r.get("message", {}) or {}).get("text", "")[:300],
                "file": art,
                "line": line,
            })
    return out


def scan_semgrep(repo: Path, rep: Path, deep: bool) -> None:
    if not have("semgrep") and not have("opengrep"):
        log("SKIP semgrep/opengrep (not installed)")
        return
    bin_ = "semgrep" if have("semgrep") else "opengrep"
    cfgs = ["--config", "p/security-audit", "--config", "p/owasp-top-ten", "--config", "p/secrets"]
    out = rep / "semgrep.sarif"
    run([bin_, "scan", *cfgs, "--sarif", "--output", str(out), "--quiet", "--timeout", "120", "."], repo)


def scan_gitleaks(repo: Path, rep: Path) -> None:
    if not have("gitleaks"):
        log("SKIP gitleaks (not installed)")
        return
    is_git = (repo / ".git").exists()
    if is_git:
        run(["gitleaks", "git", "-v", "--report-format", "sarif",
             "--report-path", str(rep / "gitleaks-history.sarif"), "."], repo)
    run(["gitleaks", "dir", "--report-format", "sarif",
         "--report-path", str(rep / "gitleaks-tree.sarif"), "."], repo)


def scan_native(repo: Path, rep: Path, stacks: set[str]) -> None:
    if "python" in stacks and have("bandit"):
        run(["bandit", "-r", ".", "-ll", "-f", "sarif", "-o", str(rep / "bandit.sarif")], repo)
    if "go" in stacks and have("gosec"):
        run(["gosec", "-fmt", "sarif", "-out", str(rep / "gosec.sarif"), "./..."], repo)
    if {"node", "vite", "next", "rn"} & stacks and have("njsscan"):
        run(["njsscan", "--sarif", "-o", str(rep / "njsscan.sarif"), "."], repo)


def scan_deps(repo: Path, rep: Path, stacks: set[str]) -> None:
    if "python" in stacks and have("pip-audit"):
        req = repo / "requirements.txt"
        cmd = ["pip-audit", "-f", "sarif", "-o", str(rep / "pip-audit.sarif")]
        if req.exists():
            cmd += ["-r", "requirements.txt"]
        run(cmd, repo)
    if {"node", "vite", "next", "rn"} & stacks and have("osv-scanner"):
        run(["osv-scanner", "--format", "sarif", "--output", str(rep / "osv.sarif"), "-r", "."], repo)
    if have("trivy"):
        run(["trivy", "fs", "--scanners", "vuln,secret,misconfig", "--format", "sarif",
             "-o", str(rep / "trivy.sarif"), "."], repo)
    if "java" in stacks and have("dependency-check"):
        run(["dependency-check", "--scan", ".", "--format", "SARIF", "--out", str(rep)], repo)


def merge(rep: Path) -> dict:
    all_findings: list[dict] = []
    seen: set[tuple] = set()
    for sarif in sorted(rep.glob("*.sarif")):
        for fnd in sarif_findings(sarif):
            key = (fnd["file"], fnd["line"], fnd["ruleId"])
            if key in seen:
                continue
            seen.add(key)
            all_findings.append(fnd)
    sev_order = {"error": 0, "warning": 1, "note": 2, "none": 3}
    all_findings.sort(key=lambda f: (sev_order.get(f["level"], 9), f["file"], f["line"]))
    digest = {
        "total": len(all_findings),
        "by_level": _counts(all_findings, "level"),
        "by_tool": _counts(all_findings, "tool"),
        "findings": all_findings,
    }
    (rep / "_digest.json").write_text(json.dumps(digest, indent=2), "utf-8")
    return digest


def _counts(items: list[dict], key: str) -> dict:
    c: dict[str, int] = {}
    for it in items:
        c[it[key]] = c.get(it[key], 0) + 1
    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["full", "diff", "secrets", "deps"])
    ap.add_argument("repo")
    ap.add_argument("--base", default="origin/main", help="diff base ref")
    ap.add_argument("--deep", action="store_true", help="opt-in CodeQL (OSI/public repos only)")
    ap.add_argument("--native", action="store_true", help="run language-native SAST too")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.exists():
        log(f"no such repo: {repo}")
        return 2
    rep = repo / REPORTS
    rep.mkdir(exist_ok=True)
    stacks = detect_stack(repo)
    log(f"stacks: {sorted(stacks) or ['?']}  mode: {args.mode}")

    if args.mode in ("full", "diff"):
        scan_semgrep(repo, rep, args.deep)
        scan_gitleaks(repo, rep)
        if args.native or args.mode == "full":
            scan_native(repo, rep, stacks)
        scan_deps(repo, rep, stacks)
    elif args.mode == "secrets":
        scan_gitleaks(repo, rep)
    elif args.mode == "deps":
        scan_deps(repo, rep, stacks)

    digest = merge(rep)
    print(json.dumps({"stacks": sorted(stacks), "mode": args.mode,
                      "total": digest["total"], "by_level": digest["by_level"],
                      "by_tool": digest["by_tool"], "reports": str(rep)}, indent=2))
    if args.mode == "diff":
        rc, out, _ = run(["git", "diff", "--name-only", f"{args.base}...HEAD"], repo)
        print("\n# changed files vs", args.base, "\n" + out)
    log("Layer-1 done. Next: feed reports/_digest.json + git diff to the claude-code-security-review prompt (≥0.8 confidence, 18-item exclusion list).")
    # exit non-zero if any error-level finding (gate behavior)
    return 1 if digest["by_level"].get("error", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
