import logging
import os
from datetime import UTC, datetime, timedelta

from app.extensions import scheduler
from app.jobs_manager import (
    scheduled_refresh_all_feeds,
)
from app.memory_pressure import release_memory_to_os
from app.post_cleanup import scheduled_cleanup_processed_posts

_memory_trim_logger = logging.getLogger("global_logger")


def scheduled_memory_trim() -> None:
    """APScheduler entry-point: trim allocator arenas during idle periods.

    The on-demand trims in feeds.py / writer service.py only run after
    specific work units. When the web process is idle (no feed refreshes,
    no large XML renders), nothing reclaims fragmented arenas, so RSS
    drifts upward. This periodic trim catches that slow drift.

    Logs at INFO so operators can confirm the job is actually firing —
    APScheduler swallows exceptions to its own logger which is usually
    silenced, so without an INFO breadcrumb this fire was invisible.
    """
    _memory_trim_logger.info("scheduled idle trim: starting")
    try:
        release_memory_to_os("scheduled idle trim", _memory_trim_logger)
    except Exception:
        _memory_trim_logger.exception("scheduled idle trim: failed")
        return
    _memory_trim_logger.info("scheduled idle trim: done")


def add_background_job(minutes: int) -> None:
    """Add the recurring background job for refreshing feeds.

    minutes: interval in minutes; must be a positive integer.
    """

    scheduler.add_job(
        id="refresh_all_feeds",
        func=scheduled_refresh_all_feeds,
        trigger="interval",
        minutes=minutes,
        replace_existing=True,
    )


def schedule_cleanup_job(retention_days: int | None) -> None:
    """Ensure the periodic cleanup job is scheduled or disabled as needed."""
    job_id = "cleanup_processed_posts"
    if retention_days is None or retention_days <= 0:
        try:
            scheduler.remove_job(job_id)
        except Exception:  # noqa: BLE001
            # Job may not be scheduled; ignore.
            pass
        return

    # Run daily; allow scheduler to coalesce missed runs.
    scheduler.add_job(
        id=job_id,
        func=scheduled_cleanup_processed_posts,
        trigger="interval",
        hours=24,
        next_run_time=datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=15),
        replace_existing=True,
    )


def schedule_memory_trim_job() -> None:
    """Schedule a periodic allocator trim. Disabled with interval <= 0."""
    job_id = "memory_trim"
    raw = os.environ.get("PODLY_MEMORY_TRIM_INTERVAL_MIN", "15")
    try:
        interval_min = int(raw)
    except ValueError:
        interval_min = 15

    if interval_min <= 0:
        try:
            scheduler.remove_job(job_id)
        except Exception:  # noqa: BLE001
            pass
        return

    # misfire_grace_time=None: a memory trim that's "late" is still useful;
    # the default 1s makes the job get skipped whenever the scheduler is
    # busy (e.g. mid refresh-all batch), which is exactly when we'd want
    # the trim to run. coalesce=True merges any backed-up runs into one
    # fire so we don't trim multiple times in a row after a long pause.
    scheduler.add_job(
        id=job_id,
        func=scheduled_memory_trim,
        trigger="interval",
        minutes=interval_min,
        next_run_time=datetime.now(UTC).replace(tzinfo=None)
        + timedelta(minutes=interval_min),
        replace_existing=True,
        misfire_grace_time=None,
        coalesce=True,
    )
