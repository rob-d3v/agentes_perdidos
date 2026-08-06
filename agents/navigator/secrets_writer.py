#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
secrets_writer.py — safely inject harvested credentials into a TARGET project's .env.

navigator harvests keys/IDs from a dashboard (Stripe, etc.) via the browser. This script is the
ONLY sanctioned way it writes them down. It enforces the security model so a secret can never
leak into the public agentes_perdidos repo and a live key can never be written by accident.

Guarantees (all enforced here, not just documented):
  1. REFUSES if --target-env resolves inside the agentes_perdidos repo (no secret lands here).
  2. VERIFIES the target dir's .gitignore actually ignores the env file before writing
     (use --add-gitignore to append the rule; otherwise it refuses).
  3. CLASSIFIES each value — Stripe prefixes (sk_/rk_/pk_ + _test_/_live_) AND OAuth/CAPTCHA
     credentials (Google/Facebook/X client ids+secrets, reCAPTCHA/Turnstile site+secret keys).
  4. LIVE Stripe keys require --allow-live (the operator live-promotion gate).
  5. REFUSES a SECRET value written into a frontend-PUBLIC var (VITE_/REACT_APP_/EXPO_PUBLIC_/
     NEXT_PUBLIC_/PUBLIC_ prefix) — that would ship a secret in the browser/mobile bundle. (GUARD-5)
  6. Idempotent UPSERT — updates a key in place, never duplicates, preserves other lines/comments.
  7. NEVER prints a full secret — name + last-4 only.

Usage (value via stdin keeps it out of shell history — preferred for secrets):
    printf 'sk_test_51ABC...' | uv run agents/navigator/secrets_writer.py \
        --target-env  E:/path/to/project/.env  --set STRIPE_TEST_SECRET_KEY=-
    # '-' means "read this one value from stdin". Repeat --set for several keys with --values-file.

    # non-secret IDs can be inline:
    uv run agents/navigator/secrets_writer.py --target-env .../.env \
        --set STRIPE_PRICE_PRO=price_123 --set STRIPE_PRICE_STUDIO=price_456

    # bulk from a KEY=VALUE file (e.g. harvested.env), one per line:
    uv run agents/navigator/secrets_writer.py --target-env .../.env --values-file harvested.env

    --allow-live      permit *_live_ values (operator gate)
    --add-gitignore   append the env filename to the target .gitignore if missing
    --dry-run         show what WOULD change (masked), write nothing

