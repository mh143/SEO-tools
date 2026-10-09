"""Fix lifecycle state machine.

Detected → Analyzed → Drafted → Awaiting approval → Approved → Applying → Verifying → Verified
plus Rejected, Failed, Externally applied (unverified) and Rolled back.

Every transition writes a ChangeLog row with actor, timestamp and data. ``verified`` can only be
reached from ``verifying`` / ``externally_applied_unverified`` and only by the verifier.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import ChangeLog, FixProposal, FixStatus

S = FixStatus
TRANSITIONS: dict[FixStatus, set[FixStatus]] = {
    S.detected: {S.analyzed, S.failed},
    S.analyzed: {S.drafted, S.failed, S.analyzed},
    S.drafted: {S.drafted, S.awaiting_approval, S.rejected, S.externally_applied_unverified, S.analyzed},
    S.awaiting_approval: {S.approved, S.rejected, S.drafted, S.externally_applied_unverified},
    S.approved: {S.applying, S.drafted, S.externally_applied_unverified, S.rejected},
    S.applying: {S.verifying, S.failed},
    S.verifying: {S.verified, S.failed, S.verifying},
    S.verified: {S.rolled_back, S.verifying, S.failed},
    S.failed: {S.drafted, S.approved, S.verifying, S.rolled_back, S.externally_applied_unverified},
    S.rejected: {S.drafted},
    S.externally_applied_unverified: {S.verifying, S.verified, S.failed, S.drafted},
    S.rolled_back: {S.drafted},
}

VERIFIER_ONLY = {S.verified}


class TransitionError(HTTPException):
    def __init__(self, frm: FixStatus, to: FixStatus):
        super().__init__(status_code=409, detail=f"Cannot move a fix from '{frm.value}' to '{to.value}'.")


def transition(db: Session, fix: FixProposal, to: FixStatus, *, actor_id: uuid.UUID | None, message: str = "",
               data: dict | None = None, by_verifier: bool = False) -> None:
    frm = fix.status
    if to not in TRANSITIONS.get(frm, set()):
        raise TransitionError(frm, to)
    if to in VERIFIER_ONLY and not by_verifier:
        raise HTTPException(status_code=409, detail="Only independent verification can mark a fix as verified.")
    fix.status = to
    now = datetime.now(UTC)
    if to == S.approved:
        fix.approved_by, fix.approved_at = actor_id, now
    elif to == S.verified:
        fix.verified_at = now
    elif to == S.rolled_back:
        fix.rolled_back_at = now
    elif to == S.drafted and frm in (S.approved, S.awaiting_approval):
        fix.approved_by = fix.approved_at = None
    db.add(ChangeLog(org_id=fix.org_id, fix_id=fix.id, website_id=fix.website_id, from_status=frm.value,
                     to_status=to.value, actor_user_id=actor_id, message=message, data=data or {}))
