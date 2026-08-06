#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27", "beautifulsoup4>=4.12", "lxml>=5.0"]
# ///
"""
liveness.py — how inhabited does this product LOOK to an anonymous visitor?

Framework-blind by design: this script knows nothing about React, Next, Django or Spring.
Everything stack-specific lives in habitar.json, which the agent writes during `audit`.
The script only does HTTP, counting, and regex.

Three jobs:
  1. Fetch every declared surface TWICE — raw (no JS, what a crawler sees) and rendered
     (what a human sees, via --rendered-cmd). Report the gap instead of guessing.
  2. Score each surface on five dimensions, then apply an honesty multiplier H, so a
     surface that looks inhabited BECAUSE IT LIES always scores below an honestly empty one.
  3. Leak-scan every JSON response for personal data and secrets. This is the highest-value
     accident in the agent: crawling public endpoints as an anonymous visitor is exactly how
     you find an API serializing whole user records to the open internet.

Usage:
  liveness.py --init https://example.com --out example.habitar.json
  liveness.py --config app.habitar.json --out .habitar/liveness.json
  liveness.py --config app.habitar.json --baseline .habitar/baseline.json
  liveness.py --config app.habitar.json --promises .habitar/promises.json

See SKILL.md for the scoring model and the PERMITTED/DISCLOSE/FORBIDDEN matrix.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

SCHEMA = 1
CRAWLER_UA = "Mozilla/5.0 (compatible; habitar-audit/1.0; +anonymous-visitor)"

# --------------------------------------------------------------------------------------
# leak scan
# --------------------------------------------------------------------------------------

# Key names that should essentially never appear in an unauthenticated response.
LEAK_KEYS: list[tuple[str, str, str]] = [
    (r"^password|passwd|pwd$", "critical", "credential"),
    (r"secret|api_?key|apikey|access_?token|refresh_?token|^token$|bearer", "critical", "secret"),
    (r"^cpf$|^cnpj$|^ssn$|nationalid|tax_?id", "critical", "national-id"),
    (r"^email$|emailaddress|e_?mail$", "high", "pii-email"),
    (r"^phone|telefone|mobile_?number|whatsapp", "high", "pii-phone"),
    (r"address|endereco|cep$|zip_?code|postal_?code", "medium", "pii-address"),
    (r"birth|nascimento|dob$", "high", "pii-dob"),
    (r"stripe.*id|customer_?id|payment_?method|payout", "medium", "payment-identifier"),
    (r"google_?id|facebook_?id|oauth_?id|provider_?id", "medium", "oauth-identifier"),
    (r"ip_?address|user_?agent|session_?id", "medium", "session-telemetry"),
    (r"reason$|_reason|internal_?note|moderat", "low", "moderation-internal"),
    (r"^role$|is_?admin|permissions", "low", "authorization-internal"),
]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
SK_RE = re.compile(r"\b(sk_live|sk_test|rk_live|rk_test|AKIA|ghp_|xox[baprs]-)[A-Za-z0-9_-]{8,}")


def _redact(value: Any) -> str:
    """Never let a real value reach an artifact. Shape only."""
    s = str(value)
    if "@" in s and EMAIL_RE.search(s):
        local, _, domain = s.partition("@")
        return f"{local[:1]}***@{domain}"
    if len(s) <= 4:
        return "***"
    return f"{s[:2]}***{s[-2:]} (len {len(s)})"


def leak_scan(payload: Any, source: str) -> list[dict]:
    """Walk a decoded JSON payload; flag keys and values that should not be public."""
    found: dict[tuple[str, str], dict] = {}

    def note(path: str, severity: str, kind: str, value: Any) -> None:
        key = (path, kind)
        if key in found:
            found[key]["n"] += 1
            return
        found[key] = {
            "source": source,
            "key_path": path,
            "severity": severity,
            "kind": kind,
            "sample_redacted": _redact(value),
            "n": 1,
        }

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                sub = f"{path}.{k}" if path else k
                if v not in (None, "", [], {}):
                    lk = k.lower()
                    for pattern, severity, kind in LEAK_KEYS:
                        if re.search(pattern, lk):
                            note(_generalize(sub), severity, kind, v)
                            break
                walk(v, sub)
        elif isinstance(node, list):
            for item in node[:200]:
                walk(item, f"{path}[]")
        elif isinstance(node, str):
            if EMAIL_RE.fullmatch(node.strip()):
                note(_generalize(path), "high", "pii-email", node)
            elif JWT_RE.search(node):
                note(_generalize(path), "critical", "jwt", node)
            elif SK_RE.search(node):
                note(_generalize(path), "critical", "api-key", node)

    walk(payload, "")
    return sorted(found.values(), key=lambda f: ("critical high medium low".split().index(f["severity"]), f["key_path"]))


def _generalize(path: str) -> str:
    return re.sub(r"\[\]", "[]", path)


# --------------------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------------------


def http_get(client: httpx.Client, url: str, ua: str = CRAWLER_UA) -> tuple[int, str, str]:
    try:
        r = client.get(url, headers={"User-Agent": ua}, follow_redirects=True)
        return r.status_code, r.text, r.headers.get("content-type", "")
    except Exception as exc:  # network is the environment, not a bug
        return 0, f"__ERROR__ {exc}", ""


def render(cmd_template: str | None, url: str) -> str | None:
    """Plug any headless renderer: --rendered-cmd 'my-renderer {url}'. Must print HTML."""
    if not cmd_template:
        return None
    cmd = cmd_template.replace("{url}", url)
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=90)
        return out.stdout if out.returncode == 0 and out.stdout.strip() else None
    except Exception:
        return None


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


# --------------------------------------------------------------------------------------
# data sources: a deliberately small path language, not JSONPath
# --------------------------------------------------------------------------------------


def dig(obj: Any, dotted: str) -> Any:
    """'a.b.c' -> obj['a']['b']['c']. Empty string returns obj. Missing -> None."""
    if not dotted:
        return obj
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)] if int(part) < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


def load_sources(client: httpx.Client, cfg: dict, base: str) -> tuple[dict[str, list], list[dict]]:
    sources: dict[str, list] = {}
    leaks: list[dict] = []
    for src in cfg.get("data_sources", []):
        url = urljoin(base, src["url"])
        status, body, ctype = http_get(client, url)
        if status != 200:
            sources[src["id"]] = []
            continue
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            sources[src["id"]] = []
            continue
        leaks.extend(leak_scan(payload, src["id"]))
        items = dig(payload, src.get("items_path", ""))
        sources[src["id"]] = items if isinstance(items, list) else []
    return sources, leaks


def select(items: list, spec: dict) -> list:
    """Model what a section renders, declaratively — mirrors the frontend's own query."""
    out = list(items)
    for key, want in (spec.get("filter") or {}).items():
        if want == "__truthy__":
            out = [i for i in out if dig(i, key)]
        elif want == "__falsy__":
            out = [i for i in out if not dig(i, key)]
        else:
            out = [i for i in out if dig(i, key) == want]
    sort_by = spec.get("sort_by")
    if sort_by:
        out.sort(key=lambda i: (dig(i, sort_by) is None, _sortable(dig(i, sort_by))),
                 reverse=spec.get("order", "desc") == "desc")
    limit = spec.get("limit")
    return out[:limit] if limit else out


