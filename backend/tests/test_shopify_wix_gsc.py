"""Contract tests for the Shopify and Wix publishing connectors and Google Search Console data."""

import json
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest

from app.ai.provider import get_provider
from app.core.config import get_settings
from app.core.db import db_session
from app.integrations import registry, search_console
from app.integrations.base import ConnectorError
from app.integrations.shopify import ShopifyConnector, normalize_shop
from app.integrations.wix import WixConnector
from app.models import Integration
from app.tasks.dispatch import wait_inline
from tests.conftest import crawl_site, set_plan
from tests.fixtures.fake_shopify import TOKEN, FakeShopify
from tests.fixtures.fake_wix import API_KEY, SITE_ID, FakeWix
from tests.fixtures.site import FixtureSite


def issues(client, crawl_id, rule_id):
    return client.get(f"/api/orgs/{client.org_id}/crawls/{crawl_id}/issues?rule_id={rule_id}&limit=100").json()["items"]


def publish(client, fix_id):
    for step in ("submit", "approve", "apply"):
        r = client.post(f"/api/orgs/{client.org_id}/fixes/{fix_id}/{step}")
        assert r.status_code == 200, (step, r.text)
    wait_inline()
    return client.get(f"/api/orgs/{client.org_id}/fixes/{fix_id}").json()


# ------------------------------------------------------------------------------------ Shopify
@pytest.fixture
def shop(alice, loopback):
    set_plan(alice.org_id, "pro")
    get_provider().override = None
    with FakeShopify() as fake:
        registry._override["shopify"] = ShopifyConnector(endpoint_for=fake.endpoint_for)
        res = crawl_site(alice, fake.base)
        yield alice, fake, res
    registry._override.pop("shopify", None)


def shopify_connect(client, website_id, token=TOKEN):
    return client.post(f"/api/orgs/{client.org_id}/integrations/shopify",
                       {"website_id": website_id, "shop": "bean-there", "access_token": token})


def test_shop_domain_validation():
    assert normalize_shop("Bean-There") == "bean-there.myshopify.com"
    assert normalize_shop("https://bean-there.myshopify.com/admin") == "bean-there.myshopify.com"
    for bad in ("evil.com", "127.0.0.1", "a.myshopify.com.evil.com", ""):
        with pytest.raises(ConnectorError):
            normalize_shop(bad)


def test_shopify_connect_and_capabilities(shop):
    alice, fake, res = shop
    r = shopify_connect(alice, res["website"]["id"], token="shpat_wrong_token_000")
    assert r.status_code == 422 and "rejected the credentials" in r.json()["detail"]
    r = shopify_connect(alice, res["website"]["id"])
    assert r.status_code == 200, r.text
    integ = r.json()
    assert integ["provider"] == "shopify" and integ["status"] == "connected"
    caps = integ["capabilities"]
    for op in ("set_title", "set_meta_description", "set_image_alt", "create_redirect"):
        assert caps[op]["supported"] and caps[op]["rollback"], op
    assert not caps["set_canonical"]["supported"] and "theme" in caps["set_canonical"]["reason"]
    assert TOKEN not in json.dumps(integ) and TOKEN not in alice.get(f"/api/orgs/{alice.org_id}/integrations").text
    with db_session() as s:
        assert TOKEN not in s.get(Integration, uuid.UUID(integ["id"])).encrypted_credentials


def test_shopify_meta_description_publish_verify_rollback(shop):
    alice, fake, res = shop
    shopify_connect(alice, res["website"]["id"])
    issue = next(i for i in issues(alice, res["crawl"]["id"], "tech.meta_description_missing")
                 if i["url"].endswith("/products/cold-brew"))
    desc = "Cold brew coffee slow-steeped for 18 hours in Halifax for a smooth, low-acid cup you can enjoy all day."
    get_provider().override = {"description": desc, "rationale": "", "insufficient_information": False}
    fix = alice.post(f"/api/orgs/{alice.org_id}/issues/{issue['id']}/fixes").json()
    assert fix["direct_apply_supported"], fix["apply_unsupported_reason"]
    d = publish(alice, fix["id"])
    assert d["status"] == "verified", (d["error"], d["verification_result"])
    assert fake.products["gid://shopify/Product/1"]["seo_description"] == desc
    alice.post(f"/api/orgs/{alice.org_id}/fixes/{fix['id']}/rollback")
    wait_inline()
    d = alice.get(f"/api/orgs/{alice.org_id}/fixes/{fix['id']}").json()
    assert d["status"] == "rolled_back", d["error"]
    assert fake.products["gid://shopify/Product/1"]["seo_description"] == ""


