"""One-shot bootstrap must not start a competing runtime writer or web app."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import flask_migrate
import pytest

import app as app_module
from app.auth.settings import AuthSettings


def test_bootstrap_factory_runs_strict_startup_without_http_or_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup_calls: list[bool] = []

    def startup(_settings: object, *, fail_on_settings_error: bool = False) -> None:
        startup_calls.append(fail_on_settings_error)

    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail("one-shot bootstrap must not start HTTP or the scheduler")

    monkeypatch.setattr(app_module, "_run_app_startup", startup)
    monkeypatch.setattr(app_module, "_start_scheduler_and_jobs", unexpected)
    monkeypatch.setattr(app_module, "_register_routes_and_middleware", unexpected)
    monkeypatch.setattr(
        app_module, "load_discord_settings", lambda: SimpleNamespace(enabled=False)
    )

    app = app_module.create_bootstrap_app()

    assert app.config["PODLY_APP_ROLE"] == "bootstrap"
    assert startup_calls == [True]
    assert "migrate" in app.extensions


def test_strict_bootstrap_propagates_settings_initialization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(flask_migrate, "upgrade", lambda: None)
    monkeypatch.setattr(app_module, "bootstrap_admin_user", lambda _settings: None)

    def fail_defaults() -> None:
        raise RuntimeError("synthetic settings failure")

    monkeypatch.setattr(app_module, "ensure_defaults_and_hydrate", fail_defaults)

    with pytest.raises(RuntimeError, match="synthetic settings failure"):
        app_module._run_app_startup(
            cast(AuthSettings, object()), fail_on_settings_error=True
        )


def test_bootstrap_entrypoint_returns_when_initialization_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bootstrap

    calls: list[str] = []
    monkeypatch.setattr(bootstrap, "create_bootstrap_app", lambda: calls.append("done"))

    bootstrap.main()

    assert calls == ["done"]
