"""Differential parity cases for transcript and processor persistence actions."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from app.writer.protocol import WriteCommand, WriteCommandType
from tests.writer_parity_fixtures import WriterParityPair

ParamsFactory = Callable[[WriterParityPair], dict[str, Any]]
_NORMALIZED_TEMP_FILES_BEFORE: dict[str, set[str]] = {}


WRITER_DIFFERENTIAL_CASES = (
    {
        "case_id": "processor_upsert_model_call_new_precision",
        "operation": "action",
        "action": "upsert_model_call",
        "owner": "upsert_model_call",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
        "semantics": "new_model_call",
    },
    {
        "case_id": "processor_delete_model_calls_by_name",
        "operation": "action",
        "action": "delete_model_calls_for_post_by_model_name",
        "owner": "delete_model_calls_for_post_by_model_name",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
    },
    {
        "case_id": "processor_upsert_whisper_model_call_reset_fields",
        "operation": "action",
        "action": "upsert_whisper_model_call",
        "owner": "upsert_whisper_model_call",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
    },
    {
        "case_id": "processor_replace_transcription_large_precision",
        "operation": "action",
        "action": "replace_transcription",
        "owner": "replace_transcription",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
        "semantics": "transcription_json",
    },
    {
        "case_id": "processor_start_transcription_replace_side_effects",
        "operation": "action",
        "action": "start_transcription_replace",
        "owner": "start_transcription_replace",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
    },
    {
        "case_id": "processor_insert_transcript_segments_large_precision",
        "operation": "action",
        "action": "insert_transcript_segments",
        "owner": "insert_transcript_segments",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
        "semantics": "transcript_segment_order",
    },
    {
        "case_id": "processor_insert_transcript_segments_partial_failure_rolls_back",
        "operation": "action",
        "action": "insert_transcript_segments",
        "owner": "insert_transcript_segments",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
        "expect_success": False,
    },
    {
        "case_id": "processor_finish_transcription_replace_updates_model_and_json",
        "operation": "action",
        "action": "finish_transcription_replace",
        "owner": "finish_transcription_replace",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
        "semantics": "transcription_json",
    },
    {
        "case_id": "processor_finish_transcription_replace_from_large_artifact",
        "operation": "action",
        "action": "finish_transcription_replace_from_artifact",
        "owner": "finish_transcription_replace_from_artifact",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
        "semantics": "artifact",
    },
    {
        "case_id": "processor_mark_model_call_failed_unicode",
        "operation": "action",
        "action": "mark_model_call_failed",
        "owner": "mark_model_call_failed",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
    },
    {
        "case_id": "processor_insert_identifications_large_duplicate_batch",
        "operation": "action",
        "action": "insert_identifications",
        "owner": "insert_identifications",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
        "semantics": "identification_batch",
    },
    {
        "case_id": "processor_replace_identifications_requested_delete_count",
        "operation": "action",
        "action": "replace_identifications",
        "owner": "replace_identifications",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
    },
    {
        "case_id": "processor_replace_identifications_failure_rolls_back_delete",
        "operation": "action",
        "action": "replace_identifications",
        "owner": "replace_identifications",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
        "expect_success": False,
    },
    {
        "case_id": "processor_replace_audio_segments_precision_and_filtering",
        "operation": "action",
        "action": "replace_audio_segments",
        "owner": "replace_audio_segments",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
        "semantics": "audio_segments",
    },
    {
        "case_id": "processor_replace_audio_segments_failure_rolls_back_delete",
        "operation": "action",
        "action": "replace_audio_segments",
        "owner": "replace_audio_segments",
        "owner_group": "processor",
        "source": "src/app/writer/actions/processor.py",
        "expect_success": False,
    },
)


def _long_transcript_text() -> str:
    return "Synthetic transcript — café, 東京, and precise speech. " * 11_000


def _word_timestamp_payload(*, word_count: int = 4) -> list[dict[str, Any]]:
    words = [
        {
            "word": f"café-{index:05d}",
            "start": index * 0.125000000123,
            "end": index * 0.125000000123 + 0.087654321987,
            "score": 0.987654321012 if index % 2 == 0 else None,
        }
        for index in range(word_count)
    ]
    return [{"sequence_num": 3, "words": words}]


def _large_word_timestamp_payload() -> list[dict[str, Any]]:
    return _word_timestamp_payload(word_count=9_000)


def _segments() -> list[dict[str, Any]]:
    return [
        {
            "sequence_num": 11,
            "start_time": 0.100000000123,
            "end_time": 0.987654321987,
            "text": _long_transcript_text(),
            "speaker_label": "Speaker café 🐕",
        },
        {
            "sequence_num": 12,
            "start_time": 1.234567890123,
            "end_time": 2.345678901234,
            "text": "second segment 東京",
            "speaker_label": None,
        },
    ]


def _bulk_segments() -> list[dict[str, Any]]:
    chunk = "Synthetic batch transcript text with enough content. " * 110
    return [
        {
            "sequence_num": 1_000 + index,
            "start_time": index * 0.125000000123,
            "end_time": index * 0.125000000123 + 0.111111111987,
            "text": f"{index:04d}: {chunk}",
            "speaker_label": "A" if index % 2 == 0 else "B",
        }
        for index in range(96)
    ]


def _identifications(*, count: int = 2) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = [
        {
            "transcript_segment_id": 701,
            "model_call_id": 601,
            "label": "ad",
            "confidence": 0.912345678901,
        },
        {
            "transcript_segment_id": 701,
            "model_call_id": 601,
            "label": "ad",
            "confidence": 0.1,
        },
        "skip-non-object",
    ]
    values.extend(
        {
            "transcript_segment_id": 701,
            "model_call_id": 601,
            "label": f"synthetic-{index:04d}",
            "confidence": index / 1_000_003,
        }
        for index in range(count)
    )
    return values


def _params_for_case(case_id: str, pair: WriterParityPair) -> dict[str, Any]:
    manifest = pair.manifest
    factories = {
        "processor_upsert_model_call_new_precision": lambda: {
            "post_id": manifest.post_ids[1],
            "model_name": "synthetic/parity-upsert-model",
            "first_segment_sequence_num": 7,
            "last_segment_sequence_num": 19,
            "prompt": "Synthetic prompt with precision-safe sequence bounds — 東京",
        },
        "processor_delete_model_calls_by_name": lambda: {
            "post_id": manifest.post_ids[1],
            "model_name": "synthetic/delete-target",
        },
        "processor_upsert_whisper_model_call_reset_fields": lambda: {
            "post_id": manifest.post_ids[0],
            "model_name": "synthetic/parity-model",
            "first_segment_sequence_num": 0,
            "last_segment_sequence_num": 0,
            "prompt": "Synthetic whisper prompt",
            "reset_fields": {
                "status": "failed_retries",
                "prompt": "Synthetic retry prompt",
                "retry_attempts": 2,
                "error_message": "Synthetic prior failure",
                "response": "Synthetic prior response",
            },
        },
        "processor_replace_transcription_large_precision": lambda: {
            "post_id": manifest.post_ids[0],
            "model_call_id": 601,
            "segments": _segments(),
            "transcript_word_timestamps": _word_timestamp_payload(),
        },
        "processor_start_transcription_replace_side_effects": lambda: {
            "post_id": manifest.post_ids[0],
            "model_call_id": 601,
        },
        "processor_insert_transcript_segments_large_precision": lambda: {
            "post_id": manifest.post_ids[1],
            "segments": _bulk_segments(),
        },
        "processor_insert_transcript_segments_partial_failure_rolls_back": lambda: {
            "post_id": manifest.post_ids[1],
            "segments": [
                {
                    "sequence_num": 91,
                    "start_time": 0.25,
                    "end_time": 0.5,
                    "text": "would be inserted",
                },
                {"sequence_num": 92, "start_time": 0.75, "text": "missing end_time"},
            ],
        },
        "processor_finish_transcription_replace_updates_model_and_json": lambda: {
            "post_id": manifest.post_ids[0],
            "model_call_id": 601,
            "segment_count": 17,
            "transcript_word_timestamps": _word_timestamp_payload(),
        },
        "processor_finish_transcription_replace_from_large_artifact": lambda: {
            "post_id": manifest.post_ids[0],
            "model_call_id": 601,
            "segment_count": 9_000,
        },
        "processor_mark_model_call_failed_unicode": lambda: {
            "model_call_id": 601,
            "status": "failed_retries",
            "error_message": "Synthetic provider failure: café 東京 🐕",
        },
        "processor_insert_identifications_large_duplicate_batch": lambda: {
            "identifications": _identifications(count=540)
        },
        "processor_replace_identifications_requested_delete_count": lambda: {
            "delete_ids": [801, 987_654],
            "new_identifications": [
                {
                    "transcript_segment_id": 701,
                    "model_call_id": 601,
                    "label": "replacement-label",
                    "confidence": 0.500000000123,
                },
                {
                    "transcript_segment_id": 701,
                    "model_call_id": 601,
                    "label": "replacement-label",
                    "confidence": 0.2,
                },
            ],
        },
        "processor_replace_identifications_failure_rolls_back_delete": lambda: {
            "delete_ids": [801],
            "new_identifications": [
                {"transcript_segment_id": 701, "label": "missing-model-call"}
            ],
        },
        "processor_replace_audio_segments_precision_and_filtering": lambda: {
            "post_id": manifest.post_ids[0],
            "model_call_id": 601,
            "segments": [
                {
                    "start_time": 0.125000000123,
                    "end_time": 0.987654321987,
                    "label": "speech café",
                },
                {
                    "start_time": 2.0,
                    "end_time": 1.0,
                    "label": "discarded-reversed-window",
                },
                "skip-non-object",
                {
                    "start_time": 1.234567890123,
                    "end_time": 1.999999999987,
                    "label": "music",
                },
            ],
        },
        "processor_replace_audio_segments_failure_rolls_back_delete": lambda: {
            "post_id": manifest.post_ids[0],
            "model_call_id": 601,
            "segments": [
                {"start_time": 10.0, "end_time": 11.0, "label": "would replace"},
                {"start_time": 12.0, "label": "missing end"},
            ],
        },
    }
    try:
        return factories[case_id]()
    except KeyError as exc:
        raise AssertionError(f"No processor payload factory for {case_id}") from exc


def _seed_delete_target(pair: WriterParityPair) -> None:
    sql = """INSERT INTO model_call(
        id,post_id,first_segment_sequence_num,last_segment_sequence_num,
        model_name,prompt,timestamp,status,retry_attempts
    ) VALUES (?,?,?,?,?,?,?,?,?)"""
    rows = [
        (
            602,
            pair.manifest.post_ids[1],
            0,
            1,
            "synthetic/delete-target",
            "one",
            "2026-01-01 00:00:00",
            "success",
            0,
        ),
        (
            603,
            pair.manifest.post_ids[1],
            3,
            8,
            "synthetic/delete-target",
            "two",
            "2026-01-02 00:00:00",
            "failed_retries",
            1,
        ),
        (
            604,
            pair.manifest.post_ids[1],
            0,
            1,
            "synthetic/keep-target",
            "keep",
            "2026-01-03 00:00:00",
            "success",
            0,
        ),
    ]
    for backend in (pair.python, pair.rust):
        with sqlite3.connect(backend.db_path) as connection:
            connection.executemany(sql, rows)


def _artifact_path(backend: Any, case_id: str) -> Path:
    return backend.instance_dir / "data" / "processor-artifacts" / f"{case_id}.json"


def _write_artifact(backend: Any, case_id: str) -> Path:
    path = _artifact_path(backend, case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_large_word_timestamp_payload(), ensure_ascii=False))
    return path


def writer_processor_environment(
    case_id: str, pair: WriterParityPair
) -> dict[str, dict[str, str]]:
    if case_id != "processor_finish_transcription_replace_from_large_artifact":
        return {"python": {}, "rust": {}}
    return {
        backend.name: {
            "PODLY_INSTANCE_DIR": str(backend.instance_dir),
            "PODLY_PODCAST_DATA_DIR": str(backend.instance_dir / "data"),
            **(
                {
                    "PODLY_RUST_TOOLS_BIN": str(
                        Path(__file__).resolve().parents[2]
                        / "rust"
                        / "target"
                        / "debug"
                        / "podly_tools"
                    )
                }
                if backend.name == "python"
                else {}
            ),
        }
        for backend in (pair.python, pair.rust)
    }


def build_writer_processor_case(
    case_id: str, pair: WriterParityPair
) -> tuple[dict[str, Any], WriteCommand, dict[str, dict[str, str]]]:
    if case_id == "processor_delete_model_calls_by_name":
        _seed_delete_target(pair)
    params = _params_for_case(case_id, pair)
    rust_params = dict(params)
    python_params = dict(params)
    environments = writer_processor_environment(case_id, pair)
    if case_id == "processor_finish_transcription_replace_from_large_artifact":
        python_path = _write_artifact(pair.python, case_id)
        rust_path = _write_artifact(pair.rust, case_id)
        _NORMALIZED_TEMP_FILES_BEFORE[case_id] = {
            str(path) for path in Path(tempfile.gettempdir()).glob("*.normalized.json")
        }
        python_params["artifact_path"] = str(python_path)
        rust_params["artifact_path"] = str(rust_path)

    action = next(
        case["action"]
        for case in WRITER_DIFFERENTIAL_CASES
        if case["case_id"] == case_id
    )
    rust_operation = {"operation": "action", "action": action, "params": rust_params}
    python_command = WriteCommand(
        id=f"parity-{case_id}",
        type=WriteCommandType.ACTION,
        model=None,
        data={"action": action, "params": python_params},
    )
    return rust_operation, python_command, environments


def _table_columns(db_path: Any) -> dict[str, list[str]]:
    with sqlite3.connect(db_path) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            table: [
                row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
            ]
            for table in tables
        }


def _read_model_call(db_path: Any, model_call_id: int) -> dict[str, Any]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM model_call WHERE id=?", (model_call_id,)
        ).fetchone()
        assert row is not None
        return dict(row)


def _semantic_projection(
    projection: dict[str, list[tuple[Any, ...]]],
    columns: dict[str, list[str]],
    *,
    created_model_call_id: int | None = None,
) -> dict[str, list[tuple[Any, ...]]]:
    result: dict[str, list[tuple[Any, ...]]] = {}
    for table, rows in projection.items():
        names = columns[table]
        normalized_rows = []
        for row in rows:
            record = dict(zip(names, row, strict=True))
            if (
                table == "model_call"
                and record.get("id") == created_model_call_id
                and created_model_call_id is not None
            ):
                record["timestamp"] = "<nondeterministic:timestamp>"
            for field in ("transcript_word_timestamps",):
                if field in record and isinstance(record[field], str):
                    try:
                        record[field] = json.dumps(
                            json.loads(record[field]),
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    except json.JSONDecodeError:
                        pass
            normalized_rows.append(tuple(record[name] for name in names))
        result[table] = sorted(normalized_rows, key=repr)
    return result


def _assert_transcript_segment_order(
    db_path: Any, post_id: int, expected: list[dict[str, Any]]
) -> None:
    with sqlite3.connect(db_path) as connection:
        actual = connection.execute(
            "SELECT sequence_num,start_time,end_time,text,speaker_label "
            "FROM transcript_segment WHERE post_id=? ORDER BY sequence_num",
            (post_id,),
        ).fetchall()
    assert len(actual) >= len(expected)
    assert actual[-len(expected) :] == [
        (
            item["sequence_num"],
            float(item["start_time"]),
            float(item["end_time"]),
            item["text"],
            item["speaker_label"],
        )
        for item in expected
    ]


def assert_writer_processor_parity(observation: dict[str, Any]) -> None:
    case = observation["case"]
    case_id = case["case_id"]
    pair = observation["pair"]
    expected_success = case.get("expect_success", True)
    assert observation["python_success"] is expected_success
    assert observation["rust_success"] is expected_success

    if not expected_success:
        assert observation["python_error"]
        assert observation["rust_error"]
        assert observation["python_before"] == observation["python_rows"]
        assert observation["rust_before"] == observation["rust_rows"]
        if case_id == "processor_replace_identifications_failure_rolls_back_delete":
            assert "model_call_id" in str(observation["python_error"])
            assert "model_call_id" in str(observation["rust_error"])
        return

    python_data = observation["python_data"]
    rust_result = observation["rust_result"]
    semantics = case.get("semantics")
    created_model_call_id: int | None = None
    if semantics == "new_model_call":
        assert python_data == rust_result
        created_model_call_id = int(python_data["model_call_id"])
        python_call = _read_model_call(pair.python.db_path, created_model_call_id)
        rust_call = _read_model_call(pair.rust.db_path, created_model_call_id)
        for call in (python_call, rust_call):
            assert call["model_name"] == "synthetic/parity-upsert-model"
            assert call["first_segment_sequence_num"] == 7
            assert call["last_segment_sequence_num"] == 19
            assert call["prompt"].endswith("東京")
            assert call["status"] == "pending"
            assert call["retry_attempts"] == 0
            assert call["error_message"] is None
            assert call["response"] is None
            datetime.fromisoformat(call["timestamp"])
    elif semantics == "transcript_segment_order":
        assert python_data == rust_result
        expected = _bulk_segments()
        for backend in (pair.python, pair.rust):
            _assert_transcript_segment_order(
                backend.db_path, pair.manifest.post_ids[1], expected
            )
    elif semantics == "identification_batch":
        assert python_data == rust_result == {"inserted": 540}
        for backend in (pair.python, pair.rust):
            with sqlite3.connect(backend.db_path) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM identification WHERE label LIKE 'synthetic-%'"
                ).fetchone()[0]
            assert count == 540
    elif semantics == "artifact":
        assert (
            python_data
            == rust_result
            == {
                "post_id": pair.manifest.post_ids[0],
                "segment_count": 9_000,
            }
        )
        for backend in (pair.python, pair.rust):
            artifact = _artifact_path(backend, case_id)
            assert artifact.is_file()
            with sqlite3.connect(backend.db_path) as connection:
                stored = connection.execute(
                    "SELECT transcript_word_timestamps FROM post WHERE id=?",
                    (pair.manifest.post_ids[0],),
                ).fetchone()[0]
            assert json.loads(stored) == _large_word_timestamp_payload()
        prior_temp_files = _NORMALIZED_TEMP_FILES_BEFORE[case_id]
        remaining_temp_files = {
            str(path) for path in Path(tempfile.gettempdir()).glob("*.normalized.json")
        }
        assert remaining_temp_files == prior_temp_files
    else:
        assert python_data == rust_result

    columns = _table_columns(pair.python.db_path)
    python_normalized = _semantic_projection(
        observation["python_rows"], columns, created_model_call_id=created_model_call_id
    )
    rust_normalized = _semantic_projection(
        observation["rust_rows"], columns, created_model_call_id=created_model_call_id
    )
    assert python_normalized == rust_normalized, (
        f"processor DB state differs for {case_id}"
    )
