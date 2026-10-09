"""Dispatch background jobs either to Celery or to an in-process thread (TASK_BACKEND=inline).

Inline mode exists for local development and end-to-end tests without a worker. It is not
intended for production: jobs are lost if the API process restarts.
"""

from __future__ import annotations

import logging
import threading

from app.core.config import get_settings

log = logging.getLogger(__name__)


def enqueue(task_name: str, *args) -> None:
    from app.tasks import jobs

    if get_settings().task_backend == "inline":
        fn = getattr(jobs, task_name)
        target = getattr(fn, "run", fn)  # celery task -> underlying function

        def _run():
            try:
                target(*args)
            except Exception:
                log.exception("inline job %s failed", task_name)

        t = threading.Thread(target=_run, daemon=True, name=f"job-{task_name}")
        t.start()
        _threads.append(t)
        return
    getattr(jobs, task_name).delay(*args)


_threads: list[threading.Thread] = []


def wait_inline(timeout: float = 60) -> None:
    """Test helper: wait for inline jobs to finish."""
    for t in list(_threads):
        t.join(timeout)
    _threads.clear()
