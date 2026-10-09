from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, OrgAccess, OrgContext, require_auth
from app.api.routes.auth import create_org_for
from app.billing.entitlements import check_seat_limit, effective_plan, usage_summary
from app.core import audit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import hash_token, new_token
from app.models import (
    AuditLog,
    CrawlRun,
    FixProposal,
    FixStatus,
    Invitation,
    Issue,
    IssueStatus,
    Membership,
    Notification,
    Role,
    User,
    Website,
)

router = APIRouter(prefix="/orgs", tags=["organizations"])


class OrgCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class OrgUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    report_company_name: str | None = Field(default=None, max_length=200)
    report_accent_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


def org_out(org, role: Role | None = None) -> dict:
    return {
        "id": str(org.id),
        "name": org.name,
        "plan_key": org.plan_key,
        "branding": org.branding or {},
        "role": role.value if role else None,
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }


@router.post("")
def create_org(body: OrgCreateIn, request: Request, ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    org = create_org_for(db, ctx.user, body.name.strip())
    audit.record(db, "org.created", org_id=org.id, actor_id=ctx.user.id, target_type="org", target_id=org.id, request=request)
    db.commit()
    return org_out(org, Role.owner)


@router.get("/{org_id}")
def get_org(o: OrgContext = Depends(OrgAccess())):
    return org_out(o.org, o.membership.role)


@router.patch("/{org_id}")
def update_org(body: OrgUpdateIn, request: Request, o: OrgContext = Depends(OrgAccess(Role.admin)), db: Session = Depends(get_db)):
    if body.name:
        o.org.name = body.name.strip()
    branding = dict(o.org.branding or {})
    if body.report_company_name is not None:
        branding["report_company_name"] = body.report_company_name.strip()
    if body.report_accent_color is not None:
        branding["report_accent_color"] = body.report_accent_color
    o.org.branding = branding
    audit.record(db, "org.updated", org_id=o.org_id, actor_id=o.user.id, request=request, data=body.model_dump(exclude_none=True))
    db.commit()
    return org_out(o.org, o.membership.role)


@router.delete("/{org_id}")
def delete_org(request: Request, o: OrgContext = Depends(OrgAccess(Role.owner)), db: Session = Depends(get_db)):
    """Permanently delete the organization and all of its data (websites, crawls, fixes, credentials)."""
    audit.record(db, "org.deleted", actor_id=o.user.id, target_type="org", target_id=o.org_id, request=request,
                 data={"name": o.org.name})
    db.delete(o.org)
    db.commit()
    return {"ok": True}


@router.get("/{org_id}/overview")
def overview(o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    sites = db.scalars(select(Website).where(Website.org_id == o.org_id).order_by(Website.created_at)).all()
    site_rows = []
    for w in sites:
        last = db.scalar(
            select(CrawlRun).where(CrawlRun.org_id == o.org_id, CrawlRun.website_id == w.id)
            .order_by(CrawlRun.created_at.desc()).limit(1)
        )
        site_rows.append(
            {
                "id": str(w.id),
                "name": w.name,
                "root_url": w.root_url,
                "schedule": w.schedule,
                "last_crawl": None if last is None else {
                    "id": str(last.id),
                    "status": last.status.value,
                    "created_at": last.created_at.isoformat(),
                    "summary": last.summary,
                },
            }
        )
    open_issues = db.scalar(
        select(func.count()).select_from(Issue).join(CrawlRun, CrawlRun.id == Issue.crawl_run_id)
        .where(Issue.org_id == o.org_id, Issue.status.in_([IssueStatus.open, IssueStatus.regressed]))
    ) or 0
    fixes_by_status = dict(
        db.execute(
            select(FixProposal.status, func.count()).where(FixProposal.org_id == o.org_id).group_by(FixProposal.status)
        ).all()
    )
    notes = db.scalars(
        select(Notification).where(Notification.org_id == o.org_id).order_by(Notification.created_at.desc()).limit(10)
    ).all()
    return {
        "org": org_out(o.org, o.membership.role),
        "websites": site_rows,
        "open_issue_rows": open_issues,
        "fixes": {k.value if isinstance(k, FixStatus) else k: v for k, v in fixes_by_status.items()},
        "notifications": [
            {"id": str(n.id), "kind": n.kind, "title": n.title, "body": n.body, "created_at": n.created_at.isoformat(),
             "read": n.read_at is not None, "website_id": str(n.website_id) if n.website_id else None}
            for n in notes
        ],
        "usage": usage_summary(db, o.org_id),
    }


@router.post("/{org_id}/notifications/read")
def mark_notifications_read(o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    for n in db.scalars(select(Notification).where(Notification.org_id == o.org_id, Notification.read_at.is_(None))):
        n.read_at = datetime.now(UTC)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- team
class InviteIn(BaseModel):
    email: EmailStr
    role: Role = Role.editor


class RoleUpdateIn(BaseModel):
    role: Role


@router.get("/{org_id}/members")
def list_members(o: OrgContext = Depends(OrgAccess()), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.org_id == o.org_id)
        .order_by(Membership.created_at)
    ).all()
    invites = db.scalars(
        select(Invitation).where(Invitation.org_id == o.org_id, Invitation.accepted_at.is_(None),
                                 Invitation.expires_at > datetime.now(UTC))
    ).all()
    return {
        "members": [
            {"id": str(m.id), "user_id": str(u.id), "email": u.email, "name": u.name, "role": m.role.value,
             "joined_at": m.created_at.isoformat()}
            for m, u in rows
        ],
        "invitations": [
            {"id": str(i.id), "email": i.email, "role": i.role.value, "expires_at": i.expires_at.isoformat()}
            for i in invites
        ],
        "seat_limit": effective_plan(db, o.org_id).team_seats,
    }


@router.post("/{org_id}/invitations")
def invite(body: InviteIn, request: Request, o: OrgContext = Depends(OrgAccess(Role.admin)), db: Session = Depends(get_db)):
    if body.role == Role.owner and o.membership.role != Role.owner:
        raise HTTPException(status_code=403, detail="Only owners can invite owners.")
    pending = db.scalar(
        select(func.count()).select_from(Invitation).where(
            Invitation.org_id == o.org_id, Invitation.accepted_at.is_(None), Invitation.expires_at > datetime.now(UTC))
    ) or 0
    check_seat_limit(db, o.org_id, pending)
    token = new_token()
    inv = Invitation(org_id=o.org_id, email=body.email.lower(), role=body.role, token_hash=hash_token(token),
                     invited_by=o.user.id, expires_at=datetime.now(UTC) + timedelta(days=7))
    db.add(inv)
    audit.record(db, "member.invited", org_id=o.org_id, actor_id=o.user.id, request=request,
                 data={"email": body.email.lower(), "role": body.role.value})
    db.commit()
    # No email service is required: the inviter shares this link. (SMTP delivery is optional.)
    return {"id": str(inv.id), "invite_url": f"{get_settings().public_app_url}/invite/{token}"}


@router.delete("/{org_id}/invitations/{invitation_id}")
def revoke_invite(invitation_id: uuid.UUID, o: OrgContext = Depends(OrgAccess(Role.admin)), db: Session = Depends(get_db)):
    inv = db.scalar(select(Invitation).where(Invitation.id == invitation_id, Invitation.org_id == o.org_id))
    if not inv:
        raise HTTPException(status_code=404, detail="Not found.")
    db.delete(inv)
    db.commit()
    return {"ok": True}


def _owner_count(db: Session, org_id) -> int:
    return db.scalar(select(func.count()).select_from(Membership).where(Membership.org_id == org_id, Membership.role == Role.owner)) or 0


@router.patch("/{org_id}/members/{membership_id}")
def update_member(membership_id: uuid.UUID, body: RoleUpdateIn, request: Request,
                  o: OrgContext = Depends(OrgAccess(Role.admin)), db: Session = Depends(get_db)):
    m = db.scalar(select(Membership).where(Membership.id == membership_id, Membership.org_id == o.org_id))
    if not m:
        raise HTTPException(status_code=404, detail="Not found.")
    if (m.role == Role.owner or body.role == Role.owner) and o.membership.role != Role.owner:
        raise HTTPException(status_code=403, detail="Only owners can change owner roles.")
    if m.role == Role.owner and body.role != Role.owner and _owner_count(db, o.org_id) <= 1:
        raise HTTPException(status_code=400, detail="An organization must keep at least one owner.")
    m.role = body.role
    audit.record(db, "member.role_changed", org_id=o.org_id, actor_id=o.user.id, target_type="membership",
                 target_id=m.id, request=request, data={"role": body.role.value})
    db.commit()
    return {"ok": True}


@router.delete("/{org_id}/members/{membership_id}")
def remove_member(membership_id: uuid.UUID, request: Request, o: OrgContext = Depends(OrgAccess(Role.viewer)),
                  db: Session = Depends(get_db)):
    m = db.scalar(select(Membership).where(Membership.id == membership_id, Membership.org_id == o.org_id))
    if not m:
        raise HTTPException(status_code=404, detail="Not found.")
    leaving_self = m.user_id == o.user.id
    if not leaving_self and not o.has_role(Role.admin):
        raise HTTPException(status_code=403, detail="This action requires the admin role or higher.")
    if m.role == Role.owner and not leaving_self and o.membership.role != Role.owner:
        raise HTTPException(status_code=403, detail="Only owners can remove owners.")
    if m.role == Role.owner and _owner_count(db, o.org_id) <= 1:
        raise HTTPException(status_code=400, detail="An organization must keep at least one owner.")
    db.delete(m)
    audit.record(db, "member.removed", org_id=o.org_id, actor_id=o.user.id, target_type="membership",
                 target_id=membership_id, request=request)
    db.commit()
    return {"ok": True}


@router.get("/{org_id}/audit-logs")
def audit_logs(o: OrgContext = Depends(OrgAccess(Role.admin)), db: Session = Depends(get_db), limit: int = 100):
    rows = db.scalars(
        select(AuditLog).where(AuditLog.org_id == o.org_id).order_by(AuditLog.created_at.desc()).limit(min(limit, 500))
    ).all()
    return [
        {"id": str(r.id), "action": r.action, "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
         "target_type": r.target_type, "target_id": r.target_id, "data": r.data, "ip": r.ip,
         "created_at": r.created_at.isoformat()}
        for r in rows
    ]