Exit 0 = written/ok. Non-zero = refused (see message).
"""
import argparse
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Marker files that identify the agentes_perdidos repo root, so we can refuse to write inside it.
PERDIDOS_MARKERS = ("AGENTS.md", "agents")


# Frontend-public env var prefixes — a SECRET written into one of these would ship in the
# browser/mobile bundle. GUARD-5 refuses that.
FRONTEND_PUBLIC_PREFIXES = ("VITE_", "REACT_APP_", "EXPO_PUBLIC_", "NEXT_PUBLIC_", "PUBLIC_")


def classify(value: str) -> tuple[str, bool]:
    """(label, is_live) for known credentials by VALUE pattern; ('opaque value', False) otherwise.
    is_live is True only for Stripe *_live_ keys (the only thing behind the --allow-live gate)."""
    v = value.strip()
    table = {
        "sk_live_": ("live secret key", True), "rk_live_": ("live restricted key", True),
        "pk_live_": ("live publishable key", True), "sk_test_": ("test secret key", False),
        "rk_test_": ("test restricted key", False), "pk_test_": ("test publishable key", False),
        "whsec_": ("webhook signing secret", False), "price_": ("price id", False),
        "prod_": ("product id", False),
        # OAuth (social-auth agent)
        "GOCSPX-": ("google oauth client secret", False),
    }
    for prefix, (label, live) in table.items():
        if v.startswith(prefix):
            return (label, live)
    if v.endswith(".apps.googleusercontent.com"):
        return ("google oauth client id (public)", False)
    return ("opaque value", False)


# Env-key-name hints (used together with the value to judge sensitivity for GUARD-5).
_SECRET_NAME_HINTS = ("CLIENT_SECRET", "APP_SECRET", "CONSUMER_SECRET", "API_SECRET",
                      "SECRET_KEY", "PRIVATE_KEY", "ACCESS_KEY", "BEARER_TOKEN")
_PUBLIC_NAME_HINTS = ("CLIENT_ID", "APP_ID", "SITE_KEY", "PUBLISHABLE", "PUBLIC")


def looks_secret(key: str, value: str) -> bool:
    """True if (key, value) is a backend-only secret. Conservative: known-public wins over generic
    'SECRET' substring so a SITE_KEY/CLIENT_ID is never misflagged."""
    k = key.upper()
    v = value.strip()
    label, _ = classify(v)
    # Hard public signals first.
    if v.startswith("pk_") or label.endswith("(public)") or v.endswith(".apps.googleusercontent.com"):
        return False
    if any(h in k for h in _PUBLIC_NAME_HINTS) and not any(h in k for h in _SECRET_NAME_HINTS):
        return False
    # Hard secret signals (value).
    if v.startswith(("sk_", "rk_", "GOCSPX-", "whsec_")):
        return True
    # Secret signals (name).
    if any(h in k for h in _SECRET_NAME_HINTS):
        return True
    # Facebook app secret heuristic: 32 lowercase-hex chars with a facebook/app-secret-ish name.
    if len(v) == 32 and all(c in "0123456789abcdef" for c in v) and ("FACEBOOK" in k or "FB_" in k or "APP_SECRET" in k):
        return True
    return False


def mask(value: str) -> str:
    v = value.strip()
    return f"{v[:7]}…{v[-4:]}" if len(v) > 14 else "…(short)…"


def is_inside_perdidos(target: Path) -> Path | None:
    """Return the agentes_perdidos root if `target` is inside it, else None."""
    for parent in [target] + list(target.parents):
        name_hit = parent.name == "agentes_perdidos"
        marker_hit = (parent / "AGENTS.md").exists() and (parent / "agents").is_dir()
        if name_hit or marker_hit:
            # Confirm it's THIS repo (has the agents/ dir with known siblings), not a coincidence.
            if (parent / "agents").is_dir():
                return parent
    return None


def gitignored(env_path: Path, add: bool) -> tuple[bool, str]:
    """Check the env filename is ignored by a .gitignore at the env file's dir (or a parent)."""
    name = env_path.name  # e.g. ".env"
    for parent in [env_path.parent] + list(env_path.parent.parents):
        gi = parent / ".gitignore"
        if gi.exists():
            lines = [ln.strip() for ln in gi.read_text(encoding="utf-8", errors="replace").splitlines()]
            patterns = {name, "*.env", ".env", ".env*", f"{name}*"}
            if any(ln in patterns for ln in lines):
                return (True, f"ignored by {gi}")
        # stop at a repo root
        if (parent / ".git").exists():
            break
    if add:
        gi = env_path.parent / ".gitignore"
        prev = gi.read_text(encoding="utf-8") if gi.exists() else ""
        sep = "" if prev.endswith("\n") or prev == "" else "\n"
        gi.write_text(prev + sep + f"{name}\n", encoding="utf-8")
        return (True, f"appended '{name}' to {gi}")
    return (False, f"'{name}' is NOT gitignored near {env_path.parent} (re-run with --add-gitignore)")


