import json
import uuid

import pytest
from sqlalchemy import select

from app.ai.provider import get_provider
from app.core.db import db_session
from app.fixes import publisher
from app.models import Integration
from app.tasks.dispatch import wait_inline
from tests.conftest import crawl_site, set_plan
from tests.fixtures.fake_wordpress import APP_PASSWORD, FakeWordPress


@pytest.fixture
def wp(alice, loopback):
    set_plan(alice.org_id, "pro")
    get_provider().override = None
    with FakeWordPress() as fake:
        res = crawl_site(alice, fake.base)
        yield alice, fake, res


def connect(client, fake, website_id, password=APP_PASSWORD):
    return client.post(f"/api/orgs/{client.org_id}/integrations/wordpress/manual",
                       {"website_id": website_id, "username": "admin", "application_password": password})


def issue_for(client, crawl_id, rule_id, suffix="/about/"):
    items = client.get(f"/api/orgs/{client.org_id}/crawls/{crawl_id}/issues?rule_id={rule_id}&limit=100").json()["items"]
    return next(i for i in items if (i["url"] or "").endswith(suffix))


def test_connect_manual_and_capabilities(wp):
    alice, fake, res = wp
    r = connect(alice, fake, res["website"]["id"], password="wrong-password-123")
    assert r.status_code == 422 and "rejected the credentials" in r.json()["detail"]
    r = connect(alice, fake, res["website"]["id"])
    assert r.status_code == 200, r.text
    integ = r.json()
    assert integ["status"] == "connected"
    caps = integ["capabilities"]
    assert caps["set_title"]["supported"] and caps["set_title"]["rollback"]
    assert not caps["set_meta_description"]["supported"]
    assert "meta description" in caps["set_meta_description"]["reason"]
    assert not caps["create_redirect"]["supported"]
    # Secrets never leave the backend and are encrypted at rest.
    assert APP_PASSWORD not in json.dumps(integ)
    assert APP_PASSWORD not in alice.get(f"/api/orgs/{alice.org_id}/integrations").text
    with db_session() as s:
        row = s.get(Integration, uuid.UUID(integ["id"]))
        assert APP_PASSWORD not in row.encrypted_credentials


def test_publish_verify_rollback_title(wp):
    alice, fake, res = wp
    org = alice.org_id
    connect(alice, fake, res["website"]["id"])
    issue = issue_for(alice, res["crawl"]["id"], "tech.title_short")
    get_provider().override = {"title": "About Bean There: Halifax Coffee Roasters", "rationale": "x",
                               "insufficient_information": False}
    fix = alice.post(f"/api/orgs/{org}/issues/{issue['id']}/fixes").json()
    assert fix["status"] == "drafted", fix["error"]
    assert fix["direct_apply_supported"], fix["apply_unsupported_reason"]
    alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/submit")
    alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/approve")
    r = alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/apply")
    assert r.status_code == 200, r.text
    wait_inline()
    d = alice.get(f"/api/orgs/{org}/fixes/{fix['id']}").json()
    assert d["status"] == "verified", (d["error"], d["verification_result"])
    assert d["original_state"]["title"] == "About"
    assert fake.pages[12]["title"] == "About Bean There: Halifax Coffee Roasters"
    statuses = [h["to_status"] for h in d["history"]]
    assert statuses[-3:] == ["applying", "verifying", "verified"]

    r = alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/rollback")
    assert r.status_code == 200
    wait_inline()
    d = alice.get(f"/api/orgs/{org}/fixes/{fix['id']}").json()
    assert d["status"] == "rolled_back"
    assert fake.pages[12]["title"] == "About"


