#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
backend_check.py — probe the navigator agent's browser backends and recommend a tier.

navigator drives web dashboards through a 4-tier backend ladder. This script does NOT drive a
browser; it only reports which tiers are reachable RIGHT NOW and which one to use for a given
surface, so the LLM doesn't waste a refused round-trip discovering a backend is down.

Tiers:
  1  Claude-in-Chrome MCP      fast DOM; refuses *.stripe.com (safety policy)
  2  chrome-devtools-mcp       Puppeteer; drives dashboard/checkout.stripe.com; not safety-policed
  3  hermes Camofox / CDP      stealth Firefox; anti-detection / bot-walled surfaces
  4  computer-use MCP          native desktop; last resort

Tier 1 and Tier 4 are MCP servers loaded into the LLM host — this script cannot see them, so it
reports them as "ask-host" (the LLM checks its own tool list). It CAN probe tiers 2 and 3 over
the network (a Chrome remote-debugging port, a Camofox /health endpoint, a CDP endpoint, the VPS).

Usage:
    uv run agents/navigator/backend_check.py                      # full report (all tiers)
    uv run agents/navigator/backend_check.py --surface stripe-dashboard   # + recommended tier
    uv run agents/navigator/backend_check.py --json              # machine-readable

Env (all optional; see .env.example):
    CHROME_REMOTE_DEBUG_URL   Tier 2 attach target, default http://127.0.0.1:9222
    CAMOFOX_URL               Tier 3 Camofox REST base, e.g. http://localhost:9377
    BROWSER_CDP_URL           Tier 3 raw-CDP endpoint (optional)
    HERMES_VPS_HOST           Tier 3 VPS fallback host, e.g. 203.0.113.10

