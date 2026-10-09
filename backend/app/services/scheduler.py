"""Recurring audits. Celery beat calls ``dispatch_due`` every 5 minutes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.billing import entitlements
from app.core.db import db_session
from app.models import Website

log = logging.getLogger(__name__)

INTERVALS = {"daily": timedelta(days=1), "weekly": timedelta(days=7), "monthly": timedelta(days=30)}


def compute_next(schedule: str, after: datetime | None = None) -> datetime | None:
    if schedule not in INTERVALS:
        return None
    return (after or datetime.now(UTC)) + INTERVALS[schedule]


def dispatch_due(now: datetime | None = None) -> int:
    from app.services.crawl_service import create_run
    from app.tasks.dispatch import enqueue

    now = now or datetime.now(UTC)
    started = 0
    with db_session() as db:
        due = db.scalars(
            select(Website).where(Website.schedule != "none", Website.next_scheduled_at.is_not(None),
                                  Website.next_scheduled_at <= now).with_for_update(skip_locked=True).limit(100)
        ).all()
        to_enqueue = []
        for w in due:
            plan = entitlements.effective_plan(db, w.org_id)
            w.next_scheduled_at = compute_next(w.schedule, now)
            if w.schedule not in plan.schedules:
                # Plan was downgraded: disable the schedule instead of silently failing every time.
                log.info("disabling schedule for website %s (plan %s)", w.id, plan.key)
                w.schedule, w.next_scheduled_at = "none", None
                continue
            try:
                with db.begin_nested():
                    run = create_run(db, website=w, user_id=None, trigger="scheduled")
                to_enqueue.append(str(run.id))
            except HTTPException as exc:  # limit reached / crawl already running
                log.info("scheduled crawl skipped for %s: %s", w.id, exc.detail)
        db.commit()
    for run_id in to_enqueue:
        enqueue("run_crawl", run_id)
        started += 1
    return started
