from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, optional_auth, require_auth
from app.core import audit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.ratelimit import enforce
from app.core.security import (
    hash_password,
    hash_token,
    new_token,
    validate_password_strength,
    verify_password,
)
from app.models import Invitation, Membership, Organization, Role, Subscription, User, UserSession

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    name: str = Field(default="", max_length=200)
    org_name: str = Field(default="", max_length=200)
    invite_token: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


def _set_session(db: Session, response: Response, request: Request, user: User) -> dict:
    s = get_settings()
    token = new_token()
    csrf = new_token(24)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_token(token),
            csrf_token=csrf,
            expires_at=datetime.now(UTC) + timedelta(hours=s.session_ttl_hours),
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:400],
        )
    )
    max_age = s.session_ttl_hours * 3600
    response.set_cookie(
        s.session_cookie_name, token, httponly=True, secure=s.cookie_secure, samesite="lax", max_age=max_age, path="/"
    )
    # Readable by JS so the frontend can echo it in the X-CSRF-Token header (double submit).
    response.set_cookie(
        s.csrf_cookie_name, csrf, httponly=False, secure=s.cookie_secure, samesite="lax", max_age=max_age, path="/"
    )
    return {"csrf_token": csrf}


def user_payload(db: Session, user: User) -> dict:
    rows = db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.org_id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.created_at)
    ).all()
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "is_platform_admin": user.is_platform_admin,
        "organizations": [
            {"id": str(o.id), "name": o.name, "role": m.role.value, "plan_key": o.plan_key} for m, o in rows
        ],
    }


def create_org_for(db: Session, user: User, name: str) -> Organization:
    org = Organization(name=name or "My workspace", plan_key="free")
    db.add(org)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role=Role.owner))
    db.add(Subscription(org_id=org.id, plan_key="free", status="active"))
    return org


@router.post("/signup")
def signup(body: SignupIn, request: Request, response: Response, db: Session = Depends(get_db)):
    enforce(request, "signup", get_settings().rate_limit_auth_per_minute, 60)
    if err := validate_password_strength(body.password):
        raise HTTPException(status_code=422, detail=err)
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    s = get_settings()
    user = User(
        email=email,
        name=body.name.strip(),
        password_hash=hash_password(body.password),
        is_platform_admin=bool(s.bootstrap_admin_email and s.bootstrap_admin_email.lower() == email),
    )
    db.add(user)
    db.flush()
    invited_org = None
    if body.invite_token:
        inv = db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(body.invite_token)))
        if inv and inv.accepted_at is None and inv.expires_at > datetime.now(UTC) and inv.email.lower() == email:
            db.add(Membership(org_id=inv.org_id, user_id=user.id, role=inv.role))
            inv.accepted_at = datetime.now(UTC)
            invited_org = inv.org_id
    if invited_org is None:
        org = create_org_for(db, user, body.org_name.strip() or f"{body.name.strip() or email.split('@')[0]}'s workspace")
        audit.record(db, "org.created", org_id=org.id, actor_id=user.id, target_type="org", target_id=org.id, request=request)
    audit.record(db, "user.signup", actor_id=user.id, target_type="user", target_id=user.id, request=request)
    csrf = _set_session(db, response, request, user)
    db.commit()
    return {"user": user_payload(db, user), **csrf}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    enforce(request, "login", get_settings().rate_limit_auth_per_minute, 60)
    enforce(request, "login-email", 20, 3600, identity=body.email.lower())
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not verify_password(body.password, user.password_hash if user else None) or not user or not user.is_active:
        audit.record(db, "user.login_failed", request=request, data={"email": body.email.lower()})
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    user.last_login_at = datetime.now(UTC)
    csrf = _set_session(db, response, request, user)
    audit.record(db, "user.login", actor_id=user.id, target_type="user", target_id=user.id, request=request)
    db.commit()
    return {"user": user_payload(db, user), **csrf}


@router.post("/logout")
def logout(response: Response, ctx: AuthContext | None = Depends(optional_auth), db: Session = Depends(get_db)):
    if ctx:
        ctx.session.revoked_at = datetime.now(UTC)
        db.commit()
    s = get_settings()
    response.delete_cookie(s.session_cookie_name, path="/")
    response.delete_cookie(s.csrf_cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    return {"user": user_payload(db, ctx.user), "csrf_token": ctx.session.csrf_token}


@router.post("/password")
def change_password(
    body: PasswordChangeIn, request: Request, ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)
):
    if not verify_password(body.current_password, ctx.user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if err := validate_password_strength(body.new_password):
        raise HTTPException(status_code=422, detail=err)
    ctx.user.password_hash = hash_password(body.new_password)
    # Revoke all other sessions.
    for sess in db.scalars(select(UserSession).where(UserSession.user_id == ctx.user.id, UserSession.id != ctx.session.id)):
        sess.revoked_at = datetime.now(UTC)
    audit.record(db, "user.password_changed", actor_id=ctx.user.id, request=request)
    db.commit()
    return {"ok": True}


class AcceptInviteIn(BaseModel):
    token: str


@router.post("/invitations/accept")
def accept_invite(body: AcceptInviteIn, request: Request, ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(body.token)))
    if not inv or inv.accepted_at is not None or inv.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=404, detail="Invitation not found or expired.")
    if inv.email.lower() != ctx.user.email:
        raise HTTPException(status_code=403, detail="This invitation was sent to a different email address.")
    exists = db.scalar(select(Membership).where(Membership.org_id == inv.org_id, Membership.user_id == ctx.user.id))
    if not exists:
        db.add(Membership(org_id=inv.org_id, user_id=ctx.user.id, role=inv.role))
    inv.accepted_at = datetime.now(UTC)
    audit.record(db, "member.joined", org_id=inv.org_id, actor_id=ctx.user.id, request=request)
    db.commit()
    return {"org_id": str(inv.org_id)}


class DeleteAccountIn(BaseModel):
    password: str


@router.post("/delete-account")
def delete_account(body: DeleteAccountIn, request: Request, response: Response,
                   ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    """Deletes the user. Organizations where they are the sole owner are deleted with all their data."""
    if not verify_password(body.password, ctx.user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect.")
    for m in list(db.scalars(select(Membership).where(Membership.user_id == ctx.user.id))):
        if m.role == Role.owner:
            other_owners = db.scalars(
                select(Membership).where(Membership.org_id == m.org_id, Membership.role == Role.owner,
                                         Membership.user_id != ctx.user.id)
            ).first()
            if other_owners is None:
                org = db.get(Organization, m.org_id)
                if org:
                    db.delete(org)
    audit.record(db, "user.deleted", target_type="user", target_id=ctx.user.id, request=request)
    db.delete(ctx.user)
    db.commit()
    s = get_settings()
    response.delete_cookie(s.session_cookie_name, path="/")
    response.delete_cookie(s.csrf_cookie_name, path="/")
    return {"ok": True}
