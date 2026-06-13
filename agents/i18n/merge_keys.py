#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
merge_keys.py — append agent-extracted i18n keys into the base .properties files.

Given one or more keymap JSON files (each a list of {"key","en","ptBR"} or an
object with a "keymap" list), append every NOT-yet-present key to messages_en
and messages_pt-BR in the target languages dir. Idempotent: keys already in a
base file are left untouched (base languages are sacred / hand-authored).

Real newlines in values are stored as the literal escape \\n (the runtime + the
gtx masker expect escaped whitespace, and that is how the existing base stores
multi-line values). Leading whitespace is escaped so .properties keeps it.

Usage:
  uv run agents/i18n/merge_keys.py --src <languages_dir> --keys a.json b.json ...
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="languages dir with messages_en/pt-BR")
    ap.add_argument("--keys", nargs="+", required=True, help="keymap JSON files")
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

    en = os.path.join(a.src, "messages_en.properties")
    pt = os.path.join(a.src, "messages_pt-BR.properties")
    append_missing(en, uniq, "en")
    append_missing(pt, uniq, "pt-BR")


if __name__ == "__main__":
    main()
