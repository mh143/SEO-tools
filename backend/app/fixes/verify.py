"""Independent verification: fetch the live page and check that the intended change is visible.

This never trusts the provider's response. A fix is only ``verified`` if these checks pass.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode, urlsplit, urlunsplit

from app.crawler.extractor import extract
from app.crawler.fetcher import SafeFetcher
from app.crawler.urls import host_of, normalize_url


def _n(s: str | None) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip().lower()


def _bust(url: str) -> str:
    p = urlsplit(url)
    q = (p.query + "&" if p.query else "") + urlencode({"_rlv": secrets.token_hex(4)})
    return urlunsplit((p.scheme, p.netloc, p.path, q, ""))


def _variants(url: str) -> set[str]:
    n = normalize_url(url) or url
    return {n, n.rstrip("/"), n.rstrip("/") + "/"}


def checks_for(fix_type: str, before: dict, after: dict, ex: dict, expect_reverted: bool = False) -> list[dict]:
    """Build check results comparing the extracted live page with the expected state."""
    checks: list[dict] = []

    def add(name, expected, observed, passed):
        checks.append({"name": name, "expected": expected, "observed": observed, "passed": bool(passed)})

    title = ex.get("title") or ""
    if fix_type == "meta_title":
        exp = after.get("title", "")
        add("<title> contains the new title", exp, title, _n(exp) in _n(title) if not expect_reverted else _n(exp) not in _n(title))
    elif fix_type == "h1":
        exp = after.get("h1", "")
        h1s = ex.get("h1s", [])
        found = any(_n(exp) == _n(h) or _n(exp) in _n(h) for h in h1s)
        add("An H1 contains the new heading", exp, h1s, found if not expect_reverted else not found)
    elif fix_type == "meta_description":
        exp = after.get("description", "")
        obs = ex.get("meta_description")
        add("Meta description matches", exp, obs, (_n(obs) == _n(exp)) != expect_reverted)
    elif fix_type == "image_alt":
        src = before.get("src") or ""
        variants = _variants(src)
        imgs = [i for i in ex.get("images", []) if (normalize_url(i.get("src") or "") or "") in variants or i.get("src") in variants]
        exp = after.get("alt", "")
        ok = bool(imgs) and all(_n(i.get("alt")) == _n(exp) for i in imgs)
        add("Image has the new alt text", exp, [i.get("alt") for i in imgs] or "image not found", ok != expect_reverted if imgs else False)
    elif fix_type == "answer_paragraph":
        exp = _n(after.get("answer_html", ""))
        text = _n(ex.get("main_text", ""))
        add("Answer text is present on the page", exp[:200], "found" if exp in text else "not found", (exp in text) != expect_reverted)
    elif fix_type == "faq_section":
        text = _n(ex.get("main_text", ""))
        for item in after.get("items", []):
            q = _n(item.get("question"))
            add(f"FAQ question present: {item.get('question')}", q, "found" if q in text else "not found", (q in text) != expect_reverted)
    elif fix_type == "internal_link_update":
        links = {link["href"] for link in ex.get("links", [])}
        old = _variants(before.get("old_href") or "")
        new = _variants(after.get("new_href") or "")
        add("No link to the old URL", sorted(old)[0] if old else "", "present" if links & old else "absent",
            (not (links & old)) != expect_reverted)
        add("Link to the new URL exists", sorted(new)[0] if new else "", "present" if links & new else "absent",
            bool(links & new) != expect_reverted)
    elif fix_type == "internal_link_add":
        links = {link["href"] for link in ex.get("links", [])}
        tgt = _variants(after.get("target_url") or "")
        add("Link to the target page exists", after.get("target_url"), "present" if links & tgt else "absent",
            bool(links & tgt) != expect_reverted)
    elif fix_type == "canonical":
        exp = normalize_url(after.get("canonical_url") or "") or ""
        tags = ex.get("canonical_tags", [])
        add("Exactly one canonical pointing to the expected URL", exp, tags,
            (len(set(tags)) == 1 and tags[0].rstrip("/") == exp.rstrip("/")) != expect_reverted)
    elif fix_type == "json_ld":
        try:
            expected = json.loads(after.get("json_ld") or "{}")
            exp_types = {expected.get("@type")} if isinstance(expected, dict) else {n.get("@type") for n in expected}
        except (json.JSONDecodeError, AttributeError):
            exp_types = set()
        valid = [j for j in ex.get("json_ld", []) if j.get("valid")]
        found = set().union(*[set(j.get("types", [])) for j in valid]) if valid else set()
        ok = bool(exp_types) and exp_types <= found and all(j.get("valid") for j in ex.get("json_ld", []))
        add("Valid JSON-LD with the expected @type present", sorted(t for t in exp_types if t), sorted(found), ok != expect_reverted)
    elif fix_type == "robots_directive":
        directives = " ".join(ex.get("meta_robots", [])).lower()
        add("No noindex directive", "no noindex", directives or "(none)", ("noindex" not in directives) != expect_reverted)
    return checks


async def verify_live(fix_type: str, url: str, before: dict, after: dict, *, expect_reverted: bool = False) -> dict:
    """Fetch the live page (bypassing caches where possible) and run the checks."""
    result: dict = {"checked_at": datetime.now(UTC).isoformat(), "url": url, "passed": False, "checks": []}
    async with SafeFetcher() as f:
        if fix_type in ("redirect", "broken_link"):
            r = await f.fetch(after.get("from_url") or url, follow_redirects=False)
            loc = normalize_url(r.headers.get("location", ""), url) if r.headers.get("location") else None
            to = normalize_url(after.get("to_url") or "") or ""
            redirected = bool(r.status_code in (301, 308) and loc and loc.rstrip("/") == to.rstrip("/"))
            ok = (not redirected) if expect_reverted else (redirected or r.status_code == 200)
            name = ("Old URL no longer redirects to the target" if expect_reverted
                    else "Old URL redirects (301/308) to the target or returns 200")
            result["checks"] = [{"name": name, "expected": to,
                                 "observed": {"status": r.status_code, "location": loc}, "passed": bool(ok)}]
            result["status_code"] = r.status_code
            result["passed"] = bool(ok)
            return result
        attempts = []
        for target in (url, _bust(url)):
            r = await f.fetch(target, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
            if r.error or not r.ok:
                attempts.append({"url": target, "error": r.error, "status": r.status_code})
                continue
            ex = extract(r.text, r.final_url, host_of(url))
            checks = checks_for(fix_type, before, after, ex, expect_reverted)
            result.update({"status_code": r.status_code, "checks": checks, "fetched_url": target,
                           "passed": bool(checks) and all(c["passed"] for c in checks)})
            if result["passed"]:
                return result
        if attempts and not result["checks"]:
            result["error"] = f"Could not fetch the live page: {attempts[-1]}"
    return result
