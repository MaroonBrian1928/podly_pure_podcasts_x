import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

from app.models import Post, ProcessingJob
from app.runtime_config import config as runtime_config
from podcast_processor.chapter_reader import Chapter
from podcast_processor.podcast_processor import PodcastProcessor, ProfanityBleepResult
from shared.config import RemoteWhisperConfig
from shared.test_utils import create_standard_test_config


def test_llm_chapter_fallback_tagging_disabled_skips_resolver_and_writer() -> None:
    config = create_standard_test_config()
    config.enable_llm_chapter_fallback_tagging = False

    transcription_manager = MagicMock()
    transcript_segments = [
        SimpleNamespace(sequence_num=0, start_time=0.0, end_time=5.0, text="hello")
    ]
    transcription_manager.transcribe.return_value = transcript_segments

    audio_processor = MagicMock()
    audio_processor.process_audio.return_value = [(1000, 2000)]

    status_manager = MagicMock()

    # Bypass __init__ to avoid beartype constructor checks on MagicMock doubles.
    processor = object.__new__(PodcastProcessor)
    processor.config = config
    processor.logger = MagicMock()
    processor.transcription_manager = transcription_manager
    processor.audio_processor = audio_processor
    processor.status_manager = status_manager
    processor._classify_ad_segments = MagicMock()
    processor._finalize_processing = MagicMock()

    post = Post(
        id=1,
        feed_id=1,
        guid="test-guid",
        title="Test Episode",
        download_url="https://example.com/test.mp3",
        description="00:00 Intro",
        unprocessed_audio_path="/tmp/input.mp3",
    )
    job = ProcessingJob(id="job-1", post_guid="test-guid", status="running")

    with (
        patch(
            "podcast_processor.podcast_processor.resolve_llm_path_chapters"
        ) as resolve_mock,
        patch(
            "podcast_processor.podcast_processor.write_adjusted_chapters"
        ) as write_mock,
    ):
        processor._perform_llm_based_processing(post, job, "/tmp/output.mp3")

    resolve_mock.assert_not_called()
    write_mock.assert_not_called()
    audio_processor.process_audio.assert_called_once_with(post, "/tmp/output.mp3")


def test_llm_description_chapters_skip_word_refiner_and_write_unmodified() -> None:
    config = create_standard_test_config()
    config.enable_llm_chapter_fallback_tagging = True
    # Intra-segment refinement OFF -> description chapters are written verbatim.
    config.enable_word_level_boundary_refinder = False

    transcription_manager = MagicMock()
    transcript_segments = [
        SimpleNamespace(
            sequence_num=0,
            start_time=0.0,
            end_time=10.0,
            text="Intro content",
        ),
        SimpleNamespace(
            sequence_num=1,
            start_time=10.0,
            end_time=20.0,
            text="Topic content",
        ),
    ]
    transcription_manager.transcribe.return_value = transcript_segments

    audio_processor = MagicMock()
    audio_processor.process_audio.return_value = []

    status_manager = MagicMock()

    processor = object.__new__(PodcastProcessor)
    processor.config = config
    processor.logger = MagicMock()
    processor.transcription_manager = transcription_manager
    processor.audio_processor = audio_processor
    processor.status_manager = status_manager
    processor._classify_ad_segments = MagicMock()
    processor._finalize_processing = MagicMock()

    post = Post(
        id=1,
        feed_id=1,
        guid="test-guid",
        title="Test Episode",
        download_url="https://example.com/test.mp3",
        description="00:00 Intro\n00:10 Topic",
        unprocessed_audio_path="/tmp/input.mp3",
    )
    job = ProcessingJob(id="job-1", post_guid="test-guid", status="running")
    description_chapters = [
        Chapter("desc0", "Intro", 0, 10_000),
        Chapter("desc1", "Topic", 10_000, 20_000),
    ]

    with (
        patch(
            "podcast_processor.podcast_processor.resolve_llm_path_chapters",
            return_value=(description_chapters, "description"),
        ) as resolve_mock,
        patch(
            "podcast_processor.podcast_processor.write_adjusted_chapters"
        ) as write_mock,
    ):
        processor._perform_llm_based_processing(post, job, "/tmp/output.mp3")

    resolve_mock.assert_called_once()
    assert write_mock.call_count == 1
    assert write_mock.call_args.kwargs["chapters_to_keep"] == description_chapters
    assert write_mock.call_args.kwargs["removed_segments"] == []


