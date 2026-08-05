"""Shared helpers for working with LLM provider quirks."""

from __future__ import annotations

import logging
from typing import Any, Final

logger = logging.getLogger("global_logger")

# Patterns for models that require the `max_completion_tokens` parameter
# instead of the legacy `max_tokens`. OpenAI began enforcing this on the
# newer gpt-4o / gpt-5 / o1 style models.
_MAX_COMPLETION_TOKEN_MODELS: Final[tuple[str, ...]] = (
    "gpt-5",
    "gpt-4o",
    "o1-",
    "o1_",
    "o1/",
    "chatgpt-4o-latest",
)


def model_uses_max_completion_tokens(model_name: str | None) -> bool:
    """Return True when the target model expects `max_completion_tokens`."""
    if not model_name:
        return False
    model_lower = model_name.lower()
    return any(pattern in model_lower for pattern in _MAX_COMPLETION_TOKEN_MODELS)


def normalize_completion_args_for_model(
    completion_args: dict[str, Any],
) -> dict[str, Any]:
    """Apply provider limits/quirks from LiteLLM metadata in place."""
    model_name = str(completion_args.get("model") or "")
    if not model_name:
        return completion_args

    # Current OpenAI reasoning models reject non-default temperature values.
    if model_uses_max_completion_tokens(model_name):
        completion_args.pop("temperature", None)

    try:
        import litellm

        model_info = litellm.get_model_info(model_name)
    except Exception as exc:  # noqa: BLE001
        # GPT reasoning models reject oversized output limits. If metadata is
        # unavailable, use the provider default instead of forwarding a value
        # that may be invalid for the selected model.
        if model_uses_max_completion_tokens(model_name):
            completion_args.pop("max_completion_tokens", None)
            completion_args.pop("max_tokens", None)
        logger.warning(
            "Unable to load LiteLLM metadata for %s; omitted explicit output "
            "limit for reasoning model: %s",
            model_name,
            exc,
        )
        return completion_args

    max_output_tokens = model_info.get("max_output_tokens") or model_info.get(
        "max_tokens"
    )
    if max_output_tokens is None:
        return completion_args
    try:
        output_limit = int(max_output_tokens)
    except TypeError, ValueError:
        return completion_args
    if output_limit <= 0:
        return completion_args

    for key in ("max_completion_tokens", "max_tokens"):
        configured_value = completion_args.get(key)
        if configured_value is None:
            continue
        try:
            completion_args[key] = min(int(configured_value), output_limit)
        except TypeError, ValueError:
            continue
    return completion_args
