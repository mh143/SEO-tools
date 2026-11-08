"""Google Search Console (read-only search performance data).

OAuth 2.0 web-server flow with Google (scope ``webmasters.readonly``, offline access). The refresh
token is encrypted at rest; access tokens are cached in-process until shortly before they expire.
The connected *property* must belong to the website (a ``sc-domain:`` property for the registrable
domain or a URL-prefix property on the same host).

Data comes from the Search Analytics API (``searchAnalytics/query``) and is labelled as Google's
measured data. Google reports with a delay of ~2-3 days; we never extrapolate.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote, urlencode, urlsplit

from app.core.config import get_settings
from app.integrations.base import ConnectorError
from app.integrations.http import request_json

SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
PROVIDER = "google_search_console"

_token_cache: dict[str, tuple[str, float]] = {}


def configured() -> bool:
    s = get_settings()
    return bool(s.google_client_id and s.google_client_secret)


def redirect_uri() -> str:
    s = get_settings()
    return f"{s.public_app_url}{s.api_base_path}/integrations/google/callback"


def authorization_url(state: str) -> str:
    s = get_settings()
    q = {"client_id": s.google_client_id, "redirect_uri": redirect_uri(), "response_type": "code", "scope": SCOPE,
         "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state}
    return f"{s.google_oauth_authorize_url}?{urlencode(q)}"


async def exchange_code(code: str) -> dict:
    s = get_settings()
    _, data = await request_json("POST", s.google_token_url, provider="Google", form={
        "code": code, "client_id": s.google_client_id, "client_secret": s.google_client_secret,
        "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
    if not isinstance(data, dict) or not data.get("refresh_token"):
        raise ConnectorError("Google did not return offline access. Remove RankLens from your Google account's "
                             "third-party access and connect again.")
    return data


async def access_token(creds: dict) -> str:
    key = creds["refresh_token"][-24:]
    hit = _token_cache.get(key)
    if hit and hit[1] > time.time() + 60:
        return hit[0]
    s = get_settings()
    _, data = await request_json("POST", s.google_token_url, provider="Google", form={
        "refresh_token": creds["refresh_token"], "client_id": s.google_client_id,
        "client_secret": s.google_client_secret, "grant_type": "refresh_token"})
    tok = (data or {}).get("access_token")
    if not tok:
        raise ConnectorError("Google access was revoked; reconnect Search Console.")
    _token_cache[key] = (tok, time.time() + int((data or {}).get("expires_in", 3600)))
    return tok


async def list_sites(creds: dict) -> list[dict]:
    tok = await access_token(creds)
    _, data = await request_json("GET", f"{get_settings().gsc_api_base}/sites", provider="Google Search Console",
                                 headers={"Authorization": f"Bearer {tok}"})
    return [x for x in (data or {}).get("siteEntry", []) if x.get("permissionLevel") != "siteUnverifiedUser"]


def _registrable(host: str) -> str:
    host = host.lower().removeprefix("www.")
    return host


def matching_properties(sites: list[dict], hostname: str) -> list[str]:
    """Properties that cover ``hostname``: domain properties first, then URL-prefix properties on that host."""
    host = hostname.lower()
    out_domain, out_prefix = [], []
    for s in sites:
        url = s.get("siteUrl", "")
        if url.startswith("sc-domain:"):
            dom = url[len("sc-domain:"):].lower()
            if host == dom or host.endswith("." + dom):
                out_domain.append(url)
        else:
            h = (urlsplit(url).hostname or "").lower()
            if h == host or _registrable(h) == _registrable(host):
                out_prefix.append(url)
    return out_domain + out_prefix


async def query(creds: dict, body: dict) -> list[dict]:
    tok = await access_token(creds)
    prop = quote(creds["property"], safe="")
    _, data = await request_json("POST", f"{get_settings().gsc_api_base}/sites/{prop}/searchAnalytics/query",
                                 provider="Google Search Console", headers={"Authorization": f"Bearer {tok}"}, body=body)
    return (data or {}).get("rows", [])


def _row(r: dict, key: str | None = None) -> dict:
    out = {"clicks": int(r.get("clicks", 0)), "impressions": int(r.get("impressions", 0)),
           "ctr": round(float(r.get("ctr", 0.0)), 4), "position": round(float(r.get("position", 0.0)), 1)}
    if key:
        out[key] = (r.get("keys") or [""])[0]
    return out


async def performance(creds: dict, days: int = 28) -> dict:
    days = max(7, min(int(days), 480))
    end = date.today() - timedelta(days=2)  # GSC data is delayed
    start = end - timedelta(days=days - 1)
    base = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dataState": "final"}
    by_date = await query(creds, {**base, "dimensions": ["date"], "rowLimit": 500})
    queries = await query(creds, {**base, "dimensions": ["query"], "rowLimit": 25})
    pages = await query(creds, {**base, "dimensions": ["page"], "rowLimit": 25})
    totals = {"clicks": 0, "impressions": 0}
    wpos = 0.0
    for r in by_date:
        totals["clicks"] += int(r.get("clicks", 0))
        totals["impressions"] += int(r.get("impressions", 0))
        wpos += float(r.get("position", 0.0)) * int(r.get("impressions", 0))
    totals["ctr"] = round(totals["clicks"] / totals["impressions"], 4) if totals["impressions"] else 0.0
    totals["position"] = round(wpos / totals["impressions"], 1) if totals["impressions"] else None
    return {
        "property": creds["property"], "start_date": start.isoformat(), "end_date": end.isoformat(), "days": days,
        "totals": totals, "by_date": [_row(r, "date") for r in by_date],
        "top_queries": [_row(r, "query") for r in queries], "top_pages": [_row(r, "page") for r in pages],
        "fetched_at": datetime.now(UTC).isoformat(), "source": "Google Search Console (measured)",
    }
