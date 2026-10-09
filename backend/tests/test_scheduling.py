import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import db_session
from app.models import (
    CrawlRun,
    FixProposal,
    FixStatus,
    Issue,
    IssueStatus,
    Notification,
    PageSnapshot,
    Website,
)
from app.services.retention import apply_retention
from app.services.scheduler import dispatch_due
from app.tasks.dispatch import wait_inline
from tests.conftest import crawl_site, set_plan
from tests.fixtures.demo_site import demo_site


def test_scheduled_audit_and_regression_alert(alice, loopback):
    set_plan(alice.org_id, "pro")
    org = alice.org_id
    with demo_site() as site:
        res = crawl_site(alice, site.base)
        wid = res["website"]["id"]
        assert alice.patch(f"/api/orgs/{org}/websites/{wid}", {"schedule": "daily"}).status_code == 200
        # Pretend a fix for the duplicate title was verified earlier.
        with db_session() as s:
            issue = s.scalars(select(Issue).where(Issue.crawl_run_id == uuid.UUID(res["crawl"]["id"]),
                                                  Issue.rule_id == "tech.title_duplicate")).first()
            s.add(FixProposal(org_id=issue.org_id, issue_id=issue.id, website_id=issue.website_id, url=issue.url,
                              fix_type="meta_title", status=FixStatus.verified, generator="rule", risk_level="low",
                              confidence="high"))
            s.get(Website, uuid.UUID(wid)).next_scheduled_at = datetime.now(UTC) - timedelta(minutes=1)
        assert dispatch_due() == 1
        wait_inline(120)
    with db_session() as s:
        runs = s.scalars(select(CrawlRun).where(CrawlRun.website_id == uuid.UUID(wid)).order_by(CrawlRun.created_at)).all()
        assert runs[-1].trigger == "scheduled"
        assert runs[-1].summary["diff"]["regressed"] >= 1
        regressed = s.scalars(select(Issue).where(Issue.crawl_run_id == runs[-1].id, Issue.status == IssueStatus.regressed)).all()
        assert regressed
        notes = s.scalars(select(Notification).where(Notification.org_id == uuid.UUID(org))).all()
        assert any(n.kind == "regression" for n in notes)
        assert s.get(Website, uuid.UUID(wid)).next_scheduled_at > datetime.now(UTC)
    ov = alice.get(f"/api/orgs/{org}/overview").json()
    assert ov["notifications"]


def test_schedule_disabled_after_downgrade(alice, loopback):
    set_plan(alice.org_id, "pro")
    site = alice.post(f"/api/orgs/{alice.org_id}/websites", {"url": "https://example.com"}).json()
    alice.patch(f"/api/orgs/{alice.org_id}/websites/{site['id']}", {"schedule": "daily"})
    set_plan(alice.org_id, "free")
    with db_session() as s:
        s.get(Website, uuid.UUID(site["id"])).next_scheduled_at = datetime.now(UTC) - timedelta(minutes=1)
    assert dispatch_due() == 0
    with db_session() as s:
        assert s.get(Website, uuid.UUID(site["id"])).schedule == "none"


def test_retention(alice, loopback, monkeypatch):
    from app.core.config import get_settings

    set_plan(alice.org_id, "pro")
    with demo_site() as site:
        crawl_site(alice, site.base)
        alice.post("/api/public/audits", {"url": site.base + "/"})
        wait_inline()
    with db_session() as s:
        assert s.scalars(select(PageSnapshot)).first() is not None
    monkeypatch.setattr(get_settings(), "snapshot_retention_days", 0)
    out = apply_retention(datetime.now(UTC) + timedelta(days=30))
    assert out["snapshots"] > 0 and out["anonymous_audits"] == 1
    with db_session() as s:
        assert s.scalars(select(PageSnapshot)).first() is None
        assert s.scalars(select(CrawlRun).where(CrawlRun.org_id.is_(None))).first() is None


def test_delete_website_removes_data(alice, loopback):
    set_plan(alice.org_id, "pro")
    with demo_site() as site:
        res = crawl_site(alice, site.base)
    r = alice.delete(f"/api/orgs/{alice.org_id}/websites/{res['website']['id']}")
    assert r.status_code == 200
    with db_session() as s:
        assert s.scalars(select(CrawlRun).where(CrawlRun.website_id == uuid.UUID(res["website"]["id"]))).first() is None
        assert s.scalars(select(Issue).where(Issue.website_id == uuid.UUID(res["website"]["id"]))).first() is None
