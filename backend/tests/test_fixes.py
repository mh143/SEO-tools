import pytest

from app.ai.provider import get_provider
from app.tasks.dispatch import wait_inline
from tests.conftest import crawl_site, set_plan
from tests.fixtures.demo_site import demo_site


@pytest.fixture
def audited(alice, loopback):
    set_plan(alice.org_id, "pro")
    with demo_site() as site:
        res = crawl_site(alice, site.base)
        yield alice, res, site


def _issue(client, crawl_id, rule_id, url_suffix=None):
    items = client.get(f"/api/orgs/{client.org_id}/crawls/{crawl_id}/issues?rule_id={rule_id}&limit=100").json()["items"]
    if url_suffix:
        items = [i for i in items if (i["url"] or "").endswith(url_suffix)]
    return items[0]


@pytest.fixture(autouse=True)
def reset_mock():
    get_provider().override = None
    yield
    get_provider().override = None


def test_ai_fix_lifecycle_and_permissions(audited, client_factory):
    alice, res, site = audited
    org = alice.org_id
    issue = _issue(alice, res["crawl"]["id"], "tech.title_duplicate", "/shop")
    r = alice.post(f"/api/orgs/{org}/issues/{issue['id']}/fixes")
    assert r.status_code == 200, r.text
    fix = r.json()
    assert fix["status"] == "drafted", (fix["error"], fix["validation"])
    assert fix["generator"] == "ai:mock"
    assert fix["before"]["title"] == "Bean There Coffee"
    assert fix["after"]["title"]
    assert not fix["direct_apply_supported"]
    assert "No publishing integration" in fix["apply_unsupported_reason"]
    assert [h["to_status"] for h in fix["history"]] == ["detected", "analyzed", "drafted"]

    # editing restricted to allowed fields
    bad = alice.patch(f"/api/orgs/{org}/fixes/{fix['id']}", {"after": {"description": "nope"}})
    assert bad.status_code == 422
    bad = alice.patch(f"/api/orgs/{org}/fixes/{fix['id']}", {"after": {"title": "<b>x</b>"}})
    assert bad.status_code == 422
    ok = alice.patch(f"/api/orgs/{org}/fixes/{fix['id']}", {"after": {"title": "Shop Small-Batch Coffee"}})
    assert ok.json()["after"]["title"] == "Shop Small-Batch Coffee"

    # cannot apply before approval; cannot verify-mark as verified
    assert alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/apply").status_code == 409
    alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/submit")
    r = alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/approve")
    assert r.json()["status"] == "approved" and r.json()["approved_by"]
    # no integration -> 422 with reason
    r = alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/apply")
    assert r.status_code == 422

    # Mark as applied manually -> verification fails because the live page did not change
    r = alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/mark-applied")
    assert r.json()["status"] == "externally_applied_unverified"
    wait_inline()
    d = alice.get(f"/api/orgs/{org}/fixes/{fix['id']}").json()
    assert d["status"] == "verifying"  # NOT verified
    assert d["verification_result"]["passed"] is False

    # Now actually change the site and re-verify -> verified
    from tests.fixtures.site import page

    site.routes["/shop"] = (200, {}, page("Shop Small-Batch Coffee", "<main><h1>Shop</h1></main>"))
    alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/verify")
    wait_inline()
    d = alice.get(f"/api/orgs/{org}/fixes/{fix['id']}").json()
    assert d["status"] == "verified", d["verification_result"]
    assert d["verified_at"]
    # exports
    assert "Shop Small-Batch Coffee" in alice.get(f"/api/orgs/{org}/fixes/{fix['id']}/export?format=txt").text
    assert alice.get(f"/api/orgs/{org}/fixes-export?format=csv").status_code == 200
    changes = alice.get(f"/api/orgs/{org}/changes").json()
    assert any(c["to_status"] == "verified" for c in changes)


def test_rejected_ai_output_is_never_drafted(audited):
    alice, res, _ = audited
    org = alice.org_id
    issue = _issue(alice, res["crawl"]["id"], "tech.meta_description_missing")
    get_provider().override = {"description": "Award-winning roaster with 500 5-star reviews since 1999. Call now!",
                               "rationale": "", "insufficient_information": False}
    fix = alice.post(f"/api/orgs/{org}/issues/{issue['id']}/fixes").json()
    assert fix["status"] == "analyzed"
    assert fix["after"] == {}
    assert "not found on the page" in fix["error"]
    assert alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/submit").status_code in (409, 422)

    get_provider().override = {"description": "ok", "evil_field": "x", "rationale": "", "insufficient_information": False}
    fix = alice.post(f"/api/orgs/{org}/issues/{issue['id']}/fixes").json()
    assert fix["status"] == "analyzed" and "not permitted" in fix["error"]


def test_prompt_injection_page_does_not_reach_output(audited):
    alice, res, site = audited
    # The /widgets page contains hidden "ignore all previous instructions" text; it is never in main_text.
    from sqlalchemy import select

    from app.core.db import db_session
    from app.models import Page

    with db_session() as s:
        pages = s.scalars(select(Page).where(Page.url.like("%/widgets"))).all()
        for p in pages:
            assert "ignore all previous" not in (p.extracted.get("main_text") or "").lower()


def test_rule_based_fix_for_redirect_link(audited):
    alice, res, _ = audited
    issue = _issue(alice, res["crawl"]["id"], "tech.link_to_redirect")
    fix = alice.post(f"/api/orgs/{alice.org_id}/issues/{issue['id']}/fixes").json()
    assert fix["generator"] == "rule" and fix["status"] == "drafted"
    assert fix["after"]["new_href"].endswith("/shop")
    assert fix["confidence"] == "high"


def test_viewer_and_editor_permissions(audited, client_factory):
    alice, res, _ = audited
    org = alice.org_id
    r = alice.post(f"/api/orgs/{org}/invitations", {"email": "ed@example.com", "role": "editor"})
    token = r.json()["invite_url"].rsplit("/", 1)[1]
    ed = client_factory().signup("ed@example.com")
    ed.post("/api/auth/invitations/accept", {"token": token})
    ed.user = ed.get("/api/auth/me").json()["user"]
    issue = _issue(alice, res["crawl"]["id"], "tech.title_duplicate")
    fix = ed.post(f"/api/orgs/{org}/issues/{issue['id']}/fixes").json()
    assert ed.post(f"/api/orgs/{org}/fixes/{fix['id']}/submit").status_code == 200
    assert ed.post(f"/api/orgs/{org}/fixes/{fix['id']}/approve").status_code == 403
    assert ed.post(f"/api/orgs/{org}/fixes/{fix['id']}/apply").status_code == 403


def test_ai_limit_enforced(audited):
    alice, res, _ = audited
    set_plan(alice.org_id, "free")
    issue = _issue(alice, res["crawl"]["id"], "tech.title_duplicate")
    codes = [alice.post(f"/api/orgs/{alice.org_id}/issues/{issue['id']}/fixes").status_code for _ in range(12)]
    assert codes[:10] == [200] * 10
    assert codes[10] == 402
