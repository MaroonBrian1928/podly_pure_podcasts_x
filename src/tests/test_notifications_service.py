import logging
from types import SimpleNamespace
from unittest import mock

from app.notifications import NotificationService


def _settings(**overrides):
    base = {
        "enabled": True,
        "apprise_urls": ["json://localhost"],
        "notify_on_failure": True,
        "notify_on_success": True,
        "notify_on_rust_fallback": True,
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


def test_notify_success_sends_when_enabled():
    service = NotificationService(config=_config(_settings()))
    fake = mock.MagicMock()
    fake.add.return_value = True
    fake.notify.return_value = True
    with mock.patch("apprise.Apprise", return_value=fake):
        service.notify_processing_succeeded(
            post_guid="g",
            post_title="Ep 1",
            feed_title="Feed",
            ad_windows_count=3,
        )
    _, kwargs = fake.notify.call_args
    assert "Ep 1" in kwargs["title"]
    assert "Ad segments removed: 3" in kwargs["body"]


def test_notify_success_skipped_when_toggle_off():
    service = NotificationService(config=_config(_settings(notify_on_success=False)))
    with mock.patch("apprise.Apprise") as apprise_cls:
        service.notify_processing_succeeded(
            post_guid="g", post_title="t", feed_title="f", ad_windows_count=None
        )
    apprise_cls.assert_not_called()


def test_notify_rust_fallback_sends_and_throttles():
    import app.notifications as notif_mod

    # Reset throttle state so this test is deterministic.
    with notif_mod._throttle_lock:
        notif_mod._last_sent_at.clear()

    service = NotificationService(config=_config(_settings()))
    fake = mock.MagicMock()
    fake.add.return_value = True
    fake.notify.return_value = True
    with mock.patch("apprise.Apprise", return_value=fake):
        service.notify_rust_fallback(operation="stats render", error="boom")
        service.notify_rust_fallback(operation="stats render", error="boom again")
        service.notify_rust_fallback(operation="audio probe", error="different op")

    # Same operation is throttled (1 send), a different operation is not.
    titles = [c.kwargs["title"] for c in fake.notify.call_args_list]
    assert len(titles) == 2  # stats render (once) + audio probe (once)


def test_notify_rust_fallback_skipped_when_toggle_off():
    import app.notifications as notif_mod

    with notif_mod._throttle_lock:
        notif_mod._last_sent_at.clear()
    service = NotificationService(
        config=_config(_settings(notify_on_rust_fallback=False))
    )
    with mock.patch("apprise.Apprise") as apprise_cls:
        service.notify_rust_fallback(operation="stats render", error="boom")
    apprise_cls.assert_not_called()


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