def test_llm_description_chapters_refined_when_word_level_enabled() -> None:
    config = create_standard_test_config()
    config.enable_llm_chapter_fallback_tagging = True
    config.enable_boundary_refinement = True
    config.enable_word_level_boundary_refinder = True

    transcription_manager = MagicMock()
    transcript_segments = [
        SimpleNamespace(sequence_num=0, start_time=0.0, end_time=10.0, text="Intro"),
        SimpleNamespace(sequence_num=1, start_time=10.0, end_time=20.0, text="Topic"),
    ]
    transcription_manager.transcribe.return_value = transcript_segments

    audio_processor = MagicMock()
    audio_processor.process_audio.return_value = []

    processor = object.__new__(PodcastProcessor)
    processor.config = config
    processor.logger = MagicMock()
    processor.transcription_manager = transcription_manager
    processor.audio_processor = audio_processor
    processor.status_manager = MagicMock()
    processor._classify_ad_segments = MagicMock()
    processor._finalize_processing = MagicMock()

    post = Post(
        id=1,
        feed_id=1,
        guid="test-guid",
        title="Test Episode",
        download_url="https://example.com/test.mp3",
        description="00:00 Intro\n00:10 Topic",
        unprocessed_audio_path="/tmp/input.mp3",
    )
    job = ProcessingJob(id="job-1", post_guid="test-guid", status="running")
    description_chapters = [
        Chapter("desc0", "Intro", 0, 10_000),
        Chapter("desc1", "Topic", 10_000, 20_000),
    ]
    refined_chapters = [
        Chapter("desc0", "Intro", 0, 12_000),
        Chapter("desc1", "Topic", 12_000, 20_000),
    ]

    with (
        patch(
            "podcast_processor.podcast_processor.resolve_llm_path_chapters",
            return_value=(description_chapters, "description"),
        ),
        patch(
            "podcast_processor.podcast_processor.write_adjusted_chapters"
        ) as write_mock,
        patch(
            "podcast_processor.podcast_processor."
            "refine_description_chapters_with_word_refiner",
            return_value=refined_chapters,
        ) as refine_mock,
    ):
        processor._perform_llm_based_processing(post, job, "/tmp/output.mp3")

    assert refine_mock.called
    assert write_mock.call_args.kwargs["chapters_to_keep"] == refined_chapters


