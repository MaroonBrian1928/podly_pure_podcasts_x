import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
        # The shared executor has one worker. Run delayed refreshes once instead
        # of dropping them after the default one-second misfire grace period.
        misfire_grace_time=None,
        coalesce=True,
        max_instances=1,
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
        misfire_grace_time=None,
        coalesce=True,
        max_instances=1,
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


CUT_WINDOW_BACKFILL_JOB_ID = "backfill_cut_windows"
CUT_WINDOW_BACKFILL_DELAY_SECONDS = 60


def scheduled_cut_window_backfill() -> None:
    """One-off job: verify and store cut windows for already-processed posts."""
    from app.cut_stats import backfill_cut_windows

    if scheduler.app is None:
        _memory_trim_logger.warning("cut window backfill skipped: no app")
        return
    try:
        with scheduler.app.app_context():
            result = backfill_cut_windows(apply=True)
        _memory_trim_logger.info("cut window backfill: %s", result)
    except Exception:
        _memory_trim_logger.exception("cut window backfill: failed")


WORD_TIMESTAMP_COMPRESSION_JOB_ID = "compress_word_timestamps"
WORD_TIMESTAMP_COMPRESSION_DELAY_SECONDS = 180
# Each run handles one batch, then schedules the next, so the scheduler's single
# worker is free for feed refreshes and cleanup in between.
WORD_TIMESTAMP_COMPRESSION_BATCH_SIZE = 200
WORD_TIMESTAMP_COMPRESSION_BATCH_GAP_SECONDS = 30


def _word_timestamp_compression_marker() -> Path:
    """Exists once a run has found nothing left to compress.

    The candidate query reads every row's word timestamps, so without the marker
    each startup would scan the whole column again. Delete the file to rescan.
    """
    from shared.processing_paths import get_instance_dir

    return get_instance_dir() / "word_timestamps_compressed"


def scheduled_word_timestamp_compression() -> None:
    """One-off job: gzip word timestamps saved as plain JSON by earlier releases."""
    from app.word_timestamp_compression import compress_word_timestamps

    marker = _word_timestamp_compression_marker()
    if marker.exists():
        return
    if scheduler.app is None:
        _memory_trim_logger.warning("word timestamp compression skipped: no app")
        return
    try:
        with scheduler.app.app_context():
            result = compress_word_timestamps(
                apply=True, limit=WORD_TIMESTAMP_COMPRESSION_BATCH_SIZE
            )
        _memory_trim_logger.info("word timestamp compression: %s", result)
    except Exception:
        _memory_trim_logger.exception("word timestamp compression: failed")
        return
    if (
        result["candidates"] < WORD_TIMESTAMP_COMPRESSION_BATCH_SIZE
        and result["failed"] == 0
    ):
        marker.touch()
        return
    # A full batch that made progress means more rows may remain. A batch that
    # compressed nothing (only failing rows left) ends the job instead of looping.
    if (
        result["candidates"] >= WORD_TIMESTAMP_COMPRESSION_BATCH_SIZE
        and result["compressed"] > 0
    ):
        schedule_word_timestamp_compression_job(
            delay_seconds=WORD_TIMESTAMP_COMPRESSION_BATCH_GAP_SECONDS
        )


def schedule_word_timestamp_compression_job(
    delay_seconds: int = WORD_TIMESTAMP_COMPRESSION_DELAY_SECONDS,
) -> None:
    """Run one batch of word timestamp compression after the delay."""
    scheduler.add_job(
        id=WORD_TIMESTAMP_COMPRESSION_JOB_ID,
        func=scheduled_word_timestamp_compression,
        trigger="date",
        run_date=datetime.now(UTC).replace(tzinfo=None)
        + timedelta(seconds=delay_seconds),
        replace_existing=True,
        misfire_grace_time=None,
        max_instances=1,
    )


def schedule_cut_window_backfill_job() -> None:
    """Run the cut-window backfill once shortly after startup."""
    scheduler.add_job(
        id=CUT_WINDOW_BACKFILL_JOB_ID,
        func=scheduled_cut_window_backfill,
        trigger="date",
        run_date=datetime.now(UTC).replace(tzinfo=None)
        + timedelta(seconds=CUT_WINDOW_BACKFILL_DELAY_SECONDS),
        replace_existing=True,
        misfire_grace_time=None,
        max_instances=1,
    )
