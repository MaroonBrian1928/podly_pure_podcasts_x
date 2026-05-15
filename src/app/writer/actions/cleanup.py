import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.extensions import db
from app.job_stage_history import initial_stage_history
from app.jobs_manager_run_service import recalculate_run_counts
from app.model_call_utils import whisper_model_call_filter
from app.models import (
    AudioSegment,
    Identification,
    ModelCall,
    Post,
    ProcessingJob,
    TranscriptSegment,
)
from shared.processing_paths import (
    find_existing_processed_audio_path,
    get_processed_audio_path_candidates,
)

logger = logging.getLogger("writer")


def cleanup_missing_audio_paths_action(params: dict[str, Any]) -> int:
    inconsistent_posts = Post.query.filter(
        Post.whitelisted,
        (
            (Post.unprocessed_audio_path.isnot(None))
            | (Post.processed_audio_path.isnot(None))
        ),
    ).all()

    count = 0
    for post in inconsistent_posts:
        changed = False
        existing_processed_path = find_existing_processed_audio_path(
            processed_audio_path=post.processed_audio_path,
            unprocessed_audio_path=post.unprocessed_audio_path,
            feed_title=getattr(post.feed, "title", None),
            post_title=post.title,
        )
        if existing_processed_path:
            resolved_processed_path = str(existing_processed_path)
            if post.processed_audio_path != resolved_processed_path:
                post.processed_audio_path = resolved_processed_path
                changed = True
        elif post.processed_audio_path:
            post.processed_audio_path = None
            changed = True
        if post.unprocessed_audio_path and not os.path.exists(
            post.unprocessed_audio_path
        ):
            post.unprocessed_audio_path = None
            changed = True

        if changed:
            latest_job = (
                ProcessingJob.query.filter_by(post_guid=post.guid)
                .order_by(ProcessingJob.created_at.desc())
                .first()
            )
            if latest_job and latest_job.status not in {"pending", "running"}:
                latest_job.status = "pending"
                latest_job.current_step = 0
                latest_job.progress_percentage = 0.0
                latest_job.step_name = "Not started"
                latest_job.error_message = None
                latest_job.started_at = None
                latest_job.completed_at = None
                # Drop the previous run's stage history and reseed step 0 from
                # the requeue moment so the UI reports the new queue wait and
                # doesn't surface stale per-stage timings from the prior run.
                requeued_at = datetime.now(UTC).replace(tzinfo=None)
                latest_job.stage_history = initial_stage_history(
                    step_name="Not started", at=requeued_at
                )

            count += 1

    return count


def clear_post_processing_data_action(params: dict[str, Any]) -> dict[str, Any]:
    post_id = params.get("post_id")
    post = db.session.get(Post, post_id)
    if not post:
        raise ValueError(f"Post {post_id} not found")

    logger.info("[WRITER] clear_post_processing_data_action: post_id=%s", post_id)

    # Chunked deletes for segments and identifications
    while True:
        ids_batch = [
            row[0]
            for row in db.session.query(TranscriptSegment.id)
            .filter_by(post_id=post.id)
            .limit(500)
            .all()
        ]
        if not ids_batch:
            logger.debug(
                "[WRITER] clear_post_processing_data_action: no more segments for post_id=%s",
                post_id,
            )
            break

        db.session.query(Identification).filter(
            Identification.transcript_segment_id.in_(ids_batch)
        ).delete(synchronize_session=False)

        db.session.query(TranscriptSegment).filter(
            TranscriptSegment.id.in_(ids_batch)
        ).delete(synchronize_session=False)

    db.session.query(AudioSegment).filter_by(post_id=post.id).delete()

    # Model calls
    db.session.query(ModelCall).filter_by(post_id=post.id).delete()

    # Processing jobs
    db.session.query(ProcessingJob).filter_by(post_guid=post.guid).delete()

    # Reset post fields
    post.unprocessed_audio_path = None
    post.processed_audio_path = None
    post.duration = None
    post.chapter_data = None
    post.bleep_windows = None
    post.transcript_word_timestamps = None
    post.refined_ad_boundaries = None
    post.refined_ad_boundaries_updated_at = None

    logger.info(
        "[WRITER] clear_post_processing_data_action: completed post_id=%s", post_id
    )

    return {"post_id": post.id}


