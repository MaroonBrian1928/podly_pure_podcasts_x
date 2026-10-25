from typing import Any
from unittest import mock

import pytest

from app.cut_stats import backfill_cut_windows
from app.extensions import db
from app.models import Feed, Post, TranscriptSegment
from app.runtime_config import config as runtime_config

AD_WINDOW = (100.0, 160.0)
TRANSCRIPT_END = 1000.0


def _fade_seconds() -> float:
    return int(runtime_config.output.fade_ms) / 1000.0


def _removed_seconds() -> float:
    fade = _fade_seconds()
    return (AD_WINDOW[1] - AD_WINDOW[0]) - 2 * fade


def _add_post(guid: str, *, duration: float | None, with_transcript: bool = True):
    feed = Feed(title=f"Feed {guid}", rss_url=f"https://example.com/{guid}.xml")
    db.session.add(feed)
    db.session.flush()
    post = Post(
        feed_id=feed.id,
        guid=guid,
        title=f"Episode {guid}",
        download_url="https://example.com/audio.mp3",
        processed_audio_path="/tmp/processed.mp3",
        duration=duration,
    )
    db.session.add(post)
    db.session.flush()
    if with_transcript:
        db.session.add(
            TranscriptSegment(
                post_id=post.id,
                sequence_num=0,
                start_time=0.0,
                end_time=TRANSCRIPT_END,
                text="hello",
            )
        )
    db.session.commit()
    return post


@pytest.fixture(autouse=True)
def _cutter_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(runtime_config.output, "min_ad_segment_length_seconds", 10)
    monkeypatch.setattr(runtime_config.output, "min_ad_segment_separation_seconds", 60)
    with mock.patch(
        "podcast_processor.audio_processor.AudioProcessor.get_ad_segments",
        return_value=[AD_WINDOW],
    ):
        yield


def test_backfill_stores_reconciled_windows(app: Any) -> None:
    post = _add_post("bf-ok", duration=TRANSCRIPT_END - _removed_seconds())

    result = backfill_cut_windows(apply=True)
    db.session.refresh(post)

    assert result["checked"] == 1
    assert result["stored"] == 1
    assert result["skipped_mismatch"] == 0
    assert post.cut_stats_source == "backfilled"
    assert post.original_duration_seconds == TRANSCRIPT_END
    fade = _fade_seconds()
    assert post.removed_ad_windows == [[AD_WINDOW[0] + fade, AD_WINDOW[1] - fade]]


def test_backfill_skips_when_durations_do_not_reconcile(app: Any) -> None:
    post = _add_post("bf-mismatch", duration=TRANSCRIPT_END - _removed_seconds() - 30)

    result = backfill_cut_windows(apply=True)
    db.session.refresh(post)

    assert result["stored"] == 0
    assert result["skipped_mismatch"] == 1
    assert result["largest_mismatches"][0]["title"] == "Episode bf-mismatch"
    assert result["largest_mismatches"][0]["gap_seconds"] == pytest.approx(30.0)
    assert post.removed_ad_windows is None
    assert post.cut_stats_source == "unverified"


def test_backfill_dry_run_writes_nothing(app: Any) -> None:
    post = _add_post("bf-dry", duration=TRANSCRIPT_END - _removed_seconds())

    with mock.patch("app.writer.client.writer_client.update") as update:
        result = backfill_cut_windows(apply=False)
    db.session.refresh(post)

    update.assert_not_called()
    assert result["stored"] == 1
    assert post.removed_ad_windows is None
    assert post.original_duration_seconds is None
    assert post.cut_stats_source is None


def test_backfill_counts_posts_without_transcript_or_duration(app: Any) -> None:
    _add_post("bf-no-transcript", duration=500.0, with_transcript=False)
    _add_post("bf-no-duration", duration=None)

    result = backfill_cut_windows(apply=True)

    assert result["checked"] == 2
    assert result["skipped_no_transcript"] == 1
    assert result["skipped_no_duration"] == 1
    assert result["stored"] == 0


def test_backfill_leaves_already_recorded_posts_alone(app: Any) -> None:
    post = _add_post("bf-recorded", duration=900.0)
    post.removed_ad_windows = []
    post.original_duration_seconds = 900.0
    post.cut_stats_source = "recorded"
    db.session.commit()

    result = backfill_cut_windows(apply=True)
    db.session.refresh(post)

    assert result["checked"] == 0
    assert post.cut_stats_source == "recorded"


def test_backfill_marks_mismatch_unverified_and_does_not_reexamine(app: Any) -> None:
    post = _add_post("bf-unv", duration=TRANSCRIPT_END - _removed_seconds() - 30)

    first = backfill_cut_windows(apply=True)
    db.session.refresh(post)
    second = backfill_cut_windows(apply=True)

    assert first["skipped_mismatch"] == 1
    assert post.cut_stats_source == "unverified"
    assert post.removed_ad_windows is None
    assert post.original_duration_seconds is None
    assert second["checked"] == 0


def test_backfill_marks_no_transcript_unverified(app: Any) -> None:
    post = _add_post("bf-unv-nt", duration=500.0, with_transcript=False)

    backfill_cut_windows(apply=True)
    db.session.refresh(post)

    assert post.cut_stats_source == "unverified"


def test_backfill_dry_run_writes_no_unverified_marker(app: Any) -> None:
    post = _add_post("bf-dry-unv", duration=TRANSCRIPT_END - _removed_seconds() - 30)

    with mock.patch("app.writer.client.writer_client.update") as update:
        result = backfill_cut_windows(apply=False)
    db.session.refresh(post)

    update.assert_not_called()
    assert result["skipped_mismatch"] == 1
    assert post.cut_stats_source is None
