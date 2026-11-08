"""Small JSON HTTP helper shared by API-key / OAuth connectors (Shopify, Wix, Google).

Every request goes through the SSRF-safe fetcher, redirects are never followed while credentials
are attached, and provider errors are turned into ``ConnectorError`` with a user-safe message.
"""

from __future__ import annotations

import json
from typing import Any

from app.crawler.fetcher import SafeFetcher
from app.crawler.ssrf import BlockedURLError, validate_url
from app.integrations.base import ConnectorError


async def request_json(method: str, url: str, *, headers: dict | None = None, body: Any = None,
                       form: dict | None = None, provider: str = "provider",
                       fetcher_factory=SafeFetcher) -> tuple[int, Any]:
    try:
        validate_url(url)
    except BlockedURLError as exc:
        raise ConnectorError(str(exc)) from exc
    h = {"Accept": "application/json", **(headers or {})}
    content = None
    if form is not None:
        from urllib.parse import urlencode

        h["Content-Type"] = "application/x-www-form-urlencoded"
        content = urlencode(form).encode()
    elif body is not None:
        h["Content-Type"] = "application/json"
        content = json.dumps(body).encode()
    async with fetcher_factory() as f:
        res = await f.fetch(url, method=method, headers=h, content=content, follow_redirects=False,
                            max_bytes=8 * 1024 * 1024)
    if res.error:
        raise ConnectorError(f"Could not reach {provider}: {res.error}")
    try:
        data = json.loads(res.content or b"null")
    except json.JSONDecodeError:
        data = None
    status = res.status_code or 0
    if status in (301, 302, 307, 308):
        raise ConnectorError(f"{provider} redirected the API request; check the store/site address.")
    if status == 401:
        raise ConnectorError(f"{provider} rejected the credentials (the token may be invalid or revoked).", detail=data)
    if status == 403:
        raise ConnectorError(f"The {provider} credentials are not allowed to perform this action "
                             "(a required permission/scope is missing).", detail=data)
    if status == 404:
        raise ConnectorError(f"{provider} resource not found.", detail=data)
    if status == 429:
        raise ConnectorError(f"{provider} rate limit reached; try again in a minute.", detail=data)
    if status >= 400 or status == 0:
        msg = None
        if isinstance(data, dict):
            msg = data.get("message") or data.get("error_description") or data.get("error")
            if isinstance(msg, dict):
                msg = msg.get("message")
        raise ConnectorError(f"{provider} API error (HTTP {status}){': ' + str(msg) if msg else ''}.", detail=data)
    return status, data
