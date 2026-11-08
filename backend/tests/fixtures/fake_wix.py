"""A fake Wix site: the subset of the Wix REST APIs the connector uses (site properties, published
URLs, Blog draft posts, Stores products) plus a public site rendering from stored state.
A contract-test double following Wix's documented shapes, not Wix."""

from __future__ import annotations

import html
import json
import re
from urllib.parse import urlsplit

from tests.fixtures.site import FixtureSite

API_KEY = "IST.test-wix-api-key-0123456789"
SITE_ID = "1a2b3c4d-0000-4000-8000-123456789abc"


def _seo_title(seo):
    return next((t["children"] for t in seo.get("tags", []) if t.get("type") == "title"), "")


def _seo_desc(seo):
    return next((t["props"]["content"] for t in seo.get("tags", [])
                 if t.get("type") == "meta" and t.get("props", {}).get("name") == "description"), "")


class FakeWix:
    def __init__(self):
        self.site = FixtureSite({"*": self._route})
        self.posts = {"p1": {"id": "p1", "slug": "brewing-guide", "title": "Guide", "seoData": {"tags": []}}}
        self.products = {"x9": {"id": "x9", "slug": "house-blend", "name": "House Blend", "seoData": {"tags": []}}}
        self.writes: list[dict] = []

    @property
    def base(self):
        return self.site.base

    def __enter__(self):
        self.site.__enter__()
        return self

    def __exit__(self, *exc):
        self.site.__exit__(*exc)

    def _json(self, data, status=200):
        return status, {"Content-Type": "application/json"}, json.dumps(data)

    def _page(self, title, h1, seo):
        t = _seo_title(seo) or title
        d = _seo_desc(seo)
        meta = f'<meta name="description" content="{html.escape(d)}">' if d else ""
        return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                f"<title>{html.escape(t)}</title>{meta}</head><body><main><h1>{html.escape(h1)}</h1>"
                f"<p>Everything about our coffee.</p></main></body></html>")

    def _route(self, h):
        u = urlsplit(h.path)
        path = u.path
        if path.startswith(("/site-properties/", "/urls-server/", "/blog/", "/stores/")):
            if h.headers.get("Authorization") != API_KEY or h.headers.get("wix-site-id") != SITE_ID:
                return self._json({"message": "UNAUTHORIZED"}, 401)
            return self._api(h.command, path, json.loads(h.body or b"null"))
        for p in self.posts.values():
            if path == f"/post/{p['slug']}":
                return 200, {}, self._page(p["title"], p["title"], p["seoData"])
        for p in self.products.values():
            if path == f"/product-page/{p['slug']}":
                return 200, {}, self._page(p["name"], p["name"], p["seoData"])
        if path == "/":
            return 200, {}, ("<!doctype html><html lang='en'><head><title>Bean There Coffee Roasters</title></head>"
                             "<body><main><h1>Bean There</h1><a href='/post/brewing-guide'>Guide</a> "
                             "<a href='/product-page/house-blend'>Blend</a></main></body></html>")
        return 404, {}, "<html><body>Not found</body></html>"

    def _api(self, method, path, body):
        if path == "/site-properties/v4/properties":
            return self._json({"properties": {"siteDisplayName": "Bean There"}})
        if path == "/urls-server/v2/published-site-urls":
            return self._json({"urls": [{"url": self.base, "primary": True, "type": "PRIMARY"}]})
        if path == "/blog/v3/posts" and method == "GET":
            return self._json({"posts": list(self.posts.values())[:1]})
        m = re.fullmatch(r"/blog/v3/posts/slugs/([^/]+)", path)
        if m:
            p = next((p for p in self.posts.values() if p["slug"] == m.group(1)), None)
            return self._json({"post": p}) if p else self._json({"message": "Post not found"}, 404)
        m = re.fullmatch(r"/blog/v3/draft-posts/(\w+)", path)
        if m:
            p = self.posts[m.group(1)]
            if method == "PATCH":
                assert body["action"] == "UPDATE_PUBLISH"
                p.update({k: v for k, v in body["draftPost"].items() if k in ("title", "seoData")})
                self.writes.append(body)
            return self._json({"draftPost": p})
        if path == "/stores/v1/products/query":
            filt = json.loads((body.get("query") or {}).get("filter") or "{}")
            items = [p for p in self.products.values() if not filt or p["slug"] == filt.get("slug")]
            return self._json({"products": items})
        m = re.fullmatch(r"/stores/v1/products/(\w+)", path)
        if m:
            p = self.products[m.group(1)]
            if method == "PATCH":
                p.update({k: v for k, v in body["product"].items() if k in ("name", "seoData")})
                self.writes.append(body)
            return self._json({"product": p})
        return self._json({"message": "Not found"}, 404)
