"""Backend tests for the zero-ads guard.

Covers:
- Writer actions for the new ProcessingJob fields (record_ad_windows_count,
  mark_classification_parse_error, mark_auto_retry_attempted).
- PodcastProcessor._evaluate_zero_ads_guard: records the count, sets the
  parse-error flag, logs the warning, and only enqueues a retry when the
  setting is enabled AND a parse error happened AND no retry was already
  attempted AND the strategy is LLM.
- OutputSettings round-trips the new column through config_store.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask

from app.extensions import db
from app.models import Feed, OutputSettings, Post, ProcessingJob
from app.writer.actions.jobs import (
    create_job_action,
    mark_auto_retry_attempted_action,
    mark_classification_parse_error_action,
    record_ad_windows_count_action,
)
from podcast_processor.podcast_processor import PodcastProcessor


@pytest.fixture
def app() -> Generator[Flask]:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    with app.app_context():
        db.init_app(app)
        db.create_all()
        yield app


def _make_post_and_job(*, strategy: str = "llm") -> tuple[Post, ProcessingJob]:
    feed = Feed(
        title="Zero Ads Feed",
        description="d",
        author="a",
        rss_url=f"https://example.com/{strategy}.xml",
        ad_detection_strategy=strategy,
    )
    db.session.add(feed)
    db.session.commit()
    post = Post(
        guid=f"zero-ads-{strategy}",
        title="An episode",
        download_url="https://example.com/audio.mp3",
        feed_id=feed.id,
        whitelisted=True,
    )
    db.session.add(post)
    db.session.commit()
    result = create_job_action(
        {
            "job_data": {
                "post_guid": post.guid,
                "status": "running",
                "current_step": 4,
                "total_steps": 4,
                "step_name": "Processing audio",
            }
        }
    )
    db.session.commit()
    job = db.session.get(ProcessingJob, result["job_id"])
    assert job is not None
    return post, job


def test_record_ad_windows_count_persists_zero_and_positive(app: Flask) -> None:
    with app.app_context():
        _, job = _make_post_and_job()

        record_ad_windows_count_action({"job_id": job.id, "count": 0})
        db.session.commit()
        db.session.refresh(job)
        assert job.ad_windows_count == 0

        record_ad_windows_count_action({"job_id": job.id, "count": 7})
        db.session.commit()
        db.session.refresh(job)
        assert job.ad_windows_count == 7


def test_mark_classification_parse_error_is_idempotent(app: Flask) -> None:
    with app.app_context():
        _, job = _make_post_and_job()
        assert job.had_classification_parse_error is False
        mark_classification_parse_error_action({"job_id": job.id})
        mark_classification_parse_error_action({"job_id": job.id})
        db.session.commit()
        db.session.refresh(job)
        assert job.had_classification_parse_error is True


def test_mark_auto_retry_attempted_sets_flag(app: Flask) -> None:
    with app.app_context():
        _, job = _make_post_and_job()
        assert job.auto_retry_attempted is False
        mark_auto_retry_attempted_action({"job_id": job.id})
        db.session.commit()
        db.session.refresh(job)
        assert job.auto_retry_attempted is True


def _make_processor_with_config(*, auto_retry_enabled: bool) -> PodcastProcessor:
    processor = PodcastProcessor.__new__(PodcastProcessor)
    processor.logger = logging.getLogger("zero-ads-guard-test")
    output = MagicMock(auto_retry_zero_ads_on_parse_error=auto_retry_enabled)
    processor.config = MagicMock(output=output)
    return processor


def _capture_writer_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, dict[str, Any]]]:
    """Stub ``writer_client.action`` so tests can assert which writer calls
    the guard emitted without spinning up the writer thread."""
    from podcast_processor import podcast_processor as pp

    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_action(name: str, params: dict[str, Any], **_: Any) -> MagicMock:
        calls.append((name, params))
        result = MagicMock()
        result.success = True
        result.data = {}
        return result

    monkeypatch.setattr(pp.writer_client, "action", fake_action)
    return calls


def test_zero_ads_guard_records_count_and_warns_without_retry_when_no_parse_error(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    with app.app_context():
        post, job = _make_post_and_job()
        processor = _make_processor_with_config(auto_retry_enabled=True)
        calls = _capture_writer_actions(monkeypatch)

        processor._evaluate_zero_ads_guard(
            post,
            job,
            ad_windows_count=0,
            had_classification_parse_error=False,
        )

        names = [name for name, _ in calls]
        # Records the 0 count but does NOT mark a parse error and does NOT
        # auto-retry — a clean LLM run that found no ads is allowed to stand.
        assert "record_ad_windows_count" in names
        assert "mark_classification_parse_error" not in names
        assert "create_job" not in names
        assert "mark_auto_retry_attempted" not in names


def test_zero_ads_guard_skips_for_non_llm_strategies(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    with app.app_context():
        post, job = _make_post_and_job(strategy="chapter")
        processor = _make_processor_with_config(auto_retry_enabled=True)
        calls = _capture_writer_actions(monkeypatch)

        processor._evaluate_zero_ads_guard(
            post,
            job,
            ad_windows_count=0,
            had_classification_parse_error=True,
        )

        names = [name for name, _ in calls]
        # Count is still recorded (useful UI signal) AND the parse-error flag
        # is honored (since it was raised), but no retry — chapter-strategy
        # zero-ad runs are common and legitimate.
        assert "record_ad_windows_count" in names
        assert "mark_classification_parse_error" in names
        assert "create_job" not in names
        assert "mark_auto_retry_attempted" not in names


def test_zero_ads_guard_retries_when_parse_error_and_setting_enabled(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    with app.app_context():
        post, job = _make_post_and_job()
        processor = _make_processor_with_config(auto_retry_enabled=True)
        calls = _capture_writer_actions(monkeypatch)

        processor._evaluate_zero_ads_guard(
            post,
            job,
            ad_windows_count=0,
            had_classification_parse_error=True,
        )

        names = [name for name, _ in calls]
        assert "mark_auto_retry_attempted" in names
        assert "create_job" in names
        # The new job inherits the run id so it lands in the same manager run.
        create_call = next(p for n, p in calls if n == "create_job")
        assert create_call["job_data"]["post_guid"] == post.guid
        assert create_call["job_data"]["status"] == "pending"


def test_zero_ads_guard_does_not_retry_when_setting_disabled(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    with app.app_context():
        post, job = _make_post_and_job()
        processor = _make_processor_with_config(auto_retry_enabled=False)
        calls = _capture_writer_actions(monkeypatch)

        processor._evaluate_zero_ads_guard(
            post,
            job,
            ad_windows_count=0,
            had_classification_parse_error=True,
        )

        names = [name for name, _ in calls]
        assert "record_ad_windows_count" in names
        assert "mark_classification_parse_error" in names
        # Setting is off → guard logs but doesn't enqueue.
        assert "create_job" not in names
        assert "mark_auto_retry_attempted" not in names


def test_zero_ads_guard_does_not_retry_twice(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    with app.app_context():
        post, job = _make_post_and_job()
        # Simulate a prior retry already having happened.
        job.auto_retry_attempted = True
        db.session.commit()

        processor = _make_processor_with_config(auto_retry_enabled=True)
        calls = _capture_writer_actions(monkeypatch)

        processor._evaluate_zero_ads_guard(
            post,
            job,
            ad_windows_count=0,
            had_classification_parse_error=True,
        )

        names = [name for name, _ in calls]
        assert "create_job" not in names
        assert "mark_auto_retry_attempted" not in names


def test_zero_ads_guard_does_not_retry_when_ads_were_found(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    with app.app_context():
        post, job = _make_post_and_job()
        processor = _make_processor_with_config(auto_retry_enabled=True)
        calls = _capture_writer_actions(monkeypatch)

        processor._evaluate_zero_ads_guard(
            post,
            job,
            ad_windows_count=5,
            had_classification_parse_error=True,
        )

        names = [name for name, _ in calls]
        # Count is recorded and parse error flagged, but no retry — there were
        # 5 ads, so the parse error didn't actually cause a miss.
        assert "record_ad_windows_count" in names
        assert "mark_classification_parse_error" in names
        assert "create_job" not in names


def test_zero_ads_guard_propagates_retry_flag_into_new_job(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the auto-retry job itself must carry
    ``auto_retry_attempted=True`` so a second malformed-zero-ad outcome on
    the retry can't enqueue *another* retry. Without this, the flag only
    lives on the failed job we just marked and we could loop indefinitely.
    """
    with app.app_context():
        post, job = _make_post_and_job()
        processor = _make_processor_with_config(auto_retry_enabled=True)
        calls = _capture_writer_actions(monkeypatch)

        processor._evaluate_zero_ads_guard(
            post,
            job,
            ad_windows_count=0,
            had_classification_parse_error=True,
        )

        create_call = next(p for n, p in calls if n == "create_job")
        assert create_call["job_data"]["auto_retry_attempted"] is True


