"""A fake WordPress site implementing the subset of the core REST API the connector uses, and
rendering public pages from the stored state so verification sees real HTML.

It follows the documented response shapes of WordPress core (wp/v2 posts/pages/media/users,
context=edit raw fields, Application Password Basic auth). It is a contract-test double, not WordPress.
"""

from __future__ import annotations

import base64
import html
import json
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from tests.fixtures.site import FixtureSite

APP_PASSWORD = "abcd EFGH 1234 ijkl MNOP 5678"


class FakeWordPress:
    def __init__(self, *, editor_caps: bool = True):
        self.site = FixtureSite({"*": self._route})
        self.editor_caps = editor_caps
        self.stale = False  # simulate a CDN serving old HTML
        self._stale_html: dict[str, str] = {}
        self.pages = {
            12: {"slug": "about", "title": "About", "status": "publish",
                 "content": "<!-- wp:paragraph -->\n<p>We roast coffee in Halifax since 2015. Read our "
                            "<a href=\"/old-shop/\">shop page</a>.</p>\n<!-- /wp:paragraph -->\n"
                            "<!-- wp:heading -->\n<h2>What beans do you use?</h2>\n<!-- /wp:heading -->\n"
                            "<!-- wp:image -->\n<figure><img src=\"/wp-content/uploads/beans.jpg\" class=\"wp-image-7\"></figure>\n"
                            "<!-- /wp:image -->\n<p>We buy single-origin beans from Colombia and Ethiopia.</p>"},
        }
        self.media = {7: {"alt_text": ""}}
        self.writes: list[dict] = []

    @property
    def base(self):
        return self.site.base

    def __enter__(self):
        self.site.__enter__()
        return self

    def __exit__(self, *exc):
        self.site.__exit__(*exc)

    # ---------------------------------------------------------------- helpers
    def _authed(self, h) -> bool:
        auth = h.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return False
        user, _, pw = base64.b64decode(auth[6:]).decode().partition(":")
        return user == "admin" and pw == APP_PASSWORD

    def _page_json(self, pid: int, edit: bool):
        p = self.pages[pid]
        d = {"id": pid, "slug": p["slug"], "status": p["status"], "link": f"{self.base}/{p['slug']}/",
             "modified_gmt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
             "title": {"rendered": html.escape(p["title"])}, "content": {"rendered": p["content"]}}
        if edit:
            d["title"]["raw"] = p["title"]
            d["content"]["raw"] = p["content"]
        return d

    def render(self, pid: int) -> str:
        p = self.pages[pid]
        return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                f"<title>{html.escape(p['title'])}</title>"
                f"<link rel='canonical' href='{self.base}/{p['slug']}/'>"
                f"<link rel='alternate' type='application/json' href='{self.base}/wp-json/wp/v2/pages/{pid}'>"
                f"</head><body><main><h1>{html.escape(p['title'])}</h1>{p['content']}</main></body></html>")

    def _json(self, status, data):
        return status, {"Content-Type": "application/json"}, json.dumps(data)

    # ---------------------------------------------------------------- routing
    def _route(self, h):
        u = urlsplit(h.path)
        path, qs = u.path, parse_qs(u.query)
        method = h.command
        if path in ("/wp-json", "/wp-json/"):
            return self._json(200, {
                "name": "Bean There", "url": self.base, "home": self.base, "namespaces": ["wp/v2"], "routes": {},
                "authentication": {"application-passwords": {"endpoints": {
                    "authorization": f"{self.base}/wp-admin/authorize-application.php"}}}})
        if path.startswith("/wp-json/"):
            if not self._authed(h):
                return self._json(401, {"code": "rest_not_logged_in", "message": "You are not currently logged in."})
            route = path[len("/wp-json"):]
            if route == "/wp/v2/users/me":
                caps = {"edit_posts": True, "edit_pages": True, "upload_files": True,
                        "edit_published_posts": self.editor_caps, "edit_published_pages": self.editor_caps,
                        "edit_others_posts": self.editor_caps, "edit_others_pages": self.editor_caps}
                return self._json(200, {"id": 1, "username": "admin", "slug": "admin", "roles": ["administrator"],
                                        "capabilities": caps})
            m = re.fullmatch(r"/wp/v2/(pages|posts)", route)
            if m and method == "GET":
                if m.group(1) == "posts":
                    return self._json(200, [])
                slug = qs.get("slug", [""])[0]
                return self._json(200, [self._page_json(i, True) for i, p in self.pages.items() if p["slug"] == slug])
            m = re.fullmatch(r"/wp/v2/pages/(\d+)", route)
            if m:
                pid = int(m.group(1))
                if pid not in self.pages:
                    return self._json(404, {"code": "rest_post_invalid_id", "message": "Invalid post ID."})
                if method == "POST":
                    body = json.loads(h.body or b"{}")
                    if not self.editor_caps:
                        return self._json(403, {"code": "rest_cannot_edit", "message": "Sorry, you are not allowed to edit this post."})
                    if not self.stale:
                        self._stale_html.pop(self.pages[pid]["slug"], None)
                    else:
                        self._stale_html.setdefault(self.pages[pid]["slug"], self.render(pid))
                    for k in ("title", "content"):
                        if k in body:
                            self.pages[pid][k] = body[k]
                    self.writes.append({"id": pid, **body})
                    return self._json(200, self._page_json(pid, True))
                return self._json(200, self._page_json(pid, "edit" in qs.get("context", [""])))
            m = re.fullmatch(r"/wp/v2/media/(\d+)", route)
            if m and method == "POST":
                mid = int(m.group(1))
                self.media.setdefault(mid, {})["alt_text"] = json.loads(h.body or b"{}").get("alt_text", "")
                return self._json(200, {"id": mid, "alt_text": self.media[mid]["alt_text"]})
            return self._json(404, {"code": "rest_no_route", "message": "No route was found."})
        for pid, p in self.pages.items():
            if path in (f"/{p['slug']}/", f"/{p['slug']}"):
                if path == f"/{p['slug']}":
                    return 301, {"Location": f"/{p['slug']}/"}, ""
                if self.stale and p["slug"] in self._stale_html:
                    return 200, {}, self._stale_html[p["slug"]]
                return 200, {}, self.render(pid)
        if path == "/":
            return 200, {}, ("<!doctype html><html lang='en'><head><title>Bean There</title></head><body><main>"
                             "<h1>Bean There</h1><p><a href='/about/'>About</a></p></main></body></html>")
        return 404, {}, "<html><body>Not found</body></html>"