def test_llm_transcript_chapters_exclude_removed_ad_overlap_segments() -> None:
    config = create_standard_test_config()
    config.enable_llm_chapter_fallback_tagging = True

    transcription_manager = MagicMock()
    transcript_segments = [
        SimpleNamespace(sequence_num=0, start_time=0.0, end_time=10.0, text="Intro"),
        SimpleNamespace(sequence_num=1, start_time=10.0, end_time=20.0, text="Ad read"),
        SimpleNamespace(
            sequence_num=2,
            start_time=20.0,
            end_time=30.0,
            text="Main discussion",
        ),
    ]
    transcription_manager.transcribe.return_value = transcript_segments

    audio_processor = MagicMock()
    audio_processor.process_audio.return_value = [(10_000, 20_000)]

    status_manager = MagicMock()

    processor = object.__new__(PodcastProcessor)
    processor.config = config
    processor.logger = MagicMock()
    processor.transcription_manager = transcription_manager
    processor.audio_processor = audio_processor
    processor.status_manager = status_manager
    processor._classify_ad_segments = MagicMock()
    processor._finalize_processing = MagicMock()

    post = Post(
        id=1,
        feed_id=1,
        guid="test-guid",
        title="Test Episode",
        download_url="https://example.com/test.mp3",
        description="",
        unprocessed_audio_path="/tmp/input.mp3",
    )
    job = ProcessingJob(id="job-1", post_guid="test-guid", status="running")

    transcript_seed_chapters = [Chapter("gen0", "Initial chapter", 0, 30_000)]
    topic_chapters = [
        Chapter("topic0", "Intro", 0, 10_000),
        Chapter("topic1", "Main discussion", 20_000, 30_000),
    ]

    with (
        patch(
            "podcast_processor.podcast_processor.resolve_llm_path_chapters",
            return_value=(transcript_seed_chapters, "transcript"),
        ),
        patch(
            "podcast_processor.podcast_processor."
            "generate_topic_chapters_from_transcript_with_llm",
            return_value=topic_chapters,
        ) as topic_mock,
        patch(
            "podcast_processor.podcast_processor.write_adjusted_chapters"
        ) as write_mock,
    ):
        processor._perform_llm_based_processing(post, job, "/tmp/output.mp3")

    topic_input_segments = topic_mock.call_args.args[0]
    assert [segment.sequence_num for segment in topic_input_segments] == [0, 2]

    assert write_mock.call_args.kwargs["chapters_to_keep"] == [
        Chapter("topic0", "Intro", 0, 20_000),
        Chapter("topic1", "Main discussion", 20_000, 30_000),
    ]
    assert write_mock.call_args.kwargs["removed_segments"] == [(10.0, 20.0)]

    chapter_data = json.loads(
        processor._finalize_processing.call_args.kwargs["chapter_data"]
    )
    assert chapter_data["chapter_source"] == "transcript"
    assert chapter_data["chapters_for_output"] == [
        {"title": "Intro", "start_time": 0.0, "end_time": 10.0},
        {"title": "Main discussion", "start_time": 10.0, "end_time": 20.0},
    ]


def test_transcript_topic_chapters_pull_coarse_boundary_back_to_title_match() -> None:
    config = create_standard_test_config()

    processor = object.__new__(PodcastProcessor)
    processor.config = config
    processor.logger = MagicMock()

    transcript_segments = [
        SimpleNamespace(
            sequence_num=0,
            start_time=0.0,
            end_time=120.0,
            text="Xbox strategy and leadership discussion continues.",
        ),
        SimpleNamespace(
            sequence_num=1,
            start_time=225.0,
            end_time=235.0,
            text="Harlem Globetrotters are back in video game form.",
        ),
        SimpleNamespace(
            sequence_num=2,
            start_time=236.0,
            end_time=390.0,
            text="More on the Harlem Globetrotters game announcement.",
        ),
        SimpleNamespace(
            sequence_num=3,
            start_time=390.0,
            end_time=540.0,
            text="They keep talking about the game and Acclaim.",
        ),
    ]

    coarse_topic_chapters = [
        Chapter("topic0", "Xbox strategy and leadership", 0, 390_000),
        Chapter("topic1", "Harlem Globetrotters game", 390_000, 540_000),
    ]

    with patch(
        "podcast_processor.podcast_processor."
        "generate_topic_chapters_from_transcript_with_llm",
        return_value=coarse_topic_chapters,
    ):
        refined = processor._refine_transcript_sourced_chapters(
            chapters_for_output=[Chapter("seed0", "Seed", 0, 540_000)],
            transcript_segments=transcript_segments,
            post_id=1,
        )

    assert [ch.start_time_ms for ch in refined] == [0, 225_000]
    assert [ch.end_time_ms for ch in refined] == [225_000, 540_000]
    assert [ch.title for ch in refined] == [
        "Xbox strategy and leadership",
        "Harlem Globetrotters game",
    ]


