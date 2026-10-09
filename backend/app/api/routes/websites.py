from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import OrgAccess, OrgContext, scoped_get
from app.api.serializers import crawl_out, integration_out, website_out
from app.billing import entitlements
from app.core import audit
from app.core.db import get_db
from app.crawler.ssrf import BlockedURLError, validate_url
from app.crawler.urls import normalize_url
from app.models import CrawlRun, Integration, Role, Website
from app.services.crawl_service import create_run
from app.services.scheduler import compute_next
from app.tasks.dispatch import enqueue

router = APIRouter(prefix="/orgs/{org_id}/websites", tags=["websites"])


class WebsiteIn(BaseModel):
    url: str = Field(max_length=2048)
    name: str | None = Field(default=None, max_length=200)


class CrawlSettingsIn(BaseModel):
    max_pages: int | None = Field(default=None, ge=1, le=10000)
    max_depth: int | None = Field(default=None, ge=0, le=20)
    render_js: bool | None = None


class WebsiteUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    schedule: str | None = Field(default=None, pattern="^(none|daily|weekly|monthly)$")
    crawl_settings: CrawlSettingsIn | None = None


class CrawlStartIn(BaseModel):
    max_pages: int | None = Field(default=None, ge=1, le=10000)
    max_depth: int | None = Field(default=None, ge=0, le=20)
    render_js: bool = False


def normalize_site_url(url: str) -> tuple[str, str]:
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    try:
        validate_url(url)
    except BlockedURLError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    n = normalize_url(url)
    if not n:
        raise HTTPException(status_code=422, detail="Invalid URL.")
    p = urlsplit(n)
    return f"{p.scheme}://{p.netloc}{p.path if p.path not in ('', '/') else '/'}", (p.hostname or "").lower()


@router.get("")
def list_websites(o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    rows = db.scalars(select(Website).where(Website.org_id == o.org_id).order_by(Website.created_at)).all()
    return [website_out(w) for w in rows]


@router.post("")
def create_website(body: WebsiteIn, request: Request, o: OrgContext = Depends(OrgAccess(Role.editor)),
                   db: Session = Depends(get_db)):
    root, host = normalize_site_url(body.url)
    entitlements.check_website_limit(db, o.org_id)
    if db.scalar(select(Website).where(Website.org_id == o.org_id, Website.hostname == host)):
        raise HTTPException(status_code=409, detail="This website is already in your workspace.")
    w = Website(org_id=o.org_id, name=(body.name or host).strip()[:200], root_url=root, hostname=host,
                crawl_settings={}, schedule="none")
    db.add(w)
    db.flush()
    audit.record(db, "website.created", org_id=o.org_id, actor_id=o.user.id, target_type="website", target_id=w.id,
                 request=request, data={"url": root})
    db.commit()
    return website_out(w)


@router.get("/{website_id}")
def get_website(website_id: uuid.UUID, o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    w = scoped_get(db, Website, website_id, o.org_id)
    runs = db.scalars(select(CrawlRun).where(CrawlRun.org_id == o.org_id, CrawlRun.website_id == w.id)
                      .order_by(CrawlRun.created_at.desc()).limit(30)).all()
    integrations = db.scalars(select(Integration).where(Integration.org_id == o.org_id, Integration.website_id == w.id)).all()
    plan = entitlements.effective_plan(db, o.org_id)
    return {**website_out(w), "crawls": [crawl_out(r) for r in runs],
            "integrations": [integration_out(i) for i in integrations],
            "plan_limits": {"max_pages": plan.max_pages_per_crawl, "max_depth": plan.max_depth,
                            "js_rendering": plan.js_rendering, "schedules": list(plan.schedules)}}


@router.patch("/{website_id}")
def update_website(website_id: uuid.UUID, body: WebsiteUpdateIn, request: Request,
                   o: OrgContext = Depends(OrgAccess(Role.editor)), db: Session = Depends(get_db)):
    w = scoped_get(db, Website, website_id, o.org_id)
    plan = entitlements.effective_plan(db, o.org_id)
    if body.name:
        w.name = body.name.strip()
    if body.schedule is not None:
        entitlements.check_schedule(plan, body.schedule)
        w.schedule = body.schedule
        w.next_scheduled_at = compute_next(body.schedule)
    if body.crawl_settings is not None:
        cs = dict(w.crawl_settings or {})
        if body.crawl_settings.max_pages is not None:
            cs["max_pages"] = min(body.crawl_settings.max_pages, plan.max_pages_per_crawl)
        if body.crawl_settings.max_depth is not None:
            cs["max_depth"] = min(body.crawl_settings.max_depth, plan.max_depth)
        if body.crawl_settings.render_js is not None:
            if body.crawl_settings.render_js:
                entitlements.require_feature(db, o.org_id, "js_rendering")
            cs["render_js"] = body.crawl_settings.render_js
        w.crawl_settings = cs
    audit.record(db, "website.updated", org_id=o.org_id, actor_id=o.user.id, target_type="website", target_id=w.id,
                 request=request, data=body.model_dump(exclude_none=True))
    db.commit()
    return website_out(w)


@router.delete("/{website_id}")
def delete_website(website_id: uuid.UUID, request: Request, o: OrgContext = Depends(OrgAccess(Role.admin)),
                   db: Session = Depends(get_db)):
    """Deletes the website and all crawls, pages, snapshots, issues, fixes and integration credentials."""
    w = scoped_get(db, Website, website_id, o.org_id)
    audit.record(db, "website.deleted", org_id=o.org_id, actor_id=o.user.id, target_type="website", target_id=w.id,
                 request=request, data={"url": w.root_url})
    db.delete(w)
    db.commit()
    return {"ok": True}


@router.post("/{website_id}/crawls")
def start_crawl(website_id: uuid.UUID, request: Request, body: CrawlStartIn | None = None,
                o: OrgContext = Depends(OrgAccess(Role.editor)), db: Session = Depends(get_db)):
    w = scoped_get(db, Website, website_id, o.org_id)
    run = create_run(db, website=w, user_id=o.user.id, trigger="manual",
                     requested=(body.model_dump(exclude_none=True) if body else None))
    audit.record(db, "crawl.started", org_id=o.org_id, actor_id=o.user.id, target_type="crawl", target_id=run.id,
                 request=request)
    db.commit()
    enqueue("run_crawl", str(run.id))
    return crawl_out(run)


@router.get("/{website_id}/crawls")
def list_crawls(website_id: uuid.UUID, o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    w = scoped_get(db, Website, website_id, o.org_id)
    runs = db.scalars(select(CrawlRun).where(CrawlRun.org_id == o.org_id, CrawlRun.website_id == w.id)
                      .order_by(CrawlRun.created_at.desc()).limit(100)).all()
    return [crawl_out(r) for r in runs]
