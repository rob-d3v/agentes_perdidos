#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["beautifulsoup4>=4.12", "requests>=2.31", "lxml>=5.0"]
# ///
"""
AI Visibility scorer — grades a page against the 23-element GEO/AEO framework, with
Element 0 (crawler extractability) as the gate. Fetches a URL exactly as an AI crawler does
(raw HTML, NO JavaScript execution) or reads a local HTML file, then emits a 0-100 score plus
a per-element pass/fail table and a prioritized action plan.

This is a HEURISTIC. It detects what is structurally present in the HTML (schema, tables,
headings, meta, author markup, freshness date, https, url shape). Judgment elements (intent
match, original data quality, methodology, social-proof authenticity) are reported as
"needs-human" — the LLM driving the agent fills those in. Don't treat the number as a promise.

Usage:
  uv run score.py --url https://site/blog/post --type blog
  uv run score.py --file dist/index.html --type spa-landing
  uv run score.py --url https://site --extractability-only
  uv run score.py --url ... --type product --json
"""
from __future__ import annotations
import argparse, json, re, sys
from dataclasses import dataclass, field
from urllib.parse import urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except Exception as e:  # pragma: no cover
    print(f"missing deps ({e}); run via `uv run score.py ...`", file=sys.stderr)
    sys.exit(2)

# AI crawlers fetch raw HTML and do NOT run JS. Identify as one so the server returns what a
# crawler would actually index (some sites vary output by UA).
GPTBOT_UA = ("Mozilla/5.0 (compatible; GPTBot/1.1; +https://openai.com/gptbot)")

TYPES = {"blog", "spa-landing", "product"}

# Which elements are scored per content type. Anything not listed = N/A (skipped, not penalized).
# Keys are element ids; value True means "applies". Judgment-only elements are scored too but
# flagged needs_human when not auto-detectable.
ADAPTER = {
    "blog":        set(range(1, 24)) - {17},               # everything except conversion
    "spa-landing": {0,1,2,4,5,6,10,12,13,14,15,16,17,18,19,20,21,22,23},
    "product":     {0,1,2,3,4,5,6,10,12,13,14,15,16,17,18,19,20,21,22,23},
}
# Element 0 always applies.
for k in ADAPTER:
    ADAPTER[k].add(0)

WEIGHTS = {  # critical heavy, technical light. Element 0 is a gate, scored separately.
    1: 6, 2: 6, 3: 5, 4: 6,                       # critical
    5: 4, 6: 4, 7: 4, 8: 4, 9: 3, 10: 4, 11: 3,   # high
    12: 2, 13: 2, 14: 2, 15: 2, 16: 2, 17: 2,     # enhancement
    18: 3, 19: 2, 20: 1, 21: 1, 22: 1, 23: 2,     # technical
}

NAMES = {
    0: "Extractability (crawler can read it)", 1: "Intent match", 2: "Direct answer first 100w",
    3: "Freshness / last-updated", 4: "Scannability & tables", 5: "Comprehensive coverage / FAQ",
    6: "Expert author (E-E-A-T)", 7: "Original data", 8: "Authoritative citations",
    9: "Transparent methodology", 10: "Q&A format + FAQPage schema", 11: "Hero resource",
    12: "Semantic HTML5", 13: "Factual precision", 14: "Social proof",
    15: "Problem-solution framing", 16: "Value anchoring / ROI", 17: "Conversion elements",
    18: "Schema markup", 19: "Page speed (CWV)", 20: "Mobile responsive", 21: "HTTPS",
    22: "Clean URL", 23: "Meta + sitemap",
}


@dataclass
class Result:
    elem: int
    status: str   # pass | fail | partial | needs_human | n/a
    note: str = ""


@dataclass
class Audit:
    url: str
    ctype: str
    extractable: bool
    visible_chars: int
    results: list[Result] = field(default_factory=list)
    score: int = 0
    max_score: int = 0


def fetch(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": GPTBOT_UA}, timeout=20, allow_redirects=True)
    r.raise_for_status()
    return r.text


def visible_text(soup: BeautifulSoup) -> str:
    # Keep <noscript>: AI crawlers receive its bytes, so it IS extractable text. We grade its
    # *weight* separately (see noscript_split) — noscript is a discounted signal vs real DOM.
    for t in soup(["script", "style", "template"]):
        t.extract()
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def noscript_split(html: str) -> tuple[int, int]:
    """Return (chars outside <noscript>, chars inside <noscript>) of visible text."""
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)  # comments aren't DOM; a literal
    # "<noscript>" inside a comment must not anchor the match (parsers ignore comments).
    ns = re.findall(r"<noscript[^>]*>(.*?)</noscript>", html, flags=re.S | re.I)
    body = re.sub(r"<noscript[^>]*>.*?</noscript>", " ", html, flags=re.S | re.I)
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S | re.I)
    strip = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()
    return len(strip(body)), len(strip(" ".join(ns)))


