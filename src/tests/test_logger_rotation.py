"""Tests for the rotating file handler wiring in app.logger."""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from app import logger as logger_module
from app.logger import setup_logger


@pytest.fixture
def isolated_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Each test gets a unique logger name so handler dedup state doesn't bleed
    # between tests via the global logging registry.
    for var in ("PODLY_LOG_MAX_BYTES", "PODLY_LOG_BACKUP_COUNT"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def _make_logger(name: str, log_file: Path) -> logging.Logger:
    lg = setup_logger(name, str(log_file))
    return lg


def _file_handlers(lg: logging.Logger) -> list[logging.FileHandler]:
    return [h for h in lg.handlers if isinstance(h, logging.FileHandler)]


def test_setup_logger_attaches_rotating_file_handler(
    isolated_log_dir: Path,
) -> None:
    log_file = isolated_log_dir / "app.log"
    lg = _make_logger("test_logger_rotation.attach", log_file)

    handlers = _file_handlers(lg)
    assert len(handlers) == 1
    handler = handlers[0]
    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes == logger_module.DEFAULT_LOG_MAX_BYTES
    assert handler.backupCount == logger_module.DEFAULT_LOG_BACKUP_COUNT
    # delay=True means the underlying stream is opened lazily.
    assert handler.stream is None


def test_setup_logger_respects_env_overrides(
    isolated_log_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PODLY_LOG_MAX_BYTES", "12345")
    monkeypatch.setenv("PODLY_LOG_BACKUP_COUNT", "9")

    log_file = isolated_log_dir / "app.log"
    lg = _make_logger("test_logger_rotation.env", log_file)

    handler = _file_handlers(lg)[0]
    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes == 12345
    assert handler.backupCount == 9


def test_setup_logger_dedups_on_double_call(isolated_log_dir: Path) -> None:
    log_file = isolated_log_dir / "app.log"
    name = "test_logger_rotation.dedup"
    lg1 = _make_logger(name, log_file)
    handlers_after_first = list(lg1.handlers)
    lg2 = _make_logger(name, log_file)

    assert lg1 is lg2
    # Calling setup_logger twice for the same file must not duplicate the
    # rotating file handler that was attached on the first call.
    assert len(_file_handlers(lg1)) == 1
    assert lg1.handlers == handlers_after_first


def test_setup_logger_creates_log_dir(isolated_log_dir: Path) -> None:
    nested = isolated_log_dir / "nested" / "deeper"
    log_file = nested / "app.log"
    _make_logger("test_logger_rotation.mkdir", log_file)

    assert nested.is_dir()
    # delay=True means the file itself is not created until first emit.
    assert not log_file.exists()


def test_setup_logger_writes_and_can_rotate(isolated_log_dir: Path) -> None:
    """End-to-end smoke test: small maxBytes should produce backup files."""
    log_file = isolated_log_dir / "app.log"
    # Bypass env so we can force tiny rotation thresholds for this case.
    os.environ["PODLY_LOG_MAX_BYTES"] = "200"
    os.environ["PODLY_LOG_BACKUP_COUNT"] = "2"
    try:
        lg = _make_logger("test_logger_rotation.rotate", log_file)
        for i in range(50):
            lg.info("log line %d filler-aaaaaaaaaaaaaaaaaaaa", i)
        for h in lg.handlers:
            h.flush()
        assert log_file.exists()
        rotated = list(isolated_log_dir.glob("app.log.*"))
        assert rotated, "rotation should have produced at least one backup"
    finally:
        del os.environ["PODLY_LOG_MAX_BYTES"]
        del os.environ["PODLY_LOG_BACKUP_COUNT"]
        # Detach handlers so the tmp_path file can be cleaned up on Windows-like FS.
        lg = logging.getLogger("test_logger_rotation.rotate")
        for h in list(lg.handlers):
            h.close()
            lg.removeHandler(h)
