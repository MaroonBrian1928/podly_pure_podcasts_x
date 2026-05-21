import json
import logging
import os
from logging.handlers import RotatingFileHandler

from app.sanitize import redact_secrets

DEFAULT_LOG_MAX_BYTES = 50_000_000
DEFAULT_LOG_BACKUP_COUNT = 5


class ExtraFormatter(logging.Formatter):
    """Formatter that appends structured extras to log lines.

    Any LogRecord attributes not in the standard set are captured into a JSON
    object and appended as ``extra={...}`` so contextual fields are visible in
    plain-text logs.
    """

    _standard_attrs = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
    }

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            k: v for k, v in record.__dict__.items() if k not in self._standard_attrs
        }
        if extras:
            try:
                extras_json = json.dumps(extras, ensure_ascii=True, default=str)
            except Exception:  # noqa: BLE001
                extras_json = str(extras)
            final_str = f"{base} | extra={extras_json}"
        else:
            final_str = base

        return redact_secrets(final_str)


def setup_logger(
    name: str, log_file: str, level: int = logging.DEBUG
) -> logging.Logger:
    """Create or return a configured logger.

    - Writes to the specified log_file
    - Emits to console exactly once (no duplicates)
    - Disables propagation to avoid duplicate root handling
    - Guards against adding duplicate handlers across repeated calls
    """
    file_formatter = ExtraFormatter("%(asctime)s %(levelname)s %(message)s")
    console_formatter = ExtraFormatter("%(levelname)s  [%(name)s] %(message)s")

    logger = logging.getLogger(name)
    logger.setLevel(level)
    # Prevent records from also bubbling up to root logger handlers (which can cause duplicates)
    logger.propagate = False

    # Ensure directory exists for log file
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    # Add file handler if not already present for this file
    abs_log_file = os.path.abspath(log_file)
    has_file_handler = any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", None) == abs_log_file
        for h in logger.handlers
    )
    if not has_file_handler:
        max_bytes = int(os.environ.get("PODLY_LOG_MAX_BYTES", DEFAULT_LOG_MAX_BYTES))
        backup_count = int(
            os.environ.get("PODLY_LOG_BACKUP_COUNT", DEFAULT_LOG_BACKUP_COUNT)
        )
        # delay=True: per-job processing_worker subprocesses import the logger
        # but may never write. Without delay, every spawn bumps the file mtime
        # and risks spurious rotation triggers across processes.
        file_handler = RotatingFileHandler(
            abs_log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    # Add a single console handler if not already present
    has_stream_handler = any(
        isinstance(h, logging.StreamHandler) for h in logger.handlers
    )
    if not has_stream_handler:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(console_formatter)
        logger.addHandler(stream_handler)

    return logger