def _sortable(v: Any) -> Any:
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return v
    return str(v)


def freshest_days(items: list, field: str | None) -> float | None:
    if not field or not items:
        return None
    best = None
    for i in items:
        raw = dig(i, field)
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        best = age if best is None else min(best, age)
    return best


# --------------------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------------------


def score_population(n: int, target: int) -> float:
    if target <= 0:
        return 30.0 if n else 0.0
    return 30.0 * min(1.0, math.log1p(n) / math.log1p(target))


def score_variety(unique: int, rendered: int, overlap: float) -> float:
    if rendered <= 0:
        return 0.0
    return 20.0 * (unique / rendered) * (1.0 - overlap)


def score_activity(days: float | None) -> float:
    if days is None:
        return 0.0
    return 20.0 * math.exp(-max(days, 0.0) / 30.0)


def score_continuity(dead_links: int, placeholders: int, outbound_404: int) -> float:
    return max(0.0, 15.0 - 3 * dead_links - 3 * placeholders - 4 * outbound_404)


def score_invitation(empty_state: bool, cta: bool, capture: bool) -> float:
    return 5.0 * bool(empty_state) + 5.0 * bool(cta) + 5.0 * bool(capture)


def honesty(violations: list[dict]) -> float:
    if any(v.get("class") == "fabricated_person" for v in violations):
        return 0.0
    if violations:
        return 0.5
    return 1.0


