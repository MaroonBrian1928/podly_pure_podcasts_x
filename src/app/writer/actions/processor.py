from __future__ import annotations

import json
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.memory_pressure import collect_incremental
from app.models import AudioSegment, Identification, ModelCall, Post, TranscriptSegment
from app.writer.batching import (
    batch_count_for,
    get_writer_batch_size,
    iter_writer_batches,
)
from shared.processing_paths import get_base_podcast_data_dir, get_instance_dir
from shared.rust_sidecar import normalize_word_timestamps_artifact


def upsert_model_call_action(params: dict[str, Any]) -> dict[str, Any]:
    post_id = params.get("post_id")
    model_name = params.get("model_name")
    first_seq = params.get("first_segment_sequence_num")
    last_seq = params.get("last_segment_sequence_num")
    prompt = params.get("prompt")

    if post_id is None or model_name is None or first_seq is None or last_seq is None:
        raise ValueError(
            "post_id, model_name, first_segment_sequence_num, last_segment_sequence_num are required"
        )
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("prompt is required")

    def _query() -> ModelCall | None:
        return (
            db.session.query(ModelCall)
            .filter_by(
                post_id=int(post_id),
                model_name=str(model_name),
                first_segment_sequence_num=int(first_seq),
                last_segment_sequence_num=int(last_seq),
            )
            .order_by(ModelCall.timestamp.desc())
            .first()
        )

    model_call = _query()
    if model_call is None:
        model_call = ModelCall(
            post_id=int(post_id),
            first_segment_sequence_num=int(first_seq),
            last_segment_sequence_num=int(last_seq),
            model_name=str(model_name),
            prompt=str(prompt),
            status="pending",
            timestamp=datetime.now(UTC).replace(tzinfo=None),
            retry_attempts=0,
            error_message=None,
            response=None,
        )
        db.session.add(model_call)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            model_call = _query()
            if model_call is None:
                raise

    # Reset rows the next run is allowed to re-attempt: previously aborted
    # (pending, retrying, failed_retries) or explicitly cancelled by a
    # superseding job. Without these here, the next upsert of the same chunk
    # would find the row, leave its status alone, and the classifier would
    # immediately re-call the LLM with the wrong carried-over error_message
    # visible in the UI.
    if model_call.status in ["pending", "retrying", "failed_retries", "cancelled"]:
        model_call.status = "pending"
        model_call.prompt = str(prompt)
        model_call.retry_attempts = 0
        model_call.error_message = None
        model_call.response = None

    db.session.flush()
    return {"model_call_id": int(model_call.id)}


def delete_model_calls_for_post_by_model_name_action(
    params: dict[str, Any],
) -> dict[str, Any]:
    """Delete every ModelCall row for ``(post_id, model_name)`` regardless of
    its segment range.

    The unique index on ``(post_id, first_segment_sequence_num,
    last_segment_sequence_num, model_name)`` makes the INA flow brittle on
    re-processing: a prior successful run leaves a row keyed at the *real*
    segment count, but the next run's placeholder is keyed at ``(0, 0)``.
    The final UPDATE then collides with the old row. Clearing the
    name-scoped rows up-front makes the path idempotent.
    """
    post_id = params.get("post_id")
    model_name = params.get("model_name")
    if post_id is None or not model_name:
        raise ValueError("post_id and model_name are required")

    deleted = (
        db.session.query(ModelCall)
        .filter_by(post_id=int(post_id), model_name=str(model_name))
        .delete(synchronize_session=False)
    )
    db.session.flush()
    return {"deleted": int(deleted or 0)}


def upsert_whisper_model_call_action(params: dict[str, Any]) -> dict[str, Any]:
    post_id = params.get("post_id")
    model_name = params.get("model_name")
    first_seq = params.get("first_segment_sequence_num", 0)
    last_seq = params.get("last_segment_sequence_num", -1)
    prompt = params.get("prompt") or "Whisper transcription job"

    if post_id is None or model_name is None:
        raise ValueError("post_id and model_name are required")

    reset_fields: dict[str, Any] = params.get("reset_fields") or {
        "status": "pending",
        "prompt": "Whisper transcription job",
        "retry_attempts": 0,
        "error_message": None,
        "response": None,
    }

    def _query() -> ModelCall | None:
        return (
            db.session.query(ModelCall)
            .filter_by(
                post_id=int(post_id),
                model_name=str(model_name),
                first_segment_sequence_num=int(first_seq),
                last_segment_sequence_num=int(last_seq),
            )
            .order_by(ModelCall.timestamp.desc())
            .first()
        )

    model_call = _query()
    if model_call is None:
        model_call = ModelCall(
            post_id=int(post_id),
            model_name=str(model_name),
            first_segment_sequence_num=int(first_seq),
            last_segment_sequence_num=int(last_seq),
            prompt=str(prompt),
            status=str(reset_fields.get("status") or "pending"),
            retry_attempts=int(reset_fields.get("retry_attempts") or 0),
            error_message=reset_fields.get("error_message"),
            response=reset_fields.get("response"),
            timestamp=datetime.now(UTC).replace(tzinfo=None),
        )
        db.session.add(model_call)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            model_call = _query()
            if model_call is None:
                raise

    for k, v in reset_fields.items():
        if hasattr(model_call, k):
            setattr(model_call, k, v)

    db.session.flush()
    return {"model_call_id": int(model_call.id)}


