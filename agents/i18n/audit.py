#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
audit.py — the i18n agent's completeness GATE: reconciles the keys *used in code*
against the keys *present in the base locale files*. This is the check the other
scripts lack — `scan.py` only finds UNWRAPPED literals, `status.py` only compares
locales against each other. Neither catches a key that is referenced in code but
absent from en/pt-BR, which makes i18next render the raw key (e.g. a sidebar item
showing the literal text "nav.whatsapp"). Ported from the completeness invariant of
the user's InterPRO tool: never finish with a used key missing, an empty base value,
or code/base drift.

It reports three classes (the InterPRO three-way diff, across the code boundary):

  USED_BUT_MISSING  key passed to t()/translate()/i18nKey in code, absent from base
                    -> ERROR. The classic raw-key leak.
  PHANTOM           a string literal shaped like an i18n key (e.g. "nav.whatsapp"),
                    sitting in code NOT inside a t() call, whose namespace is real
                    (its parent prefix exists among known keys) but the full key is
                    in neither base nor used -> WARN (review). Catches data-driven
                    labels (`label: "nav.whatsapp"` rendered via bare `{label}`) —
                    the missing t() wrapper AND/OR missing base key. It is a HEURISTIC
                    review list (it also catches non-key identifiers like a `helpKey=`
                    prop that happens to match a namespace), so it does NOT fail the
                    gate by default — triage it, or opt in with --strict-phantom.
  RENDER_BARE       a JSX child that renders a label-ish variable WITHOUT t() —
                    `{label}` / `{item.title}` instead of `{t(label)}` -> WARN. This
                    is the exact "data-driven label rendered raw" leak from the
                    screenshot (`const nav = [{label:'nav.whatsapp'}]` then `{label}`):
                    the key exists in base, the render just forgot t(), so i18next
                    never runs and the raw key shows. Precise (skips `{t(label)}`),
                    low-noise — review each. Fields configurable via --label-fields.
  UNUSED_IN_CODE    base key never referenced in code (minus dynamic-prefix cover)
                    -> WARN. Orphan / dead key. Never auto-deleted.

With --check-empty it also flags base keys whose value is blank (InterPRO checkEmptyTags).

Usage:
  uv run agents/i18n/audit.py --root <ui_src> --src <locales_dir> [opts]
  uv run agents/i18n/audit.py --root frontend/src --src frontend/src/i18n/locales --strict --check-empty

  # extra/alternate call names (Spring, custom helpers), comma separated:
  uv run agents/i18n/audit.py --root src --src i18n --call t,translate,Tools.translate,getMessage

