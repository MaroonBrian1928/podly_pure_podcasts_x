from __future__ import annotations

from unittest import mock

from app import background


def test_scheduled_memory_trim_calls_release_memory_to_os() -> None:
    with mock.patch.object(background, "release_memory_to_os") as release_mock:
        background.scheduled_memory_trim()

    release_mock.assert_called_once()
    context_arg = release_mock.call_args.args[0]
    assert "idle" in context_arg


def test_scheduled_memory_trim_logs_start_and_done() -> None:
    """Operators must be able to confirm fires via grep — INFO breadcrumbs
    are intentional. APScheduler swallows exceptions to its own (silenced)
    logger, so without these breadcrumbs the job was invisible.

    setup_logger marks the global_logger as `propagate=False`, so pytest's
    caplog (which hooks into root) can't see the records. Mock the logger
    directly and assert the calls landed.
    """
    with (
        mock.patch.object(background, "release_memory_to_os"),
        mock.patch.object(background, "_memory_trim_logger") as log_mock,
    ):
        background.scheduled_memory_trim()

    info_calls = [c.args[0] for c in log_mock.info.call_args_list]
    assert any("scheduled idle trim: starting" in m for m in info_calls)
    assert any("scheduled idle trim: done" in m for m in info_calls)
    log_mock.exception.assert_not_called()


def test_scheduled_memory_trim_logs_exception_and_swallows() -> None:
    with (
        mock.patch.object(
            background, "release_memory_to_os", side_effect=RuntimeError("boom")
        ),
        mock.patch.object(background, "_memory_trim_logger") as log_mock,
    ):
        # Must not raise — APScheduler would silently log the exception to
        # its own logger otherwise, and operators would never see it.
        background.scheduled_memory_trim()

    log_mock.exception.assert_called_once()
    assert "scheduled idle trim: failed" in log_mock.exception.call_args.args[0]
    # "done" must NOT be logged when release_memory_to_os failed.
    info_calls = [c.args[0] for c in log_mock.info.call_args_list]
    assert not any("scheduled idle trim: done" in m for m in info_calls)


def test_schedule_memory_trim_job_adds_job_with_env_interval(monkeypatch) -> None:
    monkeypatch.setenv("PODLY_MEMORY_TRIM_INTERVAL_MIN", "7")
    with mock.patch.object(background.scheduler, "add_job") as add_mock:
        background.schedule_memory_trim_job()

    add_mock.assert_called_once()
    kwargs = add_mock.call_args.kwargs
    assert kwargs["id"] == "memory_trim"
    assert kwargs["trigger"] == "interval"
    assert kwargs["minutes"] == 7
    assert kwargs["func"] is background.scheduled_memory_trim
    assert kwargs["replace_existing"] is True


def test_schedule_memory_trim_job_removes_job_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("PODLY_MEMORY_TRIM_INTERVAL_MIN", "0")
    with (
        mock.patch.object(background.scheduler, "add_job") as add_mock,
        mock.patch.object(background.scheduler, "remove_job") as remove_mock,
    ):
        background.schedule_memory_trim_job()

    add_mock.assert_not_called()
    remove_mock.assert_called_once_with("memory_trim")


def test_schedule_memory_trim_job_falls_back_to_default_for_bad_value(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PODLY_MEMORY_TRIM_INTERVAL_MIN", "not-a-number")
    with mock.patch.object(background.scheduler, "add_job") as add_mock:
        background.schedule_memory_trim_job()

    add_mock.assert_called_once()
    assert add_mock.call_args.kwargs["minutes"] == 15
