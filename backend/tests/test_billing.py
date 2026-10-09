import hashlib
import hmac
import json
import time
import uuid

import pytest

from app.core.config import get_settings
from app.core.db import db_session
from app.models import Subscription


def _sig(payload: bytes, secret: str, ts: int | None = None) -> str:
    ts = ts or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


@pytest.fixture
def stripe_mode(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "billing_mode", "stripe")
    monkeypatch.setattr(s, "stripe_secret_key", "sk_test_dummy")
    monkeypatch.setattr(s, "stripe_webhook_secret", "whsec_test")
    monkeypatch.setattr(s, "stripe_price_pro", "price_pro_123")
    monkeypatch.setattr(s, "stripe_price_starter", "price_starter_123")


def _post_event(client, event: dict, secret="whsec_test", sig=None):
    payload = json.dumps(event).encode()
    return client.c.post("/api/billing/webhook", content=payload,
                         headers={"Stripe-Signature": sig or _sig(payload, secret), "Content-Type": "application/json"})


def test_free_plan_limits_enforced_server_side(alice):
    org = alice.org_id
    assert alice.post(f"/api/orgs/{org}/websites", {"url": "https://one.example.com"}).status_code == 200
    r = alice.post(f"/api/orgs/{org}/websites", {"url": "https://two.example.com"})
    assert r.status_code == 402 and r.json()["detail"]["code"] == "plan_limit"
    site = alice.get(f"/api/orgs/{org}/websites").json()[0]
    assert alice.patch(f"/api/orgs/{org}/websites/{site['id']}", {"schedule": "daily"}).status_code == 402
    assert alice.patch(f"/api/orgs/{org}/websites/{site['id']}", {"crawl_settings": {"render_js": True}}).status_code == 402


def test_crawl_quota(alice, monkeypatch):
    from app.tasks import dispatch

    monkeypatch.setattr(dispatch, "enqueue", lambda *a: None)
    import app.api.routes.websites as w

    monkeypatch.setattr(w, "enqueue", lambda *a: None)
    org = alice.org_id
    site = alice.post(f"/api/orgs/{org}/websites", {"url": "https://one.example.com"}).json()
    from app.models import CrawlRun, CrawlStatus

    for _ in range(3):
        assert alice.post(f"/api/orgs/{org}/websites/{site['id']}/crawls").status_code == 200
        with db_session() as s:  # finish it so the next one can start
            for r in s.query(CrawlRun).filter(CrawlRun.status == CrawlStatus.queued):
                r.status = CrawlStatus.completed
    r = alice.post(f"/api/orgs/{org}/websites/{site['id']}/crawls")
    assert r.status_code == 402


def test_dev_billing_mode_is_labelled(alice):
    org = alice.org_id
    r = alice.post(f"/api/orgs/{org}/billing/checkout", {"plan_key": "pro"})
    assert r.status_code == 200
    assert r.json()["simulated"] is True and "No real transaction" in r.json()["message"]
    b = alice.get(f"/api/orgs/{org}/billing").json()
    assert b["subscription"]["plan_key"] == "pro" and b["subscription"]["is_simulated"]
    assert b["usage"]["plan"]["key"] == "pro"
    # simulated failed payment drops entitlements to free
    alice.post(f"/api/orgs/{org}/billing/dev/simulate-payment-failure")
    b = alice.get(f"/api/orgs/{org}/billing").json()
    assert b["subscription"]["status"] == "past_due"
    assert b["usage"]["plan"]["key"] == "free"


def test_only_owner_manages_billing(alice, client_factory):
    from tests.conftest import set_plan

    set_plan(alice.org_id, "pro")
    tok = alice.post(f"/api/orgs/{alice.org_id}/invitations", {"email": "adm@example.com", "role": "admin"}).json()
    adm = client_factory().signup("adm@example.com")
    adm.post("/api/auth/invitations/accept", {"token": tok["invite_url"].rsplit("/", 1)[1]})
    assert adm.post(f"/api/orgs/{alice.org_id}/billing/checkout", {"plan_key": "agency"}).status_code == 403


