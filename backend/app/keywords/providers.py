"""Keyword data providers.

Measured metrics (search volume, CPC, difficulty) only ever come from a named provider. AI-generated
ideas never carry metrics. This module implements DataForSEO v3 (HTTP Basic auth):

* Search volume: POST /v3/keywords_data/google_ads/search_volume/live
* Difficulty:    POST /v3/dataforseo_labs/google/bulk_keyword_difficulty/live
* Ideas:         POST /v3/dataforseo_labs/google/keyword_ideas/live

It has been tested against mocked responses shaped like the documented API, not against the live
service (no credentials were available during development).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import get_settings

PROVIDER_LABEL = "DataForSEO (Google Ads volume, DataForSEO Labs difficulty)"


class KeywordProviderError(Exception):
    pass


@dataclass
class KeywordMetric:
    keyword: str
    search_volume: int | None
    cpc: float | None
    competition: str | None
    difficulty: float | None
    intent: str | None = None


def dataforseo_configured() -> bool:
    s = get_settings()
    return bool(s.dataforseo_login and s.dataforseo_password)


class DataForSEO:
    def __init__(self) -> None:
        s = get_settings()
        if not dataforseo_configured():
            raise KeywordProviderError("DataForSEO credentials are not configured.")
        self.base = s.dataforseo_base_url.rstrip("/")
        self.auth = (s.dataforseo_login, s.dataforseo_password)

    async def _post(self, client: httpx.AsyncClient, path: str, payload: list[dict]) -> dict:
        try:
            r = await client.post(self.base + path, json=payload, auth=self.auth, timeout=60)
        except httpx.HTTPError as exc:
            raise KeywordProviderError(f"Could not reach DataForSEO: {type(exc).__name__}") from exc
        if r.status_code != 200:
            raise KeywordProviderError(f"DataForSEO returned HTTP {r.status_code}.")
        data = r.json()
        if data.get("status_code") != 20000:
            raise KeywordProviderError(f"DataForSEO error: {data.get('status_message')}")
        task = (data.get("tasks") or [{}])[0]
        if task.get("status_code") != 20000:
            raise KeywordProviderError(f"DataForSEO task error: {task.get('status_message')}")
        return task

    async def metrics(self, keywords: list[str], location: str, language: str) -> list[KeywordMetric]:
        keywords = [k.strip().lower() for k in keywords if k.strip()][:100]
        async with httpx.AsyncClient() as c:
            vol = await self._post(c, "/v3/keywords_data/google_ads/search_volume/live",
                                   [{"keywords": keywords, "location_name": location, "language_code": language}])
            diff = await self._post(c, "/v3/dataforseo_labs/google/bulk_keyword_difficulty/live",
                                    [{"keywords": keywords, "location_name": location, "language_code": language}])
        difficulty = {}
        for res in diff.get("result") or []:
            for it in res.get("items") or []:
                difficulty[it.get("keyword")] = it.get("keyword_difficulty")
        out = []
        for it in vol.get("result") or []:
            kw = it.get("keyword")
            out.append(KeywordMetric(kw, it.get("search_volume"), it.get("cpc"), it.get("competition"), difficulty.get(kw)))
        return out

    async def ideas(self, seeds: list[str], location: str, language: str, limit: int = 50) -> list[KeywordMetric]:
        async with httpx.AsyncClient() as c:
            task = await self._post(c, "/v3/dataforseo_labs/google/keyword_ideas/live",
                                    [{"keywords": seeds[:20], "location_name": location, "language_code": language,
                                      "limit": limit}])
        out = []
        for res in task.get("result") or []:
            for it in res.get("items") or []:
                info = it.get("keyword_info") or {}
                props = it.get("keyword_properties") or {}
                intent = (it.get("search_intent_info") or {}).get("main_intent")
                out.append(KeywordMetric(it.get("keyword"), info.get("search_volume"), info.get("cpc"),
                                         info.get("competition_level"), props.get("keyword_difficulty"), intent))
        return out
