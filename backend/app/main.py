from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import get_settings

log = logging.getLogger("app")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        docs_url=f"{settings.api_base_path}/docs",
        openapi_url=f"{settings.api_base_path}/openapi.json",
        redoc_url=None,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        if settings.is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        errors = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    from app.api.routes import (
        admin,
        auth,
        billing,
        crawls,
        fixes,
        integrations,
        keywords,
        orgs,
        public,
        reports,
        websites,
    )

    prefix = settings.api_base_path
    for r in (auth, orgs, websites, crawls, fixes, integrations, keywords, billing, reports, public, admin):
        app.include_router(r.router, prefix=prefix)

    @app.get(f"{prefix}/health")
    def health():
        """Liveness: the process is up."""
        return {"status": "ok"}

    @app.get(f"{prefix}/health/ready")
    def ready():
        """Readiness: database and Redis are reachable."""
        from sqlalchemy import text

        from app.core.db import get_engine

        checks = {}
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:  # pragma: no cover - exercised in deployment
            checks["database"] = f"error: {type(exc).__name__}"
        try:
            import redis

            redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1).ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {type(exc).__name__}"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "degraded", **checks})

    return app


app = create_app()
