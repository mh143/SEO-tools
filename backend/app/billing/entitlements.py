"""Server-side entitlement checks and usage metering.

Every metered action calls ``consume`` which locks the organization row (SELECT ... FOR UPDATE)
so concurrent requests cannot both pass a limit check, then records a UsageEvent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.billing.plans import Plan, get_plan
from app.models import Membership, Organization, Subscription, UsageEvent, Website

METRICS = (
    "crawl_runs",
    "crawled_pages",
    "rendered_pages",
    "ai_requests",
    "ai_tokens",
    "keyword_requests",
    "publish_ops",
)

ACTIVE_STATUSES = {"active", "trialing"}

_LIMIT_FIELD = {
    "crawl_runs": "crawls_per_month",
    "rendered_pages": "rendered_pages_per_month",
    "ai_requests": "ai_requests_per_month",
    "keyword_requests": "keyword_requests_per_month",
    "publish_ops": "publish_ops_per_month",
}


class EntitlementError(HTTPException):
    def __init__(self, message: str, code: str = "plan_limit"):
        super().__init__(status_code=402, detail={"code": code, "message": message})


def effective_plan(db: Session, org_id: uuid.UUID) -> Plan:
    """Plan currently in force. Past-due/cancelled/unpaid subscriptions fall back to Free limits."""
    sub = db.scalar(select(Subscription).where(Subscription.org_id == org_id))
    if sub is None or sub.status not in ACTIVE_STATUSES:
        return get_plan("free")
    return get_plan(sub.plan_key)


def period_start(db: Session, org_id: uuid.UUID) -> datetime:
    sub = db.scalar(select(Subscription).where(Subscription.org_id == org_id))
    now = datetime.now(UTC)
    if sub and sub.current_period_start and sub.current_period_end and sub.current_period_end > now:
        return sub.current_period_start
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def usage(db: Session, org_id: uuid.UUID, metric: str, since: datetime | None = None) -> int:
    since = since or period_start(db, org_id)
    return int(
        db.scalar(
            select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
                UsageEvent.org_id == org_id, UsageEvent.metric == metric, UsageEvent.created_at >= since
            )
        )
        or 0
    )


def limit_for(plan: Plan, metric: str) -> int | None:
    field = _LIMIT_FIELD.get(metric)
    return getattr(plan, field) if field else None


def _lock_org(db: Session, org_id: uuid.UUID) -> None:
    db.execute(select(Organization.id).where(Organization.id == org_id).with_for_update())


def consume(db: Session, org_id: uuid.UUID, metric: str, quantity: int = 1, ref: dict | None = None) -> None:
    """Check the limit for ``metric`` and record usage. Raises EntitlementError (HTTP 402)."""
    assert metric in METRICS, metric
    _lock_org(db, org_id)
    plan = effective_plan(db, org_id)
    limit = limit_for(plan, metric)
    if limit is not None:
        used = usage(db, org_id, metric)
        if used + quantity > limit:
            raise EntitlementError(
                f"Your {plan.name} plan allows {limit} {metric.replace('_', ' ')} per billing period "
                f"({used} used). Upgrade your plan to continue."
            )
    record(db, org_id, metric, quantity, ref)


def record(db: Session, org_id: uuid.UUID, metric: str, quantity: int, ref: dict | None = None) -> None:
    """Record usage without a limit check (e.g. pages crawled inside an already-authorized crawl)."""
    if quantity <= 0:
        return
    db.add(UsageEvent(org_id=org_id, metric=metric, quantity=quantity, ref=ref or {}))


def require_feature(db: Session, org_id: uuid.UUID, feature: str) -> Plan:
    plan = effective_plan(db, org_id)
    if feature == "js_rendering" and not plan.js_rendering:
        raise EntitlementError("JavaScript rendering requires the Pro plan or higher.", "feature_unavailable")
    if feature == "white_label" and not plan.reports_white_label:
        raise EntitlementError("White-label reports require the Agency plan.", "feature_unavailable")
    if feature == "publishing" and plan.publish_ops_per_month <= 0:
        raise EntitlementError("Direct publishing requires a paid plan.", "feature_unavailable")
    if feature == "keywords" and plan.keyword_requests_per_month <= 0:
        raise EntitlementError("Keyword data requires a paid plan.", "feature_unavailable")
    return plan


def check_website_limit(db: Session, org_id: uuid.UUID) -> None:
    _lock_org(db, org_id)
    plan = effective_plan(db, org_id)
    count = db.scalar(select(func.count()).select_from(Website).where(Website.org_id == org_id)) or 0
    if count >= plan.max_websites:
        raise EntitlementError(f"Your {plan.name} plan allows {plan.max_websites} website(s).")


def check_seat_limit(db: Session, org_id: uuid.UUID, pending_invites: int = 0) -> None:
    plan = effective_plan(db, org_id)
    count = db.scalar(select(func.count()).select_from(Membership).where(Membership.org_id == org_id)) or 0
    if count + pending_invites >= plan.team_seats:
        raise EntitlementError(f"Your {plan.name} plan allows {plan.team_seats} team member(s).")


def check_schedule(plan: Plan, schedule: str) -> None:
    if schedule not in plan.schedules:
        raise EntitlementError(f"The {plan.name} plan does not include '{schedule}' scheduled audits.")


def usage_summary(db: Session, org_id: uuid.UUID) -> dict:
    plan = effective_plan(db, org_id)
    since = period_start(db, org_id)
    out = {}
    for m in METRICS:
        out[m] = {"used": usage(db, org_id, m, since), "limit": limit_for(plan, m)}
    out["websites"] = {
        "used": db.scalar(select(func.count()).select_from(Website).where(Website.org_id == org_id)) or 0,
        "limit": plan.max_websites,
    }
    out["team_seats"] = {
        "used": db.scalar(select(func.count()).select_from(Membership).where(Membership.org_id == org_id)) or 0,
        "limit": plan.team_seats,
    }
    return {"plan": plan.public(), "period_start": since.isoformat(), "metrics": out}
