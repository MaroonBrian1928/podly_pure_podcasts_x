from datetime import UTC, datetime

from app.extensions import db
from app.models import (
    AudioSegment,
    Feed,
    Identification,
    ModelCall,
    Post,
    ProcessingJob,
    TranscriptSegment,
)
from app.writer.actions.cleanup import (
    clear_post_processing_data_action,
    clear_post_processing_data_keep_transcript_action,
)


def test_clear_post_processing_data_action_clears_chapter_data(app) -> None:
    with app.app_context():
        feed = Feed(
            title="Test Feed",
            description="Test Description",
            author="Test Author",
            rss_url="https://example.com/feed.xml",
        )
        db.session.add(feed)
        db.session.commit()

        post = Post(
            guid="cleanup-test-guid",
            title="Cleanup Test Episode",
            download_url="https://example.com/episode.mp3",
            feed_id=feed.id,
            unprocessed_audio_path="/tmp/in.mp3",
            processed_audio_path="/tmp/out.mp3",
            duration=123,
            chapter_data='{"chapter_source":"transcript","chapters_for_output":[]}',
            transcript_word_timestamps=[
                {
                    "sequence_num": 0,
                    "words": [{"word": "hello", "start": 0.0, "end": 0.5}],
                }
            ],
        )
        db.session.add(post)
        db.session.commit()
        db.session.add(
            AudioSegment(
                post_id=post.id,
                start_time=0.0,
                end_time=2.0,
                label="music",
            )
        )
        db.session.commit()

        result = clear_post_processing_data_action({"post_id": post.id})
        db.session.commit()
        db.session.refresh(post)

        assert result == {"post_id": post.id}
        assert post.unprocessed_audio_path is None
        assert post.processed_audio_path is None
        assert post.duration is None
        assert post.chapter_data is None
        assert post.transcript_word_timestamps is None
        assert AudioSegment.query.filter_by(post_id=post.id).count() == 0


def test_clear_post_processing_data_keep_transcript_preserves_transcript(app) -> None:
    with app.app_context():
        feed = Feed(
            title="Test Feed",
            description="Test Description",
            author="Test Author",
            rss_url="https://example.com/feed.xml",
        )
        db.session.add(feed)
        db.session.commit()

        post = Post(
            guid="cleanup-keep-transcript-guid",
            title="Cleanup Keep Transcript Episode",
            download_url="https://example.com/episode.mp3",
            feed_id=feed.id,
            unprocessed_audio_path="/tmp/in.mp3",
            processed_audio_path="/tmp/out.mp3",
            duration=321,
            chapter_data='{"chapter_source":"transcript","chapters_for_output":[]}',
            bleep_windows=[{"start_time": 1.25, "end_time": 1.75}],
            transcript_word_timestamps=[
                {
                    "sequence_num": 0,
                    "words": [{"word": "hello", "start": 0.0, "end": 0.5}],
                }
            ],
            refined_ad_boundaries=[{"start": 1.0, "end": 2.0}],
            refined_ad_boundaries_updated_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db.session.add(post)
        db.session.commit()
        db.session.add(
            AudioSegment(
                post_id=post.id,
                start_time=2.0,
                end_time=4.0,
                label="noise",
            )
        )
        db.session.commit()

        seg = TranscriptSegment(
            post_id=post.id,
            sequence_num=0,
            start_time=0.0,
            end_time=5.0,
            text="hello",
        )
        db.session.add(seg)
        db.session.commit()

        whisper_call = ModelCall(
            post_id=post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="groq_whisper-large-v3-turbo",
            prompt="Whisper transcription job",
            status="success",
        )
        local_whisper_call = ModelCall(
            post_id=post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="local_base.en",
            prompt="Whisper transcription job",
            status="success",
        )
        llm_call = ModelCall(
            post_id=post.id,
            first_segment_sequence_num=0,
            last_segment_sequence_num=0,
            model_name="groq/openai/gpt-oss-120b",
            prompt="Classify ads",
            status="success",
        )
        db.session.add(whisper_call)
        db.session.add(local_whisper_call)
        db.session.add(llm_call)
        db.session.commit()

        ident = Identification(
            transcript_segment_id=seg.id,
            model_call_id=llm_call.id,
            label="ad",
            confidence=0.9,
        )
        job = ProcessingJob(post_guid=post.guid, status="completed")
        db.session.add(ident)
        db.session.add(job)
        db.session.commit()

        result = clear_post_processing_data_keep_transcript_action({"post_id": post.id})
        db.session.commit()
        db.session.refresh(post)

        assert result == {"post_id": post.id}
        assert post.unprocessed_audio_path is None
        assert post.processed_audio_path is None
        assert post.duration is None
        assert post.chapter_data is None
        assert post.bleep_windows == [{"start_time": 1.25, "end_time": 1.75}]
        assert post.transcript_word_timestamps == [
            {
                "sequence_num": 0,
                "words": [{"word": "hello", "start": 0.0, "end": 0.5}],
            }
        ]
        assert post.refined_ad_boundaries is None
        assert post.refined_ad_boundaries_updated_at is None

        assert TranscriptSegment.query.filter_by(post_id=post.id).count() == 1
        assert AudioSegment.query.filter_by(post_id=post.id).count() == 0
        assert (
            ModelCall.query.filter_by(
                post_id=post.id,
                model_name="groq_whisper-large-v3-turbo",
            ).count()
            == 1
        )
        assert (
            ModelCall.query.filter_by(
                post_id=post.id,
                model_name="local_base.en",
            ).count()
            == 1
        )
        assert (
            ModelCall.query.filter_by(
                post_id=post.id,
                model_name="groq/openai/gpt-oss-120b",
            ).count()
            == 0
        )
        assert Identification.query.count() == 0
        assert ProcessingJob.query.filter_by(post_guid=post.guid).count() == 0
