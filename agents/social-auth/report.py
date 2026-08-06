#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["reportlab>=4"]
# ///
"""
report.py — build the per-app social-login homologation PDF from verify_token.py results + screenshots.

The PDF is the owner-facing deliverable for the `social-auth` agent: every provider × surface marked
functional / pending / broken, with the Lane-B customer-experience screenshots, the pending items, and
the next actions. Save it UNDER THE TARGET PROJECT (its brain/docs), never in agentes_perdidos.

Usage:
  uv run agents/social-auth/report.py --results results.json --shots ./shots \
        --out HouseStudio-social-auth.pdf [--title "House Studio — Social Login Homologation"] \
        [--notes notes.md]

  --shots  a directory of PNG/JPG screenshots. Each result's `evidence` filenames are matched against
           files in this dir and embedded under that result's section. Optional.
  --notes  a markdown/plain-text file appended after the auto-built "Pending / Next actions". Optional.

Results JSON shape (the canonical one a sibling verify_token.py emits — see that file's docstring):
  {
    "app": "House Studio (mae-app1)",
    "generated_note": "Lane A social-auth token-verify ...",     # printed under the title
    "results": [
      {
        "provider": "google" | "facebook" | "x",
        "surface":  "web" | "mobile" | "desktop",                # provider × surface = one table row
        "status":   "pass" | "pending" | "fail",
        "detail":   "free-text explaining the result",
        "evidence": ["consent.png", "logged_in.png"]              # screenshot filenames in --shots
      },
      ...
    ]
  }

LOOSER shape also accepted (degrade gracefully): a result item may carry "check" instead of "surface"
(this is exactly what verify_token.py emits — e.g. "negative: tampered alg=none JWT"). When "surface"
is absent we fall back to "check", then to a generic "—". `evidence` may be missing (no screenshots).
`http_code` (if present, as verify_token.py emits) is shown inline with the detail. `app` /
`generated_note` may be absent. Anything missing degrades to a placeholder rather than crashing.

If reportlab can't be installed, fall back to the `pdf` skill: this script writes the same content as
a Markdown file next to --out, prints it to stdout, and tells you to convert it with the `pdf` skill.
"""
import argparse
import json
import os
import sys
from datetime import date

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# cp1252-safe: keep emoji to the PDF/markdown body; never rely on the console encoding for the legend.
STATUS_EMOJI = {"pass": "✅", "fail": "❌", "pending": "⚠️"}  # ✅ ❌ ⚠️
STATUS_LABEL = {"pass": "FUNCTIONAL", "fail": "BROKEN", "pending": "PENDING"}
STATUS_RGB = {"pass": (0.13, 0.55, 0.13), "fail": (0.75, 0.16, 0.16), "pending": (0.78, 0.55, 0.0)}


def _emoji(status: str) -> str:
    return STATUS_EMOJI.get(status, "")


def _ascii(text: str) -> str:
    """Drop characters the console (often cp1252 on Windows) can't encode, so prints never crash."""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(enc)
        return text
    except Exception:
        return text.encode(enc, "replace").decode(enc, "replace")


def _surface(r: dict) -> str:
    """Surface for the row label — accept the canonical 'surface', else the looser 'check', else '—'."""
    return str(r.get("surface") or r.get("check") or "—")


def _detail(r: dict) -> str:
    """Detail text, with verify_token.py's optional http_code folded in when present."""
    detail = str(r.get("detail", "") or "")
    code = r.get("http_code")
    if code is not None:
        detail = f"[HTTP {code}] {detail}".strip()
    return detail


def _counts(results: list) -> dict:
    return {k: sum(1 for r in results if r.get("status") == k) for k in ("pass", "fail", "pending")}


