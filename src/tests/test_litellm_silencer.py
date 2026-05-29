"""Tests that startup-only filter install does NOT import litellm.

Importing litellm pulls in ~160 MiB and several hundred ``openai`` submodules.
``install_litellm_log_filter()`` is called from ``app/__init__.py`` and must
stay import-free so every Podly process doesn't pay that cost at startup.
The deferred ``apply_litellm_suppress_debug_info()`` is what triggers the
import, and it's only called from code paths that already touch litellm
themselves.
"""

from __future__ import annotations

import importlib
import logging
import sys
from typing import Any


def test_install_litellm_log_filter_does_not_import_litellm(
    monkeypatch: Any,
) -> None:
    monkeypatch.delitem(sys.modules, "litellm", raising=False)
    monkeypatch.delitem(sys.modules, "openai", raising=False)

    # Reload the silencer module so its module-level guard flags reset and
    # this test exercises the real install path, not a no-op short-circuit
    # from an earlier test in the session.
    silencer = importlib.reload(importlib.import_module("app.litellm_silencer"))
    silencer.install_litellm_log_filter()

    assert "litellm" not in sys.modules
    assert "openai" not in sys.modules

    # And the filter actually drops the bedrock/sagemaker noise.
    litellm_logger = logging.getLogger("LiteLLM")
    record = logging.LogRecord(
        name="LiteLLM",
        level=logging.WARNING,
        pathname=__file__,
        lineno=0,
        msg="litellm: could not pre-load bedrock-runtime response stream shape",
        args=(),
        exc_info=None,
    )
    # ``filters`` is typed as ``list[_SupportsFilter | Callable]``; our filter
    # is a real ``logging.Filter`` subclass, so narrow to that branch first.
    assert any(
        isinstance(f, logging.Filter) and not f.filter(record)
        for f in litellm_logger.filters
    )


def test_apply_litellm_suppress_debug_info_is_idempotent_and_noop_without_litellm(
    monkeypatch: Any,
) -> None:
    # Pretend litellm isn't installed by making the import raise. The
    # function must swallow the error so callers (cost_routes,
    # llm_model_call_utils) don't have to.
    monkeypatch.delitem(sys.modules, "litellm", raising=False)
    real_import = (
        __builtins__["__import__"]
        if isinstance(__builtins__, dict)
        else __builtins__.__import__
    )

    def _block_litellm(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "litellm":
            raise ModuleNotFoundError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _block_litellm)

    silencer = importlib.reload(importlib.import_module("app.litellm_silencer"))
    # Should not raise even though the import fails.
    silencer.apply_litellm_suppress_debug_info()
    silencer.apply_litellm_suppress_debug_info()  # idempotent
