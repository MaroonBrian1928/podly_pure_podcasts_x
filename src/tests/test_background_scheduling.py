from unittest import mock

import pytest

from app import background


@pytest.mark.parametrize(
    ("register", "argument", "job_id", "callback", "interval_key", "interval"),
    [
        (
            background.add_background_job,
            10,
            "refresh_all_feeds",
            background.scheduled_refresh_all_feeds,
            "minutes",
            10,
        ),
        (
            background.schedule_cleanup_job,
            7,
            "cleanup_processed_posts",
            background.scheduled_cleanup_processed_posts,
            "hours",
            24,
        ),
    ],
)
def test_recurring_jobs_run_overdue_work_once(
    register, argument, job_id, callback, interval_key, interval
) -> None:
    """A busy shared executor must not discard refresh or daily cleanup work."""
    with mock.patch.object(background.scheduler, "add_job") as add_mock:
        register(argument)

    add_mock.assert_called_once()
    options = add_mock.call_args.kwargs
    assert options["id"] == job_id
    assert options["func"] is callback
    assert options["trigger"] == "interval"
    assert options[interval_key] == interval
    assert options["replace_existing"] is True
    assert options["misfire_grace_time"] is None
    assert options["coalesce"] is True
    assert options["max_instances"] == 1


@pytest.mark.parametrize("retention_days", [None, 0, -1])
def test_disabled_cleanup_removes_job(retention_days) -> None:
    with (
        mock.patch.object(background.scheduler, "add_job") as add_mock,
        mock.patch.object(background.scheduler, "remove_job") as remove_mock,
    ):
        background.schedule_cleanup_job(retention_days)

    add_mock.assert_not_called()
    remove_mock.assert_called_once_with("cleanup_processed_posts")
