"""Encryption of integration credentials at rest (Fernet / AES-128-CBC + HMAC-SHA256).

ENCRYPTION_KEYS holds one or more comma separated Fernet keys. The first key encrypts;
all keys can decrypt, enabling rotation. In development a key is derived from SECRET_KEY
so the app runs out of the box; production refuses to boot without ENCRYPTION_KEYS.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings


def _fernet() -> MultiFernet:
    s = get_settings()
    keys = [k.strip() for k in s.encryption_keys.split(",") if k.strip()]
    if not keys:
        derived = base64.urlsafe_b64encode(hashlib.sha256(("enc:" + s.secret_key).encode()).digest())
        keys = [derived.decode()]
    return MultiFernet([Fernet(k) for k in keys])


def encrypt_json(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt_json(token: str) -> dict[str, Any]:
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as exc:  # pragma: no cover - indicates key misconfiguration
        raise RuntimeError("Unable to decrypt credentials (check ENCRYPTION_KEYS)") from exc