def test_api_accepts_but_live_page_unchanged_is_not_verified(wp, monkeypatch):
    alice, fake, res = wp
    org = alice.org_id
    connect(alice, fake, res["website"]["id"])
    fake.stale = True  # CDN keeps serving the old HTML
    issue = issue_for(alice, res["crawl"]["id"], "tech.title_short")
    get_provider().override = {"title": "About Bean There: Halifax Coffee Roasters", "rationale": "",
                               "insufficient_information": False}
    fix = alice.post(f"/api/orgs/{org}/issues/{issue['id']}/fixes").json()
    alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/submit")
    alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/approve")
    alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/apply")
    wait_inline()
    d = alice.get(f"/api/orgs/{org}/fixes/{fix['id']}").json()
    assert fake.writes, "provider accepted the write"
    assert d["status"] == "verifying"
    assert d["verification_result"]["passed"] is False
    for _ in range(publisher.MAX_VERIFY_ATTEMPTS):
        publisher.verify_pending()
    d = alice.get(f"/api/orgs/{org}/fixes/{fix['id']}").json()
    assert d["status"] == "failed"
    assert "not visible on the live page" in d["error"]


def test_rollback_conflict_detected(wp):
    alice, fake, res = wp
    org = alice.org_id
    connect(alice, fake, res["website"]["id"])
    issue = issue_for(alice, res["crawl"]["id"], "tech.title_short")
    get_provider().override = {"title": "About Bean There: Halifax Coffee Roasters", "rationale": "",
                               "insufficient_information": False}
    fix = alice.post(f"/api/orgs/{org}/issues/{issue['id']}/fixes").json()
    for step in ("submit", "approve", "apply"):
        alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/{step}")
    wait_inline()
    fake.pages[12]["title"] = "Edited later by a human"
    alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/rollback")
    wait_inline()
    d = alice.get(f"/api/orgs/{org}/fixes/{fix['id']}").json()
    assert d["status"] == "verified"
    assert "changed after this fix was applied" in d["error"]
    assert fake.pages[12]["title"] == "Edited later by a human"


def test_content_ops_alt_link_answer(wp):
    alice, fake, res = wp
    org = alice.org_id
    connect(alice, fake, res["website"]["id"])
    # image alt
    issue = issue_for(alice, res["crawl"]["id"], "tech.img_alt_missing")
    get_provider().override = {"alt": "Single-origin coffee beans", "is_decorative": False, "rationale": "",
                               "insufficient_information": False}
    fix = alice.post(f"/api/orgs/{org}/issues/{issue['id']}/fixes").json()
    assert fix["status"] == "drafted", fix["error"]
    for step in ("submit", "approve", "apply"):
        assert alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/{step}").status_code == 200
    wait_inline()
    d = alice.get(f"/api/orgs/{org}/fixes/{fix['id']}").json()
    assert d["status"] == "verified", (d["error"], d["verification_result"])
    assert 'alt="Single-origin coffee beans"' in fake.pages[12]["content"]
    assert fake.media[7]["alt_text"] == "Single-origin coffee beans"
    assert "<!-- wp:image -->" in fake.pages[12]["content"]  # block structure preserved

    # answer paragraph under the question heading
    issue = issue_for(alice, res["crawl"]["id"], "aeo.question_unanswered") if any(
        i["rule_id"] == "aeo.question_unanswered" for i in alice.get(
            f"/api/orgs/{org}/crawls/{res['crawl']['id']}/issues?limit=500").json()["items"]) else None
    if issue:
        get_provider().override = {"answer_html": "<p>We use single-origin beans from Colombia and Ethiopia.</p>",
                                   "rationale": "", "insufficient_information": False}
        fix = alice.post(f"/api/orgs/{org}/issues/{issue['id']}/fixes").json()
        for step in ("submit", "approve", "apply"):
            alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/{step}")
        wait_inline()
        d = alice.get(f"/api/orgs/{org}/fixes/{fix['id']}").json()
        assert d["status"] == "verified", (d["error"], d["verification_result"])


def test_unsupported_operation_never_attempted(wp):
    alice, fake, res = wp
    org = alice.org_id
    connect(alice, fake, res["website"]["id"])
    issue = issue_for(alice, res["crawl"]["id"], "tech.meta_description_missing")
    get_provider().override = {"description": "We roast coffee in Halifax since 2015 and buy single-origin beans "
                                              "from Colombia and Ethiopia.", "rationale": "", "insufficient_information": False}
    fix = alice.post(f"/api/orgs/{org}/issues/{issue['id']}/fixes").json()
    assert fix["status"] == "drafted", fix["error"]
    assert not fix["direct_apply_supported"]
    assert "meta description" in fix["apply_unsupported_reason"]
    alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/submit")
    alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/approve")
    n = len(fake.writes)
    assert alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/apply").status_code == 422
    assert len(fake.writes) == n


