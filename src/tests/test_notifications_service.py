import logging
from types import SimpleNamespace
from unittest import mock

from app.notifications import NotificationService


def _settings(**overrides):
    base = {
        "enabled": True,
        "apprise_urls": ["json://localhost"],
        "notify_on_failure": True,
        "include_llm_explanation": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _config(settings, *, llm_api_key="sk-test"):
    return SimpleNamespace(notifications=settings, llm_api_key=llm_api_key)


def test_notify_failure_includes_llm_explanation():
    cfg = _config(_settings())
    service = NotificationService(config=cfg)

    fake_apprise = mock.MagicMock()
    fake_apprise.add.return_value = True
    fake_apprise.notify.return_value = True

    with (
        mock.patch("apprise.Apprise", return_value=fake_apprise),
        mock.patch(
            "app.failure_explainer.build_troubleshoot_context",
            return_value="ConnectionError traceback",
        ),
        mock.patch(
            "app.failure_explainer.explain_failure",
            return_value="Your Whisper server refused the connection.",
        ),
    ):
        service.notify_processing_failed(
            post_guid="guid-1",
            post_id=7,
            post_title="Episode 42",
            feed_title="My Feed",
            step_name="Transcribing audio",
            error_message="Unexpected error: Connection error.",
            job_id="job-1",
        )

    assert fake_apprise.notify.called
    _, kwargs = fake_apprise.notify.call_args
    assert "Episode 42" in kwargs["title"]
    assert "My Feed" in kwargs["body"]
    assert "Transcribing audio" in kwargs["body"]
    assert "Connection error." in kwargs["body"]
    assert "Your Whisper server refused the connection." in kwargs["body"]


def test_notify_failure_omits_explanation_when_disabled():
    cfg = _config(_settings(include_llm_explanation=False))
    service = NotificationService(config=cfg)

    fake_apprise = mock.MagicMock()
    fake_apprise.add.return_value = True
    fake_apprise.notify.return_value = True

    with (
        mock.patch("apprise.Apprise", return_value=fake_apprise),
        mock.patch("app.failure_explainer.explain_failure") as explain,
    ):
        service.notify_processing_failed(
            post_guid="guid-1",
            post_id=7,
            post_title="Episode 42",
            feed_title="My Feed",
            step_name="Transcribing audio",
            error_message="boom",
            job_id="job-1",
        )

    explain.assert_not_called()
    _, kwargs = fake_apprise.notify.call_args
    assert "Likely cause" not in kwargs["body"]


def test_notify_failure_disabled_sends_nothing():
    cfg = _config(_settings(enabled=False))
    service = NotificationService(config=cfg)
    with mock.patch("apprise.Apprise") as apprise_cls:
        service.notify_processing_failed(
            post_guid="g",
            post_id=1,
            post_title="t",
            feed_title="f",
            step_name=None,
            error_message="e",
            job_id=None,
        )
    apprise_cls.assert_not_called()


def test_notify_failure_swallows_apprise_errors():
    cfg = _config(_settings())
    service = NotificationService(config=cfg)
    with (
        mock.patch("apprise.Apprise", side_effect=RuntimeError("boom")),
        mock.patch(
            "app.failure_explainer.build_troubleshoot_context", return_value=None
        ),
    ):
        # Must not raise.
        service.notify_processing_failed(
            post_guid="g",
            post_id=1,
            post_title="t",
            feed_title="f",
            step_name=None,
            error_message="e",
            job_id=None,
        )


def test_notify_failure_swallows_explainer_errors():
    cfg = _config(_settings())
    service = NotificationService(config=cfg)

    fake_apprise = mock.MagicMock()
    fake_apprise.add.return_value = True
    fake_apprise.notify.return_value = True

    with (
        mock.patch("apprise.Apprise", return_value=fake_apprise),
        mock.patch(
            "app.failure_explainer.build_troubleshoot_context",
            side_effect=RuntimeError("llm down"),
        ),
    ):
        service.notify_processing_failed(
            post_guid="g",
            post_id=1,
            post_title="t",
            feed_title="f",
            step_name=None,
            error_message="raw error",
            job_id=None,
        )

    # Still sent the notification with the raw error, no explanation.
    _, kwargs = fake_apprise.notify.call_args
    assert "raw error" in kwargs["body"]
    assert "Likely cause" not in kwargs["body"]


def test_send_test_reports_no_urls():
    service = NotificationService(config=_config(_settings(apprise_urls=[])))
    ok, error = service.send_test(None)
    assert ok is False
    assert error


def test_send_test_success():
    service = NotificationService(config=_config(_settings()))
    fake_apprise = mock.MagicMock()
    fake_apprise.add.return_value = True
    fake_apprise.notify.return_value = True
    with mock.patch("apprise.Apprise", return_value=fake_apprise):
        ok, error = service.send_test(["json://localhost"])
    assert ok is True
    assert error is None


def test_processor_notify_helper_swallows_errors():
    # Exercise PodcastProcessor._notify_processing_failed without constructing a
    # full processor: it only needs `self.logger` and forwards to the service.
    from typing import cast

    from podcast_processor.podcast_processor import PodcastProcessor

    fake_self = cast(
        PodcastProcessor, SimpleNamespace(logger=logging.getLogger("test"))
    )
    with mock.patch(
        "app.notifications.notification_service.notify_processing_failed",
        side_effect=RuntimeError("boom"),
    ) as notify:
        # Bound-method call via the class; must not raise.
        PodcastProcessor._notify_processing_failed(
            fake_self,
            post_guid="g",
            post_id=1,
            post_title="t",
            feed_title="f",
            step_name="Transcribing audio",
            error_message="e",
            job_id="j",
        )
    notify.assert_called_once()
