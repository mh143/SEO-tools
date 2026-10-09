"""Sitemap discovery and parsing (XML and sitemap index, optionally gzipped).

The XML parser disables entity resolution, DTD loading and network access (XXE-safe) and
decompression is size-capped.
"""

from __future__ import annotations

import gzip
import io
from dataclasses import dataclass, field

from lxml import etree

from app.crawler.fetcher import SafeFetcher
from app.crawler.urls import normalize_url, same_site

MAX_SITEMAPS = 25
MAX_URLS = 50_000
MAX_SITEMAP_BYTES = 50 * 1024 * 1024  # protocol limit (uncompressed)


@dataclass
class SitemapResult:
    sitemaps: list[dict] = field(default_factory=list)  # {url, status, kind, url_count, errors}
    urls: dict[str, dict] = field(default_factory=dict)  # url -> {lastmod, sitemap}
    errors: list[dict] = field(default_factory=list)


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False, recover=False)


def _ln(el) -> str | None:
    return etree.QName(el).localname if isinstance(el.tag, str) else None


def _gunzip_capped(data: bytes) -> bytes | None:
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as f:
        out = f.read(MAX_SITEMAP_BYTES + 1)
    return None if len(out) > MAX_SITEMAP_BYTES else out


async def discover_sitemaps(fetcher: SafeFetcher, origin: str, robots_sitemaps: list[str], root_host: str) -> SitemapResult:
    res = SitemapResult()
    queue: list[tuple[str, str]] = [(u, "robots.txt") for u in robots_sitemaps]
    if not queue:
        queue = [(f"{origin}/sitemap.xml", "default location"), (f"{origin}/sitemap_index.xml", "default location")]
    seen: set[str] = set()
    while queue and len(res.sitemaps) < MAX_SITEMAPS:
        url, source = queue.pop(0)
        url = normalize_url(url) or url
        if url in seen:
            continue
        seen.add(url)
        entry: dict = {"url": url, "source": source, "status": None, "kind": None, "url_count": 0, "errors": []}
        res.sitemaps.append(entry)
        if not same_site(url, root_host):
            entry["errors"].append("Sitemap is hosted on a different host and was not fetched.")
            continue
        r = await fetcher.fetch(url, max_bytes=MAX_SITEMAP_BYTES)
        entry["status"] = r.status_code
        if r.error:
            entry["errors"].append(r.error)
            continue
        if r.status_code != 200:
            if source != "default location":
                entry["errors"].append(f"Sitemap returned HTTP {r.status_code}.")
            else:
                entry["missing"] = True
            continue
        body = r.content
        if url.endswith(".gz") or body[:2] == b"\x1f\x8b":
            try:
                body = _gunzip_capped(body)
            except OSError:
                body = None
            if body is None:
                entry["errors"].append("Gzipped sitemap is invalid or exceeds 50 MB uncompressed.")
                continue
        try:
            root = etree.fromstring(body, _parser())
        except etree.XMLSyntaxError as exc:
            entry["errors"].append(f"Invalid XML: {exc}"[:300])
            continue
        tag = etree.QName(root).localname
        locs = [el.text.strip() for el in root.iter(etree.Element) if _ln(el) == "loc" and el.text]
        if tag == "sitemapindex":
            entry["kind"] = "index"
            entry["url_count"] = len(locs)
            queue.extend((loc, f"index {url}") for loc in locs)
        elif tag == "urlset":
            entry["kind"] = "urlset"
            entry["url_count"] = len(locs)
            if len(locs) > MAX_URLS:
                entry["errors"].append(f"Sitemap lists {len(locs)} URLs; the protocol limit is 50,000.")
            lastmods = {}
            for u_el in root:
                if _ln(u_el) != "url":
                    continue
                loc = lm = None
                for c in u_el:
                    n = _ln(c)
                    if n == "loc" and c.text:
                        loc = c.text.strip()
                    elif n == "lastmod" and c.text:
                        lm = c.text.strip()
                if loc:
                    lastmods[loc] = lm
            off_host = 0
            for loc in locs[:MAX_URLS]:
                n = normalize_url(loc)
                if not n:
                    continue
                if not same_site(n, root_host):
                    off_host += 1
                    continue
                res.urls.setdefault(n, {"lastmod": lastmods.get(loc), "sitemap": url})
            if off_host:
                entry["errors"].append(f"{off_host} URL(s) point to a different host.")
        else:
            entry["errors"].append(f"Unexpected root element <{tag}>; expected <urlset> or <sitemapindex>.")
    for e in res.sitemaps:
        for msg in e["errors"]:
            res.errors.append({"sitemap": e["url"], "error": msg})
    return res
