"""Ad classification must be complete before an episode is cut or published."""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from jinja2 import Template
from litellm.types.utils import Choices

from app.extensions import db
from app.models import (
    Identification,
    ModelCall,
    Post,
    ProcessingJob,
    TranscriptSegment,
)
from podcast_processor.ad_classifier import (
    AdClassifier,
    ClassificationIncompleteError,
    ClassificationOutputTruncatedError,
    ClassificationRefusedError,
    ClassifyException,
    ClassifyParams,
    InvalidClassificationOutputError,
)
from podcast_processor.podcast_processor import PodcastProcessor, ProcessorException
from podcast_processor.transcribe import OpenAIWhisperTranscriber
from shared.config import Config
from shared.processing_paths import (
    adopts_unrecorded_processed_audio,
    find_existing_processed_audio_path,
)
from shared.test_utils import create_standard_test_config

VALID = '{"ad_segments": [{"segment_offset": 10.0, "confidence": 0.95}]}'


@pytest.fixture
def app() -> Generator[Flask]:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    with app.app_context():
        db.init_app(app)
        db.create_all()
        yield app


@pytest.fixture
def config() -> Config:
    return create_standard_test_config()


def _segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            id=1, post_id=1, sequence_num=0, start_time=0.0, end_time=10.0, text="a"
        ),
        TranscriptSegment(
            id=2, post_id=1, sequence_num=1, start_time=10.0, end_time=20.0, text="b"
        ),
    ]


def _pending_call(
    config: Config, prompt: str = "prompt", first_seq: int = 0, last_seq: int = 1
) -> ModelCall:
    call = ModelCall(
        post_id=1,
        model_name=config.llm_model,
        prompt=prompt,
        first_segment_sequence_num=first_seq,
        last_segment_sequence_num=last_seq,
        status="pending",
    )
    db.session.add(call)
    db.session.commit()
    return call


def _response(content: str | None, finish_reason: str = "stop") -> MagicMock:
    choice = MagicMock(spec=Choices)
    choice.message = MagicMock(content=content)
    choice.finish_reason = finish_reason
    response = MagicMock()
    response.choices = [choice]
    response.usage = None
    return response


def _validator(classifier: AdClassifier) -> Any:
    segments = _segments()
    return lambda content, response=None: classifier._validate_classification_output(
        content, response=response, chunk_segments=segments
    )


@pytest.mark.parametrize(
    "bad",
    [
        _response(""),
        _response(None),
        _response('{"ad_segments": ['),
        _response("{'ad_segments': []} {'ad_segments': [{'segment_offset': 10.0, 'confidence': 0.9}]}"),
        _response("not json"),
        _response('{"ad_segments": []} {"ad_segments": [{"segment_offset": 10.0, "confidence": 0.9}]}'),
        _response('{"ad_segments": [{"segment_offset": 55.0, "confidence": 0.95}]}'),
    ],
)  # fmt: skip
def test_unusable_answers_are_retried_before_success(
    config: Config, app: Flask, bad: MagicMock
) -> None:
    with app.app_context():
        classifier = AdClassifier(config=config, db_session=db.session)
        call = _pending_call(config)
        with (
            patch("time.sleep"),
            patch("litellm.completion", side_effect=[bad, _response(VALID)]) as llm,
        ):
            classifier._call_model(
                model_call_obj=call,
                system_prompt="sys",
                validate=_validator(classifier),
            )

        assert llm.call_count == 2
        stored = db.session.get(ModelCall, call.id)
        assert stored is not None
        assert stored.status == "success"
        assert stored.response == VALID


def test_answers_that_stay_unusable_fail_the_call(config: Config, app: Flask) -> None:
    with app.app_context():
        classifier = AdClassifier(config=config, db_session=db.session)
        call = _pending_call(config)
        empty = _response("")
        with (
            patch("time.sleep"),
            patch("litellm.completion", return_value=empty),
            pytest.raises(InvalidClassificationOutputError),
        ):
            classifier._call_model(
                model_call_obj=call,
                system_prompt="sys",
                validate=_validator(classifier),
            )

        stored = db.session.get(ModelCall, call.id)
        assert stored is not None
        assert stored.status == "failed_retries"
        assert stored.response is None