def test_llm_embedded_chapters_adjust_each_marker_by_prior_removed_audio() -> None:
    config = create_standard_test_config()
    config.enable_llm_chapter_fallback_tagging = True

    transcription_manager = MagicMock()
    transcription_manager.transcribe.return_value = [
        SimpleNamespace(sequence_num=0, start_time=0.0, end_time=10.0, text="Intro")
    ]

    audio_processor = MagicMock()
    audio_processor.process_audio.return_value = [(10_000, 20_000), (50_000, 70_000)]

    processor = object.__new__(PodcastProcessor)
    processor.config = config
    processor.logger = MagicMock()
    processor.transcription_manager = transcription_manager
    processor.audio_processor = audio_processor
    processor.status_manager = MagicMock()
    processor._classify_ad_segments = MagicMock()
    processor._finalize_processing = MagicMock()

    post = Post(
        id=1,
        feed_id=1,
        guid="test-guid",
        title="Test Episode",
        download_url="https://example.com/test.mp3",
        description="",
        unprocessed_audio_path="/tmp/input.mp3",
    )
    job = ProcessingJob(id="job-1", post_guid="test-guid", status="running")

    embedded_chapters = [
        Chapter("chp0", "Intro", 0, 30_000),
        Chapter("chp1", "Main", 30_000, 90_000),
        Chapter("chp2", "Wrap", 90_000, 120_000),
    ]

    with (
        patch(
            "podcast_processor.podcast_processor.resolve_llm_path_chapters",
            return_value=(embedded_chapters, "embedded"),
        ),
        patch(
            "podcast_processor.podcast_processor.write_adjusted_chapters"
        ) as write_mock,
    ):
        processor._perform_llm_based_processing(post, job, "/tmp/output.mp3")

    assert write_mock.call_args.kwargs["chapters_to_keep"] == embedded_chapters
    assert write_mock.call_args.kwargs["removed_segments"] == [
        (10.0, 20.0),
        (50.0, 70.0),
    ]

    chapter_data = json.loads(
        processor._finalize_processing.call_args.kwargs["chapter_data"]
    )
    assert chapter_data["chapter_source"] == "embedded"
    assert chapter_data["chapters_for_output"] == [
        {"title": "Intro", "start_time": 0.0, "end_time": 20.0},
        {"title": "Main", "start_time": 20.0, "end_time": 60.0},
        {"title": "Wrap", "start_time": 60.0, "end_time": 90.0},
    ]


def test_llm_processing_persists_bleep_windows_when_enabled() -> None:
    config = create_standard_test_config()

    processor = object.__new__(PodcastProcessor)
    processor.config = config
    processor.logger = MagicMock()
    processor.status_manager = MagicMock()
    processor.audio_processor = MagicMock()
    processor.audio_processor.process_audio.return_value = []
    processor._classify_ad_segments = MagicMock()
    processor._transcribe_for_processing = MagicMock(
        return_value=(
            [SimpleNamespace(sequence_num=0, start_time=0.0, end_time=5.0)],
            [],
        )
    )
    processor._prepare_profanity_bleeped_audio = MagicMock(
        return_value=ProfanityBleepResult(
            "/tmp/bleeped.mp3",
            [(120, 240), (1000, 1300)],
        )
    )
    processor._cleanup_temp_audio_path = MagicMock()
    processor._finalize_processing = MagicMock()

    post = Post(
        id=1,
        feed_id=1,
        guid="test-guid",
        title="Test Episode",
        download_url="https://example.com/test.mp3",
        description="",
        unprocessed_audio_path="/tmp/input.mp3",
    )
    job = ProcessingJob(id="job-1", post_guid="test-guid", status="running")

    processor._perform_llm_based_processing(
        post,
        job,
        "/tmp/output.mp3",
        enable_profanity_bleeping=True,
    )

    processor.audio_processor.process_audio.assert_called_once_with(
        post,
        "/tmp/output.mp3",
        input_audio_path="/tmp/bleeped.mp3",
    )
    assert processor._finalize_processing.call_args.kwargs["bleep_windows"] == [
        {"start_time": 0.12, "end_time": 0.24},
        {"start_time": 1.0, "end_time": 1.3},
    ]