def clear_post_processing_data_keep_transcript_action(
    params: dict[str, Any],
) -> dict[str, Any]:
    """Clear processing outputs/classification state but preserve transcript rows."""
    post_id = params.get("post_id")
    post = db.session.get(Post, post_id)
    if not post:
        raise ValueError(f"Post {post_id} not found")

    logger.info(
        "[WRITER] clear_post_processing_data_keep_transcript_action: post_id=%s",
        post_id,
    )

    # Remove identifications tied to this post's transcript segments, but keep the
    # transcript segments themselves so the next run can reuse Whisper output.
    total_identifications_deleted = 0
    last_transcript_segment_id = 0
    while True:
        ids_batch = [
            row[0]
            for row in db.session.query(TranscriptSegment.id)
            .filter(
                TranscriptSegment.post_id == post.id,
                TranscriptSegment.id > last_transcript_segment_id,
            )
            .order_by(TranscriptSegment.id.asc())
            .limit(500)
            .all()
        ]
        if not ids_batch:
            logger.debug(
                "[WRITER] clear_post_processing_data_keep_transcript_action: "
                "no transcript segments for post_id=%s",
                post_id,
            )
            break

        deleted = (
            db.session.query(Identification)
            .filter(Identification.transcript_segment_id.in_(ids_batch))
            .delete(synchronize_session=False)
        )
        total_identifications_deleted += int(deleted or 0)
        last_transcript_segment_id = int(ids_batch[-1])

    db.session.query(AudioSegment).filter_by(post_id=post.id).delete(
        synchronize_session=False
    )

    # Keep Whisper model calls so transcription can be reused; drop all others.
    non_whisper_model_calls_deleted = (
        db.session.query(ModelCall)
        .filter(ModelCall.post_id == post.id)
        .filter(~whisper_model_call_filter())
        .delete(synchronize_session=False)
    )

    # Processing jobs should be regenerated for the new run.
    db.session.query(ProcessingJob).filter_by(post_guid=post.guid).delete(
        synchronize_session=False
    )

    # Reset output and most derived processing fields, but preserve transcript/model
    # calls and saved transcript metadata so keep-transcript reprocess can reuse them.
    post.unprocessed_audio_path = None
    post.processed_audio_path = None
    post.duration = None
    post.chapter_data = None
    post.bleep_windows = None
    post.refined_ad_boundaries = None
    post.refined_ad_boundaries_updated_at = None

    logger.info(
        "[WRITER] clear_post_processing_data_keep_transcript_action: completed "
        "post_id=%s identifications_deleted=%s non_whisper_model_calls_deleted=%s",
        post_id,
        total_identifications_deleted,
        int(non_whisper_model_calls_deleted or 0),
    )

    return {"post_id": post.id}


