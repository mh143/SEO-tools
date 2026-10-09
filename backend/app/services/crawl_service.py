from __future__ import annotations

import asyncio
import gzip
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit.engine import PageData, SiteContext, run_rules, scores
from app.billing import entitlements
from app.billing.plans import Plan
from app.core.config import get_settings
from app.core.db import db_session
from app.crawler.crawler import CrawlConfig, CrawlOutput, crawl
from app.crawler.robots import Robots
from app.models import (
    CrawlRun,
    CrawlStatus,
    FixProposal,
    FixStatus,
    Issue,
    IssueStatus,
    Notification,
    Page,
    PageSnapshot,
    Website,
)

log = logging.getLogger(__name__)


def crawl_settings_for(plan: Plan, website: Website | None, requested: dict | None = None) -> dict:
    requested = requested or {}
    ws = (website.crawl_settings if website else {}) or {}
    max_pages = min(int(requested.get("max_pages") or ws.get("max_pages") or plan.max_pages_per_crawl), plan.max_pages_per_crawl)
    max_depth = min(int(requested.get("max_depth") or ws.get("max_depth") or plan.max_depth), plan.max_depth)
    render = bool(requested.get("render_js", ws.get("render_js", False))) and plan.js_rendering
    return {"max_pages": max_pages, "max_depth": max_depth, "render_js": render}


def create_run(db: Session, *, website: Website, user_id: uuid.UUID | None, trigger: str,
               requested: dict | None = None) -> CrawlRun:
    """Create a queued crawl run after checking entitlements (caller commits and enqueues)."""
    running = db.scalar(select(CrawlRun).where(
        CrawlRun.website_id == website.id, CrawlRun.status.in_([CrawlStatus.queued, CrawlStatus.running])))
    if running:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="A crawl is already in progress for this website.")
    plan = entitlements.effective_plan(db, website.org_id)
    if (requested or {}).get("render_js") and not plan.js_rendering:
        entitlements.require_feature(db, website.org_id, "js_rendering")
    entitlements.consume(db, website.org_id, "crawl_runs", 1, {"website_id": str(website.id)})
    run = CrawlRun(org_id=website.org_id, website_id=website.id, start_url=website.root_url, status=CrawlStatus.queued,
                   trigger=trigger, settings=crawl_settings_for(plan, website, requested), created_by=user_id)
    db.add(run)
    db.flush()
    return run


# ------------------------------------------------------------------ execution
def _page_data(out: CrawlOutput) -> list[PageData]:
    sitemap_urls = set(out.sitemap.urls)
    pages = []
    for url, pr in out.pages.items():
        f = pr.fetch
        pages.append(PageData(
            url=url,
            final_url=(f.final_url if f else url),
            status=(f.status_code if f else None),
            depth=pr.depth,
            content_type=(f.content_type if f else ""),
            headers=(f.headers if f else {}),
            redirect_chain=(f.redirect_chain if f else []),
            extracted=pr.extracted,
            error=(f.error if f else None),
            error_kind=(f.error_kind if f else None),
            robots_blocked=pr.robots_blocked,
            confirmed_error=pr.confirmed_error,
            response_ms=(f.elapsed_ms if f else 0),
            in_sitemap=url in sitemap_urls,
        ))
    return pages


def build_context(out: CrawlOutput) -> SiteContext:
    return SiteContext(
        start_url=out.resolved_start_url or out.start_url, root_host=out.root_host, pages=_page_data(out),
        sitemap={"sitemaps": out.sitemap.sitemaps, "urls": out.sitemap.urls, "errors": out.sitemap.errors},
        robots=out.robots or Robots(), robots_status=out.robots_status, robots_error=out.robots_error,
        inlinks=out.inlinks, llms_txt=out.llms_txt, limit_reached=out.limit_reached,
    )


def _make_renderer(settings: dict):
    if not settings.get("render_js") or not get_settings().rendering_enabled:
        return None
    try:
        from app.crawler.renderer import Renderer

        return Renderer()
    except Exception:  # pragma: no cover - playwright missing
        log.warning("Rendering requested but Playwright is unavailable")
        return None