def test_content_filter_is_not_retried(config: Config, app: Flask) -> None:
    with app.app_context():
        classifier = AdClassifier(config=config, db_session=db.session)
        call = _pending_call(config)
        filtered = _response("", finish_reason="content_filter")
        with (
            patch("litellm.completion", return_value=filtered) as llm,
            pytest.raises(ClassificationRefusedError),
        ):
            classifier._call_model(
                model_call_obj=call,
                system_prompt="sys",
                validate=_validator(classifier),
            )

        assert llm.call_count == 1
        stored = db.session.get(ModelCall, call.id)
        assert stored is not None
        assert stored.status == "failed_permanent"


def test_low_confidence_predictions_need_no_matching_segment(
    config: Config, app: Flask
) -> None:
    with app.app_context():
        classifier = AdClassifier(config=config, db_session=db.session)
        _validator(classifier)(
            '{"ad_segments": [{"segment_offset": 55.0, "confidence": 0.01}]}'
        )


def test_prompt_over_the_token_limit_fails_the_call(config: Config, app: Flask) -> None:
    config.llm_max_input_tokens_per_call = 1
    with app.app_context():
        classifier = AdClassifier(config=config, db_session=db.session)
        call = _pending_call(config, prompt="a prompt longer than one token")
        with (
            patch("litellm.completion") as llm,
            pytest.raises(ClassificationIncompleteError),
        ):
            classifier._call_model(model_call_obj=call, system_prompt="sys")

        llm.assert_not_called()


def test_chunk_without_a_successful_call_fails_classification(
    config: Config, app: Flask
) -> None:
    with app.app_context():
        classifier = AdClassifier(config=config, db_session=db.session)
        call = _pending_call(config)
        call.status = "failed_retries"
        with (
            patch.object(classifier, "_get_or_create_model_call", return_value=call),
            patch.object(classifier, "_perform_llm_call"),
            pytest.raises(ClassificationIncompleteError),
        ):
            classifier._process_chunk(
                chunk_segments=_segments(),
                system_prompt="sys",
                post=Post(id=1, title="t"),
                user_prompt_str="prompt",
            )


@pytest.mark.parametrize(
    ("stored_prompt", "stored_response", "reused"),
    [
        ("prompt", VALID, True),
        ("an older prompt", VALID, False),
        ("prompt", "", False),
        ("prompt", "garbage", False),
    ],
)
def test_stored_success_is_reused_only_for_the_same_valid_answer(
    config: Config,
    app: Flask,
    stored_prompt: str,
    stored_response: str,
    reused: bool,
) -> None:
    with app.app_context():
        classifier = AdClassifier(config=config, db_session=db.session)
        call = _pending_call(config, prompt=stored_prompt)
        call.status = "success"
        call.response = stored_response
        db.session.commit()

        def answer(**_kwargs: Any) -> None:
            call.status = "success"
            call.response = VALID

        with (
            patch.object(classifier, "_get_or_create_model_call", return_value=call),
            patch.object(
                classifier, "_perform_llm_call", side_effect=answer
            ) as perform,
            patch.object(classifier, "_process_successful_response", return_value=[]),
        ):
            classifier._process_chunk(
                chunk_segments=_segments(),
                system_prompt="sys",
                post=Post(id=1, title="t"),
                user_prompt_str="prompt",
            )

        assert perform.called is not reused
        if not reused:
            stored = db.session.get(ModelCall, call.id)
            assert stored is not None
            assert stored.prompt == "prompt"


def test_unparseable_stored_answer_fails_instead_of_counting_as_no_ads(
    config: Config, app: Flask
) -> None:
    with app.app_context():
        classifier = AdClassifier(config=config, db_session=db.session)
        call = _pending_call(config)
        call.response = '{"ad_segments": [{"segment_offset": "x"}]}'
        with pytest.raises(ClassificationIncompleteError):
            classifier._process_successful_response(
                model_call=call, current_chunk_db_segments=_segments()
            )


def test_classify_fails_when_it_cannot_reach_the_end_of_the_transcript(
    config: Config, app: Flask
) -> None:
    with app.app_context():
        classifier = AdClassifier(config=config, db_session=db.session)
        with (
            patch.object(
                classifier, "_step", side_effect=ClassifyException("no progress")
            ),
            pytest.raises(ClassificationIncompleteError),
        ):
            classifier.classify(
                transcript_segments=_segments(),
                system_prompt="sys",
                user_prompt_template=Template(""),
                post=Post(id=1, title="t"),
            )


