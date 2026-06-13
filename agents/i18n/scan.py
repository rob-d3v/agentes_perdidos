#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
scan.py — list candidate user-facing string literals in a codebase so the agent
can assign semantic dotted keys to them. This is the *systematic* half of
extraction; the agent does the *judgement* half (which strings are really
user-facing, what key to name them).

It is intentionally a lightweight heuristic (one regex per file family), NOT a
full parser — a port of the idea behind InterPRO's Scanner framework without
re-implementing 19 language scanners.

Usage:
  uv run agents/i18n/scan.py --root <project_dir> [--ext tsx,ts,jsx,js,java,vue,svelte]
                              [--ignore node_modules,dist,build,.git]
                              [--min-len 2] [--json]

Output (default = human table; --json = machine list):
  file:line  [suggestedKey]  "the string"
"""
import argparse, json, os, re, sys

# Windows consoles default to cp1252 → printing UI strings with arrows/emoji/
# accents raises UnicodeEncodeError. Force UTF-8 output everywhere.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

EXT_DEFAULT = "tsx,ts,jsx,js,java,vue,svelte,kt,py"
IGNORE_DEFAULT = "node_modules,dist,build,.git,.expo,android,ios,vendor,__pycache__,locales,i18n"

STRING_RE = re.compile(r"""(?<![\w$])(["'`])((?:\\.|(?!\1).)*?)\1""")

# Lines/strings to skip — not user-facing.
SKIP_LINE = re.compile(r"""\b(import|require|export\s+\*|from)\b""")
SKIP_CALL = re.compile(r"""\b(t|translate|getText|i18n|useTranslation|key|className|"""
                       r"""classList|styles?|testID|console\.\w+|require|import|"""
                       r"""getString|setProperty|getProperty)\s*\(?\s*$""")
# Already inside a translation call as the DEFAULT-value arg, e.g.
# `t('home.x', 'Hello')` — the 'Hello' is keyed already, not residual.
INSIDE_T = re.compile(r"""\b(t|translate|getText|tx)\(\s*(['"]).*?\2\s*,\s*$""")
URLISH = re.compile(r"""^(https?://|/|\.{0,2}/|@|#[0-9a-fA-F]{3,8}$|data:|mailto:)""")
LOOKS_CODE = re.compile(r"""^[\w.\-/]+$""")          # identifiers, paths, css tokens
# JSX/HTML attributes whose value is never user-facing text (unlike placeholder/
# title/aria-label/alt, which ARE). Matches `className=`, `className={`, etc.
SKIP_ATTR = re.compile(
    r"""\b(className|class|style|key|id|type|name|role|htmlFor|to|href|src|rel|"""
    r"""target|xmlns|viewBox|fill|stroke|transform|points|d|cx|cy|r|x|y|width|"""
    r"""height|data-[\w-]+)\s*=\s*[{]?\s*$""")
# A Tailwind/CSS class token: has a hyphen/colon/slash, or is a known utility.
CSS_TOKEN = re.compile(
    r"""^(-?[a-z]+[-:/][-a-z0-9.:/\[\]%#()]*|flex|grid|relative|absolute|fixed|"""
    r"""sticky|block|inline|hidden|container|truncate|uppercase|lowercase|italic|"""
    r"""underline|rounded|border|shadow|transition|transform|overflow|group|peer|"""
    r"""static|visible|invisible|isolate)$""")
HAS_LETTERS = re.compile(r"[A-Za-zÀ-ÿ]")
HAS_SPACE_OR_CAP_SENTENCE = re.compile(r"[ ]|^[A-ZÀ-Ý].*[a-zà-ÿ]")


def slugify(s, maxw=4):
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", s.lower())[:maxw]
    return ".".join(words) or "label"


def suggested_key(path, root, text):
    rel = os.path.relpath(path, root).replace("\\", "/")
    stem = re.sub(r"\.[^.]+$", "", os.path.basename(rel))
    stem = re.sub(r"[^A-Za-z0-9]+", "", stem)
    ns = stem[:1].lower() + stem[1:] if stem else "app"
    return f"{ns}.{slugify(text)}"


def is_candidate(text, min_len):
    t = text.strip()
    if len(t) < min_len:
        return False
    if not HAS_LETTERS.search(t):
        return False
    if URLISH.match(t):
        return False
    if LOOKS_CODE.match(t):                  # single identifier / path / token
        return False
    toks = t.split()
    if len(toks) >= 2:                        # className / style soup, not text
        cssish = sum(1 for w in toks if CSS_TOKEN.match(w))
        if cssish / len(toks) >= 0.6:
            return False
    if t.isupper() and " " not in t:         # ENUM_CONST
        return False
    # require either a space, or a capitalized word (likely a sentence/label)
    if " " not in t and not re.match(r"^[A-ZÀ-Ý][a-zà-ÿ]+$", t):
        return False
    return True


def scan(root, exts, ignore, min_len):
    out = []
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignore]
        for fn in files:
            if fn.rsplit(".", 1)[-1] not in exts:
                continue
            p = os.path.join(dirpath, fn)
            try:
                lines = open(p, encoding="utf-8", errors="ignore").read().splitlines()
            except Exception:                # noqa: BLE001
                continue
            for ln, line in enumerate(lines, 1):
                if SKIP_LINE.search(line):
                    continue
                for m in STRING_RE.finditer(line):
                    text = m.group(2)
                    before = line[:m.start()]
                    if (SKIP_CALL.search(before) or INSIDE_T.search(before)
                            or SKIP_ATTR.search(before)):
                        continue
                    if is_candidate(text, min_len):
                        out.append({
                            "file": os.path.relpath(p, root).replace("\\", "/"),
                            "line": ln,
                            "text": text,
                            "suggestedKey": suggested_key(p, root, text),
                        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--ext", default=EXT_DEFAULT)
    ap.add_argument("--ignore", default=IGNORE_DEFAULT)
    ap.add_argument("--min-len", type=int, default=2)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    exts = set(a.ext.split(","))
    ignore = set(a.ignore.split(","))
    rows = scan(os.path.abspath(a.root), exts, ignore, a.min_len)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print(f'{r["file"]}:{r["line"]}  [{r["suggestedKey"]}]  "{r["text"]}"')
        print(f"\n{len(rows)} candidate strings in {len({r['file'] for r in rows})} files.")


if __name__ == "__main__":
    main()