def execute_run(run_id: uuid.UUID) -> None:
    """Run a crawl + audit. Safe to call from a Celery worker or a background thread."""
    with db_session() as db:
        run = db.get(CrawlRun, run_id)
        if run is None or run.status not in (CrawlStatus.queued,):
            return
        run.status = CrawlStatus.running
        run.started_at = datetime.now(UTC)
        settings = dict(run.settings)
        start_url = run.start_url

    last_update = [0.0]

    def on_progress(out: CrawlOutput, discovered: int) -> None:
        now = time.monotonic()
        if now - last_update[0] < 1.0:
            return
        last_update[0] = now
        crawled = sum(1 for p in out.pages.values() if p.fetch is not None)
        # Fetch failures only; HTTP 4xx/5xx responses are audit findings, not crawl failures.
        failed = sum(1 for p in out.pages.values() if p.fetch and p.fetch.error)
        with db_session() as db:
            db.execute(update(CrawlRun).where(CrawlRun.id == run_id).values(
                pages_crawled=crawled, pages_discovered=discovered, pages_failed=failed))

    def should_cancel() -> bool:
        with db_session() as db:
            st = db.scalar(select(CrawlRun.status).where(CrawlRun.id == run_id))
            return st == CrawlStatus.cancelled

    renderer = _make_renderer(settings)
    try:
        cfg = CrawlConfig(start_url=start_url, max_pages=settings.get("max_pages", 25),
                          max_depth=settings.get("max_depth", 3), render_js=bool(renderer))
        out = asyncio.run(_crawl_with_renderer(cfg, on_progress, should_cancel, renderer))
    except Exception as exc:
        log.exception("crawl failed")
        with db_session() as db:
            run = db.get(CrawlRun, run_id)
            run.status = CrawlStatus.failed
            run.error = f"Crawler error: {type(exc).__name__}"
            run.finished_at = datetime.now(UTC)
        return
    persist_results(run_id, out)


async def _crawl_with_renderer(cfg, on_progress, should_cancel, renderer):
    if renderer is None:
        return await crawl(cfg, on_progress=on_progress, should_cancel=should_cancel)
    async with renderer:
        return await crawl(cfg, on_progress=on_progress, should_cancel=should_cancel, renderer=renderer)


def persist_results(run_id: uuid.UUID, out: CrawlOutput) -> None:
    with db_session() as db:
        run = db.get(CrawlRun, run_id)
        if run is None:
            return
        if run.status == CrawlStatus.cancelled:
            run.finished_at = datetime.now(UTC)
            return
        run.finished_at = datetime.now(UTC)
        if out.fatal_error:
            run.status = CrawlStatus.failed
            run.error = out.fatal_error
            return
        ctx = build_context(out)
        page_rows: dict[str, Page] = {}
        snapshot_retention = get_settings().snapshot_retention_days
        for pd in ctx.pages:
            pr = out.pages[pd.url]
            ex = pd.extracted or {}
            row = Page(
                org_id=run.org_id, crawl_run_id=run.id, url=pd.url[:2048], final_url=pd.final_url[:2048],
                status_code=pd.status, depth=pd.depth, content_type=pd.content_type[:200] or None,
                response_time_ms=pd.response_ms, redirect_chain=pd.redirect_chain,
                title=ex.get("title"), meta_description=ex.get("meta_description"),
                canonical=(pd.canonical or None) and pd.canonical[:2048], h1=(ex.get("h1s") or [None])[0],
                word_count=ex.get("word_count"), content_hash=ex.get("content_hash"),
                indexable=pd.indexable if pd.is_html else None, in_sitemap=pd.in_sitemap,
                inbound_links=len({x["source"] for x in out.inlinks.get(pd.url, [])}),
                rendered=pr.rendered, extracted=_trim_extracted(ex), error=pd.error or ("Blocked by robots.txt" if pd.robots_blocked else None),
                fetched_at=datetime.now(UTC),
            )
            db.add(row)
            page_rows[pd.url] = row
            if pr.html and snapshot_retention > 0:
                db.flush()
                db.add(PageSnapshot(org_id=run.org_id, page_id=row.id, html_gz=gzip.compress(pr.html.encode()[:3_000_000]),
                                    headers={k: v for k, v in pd.headers.items() if k in (
                                        "content-type", "x-robots-tag", "link", "cache-control", "last-modified",
                                        "server", "content-language")}))
        db.flush()

        findings = run_rules(ctx)
        site_key = str(run.website_id or ctx.root_host)
        prev_status = _previous_issue_states(db, run)
        verified_fps = _verified_fix_fingerprints(db, run)
        counts = {"error": 0, "warning": 0, "recommendation": 0, "info": 0}
        sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        regressions = []
        for f in findings:
            fp = f.fingerprint(site_key)
            status = IssueStatus.open
            if prev_status.get(fp) == IssueStatus.ignored:
                status = IssueStatus.ignored
            elif fp in verified_fps:
                status = IssueStatus.regressed
                regressions.append(f)
            page = page_rows.get(f.url) if f.url else None
            db.add(Issue(
                org_id=run.org_id, crawl_run_id=run.id, website_id=run.website_id, page_id=page.id if page else None,
                url=f.url, rule_id=f.rule_id, category=f.category, severity=f.severity, finding_type=f.finding_type,
                confidence=f.confidence, title=f.title[:300], description=f.description, why_it_matters=f.why_it_matters,
                recommendation=f.recommendation, evidence=_json_safe(f.evidence), fix_type=f.fix_type, fingerprint=fp,
                status=status, source="rule",
            ))
            counts[f.finding_type] = counts.get(f.finding_type, 0) + 1
            sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1

        # Per-page scores for the dashboard
        sc = scores(ctx, findings)
        crawled = sum(1 for p in ctx.pages if p.status is not None)
        failed = sum(1 for p in ctx.pages if p.error and not p.robots_blocked)
        run.pages_crawled = crawled
        run.pages_failed = failed
        run.pages_discovered = max(run.pages_discovered, len(ctx.pages))
        run.pages_rendered = out.rendered_count
        run.site_data = {
            "resolved_start_url": out.resolved_start_url,
            "root_host": out.root_host,
            "robots": {"status": out.robots_status, "error": out.robots_error, "sitemaps": out.robots.sitemaps,
                       "raw": (out.robots.raw or "")[:20000]},
            "sitemaps": out.sitemap.sitemaps,
            "sitemap_url_count": len(out.sitemap.urls),
            "llms_txt": out.llms_txt,
        }
        new_fps = {f.fingerprint(site_key) for f in findings}
        resolved_count = sum(1 for fp, st in prev_status.items() if fp not in new_fps and st != IssueStatus.ignored)
        new_count = sum(1 for fp in new_fps if fp not in prev_status)
        run.summary = {
            "scores": sc,
            "by_type": counts,
            "by_severity": sev_counts,
            "issue_count": len(findings),
            "limit_reached": out.limit_reached,
            "diff": {"new": new_count, "resolved": resolved_count, "regressed": len(regressions),
                     "has_previous": bool(prev_status)},
        }
        run.status = CrawlStatus.partial if (out.limit_reached or failed or out.cancelled) else CrawlStatus.completed
        if out.robots_error and out.robots.disallow_all:
            run.status = CrawlStatus.partial
            run.error = out.robots_error

        if run.org_id:
            entitlements.record(db, run.org_id, "crawled_pages", crawled, {"crawl_run_id": str(run.id)})
            entitlements.record(db, run.org_id, "rendered_pages", out.rendered_count, {"crawl_run_id": str(run.id)})
            _mark_previous_issue_states(db, run, new_fps)
            if regressions or (run.trigger == "scheduled" and new_count):
                db.add(Notification(
                    org_id=run.org_id, website_id=run.website_id, kind="regression" if regressions else "new_issues",
                    title=(f"{len(regressions)} previously fixed issue(s) reappeared" if regressions
                           else f"{new_count} new issue(s) found in scheduled audit"),
                    body="; ".join(f"{f.title} — {f.url or 'site-wide'}" for f in regressions[:5]),
                    data={"crawl_run_id": str(run.id)},
                ))
                from app.services.notify import send_alert_email

                send_alert_email(db, run.org_id, run, regressions, new_count)


