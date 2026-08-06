#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
secondbrain.py — operational helper for the second-brain agent.

A project's "brain" is a markdown LLM-wiki that lives INSIDE the project's
Obsidian vault folder (the folder containing `.obsidian/`). This script does the
mechanical bookkeeping so the LLM can spend its tokens on thinking, not plumbing:

    detect   find the Obsidian vault root(s) under a project           (no writes)
    init     scaffold an empty brain inside a vault (idempotent)
    log      append a greppable, dated entry to log.md
    reindex  regenerate index.md from the frontmatter of wiki/ pages
    search   naive ranked term-frequency search over wiki/ pages       (no deps)
    stats    counts: pages by type, sources, orphans, links

Stdlib only — runs with plain `python` or `uv run`, online or offline.

Examples
--------
    uv run secondbrain.py detect "E:/backup_2026/Repositorios/diario-de-obra-back-end"
    uv run secondbrain.py init  "<vault>" --project "ObraVision" --confidential false
    uv run secondbrain.py log   "<vault>" ingest "README.md"
    uv run secondbrain.py reindex "<vault>"
    uv run secondbrain.py search  "<vault>" "auth token refresh"
    uv run secondbrain.py stats   "<vault>"

`<vault>` is the vault root (the dir holding `.obsidian/`). The brain files
(index.md, log.md, wiki/, raw/, CLAUDE.md) are created/maintained directly in it.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import math
import os
import re
import sys
from pathlib import Path

WIKI = "wiki"
RAW = "raw"
INDEX = "index.md"
LOG = "log.md"
SCHEMA = "CLAUDE.md"