def prepare_post_for_auto_retry_action(params: dict[str, Any]) -> dict[str, Any]:
    """Reset a post so the zero-ads-guard auto-retry job can actually rerun.

    Differs from ``clear_post_processing_data_keep_transcript_action`` in two
    important ways:
    1. **Does not delete existing ProcessingJob rows.** That action would
       wipe the retry job itself (since it's scoped to the same post),
       which would surface as a "Job not found" error the next time the
       worker tried to update its status. We need the retry job preserved
       so the worker can drive it through.
    2. **Deletes the processed audio file on disk** so
       ``_check_existing_processed_audio`` (which also scans disk by
       feed/post title, not just the DB path) returns False on the retry.

    Preserves transcripts and Whisper model calls so the retry doesn't
    re-transcribe (the parse error was downstream of transcription).

    DAI-safety: the **unprocessed** audio file and ``unprocessed_audio_path``
    are intentionally preserved. Dynamic-ad-insertion feeds (Megaphone,
    ART19, etc.) serve different bytes per request, so re-downloading would
    desynchronise the retained transcripts from the new audio. Keeping the
    exact bytes the transcripts were made from is what makes transcript
    reuse safe. The orchestrator separately suppresses
    ``_remove_unprocessed_audio`` on the failed job's finalization so the
    file survives the handoff to the retry job.
    """
    post_id = params.get("post_id")
    post = db.session.get(Post, post_id)
    if not post:
        raise ValueError(f"Post {post_id} not found")

    logger.info("[WRITER] prepare_post_for_auto_retry_action: post_id=%s", post_id)

    # Delete every processed-audio candidate before nulling the DB path so
    # the disk scan inside _check_existing_processed_audio can't resurrect a
    # stale legacy/derived output path. The unprocessed audio is intentionally
    # NOT touched — see docstring.
    post_guid: str = post.guid
    processed_candidates = get_processed_audio_path_candidates(
        processed_audio_path=post.processed_audio_path,
        unprocessed_audio_path=post.unprocessed_audio_path,
        feed_title=getattr(post.feed, "title", None),
        post_title=post.title,
    )
    processed_files_deleted = 0
    for file_path in processed_candidates:
        if not file_path.exists():
            continue
        if not file_path.is_file():
            logger.warning(
                "[WRITER] Skipping non-file processed audio candidate for post %s: %s",
                post_guid,
                file_path,
            )
            continue
        try:
            file_path.unlink()
            processed_files_deleted += 1
            logger.info("[WRITER] Deleted processed audio: %s", file_path)
        except OSError as exc:
            logger.warning(
                "[WRITER] Unable to delete processed audio for post %s at %s: %s",
                post_guid,
                file_path,
                exc,
            )

    # Drop classification output. Re-running the classifier without this
    # leaves stale (possibly empty) identifications around.
    total_identifications_deleted = 0
    last_transcript_segment_id = 0
    while True:
        ids_batch = [
            row[0]
            for row in db.session.query(TranscriptSegment.id)
            .filter(
                TranscriptSegment.post_id == post.id,
                TranscriptSegment.id > last_transcript_segment_id,
            )
            .order_by(TranscriptSegment.id.asc())
            .limit(500)
            .all()
        ]
        if not ids_batch:
            break
        deleted = (
            db.session.query(Identification)
            .filter(Identification.transcript_segment_id.in_(ids_batch))
            .delete(synchronize_session=False)
        )
        total_identifications_deleted += int(deleted or 0)
        last_transcript_segment_id = int(ids_batch[-1])

    # Drop classifier ModelCall rows so the retry actually issues a fresh
    # LLM call instead of reusing the malformed-response artifact.
    non_whisper_model_calls_deleted = (
        db.session.query(ModelCall)
        .filter(ModelCall.post_id == post.id)
        .filter(~whisper_model_call_filter())
        .delete(synchronize_session=False)
    )

    # Reset output fields. Leave transcripts + whisper model calls alone.
    # Also preserve ``unprocessed_audio_path`` (and its file on disk) so the
    # retry can reuse the exact bytes the transcripts were made from — see
    # docstring for the DAI rationale.
    post.processed_audio_path = None
    post.duration = None
    post.chapter_data = None
    post.bleep_windows = None
    post.refined_ad_boundaries = None
    post.refined_ad_boundaries_updated_at = None

    logger.info(
        "[WRITER] prepare_post_for_auto_retry_action: completed post_id=%s "
        "processed_files_deleted=%s identifications_deleted=%s "
        "non_whisper_model_calls_deleted=%s",
        post_id,
        processed_files_deleted,
        total_identifications_deleted,
        int(non_whisper_model_calls_deleted or 0),
    )

    return {"post_id": post.id}


def cleanup_processed_post_action(params: dict[str, Any]) -> dict[str, Any]:
    post_id = params.get("post_id")
    if not post_id:
        raise ValueError("post_id is required")

    post = db.session.get(Post, int(post_id))
    if not post:
        raise ValueError(f"Post {post_id} not found")

    logger.info("[WRITER] cleanup_processed_post_action: post_id=%s", post_id)

    # Remove processing artifacts and dependent rows.
    clear_post_processing_data_action({"post_id": post.id})
    post.whitelisted = False

    recalculate_run_counts(db.session)

    logger.info("[WRITER] cleanup_processed_post_action: completed post_id=%s", post_id)

    return {"post_id": post.id}


def cleanup_processed_post_files_only_action(params: dict[str, Any]) -> dict[str, Any]:
    """Remove audio files but preserve processing metadata."""
    post_id = params.get("post_id")
    if not post_id:
        raise ValueError("post_id is required")
    post = db.session.get(Post, int(post_id))
    if not post:
        raise ValueError(f"Post {post_id} not found")

    logger.info(
        "[WRITER] cleanup_processed_post_files_only_action: post_id=%s", post_id
    )

    # Delete audio files (using same pattern as post_cleanup.py)
    for path_str in [post.unprocessed_audio_path, post.processed_audio_path]:
        if not path_str:
            continue
        try:
            file_path = Path(path_str)
        except Exception:  # noqa: BLE001
            logger.warning("[WRITER] Invalid path for post %s: %s", post.guid, path_str)
            continue
        if not file_path.exists():
            continue
        try:
            file_path.unlink()
            logger.info("[WRITER] Deleted file: %s", file_path)
        except OSError as exc:
            logger.warning("[WRITER] Unable to delete %s: %s", file_path, exc)

    # Clear file paths but preserve duration and other metadata
    post.unprocessed_audio_path = None
    post.processed_audio_path = None
    # Un-whitelist the post (prevents re-queuing for processing)
    post.whitelisted = False

    # DO NOT delete: ModelCall, ProcessingJob, TranscriptSegment, Identification
    # DO NOT null: post.duration

    logger.info(
        "[WRITER] cleanup_processed_post_files_only_action: completed post_id=%s",
        post_id,
    )

    return {"post_id": post.id}
