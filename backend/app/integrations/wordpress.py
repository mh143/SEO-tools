"""WordPress connector (self-hosted WordPress 5.6+), no plugin required.

Authorization uses WordPress core *Application Passwords*:
  * Discovery: ``GET /wp-json/`` → ``authentication["application-passwords"]["endpoints"]["authorization"]``.
  * The user approves access on their own site at ``/wp-admin/authorize-application.php`` and WordPress
    redirects back to our ``success_url`` with ``site_url``, ``user_login`` and ``password``
    (``success_url`` must be HTTPS). Users can alternatively paste an application password they
    created under Users → Profile.
  * Requests use HTTP Basic auth with the application password.

Supported operations (core REST API, ``/wp/v2/posts|pages/<id>`` and ``/wp/v2/media/<id>``):
  set_title, set_image_alt, content_insert_after_heading, content_append, content_replace_href,
  content_link_phrase. All of them store the previous raw value so they can be rolled back.

Not supported by WordPress core (declared, never faked): meta descriptions, JSON-LD in <head>,
canonical tags, redirects, robots directives. These need an SEO plugin whose fields core does not
expose for writing; fixes of these types are exported for manual application instead.
"""

from __future__ import annotations

import base64
import json
import re
from urllib.parse import urlencode, urljoin, urlsplit

from app.crawler.fetcher import SafeFetcher
from app.crawler.ssrf import BlockedURLError, validate_url
from app.crawler.urls import normalize_url, same_site
from app.integrations import content_ops
from app.integrations.base import (
    ApplyResult,
    Capability,
    Connector,
    ConnectorError,
    ResourceRef,
    SiteIdentity,
)

UNSUPPORTED = {
    "set_meta_description": "WordPress core has no meta description field. SEO plugins store it in fields that "
                            "the core REST API does not expose for writing, so this change must be made manually.",
    "add_json_ld": "WordPress core provides no API for adding structured data to the page <head>, and <script> "
                   "tags in post content are filtered for most users. Add the JSON-LD with your theme or SEO plugin.",
    "set_canonical": "WordPress core generates canonical tags automatically and has no API to change them.",
    "create_redirect": "WordPress core has no redirect API; use your server, CDN or a redirect plugin.",
    "set_robots": "WordPress core has no per-page robots directive API.",
}

_REST_RE = re.compile(r"/wp/v2/(posts|pages)/(\d+)$")


