from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import OrgAccess, OrgContext, scoped_get
from app.api.routes.public import _run_for_token
from app.billing.entitlements import effective_plan
from app.core.config import get_settings
from app.core.db import get_db
from app.models import CrawlRun, FixProposal, FixStatus, Issue, Website
from app.reports import export

router = APIRouter(tags=["reports"])

MEDIA = {"csv": "text/csv", "json": "application/json", "md": "text/markdown", "html": "text/html",
         "txt": "text/plain"}


def _download(body: str, fmt: str, name: str) -> Response:
    headers = {"Content-Disposition": f'attachment; filename="{name}.{fmt}"',
               # Reports contain third-party content; never let them run scripts in our origin.
               "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"}
    return Response(content=body, media_type=f"{MEDIA[fmt]}; charset=utf-8", headers=headers)


def _render(run: CrawlRun, issues: list[Issue], fmt: str, *, company=None, accent="#2563eb", white_label=False) -> Response:
    name = f"audit-{run.id}"
    if fmt == "csv":
        return _download(export.issues_csv(issues), fmt, name)
    if fmt == "json":
        return _download(export.issues_json(run, issues), fmt, name)
    if fmt == "md":
        return _download(export.issues_markdown(run, issues), fmt, name)
    if fmt == "html":
        return _download(export.report_html(run, issues, company=company, accent=accent, white_label=white_label,
                                            product_name=get_settings().app_name), fmt, name)
    raise HTTPException(status_code=422, detail="Unknown format.")


@router.get("/orgs/{org_id}/crawls/{crawl_id}/export")
def export_crawl(crawl_id: uuid.UUID, format: str = Query(default="csv", pattern="^(csv|json|md|html)$"),
                 include_ignored: bool = False, o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    run = scoped_get(db, CrawlRun, crawl_id, o.org_id)
    stmt = select(Issue).where(Issue.crawl_run_id == run.id, Issue.org_id == o.org_id)
    issues = [i for i in db.scalars(stmt) if include_ignored or i.status.value != "ignored"]
    plan = effective_plan(db, o.org_id)
    b = o.org.branding or {}
    return _render(run, issues, format, company=b.get("report_company_name") or o.org.name,
                   accent=b.get("report_accent_color") or "#2563eb", white_label=plan.reports_white_label)


@router.get("/public/audits/{token}/export")
def export_public(token: str, format: str = Query(default="csv", pattern="^(csv|json|md|html)$"),
                  db: Session = Depends(get_db)):
    run = _run_for_token(db, token)
    issues = list(db.scalars(select(Issue).where(Issue.crawl_run_id == run.id, Issue.org_id.is_(None))))
    return _render(run, issues, format)


@router.get("/orgs/{org_id}/fixes-export")
def export_fixes(format: str = Query(default="json", pattern="^(json|csv)$"), website_id: uuid.UUID | None = None,
                 status: str | None = None, o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    stmt = select(FixProposal).where(FixProposal.org_id == o.org_id)
    if website_id:
        scoped_get(db, Website, website_id, o.org_id)
        stmt = stmt.where(FixProposal.website_id == website_id)
    if status:
        stmt = stmt.where(FixProposal.status.in_([FixStatus(s) for s in status.split(",") if s in FixStatus._value2member_map_]))
    fixes = list(db.scalars(stmt.order_by(FixProposal.created_at)))
    body = export.fixes_json(fixes) if format == "json" else export.fixes_csv(fixes)
    return _download(body, format, "fixes")


@router.get("/orgs/{org_id}/fixes/{fix_id}/export")
def export_fix(fix_id: uuid.UUID, format: str = Query(default="txt", pattern="^(txt|json)$"),
               o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    fix = scoped_get(db, FixProposal, fix_id, o.org_id)
    if format == "json":
        return _download(export.fixes_json([fix]), "json", f"fix-{fix.id}")
    return _download(export.fix_instructions(fix), "txt", f"fix-{fix.id}")
