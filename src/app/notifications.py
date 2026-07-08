"""Apprise-backed notifications for operational events.

Global, admin-configured notifications (one set of Apprise target URLs) driven
by the runtime ``NotificationConfig``. Everything here is best-effort: a failing
notification (bad URL, unreachable endpoint, import error, LLM hiccup) must never
affect the outcome of the job that triggered it, so every public entry point
swallows and logs its own exceptions.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.runtime_config import config as runtime_config
from shared import defaults as DEFAULTS

logger = logging.getLogger("global_logger")

# Per-process throttle for high-frequency events (keyed by event+operation).
_throttle_lock = threading.Lock()
_last_sent_at: dict[str, float] = {}


def _throttled(key: str, min_interval_sec: float) -> bool:
    """Return True if a notification for ``key`` was sent within the window.

    Records ``now`` as the last-sent time when it returns False (i.e. when the
    caller is cleared to send).
    """
    now = time.monotonic()
    with _throttle_lock:
        last = _last_sent_at.get(key)
        if last is not None and (now - last) < min_interval_sec:
            return True
        _last_sent_at[key] = now
        return False


def _resolve_config(config: Any | None) -> Any:
    return config if config is not None else runtime_config


def _notification_settings(config: Any | None) -> Any | None:
    cfg = _resolve_config(config)
    return getattr(cfg, "notifications", None)


def _dispatch(urls: list[str], *, title: str, body: str) -> tuple[bool, str | None]:
    """Send one notification to every configured Apprise URL.

    Returns ``(ok, error)``. ``apprise`` is imported lazily so cold paths that
    never notify don't pay the import cost.
    """
    urls = [u for u in urls if u and u.strip()]
    if not urls:
        return False, "No Apprise URLs configured"

    try:
        import apprise
    except Exception as exc:  # noqa: BLE001 - defensive: optional at runtime
        logger.error("apprise import failed; cannot send notification: %s", exc)
        return False, f"apprise unavailable: {exc}"

    apobj = apprise.Apprise()
    added = 0
    for url in urls:
        if apobj.add(url.strip()):
            added += 1
        else:
            logger.warning("Ignoring invalid Apprise URL (failed to parse)")

    if added == 0:
        return False, "No valid Apprise URLs could be added"

    ok = bool(apobj.notify(title=title, body=body))
    if not ok:
        return False, "Apprise reported the notification was not delivered"
    return True, None


class NotificationService:
    """Sends operational notifications via Apprise."""

    def __init__(self, config: Any | None = None) -> None:
        self._config = config

    # -- Failure notifications -------------------------------------------------

    def notify_processing_failed(
        self,
        *,
        post_guid: str,
        post_id: int | None,
        post_title: str | None,
        feed_title: str | None,
        step_name: str | None,
        error_message: str,
        job_id: str | None = None,
    ) -> None:
        """Notify that an episode failed to process.

        Includes the raw error and, when ``include_llm_explanation`` is enabled,
        the plain-English LLM root cause (the same analysis as the Troubleshoot
        button). Entirely best-effort.
        """
        try:
            settings = _notification_settings(self._config)
            if settings is None:
                return
            if not getattr(settings, "enabled", False):
                return
            if not getattr(settings, "notify_on_failure", False):
                return

            urls = list(getattr(settings, "apprise_urls", []) or [])
            if not urls:
                logger.warning(
                    "Notifications enabled but no Apprise URLs configured; "
                    "skipping failure notification for post %s",
                    post_guid,
                )
                return

            episode = post_title or post_guid
            feed = feed_title or "Unknown feed"
            title = f'❌ Podly: "{episode}" failed to process'

            body_lines = [
                f"Feed: {feed}",
                f"Episode: {episode}",
            ]
            if step_name:
                body_lines.append(f"Failed at: {step_name}")
            body_lines.append(f"Error: {error_message}")

            explanation = None
            if (
                getattr(settings, "include_llm_explanation", False)
                and post_id is not None
            ):
                explanation = self._build_explanation(
                    post_guid=post_guid,
                    post_id=post_id,
                    job_id=job_id,
                )
            if explanation:
                body_lines.append("")
                body_lines.append("Likely cause (AI):")
                body_lines.append(explanation)

            ok, error = _dispatch(urls, title=title, body="\n".join(body_lines))
            if ok:
                logger.info(
                    "Sent processing-failed notification for post %s", post_guid
                )
            else:
                logger.warning(
                    "Failed to send processing-failed notification for post %s: %s",
                    post_guid,
                    error,
                )
        except Exception:
            logger.exception(
                "Unexpected error while sending failure notification for post %s",
                post_guid,
            )

    def _build_explanation(
        self, *, post_guid: str, post_id: int, job_id: str | None
    ) -> str | None:
        """Run the LLM troubleshoot analysis; return None on any problem."""
        try:
            from app.failure_explainer import (
                build_troubleshoot_context,
                explain_failure,
            )

            cfg = _resolve_config(self._config)
            if not getattr(cfg, "llm_api_key", None):
                return None

            job_ids = {job_id} if job_id else set()
            context = build_troubleshoot_context(
                post_guid=post_guid,
                post_id=post_id,
                job_ids=job_ids,
                target_job_id=job_id,
            )
            if not context:
                return None
            return explain_failure(context, cfg) or None
        except Exception:
            logger.exception(
                "Failed to build LLM failure explanation for post %s", post_guid
            )
            return None

    def notify_processing_succeeded(
        self,
        *,
        post_guid: str,
        post_title: str | None,
        feed_title: str | None,
        ad_windows_count: int | None = None,
    ) -> None:
        """Notify that an episode finished processing successfully. Best-effort."""
        try:
            settings = _notification_settings(self._config)
            if settings is None or not getattr(settings, "enabled", False):
                return
            if not getattr(settings, "notify_on_success", False):
                return

            urls = list(getattr(settings, "apprise_urls", []) or [])
            if not urls:
                return

            episode = post_title or post_guid
            feed = feed_title or "Unknown feed"
            title = f'✅ Podly: "{episode}" processed'
            body_lines = [f"Feed: {feed}", f"Episode: {episode}"]
            if ad_windows_count is not None:
                body_lines.append(f"Ad segments removed: {ad_windows_count}")

            ok, error = _dispatch(urls, title=title, body="\n".join(body_lines))
            if not ok:
                logger.warning(
                    "Failed to send processing-succeeded notification for post %s: %s",
                    post_guid,
                    error,
                )
        except Exception:
            logger.exception(
                "Unexpected error while sending success notification for post %s",
                post_guid,
            )

    def notify_rust_fallback(self, *, operation: str, error: str) -> None:
        """Notify that the Rust sidecar failed and Podly fell back to Python.

        Throttled per operation because this can fire very frequently (e.g. a
        broken binary hit on every request). Best-effort.
        """
        try:
            settings = _notification_settings(self._config)
            if settings is None or not getattr(settings, "enabled", False):
                return
            if not getattr(settings, "notify_on_rust_fallback", False):
                return

            urls = list(getattr(settings, "apprise_urls", []) or [])
            if not urls:
                return

            if _throttled(
                f"rust_fallback:{operation}",
                DEFAULTS.NOTIFY_RUST_FALLBACK_THROTTLE_SEC,
            ):
                return

            title = "⚠️ Podly: Rust sidecar fell back to Python"
            body = (
                f"Operation: {operation}\n"
                f"Error: {error}\n\n"
                "Podly automatically used the Python implementation, so "
                "processing still works, but the faster Rust path is failing. "
                "Check the sidecar binary/logs. (Further alerts for this "
                "operation are throttled.)"
            )
            ok, err = _dispatch(urls, title=title, body=body)
            if not ok:
                logger.warning("Failed to send rust-fallback notification: %s", err)
        except Exception:
            logger.exception(
                "Unexpected error while sending rust-fallback notification"
            )

    # -- Test send -------------------------------------------------------------

    def send_test(self, urls: list[str] | None = None) -> tuple[bool, str | None]:
        """Send a test notification. Returns ``(ok, error)``."""
        settings = _notification_settings(self._config)
        if urls:
            target_urls = list(urls)
        elif settings is not None:
            target_urls = list(getattr(settings, "apprise_urls", []) or [])
        else:
            target_urls = []
        try:
            return _dispatch(
                target_urls,
                title="✅ Podly test notification",
                body="This is a test notification from Podly. If you can read "
                "this, your Apprise configuration works.",
            )
        except Exception as exc:
            logger.exception("Test notification failed")
            return False, str(exc)


# Module-level singleton for convenient dispatch from the processing worker.
notification_service = NotificationService()
