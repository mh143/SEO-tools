from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import OrgAccess, OrgContext
from app.billing import stripe_service
from app.billing.entitlements import usage_summary
from app.billing.plans import PLANS
from app.core import audit
from app.core.config import get_settings
from app.core.db import get_db
from app.models import BillingWebhookEvent, Role

router = APIRouter(tags=["billing"])


@router.get("/orgs/{org_id}/billing")
def billing_overview(o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    s = get_settings()
    sub = stripe_service.get_subscription(db, o.org_id)
    db.commit()
    return {
        "billing_mode": s.billing_mode,
        "stripe_configured": stripe_service.stripe_configured(),
        "subscription": {
            "plan_key": sub.plan_key, "status": sub.status, "is_simulated": sub.is_simulated,
            "cancel_at_period_end": sub.cancel_at_period_end, "last_payment_error": sub.last_payment_error,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "has_stripe_customer": bool(sub.stripe_customer_id),
        },
        "usage": usage_summary(db, o.org_id),
        "plans": [p.public() for p in PLANS.values()],
        "can_manage": o.membership.role == Role.owner,
    }


class CheckoutIn(BaseModel):
    plan_key: str


@router.post("/orgs/{org_id}/billing/checkout")
def checkout(body: CheckoutIn, request: Request, o: OrgContext = Depends(OrgAccess(Role.owner)), db: Session = Depends(get_db)):
    result = stripe_service.create_checkout(db, o.org, body.plan_key, o.user.email)
    audit.record(db, "billing.checkout" if result.get("mode") == "stripe" else "billing.simulated_plan_change",
                 org_id=o.org_id, actor_id=o.user.id, request=request, data={"plan_key": body.plan_key})
    db.commit()
    return result


@router.post("/orgs/{org_id}/billing/portal")
def portal(o: OrgContext = Depends(OrgAccess(Role.owner)), db: Session = Depends(get_db)):
    result = stripe_service.create_portal(db, o.org)
    db.commit()
    return result


@router.post("/orgs/{org_id}/billing/cancel")
def cancel(request: Request, o: OrgContext = Depends(OrgAccess(Role.owner)), db: Session = Depends(get_db)):
    result = stripe_service.cancel(db, o.org)
    audit.record(db, "billing.cancel_requested", org_id=o.org_id, actor_id=o.user.id, request=request)
    db.commit()
    return result


@router.post("/orgs/{org_id}/billing/dev/simulate-payment-failure")
def simulate_failure(o: OrgContext = Depends(OrgAccess(Role.owner)), db: Session = Depends(get_db)):
    if get_settings().billing_mode != "dev":
        raise HTTPException(status_code=404, detail="Not found.")
    result = stripe_service.simulate_payment_failure(db, o.org)
    db.commit()
    return result


@router.post("/billing/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    event = stripe_service.verify_event(payload, request.headers.get("stripe-signature"))
    try:
        result = stripe_service.process_event(db, event)
        db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        row = db.get(BillingWebhookEvent, event.get("id"))
        if row is None:
            db.add(BillingWebhookEvent(id=event.get("id"), type=event.get("type", ""), status="failed",
                                       error=type(exc).__name__, payload={"type": event.get("type")}))
        else:
            row.status, row.error = "failed", type(exc).__name__
        db.commit()
        # Non-2xx makes Stripe retry later.
        raise HTTPException(status_code=500, detail="Webhook processing failed.") from None
    return {"received": True, "result": result}
