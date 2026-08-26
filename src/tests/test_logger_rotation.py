"""Tests for the rotating file handler wiring in app.logger."""

import logging
import os
import subprocess
import sys
import textwrap
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


class TestMultiProcessRotation:
    """Rotation must stay coherent when several processes share one log file.

    Podly logs to ``app.log`` from the writer service, the Flask app, and every
    per-job ``processing_worker`` subprocess. With a stock RotatingFileHandler
    each of them rotates independently, so one process renames ``app.log`` out
    from under the others and they carry on writing into the renamed inode.
    """

    @staticmethod
    def _handler(log_file: Path) -> logger_module.MultiProcessRotatingFileHandler:
        handler = logger_module.MultiProcessRotatingFileHandler(
            str(log_file), maxBytes=300, backupCount=20, encoding="utf-8", delay=True
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        return handler

    @staticmethod
    def _record(message: str) -> logging.LogRecord:
        return logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )

    def test_setup_logger_uses_the_multiprocess_handler(
        self, isolated_log_dir: Path
    ) -> None:
        lg = setup_logger(
            "test_logger_rotation.mp_wiring", str(isolated_log_dir / "app.log")
        )
        handler = _file_handlers(lg)[0]
        assert isinstance(handler, logger_module.MultiProcessRotatingFileHandler)

    def test_second_handler_reopens_instead_of_rotating_again(
        self, isolated_log_dir: Path
    ) -> None:
        """A handler whose file was rotated away must reopen, not re-rotate."""
        log_file = isolated_log_dir / "app.log"
        a = self._handler(log_file)
        b = self._handler(log_file)
        try:
            # Both open the same inode.
            a.emit(self._record("from-a-before"))
            b.emit(self._record("from-b-before"))
            assert a.stream is not None and b.stream is not None

            # Fill to just under the limit, then tip A over it. app.log.1 now
            # holds the "before" lines; app.log is fresh and well under
            # maxBytes, so no further rotation is due.
            a.emit(self._record("f" * 280))
            a.emit(self._record("from-a-trigger"))

            rotated_text = (isolated_log_dir / "app.log.1").read_text()
            assert "from-a-before" in rotated_text
            assert "from-b-before" in rotated_text
            assert "from-a-trigger" in log_file.read_text()

            # B still holds the renamed inode. Its next emit must land in the
            # current app.log -- and must NOT shift A's fresh log to app.log.2.
            b.emit(self._record("from-b-after"))

            current = log_file.read_text()
            assert "from-b-after" in current
            assert "from-a-trigger" in current, "B must not have rotated A's log away"
            assert not (isolated_log_dir / "app.log.2").exists()
            assert "from-a-before" in (isolated_log_dir / "app.log.1").read_text()
        finally:
            a.close()
            b.close()

    def test_stale_handler_reopens_without_a_rotation_of_its_own(
        self, isolated_log_dir: Path
    ) -> None:
        """Reopening must not wait until the stale handler hits maxBytes.

        Detecting the swap only in doRollover would let a process write up to
        another maxBytes into the rotated-away file first -- which is how
        app.log stopped being the current log for hours in production.
        """
        log_file = isolated_log_dir / "app.log"
        a = self._handler(log_file)
        b = self._handler(log_file)
        try:
            a.emit(self._record("open-a"))
            b.emit(self._record("open-b"))
            a.emit(self._record("f" * 280))
            a.emit(self._record("from-a-trigger"))

            assert b.stream is not None
            stale_inode = os.fstat(b.stream.fileno()).st_ino
            assert stale_inode != os.stat(log_file).st_ino

            # Well under maxBytes, so nothing here would trigger B's own rollover.
            b.emit(self._record("tiny"))

            assert b.stream is not None
            assert os.fstat(b.stream.fileno()).st_ino == os.stat(log_file).st_ino
            assert "tiny" in log_file.read_text()
            assert "tiny" not in (isolated_log_dir / "app.log.1").read_text()
        finally:
            a.close()
            b.close()

    def test_no_lines_are_lost_across_real_processes(
        self, isolated_log_dir: Path
    ) -> None:
        """End-to-end: two OS processes hammering one log lose nothing."""
        log_file = isolated_log_dir / "app.log"
        lines_per_process = 150
        script = textwrap.dedent(
            f"""
            import logging, sys
            from app.logger import MultiProcessRotatingFileHandler

            tag = sys.argv[1]
            handler = MultiProcessRotatingFileHandler(
                {str(log_file)!r}, maxBytes=2000, backupCount=200,
                encoding="utf-8", delay=True,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            lg = logging.getLogger("rotation-" + tag)
            lg.setLevel(logging.INFO)
            lg.propagate = False
            lg.addHandler(handler)
            for i in range({lines_per_process}):
                lg.info("%s-%04d-%s", tag, i, "p" * 60)
            handler.close()
            """
        )
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        procs = [
            subprocess.Popen([sys.executable, "-c", script, tag], env=env)
            for tag in ("alpha", "beta")
        ]
        for proc in procs:
            assert proc.wait(timeout=120) == 0

        written = []
        for path in isolated_log_dir.glob("app.log*"):
            if path.name.endswith(".lock"):
                continue
            written.extend(
                line for line in path.read_text().splitlines() if line.strip()
            )

        for tag in ("alpha", "beta"):
            found = {line.split("-")[1] for line in written if line.startswith(tag)}
            missing = {f"{i:04d}" for i in range(lines_per_process)} - found
            assert not missing, (
                f"{tag} lost {len(missing)} lines: {sorted(missing)[:5]}"
            )
