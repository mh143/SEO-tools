from __future__ import annotations

import gzip
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import OrgAccess, OrgContext, scoped_get
from app.api.serializers import crawl_out, fix_out, issue_out, page_out
from app.core import audit
from app.core.db import get_db
from app.models import (
    CrawlRun,
    CrawlStatus,
    FindingType,
    FixProposal,
    Issue,
    IssueStatus,
    Page,
    PageSnapshot,
    Role,
    Severity,
)

router = APIRouter(prefix="/orgs/{org_id}", tags=["crawls"])

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


@router.get("/crawls/{crawl_id}")
def get_crawl(crawl_id: uuid.UUID, o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    run = scoped_get(db, CrawlRun, crawl_id, o.org_id)
    data = crawl_out(run)
    data["site_data"] = run.site_data or {}
    return data


@router.post("/crawls/{crawl_id}/cancel")
def cancel_crawl(crawl_id: uuid.UUID, request: Request, o: OrgContext = Depends(OrgAccess(Role.editor)),
                 db: Session = Depends(get_db)):
    run = scoped_get(db, CrawlRun, crawl_id, o.org_id)
    if run.status not in (CrawlStatus.queued, CrawlStatus.running):
        raise HTTPException(status_code=409, detail="Crawl is not running.")
    run.status = CrawlStatus.cancelled
    audit.record(db, "crawl.cancelled", org_id=o.org_id, actor_id=o.user.id, target_type="crawl", target_id=run.id,
                 request=request)
    db.commit()
    return crawl_out(run)


def issue_query(db: Session, crawl: CrawlRun, *, category=None, severity=None, finding_type=None, status=None,
                rule_id=None, q=None, url=None):
    stmt = select(Issue).where(Issue.crawl_run_id == crawl.id)
    if crawl.org_id is not None:
        stmt = stmt.where(Issue.org_id == crawl.org_id)
    if category:
        stmt = stmt.where(Issue.category == category)
    if severity:
        stmt = stmt.where(Issue.severity == Severity(severity))
    if finding_type:
        stmt = stmt.where(Issue.finding_type == FindingType(finding_type))
    if status:
        stmt = stmt.where(Issue.status == IssueStatus(status))
    if rule_id:
        stmt = stmt.where(Issue.rule_id == rule_id)
    if url:
        stmt = stmt.where(Issue.url == url)
    if q:
        like = f"%{q[:100]}%"
        stmt = stmt.where(or_(Issue.title.ilike(like), Issue.url.ilike(like), Issue.description.ilike(like)))
    return stmt


@router.get("/crawls/{crawl_id}/issues")
def list_issues(
    crawl_id: uuid.UUID,
    o: OrgContext = Depends(OrgAccess()),
    db: Session = Depends(get_db),
    category: str | None = Query(default=None, pattern="^(technical|content|aeo|geo)$"),
    severity: str | None = Query(default=None, pattern="^(critical|high|medium|low|info)$"),
    finding_type: str | None = Query(default=None, pattern="^(error|warning|recommendation|info)$"),
    status: str | None = Query(default=None, pattern="^(open|ignored|fixed|regressed)$"),
    rule_id: str | None = None,
    url: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    run = scoped_get(db, CrawlRun, crawl_id, o.org_id)
    stmt = issue_query(db, run, category=category, severity=severity, finding_type=finding_type, status=status,
                       rule_id=rule_id, q=q, url=url)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sev_case = case(*[(Issue.severity == Severity(k), v) for k, v in SEVERITY_ORDER.items()], else_=9)
    rows = db.scalars(stmt.order_by(sev_case, Issue.rule_id, Issue.url).limit(limit).offset(offset)).all()
    groups = db.execute(
        select(Issue.rule_id, Issue.title, Issue.category, Issue.severity, Issue.finding_type, func.count())
        .where(Issue.crawl_run_id == run.id, Issue.org_id == o.org_id)
        .group_by(Issue.rule_id, Issue.title, Issue.category, Issue.severity, Issue.finding_type)
    ).all()
    grouped: dict[str, dict] = {}
    for rid, title, cat, sev, ft, n in groups:
        g = grouped.setdefault(rid, {"rule_id": rid, "title": title, "category": cat, "severity": sev.value,
                                     "finding_type": ft.value, "count": 0})
        g["count"] += n
    return {
        "total": total,
        "items": [issue_out(i) for i in rows],
        "groups": sorted(grouped.values(), key=lambda g: (SEVERITY_ORDER[g["severity"]], -g["count"])),
    }


@router.get("/crawls/{crawl_id}/pages")
def list_pages(crawl_id: uuid.UUID, o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db),
               q: str | None = None, status_class: str | None = Query(default=None, pattern="^(2xx|3xx|4xx|5xx|error)$"),
               limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0)):
    run = scoped_get(db, CrawlRun, crawl_id, o.org_id)
    stmt = select(Page).where(Page.crawl_run_id == run.id, Page.org_id == o.org_id)
    if q:
        stmt = stmt.where(or_(Page.url.ilike(f"%{q[:100]}%"), Page.title.ilike(f"%{q[:100]}%")))
    if status_class == "error":
        stmt = stmt.where(Page.status_code.is_(None))
    elif status_class:
        lo = int(status_class[0]) * 100
        stmt = stmt.where(Page.status_code >= lo, Page.status_code < lo + 100)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Page.depth, Page.url).limit(limit).offset(offset)).all()
    counts = dict(db.execute(select(Issue.page_id, func.count()).where(
        Issue.crawl_run_id == run.id, Issue.page_id.in_([p.id for p in rows])).group_by(Issue.page_id)).all())
    return {"total": total, "items": [{**page_out(p), "issue_count": counts.get(p.id, 0)} for p in rows]}