def _auth_header(creds: dict) -> dict:
    token = base64.b64encode(f"{creds['user_login']}:{creds['password']}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _route(api_root: str, route: str, query: dict | None = None) -> str:
    """Build a REST URL for both pretty (/wp-json/) and plain (?rest_route=) permalinks."""
    if "rest_route=" in api_root:
        base = api_root.split("?")[0]
        q = {"rest_route": route}
        q.update(query or {})
        return f"{base}?{urlencode(q)}"
    url = api_root.rstrip("/") + route
    return url + (("?" + urlencode(query)) if query else "")


class WordPressConnector(Connector):
    provider = "wordpress"
    display_name = "WordPress (Application Passwords)"

    def __init__(self, fetcher_factory=SafeFetcher):
        self._fetcher_factory = fetcher_factory

    # ------------------------------------------------------------------ http
    async def _request(self, method: str, url: str, creds: dict | None = None, body: dict | None = None) -> dict:
        try:
            validate_url(url)
        except BlockedURLError as exc:
            raise ConnectorError(str(exc)) from exc
        headers = _auth_header(creds) if creds else {"Accept": "application/json"}
        content = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            content = json.dumps(body).encode()
        async with self._fetcher_factory() as f:
            # Never follow redirects with credentials attached (could leak them to another host).
            res = await f.fetch(url, method=method, headers=headers, content=content,
                                follow_redirects=creds is None, max_bytes=8 * 1024 * 1024)
        if res.error:
            raise ConnectorError(f"Could not reach the WordPress site: {res.error}")
        try:
            data = json.loads(res.content or b"null")
        except json.JSONDecodeError:
            data = None
        if res.status_code in (301, 302, 307, 308):
            raise ConnectorError("The WordPress API redirected the request; check the site URL (http vs https, www).")
        if res.status_code == 401:
            raise ConnectorError("WordPress rejected the credentials (the application password may have been revoked).")
        if res.status_code == 403:
            raise ConnectorError("The connected WordPress user is not allowed to perform this action.")
        if res.status_code == 404:
            raise ConnectorError("WordPress resource not found.", detail=data)
        if res.status_code is None or res.status_code >= 400:
            msg = data.get("message") if isinstance(data, dict) else None
            raise ConnectorError(f"WordPress API error (HTTP {res.status_code}){': ' + msg if msg else ''}.", detail=data)
        return {"status": res.status_code, "data": data, "headers": res.headers, "final_url": res.final_url}

    # ------------------------------------------------------------------ discovery & auth
    async def discover(self, site_url: str) -> dict:
        """Find the REST API root and the Application Passwords authorization endpoint."""
        candidates = [urljoin(site_url, "/wp-json/"), urljoin(site_url, "/?rest_route=/")]
        last: Exception | None = None
        for api in candidates:
            try:
                r = await self._request("GET", api)
            except ConnectorError as exc:
                last = exc
                continue
            data = r["data"]
            if not isinstance(data, dict) or "routes" not in data and "namespaces" not in data:
                continue
            final = r["final_url"]
            api_root = final if "rest_route" not in final else final.split("?")[0] + "?rest_route="
            auth = (data.get("authentication") or {}).get("application-passwords") or {}
            endpoint = (auth.get("endpoints") or {}).get("authorization")
            return {"api_root": api_root if api_root.endswith(("/", "=")) else api_root + "/",
                    "name": data.get("name", ""), "home": data.get("home") or data.get("url") or site_url,
                    "authorization_endpoint": endpoint, "namespaces": data.get("namespaces", [])}
        raise ConnectorError("No WordPress REST API was found at this site."
                             + (f" ({last})" if last else ""))

    def authorization_url(self, endpoint: str, *, app_name: str, app_id: str, success_url: str, reject_url: str) -> str:
        if not endpoint.startswith("https://"):
            raise ConnectorError("WordPress only offers the authorization flow over HTTPS. Use the manual "
                                 "application password option instead.")
        q = urlencode({"app_name": app_name, "app_id": app_id, "success_url": success_url, "reject_url": reject_url})
        return f"{endpoint}{'&' if '?' in endpoint else '?'}{q}"

    async def verify_identity(self, creds: dict) -> SiteIdentity:
        r = await self._request("GET", _route(creds["api_root"], "/wp/v2/users/me", {"context": "edit"}), creds)
        me = r["data"] or {}
        if not isinstance(me, dict) or not me.get("id"):
            raise ConnectorError("Could not read the authorized WordPress user.")
        idx = await self._request("GET", creds["api_root"] if "rest_route" not in creds["api_root"] else _route(creds["api_root"], "/"))
        site = idx["data"] or {}
        home = site.get("home") or site.get("url") or creds.get("site_url", "")
        return SiteIdentity(site_url=home, name=site.get("name", ""), account=me.get("username") or me.get("slug") or "",
                            raw={"user_id": me.get("id"), "roles": me.get("roles", []),
                                 "capabilities": {k: v for k, v in (me.get("capabilities") or {}).items()
                                                  if k in ("edit_posts", "edit_pages", "edit_published_posts",
                                                           "edit_published_pages", "edit_others_posts",
                                                           "edit_others_pages", "upload_files", "unfiltered_html")}})

    async def discover_capabilities(self, creds: dict, identity: SiteIdentity | None = None) -> dict[str, Capability]:
        identity = identity or await self.verify_identity(creds)
        caps = identity.raw.get("capabilities", {})
        can_posts = bool(caps.get("edit_published_posts") and caps.get("edit_others_posts"))
        can_pages = bool(caps.get("edit_published_pages") and caps.get("edit_others_pages"))
        can_edit = can_posts or can_pages
        scope = ", ".join(x for x, ok in (("posts", can_posts), ("pages", can_pages)) if ok) or "nothing"
        no_edit = ("The connected user cannot edit published posts/pages written by others "
                   "(needs the Editor or Administrator role).")
        out: dict[str, Capability] = {
            "set_title": Capability(can_edit, "" if can_edit else no_edit, rollback=True,
                                    notes=f"Edits the post/page title ({scope}). In WordPress the title usually "
                                          "drives both the <title> tag and the visible H1."),
            "set_image_alt": Capability(can_edit, "" if can_edit else no_edit, rollback=True,
                                        notes="Updates the alt attribute of the image inside the post/page content "
                                              "(and the media library alt text when available)."),
            "content_insert_after_heading": Capability(can_edit, "" if can_edit else no_edit, rollback=True),
            "content_append": Capability(can_edit, "" if can_edit else no_edit, rollback=True),
            "content_replace_href": Capability(can_edit, "" if can_edit else no_edit, rollback=True,
                                               notes="Only links inside post/page content; menus and widgets are not changed."),
            "content_link_phrase": Capability(can_edit, "" if can_edit else no_edit, rollback=True),
        }
        for op, reason in UNSUPPORTED.items():
            out[op] = Capability(False, reason)
        return out

    # ------------------------------------------------------------------ resources
    async def locate(self, creds: dict, page_url: str, extracted: dict | None) -> ResourceRef | None:
        api_root = creds["api_root"]
        target = (normalize_url(page_url) or page_url).rstrip("/")
        hint = (extracted or {}).get("wp_rest_link")
        candidates: list[tuple[str, str]] = []
        if hint and same_site(hint, urlsplit(api_root).hostname or ""):
            m = _REST_RE.search(urlsplit(hint).path) or _REST_RE.search(dict(
                x.split("=", 1) for x in urlsplit(hint).query.split("&") if "=" in x).get("rest_route", ""))
            if m:
                candidates.append((m.group(1), m.group(2)))
        for kind, rid in candidates:
            try:
                r = await self._request("GET", _route(api_root, f"/wp/v2/{kind}/{rid}", {"context": "edit"}), creds)
            except ConnectorError:
                continue
            d = r["data"] or {}
            if (normalize_url(d.get("link", "")) or "").rstrip("/") == target:
                return ResourceRef(kind, str(rid), d.get("link", ""), _route(api_root, f"/wp/v2/{kind}/{rid}"))
        slug = urlsplit(target).path.rstrip("/").rsplit("/", 1)[-1]
        if slug:
            for kind in ("pages", "posts"):
                try:
                    r = await self._request("GET", _route(api_root, f"/wp/v2/{kind}",
                                                          {"slug": slug, "context": "edit", "status": "publish"}), creds)
                except ConnectorError:
                    continue
                for d in r["data"] or []:
                    if (normalize_url(d.get("link", "")) or "").rstrip("/") == target:
                        return ResourceRef(kind, str(d["id"]), d.get("link", ""), _route(api_root, f"/wp/v2/{kind}/{d['id']}"))
        return None

    async def read(self, creds: dict, ref: ResourceRef) -> dict:
        url = ref.api_url + ("&" if "?" in ref.api_url else "?") + "context=edit"
        d = (await self._request("GET", url, creds))["data"] or {}
        return {"title": (d.get("title") or {}).get("raw", ""), "content": (d.get("content") or {}).get("raw", ""),
                "link": d.get("link"), "modified_gmt": d.get("modified_gmt"), "status": d.get("status")}

    async def _write(self, creds: dict, ref: ResourceRef, body: dict) -> dict:
        r = await self._request("POST", ref.api_url, creds, body)
        return r["data"] or {}

    async def apply(self, creds: dict, ref: ResourceRef, operation: str, params: dict) -> ApplyResult:
        if operation in UNSUPPORTED:
            raise ConnectorError(UNSUPPORTED[operation])
        current = await self.read(creds, ref)
        base = ref.link or creds.get("site_url", "")
        field = "content"
        if operation == "set_title":
            field, new_value = "title", params["value"]
        elif operation == "content_insert_after_heading":
            new_value = content_ops.insert_after_heading(current["content"], params["heading_text"], params["html"])
        elif operation == "content_append":
            new_value = content_ops.append(current["content"], params["html"])
        elif operation == "content_replace_href":
            new_value = content_ops.replace_href(current["content"], params["old_href"], params["new_href"], base)
        elif operation == "content_link_phrase":
            new_value = content_ops.link_phrase(current["content"], params["phrase"], params["href"])
        elif operation == "set_image_alt":
            new_value, _ = content_ops.set_img_alt(current["content"], params["src"], params["alt"], base)
        else:
            raise ConnectorError(f"Unsupported operation: {operation}")
        if new_value == current[field]:
            raise ConnectorError("The change would not modify the stored content.")
        data = await self._write(creds, ref, {field: new_value})
        stored = (data.get(field) or {}).get("raw") if isinstance(data.get(field), dict) else None
        media = None
        if operation == "set_image_alt" and params.get("attachment_id"):
            try:
                m = await self._request("POST", _route(creds["api_root"], f"/wp/v2/media/{int(params['attachment_id'])}"),
                                        creds, {"alt_text": params["alt"]})
                media = {"id": params["attachment_id"], "alt_text": (m["data"] or {}).get("alt_text")}
            except ConnectorError as exc:
                media = {"id": params["attachment_id"], "error": exc.user_message}
        return ApplyResult(
            original_state={field: current[field], "modified_gmt": current.get("modified_gmt")},
            new_state={field: new_value},
            provider_response={"id": data.get("id"), "modified_gmt": data.get("modified_gmt"),
                               "link": data.get("link"), "stored_matches_request": stored == new_value if stored is not None else None,
                               "media": media},
            rollback_ref={"resource": ref.to_dict(), "field": field, "original": current[field], "applied": new_value},
        )

    async def rollback(self, creds: dict, rollback_ref: dict) -> dict:
        r = rollback_ref["resource"]
        ref = ResourceRef(r["kind"], r["id"], r["link"], r["api_url"])
        current = await self.read(creds, ref)
        field = rollback_ref["field"]
        if current[field] != rollback_ref["applied"]:
            raise ConnectorError("The content was changed after this fix was applied. Rolling back automatically "
                                 "could overwrite those later edits, so it was not attempted.", conflict=True)
        data = await self._write(creds, ref, {field: rollback_ref["original"]})
        return {"id": data.get("id"), "modified_gmt": data.get("modified_gmt")}