Exit code: with --strict, exits 1 if any ERROR class (USED_BUT_MISSING / PHANTOM) is
non-empty — wire it into the agent's done-gate / CI.
"""
import argparse, json, os, re, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))

EXT_DEFAULT = "tsx,ts,jsx,js,java,kt,vue,svelte,py"
IGNORE_DEFAULT = ("node_modules,dist,build,.git,.expo,android,ios,vendor,"
                  "__pycache__,coverage,.next,.turbo,out")
# Translation-call helper names. A receiver (i18n., props., this., messageSource.)
# is allowed before the name; the lookbehind keeps `t` from matching inside a word.
CALL_DEFAULT = "t,translate,getText,tx,$t,getMessage,getString,i18n"
# JSX child variables that almost always hold user-facing text → must be t()-wrapped.
LABEL_FIELDS_DEFAULT = "label,title,heading,subtitle,cta,placeholder,tooltip,caption,header"

# A string literal shaped like a semantic dotted i18n key: lowercase-ish first
# segment, dot-separated, no spaces/slashes. `nav.whatsapp`, `a.b.cD`, `x.y_z2`.
KEYLIKE = re.compile(r"^[a-z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9_]+)+$")
# Any quoted string literal (single/double/backtick), capturing the inner text.
STRING_RE = re.compile(r"""(["'`])((?:\\.|(?!\1).)*?)\1""")
# Attribute form: <Trans i18nKey="a.b" />  /  i18nKey={'a.b'}
ATTR_RE = re.compile(r"""i18nKey\s*=\s*\{?\s*([`'"])([^`'"]+)\1""")
# A captured static key must look like a key (allow -, :, / for namespaced libs).
KEY_OK = re.compile(r"^[\w.][\w.\-:]*$")
SKIP_LINE = re.compile(r"""^\s*(import|export\s|from\s|//|\*|/\*)""")
# i18next plural/ordinal suffixes (CLDR). A `t('k',{count})` call resolves to a
# SUFFIXED base key (`k_one`/`k_other`/…), so a bare `k` used in code is satisfied
# when the base holds any plural variant of it — not a missing key.
PLURAL_RE = re.compile(r"_(?:ordinal_)?(?:zero|one|two|few|many|other)$")


# ---------- base-file loading (shared model with translate.py/status.py) -------
def detect_format(src):
    for f in sorted(os.listdir(src)):
        if f.startswith("."):
            continue
        if f.endswith(".properties"):
            return "properties"
        if f.endswith(".json"):
            return "json"
    return "properties"


def load_props(p):
    d = {}
    for line in open(p, encoding="utf-8"):
        s = line.rstrip("\n")
        if not s.strip() or s.lstrip().startswith(("#", "!")) or "=" not in s:
            continue
        k, v = s.split("=", 1)
        d[k.strip()] = v
    return d


def flatten(o, pre=""):
    out = {}
    for k, v in o.items():
        key = f"{pre}.{k}" if pre else k
        out.update(flatten(v, key)) if isinstance(v, dict) else out.update({key: v})
    return out


def load_json(p):
    return flatten(json.load(open(p, encoding="utf-8")))


def find_base(src, code, fmt):
    cands = ([f"{code}.json"] if fmt == "json"
             else [f"messages_{code}.properties", f"{code}.properties"])
    for c in cands:
        p = os.path.join(src, c)
        if os.path.exists(p):
            return p
    return None


# ---------- code extraction ---------------------------------------------------
def build_call_re(names):
    alt = "|".join(re.escape(n) for n in names)
    # optional `receiver.` then the helper name then `( "key"` (key = group 3).
    return re.compile(
        r"(?<![\w$.])(?:[A-Za-z_$][\w$]*\.)?(" + alt + r")\s*\(\s*([`'\"])"
        r"([^`'\"]*?)\2", re.S)


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def build_render_bare_re(label_fields):
    leaf = "|".join(re.escape(f) for f in label_fields)
    # a JSX child `{ ...label }` (path leaf is label-ish) that is NOT `{t(...)}`.
    # Anchored to a JSX boundary (`>` before or `<` after) so it doesn't match
    # object destructuring like `const { label } = x`.
    path = r"(?:[A-Za-z_$][\w$]*\.)*(?:" + leaf + r")"
    return re.compile(
        r"(?:>\s*\{\s*(" + path + r")\s*\}"          # >{label}
        r"|\{\s*(" + path + r")\s*\}\s*<)")          # {label}<


def build_field_keylike_re(label_fields):
    leaf = "|".join(re.escape(f) for f in label_fields)
    # `label: "nav.whatsapp"` — a label-ish field assigned a key-shaped literal.
    return re.compile(r"\b(?:" + leaf + r")\s*:\s*([`'\"])([a-z][a-zA-Z0-9]*"
                      r"(?:\.[a-zA-Z0-9_]+)+)\1")


def scan_code(root, exts, ignore, names, label_fields):
    """used{key:loc}, dynamic{set}, literals{text:loc}, render_bare[(expr,loc,file)],
    keylabel_files{set} (files that assign a key-like literal to a label field)."""
    call_re = build_call_re(names)
    render_re = build_render_bare_re(label_fields)
    field_re = build_field_keylike_re(label_fields)
    used, dynamic, literals, render_bare, keylabel_files = {}, set(), {}, [], set()
    for dirpath, dirnames, files in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignore]
        for fn in files:
            if fn.rsplit(".", 1)[-1] not in exts:
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace("\\", "/")
            try:
                text = open(p, encoding="utf-8", errors="ignore").read()
            except Exception:  # noqa: BLE001
                continue

            def loc(pos):
                return f"{rel}:{line_of(text, pos)}"

            # 1) translation calls  →  used keys (+ dynamic prefixes)
            for m in call_re.finditer(text):
                key = m.group(3)
                if "${" in key or "' +" in key or '" +' in key:  # template / concat
                    pre = key.split("${")[0].split("' +")[0].split('" +')[0]
                    if "." in pre:
                        prefix = pre[:pre.rfind(".")]
                        if prefix:
                            dynamic.add(prefix)
                    continue
                if key and KEY_OK.match(key) and "." in key:
                    used.setdefault(key, loc(m.start(3)))
            for m in ATTR_RE.finditer(text):
                key = m.group(2)
                if "${" not in key and KEY_OK.match(key):
                    used.setdefault(key, loc(m.start(2)))

            # 2) every string literal  →  phantom candidates
            for m in STRING_RE.finditer(text):
                inner = m.group(2)
                if KEYLIKE.match(inner):
                    literals.setdefault(inner, loc(m.start(2)))

            # 3) JSX render of a label-ish var without t()  →  render-bare leak.
            #    High-signal only when the file also assigns a KEY-LIKE literal to a
            #    label field (so the bare-rendered var actually holds an i18n key).
            if fn.endswith((".tsx", ".jsx")):
                if field_re.search(text):
                    keylabel_files.add(rel)
                for m in render_re.finditer(text):
                    expr = m.group(1) or m.group(2)
                    render_bare.append((expr, loc(m.start()), rel))
    return used, dynamic, literals, render_bare, keylabel_files


