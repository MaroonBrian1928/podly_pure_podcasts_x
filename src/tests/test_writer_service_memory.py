from __future__ import annotations

from app.writer import executor, service
from app.writer.protocol import WriteCommand, WriteCommandType


def test_memory_trim_context_detects_large_writer_actions() -> None:
    cmd = WriteCommand(
        id="cmd-1",
        type=WriteCommandType.ACTION,
        model=None,
        data={"action": "replace_transcription", "params": {"segments": []}},
    )

    assert service._memory_trim_context_for_command(cmd) == (
        "writer large action replace_transcription"
    )


def test_memory_trim_context_ignores_polling_actions() -> None:
    cmd = WriteCommand(
        id="cmd-1",
        type=WriteCommandType.ACTION,
        model=None,
        data={"action": "dequeue_job", "params": {}},
    )

    assert service._memory_trim_context_for_command(cmd) is None


def test_memory_trim_context_detects_other_writer_actions() -> None:
    cmd = WriteCommand(
        id="cmd-1",
        type=WriteCommandType.ACTION,
        model=None,
        data={"action": "mark_model_call_failed", "params": {}},
    )

    assert service._memory_trim_context_for_command(cmd) == (
        "writer action mark_model_call_failed"
    )


def test_writer_executor_detects_dequeue_job_polling_commands() -> None:
    cmd = WriteCommand(
        id="cmd-1",
        type=WriteCommandType.ACTION,
        model=None,
        data={"action": "dequeue_job", "params": {}},
    )

    assert executor._command_action_name(cmd) == "dequeue_job"
    assert executor._is_dequeue_job_poll(cmd) is True


def test_writer_executor_action_name_ignores_non_action_commands() -> None:
    cmd = WriteCommand(
        id="cmd-1",
        type=WriteCommandType.TRANSACTION,
        model=None,
        data={"action": "dequeue_job", "params": {}},
    )

    assert executor._command_action_name(cmd) is None
    assert executor._is_dequeue_job_poll(cmd) is False


def test_discard_processed_command_payload_releases_payload_refs() -> None:
    payload = {"action": "replace_transcription", "params": {"segments": ["large"]}}
    reply_queue = object()
    cmd = WriteCommand(
        id="cmd-1",
        type=WriteCommandType.ACTION,
        model=None,
        data=payload,
        reply_queue=reply_queue,
    )

    service._discard_processed_command_payload(cmd)

    assert cmd.data == {}
    assert cmd.reply_queue is None