def _previous_run(db: Session, run: CrawlRun) -> CrawlRun | None:
    if not run.website_id:
        return None
    return db.scalar(
        select(CrawlRun).where(CrawlRun.website_id == run.website_id, CrawlRun.id != run.id,
                               CrawlRun.status.in_([CrawlStatus.completed, CrawlStatus.partial]),
                               CrawlRun.created_at < run.created_at)
        .order_by(CrawlRun.created_at.desc()).limit(1))


def _previous_issue_states(db: Session, run: CrawlRun) -> dict[str, IssueStatus]:
    prev = _previous_run(db, run)
    if not prev:
        return {}
    return {fp: st for fp, st in db.execute(select(Issue.fingerprint, Issue.status).where(Issue.crawl_run_id == prev.id))}


def _mark_previous_issue_states(db: Session, run: CrawlRun, new_fps: set[str]) -> None:
    prev = _previous_run(db, run)
    if not prev:
        return
    for issue in db.scalars(select(Issue).where(Issue.crawl_run_id == prev.id, Issue.status == IssueStatus.open)):
        if issue.fingerprint not in new_fps:
            issue.status = IssueStatus.fixed


def _verified_fix_fingerprints(db: Session, run: CrawlRun) -> set[str]:
    if not run.website_id:
        return set()
    rows = db.execute(
        select(Issue.fingerprint).join(FixProposal, FixProposal.issue_id == Issue.id)
        .where(FixProposal.website_id == run.website_id, FixProposal.status == FixStatus.verified)
    ).all()
    return {r[0] for r in rows}


def _trim_extracted(ex: dict) -> dict:
    ex = dict(ex)
    ex["main_text"] = (ex.get("main_text") or "")[:20000]
    ex["links"] = (ex.get("links") or [])[:500]
    ex["paragraphs"] = (ex.get("paragraphs") or [])[:150]
    return ex


def _json_safe(v):
    import json

    return json.loads(json.dumps(v, default=str))


def cleanup_stale_runs(max_age_hours: int = 6) -> int:
    """Mark runs stuck in running/queued (e.g. worker crash) as failed."""
    cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
    with db_session() as db:
        res = db.execute(update(CrawlRun).where(
            CrawlRun.status.in_([CrawlStatus.queued, CrawlStatus.running]), CrawlRun.created_at < cutoff
        ).values(status=CrawlStatus.failed, error="Crawl did not finish (worker timeout).", finished_at=datetime.now(UTC)))
        return res.rowcount or 0
