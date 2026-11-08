"""Wix connector (Wix REST APIs, API key + site ID).

Authorization: the site owner creates an API key in the Wix API Keys Manager
(account settings → API Keys) with the *Wix Blog* and/or *Wix Stores* permissions and pastes it
together with the Site ID (from the dashboard URL ``/dashboard/<site-id>/``). Requests send
``Authorization: <API key>`` and ``wix-site-id: <site id>``. The key is encrypted at rest.

Supported (with rollback):
  * Blog posts (``/post/<slug>``): SEO title, meta description (``seoData.tags``), post title.
  * Store products (``/product-page/<slug>``): SEO title, meta description, product name.

Not supported (declared, never faked): Wix blog content is Ricos rich content (not HTML), so content
edits, image alt and link changes are not applied automatically; canonical, JSON-LD in <head>, robots
and redirects are managed in the Wix SEO settings / editor and are exported for manual application.

Field mappings follow Wix's published REST reference; verify with your account before relying on them.
"""

from __future__ import annotations

import copy
import json
from urllib.parse import quote, urlsplit

from app.crawler.urls import normalize_url
from app.integrations.base import (
    ApplyResult,
    Capability,
    Connector,
    ConnectorError,
    ResourceRef,
    SiteIdentity,
)
from app.integrations.http import request_json

API_BASE = "https://www.wixapis.com"

UNSUPPORTED = {
    "set_image_alt": "Wix stores blog content as Ricos rich content, not HTML; change image alt text in the Wix editor.",
    "content_insert_after_heading": "Wix blog content is Ricos rich content; content edits must be made in the Wix editor.",
    "content_append": "Wix blog content is Ricos rich content; content edits must be made in the Wix editor.",
    "content_replace_href": "Links in Wix pages/posts are edited in the Wix editor; no safe API edit is available.",
    "content_link_phrase": "Links in Wix pages/posts are edited in the Wix editor; no safe API edit is available.",
    "add_json_ld": "Add structured data under the page's SEO settings (Advanced SEO → Structured data markup) in Wix.",
    "set_canonical": "Wix generates canonical tags automatically; change them in the page's Advanced SEO settings.",
    "create_redirect": "Create redirects with the Wix URL Redirect Manager (Marketing & SEO → SEO Tools).",
    "set_robots": "Set robots directives in the page's SEO settings (Let search engines index this page).",
}


def _seo_get(seo: dict | None, which: str) -> str:
    for t in (seo or {}).get("tags") or []:
        if which == "title" and t.get("type") == "title":
            return t.get("children") or ""
        if which == "description" and t.get("type") == "meta" and (t.get("props") or {}).get("name") == "description":
            return (t.get("props") or {}).get("content") or ""
    return ""


def _seo_set(seo: dict | None, which: str, value: str) -> dict:
    out = copy.deepcopy(seo or {})
    tags = out.setdefault("tags", [])
    for t in tags:
        if which == "title" and t.get("type") == "title":
            t["children"], t["custom"], t["disabled"] = value, True, False
            return out
        if which == "description" and t.get("type") == "meta" and (t.get("props") or {}).get("name") == "description":
            t["props"]["content"], t["custom"], t["disabled"] = value, True, False
            return out
    if which == "title":
        tags.append({"type": "title", "children": value, "custom": True, "disabled": False})
    else:
        tags.append({"type": "meta", "props": {"name": "description", "content": value}, "custom": True, "disabled": False})
    return out


