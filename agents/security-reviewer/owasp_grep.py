#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
owasp_grep.py — per-stack OWASP Top-10 candidate finder.

Stdlib-only (no ripgrep dependency): walks the repo, applies framework-keyed regex rules, and
emits structured *candidates* for the AI layer to CONFIRM at confidence >= 0.8. These are
high-recall / low-precision by design — every hit is a question, not a verdict. NEVER prints the
matched secret value for secret-class rules: only file:line + rule.

Usage:  uv run owasp_grep.py <repo> [--json]
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "dist", "build", ".next", "target",
             "__pycache__", ".gradle", "vendor", "reports", ".idea"}
TEXT_EXT = {".java", ".kt", ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".go", ".rb", ".php",
            ".yml", ".yaml", ".properties", ".env", ".xml", ".json", ".gradle", ".tsx"}

# (owasp, rule, regex, redact?) — redact=True means never echo the matched line content
RULES = [
    ("A05", "cors-wildcard-credentials",
     r"(allow_origins\s*=\s*\[?\s*[\"']\*[\"']|Access-Control-Allow-Origin[\"'\s:]+\*)", False),
    ("A05", "cors-credentials-true", r"allow_credentials\s*=\s*True|credentials:\s*true", False),
    ("A10", "ssrf-metadata", r"169\.254\.169\.254|metadata\.google\.internal", False),
    ("A02", "jwt-alg-none", r"alg['\"\s:=]+none|verify\s*=\s*False|verifyJwt.*false", False),
    ("A03", "sql-string-concat",
     r"(execute|query|createQuery|prepareStatement)\s*\(\s*[\"'].*\+|f[\"'].*SELECT .*\{", False),
    ("A03", "command-injection",
     r"shell\s*=\s*True|Runtime\.getRuntime\(\)\.exec|child_process\.exec\(|os\.system\(", False),
    ("A03", "xss-dangerous-html",
     r"dangerouslySetInnerHTML|v-html|\.innerHTML\s*=", False),
    ("A02", "token-in-localstorage", r"localStorage\.setItem\([^)]*[Tt]oken", False),
    ("A02", "rn-asyncstorage-token", r"AsyncStorage\.setItem\([^)]*([Tt]oken|secret|password)", False),
    ("A08", "webhook-no-verify",
     r"(permitAll\(\).*webhook|@PostMapping.*webhook)", False),
    ("A05", "actuator-exposed",
     r"management\.endpoints\.web\.exposure\.include\s*=\s*\*|expose.*actuator", False),
    ("A05", "committed-key-material",
     r"-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----", True),
    ("A07", "hardcoded-password",
     r"(password|passwd|pwd)\s*[:=]\s*[\"'][^\"']{4,}[\"']", True),
    ("A02", "client-side-secret-prefix",
     r"(VITE_|NEXT_PUBLIC_|EXPO_PUBLIC_)\w*(SECRET|PASSWORD|KEY|TOKEN)", True),
    ("A06", "eval-dynamic",
     r"\beval\(|new Function\(|pickle\.loads\(", False),
    ("A05", "debug-true-prod", r"DEBUG\s*=\s*True|app\.debug\s*=\s*true", False),
]

# extra signal if these framework markers exist (raises priority, not a separate scan)
NEXT_HINT = re.compile(r"\"next\"\s*:")


def is_text(p: Path) -> bool:
    return p.suffix.lower() in TEXT_EXT or p.name in {".env", "Dockerfile"}


def walk(repo: Path):
    for p in repo.rglob("*"):
        if p.is_dir():
            continue
        if SKIP_DIRS & set(p.parts):
            continue
        if p.is_file() and is_text(p):
            yield p


def scan(repo: Path) -> list[dict]:
    compiled = [(o, name, re.compile(rx, re.IGNORECASE), redact) for o, name, rx, redact in RULES]
    out: list[dict] = []
    for f in walk(repo):
        try:
            lines = f.read_text("utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        rel = str(f.relative_to(repo))
        for i, line in enumerate(lines, 1):
            if len(line) > 1000:
                continue
            for owasp, name, rx, redact in compiled:
                if rx.search(line):
                    out.append({
                        "owasp": owasp,
                        "rule": name,
                        "file": rel,
                        "line": i,
                        "evidence": "[redacted]" if redact else line.strip()[:160],
                    })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    cands = scan(repo)
    by_owasp: dict[str, int] = {}
    for c in cands:
        by_owasp[c["owasp"]] = by_owasp.get(c["owasp"], 0) + 1
    result = {"repo": str(repo), "candidate_count": len(cands), "by_owasp": by_owasp, "candidates": cands}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"# {len(cands)} OWASP candidates (confirm each at >=0.8 confidence)")
        for c in cands:
            print(f"{c['owasp']} {c['rule']:28} {c['file']}:{c['line']}  {c['evidence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
