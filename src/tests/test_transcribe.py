import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

# from pytest_mock import MockerFixture


@pytest.mark.skip
def test_remote_transcribe() -> None:
    # Import here to keep this skipped integration check out of test collection.
    from podcast_processor.transcribe import (
        OpenAIWhisperTranscriber,
    )
    from shared.config import RemoteWhisperConfig

    logger = logging.getLogger("global_logger")
    config = RemoteWhisperConfig(api_key="test-key")

    transcriber = OpenAIWhisperTranscriber(logger, config)

    transcription = transcriber.transcribe("file.mp3")
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
    # Import here to keep the test focused on the shared offset helper.
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


def test_serialize_segment_word_timestamps_compacts_payload() -> None:
    from podcast_processor.transcribe import (
        Segment,
        WordTimestamp,
        serialize_segment_word_timestamps,
    )

    payload = serialize_segment_word_timestamps(
        [
            Segment(
                start=0.0,
                end=1.0,
                text="Hello world",
                words=[
                    WordTimestamp(word="Hello", start=0.0, end=0.4, score=0.98),
                    WordTimestamp(word="world", start=0.41, end=1.0, score=0.97),
                ],
            ),
            Segment(start=1.0, end=2.0, text="No word timings here"),
        ]
    )

    assert payload == [
        {
            "sequence_num": 0,
            "words": [
                {"word": "Hello", "start": 0.0, "end": 0.4, "score": 0.98},
                {"word": "world", "start": 0.41, "end": 1.0, "score": 0.97},
            ],
        }
    ]


def test_merge_segments_with_saved_word_timestamps_rebuilds_rich_segments() -> None:
    from podcast_processor.transcribe import merge_segments_with_saved_word_timestamps

    merged = merge_segments_with_saved_word_timestamps(
        [
            SimpleNamespace(
                sequence_num=0,
                start_time=0.0,
                end_time=1.0,
                text="Hello world",
                speaker_label="SPEAKER_00",
            ),
            SimpleNamespace(
                sequence_num=1,
                start_time=1.0,
                end_time=2.0,
                text="No timings",
                speaker_label=None,
            ),
        ],
        [
            {
                "sequence_num": 0,
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.4, "score": 0.98},
                    {"word": "world", "start": 0.41, "end": 1.0, "score": 0.97},
                ],
            }
        ],
    )

    assert merged is not None
    assert merged[0].speaker_label == "SPEAKER_00"
    assert [word.word for word in (merged[0].words or [])] == ["Hello", "world"]
    assert merged[1].words is None


def test_non_finite_word_values_never_reach_the_artifact_payload() -> None:
    import json

    from podcast_processor.transcribe import (
        OpenAIWhisperTranscriber,
        serialize_segment_word_timestamps,
    )

    segments = OpenAIWhisperTranscriber.extract_segments_from_transcription(
        {
            "segments": [
                {
                    "start": 0.0,
                    "end": 2.0,
                    "text": "Hello world",
                    "words": [
                        {"word": "Hello", "start": 0.0, "end": 0.5, "score": "nan"},
                        {"word": "world", "start": "inf", "end": 1.0, "score": 0.9},
                    ],
                }
            ]
        }
    )

    payload = serialize_segment_word_timestamps(segments)
    assert payload == [
        {
            "sequence_num": 0,
            "words": [{"word": "Hello", "start": 0.0, "end": 0.5, "score": None}],
        }
    ]
    json.dumps(payload, allow_nan=False)


def _make_groq_transcriber(
    mocker: Any, response_segments: list, response_words: list | None = None
) -> Any:
    from podcast_processor.transcribe import GroqWhisperTranscriber
    from shared.config import GroqWhisperConfig

    mock_client = MagicMock()
    mock_client.audio.transcriptions.create.return_value = SimpleNamespace(
        segments=response_segments, words=response_words
    )
    mocker.patch("podcast_processor.transcribe.Groq", return_value=mock_client)
    logger = logging.getLogger("global_logger")
    config = GroqWhisperConfig(
        api_key="test",
        model="whisper-large-v3-turbo",
    )
    transcriber = GroqWhisperTranscriber(logger, config)
    return transcriber, mock_client


def test_groq_get_segments_for_chunk_requests_word_granularities(mocker: Any) -> None:
    transcriber, mock_client = _make_groq_transcriber(
        mocker, [{"start": 0.0, "end": 1.0, "text": "hi"}]
    )

    transcriber.get_segments_for_chunk("chunk.mp3", include_word_timestamps=True)

    _, kwargs = mock_client.audio.transcriptions.create.call_args
    assert kwargs["timestamp_granularities"] == ["segment", "word"]


def test_groq_get_segments_for_chunk_omits_word_granularities_by_default(
    mocker: Any,
) -> None:
    transcriber, mock_client = _make_groq_transcriber(
        mocker, [{"start": 0.0, "end": 1.0, "text": "hi"}]
    )

    transcriber.get_segments_for_chunk("chunk.mp3")

    _, kwargs = mock_client.audio.transcriptions.create.call_args
    assert "timestamp_granularities" not in kwargs


