from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import ai_status
from app.api.deps import OrgAccess, OrgContext, scoped_get
from app.core import audit
from app.core.db import get_db
from app.keywords import service
from app.keywords.providers import PROVIDER_LABEL, dataforseo_configured
from app.models import KeywordResearch, Role, Website

router = APIRouter(prefix="/orgs/{org_id}", tags=["keywords"])


def kw_out(k: KeywordResearch) -> dict:
    return {"id": str(k.id), "keyword": k.keyword, "source": k.source, "data_provider": k.data_provider,
            "search_volume": k.search_volume, "difficulty": k.difficulty, "cpc": k.cpc, "competition": k.competition,
            "location": k.location, "language": k.language, "intent": k.intent, "related_url": k.related_url,
            "notes": k.notes, "fetched_at": k.fetched_at.isoformat() if k.fetched_at else None}


@router.get("/websites/{website_id}/keywords")
def list_keywords(website_id: uuid.UUID, o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    w = scoped_get(db, Website, website_id, o.org_id)
    rows = db.scalars(select(KeywordResearch).where(KeywordResearch.org_id == o.org_id, KeywordResearch.website_id == w.id)
                      .order_by(KeywordResearch.source, KeywordResearch.search_volume.desc().nullslast())).all()
    return {
        "providers": {"measured": {"configured": dataforseo_configured(), "name": PROVIDER_LABEL},
                      "ai": ai_status()},
        "keywords": [kw_out(k) for k in rows],
    }


class ResearchIn(BaseModel):
    seeds: list[str] = Field(min_length=1, max_length=20)
    location: str = Field(default="Canada", max_length=80)
    language: str = Field(default="en", max_length=10)


@router.post("/websites/{website_id}/keywords/research")
def research(website_id: uuid.UUID, body: ResearchIn, request: Request, o: OrgContext = Depends(OrgAccess(Role.editor)),
             db: Session = Depends(get_db)):
    w = scoped_get(db, Website, website_id, o.org_id)
    rows = service.measured_research(db, w, [s[:100] for s in body.seeds], body.location, body.language)
    audit.record(db, "keywords.research", org_id=o.org_id, actor_id=o.user.id, request=request, data={"seeds": body.seeds})
    db.commit()
    return [kw_out(k) for k in rows]


@router.post("/websites/{website_id}/keywords/ideas")
def ideas(website_id: uuid.UUID, o: OrgContext = Depends(OrgAccess(Role.editor)), db: Session = Depends(get_db)):
    w = scoped_get(db, Website, website_id, o.org_id)
    rows = service.ai_ideas(db, w)
    db.commit()
    return [kw_out(k) for k in rows]


@router.post("/websites/{website_id}/keywords/on-page")
def on_page(website_id: uuid.UUID, o: OrgContext = Depends(OrgAccess(Role.editor)), db: Session = Depends(get_db)):
    w = scoped_get(db, Website, website_id, o.org_id)
    rows = service.on_page_terms(db, w)
    db.commit()
    return [kw_out(k) for k in rows]


@router.delete("/keywords/{keyword_id}")
def delete_keyword(keyword_id: uuid.UUID, o: OrgContext = Depends(OrgAccess(Role.editor)), db: Session = Depends(get_db)):
    k = scoped_get(db, KeywordResearch, keyword_id, o.org_id)
    db.delete(k)
    db.commit()
    return {"ok": True}
