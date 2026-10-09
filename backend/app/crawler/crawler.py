"""Breadth-first crawler with safety limits.

Respects robots.txt (RFC 9309), stays on the start host (www/apex treated as one site), never
submits forms, never sends credentials, and stops at the configured page/depth limits.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.crawler.extractor import extract
from app.crawler.fetcher import FetchResult, SafeFetcher
from app.crawler.robots import Robots, parse_robots
from app.crawler.sitemap import SitemapResult, discover_sitemaps
from app.crawler.ssrf import BlockedURLError, validate_url
from app.crawler.urls import host_of, looks_like_page, normalize_url, origin, same_site

log = logging.getLogger(__name__)

HTML_TYPES = ("text/html", "application/xhtml+xml")


@dataclass
class CrawlConfig:
    start_url: str
    max_pages: int = 25
    max_depth: int = 3
    render_js: bool = False
    respect_robots: bool = True
    concurrency: int | None = None
    delay: float | None = None


@dataclass
class PageResult:
    url: str
    depth: int
    fetch: FetchResult | None
    extracted: dict | None = None
    rendered: bool = False
    robots_blocked: bool = False
    confirmed_error: bool = False  # error status re-checked and reproduced
    html: str | None = None


@dataclass
class CrawlOutput:
    start_url: str
    resolved_start_url: str | None = None
    root_host: str = ""
    robots: Robots = field(default_factory=Robots)
    robots_status: int | None = None
    robots_error: str | None = None
    sitemap: SitemapResult = field(default_factory=SitemapResult)
    pages: dict[str, PageResult] = field(default_factory=dict)
    inlinks: dict[str, list[dict]] = field(default_factory=dict)  # target -> [{source, text}]
    limit_reached: bool = False
    fatal_error: str | None = None
    cancelled: bool = False
    rendered_count: int = 0
    llms_txt: dict | None = None


ProgressCb = Callable[[CrawlOutput, int], Awaitable[None] | None]


def _needs_render(extracted: dict, html: str) -> bool:
    low = html.lower()
    spa_marker = any(m in low for m in ('id="root"></div>', 'id="__next"></div>', 'id="app"></div>', "ng-app"))
    return extracted.get("word_count", 0) < 60 and (spa_marker or low.count("<script") >= 3)


async def crawl(cfg: CrawlConfig, *, on_progress: ProgressCb | None = None,
                should_cancel: Callable[[], bool] | None = None, renderer=None) -> CrawlOutput:
    s = get_settings()
    out = CrawlOutput(start_url=cfg.start_url)
    max_pages = max(1, min(cfg.max_pages, s.crawler_hard_max_pages))
    max_depth = max(0, min(cfg.max_depth, s.crawler_hard_max_depth))
    concurrency = max(1, min(cfg.concurrency or s.crawler_concurrency, 8))
    delay = s.crawler_delay_seconds if cfg.delay is None else cfg.delay

    try:
        start = validate_url(cfg.start_url)
    except BlockedURLError as exc:
        out.fatal_error = str(exc)
        return out
    start = normalize_url(start) or start

    async with SafeFetcher() as fetcher:
        first = await fetcher.fetch(start)
        if first.error and first.error_kind == "blocked":
            out.fatal_error = first.error
            return out
        if first.error and not first.redirect_chain:
            out.fatal_error = f"Could not fetch the start URL: {first.error}"
            return out
        resolved = normalize_url(first.final_url) or first.final_url
        out.resolved_start_url = resolved
        out.root_host = host_of(resolved)
        site_origin = origin(resolved)

        # robots.txt
        if cfg.respect_robots:
            rr = await fetcher.fetch(f"{site_origin}/robots.txt", max_bytes=512 * 1024)
            out.robots_status = rr.status_code
            if rr.error:
                out.robots_error = rr.error
                out.robots = Robots(disallow_all=True)
            elif rr.status_code == 200:
                out.robots = parse_robots(rr.text)
                out.robots.status_code = 200
            elif rr.status_code is not None and 400 <= rr.status_code < 500:
                out.robots = Robots(fetched=False, status_code=rr.status_code)  # allow all
            else:
                out.robots = Robots(disallow_all=True, status_code=rr.status_code)
                out.robots_error = f"robots.txt returned HTTP {rr.status_code}; treated as 'disallow all' (RFC 9309)."
        ua_token = "RankLensBot"
        crawl_delay = out.robots.crawl_delay(ua_token)
        if crawl_delay:
            delay = max(delay, min(crawl_delay, 5.0))

        # llms.txt (informational only)
        lt = await fetcher.fetch(f"{site_origin}/llms.txt", max_bytes=256 * 1024)
        out.llms_txt = {"status": lt.status_code, "bytes": len(lt.content),
                        "present": lt.status_code == 200 and bool(lt.content.strip())
                        and lt.content_type not in HTML_TYPES}

        out.sitemap = await discover_sitemaps(fetcher, site_origin, out.robots.sitemaps, out.root_host)

        queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        seen: set[str] = set()

        def enqueue(u: str, depth: int) -> None:
            if u in seen or depth > max_depth:
                return
            if len(seen) >= max_pages:
                out.limit_reached = True
                return
            seen.add(u)
            queue.put_nowait((u, depth))

        enqueue(resolved, 0)
        for u in list(out.sitemap.urls)[: max_pages * 2]:
            if looks_like_page(u):
                enqueue(u, 1)
        # Record the original start URL hop if it redirected.
        if start != resolved:
            out.pages[start] = PageResult(url=start, depth=0, fetch=first)
            seen.add(start)

        async def handle(url: str, depth: int) -> None:
            if cfg.respect_robots and not out.robots.is_allowed(url, ua_token):
                out.pages[url] = PageResult(url=url, depth=depth, fetch=None, robots_blocked=True)
                return
            if url == resolved and not first.error:
                res = dataclasses.replace(first, url=url, redirect_chain=[])
            else:
                res = await fetcher.fetch(url)
            if (res.error and res.error_kind in ("timeout", "network")) or (res.status_code and res.status_code >= 500):
                await asyncio.sleep(min(1.0, delay * 4) if delay else 0)
                retry = await fetcher.fetch(url)
                confirmed = bool(retry.error or (retry.status_code and retry.status_code >= 500))
                res = retry
            else:
                confirmed = bool(res.status_code and res.status_code >= 400)
            pr = PageResult(url=url, depth=depth, fetch=res, confirmed_error=confirmed)
            out.pages[url] = pr
            final = normalize_url(res.final_url) or res.final_url
            if final != url:
                seen.add(final)
            if res.ok and res.content_type in HTML_TYPES and same_site(final, out.root_host):
                html = res.text
                ex = extract(html, final, out.root_host)
                if cfg.render_js and renderer is not None and _needs_render(ex, html):
                    rendered_html = await renderer.render(final)
                    if rendered_html:
                        ex = extract(rendered_html, final, out.root_host)
                        pr.rendered = True
                        out.rendered_count += 1
                        html = rendered_html
                pr.extracted, pr.html = ex, html
                for link in ex.get("links", []):
                    if not link["internal"]:
                        continue
                    target = link["href"]
                    out.inlinks.setdefault(target, []).append({"source": final, "text": link["text"][:120]})
                    if looks_like_page(target) and urlsplit(target).scheme in ("http", "https"):
                        enqueue(target, depth + 1)

        async def worker() -> None:
            while True:
                try:
                    url, depth = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    if should_cancel and should_cancel():
                        out.cancelled = True
                        return
                    await handle(url, depth)
                    if on_progress:
                        r = on_progress(out, len(seen))
                        if asyncio.iscoroutine(r):
                            await r
                    if delay:
                        await asyncio.sleep(delay)
                except Exception as exc:  # one bad page must not kill the crawl
                    log.exception("crawl page failed: %s", url)
                    out.pages[url] = PageResult(url=url, depth=depth, fetch=FetchResult(
                        url=url, final_url=url, error=f"Internal error while processing page: {type(exc).__name__}",
                        error_kind="internal"))
                finally:
                    queue.task_done()

        # Workers exit when the queue is momentarily empty; loop until nothing remains.
        while not queue.empty() and not out.cancelled:
            await asyncio.gather(*(worker() for _ in range(concurrency)))
    return out
