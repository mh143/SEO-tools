"""A fake Shopify store: the subset of the Admin GraphQL API the connector uses (dispatched by
operation name, following the documented request/response shapes) plus a storefront that renders
pages from the stored state, so verification sees real HTML. A contract-test double, not Shopify."""

from __future__ import annotations

import html
import json
import re
from urllib.parse import urlsplit

from tests.fixtures.site import FixtureSite

TOKEN = "shpat_test_0123456789abcdef"
GQL_PATH = "/admin/api/2025-01/graphql.json"


class FakeShopify:
    def __init__(self, *, scopes=("read_products", "write_products", "read_content", "write_content",
                                  "write_online_store_navigation")):
        self.site = FixtureSite({"*": self._route})
        self.scopes = list(scopes)
        self.products = {"gid://shopify/Product/1": {
            "handle": "cold-brew", "title": "Cold Brew", "seo_title": "", "seo_description": "",
            "body": "<p>Slow-steeped for 18 hours. <img src=\"/cdn/cold-brew.jpg\"></p>"}}
        self.pages = {"gid://shopify/Page/5": {"handle": "about", "title": "About", "seo_title": "",
                                               "seo_description": "", "body": "<p>Roasting in Halifax since 2015.</p>"}}
        self.redirects: dict[str, dict] = {}
        self.mutations: list[str] = []

    @property
    def base(self):
        return self.site.base

    def endpoint_for(self, shop: str) -> str:
        return self.base + GQL_PATH

    def __enter__(self):
        self.site.__enter__()
        return self

    def __exit__(self, *exc):
        self.site.__exit__(*exc)

    def _json(self, data, status=200):
        return status, {"Content-Type": "application/json"}, json.dumps(data)

    # ------------------------------------------------------------------ storefront
    def _render(self, r: dict, kind: str) -> str:
        title = r["seo_title"] or r["title"]
        meta = f'<meta name="description" content="{html.escape(r["seo_description"])}">' if r["seo_description"] else ""
        return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                f"<title>{html.escape(title)}</title>{meta}<link rel='canonical' href='{self.base}/{kind}/{r['handle']}'>"
                f"</head><body><main><h1>{html.escape(r['title'])}</h1>{r['body']}</main></body></html>")

    def _route(self, h):
        path = urlsplit(h.path).path
        if path == GQL_PATH:
            if h.command != "POST":
                return self._json({"errors": "Not found"}, 404)
            if h.headers.get("X-Shopify-Access-Token") != TOKEN:
                return self._json({"errors": "[API] Invalid API key or access token (unrecognized login or wrong password)"}, 401)
            return self._json(self._gql(json.loads(h.body or b"{}")))
        for r in self.products.values():
            if path == f"/products/{r['handle']}":
                return 200, {}, self._render(r, "products")
        for r in self.pages.values():
            if path == f"/pages/{r['handle']}":
                return 200, {}, self._render(r, "pages")
        if path in self.redirects:
            return 301, {"Location": self.redirects[path]["target"]}, ""
        if path == "/":
            return 200, {}, ("<!doctype html><html lang='en'><head><title>Bean There Coffee Shop</title></head><body><main>"
                             "<h1>Bean There</h1><a href='/products/cold-brew'>Cold brew</a> "
                             "<a href='/pages/about'>About</a> <a href='/products/discontinued'>Old blend</a>"
                             "</main></body></html>")
        return 404, {}, "<html><head><title>Not found</title></head><body>Not found</body></html>"

    # ------------------------------------------------------------------ admin graphql
    def _gql(self, body: dict) -> dict:
        q, v = body.get("query", ""), body.get("variables") or {}
        op = re.search(r"(?:query|mutation)\s+(\w+)", q).group(1)
        if op.endswith("Update") or op.startswith("RankLensRedirect") and "mutation" in q:
            self.mutations.append(op)

        def product(gid):
            r = self.products.get(gid)
            return r and {"id": gid, "title": r["title"], "handle": r["handle"], "onlineStoreUrl": None,
                          "descriptionHtml": r["body"], "seo": {"title": r["seo_title"] or None,
                                                                 "description": r["seo_description"] or None}}

        def page(gid):
            r = self.pages.get(gid)
            return r and {"id": gid, "title": r["title"], "handle": r["handle"], "body": r["body"],
                          "titleTag": {"value": r["seo_title"]} if r["seo_title"] else None,
                          "descriptionTag": {"value": r["seo_description"]} if r["seo_description"] else None}

        def denied(scope):
            if scope not in self.scopes:
                return {"errors": [{"message": f"Access denied for {op}. Required access: `{scope}` access scope."}]}
            return None

        if op == "RankLensIdentity":
            return {"data": {"shop": {"name": "Bean There", "myshopifyDomain": "bean-there.myshopify.com",
                                      "primaryDomain": {"url": self.base, "host": "127.0.0.1"}},
                             "currentAppInstallation": {"accessScopes": [{"handle": s} for s in self.scopes]}}}
        if op == "RankLensProduct":
            gid = next((g for g, r in self.products.items() if r["handle"] == v["handle"]), None)
            return {"data": {"productByIdentifier": product(gid) if gid else None}}
        if op == "RankLensProductById":
            return {"data": {"product": product(v["id"])}}
        if op == "RankLensPage":
            handle = re.search(r"handle:'([^']+)'", v["query"]).group(1)
            return {"data": {"pages": {"nodes": [page(g) for g, r in self.pages.items() if r["handle"] == handle]}}}
        if op == "RankLensPageById":
            return {"data": {"page": page(v["id"])}}
        if op == "RankLensArticle":
            return {"data": {"articles": {"nodes": []}}}
        if op == "RankLensProductUpdate":
            if (e := denied("write_products")):
                return e
            data = v["product"]
            r = self.products[data["id"]]
            if "title" in data:
                r["title"] = data["title"]
            if "descriptionHtml" in data:
                r["body"] = data["descriptionHtml"]
            if "seo" in data:
                r["seo_title"] = data["seo"].get("title") or ""
                r["seo_description"] = data["seo"].get("description") or ""
            return {"data": {"productUpdate": {"product": {"id": data["id"]}, "userErrors": []}}}
        if op == "RankLensPageUpdate":
            if (e := denied("write_content")):
                return e
            r = self.pages[v["id"]]
            p = v["page"]
            r["title"] = p.get("title", r["title"])
            r["body"] = p.get("body", r["body"])
            for m in p.get("metafields", []):
                r["seo_title" if m["key"] == "title_tag" else "seo_description"] = m["value"]
            return {"data": {"pageUpdate": {"page": {"id": v["id"]}, "userErrors": []}}}
        if op == "RankLensRedirectCreate":
            if (e := denied("write_online_store_navigation")):
                return e
            red = v["urlRedirect"]
            if red["path"] in self.redirects:
                return {"data": {"urlRedirectCreate": {"urlRedirect": None, "userErrors": [
                    {"field": ["path"], "message": "Path has already been taken"}]}}}
            rid = f"gid://shopify/UrlRedirect/{len(self.redirects) + 1}"
            self.redirects[red["path"]] = {"id": rid, "path": red["path"], "target": red["target"]}
            return {"data": {"urlRedirectCreate": {"urlRedirect": self.redirects[red["path"]], "userErrors": []}}}
        if op == "RankLensRedirect":
            return {"data": {"urlRedirect": next((r for r in self.redirects.values() if r["id"] == v["id"]), None)}}
        if op == "RankLensRedirectDelete":
            path = next((p for p, r in self.redirects.items() if r["id"] == v["id"]), None)
            if path:
                del self.redirects[path]
            return {"data": {"urlRedirectDelete": {"deletedUrlRedirectId": v["id"], "userErrors": []}}}
        return {"errors": [{"message": f"Field '{op}' doesn't exist on type 'QueryRoot'"}]}
