from typing import Any
from unittest import mock


def _client(app: Any):
    app.testing = True
    from app.routes.config_routes import config_bp

    app.register_blueprint(config_bp)
    return app.test_client()


def test_test_notification_success(app: Any) -> None:
    with app.app_context():
        client = _client(app)
        with mock.patch(
            "app.notifications.notification_service.send_test",
            return_value=(True, None),
        ) as send_test:
            resp = client.post(
                "/api/config/test-notification",
                json={"notifications": {"apprise_urls": ["json://localhost"]}},
            )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    send_test.assert_called_once_with(["json://localhost"])


def test_test_notification_error(app: Any) -> None:
    with app.app_context():
        client = _client(app)
        with mock.patch(
            "app.notifications.notification_service.send_test",
            return_value=(False, "No Apprise URLs configured"),
        ):
            resp = client.post("/api/config/test-notification", json={})

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert "No Apprise URLs" in body["error"]