def test_process_clears_state_when_retry_flag_set(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end-ish: when the worker invokes ``process()`` on a job
    flagged as an auto-retry, the processor must call the new
    ``prepare_post_for_auto_retry`` writer action *before* the existing-
    processed-audio fast path would otherwise short-circuit the run.
    """
    from podcast_processor import podcast_processor as pp

    with app.app_context():
        post, _failed_job = _make_post_and_job()
        # Simulate the prior failed run's persisted state.
        post.processed_audio_path = "/tmp/should-not-stop-the-retry.mp3"
        db.session.commit()

        # Create the retry job carrying the propagated flag.
        retry = create_job_action(
            {
                "job_data": {
                    "post_guid": post.guid,
                    "status": "pending",
                    "current_step": 0,
                    "total_steps": 4,
                    "step_name": "Queued (auto-retry)",
                    "auto_retry_attempted": True,
                }
            }
        )
        db.session.commit()
        retry_job = db.session.get(ProcessingJob, retry["job_id"])
        assert retry_job is not None
        assert retry_job.auto_retry_attempted is True

        prepare_calls: list[dict[str, Any]] = []
        check_existing_calls: list[Post] = []

        def fake_action(name: str, params: dict[str, Any], **_: Any) -> MagicMock:
            if name == "prepare_post_for_auto_retry":
                prepare_calls.append(params)
                # Simulate the action clearing on-disk state and DB paths.
                post.processed_audio_path = None
                db.session.commit()
            result = MagicMock()
            result.success = True
            result.data = {}
            return result

        monkeypatch.setattr(pp.writer_client, "action", fake_action)
        # Make any post-status updates no-op so the test stays focused.
        monkeypatch.setattr(
            pp,
            "ProcessorException",
            type("ProcessorException", (Exception,), {}),
        )

        processor = PodcastProcessor.__new__(PodcastProcessor)
        processor.logger = logging.getLogger("zero-ads-guard-test")
        processor.config = MagicMock(output=MagicMock())
        processor.db_session = db.session
        processor.status_manager = MagicMock()
        # Make _check_existing_processed_audio observable; cut the rest of
        # process() short by raising once we know the early-exit didn't fire.

        def fake_check(checked_post: Post) -> bool:
            check_existing_calls.append(checked_post)
            return checked_post.processed_audio_path is not None

        processor._check_existing_processed_audio = fake_check
        # Halt process() right after the early-exit decision so we don't
        # need to set up downloader / classifier / audio_processor.
        sentinel = RuntimeError("halt after early-exit")

        def boom(*_args: Any, **_kwargs: Any) -> None:
            raise sentinel

        processor._simulate_developer_processing = boom

        with pytest.raises(RuntimeError, match="halt after early-exit"):
            processor.process(post, retry_job.id)

        # Prepare action ran with the right post id.
        assert prepare_calls == [{"post_id": post.id}]
        # _check_existing_processed_audio ran AFTER cleanup, so it saw the
        # cleared path and returned False — the early-exit didn't fire.
        assert len(check_existing_calls) == 1
        assert check_existing_calls[0].processed_audio_path is None


def test_prepare_post_for_auto_retry_preserves_unprocessed_audio_and_deletes_processed_candidates(
    app: Flask, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DAI-safety: the prepare action must NOT delete the unprocessed audio
    file or clear its DB path. Dynamic-ad-insertion feeds return different
    bytes per download, so the retry needs to reuse the exact file the
    retained transcripts describe.

    Regression: cleanup must delete every processed-audio candidate that the
    early-exit fast path can rediscover, not only ``post.processed_audio_path``.
    """
    from app.writer.actions.cleanup import prepare_post_for_auto_retry_action
    from shared.processing_paths import get_processed_audio_path_candidates

    with app.app_context():
        data_root = tmp_path / "podcast-data"
        monkeypatch.setenv("PODLY_PODCAST_DATA_DIR", str(data_root))
        post, _ = _make_post_and_job()
        unprocessed = data_root / "in" / "source.mp3"
        unprocessed.parent.mkdir(parents=True)
        unprocessed.write_bytes(b"original audio bytes")
        processed = tmp_path / "edited.mp3"
        processed.write_bytes(b"zero-ads stale output")
        post.unprocessed_audio_path = str(unprocessed)
        post.processed_audio_path = str(processed)
        db.session.commit()

        processed_candidates = get_processed_audio_path_candidates(
            processed_audio_path=post.processed_audio_path,
            unprocessed_audio_path=post.unprocessed_audio_path,
            feed_title=post.feed.title,
            post_title=post.title,
        )
        for candidate in processed_candidates:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(b"stale processed bytes")

        prepare_post_for_auto_retry_action({"post_id": post.id})
        db.session.commit()
        db.session.refresh(post)

        # Processed artifacts are wiped (DB path plus derived/legacy disk paths).
        assert all(not candidate.exists() for candidate in processed_candidates)
        assert post.processed_audio_path is None

        # Unprocessed artifact survives both checks — the retry will reuse it.
        assert unprocessed.exists()
        assert post.unprocessed_audio_path == str(unprocessed)


def test_remove_unprocessed_audio_skips_when_retry_suppression_set(
    app: Flask, tmp_path: Any
) -> None:
    """Once the zero-ads guard sets the suppression flag for a post, the
    failing run's finalization must NOT delete the unprocessed audio.
    Without this gate the retry would re-download and DAI feeds would
    silently desync from the retained transcripts."""
    with app.app_context():
        post, _ = _make_post_and_job()
        unprocessed = tmp_path / "source.mp3"
        unprocessed.write_bytes(b"keep me")
        post.unprocessed_audio_path = str(unprocessed)
        db.session.commit()

        processor = PodcastProcessor.__new__(PodcastProcessor)
        processor.logger = logging.getLogger("zero-ads-guard-test")
        processor.db_session = db.session
        processor._suppress_unprocessed_cleanup_for_guid = post.guid

        processor._remove_unprocessed_audio(post)

        assert unprocessed.exists(), "unprocessed file must survive for retry"
        # Suppression is single-shot so later calls clean up normally.
        assert processor._suppress_unprocessed_cleanup_for_guid is None

        processor._remove_unprocessed_audio(post)
        assert not unprocessed.exists()


def test_remove_unprocessed_audio_proceeds_for_unrelated_posts(
    app: Flask, tmp_path: Any
) -> None:
    """The suppression flag must scope by post guid — a retry triggered for
    post A must not block the unprocessed-audio cleanup of unrelated post
    B that happens to finalize while the flag is set."""
    with app.app_context():
        other_post, _ = _make_post_and_job(strategy="chapter")
        unprocessed = tmp_path / "other.mp3"
        unprocessed.write_bytes(b"unrelated bytes")
        other_post.unprocessed_audio_path = str(unprocessed)
        db.session.commit()

        processor = PodcastProcessor.__new__(PodcastProcessor)
        processor.logger = logging.getLogger("zero-ads-guard-test")
        processor.db_session = db.session
        processor._suppress_unprocessed_cleanup_for_guid = "some-other-guid"

        processor._remove_unprocessed_audio(other_post)

        # Unrelated post's audio still got cleaned up; flag still set so the
        # actual retry's matching post would benefit.
        assert not unprocessed.exists()
        assert processor._suppress_unprocessed_cleanup_for_guid == "some-other-guid"


def test_output_settings_persists_auto_retry_flag(app: Flask) -> None:
    """Round-trip the new column through the model: write True, read True."""
    with app.app_context():
        settings = OutputSettings(id=1)
        db.session.add(settings)
        db.session.commit()
        # Default for new rows is False (server_default sa.false()).
        db.session.refresh(settings)
        assert settings.auto_retry_zero_ads_on_parse_error is False

        settings.auto_retry_zero_ads_on_parse_error = True
        db.session.commit()
        db.session.refresh(settings)
        assert settings.auto_retry_zero_ads_on_parse_error is True
