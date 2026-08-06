#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""
promises.py — does this site keep the promises it makes?

Three legs. The third is the one people skip and the one that matters legally.

  1. PLACEHOLDER SCAN (static)  — dead hrefs, lorem ipsum, sample media IDs, TODOs shipped
     to production. File:line, so they are fixable.
  2. OUTBOUND VERIFICATION (live) — every URL the site presents as proof that something
     exists (schema.org sameAs, social links, "as seen in") fetched for real. A `sameAs`
     pointing at a 404 is a machine-readable false claim.
  3. SUBSTANTIATION (the lint) — every hardcoded number the site asserts must map to a
     declared `data_source`, or it is UNSUBSTANTIATED. "Every number on screen must be
     recomputable from a query the agent can run." This is the leg that turns the
     PERMITTED/DISCLOSE/FORBIDDEN matrix from prose into a check that can fail in CI.

THE RESOLUTION IS NEVER "DELETE IT".
Every finding carries a `fulfil` resolution: create the profile, build the destination, or
convert the dead end into a disclosed "coming soon — notify me" capture. Removal is only ever
the fallback, and only when the owner declines the channel. Deleting a dead link to raise a
liveness score is gaming the metric, and this script says so in the output.

Usage:
  promises.py --config app.habitar.json --root /path/to/repo --out .habitar/promises.json
  promises.py --config app.habitar.json --root . --strict     # exit 1 on any violation (CI)
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx

SCHEMA = 1
UA = "Mozilla/5.0 (compatible; habitar-promises/1.0)"

# Well-known sample/placeholder identifiers that regularly reach production.
KNOWN_PLACEHOLDERS = {
    "dQw4w9WgXcQ": "the Rick Astley video ID — a placeholder that shipped",
    "lorem ipsum": "filler copy",
    "example.com": "example domain",
    "test@example.com": "sample address",
    "John Doe": "sample name",
    "Jane Doe": "sample name",
    "+1 555": "sample phone",
    "0000-0000-0000-0000": "sample card",
    "your-domain": "unreplaced template token",
    "REPLACE_ME": "unreplaced template token",
    "CHANGEME": "unreplaced template token",
}

DEAD_HREF_RE = re.compile(r"""(?:href|to|url)\s*[:=]\s*["'](#|javascript:void\(0\);?)["']""")
JSONLD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                       re.S | re.I)

TEXT_EXT = {".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte", ".html", ".htm", ".astro",
            ".py", ".java", ".kt", ".rb", ".go", ".php", ".md", ".properties", ".yml",
            ".yaml", ".json", ".txt", ".env.example"}


#: Comment openers per family. A match after one of these on the line is documentation,
#: not a shipped promise.
_COMMENT_MARKERS = ("//", "/*", "*", "#", "<!--", "--")


def strip_comment(line: str) -> str:
    """
    Return the code part of a line, dropping any trailing comment.

    Why this exists: the scanner used to flag its own paper trail. When a placeholder is
    removed, the responsible thing is to leave a comment saying what it was and why it went
    ("all four carried dQw4w9WgXcQ into production") — and the next run would report that
    comment as the very violation it documents. A lint that punishes explaining yourself
    trains people to delete the explanation.

    Deliberately a heuristic, not a parser: it will also blank a `//` inside a string
    literal, which costs a false negative on `href="http://..."`-style matches. Missing a
    real one is recoverable; crying wolf on every documented fix is what gets a lint muted.
    """
    stripped = line.lstrip()
    for marker in _COMMENT_MARKERS:
        if stripped.startswith(marker):
            return ""
    cut = len(line)
    for marker in ("//", "/*", "<!--"):
        idx = line.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    return line[:cut]


def iter_files(root: str, patterns: list[str]):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {
            "node_modules", ".git", "dist", "build", "target", "__pycache__", ".venv",
            "venv", ".next", ".nuxt", "coverage", "vendor"}]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            if os.path.splitext(fn)[1].lower() not in TEXT_EXT:
                continue
            if patterns and not any(fnmatch.fnmatch(rel, p) for p in patterns):
                continue
            yield rel, full


