from __future__ import annotations

from collections.abc import Callable
from typing import cast

from app import processing_worker
from app.extensions import db
from app.models import Feed, Post, ProcessingJob


class RecordingStatusManager:
    calls: list[tuple[str, str, int, str, float | None]] = []

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def update_job_status(
        self,
        job: ProcessingJob,
        status: str,
        step: int,
        step_name: str,
        progress: float | None = None,
    ) -> None:
        self.calls.append((job.id, status, step, step_name, progress))


class NoopProcessor:
    def process(self, *_args, **_kwargs) -> None:
        pass


def _create_post(guid: str = "post-guid") -> Post:
    feed = Feed(title="Test Feed", rss_url=f"https://example.com/{guid}.xml")
    db.session.add(feed)
    db.session.flush()
    post = Post(
        feed_id=feed.id,
        guid=guid,
        download_url=f"https://example.com/{guid}.mp3",
        title=guid,
        whitelisted=True,
    )
    db.session.add(post)
    db.session.commit()
    return post


def _create_job(post_guid: str, status: str = "running") -> ProcessingJob:
    job = ProcessingJob(id=f"job-{post_guid}", post_guid=post_guid, status=status)
    db.session.add(job)
    db.session.commit()
    return job


def _patch_worker_app(app, monkeypatch) -> None:
    monkeypatch.setattr(processing_worker, "create_processing_app", lambda: app)
    RecordingStatusManager.calls = []
    monkeypatch.setattr(
        processing_worker, "ProcessingStatusManager", RecordingStatusManager
    )


def test_missing_post_marks_job_failed(app, monkeypatch) -> None:
    _patch_worker_app(app, monkeypatch)
    job = _create_job("missing-guid")

    exit_code = processing_worker.run_processing_job(
        job.id,
        "missing-guid",
        processor_factory=NoopProcessor,
    )

    assert exit_code == 1
    assert RecordingStatusManager.calls == [
        (job.id, "failed", 0, "Post not found", 0.0)
    ]


def test_successful_processor_call_exits_cleanly(app, monkeypatch) -> None:
    _patch_worker_app(app, monkeypatch)
    post = _create_post("success-guid")
    job = _create_job(post.guid)
    calls: list[tuple[str, str, bool]] = []

    class FakeProcessor:
        def process(
            self,
            received_post: Post,
            *,
            job_id: str,
            cancel_callback: Callable[[], bool],
        ) -> None:
            calls.append((received_post.guid, job_id, cancel_callback()))

    def fake_processor_factory() -> processing_worker.Processor:
        return cast(processing_worker.Processor, FakeProcessor())

    exit_code = processing_worker.run_processing_job(
        job.id,
        post.guid,
        processor_factory=fake_processor_factory,
    )

    assert exit_code == 0
    assert calls == [(post.guid, job.id, False)]
    assert RecordingStatusManager.calls == []


def test_processor_exception_does_not_double_fail_terminal_job(
    app, monkeypatch
) -> None:
    _patch_worker_app(app, monkeypatch)
    post = _create_post("terminal-guid")
    job = _create_job(post.guid, status="completed")

    class FakeProcessor:
        def process(self, *_args, **_kwargs) -> None:
            raise RuntimeError("processor already handled status")

    def fake_processor_factory() -> processing_worker.Processor:
        return FakeProcessor()

    exit_code = processing_worker.run_processing_job(
        job.id,
        post.guid,
        processor_factory=fake_processor_factory,
    )

    assert exit_code == 0
    assert RecordingStatusManager.calls == []


def test_unexpected_exception_marks_nonterminal_job_failed(app, monkeypatch) -> None:
    _patch_worker_app(app, monkeypatch)
    post = _create_post("failure-guid")
    job = _create_job(post.guid, status="running")

    class FakeProcessor:
        def process(self, *_args, **_kwargs) -> None:
            raise RuntimeError("boom")

    def fake_processor_factory() -> processing_worker.Processor:
        return FakeProcessor()

    exit_code = processing_worker.run_processing_job(
        job.id,
        post.guid,
        processor_factory=fake_processor_factory,
    )

    assert exit_code == 1
    assert RecordingStatusManager.calls == [
        (job.id, "failed", 0, "Job execution failed: boom", 0.0)
    ]
