import logging
import os
import threading
import time

from app.ipc import get_queue, make_server_manager
from app.logger import setup_logger
from app.memory_pressure import release_memory_to_os
from app.writer.protocol import WriteCommand, WriteCommandType

from .executor import CommandExecutor

logger = setup_logger("writer", "src/instance/logs/app.log", level=logging.INFO)


def _idle_trim_interval_seconds() -> int:
    raw = os.environ.get("PODLY_WRITER_IDLE_TRIM_INTERVAL_SEC", "900")
    try:
        return int(raw)
    except ValueError:
        return 900


def _start_idle_trim_thread(activity_counter: list[int]) -> threading.Thread | None:
    """Periodically trim allocator arenas if any commands were processed
    since the last trim. Skips when truly idle so we don't churn syscalls
    while waiting on an empty queue.
    """
    interval = _idle_trim_interval_seconds()
    if interval <= 0:
        return None

    def _loop() -> None:
        last_count = 0
        while True:
            time.sleep(interval)
            current = activity_counter[0]
            if current == last_count:
                continue
            last_count = current
            try:
                release_memory_to_os("writer idle tick", logger)
            except Exception:  # noqa: BLE001
                logger.debug("writer idle trim failed", exc_info=True)

    thread = threading.Thread(target=_loop, name="writer-idle-trim", daemon=True)
    thread.start()
    return thread


MEMORY_TRIM_ACTIONS = {
    "insert_identifications",
    "insert_transcript_segments",
    "finish_transcription_replace",
    "finish_transcription_replace_from_artifact",
    "refresh_feed",
    "replace_audio_segments",
    "replace_identifications",
    "replace_transcription",
    "start_transcription_replace",
    "upsert_model_call",
}


def _action_name(cmd: object) -> str | None:
    data = getattr(cmd, "data", None)
    if not isinstance(data, dict):
        return None
    action = data.get("action")
    return action if isinstance(action, str) else None


def _memory_trim_context_for_command(cmd: object) -> str | None:
    if getattr(cmd, "type", None) != WriteCommandType.ACTION:
        return None
    action = _action_name(cmd)
    if action == "dequeue_job":
        return None
    if action not in MEMORY_TRIM_ACTIONS:
        return f"writer action {action or 'unknown'}"
    return f"writer large action {action}"


def _discard_processed_command_payload(cmd: WriteCommand) -> None:
    try:
        cmd.data = {}
        cmd.reply_queue = None
    except Exception:  # noqa: BLE001
        return


def run_writer_service() -> None:
    from app import create_writer_app

    logger.info("Starting Writer Service...")

    # 1. Start the IPC Server
    manager = make_server_manager()
    server = manager.get_server()

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    logger.info("IPC Server started on port 50001")

    # 2. Get the queue
    queue = get_queue()

    # 3. Initialize App and Executor
    app = create_writer_app()
    executor = CommandExecutor(app)

    # Activity counter consumed by the idle-trim watchdog. Using a single-element
    # list avoids the `nonlocal`/`global` plumbing a bare int would need.
    activity_counter = [0]
    _start_idle_trim_thread(activity_counter)

    logger.info("Writer Loop starting...")

    # 4. Writer Loop
    while True:
        cmd = None
        result = None
        trim_context = None
        try:
            cmd = queue.get()
            activity_counter[0] += 1
            trim_context = _memory_trim_context_for_command(cmd)

            # Check if this is a polling command (dequeue_job)
            is_polling = (
                getattr(cmd, "type", None) == WriteCommandType.ACTION
                and isinstance(getattr(cmd, "data", None), dict)
                and cmd.data.get("action") == "dequeue_job"
            )

            if not is_polling:
                logger.info(
                    "[WRITER] Received command: id=%s type=%s model=%s has_reply=%s",
                    getattr(cmd, "id", None),
                    getattr(cmd, "type", None),
                    getattr(cmd, "model", None),
                    bool(getattr(cmd, "reply_queue", None)),
                )

            result = executor.process_command(cmd)

            # Only log finished/reply if not polling or if polling actually did something
            if not is_polling or (result and result.data):
                logger.info(
                    "[WRITER] Finished command: id=%s success=%s error=%s",
                    getattr(result, "command_id", None),
                    getattr(result, "success", None),
                    getattr(result, "error", None),
                )

            if cmd.reply_queue:
                if not is_polling or (result and result.data):
                    logger.info(
                        "[WRITER] Sending reply for command id=%s",
                        getattr(cmd, "id", None),
                    )
                cmd.reply_queue.put(result)

        except Exception as e:
            logger.error("Error in writer loop: %s", e, exc_info=True)
            time.sleep(1)
        finally:
            if cmd is not None:
                _discard_processed_command_payload(cmd)
                cmd = None
                result = None
            if trim_context is not None:
                release_memory_to_os(trim_context, logger)
