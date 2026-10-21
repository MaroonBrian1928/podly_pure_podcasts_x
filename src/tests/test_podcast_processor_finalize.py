from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.models import Post, ProcessingJob
from podcast_processor.podcast_processor import PodcastProcessor


def _processor() -> PodcastProcessor:
    # Bypass __init__ to avoid beartype constructor checks on MagicMock doubles.
    processor = object.__new__(PodcastProcessor)
    processor.logger = MagicMock()
    processor.status_manager = MagicMock()
    processor._suppress_unprocessed_cleanup_for_guid = None
    processor._remove_unprocessed_audio = MagicMock()
    return processor


def _post() -> Post:
    return Post(id=7, guid="ep-7", unprocessed_audio_path="/in/ep.mp3", duration=3723)


def test_finalize_persists_processed_audio_duration() -> None:
    post = _post()
    with (
        patch(
            "podcast_processor.podcast_processor.get_audio_duration_ms",
            return_value=3_000_500,
        ) as probe,
        patch("podcast_processor.podcast_processor.writer_client") as writer,
    ):
        writer.update.return_value = SimpleNamespace(success=True)
        _processor()._finalize_processing(
            post, ProcessingJob(total_steps=4), "/out/ep.mp3", chapter_data="{}"
        )

    probe.assert_called_once_with("/out/ep.mp3")
    update_data = writer.update.call_args.args[2]
    assert update_data["duration"] == 3000.5
    assert post.duration == 3000.5


def test_finalize_keeps_stored_duration_when_probe_fails() -> None:
    post = _post()
    with (
        patch(
            "podcast_processor.podcast_processor.get_audio_duration_ms",
            return_value=None,
        ),
        patch("podcast_processor.podcast_processor.writer_client") as writer,
    ):
        writer.update.return_value = SimpleNamespace(success=True)
        _processor()._finalize_processing(
            post, ProcessingJob(total_steps=4), "/out/ep.mp3"
        )

    assert "duration" not in writer.update.call_args.args[2]
    assert post.duration == 3723


def _finalize_update(**kwargs) -> dict:
    with (
        patch(
            "podcast_processor.podcast_processor.get_audio_duration_ms",
            return_value=1000,
        ),
        patch("podcast_processor.podcast_processor.writer_client") as writer,
    ):
        writer.update.return_value = SimpleNamespace(success=True)
        _processor()._finalize_processing(
            _post(), ProcessingJob(total_steps=4), "/out/ep.mp3", **kwargs
        )
    return writer.update.call_args.args[2]


def test_finalize_records_cut_stats() -> None:
    update_data = _finalize_update(
        removed_ad_windows=[[10.0, 20.5]], original_duration_seconds=600.123
    )

    assert update_data["removed_ad_windows"] == [[10.0, 20.5]]
    assert update_data["original_duration_seconds"] == 600.123
    assert update_data["cut_stats_source"] == "recorded"


def test_finalize_without_cutter_clears_cut_stats() -> None:
    update_data = _finalize_update()

    assert update_data["removed_ad_windows"] is None
    assert update_data["original_duration_seconds"] is None
    assert update_data["cut_stats_source"] is None


def test_finalize_records_empty_cut_list_as_recorded() -> None:
    update_data = _finalize_update(
        removed_ad_windows=[], original_duration_seconds=60.0
    )

    assert update_data["removed_ad_windows"] == []
    assert update_data["cut_stats_source"] == "recorded"