def test_prepare_profanity_bleeped_audio_uses_configured_bleep_padding(
    tmp_path: Path,
) -> None:
    config = create_standard_test_config()
    config.output.bleep_padding_start_ms = 25
    config.output.bleep_padding_end_ms = 75

    processor = object.__new__(PodcastProcessor)
    processor.config = config

    original_whisper = runtime_config.whisper
    runtime_config.whisper = RemoteWhisperConfig(api_key="test-key", model="whisper-1")

    source_path = tmp_path / "source.mp3"
    output_path = tmp_path / "output.mp3"
    transcript_segments = [object()]

    try:
        with (
            patch(
                "podcast_processor.podcast_processor.extract_profanity_windows",
                return_value=([(475, 775)], True),
            ) as extract_windows,
            patch("podcast_processor.podcast_processor.overlay_beeps_with_ducking"),
        ):
            result = processor._prepare_profanity_bleeped_audio(
                source_audio_path=str(source_path),
                processed_audio_path=str(output_path),
                rich_transcript_segments=transcript_segments,
                enable_profanity_bleeping=True,
            )
    finally:
        runtime_config.whisper = original_whisper

    extract_windows.assert_called_once_with(
        transcript_segments,
        pad_start_ms=25,
        pad_end_ms=75,
    )
    assert result.windows_ms == [(475, 775)]


def test_llm_processing_reuses_saved_bleep_windows_without_word_timestamps() -> None:
    config = create_standard_test_config()

    processor = object.__new__(PodcastProcessor)
    processor.config = config
    processor.logger = MagicMock()
    processor.status_manager = MagicMock()
    processor.audio_processor = MagicMock()
    processor.audio_processor.process_audio.return_value = []
    processor._classify_ad_segments = MagicMock()
    processor._transcribe_for_processing = MagicMock(
        return_value=(
            [SimpleNamespace(sequence_num=0, start_time=0.0, end_time=5.0)],
            None,
        )
    )
    processor._prepare_profanity_bleeped_audio = MagicMock(
        return_value=ProfanityBleepResult(
            "/tmp/bleeped.mp3",
            [(1250, 1750)],
        )
    )
    processor._cleanup_temp_audio_path = MagicMock()
    processor._finalize_processing = MagicMock()

    post = Post(
        id=1,
        feed_id=1,
        guid="test-guid",
        title="Test Episode",
        download_url="https://example.com/test.mp3",
        description="",
        unprocessed_audio_path="/tmp/input.mp3",
        bleep_windows=[{"start_time": 1.25, "end_time": 1.75}],
    )
    job = ProcessingJob(id="job-1", post_guid="test-guid", status="running")

    processor._perform_llm_based_processing(
        post,
        job,
        "/tmp/output.mp3",
        enable_profanity_bleeping=True,
    )

    processor._transcribe_for_processing.assert_called_once_with(
        post,
        include_word_timestamps=False,
        progress_callback=ANY,
    )
    assert processor._prepare_profanity_bleeped_audio.call_args.kwargs[
        "saved_bleep_windows_ms"
    ] == [(1250, 1750)]


