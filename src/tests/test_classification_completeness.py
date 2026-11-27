"""Ad classification must be complete before an episode is cut or published."""

from __future__ import annotations

import logging
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from jinja2 import Template
from litellm.types.utils import Choices

from app.extensions import db
from app.models import ModelCall, Post, ProcessingJob, TranscriptSegment
from podcast_processor.ad_classifier import (
    AdClassifier,
    ClassificationIncompleteError,
    ClassificationRefusedError,
    ClassifyException,
    InvalidClassificationOutputError,
)
from podcast_processor.podcast_processor import PodcastProcessor, ProcessorException
from podcast_processor.transcribe import OpenAIWhisperTranscriber
from shared.config import Config
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


def _pending_call(config: Config, prompt: str = "prompt") -> ModelCall:
    call = ModelCall(
        post_id=1,
        model_name=config.llm_model,
        prompt=prompt,
        first_segment_sequence_num=0,
        last_segment_sequence_num=1,
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
        _response('{"ad_segments": [', finish_reason="length"),
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
        cut_off = _response('{"ad_segments": [', finish_reason="length")
        with (
            patch("time.sleep"),
            patch("litellm.completion", return_value=cut_off),
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


@pytest.mark.parametrize(
    ("total", "successful", "trusted"),
    [(3, 3, True), (3, 2, False), (0, 0, True)],
)
def test_rediscovered_output_requires_successful_classification(
    config: Config, total: int, successful: int, trusted: bool
) -> None:
    processor = _bare_processor(config)
    counts = SimpleNamespace(total=total, successful=successful)
    with patch.object(
        processor, "_get_llm_classification_model_call_counts", return_value=counts
    ):
        assert (
            processor._rediscovered_output_is_trusted(
                Post(id=1, title="t"), "/tmp/x.mp3"
            )
            is trusted
        )


def test_transcription_without_segments_is_an_error() -> None:
    with pytest.raises(ValueError, match="segments"):
        OpenAIWhisperTranscriber.extract_segments_from_transcription({"text": "hi"})
