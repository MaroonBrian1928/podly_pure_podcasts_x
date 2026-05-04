from datetime import UTC, datetime, timedelta
from typing import Any

from app.extensions import db
from app.jobs_manager_run_service import recalculate_run_counts
from app.models import Post, ProcessingJob


def dequeue_job_action(params: dict[str, Any]) -> dict[str, Any] | None:
    run_id = params.get("run_id")

    # Check for running jobs
    running_job = (
        ProcessingJob.query.filter(ProcessingJob.status == "running")
        .order_by(ProcessingJob.started_at.desc().nullslast())
        .first()
    )
    if running_job:
        return None

    job = (
        ProcessingJob.query.filter(ProcessingJob.status == "pending")
        .order_by(ProcessingJob.created_at.asc())
        .first()
    )
    if not job:
        return None

    job.status = "running"
    job.started_at = datetime.now(UTC).replace(tzinfo=None)

    if run_id and job.jobs_manager_run_id != run_id:
        job.jobs_manager_run_id = run_id

    return {"job_id": job.id, "post_guid": job.post_guid}


def cleanup_stale_jobs_action(params: dict[str, Any]) -> dict[str, Any]:
    older_than_seconds = params.get("older_than_seconds", 3600)
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(
        seconds=older_than_seconds
    )

    old_jobs = ProcessingJob.query.filter(ProcessingJob.created_at < cutoff).all()

    count = len(old_jobs)
    for job in old_jobs:
        db.session.delete(job)

    return {"count": count}


def clear_all_jobs_action(params: dict[str, Any]) -> int:
    all_jobs = ProcessingJob.query.all()
    count = len(all_jobs)
    for job in all_jobs:
        db.session.delete(job)
    return count


def clear_active_jobs_action(params: dict[str, Any]) -> int:
    """Reset interrupted running jobs back to pending on startup.

    Only affects jobs with status="running" — those were mid-execution when the
    process was killed and must be retried. Pending jobs are left untouched so
    their existing queue position is preserved and _ensure_jobs_for_all_posts
    does not re-create duplicates for every whitelisted episode.
    """
    running_jobs = ProcessingJob.query.filter(
        ProcessingJob.status == "running"
    ).all()
    count = len(running_jobs)
    for job in running_jobs:
        job.status = "pending"
        job.started_at = None
    if count > 0:
        recalculate_run_counts(db.session)
    return count


def create_job_action(params: dict[str, Any]) -> dict[str, Any]:
    job_data = params.get("job_data")
    if not isinstance(job_data, dict):
        raise ValueError("job_data must be a dictionary")

    # Convert date strings back to datetime objects if necessary
    if "created_at" in job_data and isinstance(job_data["created_at"], str):
        job_data["created_at"] = datetime.fromisoformat(job_data["created_at"])

    job = ProcessingJob(**job_data)
    db.session.add(job)

    if job.jobs_manager_run_id:
        recalculate_run_counts(db.session)

    db.session.flush()
    return {"job_id": job.id}


def create_job_if_missing_action(params: dict[str, Any]) -> dict[str, Any]:
    """Create a new pending job only if no completed/skipped job already exists for the post."""
    job_data = params.get("job_data")
    if not isinstance(job_data, dict):
        raise ValueError("job_data must be a dictionary")

    post_guid = job_data.get("post_guid")
    if not post_guid:
        raise ValueError("job_data must contain post_guid")

    existing = ProcessingJob.query.filter_by(post_guid=post_guid).first()
    if existing:
        return {"job_id": None, "skipped": True}

    return create_job_action({"job_data": job_data})


def cancel_existing_jobs_action(params: dict[str, Any]) -> int:
    post_guid = params.get("post_guid")
    current_job_id = params.get("current_job_id")

    existing_jobs = (
        ProcessingJob.query.filter_by(post_guid=post_guid)
        .filter(
            ProcessingJob.status.in_(["pending", "running"]),
            ProcessingJob.id != current_job_id,
        )
        .all()
    )

    count = len(existing_jobs)
    for existing_job in existing_jobs:
        db.session.delete(existing_job)

    if count > 0:
        recalculate_run_counts(db.session)

    return count


