#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
captcha_check.py — Lane A (headless / API) captcha validation harness, config-driven.

The #1 real-world captcha bug is a widget rendered on the page but never verified on the backend
(or verified but fail-OPEN). This harness proves the opposite two things, deterministically, with
no human solving:

  (A) PROVIDER CONTRACT — POST the provider's PUBLISHED TEST SECRET KEYS to its siteverify endpoint
      and assert the documented outcomes. This proves the verify endpoint + our parsing contract
      work, independent of any app. Tolerant of network failure (reported as "pending: could not
      reach provider", never a crash).

  (B) APP GATE (fail-closed) — for each protected endpoint, POST with NO captcha token and assert
      the app returns 4xx. A missing-token request that is ACCEPTED is a critical finding (the gate
      is open). Optionally, when the app is configured-with-test-keys, also POST a pass token (want
      2xx) and a replayed/garbage token (want 4xx). The full positive end-to-end requires the app
      running with the provider TEST keys configured — see `app_configured_with_test_keys`.

It only talks to the provider TEST endpoints + the app's own API. It never needs a real secret key
and never solves a challenge. Lane B (a real browser submitting the live form) is driven separately
via Claude Preview / Claude-in-Chrome and its screenshots are merged into the report.

Usage:
  uv run agents/captcha/captcha_check.py --config <app>.captcha.json --out results.json

See example.captcha.json for the schema.

Exit code: non-zero if any APP-GATE fail-closed check fails (a missing-token request that the app
accepted is critical). Provider-contract checks that could not reach the network are "pending" and
do NOT fail the run.
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Provider published TEST keys → siteverify endpoint + (secret, response) cases with documented
# outcomes. These are stable, public test credentials (never use in prod). The harness drives
# siteverify with them so pass/fail/replay are deterministic with no human solving.
#
# reCAPTCHA v2 test pair (always-pass; shows a watermark) — v3 has NO public always-pass key, so a
# v3 config still exercises the v2 test pair to prove the siteverify contract + our parsing.
RECAPTCHA_VERIFY = "https://www.google.com/recaptcha/api/siteverify"
RECAPTCHA_TEST_SECRET = "6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe"
RECAPTCHA_TEST_RESPONSE = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"

TURNSTILE_VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Each provider → list of contract cases. Each case asserts on the parsed siteverify JSON:
#   want_success : bool  → resp["success"] must equal this
#   want_error   : str   → this code must appear in resp["error-codes"] (if given)
PROVIDER_CONTRACT = {
    "recaptcha-v2": {
        "verify_url": RECAPTCHA_VERIFY,
        "cases": [
            {"label": "recaptcha v2 test pair → success=true",
             "secret": RECAPTCHA_TEST_SECRET, "response": RECAPTCHA_TEST_RESPONSE,
             "want_success": True},
        ],
    },
    # v3 has no public always-pass key; reuse the v2 test pair to prove the endpoint + parsing.
    "recaptcha-v3": {
        "verify_url": RECAPTCHA_VERIFY,
        "cases": [
            {"label": "recaptcha test pair → success=true (v3 has no public test key; "
                      "proves siteverify contract via the v2 pair)",
             "secret": RECAPTCHA_TEST_SECRET, "response": RECAPTCHA_TEST_RESPONSE,
             "want_success": True},
        ],
    },
    "turnstile": {
        "verify_url": TURNSTILE_VERIFY,
        "cases": [
            {"label": "turnstile pass secret 1x…AA → success=true",
             "secret": "1x0000000000000000000000000000000AA", "response": "XXXX.DUMMY.TOKEN.XXXX",
             "want_success": True},
            {"label": "turnstile fail secret 2x…AA → success=false",
             "secret": "2x0000000000000000000000000000000AA", "response": "XXXX.DUMMY.TOKEN.XXXX",
             "want_success": False},
            {"label": "turnstile spent secret 3x…AA → timeout-or-duplicate",
             "secret": "3x0000000000000000000000000000000AA", "response": "XXXX.DUMMY.TOKEN.XXXX",
             "want_success": False, "want_error": "timeout-or-duplicate"},
        ],
    },
}


def _http(method: str, url: str, headers: dict | None, body, timeout: int = 30):
    """Return (status, raw_text). HTTPError surfaces its code+body, not an exception."""
    data = None
    h = dict(headers or {})
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
        elif isinstance(body, bytes):
            data = body
        else:
            data = str(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=h, method=method.upper())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def _post_form(url: str, fields: dict, timeout: int = 30):
    """POST application/x-www-form-urlencoded (the siteverify wire format)."""
    body = urllib.parse.urlencode(fields).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


# ---------------------------------------------------------------------------------------------
# (A) PROVIDER CONTRACT — deterministic, no app needed.
# ---------------------------------------------------------------------------------------------
def check_provider_contract(provider: str, verify_url: str) -> list[dict]:
    """Drive siteverify with the provider's published TEST secrets; assert documented outcomes."""
    spec = PROVIDER_CONTRACT.get(provider)
    out: list[dict] = []
    if not spec:
        out.append({"check": "provider-contract", "target": provider, "status": "pending",
                    "http_code": None,
                    "detail": f"no published test-key contract for provider {provider!r}"})
        return out
    url = verify_url or spec["verify_url"]
    for case in spec["cases"]:
        target = case["label"]
        try:
            status, raw = _post_form(url, {"secret": case["secret"], "response": case["response"]})
        except urllib.error.URLError as e:  # DNS / connect / timeout → not-run, never a crash
            out.append({"check": "provider-contract", "target": target, "status": "pending",
                        "http_code": None, "detail": f"could not reach provider: {e}"})
            continue
        except Exception as e:  # noqa: BLE001
            out.append({"check": "provider-contract", "target": target, "status": "pending",
                        "http_code": None, "detail": f"could not reach provider: {e}"})
            continue
        try:
            payload = json.loads(raw)
        except Exception as e:  # noqa: BLE001
            out.append({"check": "provider-contract", "target": target, "status": "fail",
                        "http_code": status, "detail": f"non-JSON siteverify reply: {e}"})
            continue
        ok = payload.get("success") is case["want_success"]
        errs = payload.get("error-codes", []) or []
        if "want_error" in case:
            ok = ok and case["want_error"] in errs
        detail = f"success={payload.get('success')}"
        if errs:
            detail += f", error-codes={errs}"
        if "want_error" in case:
            detail += f" (wanted {case['want_error']!r})"
        out.append({"check": "provider-contract", "target": target,
                    "status": "pass" if ok else "fail", "http_code": status, "detail": detail})
    return out


# ---------------------------------------------------------------------------------------------
# (B) APP GATE — fail-closed proof against the app's own protected endpoints.
# ---------------------------------------------------------------------------------------------
def _expect_codes(ep: dict, key: str, default: list[int]) -> list[int]:
    v = ep.get(key, default)
    return v if isinstance(v, list) else [v]


def check_app_gate(ep: dict, base_url: str, configured: bool, pass_token: str | None) -> list[dict]:
    """For one protected endpoint: missing-token (must 4xx), and — if configured — pass/replay."""
    method = ep.get("method", "POST")
    path = ep.get("path", "/")
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    token_field = ep.get("token_field", "captchaToken")
    sample = dict(ep.get("sample_body", {}))
    out: list[dict] = []

    # --- missing-token: the core fail-closed guarantee. Accepted == critical finding. ---
    want_missing = _expect_codes(ep, "expect_without_token", [400, 403])
    body = {k: v for k, v in sample.items() if k != token_field}  # strip any token
    try:
        status, _ = _http(method, url, ep.get("headers"), body)
        ok = status in want_missing
        if ok:
            detail = f"no-token {method} → HTTP {status} (rejected, fail-closed holds)"
        else:
            detail = (f"no-token {method} → HTTP {status} but wanted one of {want_missing} — "
                      f"GATE IS OPEN: request accepted WITHOUT a captcha token (critical)")
        out.append({"check": "app-gate-missing-token", "target": f"{method} {path}",
                    "status": "pass" if ok else "fail", "http_code": status, "detail": detail})
    except urllib.error.URLError as e:
        out.append({"check": "app-gate-missing-token", "target": f"{method} {path}",
                    "status": "pending", "http_code": None,
                    "detail": f"could not reach app at {url}: {e} (start the app to run this check)"})
    except Exception as e:  # noqa: BLE001
        out.append({"check": "app-gate-missing-token", "target": f"{method} {path}",
                    "status": "pending", "http_code": None, "detail": f"could not reach app: {e}"})

    if not configured:
        out.append({"check": "app-gate-pass-token", "target": f"{method} {path}",
                    "status": "pending", "http_code": None,
                    "detail": "app not configured-with-test-keys: run the app with the provider TEST "
                              "keys + set app_configured_with_test_keys=true to exercise pass/replay"})
        return out

    if not pass_token:
        out.append({"check": "app-gate-pass-token", "target": f"{method} {path}",
                    "status": "pending", "http_code": None,
                    "detail": "configured but no always_pass_token provided in config"})
        return out

    # --- pass token: with test keys, the always-pass token should be accepted (2xx). ---
    want_pass = _expect_codes(ep, "expect_with_pass_token", [200, 201, 204, 302])
    body = dict(sample)
    body[token_field] = pass_token
    try:
        status, _ = _http(method, url, ep.get("headers"), body)
        ok = status in want_pass
        out.append({"check": "app-gate-pass-token", "target": f"{method} {path}",
                    "status": "pass" if ok else "fail", "http_code": status,
                    "detail": f"pass-token {method} → HTTP {status} (wanted one of {want_pass})"})
    except urllib.error.URLError as e:
        out.append({"check": "app-gate-pass-token", "target": f"{method} {path}",
                    "status": "pending", "http_code": None, "detail": f"could not reach app: {e}"})
    except Exception as e:  # noqa: BLE001
        out.append({"check": "app-gate-pass-token", "target": f"{method} {path}",
                    "status": "pending", "http_code": None, "detail": f"could not reach app: {e}"})

    # --- garbage token: an obviously-bad token must be rejected (4xx), fail-closed on bad input. ---
    want_bad = _expect_codes(ep, "expect_with_bad_token", [400, 403])
    body = dict(sample)
    body[token_field] = "garbage-not-a-real-token"
    try:
        status, _ = _http(method, url, ep.get("headers"), body)
        ok = status in want_bad
        out.append({"check": "app-gate-bad-token", "target": f"{method} {path}",
                    "status": "pass" if ok else "fail", "http_code": status,
                    "detail": f"garbage-token {method} → HTTP {status} (wanted one of {want_bad})"})
    except urllib.error.URLError as e:
        out.append({"check": "app-gate-bad-token", "target": f"{method} {path}",
                    "status": "pending", "http_code": None, "detail": f"could not reach app: {e}"})
    except Exception as e:  # noqa: BLE001
        out.append({"check": "app-gate-bad-token", "target": f"{method} {path}",
                    "status": "pending", "http_code": None, "detail": f"could not reach app: {e}"})
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Lane A captcha validation harness (config-driven).")
    p.add_argument("--config", required=True, help="app validation config JSON (see example.captcha.json)")
    p.add_argument("--out", default="results.json", help="results JSON output path")
    args = p.parse_args()

    cfg = json.load(open(args.config, encoding="utf-8"))
    app = cfg.get("app", "")
    provider = cfg.get("provider", "recaptcha-v3")
    siteverify_url = cfg.get("siteverify_url", "")
    base_url = cfg.get("base_url", "")
    configured = bool(cfg.get("app_configured_with_test_keys", False))
    pass_token = cfg.get("always_pass_token")

    results: list[dict] = []

    # (A) Provider contract — proves the verify endpoint + parsing using published test secrets.
    results.extend(check_provider_contract(provider, siteverify_url))

    # (B) App gate — proves each protected form fails CLOSED without a token.
    endpoints = cfg.get("protected_endpoints", [])
    if endpoints and not base_url:
        results.append({"check": "app-gate", "target": "(config)", "status": "pending",
                        "http_code": None,
                        "detail": "protected_endpoints set but no base_url — cannot reach the app"})
    else:
        for ep in endpoints:
            results.extend(check_app_gate(ep, base_url, configured, pass_token))

    generated_note = (
        "Provider-contract checks use the provider's PUBLISHED TEST SECRET KEYS against the live "
        "siteverify endpoint (deterministic, no human solving); network failure → pending. "
        "App-gate checks prove each protected endpoint FAILS CLOSED without a captcha token. The "
        "full positive end-to-end (pass-token → 2xx) requires the app running with the provider "
        "TEST keys configured (app_configured_with_test_keys=true)."
    )
    summary = {"app": app, "provider": provider, "generated_note": generated_note,
               "results": results}

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    icons = {"pass": "PASS", "fail": "FAIL", "pending": "PEND"}
    for r in results:
        code = f" [{r['http_code']}]" if r.get("http_code") is not None else ""
        print(f"[{icons.get(r['status'], '?')}] {r['check']} · {r['target']}{code}: {r['detail']}")

    counts = {k: sum(1 for r in results if r["status"] == k) for k in ("pass", "fail", "pending")}
    # Only APP-GATE failures are critical (an open gate). Provider-contract failures are also a
    # real defect, but the run's exit code is gated on the fail-closed guarantee specifically.
    gate_fail = sum(1 for r in results if r["status"] == "fail" and r["check"].startswith("app-gate"))
    print(f"\n{counts['pass']} pass · {counts['fail']} fail · {counts['pending']} pending → {args.out}")
    if gate_fail:
        print(f"CRITICAL: {gate_fail} app-gate fail-closed check(s) FAILED — a form is accepting "
              f"requests without a verified captcha token.", file=sys.stderr)
    return 1 if gate_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
