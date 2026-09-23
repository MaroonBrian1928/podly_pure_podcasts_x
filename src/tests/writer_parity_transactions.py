"""Differential checks for generic model commands and transaction semantics."""

from __future__ import annotations

from typing import Any, TypedDict

from app.writer.protocol import WriteCommand, WriteCommandType
from tests.writer_parity_fixtures import WriterParityPair

WRITER_DIFFERENTIAL_CASES = (
    {
        "case_id": "generic_update_ignores_unknown_model_field",
        "owner_group": "transaction",
        "operation": "update",
        "model": "Post",
    },
    {
        "case_id": "generic_update_missing_record",
        "owner_group": "transaction",
        "operation": "update",
        "model": "Post",
        "expect_success": False,
    },
    {
        "case_id": "transaction_ordered_results",
        "owner_group": "transaction",
        "operation": "transaction",
    },
    {
        "case_id": "transaction_failure_rolls_back_earlier_update",
        "owner_group": "transaction",
        "operation": "transaction",
        "expect_success": False,
    },
    {
        "case_id": "transaction_constraint_failure_rolls_back_earlier_update",
        "owner_group": "transaction",
        "operation": "transaction",
        "expect_success": False,
    },
)


class _UpdateCommand(TypedDict):
    id: str
    type: str
    model: str
    data: dict[str, Any]


def _update(model: str, record_id: int, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation": "update",
        "model": model,
        "id": record_id,
        "data": data,
    }


def build_writer_transaction_case(
    case_id: str, pair: WriterParityPair
) -> tuple[dict[str, Any], WriteCommand]:
    """Build equivalent wire and legacy commands from an isolated fixture pair."""
    post_id = pair.manifest.post_ids[1]
    missing_post_id = pair.manifest.missing_post_id
    if case_id == "generic_update_ignores_unknown_model_field":
        data = {"duration": 73.25, "not_a_post_column": "ignored"}
        return (
            _update("Post", post_id, data),
            WriteCommand(
                f"parity-{case_id}",
                WriteCommandType.UPDATE,
                "Post",
                {"id": post_id, **data},
            ),
        )
    if case_id == "generic_update_missing_record":
        data = {"duration": 73.25}
        return (
            _update("Post", missing_post_id, data),
            WriteCommand(
                f"parity-{case_id}",
                WriteCommandType.UPDATE,
                "Post",
                {"id": missing_post_id, **data},
            ),
        )
    if case_id in {
        "transaction_ordered_results",
        "transaction_failure_rolls_back_earlier_update",
        "transaction_constraint_failure_rolls_back_earlier_update",
    }:
        commands: list[_UpdateCommand] = [
            {
                "id": "ordered-post-update",
                "type": "update",
                "model": "Post",
                "data": {"id": post_id, "duration": 81.5},
            },
            {
                "id": "ordered-feed-update",
                "type": "update",
                "model": "Feed",
                "data": {
                    "id": pair.manifest.feed_ids[1],
                    "chapter_filter_strings": "synthetic filter",
                },
            },
            {
                "id": "ordered-post-update-again",
                "type": "update",
                "model": "Post",
                "data": {"id": post_id, "duration": 82.5},
            },
        ]
        if case_id == "transaction_failure_rolls_back_earlier_update":
            commands[1] = {
                "id": "missing-post-update",
                "type": "update",
                "model": "Post",
                "data": {"id": missing_post_id, "duration": 99},
            }
        elif case_id == "transaction_constraint_failure_rolls_back_earlier_update":
            # Python assigns this valid model attribute and fails at commit on
            # ModelCall.status's NOT NULL constraint. Rust observes the constraint
            # while executing the UPDATE; both must roll back the first update.
            commands[1] = {
                "id": "null-model-call-status",
                "type": "update",
                "model": "ModelCall",
                "data": {"id": 601, "status": None},
            }
        wire_commands = [
            {
                "command_id": command["id"],
                **_update(
                    command["model"],
                    command["data"]["id"],
                    {
                        key: value
                        for key, value in command["data"].items()
                        if key != "id"
                    },
                ),
            }
            for command in commands
        ]
        operation = {"operation": "transaction", "commands": wire_commands}
        return (
            operation,
            WriteCommand(
                f"parity-{case_id}",
                WriteCommandType.TRANSACTION,
                None,
                {"commands": commands},
            ),
        )
    raise AssertionError(f"No transaction parity builder for {case_id}")


def assert_writer_transaction_parity(observation: dict[str, Any]) -> None:
    """Compare outcome and persisted state; retain distinct legacy error text."""
    case_id = observation["case"]["case_id"]
    python_success = observation["python_success"]
    rust_success = observation["rust_success"]
    expected_success = observation["case"].get("expect_success", True)
    assert python_success is expected_success, {
        "case_id": case_id,
        "python_error": observation["python_error"],
    }
    assert rust_success is expected_success, {
        "case_id": case_id,
        "rust_error": observation["rust_error"],
    }
    assert python_success is rust_success, {
        "case_id": case_id,
        "python_error": observation["python_error"],
        "rust_error": observation["rust_error"],
    }
    if not python_success:
        assert observation["python_rows"] == observation["python_before"], (
            f"Python failure mutated state: {case_id}"
        )
        assert observation["rust_rows"] == observation["rust_before"], (
            f"Rust failure mutated state: {case_id}"
        )
        assert observation["python_rows"] == observation["rust_rows"], (
            f"failure rollback differs for {case_id}"
        )
        return

    assert observation["python_data"] == observation["rust_result"], {
        "case_id": case_id,
        "python_result": observation["python_data"],
        "rust_result": observation["rust_result"],
    }
    assert observation["python_rows"] == observation["rust_rows"], (
        f"database effects differ for {case_id}"
    )

    if case_id == "transaction_ordered_results":
        results = observation["python_data"]["results"]
        assert [result["command_id"] for result in results] == [
            "ordered-post-update",
            "ordered-feed-update",
            "ordered-post-update-again",
        ]
