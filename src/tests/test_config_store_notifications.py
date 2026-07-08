from typing import Any

from app.extensions import db
from app.models import NotificationSettings
from shared import defaults as DEFAULTS


def test_notifications_defaults_exposed(app: Any) -> None:
    with app.app_context():
        app.config["PODLY_APP_ROLE"] = "writer"

        from app.config_store import read_combined

        payload = read_combined()

    notif = payload["notifications"]
    assert notif["enabled"] == DEFAULTS.NOTIFY_ENABLED
    assert notif["apprise_urls"] == []
    assert notif["notify_on_failure"] == DEFAULTS.NOTIFY_ON_FAILURE
    assert notif["include_llm_explanation"] == DEFAULTS.NOTIFY_INCLUDE_LLM_EXPLANATION


def test_notifications_update_roundtrip(app: Any) -> None:
    with app.app_context():
        app.config["PODLY_APP_ROLE"] = "writer"

        from app.config_store import read_combined, to_pydantic_config, update_combined

        read_combined()
        payload = update_combined(
            {
                "notifications": {
                    "enabled": True,
                    "apprise_urls": [
                        "ntfy://ntfy.sh/topic",
                        "  ",  # blank -> dropped
                        "json://localhost",
                    ],
                    "notify_on_failure": True,
                    "notify_on_success": True,
                    "notify_on_rust_fallback": True,
                    "include_llm_explanation": False,
                }
            }
        )

        row = db.session.get(NotificationSettings, 1)
        assert row is not None
        stored_urls = row.apprise_urls
        stored_enabled = row.enabled

        cfg = to_pydantic_config()

    assert payload["notifications"]["enabled"] is True
    assert payload["notifications"]["apprise_urls"] == [
        "ntfy://ntfy.sh/topic",
        "json://localhost",
    ]
    assert payload["notifications"]["include_llm_explanation"] is False
    # Persisted as newline-joined text with blanks removed.
    assert stored_urls == "ntfy://ntfy.sh/topic\njson://localhost"
    assert stored_enabled is True

    # Runtime Pydantic config carries the notification settings.
    assert cfg.notifications.enabled is True
    assert cfg.notifications.apprise_urls == [
        "ntfy://ntfy.sh/topic",
        "json://localhost",
    ]
    assert cfg.notifications.notify_on_success is True
    assert cfg.notifications.notify_on_rust_fallback is True
    assert cfg.notifications.include_llm_explanation is False


def test_notifications_accepts_newline_string(app: Any) -> None:
    with app.app_context():
        app.config["PODLY_APP_ROLE"] = "writer"

        from app.config_store import read_combined, update_combined

        read_combined()
        payload = update_combined(
            {"notifications": {"apprise_urls": "a://one\n\nb://two\n"}}
        )

    assert payload["notifications"]["apprise_urls"] == ["a://one", "b://two"]