def test_shopify_seo_title_on_page_uses_metafield(shop):
    alice, fake, res = shop
    shopify_connect(alice, res["website"]["id"])
    issue = next(i for i in issues(alice, res["crawl"]["id"], "tech.title_short") if i["url"].endswith("/pages/about"))
    get_provider().override = {"title": "About Bean There: Halifax Coffee Roasters", "rationale": "",
                               "insufficient_information": False}
    fix = alice.post(f"/api/orgs/{alice.org_id}/issues/{issue['id']}/fixes").json()
    d = publish(alice, fix["id"])
    assert d["status"] == "verified", (d["error"], d["verification_result"])
    page = fake.pages["gid://shopify/Page/5"]
    assert page["seo_title"] == "About Bean There: Halifax Coffee Roasters"
    assert page["title"] == "About"  # the visible heading is untouched by a <title> fix


def test_shopify_redirect_for_broken_url(shop):
    alice, fake, res = shop
    shopify_connect(alice, res["website"]["id"])
    issue = next(i for i in issues(alice, res["crawl"]["id"], "tech.http_error") if i["url"].endswith("/products/discontinued"))
    fix = alice.post(f"/api/orgs/{alice.org_id}/issues/{issue['id']}/fixes").json()
    target = fake.base + "/products/cold-brew"
    r = alice.patch(f"/api/orgs/{alice.org_id}/fixes/{fix['id']}",
                    {"after": {"from_url": issue["url"], "to_url": target, "status": 301}})
    assert r.status_code == 200, r.text
    assert r.json()["direct_apply_supported"], r.json()["apply_unsupported_reason"]
    d = publish(alice, fix["id"])
    assert d["status"] == "verified", (d["error"], d["verification_result"])
    assert fake.redirects["/products/discontinued"]["target"] == "/products/cold-brew"
    alice.post(f"/api/orgs/{alice.org_id}/fixes/{fix['id']}/rollback")
    wait_inline()
    d = alice.get(f"/api/orgs/{alice.org_id}/fixes/{fix['id']}").json()
    assert d["status"] == "rolled_back" and not fake.redirects and d["error"] is None


def test_shopify_missing_scope_declared(alice, loopback):
    set_plan(alice.org_id, "pro")
    with FakeShopify(scopes=("read_products",)) as fake:
        registry._override["shopify"] = ShopifyConnector(endpoint_for=fake.endpoint_for)
        try:
            res = crawl_site(alice, fake.base)
            integ = shopify_connect(alice, res["website"]["id"]).json()
        finally:
            registry._override.pop("shopify", None)
    assert not integ["capabilities"]["set_title"]["supported"]
    assert "write_products" in integ["capabilities"]["set_title"]["reason"]
    assert not integ["capabilities"]["create_redirect"]["supported"]


# ------------------------------------------------------------------------------------ Wix
@pytest.fixture
def wix(alice, loopback):
    set_plan(alice.org_id, "pro")
    get_provider().override = None
    with FakeWix() as fake:
        registry._override["wix"] = WixConnector(api_base=fake.base)
        res = crawl_site(alice, fake.base)
        yield alice, fake, res
    registry._override.pop("wix", None)


def wix_connect(client, website_id, key=API_KEY):
    return client.post(f"/api/orgs/{client.org_id}/integrations/wix",
                       {"website_id": website_id, "site_id": SITE_ID, "api_key": key})


