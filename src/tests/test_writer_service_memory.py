from __future__ import annotations

from app.writer import service
from app.writer.protocol import WriteCommand, WriteCommandType


def test_memory_trim_context_detects_large_writer_actions() -> None:
    cmd = WriteCommand(
        id="cmd-1",
        type=WriteCommandType.ACTION,
        model=None,
        data={"action": "replace_transcription", "params": {"segments": []}},
    )

    assert service._memory_trim_context_for_command(cmd) == (
        "writer action replace_transcription"
    )


def test_memory_trim_context_ignores_polling_actions() -> None:
    cmd = WriteCommand(
        id="cmd-1",
        type=WriteCommandType.ACTION,
        model=None,
        data={"action": "dequeue_job", "params": {}},
    )

    assert service._memory_trim_context_for_command(cmd) is None


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
