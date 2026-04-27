from __future__ import annotations

from app.extensions import db
from app.models import (
    AudioSegment,
    Feed,
    Identification,
    ModelCall,
    Post,
    TranscriptSegment,
)
from app.writer.actions.processor import (
    finish_transcription_replace_action,
    insert_transcript_segments_action,
    replace_audio_segments_action,
    start_transcription_replace_action,
)


def _create_post() -> Post:
    feed = Feed(title="Writer Processor Feed", rss_url="https://example.com/writer.xml")
    db.session.add(feed)
    db.session.flush()
    post = Post(
        feed_id=feed.id,
        guid="writer-processor-guid",
        download_url="https://example.com/writer.mp3",
        title="Writer Processor Episode",
    )
    db.session.add(post)
    db.session.commit()
    return post


def _create_model_call(post: Post, status: str = "success") -> ModelCall:
    model_call = ModelCall(
        post_id=post.id,
        first_segment_sequence_num=0,
        last_segment_sequence_num=0,
        model_name="test-whisper",
        prompt="Whisper transcription job",
        status=status,
        response="old",
    )
    db.session.add(model_call)
    db.session.commit()
    return model_call


def test_transcription_replace_actions_clear_insert_and_finish(
    app, monkeypatch
) -> None:
    monkeypatch.setenv("PODLY_WRITER_BATCH_SIZE", "1")
    post = _create_post()
    model_call = _create_model_call(post)
    old_segment = TranscriptSegment(
        post_id=post.id,
        sequence_num=0,
        start_time=0.0,
        end_time=1.0,
        text="old",
    )
    db.session.add(old_segment)
    db.session.commit()
    db.session.add(
        Identification(
            transcript_segment_id=old_segment.id,
            model_call_id=model_call.id,
            label="ad",
            confidence=0.9,
        )
    )
    db.session.commit()

    start_result = start_transcription_replace_action(
        {"post_id": post.id, "model_call_id": model_call.id}
    )
    db.session.commit()

    assert start_result == {"post_id": post.id, "deleted_segments": 1}
    assert TranscriptSegment.query.filter_by(post_id=post.id).count() == 0
    assert Identification.query.count() == 0
    db.session.refresh(model_call)
    assert model_call.status == "pending"
    assert model_call.last_segment_sequence_num == -1

    insert_result = insert_transcript_segments_action(
        {
            "post_id": post.id,
            "segments": [
                {"sequence_num": 0, "start_time": 0.0, "end_time": 1.0, "text": "a"},
                {"sequence_num": 1, "start_time": 1.0, "end_time": 2.0, "text": "b"},
            ],
        }
    )
    db.session.commit()

    assert insert_result == {"post_id": post.id, "inserted": 2}
    stored = TranscriptSegment.query.filter_by(post_id=post.id).order_by(
        TranscriptSegment.sequence_num
    )
    assert [segment.text for segment in stored] == ["a", "b"]

    finish_result = finish_transcription_replace_action(
        {
            "post_id": post.id,
            "model_call_id": model_call.id,
            "segment_count": 2,
            "transcript_word_timestamps": [
                {"sequence_num": 0, "words": [{"word": "a", "start": 0, "end": 1}]}
            ],
        }
    )
    db.session.commit()
    db.session.refresh(model_call)
    db.session.refresh(post)

    assert finish_result == {"post_id": post.id, "segment_count": 2}
    assert model_call.status == "success"
    assert model_call.last_segment_sequence_num == 1
    assert post.transcript_word_timestamps == [
        {
            "sequence_num": 0,
            "words": [{"word": "a", "start": 0.0, "end": 1.0, "score": None}],
        }
    ]


def test_retry_start_clears_partial_transcript_rows(app) -> None:
    post = _create_post()
    model_call = _create_model_call(post, status="pending")

    insert_transcript_segments_action(
        {
            "post_id": post.id,
            "segments": [
                {
                    "sequence_num": 0,
                    "start_time": 0.0,
                    "end_time": 1.0,
                    "text": "partial",
                }
            ],
        }
    )
    db.session.commit()

    start_transcription_replace_action(
        {"post_id": post.id, "model_call_id": model_call.id}
    )
    db.session.commit()

    assert TranscriptSegment.query.filter_by(post_id=post.id).count() == 0


def test_replace_audio_segments_batches_and_returns_count(app, monkeypatch) -> None:
    monkeypatch.setenv("PODLY_WRITER_BATCH_SIZE", "1")
    post = _create_post()
    model_call = _create_model_call(post)

    result = replace_audio_segments_action(
        {
            "post_id": post.id,
            "model_call_id": model_call.id,
            "segments": [
                {"label": "speech", "start_time": 0.0, "end_time": 1.0},
                {"label": "music", "start_time": 1.0, "end_time": 2.0},
            ],
        }
    )
    db.session.commit()

    assert result == {"post_id": post.id, "segment_count": 2}
    assert AudioSegment.query.filter_by(post_id=post.id).count() == 2