def test_wix_connect_publish_and_rollback(wix):
    alice, fake, res = wix
    assert wix_connect(alice, res["website"]["id"], key="IST.wrong-key-000000000").status_code == 422
    integ = wix_connect(alice, res["website"]["id"]).json()
    assert integ["status"] == "connected", integ
    caps = integ["capabilities"]
    assert caps["set_title"]["supported"] and caps["set_meta_description"]["supported"]
    assert not caps["content_append"]["supported"] and "Ricos" in caps["content_append"]["reason"]
    assert API_KEY not in alice.get(f"/api/orgs/{alice.org_id}/integrations").text

    issue = next(i for i in issues(alice, res["crawl"]["id"], "tech.meta_description_missing")
                 if i["url"].endswith("/product-page/house-blend"))
    desc = "Our house blend: chocolatey, balanced and roasted weekly in Halifax for espresso and filter brewing."
    get_provider().override = {"description": desc, "rationale": "", "insufficient_information": False}
    fix = alice.post(f"/api/orgs/{alice.org_id}/issues/{issue['id']}/fixes").json()
    assert fix["direct_apply_supported"], fix["apply_unsupported_reason"]
    d = publish(alice, fix["id"])
    assert d["status"] == "verified", (d["error"], d["verification_result"])
    assert fake.products["x9"]["seoData"]["tags"][0]["props"]["content"] == desc

    issue = next(i for i in issues(alice, res["crawl"]["id"], "tech.title_short") if i["url"].endswith("/post/brewing-guide"))
    get_provider().override = {"title": "Coffee Brewing Guide: Pour-Over, French Press & Espresso", "rationale": "",
                               "insufficient_information": False}
    fix = alice.post(f"/api/orgs/{alice.org_id}/issues/{issue['id']}/fixes").json()
    d = publish(alice, fix["id"])
    assert d["status"] == "verified", (d["error"], d["verification_result"])
    alice.post(f"/api/orgs/{alice.org_id}/fixes/{fix['id']}/rollback")
    wait_inline()
    d = alice.get(f"/api/orgs/{alice.org_id}/fixes/{fix['id']}").json()
    assert d["status"] == "rolled_back", d["error"]
    assert fake.posts["p1"]["seoData"]["tags"][0]["children"] == ""


# ------------------------------------------------------------------------------------ Search Console
class FakeGoogle:
    def __init__(self, sites):
        self.sites = sites
        self.site = FixtureSite({"*": self._route})
        self.queries = []

    def __enter__(self):
        self.site.__enter__()
        return self

    def __exit__(self, *exc):
        self.site.__exit__(*exc)

    def _json(self, d, status=200):
        return status, {"Content-Type": "application/json"}, json.dumps(d)

    def _route(self, h):
        path = urlsplit(h.path).path
        if path == "/token":
            form = parse_qs(h.body.decode())
            if form["grant_type"] == ["authorization_code"]:
                if form["code"] != ["good-code"]:
                    return self._json({"error": "invalid_grant"}, 400)
                return self._json({"access_token": "at-1", "refresh_token": "rt-secret-123", "expires_in": 3599})
            return self._json({"access_token": "at-2", "expires_in": 3599})
        if h.headers.get("Authorization", "").startswith("Bearer ") is False:
            return self._json({"error": {"message": "unauthenticated"}}, 401)
        if path == "/webmasters/v3/sites":
            return self._json({"siteEntry": self.sites})
        if path.endswith("/searchAnalytics/query"):
            body = json.loads(h.body)
            self.queries.append((path, body))
            dim = body["dimensions"][0]
            if dim == "date":
                rows = [{"keys": ["2026-10-01"], "clicks": 10, "impressions": 200, "ctr": 0.05, "position": 8.0},
                        {"keys": ["2026-10-02"], "clicks": 30, "impressions": 200, "ctr": 0.15, "position": 4.0}]
            elif dim == "query":
                rows = [{"keys": ["cold brew halifax"], "clicks": 25, "impressions": 150, "ctr": 0.1667, "position": 3.2}]
            else:
                rows = [{"keys": ["https://127.0.0.1/products/cold-brew"], "clicks": 40, "impressions": 400,
                         "ctr": 0.1, "position": 6.0}]
            return self._json({"rows": rows})
        return self._json({"error": "not found"}, 404)


