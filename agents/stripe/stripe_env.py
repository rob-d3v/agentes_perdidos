#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
stripe_env.py — guard that a Stripe key is TEST mode before any validation runs.

The whole agent operates in homologation = Stripe TEST mode. This script is the gate: it
HARD-REFUSES any live secret/restricted key (`sk_live_`, `rk_live_`) so a validation run can
never touch real money, and confirms a test key actually authenticates.

Usage:
    uv run agents/stripe/stripe_env.py check --key sk_test_xxx
    uv run agents/stripe/stripe_env.py check --key rk_test_xxx --no-call   # offline prefix check only

Exit code 0 = safe test key. Non-zero = refuse / not test / auth failed.

A LIVE *restricted read-only* key is allowed ONLY by mirror_catalog.py for its one-way catalog
read; this guard intentionally refuses live keys so it is never the thing that runs a charge.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

# Force UTF-8 stdout (Windows consoles default to cp1252 and choke on → / emoji).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

API = "https://api.stripe.com/v1"


def classify(key: str) -> tuple[str, bool]:
    """Return (label, is_live). Recognizes secret, restricted, and publishable keys."""
    k = key.strip()
    if k.startswith("sk_live_"):
        return ("live secret key", True)
    if k.startswith("rk_live_"):
        return ("live restricted key", True)
    if k.startswith("pk_live_"):
        return ("live publishable key", True)
    if k.startswith("sk_test_"):
        return ("test secret key", False)
    if k.startswith("rk_test_"):
        return ("test restricted key", False)
    if k.startswith("pk_test_"):
        return ("test publishable key", False)
    return ("unrecognized key prefix", False)


def call_account(key: str) -> dict:
    """GET /v1/account to confirm the key authenticates and report the account id + livemode."""
    req = urllib.request.Request(f"{API}/account", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_check(args: argparse.Namespace) -> int:
    label, is_live = classify(args.key)
    masked = f"{args.key[:11]}…{args.key[-4:]}" if len(args.key) > 16 else "…"
    print(f"key:  {masked}  ({label})")

    if label == "unrecognized key prefix":
        print("REFUSE: not a recognizable Stripe key (expected sk_/rk_/pk_ + _test_/_live_).")
        return 2
    if is_live:
        print("REFUSE: this is a LIVE key. Homologation MUST use a TEST key (sk_test_/rk_test_).")
        print("        A live read-only restricted key is only ever passed to mirror_catalog.py.")
        return 3
    if args.key.startswith("pk_"):
        print("OK (prefix): test publishable key — safe for the frontend. Cannot call the API with it.")
        return 0
    if args.no_call:
        print("OK (prefix): test mode. Skipped live API call (--no-call).")
        return 0

    try:
        acct = call_account(args.key)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"AUTH FAILED: HTTP {e.code} — {body[:300]}")
        return 4
    except Exception as e:  # noqa: BLE001
        print(f"CALL FAILED: {e}")
        return 5

    livemode = acct.get("livemode", None)
    print(f"account: {acct.get('id', '?')}  livemode={livemode}  country={acct.get('country', '?')}")
    if livemode is True:
        # Defense in depth: a test key should never report livemode true, but never trust — refuse.
        print("REFUSE: API reports livemode=true. Aborting to protect production.")
        return 6
    print("OK: authenticated TEST key. Safe to use for homologation.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Guard that a Stripe key is TEST mode.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="verify a key is a test key (and authenticates)")
    c.add_argument("--key", required=True, help="Stripe key (sk_test_/rk_test_/pk_test_)")
    c.add_argument("--no-call", action="store_true", help="prefix check only; skip the API call")
    c.set_defaults(func=cmd_check)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
