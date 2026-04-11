import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

# from pytest_mock import MockerFixture


@pytest.mark.skip
def test_remote_transcribe() -> None:
    # import here instead of the toplevel because torch is not installed properly in CI.
    from podcast_processor.transcribe import (
        OpenAIWhisperTranscriber,
    )

    logger = logging.getLogger("global_logger")
    from shared.test_utils import create_standard_test_config

    config = create_standard_test_config().model_dump()

    transcriber = OpenAIWhisperTranscriber(logger, config)

    transcription = transcriber.transcribe("file.mp3")
    assert transcription == []


@pytest.mark.skip
def test_local_transcribe() -> None:
    # import here instead of the toplevel because torch is not installed properly in CI.
    from podcast_processor.transcribe import (
        LocalWhisperTranscriber,
    )

    logger = logging.getLogger("global_logger")
    transcriber = LocalWhisperTranscriber(logger, "base.en")
    transcription = transcriber.transcribe("src/tests/file.mp3")
    assert transcription == []


@pytest.mark.skip
def test_groq_transcribe(mocker: Any) -> None:
    # import here instead of the toplevel because dependencies aren't installed properly in CI.
    from podcast_processor.transcribe import (
        GroqWhisperTranscriber,
    )
    from shared.config import (
        GroqWhisperConfig,
    )

    # Mock the requests call
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "This is a test segment."},
            {"start": 1.0, "end": 2.0, "text": "This is another test segment."},
        ]
    }
    mocker.patch("requests.post", return_value=mock_response)

    # Mock file operations
    mocker.patch("builtins.open", mocker.mock_open(read_data="test audio data"))
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("podcast_processor.audio.split_audio", return_value=[("test.mp3", 0)])
    mocker.patch("shutil.rmtree")

    logger = logging.getLogger("global_logger")
    config = GroqWhisperConfig(
        api_key="test_key", model="whisper-large-v3-turbo", language="en"
    )

    transcriber = GroqWhisperTranscriber(logger, config)
    transcription = transcriber.transcribe("test.mp3")

    assert len(transcription) == 2
    assert transcription[0].text == "This is a test segment."
    assert transcription[1].text == "This is another test segment."


def test_offset() -> None:
    # import here instead of the toplevel because torch is not installed properly in CI.
    from podcast_processor.transcribe import (
        OpenAIWhisperTranscriber,
        Segment,
    )

    assert OpenAIWhisperTranscriber.add_offset_to_segments(
        [Segment(start=12.345, end=45.678, text="hi")],
        123,
    ) == [Segment(start=12.468, end=45.800999999999995, text="hi")]


def test_remote_transcription_request_kwargs_include_diarization_flags() -> None:
    from podcast_processor.transcribe import OpenAIWhisperTranscriber
    from shared.config import RemoteWhisperConfig

    transcriber = OpenAIWhisperTranscriber(
        logging.getLogger("global_logger"),
        RemoteWhisperConfig(
            api_key="test-key",
            diarize=True,
            speaker_embeddings=True,
        ),
    )

    request_kwargs = transcriber.build_transcription_request_kwargs(MagicMock())

    assert request_kwargs["extra_body"] == {
        "align": True,
        "diarize": True,
        "speaker_embeddings": True,
    }


def test_remote_transcription_request_kwargs_match_whisperx_payload_defaults() -> None:
    from podcast_processor.transcribe import OpenAIWhisperTranscriber
    from shared.config import RemoteWhisperConfig

    transcriber = OpenAIWhisperTranscriber(
        logging.getLogger("global_logger"),
        RemoteWhisperConfig(
            api_key="test-key",
            diarize=True,
            speaker_embeddings=False,
        ),
    )

    request_kwargs = transcriber.build_transcription_request_kwargs(MagicMock())

    assert request_kwargs["extra_body"] == {
        "align": True,
        "diarize": True,
    }


def test_remote_transcription_request_kwargs_include_word_timestamps_when_requested() -> (
    None
):
    from podcast_processor.transcribe import OpenAIWhisperTranscriber
    from shared.config import RemoteWhisperConfig

    transcriber = OpenAIWhisperTranscriber(
        logging.getLogger("global_logger"),
        RemoteWhisperConfig(api_key="test-key"),
    )

    request_kwargs = transcriber.build_transcription_request_kwargs(
        MagicMock(),
        include_word_timestamps=True,
    )

    assert request_kwargs["timestamp_granularities"] == ["segment", "word"]
    assert request_kwargs["extra_body"] == {"align": True}


