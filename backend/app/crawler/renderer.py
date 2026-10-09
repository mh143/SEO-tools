"""Optional JavaScript rendering with Playwright/Chromium.

Security model: the browser is never allowed to open its own network connections. Every request
it makes (documents, scripts, XHR, images…) is intercepted with ``page.route`` and fulfilled by the
SSRF-safe fetcher, so all SSRF protections (DNS pinning, IP checks, size limits) apply. WebSockets,
service workers, downloads and permissions are disabled. Only same-site sub-resources are fetched;
third-party requests are aborted to bound cost and avoid tracking beacons.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.crawler.fetcher import SafeFetcher
from app.crawler.urls import host_of, same_site

log = logging.getLogger(__name__)

BLOCKED_RESOURCE_TYPES = {"media", "font", "websocket", "eventsource", "manifest", "other"}


class Renderer:
    def __init__(self, timeout_ms: int = 20000, max_requests: int = 150) -> None:
        self.timeout_ms = timeout_ms
        self.max_requests = max_requests
        self._pw = None
        self._browser = None
        self._fetcher: SafeFetcher | None = None

    async def __aenter__(self) -> Renderer:
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        exe = get_settings().chromium_executable_path or None
        self._browser = await self._pw.chromium.launch(
            executable_path=exe, headless=True,
            args=["--disable-background-networking", "--disable-sync", "--no-first-run",
                  "--disable-features=ServiceWorker", "--deny-permission-prompts"],
        )
        self._fetcher = await SafeFetcher().__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._fetcher:
            await self._fetcher.__aexit__(*exc)
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def render(self, url: str) -> str | None:
        assert self._browser and self._fetcher
        root = host_of(url)
        ctx = await self._browser.new_context(
            java_script_enabled=True, accept_downloads=False, service_workers="block",
            user_agent=get_settings().crawler_user_agent, ignore_https_errors=False,
        )
        count = 0

        async def handle(route):
            nonlocal count
            req = route.request
            count += 1
            if (count > self.max_requests or req.resource_type in BLOCKED_RESOURCE_TYPES
                    or req.method not in ("GET", "HEAD") or not same_site(req.url, root)):
                await route.abort()
                return
            res = await self._fetcher.fetch(req.url, follow_redirects=True, max_bytes=3 * 1024 * 1024)
            if res.error or res.status_code is None:
                await route.abort()
                return
            headers = {k: v for k, v in res.headers.items()
                       if k in ("content-type", "cache-control", "last-modified", "etag")}
            await route.fulfill(status=res.status_code, headers=headers, body=res.content)

        try:
            await ctx.route("**/*", handle)
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
            return await page.content()
        except Exception as exc:
            log.info("render failed for %s: %s", url, exc)
            return None
        finally:
            await ctx.close()