def _bare_processor(config: Config) -> PodcastProcessor:
    processor = object.__new__(PodcastProcessor)
    processor.config = config
    processor.logger = logging.getLogger("test")
    processor.status_manager = MagicMock()
    processor.ad_classifier = MagicMock()
    return processor


def test_empty_transcript_is_not_published(config: Config) -> None:
    processor = _bare_processor(config)
    classifier = MagicMock()
    processor.ad_classifier = classifier
    with pytest.raises(ProcessorException):
        processor._classify_ad_segments(
            Post(id=1, title="t"), ProcessingJob(id="job"), []
        )
    classifier.classify.assert_not_called()


def test_transcription_without_segments_is_an_error() -> None:
    with pytest.raises(ValueError, match="segments"):
        OpenAIWhisperTranscriber.extract_segments_from_transcription({"text": "hi"})


def test_output_limit_rebuilds_the_chunk_instead_of_resending(
    config: Config, app: Flask
) -> None:
    with app.app_context():
        classifier = AdClassifier(config=config, db_session=db.session)
        call = _pending_call(config)
        cut_off = _response('{"ad_segments": [', finish_reason="length")
        with (
            patch("litellm.completion", return_value=cut_off) as llm,
            pytest.raises(ClassificationOutputTruncatedError),
        ):
            classifier._call_model(
                model_call_obj=call,
                system_prompt="sys",
                validate=_validator(classifier),
            )
        assert llm.call_count == 1

        segments = [
            TranscriptSegment(
                id=index + 1,
                post_id=1,
                sequence_num=index,
                start_time=index * 10.0,
                end_time=index * 10.0 + 10.0,
                text=f"segment {index}",
            )
            for index in range(8)
        ]
        params = ClassifyParams(
            post=Post(id=1, title="t"),
            system_prompt="sys",
            user_prompt_template=Template("{{ transcript }}"),
            num_segments_per_prompt=8,
            max_overlap_segments=0,
        )
        chunk_sizes: list[int] = []

        def process(**kwargs: Any) -> list[TranscriptSegment]:
            chunk_sizes.append(len(kwargs["chunk_segments"]))
            if len(chunk_sizes) == 1:
                raise ClassificationOutputTruncatedError("cut off")
            return []

        with patch.object(classifier, "_process_chunk", side_effect=process):
            consumed, _overlap = classifier._step(params, [], 0, segments)

        assert chunk_sizes == [8, 4]
        assert consumed == 4


def test_single_segment_drops_overlap_to_fit_the_token_limit(
    config: Config, app: Flask
) -> None:
    with app.app_context():
        classifier = AdClassifier(config=config, db_session=db.session)
        segments = _segments()
        fits = {(2,): True, (1, 2): False}

        def validate(prompt: str, _system: str) -> bool:
            return fits[tuple(int(i) for i in prompt.split(","))]

        with (
            patch.object(
                classifier,
                "_generate_user_prompt",
                side_effect=lambda **kw: ",".join(
                    str(s.id) for s in kw["current_chunk_db_segments"]
                ),
            ),
            patch.object(classifier, "_validate_token_limit", side_effect=validate),
        ):
            classifier._adaptive_input_token_limit = 100
            chunk, _prompt, consumed, trimmed = classifier._build_chunk_payload(
                overlap_segments=[segments[0]],
                remaining_segments=[segments[1]],
                total_segments=segments,
                post=Post(id=1, title="t"),
                system_prompt="sys",
                user_prompt_template=Template(""),
                max_new_segments=1,
            )

        assert [s.id for s in chunk] == [2]
        assert consumed == 1
        assert trimmed


def test_replaced_answer_takes_its_ad_marks_with_it(config: Config, app: Flask) -> None:
    with app.app_context():
        classifier = AdClassifier(config=config, db_session=db.session)
        call = _pending_call(config, prompt="an older prompt")
        call.status = "success"
        call.response = VALID
        db.session.add(
            TranscriptSegment(
                id=1, post_id=1, sequence_num=0, start_time=0.0, end_time=10.0, text="a"
            )
        )
        db.session.add(
            Identification(
                transcript_segment_id=1,
                model_call_id=call.id,
                label="ad",
                confidence=0.9,
            )
        )
        db.session.commit()

        assert classifier._stored_response_is_stale(
            call, "prompt", _validator(classifier)
        )
        assert (
            db.session.query(Identification).filter_by(model_call_id=call.id).count()
            == 0
        )


