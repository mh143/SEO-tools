"""Fixed-window rate limiter backed by Redis, with an in-process fallback.

The fallback keeps development/tests working without Redis; in production Redis is required
so limits are shared across API replicas.
"""

from __future__ import annotations

import threading
import time

from fastapi import HTTPException, Request

from app.core.config import get_settings

_local: dict[str, tuple[int, float]] = {}
_lock = threading.Lock()
_redis = None
_redis_failed = False


def _get_redis():
    global _redis, _redis_failed
    if _redis is None and not _redis_failed:
        try:
            import redis

            r = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
            r.ping()
            _redis = r
        except Exception:
            if get_settings().is_production:
                raise
            _redis_failed = True
    return _redis


def hit(key: str, limit: int, window_seconds: int) -> bool:
    """Record a hit; return True if allowed."""
    if get_settings().app_env == "test" and not key.startswith("test:"):
        # Tests exercise the limiter explicitly with "test:" keys.
        return True
    bucket = int(time.time() // window_seconds)
    full_key = f"rl:{key}:{bucket}"
    r = _get_redis()
    if r is not None:
        n = r.incr(full_key)
        if n == 1:
            r.expire(full_key, window_seconds + 5)
        return int(n) <= limit
    with _lock:
        count, exp = _local.get(full_key, (0, time.time() + window_seconds))
        count += 1
        _local[full_key] = (count, exp)
        if len(_local) > 10000:
            now = time.time()
            for k in [k for k, (_, e) in _local.items() if e < now]:
                _local.pop(k, None)
        return count <= limit


def client_ip(request: Request) -> str:
    # Behind a trusted reverse proxy, uvicorn's --proxy-headers sets request.client correctly.
    return request.client.host if request.client else "unknown"


def enforce(request: Request, scope: str, limit: int, window_seconds: int, identity: str | None = None) -> None:
    ident = identity or client_ip(request)
    if not hit(f"{scope}:{ident}", limit, window_seconds):
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down and try again later.")
