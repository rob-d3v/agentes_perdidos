#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "python-dotenv>=1.0",
# ]
# ///
"""
research.py — the remodeling agent's research planner & dossier writer.

This script is deliberately *low-token and deterministic*. It does NOT call an LLM or a
paid search API. It does two jobs:

  1. `queries`  — expand a person/brand into the full geo-anchored search matrix, so the
                  driving agent runs each query via its own WebSearch/WebFetch tools and
                  triages results. (Anchoring every query on city+UF is how we beat
                  homonyms — there are many people with the same name.)

  2. `dossier`  — take the agent's *triaged* findings (a JSON file) and render a structured
                  dossie.md with CONFIRMED / UNCERTAIN / DISCARDED / TODO(@em_breve) sections,
                  each CONFIRMED fact carrying its source URL. This is the project brain the
                  remodeling work reads from — every claim on the site must trace to a
                  CONFIRMED row here, or it stays @em_breve.

Run with uv (auto-installs deps from the inline metadata above):

  uv run agents/remodeling/research.py queries \
      --name "Marco Aurélio Gomes" --city "Acreúna" --uf GO --role advogado

  uv run agents/remodeling/research.py queries --name "..." --city "..." --uf GO --json

  uv run agents/remodeling/research.py dossier \
      --findings findings.json --out /path/to/project/.remodeling/dossie.md

The anti-fake rule lives in SKILL.md — read that first.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

try:  # load a repo .env if present (no hard dependency on any key here)
    from dotenv import load_dotenv  # noqa: F401
    load_dotenv()
except Exception:
    pass


def _eprint(*a):
    print(*a, file=sys.stderr)


# ---------------------------------------------------------------------------
# Query matrix — every query is geo-anchored to disambiguate homonyms.
# ---------------------------------------------------------------------------
def build_queries(name: str, city: str, uf: str, role: str) -> list[dict]:
    """Return [{category, query, where}] — the agent runs each via WebSearch/WebFetch."""
    n, c = name.strip(), city.strip()
    uf = uf.strip().upper()
    r = (role or "").strip()
    geo = f"{c} {uf}".strip()

    M: list[tuple[str, str, str]] = [
        # category, query, where-to-look hint
        ("official-oab", f'"{n}" {r} OAB {uf}', "OAB state-section registry + national CNA lookup"),
        ("official-oab", f'{n} OAB {uf} {c}', "OAB subsection member lists"),
        ("official-oab", f'OAB {c} {uf} inscritos {n}', "OAB subsection 'consulta de inscritos' (often a POST form — may need a browser)"),
        ("courts", f'"{n}" {r} {c} {uf} processo', "Jusbrasil / TJ court publications (as the professional, not a party)"),
        ("courts", f'{n} {r} jusbrasil {c}', "Jusbrasil professional profile"),
        ("name-geo", f'"{n}" {r} {geo}', "general web, anchored to city+UF"),
        ("name-geo", f'{n} {r} {c}', "general web, city only"),
        ("name-geo", f'"{n}" escritório de advocacia {c}' if r.startswith("advog") else f'"{n}" {r} {c} escritório', "office / firm"),
        ("firm-directory", f'{n} {c} {uf} apontador OR telelistas OR guiamais', "business directories"),
        ("firm-directory", f'"{n}" {c} CNPJ OR sociedade individual', "company / CNPJ registries"),
        ("maps", f'{n} {r} {c} {uf} endereço telefone', "Google Maps / Google Business listing"),
        ("news-local", f'"{n}" {c} {uf} notícia', "local/regional news of the city"),
        ("news-local", f'{n} {c} palestra OR evento OR entrevista', "talks / events / interviews"),
        ("social", f'"{n}" {c} Instagram OR Facebook OR LinkedIn', "social profiles — verify the city before trusting"),
        ("civic", f'"{n}" {c} associação OR conselho OR câmara OR universidade', "civic / teaching / community roles"),
        ("photos", f'{n} {r} {c} foto', "publicly available photos — accept only if clearly labeled + city-tied"),
    ]
    return [{"category": cat, "query": q, "where": w} for (cat, q, w) in M]


def cmd_queries(args) -> int:
    qs = build_queries(args.name, args.city, args.uf, args.role)
    if args.json:
        print(json.dumps(qs, ensure_ascii=False, indent=2))
        return 0
    print(f"# Search matrix for: {args.name} — {args.role} — {args.city}/{args.uf.upper()}")
    print(f"# {len(qs)} queries. Run each with WebSearch/WebFetch. ANCHOR ON {args.city}/{args.uf.upper()} —")
    print(f"# discard any result tied to another city/UF (homonyms are common).\n")
    last = None
    for q in qs:
        if q["category"] != last:
            print(f"\n## {q['category']}")
            last = q["category"]
        print(f"  - {q['query']}")
        print(f"      -> {q['where']}")
    print("\n# After triage, write findings.json and run:  research.py dossier --findings findings.json --out <brain>/dossie.md")
    return 0


# ---------------------------------------------------------------------------
# Dossier writer — render triaged findings into the project brain.
# ---------------------------------------------------------------------------
_FINDINGS_SHAPE = {
    "name": "Marco Aurélio Gomes",
    "role": "advogado",
    "city": "Acreúna",
    "uf": "GO",
    "confirmed": [
        {"field": "OAB", "value": "OAB/GO 00.000", "source": "https://...", "note": ""}
    ],
    "uncertain": [
        {"field": "specialty", "value": "Direito de Família", "source": "https://...", "why": "not geo-confirmed"}
    ],
    "discarded": [
        {"value": "Marco Aurélio de Carvalho (SP)", "reason": "different city/UF"}
    ],
    "todo_em_breve": ["telefone", "e-mail", "redes sociais", "endereço do escritório"],
}


def _md_escape(s: str) -> str:
    return str(s).replace("|", "\\|")


def render_dossier(f: dict) -> str:
    name = f.get("name", "?")
    role = f.get("role", "")
    city = f.get("city", "")
    uf = (f.get("uf") or "").upper()
    confirmed = f.get("confirmed", []) or []
    uncertain = f.get("uncertain", []) or []
    discarded = f.get("discarded", []) or []
    todo = f.get("todo_em_breve", []) or []

    L: list[str] = []
    L.append(f"# Dossiê: {name} — {role} — {city}/{uf}".rstrip(" —/"))
    L.append("")
    L.append(f"_Gerado por agents/remodeling/research.py em {date.today().isoformat()}._")
    L.append("")
    L.append("> **Regra de ouro:** só o que está em **CONFIRMADO** (com fonte) pode ir pro site. "
             "Todo o resto é `@em_breve`. Nada de informação falsa.")
    L.append("")

    L.append("## ✅ CONFIRMADO (com fonte — pode publicar)")
    if confirmed:
        L.append("")
        L.append("| Campo | Valor | Fonte | Obs |")
        L.append("|---|---|---|---|")
        for c in confirmed:
            L.append(f"| {_md_escape(c.get('field',''))} | {_md_escape(c.get('value',''))} "
                     f"| {_md_escape(c.get('source',''))} | {_md_escape(c.get('note',''))} |")
    else:
        L.append("")
        L.append("**Nada confirmado publicamente ainda.** Use só o mínimo certo (nome, profissão, cidade) "
                 "e marque todo o resto como `@em_breve`.")
    L.append("")

    L.append("## ❓ INCERTO (não publicar — confirmar antes)")
    if uncertain:
        L.append("")
        L.append("| Campo | Valor | Fonte | Por que incerto |")
        L.append("|---|---|---|---|")
        for u in uncertain:
            L.append(f"| {_md_escape(u.get('field',''))} | {_md_escape(u.get('value',''))} "
                     f"| {_md_escape(u.get('source',''))} | {_md_escape(u.get('why',''))} |")
    else:
        L.append("")
        L.append("_(vazio)_")
    L.append("")

    L.append("## 🚫 DESCARTADO (homônimos / outra geografia)")
    if discarded:
        L.append("")
        for d in discarded:
            L.append(f"- {_md_escape(d.get('value',''))} — {_md_escape(d.get('reason',''))}")
    else:
        L.append("")
        L.append("_(vazio)_")
    L.append("")

    L.append("## ⏳ @em_breve (placeholders no site até confirmar)")
    if todo:
        L.append("")
        for t in todo:
            L.append(f"- [ ] {_md_escape(t)}")
    else:
        L.append("")
        L.append("_(nada pendente)_")
    L.append("")
    return "\n".join(L)


def cmd_dossier(args) -> int:
    path = Path(args.findings)
    if not path.exists():
        _eprint(f"ERROR: findings file not found: {path}")
        _eprint("Expected JSON shape:\n" + json.dumps(_FINDINGS_SHAPE, ensure_ascii=False, indent=2))
        return 2
    data = json.loads(path.read_text(encoding="utf-8"))
    md = render_dossier(data)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    n = len(data.get("confirmed", []) or [])
    print(f"Wrote {out}  ({n} confirmed fact(s))")
    if n == 0:
        print("NOTE: nothing confirmed — the site should lean heavily on @em_breve.")
    return 0


def cmd_shape(_args) -> int:
    print(json.dumps(_FINDINGS_SHAPE, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="remodeling agent — research planner & dossier writer")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("queries", help="expand a person/brand into the geo-anchored search matrix")
    q.add_argument("--name", required=True)
    q.add_argument("--city", required=True)
    q.add_argument("--uf", required=True, help="state abbreviation, e.g. GO")
    q.add_argument("--role", default="", help="profession, e.g. advogado / médico / engenheiro")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_queries)

    d = sub.add_parser("dossier", help="render triaged findings.json -> dossie.md")
    d.add_argument("--findings", required=True, help="JSON of triaged findings (see `shape`)")
    d.add_argument("--out", required=True, help="output path, e.g. <project>/.remodeling/dossie.md")
    d.set_defaults(func=cmd_dossier)

    s = sub.add_parser("shape", help="print the expected findings.json shape")
    s.set_defaults(func=cmd_shape)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