def test_llm_processing_requests_word_timestamps_for_word_level_refiner() -> None:
    config = create_standard_test_config()
    config.enable_boundary_refinement = True
    config.enable_word_level_boundary_refinder = True

    processor = object.__new__(PodcastProcessor)
    processor.config = config
    processor.logger = MagicMock()
    processor.status_manager = MagicMock()
    processor.audio_processor = MagicMock()
    processor.audio_processor.process_audio.return_value = []
    processor._classify_ad_segments = MagicMock()
    processor._transcribe_for_processing = MagicMock(
        return_value=(
            [SimpleNamespace(sequence_num=0, start_time=0.0, end_time=5.0)],
            None,
        )
    )
    processor._prepare_profanity_bleeped_audio = MagicMock(
        return_value=ProfanityBleepResult("/tmp/input.mp3", [])
    )
    processor._cleanup_temp_audio_path = MagicMock()
    processor._finalize_processing = MagicMock()

    post = Post(
        id=1,
        feed_id=1,
        guid="test-guid",
        title="Test Episode",
        download_url="https://example.com/test.mp3",
        description="",
        unprocessed_audio_path="/tmp/input.mp3",
    )
    job = ProcessingJob(id="job-1", post_guid="test-guid", status="running")

    processor._perform_llm_based_processing(
        post,
        job,
        "/tmp/output.mp3",
        enable_profanity_bleeping=False,
    )

    processor._transcribe_for_processing.assert_called_once_with(
        post,
        include_word_timestamps=True,
        progress_callback=ANY,
    )


def test_llm_processing_reuses_saved_word_timestamps_for_word_level_refiner() -> None:
    config = create_standard_test_config()
    config.enable_boundary_refinement = True
    config.enable_word_level_boundary_refinder = True

    processor = object.__new__(PodcastProcessor)
    processor.config = config
    processor.logger = MagicMock()
    processor.status_manager = MagicMock()
    processor.audio_processor = MagicMock()
    processor.audio_processor.process_audio.return_value = []
    processor._classify_ad_segments = MagicMock()
    processor._transcribe_for_processing = MagicMock(
        return_value=(
            [SimpleNamespace(sequence_num=0, start_time=0.0, end_time=5.0)],
            None,
        )
    )
    processor._prepare_profanity_bleeped_audio = MagicMock(
        return_value=ProfanityBleepResult("/tmp/input.mp3", [])
    )
    processor._cleanup_temp_audio_path = MagicMock()
    processor._finalize_processing = MagicMock()

    post = Post(
        id=1,
        feed_id=1,
        guid="test-guid",
        title="Test Episode",
        download_url="https://example.com/test.mp3",
        description="",
        unprocessed_audio_path="/tmp/input.mp3",
        transcript_word_timestamps=[
            {
                "sequence_num": 0,
                "words": [{"word": "hello", "start": 0.0, "end": 0.5}],
            }
        ],
    )
    job = ProcessingJob(id="job-1", post_guid="test-guid", status="running")

    processor._perform_llm_based_processing(
        post,
        job,
        "/tmp/output.mp3",
        enable_profanity_bleeping=False,
    )

    processor._transcribe_for_processing.assert_called_once_with(
        post,
        include_word_timestamps=False,
        progress_callback=ANY,
    )


def test_processing_steps_routes_chapter_insert_strategy() -> None:
    processor = object.__new__(PodcastProcessor)
    processor._perform_chapter_based_processing = MagicMock()
    processor._perform_chapter_insertion_only_processing = MagicMock()
    processor._perform_llm_based_processing = MagicMock()

    post = Post(
        id=1,
        feed_id=1,
        guid="test-guid",
        title="Test Episode",
        download_url="https://example.com/test.mp3",
    )
    job = ProcessingJob(id="job-1", post_guid="test-guid", status="running")

    processor._perform_processing_steps(
        post=post,
        job=job,
        processed_audio_path="/tmp/output.mp3",
        ad_detection_strategy="chapter_insert",
        chapter_filter_strings=None,
    )

    processor._perform_chapter_insertion_only_processing.assert_called_once_with(
        post,
        job,
        "/tmp/output.mp3",
        None,
    )
    processor._perform_chapter_based_processing.assert_not_called()
    processor._perform_llm_based_processing.assert_not_called()


