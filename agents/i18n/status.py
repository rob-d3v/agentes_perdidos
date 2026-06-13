#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
status.py — coverage report for a project's locale dir. Powers the agent's
incremental "confere e atualiza" mode: shows which languages are missing which
keys, plus orphan keys (present in a target but no longer in the base).

Usage:
  uv run agents/i18n/status.py --src <locales_dir> [--base en,pt-BR]
                               [--registry <langs.json>] [--json] [--verbose]
"""
import argparse, json, os, sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))


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


def fname(code, fmt):
    return f"{code}.json" if fmt == "json" else f"messages_{code}.properties"


def find(src, code, fmt):
    for c in ([f"{code}.json"] if fmt == "json"
              else [f"messages_{code}.properties", f"{code}.properties"]):
        p = os.path.join(src, c)
        if os.path.exists(p):
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--base", default="en,pt-BR")
    ap.add_argument("--registry", default=os.path.join(HERE, "langs.json"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    src = os.path.abspath(a.src)
    fmt = detect_format(src)
    load = load_json if fmt == "json" else load_props
    bases = [b.strip() for b in a.base.split(",")]
    reg = json.load(open(a.registry, encoding="utf-8"))
    codes = [l["code"] for l in reg["languages"]]

    base_keys = set()
    base_present = []
    for b in bases:
        f = find(src, b, fmt)
        if f:
            base_present.append(b)
            base_keys |= set(load(f).keys())
    if not base_keys:
        sys.exit(f"ERROR: no base file {bases} in {src}")

    report = {"format": fmt, "basePresent": base_present, "baseKeyCount": len(base_keys),
              "totalLanguages": len(codes), "missingFiles": [], "incomplete": [],
              "complete": 0, "orphansByLang": {}}

    for code in codes:
        if code in bases:
            continue
        f = find(src, code, fmt)
        if not f:
            report["missingFiles"].append(code)
            continue
        keys = set(load(f).keys())
        missing = base_keys - keys
        orphan = keys - base_keys
        if orphan:
            report["orphansByLang"][code] = sorted(orphan)
        if missing:
            report["incomplete"].append({"code": code, "missing": len(missing),
                                         "missingKeys": sorted(missing)})
        else:
            report["complete"] += 1

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print(f"format={fmt}  base={base_present} ({len(base_keys)} keys)  "
          f"languages={len(codes)}")
    print(f"  complete (non-base): {report['complete']}")
    print(f"  missing files:       {len(report['missingFiles'])}"
          + (f"  -> {', '.join(report['missingFiles'][:15])}"
             + (' ...' if len(report['missingFiles']) > 15 else '')
             if report["missingFiles"] else ""))
    print(f"  incomplete:          {len(report['incomplete'])}")
    if report["incomplete"] and a.verbose:
        for it in report["incomplete"][:30]:
            print(f"     {it['code']:<9} missing {it['missing']}")
    if report["orphansByLang"]:
        print(f"  langs with orphan keys: {len(report['orphansByLang'])}")
    miss = sorted({k for it in report["incomplete"] for k in it["missingKeys"]})
    if miss:
        print(f"\n  distinct keys needing translation somewhere: {len(miss)}")
        if a.verbose:
            for k in miss[:50]:
                print(f"     {k}")


if __name__ == "__main__":
    main()
