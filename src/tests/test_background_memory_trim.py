from __future__ import annotations

from unittest import mock

from app import background


def test_scheduled_memory_trim_calls_release_memory_to_os() -> None:
    with mock.patch.object(background, "release_memory_to_os") as release_mock:
        background.scheduled_memory_trim()

    release_mock.assert_called_once()
    context_arg = release_mock.call_args.args[0]
    assert "idle" in context_arg


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
