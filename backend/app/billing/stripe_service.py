"""Stripe Billing integration.

* Checkout (mode=subscription) and the Customer Portal are created server-side.
* Webhooks are verified with the endpoint signing secret (``stripe.Webhook.construct_event``) and
  processed idempotently: each Stripe event id is stored once in ``billing_webhook_events``.
* Plan entitlements follow subscription status: only ``active``/``trialing`` grant paid limits.

BILLING_MODE=dev replaces Stripe with an explicit simulation for local development. Simulated
subscriptions are flagged ``is_simulated`` and shown as such in the UI; the mode is refused in production.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import stripe
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.plans import PLANS, get_plan
from app.core.config import get_settings
from app.models import BillingWebhookEvent, Notification, Organization, Subscription

log = logging.getLogger(__name__)


def stripe_configured() -> bool:
    s = get_settings()
    return s.billing_mode == "stripe" and bool(s.stripe_secret_key)


def price_for(plan_key: str) -> str:
    plan = get_plan(plan_key)
    if not plan.stripe_price_env:
        raise HTTPException(status_code=422, detail="This plan cannot be purchased.")
    price = getattr(get_settings(), plan.stripe_price_env, "")
    if not price:
        raise HTTPException(status_code=503, detail=f"Stripe price for the {plan.name} plan is not configured.")
    return price


def plan_for_price(price_id: str | None) -> str | None:
    s = get_settings()
    for key, plan in PLANS.items():
        if plan.stripe_price_env and getattr(s, plan.stripe_price_env, "") == price_id and price_id:
            return key
    return None


def get_subscription(db: Session, org_id: uuid.UUID) -> Subscription:
    sub = db.scalar(select(Subscription).where(Subscription.org_id == org_id))
    if sub is None:
        sub = Subscription(org_id=org_id, plan_key="free", status="active")
        db.add(sub)
        db.flush()
    return sub


def _sync_org_plan(db: Session, sub: Subscription) -> None:
    org = db.get(Organization, sub.org_id)
    if org:
        org.plan_key = sub.plan_key if sub.status in ("active", "trialing") else "free"


# ------------------------------------------------------------------ checkout / portal
def create_checkout(db: Session, org: Organization, plan_key: str, user_email: str) -> dict:
    s = get_settings()
    if plan_key not in PLANS or plan_key == "free":
        raise HTTPException(status_code=422, detail="Unknown or free plan.")
    sub = get_subscription(db, org.id)
    if s.billing_mode == "dev":
        return simulate_plan_change(db, org, sub, plan_key)
    if not stripe_configured():
        raise HTTPException(status_code=503, detail="Stripe is not configured (set STRIPE_SECRET_KEY).")
    price = price_for(plan_key)
    if sub.stripe_subscription_id and sub.status in ("active", "trialing", "past_due"):
        # Plan changes for existing subscribers go through the portal (proration handled by Stripe).
        return create_portal(db, org)
    if not sub.stripe_customer_id:
        customer = stripe.Customer.create(api_key=s.stripe_secret_key, email=user_email, name=org.name,
                                          metadata={"org_id": str(org.id)})
        sub.stripe_customer_id = customer["id"]
    session = stripe.checkout.Session.create(
        api_key=s.stripe_secret_key,
        mode="subscription",
        customer=sub.stripe_customer_id,
        line_items=[{"price": price, "quantity": 1}],
        client_reference_id=str(org.id),
        metadata={"org_id": str(org.id), "plan_key": plan_key},
        subscription_data={"metadata": {"org_id": str(org.id), "plan_key": plan_key}},
        success_url=f"{s.public_app_url}/app/{org.id}/billing?checkout=success",
        cancel_url=f"{s.public_app_url}/app/{org.id}/billing?checkout=cancelled",
        automatic_tax={"enabled": False},
    )
    return {"url": session["url"], "mode": "stripe"}


def create_portal(db: Session, org: Organization) -> dict:
    s = get_settings()
    if s.billing_mode == "dev":
        raise HTTPException(status_code=409, detail="The billing portal is not available in development billing mode.")
    if not stripe_configured():
        raise HTTPException(status_code=503, detail="Stripe is not configured.")
    sub = get_subscription(db, org.id)
    if not sub.stripe_customer_id:
        raise HTTPException(status_code=409, detail="No Stripe customer exists for this organization yet.")
    portal = stripe.billing_portal.Session.create(api_key=s.stripe_secret_key, customer=sub.stripe_customer_id,
                                                  return_url=f"{s.public_app_url}/app/{org.id}/billing")
    return {"url": portal["url"], "mode": "stripe"}


def cancel(db: Session, org: Organization) -> dict:
    s = get_settings()
    sub = get_subscription(db, org.id)
    if sub.plan_key == "free":
        raise HTTPException(status_code=409, detail="The Free plan has nothing to cancel.")
    if s.billing_mode == "dev":
        sub.cancel_at_period_end = True
        return {"mode": "dev", "cancel_at_period_end": True}
    if not sub.stripe_subscription_id:
        raise HTTPException(status_code=409, detail="No Stripe subscription found.")
    stripe.Subscription.modify(sub.stripe_subscription_id, api_key=s.stripe_secret_key, cancel_at_period_end=True)
    sub.cancel_at_period_end = True  # webhook will confirm
    return {"mode": "stripe", "cancel_at_period_end": True}


def simulate_plan_change(db: Session, org: Organization, sub: Subscription, plan_key: str) -> dict:
    if get_settings().is_production:  # belt and braces; config validation already refuses this
        raise HTTPException(status_code=403, detail="Simulated billing is disabled in production.")
    now = datetime.now(UTC)
    sub.plan_key = plan_key
    sub.status = "active"
    sub.is_simulated = True
    sub.cancel_at_period_end = False
    sub.current_period_start = now
    sub.current_period_end = now + timedelta(days=30)
    _sync_org_plan(db, sub)
    return {"mode": "dev", "simulated": True, "plan_key": plan_key,
            "message": "Development billing: plan changed without payment. No real transaction occurred."}


def simulate_payment_failure(db: Session, org: Organization) -> dict:
    sub = get_subscription(db, org.id)
    if not sub.is_simulated:
        raise HTTPException(status_code=409, detail="Only simulated subscriptions can simulate payment failures.")
    sub.status = "past_due"
    sub.last_payment_error = "Simulated card decline (development billing)."
    _sync_org_plan(db, sub)
    return {"status": sub.status}


# ------------------------------------------------------------------ webhooks
def verify_event(payload: bytes, sig_header: str | None) -> dict:
    s = get_settings()
    if not s.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook secret not configured.")
    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header.")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, s.stripe_webhook_secret)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid webhook signature.") from None
    return event.to_dict() if hasattr(event, "to_dict") else dict(event)


def _ts(v: Any) -> datetime | None:
    return datetime.fromtimestamp(int(v), tz=UTC) if v else None


def _find_sub(db: Session, *, subscription_id=None, customer_id=None, org_id=None) -> Subscription | None:
    if subscription_id:
        sub = db.scalar(select(Subscription).where(Subscription.stripe_subscription_id == subscription_id))
        if sub:
            return sub
    if customer_id:
        sub = db.scalar(select(Subscription).where(Subscription.stripe_customer_id == customer_id))
        if sub:
            return sub
    if org_id:
        try:
            oid = uuid.UUID(str(org_id))
        except ValueError:
            return None
        if db.get(Organization, oid):
            return get_subscription(db, oid)
    return None


def process_event(db: Session, event: dict) -> str:
    """Process one verified event idempotently. Returns 'processed' | 'duplicate' | 'ignored'."""
    eid = event.get("id")
    if not eid:
        raise HTTPException(status_code=400, detail="Event has no id.")
    existing = db.get(BillingWebhookEvent, eid)
    if existing and existing.status in ("processed", "ignored"):
        return "duplicate"
    if existing is None:
        existing = BillingWebhookEvent(id=eid, type=event.get("type", ""), status="processing",
                                       payload={"type": event.get("type"), "created": event.get("created")})
        db.add(existing)
        db.flush()
    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    result = "ignored"
    if etype == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        sub = _find_sub(db, customer_id=obj.get("customer"), org_id=obj.get("client_reference_id") or meta.get("org_id"))
        if sub:
            sub.stripe_customer_id = obj.get("customer") or sub.stripe_customer_id
            sub.stripe_subscription_id = obj.get("subscription") or sub.stripe_subscription_id
            if meta.get("plan_key") in PLANS:
                sub.plan_key = meta["plan_key"]
            if obj.get("payment_status") in ("paid", "no_payment_required"):
                sub.status = "active"
            sub.is_simulated = False
            _sync_org_plan(db, sub)
            result = "processed"
    elif etype in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        meta = obj.get("metadata") or {}
        sub = _find_sub(db, subscription_id=obj.get("id"), customer_id=obj.get("customer"), org_id=meta.get("org_id"))
        if sub:
            items = ((obj.get("items") or {}).get("data") or [])
            price_id = ((items[0].get("price") or {}).get("id")) if items else None
            plan_key = plan_for_price(price_id) or meta.get("plan_key")
            sub.stripe_subscription_id = obj.get("id")
            sub.stripe_customer_id = obj.get("customer") or sub.stripe_customer_id
            sub.status = "canceled" if etype.endswith("deleted") else (obj.get("status") or sub.status)
            if plan_key in PLANS:
                sub.plan_key = plan_key
            if etype.endswith("deleted"):
                sub.plan_key = "free"
            # Period fields moved onto subscription items in newer Stripe API versions.
            start = obj.get("current_period_start") or (items[0].get("current_period_start") if items else None)
            end = obj.get("current_period_end") or (items[0].get("current_period_end") if items else None)
            sub.current_period_start, sub.current_period_end = _ts(start), _ts(end)
            sub.cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
            sub.is_simulated = False
            _sync_org_plan(db, sub)
            result = "processed"
    elif etype == "invoice.payment_failed":
        sub = _find_sub(db, subscription_id=_invoice_sub(obj), customer_id=obj.get("customer"))
        if sub:
            sub.status = "past_due"
            err = ((obj.get("last_finalization_error") or {}).get("message")) or "Payment failed."
            sub.last_payment_error = err
            _sync_org_plan(db, sub)
            db.add(Notification(org_id=sub.org_id, kind="billing", title="Payment failed",
                                body="We could not charge your payment method. Paid features are paused until the "
                                     "invoice is paid. Update your card in the billing portal."))
            result = "processed"
    elif etype in ("invoice.paid", "invoice.payment_succeeded"):
        sub = _find_sub(db, subscription_id=_invoice_sub(obj), customer_id=obj.get("customer"))
        if sub:
            if sub.status in ("past_due", "unpaid", "incomplete"):
                sub.status = "active"
            sub.last_payment_error = None
            _sync_org_plan(db, sub)
            result = "processed"
    existing.status = result
    existing.processed_at = datetime.now(UTC)
    return result


def _invoice_sub(invoice: dict) -> str | None:
    if invoice.get("subscription"):
        return invoice["subscription"]
    parent = (invoice.get("parent") or {}).get("subscription_details") or {}
    return parent.get("subscription")
