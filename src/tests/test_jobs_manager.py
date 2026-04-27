from __future__ import annotations

import os
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import cast

import app.jobs_manager as jobs_manager_module
from app.extensions import db
from app.jobs_manager import JobsManager
from app.models import Feed, Post, ProcessingJob


def _create_feed() -> Feed:
    feed = Feed(
        title="Test Feed",
        rss_url="https://example.com/feed.xml",
    )
    db.session.add(feed)
    db.session.commit()
    return feed


def _create_post(
    *,
    feed_id: int,
    guid: str,
    download_url: str,
    whitelisted: bool,
    processed_audio_path: str | None,
) -> Post:
    post = Post(
        feed_id=feed_id,
        guid=guid,
        download_url=download_url,
        title=guid,
        whitelisted=whitelisted,
        processed_audio_path=processed_audio_path,
    )
    db.session.add(post)
    db.session.commit()
    return post


def test_ensure_jobs_skips_whitelisted_posts_with_existing_processed_audio(
    app, monkeypatch, tmp_path: Path
) -> None:
    feed = _create_feed()

    processed_file = tmp_path / "processed.mp3"
    processed_file.write_bytes(b"test")

    processed_post = _create_post(
        feed_id=feed.id,
        guid="processed-guid",
        download_url="https://example.com/processed.mp3",
        whitelisted=True,
        processed_audio_path=str(processed_file),
    )
    unprocessed_post = _create_post(
        feed_id=feed.id,
        guid="unprocessed-guid",
        download_url="https://example.com/unprocessed.mp3",
        whitelisted=True,
        processed_audio_path=None,
    )
    _create_post(
        feed_id=feed.id,
        guid="not-whitelisted-guid",
        download_url="https://example.com/not-whitelisted.mp3",
        whitelisted=False,
        processed_audio_path=None,
    )

    created_guids: list[str] = []

    class FakeSingleJobManager:
        def __init__(self, post_guid: str, *_args, **_kwargs) -> None:
            self.post_guid = post_guid

        def ensure_job(self) -> None:
            created_guids.append(self.post_guid)

    monkeypatch.setattr(jobs_manager_module, "SingleJobManager", FakeSingleJobManager)

    manager = JobsManager.__new__(JobsManager)
    manager._status_manager = object()
    created = manager._ensure_jobs_for_all_posts("run-id")

    assert created == 1
    assert created_guids == [unprocessed_post.guid]
    assert processed_post.guid not in created_guids


def test_ensure_jobs_creates_job_when_processed_path_is_missing_file(
    app, monkeypatch, tmp_path: Path
) -> None:
    feed = _create_feed()

    missing_processed_path = tmp_path / "missing.mp3"
    post = _create_post(
        feed_id=feed.id,
        guid="missing-file-guid",
        download_url="https://example.com/missing-file.mp3",
        whitelisted=True,
        processed_audio_path=str(missing_processed_path),
    )

    created_guids: list[str] = []

    class FakeSingleJobManager:
        def __init__(self, post_guid: str, *_args, **_kwargs) -> None:
            self.post_guid = post_guid

        def ensure_job(self) -> None:
            created_guids.append(self.post_guid)

    monkeypatch.setattr(jobs_manager_module, "SingleJobManager", FakeSingleJobManager)

    manager = JobsManager.__new__(JobsManager)
    manager._status_manager = object()
    created = manager._ensure_jobs_for_all_posts("run-id")

    assert created == 1
    assert created_guids == [post.guid]


class FakeStatusManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int, str, float | None]] = []

    def update_job_status(
        self,
        job: ProcessingJob,
        status: str,
        step: int,
        step_name: str,
        progress: float | None = None,
    ) -> None:
        self.calls.append((job.id, status, step, step_name, progress))


class FakeProcess:
    pid = 1234

    def __init__(self, exit_code: int | None = 0) -> None:
        self.exit_code = exit_code
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True
        self.exit_code = -15

    def kill(self) -> None:
        self.killed = True
        self.exit_code = -9

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.exit_code if self.exit_code is not None else 0


