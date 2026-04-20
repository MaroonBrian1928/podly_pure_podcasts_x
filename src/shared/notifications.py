"""
Apprise API notification helper.

Sends notifications by POSTing to an Apprise API server:
  POST {apprise_url}/notify/{apprise_key}
  {"title": "...", "body": "...", "type": "success|failure"}

Both apprise_url and apprise_key must be non-empty for any notification to fire.
Uses stdlib urllib only — no new dependencies.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


def _format_processing_time(seconds: float | None) -> str | None:
    if seconds is None or seconds < 0:
        return None
    minutes, secs = divmod(int(round(seconds)), 60)
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def send_episode_notification(
    *,
    apprise_url: str,
    apprise_key: str,
    feed_title: str,
    episode_title: str,
    success: bool,
    error_message: str | None = None,
    tag_label: str,
    processing_time_seconds: float | None = None,
) -> None:
    """Send an episode processing notification via the Apprise API.

    Does nothing (silently) if either apprise_url or apprise_key is empty.
    Network errors are logged as warnings and swallowed so they never
    interrupt the processing pipeline.
    """
    if not apprise_url or not apprise_key:
        return

    # Validate scheme to prevent SSRF to internal or non-HTTP targets.
    parsed = urllib.parse.urlparse(apprise_url)
    if parsed.scheme not in ("http", "https"):
        logger.warning(
            "Apprise URL has disallowed scheme %r; notification skipped", parsed.scheme
        )
        return

    # URL-encode the key so path separators / query chars don't rewrite the request.
    safe_key = urllib.parse.quote(apprise_key.strip(), safe="")
    notify_url = apprise_url.rstrip("/") + "/notify/" + safe_key

    label = tag_label.strip()
    status_icon = "✅" if success else "⚠️"
    prefix = f"{label}: " if label else ""
    title = f"{prefix}{status_icon} {feed_title}"

    time_str = _format_processing_time(processing_time_seconds)
    body = f"Episode: {episode_title}"
    if time_str:
        body += f" | Processing time: {time_str}"
    if not success and error_message:
        body += f"\nError: {error_message}"

    msg_type = "success" if success else "failure"

    payload = json.dumps({"title": title, "body": body, "type": msg_type}).encode()

    req = urllib.request.Request(
        notify_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            if status >= 300:
                logger.warning(
                    "Apprise notification returned unexpected status %s for %s/%s",
                    status,
                    feed_title,
                    episode_title,
                )
            else:
                logger.debug(
                    "Apprise notification sent (%s) for %s/%s",
                    status,
                    feed_title,
                    episode_title,
                )
    except urllib.error.URLError as exc:
        logger.warning(
            "Apprise notification failed for %s/%s: %s",
            feed_title,
            episode_title,
            exc,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Apprise notification unexpected error for %s/%s: %s",
            feed_title,
            episode_title,
            exc,
        )
