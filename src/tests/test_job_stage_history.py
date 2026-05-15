from datetime import UTC, datetime, timedelta

from app.extensions import db
from app.models import Feed, Post, ProcessingJob
from app.writer.actions.cleanup import cleanup_missing_audio_paths_action
from app.writer.actions.feeds import add_feed_action, refresh_feed_action
from app.writer.actions.jobs import create_job_action, update_job_status_action


def _make_post(title: str = "Test Episode") -> Post:
    feed = Feed(
        title="Test Feed",
        description="Test Description",
        author="Test Author",
        rss_url=f"https://example.com/{title}.xml",
    )
    db.session.add(feed)
    db.session.commit()
    post = Post(
        guid=f"stage-history-{title}",
        title=title,
        download_url="https://example.com/episode.mp3",
        feed_id=feed.id,
        whitelisted=True,
    )
    db.session.add(post)
    db.session.commit()
    return post


def test_create_job_action_seeds_queue_stage(app) -> None:
    with app.app_context():
        post = _make_post("create-seed")
        before = datetime.now(UTC).replace(tzinfo=None)
        result = create_job_action(
            {
                "job_data": {
                    "post_guid": post.guid,
                    "status": "pending",
                    "current_step": 0,
                    "total_steps": 4,
                    "progress_percentage": 0.0,
                    "step_name": "Queued",
                }
            }
        )
        db.session.commit()

        job = db.session.get(ProcessingJob, result["job_id"])
        assert job is not None
        history = job.stage_history or []
        assert len(history) == 1
        assert history[0]["step"] == 0
        assert history[0]["step_name"] == "Queued"
        seeded_at = datetime.fromisoformat(history[0]["started_at"])
        assert seeded_at >= before - timedelta(seconds=2)


def test_update_job_status_appends_on_step_change(app) -> None:
    with app.app_context():
        post = _make_post("step-append")
        result = create_job_action(
            {
                "job_data": {
                    "post_guid": post.guid,
                    "status": "pending",
                    "current_step": 0,
                    "total_steps": 4,
                    "progress_percentage": 0.0,
                    "step_name": "Queued",
                }
            }
        )
        job_id = result["job_id"]
        db.session.commit()

        update_job_status_action(
            {
                "job_id": job_id,
                "status": "running",
                "step": 1,
                "step_name": "Downloading",
                "progress": 25.0,
            }
        )
        db.session.commit()

        update_job_status_action(
            {
                "job_id": job_id,
                "status": "running",
                "step": 1,
                "step_name": "Downloading (slow)",
                "progress": 30.0,
            }
        )
        db.session.commit()

        update_job_status_action(
            {
                "job_id": job_id,
                "status": "running",
                "step": 2,
                "step_name": "Transcribing audio",
                "progress": 50.0,
            }
        )
        db.session.commit()

        job = db.session.get(ProcessingJob, job_id)
        assert job is not None
        history = job.stage_history or []
        # Seed (0) + downloading (1) + transcribing (2). The duplicate step==1
        # update should NOT create a new entry.
        assert [entry["step"] for entry in history] == [0, 1, 2]
        assert history[1]["step_name"] == "Downloading"
        assert history[2]["step_name"] == "Transcribing audio"


def test_add_feed_action_seeds_queue_for_whitelisted_posts(app) -> None:
    with app.app_context():
        before = datetime.now(UTC).replace(tzinfo=None)
        result = add_feed_action(
            {
                "feed": {
                    "title": "Add Feed Test",
                    "description": "desc",
                    "author": "auth",
                    "rss_url": "https://example.com/add-feed.xml",
                },
                "posts": [
                    {
                        "guid": "add-feed-seed-1",
                        "title": "Seed 1",
                        "download_url": "https://example.com/seed1.mp3",
                        "whitelisted": True,
                    },
                    {
                        "guid": "add-feed-skip-1",
                        "title": "Skip 1",
                        "download_url": "https://example.com/skip1.mp3",
                        "whitelisted": False,
                    },
                ],
            }
        )
        db.session.commit()

        feed = db.session.get(Feed, result["feed_id"])
        assert feed is not None
        jobs = ProcessingJob.query.filter(
            ProcessingJob.post_guid.in_(["add-feed-seed-1", "add-feed-skip-1"])
        ).all()
        # Only the whitelisted post should have a job, and that job must carry
        # a seeded queue entry so its queue wait is measured.
        assert len(jobs) == 1
        job = jobs[0]
        assert job.post_guid == "add-feed-seed-1"
        history = job.stage_history or []
        assert len(history) == 1 and history[0]["step"] == 0
        seeded_at = datetime.fromisoformat(history[0]["started_at"])
        assert seeded_at >= before - timedelta(seconds=2)


def test_refresh_feed_action_seeds_queue_for_new_whitelisted_posts(app) -> None:
    with app.app_context():
        feed = Feed(
            title="Refresh Seed Test",
            description="d",
            author="a",
            rss_url="https://example.com/refresh-seed.xml",
        )
        db.session.add(feed)
        db.session.commit()

        before = datetime.now(UTC).replace(tzinfo=None)
        refresh_feed_action(
            {
                "feed_id": feed.id,
                "updates": {},
                "new_posts": [
                    {
                        "feed_id": feed.id,
                        "guid": "refresh-seed-1",
                        "title": "Refresh Seed 1",
                        "download_url": "https://example.com/refresh1.mp3",
                        "whitelisted": True,
                    }
                ],
                "existing_post_updates": [],
            }
        )
        db.session.commit()

        job = ProcessingJob.query.filter_by(post_guid="refresh-seed-1").one()
        history = job.stage_history or []
        assert len(history) == 1 and history[0]["step"] == 0
        seeded_at = datetime.fromisoformat(history[0]["started_at"])
        assert seeded_at >= before - timedelta(seconds=2)


def test_requeue_resets_stage_history(app) -> None:
    with app.app_context():
        post = _make_post("requeue-reset")
        post.unprocessed_audio_path = "/tmp/does-not-exist.mp3"
        post.processed_audio_path = None
        db.session.commit()

        create_result = create_job_action(
            {
                "job_data": {
                    "post_guid": post.guid,
                    "status": "pending",
                    "current_step": 0,
                    "total_steps": 4,
                    "step_name": "Queued",
                }
            }
        )
        job_id = create_result["job_id"]
        db.session.commit()

        # Drive the job through to a terminal failure so cleanup is eligible
        # to requeue it.
        update_job_status_action(
            {
                "job_id": job_id,
                "status": "running",
                "step": 2,
                "step_name": "Transcribing audio",
                "progress": 50.0,
            }
        )
        update_job_status_action(
            {
                "job_id": job_id,
                "status": "failed",
                "step": 2,
                "step_name": "Failed transcription",
                "progress": 50.0,
                "error_message": "boom",
            }
        )
        db.session.commit()

        before_requeue = datetime.now(UTC).replace(tzinfo=None)
        cleanup_missing_audio_paths_action({})
        db.session.commit()

        job = db.session.get(ProcessingJob, job_id)
        assert job is not None
        assert job.status == "pending"
        assert job.started_at is None
        assert job.completed_at is None
        history = job.stage_history or []
        # Stale entries from the prior run must be gone; we expect exactly one
        # fresh step-0 entry seeded from the requeue moment.
        assert len(history) == 1
        assert history[0]["step"] == 0
        seeded_at = datetime.fromisoformat(history[0]["started_at"])
        assert seeded_at >= before_requeue - timedelta(seconds=2)
