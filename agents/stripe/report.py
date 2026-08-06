#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["reportlab>=4"]
# ///
"""
report.py — build the per-app Stripe homologation PDF from validate.py results + screenshots.

The PDF is the owner-facing deliverable: every payment flow marked functional / pending / broken,
with evidence and the customer-experience screenshots from Lane B, plus the pending items and
next actions. Save it UNDER THE TARGET PROJECT (its brain/docs), never in agentes_perdidos.

Usage:
  uv run agents/stripe/report.py --results results.json --shots ./shots \
        --out HouseStudio-stripe-homologation.pdf --title "House Studio — Stripe Homologation" \
        --notes notes.md

  --shots  a directory of PNG/JPG screenshots; filenames become captions (sorted). Optional.
  --notes  a markdown/plain-text file appended as "Notes & next actions". Optional.

If reportlab can't be installed, fall back to the `pdf` skill: this script will print the same
content as markdown to stdout so it can be converted there.
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

STATUS_LABEL = {"pass": "FUNCTIONAL", "fail": "BROKEN", "pending": "PENDING"}
STATUS_RGB = {"pass": (0.13, 0.55, 0.13), "fail": (0.75, 0.16, 0.16), "pending": (0.78, 0.55, 0.0)}


def build_pdf(summary: dict, shots_dir: str | None, notes: str | None, out: str, title: str):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle, PageBreak)

    styles = getSampleStyleSheet()
    h1 = styles["Title"]
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], spaceBefore=14)
    body = styles["BodyText"]
    small = ParagraphStyle("small", parent=body, fontSize=8, textColor=colors.grey)

    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm, title=title)
    flow = []
    flow.append(Paragraph(title, h1))
    counts = summary.get("counts", {})
    sub = (f"App: <b>{summary.get('app', '?')}</b> &nbsp;·&nbsp; Mode: <b>{summary.get('mode', 'test')}"
           f"</b> &nbsp;·&nbsp; {date.today().isoformat()}")
    flow.append(Paragraph(sub, body))
    flow.append(Paragraph(
        f"Summary: <b>{counts.get('pass', 0)}</b> functional · "
        f"<b>{counts.get('pending', 0)}</b> pending · <b>{counts.get('fail', 0)}</b> broken.", body))
    flow.append(Paragraph("Validated in Stripe <b>TEST mode</b> (homologation). No live charges.", small))
    flow.append(Spacer(1, 0.4 * cm))

    # Results table
    flow.append(Paragraph("Payment flows", h2))
    data = [["Flow", "Check", "Status", "Evidence"]]
    style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONTSIZE", (0, 0), (-1, -1), 8),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")])]
    for i, r in enumerate(summary.get("results", []), start=1):
        st = r.get("status", "pending")
        data.append([Paragraph(r.get("flow", "") or "—", small),
                     Paragraph(r.get("name", ""), small),
                     Paragraph(STATUS_LABEL.get(st, st.upper()), small),
                     Paragraph(str(r.get("detail", "")), small)])
        style.append(("TEXTCOLOR", (2, i), (2, i), colors.Color(*STATUS_RGB.get(st, (0, 0, 0)))))
    t = Table(data, colWidths=[3 * cm, 4.2 * cm, 2.3 * cm, 7 * cm], repeatRows=1)
    t.setStyle(TableStyle(style))
    flow.append(t)

    # Notes
    if notes:
        flow.append(Paragraph("Notes &amp; next actions", h2))
        for line in notes.splitlines():
            line = line.strip()
            if line:
                flow.append(Paragraph(line.replace("&", "&amp;").replace("<", "&lt;"), body))

    # Screenshots
    if shots_dir and os.path.isdir(shots_dir):
        imgs = sorted(f for f in os.listdir(shots_dir)
                      if f.lower().endswith((".png", ".jpg", ".jpeg")))
        if imgs:
            flow.append(PageBreak())
            flow.append(Paragraph("Customer-experience evidence (Lane B)", h2))
            for fn in imgs:
                path = os.path.join(shots_dir, fn)
                try:
                    from reportlab.lib.utils import ImageReader
                    iw, ih = ImageReader(path).getSize()
                    w = 14 * cm
                    h = w * ih / iw
                    flow.append(Image(path, width=w, height=min(h, 18 * cm)))
                    flow.append(Paragraph(os.path.splitext(fn)[0].replace("_", " "), small))
                    flow.append(Spacer(1, 0.3 * cm))
                except Exception as e:  # noqa: BLE001
                    flow.append(Paragraph(f"[could not embed {fn}: {e}]", small))

    doc.build(flow)
    print(f"PDF written → {out}")


def markdown_fallback(summary, notes, title):
    print(f"# {title}\n")
    c = summary.get("counts", {})
    print(f"App: {summary.get('app','?')} · TEST mode · {date.today().isoformat()}")
    print(f"Summary: {c.get('pass',0)} functional · {c.get('pending',0)} pending · {c.get('fail',0)} broken\n")
    print("| Flow | Check | Status | Evidence |\n|---|---|---|---|")
    for r in summary.get("results", []):
        print(f"| {r.get('flow','')} | {r.get('name','')} | "
              f"{STATUS_LABEL.get(r.get('status'),'')} | {r.get('detail','')} |")
    if notes:
        print("\n## Notes & next actions\n")
        print(notes)
    print("\n> reportlab unavailable — convert this markdown to PDF with the `pdf` skill.", file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser(description="Build the per-app Stripe homologation PDF.")
    p.add_argument("--results", required=True, help="validate.py results JSON")
    p.add_argument("--shots", help="directory of Lane B screenshots")
    p.add_argument("--notes", help="markdown/text file appended as notes & next actions")
    p.add_argument("--out", default="stripe-homologation.pdf")
    p.add_argument("--title", default="Stripe Homologation Report")
    args = p.parse_args()

    summary = json.load(open(args.results, encoding="utf-8"))
    notes = open(args.notes, encoding="utf-8").read() if args.notes and os.path.exists(args.notes) else None
    try:
        build_pdf(summary, args.shots, notes, args.out, args.title)
    except ImportError:
        markdown_fallback(summary, notes, args.title)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
