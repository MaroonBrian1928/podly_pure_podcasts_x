from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Identification, ModelCall, Post, TranscriptSegment


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

    # Match prior behavior: reset only when pending/failed_retries.
    if model_call.status in ["pending", "failed_retries"]:
        model_call.status = "pending"
        model_call.prompt = str(prompt)
        model_call.retry_attempts = 0
        model_call.error_message = None
        model_call.response = None

    db.session.flush()
    return {"model_call_id": int(model_call.id)}


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

    payload = []
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            continue
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

    if payload:
        db.session.execute(sqlite_insert(TranscriptSegment).values(payload))

    post.transcript_word_timestamps = transcript_word_timestamps

    if model_call_id is not None:
        mc = db.session.get(ModelCall, int(model_call_id))
        if mc is not None:
            mc.first_segment_sequence_num = 0
            mc.last_segment_sequence_num = len(payload) - 1
            mc.response = f"{len(payload)} segments transcribed."
            mc.status = "success"
            mc.error_message = None

    db.session.flush()
    return {"post_id": post_id_i, "segment_count": len(payload)}


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

    stmt = sqlite_insert(Identification).values(values).prefix_with("OR IGNORE")
    result = db.session.execute(stmt)
    db.session.flush()
    return {"inserted": int(getattr(result, "rowcount", 0) or 0)}


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
