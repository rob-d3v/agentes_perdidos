#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
merge_keys.py — append agent-extracted i18n keys into the base locale files.

Given one or more keymap JSON files (each a list of {"key","en","ptBR"} or an
object with a "keymap" list), append every NOT-yet-present key to the en and
pt-BR base files in the target languages dir. Idempotent: keys already in a
base file are left untouched (base languages are sacred / hand-authored).

Auto-detects the base format (locked to the project's framework idiom):
  * properties  → messages_en.properties / messages_pt-BR.properties (Java/Spring,
    custom React). Keys stored flat. Real newlines → literal \\n; leading space escaped.
  * json        → en.json / pt-BR.json (i18next). Dotted keymap keys are nested into
    the existing tree (same flatten/unflatten model translate.py uses), so a key like
    "settings.payment.pix" becomes {"settings":{"payment":{"pix": ...}}}.

Usage:
  uv run agents/i18n/merge_keys.py --src <languages_dir> --keys a.json b.json ...
  uv run agents/i18n/merge_keys.py --src <dir> --format json --keys a.json ...
"""
import argparse, json, os, sys


def load_keymap(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = data.get("keymap", [])
    out = []
    for e in data:
        k = e.get("key")
        if not k:
            continue
        out.append((k, e.get("en", ""), e.get("ptBR", "")))
    return out


def existing_keys(path):
    keys = set()
    if not os.path.exists(path):
        return keys
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.lstrip()
            if not s or s.startswith("#") or s.startswith("!"):
                continue
            # split on first unescaped = or :
            for i, ch in enumerate(line):
                if ch in "=:" and (i == 0 or line[i - 1] != "\\"):
                    keys.add(line[:i].strip())
                    break
    return keys


def esc_value(v):
    v = v.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t").replace("\r", "\\r")
    if v[:1] == " ":
        v = "\\" + v  # escape leading space so it is preserved
    return v


def append_missing(path, entries, lang):
    have = existing_keys(path)
    add = [(k, val) for (k, en, pt) in entries
           for val in [en if lang == "en" else pt]
           if k not in have]
    if not add:
        print(f"  {os.path.basename(path)}: nothing to add ({len(have)} keys present)")
        return 0
    # dedupe within the batch, first wins
    seen, rows = set(), []
    for k, val in add:
        if k in seen:
            continue
        seen.add(k)
        rows.append(f"{k}={esc_value(val)}")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n# --- appended by i18n agent (extraction pass) ---\n")
        f.write("\n".join(rows) + "\n")
    print(f"  {os.path.basename(path)}: +{len(rows)} keys")
    return len(rows)


# ---------- json base support (i18next nested locales) ------------------------
def detect_format(src, override):
    if override and override != "auto":
        return override
    has_props = os.path.exists(os.path.join(src, "messages_en.properties")) or \
        os.path.exists(os.path.join(src, "messages_pt-BR.properties"))
    has_json = os.path.exists(os.path.join(src, "en.json")) or \
        os.path.exists(os.path.join(src, "pt-BR.json"))
    if has_json and not has_props:
        return "json"
    return "properties"


def _flatten(obj, prefix=""):
    out = {}
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _unflatten(flat):
    root = {}
    for k, v in flat.items():
        parts = k.split(".")
        node = root
        for p in parts[:-1]:
            nxt = node.get(p)
            if not isinstance(nxt, dict):
                if nxt is not None:
                    raise SystemExit(
                        f"ERROR: key collision — '{p}' is both a value and a parent "
                        f"(offending key '{k}'). Rename one of the keys.")
                nxt = {}
                node[p] = nxt
            node = nxt
        node[parts[-1]] = v
    return root


def append_missing_json(path, entries, lang):
    base = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            base = json.load(f)
    flat = _flatten(base)
    added = 0
    for (k, en, pt) in entries:
        if k in flat:
            continue
        flat[k] = en if lang == "en" else pt
        added += 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_unflatten(flat), f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"  {os.path.basename(path)}: +{added} keys")
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="languages dir with the en/pt-BR base files")
    ap.add_argument("--keys", nargs="+", required=True, help="keymap JSON files")
    ap.add_argument("--format", default="auto", choices=["auto", "properties", "json"])
    a = ap.parse_args()

    entries = []
    for p in a.keys:
        km = load_keymap(p)
        print(f"loaded {len(km)} from {os.path.basename(p)}")
        entries.extend(km)

    # global dedupe by key (first occurrence wins) — common.* repeated across agents
    seen, uniq = set(), []
    for e in entries:
        if e[0] in seen:
            continue
        seen.add(e[0])
        uniq.append(e)
    print(f"total distinct keys: {len(uniq)}")

    fmt = detect_format(a.src, a.format)
    print(f"format: {fmt}")
    if fmt == "json":
        append_missing_json(os.path.join(a.src, "en.json"), uniq, "en")
        append_missing_json(os.path.join(a.src, "pt-BR.json"), uniq, "pt-BR")
    else:
        append_missing(os.path.join(a.src, "messages_en.properties"), uniq, "en")
        append_missing(os.path.join(a.src, "messages_pt-BR.properties"), uniq, "pt-BR")


if __name__ == "__main__":
    main()
