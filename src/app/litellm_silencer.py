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

This module is import-side-effect free; call `silence_litellm_noise()`
once at process startup (after the global logger is configured but before
any litellm code runs).
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


_applied = False


def silence_litellm_noise() -> None:
    """Idempotently attach the filter and flip suppress_debug_info.

    Safe to call before litellm is imported -- the filter applies to the
    "LiteLLM" logger by name and takes effect when litellm later logs to it.
    `litellm.suppress_debug_info` is set lazily inside a guarded import so
    callers that don't depend on litellm still don't pay the import cost.
    """
    global _applied
    if _applied:
        return
    _applied = True

    litellm_logger = logging.getLogger("LiteLLM")
    if not any(isinstance(f, _BotocoreMissingFilter) for f in litellm_logger.filters):
        litellm_logger.addFilter(_BotocoreMissingFilter())

    try:
        litellm: Any = __import__("litellm")
        litellm.suppress_debug_info = True
    except Exception:  # noqa: BLE001
        # litellm isn't installed in some minimal contexts (e.g. CLI tasks).
        # The logging filter is still in place for future imports.
        pass
