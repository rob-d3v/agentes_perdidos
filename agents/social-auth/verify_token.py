#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
verify_token.py — Lane A (headless / token-verify) social-login validation harness, config-driven.

This is the always-on guardrail for the `social-auth` agent. It checks the backend's provider-token
VERIFIER wiring without running a real consent dance, against the app running in its test/homologation
profile. It asserts, per provider:

  1. NEGATIVE PATH (always runnable, no real token needed) — the most important check.
     POST an obviously-invalid token (a hand-crafted tampered/garbage JWT and an empty token) to the
     provider's `/auth/{provider}` endpoint and assert the server REJECTS it (HTTP 400/401/403).
     PASS if rejected; FAIL if the endpoint returns 2xx — that would mean the server trusts an
     UNVERIFIED token, the classic "we never actually verify the signature" critical finding.

  2. POSITIVE PATH (only if --id-token is supplied) — left "pending" otherwise.
     POST a real, freshly-minted ID token to the provider endpoint and assert it returns 2xx and an
     app session (a token field in the JSON body OR a Set-Cookie). If `auth_me` is configured, call it
     with that returned session and assert it returns the current user (matching --expect-email when
     given). Best-effort report of whether a NEW user was created vs an EXISTING user linked.

A real id-token for the positive path can be obtained from Google's OAuth Playground
(https://developers.google.com/oauthplayground — exchange for tokens, copy the `id_token`) or by
copying one straight out of a real "Sign in with Google" attempt (DevTools → the request the GIS
button fires → the `credential` field). Facebook Limited-Login JWTs work the same way. The negative
path needs none of this — it is the deterministic guardrail you can run anytime, even pre-credentials.

Lane B (a real browser login driven by the `navigator` agent) proves the customer experience and
supplies the PDF screenshots; this script is its fast, deterministic counterpart.

CLI:
  uv run agents/social-auth/verify_token.py --config <app>.social.json [--id-token <jwt>] \
      [--provider google] [--out results.json] [--base-url <override>] [--expect-email a@b.com]

Config JSON shape (see fields below; mirror these into <app>.social.json in the project brain):
  {
    "app": "House Studio (mae-app1)",
    "base_url": "http://localhost:8080",          // app API root; --base-url overrides it
    "headers": { "X-App": "..." },                 // optional, sent on every request
    "auth_me": {                                    // optional; GET that returns the current user
      "path": "/api/auth/me",                       //   given the issued session
      "user_email_path": "user.email",              // dotted path to the email in the response
      "created_flag_path": "created"                 // optional dotted path: truthy => new user created
    },
    "providers": {
      "google": {
        "endpoint": "/auth/google",                 // POST path that accepts the provider token
        "token_field": "credential",                // JSON field to carry the token (default below)
        "enabled_flag": true,                        // optional; false => skipped (status pending)
        "session_field": "token",                    // optional dotted path to the app session in 2xx body
        "extra_body": { "client": "web" }            // optional extra JSON merged into the POST body
      },
      "facebook": { "endpoint": "/auth/facebook", "token_field": "accessToken" }
    }
  }

Default token_field per provider when omitted: google->"credential", facebook->"accessToken",
apple->"idToken", anything else->"token".

Emits a results JSON: {app, base_url, generated_note, results:[{provider, check, status, http_code,
detail}]} to --out (default results.json), and prints a readable PASS/FAIL/PEND summary. Status is
"pending" for the positive path when no --id-token was supplied (or a provider is flag-off).

stdlib-only (urllib + json); robust to connection errors (a check that cannot reach the server is
reported as failing-to-run, never a crash). report.py turns the results JSON into the per-app PDF.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Hand-crafted, obviously-invalid JWTs (dependency-free — no PyJWT needed to forge a bad token).
# alg=none, empty claims, signature literally "invalid": any correct verifier MUST reject these.
TAMPERED_JWT = "eyJhbGciOiJub25lIn0.e30.invalid"
GARBAGE_JWT = "not-a-jwt.at-all.0000"
EMPTY_TOKEN = ""

# A token field is rejected only if the endpoint answers with one of these.
REJECT_CODES = (400, 401, 403, 422)

DEFAULT_TOKEN_FIELDS = {
    "google": "credential",
    "facebook": "accessToken",
    "apple": "idToken",
    "x": "accessToken",
    "twitter": "accessToken",
}


def _json_path(obj, path: str):
    """Tiny dotted-path getter: 'data.0.email' -> obj['data'][0]['email']. Raises on a miss."""
    cur = obj
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    return cur


def _http(method, url, headers, body, timeout=30):
    """Return (status, raw_body, set_cookie_or_None). Connection failures raise; callers catch them."""
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
            return resp.status, raw, resp.headers.get("Set-Cookie")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.headers.get("Set-Cookie") if e.headers else None


def _url(base, path):
    return base.rstrip("/") + "/" + str(path).lstrip("/")


def _token_field(provider, pcfg):
    return pcfg.get("token_field") or DEFAULT_TOKEN_FIELDS.get(provider.lower(), "token")


def _post_token(base, headers, provider, pcfg, token):
    """POST one token to a provider endpoint. Returns (status, raw, set_cookie) or raises on connect err."""
    url = _url(base, pcfg["endpoint"])
    body = {_token_field(provider, pcfg): token}
    if isinstance(pcfg.get("extra_body"), dict):
        body.update(pcfg["extra_body"])
    return _http("POST", url, headers, body)


def check_negative(base, headers, provider, pcfg):
    """Assert the endpoint rejects clearly-invalid tokens. The critical guardrail."""
    results = []
    cases = [("tampered alg=none JWT", TAMPERED_JWT), ("garbage JWT", GARBAGE_JWT), ("empty token", EMPTY_TOKEN)]
    for label, token in cases:
        try:
            status, raw, _ = _post_token(base, headers, provider, pcfg, token)
        except urllib.error.URLError as e:
            results.append({"provider": provider, "check": f"negative: {label}", "status": "fail",
                            "http_code": None, "detail": f"could not reach endpoint to run check: {e.reason}"})
            continue
        except Exception as e:  # noqa: BLE001
            results.append({"provider": provider, "check": f"negative: {label}", "status": "fail",
                            "http_code": None, "detail": f"check failed to run: {e}"})
            continue
        if status in REJECT_CODES:
            results.append({"provider": provider, "check": f"negative: {label}", "status": "pass",
                            "http_code": status, "detail": f"rejected with HTTP {status} (good)"})
        elif 200 <= status < 300:
            results.append({"provider": provider, "check": f"negative: {label}", "status": "fail",
                            "http_code": status,
                            "detail": f"CRITICAL: HTTP {status} — server ACCEPTED an unverified token; "
                                      f"it is not verifying the signature server-side"})
        else:
            # Some other non-2xx (e.g. 404 wrong path, 500). Not an accept, but not the clean reject we want.
            results.append({"provider": provider, "check": f"negative: {label}", "status": "fail",
                            "http_code": status,
                            "detail": f"HTTP {status} — not a clean 400/401/403 reject (check endpoint path/server)"})
    return results


def _extract_session(raw, set_cookie, pcfg):
    """Best-effort: pull an app session out of a 2xx response. Returns (session_str_or_None, how)."""
    # 1) explicit configured field wins
    field = pcfg.get("session_field")
    try:
        body = json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        body = None
    if field and isinstance(body, (dict, list)):
        try:
            return str(_json_path(body, field)), f"body.{field}"
        except Exception:  # noqa: BLE001
            pass
    # 2) common token field names
    if isinstance(body, dict):
        for k in ("token", "accessToken", "access_token", "jwt", "session", "sessionToken", "id_token"):
            if body.get(k):
                return str(body[k]), f"body.{k}"
    # 3) a Set-Cookie counts as an issued session
    if set_cookie:
        return set_cookie.split(";", 1)[0], "Set-Cookie"
    return None, ""


def check_positive(base, headers, provider, pcfg, id_token, expect_email):
    """Only when --id-token is given: assert a real token yields an app session (+ auth_me identity)."""
    results = []
    try:
        status, raw, set_cookie = _post_token(base, headers, provider, pcfg, id_token)
    except urllib.error.URLError as e:
        return [{"provider": provider, "check": "positive: token exchange", "status": "fail",
                 "http_code": None, "detail": f"could not reach endpoint to run check: {e.reason}"}]
    except Exception as e:  # noqa: BLE001
        return [{"provider": provider, "check": "positive: token exchange", "status": "fail",
                 "http_code": None, "detail": f"check failed to run: {e}"}]

    if not (200 <= status < 300):
        return [{"provider": provider, "check": "positive: token exchange", "status": "fail",
                 "http_code": status,
                 "detail": f"HTTP {status} — real token was not accepted (expired token? wrong aud/client_id?)"}]

    session, how = _extract_session(raw, set_cookie, pcfg)
    if not session:
        results.append({"provider": provider, "check": "positive: token exchange", "status": "fail",
                        "http_code": status,
                        "detail": f"HTTP {status} but no app session in body or Set-Cookie (no session issued)"})
        return results

    # Best-effort new-vs-linked signal from the exchange response.
    linkage = ""
    try:
        body = json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        body = {}
    if isinstance(body, dict):
        created = None
        for k in ("created", "isNew", "is_new", "newUser", "new_user"):
            if k in body:
                created = bool(body[k])
                break
        if created is True:
            linkage = " — NEW user created"
        elif created is False:
            linkage = " — EXISTING user linked"
    results.append({"provider": provider, "check": "positive: token exchange", "status": "pass",
                    "http_code": status, "detail": f"HTTP {status}, app session issued via {how}{linkage}"})

    # auth_me: use the issued session to confirm the logged-in identity.
    me = cfg_global.get("auth_me")
    if not me:
        results.append({"provider": provider, "check": "positive: auth_me identity", "status": "pending",
                        "http_code": None, "detail": "no auth_me configured — skipped"})
        return results

    me_headers = dict(headers or {})
    if how == "Set-Cookie":
        me_headers["Cookie"] = session
    else:
        me_headers.setdefault("Authorization", f"Bearer {session}")
    try:
        mstatus, mraw, _ = _http("GET", _url(base, me["path"]), me_headers, None)
    except Exception as e:  # noqa: BLE001
        results.append({"provider": provider, "check": "positive: auth_me identity", "status": "fail",
                        "http_code": None, "detail": f"auth_me failed to run: {e}"})
        return results

    if not (200 <= mstatus < 300):
        results.append({"provider": provider, "check": "positive: auth_me identity", "status": "fail",
                        "http_code": mstatus, "detail": f"auth_me returned HTTP {mstatus} — session not accepted"})
        return results

    try:
        mbody = json.loads(mraw)
    except Exception as e:  # noqa: BLE001
        results.append({"provider": provider, "check": "positive: auth_me identity", "status": "fail",
                        "http_code": mstatus, "detail": f"auth_me body not JSON: {e}"})
        return results

    got_email = None
    if me.get("user_email_path"):
        try:
            got_email = _json_path(mbody, me["user_email_path"])
        except Exception:  # noqa: BLE001
            got_email = None
    created_note = ""
    if me.get("created_flag_path"):
        try:
            created_note = " — NEW user created" if _json_path(mbody, me["created_flag_path"]) else " — existing user"
        except Exception:  # noqa: BLE001
            pass

    if expect_email:
        if got_email and str(got_email).lower() == expect_email.lower():
            results.append({"provider": provider, "check": "positive: auth_me identity", "status": "pass",
                            "http_code": mstatus, "detail": f"auth_me identity = {got_email} (matches expected){created_note}"})
        else:
            results.append({"provider": provider, "check": "positive: auth_me identity", "status": "fail",
                            "http_code": mstatus,
                            "detail": f"auth_me identity = {got_email!r}, expected {expect_email!r}"})
    else:
        results.append({"provider": provider, "check": "positive: auth_me identity", "status": "pass",
                        "http_code": mstatus,
                        "detail": f"auth_me returned a user (email={got_email!r}; pass --expect-email to assert){created_note}"})
    return results


cfg_global = {}  # set in main(); read by check_positive for auth_me without threading it through every call.


def main():
    p = argparse.ArgumentParser(description="Lane A social-login token-verify harness (config-driven, stdlib-only).")
    p.add_argument("--config", required=True, help="app validation config JSON (see docstring for shape)")
    p.add_argument("--id-token", help="a real, freshly-minted provider ID token to run the positive path")
    p.add_argument("--provider", help="only validate this provider key from the config (default: all)")
    p.add_argument("--base-url", help="override base_url from the config")
    p.add_argument("--expect-email", help="assert auth_me returns this email on the positive path")
    p.add_argument("--out", default="results.json", help="results JSON output path")
    args = p.parse_args()

    global cfg_global
    try:
        cfg_global = json.load(open(args.config, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"REFUSE: cannot read --config {args.config!r}: {e}", file=sys.stderr)
        return 2

    base = args.base_url or cfg_global.get("base_url")
    if not base:
        print("REFUSE: no base_url (set it in the config or pass --base-url).", file=sys.stderr)
        return 2
    headers = cfg_global.get("headers") or {}
    providers = cfg_global.get("providers") or {}
    if args.provider:
        if args.provider not in providers:
            print(f"REFUSE: provider {args.provider!r} not in config providers {list(providers)}", file=sys.stderr)
            return 2
        providers = {args.provider: providers[args.provider]}
    if not providers:
        print("REFUSE: config has no providers.", file=sys.stderr)
        return 2

    results = []
    for name, pcfg in providers.items():
        if pcfg.get("enabled_flag") is False:
            results.append({"provider": name, "check": "provider", "status": "pending",
                            "http_code": None, "detail": "enabled_flag is false — provider off, skipped"})
            continue
        if not pcfg.get("endpoint"):
            results.append({"provider": name, "check": "config", "status": "fail",
                            "http_code": None, "detail": "no 'endpoint' configured for provider"})
            continue
        # 1) Negative path — always run.
        results.extend(check_negative(base, headers, name, pcfg))
        # 2) Positive path — only with a real token; else pending.
        if args.id_token:
            results.extend(check_positive(base, headers, name, pcfg, args.id_token, args.expect_email))
        else:
            results.append({"provider": name, "check": "positive: token exchange", "status": "pending",
                            "http_code": None, "detail": "no --id-token supplied — positive path skipped (negative path is the guardrail)"})

    for r in results:
        icon = {"pass": "PASS", "fail": "FAIL", "pending": "PEND"}[r["status"]]
        code = f" [{r['http_code']}]" if r.get("http_code") is not None else ""
        print(f"[{icon}] {r['provider']} · {r['check']}:{code} {r['detail']}")

    summary = {
        "app": cfg_global.get("app", ""),
        "base_url": base,
        "generated_note": "Lane A social-auth token-verify. Negative path is the always-on guardrail "
                          "(unverified tokens MUST be rejected). Positive path runs only with --id-token. "
                          "Lane B (real browser login) is driven by the navigator agent.",
        "counts": {k: sum(1 for r in results if r["status"] == k) for k in ("pass", "fail", "pending")},
        "results": results,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    c = summary["counts"]
    print(f"\n{c['pass']} pass · {c['fail']} fail · {c['pending']} pending → {args.out}")
    return 1 if c["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