@router.get("/pages/{page_id}")
def get_page(page_id: uuid.UUID, o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    p = scoped_get(db, Page, page_id, o.org_id)
    issues = db.scalars(select(Issue).where(Issue.page_id == p.id, Issue.org_id == o.org_id)).all()
    snap = db.scalar(select(PageSnapshot).where(PageSnapshot.page_id == p.id, PageSnapshot.org_id == o.org_id))
    return {**page_out(p, full=True), "issues": [issue_out(i) for i in issues],
            "snapshot": {"available": snap is not None, "headers": snap.headers if snap else {},
                         "created_at": snap.created_at.isoformat() if snap else None}}


@router.get("/pages/{page_id}/snapshot")
def page_snapshot(page_id: uuid.UUID, o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    """Returns the stored HTML as text (JSON-wrapped, never rendered as HTML by the API)."""
    p = scoped_get(db, Page, page_id, o.org_id)
    snap = db.scalar(select(PageSnapshot).where(PageSnapshot.page_id == p.id, PageSnapshot.org_id == o.org_id))
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not available (expired or not captured).")
    return {"url": p.url, "html": gzip.decompress(snap.html_gz).decode("utf-8", errors="replace")[:500_000]}


@router.get("/issues/{issue_id}")
def get_issue(issue_id: uuid.UUID, o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    i = scoped_get(db, Issue, issue_id, o.org_id)
    fixes = db.scalars(select(FixProposal).where(FixProposal.issue_id == i.id, FixProposal.org_id == o.org_id)
                       .order_by(FixProposal.created_at.desc())).all()
    history = db.execute(
        select(Issue.id, Issue.status, CrawlRun.id, CrawlRun.created_at)
        .join(CrawlRun, CrawlRun.id == Issue.crawl_run_id)
        .where(Issue.org_id == o.org_id, Issue.fingerprint == i.fingerprint)
        .order_by(CrawlRun.created_at.desc()).limit(20)
    ).all()
    page = db.get(Page, i.page_id) if i.page_id else None
    from app.fixes.capabilities import fix_support_for_issue

    return {
        **issue_out(i, full=True),
        "page": page_out(page) if page and page.org_id == o.org_id else None,
        "fixes": [fix_out(f) for f in fixes],
        "history": [{"issue_id": str(a), "status": b.value, "crawl_run_id": str(c), "crawled_at": d.isoformat()}
                    for a, b, c, d in history],
        "fix_support": fix_support_for_issue(db, i),
    }


class IssueStatusIn(BaseModel):
    status: str


@router.patch("/issues/{issue_id}")
def update_issue(issue_id: uuid.UUID, body: IssueStatusIn, request: Request,
                 o: OrgContext = Depends(OrgAccess(Role.editor)), db: Session = Depends(get_db)):
    if body.status not in ("open", "ignored"):
        raise HTTPException(status_code=422, detail="Status must be 'open' or 'ignored'.")
    i = scoped_get(db, Issue, issue_id, o.org_id)
    i.status = IssueStatus(body.status)
    audit.record(db, "issue.status_changed", org_id=o.org_id, actor_id=o.user.id, target_type="issue", target_id=i.id,
                 request=request, data={"status": body.status})
    db.commit()
    return issue_out(i, full=True)