def test_groq_top_level_words_are_grouped_into_their_segments(mocker: Any) -> None:
    """Groq returns words as one top-level list; segments carry none."""
    from podcast_processor.transcribe import GroqWhisperTranscriber

    transcriber, _ = _make_groq_transcriber(
        mocker,
        [
            {"start": 10.0, "end": 12.0, "text": "hello world"},
            {"start": 12.0, "end": 13.0, "text": "no words here"},
            {"start": 13.0, "end": 14.0, "text": "bye"},
        ],
        [
            {"word": "hello", "start": 10.1, "end": 10.5},
            {"word": "world", "start": 10.6, "end": 11.0},
            {"word": "bye", "start": 13.1, "end": 13.4},
        ],
    )

    segments = transcriber.get_segments_for_chunk(
        "chunk.mp3", include_word_timestamps=True
    )

    assert [[w.word for w in (s.words or [])] for s in segments] == [
        ["hello", "world"],
        [],
        ["bye"],
    ]
    assert segments[1].words is None

    converted = GroqWhisperTranscriber.convert_segments(segments)
    assert [w.word for w in (converted[0].words or [])] == ["hello", "world"]


def test_groq_word_without_start_follows_the_previous_word(mocker: Any) -> None:
    transcriber, _ = _make_groq_transcriber(
        mocker,
        [
            {"start": 0.0, "end": 2.0, "text": "one two"},
            {"start": 2.0, "end": 4.0, "text": "three"},
        ],
        [
            {"word": "one", "start": 0.1, "end": 0.5},
            {"word": "two", "start": None, "end": None},
            {"word": "three", "start": 2.1, "end": 2.5},
        ],
    )

    segments = transcriber.get_segments_for_chunk(
        "chunk.mp3", include_word_timestamps=True
    )

    assert [w.word for w in (segments[0].words or [])] == ["one", "two"]
    assert [w.word for w in (segments[1].words or [])] == ["three"]


def test_groq_words_in_overlapping_gap_and_trailing_positions(mocker: Any) -> None:
    transcriber, _ = _make_groq_transcriber(
        mocker,
        [
            {"start": 0.0, "end": 2.0, "text": "a"},
            {"start": 1.8, "end": 4.0, "text": "b"},
            {"start": 6.0, "end": 7.0, "text": "c"},
        ],
        [
            {"word": "early", "start": 0.5, "end": 0.7},
            {"word": "buy", "start": 1.9, "end": 2.0},
            {"word": "acme", "start": 2.1, "end": 2.4},
            {"word": "gap", "start": 5.0, "end": 5.2},
            {"word": "tail", "start": 9.0, "end": 9.3},
        ],
    )

    segments = transcriber.get_segments_for_chunk(
        "chunk.mp3", include_word_timestamps=True
    )

    assert [[w.word for w in (s.words or [])] for s in segments] == [
        ["early"],
        ["buy", "acme", "gap"],
        ["tail"],
    ]


def test_groq_unsorted_segments_keep_words_with_their_own_segment(mocker: Any) -> None:
    transcriber, _ = _make_groq_transcriber(
        mocker,
        [
            {"start": 5.0, "end": 6.0, "text": "second"},
            {"start": 0.0, "end": 1.0, "text": "first"},
        ],
        [
            {"word": "one", "start": 0.2, "end": 0.4},
            {"word": "two", "start": 5.2, "end": 5.4},
        ],
    )

    segments = transcriber.get_segments_for_chunk(
        "chunk.mp3", include_word_timestamps=True
    )

    assert [[w.word for w in (s.words or [])] for s in segments] == [["two"], ["one"]]


def test_groq_words_without_segments_do_not_crash(mocker: Any) -> None:
    transcriber, _ = _make_groq_transcriber(
        mocker, [], [{"word": "lost", "start": 0.2, "end": 0.4}]
    )

    assert (
        transcriber.get_segments_for_chunk("chunk.mp3", include_word_timestamps=True)
        == []
    )


def test_groq_nested_segment_words_are_still_accepted(mocker: Any) -> None:
    transcriber, _ = _make_groq_transcriber(
        mocker,
        [
            {
                "start": 10.0,
                "end": 12.0,
                "text": "hello",
                "words": [{"word": "hello", "start": 10.1, "end": 10.5}],
            }
        ],
    )

    segments = transcriber.get_segments_for_chunk(
        "chunk.mp3", include_word_timestamps=True
    )

    assert [w.word for w in (segments[0].words or [])] == ["hello"]


def test_groq_add_offset_to_segments_shifts_word_timestamps() -> None:
    from podcast_processor.transcribe import (
        GroqTranscriptionSegment,
        GroqWhisperTranscriber,
        WordTimestamp,
    )

    segments = [
        GroqTranscriptionSegment(
            start=1.0,
            end=2.0,
            text="hi",
            words=[WordTimestamp(word="hi", start=1.1, end=1.5)],
        )
    ]

    shifted = GroqWhisperTranscriber.add_offset_to_segments(segments, 60_000)

    assert shifted[0].start == pytest.approx(61.0)
    assert shifted[0].words is not None
    assert shifted[0].words[0].start == pytest.approx(61.1)
    assert shifted[0].words[0].end == pytest.approx(61.5)
