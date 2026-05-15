from __future__ import annotations

import sys

import app as app_module


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