def test_matching_properties():
    sites = [{"siteUrl": "sc-domain:example.com"}, {"siteUrl": "https://www.example.com/"},
             {"siteUrl": "https://other.com/"}]
    assert search_console.matching_properties(sites, "shop.example.com") == ["sc-domain:example.com"]
    assert search_console.matching_properties(sites, "example.com") == ["sc-domain:example.com", "https://www.example.com/"]
    assert search_console.matching_properties(sites, "evil-example.com") == []


def test_search_console_oauth_and_performance(alice, loopback, monkeypatch):
    s = get_settings()
    r = alice.post(f"/api/orgs/{alice.org_id}/websites", {"url": "http://127.0.0.1/", "name": "Local"})
    wid = r.json()["id"]
    r = alice.post(f"/api/orgs/{alice.org_id}/integrations/google/start", {"website_id": wid})
    assert r.status_code == 422 and "GOOGLE_CLIENT_ID" in r.json()["detail"]
    with FakeGoogle([{"siteUrl": "http://127.0.0.1/", "permissionLevel": "siteOwner"},
                     {"siteUrl": "https://unrelated.example/", "permissionLevel": "siteOwner"}]) as g:
        for k, v in {"google_client_id": "cid", "google_client_secret": "csecret",
                     "google_oauth_authorize_url": g.site.base + "/auth", "google_token_url": g.site.base + "/token",
                     "gsc_api_base": g.site.base + "/webmasters/v3"}.items():
            monkeypatch.setattr(s, k, v)
        search_console._token_cache.clear()
        providers = alice.get("/api/integrations/providers").json()
        assert next(p for p in providers if p["provider"] == "google_search_console")["status"] == "available"
        r = alice.post(f"/api/orgs/{alice.org_id}/integrations/google/start", {"website_id": wid})
        assert r.status_code == 200, r.text
        q = parse_qs(urlsplit(r.json()["authorization_url"]).query)
        assert q["scope"] == [search_console.SCOPE] and q["access_type"] == ["offline"]
        state = q["state"][0]
        r = alice.get(f"/api/integrations/google/callback?state={state}&code=good-code", follow_redirects=False)
        assert r.status_code == 303 and "result=connected" in r.headers["location"]
        integ = next(i for i in alice.get(f"/api/orgs/{alice.org_id}/integrations").json()
                     if i["provider"] == "google_search_console")
        assert integ["status"] == "connected" and integ["capabilities"]["properties"] == ["http://127.0.0.1/"]
        assert "rt-secret-123" not in json.dumps(integ)
        # replayed state is refused
        r = alice.get(f"/api/integrations/google/callback?state={state}&code=good-code", follow_redirects=False)
        assert r.status_code == 400
        perf = alice.get(f"/api/orgs/{alice.org_id}/websites/{wid}/search-console?days=28").json()
        assert perf["connected"] and perf["totals"]["clicks"] == 40 and perf["totals"]["impressions"] == 400
        assert perf["totals"]["position"] == 6.0 and perf["top_queries"][0]["query"] == "cold brew halifax"
        assert len(perf["by_date"]) == 2
        # property can only be switched to one that matches the website
        r = alice.post(f"/api/orgs/{alice.org_id}/integrations/{integ['id']}/property", {"property": "https://unrelated.example/"})
        assert r.status_code == 422
        # a GSC connection never counts as a publishing integration
        from app.fixes.capabilities import connected_integration
        with db_session() as d:
            assert connected_integration(d, uuid.UUID(alice.org_id), uuid.UUID(wid)) is None


def test_search_console_not_connected(alice):
    r = alice.post(f"/api/orgs/{alice.org_id}/websites", {"url": "https://example.com/", "name": "Ex"})
    d = alice.get(f"/api/orgs/{alice.org_id}/websites/{r.json()['id']}/search-console").json()
    assert d == {"connected": False, "configured": False}