def _normalize_segments_payload(
    segments: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        speaker_label = seg.get("speaker_label")
        normalized.append(
            {
                "post_id": int(seg["post_id"]),
                "sequence_num": int(seg["sequence_num"]),
                "start_time": float(seg["start_time"]),
                "end_time": float(seg["end_time"]),
                "text": str(seg["text"]),
                "speaker_label": (
                    str(speaker_label) if speaker_label is not None else None
                ),
            }
        )
    return normalized


def _normalize_transcript_word_timestamps_payload(
    payload: Any,
) -> list[dict[str, Any]] | None:
    if not isinstance(payload, list):
        return None

    normalized_segments: list[dict[str, Any]] = []
    for segment_payload in payload:
        if not isinstance(segment_payload, dict):
            continue

        sequence_num = segment_payload.get("sequence_num")
        words = segment_payload.get("words")
        if sequence_num is None or not isinstance(words, list):
            continue

        try:
            sequence_num_i = int(sequence_num)
        except Exception:  # noqa: BLE001
            continue

        normalized_words: list[dict[str, Any]] = []
        for word_payload in words:
            if not isinstance(word_payload, dict):
                continue

            raw_word = word_payload.get("word")
            raw_start = word_payload.get("start")
            raw_end = word_payload.get("end")
            if raw_word is None or raw_start is None or raw_end is None:
                continue

            try:
                start_f = float(raw_start)
                end_f = float(raw_end)
            except Exception:  # noqa: BLE001
                continue
            if end_f < start_f:
                continue

            raw_score = word_payload.get("score")
            normalized_words.append(
                {
                    "word": str(raw_word),
                    "start": start_f,
                    "end": end_f,
                    "score": (float(raw_score) if raw_score is not None else None),
                }
            )

        if normalized_words:
            normalized_segments.append(
                {
                    "sequence_num": sequence_num_i,
                    "words": normalized_words,
                }
            )

    return normalized_segments or None


def replace_transcription_action(params: dict[str, Any]) -> dict[str, Any]:
    post_id = params.get("post_id")
    segments = params.get("segments")
    model_call_id = params.get("model_call_id")
    transcript_word_timestamps = _normalize_transcript_word_timestamps_payload(
        params.get("transcript_word_timestamps")
    )

    if post_id is None:
        raise ValueError("post_id is required")
    if not isinstance(segments, list):
        raise ValueError("segments must be a list")

    start_result = start_transcription_replace_action(
        {"post_id": post_id, "model_call_id": model_call_id}
    )
    post_id_i = int(start_result["post_id"])

    segment_count = insert_transcript_segments_action(
        {"post_id": post_id_i, "segments": segments}
    )["inserted"]

    finish_transcription_replace_action(
        {
            "post_id": post_id_i,
            "model_call_id": model_call_id,
            "segment_count": segment_count,
            "transcript_word_timestamps": transcript_word_timestamps,
        }
    )

    db.session.flush()
    return {"post_id": post_id_i, "segment_count": int(segment_count)}


def start_transcription_replace_action(params: dict[str, Any]) -> dict[str, Any]:
    post_id = params.get("post_id")
    model_call_id = params.get("model_call_id")

    if post_id is None:
        raise ValueError("post_id is required")

    post_id_i = int(post_id)
    post = db.session.get(Post, post_id_i)
    if post is None:
        raise ValueError(f"Post {post_id_i} not found")

    seg_ids = [
        row[0]
        for row in db.session.query(TranscriptSegment.id)
        .filter(TranscriptSegment.post_id == post_id_i)
        .all()
    ]
    if seg_ids:
        db.session.query(Identification).filter(
            Identification.transcript_segment_id.in_(seg_ids)
        ).delete(synchronize_session=False)

    db.session.query(TranscriptSegment).filter(
        TranscriptSegment.post_id == post_id_i
    ).delete(synchronize_session=False)

    post.transcript_word_timestamps = None

    if model_call_id is not None:
        mc = db.session.get(ModelCall, int(model_call_id))
        if mc is not None:
            mc.first_segment_sequence_num = 0
            mc.last_segment_sequence_num = -1
            mc.response = None
            mc.status = "pending"
            mc.error_message = None

    db.session.flush()
    return {"post_id": post_id_i, "deleted_segments": len(seg_ids)}


def insert_transcript_segments_action(params: dict[str, Any]) -> dict[str, Any]:
    post_id = params.get("post_id")
    segments = params.get("segments")

    if post_id is None:
        raise ValueError("post_id is required")
    if not isinstance(segments, list):
        raise ValueError("segments must be a list")

    post_id_i = int(post_id)
    if db.session.get(Post, post_id_i) is None:
        raise ValueError(f"Post {post_id_i} not found")

    payload = []
    for i, raw_seg in enumerate(segments):
        if not isinstance(raw_seg, dict):
            continue
        seg = cast(dict[str, Any], raw_seg)
        speaker_label = seg.get("speaker_label")
        payload.append(
            {
                "post_id": post_id_i,
                "sequence_num": int(seg.get("sequence_num", i)),
                "start_time": float(seg["start_time"]),
                "end_time": float(seg["end_time"]),
                "text": str(seg["text"]),
                "speaker_label": (
                    str(speaker_label) if speaker_label is not None else None
                ),
            }
        )

    batch_size = get_writer_batch_size()
    total_batches = batch_count_for(len(payload), batch_size=batch_size)
    inserted = 0
    for batch_index, batch in enumerate(
        iter_writer_batches(payload, batch_size=batch_size), start=1
    ):
        db.session.execute(sqlite_insert(TranscriptSegment).values(list(batch)))
        inserted += len(batch)
        collect_incremental(
            f"insert_transcript_segments batch {batch_index}/{total_batches}"
        )

    db.session.flush()
    return {"post_id": post_id_i, "inserted": inserted}


def finish_transcription_replace_action(params: dict[str, Any]) -> dict[str, Any]:
    post_id = params.get("post_id")
    model_call_id = params.get("model_call_id")
    segment_count = int(params.get("segment_count") or 0)
    transcript_word_timestamps = _normalize_transcript_word_timestamps_payload(
        params.get("transcript_word_timestamps")
    )

    if post_id is None:
        raise ValueError("post_id is required")

    post_id_i = int(post_id)
    post = db.session.get(Post, post_id_i)
    if post is None:
        raise ValueError(f"Post {post_id_i} not found")

    post.transcript_word_timestamps = transcript_word_timestamps

    if model_call_id is not None:
        mc = db.session.get(ModelCall, int(model_call_id))
        if mc is not None:
            mc.first_segment_sequence_num = 0
            mc.last_segment_sequence_num = segment_count - 1
            mc.response = f"{segment_count} segments transcribed."
            mc.status = "success"
            mc.error_message = None

    db.session.flush()
    return {"post_id": post_id_i, "segment_count": segment_count}


def finish_transcription_replace_from_artifact_action(
    params: dict[str, Any],
) -> dict[str, Any]:
    post_id = params.get("post_id")
    model_call_id = params.get("model_call_id")
    segment_count = int(params.get("segment_count") or 0)
    artifact_path = params.get("artifact_path")

    if post_id is None:
        raise ValueError("post_id is required")
    if not isinstance(artifact_path, str):
        raise ValueError("artifact_path is required")

    artifact = _validate_transcript_artifact_path(Path(artifact_path))
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".normalized.json",
        delete=False,
    ) as temp_file:
        normalized_path = Path(temp_file.name)

    try:
        transcript_word_timestamps: Any
        if normalize_word_timestamps_artifact(artifact, normalized_path):
            transcript_word_timestamps = json.loads(normalized_path.read_text())
        else:
            transcript_word_timestamps = _normalize_transcript_word_timestamps_payload(
                json.loads(artifact.read_text())
            )
    finally:
        normalized_path.unlink(missing_ok=True)

    return finish_transcription_replace_action(
        {
            "post_id": post_id,
            "model_call_id": model_call_id,
            "segment_count": segment_count,
            "transcript_word_timestamps": transcript_word_timestamps,
        }
    )


