from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

import app as app_module


@pytest.fixture
def isolated_startup(monkeypatch):
    monkeypatch.setattr(app_module, "_hydrate_web_config", lambda: None)
    monkeypatch.setattr(app_module, "_run_app_startup", lambda _settings: None)
    monkeypatch.setattr(app_module, "_start_scheduler_and_jobs", lambda _app: None)
    monkeypatch.setattr(
        app_module, "load_discord_settings", lambda: SimpleNamespace(enabled=False)
    )


@pytest.mark.parametrize("factory", ["create_web_app", "create_processing_app"])
def test_reader_factories_skip_migrations(factory, isolated_startup, monkeypatch):
    def unexpected_migration_init(*_args, **_kwargs):
        pytest.fail("Reader processes must not initialize migration dependencies")

    monkeypatch.setattr(app_module.migrate, "init_app", unexpected_migration_init)
    app = getattr(app_module, factory)()
    assert "migrate" not in app.extensions
    assert "db" not in app.cli.commands


@pytest.mark.parametrize("factory", ["create_app", "create_writer_app"])
def test_migration_factories_keep_cli(factory, isolated_startup, monkeypatch):
    monkeypatch.setenv("PODLY_RUN_STARTUP", "False")
    monkeypatch.setenv("PODLY_DISABLE_SCHEDULER", "True")
    app = getattr(app_module, factory)()
    result = app.test_cli_runner().invoke(args=["db", "--help"])
    assert result.exit_code == 0
    assert "upgrade" in result.output
    assert "migrate" in app.extensions


@pytest.mark.parametrize("factory", ["create_web_app", "create_processing_app"])
def test_reader_factories_do_not_import_migration_dependencies(factory):
    # A fresh interpreter checks actual imports without removing shared modules
    # from the pytest process and breaking existing class/module identities.
    script = f"""
import sys
from types import SimpleNamespace
import pytest
import app
app._hydrate_web_config = lambda: None
app._start_scheduler_and_jobs = lambda _app: None
app.load_discord_settings = lambda: SimpleNamespace(enabled=False)
app.{factory}()
assert 'flask_migrate' not in sys.modules
assert 'alembic' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_create_web_app_does_not_import_processing_or_llm_clients(monkeypatch) -> None:
    heavy_modules = [
        "podcast_processor.podcast_processor",
        "litellm",
        "openai",
        "groq",
    ]
    for module_name in heavy_modules:
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    monkeypatch.setattr(app_module, "_hydrate_web_config", lambda: None)
    monkeypatch.setattr(app_module, "_start_scheduler_and_jobs", lambda _app: None)

    app = app_module.create_web_app()

    assert app.config["PODLY_APP_ROLE"] == "web"
    for module_name in heavy_modules:
        assert module_name not in sys.modules
