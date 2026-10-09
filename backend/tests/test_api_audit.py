from app.tasks.dispatch import wait_inline
from tests.conftest import crawl_site, set_plan
from tests.fixtures.demo_site import demo_site


def test_full_audit_via_api(alice, loopback):
    set_plan(alice.org_id, "pro")
    with demo_site() as site:
        res = crawl_site(alice, site.base)
    crawl = res["crawl"]
    assert crawl["status"] in ("completed", "partial"), crawl
    assert crawl["pages_crawled"] >= 6
    assert crawl["summary"]["scores"]["technical"] <= 100
    assert "disclaimer" in crawl["summary"]["scores"]
    org = alice.org_id
    issues = alice.get(f"/api/orgs/{org}/crawls/{crawl['id']}/issues?limit=500").json()
    assert issues["total"] > 10
    rules = {g["rule_id"] for g in issues["groups"]}
    assert {"tech.broken_internal_link", "tech.title_duplicate", "tech.jsonld_invalid"} <= rules
    # filter by type
    errs = alice.get(f"/api/orgs/{org}/crawls/{crawl['id']}/issues?finding_type=error").json()
    assert all(i["finding_type"] == "error" for i in errs["items"])
    # issue detail contains evidence and fix support info
    broken = next(i for i in issues["items"] if i["rule_id"] == "tech.broken_internal_link")
    d = alice.get(f"/api/orgs/{org}/issues/{broken['id']}").json()
    assert d["evidence"]["target_status"] == 404
    assert d["fix_support"]["fix_type"] == "internal_link_update"
    # pages and snapshots
    pages = alice.get(f"/api/orgs/{org}/crawls/{crawl['id']}/pages").json()
    assert pages["total"] >= 6
    p = next(x for x in pages["items"] if x["url"].endswith("/guides/pour-over"))
    pd = alice.get(f"/api/orgs/{org}/pages/{p['id']}").json()
    assert pd["snapshot"]["available"]
    snap = alice.get(f"/api/orgs/{org}/pages/{p['id']}/snapshot").json()
    assert "pour-over" in snap["html"].lower()
    # ignore an issue
    r = alice.patch(f"/api/orgs/{org}/issues/{broken['id']}", {"status": "ignored"})
    assert r.json()["status"] == "ignored"
    # exports
    for fmt, needle in (("csv", "severity"), ("json", '"issues"'), ("md", "# Audit report"), ("html", "<table>")):
        r = alice.get(f"/api/orgs/{org}/crawls/{crawl['id']}/export?format={fmt}")
        assert r.status_code == 200 and needle in r.text, fmt
        assert "attachment" in r.headers["content-disposition"]
    html = alice.get(f"/api/orgs/{org}/crawls/{crawl['id']}/export?format=html").text
    assert "<script>alert" not in html  # untrusted content escaped


def test_second_crawl_tracks_diff_and_ignored(alice, loopback):
    set_plan(alice.org_id, "pro")
    with demo_site() as site:
        first = crawl_site(alice, site.base)["crawl"]
        org = alice.org_id
        items = alice.get(f"/api/orgs/{org}/crawls/{first['id']}/issues?rule_id=tech.title_duplicate").json()["items"]
        alice.patch(f"/api/orgs/{org}/issues/{items[0]['id']}", {"status": "ignored"})
        # fix the duplicate title on /shop
        from tests.fixtures.site import page

        site.routes["/shop"] = (200, {}, page("Shop coffee beans", "<main><h1>Shop</h1><p>Our coffees.</p></main>"))
        second = crawl_site(alice, site.base)["crawl"]
    assert second["summary"]["diff"]["has_previous"]
    assert second["summary"]["diff"]["resolved"] >= 1
    statuses = {i["status"] for i in alice.get(
        f"/api/orgs/{org}/crawls/{first['id']}/issues?rule_id=tech.title_duplicate").json()["items"]}
    assert "fixed" in statuses or "ignored" in statuses


def test_public_quick_audit(client_factory, loopback):
    c = client_factory()
    with demo_site() as site:
        r = c.post("/api/public/audits", {"url": site.base + "/"})
        assert r.status_code == 200, r.text
        token = r.json()["token"]
        wait_inline(60)
        d = c.get(f"/api/public/audits/{token}").json()
    assert d["status"] in ("completed", "partial")
    assert d["pages_crawled"] <= 10
    assert d["issues"]
    assert c.get("/api/public/audits/not-a-real-token").status_code == 404
    assert c.get(f"/api/public/audits/{token}/export?format=csv").status_code == 200


def test_public_audit_blocks_internal_targets(client_factory):
    c = client_factory()
    for url in ("http://127.0.0.1/", "http://169.254.169.254/", "file:///etc/passwd", "http://localhost:8000"):
        assert c.post("/api/public/audits", {"url": url}).status_code == 422, url


def test_crawl_of_unreachable_site_fails_cleanly(alice, monkeypatch):
    import asyncio
    import socket

    async def fake(self, host, port, *a, **kw):
        raise socket.gaierror("nope")

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake)
    r = alice.post(f"/api/orgs/{alice.org_id}/websites", {"url": "https://does-not-exist.example.com"})
    w = r.json()
    r = alice.post(f"/api/orgs/{alice.org_id}/websites/{w['id']}/crawls")
    wait_inline(30)
    crawl = alice.get(f"/api/orgs/{alice.org_id}/crawls/{r.json()['id']}").json()
    assert crawl["status"] == "failed"
    assert crawl["error"]
