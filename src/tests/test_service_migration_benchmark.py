from __future__ import annotations

import json

import pytest
from scripts.bench_service_migration import (
    parse_size_bytes,
    parse_writer_timing,
    quantiles,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1KiB", 1024), ("1.5MiB", 1_572_864), ("2 MB", 2_000_000)],
)
def test_parse_size_bytes(raw: str, expected: int) -> None:
    assert parse_size_bytes(raw) == expected


def test_quantiles_report_expected_keys() -> None:
    result = quantiles([float(value) for value in range(1, 101)])
    assert result == {"p50": 50.5, "p95": 95.05, "p99": 99.01, "max": 100.0}


def test_parse_writer_timing_filters_actions_and_counts_failures() -> None:
    good = {
        "action": "replace_transcription",
        "queue_ms": 2.0,
        "execution_ms": 8.0,
        "total_ms": 10.0,
        "success": True,
    }
    failed = {**good, "queue_ms": 4.0, "success": False}
    ignored = {**good, "action": "dequeue_job"}
    logs = "\n".join(
        f'INFO [WRITER_TIMING] {json.dumps(row)} | extra={{"taskName":null}}'
        for row in (good, failed, ignored)
    )

    result = parse_writer_timing(logs, {"replace_transcription"})

    assert result["count"] == 2
    assert result["failures"] == 1
    assert result["queue_ms"]["p50"] == 3.0
