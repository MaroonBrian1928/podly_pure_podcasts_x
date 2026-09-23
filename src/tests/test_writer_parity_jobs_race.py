from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.writer.protocol import WriteCommand, WriteCommandType
from tests.test_writer_differential_parity import (
    RustWriterParityServer,
    execute_python_parity_command,
    writer_database_projection,
)
from tests.writer_parity_fixtures import WriterParityPair
from tests.writer_parity_jobs import (
    _normalize_time_columns,
    build_writer_job_case,
    writer_job_records,
)


def test_dequeue_job_concurrent_polls_never_claim_the_same_or_multiple_jobs(
    writer_parity_pair: WriterParityPair, tmp_path: Path
) -> None:
    pair = writer_parity_pair
    operation, base_command = build_writer_job_case("action_dequeue_job_claim", pair)
    python_before = writer_database_projection(
        pair.python.db_path, pair.python.instance_dir
    )
    rust_before = writer_database_projection(pair.rust.db_path, pair.rust.instance_dir)

    rust = RustWriterParityServer(pair.rust.db_path, tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            rust_outcomes = list(
                pool.map(lambda _index: rust.execute_outcome(operation), range(8))
            )
    finally:
        rust.close()

    python_results = []
    for index in range(8):
        command = WriteCommand(
            f"{base_command.id}-{index}",
            WriteCommandType.ACTION,
            None,
            json.loads(json.dumps(base_command.data)),
        )
        success, result, error = execute_python_parity_command(pair.python, command)
        assert success, error
        python_results.append(result)

    rust_results = [outcome["result"] for outcome in rust_outcomes]
    assert sum(result is not None for result in rust_results) == 1
    assert sum(result is not None for result in python_results) == 1
    expected_job = "00000000-0000-0000-0000-000000000451"
    assert next(result for result in rust_results if result is not None) == {
        "job_id": expected_job,
        "post_guid": pair.manifest.post_guids[0],
    }
    assert next(result for result in python_results if result is not None) == {
        "job_id": expected_job,
        "post_guid": pair.manifest.post_guids[0],
    }

    python_after = writer_database_projection(
        pair.python.db_path, pair.python.instance_dir
    )
    rust_after = writer_database_projection(pair.rust.db_path, pair.rust.instance_dir)
    python_after["processing_job"] = _normalize_time_columns(
        pair.python.db_path,
        "processing_job",
        python_after["processing_job"],
        python_before["processing_job"],
    )
    rust_after["processing_job"] = _normalize_time_columns(
        pair.rust.db_path,
        "processing_job",
        rust_after["processing_job"],
        rust_before["processing_job"],
    )
    assert rust_after == python_after
    jobs = writer_job_records(pair.rust.db_path, rust_after["processing_job"])
    assert jobs[expected_job]["status"] == "running"
    assert jobs["00000000-0000-0000-0000-000000000452"]["status"] == "pending"
