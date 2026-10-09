"""SSRF-safe HTTP fetcher used by the crawler, verifier, renderer and integrations.

* Environment proxies are ignored (``trust_env=False``) so the connect-time checks always apply.
* Redirects are followed manually; each hop is validated.
* Responses are streamed and aborted once ``max_bytes`` is exceeded.
* A total deadline applies on top of connect/read timeouts.
"""

from __future__ import annotations

import asyncio
import ssl
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import certifi
import httpcore
import httpx

from app.core.config import get_settings
from app.crawler.ssrf import BlockedURLError, SafeNetworkBackend, validate_url

REDIRECT_CODES = {301, 302, 303, 307, 308}


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    content: bytes = b""
    redirect_chain: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0
    error: str | None = None
    error_kind: str | None = None  # blocked|timeout|too_large|network|redirect_loop|too_many_redirects

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code is not None and 200 <= self.status_code < 300

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def text(self) -> str:
        charset = "utf-8"
        ct = self.headers.get("content-type", "")
        if "charset=" in ct:
            charset = ct.split("charset=")[-1].split(";")[0].strip().strip('"') or "utf-8"
        try:
            return self.content.decode(charset, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")


class SafeTransport(httpx.AsyncHTTPTransport):
    def __init__(self, limits: httpx.Limits | None = None) -> None:
        super().__init__(trust_env=False)
        ctx = ssl.create_default_context(cafile=certifi.where())
        limits = limits or httpx.Limits(max_connections=20, max_keepalive_connections=10)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ctx,
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            network_backend=SafeNetworkBackend(),
        )


class SafeFetcher:
    def __init__(self, user_agent: str | None = None, max_bytes: int | None = None) -> None:
        s = get_settings()
        self.user_agent = user_agent or s.crawler_user_agent
        self.max_bytes = max_bytes or s.crawler_max_response_bytes
        self.timeout = httpx.Timeout(connect=s.crawler_connect_timeout, read=s.crawler_read_timeout,
                                     write=s.crawler_read_timeout, pool=s.crawler_connect_timeout)
        self.total_timeout = s.crawler_total_timeout
        self.max_redirects = s.crawler_max_redirects
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> SafeFetcher:
        self._client = httpx.AsyncClient(
            transport=SafeTransport(), timeout=self.timeout, follow_redirects=False, trust_env=False,
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        assert self._client is not None, "use 'async with SafeFetcher()'"
        return self._client

    async def _one(self, method: str, url: str, headers: dict | None, content: bytes | None,
                   max_bytes: int) -> tuple[int, dict[str, str], bytes, bool]:
        req = self.client.build_request(method, url, headers=headers, content=content)
        resp = await self.client.send(req, stream=True)
        try:
            buf = bytearray()
            too_large = False
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                too_large = True
            else:
                async for chunk in resp.aiter_raw():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        too_large = True
                        break
            raw = bytes(buf)
            # Decode content-encoding ourselves so the size cap applies to compressed bytes,
            # and guard against decompression bombs.
            enc = resp.headers.get("content-encoding", "").lower()
            if enc and not too_large:
                raw, too_large = _decode(raw, enc, max_bytes)
            return resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, raw, too_large
        finally:
            await resp.aclose()

    async def fetch(self, url: str, *, method: str = "GET", follow_redirects: bool = True,
                    headers: dict | None = None, content: bytes | None = None,
                    max_bytes: int | None = None) -> FetchResult:
        max_bytes = max_bytes or self.max_bytes
        result = FetchResult(url=url, final_url=url)
        start = time.monotonic()
        try:
            async with asyncio.timeout(self.total_timeout):
                current = url
                seen: set[str] = set()
                for _ in range(self.max_redirects + 1):
                    validate_url(current)
                    seen.add(current)
                    status, hdrs, body, too_large = await self._one(method, current, headers, content, max_bytes)
                    if follow_redirects and status in REDIRECT_CODES and "location" in hdrs:
                        nxt = urljoin(current, hdrs["location"].strip())
                        result.redirect_chain.append({"url": current, "status": status, "location": nxt})
                        if nxt in seen:
                            result.status_code, result.headers, result.final_url = status, hdrs, current
                            result.error, result.error_kind = "Redirect loop detected.", "redirect_loop"
                            return result
                        if status == 303:
                            method, content = "GET", None
                        current = nxt
                        continue
                    result.final_url, result.status_code, result.headers = current, status, hdrs
                    if too_large:
                        result.error, result.error_kind = f"Response exceeded {max_bytes} bytes.", "too_large"
                        result.content = b""
                    else:
                        result.content = body
                    return result
                result.final_url = current
                result.error, result.error_kind = "Too many redirects.", "too_many_redirects"
                return result
        except BlockedURLError as exc:
            result.error, result.error_kind = str(exc), "blocked"
        except TimeoutError:
            result.error, result.error_kind = "Request timed out.", "timeout"
        except httpx.TimeoutException:
            result.error, result.error_kind = "Request timed out.", "timeout"
        except (httpx.HTTPError, httpcore.ConnectError, OSError, ssl.SSLError) as exc:
            # BlockedURLError raised inside the transport may be wrapped by httpx.
            cause = exc.__cause__ or exc.__context__
            if isinstance(cause, BlockedURLError) or "BlockedURLError" in type(cause).__name__:
                result.error, result.error_kind = str(cause), "blocked"
            else:
                result.error, result.error_kind = f"Network error: {type(exc).__name__}: {exc}"[:500], "network"
        finally:
            result.elapsed_ms = int((time.monotonic() - start) * 1000)
        return result


def _decode(raw: bytes, encoding: str, max_bytes: int) -> tuple[bytes, bool]:
    import zlib

    if encoding in ("gzip", "x-gzip", "deflate"):
        wbits = 16 + zlib.MAX_WBITS if "gzip" in encoding else zlib.MAX_WBITS
        d = zlib.decompressobj(wbits)
        try:
            out = d.decompress(raw, max_bytes + 1)
        except zlib.error:
            try:
                out = zlib.decompressobj(-zlib.MAX_WBITS).decompress(raw, max_bytes + 1)
            except zlib.error:
                return b"", False
        return (b"", True) if len(out) > max_bytes else (out, False)
    # We only advertise gzip/deflate; anything else is passed through undecoded.
    return raw, False