class WixConnector(Connector):
    provider = "wix"
    display_name = "Wix (API key)"

    def __init__(self, api_base: str | None = None, fetcher_factory=None):
        self.api_base = (api_base or API_BASE).rstrip("/")
        self._fetcher_factory = fetcher_factory

    async def _call(self, creds: dict, method: str, path: str, body: dict | None = None) -> dict:
        kw = {"fetcher_factory": self._fetcher_factory} if self._fetcher_factory else {}
        _, data = await request_json(method, self.api_base + path, body=body, provider="Wix",
                                     headers={"Authorization": creds["api_key"], "wix-site-id": creds["site_id"]}, **kw)
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ identity & capabilities
    async def verify_identity(self, creds: dict) -> SiteIdentity:
        props = (await self._call(creds, "GET", "/site-properties/v4/properties")).get("properties") or {}
        urls = (await self._call(creds, "GET", "/urls-server/v2/published-site-urls")).get("urls") or []
        primary = next((u.get("url") for u in urls if u.get("primary")), None) or (urls[0].get("url") if urls else "")
        if not primary:
            raise ConnectorError("This Wix site is not published yet, or the API key cannot read its URLs.")
        apps = {"blog": False, "stores": False}
        for app, path, body in (("blog", "/blog/v3/posts?paging.limit=1", None),
                                ("stores", "/stores/v1/products/query", {"query": {"paging": {"limit": 1}}})):
            try:
                await self._call(creds, "POST" if body else "GET", path, body)
                apps[app] = True
            except ConnectorError:
                apps[app] = False
        return SiteIdentity(site_url=primary, name=props.get("siteDisplayName") or "", account=creds["site_id"],
                            raw={"apps": apps})

    async def discover_capabilities(self, creds: dict, identity: SiteIdentity | None = None) -> dict[str, Capability]:
        identity = identity or await self.verify_identity(creds)
        apps = identity.raw.get("apps", {})
        scope = ", ".join(x for x, ok in (("blog posts", apps.get("blog")), ("store products", apps.get("stores"))) if ok)
        ok = bool(scope)
        need = ("The API key cannot access Wix Blog or Wix Stores on this site (add those permissions to the key, "
                "or install the apps).")
        out = {
            "set_title": Capability(ok, "" if ok else need, rollback=True,
                                    notes=f"Page titles set the SEO title tag; H1 fixes change the post title / product "
                                          f"name. Applies to: {scope or 'nothing'}. Static Wix pages are edited in the editor."),
            "set_meta_description": Capability(ok, "" if ok else need, rollback=True,
                                               notes=f"Sets the SEO meta description. Applies to: {scope or 'nothing'}."),
        }
        for op, reason in UNSUPPORTED.items():
            out[op] = Capability(False, reason)
        return out

    # ------------------------------------------------------------------ resources
    async def locate(self, creds: dict, page_url: str, extracted: dict | None) -> ResourceRef | None:
        parts = [p for p in urlsplit(normalize_url(page_url) or page_url).path.split("/") if p]
        if len(parts) >= 2 and parts[-2] == "post":
            try:
                d = await self._call(creds, "GET", f"/blog/v3/posts/slugs/{quote(parts[-1])}?fieldsets=SEO&fieldsets=URL")
            except ConnectorError:
                return None
            post = d.get("post")
            return ResourceRef("post", post["id"], page_url, f"wix:post:{post['id']}") if post else None
        if len(parts) >= 2 and parts[-2] == "product-page":
            filt = json.dumps({"slug": parts[-1]})
            d = await self._call(creds, "POST", "/stores/v1/products/query", {"query": {"filter": filt}})
            prod = next(iter(d.get("products") or []), None)
            return ResourceRef("product", prod["id"], page_url, f"wix:product:{prod['id']}") if prod else None
        return None

    async def _raw(self, creds: dict, ref: ResourceRef) -> dict:
        if ref.kind == "post":
            return (await self._call(creds, "GET", f"/blog/v3/draft-posts/{ref.id}?fieldsets=SEO")).get("draftPost") or {}
        return (await self._call(creds, "GET", f"/stores/v1/products/{ref.id}")).get("product") or {}

    async def read(self, creds: dict, ref: ResourceRef) -> dict:
        r = await self._raw(creds, ref)
        if not r:
            raise ConnectorError("The Wix item no longer exists.")
        return {"title": r.get("title") if ref.kind == "post" else r.get("name") or "",
                "seo_title": _seo_get(r.get("seoData"), "title"),
                "seo_description": _seo_get(r.get("seoData"), "description"), "_seo": r.get("seoData") or {}}

    async def _write(self, creds: dict, ref: ResourceRef, field: str, value: str) -> None:
        raw = await self._raw(creds, ref)
        if field == "title":
            patch = {"title": value} if ref.kind == "post" else {"name": value}
        else:
            patch = {"seoData": _seo_set(raw.get("seoData"), "title" if field == "seo_title" else "description", value)}
        if ref.kind == "post":
            await self._call(creds, "PATCH", f"/blog/v3/draft-posts/{ref.id}",
                             {"draftPost": {"id": ref.id, **patch}, "action": "UPDATE_PUBLISH"})
        else:
            await self._call(creds, "PATCH", f"/stores/v1/products/{ref.id}", {"product": patch})

    async def apply(self, creds: dict, ref: ResourceRef, operation: str, params: dict) -> ApplyResult:
        if operation in UNSUPPORTED:
            raise ConnectorError(UNSUPPORTED[operation])
        if operation == "set_title":
            field = "title" if params.get("target") == "heading" else "seo_title"
        elif operation == "set_meta_description":
            field = "seo_description"
        else:
            raise ConnectorError(f"Unsupported operation: {operation}")
        value = params["value"]
        current = await self.read(creds, ref)
        if current[field] == value:
            raise ConnectorError("The change would not modify the stored content.")
        await self._write(creds, ref, field, value)
        stored = await self.read(creds, ref)
        return ApplyResult(original_state={field: current[field]}, new_state={field: value},
                           provider_response={"id": ref.id, "kind": ref.kind, "field": field,
                                              "stored_matches_request": stored[field] == value},
                           rollback_ref={"resource": ref.to_dict(), "field": field, "original": current[field],
                                         "applied": value})

    async def rollback(self, creds: dict, rollback_ref: dict) -> dict:
        r = rollback_ref["resource"]
        ref = ResourceRef(r["kind"], r["id"], r["link"], r["api_url"])
        field = rollback_ref["field"]
        current = await self.read(creds, ref)
        if current[field] != rollback_ref["applied"]:
            raise ConnectorError("The item was changed after this fix was applied. Rolling back automatically "
                                 "could overwrite those later edits, so it was not attempted.", conflict=True)
        await self._write(creds, ref, field, rollback_ref["original"])
        return {"id": ref.id, "restored_field": field}