def scan_placeholders(root: str, cfg: dict) -> list[dict]:
    out: list[dict] = []
    extra = cfg.get("promise_patterns", [])
    compiled = [(p, re.compile(p, re.I)) for p in extra]
    for rel, full in iter_files(root, cfg.get("scan_paths", [])):
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for n, raw in enumerate(lines, 1):
            if len(raw) > 4000:
                continue
            # Only the code half of the line counts. A placeholder named in a comment that
            # explains its own removal is a paper trail, not a shipped promise.
            line = strip_comment(raw)
            if not line.strip():
                continue
            for token, why in KNOWN_PLACEHOLDERS.items():
                if token.lower() in line.lower():
                    out.append({
                        "class": "unkept_promise", "kind": "placeholder",
                        "where": f"{rel}:{n}", "asserted": token, "why": why,
                        "fulfil": "Replace with the real asset. If it does not exist yet, use the "
                                  "codebase's existing 'coming soon' affordance -- check for one "
                                  "before building a new one.",
                        "severity": "high",
                    })
            for m in DEAD_HREF_RE.finditer(line):
                out.append({
                    "class": "unkept_promise", "kind": "dead_link",
                    "where": f"{rel}:{n}", "asserted": m.group(1),
                    "why": "a navigation affordance that goes nowhere",
                    "fulfil": "Build the destination, OR convert into a disclosed "
                              "'coming soon / notify me' capture. The second is also an "
                              "`invite` win. Do NOT delete the card to raise the score.",
                    "severity": "high",
                })
            for pat, rx in compiled:
                if rx.search(line) and not DEAD_HREF_RE.search(line):
                    out.append({
                        "class": "unkept_promise", "kind": "custom_pattern",
                        "where": f"{rel}:{n}", "asserted": pat,
                        "why": "matched a promise_pattern declared in habitar.json",
                        "fulfil": "Fulfil or convert to a disclosed capture.",
                        "severity": "medium",
                    })
    return out


#: Terminal states for a claim the site no longer makes. Kept in the config as a record of
#: what was there and why it went — a resolved claim must stop being reported, or the ledger
#: never converges and people start deleting history to make the number move.
RESOLVED = {"removed", "resolved", "retired"}


def is_resolved(claim: dict) -> bool:
    return str(claim.get("substantiated_by") or "").lower() in RESOLVED


def collect_outbound_claims(cfg: dict, live_html: str | None) -> list[dict]:
    """Claims of existence: schema.org sameAs plus anything declared in config."""
    claims: list[dict] = []
    for c in cfg.get("claims", []):
        if is_resolved(c):
            continue
        if c.get("type") == "outbound":
            claims.append({"id": c.get("id"), "url": c["asserted"], "where": c.get("where", "config"),
                           "surface": c.get("surface", "home")})
    if live_html:
        for block in JSONLD_RE.findall(live_html):
            try:
                data = json.loads(block.strip())
            except json.JSONDecodeError:
                continue
            for node in (data if isinstance(data, list) else [data]):
                if not isinstance(node, dict):
                    continue
                same = node.get("sameAs") or []
                for url in (same if isinstance(same, list) else [same]):
                    claims.append({"id": f"sameAs:{url}", "url": url,
                                   "where": "JSON-LD sameAs (served HTML)", "surface": "home"})
    seen, uniq = set(), []
    for c in claims:
        if c["url"] in seen:
            continue
        seen.add(c["url"])
        uniq.append(c)
    return uniq


def verify_outbound(claims: list[dict]) -> list[dict]:
    out: list[dict] = []
    with httpx.Client(timeout=25, follow_redirects=True) as client:
        for c in claims:
            try:
                r = client.get(c["url"], headers={"User-Agent": UA})
                code = r.status_code
            except Exception:
                code = 0
            rec = {**c, "http": code, "asserted": c["url"]}
            if code in (0, 404, 410):
                rec.update({
                    "class": "unsubstantiated_claim", "kind": "outbound_404",
                    "why": f"the site declares this profile/page exists; it returns {code or 'no response'}. "
                           f"In JSON-LD this is a machine-readable false claim.",
                    "fulfil": "CREATE the profile so the claim becomes true -- that is the default "
                              "resolution. Removing the claim is the fallback, only if the owner "
                              "has decided not to run that channel.",
                    "severity": "high",
                })
                out.append(rec)
            else:
                out.append({**rec, "class": "ok", "kind": "outbound_ok"})
    return out