def _create_job(post_guid: str, status: str = "running") -> ProcessingJob:
    job = ProcessingJob(
        id=f"job-{post_guid}",
        post_guid=post_guid,
        status=status,
        current_step=2,
        progress_percentage=50.0,
    )
    db.session.add(job)
    db.session.commit()
    return job


def _manager() -> tuple[JobsManager, FakeStatusManager]:
    status_manager = FakeStatusManager()
    manager = JobsManager.__new__(JobsManager)
    manager._status_manager = status_manager
    return manager, status_manager


def test_process_job_spawns_expected_processing_worker_command(
    app, monkeypatch
) -> None:
    job = _create_job("spawn-guid")
    job_id = job.id
    manager, status_manager = _manager()
    launched: dict[str, object] = {}

    def fake_popen(command, env=None):
        launched["command"] = command
        launched["env"] = env
        return FakeProcess(0)

    monkeypatch.setattr(jobs_manager_module, "_scheduler_app_context", nullcontext)
    monkeypatch.setattr(jobs_manager_module.subprocess, "Popen", fake_popen)

    manager._process_job(job_id, "spawn-guid")

    assert launched["command"] == [
        sys.executable,
        "-m",
        "app.processing_worker",
        "--job-id",
        job_id,
        "--post-guid",
        "spawn-guid",
    ]
    env = cast(dict[str, str], launched["env"])
    assert "PYTHONPATH" in env
    assert str(Path(jobs_manager_module.__file__).resolve().parents[1]) in env[
        "PYTHONPATH"
    ].split(os.pathsep)
    assert status_manager.calls == []


def test_nonzero_processing_worker_exit_marks_nonterminal_job_failed(
    app, monkeypatch
) -> None:
    job = _create_job("nonzero-guid", status="running")
    job_id = job.id
    manager, status_manager = _manager()

    monkeypatch.setattr(jobs_manager_module, "_scheduler_app_context", nullcontext)
    monkeypatch.setattr(
        jobs_manager_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FakeProcess(7),
    )

    manager._process_job(job_id, "nonzero-guid")

    assert status_manager.calls == [
        (
            job_id,
            "failed",
            2,
            "Processing worker exited with status 7",
            50.0,
        )
    ]


def test_nonzero_processing_worker_exit_leaves_terminal_job_alone(
    app, monkeypatch
) -> None:
    job = _create_job("terminal-guid", status="completed")
    job_id = job.id
    manager, status_manager = _manager()

    monkeypatch.setattr(jobs_manager_module, "_scheduler_app_context", nullcontext)
    monkeypatch.setattr(
        jobs_manager_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FakeProcess(7),
    )

    manager._process_job(job_id, "terminal-guid")

    assert status_manager.calls == []


def test_cancelled_job_terminates_processing_worker(monkeypatch) -> None:
    manager, _status_manager = _manager()
    process = FakeProcess(None)
    statuses = iter([None, "cancelled"])

    monkeypatch.setattr(manager, "_job_status", lambda _job_id: next(statuses))
    monkeypatch.setattr(jobs_manager_module.time, "sleep", lambda _seconds: None)

    exit_code = manager._wait_for_processing_worker(
        process, "cancel-job", "cancel-guid"
    )

    assert exit_code == -15
    assert process.terminated is True
    assert process.killed is False


def test_process_job_trims_web_memory_after_worker_exit(app, monkeypatch) -> None:
    job = _create_job("trim-guid")
    job_id = job.id
    manager, _status_manager = _manager()
    trim_contexts: list[str] = []

    monkeypatch.setattr(jobs_manager_module, "_scheduler_app_context", nullcontext)
    monkeypatch.setattr(
        jobs_manager_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: FakeProcess(0),
    )
    monkeypatch.setattr(
        jobs_manager_module,
        "release_memory_to_os",
        lambda context, _logger: trim_contexts.append(context),
    )

    manager._process_job(job_id, "trim-guid")

    assert trim_contexts == [f"web supervisor after processing job {job_id}"]