def _safe(text: str) -> str:
    """Escape the few characters reportlab's mini-HTML Paragraph parser treats specially."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_pdf(summary: dict, shots_dir: str | None, notes: str | None, out: str, title: str):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle, PageBreak)
    from reportlab.lib.utils import ImageReader

    styles = getSampleStyleSheet()
    h1 = styles["Title"]
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], spaceBefore=14)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], spaceBefore=10)
    body = styles["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.grey)

    results = summary.get("results", []) or []
    counts = _counts(results)

    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm, title=title)
    flow = []
    flow.append(Paragraph(_safe(title), h1))
    sub = (f"App: <b>{_safe(summary.get('app', '?'))}</b> &nbsp;·&nbsp; "
           f"{date.today().isoformat()}")
    flow.append(Paragraph(sub, body))
    flow.append(Paragraph(
        f"Summary: <b>{counts['pass']}</b> functional · "
        f"<b>{counts['pending']}</b> pending · <b>{counts['fail']}</b> broken.", body))
    gen = summary.get("generated_note")
    if gen:
        flow.append(Paragraph(_safe(gen), small))
    # Legend (✅ functional / ⚠️ pending / ❌ broken).
    flow.append(Paragraph(
        f"Legend: {STATUS_EMOJI['pass']} functional &nbsp; "
        f"{STATUS_EMOJI['pending']} pending &nbsp; {STATUS_EMOJI['fail']} broken", small))
    flow.append(Spacer(1, 0.4 * cm))

    # Summary table: rows = provider × surface, a status cell, the detail.
    flow.append(Paragraph("Provider × surface", h2))
    data = [["Provider", "Surface", "Status", "Detail"]]
    style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONTSIZE", (0, 0), (-1, -1), 8),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")])]
    for i, r in enumerate(results, start=1):
        st = r.get("status", "pending")
        label = f"{_emoji(st)} {STATUS_LABEL.get(st, str(st).upper())}".strip()
        data.append([Paragraph(_safe(r.get("provider", "") or "—"), small),
                     Paragraph(_safe(_surface(r)), small),
                     Paragraph(label, small),
                     Paragraph(_safe(_detail(r)), small)])
        style.append(("TEXTCOLOR", (2, i), (2, i), colors.Color(*STATUS_RGB.get(st, (0, 0, 0)))))
    t = Table(data, colWidths=[2.6 * cm, 2.6 * cm, 3.0 * cm, 8.3 * cm], repeatRows=1)
    t.setStyle(TableStyle(style))
    flow.append(t)

    # Per-result sections embedding the screenshots named in each result's `evidence`.
    have_evidence = any(r.get("evidence") for r in results)
    if have_evidence:
        flow.append(PageBreak())
        flow.append(Paragraph("Evidence (Lane B — real browser login)", h2))
        for r in results:
            evidence = r.get("evidence") or []
            if not evidence:
                continue
            st = r.get("status", "pending")
            head = (f"{_emoji(st)} {_safe(r.get('provider', '') or '?')} · {_safe(_surface(r))} "
                    f"— {STATUS_LABEL.get(st, str(st).upper())}")
            flow.append(Paragraph(head, h3))
            if r.get("detail"):
                flow.append(Paragraph(_safe(_detail(r)), small))
            for fn in evidence:
                path = os.path.join(shots_dir, fn) if shots_dir else fn
                if not (shots_dir and os.path.isfile(path)):
                    flow.append(Paragraph(f"(screenshot not found: {_safe(fn)})", small))
                    continue
                try:
                    iw, ih = ImageReader(path).getSize()
                    w = 14 * cm
                    h = w * ih / iw if iw else 8 * cm
                    flow.append(Image(path, width=w, height=min(h, 18 * cm)))
                    flow.append(Paragraph(_safe(os.path.splitext(fn)[0].replace("_", " ")), small))
                    flow.append(Spacer(1, 0.3 * cm))
                except Exception as e:  # noqa: BLE001
                    flow.append(Paragraph(f"(could not embed {_safe(fn)}: {_safe(e)})", small))

    # Pending / Next actions — every ⚠️/❌ with its detail.
    todo = [r for r in results if r.get("status") in ("pending", "fail")]
    flow.append(Paragraph("Pending / Next actions", h2))
    if not todo:
        flow.append(Paragraph("None — every provider × surface is functional. ✅", body))
    else:
        for r in todo:
            st = r.get("status", "pending")
            line = (f"{_emoji(st)} <b>{_safe(r.get('provider', '') or '?')} · {_safe(_surface(r))}</b> — "
                    f"{_safe(_detail(r)) or 'no detail provided'}")
            flow.append(Paragraph(line, body))

    # Free-text notes (appended verbatim, escaped).
    if notes:
        flow.append(Paragraph("Notes", h2))
        for ln in notes.splitlines():
            ln = ln.strip()
            if ln:
                flow.append(Paragraph(_safe(ln), body))

    doc.build(flow)
    print(_ascii(f"PDF written -> {out} "
                 f"({counts['pass']} functional · {counts['pending']} pending · {counts['fail']} broken)"))


def markdown_fallback(summary: dict, shots_dir: str | None, notes: str | None, out: str, title: str) -> str:
    """Render the same content as Markdown so the `pdf` skill can convert it. Returns the markdown text."""
    results = summary.get("results", []) or []
    c = _counts(results)
    lines = []
    lines.append(f"# {title}\n")
    lines.append(f"App: {summary.get('app', '?')} · {date.today().isoformat()}")
    lines.append(f"Summary: {c['pass']} functional · {c['pending']} pending · {c['fail']} broken")
    if summary.get("generated_note"):
        lines.append(f"\n_{summary['generated_note']}_")
    lines.append(f"\nLegend: {STATUS_EMOJI['pass']} functional · "
                 f"{STATUS_EMOJI['pending']} pending · {STATUS_EMOJI['fail']} broken\n")

    lines.append("| Provider | Surface | Status | Detail |")
    lines.append("|---|---|---|---|")
    for r in results:
        st = r.get("status", "pending")
        label = f"{_emoji(st)} {STATUS_LABEL.get(st, str(st).upper())}".strip()
        detail = _detail(r).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {r.get('provider', '') or '—'} | {_surface(r)} | {label} | {detail} |")

    # Per-result evidence listing (filenames; the skill can embed them).
    if any(r.get("evidence") for r in results):
        lines.append("\n## Evidence (Lane B — real browser login)\n")
        for r in results:
            evidence = r.get("evidence") or []
            if not evidence:
                continue
            st = r.get("status", "pending")
            lines.append(f"### {_emoji(st)} {r.get('provider', '?')} · {_surface(r)} — "
                         f"{STATUS_LABEL.get(st, str(st).upper())}")
            for fn in evidence:
                path = os.path.join(shots_dir, fn) if shots_dir else fn
                if shots_dir and os.path.isfile(path):
                    lines.append(f"![{fn}]({path})")
                else:
                    lines.append(f"_(screenshot not found: {fn})_")
            lines.append("")

    todo = [r for r in results if r.get("status") in ("pending", "fail")]
    lines.append("## Pending / Next actions\n")
    if not todo:
        lines.append("None — every provider × surface is functional. ✅")
    else:
        for r in todo:
            st = r.get("status", "pending")
            lines.append(f"- {_emoji(st)} **{r.get('provider', '?')} · {_surface(r)}** — "
                         f"{_detail(r) or 'no detail provided'}")

    if notes:
        lines.append("\n## Notes\n")
        lines.append(notes)

    md = "\n".join(lines) + "\n"

    # Write the markdown next to --out so the `pdf` skill has a file to convert.
    md_path = os.path.splitext(out)[0] + ".md"
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)
        wrote = md_path
    except Exception as e:  # noqa: BLE001
        wrote = None
        print(_ascii(f"(could not write markdown fallback {md_path}: {e})"), file=sys.stderr)

    print(_ascii(md))
    print("", file=sys.stderr)
    if wrote:
        print(_ascii(f"reportlab unavailable -> wrote Markdown summary to {wrote}. "
                     f"Convert it to PDF with the `pdf` skill."), file=sys.stderr)
    else:
        print("reportlab unavailable -> convert the Markdown above to PDF with the `pdf` skill.",
              file=sys.stderr)
    return md


def main() -> int:
    p = argparse.ArgumentParser(description="Build the per-app social-login homologation PDF.")
    p.add_argument("--results", required=True, help="verify_token.py results JSON")
    p.add_argument("--shots", help="directory of Lane B screenshots (matched by name to result evidence)")
    p.add_argument("--notes", help="markdown/text file appended as a free-text Notes section")
    p.add_argument("--out", default="social-auth.pdf")
    p.add_argument("--title", help="PDF title (default: '<app> — Social Login Homologation')")
    args = p.parse_args()

    try:
        summary = json.load(open(args.results, encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(_ascii(f"REFUSE: cannot read --results {args.results!r}: {e}"), file=sys.stderr)
        return 2
    if not isinstance(summary, dict):
        print("REFUSE: --results must be a JSON object (see report.py docstring for the shape).",
              file=sys.stderr)
        return 2

    title = args.title or f"{summary.get('app', 'App')} — Social Login Homologation"
    notes = open(args.notes, encoding="utf-8").read() if args.notes and os.path.exists(args.notes) else None

    try:
        build_pdf(summary, args.shots, notes, args.out, title)
    except ImportError:
        markdown_fallback(summary, args.shots, notes, args.out, title)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
