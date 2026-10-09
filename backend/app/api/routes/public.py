"""Public (no account) quick audits and plan catalogue.

Anonymous audits are limited to a few pages, rate limited per IP, capped globally, reachable only
through an unguessable token (only its hash is stored), and deleted after a retention period.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.crawls import SEVERITY_ORDER
from app.api.routes.websites import normalize_site_url
from app.api.serializers import crawl_out, issue_out
from app.billing.plans import PLANS
from app.core.config import get_settings
from app.core.db import get_db
from app.core.ratelimit import enforce
from app.core.security import hash_token, new_token
from app.models import CrawlRun, CrawlStatus, Issue
from app.tasks.dispatch import enqueue

router = APIRouter(prefix="/public", tags=["public"])

MAX_CONCURRENT_PUBLIC = 10


class PublicAuditIn(BaseModel):
    url: str = Field(max_length=2048)


@router.get("/plans")
def plans():
    s = get_settings()
    return {
        "currency": "CAD",
        "billing_mode": s.billing_mode,
        "note": "Prices are introductory and may change. Taxes may apply.",
        "plans": [p.public() for p in PLANS.values()],
    }


@router.post("/audits")
def start_public_audit(body: PublicAuditIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    enforce(request, "public-audit", s.rate_limit_public_audit_per_hour, 3600)
    root, _host = normalize_site_url(body.url)
    running = db.scalar(select(func.count()).select_from(CrawlRun).where(
        CrawlRun.org_id.is_(None), CrawlRun.status.in_([CrawlStatus.queued, CrawlStatus.running]))) or 0
    if running >= MAX_CONCURRENT_PUBLIC:
        raise HTTPException(status_code=503, detail="Free audits are busy right now. Please try again in a minute.")
    token = new_token(24)
    run = CrawlRun(
        org_id=None, website_id=None, public_token_hash=hash_token(token), start_url=root, status=CrawlStatus.queued,
        trigger="public", settings={"max_pages": s.public_audit_max_pages, "max_depth": 2, "render_js": False},
        expires_at=datetime.now(UTC) + timedelta(days=s.anonymous_audit_retention_days),
    )
    db.add(run)
    db.commit()
    enqueue("run_crawl", str(run.id))
    return {"token": token, "status": run.status.value, "expires_at": run.expires_at.isoformat()}


def _run_for_token(db: Session, token: str) -> CrawlRun:
    if not token or len(token) > 100:
        raise HTTPException(status_code=404, detail="Not found.")
    run = db.scalar(select(CrawlRun).where(CrawlRun.public_token_hash == hash_token(token), CrawlRun.org_id.is_(None)))
    if not run or (run.expires_at and run.expires_at < datetime.now(UTC)):
        raise HTTPException(status_code=404, detail="Audit not found or expired.")
    return run


@router.get("/audits/{token}")
def get_public_audit(token: str, db: Session = Depends(get_db)):
    run = _run_for_token(db, token)
    data = crawl_out(run)
    data.pop("website_id", None)
    data["expires_at"] = run.expires_at.isoformat() if run.expires_at else None
    issues = db.scalars(select(Issue).where(Issue.crawl_run_id == run.id, Issue.org_id.is_(None)).limit(500)).all()
    items = sorted((issue_out(i, full=True) for i in issues), key=lambda d: (SEVERITY_ORDER[d["severity"]], d["rule_id"]))
    data["issues"] = items[:200]
    data["site_data"] = {k: v for k, v in (run.site_data or {}).items() if k != "robots"}
    return data
