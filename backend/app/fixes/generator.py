"""Create and edit fix proposals.

Rule-based fixes are deterministic (derived from crawl evidence). AI fixes go through the provider
abstraction and are rejected unless they pass ``app.ai.tasks.validate_output``.
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import AIError, AINotConfigured, get_provider
from app.ai.tasks import SYSTEM_PROMPT, TASKS, _has_markup, build_user_message, sanitize_html, validate_output
from app.billing import entitlements
from app.fixes.capabilities import direct_apply_for
from app.fixes.lifecycle import transition
from app.fixes.types import FIX_TYPES, FixTypeSpec, spec_for
from app.models import FixProposal, FixStatus, Issue, Page

log = logging.getLogger(__name__)


def _source_text(page: Page | None, extra: str = "") -> str:
    if page is None:
        return extra
    ex = page.extracted or {}
    parts = [page.url, page.final_url or "", page.title or "", page.meta_description or "", page.h1 or "",
             " ".join(h["text"] for h in ex.get("headings", [])), ex.get("main_text", ""),
             " ".join(i.get("src", "") for i in ex.get("images", [])), json.dumps(ex.get("og", {})), extra]
    return "\n".join(parts)


def _facts(page: Page | None, issue: Issue, db: Session) -> dict:
    ex = (page.extracted if page else {}) or {}
    paras = ex.get("paragraphs", [])
    facts = {
        "url": page.url if page else issue.url,
        "title": page.title if page else None,
        "h1": page.h1 if page else None,
        "meta_description": page.meta_description if page else None,
        "lang": ex.get("lang"),
        "headings": [h["text"] for h in ex.get("headings", [])][:30],
        "first_paragraph": paras[0]["text"] if paras else None,
        "schema_types": ex.get("schema_types", []),
        "issue": {"rule": issue.rule_id, "title": issue.title, "description": issue.description},
    }
    ev = issue.evidence or {}
    if issue.fix_type == "image_alt":
        facts["image"] = {"src": ev.get("src"), "surrounding_text": ev.get("context")}
    if issue.fix_type == "answer_paragraph":
        facts["question"] = ev.get("question")
    if issue.fix_type == "meta_title" and page is not None:
        others = db.scalars(select(Page.title).where(Page.crawl_run_id == page.crawl_run_id, Page.id != page.id,
                                                      Page.title.is_not(None)).limit(30)).all()
        facts["other_site_titles"] = [t for t in others if t]
    if issue.fix_type == "json_ld":
        facts["json_ld_issue_evidence"] = {k: ev.get(k) for k in ("error", "snippet", "type", "missing") if k in ev}
    return facts


def _before(spec: FixTypeSpec, issue: Issue, page: Page | None) -> dict:
    ev = issue.evidence or {}
    ex = (page.extracted if page else {}) or {}
    k = spec.key
    if k == "meta_title":
        return {"title": page.title if page else ev.get("title")}
    if k == "meta_description":
        return {"description": page.meta_description if page else None}
    if k == "h1":
        return {"h1": page.h1 if page else None, "title": page.title if page else None}
    if k == "image_alt":
        return {"src": ev.get("src"), "alt": None, "wp_attachment_id": ev.get("wp_attachment_id")}
    if k == "answer_paragraph":
        return {"question": ev.get("question"), "answer_preview": ev.get("answer_preview", "")}
    if k == "faq_section":
        return {"existing_questions": [q["question"] for q in ex.get("question_headings", [])]}
    if k == "json_ld":
        return {"existing_types": ex.get("schema_types", []), "invalid_snippet": ev.get("snippet")}
    if k == "canonical":
        return {"canonical": page.canonical if page else None, "canonical_tags": ex.get("canonical_tags", [])}
    if k in ("redirect", "broken_link"):
        return {"url": issue.url, "chain": ev.get("chain"), "status": ev.get("status")}
    if k == "robots_directive":
        return {"directives": ev.get("directives", [])}
    if k == "internal_link_update":
        return {"source_url": ev.get("source"), "old_href": ev.get("target"), "anchor_texts": ev.get("anchor_texts")}
    if k == "internal_link_add":
        return {"source_url": issue.url, "phrase": ev.get("phrase"), "target_url": ev.get("target")}
    if k == "content_recommendations":
        return {"word_count": page.word_count if page else None, "finding": issue.title}
    return {}


def _rule_after(spec: FixTypeSpec, issue: Issue, page: Page | None) -> tuple[dict, str, list[str]]:
    """Returns (after, rationale, warnings)."""
    ev = issue.evidence or {}
    rid = issue.rule_id
    warnings: list[str] = []
    if spec.key == "canonical":
        if rid == "tech.duplicate_content":
            target = (ev.get("pages") or [issue.url])[0]
            why = "Consolidate duplicates on the first URL of the group. Review which URL should be preferred."
            warnings.append("Choose the preferred URL deliberately; the first duplicate was pre-selected.")
        elif rid == "tech.canonical_to_non_200":
            target, why = ev.get("canonical_final") or issue.url, "Point the canonical to the final 200 URL."
        elif rid == "tech.canonical_relative":
            target, why = ev.get("resolved") or issue.url, "Use the absolute form of the same URL."
        elif rid == "tech.canonical_multiple":
            target = page.final_url if page else issue.url
            why = "Keep a single self-referencing canonical; remove the others."
        else:
            target, why = (page.final_url if page else issue.url), "Add a self-referencing canonical."
        return {"canonical_url": target, "html": f'<link rel="canonical" href="{html_lib.escape(target or "")}">'}, why, warnings
    if spec.key in ("redirect", "broken_link"):
        if rid == "tech.redirect_chain":
            return ({"from_url": issue.url, "to_url": ev.get("final_url"), "status": 301},
                    "Redirect the original URL straight to its final destination.", warnings)
        warnings.append("Choose the destination URL: the most relevant live page (or restore the page).")
        return ({"from_url": issue.url, "to_url": "", "status": 301},
                "Redirect the broken/looping URL to the most relevant live page, or restore the content.", warnings)
    if spec.key == "robots_directive":
        if rid == "tech.noindex_in_sitemap":
            warnings.append("Alternatively, remove this URL from the sitemap if it should stay out of search.")
        return {"directive": "index, follow"}, "Remove the noindex directive if this page should appear in search.", warnings
    if spec.key == "internal_link_update":
        if rid == "tech.link_to_redirect":
            return {"new_href": ev.get("final_url")}, "Link directly to the final URL.", warnings
        warnings.append("Pick a replacement URL for the broken link before approving.")
        return {"new_href": ""}, "Replace the broken link with a working URL.", warnings
    if spec.key == "internal_link_add":
        return ({"phrase": ev.get("phrase", ""), "target_url": ev.get("target", "")},
                "Link the first plain-text mention of the phrase to the related page.", warnings)
    return {}, "", warnings


def _ai_after(db: Session, spec: FixTypeSpec, issue: Issue, page: Page | None) -> tuple[dict, str, dict, str]:
    """Returns (after, rationale, validation, model). Raises HTTPException for config/limit problems."""
    task = TASKS[spec.key]
    try:
        provider = get_provider()
    except AINotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    entitlements.consume(db, issue.org_id, "ai_requests", 1, {"issue_id": str(issue.id), "task": spec.key})
    facts = _facts(page, issue, db)
    page_text = ((page.extracted or {}).get("main_text") if page else "") or ""
    user = build_user_message(task, facts, page_text)
    try:
        res = provider.generate(task=spec.key, system=SYSTEM_PROMPT, user=user, schema=task.schema)
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    entitlements.record(db, issue.org_id, "ai_tokens", res.input_tokens + res.output_tokens, {"task": spec.key})
    v = validate_output(spec.key, res.data, _source_text(page))
    after = dict(v.data)
    rationale = str(after.pop("rationale", "") or "")
    after.pop("insufficient_information", None)
    return after, rationale, {"errors": v.errors, "warnings": v.warnings, "raw_rejected": None if v.ok else res.data}, res.model


def create_fix(db: Session, issue: Issue, user_id: uuid.UUID | None) -> FixProposal:
    spec = spec_for(issue.fix_type)
    if spec is None or issue.org_id is None or issue.website_id is None:
        raise HTTPException(status_code=422, detail="No automated fix is available for this finding.")
    page = db.get(Page, issue.page_id) if issue.page_id else None
    if page is not None and page.org_id != issue.org_id:
        page = None
    fix = FixProposal(
        org_id=issue.org_id, issue_id=issue.id, website_id=issue.website_id, url=issue.url or "",
        fix_type=spec.key, status=FixStatus.detected, generator="pending", risk_level=spec.risk,
        confidence="high" if spec.generator == "rule" else ("low" if spec.key == "image_alt" else "medium"),
        requires_approval=spec.requires_approval, verification_steps=list(spec.verification), created_by=user_id,
    )
    db.add(fix)
    db.flush()
    from app.models import ChangeLog

    db.add(ChangeLog(org_id=fix.org_id, fix_id=fix.id, website_id=fix.website_id, from_status=None,
                     to_status=FixStatus.detected.value, actor_user_id=user_id, message=f"Created from finding {issue.rule_id}"))
    fix.before = _before(spec, issue, page)
    transition(db, fix, FixStatus.analyzed, actor_id=user_id, message="Context collected from crawl evidence.")

    if spec.generator == "ai":
        after, rationale, validation, model = _ai_after(db, spec, issue, page)
        fix.generator = f"ai:{model}"
    else:
        after, rationale, warnings = _rule_after(spec, issue, page)
        validation = {"errors": [], "warnings": warnings}
        fix.generator = "rule"
    fix.rationale = rationale
    fix.validation = validation
    _set_apply_support(db, fix)
    if validation["errors"]:
        fix.after = {}
        fix.error = "The generated suggestion failed validation and was discarded: " + "; ".join(validation["errors"])
        transition(db, fix, FixStatus.analyzed, actor_id=user_id, message="Draft rejected by validation.",
                   data={"errors": validation["errors"]})
    else:
        fix.after = after
        fix.error = None
        transition(db, fix, FixStatus.drafted, actor_id=user_id, message=f"Draft generated ({fix.generator}).")
    return fix


def _set_apply_support(db: Session, fix: FixProposal) -> None:
    support = direct_apply_for(db, fix.org_id, fix.website_id, fix.fix_type)
    fix.direct_apply_supported = bool(support["supported"])
    fix.apply_unsupported_reason = None if support["supported"] else support.get("reason")
    fix.integration_id = uuid.UUID(support["integration_id"]) if support.get("integration_id") else None


def refresh_apply_support(db: Session, fix: FixProposal) -> None:
    _set_apply_support(db, fix)


def validate_manual_after(fix: FixProposal, after: dict) -> tuple[dict, list[str], list[str]]:
    spec = FIX_TYPES[fix.fix_type]
    errors: list[str] = []
    warnings: list[str] = []
    extra = set(after) - set(spec.editable_fields) - {"html"}
    if extra:
        errors.append(f"These fields cannot be edited for this fix type: {sorted(extra)}")
        return {}, errors, warnings
    clean = dict(fix.after or {})
    task = TASKS.get(spec.key)
    for k, v in after.items():
        if k == "items":
            if not isinstance(v, list) or not all(isinstance(i, dict) and set(i) <= {"question", "answer"} for i in v):
                errors.append("FAQ items must be a list of {question, answer}.")
                continue
            for i in v:
                if _has_markup(i.get("question", "")) or _has_markup(i.get("answer", "")):
                    errors.append("FAQ items must be plain text.")
            clean[k] = [{"question": str(i.get("question", ""))[:200], "answer": str(i.get("answer", ""))[:700]} for i in v]
            continue
        if not isinstance(v, (str, int)):
            errors.append(f"'{k}' has an invalid type.")
            continue
        v = str(v)
        if task and k in task.html_fields:
            if re.search(r"<script|javascript:|on\w+\s*=", v, re.I):
                errors.append(f"'{k}' must not contain scripts.")
            v = sanitize_html(v)
        elif k == "json_ld":
            try:
                json.loads(v)
            except json.JSONDecodeError:
                errors.append("json_ld must be valid JSON.")
            if re.search(r"</?script", v, re.I):
                errors.append("json_ld must not contain script tags.")
        else:
            if _has_markup(v):
                errors.append(f"'{k}' must not contain HTML.")
            v = re.sub(r"\s+", " ", v).strip()
            if task and k in task.plain_fields and len(v) > task.plain_fields[k][1] + 40:
                errors.append(f"'{k}' is too long.")
            if k in ("new_href", "to_url", "canonical_url", "target_url") and v and not re.match(r"^https?://", v):
                errors.append(f"'{k}' must be an absolute http(s) URL.")
        clean[k] = v
    return clean, errors, warnings