# wiki/ is organised into these category subfolders (type -> folder)
CATEGORIES = {
    "overview": "overview",
    "synthesis": "overview",
    "entity": "entities",
    "concept": "concepts",
    "source": "sources",
    "comparison": "comparisons",
    "decision": "decisions",
    "experiment": "experiments",
}
CATEGORY_ORDER = ["overview", "entities", "concepts", "experiments", "comparisons", "decisions", "sources"]

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
_STOP = set(
    "the a an and or of to in is are be for on with as at by from this that it its "
    "into via per not no if then else when how what which who whom whose".split()
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _today() -> str:
    return _dt.date.today().isoformat()


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def _parse_frontmatter(text: str) -> dict:
    """Tiny YAML-ish frontmatter parser (flat keys, scalars + [a, b] lists)."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    fm: dict = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            fm[key] = [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()]
        else:
            fm[key] = val.strip("'\"")
    return fm


def _iter_pages(wiki_dir: Path):
    for p in sorted(wiki_dir.rglob("*.md")):
        yield p, _read(p)


def _slug(p: Path) -> str:
    return p.stem


# --------------------------------------------------------------------------- #
# detect
# --------------------------------------------------------------------------- #
def cmd_detect(args) -> int:
    root = Path(args.project)
    if not root.exists():
        print(f"!! path does not exist: {root}", file=sys.stderr)
        return 2
    skip = {"node_modules", ".git", "venv", ".venv", "vendor", "dist", "build", "__pycache__", "target"}
    vaults = []
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip]
        if ".obsidian" in dirnames:
            vaults.append(Path(dirpath))
    if not vaults:
        print("(no Obsidian vault found — fall back to ./.second-brain/)")
        return 1
    for v in vaults:
        brain = "brain-present" if (v / INDEX).exists() else "empty"
        print(f"{v}\t[{brain}]")
    return 0


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #
def cmd_init(args) -> int:
    vault = Path(args.vault)
    if not vault.exists():
        print(f"!! vault path does not exist: {vault}", file=sys.stderr)
        return 2
    (vault / WIKI).mkdir(parents=True, exist_ok=True)
    (vault / RAW).mkdir(parents=True, exist_ok=True)
    for cat in CATEGORY_ORDER:
        (vault / WIKI / cat).mkdir(parents=True, exist_ok=True)

    project = args.project or vault.name
    created = []

    log_p = vault / LOG
    if not log_p.exists():
        log_p.write_text(
            f"# {project} — brain log\n\n"
            "Append-only. One line per op, greppable: `## [YYYY-MM-DD] <op> | <title>`\n\n",
            encoding="utf-8",
        )
        created.append(LOG)

    idx_p = vault / INDEX
    if not idx_p.exists():
        idx_p.write_text(
            f"# {project} — brain index\n\n"
            "Catalog of every wiki page. Read this FIRST on any query, then drill in.\n"
            "Regenerate with `secondbrain.py reindex`.\n\n_(empty — run an ingest)_\n",
            encoding="utf-8",
        )
        created.append(INDEX)

    schema_p = vault / SCHEMA
    if not schema_p.exists():
        schema_p.write_text(_project_schema(project, args.confidential, args.shared), encoding="utf-8")
        created.append(SCHEMA)

    print(f"brain ready in: {vault}")
    print(f"created: {', '.join(created) if created else '(nothing new — already initialised)'}")
    return 0


def _project_schema(project: str, confidential: str, shared: str) -> str:
    conf = str(confidential).lower() in ("1", "true", "yes")
    conf_block = (
        "> ⚠️ **CONFIDENTIAL brain.** This project holds secrets/infra (IPs, creds, configs).\n"
        "> This brain lives ONLY in this repo. **Never** copy pages, snippets, or summaries of\n"
        "> it into `agentes_perdidos` or any shared base. Links to the shared base are one-way.\n\n"
        if conf
        else ""
    )
    return f"""---
brain: {project}
maintained-by: second-brain agent (agentes_perdidos)
confidential: {str(conf).lower()}
---

# {project} — brain schema

This folder is an **LLM-wiki second brain**, maintained by the `second-brain` agent.
It's an Obsidian vault: open it in Obsidian to browse pages, links, and the graph.

{conf_block}## Layout

- `index.md` — catalog of every page. Read FIRST on a query. Regenerate via reindex.
- `log.md`   — append-only dated history (`## [YYYY-MM-DD] <op> | <title>`).
- `wiki/`    — LLM-owned pages: `overview/ entities/ concepts/ comparisons/ decisions/ sources/`.
- `raw/`     — immutable source documents. Read from, never edit.

## Conventions

- One page per entity/concept/source. Filename = kebab-case slug.
- Every page opens with YAML frontmatter (`title, type, created, updated, sources, tags`).
- Cross-link liberally with `[[slug]]`. Cite sources inline: `(per [[source-slug]])`.
- Contradictions are flagged inline (`> ⚠️ Contradiction: ...`), never silently overwritten.

## Generic knowledge → shared base (don't duplicate)

Generic, non-confidential topics (Claude Code best practices, uv/PEP-723, the LLM-wiki
pattern, the agentes_perdidos agents) live ONCE in the shared base at:

    {shared}

Reference those pages instead of re-ingesting them here. Keep this brain project-specific.

## How to drive

Point an LLM at `agents/second-brain/SKILL.md` (in agentes_perdidos) and this vault, then:
`ingest <raw/...>`, `query <question>`, `lint`, `onboard`.
"""


# --------------------------------------------------------------------------- #
# log
# --------------------------------------------------------------------------- #
def cmd_log(args) -> int:
    vault = Path(args.vault)
    log_p = vault / LOG
    if not log_p.exists():
        log_p.write_text(f"# {vault.name} — brain log\n\n", encoding="utf-8")
    entry = f"## [{_today()}] {args.op} | {args.title}\n"
    if args.note:
        entry += f"{args.note.strip()}\n"
    with log_p.open("a", encoding="utf-8") as f:
        f.write(entry + "\n")
    print(entry.strip())
    return 0


# --------------------------------------------------------------------------- #
# reindex
# --------------------------------------------------------------------------- #
def cmd_reindex(args) -> int:
    vault = Path(args.vault)
    wiki_dir = vault / WIKI
    if not wiki_dir.exists():
        print("!! no wiki/ dir — run init first", file=sys.stderr)
        return 2

    buckets: dict[str, list[tuple[str, str, str]]] = {c: [] for c in CATEGORY_ORDER}
    n = 0
    for p, text in _iter_pages(wiki_dir):
        fm = _parse_frontmatter(text)
        ptype = fm.get("type", "")
        cat = CATEGORIES.get(ptype) or _category_from_path(p, wiki_dir)
        title = fm.get("title") or _slug(p).replace("-", " ").title()
        summary = _first_sentence(text)
        rel = p.relative_to(vault).as_posix()
        buckets.setdefault(cat, []).append((title, rel, summary))
        n += 1

    lines = [f"# {vault.name} — brain index", ""]
    lines.append(f"_{n} pages · regenerated {_today()}._ Read this first; then open the page.")
    lines.append("")
    for cat in CATEGORY_ORDER:
        items = sorted(buckets.get(cat, []))
        if not items:
            continue
        lines.append(f"## {cat.title()}")
        lines.append("")
        for title, rel, summary in items:
            link = rel[:-3] if rel.endswith(".md") else rel  # vault-relative, no extension
            suffix = f" — {summary}" if summary else ""
            # Obsidian graph only draws edges for [[wikilinks]], not [md](links) — use wikilinks
            # so index.md becomes the hub node connecting to every page.
            lines.append(f"- [[{link}|{title}]]{suffix}")
        lines.append("")
    (vault / INDEX).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"reindexed {n} pages -> {vault / INDEX}")
    return 0


def _category_from_path(p: Path, wiki_dir: Path) -> str:
    try:
        top = p.relative_to(wiki_dir).parts[0]
    except ValueError:
        return "concepts"
    return top if top in CATEGORY_ORDER else "concepts"


def _first_sentence(text: str) -> str:
    body = FRONTMATTER_RE.sub("", text).strip()
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(">"):
            continue
        line = re.sub(r"[*_`]", "", line)
        m = re.match(r"(.+?[.!?])(\s|$)", line)
        out = (m.group(1) if m else line).strip()
        return out[:160] + ("…" if len(out) > 160 else "")
    return ""


# --------------------------------------------------------------------------- #
# search
# --------------------------------------------------------------------------- #
def _tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in _STOP and len(t) > 1]


def cmd_search(args) -> int:
    """BM25-lite ranked retrieval over wiki pages — the agent's recall primitive.

    Designed for an LLM agent to call, read the top 1-3 hits, and answer — instead
    of bulk-reading the wiki. Output is token-lean: score · title · path · summary.
    Ranking: idf-weighted term frequency, length-normalized, with title/tag/heading
    boosts and a coverage multiplier favouring pages that hit MORE query terms.
    """
    vault = Path(args.vault)
    wiki_dir = vault / WIKI
    if not wiki_dir.exists():
        print("!! no wiki/ dir", file=sys.stderr)
        return 2
    q = _tokens(args.query)
    if not q:
        print("!! empty query after stopword removal", file=sys.stderr)
        return 2
    qset = set(q)

    # pass 1: load docs + document frequency per term (for idf)
    docs = []  # (p, fm, body_lower, title_lower, headings_lower, tags_lower, doclen)
    df = {}
    for p, text in _iter_pages(wiki_dir):
        fm = _parse_frontmatter(text)
        body = text.lower()
        title = (str(fm.get("title", "")) + " " + _slug(p)).lower()
        headings = " ".join(re.findall(r"^#{1,3}\s+(.*)", text, re.M)).lower()
        tags = " ".join(fm.get("tags", []) if isinstance(fm.get("tags"), list) else []).lower()
        doclen = max(1, body.count(" "))
        docs.append((p, fm, body, title, headings, tags, doclen))
        for t in qset:
            if t in body or t in title:
                df[t] = df.get(t, 0) + 1

    n = max(1, len(docs))
    idf = {t: math.log(1 + n / (df.get(t, 0) + 0.5)) for t in qset}

    scored = []
    for p, fm, body, title, headings, tags, doclen in docs:
        raw = 0.0
        matched = 0
        for t in q:
            tf = body.count(t)
            if tf == 0 and t not in title and t not in tags:
                continue
            matched += 1
            w = tf + 4 * title.count(t) + 3 * tags.count(t) + 2 * headings.count(t)
            raw += idf[t] * w / (1 + math.log(doclen))
        if matched:
            coverage = matched / len(q)  # favour pages hitting more distinct query terms
            scored.append((raw * (0.4 + 0.6 * coverage), p, fm))
    scored.sort(reverse=True, key=lambda x: x[0])
    if not scored:
        print("(no matches)")
        return 1
    for score, p, fm in scored[: args.top]:
        title = fm.get("title") or _slug(p)
        rel = p.relative_to(vault).as_posix()
        summ = _first_sentence(_read(p))
        print(f"{score:6.2f}  {title}  ·  {rel}")
        if summ:
            print(f"         {summ}")
    return 0


# --------------------------------------------------------------------------- #
# stats
# --------------------------------------------------------------------------- #
def cmd_stats(args) -> int:
    vault = Path(args.vault)
    wiki_dir = vault / WIKI
    if not wiki_dir.exists():
        print("!! no wiki/ dir", file=sys.stderr)
        return 2
    by_type: dict[str, int] = {}
    slugs: set[str] = set()
    inbound: dict[str, int] = {}
    total = 0
    for p, text in _iter_pages(wiki_dir):
        total += 1
        fm = _parse_frontmatter(text)
        by_type[fm.get("type", "?")] = by_type.get(fm.get("type", "?"), 0) + 1
        slugs.add(_slug(p))
        for tgt in WIKILINK_RE.findall(text):
            tgt = tgt.strip().split("/")[-1].lower()  # path-qualified -> basename, case-insensitive
            inbound[tgt] = inbound.get(tgt, 0) + 1
    orphans = sorted(s for s in slugs if inbound.get(s.lower(), 0) == 0)
    raw_n = len(list((vault / RAW).rglob("*"))) if (vault / RAW).exists() else 0

    print(f"vault:   {vault}")
    print(f"pages:   {total}   raw sources: {raw_n}")
    print("by type: " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
    print(f"orphans ({len(orphans)}): " + (", ".join(orphans[:20]) + (" …" if len(orphans) > 20 else "") if orphans else "none"))
    return 0


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def main() -> int:
    # Windows consoles default to cp1252 and crash on Unicode in page titles/summaries.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="second-brain LLM-wiki helper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("detect", help="find Obsidian vault root(s) under a project")
    p.add_argument("project")
    p.set_defaults(fn=cmd_detect)

    p = sub.add_parser("init", help="scaffold a brain inside a vault")
    p.add_argument("vault")
    p.add_argument("--project", default="")
    p.add_argument("--confidential", default="false")
    p.add_argument("--shared", default="<agentes_perdidos>/agents/second-brain/shared/")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("log", help="append a dated log entry")
    p.add_argument("vault")
    p.add_argument("op", help="ingest | query | lint | onboard | ...")
    p.add_argument("title")
    p.add_argument("--note", default="")
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("reindex", help="regenerate index.md from wiki frontmatter")
    p.add_argument("vault")
    p.set_defaults(fn=cmd_reindex)

    p = sub.add_parser("search", help="ranked term-frequency search over wiki pages")
    p.add_argument("vault")
    p.add_argument("query")
    p.add_argument("--top", type=int, default=8)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("stats", help="page/source/orphan counts")
    p.add_argument("vault")
    p.set_defaults(fn=cmd_stats)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
