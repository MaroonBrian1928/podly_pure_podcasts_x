"""Silence litellm log noise we can't act on.

litellm 1.86+ emits two unrelated bits of noise we don't want in our logs:

1. WARNINGs at import time about being unable to pre-load Bedrock /
   SageMaker response stream shapes because `botocore` isn't installed.
   We don't use AWS providers, so installing botocore just to silence the
   warning is wasteful. Drop those records via a logging Filter.

2. The "Give Feedback / Get Help: https://github.com/BerriAI/litellm" +
   "If you need to debug this error, use litellm._turn_on_debug()" blurb
   printed by litellm's error path on every failure. Controlled by
   `litellm.suppress_debug_info`.

These are split into two functions so the cheap one can run at process
startup without importing litellm:

- ``install_litellm_log_filter()`` registers the logging filter by logger
  name. The "LiteLLM" logger doesn't have to exist yet — Python's logging
  module creates it on first ``getLogger("LiteLLM")`` call and the filter
  is already attached. **No litellm import. Safe at startup.**

- ``apply_litellm_suppress_debug_info()`` actually imports litellm to set
  the module attribute. Importing litellm pulls in ~160 MiB and 500+
  ``openai`` submodules, so call this lazily — right next to the call sites
  that already trigger the import (e.g. ``litellm.completion``,
  ``litellm.model_cost``). Both functions are idempotent.

``silence_litellm_noise()`` is kept as a legacy shim that calls both —
prefer the split functions for new call sites.
"""

from __future__ import annotations

import logging
from typing import Any

_BOTOCORE_NOISE_FRAGMENTS = (
    "could not pre-load bedrock-runtime response stream shape",
    "could not pre-load sagemaker-runtime response stream shape",
)


class _BotocoreMissingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        return not any(frag in msg for frag in _BOTOCORE_NOISE_FRAGMENTS)


_filter_installed = False
_suppress_applied = False


def install_litellm_log_filter() -> None:
    """Attach the botocore-noise filter to the LiteLLM logger.

    Idempotent. Does not import litellm — safe to call at process startup.
    """
    global _filter_installed
    if _filter_installed:
        return
    litellm_logger = logging.getLogger("LiteLLM")
    if not any(isinstance(f, _BotocoreMissingFilter) for f in litellm_logger.filters):
        litellm_logger.addFilter(_BotocoreMissingFilter())
    _filter_installed = True


def apply_litellm_suppress_debug_info() -> None:
    """Flip ``litellm.suppress_debug_info = True``.

    Idempotent. Imports litellm, which is expensive — only call from code
    paths that have already triggered (or are about to trigger) a litellm
    import of their own.
    """
    global _suppress_applied
    if _suppress_applied:
        return
    try:
        litellm: Any = __import__("litellm")
        vars(litellm)["suppress_debug_info"] = True
    except Exception:  # noqa: BLE001
        # litellm isn't installed in some minimal contexts (e.g. CLI tasks).
        # The logging filter is still in place for future imports.
        return
    _suppress_applied = True


def silence_litellm_noise() -> None:
    """Legacy entry point: install the filter and apply suppress_debug_info.

    Calling this at startup forces a litellm import (~160 MiB). Prefer
    ``install_litellm_log_filter()`` at startup plus
    ``apply_litellm_suppress_debug_info()`` next to your litellm call sites.
    """
    install_litellm_log_filter()
    apply_litellm_suppress_debug_info()