# --------------------------------------------------------------------------------------
# surface analysis
# --------------------------------------------------------------------------------------

DEAD_HREF_RE = re.compile(r"""href\s*=\s*["'](#|javascript:void\(0\);?|)["']""", re.I)


def analyse_html(html: str, cfg: dict) -> dict:
    soup = BeautifulSoup(html, "lxml")
    patterns = cfg.get("promise_patterns", [])
    dead = len(DEAD_HREF_RE.findall(html))
    placeholders = sum(len(re.findall(p, html, re.I)) for p in patterns)
    outbound = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and urlparse(href).netloc:
            outbound.append(href)
    return {
        "chars": len(visible_text(html)),
        "dead_links": dead,
        "placeholders": placeholders,
        "outbound": sorted(set(outbound)),
    }


def count_dom_items(html: str, selector: str | None, dedupe_key: str | None) -> tuple[int, int, set]:
    if not selector:
        return 0, 0, set()
    soup = BeautifulSoup(html, "lxml")
    nodes = soup.select(selector)
    keys = set()
    for n in nodes:
        k = n.get(dedupe_key) if dedupe_key else None
        keys.add(k if k else str(n)[:120])
    return len(nodes), len(keys), keys


def analyse_surface(
    surface: dict,
    cfg: dict,
    client: httpx.Client,
    base: str,
    sources: dict[str, list],
    rendered_cmd: str | None,
    claims_by_surface: dict[str, list],
) -> dict:
    url = urljoin(base, surface["url"])
    status, raw_html, _ = http_get(client, url)
    rendered_html = render(rendered_cmd, url)
    have_renderer = rendered_html is not None
    html_for_dom = rendered_html or raw_html

    raw_stats = analyse_html(raw_html, cfg) if status == 200 else {"chars": 0, "dead_links": 0, "placeholders": 0, "outbound": []}
    dom_stats = analyse_html(html_for_dom, cfg) if status == 200 else raw_stats

    # Model each section's item set from its declared query (no browser needed).
    section_sets: dict[str, list] = {}
    section_reports: list[dict] = []
    for sec in surface.get("sections", []):
        items = sources.get(sec.get("source", ""), [])
        modelled = select(items, sec.get("select", {}))
        section_sets[sec["id"]] = modelled

    total_items = 0
    total_unique: set = set()
    pair_overlaps: list[float] = []
    for sec in surface.get("sections", []):
        sid = sec["id"]
        expects = sec.get("expects", {})
        id_key = sec.get("id_key", "id")
        modelled = section_sets[sid]
        mkeys = {str(dig(i, id_key)) for i in modelled}

        overlaps = {}
        for other in expects.get("distinct_from", []):
            okeys = {str(dig(i, id_key)) for i in section_sets.get(other, [])}
            if mkeys and okeys:
                ov = len(mkeys & okeys) / len(mkeys)
                overlaps[other] = round(ov, 3)
                # Mean, not max: one duplicated section should not zero a whole surface's
                # variety. The per-section finding below is what names the duplicate.
                pair_overlaps.append(ov)

        dom_n, dom_unique, _ = count_dom_items(html_for_dom, sec.get("item_selector"), expects.get("dedupe_key"))
        total_items += len(modelled)
        total_unique |= mkeys

        report = {
            "id": sid,
            "modelled_items": len(modelled),
            "modelled_unique": len(mkeys),
            "target_items": expects.get("target_items"),
            "min_items": expects.get("min_items"),
            "overlap_with": overlaps,
            "dom_items": dom_n if sec.get("item_selector") else None,
            "dom_unique": dom_unique if sec.get("item_selector") else None,
            "findings": [],
        }
        for other, ov in overlaps.items():
            if ov >= 0.9:
                report["findings"].append(
                    f"{sid} is {int(ov * 100)}% identical to {other} -- declared distinct_from, "
                    f"but renders the same items"
                )
            elif ov >= 0.5:
                report["findings"].append(f"{sid} overlaps {other} by {int(ov*100)}%")
        if expects.get("min_items") is not None and len(modelled) < expects["min_items"]:
            report["findings"].append(f"{sid} has {len(modelled)} items, below min_items={expects['min_items']}")
        section_reports.append(report)

    # Freshness across every source this surface draws from.
    fresh_field = surface.get("freshness_field") or cfg.get("freshness_field")
    all_items = [i for sec in surface.get("sections", []) for i in section_sets.get(sec["id"], [])]
    days = freshest_days(all_items, fresh_field)

    inv = surface.get("invitation", {})
    empty_state = _present(html_for_dom, inv.get("empty_state_selector"), inv.get("empty_state_text"))
    cta = _present(html_for_dom, inv.get("cta_selector"), inv.get("cta_text"))
    capture = _present(html_for_dom, inv.get("capture_selector"), inv.get("capture_text"))

    # Outbound claims that 404 — a promise the site makes and does not keep.
    outbound_404 = 0
    outbound_report = []
    for href in dom_stats["outbound"][: cfg.get("thresholds", {}).get("max_outbound_checks", 40)]:
        if not _is_claim(href, cfg):
            continue
        code, _, _ = http_get(client, href)
        outbound_report.append({"url": href, "http": code})
        if code in (0, 404, 410):
            outbound_404 += 1

    target = sum((s.get("expects", {}).get("target_items") or 0) for s in surface.get("sections", [])) or \
        cfg.get("thresholds", {}).get("default_target_items", 8)

    violations = claims_by_surface.get(surface["id"], [])
    H = honesty(violations)

    overlap = sum(pair_overlaps) / len(pair_overlaps) if pair_overlaps else 0.0
    C = score_continuity(dom_stats["dead_links"], dom_stats["placeholders"], outbound_404)
    I = score_invitation(empty_state, cta, capture)

    # N/A is not failure. A static page (no data-backed sections) is not *supposed* to have a
    # population or a freshness date — scoring it 0 on those would say a FAQ is a ghost town.
    # Score only the applicable dimensions and renormalize to 0-100. Same lesson as
    # ai-visibility's content-type adapter.
    is_static = not surface.get("sections")
    if is_static:
        P = V = A = None
        applicable = 30.0
        total = ((C + I) / applicable * 100.0) * H
        at_zero = total
        at_target = ((C + 15.0) / applicable * 100.0) * H
    else:
        P = score_population(len(total_unique), target)
        V = score_variety(len(total_unique), max(total_items, 1), overlap)
        A = score_activity(days)
        total = (P + V + A + C + I) * H
        # Modelled columns — NOT measured. Said out loud so nobody empties a prod DB for N=0.
        at_zero = (score_population(0, target) + 0.0 + 0.0 + C + I) * H
        at_target = (score_population(target, target) + score_variety(target, target, 0.0)
                     + score_activity(0.0) + C + I) * H

    return {
        "id": surface["id"],
        "url": url,
        "http": status,
        "weight": surface.get("weight", 1),
        "raw": {"chars": raw_stats["chars"], "renderer_used": False},
        "rendered": {
            "chars": dom_stats["chars"],
            "renderer_used": have_renderer,
            "dead_links": dom_stats["dead_links"],
            "placeholders": dom_stats["placeholders"],
            "outbound_404": outbound_404,
            "empty_state": empty_state,
            "cta": cta,
            "capture": capture,
            "freshest_item_days": round(days, 1) if days is not None else None,
        },
        "sections": section_reports,
        "outbound_checked": outbound_report,
        "honesty_violations": violations,
        "kind": "static" if is_static else "data-backed",
        "cross_section_overlap": round(overlap, 3),
        "scores": {
            "P": round(P, 1) if P is not None else None,
            "V": round(V, 1) if V is not None else None,
            "A": round(A, 1) if A is not None else None,
            "C": round(C, 1), "I": round(I, 1), "H": H, "total": round(total, 1),
        },
        "modelled": {"at_n0": round(at_zero, 1), "at_target": round(at_target, 1),
                     "note": "at_n0 and at_target are MODELLED by substituting n, not measured"},
    }


