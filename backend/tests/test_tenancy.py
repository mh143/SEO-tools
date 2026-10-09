"""Cross-tenant access attempts: Bob must not read or modify anything belonging to Alice's org."""

from app.ai.provider import get_provider
from tests.conftest import crawl_site, set_plan
from tests.fixtures.fake_wordpress import APP_PASSWORD, FakeWordPress


def test_cross_tenant_isolation(alice, bob, loopback):
    set_plan(alice.org_id, "pro")
    get_provider().override = None
    with FakeWordPress() as fake:
        res = crawl_site(alice, fake.base)
        a = alice.org_id
        crawl_id = res["crawl"]["id"]
        site_id = res["website"]["id"]
        integ = alice.post(f"/api/orgs/{a}/integrations/wordpress/manual",
                           {"website_id": site_id, "username": "admin", "application_password": APP_PASSWORD}).json()
        issues = alice.get(f"/api/orgs/{a}/crawls/{crawl_id}/issues?limit=200").json()["items"]
        issue = next(i for i in issues if i["fix_type"] == "meta_title")
        fix = alice.post(f"/api/orgs/{a}/issues/{issue['id']}/fixes").json()
        page_id = alice.get(f"/api/orgs/{a}/crawls/{crawl_id}/pages").json()["items"][0]["id"]
        alice.post(f"/api/orgs/{a}/websites/{site_id}/keywords/on-page")
        kw = alice.get(f"/api/orgs/{a}/websites/{site_id}/keywords").json()["keywords"][0]

    b = bob.org_id
    # 1) Using Alice's org id directly
    for path in [f"/api/orgs/{a}", f"/api/orgs/{a}/overview", f"/api/orgs/{a}/websites", f"/api/orgs/{a}/fixes",
                 f"/api/orgs/{a}/crawls/{crawl_id}", f"/api/orgs/{a}/issues/{issue['id']}", f"/api/orgs/{a}/billing",
                 f"/api/orgs/{a}/integrations", f"/api/orgs/{a}/changes", f"/api/orgs/{a}/members",
                 f"/api/orgs/{a}/crawls/{crawl_id}/export?format=csv"]:
        assert bob.get(path).status_code == 404, path
    # 2) Using Bob's own org id with Alice's resource ids (IDOR)
    for path in [f"/api/orgs/{b}/websites/{site_id}", f"/api/orgs/{b}/crawls/{crawl_id}",
                 f"/api/orgs/{b}/crawls/{crawl_id}/issues", f"/api/orgs/{b}/crawls/{crawl_id}/pages",
                 f"/api/orgs/{b}/issues/{issue['id']}", f"/api/orgs/{b}/fixes/{fix['id']}",
                 f"/api/orgs/{b}/pages/{page_id}", f"/api/orgs/{b}/pages/{page_id}/snapshot",
                 f"/api/orgs/{b}/websites/{site_id}/keywords", f"/api/orgs/{b}/fixes/{fix['id']}/export",
                 f"/api/orgs/{b}/crawls/{crawl_id}/export?format=json"]:
        assert bob.get(path).status_code == 404, path
    writes = [
        ("post", f"/api/orgs/{b}/websites/{site_id}/crawls", None),
        ("patch", f"/api/orgs/{b}/websites/{site_id}", {"name": "pwned"}),
        ("delete", f"/api/orgs/{b}/websites/{site_id}", None),
        ("post", f"/api/orgs/{b}/issues/{issue['id']}/fixes", None),
        ("patch", f"/api/orgs/{b}/issues/{issue['id']}", {"status": "ignored"}),
        ("patch", f"/api/orgs/{b}/fixes/{fix['id']}", {"after": {"title": "pwned title here"}}),
        ("post", f"/api/orgs/{b}/fixes/{fix['id']}/approve", None),
        ("post", f"/api/orgs/{b}/fixes/{fix['id']}/apply", None),
        ("post", f"/api/orgs/{b}/fixes/{fix['id']}/rollback", None),
        ("post", f"/api/orgs/{b}/crawls/{crawl_id}/cancel", None),
        ("delete", f"/api/orgs/{b}/integrations/{integ['id']}", None),
        ("post", f"/api/orgs/{b}/integrations/{integ['id']}/refresh", None),
        ("post", f"/api/orgs/{b}/integrations/wordpress/manual",
         {"website_id": site_id, "username": "admin", "application_password": APP_PASSWORD}),
        ("delete", f"/api/orgs/{b}/keywords/{kw['id']}", None),
        ("post", f"/api/orgs/{a}/websites", {"url": "https://example.com"}),
        ("post", f"/api/orgs/{a}/invitations", {"email": "bob@example.com", "role": "owner"}),
    ]
    for method, path, body in writes:
        fn = getattr(bob, method)
        r = fn(path, body) if body is not None else fn(path)
        assert r.status_code in (404, 422), (method, path, r.status_code)
    # Alice's data is untouched
    assert alice.get(f"/api/orgs/{a}/websites/{site_id}").json()["name"] != "pwned"
    assert alice.get(f"/api/orgs/{a}/fixes/{fix['id']}").json()["status"] == fix["status"]
    assert alice.get(f"/api/orgs/{a}/integrations").json()[0]["status"] == "connected"
    # Bob's lists are empty
    assert bob.get(f"/api/orgs/{b}/fixes").json() == []
    assert bob.get(f"/api/orgs/{b}/changes").json() == []


def test_unauthenticated_access_denied(client_factory, alice):
    anon = client_factory()
    for path in (f"/api/orgs/{alice.org_id}", f"/api/orgs/{alice.org_id}/websites", "/api/auth/me", "/api/admin/overview"):
        assert anon.get(path).status_code == 401, path


def test_admin_dashboard_requires_platform_admin(alice, monkeypatch, client_factory):
    assert alice.get("/api/admin/overview").status_code == 404
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "bootstrap_admin_email", "root@example.com")
    root = client_factory().signup("root@example.com")
    r = root.get("/api/admin/overview")
    assert r.status_code == 200 and r.json()["users"] >= 2
    assert root.get("/api/admin/organizations").status_code == 200
