"""Data retention: snapshots, anonymous audits, expired sessions and invitations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.core.config import get_settings
from app.core.db import db_session
from app.models import CrawlRun, Invitation, PageSnapshot, UserSession


def apply_retention(now: datetime | None = None) -> dict:
    s = get_settings()
    now = now or datetime.now(UTC)
    out = {}
    with db_session() as db:
        out["snapshots"] = db.execute(delete(PageSnapshot).where(
            PageSnapshot.created_at < now - timedelta(days=s.snapshot_retention_days))).rowcount
        out["anonymous_audits"] = db.execute(delete(CrawlRun).where(
            CrawlRun.org_id.is_(None), CrawlRun.expires_at.is_not(None), CrawlRun.expires_at < now)).rowcount
        out["sessions"] = db.execute(delete(UserSession).where(UserSession.expires_at < now - timedelta(days=1))).rowcount
        out["invitations"] = db.execute(delete(Invitation).where(
            Invitation.accepted_at.is_(None), Invitation.expires_at < now - timedelta(days=30))).rowcount
    return out
