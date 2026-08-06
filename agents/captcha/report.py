#!/usr/bin/env python
# /// script
# requires-python = ">=3.11"
# dependencies = ["reportlab>=4"]
# ///
"""
report.py — build the per-app captcha PDF from captcha_check.py results + screenshots.

The PDF is the owner-facing deliverable: every protected form marked ✅ enforced (server-side
verification fails closed) / ⚠️ widget-only (rendered but not gated, or only partially proven) /
❌ missing, with the provider test-key matrix, the Lane B browser screenshots, and a pending /
next-actions section. Save it UNDER THE TARGET PROJECT (its brain/docs), never in agentes_perdidos.

Usage:
  uv run agents/captcha/report.py --results results.json --shots ./shots \
        --out my-app-captcha.pdf --title "My App — CAPTCHA Enforcement" --notes notes.md

  --shots  a directory of PNG/JPG screenshots; filenames become captions (sorted). Optional.
  --notes  a markdown/plain-text file appended as "Notes & next actions". Optional.

If reportlab can't be installed, fall back to the `pdf` skill: this script prints the same content
as markdown to stdout so it can be converted there.
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

# Per-check status → label (verdict). The PDF translates results into the SKILL's ✅/⚠️/❌ vocabulary.
STATUS_LABEL = {"pass": "ENFORCED", "fail": "OPEN / BROKEN", "pending": "PENDING"}
STATUS_ICON = {"pass": "✅", "fail": "❌", "pending": "⚠️"}
STATUS_RGB = {"pass": (0.13, 0.55, 0.13), "fail": (0.75, 0.16, 0.16), "pending": (0.78, 0.55, 0.0)}


def _verdict_per_endpoint(results: list[dict]) -> dict:
    """Roll per-check rows up into a per-endpoint (form) verdict using the SKILL vocabulary.

    ✅ enforced   = the missing-token gate PASSED (form fails closed).
    ❌ missing    = the missing-token gate FAILED (request accepted without a token — open gate).
    ⚠️ widget-only = the gate could not be proven (pending: app not reached / not configured).
    """
    by_ep: dict[str, list[dict]] = {}
    for r in results:
        if not r.get("check", "").startswith("app-gate"):
            continue
        by_ep.setdefault(r.get("target", "?"), []).append(r)
    verdicts = {}
    for ep, rows in by_ep.items():
        missing = next((x for x in rows if x["check"] == "app-gate-missing-token"), None)
        if missing and missing["status"] == "pass":
            verdicts[ep] = ("pass", "enforced (fails closed without a token)")
        elif missing and missing["status"] == "fail":
            verdicts[ep] = ("fail", "OPEN — accepted a request with no captcha token")
        else:
            verdicts[ep] = ("pending", "widget-only / unproven (app not reached or not configured)")
    return verdicts


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

    results = summary.get("results", [])
    counts = {k: sum(1 for r in results if r.get("status") == k) for k in ("pass", "fail", "pending")}

    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm, title=title)
    flow = []
    flow.append(Paragraph(title, h1))
    sub = (f"App: <b>{summary.get('app', '?')}</b> &nbsp;·&nbsp; Provider: "
           f"<b>{summary.get('provider', '?')}</b> &nbsp;·&nbsp; {date.today().isoformat()}")
    flow.append(Paragraph(sub, body))
    flow.append(Paragraph(
        f"Summary: <b>{counts['pass']}</b> pass · <b>{counts['pending']}</b> pending · "
        f"<b>{counts['fail']}</b> fail.", body))
    flow.append(Paragraph("Validated Lane A with the provider's <b>TEST keys</b> (deterministic, "
                          "no human solving). The gate must fail CLOSED.", small))
    flow.append(Spacer(1, 0.4 * cm))

    # Per-form verdict (the headline: ✅ enforced / ⚠️ widget-only / ❌ missing).
    verdicts = _verdict_per_endpoint(results)
    if verdicts:
        flow.append(Paragraph("Protected forms — verdict", h2))
        data = [["Form / endpoint", "Verdict", "Why"]]
        style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                 ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                 ("FONTSIZE", (0, 0), (-1, -1), 8),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                 ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")])]
        for i, (ep, (st, why)) in enumerate(sorted(verdicts.items()), start=1):
            label = f"{STATUS_ICON.get(st, '')} {STATUS_LABEL.get(st, st.upper())}"
            data.append([Paragraph(ep, small), Paragraph(label, small), Paragraph(why, small)])
            style.append(("TEXTCOLOR", (1, i), (1, i), colors.Color(*STATUS_RGB.get(st, (0, 0, 0)))))
        t = Table(data, colWidths=[5.5 * cm, 4 * cm, 7 * cm], repeatRows=1)
        t.setStyle(TableStyle(style))
        flow.append(t)

    # Provider test-key matrix.
    contract = [r for r in results if r.get("check") == "provider-contract"]
    if contract:
        flow.append(Paragraph("Provider test-key matrix (siteverify contract)", h2))
        data = [["Case", "Status", "Result"]]
        style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                 ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                 ("FONTSIZE", (0, 0), (-1, -1), 8),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                 ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")])]
        for i, r in enumerate(contract, start=1):
            st = r.get("status", "pending")
            data.append([Paragraph(r.get("target", ""), small),
                         Paragraph(STATUS_LABEL.get(st, st.upper()), small),
                         Paragraph(str(r.get("detail", "")), small)])
            style.append(("TEXTCOLOR", (1, i), (1, i), colors.Color(*STATUS_RGB.get(st, (0, 0, 0)))))
        t = Table(data, colWidths=[6.5 * cm, 2.3 * cm, 7.7 * cm], repeatRows=1)
        t.setStyle(TableStyle(style))
        flow.append(t)

    # Full per-check detail (every app-gate row).
    gate = [r for r in results if r.get("check", "").startswith("app-gate")]
    if gate:
        flow.append(Paragraph("App-gate checks (fail-closed detail)", h2))
        data = [["Check", "Target", "Status", "HTTP", "Detail"]]
        style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                 ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                 ("FONTSIZE", (0, 0), (-1, -1), 8),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                 ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")])]
        for i, r in enumerate(gate, start=1):
            st = r.get("status", "pending")
            code = r.get("http_code")
            data.append([Paragraph(r.get("check", ""), small),
                         Paragraph(r.get("target", ""), small),
                         Paragraph(STATUS_LABEL.get(st, st.upper()), small),
                         Paragraph(str(code) if code is not None else "—", small),
                         Paragraph(str(r.get("detail", "")), small)])
            style.append(("TEXTCOLOR", (2, i), (2, i), colors.Color(*STATUS_RGB.get(st, (0, 0, 0)))))
        t = Table(data, colWidths=[3.6 * cm, 3.4 * cm, 2.6 * cm, 1.4 * cm, 5.5 * cm], repeatRows=1)
        t.setStyle(TableStyle(style))
        flow.append(t)

    # Pending / next actions (from results + notes file).
    flow.append(Paragraph("Pending &amp; next actions", h2))
    pend = [r for r in results if r.get("status") == "pending"]
    if pend:
        for r in pend:
            flow.append(Paragraph(
                f"⚠️ {r.get('check', '')} · {r.get('target', '')}: "
                f"{str(r.get('detail', '')).replace('&', '&amp;').replace('<', '&lt;')}", body))
    if any(r.get("status") == "fail" and r.get("check", "").startswith("app-gate") for r in results):
        flow.append(Paragraph("❌ CRITICAL: a protected form accepted a request with no captcha "
                              "token. Add/enforce the server-side siteverify gate BEFORE the action "
                              "and fail closed.", body))
    if notes:
        for line in notes.splitlines():
            line = line.strip()
            if line:
                flow.append(Paragraph(line.replace("&", "&amp;").replace("<", "&lt;"), body))
    if not pend and not notes:
        flow.append(Paragraph("None — all checks resolved.", body))

    # Screenshots (Lane B browser evidence).
    if shots_dir and os.path.isdir(shots_dir):
        imgs = sorted(f for f in os.listdir(shots_dir)
                      if f.lower().endswith((".png", ".jpg", ".jpeg")))
        if imgs:
            flow.append(PageBreak())
            flow.append(Paragraph("Live-form evidence (Lane B)", h2))
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
    results = summary.get("results", [])
    c = {k: sum(1 for r in results if r.get("status") == k) for k in ("pass", "fail", "pending")}
    print(f"# {title}\n")
    print(f"App: {summary.get('app','?')} · Provider: {summary.get('provider','?')} · "
          f"{date.today().isoformat()}")
    print(f"Summary: {c['pass']} pass · {c['pending']} pending · {c['fail']} fail\n")

    verdicts = _verdict_per_endpoint(results)
    if verdicts:
        print("## Protected forms — verdict\n")
        print("| Form / endpoint | Verdict | Why |\n|---|---|---|")
        for ep, (st, why) in sorted(verdicts.items()):
            print(f"| {ep} | {STATUS_ICON.get(st,'')} {STATUS_LABEL.get(st, st.upper())} | {why} |")
        print()

    print("## Provider test-key matrix\n")
    print("| Case | Status | Result |\n|---|---|---|")
    for r in results:
        if r.get("check") == "provider-contract":
            print(f"| {r.get('target','')} | {STATUS_LABEL.get(r.get('status'),'')} | "
                  f"{r.get('detail','')} |")

    print("\n## App-gate checks\n")
    print("| Check | Target | Status | HTTP | Detail |\n|---|---|---|---|---|")
    for r in results:
        if r.get("check", "").startswith("app-gate"):
            code = r.get("http_code")
            print(f"| {r.get('check','')} | {r.get('target','')} | "
                  f"{STATUS_LABEL.get(r.get('status'),'')} | "
                  f"{code if code is not None else '—'} | {r.get('detail','')} |")

    print("\n## Pending & next actions\n")
    for r in results:
        if r.get("status") == "pending":
            print(f"- ⚠️ {r.get('check','')} · {r.get('target','')}: {r.get('detail','')}")
    if any(r.get("status") == "fail" and r.get("check", "").startswith("app-gate") for r in results):
        print("- ❌ CRITICAL: a protected form accepted a request with no captcha token — "
              "enforce the server-side siteverify gate before the action and fail closed.")
    if notes:
        print(f"\n{notes}")
    print("\n> reportlab unavailable — convert this markdown to PDF with the `pdf` skill.",
          file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser(description="Build the per-app captcha enforcement PDF.")
    p.add_argument("--results", required=True, help="captcha_check.py results JSON")
    p.add_argument("--shots", help="directory of Lane B screenshots")
    p.add_argument("--notes", help="markdown/text file appended as notes & next actions")
    p.add_argument("--out", default="captcha-report.pdf")
    p.add_argument("--title", default="CAPTCHA Enforcement Report")
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
