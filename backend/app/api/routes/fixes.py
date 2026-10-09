from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import OrgAccess, OrgContext, scoped_get
from app.api.serializers import changelog_out, fix_out, issue_out
from app.billing import entitlements
from app.core import audit
from app.core.db import get_db
from app.fixes.generator import create_fix, refresh_apply_support, validate_manual_after
from app.fixes.lifecycle import transition
from app.fixes.types import FIX_TYPES
from app.models import ChangeLog, FixProposal, FixStatus, Issue, Role
from app.tasks.dispatch import enqueue

router = APIRouter(prefix="/orgs/{org_id}", tags=["fixes"])

REQUIRED_NONEMPTY = {
    "meta_title": ["title"], "meta_description": ["description"], "h1": ["h1"], "answer_paragraph": ["answer_html"],
    "faq_section": ["items"], "json_ld": ["json_ld"], "canonical": ["canonical_url"],
    "redirect": ["from_url", "to_url"], "broken_link": ["from_url", "to_url"], "internal_link_update": ["new_href"],
    "internal_link_add": ["phrase", "target_url"], "robots_directive": ["directive"],
}


def _detail(db: Session, fix: FixProposal) -> dict:
    logs = db.scalars(select(ChangeLog).where(ChangeLog.fix_id == fix.id, ChangeLog.org_id == fix.org_id)
                      .order_by(ChangeLog.created_at)).all()
    issue = db.get(Issue, fix.issue_id) if fix.issue_id else None
    spec = FIX_TYPES.get(fix.fix_type)
    return {**fix_out(fix, full=True), "history": [changelog_out(c) for c in logs],
            "issue": issue_out(issue, full=True) if issue and issue.org_id == fix.org_id else None,
            "spec": {"label": spec.label, "editable_fields": list(spec.editable_fields), "operation": spec.operation,
                     "generator": spec.generator} if spec else None}


@router.post("/issues/{issue_id}/fixes")
def generate_fix(issue_id: uuid.UUID, request: Request, o: OrgContext = Depends(OrgAccess(Role.editor)),
                 db: Session = Depends(get_db)):
    issue = scoped_get(db, Issue, issue_id, o.org_id)
    fix = create_fix(db, issue, o.user.id)
    audit.record(db, "fix.generated", org_id=o.org_id, actor_id=o.user.id, target_type="fix", target_id=fix.id,
                 request=request, data={"fix_type": fix.fix_type, "generator": fix.generator, "status": fix.status.value})
    db.commit()
    return _detail(db, fix)


@router.get("/fixes")
def list_fixes(o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db),
               status: str | None = None, website_id: uuid.UUID | None = None, fix_type: str | None = None,
               limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0)):
    stmt = select(FixProposal).where(FixProposal.org_id == o.org_id)
    if status:
        try:
            stmt = stmt.where(FixProposal.status.in_([FixStatus(s) for s in status.split(",")]))
        except ValueError:
            raise HTTPException(status_code=422, detail="Unknown status.") from None
    if website_id:
        stmt = stmt.where(FixProposal.website_id == website_id)
    if fix_type:
        stmt = stmt.where(FixProposal.fix_type == fix_type)
    rows = db.scalars(stmt.order_by(FixProposal.updated_at.desc()).limit(limit).offset(offset)).all()
    return [fix_out(f) | {"after": f.after, "before": f.before} for f in rows]