def _validate_transcript_artifact_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    allowed_roots = [
        get_instance_dir().expanduser().resolve(),
        get_base_podcast_data_dir().expanduser().resolve(),
    ]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise ValueError("artifact_path must be under the Podly instance data root")
    if not resolved.is_file():
        raise ValueError("artifact_path must point to an existing file")
    return resolved


def mark_model_call_failed_action(params: dict[str, Any]) -> dict[str, Any]:
    model_call_id = params.get("model_call_id")
    error_message = params.get("error_message")
    status = params.get("status", "failed_permanent")

    if model_call_id is None:
        raise ValueError("model_call_id is required")

    mc = db.session.get(ModelCall, int(model_call_id))
    if mc is None:
        return {"updated": False}

    mc.status = str(status)
    mc.error_message = str(error_message) if error_message is not None else None
    db.session.flush()
    return {"updated": True, "model_call_id": int(mc.id)}


def insert_identifications_action(params: dict[str, Any]) -> dict[str, Any]:
    identifications = params.get("identifications")
    if not isinstance(identifications, list):
        raise ValueError("identifications must be a list")

    values = []
    for ident in identifications:
        if not isinstance(ident, dict):
            continue
        values.append(
            {
                "transcript_segment_id": int(ident["transcript_segment_id"]),
                "model_call_id": int(ident["model_call_id"]),
                "label": str(ident.get("label") or "ad"),
                "confidence": ident.get("confidence"),
            }
        )

    if not values:
        return {"inserted": 0}

    inserted = 0
    batch_size = get_writer_batch_size()
    total_batches = batch_count_for(len(values), batch_size=batch_size)
    for batch_index, batch in enumerate(
        iter_writer_batches(values, batch_size=batch_size), start=1
    ):
        stmt = (
            sqlite_insert(Identification).values(list(batch)).prefix_with("OR IGNORE")
        )
        result = db.session.execute(stmt)
        inserted += int(getattr(result, "rowcount", 0) or 0)
        collect_incremental(
            f"insert_identifications batch {batch_index}/{total_batches}"
        )
    db.session.flush()
    return {"inserted": inserted}


