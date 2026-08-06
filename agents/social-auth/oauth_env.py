#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
oauth_env.py — guard that social-OAuth credentials are sorted correctly in a project's .env.

social-auth's hard rule: **client IDs / site keys are PUBLIC** (may ship in the frontend);
**client/app secrets are BACKEND-ONLY** and must NEVER live in a frontend-public var
(`VITE_`/`REACT_APP_`/`EXPO_PUBLIC_`/`NEXT_PUBLIC_`/`PUBLIC_`). This script reads a harvested
.env, classifies each Google / Facebook / X credential by BOTH key-name and value-pattern,
masks every secret in its output, and HARD-REFUSES if a secret is assigned to a public-prefixed
var (the classic "secret leaked into the bundle" finding).

Usage:
    uv run agents/social-auth/oauth_env.py check --env <project>/.env

Exit code 0 = clean. Exit 5 = a secret leaked into a frontend-public var (the only HARD failure).
Everything else (missing creds, a committed client token) is a WARNING, not a failure.
"""
import argparse
import re
import sys
from pathlib import Path

# Force UTF-8 stdout (Windows consoles default to cp1252 and choke on → / ✅ / ❌).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Frontend-public prefixes — a SECRET behind any of these is a leak (the hard failure).
PUBLIC_PREFIXES = ("VITE_", "REACT_APP_", "EXPO_PUBLIC_", "NEXT_PUBLIC_", "PUBLIC_")

# Value patterns that betray a secret regardless of the key name.
GOOGLE_SECRET_RE = re.compile(r"^GOCSPX-")
HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")
GOOGLE_CLIENT_ID_SUFFIX = ".apps.googleusercontent.com"
DIGITS_RE = re.compile(r"^\d{15,17}$")


def strip_public_prefix(key: str) -> str:
    """Return the key name with any frontend-public prefix removed (for name matching)."""
    for pre in PUBLIC_PREFIXES:
        if key.startswith(pre):
            return key[len(pre):]
    return key


def has_public_prefix(key: str) -> bool:
    return key.startswith(PUBLIC_PREFIXES)


def classify(key: str, value: str) -> tuple[str, str, str]:
    """
    Return (provider, kind, sensitivity) for an OAuth credential, using BOTH key name and value.
    sensitivity ∈ {"public", "secret", "semi", "opaque"}.
    """
    name = strip_public_prefix(key).upper()
    v = (value or "").strip()

    # --- Google -----------------------------------------------------------------
    if v.endswith(GOOGLE_CLIENT_ID_SUFFIX) or (re.search(r"GOOGLE.*CLIENT_ID", name)):
        return ("google", "client id", "public")
    if GOOGLE_SECRET_RE.match(v) or re.search(r"GOOGLE.*CLIENT_SECRET", name):
        return ("google", "client secret", "secret")

    # --- Facebook (check CLIENT_TOKEN by name FIRST so the hex-32 value heuristic
    #     below doesn't mis-tag a low-sensitivity client token as an app secret) ----
    if "CLIENT_TOKEN" in name and re.search(r"(FACEBOOK|FB)", name):
        return ("facebook", "client token", "semi")
    if re.search(r"(FACEBOOK|FB).*APP_SECRET", name) or (re.search(r"(FACEBOOK|FB)", name) and HEX32_RE.match(v)):
        return ("facebook", "app secret", "secret")
    if re.search(r"(FACEBOOK|FB).*APP_ID", name) or (re.search(r"(FACEBOOK|FB)", name) and DIGITS_RE.match(v)):
        return ("facebook", "app id", "public")

    # --- X / Twitter ------------------------------------------------------------
    if re.search(r"(X|TWITTER)_CLIENT_ID", name):
        return ("x", "client id", "public")
    if (re.search(r"(X|TWITTER)_CLIENT_SECRET", name) or "CONSUMER_SECRET" in name
            or "API_SECRET" in name or "BEARER_TOKEN" in name):
        return ("x", "secret", "secret")

    # --- generic Facebook client token (no provider word, but unmistakable) -----
    if "CLIENT_TOKEN" in name:
        return ("facebook", "client token", "semi")

    # --- fallback by key-name keywords + value patterns -------------------------
    if GOOGLE_SECRET_RE.match(v) or HEX32_RE.match(v):
        # A secret-shaped value with no provider context — still a secret.
        return ("?", "secret-shaped value", "secret")
    if any(tok in name for tok in ("SECRET", "PRIVATE", "TOKEN")):
        return ("?", "secret", "secret")
    if any(tok in name for tok in ("CLIENT_ID", "APP_ID", "SITE_KEY", "PUBLIC")):
        return ("?", "public id", "public")
    return ("?", "opaque", "opaque")


def mask(value: str) -> str:
    """Name + last-4 only. Never print a full secret."""
    v = (value or "").strip()
    return f"…{v[-4:]}" if len(v) >= 8 else "…(short)…"


def parse_env(path: Path) -> list[tuple[str, str]]:
    """Parse KEY=VALUE lines; ignore comments and blanks. Strips one layer of surrounding quotes."""
    pairs: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        if ln.lower().startswith("export "):
            ln = ln[len("export "):].lstrip()
        k, _, v = ln.partition("=")
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        if k:
            pairs.append((k, v))
    return pairs


# Expected creds per provider for a WEB client. Native/mobile public clients have NO secret.
EXPECTED = {
    "google": [("client id", "public"), ("client secret", "secret")],
    "facebook": [("app id", "public"), ("app secret", "secret")],
    "x": [("client id", "public"), ("secret", "secret")],
}


def cmd_check(args: argparse.Namespace) -> int:
    path = Path(args.env).expanduser()
    if not path.exists():
        print(f"REFUSE: env file not found: {path}")
        return 2

    pairs = parse_env(path)
    if not pairs:
        print(f"REFUSE: no KEY=VALUE lines parsed from {path}")
        return 2

    print(f"env: {path}  ({len(pairs)} assignments)")
    print("-" * 72)

    leaks: list[tuple[str, str, str]] = []     # (key, provider, kind) — HARD failures
    warnings: list[str] = []
    # provider -> set of kinds present
    present: dict[str, set[str]] = {p: set() for p in EXPECTED}

    rows: list[tuple[str, str, str]] = []      # (key, label, shown-value)
    for key, value in pairs:
        provider, kind, sens = classify(key, value)
        if provider == "?" and sens == "opaque":
            continue  # not an OAuth credential we recognize — skip silently

        label = f"{provider}/{kind} [{sens}]"
        if sens == "secret":
            shown = mask(value)
            if has_public_prefix(key):
                leaks.append((key, provider, kind))
        elif sens == "semi":
            shown = mask(value)
            if has_public_prefix(key):
                warnings.append(
                    f"⚠️  {key}: a Facebook client token in a frontend-public var. "
                    f"Low-sensitivity but should not be committed/bundled — prefer backend-only."
                )
        else:  # public — safe to show in full
            shown = value if value else "(empty)"
            if not value:
                warnings.append(f"⚠️  {key}: declared {provider}/{kind} but value is empty.")

        rows.append((key, label, shown))
        if provider in present:
            present[provider].add(kind)

    # --- credential table ----------------------------------------------------
    if rows:
        kw = max(len(r[0]) for r in rows)
        lw = max(len(r[1]) for r in rows)
        for key, label, shown in rows:
            print(f"  {key.ljust(kw)}  {label.ljust(lw)}  {shown}")
    else:
        print("  (no recognized Google/Facebook/X OAuth credentials found)")
    print("-" * 72)

    # --- GUARD: a secret behind a frontend-public prefix is a LEAK -----------
    if leaks:
        print("❌ REFUSE: secret(s) assigned to a FRONTEND-PUBLIC var — this leaks into the bundle:")
        for key, provider, kind in leaks:
            pre = next((p for p in PUBLIC_PREFIXES if key.startswith(p)), "")
            print(f"   ❌ {key}  →  {provider}/{kind} behind public prefix '{pre}'")
        print("   FIX: move the secret to a BACKEND-only var (no VITE_/REACT_APP_/EXPO_PUBLIC_/")
        print("        NEXT_PUBLIC_/PUBLIC_ prefix). Client IDs/site keys are public; secrets are not.")
        print("        Then ROTATE the exposed secret — assume it is already compromised.")
        # Still print the summary below for context, but the exit code is the hard failure.

    # --- per-provider PRESENT vs MISSING summary -----------------------------
    print("Provider summary (web-client expectation):")
    for provider, expected in EXPECTED.items():
        seen = present.get(provider, set())
        if not seen:
            print(f"  {provider:9} — not configured (no creds found).")
            continue
        bits = []
        for kind, sens in expected:
            if kind in seen:
                bits.append(f"{kind} ✅")
            elif sens == "secret":
                # Absent secret is OK for native/mobile public PKCE clients — say so.
                bits.append(f"{kind} ⚠️ missing (OK if this is a native/mobile public client — no secret)")
                warnings.append(
                    f"⚠️  {provider}: no {kind} present. Fine for an Android/iOS/Desktop public PKCE "
                    f"client (they have no secret); a WEB client needs it."
                )
            else:
                bits.append(f"{kind} ⚠️ missing")
                warnings.append(f"⚠️  {provider}: missing {kind} (public id) — frontend cannot start the flow.")
        print(f"  {provider:9} — " + "  |  ".join(bits))

    # --- warnings ------------------------------------------------------------
    if warnings:
        print("-" * 72)
        for w in dict.fromkeys(warnings):  # de-dup, keep order
            print(w)

    # --- verdict -------------------------------------------------------------
    print("=" * 72)
    if leaks:
        print(f"VERDICT: ❌ FAIL — {len(leaks)} secret(s) in a public var. Rotate + relocate, then re-run.")
        return 5
    if warnings:
        print("VERDICT: ✅ no secret leaked — but see warnings above (not blocking).")
        return 0
    print("VERDICT: ✅ clean — no secret in a public var; recognized creds look well-placed.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Guard social-OAuth creds: secrets stay backend-only.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="classify creds in a .env and refuse a secret in a public var")
    c.add_argument("--env", required=True, help="path to the TARGET project's .env to inspect")
    c.set_defaults(func=cmd_check)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
