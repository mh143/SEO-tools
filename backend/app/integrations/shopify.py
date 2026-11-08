"""Shopify connector (Admin GraphQL API, custom app access token).

Authorization: the merchant creates a *custom app* in Shopify admin (Settings → Apps and sales
channels → Develop apps), grants the scopes below and pastes the Admin API access token
(``shpat_…``) together with the store's ``*.myshopify.com`` domain. The token is encrypted at rest.

Scopes and what they unlock:
  * ``write_products``                 products & collections: SEO title, meta description, title, description HTML
  * ``write_content``                  online-store pages & blog articles: SEO title/description (``global``
                                       ``title_tag``/``description_tag`` metafields), title, body HTML
  * ``write_online_store_navigation``  URL redirects (create / delete for rollback)

URL → resource mapping follows Shopify's fixed storefront routes: ``/products/<handle>``,
``/collections/<handle>``, ``/pages/<handle>``, ``/blogs/<blog>/<handle>`` (with an optional locale prefix).

Not supported (declared, never faked): canonical tags, JSON-LD in <head> and robots directives are
rendered by the theme (Liquid) and have no Admin API field.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from app.crawler.urls import normalize_url
from app.integrations import content_ops
from app.integrations.base import (
    ApplyResult,
    Capability,
    Connector,
    ConnectorError,
    ResourceRef,
    SiteIdentity,
)
from app.integrations.http import request_json

API_VERSION = "2025-01"
SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}\.myshopify\.com$")

UNSUPPORTED = {
    "add_json_ld": "Shopify renders structured data from the theme (Liquid); the Admin API cannot add JSON-LD to "
                   "the page <head>. Add it in your theme or a structured-data app.",
    "set_canonical": "Shopify themes generate canonical tags automatically; there is no API to change them.",
    "set_robots": "Robots directives are controlled by the theme (robots.txt.liquid / theme.liquid), not the Admin API.",
}

Q_IDENTITY = """query RankLensIdentity {
  shop { name myshopifyDomain primaryDomain { url host } }
  currentAppInstallation { accessScopes { handle } }
}"""

Q_PRODUCT = """query RankLensProduct($handle: String!) {
  productByIdentifier(identifier: {handle: $handle}) { id title handle onlineStoreUrl descriptionHtml seo { title description } }
}"""
Q_PRODUCT_ID = """query RankLensProductById($id: ID!) {
  product(id: $id) { id title handle onlineStoreUrl descriptionHtml seo { title description } }
}"""
Q_COLLECTION = """query RankLensCollection($handle: String!) {
  collectionByIdentifier(identifier: {handle: $handle}) { id title handle descriptionHtml seo { title description } }
}"""
Q_COLLECTION_ID = """query RankLensCollectionById($id: ID!) {
  collection(id: $id) { id title handle descriptionHtml seo { title description } }
}"""
_META = """titleTag: metafield(namespace: "global", key: "title_tag") { value }
    descriptionTag: metafield(namespace: "global", key: "description_tag") { value }"""
Q_PAGE = """query RankLensPage($query: String!) {
  pages(first: 5, query: $query) { nodes { id title handle body %s } }
}""".replace("%s", _META)
Q_PAGE_ID = """query RankLensPageById($id: ID!) {
  page(id: $id) { id title handle body %s }
}""".replace("%s", _META)
Q_ARTICLE = """query RankLensArticle($query: String!) {
  articles(first: 10, query: $query) { nodes { id title handle body blog { handle } %s } }
}""".replace("%s", _META)
Q_ARTICLE_ID = """query RankLensArticleById($id: ID!) {
  article(id: $id) { id title handle body blog { handle } %s }
}""".replace("%s", _META)
Q_REDIRECT = """query RankLensRedirect($id: ID!) { urlRedirect(id: $id) { id path target } }"""

M_PRODUCT = """mutation RankLensProductUpdate($product: ProductUpdateInput!) {
  productUpdate(product: $product) { product { id } userErrors { field message } }
}"""
M_COLLECTION = """mutation RankLensCollectionUpdate($input: CollectionInput!) {
  collectionUpdate(input: $input) { collection { id } userErrors { field message } }
}"""
M_PAGE = """mutation RankLensPageUpdate($id: ID!, $page: PageUpdateInput!) {
  pageUpdate(id: $id, page: $page) { page { id } userErrors { field message } }
}"""
M_ARTICLE = """mutation RankLensArticleUpdate($id: ID!, $article: ArticleUpdateInput!) {
  articleUpdate(id: $id, article: $article) { article { id } userErrors { field message } }
}"""
M_REDIRECT_CREATE = """mutation RankLensRedirectCreate($urlRedirect: UrlRedirectInput!) {
  urlRedirectCreate(urlRedirect: $urlRedirect) { urlRedirect { id path target } userErrors { field message } }
}"""
M_REDIRECT_DELETE = """mutation RankLensRedirectDelete($id: ID!) {
  urlRedirectDelete(id: $id) { deletedUrlRedirectId userErrors { field message } }
}"""

_LOCALE = re.compile(r"^[a-z]{2}(-[a-z0-9]{2,4})?$", re.I)


def normalize_shop(value: str) -> str:
    v = (value or "").strip().lower()
    v = re.sub(r"^https?://", "", v).split("/")[0]
    if v and "." not in v:
        v += ".myshopify.com"
    if not SHOP_RE.match(v):
        raise ConnectorError("Enter your store's myshopify.com domain (for example: my-store.myshopify.com). "
                             "You can find it in Shopify admin under Settings → Domains.")
    return v


def _path_target(page_url: str) -> tuple[str, list[str]] | None:
    parts = [p for p in urlsplit(page_url).path.split("/") if p]
    if parts and _LOCALE.match(parts[0]) and len(parts) > 1 and parts[1] in ("products", "collections", "pages", "blogs"):
        parts = parts[1:]
    if len(parts) >= 2 and parts[0] in ("products", "collections", "pages"):
        return parts[0], parts[1:2]
    if len(parts) >= 3 and parts[0] == "blogs":
        return "blogs", parts[1:3]
    # /collections/<c>/products/<handle>
    if len(parts) >= 4 and parts[0] == "collections" and parts[2] == "products":
        return "products", parts[3:4]
    return None


class ShopifyConnector(Connector):
    provider = "shopify"
    display_name = "Shopify (custom app token)"
    site_level_operations = frozenset({"create_redirect"})

    def __init__(self, endpoint_for=None, fetcher_factory=None):
        # ``endpoint_for`` is only overridden by tests (pointing at a local contract fake).
        self._endpoint_for = endpoint_for
        self._fetcher_factory = fetcher_factory

    def normalize_shop(self, value: str) -> str:
        if self._endpoint_for is not None:
            return (value or "").strip().lower()
        return normalize_shop(value)

    def endpoint(self, shop: str) -> str:
        if self._endpoint_for is not None:
            return self._endpoint_for(shop)
        return f"https://{normalize_shop(shop)}/admin/api/{API_VERSION}/graphql.json"

    async def _gql(self, creds: dict, query: str, variables: dict | None = None) -> dict:
        kw = {"fetcher_factory": self._fetcher_factory} if self._fetcher_factory else {}
        _, data = await request_json("POST", self.endpoint(creds["shop"]),
                                     headers={"X-Shopify-Access-Token": creds["access_token"]},
                                     body={"query": query, "variables": variables or {}}, provider="Shopify", **kw)
        if not isinstance(data, dict):
            raise ConnectorError("Shopify returned an unexpected response.")
        if data.get("errors"):
            errs = data["errors"]
            msg = errs[0].get("message") if isinstance(errs, list) and errs and isinstance(errs[0], dict) else str(errs)
            if "access denied" in (msg or "").lower():
                raise ConnectorError("The Shopify app token is missing a required access scope for this change.",
                                     detail=errs)
            raise ConnectorError(f"Shopify API error: {msg}", detail=errs)
        return data.get("data") or {}

    @staticmethod
    def _user_errors(payload: dict | None) -> None:
        errs = (payload or {}).get("userErrors") or []
        if errs:
            raise ConnectorError("Shopify refused the change: " + "; ".join(e.get("message", "") for e in errs),
                                 detail=errs)

    # ------------------------------------------------------------------ identity & capabilities
    async def verify_identity(self, creds: dict) -> SiteIdentity:
        d = await self._gql(creds, Q_IDENTITY)
        shop = d.get("shop") or {}
        if not shop.get("myshopifyDomain"):
            raise ConnectorError("Could not read the Shopify store with this token.")
        scopes = sorted(s["handle"] for s in ((d.get("currentAppInstallation") or {}).get("accessScopes") or []))
        primary = (shop.get("primaryDomain") or {}).get("url") or f"https://{shop['myshopifyDomain']}"
        return SiteIdentity(site_url=primary, name=shop.get("name", ""), account=shop["myshopifyDomain"],
                            raw={"scopes": scopes, "myshopify_domain": shop["myshopifyDomain"]})

    async def discover_capabilities(self, creds: dict, identity: SiteIdentity | None = None) -> dict[str, Capability]:
        identity = identity or await self.verify_identity(creds)
        scopes = set(identity.raw.get("scopes", []))
        products, content = "write_products" in scopes, "write_content" in scopes
        nav = "write_online_store_navigation" in scopes
        scope_list = ", ".join(x for x, ok in (("products & collections", products), ("pages & blog posts", content)) if ok)
        need = "The app token needs the write_products and/or write_content access scope."
        any_ = products or content

        def cap(notes: str) -> Capability:
            return Capability(any_, "" if any_ else need, rollback=True, notes=f"{notes} Applies to: {scope_list or 'nothing'}.")

        out: dict[str, Capability] = {
            "set_title": cap("Page titles set the SEO title (<title>); H1 fixes change the product/page/post title."),
            "set_meta_description": cap("Sets the SEO meta description."),
            "set_image_alt": cap("Updates the alt attribute of images inside the description/body HTML."),
            "content_insert_after_heading": cap("Edits the description/body HTML."),
            "content_append": cap("Edits the description/body HTML."),
            "content_replace_href": cap("Only links inside the description/body HTML; theme menus are not changed."),
            "content_link_phrase": cap("Edits the description/body HTML."),
            "create_redirect": Capability(nav, "" if nav else "The app token needs the write_online_store_navigation "
                                                               "access scope to create URL redirects.", rollback=True,
                                          notes="Creates a Shopify URL redirect (301). Shopify only applies redirects "
                                                "for paths that no longer have a page."),
        }
        for op, reason in UNSUPPORTED.items():
            out[op] = Capability(False, reason)
        return out

    # ------------------------------------------------------------------ resources
    async def locate(self, creds: dict, page_url: str, extracted: dict | None) -> ResourceRef | None:
        t = _path_target(normalize_url(page_url) or page_url)
        if t is None:
            return None
        kind, args = t
        if kind == "products":
            node = (await self._gql(creds, Q_PRODUCT, {"handle": args[0]})).get("productByIdentifier")
            return ResourceRef("product", node["id"], page_url, f"shopify:{node['id']}") if node else None
        if kind == "collections":
            node = (await self._gql(creds, Q_COLLECTION, {"handle": args[0]})).get("collectionByIdentifier")
            return ResourceRef("collection", node["id"], page_url, f"shopify:{node['id']}") if node else None
        if kind == "pages":
            nodes = ((await self._gql(creds, Q_PAGE, {"query": f"handle:'{args[0]}'"})).get("pages") or {}).get("nodes") or []
            node = next((n for n in nodes if n.get("handle") == args[0]), None)
            return ResourceRef("page", node["id"], page_url, f"shopify:{node['id']}") if node else None
        blog, handle = args
        nodes = ((await self._gql(creds, Q_ARTICLE, {"query": f"handle:'{handle}'"})).get("articles") or {}).get("nodes") or []
        node = next((n for n in nodes if n.get("handle") == handle and (n.get("blog") or {}).get("handle") == blog), None)
        return ResourceRef("article", node["id"], page_url, f"shopify:{node['id']}") if node else None

    async def read(self, creds: dict, ref: ResourceRef) -> dict:
        q, key = {"product": (Q_PRODUCT_ID, "product"), "collection": (Q_COLLECTION_ID, "collection"),
                  "page": (Q_PAGE_ID, "page"), "article": (Q_ARTICLE_ID, "article")}[ref.kind]
        n = (await self._gql(creds, q, {"id": ref.id})).get(key)
        if not n:
            raise ConnectorError("The Shopify resource no longer exists.")
        if ref.kind in ("product", "collection"):
            seo = n.get("seo") or {}
            return {"title": n.get("title") or "", "body": n.get("descriptionHtml") or "",
                    "seo_title": seo.get("title") or "", "seo_description": seo.get("description") or ""}
        return {"title": n.get("title") or "", "body": n.get("body") or "",
                "seo_title": (n.get("titleTag") or {}).get("value") or "",
                "seo_description": (n.get("descriptionTag") or {}).get("value") or ""}

    async def _write(self, creds: dict, ref: ResourceRef, current: dict, changes: dict) -> dict:
        merged = {**current, **changes}
        if ref.kind in ("product", "collection"):
            data: dict = {"id": ref.id}
            if "title" in changes:
                data["title"] = merged["title"]
            if "body" in changes:
                data["descriptionHtml"] = merged["body"]
            if "seo_title" in changes or "seo_description" in changes:
                data["seo"] = {"title": merged["seo_title"], "description": merged["seo_description"]}
            if ref.kind == "product":
                d = await self._gql(creds, M_PRODUCT, {"product": data})
                self._user_errors(d.get("productUpdate"))
            else:
                d = await self._gql(creds, M_COLLECTION, {"input": data})
                self._user_errors(d.get("collectionUpdate"))
            return d
        payload: dict = {}
        if "title" in changes:
            payload["title"] = merged["title"]
        if "body" in changes:
            payload["body"] = merged["body"]
        metas = []
        for f, key in (("seo_title", "title_tag"), ("seo_description", "description_tag")):
            if f in changes:
                metas.append({"namespace": "global", "key": key, "type": "single_line_text_field"
                              if key == "title_tag" else "multi_line_text_field", "value": merged[f]})
        if metas:
            payload["metafields"] = metas
        if ref.kind == "page":
            d = await self._gql(creds, M_PAGE, {"id": ref.id, "page": payload})
            self._user_errors(d.get("pageUpdate"))
        else:
            d = await self._gql(creds, M_ARTICLE, {"id": ref.id, "article": payload})
            self._user_errors(d.get("articleUpdate"))
        return d

    async def apply(self, creds: dict, ref: ResourceRef, operation: str, params: dict) -> ApplyResult:
        if operation in UNSUPPORTED:
            raise ConnectorError(UNSUPPORTED[operation])
        if operation == "create_redirect":
            return await self._create_redirect(creds, params)
        current = await self.read(creds, ref)
        base = ref.link
        if operation == "set_title":
            field = "title" if params.get("target") == "heading" else "seo_title"
            new_value = params["value"]
        elif operation == "set_meta_description":
            field, new_value = "seo_description", params["value"]
        else:
            field = "body"
            body = current["body"]
            if operation == "content_insert_after_heading":
                new_value = content_ops.insert_after_heading(body, params["heading_text"], params["html"])
            elif operation == "content_append":
                new_value = content_ops.append(body, params["html"])
            elif operation == "content_replace_href":
                new_value = content_ops.replace_href(body, params["old_href"], params["new_href"], base)
            elif operation == "content_link_phrase":
                new_value = content_ops.link_phrase(body, params["phrase"], params["href"])
            elif operation == "set_image_alt":
                new_value, _ = content_ops.set_img_alt(body, params["src"], params["alt"], base)
            else:
                raise ConnectorError(f"Unsupported operation: {operation}")
        if new_value == current[field]:
            raise ConnectorError("The change would not modify the stored content.")
        await self._write(creds, ref, current, {field: new_value})
        stored = await self.read(creds, ref)
        return ApplyResult(
            original_state={field: current[field]}, new_state={field: new_value},
            provider_response={"id": ref.id, "kind": ref.kind, "field": field,
                               "stored_matches_request": stored[field] == new_value},
            rollback_ref={"resource": ref.to_dict(), "field": field, "original": current[field], "applied": new_value},
        )

    async def _create_redirect(self, creds: dict, params: dict) -> ApplyResult:
        src, dst = urlsplit(params["from_url"]), params.get("to_url") or ""
        if not dst:
            raise ConnectorError("Choose the redirect destination before publishing.")
        path = src.path + (f"?{src.query}" if src.query else "")
        d_parts = urlsplit(dst)
        target = (d_parts.path or "/") + (f"?{d_parts.query}" if d_parts.query else "") if d_parts.netloc == src.netloc else dst
        d = await self._gql(creds, M_REDIRECT_CREATE, {"urlRedirect": {"path": path, "target": target}})
        payload = d.get("urlRedirectCreate") or {}
        self._user_errors(payload)
        red = payload.get("urlRedirect") or {}
        return ApplyResult(original_state={"redirect": None}, new_state={"path": path, "target": target},
                           provider_response={"redirect_id": red.get("id"), "path": red.get("path"),
                                              "target": red.get("target")},
                           rollback_ref={"redirect_id": red.get("id"), "path": path, "target": target})

    async def rollback(self, creds: dict, rollback_ref: dict) -> dict:
        if rollback_ref.get("redirect_id"):
            cur = (await self._gql(creds, Q_REDIRECT, {"id": rollback_ref["redirect_id"]})).get("urlRedirect")
            if cur and (cur.get("path"), cur.get("target")) != (rollback_ref["path"], rollback_ref["target"]):
                raise ConnectorError("The redirect was edited after it was created; it was not deleted automatically.",
                                     conflict=True)
            if cur:
                d = await self._gql(creds, M_REDIRECT_DELETE, {"id": rollback_ref["redirect_id"]})
                self._user_errors(d.get("urlRedirectDelete"))
            return {"deleted_redirect": rollback_ref["redirect_id"]}
        r = rollback_ref["resource"]
        ref = ResourceRef(r["kind"], r["id"], r["link"], r["api_url"])
        current = await self.read(creds, ref)
        field = rollback_ref["field"]
        if current[field] != rollback_ref["applied"]:
            raise ConnectorError("The content was changed after this fix was applied. Rolling back automatically "
                                 "could overwrite those later edits, so it was not attempted.", conflict=True)
        await self._write(creds, ref, current, {field: rollback_ref["original"]})
        return {"id": ref.id, "restored_field": field}
