#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["stripe>=11"]
# ///
"""
validate.py — Lane A (headless / API) Stripe validation harness, config-driven.

Reads a small JSON config describing an app's payment flows and runs a matrix of checks against
BOTH Stripe (test mode) and the app's own API, emitting a results JSON that report.py turns into
the per-app PDF. The point is to assert the *app* reacts correctly — not just that Stripe works.

It runs in TEST mode only (it refuses a live --test-key). Lane B (real browser checkout with the
test-card matrix) is driven separately via Claude Preview / Claude-in-Chrome and its screenshots
are merged into the report.

Check types (each → {name, status: pass|fail|pending, detail}):
  http                 call an app endpoint; assert status code and/or a JSON field (with polling).
  stripe_paymentintent create+confirm a PaymentIntent with a test payment-method token; assert the
                       resulting status (succeeded / requires_action / requires_payment_method).
  webhook_signature    POST junk to the app's webhook URL with a bad Stripe-Signature; assert 400.
  stripe_idempotency   create an object twice with one idempotency key; assert the same id back.

Usage:
  uv run agents/stripe/validate.py --config app.stripe.json --test-key sk_test_xxx --out results.json

See example.stripe.json for the schema.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

import stripe

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Stripe test payment-method tokens → expected terminal PaymentIntent status.
PM_TOKENS = {
    "pm_card_visa": "succeeded",
    "pm_card_mastercard": "succeeded",
    "pm_card_threeDSecure2Required": "requires_action",
    "pm_card_chargeDeclined": "requires_payment_method",
    "pm_card_chargeDeclinedInsufficientFunds": "requires_payment_method",
    "pm_card_chargeDeclinedExpiredCard": "requires_payment_method",
}


def _json_path(obj, path: str):
    """Tiny dotted-path getter: 'data.0.status' → obj['data'][0]['status']."""
    cur = obj
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    return cur


def _http(method: str, url: str, headers: dict | None, body, timeout: int = 30):
    data = None
    h = dict(headers or {})
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
        else:
            data = str(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=h, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def check_http(c: dict) -> dict:
    """Poll an app endpoint until expectations hold or attempts run out."""
    name = c["name"]
    attempts = c.get("poll", {}).get("attempts", 1)
    interval = c.get("poll", {}).get("interval_seconds", 2)
    expect_status = c.get("expect_status")
    expect_field = c.get("expect_field")  # {"path": "...", "equals": ...} or {"path","in":[...]}
    last = ""
    for i in range(attempts):
        status, raw = _http(c.get("method", "GET"), c["url"], c.get("headers"), c.get("body"))
        last = f"HTTP {status}"
        ok = True
        if expect_status is not None and status != expect_status:
            ok = False
        if ok and expect_field:
            try:
                val = _json_path(json.loads(raw), expect_field["path"])
                if "equals" in expect_field and val != expect_field["equals"]:
                    ok = False
                if "in" in expect_field and val not in expect_field["in"]:
                    ok = False
                last = f"HTTP {status}, {expect_field['path']}={val!r}"
            except Exception as e:  # noqa: BLE001
                ok = False
                last = f"HTTP {status}, field error: {e}"
        if ok:
            return {"name": name, "status": "pass", "detail": last}
        if i < attempts - 1:
            time.sleep(interval)
    return {"name": name, "status": "fail", "detail": f"expectations not met (last: {last})"}


def check_paymentintent(c: dict, client: "stripe.StripeClient") -> dict:
    name = c["name"]
    token = c["payment_method"]
    expected = c.get("expect_status") or PM_TOKENS.get(token, "succeeded")
    params = {
        "amount": c.get("amount", 1000),
        "currency": c.get("currency", "brl"),
        "payment_method": token,
        "confirm": True,
        "automatic_payment_methods": {"enabled": True, "allow_redirects": "never"},
        "metadata": {"validate_run": name},
    }
    try:
        pi = client.v1.payment_intents.create(params)
    except stripe.CardError as e:
        # Declines surface as CardError; the failed PaymentIntent rides on e.error.payment_intent
        # (a PaymentIntent object — use attribute access, not dict .get).
        epi = getattr(e.error, "payment_intent", None)
        actual = getattr(epi, "status", "requires_payment_method") if epi is not None else "requires_payment_method"
        ok = actual == expected
        return {"name": name, "status": "pass" if ok else "fail",
                "detail": f"declined as expected → {actual}" if ok else f"got {actual}, wanted {expected}"}
    except Exception as e:  # noqa: BLE001
        return {"name": name, "status": "fail", "detail": f"create error: {e}"}
    actual = pi["status"]
    ok = actual == expected
    return {"name": name, "status": "pass" if ok else "fail",
            "detail": f"PaymentIntent {pi['id']} status={actual} (wanted {expected})"}


def check_webhook_signature(c: dict) -> dict:
    name = c["name"]
    body = json.dumps({"id": "evt_test", "object": "event", "type": "ping"})
    headers = {"Content-Type": "application/json", "Stripe-Signature": "t=0,v1=deadbeef"}
    status, _ = _http("POST", c["url"], headers, body)
    ok = status in (c.get("expect_status_any") or [400, 401, 403])
    return {"name": name, "status": "pass" if ok else "fail",
            "detail": f"bad-signature POST → HTTP {status} (want signature rejection)"}


def check_idempotency(c: dict, client: "stripe.StripeClient") -> dict:
    name = c["name"]
    key = c.get("idempotency_key", f"validate-{name}")
    try:
        a = client.v1.customers.create({"description": f"idempotency test {name}"}, {"idempotency_key": key})
        b = client.v1.customers.create({"description": f"idempotency test {name}"}, {"idempotency_key": key})
    except Exception as e:  # noqa: BLE001
        return {"name": name, "status": "fail", "detail": f"error: {e}"}
    ok = a["id"] == b["id"]
    return {"name": name, "status": "pass" if ok else "fail",
            "detail": f"same idempotency key → {'same' if ok else 'DIFFERENT'} id ({a['id']})"}


DISPATCH = {
    "http": lambda c, client: check_http(c),
    "stripe_paymentintent": lambda c, client: check_paymentintent(c, client),
    "webhook_signature": lambda c, client: check_webhook_signature(c),
    "stripe_idempotency": lambda c, client: check_idempotency(c, client),
}


def main() -> int:
    p = argparse.ArgumentParser(description="Lane A Stripe validation harness (config-driven).")
    p.add_argument("--config", required=True, help="app validation config JSON (see example.stripe.json)")
    p.add_argument("--test-key", required=True, help="TEST secret key (sk_test_/rk_test_)")
    p.add_argument("--out", default="results.json", help="results JSON output path")
    args = p.parse_args()

    if args.test_key.startswith(("sk_live_", "rk_live_")):
        print("REFUSE: --test-key is a LIVE key. Use sk_test_/rk_test_.", file=sys.stderr)
        return 2
    client = stripe.StripeClient(args.test_key)
    cfg = json.load(open(args.config, encoding="utf-8"))

    results = []
    for c in cfg.get("checks", []):
        fn = DISPATCH.get(c["type"])
        if not fn:
            results.append({"name": c.get("name", "?"), "status": "pending",
                            "detail": f"unknown check type {c['type']!r}"})
            continue
        try:
            r = fn(c, client)
        except Exception as e:  # noqa: BLE001
            r = {"name": c.get("name", "?"), "status": "fail", "detail": f"harness error: {e}"}
        r["type"] = c["type"]
        r["flow"] = c.get("flow", "")
        results.append(r)
        icon = {"pass": "PASS", "fail": "FAIL", "pending": "PEND"}[r["status"]]
        print(f"[{icon}] {r['name']}: {r['detail']}")

    summary = {"app": cfg.get("app", ""), "mode": "test",
               "counts": {k: sum(1 for r in results if r["status"] == k) for k in ("pass", "fail", "pending")},
               "results": results}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    c = summary["counts"]
    print(f"\n{c['pass']} pass · {c['fail']} fail · {c['pending']} pending → {args.out}")
    return 1 if c["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
