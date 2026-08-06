#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
buildscan.py — scan the SHIPPED build artifact for leaked secrets.

Front-end bundlers inline VITE_* / NEXT_PUBLIC_* / EXPO_PUBLIC_* env vars into the output bundle,
so a secret that is safe in .env can ship to every browser/device. This scans the BUILT artifact
(dist/ .next/static/ build/ or an extracted APK) with gitleaks/trufflehog, never the source tree.

It does NOT build for you by default (building can run untrusted scripts) — point it at an existing
build dir, or pass --build to run the project's build in a scratch copy.

Usage:
  uv run buildscan.py <repo> [--dist dist] [--apk app.apk]
"""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys, tempfile, zipfile
from pathlib import Path

CANDIDATE_DIRS = ["dist", "build", ".next/static", "web-build", "out"]
# things that legitimately ship to clients (publishable) — flag everything else
PUBLISHABLE_OK = ("pk_live_", "pk_test_", "AIza")  # Stripe publishable, Firebase web API key


def have(t: str) -> bool:
    return shutil.which(t) is not None


def find_build_dir(repo: Path, override: str | None) -> Path | None:
    if override:
        p = (repo / override) if not Path(override).is_absolute() else Path(override)
        return p if p.exists() else None
    for c in CANDIDATE_DIRS:
        p = repo / c
        if p.exists() and any(p.iterdir()):
            return p
    return None


def scan_dir(target: Path) -> dict:
    findings = []
    if have("gitleaks"):
        out = target.parent / "_buildscan-gitleaks.json"
        subprocess.run(["gitleaks", "dir", "--report-format", "json",
                        "--report-path", str(out), "--no-banner", "."],
                       cwd=target, capture_output=True, text=True)
        if out.exists():
            try:
                for f in json.loads(out.read_text("utf-8") or "[]"):
                    secret = f.get("Secret", "")
                    if secret.startswith(PUBLISHABLE_OK):
                        continue
                    findings.append({
                        "rule": f.get("RuleID"),
                        "file": f.get("File"),
                        "line": f.get("StartLine"),
                        "note": "publishable-ok" if secret.startswith(PUBLISHABLE_OK) else "LEAK in shipped bundle — rotate",
                    })
            except Exception as e:
                print(f"[buildscan] parse error: {e}", file=sys.stderr)
    else:
        print("[buildscan] gitleaks not installed — install it for bundle scanning", file=sys.stderr)
    return {"scanned": str(target), "leak_count": len(findings), "findings": findings}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--dist", help="explicit build dir (relative to repo or absolute)")
    ap.add_argument("--apk", help="path to an .apk to extract + scan")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()

    if args.apk:
        apk = Path(args.apk)
        with tempfile.TemporaryDirectory() as td:
            with zipfile.ZipFile(apk) as z:
                z.extractall(td)
            result = scan_dir(Path(td))
            print(json.dumps(result, indent=2))
            return 1 if result["leak_count"] else 0

    bdir = find_build_dir(repo, args.dist)
    if not bdir:
        print(json.dumps({"error": "no build dir found",
                          "hint": f"build first, or pass --dist; looked in {CANDIDATE_DIRS}"}, indent=2))
        return 0
    result = scan_dir(bdir)
    print(json.dumps(result, indent=2))
    if result["leak_count"]:
        print(f"\n[buildscan] {result['leak_count']} secret(s) shipped in {bdir} — ROTATE them and "
              f"remove from the client bundle (never put real secrets behind VITE_/NEXT_PUBLIC_/EXPO_PUBLIC_).",
              file=sys.stderr)
    return 1 if result["leak_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