def check_substantiation(cfg: dict, live_html: str | None) -> list[dict]:
    """Every asserted number must map to a data_source. No source -> UNSUBSTANTIATED."""
    known_sources = {s["id"] for s in cfg.get("data_sources", [])}
    min_n = cfg.get("thresholds", {}).get("aggregate_rating_min_n", 5)
    out: list[dict] = []

    for c in cfg.get("claims", []):
        if c.get("type") == "outbound" or is_resolved(c):
            continue
        src = c.get("substantiated_by")
        if src in (None, "", "null"):
            out.append({
                "class": "unsubstantiated_claim", "kind": c.get("type", "number"),
                "where": c.get("where", "config"), "asserted": c.get("asserted"),
                "surface": c.get("surface", "home"),
                "why": "asserted on screen with no data_source that can recompute it",
                "fulfil": "Either wire it to a real query, or stop asserting it. A number you "
                          "cannot recompute is a number you cannot defend.",
                "severity": "high",
            })
        elif src not in known_sources and src not in {"config", "http_200", "code"}:
            out.append({
                "class": "unsubstantiated_claim", "kind": "unknown_source",
                "where": c.get("where", "config"), "asserted": c.get("asserted"),
                "surface": c.get("surface", "home"),
                "why": f"substantiated_by='{src}' is not a declared data_source",
                "fulfil": "Declare the data_source in habitar.json or correct the reference.",
                "severity": "medium",
            })

    # aggregateRating in served HTML is the classic. Check it even if the config forgot it.
    if live_html:
        for block in JSONLD_RE.findall(live_html):
            try:
                data = json.loads(block.strip())
            except json.JSONDecodeError:
                continue
            for node in (data if isinstance(data, list) else [data]):
                if not isinstance(node, dict):
                    continue
                ar = node.get("aggregateRating")
                if not isinstance(ar, dict):
                    continue
                declared = next((c for c in cfg.get("claims", [])
                                 if c.get("type") == "aggregate_rating"), None)
                # A declared-and-resolved claim is not "backed" -- but if the live HTML still
                # emits the markup after we recorded it as removed, that is a REGRESSION and
                # must shout, not go quiet.
                backed = bool(declared and declared.get("substantiated_by")
                              and not is_resolved(declared))
                count = ar.get("ratingCount") or ar.get("reviewCount")
                out.append({
                    "class": "unsubstantiated_claim" if not backed else "ok",
                    "kind": "aggregate_rating",
                    "where": "JSON-LD aggregateRating (served HTML)",
                    "asserted": f"{ar.get('ratingValue')} from {count}",
                    "surface": "home",
                    "why": ("aggregateRating with no on-page reviews to back it. Google's "
                            "structured-data policy treats this as manipulation: the markup is "
                            "ignored or the site gets a manual action. FTC 16 CFR 465 treats "
                            "fabricated ratings as deceptive."
                            if not backed else
                            f"backed; suppress display below n={min_n} for quality"),
                    "fulfil": ("There is no way to make this true except by collecting real "
                               "ratings. Until then it must not be asserted. Nearest legitimate "
                               "substitute: `invite` -- 'be the first to review', plus a founding-"
                               "reviewer cohort of real invited users."),
                    "severity": "critical" if not backed else "info",
                })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="habitar — promise & substantiation lint")
    ap.add_argument("--config", required=True)
    ap.add_argument("--root", default=".", help="repo root for the static scan")
    ap.add_argument("--out")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any violation (CI)")
    ap.add_argument("--no-network", action="store_true")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)

    live_html = None
    if not args.no_network:
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                r = client.get(urljoin(cfg["app"]["base_url"], "/"), headers={"User-Agent": UA})
                live_html = r.text
        except Exception:
            live_html = None

    placeholders = scan_placeholders(args.root, cfg)
    outbound = [] if args.no_network else verify_outbound(collect_outbound_claims(cfg, live_html))
    substantiation = check_substantiation(cfg, live_html)

    everything = placeholders + outbound + substantiation
    violations = [v for v in everything if v.get("class") != "ok"]
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    violations.sort(key=lambda v: order.get(v.get("severity", "low"), 5))

    result = {
        "schema": SCHEMA,
        "app": cfg["app"].get("id"),
        "run": {"ts": datetime.now(timezone.utc).isoformat(), "root": os.path.abspath(args.root)},
        "violations": violations,
        "verified_ok": [v for v in everything if v.get("class") == "ok"],
        "totals": {
            "violations": len(violations),
            "critical": sum(1 for v in violations if v.get("severity") == "critical"),
            "high": sum(1 for v in violations if v.get("severity") == "high"),
            "unkept_promises": sum(1 for v in violations if v["class"] == "unkept_promise"),
            "unsubstantiated": sum(1 for v in violations if v["class"] == "unsubstantiated_claim"),
        },
        "note": "Resolutions are `fulfil`, never `delete`. Removing a dead link to raise a "
                "liveness score is gaming the metric -- see SKILL.md, Links & placeholders.",
    }

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")

    t = result["totals"]
    print(f"{t['violations']} violation(s): {t['critical']} critical, {t['high']} high  "
          f"({t['unkept_promises']} unkept promises, {t['unsubstantiated']} unsubstantiated)\n")
    for v in violations[:40]:
        print(f"  [{v.get('severity','?'):8s}] {v['kind']:<18} {v.get('where','')}")
        print(f"             asserted: {v.get('asserted')}")
        print(f"             fulfil:   {v.get('fulfil','')[:160]}")
    if len(violations) > 40:
        print(f"  … {len(violations)-40} more")
    if args.out:
        print(f"\n-> {args.out}")

    return 1 if (args.strict and violations) else 0


if __name__ == "__main__":
    sys.exit(main())
