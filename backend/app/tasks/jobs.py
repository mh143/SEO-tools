from __future__ import annotations

import logging
import uuid

from app.tasks.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.jobs.run_crawl")
def run_crawl(run_id: str) -> None:
    from app.services.crawl_service import execute_run

    execute_run(uuid.UUID(run_id))


@celery_app.task(name="app.tasks.jobs.apply_fix")
def apply_fix(fix_id: str, actor_id: str | None = None) -> None:
    from app.fixes.publisher import apply_fix_job

    apply_fix_job(uuid.UUID(fix_id), uuid.UUID(actor_id) if actor_id else None)


@celery_app.task(name="app.tasks.jobs.verify_fix")
def verify_fix(fix_id: str) -> None:
    from app.fixes.publisher import verify_fix_job

    verify_fix_job(uuid.UUID(fix_id))


@celery_app.task(name="app.tasks.jobs.rollback_fix")
def rollback_fix(fix_id: str, actor_id: str | None = None) -> None:
    from app.fixes.publisher import rollback_fix_job

    rollback_fix_job(uuid.UUID(fix_id), uuid.UUID(actor_id) if actor_id else None)


@celery_app.task(name="app.tasks.jobs.dispatch_scheduled_audits")
def dispatch_scheduled_audits() -> int:
    from app.services.scheduler import dispatch_due

    return dispatch_due()


@celery_app.task(name="app.tasks.jobs.verify_pending_fixes")
def verify_pending_fixes() -> int:
    from app.fixes.publisher import verify_pending

    return verify_pending()


@celery_app.task(name="app.tasks.jobs.apply_retention")
def apply_retention() -> dict:
    from app.services.retention import apply_retention as run

    return run()


@celery_app.task(name="app.tasks.jobs.cleanup_stale")
def cleanup_stale() -> int:
    from app.services.crawl_service import cleanup_stale_runs

    return cleanup_stale_runs()