def json_ld_types(soup: BeautifulSoup) -> set[str]:
    types: set[str] = set()
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "{}")
        except Exception:
            continue
        for obj in (data if isinstance(data, list) else [data]):
            t = obj.get("@type") if isinstance(obj, dict) else None
            if isinstance(t, list):
                types.update(t)
            elif t:
                types.add(t)
    return types


def check(soup: BeautifulSoup, html: str, url: str, text: str) -> dict[int, Result]:
    low = html.lower()
    ld = json_ld_types(soup)
    paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    first_text = text[:700]
    parsed = urlparse(url) if url else None
    R = {}

    def r(i, status, note=""):
        R[i] = Result(i, status, note)

    # 2 — direct answer up top: substantial prose in the first paragraphs, no link in first 100w.
    first_p = next((p for p in paras if len(p.split()) >= 20), "")
    first_100 = " ".join(text.split()[:100])
    has_link_first100 = bool(soup.find("a") and any(
        a.get_text(strip=True) and a.get_text(strip=True) in first_100 for a in soup.find_all("a")))
    if 40 <= len(first_p.split()) <= 160 and not has_link_first100:
        r(2, "pass", f"opening ~{len(first_p.split())}w, no links")
    elif first_p:
        r(2, "partial", "opening present but check 90-110w / no-link rule")
    else:
        r(2, "fail", "no substantive opening paragraph found")

    # 3 — freshness
    if re.search(r"(last\s*updated|atualizado|updated on|modified)", low) or \
       soup.find(attrs={"datetime": True}) or "datemodified" in low:
        r(3, "pass", "date/last-updated signal present")
    else:
        r(3, "fail", "no visible last-updated date")

    # 4 — scannability & tables
    tables = len(soup.find_all("table"))
    h = len(soup.find_all(["h2", "h3"]))
    if tables and h >= 2:
        r(4, "pass", f"{tables} table(s), {h} sub-headings")
    elif h >= 2:
        r(4, "partial", f"{h} sub-headings but 0 tables (tabular data → +~40% citation)")
    else:
        r(4, "fail", "flat structure: <2 sub-headings, no tables")

    # 5 / 10 — FAQ
    has_faq = "FAQPage" in ld or bool(re.search(r"\b(faq|perguntas frequentes|frequently asked)\b", low))
    r(5, "pass" if has_faq else "needs_human", "FAQ section detected" if has_faq else "no FAQ found")
    r(10, "pass" if "FAQPage" in ld else ("partial" if has_faq else "fail"),
      "FAQPage schema" if "FAQPage" in ld else ("FAQ text but no FAQPage schema" if has_faq else "no Q&A/FAQ"))

    # 6 — author / E-E-A-T
    if soup.find(attrs={"rel": "author"}) or "Person" in ld or \
       soup.find(class_=re.compile("author|byline", re.I)) or 'name="author"' in low:
        r(6, "partial", "author signal present — verify named + bio + author page")
    else:
        r(6, "fail", "no author markup")

    # 8 — citations: external links to primary-ish sources
    ext = [a.get("href", "") for a in soup.find_all("a") if a.get("href", "").startswith("http")]
    primary = [u for u in ext if re.search(r"\.(gov|edu)|doi\.org|/study|/research|arxiv", u)]
    if primary:
        r(8, "pass", f"{len(primary)} primary-ish source link(s)")
    elif ext:
        r(8, "partial", "external links present but none look like primary sources")
    else:
        r(8, "fail", "no outbound citations")

    # 11 — hero asset: image with descriptive alt, or chart/svg/figure
    figs = soup.find_all("figure") + soup.find_all("svg")
    alt_imgs = [i for i in soup.find_all("img") if len(i.get("alt", "")) > 12]
    r(11, "pass" if (figs or alt_imgs) else "needs_human",
      f"{len(figs)} figure/svg, {len(alt_imgs)} captioned img" if (figs or alt_imgs) else "no hero asset detected")

    # 12 — semantic HTML5
    sem = sum(bool(soup.find(t)) for t in ("article", "section", "header", "main", "nav"))
    r(12, "pass" if sem >= 2 else "partial" if sem else "fail", f"{sem} semantic landmark tag(s)")

    # 13 — factual precision (flag vague words)
    vague = len(re.findall(r"\b(many|some|recently|several|a lot|various|numerous)\b", text, re.I))
    r(13, "pass" if vague <= 3 else "partial", f"{vague} vague qualifier(s)" + (" — replace with figures/dates" if vague > 3 else ""))

    # 14 — social proof
    if re.search(r"\b(testimonial|review|case study|depoimento|avaliaç|★|⭐)\b", text, re.I) or "Review" in ld:
        r(14, "partial", "social-proof signal — verify named + quantified")
    else:
        r(14, "fail", "no social proof detected")

    # 15 — problem-solution: question-form headings
    q_head = sum(1 for hd in soup.find_all(["h1", "h2", "h3"]) if hd.get_text(strip=True).endswith("?") or
                 re.match(r"^(how|why|what|when|como|por que|o que)\b", hd.get_text(strip=True), re.I))
    r(15, "pass" if q_head >= 2 else "partial" if q_head else "needs_human", f"{q_head} problem/question heading(s)")

    # 16 — value anchoring
    if re.search(r"\b(roi|save|saved|increase|reduc|\d+%|\$\d|R\$\s?\d|x faster|grátis|free)\b", text, re.I):
        r(16, "partial", "value/ROI language present — verify quantified outcomes")
    else:
        r(16, "needs_human", "no quantified value language")

    # 17 — conversion
    cta = soup.find(string=re.compile(r"\b(sign up|get started|buy|comprar|começar|try free|assine)\b", re.I))
    r(17, "pass" if cta else "needs_human", "CTA detected" if cta else "no clear CTA")

    # 18 — schema markup present
    r(18, "pass" if ld else "fail", f"JSON-LD: {', '.join(sorted(ld))}" if ld else "no JSON-LD schema")

    # 21 — https
    r(21, "pass" if (parsed and parsed.scheme == "https") else "n/a" if not parsed else "fail",
      "https" if (parsed and parsed.scheme == "https") else "")

    # 22 — clean url
    if parsed:
        bad = bool(parsed.query) or re.search(r"\b(id|p|page)=\d+", parsed.query) or len(parsed.path) > 90
        r(22, "fail" if bad else "pass", parsed.path + (("?" + parsed.query) if parsed.query else ""))

    # 23 — meta title/description length
    title = (soup.title.string if soup.title else "") or ""
    desc = ""
    m = soup.find("meta", attrs={"name": "description"})
    if m:
        desc = m.get("content", "")
    ok_t = 40 <= len(title) <= 65
    ok_d = 120 <= len(desc) <= 165
    r(23, "pass" if (ok_t and ok_d) else "partial" if (title or desc) else "fail",
      f"title {len(title)}c, desc {len(desc)}c")

    # Judgment-only / not detectable from HTML → needs_human
    for i, msg in {1: "verify real query/intent match", 7: "verify original/proprietary data",
                   9: "verify methodology disclosed"}.items():
        R.setdefault(i, Result(i, "needs_human", msg))
    # 19/20 need Lighthouse / mobile test → out of scope for static parse
    R.setdefault(19, Result(19, "needs_human", "run Lighthouse: LCP<2.5s, INP, CLS"))
    R.setdefault(20, Result(20, "needs_human", "run mobile-friendly test"))
    return R


