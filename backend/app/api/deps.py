"""Request dependencies: authentication, CSRF, and organization-scoped authorization.

Tenant isolation rule: every org-scoped route takes ``org_id`` from the path and resolves it via
``OrgAccess`` which requires a membership row for the current user. Non-members receive 404 (not
403) so that the existence of other organizations is not disclosed. Resources are then loaded
with ``scoped_get`` which always filters by that org_id.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import constant_time_eq, hash_token
from app.models import ROLE_RANK, Membership, Organization, Role, User, UserSession

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

T = TypeVar("T")


@dataclass
class AuthContext:
    user: User
    session: UserSession


def _load_session(request: Request, db: Session) -> AuthContext | None:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        return None
    sess = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if sess is None or sess.revoked_at is not None or sess.expires_at < datetime.now(UTC):
        return None
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        return None
    return AuthContext(user=user, session=sess)


def check_csrf(request: Request, sess: UserSession) -> None:
    if request.method not in UNSAFE_METHODS:
        return
    header = request.headers.get("x-csrf-token", "")
    if not header or not constant_time_eq(header, sess.csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid.")


def check_origin(request: Request) -> None:
    """Reject cross-site unsafe requests when the browser tells us the origin."""
    if request.method not in UNSAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != get_settings().public_app_url and get_settings().is_production:
        raise HTTPException(status_code=403, detail="Cross-origin request rejected.")


def optional_auth(request: Request, db: Session = Depends(get_db)) -> AuthContext | None:
    ctx = _load_session(request, db)
    if ctx is not None:
        check_csrf(request, ctx.session)
    return ctx


def require_auth(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    check_origin(request)
    ctx = _load_session(request, db)
    if ctx is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    check_csrf(request, ctx.session)
    return ctx


def require_platform_admin(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
    if not ctx.user.is_platform_admin:
        raise HTTPException(status_code=404, detail="Not found.")
    return ctx


@dataclass
class OrgContext:
    org: Organization
    membership: Membership
    user: User

    @property
    def org_id(self) -> uuid.UUID:
        return self.org.id

    def has_role(self, minimum: Role) -> bool:
        return ROLE_RANK[self.membership.role] >= ROLE_RANK[minimum]


class OrgAccess:
    """Dependency: ``Depends(OrgAccess(Role.editor))``."""

    def __init__(self, minimum: Role = Role.viewer):
        self.minimum = minimum

    def __call__(
        self, org_id: uuid.UUID, ctx: AuthContext = Depends(require_auth), db: Session = Depends(get_db)
    ) -> OrgContext:
        m = db.scalar(select(Membership).where(Membership.org_id == org_id, Membership.user_id == ctx.user.id))
        if m is None:
            raise HTTPException(status_code=404, detail="Not found.")
        org = db.get(Organization, org_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Not found.")
        if ROLE_RANK[m.role] < ROLE_RANK[self.minimum]:
            raise HTTPException(status_code=403, detail=f"This action requires the {self.minimum.value} role or higher.")
        return OrgContext(org=org, membership=m, user=ctx.user)


def scoped_get(db: Session, model: type[T], obj_id: Any, org_id: uuid.UUID) -> T:
    """Load a tenant-owned row by id *and* org_id, or 404."""
    try:
        obj_uuid = obj_id if isinstance(obj_id, uuid.UUID) else uuid.UUID(str(obj_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found.") from None
    obj = db.scalar(select(model).where(model.id == obj_uuid, model.org_id == org_id))  # type: ignore[attr-defined]
    if obj is None:
        raise HTTPException(status_code=404, detail="Not found.")
    return obj
