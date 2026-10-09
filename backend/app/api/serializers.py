from __future__ import annotations

from typing import Any

from app.models import ChangeLog, CrawlRun, FixProposal, Integration, Issue, Page, Website


def _iso(d):
    return d.isoformat() if d else None


def website_out(w: Website) -> dict[str, Any]:
    return {
        "id": str(w.id), "name": w.name, "root_url": w.root_url, "hostname": w.hostname,
        "schedule": w.schedule, "next_scheduled_at": _iso(w.next_scheduled_at),
        "crawl_settings": w.crawl_settings or {}, "created_at": _iso(w.created_at),
    }


def crawl_out(r: CrawlRun) -> dict[str, Any]:
    return {
        "id": str(r.id), "website_id": str(r.website_id) if r.website_id else None, "start_url": r.start_url,
        "status": r.status.value, "trigger": r.trigger, "settings": r.settings,
        "pages_discovered": r.pages_discovered, "pages_crawled": r.pages_crawled, "pages_failed": r.pages_failed,
        "pages_rendered": r.pages_rendered, "summary": r.summary or {}, "error": r.error,
        "created_at": _iso(r.created_at), "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at),
    }


def issue_out(i: Issue, full: bool = False) -> dict[str, Any]:
    d = {
        "id": str(i.id), "crawl_run_id": str(i.crawl_run_id), "url": i.url, "rule_id": i.rule_id,
        "category": i.category, "severity": i.severity.value, "finding_type": i.finding_type.value,
        "confidence": i.confidence, "title": i.title, "status": i.status.value, "fix_type": i.fix_type,
        "source": i.source, "page_id": str(i.page_id) if i.page_id else None,
    }
    if full:
        d.update({"description": i.description, "why_it_matters": i.why_it_matters,
                  "recommendation": i.recommendation, "evidence": i.evidence, "fingerprint": i.fingerprint,
                  "created_at": _iso(i.created_at)})
    else:
        d["description"] = i.description[:300]
    return d


def page_out(p: Page, full: bool = False) -> dict[str, Any]:
    d = {
        "id": str(p.id), "url": p.url, "final_url": p.final_url, "status_code": p.status_code, "depth": p.depth,
        "title": p.title, "meta_description": p.meta_description, "canonical": p.canonical, "h1": p.h1,
        "word_count": p.word_count, "indexable": p.indexable, "in_sitemap": p.in_sitemap,
        "inbound_links": p.inbound_links, "rendered": p.rendered, "response_time_ms": p.response_time_ms,
        "error": p.error, "redirect_chain": p.redirect_chain,
    }
    if full:
        ex = dict(p.extracted or {})
        ex.pop("main_text", None)
        d["extracted"] = ex
        d["content_type"] = p.content_type
    return d


def fix_out(f: FixProposal, full: bool = False) -> dict[str, Any]:
    d = {
        "id": str(f.id), "issue_id": str(f.issue_id) if f.issue_id else None, "website_id": str(f.website_id),
        "url": f.url, "fix_type": f.fix_type, "status": f.status.value, "generator": f.generator,
        "risk_level": f.risk_level, "confidence": f.confidence, "requires_approval": f.requires_approval,
        "direct_apply_supported": f.direct_apply_supported, "apply_unsupported_reason": f.apply_unsupported_reason,
        "integration_id": str(f.integration_id) if f.integration_id else None,
        "created_at": _iso(f.created_at), "updated_at": _iso(f.updated_at), "verified_at": _iso(f.verified_at),
        "error": f.error,
    }
    if full:
        d.update({
            "before": f.before, "after": f.after, "rationale": f.rationale, "verification_steps": f.verification_steps,
            "validation": f.validation, "provider_resource": f.provider_resource, "original_state": f.original_state,
            "provider_response": f.provider_response, "rollback_ref": {k: v for k, v in (f.rollback_ref or {}).items()},
            "verification_result": f.verification_result, "verification_attempts": f.verification_attempts,
            "approved_by": str(f.approved_by) if f.approved_by else None, "approved_at": _iso(f.approved_at),
            "applied_at": _iso(f.applied_at), "rolled_back_at": _iso(f.rolled_back_at),
            "created_by": str(f.created_by) if f.created_by else None,
        })
    return d


def changelog_out(c: ChangeLog) -> dict[str, Any]:
    return {"id": str(c.id), "fix_id": str(c.fix_id), "website_id": str(c.website_id), "from_status": c.from_status,
            "to_status": c.to_status, "actor_user_id": str(c.actor_user_id) if c.actor_user_id else None,
            "message": c.message, "data": c.data, "created_at": _iso(c.created_at)}


def integration_out(i: Integration) -> dict[str, Any]:
    # Never include encrypted_credentials or auth state.
    return {"id": str(i.id), "website_id": str(i.website_id), "provider": i.provider, "status": i.status.value,
            "display_name": i.display_name, "external_site_url": i.external_site_url,
            "external_account": i.external_account, "capabilities": i.capabilities or {},
            "last_verified_at": _iso(i.last_verified_at), "error_message": i.error_message,
            "created_at": _iso(i.created_at)}
