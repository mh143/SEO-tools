from __future__ import annotations

import asyncio
import re
from collections import Counter
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.provider import AIError, AINotConfigured, get_provider
from app.ai.tasks import SYSTEM_PROMPT, TASKS, build_user_message, validate_output
from app.audit.rules.content import STOPWORDS
from app.billing import entitlements
from app.keywords.providers import PROVIDER_LABEL, DataForSEO, KeywordProviderError, dataforseo_configured
from app.models import CrawlRun, CrawlStatus, KeywordResearch, Page, Website


def latest_pages(db: Session, website: Website, limit: int = 300) -> list[Page]:
    run = db.scalar(select(CrawlRun).where(CrawlRun.website_id == website.id, CrawlRun.org_id == website.org_id,
                                           CrawlRun.status.in_([CrawlStatus.completed, CrawlStatus.partial]))
                    .order_by(CrawlRun.created_at.desc()).limit(1))
    if not run:
        return []
    return list(db.scalars(select(Page).where(Page.crawl_run_id == run.id, Page.org_id == website.org_id,
                                              Page.status_code == 200).limit(limit)))


def _best_page(keyword: str, pages: list[Page]) -> str | None:
    words = set(keyword.lower().split())
    best, score = None, 0
    for p in pages:
        hay = f"{p.title or ''} {p.h1 or ''}".lower()
        s = sum(1 for w in words if w in hay)
        if s > score:
            best, score = p.url, s
    return best if score >= max(1, len(words) // 2) else None


def on_page_terms(db: Session, website: Website) -> list[KeywordResearch]:
    pages = latest_pages(db, website)
    if not pages:
        raise HTTPException(status_code=409, detail="Run an audit first; on-page terms come from crawled pages.")
    counts: Counter = Counter()
    where: dict[str, str] = {}
    for p in pages:
        heads = [p.title or "", p.h1 or ""] + [h["text"] for h in (p.extracted or {}).get("headings", []) if h["level"] <= 3]
        for text in heads:
            words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z'\-]+", text.lower()) if w not in STOPWORDS and len(w) > 2]
            for n in (2, 3):
                for i in range(len(words) - n + 1):
                    phrase = " ".join(words[i:i + n])
                    counts[phrase] += 1
                    where.setdefault(phrase, p.url)
    db.execute(delete(KeywordResearch).where(KeywordResearch.website_id == website.id, KeywordResearch.source == "on_page"))
    rows = []
    for phrase, n in counts.most_common(40):
        rows.append(KeywordResearch(org_id=website.org_id, website_id=website.id, keyword=phrase, source="on_page",
                                    data_provider=None, related_url=where[phrase],
                                    notes=f"Appears in {n} title/heading(s) on your site. No search metrics."))
    db.add_all(rows)
    return rows


def measured_research(db: Session, website: Website, seeds: list[str], location: str, language: str) -> list[KeywordResearch]:
    if not dataforseo_configured():
        raise HTTPException(status_code=503, detail="No keyword data provider is configured (set DATAFORSEO_LOGIN and "
                                                    "DATAFORSEO_PASSWORD). Search volumes are never estimated by AI.")
    entitlements.require_feature(db, website.org_id, "keywords")
    entitlements.consume(db, website.org_id, "keyword_requests", 1, {"seeds": seeds[:10]})
    client = DataForSEO()

    async def go():
        metrics = await client.metrics(seeds, location, language)
        ideas = await client.ideas(seeds, location, language)
        return metrics, ideas

    try:
        metrics, ideas = asyncio.run(go())
    except KeywordProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    pages = latest_pages(db, website)
    now = datetime.now(UTC)
    rows = []
    seen = set()
    for m in metrics + ideas:
        if not m.keyword or m.keyword in seen:
            continue
        seen.add(m.keyword)
        url = _best_page(m.keyword, pages)
        rows.append(KeywordResearch(
            org_id=website.org_id, website_id=website.id, keyword=m.keyword[:300], source="measured",
            data_provider=PROVIDER_LABEL, search_volume=m.search_volume, difficulty=m.difficulty, cpc=m.cpc,
            competition=(str(m.competition)[:20] if m.competition is not None else None), location=location,
            language=language, intent=m.intent, related_url=url, fetched_at=now,
            notes=None if url else "No existing page clearly targets this query (content opportunity)."))
    db.add_all(rows)
    return rows


def ai_ideas(db: Session, website: Website) -> list[KeywordResearch]:
    pages = latest_pages(db, website, 60)
    if not pages:
        raise HTTPException(status_code=409, detail="Run an audit first; ideas are grounded in your crawled pages.")
    try:
        provider = get_provider()
    except AINotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    entitlements.consume(db, website.org_id, "ai_requests", 1, {"task": "keyword_ideas"})
    facts = {"site": website.root_url, "pages": [{"url": p.url, "title": p.title, "h1": p.h1} for p in pages[:60]]}
    task = TASKS["keyword_ideas"]
    try:
        res = provider.generate(task="keyword_ideas", system=SYSTEM_PROMPT,
                                user=build_user_message(task, facts, ""), schema=task.schema)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    entitlements.record(db, website.org_id, "ai_tokens", res.input_tokens + res.output_tokens, {"task": "keyword_ideas"})
    v = validate_output("keyword_ideas", res.data, "")
    if not v.ok:
        raise HTTPException(status_code=502, detail="AI output failed validation: " + "; ".join(v.errors))
    db.execute(delete(KeywordResearch).where(KeywordResearch.website_id == website.id, KeywordResearch.source == "ai_idea"))
    rows = []
    for idea in v.data.get("ideas", [])[:25]:
        kw = re.sub(r"\s+", " ", idea["keyword"]).strip().lower()[:300]
        rows.append(KeywordResearch(org_id=website.org_id, website_id=website.id, keyword=kw, source="ai_idea",
                                    data_provider=None, intent=idea.get("intent"), related_url=_best_page(kw, pages),
                                    notes=f"AI-generated idea ({res.model}); not measured. {idea.get('reason', '')}"[:1000]))
    db.add_all(rows)
    return rows