def _present(html: str, selector: str | None, text: str | None) -> bool:
    if selector:
        try:
            if BeautifulSoup(html, "lxml").select_one(selector):
                return True
        except Exception:
            pass
    if text:
        return text.lower() in html.lower()
    return False


def _is_claim(href: str, cfg: dict) -> bool:
    """Only verify links the site presents as proof of existence — not every outbound link."""
    hosts = cfg.get("claim_hosts")
    if hosts is None:
        return True
    return any(h in href for h in hosts)


# --------------------------------------------------------------------------------------
# --init
# --------------------------------------------------------------------------------------


def init_config(base_url: str) -> dict:
    surfaces: list[dict] = [{
        "id": "home", "url": "/", "weight": 3,
        "sections": [], "invitation": {"cta_text": "", "capture_text": ""},
    }]
    with httpx.Client(timeout=30) as client:
        code, body, _ = http_get(client, urljoin(base_url, "/sitemap.xml"))
        if code == 200:
            for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)[:40]:
                path = urlparse(loc).path or "/"
                if path == "/":
                    continue
                surfaces.append({"id": path.strip("/").replace("/", "-") or "root",
                                 "url": path, "weight": 1, "sections": []})
    return {
        "schema": SCHEMA,
        "app": {"id": urlparse(base_url).netloc.split(".")[0], "name": "", "base_url": base_url},
        "identity": {"first_party_accounts": [], "staff_accounts": [], "demo_accounts": []},
        "freshness_field": "createdAt",
        "data_sources": [{"id": "items", "url": "/api/REPLACE-ME", "items_path": "", "id_key": "id"}],
        "surfaces": surfaces,
        "claims": [],
        "promise_patterns": [r"href=[\"']#[\"']", r"lorem ipsum", r"TODO", r"example\.com",
                             r"placeholder", r"coming soon"],
        "scan_paths": ["src/**/*", "index.html"],
        "thresholds": {"aggregate_rating_min_n": 5, "default_target_items": 8,
                       "sessions_per_week_floor": 50, "max_outbound_checks": 40},
        "_note": "DRAFT from sitemap. --init cannot know your item selectors or which sections "
                 "must be distinct from each other. Edit before trusting any score.",
    }


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="habitar — liveness ledger")
    ap.add_argument("--config")
    ap.add_argument("--init", metavar="BASE_URL")
    ap.add_argument("--out")
    ap.add_argument("--baseline", help="previous liveness.json to diff against")
    ap.add_argument("--promises", help="promises.json from promises.py (feeds the H multiplier)")
    ap.add_argument("--rendered-cmd", help="shell cmd printing rendered HTML; {url} is substituted")
    ap.add_argument("--sessions-per-week", type=float, default=None)
    args = ap.parse_args()

    if args.init:
        cfg = init_config(args.init)
        text = json.dumps(cfg, indent=2, ensure_ascii=False)
        if args.out:
            os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text + "\n")
            print(f"draft config -> {args.out}  (EDIT IT — selectors and distinct_from are yours to declare)")
        else:
            print(text)
        return 0

    if not args.config:
        ap.error("--config or --init is required")

    with open(args.config, encoding="utf-8") as fh:
        cfg = json.load(fh)
    base = cfg["app"]["base_url"]

    claims_by_surface: dict[str, list] = {}
    unattributed: list[dict] = []
    promise_data = None
    if args.promises and os.path.exists(args.promises):
        with open(args.promises, encoding="utf-8") as fh:
            promise_data = json.load(fh)
        # Only findings that name a surface may move that surface's honesty multiplier.
        # Static code-scan hits (a stray "coming soon" in some other page) have no surface,
        # and defaulting them to "home" halved the homepage's score for a string it does not
        # render. They still appear in promises.json; they just do not libel a page.
        for v in promise_data.get("violations", []):
            surface = v.get("surface")
            if surface:
                claims_by_surface.setdefault(surface, []).append(v)
            else:
                unattributed.append(v)
    else:
        for c in cfg.get("claims", []):
            if not c.get("substantiated_by"):
                claims_by_surface.setdefault(c.get("surface", "home"), []).append(
                    {"id": c.get("id"), "class": "unsubstantiated_claim", "where": c.get("where")}
                )

    with httpx.Client(timeout=45) as client:
        sources, source_leaks = load_sources(client, cfg, base)
        surfaces = [
            analyse_surface(s, cfg, client, base, sources, args.rendered_cmd, claims_by_surface)
            for s in cfg.get("surfaces", [])
        ]

    wsum = sum(s["weight"] for s in surfaces) or 1
    site = sum(s["scores"]["total"] * s["weight"] for s in surfaces) / wsum
    site_n0 = sum(s["modelled"]["at_n0"] * s["weight"] for s in surfaces) / wsum
    site_target = sum(s["modelled"]["at_target"] * s["weight"] for s in surfaces) / wsum

    floor = cfg.get("thresholds", {}).get("sessions_per_week_floor", 50)
    spw = args.sessions_per_week
    if spw is None:
        traffic_verdict = ("UNMEASURED -- install analytics before ranking any storefront work; "
                           "a baseline captured after a change is worthless")
    elif spw < floor:
        traffic_verdict = (f"{spw:g}/week is below the floor of {floor} -- distribution outranks "
                           f"storefront work. Fixing conversion on traffic this thin yields ~0 customers")
    else:
        traffic_verdict = f"{spw:g}/week is above the floor of {floor} -- storefront work will pay"

    result = {
        "schema": SCHEMA,
        "app": cfg["app"].get("id"),
        "run": {"ts": datetime.now(timezone.utc).isoformat(),
                "visitor": "anonymous",
                "renderer": bool(args.rendered_cmd)},
        "traffic": {"sessions_per_week": spw, "floor": floor, "verdict": traffic_verdict},
        "leaks": source_leaks,
        "surfaces": surfaces,
        "totals": {
            "liveness_real": round(site, 1),
            "liveness_at_n0_modelled": round(site_n0, 1),
            "liveness_at_target_modelled": round(site_target, 1),
            "honesty_violations": sum(len(s["honesty_violations"]) for s in surfaces),
            "unattributed_violations": len(unattributed),
            "leaks_critical": sum(1 for l in source_leaks if l["severity"] == "critical"),
            "leaks_high": sum(1 for l in source_leaks if l["severity"] == "high"),
        },
        "delta_vs_baseline": None,
    }

    if args.baseline and os.path.exists(args.baseline):
        with open(args.baseline, encoding="utf-8") as fh:
            old = json.load(fh)
        result["delta_vs_baseline"] = {
            "since": old.get("run", {}).get("ts"),
            "liveness_real": round(site - old.get("totals", {}).get("liveness_real", 0), 1),
            "honesty_violations": result["totals"]["honesty_violations"]
            - old.get("totals", {}).get("honesty_violations", 0),
        }

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")

    # Human summary. sessions/week FIRST, always -- that ordering is the whole point.
    print(f"sessions/week: {traffic_verdict}")
    print(f"Liveness {result['totals']['liveness_real']:.0f}/100 "
          f"(n=0 floor {result['totals']['liveness_at_n0_modelled']:.0f} | "
          f"target {result['totals']['liveness_at_target_modelled']:.0f} -- both MODELLED, "
          f"not measured) -- {result['totals']['honesty_violations']} honesty violation(s)")
    if source_leaks:
        print(f"\n!! LEAK SCAN: {len(source_leaks)} finding(s) on UNAUTHENTICATED endpoints "
              f"({result['totals']['leaks_critical']} critical, {result['totals']['leaks_high']} high)")
        for l in source_leaks[:15]:
            print(f"   [{l['severity']:8s}] {l['source']}:{l['key_path']}  {l['kind']}  "
                  f"x{l['n']}  {l['sample_redacted']}")
    print()

    def _f(v):
        return f"{v:5.1f}" if v is not None else "  n/a"

    for s in surfaces:
        sc = s["scores"]
        print(f"  {s['id']:<18} {sc['total']:5.1f}  P{_f(sc['P'])} V{_f(sc['V'])} "
              f"A{_f(sc['A'])} C{_f(sc['C'])} I{_f(sc['I'])}  H={sc['H']}  ({s['kind']})")
        for sec in s["sections"]:
            for f in sec["findings"]:
                print(f"        - {f}")
    if args.out:
        print(f"\n-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
