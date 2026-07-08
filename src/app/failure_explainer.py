"""Shared "why did this episode fail" LLM analysis.

Captures a raw window of the application log around an episode's most recent
failure (including the Python traceback and the underlying exception -- the only
lines that actually identify the root cause) and asks the configured chat model
to explain it in plain English.

This logic used to live privately inside ``app.routes.post_routes`` behind the
``/troubleshoot`` route. It is factored out here so the failure-notification
path (which runs in the processing worker, outside any request) can reuse the
exact same analysis, and so the context builder can be driven by primitive
identifiers rather than live ORM objects (the worker's session may be in a
rolled-back state at the failure site).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from shared.processing_paths import get_instance_dir

logger = logging.getLogger("global_logger")


# Levels that signal a real problem worth explaining to the user. When the
# failure was only logged at INFO (some paths do this) we fall back to the
# tail of whatever related entries we have so the LLM still has context.
TROUBLESHOOT_LEVELS = {"WARNING", "ERROR", "CRITICAL"}
TROUBLESHOOT_FALLBACK_ENTRIES = 15
TROUBLESHOOT_MAX_ENTRIES = 40
# Output cap for the explanation. The prompt asks for a short, structured
# answer (stage + root exception + concrete fix), which lands well under this;
# the headroom just guarantees a thorough answer is never truncated mid-sentence.
TROUBLESHOOT_MAX_TOKENS = 1000

# How much raw log to capture around a failure. The useful signal (the Python
# traceback + the root exception) is logged as *continuation lines* with no
# timestamp prefix, so it never survives ``_build_related_logs``' structured,
# post-tagged filtering. We instead anchor on the failure line and grab a
# contiguous raw window *above* it so the whole traceback comes along.
TROUBLESHOOT_CONTEXT_BACK = 160
TROUBLESHOOT_CONTEXT_FORWARD = 4
TROUBLESHOOT_CONTEXT_MAX_CHARS = 14000

# Substrings that mark a line as a real failure (used together with a
# post/job reference to anchor the context window). Deliberately excludes
# benign "status=200" API lines that also mention the post guid.
TROUBLESHOOT_FAILURE_MARKERS = (
    "status=failed",
    "JOB_STATUS_ERROR",
    "Unexpected error",
    "Traceback (most recent call last)",
    "Error:",
    "Exception",
    "error=",
    "Connection error",
    "Connection refused",
    "Timeout",
    "Timed out",
)

TROUBLESHOOT_SYSTEM_PROMPT = (
    "You are a support assistant for Podly, a self-hosted app that removes ads "
    "from podcast episodes. An episode failed to process. You are given a raw "
    "slice of the application log around the failure, which usually includes a "
    "Python traceback and the underlying exception. Read it and explain, in "
    "plain non-technical English, the ROOT cause and what the user should do. "
    "Be specific and concrete:\n"
    "- Name which stage failed (downloading, transcription/Whisper, ad "
    "identification/LLM, or audio processing) based on the traceback frames.\n"
    "- Quote or paraphrase the underlying exception (e.g. 'connection "
    "refused', 'invalid API key / 401', 'timeout', 'out of disk space').\n"
    "- Give a concrete next step tied to that cause (e.g. 'your remote Whisper "
    "server appears to be down or the URL/port is wrong -- check it is running "
    "and the Whisper base URL in Settings is correct').\n"
    "Keep it to 2-4 sentences. Do NOT just restate 'a connection error "
    "occurred' -- say WHAT could not be reached and WHY it likely happened. If "
    "the log genuinely lacks a cause, say you cannot determine it from the "
    "available logs."
)


def get_app_log_path() -> Path:
    instance_candidate = get_instance_dir() / "logs" / "app.log"
    if "PODLY_INSTANCE_DIR" in os.environ or instance_candidate.exists():
        return instance_candidate

    project_candidate = (
        Path(__file__).resolve().parents[1] / "instance" / "logs" / "app.log"
    )
    return project_candidate


def tail_log_lines(path: Path, max_bytes: int = 1_000_000) -> list[str]:
    if not path.exists() or not path.is_file():
        return []

    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            file_size = handle.tell()
            read_size = min(file_size, max_bytes)
            handle.seek(max(0, file_size - read_size))
            payload = handle.read()
    except OSError:
        return []

    text = payload.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if read_size < file_size and lines:
        lines = lines[1:]
    return lines


def select_troubleshoot_entries(related: dict[str, Any]) -> list[dict[str, Any]]:
    """Pick the log entries worth sending to the LLM for an explanation.

    Prefers WARNING/ERROR/CRITICAL lines; if none are present, falls back to
    the tail of whatever related entries exist so the model still has context.
    """
    entries = related.get("entries") or []
    flagged = [
        entry
        for entry in entries
        if str(entry.get("level", "")).upper() in TROUBLESHOOT_LEVELS
    ]
    selected = flagged or entries[-TROUBLESHOOT_FALLBACK_ENTRIES:]
    return selected[-TROUBLESHOOT_MAX_ENTRIES:]


def format_troubleshoot_entries(entries: list[dict[str, Any]]) -> str:
    lines = []
    for entry in entries:
        timestamp = entry.get("timestamp", "")
        level = entry.get("level", "")
        stage = entry.get("stage", "")
        message = entry.get("message", "")
        lines.append(f"[{timestamp}] {level} ({stage}): {message}")
    return "\n".join(lines)


def _strip_log_extra(line: str) -> str:
    """Drop the noisy ``| extra={...}`` suffix appended to every log line."""
    idx = line.rfind(" | extra=")
    return line[:idx] if idx != -1 else line


def _line_references_post(
    line: str,
    *,
    post_guid: str,
    post_id: int,
    job_ids: set[str],
    target_job_id: str | None,
) -> bool:
    if target_job_id is not None:
        return target_job_id in line
    if f"post_guid={post_guid}" in line:
        return True
    if any(job_id and job_id in line for job_id in job_ids):
        return True
    return f"post_id={post_id}" in line or f"post {post_id}" in line


def _find_failure_anchor(
    lines: list[str],
    *,
    post_guid: str,
    post_id: int,
    job_ids: set[str],
    target_job_id: str | None,
) -> int | None:
    """Index of the last log line that references this post/job AND looks like
    a failure. Scans from the end so we land on the most recent failure."""
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx]
        if not _line_references_post(
            line,
            post_guid=post_guid,
            post_id=post_id,
            job_ids=job_ids,
            target_job_id=target_job_id,
        ):
            continue
        if any(marker in line for marker in TROUBLESHOOT_FAILURE_MARKERS):
            return idx
    return None


def build_troubleshoot_context(
    *,
    post_guid: str,
    post_id: int,
    job_ids: set[str],
    target_job_id: str | None = None,
) -> str | None:
    """Capture a raw log window around this post's most recent failure.

    Unlike the structured, post-tagged ``related_logs`` view (which keeps only
    timestamped, post-tagged lines for the stats UI), this returns the
    contiguous raw text around the failure so the Python traceback and the
    underlying exception -- the only lines that actually identify the root
    cause -- are included. Returns None when no failure can be located, so the
    caller can fall back to the structured entries (or, in the notification
    path, omit the explanation).
    """
    lines = tail_log_lines(get_app_log_path())
    if not lines:
        return None

    anchor = _find_failure_anchor(
        lines,
        post_guid=post_guid,
        post_id=post_id,
        job_ids=job_ids,
        target_job_id=target_job_id,
    )
    if anchor is None:
        return None

    start = max(0, anchor - TROUBLESHOOT_CONTEXT_BACK)
    end = min(len(lines), anchor + 1 + TROUBLESHOOT_CONTEXT_FORWARD)
    window = [_strip_log_extra(line) for line in lines[start:end]]
    text = "\n".join(window).strip()
    if len(text) > TROUBLESHOOT_CONTEXT_MAX_CHARS:
        # Keep the tail -- the exception and the JOB_STATUS failure line sit at
        # the bottom of the window, which is the densest signal.
        text = text[-TROUBLESHOOT_CONTEXT_MAX_CHARS:]
    return text or None


def explain_failure(context_text: str, config: Any) -> str:
    """Run a single LLM completion that explains the failure in plain English.

    Mirrors the lightweight probe pattern in ``api_test_llm``: configure
    litellm for this call, send the raw log window, and return the text
    content. The transcription (Whisper) model cannot reason about text, so
    this deliberately uses the chat model (``llm_model``).
    """
    import litellm

    from app.litellm_silencer import apply_litellm_suppress_debug_info
    from podcast_processor.llm_model_call_utils import extract_litellm_content
    from shared.llm_utils import model_uses_max_completion_tokens

    apply_litellm_suppress_debug_info()

    api_key = getattr(config, "llm_api_key", None)
    model = getattr(config, "llm_model", None) or "gpt-4o"
    base_url = getattr(config, "openai_base_url", None)
    timeout = int(getattr(config, "openai_timeout", 30) or 30)

    if api_key:
        litellm.api_key = api_key
    if base_url:
        litellm.api_base = base_url

    messages = [
        {"role": "system", "content": TROUBLESHOOT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Here is the raw application log around the failure for this "
                f"episode:\n\n{context_text}"
            ),
        },
    ]

    completion_kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "timeout": timeout,
    }
    if model_uses_max_completion_tokens(model):
        completion_kwargs["max_completion_tokens"] = TROUBLESHOOT_MAX_TOKENS
    else:
        completion_kwargs["max_tokens"] = TROUBLESHOOT_MAX_TOKENS

    response = litellm.completion(**completion_kwargs)
    return extract_litellm_content(response).strip()