def test_remote_transcription_request_kwargs_omit_diarization_flags_when_disabled() -> (
    None
):
    from podcast_processor.transcribe import OpenAIWhisperTranscriber
    from shared.config import RemoteWhisperConfig

    transcriber = OpenAIWhisperTranscriber(
        logging.getLogger("global_logger"),
        RemoteWhisperConfig(api_key="test-key"),
    )

    request_kwargs = transcriber.build_transcription_request_kwargs(MagicMock())

    assert "extra_body" not in request_kwargs


def test_remote_whisper_config_requires_diarize_for_speaker_embeddings() -> None:
    from shared.config import RemoteWhisperConfig

    with pytest.raises(ValidationError):
        RemoteWhisperConfig(
            api_key="test-key",
            diarize=False,
            speaker_embeddings=True,
        )


def test_extract_segments_from_dict_response() -> None:
    from podcast_processor.transcribe import OpenAIWhisperTranscriber, Segment

    segments = OpenAIWhisperTranscriber.extract_segments_from_transcription(
        {
            "segments": [
                {"start": 0.311, "end": 3.815, "text": "Hello"},
                {"start": 4.0, "end": 5.0, "text": "world"},
            ]
        }
    )

    assert segments == [
        Segment(start=0.311, end=3.815, text="Hello"),
        Segment(start=4.0, end=5.0, text="world"),
    ]


def test_extract_segments_from_nested_dict_response() -> None:
    from podcast_processor.transcribe import OpenAIWhisperTranscriber, Segment

    segments = OpenAIWhisperTranscriber.extract_segments_from_transcription(
        {
            "segments": {
                "segments": [
                    {"start": 0.311, "end": 3.815, "text": "Hello"},
                ]
            }
        }
    )

    assert segments == [
        Segment(start=0.311, end=3.815, text="Hello"),
    ]


def test_extract_segments_from_dict_response_preserves_speaker_labels() -> None:
    from podcast_processor.transcribe import OpenAIWhisperTranscriber, Segment

    segments = OpenAIWhisperTranscriber.extract_segments_from_transcription(
        {
            "segments": [
                {
                    "start": 0.311,
                    "end": 3.815,
                    "text": "Hello",
                    "speaker": "SPEAKER_00",
                },
                {
                    "start": 4.0,
                    "end": 5.0,
                    "text": "world",
                    "speaker_label": "SPEAKER_01",
                },
            ]
        }
    )

    assert segments == [
        Segment(start=0.311, end=3.815, text="Hello", speaker_label="SPEAKER_00"),
        Segment(start=4.0, end=5.0, text="world", speaker_label="SPEAKER_01"),
    ]


def test_extract_segments_from_dict_response_preserves_word_timestamps() -> None:
    from podcast_processor.transcribe import (
        OpenAIWhisperTranscriber,
        Segment,
        WordTimestamp,
    )

    segments = OpenAIWhisperTranscriber.extract_segments_from_transcription(
        {
            "segments": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Hello world",
                    "words": [
                        {
                            "word": "Hello",
                            "start": 0.0,
                            "end": 0.4,
                            "score": 0.98,
                        },
                        {
                            "word": "world",
                            "start": 0.41,
                            "end": 1.0,
                            "score": 0.97,
                        },
                    ],
                }
            ]
        }
    )

    assert segments == [
        Segment(
            start=0.0,
            end=1.0,
            text="Hello world",
            words=[
                WordTimestamp(word="Hello", start=0.0, end=0.4, score=0.98),
                WordTimestamp(word="world", start=0.41, end=1.0, score=0.97),
            ],
        )
    ]


def test_extract_segments_from_sdk_like_response() -> None:
    from podcast_processor.transcribe import OpenAIWhisperTranscriber, Segment

    segments = OpenAIWhisperTranscriber.extract_segments_from_transcription(
        SimpleNamespace(
            segments=[
                SimpleNamespace(start=1.25, end=2.5, text="typed response"),
            ]
        )
    )

    assert segments == [
        Segment(start=1.25, end=2.5, text="typed response"),
    ]


def test_offset_updates_word_timestamps() -> None:
    from podcast_processor.transcribe import (
        OpenAIWhisperTranscriber,
        Segment,
        WordTimestamp,
    )

    shifted = OpenAIWhisperTranscriber.add_offset_to_segments(
        [
            Segment(
                start=1.0,
                end=2.0,
                text="bad word",
                words=[WordTimestamp(word="bad", start=1.0, end=1.2, score=0.9)],
            )
        ],
        500,
    )

    assert shifted == [
        Segment(
            start=1.5,
            end=2.5,
            text="bad word",
            words=[WordTimestamp(word="bad", start=1.5, end=1.7, score=0.9)],
        )
    ]
