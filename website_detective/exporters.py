from __future__ import annotations
import base64, csv, html, io, json
from collections import Counter
from .models import AuditResult, CATEGORIES, SEVERITIES

SEV_COLOR = {"High": "#d64545", "Medium": "#e8a23a", "Low": "#4a90c2", "Info": "#8a94a3"}
DISCLAIMER = ("This report is a passive technical review based on publicly served pages and headers. "
              "It is not a penetration test or a security certification. Scores are a heuristic summary "
              "for this tool only and are not a prediction of search ranking or user outcomes.")
SEV_ORDER = {s: n for n, s in enumerate(SEVERITIES)}


def sorted_issues(issues):
    return sorted(issues, key=lambda i: (SEV_ORDER.get(i.severity, 9), i.title, i.url))


def grouped(issues):
    """Collapse repeated (category,title) into one entry listing affected URLs for compact reports."""
    g: dict[tuple, list] = {}
    for i in sorted_issues(issues):
        g.setdefault((i.category, i.title), []).append(i)
    return g


# ---------------------------------------------------------------- charts
def score_chart_png(result: AuditResult) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cats = CATEGORIES
    vals = [result.scores.get(c, 0) for c in cats]
    colors = ["#2e9e5b" if v >= 80 else "#e8a23a" if v >= 60 else "#d64545" for v in vals]
    fig, ax = plt.subplots(figsize=(6, 3), dpi=130)
    ax.barh(cats[::-1], vals[::-1], color=colors[::-1])
    ax.set_xlim(0, 100)
    for y, v in enumerate(vals[::-1]):
        ax.text(v + 1, y, str(v), va="center", fontsize=8)
    ax.set_title("Category scores (heuristic)", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png"); plt.close(fig)
    return buf.getvalue()


def severity_chart_png(result: AuditResult) -> bytes:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    bottoms = np.zeros(len(CATEGORIES))
    fig, ax = plt.subplots(figsize=(6, 3), dpi=130)
    for sev in SEVERITIES:
        counts = np.array([sum(1 for i in result.by_category(c) if i.severity == sev) for c in CATEGORIES])
        ax.bar(range(len(CATEGORIES)), counts, bottom=bottoms, label=sev, color=SEV_COLOR[sev])
        bottoms += counts
    ax.set_xticks(range(len(CATEGORIES)))
    ax.set_xticklabels([c.replace(" ", "\n") for c in CATEGORIES], fontsize=7)
    ax.set_title("Issues by category and severity", fontsize=10)
    ax.legend(fontsize=7, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png"); plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------- JSON / CSV
def export_json(result: AuditResult, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)


def _csv_safe(v: str) -> str:
    """Neutralise spreadsheet formula injection from page-controlled text."""
    v = str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def export_csv(result: AuditResult, path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["Category", "Severity", "Issue", "URL", "Why it matters", "Evidence", "Suggested improvement"])
        for i in sorted_issues(result.issues):
            w.writerow([i.category, i.severity, _csv_safe(i.title), _csv_safe(i.url), i.why,
                        _csv_safe(i.evidence), i.suggestion])


# ---------------------------------------------------------------- HTML
def export_html(result: AuditResult, path: str) -> None:
    e = html.escape
    img = lambda b: "data:image/png;base64," + base64.b64encode(b).decode()
    try:
        charts = (f'<img src="{img(score_chart_png(result))}" alt="Category scores chart">'
                  f'<img src="{img(severity_chart_png(result))}" alt="Issues by severity chart">')
    except Exception:
        charts = ""
    sev_counts = Counter(i.severity for i in result.issues)
    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Website Audit - {e(result.domain)}</title><style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f6f9;color:#1d2530}}
main{{max-width:1000px;margin:auto;padding:24px}}h1{{margin-bottom:0}}h2{{border-bottom:2px solid #dde3ea;padding-bottom:4px;margin-top:36px}}
.cards{{display:flex;flex-wrap:wrap;gap:12px}}.card{{background:#fff;border-radius:8px;padding:12px 16px;min-width:140px;box-shadow:0 1px 3px #0002}}
.card b{{display:block;font-size:22px}}.charts img{{max-width:100%;width:480px;background:#fff;border-radius:8px;margin:6px}}
table{{border-collapse:collapse;width:100%;background:#fff}}td,th{{border:1px solid #dde3ea;padding:6px 8px;font-size:13px;text-align:left;vertical-align:top}}th{{background:#eef1f5}}
.issue{{background:#fff;border-left:5px solid #888;border-radius:6px;padding:10px 14px;margin:10px 0}}.issue h3{{margin:0 0 6px;font-size:15px}}
.issue dt{{font-weight:600;margin-top:6px}}.issue dd{{margin:0;word-break:break-word}}.note{{font-size:12px;color:#5b6675}}
</style></head><body><main>
<h1>WEBSITE AUDIT</h1><p>{e(result.domain)} &middot; {e(result.started_at)}</p>
<h2>Overall findings</h2><div class="cards">
<div class="card">Overall score<b>{result.scores.get('Overall', 0)}</b></div>
<div class="card">Pages scanned<b>{len(result.pages)}</b></div>
<div class="card">Issues found<b>{len(result.issues)}</b></div>
<div class="card">Scan duration<b>{result.duration_s:.1f}s</b></div>
<div class="card">High / Medium / Low<b>{sev_counts['High']} / {sev_counts['Medium']} / {sev_counts['Low']}</b></div></div>
<div class="charts">{charts}</div>
<p class="note">{e(DISCLAIMER)}</p>
{'<p class="note"><b>Scan was cancelled before completion.</b></p>' if result.cancelled else ''}"""]
    for cat in CATEGORIES:
        iss = result.by_category(cat)
        parts.append(f"<h2>{e(cat)} &mdash; score {result.scores.get(cat, 0)} ({len(iss)} findings)</h2>")
        if not iss:
            parts.append("<p>No issues detected by this tool's checks.</p>")
        for i in sorted_issues(iss):
            parts.append(f'<div class="issue" style="border-color:{SEV_COLOR[i.severity]}"><h3>{e(i.title)} <small>[{e(i.severity)}]</small></h3><dl>'
                         f"<dt>URL</dt><dd>{e(i.url)}</dd><dt>Why it matters</dt><dd>{e(i.why)}</dd>"
                         f"<dt>Evidence</dt><dd>{e(i.evidence)}</dd><dt>Suggested improvement</dt><dd>{e(i.suggestion)}</dd></dl></div>")
    parts.append("<h2>Pages scanned</h2><table><tr><th>URL</th><th>Status</th><th>Time (ms)</th><th>HTML KB</th><th>Resources</th><th>Title</th></tr>")
    for p in result.pages:
        parts.append(f"<tr><td>{e(p.url)}</td><td>{p.status or e(p.error[:40])}</td><td>{p.response_time_ms:.0f}</td><td>{p.html_bytes / 1024:.1f}</td><td>{p.resource_count}</td><td>{e(p.title[:70])}</td></tr>")
    parts.append("</table></main></body></html>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(parts))


# ---------------------------------------------------------------- PDF
def export_pdf(result: AuditResult, path: str, max_issues_per_category: int = 60) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, KeepTogether

    ss = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=ss["BodyText"], fontSize=8, leading=10)
    cell = ParagraphStyle("cell", parent=ss["BodyText"], fontSize=8, leading=9.5)
    esc = lambda s: html.escape(str(s))
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Website Audit - {result.domain}", author="Website Detective")
    W = A4[0] - 32 * mm
    st = [Paragraph("WEBSITE AUDIT", ss["Title"]), Paragraph(f"{esc(result.domain)} &middot; {esc(result.started_at)}", ss["Normal"]), Spacer(1, 8),
          Paragraph("Overall findings", ss["Heading2"])]
    summary = [["Overall score", "Pages scanned", "Issues", "Duration"],
               [result.scores.get("Overall", 0), len(result.pages), len(result.issues), f"{result.duration_s:.1f}s"]]
    t = Table(summary, colWidths=[W / 4] * 4)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                           ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONTSIZE", (0, 1), (-1, 1), 14)]))
    st += [t, Spacer(1, 8)]
    try:
        st.append(Image(io.BytesIO(score_chart_png(result)), width=W * 0.8, height=W * 0.4))
        st.append(Image(io.BytesIO(severity_chart_png(result)), width=W * 0.8, height=W * 0.4))
    except Exception:
        pass
    st += [Paragraph(esc(DISCLAIMER), small)]
    if result.cancelled:
        st.append(Paragraph("<b>The scan was cancelled before completion.</b>", small))
    for cat in CATEGORIES:
        iss = sorted_issues(result.by_category(cat))
        st += [PageBreak() if cat == CATEGORIES[0] else Spacer(1, 10),
               Paragraph(f"{esc(cat)} &mdash; score {result.scores.get(cat, 0)} ({len(iss)} findings)", ss["Heading2"])]
        if not iss:
            st.append(Paragraph("No issues detected by this tool's checks.", ss["Normal"]))
        for i in iss[:max_issues_per_category]:
            rows = [[Paragraph(f"<b>{esc(i.title)}</b> [{esc(i.severity)}]", cell), ""],
                    ["URL", Paragraph(esc(i.url), cell)], ["Why it matters", Paragraph(esc(i.why), cell)],
                    ["Evidence", Paragraph(esc(i.evidence), cell)], ["Suggested improvement", Paragraph(esc(i.suggestion), cell)]]
            tb = Table(rows, colWidths=[32 * mm, W - 32 * mm])
            tb.setStyle(TableStyle([("SPAN", (0, 0), (1, 0)), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(SEV_COLOR[i.severity])),
                                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                                    ("FONTSIZE", (0, 1), (0, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            st += [KeepTogether([tb]), Spacer(1, 4)]
        if len(iss) > max_issues_per_category:
            st.append(Paragraph(f"… {len(iss) - max_issues_per_category} more findings in this category. See the HTML/JSON/CSV export for the full list.", small))
    st += [PageBreak(), Paragraph("Pages scanned", ss["Heading2"])]
    rows = [["URL", "Status", "ms", "HTML KB", "Title"]]
    for p in result.pages:
        rows.append([Paragraph(esc(p.url[:90]), cell), p.status or "err", f"{p.response_time_ms:.0f}", f"{p.html_bytes / 1024:.1f}", Paragraph(esc(p.title[:50]), cell)])
    pt = Table(rows, colWidths=[W * .42, W * .09, W * .08, W * .11, W * .30], repeatRows=1)
    pt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef1f5")), ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    st.append(pt)
    doc.build(st)


EXPORTERS = {"pdf": export_pdf, "html": export_html, "json": export_json, "csv": export_csv}
