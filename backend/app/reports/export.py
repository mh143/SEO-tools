"""Exports: CSV, JSON, Markdown and a self-contained printable HTML report.

All crawled content is untrusted: HTML output escapes every value, and CSV cells that start with
formula characters are prefixed to prevent spreadsheet formula injection.
"""

from __future__ import annotations

import csv
import html
import io
import json
from datetime import UTC, datetime

from app.fixes.publisher import faq_html
from app.fixes.types import FIX_TYPES
from app.models import CrawlRun, FixProposal, Issue

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
DISCLAIMER = ("Findings are produced by automated checks and should be reviewed by a person. Scores are internal "
              "heuristics, not an industry standard, and no ranking, traffic or AI-citation outcome is guaranteed.")


def _csv_safe(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def issues_csv(issues: list[Issue]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["severity", "type", "category", "confidence", "rule_id", "title", "url", "description",
                "recommendation", "status", "evidence"])
    for i in sorted(issues, key=lambda x: (SEV_ORDER[x.severity.value], x.rule_id)):
        w.writerow([_csv_safe(x) for x in (i.severity.value, i.finding_type.value, i.category, i.confidence, i.rule_id,
                                           i.title, i.url, i.description, i.recommendation, i.status.value,
                                           json.dumps(i.evidence, ensure_ascii=False)[:2000])])
    return buf.getvalue()


def issues_json(run: CrawlRun, issues: list[Issue]) -> str:
    return json.dumps({
        "generated_at": datetime.now(UTC).isoformat(), "start_url": run.start_url, "crawl_id": str(run.id),
        "status": run.status.value, "summary": run.summary, "disclaimer": DISCLAIMER,
        "issues": [{
            "id": str(i.id), "rule_id": i.rule_id, "category": i.category, "severity": i.severity.value,
            "finding_type": i.finding_type.value, "confidence": i.confidence, "title": i.title, "url": i.url,
            "description": i.description, "why_it_matters": i.why_it_matters, "recommendation": i.recommendation,
            "evidence": i.evidence, "status": i.status.value,
        } for i in sorted(issues, key=lambda x: (SEV_ORDER[x.severity.value], x.rule_id))],
    }, indent=2, ensure_ascii=False, default=str)


def issues_markdown(run: CrawlRun, issues: list[Issue]) -> str:
    lines = [f"# Audit report: {run.start_url}", "", f"Crawl finished: {run.finished_at or '-'}  ",
             f"Pages crawled: {run.pages_crawled}", ""]
    sc = (run.summary or {}).get("scores") or {}
    if sc:
        lines += ["## Heuristic scores", "", "| Technical | Content | AEO | GEO |", "|---|---|---|---|",
                  f"| {sc.get('technical')} | {sc.get('content')} | {sc.get('aeo')} | {sc.get('geo')} |", "",
                  f"_{sc.get('disclaimer', '')}_", ""]
    lines += ["## Findings", ""]
    for i in sorted(issues, key=lambda x: (SEV_ORDER[x.severity.value], x.rule_id)):
        lines += [f"### [{i.severity.value.upper()} · {i.finding_type.value}] {i.title}",
                  f"- URL: {i.url or 'site-wide'}", f"- {i.description}", f"- Why it matters: {i.why_it_matters}",
                  f"- Recommendation: {i.recommendation}", ""]
    lines += ["---", DISCLAIMER]
    return "\n".join(lines)


def report_html(run: CrawlRun, issues: list[Issue], *, company: str | None = None, accent: str = "#2563eb",
                white_label: bool = False, product_name: str = "RankLens") -> str:
    e = html.escape
    sc = (run.summary or {}).get("scores") or {}
    by_sev: dict[str, int] = {}
    for i in issues:
        by_sev[i.severity.value] = by_sev.get(i.severity.value, 0) + 1
    rows = []
    for i in sorted(issues, key=lambda x: (SEV_ORDER[x.severity.value], x.rule_id))[:1000]:
        rows.append(
            f"<tr><td><span class='sev {e(i.severity.value)}'>{e(i.severity.value)}</span><br><small>{e(i.finding_type.value)}</small></td>"
            f"<td><strong>{e(i.title)}</strong><div>{e(i.description)}</div>"
            f"<div class='rec'><b>Recommendation:</b> {e(i.recommendation)}</div></td>"
            f"<td class='url'>{e(i.url or 'site-wide')}</td></tr>")
    brand = e(company) if (white_label and company) else e(product_name)
    accent = accent if (accent.startswith("#") and len(accent) == 7) else "#2563eb"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SEO, AEO &amp; GEO audit – {e(run.start_url)}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#111;margin:32px;}}
h1{{color:{accent};margin-bottom:4px}} .muted{{color:#555}} table{{border-collapse:collapse;width:100%;margin-top:16px}}
td,th{{border-bottom:1px solid #ddd;padding:8px;vertical-align:top;text-align:left;font-size:13px}}
.url{{word-break:break-all;max-width:280px}} .rec{{margin-top:4px;color:#333}}
.sev{{display:inline-block;padding:2px 6px;border-radius:4px;font-size:11px;text-transform:uppercase;font-weight:600}}
.critical{{background:#fee2e2;color:#991b1b}} .high{{background:#ffedd5;color:#9a3412}} .medium{{background:#fef9c3;color:#854d0e}}
.low{{background:#e0f2fe;color:#075985}} .info{{background:#f3f4f6;color:#374151}}
.scores{{display:flex;gap:16px;margin:16px 0}} .score{{border:1px solid #ddd;border-radius:8px;padding:12px 16px;min-width:110px}}
.score b{{font-size:24px;display:block}} @media print{{body{{margin:0}}}}
</style></head><body>
<p class="muted">{brand}</p>
<h1>Website audit: {e(run.start_url)}</h1>
<p class="muted">Crawled {run.pages_crawled} page(s) · finished {e(str(run.finished_at or ''))} · status {e(run.status.value)}</p>
<div class="scores">{''.join(f"<div class='score'><span class='muted'>{e(k.upper())}</span><b>{e(str(sc.get(k, '–')))}</b></div>" for k in ('technical', 'content', 'aeo', 'geo'))}</div>
<p class="muted"><small>{e(sc.get('disclaimer', ''))}</small></p>
<p>{' · '.join(f"{e(k)}: {v}" for k, v in sorted(by_sev.items(), key=lambda kv: SEV_ORDER[kv[0]]))}</p>
<table><thead><tr><th>Severity</th><th>Finding</th><th>URL</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<p class="muted"><small>{e(DISCLAIMER)}</small></p>
</body></html>"""


def fix_instructions(fix: FixProposal) -> str:
    """Plain-text, copy-pasteable instructions for applying a fix manually."""
    spec = FIX_TYPES.get(fix.fix_type)
    a, b = fix.after or {}, fix.before or {}
    lines = [f"Fix: {spec.label if spec else fix.fix_type}", f"URL: {fix.url}", f"Risk: {fix.risk_level}", ""]
    if fix.fix_type == "faq_section":
        lines += ["Add this HTML section to the page content:", "", faq_html(a.get("items", []))]
    elif fix.fix_type == "json_ld":
        lines += ["Add this inside the page <head> (via your theme or SEO plugin):", "",
                  '<script type="application/ld+json">', a.get("json_ld", ""), "</script>"]
    elif fix.fix_type == "canonical":
        lines += ["Ensure the page <head> contains exactly one canonical tag:", "", a.get("html", "")]
    elif fix.fix_type in ("redirect", "broken_link"):
        lines += [f"Create a {a.get('status', 301)} redirect:", f"  from: {a.get('from_url')}", f"  to:   {a.get('to_url')}", "",
                  "Apache (.htaccess):", f"  Redirect 301 {_path(a.get('from_url'))} {a.get('to_url')}", "",
                  "Nginx:", f"  location = {_path(a.get('from_url'))} {{ return 301 {a.get('to_url')}; }}"]
    elif fix.fix_type == "meta_description":
        lines += ["Set the meta description to:", "", a.get("description", ""), "",
                  f'<meta name="description" content="{html.escape(a.get("description", ""), quote=True)}">']
    else:
        lines += ["Before:", json.dumps(b, indent=2, ensure_ascii=False), "", "After:", json.dumps(a, indent=2, ensure_ascii=False)]
    if fix.verification_steps:
        lines += ["", "Verify:"] + [f"  - {s}" for s in fix.verification_steps]
    return "\n".join(lines)


def _path(url: str | None) -> str:
    from urllib.parse import urlsplit

    p = urlsplit(url or "")
    return p.path or "/"


def fixes_json(fixes: list[FixProposal]) -> str:
    return json.dumps([{
        "id": str(f.id), "url": f.url, "fix_type": f.fix_type, "status": f.status.value, "generator": f.generator,
        "risk_level": f.risk_level, "confidence": f.confidence, "before": f.before, "after": f.after,
        "rationale": f.rationale, "verification_steps": f.verification_steps, "instructions": fix_instructions(f),
    } for f in fixes], indent=2, ensure_ascii=False, default=str)


def fixes_csv(fixes: list[FixProposal]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["url", "fix_type", "status", "generator", "risk", "before", "after", "rationale"])
    for f in fixes:
        w.writerow([_csv_safe(x) for x in (f.url, f.fix_type, f.status.value, f.generator, f.risk_level,
                                           json.dumps(f.before, ensure_ascii=False), json.dumps(f.after, ensure_ascii=False),
                                           f.rationale)])
    return buf.getvalue()
