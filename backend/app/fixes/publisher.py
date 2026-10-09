"""Apply → verify → (rollback) jobs. Run via Celery or inline threads.

Status rules:
* ``applying``  while the provider call is in flight.
* ``verifying`` once the provider accepted the change — *not* verified.
* ``verified``  only after an independent live fetch shows the expected state.
* ``failed``    on provider errors, or when the change is still not visible after
                ``MAX_VERIFY_ATTEMPTS`` checks (the provider response is kept for diagnosis).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.billing import entitlements
from app.core.crypto import decrypt_json
from app.core.db import db_session
from app.fixes.lifecycle import transition
from app.fixes.types import FIX_TYPES
from app.fixes.verify import verify_live
from app.integrations.base import ConnectorError, ResourceRef
from app.integrations.registry import get_connector
from app.models import FixProposal, FixStatus, Integration, IntegrationStatus, Page

log = logging.getLogger(__name__)

MAX_VERIFY_ATTEMPTS = 5


def faq_html(items: list[dict]) -> str:
    import html

    parts = ["<h2>Frequently asked questions</h2>"]
    for it in items:
        parts.append(f"<h3>{html.escape(it['question'])}</h3>")
        parts.append(f"<p>{html.escape(it['answer'])}</p>")
    return "\n".join(parts)


def operation_params(fix: FixProposal) -> dict:
    a, b = fix.after or {}, fix.before or {}
    t = fix.fix_type
    if t == "meta_title":
        return {"value": a["title"]}
    if t == "h1":
        return {"value": a["h1"]}
    if t == "image_alt":
        return {"src": b["src"], "alt": a.get("alt", ""), "attachment_id": b.get("wp_attachment_id")}
    if t == "answer_paragraph":
        return {"heading_text": b["question"], "html": a["answer_html"]}
    if t == "faq_section":
        return {"html": faq_html(a.get("items", []))}
    if t == "internal_link_update":
        return {"old_href": b["old_href"], "new_href": a["new_href"]}
    if t == "internal_link_add":
        return {"phrase": a["phrase"], "href": a["target_url"]}
    raise ConnectorError("This fix type cannot be published automatically.")


def preflight(db, fix: FixProposal) -> tuple[dict | None, str]:
    """Resolve the fix URL to a provider resource without modifying anything."""
    integ = db.get(Integration, fix.integration_id) if fix.integration_id else None
    if integ is None or integ.org_id != fix.org_id or integ.status != IntegrationStatus.connected:
        return None, "The publishing integration is not connected."
    creds = decrypt_json(integ.encrypted_credentials)
    page = db.scalar(select(Page).where(Page.org_id == fix.org_id, Page.url == fix.url).order_by(Page.fetched_at.desc()))
    try:
        ref = asyncio.run(get_connector(integ.provider).locate(creds, fix.url, page.extracted if page else {}))
    except ConnectorError as exc:
        return None, exc.user_message
    if ref is None:
        return None, ("This URL could not be matched to a post or page in the connected site (it may be the "
                      "homepage template, an archive, or a custom post type). Apply this fix manually instead.")
    return ref.to_dict(), ""


def _load(db, fix_id: uuid.UUID) -> tuple[FixProposal | None, Integration | None]:
    fix = db.get(FixProposal, fix_id)
    if fix is None:
        return None, None
    integ = db.get(Integration, fix.integration_id) if fix.integration_id else None
    if integ is not None and integ.org_id != fix.org_id:  # defence in depth
        integ = None
    return fix, integ


def apply_fix_job(fix_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    with db_session() as db:
        fix, integ = _load(db, fix_id)
        if fix is None or fix.status != FixStatus.applying:
            return
        if integ is None or integ.status != IntegrationStatus.connected or not integ.encrypted_credentials:
            fix.error = "The publishing integration is not connected."
            transition(db, fix, FixStatus.failed, actor_id=actor_id, message=fix.error)
            return
        creds = decrypt_json(integ.encrypted_credentials)
        operation = FIX_TYPES[fix.fix_type].operation
        page = db.scalar(select(Page).where(Page.org_id == fix.org_id, Page.url == fix.url).order_by(Page.fetched_at.desc()))
        extracted = page.extracted if page else {}
        provider = integ.provider
        url = fix.url
        params = operation_params(fix) if operation else {}
        known = dict(fix.provider_resource or {})
    connector = get_connector(provider)

    async def run():
        ref = ResourceRef(**known) if known.get("api_url") else await connector.locate(creds, url, extracted)
        if ref is None:
            raise ConnectorError("This URL could not be matched to a post or page in the connected site "
                                 "(it may be an archive, theme template or custom post type).")
        res = await connector.apply(creds, ref, operation, params)
        return ref, res

    try:
        ref, res = asyncio.run(run())
    except ConnectorError as exc:
        with db_session() as db:
            fix = db.get(FixProposal, fix_id)
            fix.error = exc.user_message
            fix.provider_response = {"error": exc.user_message, "detail": str(exc.detail)[:2000] if exc.detail else None}
            transition(db, fix, FixStatus.failed, actor_id=actor_id, message=f"Publishing failed: {exc.user_message}")
        return
    except Exception as exc:  # unexpected
        log.exception("apply failed")
        with db_session() as db:
            fix = db.get(FixProposal, fix_id)
            fix.error = f"Unexpected error while publishing ({type(exc).__name__})."
            transition(db, fix, FixStatus.failed, actor_id=actor_id, message=fix.error)
        return
    with db_session() as db:
        fix = db.get(FixProposal, fix_id)
        fix.provider_resource = ref.to_dict()
        fix.original_state = res.original_state
        fix.provider_response = res.provider_response
        fix.rollback_ref = res.rollback_ref
        fix.applied_at = datetime.now(UTC)
        fix.error = None
        transition(db, fix, FixStatus.verifying, actor_id=actor_id,
                   message="Provider accepted the change. Verifying on the live site.",
                   data={"provider_response": res.provider_response})
    verify_fix_job(fix_id)


def verify_fix_job(fix_id: uuid.UUID) -> None:
    with db_session() as db:
        fix = db.get(FixProposal, fix_id)
        if fix is None or fix.status not in (FixStatus.verifying, FixStatus.externally_applied_unverified):
            return
        args = (fix.fix_type, fix.url, dict(fix.before or {}), dict(fix.after or {}))
    try:
        result = asyncio.run(verify_live(*args))
    except Exception as exc:
        log.exception("verify failed")
        result = {"passed": False, "error": f"Verification error: {type(exc).__name__}", "checks": []}
    with db_session() as db:
        fix = db.get(FixProposal, fix_id)
        fix.verification_attempts += 1
        fix.verification_result = result
        if fix.status == FixStatus.externally_applied_unverified:
            transition(db, fix, FixStatus.verifying, actor_id=None, message="Verifying manually applied change.")
        if result.get("passed"):
            transition(db, fix, FixStatus.verified, actor_id=None, by_verifier=True,
                       message="Live page shows the expected change.", data={"checks": result.get("checks")})
            fix.error = None
        elif fix.verification_attempts >= MAX_VERIFY_ATTEMPTS:
            fix.error = ("The change is not visible on the live page after "
                         f"{fix.verification_attempts} checks. If a cache/CDN is in front of the site, purge it and "
                         "re-verify. The provider response is kept for reference.")
            transition(db, fix, FixStatus.failed, actor_id=None, message=fix.error, data={"checks": result.get("checks")})
        else:
            transition(db, fix, FixStatus.verifying, actor_id=None,
                       message=f"Not visible yet (check {fix.verification_attempts}/{MAX_VERIFY_ATTEMPTS}); will retry.",
                       data={"checks": result.get("checks")})


def verify_pending() -> int:
    with db_session() as db:
        ids = [f.id for f in db.scalars(select(FixProposal).where(FixProposal.status == FixStatus.verifying).limit(200))]
    for fid in ids:
        verify_fix_job(fid)
    return len(ids)


def rollback_fix_job(fix_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    with db_session() as db:
        fix, integ = _load(db, fix_id)
        if fix is None or not fix.rollback_ref:
            return
        if integ is None or integ.status != IntegrationStatus.connected or not integ.encrypted_credentials:
            fix.error = "Rollback failed: the publishing integration is not connected."
            return
        creds = decrypt_json(integ.encrypted_credentials)
        connector = get_connector(integ.provider)
        rb = dict(fix.rollback_ref)
        args = (fix.fix_type, fix.url, dict(fix.before or {}), dict(fix.after or {}))
        try:
            entitlements.consume(db, fix.org_id, "publish_ops", 1, {"fix_id": str(fix.id), "op": "rollback"})
        except Exception as exc:
            fix.error = f"Rollback blocked: {getattr(exc, 'detail', exc)}"
            return
    try:
        resp = asyncio.run(connector.rollback(creds, rb))
    except ConnectorError as exc:
        with db_session() as db:
            fix = db.get(FixProposal, fix_id)
            fix.error = f"Rollback not performed: {exc.user_message}"
            from app.models import ChangeLog

            db.add(ChangeLog(org_id=fix.org_id, fix_id=fix.id, website_id=fix.website_id, from_status=fix.status.value,
                             to_status=fix.status.value, actor_user_id=actor_id, message=fix.error,
                             data={"conflict": exc.conflict}))
        return
    check = asyncio.run(verify_live(*args, expect_reverted=True))
    with db_session() as db:
        fix = db.get(FixProposal, fix_id)
        fix.error = None if check.get("passed") else "Rollback was accepted by the provider but the live page still shows the change (cache?)."
        transition(db, fix, FixStatus.rolled_back, actor_id=actor_id, message="Original content restored.",
                   data={"provider_response": resp, "live_check": check})