def _segment_at(start: float, end: float) -> TranscriptSegment:
    return TranscriptSegment(
        post_id=1, sequence_num=0, start_time=start, end_time=end, text="x"
    )


@pytest.mark.parametrize(
    ("segments", "duration_ms", "ok"),
    [
        ([(0.0, 1800.0)], 1_800_000, True),
        ([(0.0, 600.0), (1100.0, 1800.0)], 1_800_000, True),
        ([(0.0, 600.0), (1300.0, 1800.0)], 1_800_000, False),
        ([(0.0, 1200.0)], 1_900_000, False),
        ([(700.0, 1800.0)], 1_800_000, False),
    ],
)
def test_transcript_must_cover_the_audio(
    config: Config,
    segments: list[tuple[float, float]],
    duration_ms: int,
    ok: bool,
) -> None:
    processor = _bare_processor(config)
    transcript = [_segment_at(start, end) for start, end in segments]
    with patch(
        "podcast_processor.podcast_processor.get_audio_duration_ms",
        return_value=duration_ms,
    ):
        if ok:
            processor._ensure_transcript_covers_audio(
                Post(id=1, title="t"), transcript, "/tmp/in.mp3"
            )
        else:
            with pytest.raises(ProcessorException):
                processor._ensure_transcript_covers_audio(
                    Post(id=1, title="t"), transcript, "/tmp/in.mp3"
                )


@pytest.mark.parametrize(
    ("strategy", "adopts"),
    [("llm", False), (None, False), ("chapter", True), ("chapter_insert", True)],
)
def test_unrecorded_processed_files_are_adopted_only_without_llm_detection(
    strategy: str | None, adopts: bool
) -> None:
    assert adopts_unrecorded_processed_audio(strategy) is adopts


def test_find_existing_processed_audio_can_ignore_unrecorded_files(
    tmp_path: Any,
) -> None:
    recorded = tmp_path / "recorded.mp3"
    assert (
        find_existing_processed_audio_path(
            processed_audio_path=str(recorded),
            unprocessed_audio_path=str(tmp_path / "in" / "episode.mp3"),
            feed_title="Feed",
            post_title="Episode",
            allow_unrecorded=False,
        )
        is None
    )
    recorded.write_bytes(b"audio")
    assert (
        find_existing_processed_audio_path(
            processed_audio_path=str(recorded),
            unprocessed_audio_path=None,
            feed_title=None,
            post_title=None,
            allow_unrecorded=False,
        )
        == recorded
    )


@pytest.mark.parametrize(
    ("duration_ms", "fails"), [(5_000, False), (45_000, True), (None, True)]
)
def test_long_chunk_without_segments_is_an_error(
    duration_ms: int | None, fails: bool
) -> None:
    from podcast_processor import transcribe

    with patch.object(transcribe, "get_audio_duration_ms", return_value=duration_ms):
        if fails:
            with pytest.raises(ValueError, match="no segments"):
                transcribe.raise_if_chunk_untranscribed("chunk.m4a", [])
        else:
            transcribe.raise_if_chunk_untranscribed("chunk.m4a", [])
        transcribe.raise_if_chunk_untranscribed("chunk.m4a", [object()])


def test_ad_mark_skipped_for_a_replaced_answer_is_restored(
    config: Config, app: Flask
) -> None:
    from podcast_processor.model_output import (
        AdSegmentPrediction,
        AdSegmentPredictionList,
    )

    with app.app_context():
        classifier = AdClassifier(config=config, db_session=db.session)
        segments = _segments()
        for segment in segments:
            db.session.add(segment)
        later = _pending_call(config, prompt="later chunk", first_seq=1, last_seq=2)
        earlier = _pending_call(config, prompt="earlier chunk")
        db.session.add(
            Identification(
                transcript_segment_id=2,
                model_call_id=later.id,
                label="ad",
                confidence=0.9,
            )
        )
        db.session.commit()

        classifier._create_identifications(
            prediction_list=AdSegmentPredictionList(
                ad_segments=[AdSegmentPrediction(segment_offset=10.0, confidence=0.95)]
            ),
            current_chunk_db_segments=segments,
            model_call=earlier,
        )
        db.session.query(Identification).filter_by(model_call_id=later.id).delete()
        db.session.commit()

        classifier._restore_deferred_marks()

        marks = (
            db.session.query(Identification).filter_by(transcript_segment_id=2).all()
        )
        assert [(m.model_call_id, m.label) for m in marks] == [(earlier.id, "ad")]
