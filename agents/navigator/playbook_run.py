#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
playbook_run.py — validate stripe_playbook.json and print an ordered, surface-specific checklist.

This does NOT drive a browser. It turns the declarative playbook into the exact step list the
LLM executes through the selected backend tier, with the right URL for the requested mode
(test/live) and a reminder of what to harvest + which env keys it maps to.

Usage:
    uv run agents/navigator/playbook_run.py --list
    uv run agents/navigator/playbook_run.py --surface create-products --mode test
    uv run agents/navigator/playbook_run.py --surface restricted-key --mode live --json
    uv run agents/navigator/playbook_run.py --playbook auth --list
    uv run agents/navigator/playbook_run.py --playbook auth --surface google-oauth-client --mode prod

Exit 0 = ok. Non-zero = unknown surface / malformed playbook.
"""
import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Named playbooks live next to this script; --playbook also accepts a path to any .json.
PLAYBOOKS = {
    "stripe": Path(__file__).with_name("stripe_playbook.json"),
    "auth": Path(__file__).with_name("auth_playbook.json"),
}


def resolve_playbook(name: str) -> Path:
    if name in PLAYBOOKS:
        return PLAYBOOKS[name]
    return Path(name).expanduser()


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"ERROR: {path} not found.")
        raise SystemExit(2)
    except json.JSONDecodeError as e:
        print(f"ERROR: {path} is invalid JSON — {e}")
        raise SystemExit(2)


def main() -> int:
    p = argparse.ArgumentParser(description="Print a navigator dashboard playbook checklist (Stripe or OAuth/CAPTCHA).")
    p.add_argument("--playbook", default="stripe",
                   help="which playbook: 'stripe' | 'auth' (or a path to a .json)")
    p.add_argument("--surface", help="surface key (see --list)")
    p.add_argument("--mode", choices=["test", "live", "dev", "prod"], default="test",
                   help="stripe uses test/live; auth uses dev/prod")
    p.add_argument("--list", action="store_true", help="list available surfaces")
    p.add_argument("--json", action="store_true", help="machine-readable")
    args = p.parse_args()

    data = load(resolve_playbook(args.playbook))
    surfaces = data.get("surfaces", {})

    if args.list or not args.surface:
        if args.json:
            print(json.dumps(sorted(surfaces), indent=2))
        else:
            print(f"navigator '{args.playbook}' playbook surfaces:")
            for k in sorted(surfaces):
                tier = surfaces[k].get("tier", "?")
                print(f"  {k:<22} (tier {tier})")
            print(f"\nRun: playbook_run.py --playbook {args.playbook} --surface <key> --mode <mode>")
        return 0

    if args.surface not in surfaces:
        print(f"ERROR: unknown surface '{args.surface}'. Known: {', '.join(sorted(surfaces))}")
        return 2

    s = surfaces[args.surface]
    url = (s.get("url", "") or "").replace("{mode}", args.mode)

    if args.json:
        out = dict(s)
        out["resolved_url"] = url
        out["mode"] = args.mode
        out["surface"] = args.surface
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    print(f"SURFACE: {args.surface}   MODE: {args.mode}   TIER: {s.get('tier', '?')}")
    print(f"URL:     {url}")
    if args.mode in ("live", "prod"):
        print("⚠ LIVE/PROD MODE — operator live-promotion gate must be cleared + recorded in project brain.")
    print("STEPS:")
    for i, step in enumerate(s.get("steps", []), 1):
        print(f"  {i}. {step}")
    if s.get("harvest"):
        print(f"HARVEST: {', '.join(s['harvest'])}")
    if s.get("env_keys_hint"):
        print(f"ENV KEYS: {', '.join(s['env_keys_hint'])}  → write via secrets_writer.py")
    if s.get("gotcha"):
        print(f"GOTCHA: {s['gotcha']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