@router.get("/fixes/{fix_id}")
def get_fix(fix_id: uuid.UUID, o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    fix = scoped_get(db, FixProposal, fix_id, o.org_id)
    if fix.status not in (FixStatus.applying, FixStatus.verifying, FixStatus.verified, FixStatus.rolled_back):
        refresh_apply_support(db, fix)
        db.commit()
    return _detail(db, fix)


class FixEditIn(BaseModel):
    after: dict = Field(default_factory=dict)


@router.patch("/fixes/{fix_id}")
def edit_fix(fix_id: uuid.UUID, body: FixEditIn, request: Request, o: OrgContext = Depends(OrgAccess(Role.editor)),
             db: Session = Depends(get_db)):
    fix = scoped_get(db, FixProposal, fix_id, o.org_id)
    if fix.status in (FixStatus.applying, FixStatus.verifying, FixStatus.verified):
        raise HTTPException(status_code=409, detail="This fix has been published; roll it back or create a new fix to edit.")
    clean, errors, warnings = validate_manual_after(fix, body.after)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    fix.after = clean
    fix.validation = {"errors": [], "warnings": warnings, "edited_by_user": True}
    fix.error = None
    transition(db, fix, FixStatus.drafted, actor_id=o.user.id, message="Draft edited.", data={"after": clean})
    audit.record(db, "fix.edited", org_id=o.org_id, actor_id=o.user.id, target_type="fix", target_id=fix.id, request=request)
    db.commit()
    return _detail(db, fix)


def _require_complete(fix: FixProposal) -> None:
    missing = [k for k in REQUIRED_NONEMPTY.get(fix.fix_type, []) if not (fix.after or {}).get(k)]
    if missing or (fix.validation or {}).get("errors"):
        raise HTTPException(status_code=422, detail=f"The draft is incomplete or invalid (missing: {missing}). Edit it first.")


@router.post("/fixes/{fix_id}/submit")
def submit_fix(fix_id: uuid.UUID, request: Request, o: OrgContext = Depends(OrgAccess(Role.editor)),
               db: Session = Depends(get_db)):
    fix = scoped_get(db, FixProposal, fix_id, o.org_id)
    _require_complete(fix)
    transition(db, fix, FixStatus.awaiting_approval, actor_id=o.user.id, message="Submitted for approval.")
    audit.record(db, "fix.submitted", org_id=o.org_id, actor_id=o.user.id, target_type="fix", target_id=fix.id, request=request)
    db.commit()
    return _detail(db, fix)


@router.post("/fixes/{fix_id}/approve")
def approve_fix(fix_id: uuid.UUID, request: Request, o: OrgContext = Depends(OrgAccess(Role.admin)),
                db: Session = Depends(get_db)):
    fix = scoped_get(db, FixProposal, fix_id, o.org_id)
    _require_complete(fix)
    transition(db, fix, FixStatus.approved, actor_id=o.user.id, message="Approved.",
               data={"after": fix.after, "risk_level": fix.risk_level})
    audit.record(db, "fix.approved", org_id=o.org_id, actor_id=o.user.id, target_type="fix", target_id=fix.id,
                 request=request, data={"fix_type": fix.fix_type})
    db.commit()
    return _detail(db, fix)


class RejectIn(BaseModel):
    reason: str = Field(default="", max_length=1000)


@router.post("/fixes/{fix_id}/reject")
def reject_fix(fix_id: uuid.UUID, body: RejectIn, request: Request, o: OrgContext = Depends(OrgAccess(Role.admin)),
               db: Session = Depends(get_db)):
    fix = scoped_get(db, FixProposal, fix_id, o.org_id)
    transition(db, fix, FixStatus.rejected, actor_id=o.user.id, message=f"Rejected. {body.reason}".strip())
    audit.record(db, "fix.rejected", org_id=o.org_id, actor_id=o.user.id, target_type="fix", target_id=fix.id, request=request)
    db.commit()
    return _detail(db, fix)


@router.post("/fixes/{fix_id}/apply")
def apply_fix(fix_id: uuid.UUID, request: Request, o: OrgContext = Depends(OrgAccess(Role.admin)),
              db: Session = Depends(get_db)):
    fix = scoped_get(db, FixProposal, fix_id, o.org_id)
    if fix.requires_approval and fix.status != FixStatus.approved:
        raise HTTPException(status_code=409, detail="This fix must be approved before it can be published.")
    refresh_apply_support(db, fix)
    if not fix.direct_apply_supported:
        db.commit()
        raise HTTPException(status_code=422, detail=fix.apply_unsupported_reason or "Direct publishing is not supported.")
    entitlements.require_feature(db, o.org_id, "publishing")
    entitlements.consume(db, o.org_id, "publish_ops", 1, {"fix_id": str(fix.id)})
    transition(db, fix, FixStatus.applying, actor_id=o.user.id, message="Publishing via integration.")
    audit.record(db, "fix.apply_started", org_id=o.org_id, actor_id=o.user.id, target_type="fix", target_id=fix.id,
                 request=request, data={"integration_id": str(fix.integration_id)})
    db.commit()
    enqueue("apply_fix", str(fix.id), str(o.user.id))
    return _detail(db, fix)


@router.post("/fixes/{fix_id}/mark-applied")
def mark_applied(fix_id: uuid.UUID, request: Request, o: OrgContext = Depends(OrgAccess(Role.editor)),
                 db: Session = Depends(get_db)):
    """The user applied the change themselves (e.g. via their CMS). We verify it on the live site."""
    fix = scoped_get(db, FixProposal, fix_id, o.org_id)
    _require_complete(fix)
    if fix.fix_type == "content_recommendations":
        raise HTTPException(status_code=422, detail="Advisory recommendations cannot be verified automatically.")
    fix.verification_attempts = 0
    transition(db, fix, FixStatus.externally_applied_unverified, actor_id=o.user.id,
               message="Marked as applied outside the platform; awaiting verification.")
    audit.record(db, "fix.marked_applied", org_id=o.org_id, actor_id=o.user.id, target_type="fix", target_id=fix.id, request=request)
    db.commit()
    enqueue("verify_fix", str(fix.id))
    return _detail(db, fix)


@router.post("/fixes/{fix_id}/verify")
def reverify(fix_id: uuid.UUID, o: OrgContext = Depends(OrgAccess(Role.editor)), db: Session = Depends(get_db)):
    fix = scoped_get(db, FixProposal, fix_id, o.org_id)
    if fix.status == FixStatus.failed and (fix.applied_at or fix.verification_attempts):
        fix.verification_attempts = 0
        transition(db, fix, FixStatus.verifying, actor_id=o.user.id, message="Re-verification requested.")
    elif fix.status == FixStatus.verified:
        transition(db, fix, FixStatus.verifying, actor_id=o.user.id, message="Re-verification requested.")
    elif fix.status not in (FixStatus.verifying, FixStatus.externally_applied_unverified):
        raise HTTPException(status_code=409, detail="Only applied fixes can be verified.")
    db.commit()
    enqueue("verify_fix", str(fix.id))
    return _detail(db, fix)


@router.post("/fixes/{fix_id}/rollback")
def rollback(fix_id: uuid.UUID, request: Request, o: OrgContext = Depends(OrgAccess(Role.admin)),
             db: Session = Depends(get_db)):
    fix = scoped_get(db, FixProposal, fix_id, o.org_id)
    if not fix.rollback_ref:
        raise HTTPException(status_code=409, detail="No rollback information is available for this fix "
                                                    "(it was not published through an integration).")
    if fix.status not in (FixStatus.verified, FixStatus.failed, FixStatus.verifying):
        raise HTTPException(status_code=409, detail="Only published fixes can be rolled back.")
    audit.record(db, "fix.rollback_requested", org_id=o.org_id, actor_id=o.user.id, target_type="fix", target_id=fix.id,
                 request=request)
    db.commit()
    enqueue("rollback_fix", str(fix.id), str(o.user.id))
    return _detail(db, fix)


@router.get("/changes")
def change_history(o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db),
                   website_id: uuid.UUID | None = None, limit: int = Query(default=200, ge=1, le=1000)):
    stmt = select(ChangeLog, FixProposal).join(FixProposal, FixProposal.id == ChangeLog.fix_id).where(
        ChangeLog.org_id == o.org_id)
    if website_id:
        stmt = stmt.where(ChangeLog.website_id == website_id)
    rows = db.execute(stmt.order_by(ChangeLog.created_at.desc()).limit(limit)).all()
    return [changelog_out(c) | {"fix_type": f.fix_type, "url": f.url} for c, f in rows]
