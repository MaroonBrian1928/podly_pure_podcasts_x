from types import SimpleNamespace
from typing import cast
from unittest import mock

from app.extensions import db
from app.job_manager import JobManager
from app.models import Feed, Post


def _create_feed(title: str = "Test Feed") -> Feed:
    feed = Feed(title=title, rss_url="https://example.com/feed.xml")
    db.session.add(feed)
    db.session.commit()
    return feed


def _create_post(
    *,
    feed_id: int,
    guid: str,
    title: str,
    download_url: str,
    whitelisted: bool = True,
    processed_audio_path: str | None = None,
    unprocessed_audio_path: str | None = None,
) -> Post:
    post = Post(
        feed_id=feed_id,
        guid=guid,
        title=title,
        download_url=download_url,
        whitelisted=whitelisted,
        processed_audio_path=processed_audio_path,
        unprocessed_audio_path=unprocessed_audio_path,
    )
    db.session.add(post)
    db.session.commit()
    return post


def test_load_and_validate_post_skips_when_processed_audio_exists_via_fallback(
    app, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("PODLY_PODCAST_DATA_DIR", str(tmp_path))

    feed = _create_feed("My Feed")
    unprocessed_name = "episode.mp3"
    resolved_processed = tmp_path / "srv" / "My_Feed" / unprocessed_name
    resolved_processed.parent.mkdir(parents=True, exist_ok=True)
    resolved_processed.write_bytes(b"audio")

    post = _create_post(
        feed_id=feed.id,
        guid="post-guid",
        title="Episode",
        download_url="https://example.com/episode.mp3",
        processed_audio_path=None,
        unprocessed_audio_path=str(
            tmp_path / "in" / "jobs" / "post-guid" / unprocessed_name
        ),
    )

    manager = JobManager(
        post.guid,
        status_manager=mock.MagicMock(),
        logger_obj=mock.MagicMock(),
        run_id=None,
    )
    skip_mock = mock.Mock(return_value=SimpleNamespace(id="job-1"))
    manager.skip = skip_mock  # type: ignore[method-assign]

    with mock.patch("app.job_manager.writer_client.update") as mock_update:
        mock_update.return_value = SimpleNamespace(success=True)
        loaded_post, early_result = manager._load_and_validate_post()

    assert loaded_post is None
    assert early_result is not None
    assert early_result["status"] == "skipped"
    assert early_result["job_id"] == "job-1"
    skip_mock.assert_called_once_with("Post already processed")
    mock_update.assert_called_once_with(
        "Post",
        post.id,
        {"processed_audio_path": str(resolved_processed)},
        wait=True,
    )


def test_load_and_validate_post_does_not_skip_when_db_path_is_stale(
    app, tmp_path
) -> None:
    feed = _create_feed("Another Feed")
    missing_path = tmp_path / "srv" / "Another_Feed" / "missing.mp3"
    post = _create_post(
        feed_id=feed.id,
        guid="stale-guid",
        title="Stale",
        download_url="https://example.com/stale.mp3",
        processed_audio_path=str(missing_path),
        unprocessed_audio_path=None,
    )

    manager = JobManager(
        post.guid,
        status_manager=mock.MagicMock(),
        logger_obj=mock.MagicMock(),
        run_id=None,
    )
    skip_mock = mock.Mock()
    manager.skip = skip_mock  # type: ignore[method-assign]

    with mock.patch("app.job_manager.writer_client.update") as mock_update:
        loaded_post, early_result = manager._load_and_validate_post()

    assert loaded_post is not None
    assert loaded_post.id == post.id
    assert early_result is None
    skip_mock.assert_not_called()
    mock_update.assert_not_called()


def test_ensure_job_routes_attribution_update_through_writer_client(app) -> None:
    """Regression: `ensure_job()` used to mutate the ORM row directly and call
    `db.session.flush()`, which the read-only session guard rejects. The fix
    routes the update through `writer_client.action("update_job_attribution",
    ...)` so the web/processing session never writes directly."""
    from app.models import ProcessingJob

    feed = _create_feed("Attribution Feed")
    post = _create_post(
        feed_id=feed.id,
        guid="attribution-guid",
        title="Attribution",
        download_url="https://example.com/attribution.mp3",
    )
    existing_job = ProcessingJob(
        id="job-123",
        post_guid=post.guid,
        status="pending",
        current_step=0,
        progress_percentage=0.0,
        step_name="Queued",
    )
    db.session.add(existing_job)
    db.session.commit()

    status_manager = mock.MagicMock()
    status_manager.db_session = db.session

    manager = JobManager(
        post.guid,
        status_manager=status_manager,
        logger_obj=mock.MagicMock(),
        run_id="run-abc",
        requested_by_user_id=7,
        billing_user_id=9,
    )

    captured: dict[str, object] = {}

    def fake_action(name: str, params: dict[str, object], *, wait: bool = False):
        captured["name"] = name
        captured["params"] = dict(params)
        captured["wait"] = wait
        # Apply the writer's intended mutation so the refresh below sees it.
        job_row = db.session.get(ProcessingJob, params["job_id"])
        assert job_row is not None
        if "run_id" in params:
            job_row.jobs_manager_run_id = params["run_id"]
        if "requested_by_user_id" in params:
            job_row.requested_by_user_id = params["requested_by_user_id"]
        if "billing_user_id" in params:
            job_row.billing_user_id = params["billing_user_id"]
        db.session.commit()
        return mock.MagicMock(success=True, data={"job_id": params["job_id"]})

    with mock.patch(
        "app.job_manager.writer_client.action", side_effect=fake_action
    ) as action_mock:
        job = manager.ensure_job()

    assert action_mock.called
    assert captured["name"] == "update_job_attribution"
    assert captured["wait"] is True
    params = cast(dict[str, object], captured["params"])
    assert params["job_id"] == "job-123"
    assert params["run_id"] == "run-abc"
    assert params["requested_by_user_id"] == 7
    assert params["billing_user_id"] == 9
    # The refresh after the writer call must update the in-memory row.
    assert job.jobs_manager_run_id == "run-abc"
    assert job.requested_by_user_id == 7
    assert job.billing_user_id == 9


def test_ensure_job_skips_writer_when_attribution_already_matches(app) -> None:
    """No-op fast path: if nothing actually needs to change on the active job,
    `ensure_job()` should not invoke the writer at all."""
    from app.models import ProcessingJob

    feed = _create_feed("Idempotent Feed")
    post = _create_post(
        feed_id=feed.id,
        guid="idempotent-guid",
        title="Idempotent",
        download_url="https://example.com/idempotent.mp3",
    )
    db.session.add(
        ProcessingJob(
            id="job-noop",
            post_guid=post.guid,
            status="running",
            current_step=1,
            progress_percentage=10.0,
            step_name="Running",
            jobs_manager_run_id="run-x",
            requested_by_user_id=4,
            billing_user_id=4,
        )
    )
    db.session.commit()

    status_manager = mock.MagicMock()
    status_manager.db_session = db.session

    manager = JobManager(
        post.guid,
        status_manager=status_manager,
        logger_obj=mock.MagicMock(),
        run_id="run-x",
        requested_by_user_id=4,
        billing_user_id=4,
    )

    with mock.patch("app.job_manager.writer_client.action") as action_mock:
        job = manager.ensure_job()

    action_mock.assert_not_called()
    assert job.id == "job-noop"
