from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("seo_platform", broker=settings.redis_url, backend=settings.redis_url, include=["app.tasks.jobs"])
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=60 * 60,
    task_soft_time_limit=55 * 60,
    task_default_queue="default",
    task_routes={"app.tasks.jobs.run_crawl": {"queue": "crawl"}},
    beat_schedule={
        "dispatch-scheduled-audits": {"task": "app.tasks.jobs.dispatch_scheduled_audits", "schedule": 300.0},
        "verify-pending-fixes": {"task": "app.tasks.jobs.verify_pending_fixes", "schedule": 300.0},
        "retention": {"task": "app.tasks.jobs.apply_retention", "schedule": 6 * 3600.0},
        "stale-runs": {"task": "app.tasks.jobs.cleanup_stale", "schedule": 1800.0},
    },
    timezone="UTC",
)
