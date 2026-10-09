from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import ai_status
from app.fixes.types import spec_for
from app.models import Integration, IntegrationStatus, Issue


def connected_integration(db: Session, org_id: uuid.UUID, website_id: uuid.UUID | None) -> Integration | None:
    if not website_id:
        return None
    return db.scalar(select(Integration).where(
        Integration.org_id == org_id, Integration.website_id == website_id,
        Integration.status == IntegrationStatus.connected).order_by(Integration.created_at.desc()))


def direct_apply_for(db: Session, org_id: uuid.UUID, website_id: uuid.UUID | None, fix_type: str) -> dict:
    spec = spec_for(fix_type)
    if spec is None or spec.operation is None:
        return {"supported": False, "reason": "This is advisory guidance; there is nothing to publish automatically.",
                "integration_id": None, "operation": None}
    integ = connected_integration(db, org_id, website_id)
    if integ is None:
        return {"supported": False, "operation": spec.operation, "integration_id": None,
                "reason": "No publishing integration is connected for this website. You can copy or export the fix."}
    cap = (integ.capabilities or {}).get(spec.operation) or {}
    return {"supported": bool(cap.get("supported")), "operation": spec.operation, "integration_id": str(integ.id),
            "provider": integ.provider, "reason": cap.get("reason", ""), "notes": cap.get("notes", ""),
            "rollback": bool(cap.get("rollback"))}


def fix_support_for_issue(db: Session, issue: Issue) -> dict:
    spec = spec_for(issue.fix_type)
    if spec is None:
        return {"fix_type": None, "generator": None, "available": False,
                "reason": "No automated fix is available for this finding; follow the recommendation."}
    ai = ai_status()
    available = spec.generator != "ai" or ai["configured"]
    return {
        "fix_type": spec.key, "label": spec.label, "generator": spec.generator, "risk": spec.risk,
        "available": available, "ai": ai,
        "reason": "" if available else "AI suggestions require an AI provider (set AI_PROVIDER and ANTHROPIC_API_KEY).",
        "direct_apply": direct_apply_for(db, issue.org_id, issue.website_id, spec.key) if issue.org_id else None,
    }
