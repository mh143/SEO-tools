from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog


def record(
    db: Session,
    action: str,
    *,
    org_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: Any = None,
    request: Request | None = None,
    data: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            org_id=org_id,
            actor_user_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            ip=(request.client.host if request and request.client else None),
            user_agent=(request.headers.get("user-agent", "")[:400] if request else None),
            data=_scrub(data or {}),
        )
    )


_SECRET_KEYS = {"password", "token", "secret", "credentials", "api_key", "authorization"}


def _scrub(data: dict) -> dict:
    out = {}
    for k, v in data.items():
        if any(s in k.lower() for s in _SECRET_KEYS):
            out[k] = "[redacted]"
        elif isinstance(v, dict):
            out[k] = _scrub(v)
        else:
            out[k] = v
    return out