def known_prefixes(keys):
    """All proper dotted prefixes of every key — the set of real namespaces."""
    s = set()
    for k in keys:
        parts = k.split(".")
        for i in range(1, len(parts)):
            s.add(".".join(parts[:i]))
    return s


def covered_by_dynamic(key, dynamic):
    return any(key == d or key.startswith(d + ".") for d in dynamic)


# ---------- main --------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Reconcile code i18n keys against base locale files.")
    ap.add_argument("--root", required=True, help="UI source dir to scan for t() calls")
    ap.add_argument("--src", required=True, help="locales dir holding the base files")
    ap.add_argument("--base", default="en,pt-BR")
    ap.add_argument("--format", default="auto", choices=["auto", "properties", "json"])
    ap.add_argument("--ext", default=EXT_DEFAULT)
    ap.add_argument("--ignore", default=IGNORE_DEFAULT)
    ap.add_argument("--call", default=CALL_DEFAULT, help="translation helper names (comma sep)")
    ap.add_argument("--label-fields", default=LABEL_FIELDS_DEFAULT,
                    help="JSX var names that must be t()-wrapped (RENDER_BARE check)")
    ap.add_argument("--no-keylike", action="store_true", help="skip the PHANTOM literal check")
    ap.add_argument("--check-empty", action="store_true", help="flag blank base values too")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on USED_BUT_MISSING (and empty base values if --check-empty)")
    ap.add_argument("--strict-phantom", action="store_true",
                    help="also exit 1 on PHANTOM warnings (heuristic; off by default)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    root = os.path.abspath(a.root)
    src = os.path.abspath(a.src)
    fmt = a.format if a.format != "auto" else detect_format(src)
    load = load_json if fmt == "json" else load_props
    exts = set(a.ext.split(","))
    ignore = set(a.ignore.split(","))
    names = [n.strip() for n in a.call.split(",") if n.strip()]
    label_fields = [f.strip() for f in a.label_fields.split(",") if f.strip()]
    bases = [b.strip() for b in a.base.split(",") if b.strip()]

    base = {}
    base_present = []
    for b in bases:
        f = find_base(src, b, fmt)
        if f:
            base_present.append(b)
            base.update(load(f))
    if not base:
        sys.exit(f"ERROR: no base file {bases} in {src} (format={fmt}).")
    base_keys = set(base)

    used, dynamic, literals, render_bare, keylabel_files = scan_code(
        root, exts, ignore, names, label_fields)
    namespaces = known_prefixes(base_keys | set(used))

    # A bare key is "resolvable" if base holds it OR any plural variant of it —
    # `t('k',{count})` resolves to `k_one`/`k_other`, so bare `k` isn't missing.
    plural_bare = {PLURAL_RE.sub("", k) for k in base_keys if PLURAL_RE.search(k)}
    resolvable = base_keys | plural_bare

    used_but_missing = sorted(
        (k, used[k]) for k in used if k not in resolvable)
    phantom = []
    if not a.no_keylike:
        for lit, loc in sorted(literals.items()):
            if lit in used or lit in resolvable:  # passed to t() / a real key — fine
                continue
            parent = lit[:lit.rfind(".")]
            if parent in namespaces:              # real namespace, missing leaf
                phantom.append((lit, loc))
    # keep only bare renders in files that demonstrably key their labels.
    render_bare = sorted({(e, loc) for e, loc, rel in render_bare
                          if rel in keylabel_files})
    unused = sorted(k for k in base_keys
                    if k not in used and not covered_by_dynamic(k, dynamic)
                    and not (PLURAL_RE.search(k) and PLURAL_RE.sub("", k) in used))
    empties = sorted(k for k in base_keys
                     if not str(base[k]).strip()) if a.check_empty else []

    n_err = len(used_but_missing)
    report = {
        "format": fmt, "basePresent": base_present, "baseKeyCount": len(base_keys),
        "usedKeyCount": len(used), "dynamicPrefixes": sorted(dynamic),
        "usedButMissing": [{"key": k, "at": loc} for k, loc in used_but_missing],
        "phantom": [{"key": k, "at": loc} for k, loc in phantom],
        "renderBare": [{"expr": e, "at": loc} for e, loc in render_bare],
        "unusedInCode": unused,
        "emptyBaseValues": empties,
        "errorCount": n_err,
    }

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"audit: format={fmt} base={base_present} "
              f"baseKeys={len(base_keys)} usedKeys={len(used)} "
              f"dynamicPrefixes={len(dynamic)}")
        print(f"  USED_BUT_MISSING (error): {len(used_but_missing)}")
        for k, loc in used_but_missing[:40]:
            print(f"     {k:<34} {loc}")
        print(f"  RENDER_BARE (label var rendered without t()) (warn): {len(render_bare)}")
        for e, loc in render_bare[:40]:
            print(f"     {{{e}}}{'':<{max(0, 28 - len(e))}} {loc}")
        if not a.no_keylike:
            print(f"  PHANTOM key-like literal (warn/review): {len(phantom)}")
            for k, loc in phantom[:40]:
                print(f"     {k:<34} {loc}")
        print(f"  UNUSED_IN_CODE (warn): {len(unused)}")
        if a.check_empty:
            print(f"  EMPTY base values (error): {len(empties)}")
            for k in empties[:40]:
                print(f"     {k}")
        fail = n_err or empties or (a.strict_phantom and phantom)
        verdict = "FAIL" if fail else "OK"
        print(f"  => {verdict} ({n_err} drift error(s)"
              f"{f', {len(empties)} empty' if a.check_empty else ''}"
              f"{f', {len(phantom)} phantom' if phantom else ''})")

    if a.strict and (n_err or empties or (a.strict_phantom and phantom)):
        sys.exit(1)


if __name__ == "__main__":
    main()