def update_job_status_action(params: dict[str, Any]) -> dict[str, Any]:
    job_id = params.get("job_id")
    status = params.get("status")
    step = params.get("step")
    step_name = params.get("step_name")
    progress = params.get("progress")
    error_message = params.get("error_message")

    job = db.session.get(ProcessingJob, job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    job.status = status
    job.current_step = step
    job.step_name = step_name
    if progress is not None:
        job.progress_percentage = progress

    if error_message:
        job.error_message = error_message

    if status == "running" and not job.started_at:
        job.started_at = datetime.now(UTC).replace(tzinfo=None)
    elif (
        status in ["completed", "failed", "cancelled", "skipped"]
        and not job.completed_at
    ):
        job.completed_at = datetime.now(UTC).replace(tzinfo=None)

    if job.jobs_manager_run_id:
        recalculate_run_counts(db.session)

    return {"job_id": job.id, "status": job.status}


def mark_cancelled_action(params: dict[str, Any]) -> dict[str, Any]:
    job_id = params.get("job_id")
    reason = params.get("reason")

    job = db.session.get(ProcessingJob, job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    job.status = "cancelled"
    job.error_message = reason
    job.completed_at = datetime.now(UTC).replace(tzinfo=None)

    if job.jobs_manager_run_id:
        recalculate_run_counts(db.session)

    return {"job_id": job.id, "status": "cancelled"}


def mark_cancelled_bulk_action(params: dict[str, Any]) -> dict[str, Any]:
    reason = params.get("reason", "Cancelled by user request")
    now = datetime.now(UTC).replace(tzinfo=None)

    active_jobs = ProcessingJob.query.filter(
        ProcessingJob.status.in_(["pending", "running"])
    ).all()

    job_ids = [job.id for job in active_jobs]
    for job in active_jobs:
        job.status = "cancelled"
        job.error_message = reason
        job.completed_at = now

    if active_jobs:
        recalculate_run_counts(db.session)

    return {"job_ids": job_ids, "cancelled_count": len(job_ids)}


def cancel_pending_jobs_for_feed_action(params: dict[str, Any]) -> dict[str, Any]:
    """Bulk-cancel all pending jobs for a feed in two SQL statements.

    Selects matching job IDs via a JOIN (SQLAlchemy can't JOIN in a bulk UPDATE
    portably), then issues a single UPDATE ... WHERE id IN (...).
    """
    feed_id = params.get("feed_id")
    if feed_id is None:
        raise ValueError("feed_id is required")

    job_ids: list[str] = [
        row.id
        for row in (
            db.session.query(ProcessingJob.id)
            .join(Post, ProcessingJob.post_guid == Post.guid)
            .filter(ProcessingJob.status == "pending", Post.feed_id == feed_id)
            .all()
        )
    ]

    if not job_ids:
        return {"cancelled_count": 0, "cancelled_ids": []}

    now = datetime.now(UTC).replace(tzinfo=None)
    ProcessingJob.query.filter(ProcessingJob.id.in_(job_ids)).update(
        {
            ProcessingJob.status: "cancelled",
            ProcessingJob.error_message: "Cancelled by user request",
            ProcessingJob.completed_at: now,
        },
        synchronize_session=False,
    )
    recalculate_run_counts(db.session)

    return {"cancelled_count": len(job_ids), "cancelled_ids": job_ids}


def reassign_pending_jobs_action(params: dict[str, Any]) -> int:
    run_id = params.get("run_id")
    if not run_id:
        return 0

    pending_jobs = (
        ProcessingJob.query.filter(ProcessingJob.status == "pending")
        .order_by(ProcessingJob.created_at.asc())
        .all()
    )

    reassigned = 0
    for job in pending_jobs:
        if job.jobs_manager_run_id != run_id:
            job.jobs_manager_run_id = run_id
            reassigned += 1

    if reassigned:
        recalculate_run_counts(db.session)

    return reassigned
