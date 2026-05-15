from __future__ import annotations

import ctypes
import gc
import logging
import os
import sys
from functools import lru_cache
from typing import Any

from flask import g

logger = logging.getLogger("global_logger")
_TRIM_CONTEXTS_ATTR = "_podly_memory_trim_after_context"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def _malloc_trim() -> Any | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        libc = ctypes.CDLL("libc.so.6")
        trim = libc.malloc_trim
        trim.argtypes = [ctypes.c_size_t]
        trim.restype = ctypes.c_int
        return trim
    except Exception:  # noqa: BLE001
        return None


def release_memory_to_os(
    context: str,
    log: logging.Logger | None = None,
) -> None:
    """Ask Python and glibc to return freed arenas after large transient work."""
    if not _env_bool("PODLY_MEMORY_TRIM_ENABLED", default=True):
        return

    active_logger = log or logger
    collected = gc.collect()
    trimmed = False

    trim = _malloc_trim()
    if trim is not None:
        try:
            trimmed = bool(trim(0))
        except Exception as exc:  # noqa: BLE001
            active_logger.debug(
                "Memory trim failed after %s: %s", context, exc, exc_info=True
            )

    active_logger.debug(
        "Memory cleanup after %s: gc_collected=%s malloc_trim=%s",
        context,
        collected,
        trimmed,
    )


def request_memory_trim_after_context(context: str) -> None:
    """Request a second trim after Flask tears down session/app-context state."""
    try:
        contexts = getattr(g, _TRIM_CONTEXTS_ATTR, None)
        if contexts is None:
            contexts = []
            setattr(g, _TRIM_CONTEXTS_ATTR, contexts)
        contexts.append(context)
    except RuntimeError:
        release_memory_to_os(context, logger)


def consume_memory_trim_contexts() -> list[str]:
    try:
        contexts = getattr(g, _TRIM_CONTEXTS_ATTR, None)
        if not contexts:
            return []
        setattr(g, _TRIM_CONTEXTS_ATTR, [])
        return list(contexts)
    except RuntimeError:
        return []


def collect_incremental(
    context: str,
    log: logging.Logger | None = None,
) -> None:
    """Run a low-pause incremental collection during long batch loops."""
    active_logger = log or logger
    collected = gc.collect(1)
    active_logger.debug(
        "Incremental memory cleanup after %s: gc_collected=%s",
        context,
        collected,
    )