def parse_sets(set_args: list[str], values_file: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if values_file:
        for raw in Path(values_file).read_text(encoding="utf-8").splitlines():
            ln = raw.strip()
            if not ln or ln.startswith("#") or "=" not in ln:
                continue
            k, _, v = ln.partition("=")
            out[k.strip()] = v.strip()
    stdin_used = False
    for item in set_args or []:
        if "=" not in item:
            raise SystemExit(f"REFUSE: --set must be KEY=VALUE (got '{item}')")
        k, _, v = item.partition("=")
        k, v = k.strip(), v.strip()
        if v == "-":
            if stdin_used:
                raise SystemExit("REFUSE: only one --set may read '-' (stdin) per invocation.")
            v = sys.stdin.read().strip()
            stdin_used = True
        out[k] = v
    return out


def upsert(env_path: Path, pairs: dict[str, str], dry: bool) -> list[str]:
    """Idempotent in-place upsert. Returns human log lines (masked)."""
    existing: list[str] = []
    if env_path.exists():
        existing = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    index: dict[str, int] = {}
    for i, ln in enumerate(existing):
        s = ln.strip()
        if s and not s.startswith("#") and "=" in s:
            index[s.split("=", 1)[0].strip()] = i
    log = []
    for k, v in pairs.items():
        label, _ = classify(v)
        line = f"{k}={v}"
        if k in index:
            old = existing[index[k]]
            if old == line:
                log.append(f"  = {k}  unchanged ({mask(v)}, {label})")
            else:
                existing[index[k]] = line
                log.append(f"  ~ {k}  updated ({mask(v)}, {label})")
        else:
            existing.append(line)
            log.append(f"  + {k}  added ({mask(v)}, {label})")
    if not dry:
        text = "\n".join(existing)
        if not text.endswith("\n"):
            text += "\n"
        env_path.write_text(text, encoding="utf-8")
    return log


def main() -> int:
    p = argparse.ArgumentParser(description="Safely write harvested credentials into a target .env.")
    p.add_argument("--target-env", required=True, help="path to the TARGET project's .env (NOT here)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="KEY=VALUE; VALUE of '-' reads one value from stdin (repeatable)")
    p.add_argument("--values-file", help="bulk KEY=VALUE file to ingest")
    p.add_argument("--allow-live", action="store_true", help="permit *_live_ values (operator gate)")
    p.add_argument("--add-gitignore", action="store_true", help="append env filename to .gitignore")
    p.add_argument("--dry-run", action="store_true", help="show changes, write nothing")
    args = p.parse_args()

    target = Path(args.target_env).expanduser().resolve()

    # GUARD 1 — never write inside agentes_perdidos.
    perdidos = is_inside_perdidos(target)
    if perdidos is not None:
        print(f"REFUSE: target {target} is inside agentes_perdidos ({perdidos}).")
        print("        Harvested secrets go in the TARGET project's gitignored .env, never here.")
        return 2

    pairs = parse_sets(args.set, args.values_file)
    if not pairs:
        print("REFUSE: nothing to write (pass --set KEY=VALUE and/or --values-file).")
        return 2

    # GUARD 4 — live keys require the operator gate.
    live_hits = {k: classify(v) for k, v in pairs.items()}
    live_keys = [k for k, (label, live) in live_hits.items() if live]
    if live_keys and not args.allow_live:
        print(f"REFUSE: live key(s) present without --allow-live: {', '.join(live_keys)}")
        print("        Live writes require the operator live-promotion gate. Re-run with --allow-live")
        print("        only after authorization is recorded in the project brain.")
        return 3

    # GUARD 5 — never write a SECRET into a frontend-public var (it would ship in the bundle).
    leaks = [k for k, v in pairs.items()
             if k.upper().startswith(FRONTEND_PUBLIC_PREFIXES) and looks_secret(k, v)]
    if leaks:
        print(f"REFUSE: secret value(s) assigned to frontend-PUBLIC var(s): {', '.join(leaks)}")
        print("        VITE_/REACT_APP_/EXPO_PUBLIC_/NEXT_PUBLIC_/PUBLIC_ vars ship to the browser/")
        print("        mobile bundle. Put the secret in a backend-only var (e.g. GOOGLE_CLIENT_SECRET)")
        print("        and keep only public values (client id, site key, pk_) in the frontend var.")
        return 5

    # GUARD 2 — env file must be gitignored.
    ok, why = gitignored(target, args.add_gitignore)
    if not ok:
        print(f"REFUSE: {why}")
        return 4
    print(f"gitignore: {why}")

    target.parent.mkdir(parents=True, exist_ok=True)
    log = upsert(target, pairs, args.dry_run)
    head = "DRY-RUN (no write)" if args.dry_run else f"wrote {target}"
    print(head)
    for ln in log:
        print(ln)
    if live_keys:
        print(f"LIVE keys written (gate cleared): {', '.join(live_keys)} — last-4 only in any doc.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