def test_webhook_signature_required(alice, stripe_mode):
    event = {"id": "evt_1", "type": "invoice.paid", "data": {"object": {}}}
    assert _post_event(alice, event, secret="wrong").status_code == 400
    r = alice.c.post("/api/billing/webhook", content=b"{}")
    assert r.status_code == 400
    # replayed old signature (outside tolerance) rejected
    payload = json.dumps(event).encode()
    assert _post_event(alice, event, sig=_sig(payload, "whsec_test", ts=int(time.time()) - 3600)).status_code == 400


def test_webhook_lifecycle_and_idempotency(alice, stripe_mode):
    org = alice.org_id
    with db_session() as s:
        sub = s.query(Subscription).filter(Subscription.org_id == uuid.UUID(org)).one()
        sub.stripe_customer_id = "cus_1"
    completed = {"id": "evt_c", "type": "checkout.session.completed", "data": {"object": {
        "customer": "cus_1", "subscription": "sub_1", "client_reference_id": org, "payment_status": "paid",
        "metadata": {"org_id": org, "plan_key": "pro"}}}}
    r = _post_event(alice, completed)
    assert r.status_code == 200 and r.json()["result"] == "processed"
    assert _post_event(alice, completed).json()["result"] == "duplicate"
    now = int(time.time())
    updated = {"id": "evt_u", "type": "customer.subscription.updated", "data": {"object": {
        "id": "sub_1", "customer": "cus_1", "status": "active", "cancel_at_period_end": False,
        "items": {"data": [{"price": {"id": "price_starter_123"}, "current_period_start": now,
                            "current_period_end": now + 30 * 86400}]}, "metadata": {"org_id": org}}}}
    _post_event(alice, updated)
    b = alice.get(f"/api/orgs/{org}/billing").json()
    assert b["subscription"]["plan_key"] == "starter" and not b["subscription"]["is_simulated"]
    failed = {"id": "evt_f", "type": "invoice.payment_failed", "data": {"object": {"customer": "cus_1",
                                                                                   "subscription": "sub_1"}}}
    _post_event(alice, failed)
    b = alice.get(f"/api/orgs/{org}/billing").json()
    assert b["subscription"]["status"] == "past_due"
    assert b["usage"]["plan"]["key"] == "free"  # entitlements paused on failed payment
    paid = {"id": "evt_p", "type": "invoice.paid", "data": {"object": {"customer": "cus_1", "subscription": "sub_1"}}}
    _post_event(alice, paid)
    assert alice.get(f"/api/orgs/{org}/billing").json()["usage"]["plan"]["key"] == "starter"
    deleted = {"id": "evt_d", "type": "customer.subscription.deleted", "data": {"object": {
        "id": "sub_1", "customer": "cus_1", "status": "canceled", "items": {"data": []}}}}
    _post_event(alice, deleted)
    b = alice.get(f"/api/orgs/{org}/billing").json()
    assert b["subscription"]["plan_key"] == "free" and b["subscription"]["status"] == "canceled"
    unknown = {"id": "evt_x", "type": "customer.created", "data": {"object": {}}}
    assert _post_event(alice, unknown).json()["result"] == "ignored"


def test_checkout_in_stripe_mode_calls_stripe(alice, stripe_mode, monkeypatch):
    import stripe

    calls = {}
    monkeypatch.setattr(stripe.Customer, "create", lambda **kw: calls.setdefault("customer", kw) and {"id": "cus_9"})
    monkeypatch.setattr(stripe.checkout.Session, "create",
                        lambda **kw: calls.setdefault("session", kw) and {"url": "https://checkout.stripe.com/c/test"})
    r = alice.post(f"/api/orgs/{alice.org_id}/billing/checkout", {"plan_key": "pro"})
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.com")
    assert calls["session"]["line_items"] == [{"price": "price_pro_123", "quantity": 1}]
    assert calls["session"]["client_reference_id"] == alice.org_id
    # plan not active until webhook arrives
    assert alice.get(f"/api/orgs/{alice.org_id}/billing").json()["subscription"]["plan_key"] == "free"