def test_chapter_insert_strategy_writes_chapters_without_ad_removal() -> None:
    config = create_standard_test_config()

    transcription_manager = MagicMock()
    transcript_segments = [
        SimpleNamespace(sequence_num=0, start_time=0.0, end_time=10.0, text="Intro"),
        SimpleNamespace(sequence_num=1, start_time=10.0, end_time=20.0, text="Topic"),
    ]
    transcription_manager.transcribe.return_value = transcript_segments

    processor = object.__new__(PodcastProcessor)
    processor.config = config
    processor.logger = MagicMock()
    processor.transcription_manager = transcription_manager
    processor.status_manager = MagicMock()
    processor._finalize_processing = MagicMock()

    post = Post(
        id=1,
        feed_id=1,
        guid="test-guid",
        title="Test Episode",
        download_url="https://example.com/test.mp3",
        description="",
        unprocessed_audio_path="/tmp/input.mp3",
    )
    job = ProcessingJob(id="job-1", post_guid="test-guid", status="running")

    transcript_seed_chapters = [Chapter("gen0", "Initial chapter", 0, 20_000)]
    topic_chapters = [
        Chapter("topic0", "Intro", 0, 10_000),
        Chapter("topic1", "Topic", 10_000, 20_000),
    ]

    with (
        patch(
            "podcast_processor.podcast_processor.resolve_llm_path_chapters",
            side_effect=[
                ([], "none"),
                (transcript_seed_chapters, "transcript"),
            ],
        ) as resolve_mock,
        patch(
            "podcast_processor.podcast_processor."
            "generate_topic_chapters_from_transcript_with_llm",
            return_value=topic_chapters,
        ) as topic_mock,
        patch("podcast_processor.podcast_processor.shutil.copyfile") as copy_mock,
        patch(
            "podcast_processor.podcast_processor.write_adjusted_chapters"
        ) as write_mock,
    ):
        processor._perform_chapter_insertion_only_processing(
            post, job, "/tmp/output.mp3"
        )

    assert resolve_mock.call_count == 2
    transcription_manager.transcribe.assert_called_once_with(
        post, progress_callback=ANY
    )
    topic_mock.assert_called_once_with(
        transcript_segments,
        llm_model=config.llm_model,
        llm_api_key=config.llm_api_key,
        openai_base_url=config.openai_base_url,
        post_id=post.id,
        post_guid=post.guid,
        removed_windows_ms=None,
        openai_timeout_sec=config.openai_timeout,
        logger_override=processor.logger,
        llm_service_tier=config.llm_service_tier,
        align_word_starts=False,
        words_by_sequence=None,
        word_align_config=None,
    )
    copy_mock.assert_called_once_with("/tmp/input.mp3", "/tmp/output.mp3")
    write_mock.assert_called_once_with(
        audio_path="/tmp/output.mp3",
        chapters_to_keep=topic_chapters,
        removed_segments=[],
    )

    chapter_data = json.loads(
        processor._finalize_processing.call_args.kwargs["chapter_data"]
    )
    assert chapter_data["chapter_source"] == "transcript"
    assert chapter_data["chapters_for_output"] == [
        {"title": "Intro", "start_time": 0.0, "end_time": 10.0},
        {"title": "Topic", "start_time": 10.0, "end_time": 20.0},
    ]


def test_feed_override_disables_llm_chapter_fallback_when_global_enabled() -> None:
    config = create_standard_test_config()
    config.enable_llm_chapter_fallback_tagging = True

    processor = object.__new__(PodcastProcessor)
    processor.config = config

    feed = SimpleNamespace(enable_llm_chapter_fallback_tagging=False)

    assert (
        processor._resolve_llm_chapter_fallback_tagging_enabled(
            feed,
            ad_detection_strategy="llm",
        )
        is False
    )


