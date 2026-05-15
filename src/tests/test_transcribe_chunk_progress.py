"""Verify that transcribers invoke ``progress_callback`` once per chunk and
that the PodcastProcessor helper publishes a useful step_name + progress
update on each invocation.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from unittest.mock import MagicMock

from app.models import Post, ProcessingJob
from podcast_processor.podcast_processor import PodcastProcessor


class _StubLogger(logging.Logger):
    def __init__(self) -> None:
        super().__init__("stub", level=logging.CRITICAL + 1)


def test_test_whisper_transcriber_invokes_progress_callback_once() -> None:
    from podcast_processor.transcribe import TestWhisperTranscriber

    calls: list[tuple[int, int]] = []
    TestWhisperTranscriber(_StubLogger()).transcribe(
        "/tmp/audio.mp3",
        progress_callback=lambda done, total: calls.append((done, total)),
    )
    # Test transcriber reports as a single conceptual chunk so callers
    # observe the same shape as the real chunked transcribers.
    assert calls == [(1, 1)]


def test_openai_whisper_transcriber_emits_one_callback_per_chunk(monkeypatch) -> None:
    from podcast_processor import transcribe as transcribe_module
    from podcast_processor.transcribe import OpenAIWhisperTranscriber, Segment

    fake_chunks = [
        ("/tmp/chunk0.mp3", 0),
        ("/tmp/chunk1.mp3", 5000),
        ("/tmp/chunk2.mp3", 10000),
    ]

    monkeypatch.setattr(
        transcribe_module, "split_audio", lambda *args, **kwargs: list(fake_chunks)
    )
    # The teardown rmtree would fail on the synthetic path; stub it out.
    monkeypatch.setattr(transcribe_module.shutil, "rmtree", lambda _path: None)

    transcriber = OpenAIWhisperTranscriber.__new__(OpenAIWhisperTranscriber)
    transcriber.logger = _StubLogger()
    transcriber.config = MagicMock(chunksize_mb=10)

    def fake_get_segments(self, chunk_path, *, include_word_timestamps=False):
        del self, chunk_path, include_word_timestamps
        return [Segment(start=0.0, end=1.0, text="hi")]

    monkeypatch.setattr(
        OpenAIWhisperTranscriber, "get_segments_for_chunk", fake_get_segments
    )

    calls: list[tuple[int, int]] = []
    segments = transcriber.transcribe(
        "/tmp/audio.mp3",
        progress_callback=lambda done, total: calls.append((done, total)),
    )

    assert calls == [(1, 3), (2, 3), (3, 3)]
    # Total segments = one per chunk.
    assert len(segments) == 3


def test_openai_whisper_transcriber_swallows_callback_errors(monkeypatch) -> None:
    """A buggy progress callback must never break the actual transcription."""
    from podcast_processor import transcribe as transcribe_module
    from podcast_processor.transcribe import OpenAIWhisperTranscriber, Segment

    monkeypatch.setattr(
        transcribe_module,
        "split_audio",
        lambda *args, **kwargs: [("/tmp/chunk0.mp3", 0)],
    )
    monkeypatch.setattr(transcribe_module.shutil, "rmtree", lambda _path: None)

    transcriber = OpenAIWhisperTranscriber.__new__(OpenAIWhisperTranscriber)
    transcriber.logger = _StubLogger()
    transcriber.config = MagicMock(chunksize_mb=10)

    monkeypatch.setattr(
        OpenAIWhisperTranscriber,
        "get_segments_for_chunk",
        lambda self, chunk_path, *, include_word_timestamps=False: [
            Segment(start=0.0, end=1.0, text="ok")
        ],
    )

    def explode(_done: int, _total: int) -> None:
        raise RuntimeError("callback exploded")

    # Should not raise even though the callback does.
    segments = transcriber.transcribe(
        "/tmp/audio.mp3",
        progress_callback=explode,
    )
    assert len(segments) == 1


def test_make_transcribe_progress_callback_updates_step_name_and_progress() -> None:
    """The PodcastProcessor helper must publish ``Transcribing audio (chunk
    N/M)`` and interpolate progress within the stage's [base, base+span)
    window."""
    processor = PodcastProcessor.__new__(PodcastProcessor)
    processor.status_manager = MagicMock()
    processor.logger = _StubLogger()

    job = MagicMock(spec=ProcessingJob, id="job-1")
    callback = processor._make_transcribe_progress_callback(
        job, step=2, label="Transcribing audio", progress_base=50.0
    )

    callback(1, 4)
    callback(2, 4)
    callback(4, 4)

    update = processor.status_manager.update_job_status
    assert update.call_count == 3

    first_args = update.call_args_list[0].args
    assert first_args[0] is job
    assert first_args[1] == "running"
    assert first_args[2] == 2
    assert first_args[3] == "Transcribing audio (chunk 1/4)"
    assert abs(first_args[4] - (50.0 + 25.0 * 0.25)) < 0.01

    last_args = update.call_args_list[-1].args
    assert last_args[3] == "Transcribing audio (chunk 4/4)"
    assert abs(last_args[4] - 75.0) < 0.01


def test_make_transcribe_progress_callback_omits_chunk_suffix_for_single_chunk() -> (
    None
):
    processor = PodcastProcessor.__new__(PodcastProcessor)
    processor.status_manager = MagicMock()
    processor.logger = _StubLogger()

    job = MagicMock(spec=ProcessingJob, id="job-2")
    processor._make_transcribe_progress_callback(
        job,
        step=3,
        label="Transcribing audio for profanity bleeping",
        progress_base=75.0,
    )(1, 1)

    args = processor.status_manager.update_job_status.call_args.args
    # Single-chunk transcriptions shouldn't read as "(chunk 1/1)" — that's
    # noise. The label stays clean and progress lands at the stage ceiling.
    assert args[3] == "Transcribing audio for profanity bleeping"
    assert abs(args[4] - 100.0) < 0.01


def test_make_transcribe_progress_callback_tolerates_status_failure() -> None:
    """If the status update raises (e.g. DB hiccup), the chunk loop must
    keep going."""
    processor = PodcastProcessor.__new__(PodcastProcessor)
    processor.status_manager = MagicMock()
    processor.status_manager.update_job_status.side_effect = RuntimeError("db down")
    processor.logger = _StubLogger()

    job = MagicMock(spec=ProcessingJob, id="job-3")
    callback = processor._make_transcribe_progress_callback(
        job, step=2, label="Transcribing audio", progress_base=50.0
    )

    callback(1, 2)  # must not raise
    callback(2, 2)  # must not raise
    assert processor.status_manager.update_job_status.call_count == 2


def test_transcribe_for_processing_forwards_progress_callback() -> None:
    """The processor must hand the chunk-progress callback through to the
    transcription manager so chunk updates can surface on the job."""
    processor = PodcastProcessor.__new__(PodcastProcessor)
    processor.logger = _StubLogger()

    manager: Any = MagicMock()
    received: dict[str, object] = {}

    def fake_transcribe_for_processing(
        post: object,
        *,
        include_word_timestamps: bool,
        progress_callback: Any,
    ) -> tuple[Sequence[object], Sequence[object] | None]:
        received["post"] = post
        received["include_word_timestamps"] = include_word_timestamps
        received["progress_callback"] = progress_callback
        return ([], None)

    manager.transcribe_for_processing = fake_transcribe_for_processing
    processor.transcription_manager = manager

    post = MagicMock(spec=Post)
    sentinel_callback: Any = lambda _d, _t: None  # noqa: E731
    result = processor._transcribe_for_processing(
        post,
        include_word_timestamps=False,
        progress_callback=sentinel_callback,
    )
    assert result == ([], None)
    assert received == {
        "post": post,
        "include_word_timestamps": False,
        "progress_callback": sentinel_callback,
    }