def score_audit(url, ctype, html) -> Audit:
    soup = BeautifulSoup(html, "lxml")
    text = visible_text(BeautifulSoup(html, "lxml"))
    vis = len(text)
    body_chars, ns_chars = noscript_split(html)
    # Element 0: real first-class DOM content is what crawlers weight. noscript counts as
    # extractable-but-weak; a CSR SPA with neither is invisible.
    real = body_chars >= 600
    ns_only = (not real) and (ns_chars >= 400)
    extractable = real or ns_only
    a = Audit(url=url or "(file)", ctype=ctype, extractable=extractable, visible_chars=vis)

    applies = ADAPTER[ctype]
    checks = check(soup, html, url or "", text)

    # Element 0 result
    if real:
        e0 = Result(0, "pass", f"{body_chars} chars of first-class crawler-visible text"
                    + (f" (+{ns_chars} in <noscript>)" if ns_chars else ""))
    elif ns_only:
        e0 = Result(0, "partial", f"only {body_chars} chars in real DOM; {ns_chars} chars are in "
                    "<noscript> — a WEAK/discounted AI signal. Promote into the live DOM "
                    "(SPA shell inside #root) or prerender/SSR.")
    else:
        e0 = Result(0, "fail", f"{body_chars} chars of real text — JS-only SPA; AI crawlers see "
                    "almost nothing. FIX FIRST (prerender/SSR or static shell in #root).")
    a.results.append(e0)

    total = 0
    got = 0
    for i in range(1, 24):
        if i not in applies:
            a.results.append(Result(i, "n/a", "not applicable for this content type"))
            continue
        w = WEIGHTS[i]
        total += w
        res = checks.get(i, Result(i, "needs_human", "manual review"))
        a.results.append(res)
        if res.status == "pass":
            got += w
        elif res.status == "partial":
            got += w * 0.5
        # fail / needs_human / n/a contribute 0 (needs_human is unproven, not credited)
    a.max_score = total
    # If a crawler can't see the content, the content score is meaningless — hard-cap.
    # noscript-only content is visible-but-weak → cap at 40 to reflect the discounted signal.
    raw = round(100 * got / total) if total else 0
    a.score = 0 if not extractable else min(raw, 40) if ns_only else raw
    return a


