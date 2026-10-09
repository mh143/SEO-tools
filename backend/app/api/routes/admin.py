"""Platform administration (staff only: users with is_platform_admin). Non-admins get 404."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_platform_admin
from app.core import audit
from app.core.db import get_db
from app.models import (
    AuditLog,
    BillingWebhookEvent,
    CrawlRun,
    CrawlStatus,
    FixProposal,
    Membership,
    Organization,
    Subscription,
    UsageEvent,
    User,
    UserSession,
    Website,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/overview")
def overview(_: AuthContext = Depends(require_platform_admin), db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    day = now - timedelta(days=1)
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def count(model, *where):
        return db.scalar(select(func.count()).select_from(model).where(*where)) or 0

    crawls_24h = dict(db.execute(select(CrawlRun.status, func.count()).where(CrawlRun.created_at >= day)
                                 .group_by(CrawlRun.status)).all())
    plans = db.execute(select(Subscription.plan_key, Subscription.status, Subscription.is_simulated, func.count())
                       .group_by(Subscription.plan_key, Subscription.status, Subscription.is_simulated)).all()
    usage = dict(db.execute(select(UsageEvent.metric, func.sum(UsageEvent.quantity)).where(UsageEvent.created_at >= month)
                            .group_by(UsageEvent.metric)).all())
    return {
        "users": count(User), "organizations": count(Organization), "websites": count(Website),
        "crawls_24h": {k.value: v for k, v in crawls_24h.items()},
        "running_crawls": count(CrawlRun, CrawlRun.status.in_([CrawlStatus.queued, CrawlStatus.running])),
        "public_audits_24h": count(CrawlRun, CrawlRun.org_id.is_(None), CrawlRun.created_at >= day),
        "fixes_total": count(FixProposal),
        "subscriptions": [{"plan_key": p, "status": s, "simulated": sim, "count": n} for p, s, sim, n in plans],
        "usage_this_month": {k: int(v or 0) for k, v in usage.items()},
        "failed_webhooks": count(BillingWebhookEvent, BillingWebhookEvent.status == "failed"),
    }


@router.get("/organizations")
def organizations(q: str | None = None, _: AuthContext = Depends(require_platform_admin), db: Session = Depends(get_db)):
    stmt = select(Organization)
    if q:
        stmt = stmt.where(Organization.name.ilike(f"%{q[:100]}%"))
    orgs = db.scalars(stmt.order_by(Organization.created_at.desc()).limit(200)).all()
    out = []
    for o in orgs:
        sub = db.scalar(select(Subscription).where(Subscription.org_id == o.id))
        out.append({"id": str(o.id), "name": o.name, "plan_key": o.plan_key, "created_at": o.created_at.isoformat(),
                    "members": db.scalar(select(func.count()).select_from(Membership).where(Membership.org_id == o.id)),
                    "websites": db.scalar(select(func.count()).select_from(Website).where(Website.org_id == o.id)),
                    "subscription_status": sub.status if sub else None, "simulated": sub.is_simulated if sub else None})
    return out


@router.get("/users")
def users(q: str | None = None, _: AuthContext = Depends(require_platform_admin), db: Session = Depends(get_db)):
    stmt = select(User)
    if q:
        stmt = stmt.where(or_(User.email.ilike(f"%{q[:100]}%"), User.name.ilike(f"%{q[:100]}%")))
    return [{"id": str(u.id), "email": u.email, "name": u.name, "is_active": u.is_active,
             "is_platform_admin": u.is_platform_admin, "created_at": u.created_at.isoformat(),
             "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None}
            for u in db.scalars(stmt.order_by(User.created_at.desc()).limit(200))]


@router.post("/users/{user_id}/active")
def set_active(user_id: uuid.UUID, active: bool, request: Request, ctx: AuthContext = Depends(require_platform_admin),
               db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="Not found.")
    if u.id == ctx.user.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate yourself.")
    u.is_active = active
    if not active:
        for s in db.scalars(select(UserSession).where(UserSession.user_id == u.id, UserSession.revoked_at.is_(None))):
            s.revoked_at = datetime.now(UTC)
    audit.record(db, "admin.user_active_changed", actor_id=ctx.user.id, target_type="user", target_id=u.id,
                 request=request, data={"active": active})
    db.commit()
    return {"ok": True}


@router.get("/crawls")
def crawls(status: str | None = None, _: AuthContext = Depends(require_platform_admin), db: Session = Depends(get_db)):
    stmt = select(CrawlRun)
    if status:
        stmt = stmt.where(CrawlRun.status == CrawlStatus(status))
    return [{"id": str(r.id), "org_id": str(r.org_id) if r.org_id else None, "start_url": r.start_url,
             "status": r.status.value, "trigger": r.trigger, "pages_crawled": r.pages_crawled, "error": r.error,
             "created_at": r.created_at.isoformat()}
            for r in db.scalars(stmt.order_by(CrawlRun.created_at.desc()).limit(200))]


@router.get("/webhooks")
def webhooks(_: AuthContext = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return [{"id": e.id, "type": e.type, "status": e.status, "error": e.error, "received_at": e.received_at.isoformat(),
             "processed_at": e.processed_at.isoformat() if e.processed_at else None}
            for e in db.scalars(select(BillingWebhookEvent).order_by(BillingWebhookEvent.received_at.desc()).limit(200))]


@router.get("/audit-logs")
def audit_logs(action: str | None = None, _: AuthContext = Depends(require_platform_admin), db: Session = Depends(get_db)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return [{"id": str(a.id), "org_id": str(a.org_id) if a.org_id else None, "action": a.action,
             "actor_user_id": str(a.actor_user_id) if a.actor_user_id else None, "target_type": a.target_type,
             "target_id": a.target_id, "ip": a.ip, "data": a.data, "created_at": a.created_at.isoformat()}
            for a in db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(300))]
