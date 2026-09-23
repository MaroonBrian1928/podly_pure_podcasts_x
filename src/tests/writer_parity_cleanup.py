"""Differential cases for cleanup actions on isolated Python/Rust clones."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from app.writer.protocol import WriteCommand, WriteCommandType
from tests.writer_parity_fixtures import WriterParityPair

WRITER_DIFFERENTIAL_CASES = (
    {
        "case_id": "cleanup_missing_audio_paths_recover_and_requeue",
        "operation": "action",
        "action": "cleanup_missing_audio_paths",
        "owner": "cleanup_missing_audio_paths",
        "owner_group": "cleanup",
        "source": "src/app/writer/actions/cleanup.py:cleanup_missing_audio_paths_action",
        "semantics": "path_recovery_and_requeue",
    },
    {
        "case_id": "cleanup_clear_all_processing_data",
        "operation": "action",
        "action": "clear_post_processing_data",
        "owner": "clear_post_processing_data",
        "owner_group": "cleanup",
        "source": "src/app/writer/actions/cleanup.py:clear_post_processing_data_action",
    },
    {
        "case_id": "cleanup_clear_outputs_keep_transcript",
        "operation": "action",
        "action": "clear_post_processing_data_keep_transcript",
        "owner": "clear_post_processing_data_keep_transcript",
        "owner_group": "cleanup",
        "source": "src/app/writer/actions/cleanup.py:clear_post_processing_data_keep_transcript_action",
    },
    {
        "case_id": "cleanup_prepare_auto_retry_preserves_input",
        "operation": "action",
        "action": "prepare_post_for_auto_retry",
        "owner": "prepare_post_for_auto_retry",
        "owner_group": "cleanup",
        "source": "src/app/writer/actions/cleanup.py:prepare_post_for_auto_retry_action",
        "semantics": "retry_preserves_unprocessed_and_transcript",
    },
    {
        "case_id": "cleanup_prepare_auto_retry_db_failure_after_unlink",
        "operation": "action",
        "action": "prepare_post_for_auto_retry",
        "owner": "prepare_post_for_auto_retry",
        "owner_group": "cleanup",
        "source": "src/app/writer/actions/cleanup.py:prepare_post_for_auto_retry_action",
        "semantics": "precommit_unlink_and_db_rollback",
        "expect_success": False,
    },
    {
        "case_id": "cleanup_processed_post_clears_db_state",
        "operation": "action",
        "action": "cleanup_processed_post",
        "owner": "cleanup_processed_post",
        "owner_group": "cleanup",
        "source": "src/app/writer/actions/cleanup.py:cleanup_processed_post_action",
    },
    {
        "case_id": "cleanup_processed_post_files_only",
        "operation": "action",
        "action": "cleanup_processed_post_files_only",
        "owner": "cleanup_processed_post_files_only",
        "owner_group": "cleanup",
        "source": "src/app/writer/actions/cleanup.py:cleanup_processed_post_files_only_action",
        "semantics": "unlink_files_keep_processing_metadata",
    },
)

_POST_ID = 301
_POST_GUID = "parity-integral-duration"
_INPUT_NAME = "cleanup-parity-input.mp3"


def _case(case_id: str) -> dict[str, Any]:
    return next(
        item for item in WRITER_DIFFERENTIAL_CASES if item["case_id"] == case_id
    )


def _paths(backend: Any) -> tuple[Path, Path, Path]:
    input_path = backend.data_in / _INPUT_NAME
    processed_path = (
        backend.data_srv / "Parity_feed_one" / "cleanup-parity-processed.mp3"
    )
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_bytes(b"synthetic unprocessed audio\n")
    processed_path.write_bytes(b"synthetic processed audio\n")
    return input_path, processed_path, backend.data_srv


def _seed_backend(backend: Any, case_id: str) -> None:
    input_path, processed_path, srv_root = _paths(backend)
    missing_input = backend.data_in / "intentionally-missing-input.mp3"
    stale_processed = backend.data_srv / "intentionally-missing-processed.mp3"
    if case_id == "cleanup_missing_audio_paths_recover_and_requeue":
        # Rust and Python both search the sanitized feed directory for a
        # processed copy derived from the unprocessed basename.
        derived_path = srv_root / "Parity_feed_one" / missing_input.name
        derived_path.write_bytes(b"recoverable derived processed audio\n")
        input_value = str(missing_input)
        processed_value = str(stale_processed)
    else:
        input_value = str(input_path)
        processed_value = str(processed_path)

    with sqlite3.connect(backend.db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """UPDATE post SET whitelisted=1,unprocessed_audio_path=?,
               processed_audio_path=?,duration=123.5,chapter_data='[1]',
               bleep_windows='[[1,2]]',transcript_word_timestamps='[{\"word\":\"kept\"}]',
               refined_ad_boundaries='[{\"start\":1,\"end\":2}]',
               refined_ad_boundaries_updated_at='2026-01-02 03:04:05.000000'
               WHERE id=?""",
            (input_value, processed_value, _POST_ID),
        )
        # Create both retainable Whisper output and a disposable classifier
        # call so keep-transcript/retry cases exercise the action's predicate.
        connection.execute(
            """UPDATE model_call SET model_name='whisper-large-v3',
               prompt='Whisper transcription job' WHERE id=601"""
        )
        connection.execute(
            """INSERT INTO model_call
               (id,post_id,first_segment_sequence_num,last_segment_sequence_num,
                model_name,prompt,response,timestamp,status,prompt_tokens,
                completion_tokens,total_tokens,retry_attempts)
               VALUES (602,301,10,10,'synthetic/classifier','Synthetic classifier',
                       'Synthetic response','2026-01-02 03:04:05.000000','success',1,1,2,0)"""
        )
        if case_id == "cleanup_missing_audio_paths_recover_and_requeue":
            connection.execute(
                """UPDATE processing_job SET status='failed',current_step=4,
                   step_name='Failed',error_message='missing output',started_at=?,
                   completed_at=?,created_at=?,stage_history='[]'
                   WHERE id='00000000-0000-0000-0000-000000000403'""",
                (
                    "2026-01-02 03:04:05.000000",
                    "2026-01-02 03:04:06.000000",
                    "2026-01-02 03:04:07.000000",
                ),
            )
        if case_id == "cleanup_prepare_auto_retry_db_failure_after_unlink":
            connection.execute(
                """CREATE TRIGGER parity_interrupt_cleanup_model_call
                   BEFORE DELETE ON model_call
                   WHEN OLD.id=602
                   BEGIN SELECT RAISE(ABORT, 'synthetic interrupted cleanup'); END"""
            )


def build_writer_cleanup_case(
    case_id: str, pair: WriterParityPair
) -> tuple[dict[str, Any], WriteCommand, dict[str, dict[str, str]]]:
    """Build each action against an isolated data root and matching DB clone."""
    case = _case(case_id)
    for backend in (pair.python, pair.rust):
        _seed_backend(backend, case_id)

    action = case["action"]
    params = {} if action == "cleanup_missing_audio_paths" else {"post_id": _POST_ID}
    operation = {
        "operation": "action",
        "action": action,
        "params": json.loads(json.dumps(params)),
    }
    command = WriteCommand(
        f"parity-{case_id}",
        WriteCommandType.ACTION,
        None,
        {"action": action, "params": json.loads(json.dumps(params))},
    )
    environment_overrides = {
        backend_name: {
            "PODLY_INSTANCE_DIR": str(backend.instance_dir),
            "PODLY_PODCAST_DATA_DIR": str(backend.instance_dir / "data"),
        }
        for backend_name, backend in (("python", pair.python), ("rust", pair.rust))
    }
    return operation, command, environment_overrides


def _projection_records(
    observation: dict[str, Any], backend: str, table: str
) -> list[dict[str, Any]]:
    db_path = getattr(observation["pair"], backend).db_path
    with sqlite3.connect(db_path) as connection:
        columns = [
            row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
        ]
    return [
        dict(zip(columns, row, strict=True))
        for row in observation[f"{backend}_rows"][table]
    ]


def _database_row_diff_summary(
    python_rows: dict[str, list[tuple[Any, ...]]],
    rust_rows: dict[str, list[tuple[Any, ...]]],
    db_path: Path,
) -> str:
    """Describe differing table/column names without logging database values."""
    summaries = []
    for table in sorted(python_rows.keys() | rust_rows.keys()):
        python_table = python_rows.get(table, [])
        rust_table = rust_rows.get(table, [])
        if python_table == rust_table:
            continue

        with sqlite3.connect(db_path) as connection:
            info = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
        columns = [row[1] for row in info]
        primary_key = [
            index
            for _, index in sorted(
                (row[5], index) for index, row in enumerate(info) if row[5]
            )
        ]
        if primary_key:
            python_by_key = {
                tuple(row[index] for index in primary_key): row for row in python_table
            }
            rust_by_key = {
                tuple(row[index] for index in primary_key): row for row in rust_table
            }
            common_keys = python_by_key.keys() & rust_by_key.keys()
            differing_columns = Counter(
                columns[index]
                for key in common_keys
                for index, (python_value, rust_value) in enumerate(
                    zip(python_by_key[key], rust_by_key[key], strict=True)
                )
                if python_value != rust_value
            )
            python_only = len(python_by_key.keys() - rust_by_key.keys())
            rust_only = len(rust_by_key.keys() - python_by_key.keys())
        else:
            differing_columns = Counter()
            python_only = len(python_table)
            rust_only = len(rust_table)

        names = sorted(
            differing_columns, key=lambda name: (-differing_columns[name], name)
        )
        shown_columns = names[:12]
        if len(names) > len(shown_columns):
            shown_columns.append(f"...+{len(names) - len(shown_columns)}")
        summaries.append(
            f"{table}(python_only_rows={python_only},rust_only_rows={rust_only},"
            f"differing_columns={shown_columns})"
        )
        if len(summaries) == 6:
            summaries.append("...")
            break
    return "; ".join(summaries)


def _normalize_times(
    projection: dict[str, list[tuple[Any, ...]]],
    before: dict[str, list[tuple[Any, ...]]],
    db_path: Path,
) -> dict[str, list[tuple[Any, ...]]]:
    normalized = dict(projection)
    with sqlite3.connect(db_path) as connection:
        table_columns = {
            table: [
                row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
            ]
            for table in ("processing_job", "jobs_manager_run")
            if table in normalized
        }
    for table, columns in table_columns.items():
        time_columns = {
            "processing_job": {"started_at", "completed_at"},
            "jobs_manager_run": {
                "started_at",
                "completed_at",
                "updated_at",
                "counters_reset_at",
            },
        }[table]
        indices = [columns.index(name) for name in time_columns if name in columns]
        history_index = (
            columns.index("stage_history") if table == "processing_job" else None
        )
        prior_by_id = {row[0]: row for row in before[table]}
        rows = []
        for row in normalized[table]:
            values = list(row)
            prior = prior_by_id.get(row[0])
            for index in indices:
                if (
                    prior is not None
                    and values[index] != prior[index]
                    and values[index]
                ):
                    values[index] = "<changed-time>"
            if history_index is not None and values[history_index]:
                history = json.loads(values[history_index])
                previous = (
                    json.loads(prior[history_index])
                    if prior and prior[history_index]
                    else []
                )
                for item_index, entry in enumerate(history):
                    if not isinstance(entry, dict) or not entry.get("started_at"):
                        continue
                    previous_started = (
                        previous[item_index].get("started_at")
                        if item_index < len(previous)
                        and isinstance(previous[item_index], dict)
                        else None
                    )
                    if entry["started_at"] != previous_started:
                        entry["started_at"] = "<changed-time>"
                values[history_index] = json.dumps(
                    history, sort_keys=True, separators=(",", ":")
                )
            rows.append(tuple(values))
        normalized[table] = rows
    return normalized


def _files(backend: Any) -> dict[str, bytes]:
    root = backend.instance_dir / "data"
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def assert_writer_cleanup_parity(observation: dict[str, Any]) -> None:
    """Compare writer outcome, all rows, and clone-local file effects."""
    case = observation["case"]
    case_id = case["case_id"]
    pair = observation["pair"]
    expected_success = case.get("expect_success", True)
    assert observation["python_success"] is expected_success, observation[
        "python_error"
    ]
    assert observation["rust_success"] is expected_success, observation["rust_error"]

    if not expected_success:
        assert observation["python_error"] and observation["rust_error"]
        assert observation["python_before"] == observation["python_rows"]
        assert observation["rust_before"] == observation["rust_rows"]
        # Filesystem unlink is outside the DB transaction: the retry action
        # removes its processed candidate before the injected SQL failure.
        for backend in (pair.python, pair.rust):
            input_path, processed_path, _ = _paths_for_assertion(backend)
            assert input_path.is_file()
            assert not processed_path.exists()
        assert _files(pair.python) == _files(pair.rust)
        return

    assert observation["rust_result"] == observation["python_data"], {
        "case_id": case_id,
        "python_result": observation["python_data"],
        "rust_result": observation["rust_result"],
    }
    python_rows = _normalize_times(
        observation["python_rows"], observation["python_before"], pair.python.db_path
    )
    rust_rows = _normalize_times(
        observation["rust_rows"], observation["rust_before"], pair.rust.db_path
    )
    if python_rows != rust_rows:
        raise AssertionError(
            f"database effects differ for {case_id}; "
            "value-free table/column summary: "
            f"{_database_row_diff_summary(python_rows, rust_rows, pair.python.db_path)}"
        )
    assert _files(pair.python) == _files(pair.rust), f"filesystem differs for {case_id}"

    python_post = next(
        row
        for row in _projection_records(observation, "python", "post")
        if row["id"] == _POST_ID
    )
    python_transcripts = _projection_records(
        observation, "python", "transcript_segment"
    )
    python_model_calls = [
        row
        for row in _projection_records(observation, "python", "model_call")
        if row["post_id"] == _POST_ID
    ]
    python_jobs = [
        row
        for row in _projection_records(observation, "python", "processing_job")
        if row["post_guid"] == _POST_GUID
    ]

    if case_id == "cleanup_missing_audio_paths_recover_and_requeue":
        assert observation["python_data"] == 1
        assert python_post["unprocessed_audio_path"] is None
        assert python_post["processed_audio_path"].endswith(
            "intentionally-missing-input.mp3"
        )
        latest = max(python_jobs, key=lambda row: row["created_at"])
        assert latest["status"] == "pending"
        assert latest["current_step"] == 0
        assert latest["step_name"] == "Not started"
    elif case_id == "cleanup_clear_all_processing_data":
        assert observation["python_data"] == {"post_id": _POST_ID}
        assert not [row for row in python_transcripts if row["post_id"] == _POST_ID]
        assert not python_model_calls
        assert not python_jobs
        assert python_post["duration"] is None
        assert python_post["transcript_word_timestamps"] == "null"
    elif case_id == "cleanup_clear_outputs_keep_transcript":
        assert observation["python_data"] == {"post_id": _POST_ID}
        assert [row for row in python_transcripts if row["post_id"] == _POST_ID]
        assert {row["id"] for row in python_model_calls} == {601}
        assert not python_jobs
        assert python_post["duration"] is None
        assert python_post["transcript_word_timestamps"] is not None
    elif case_id == "cleanup_prepare_auto_retry_preserves_input":
        assert observation["python_data"] == {"post_id": _POST_ID}
        assert python_post["processed_audio_path"] is None
        assert python_post["unprocessed_audio_path"].endswith(_INPUT_NAME)
        assert [row for row in python_transcripts if row["post_id"] == _POST_ID]
        assert {row["id"] for row in python_model_calls} == {601}
        assert len(python_jobs) == 2
        _assert_retry_files(pair.python, processed_exists=False)
        _assert_retry_files(pair.rust, processed_exists=False)
    elif case_id == "cleanup_processed_post_clears_db_state":
        assert observation["python_data"] == {"post_id": _POST_ID}
        assert python_post["whitelisted"] in (False, 0)
        assert python_post["duration"] is None
        assert not [row for row in python_transcripts if row["post_id"] == _POST_ID]
        assert not python_model_calls
        assert not python_jobs
    elif case_id == "cleanup_processed_post_files_only":
        assert observation["python_data"] == {"post_id": _POST_ID}
        assert python_post["whitelisted"] in (False, 0)
        assert python_post["unprocessed_audio_path"] is None
        assert python_post["processed_audio_path"] is None
        assert python_post["duration"] == 123.5
        assert [row for row in python_transcripts if row["post_id"] == _POST_ID]
        assert python_model_calls
        assert python_jobs
        _assert_files_only_deleted(pair.python)
        _assert_files_only_deleted(pair.rust)


def _paths_for_assertion(backend: Any) -> tuple[Path, Path, Path]:
    input_path = backend.data_in / _INPUT_NAME
    processed_path = (
        backend.data_srv / "Parity_feed_one" / "cleanup-parity-processed.mp3"
    )
    return input_path, processed_path, backend.data_srv


def _assert_retry_files(backend: Any, *, processed_exists: bool) -> None:
    input_path, processed_path, _ = _paths_for_assertion(backend)
    assert input_path.is_file()
    assert processed_path.exists() is processed_exists


def _assert_files_only_deleted(backend: Any) -> None:
    input_path, processed_path, _ = _paths_for_assertion(backend)
    assert not input_path.exists()
    assert not processed_path.exists()