Exit 0 always (it's a report). The recommended tier is printed and in JSON `recommended`.
"""
import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

# Force UTF-8 stdout (Windows consoles default to cp1252 and choke on → / emoji).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

DEFAULT_CHROME = "http://127.0.0.1:9222"

# Which tier each surface prefers, in escalation order. The LLM still owns the final call from
# the SKILL.md matrix; this is the default route grounded in "what is actually up".
SURFACE_PREFERENCE = {
    "generic":          [1, 2, 3, 4],   # any non-financial dashboard
    "stripe-dashboard": [2, 3, 4],      # products/keys/webhooks/portal/harvest — Tier 1 refuses
    "stripe-checkout":  [2, 3],         # hosted card entry — Tier 1 refuses, T4 can't read DOM well
    "create-account":   [2, 3, 4],
    "create-products":  [2, 3, 4],
    "restricted-key":   [2, 3, 4],
    "webhook":          [2, 3, 4],
    "customer-portal":  [2, 3, 4],
    "harvest":          [2, 3, 4],
    "deploy-panel":     [1, 2, 3, 4],   # Coolify/Dokploy — not safety-policed, Tier 1 fine
    "anti-detect":      [3, 2],         # bot-walled login → stealth first
}


def _http_ok(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "navigator-backend-check"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (200 <= resp.status < 400, f"HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        # A reachable server that answered (even 4xx) means the backend is UP.
        return (True, f"HTTP {e.code}")
    except Exception as e:  # noqa: BLE001
        return (False, str(e).splitlines()[0][:80] if str(e) else type(e).__name__)


def _tcp_ok(host: str, port: int, timeout: float = 2.5) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return (True, f"tcp {host}:{port} open")
    except Exception as e:  # noqa: BLE001
        return (False, f"tcp {host}:{port} {type(e).__name__}")


def probe_tier2() -> dict:
    """chrome-devtools-mcp attaches to a Chrome remote-debugging port. /json/version answers."""
    base = (os.environ.get("CHROME_REMOTE_DEBUG_URL") or DEFAULT_CHROME).rstrip("/")
    ok, detail = _http_ok(f"{base}/json/version")
    return {
        "tier": 2, "name": "chrome-devtools-mcp (Puppeteer)", "target": base,
        "up": ok, "detail": detail,
        "hint": None if ok else (
            'Start Chrome with: chrome.exe --remote-debugging-port=9222 '
            '--user-data-dir="%USERPROFILE%\\.chrome-navigator"  '
            "and register the chrome-devtools MCP server (see SKILL.md §5)."
        ),
    }


def probe_tier3() -> dict:
    """Tier 3 is reachable if Camofox /health, a CDP endpoint, OR the hermes VPS answers."""
    routes = []
    camofox = os.environ.get("CAMOFOX_URL", "").rstrip("/")
    if camofox:
        ok, detail = _http_ok(f"{camofox}/health")
        routes.append({"route": "camofox", "target": camofox, "up": ok, "detail": detail})
    cdp = os.environ.get("BROWSER_CDP_URL", "").rstrip("/")
    if cdp:
        ok, detail = _http_ok(f"{cdp}/json/version")
        routes.append({"route": "cdp", "target": cdp, "up": ok, "detail": detail})
    vps = os.environ.get("HERMES_VPS_HOST", "").strip()
    if vps:
        host = urlparse(vps).hostname or vps
        ok, detail = _tcp_ok(host, 22)  # SSH reachable == VPS up; hermes driven via its own CLI/MCP
        routes.append({"route": "hermes-vps", "target": f"{host}:22", "up": ok, "detail": detail})
    up = any(r["up"] for r in routes)
    return {
        "tier": 3, "name": "hermes Camofox / CDP / VPS", "routes": routes, "up": up,
        "hint": None if up else (
            "Set CAMOFOX_URL (e.g. http://localhost:9377) and start Camofox, or set "
            "HERMES_VPS_HOST to reach hermes on the VPS. Tier 3 is optional — only needed when "
            "Tier 2 is detected/challenged."
        ),
    }


def build_report() -> dict:
    t2 = probe_tier2()
    t3 = probe_tier3()
    # Tiers 1 & 4 are MCP servers in the LLM host; this process can't see them.
    t1 = {"tier": 1, "name": "Claude-in-Chrome MCP", "up": None,
          "detail": "ask-host: check your tool list for mcp__Claude_in_Chrome__*",
          "note": "Refuses *.stripe.com by safety policy — never route Stripe surfaces here."}
    t4 = {"tier": 4, "name": "computer-use MCP", "up": None,
          "detail": "ask-host: check your tool list for mcp__computer-use__*",
          "note": "Last resort — native desktop, slowest."}
    return {"tiers": {1: t1, 2: t2, 3: t3, 4: t4}}


def recommend(report: dict, surface: str) -> dict:
    pref = SURFACE_PREFERENCE.get(surface)
    if pref is None:
        return {"surface": surface, "error": f"unknown surface; known: {sorted(SURFACE_PREFERENCE)}"}
    tiers = report["tiers"]
    down_preferred = []  # probeable tiers earlier in preference that we confirmed are DOWN
    for t in pref:
        up = tiers[t]["up"]
        if up is True:
            return {"surface": surface, "recommended": t, "reason": "probed up",
                    "preference": pref}
        if up is False:
            down_preferred.append(t)
            continue  # don't fall past a downed higher-priority tier without flagging it
        if up is None:  # MCP tier — can't probe from here; the host owns the final check
            if down_preferred:
                # A higher-priority probeable tier is down — recommend starting IT, not the fallback.
                start = down_preferred[0]
                return {"surface": surface, "recommended": start,
                        "reason": f"Tier {start} is the right backend but DOWN — start it "
                                  f"(see Tier {start} hint); fallback ask-host Tier {t}",
                        "fallback": t, "preference": pref}
            return {"surface": surface, "recommended": t, "reason": "ask-host (MCP tier)",
                    "preference": pref}
    return {"surface": surface, "recommended": down_preferred[0] if down_preferred else None,
            "reason": "preferred backend(s) DOWN for this surface — bring one up (see hints)",
            "preference": pref}


def main() -> int:
    p = argparse.ArgumentParser(description="Probe navigator browser backends, recommend a tier.")
    p.add_argument("--surface", help=f"one of: {', '.join(sorted(SURFACE_PREFERENCE))}")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args()

    report = build_report()
    rec = recommend(report, args.surface) if args.surface else None

    if args.json:
        print(json.dumps({"report": report, "recommendation": rec}, indent=2, default=str))
        return 0

    print("navigator — browser backend report")
    print("=" * 42)
    for t in (1, 2, 3, 4):
        info = report["tiers"][t]
        up = info["up"]
        mark = "?" if up is None else ("UP" if up else "DOWN")
        print(f"  Tier {t} [{mark:>4}]  {info['name']}")
        if info.get("detail"):
            print(f"           {info['detail']}")
        if info.get("target"):
            print(f"           target: {info['target']}")
        for r in info.get("routes", []):
            rmark = "UP" if r["up"] else "DOWN"
            print(f"           - {r['route']:>10} [{rmark}] {r['target']}  ({r['detail']})")
        if info.get("note"):
            print(f"           note: {info['note']}")
        if info.get("hint"):
            print(f"           hint: {info['hint']}")
    if rec:
        print("-" * 42)
        if rec.get("error"):
            print(f"  surface '{args.surface}': {rec['error']}")
        else:
            print(f"  surface '{rec['surface']}': use Tier {rec['recommended']}  ({rec['reason']})")
            print(f"  escalation order: {rec['preference']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