def test_insufficient_wp_role(alice, loopback):
    set_plan(alice.org_id, "pro")
    with FakeWordPress(editor_caps=False) as fake:
        res = crawl_site(alice, fake.base)
        integ = connect(alice, fake, res["website"]["id"]).json()
    assert integ["status"] == "connected"
    assert not integ["capabilities"]["set_title"]["supported"]
    assert "Editor or Administrator" in integ["capabilities"]["set_title"]["reason"]


def test_authorization_flow_callback(wp, monkeypatch):
    alice, fake, res = wp
    from app.integrations.wordpress import WordPressConnector

    r = alice.post(f"/api/orgs/{alice.org_id}/integrations/wordpress/start", {"website_id": res["website"]["id"]})
    assert r.status_code == 422 and "HTTPS" in r.json()["detail"]  # fixture site is http
    monkeypatch.setattr(WordPressConnector, "authorization_url",
                        lambda self, endpoint, **kw: endpoint + "?success_url=" + kw["success_url"])
    r = alice.post(f"/api/orgs/{alice.org_id}/integrations/wordpress/start", {"website_id": res["website"]["id"]})
    assert r.status_code == 200, r.text
    from urllib.parse import parse_qs, urlsplit

    success = r.json()["authorization_url"].split("success_url=", 1)[1]
    state = parse_qs(urlsplit(success).query)["state"][0]
    # Wrong state is rejected
    bad = alice.get("/api/integrations/wordpress/callback?state=nope&user_login=admin&password=x", follow_redirects=False)
    assert bad.status_code == 400
    ok = alice.get(f"/api/integrations/wordpress/callback?state={state}&site_url={fake.base}&user_login=admin"
                   f"&password={APP_PASSWORD}", follow_redirects=False)
    assert ok.status_code == 303 and "result=connected" in ok.headers["location"]
    # State is single use
    again = alice.get(f"/api/integrations/wordpress/callback?state={state}&user_login=admin&password=x", follow_redirects=False)
    assert again.status_code == 400
    with db_session() as s:
        rows = s.scalars(select(Integration).where(Integration.status == "connected")).all()
        assert len(rows) == 1


def test_disconnect_deletes_credentials(wp):
    alice, fake, res = wp
    integ = connect(alice, fake, res["website"]["id"]).json()
    r = alice.delete(f"/api/orgs/{alice.org_id}/integrations/{integ['id']}")
    assert r.json()["status"] == "disconnected"
    with db_session() as s:
        assert s.get(Integration, uuid.UUID(integ["id"])).encrypted_credentials is None


def test_publish_preflight_rejects_unmapped_url(wp):
    """The homepage of the fake site is not a WP post/page: publishing is refused up front, state unchanged."""
    alice, fake, res = wp
    org = alice.org_id
    connect(alice, fake, res["website"]["id"])
    issue = issue_for(alice, res["crawl"]["id"], "tech.title_short", suffix=f":{fake.site.port}/")
    get_provider().override = {"title": "Bean There Coffee Roasters Home", "rationale": "", "insufficient_information": False}
    fix = alice.post(f"/api/orgs/{org}/issues/{issue['id']}/fixes").json()
    alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/submit")
    alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/approve")
    n = len(fake.writes)
    r = alice.post(f"/api/orgs/{org}/fixes/{fix['id']}/apply")
    assert r.status_code == 422 and "could not be matched" in r.json()["detail"]
    assert alice.get(f"/api/orgs/{org}/fixes/{fix['id']}").json()["status"] == "approved"
    assert len(fake.writes) == n
    usage = alice.get(f"/api/orgs/{org}/billing").json()["usage"]["metrics"]["publish_ops"]["used"]
    assert usage == 0
