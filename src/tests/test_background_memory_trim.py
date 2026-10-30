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
    # A late trim is still useful — must not inherit APScheduler's 1s default
    # misfire_grace_time, which caused the job to silently skip whenever the
    # scheduler was busy (e.g. mid refresh-all batch).
    assert kwargs["misfire_grace_time"] is None
    assert kwargs["coalesce"] is True


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


def test_cut_window_backfill_job_registered_once_with_fixed_id() -> None:
    with mock.patch.object(background, "scheduler") as sched:
        background.schedule_cut_window_backfill_job()
        background.schedule_cut_window_backfill_job()

    for call in sched.add_job.call_args_list:
        assert call.kwargs["id"] == "backfill_cut_windows"
        assert call.kwargs["trigger"] == "date"
        assert call.kwargs["replace_existing"] is True


def test_cut_window_backfill_job_runs_apply_and_swallows_errors() -> None:
    with (
        mock.patch.object(background, "scheduler") as sched,
        mock.patch(
            "app.cut_stats.backfill_cut_windows", return_value={"stored": 1}
        ) as backfill,
    ):
        background.scheduled_cut_window_backfill()
        backfill.assert_called_once_with(apply=True)
        sched.app.app_context.assert_called_once()

        backfill.side_effect = RuntimeError("boom")
        background.scheduled_cut_window_backfill()


def _run_compression(result: dict[str, int] | Exception) -> mock.MagicMock:
    with (
        mock.patch.object(background, "scheduler") as sched,
        mock.patch(
            "app.word_timestamp_compression.compress_word_timestamps",
            side_effect=[result] if isinstance(result, Exception) else None,
            return_value=None if isinstance(result, Exception) else result,
        ) as compress,
    ):
        background.scheduled_word_timestamp_compression()
    compress.assert_called_once_with(
        apply=True, limit=background.WORD_TIMESTAMP_COMPRESSION_BATCH_SIZE
    )
    return sched


def test_word_timestamp_compression_schedules_the_next_batch() -> None:
    sched = _run_compression({"candidates": 200, "compressed": 190, "failed": 10})

    call = sched.add_job.call_args
    assert call.kwargs["id"] == "compress_word_timestamps"
    assert call.kwargs["trigger"] == "date"


def test_word_timestamp_compression_stops_after_a_partial_batch() -> None:
    sched = _run_compression({"candidates": 37, "compressed": 37, "failed": 0})

    sched.add_job.assert_not_called()


def test_word_timestamp_compression_stops_when_a_full_batch_made_no_progress() -> None:
    sched = _run_compression({"candidates": 200, "compressed": 0, "failed": 200})

    sched.add_job.assert_not_called()


def test_word_timestamp_compression_does_not_reschedule_after_an_error() -> None:
    sched = _run_compression(RuntimeError("boom"))

    sched.add_job.assert_not_called()