def render(a: Audit):
    ICON = {"pass": "✅", "fail": "🔴", "partial": "🟡", "needs_human": "🧑", "n/a": "·"}
    print(f"\nAI Visibility Audit — {a.url}")
    print(f"Content type: {a.ctype}")
    print(f"Element 0 (extractability): {'✅ PASS' if a.extractable else '🔴 FAIL'} "
          f"({a.visible_chars} crawler-visible chars)")
    if not a.extractable:
        print("  ⚠  Score forced to 0: an AI crawler sees almost no content. "
              "Prerender/SSR the public routes before anything else matters.")
    print(f"\nScore: {a.score}/100   (citation probability: "
          f"{'<5%' if a.score < 30 else 'low' if a.score < 50 else 'moderate' if a.score < 75 else 'high'})\n")
    fails, humans = [], []
    for res in a.results:
        if res.status == "n/a":
            continue
        print(f"  {ICON[res.status]} [{res.elem:>2}] {NAMES[res.elem]:<34} {res.note}")
        if res.status in ("fail", "partial"):
            fails.append(res)
        elif res.status == "needs_human":
            humans.append(res)
    if fails:
        print("\n▸ Auto/fixable gaps (priority by element weight):")
        for res in sorted(fails, key=lambda r: -WEIGHTS.get(r.elem, 0)):
            print(f"   [{res.elem}] {NAMES[res.elem]} — {res.note}")
    if humans:
        print("\n▸ Needs human judgment:")
        for res in humans:
            print(f"   [{res.elem}] {NAMES[res.elem]} — {res.note}")
    print()


def main():
    try:  # Windows consoles default to cp1252 and choke on the status emoji.
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--url")
    g.add_argument("--file")
    ap.add_argument("--type", default="blog", choices=sorted(TYPES))
    ap.add_argument("--extractability-only", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    html = fetch(args.url) if args.url else open(args.file, encoding="utf-8", errors="replace").read()

    if args.extractability_only:
        body_chars, ns_chars = noscript_split(html)
        real = body_chars >= 600
        ns_only = (not real) and (ns_chars >= 400)
        verdict = "PASS" if real else "WEAK (noscript-only)" if ns_only else "FAIL (JS-only SPA?)"
        out = {"url": args.url or args.file, "real_dom_chars": body_chars,
               "noscript_chars": ns_chars, "extractable": real or ns_only,
               "first_class": real, "verdict": verdict}
        print(json.dumps(out, indent=2) if args.json else
              f"Element 0: {verdict} — {body_chars} real-DOM chars, {ns_chars} in <noscript>")
        return

    a = score_audit(args.url, args.type, html)
    if args.json:
        print(json.dumps({
            "url": a.url, "type": a.ctype, "score": a.score, "max": a.max_score,
            "extractable": a.extractable, "visible_chars": a.visible_chars,
            "elements": [{"id": r.elem, "name": NAMES[r.elem], "status": r.status, "note": r.note}
                         for r in a.results],
        }, indent=2, ensure_ascii=False))
    else:
        render(a)


if __name__ == "__main__":
    main()