def test_chapter_insert_strategy_forces_llm_chapter_fallback_enabled() -> None:
    config = create_standard_test_config()
    config.enable_llm_chapter_fallback_tagging = False

    processor = object.__new__(PodcastProcessor)
    processor.config = config

    feed = SimpleNamespace(enable_llm_chapter_fallback_tagging=False)

    assert (
        processor._resolve_llm_chapter_fallback_tagging_enabled(
            feed,
            ad_detection_strategy="chapter_insert",
        )
        is True
    )


def _chapter_dispatch_processor(config) -> PodcastProcessor:
    processor = object.__new__(PodcastProcessor)
    processor.config = config
    processor.logger = MagicMock()
    return processor


def test_refine_description_sourced_chapters_uses_word_refiner_when_enabled() -> None:
    config = create_standard_test_config()
    config.enable_boundary_refinement = True
    config.enable_word_level_boundary_refinder = True
    processor = _chapter_dispatch_processor(config)

    chapters = [Chapter("d0", "First", 5_000, 100_000)]
    segments = [
        SimpleNamespace(sequence_num=0, start_time=0.0, end_time=5.0, text="hello")
    ]
    refined = [Chapter("d0", "First", 12_000, 100_000)]

    with patch(
        "podcast_processor.podcast_processor.refine_description_chapters_with_word_refiner",
        return_value=refined,
    ) as refine_mock:
        out = processor._refine_description_sourced_chapters(
            chapters_for_output=chapters,
            transcript_segments=segments,
            post_id=1,
            post_guid="guid-1",
            words_by_sequence=None,
        )

    assert refine_mock.called
    assert out == refined


def test_refine_transcript_sourced_chapters_uses_llm_word_refiner_when_enabled() -> (
    None
):
    config = create_standard_test_config()
    config.enable_boundary_refinement = True
    config.enable_word_level_boundary_refinder = True
    processor = _chapter_dispatch_processor(config)

    chapters = [Chapter("t0", "Topic", 0, 100_000)]
    segments = [
        SimpleNamespace(sequence_num=0, start_time=0.0, end_time=5.0, text="hello")
    ]
    topic = [Chapter("t0", "Topic", 0, 100_000)]

    with (
        patch(
            "podcast_processor.podcast_processor.generate_topic_chapters_from_transcript_with_llm",
            return_value=topic,
        ) as topic_mock,
        patch(
            "podcast_processor.podcast_processor.refine_transcript_chapters_with_word_refiner",
            side_effect=AssertionError("heuristic refiner must not run when flag on"),
        ),
    ):
        out = processor._refine_transcript_sourced_chapters(
            chapters_for_output=chapters,
            transcript_segments=segments,
            post_id=1,
            post_guid="guid-1",
        )

    assert topic_mock.call_args.kwargs["align_word_starts"] is True
    assert topic_mock.call_args.kwargs["word_align_config"] is config
    assert out == topic


def test_refine_transcript_sourced_chapters_uses_heuristic_when_disabled() -> None:
    config = create_standard_test_config()
    config.enable_boundary_refinement = True
    config.enable_word_level_boundary_refinder = False
    processor = _chapter_dispatch_processor(config)

    chapters = [Chapter("t0", "Topic", 0, 100_000)]
    segments = [
        SimpleNamespace(sequence_num=0, start_time=0.0, end_time=5.0, text="hello")
    ]
    topic = [Chapter("t0", "Topic", 0, 100_000)]
    heuristic = [Chapter("t0", "Topic", 8_000, 100_000)]

    with (
        patch(
            "podcast_processor.podcast_processor.generate_topic_chapters_from_transcript_with_llm",
            return_value=topic,
        ),
        patch(
            "podcast_processor.podcast_processor.refine_transcript_chapters_with_word_refiner",
            return_value=heuristic,
        ) as heuristic_mock,
    ):
        out = processor._refine_transcript_sourced_chapters(
            chapters_for_output=chapters,
            transcript_segments=segments,
            post_id=1,
            post_guid="guid-1",
        )

    assert heuristic_mock.called
    assert out == heuristic