def replace_identifications_action(params: dict[str, Any]) -> dict[str, Any]:
    delete_ids = params.get("delete_ids") or []
    new_identifications = params.get("new_identifications") or []

    if not isinstance(delete_ids, list) or not isinstance(new_identifications, list):
        raise ValueError("delete_ids and new_identifications must be lists")

    if delete_ids:
        db.session.query(Identification).filter(
            Identification.id.in_([int(i) for i in delete_ids])
        ).delete(synchronize_session=False)

    inserted = insert_identifications_action(
        {"identifications": new_identifications}
    ).get("inserted", 0)

    db.session.flush()
    return {"deleted": len(delete_ids), "inserted": int(inserted)}


def replace_audio_segments_action(params: dict[str, Any]) -> dict[str, Any]:
    post_id = params.get("post_id")
    segments = params.get("segments")
    model_call_id = params.get("model_call_id")

    if post_id is None:
        raise ValueError("post_id is required")
    if not isinstance(segments, list):
        raise ValueError("segments must be a list")

    post_id_i = int(post_id)
    post = db.session.get(Post, post_id_i)
    if post is None:
        raise ValueError(f"Post {post_id_i} not found")

    db.session.query(AudioSegment).filter(AudioSegment.post_id == post_id_i).delete(
        synchronize_session=False
    )

    payload: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue

        try:
            start_time = float(seg["start_time"])
            end_time = float(seg["end_time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "audio segments require numeric start_time and end_time"
            ) from exc

        if end_time <= start_time:
            continue

        row: dict[str, Any] = {
            "post_id": post_id_i,
            "start_time": start_time,
            "end_time": end_time,
            "label": str(seg["label"]),
        }
        if model_call_id is not None:
            row["model_call_id"] = int(model_call_id)
        payload.append(row)

    if payload:
        batch_size = get_writer_batch_size()
        total_batches = batch_count_for(len(payload), batch_size=batch_size)
        for batch_index, batch in enumerate(
            iter_writer_batches(payload, batch_size=batch_size), start=1
        ):
            db.session.execute(sqlite_insert(AudioSegment).values(list(batch)))
            collect_incremental(
                f"replace_audio_segments batch {batch_index}/{total_batches}"
            )

    db.session.flush()
    return {"post_id": post_id_i, "segment_count": len(payload)}
