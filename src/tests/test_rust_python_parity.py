"""Parity tests: Rust sidecar render functions and their Python fallbacks must
agree on the set of JSON fields they emit. Catches the class of bug where a
field is added to one path but not the other -- which has happened twice for
the `service_tier` rollout (jobs list, then stats) because the Rust path is
preferred when available and silently masks the Python addition.

The test seeds a self-contained SQLite fixture matching the production
schemas, invokes the Rust binary directly, and asserts each returned row
includes every field listed in the contract below. The contracts are derived
from the corresponding Python serializers; if you add or rename a field in
either path, update both the Python serializer and this contract.

Skipped if the `podly_tools` binary isn't present on disk (e.g. checkout
without `cargo build --release`).
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest


def _rust_binary_path() -> Path | None:
    env = os.environ.get("PODLY_RUST_TOOLS_BIN")
    if env and Path(env).exists():
        return Path(env)
    repo_root = Path(__file__).resolve().parents[2]
    for candidate in (
        repo_root / "rust" / "target" / "release" / "podly_tools",
        repo_root / "rust" / "target" / "debug" / "podly_tools",
    ):
        if candidate.exists():
            return candidate
    return None


@pytest.fixture
def rust_bin() -> Path:
    path = _rust_binary_path()
    if path is None:
        pytest.skip("podly_tools binary not built; skipping Rust↔Python parity check")
    return path


# -----------------------------------------------------------------------------
# Field contracts
#
# Each set lists the JSON keys the corresponding Python serializer emits per
# row. The Rust render function MUST emit at least these keys for each row
# in the relevant collection.
#
# Source of truth for each contract:
#   JOB_LIST_FIELDS:
#     - Python: app/jobs_manager.py::list_active_jobs / list_all_jobs_detailed
#     - Rust:   rust/src/main.rs::render_jobs
#   MODEL_CALL_DETAIL_FIELDS:
#     - Python: app/routes/post_routes.py model_call_details build (~L713)
#     - Rust:   rust/src/main.rs::render_stats "model_calls" projection
# -----------------------------------------------------------------------------
JOB_LIST_FIELDS: frozenset[str] = frozenset(
    {
        "job_id",
        "post_guid",
        "post_title",
        "feed_title",
        "status",
        "priority",
        "step",
        "step_name",
        "total_steps",
        "progress_percentage",
        "created_at",
        "started_at",
        "completed_at",
        "error_message",
        "stage_history",
        "ad_windows_count",
        "had_classification_parse_error",
        "auto_retry_attempted",
        # service_tier is only present when at least one ModelCall row has a
        # non-null tier -- enforced by the seeded fixture, which includes
        # exactly that.
        "service_tier",
    }
)

MODEL_CALL_DETAIL_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "model_name",
        "status",
        "segment_range",
        "first_segment_sequence_num",
        "last_segment_sequence_num",
        "timestamp",
        "retry_attempts",
        "retry_count",
        "error_message",
        "prompt",
        "response",
        "service_tier",
    }
)


def _seed_fixture(db_path: Path) -> None:
    """Build a minimal SQLite DB with the columns the Rust renders read.

    Schemas mirror production but only include columns the renders touch.
    Both jobs-list and stats-render are exercised, so we need:
      - feed, post, processing_job (jobs list + stats post lookup)
      - model_call (stats + service_tier summary; one row with `flex`)
      - transcript_segment / audio_segment / identification (stats only)
    """
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE feed (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            ad_detection_strategy TEXT NOT NULL,
            chapter_filter_strings TEXT
        );
        CREATE TABLE post (
            id INTEGER PRIMARY KEY,
            feed_id INTEGER NOT NULL,
            guid TEXT NOT NULL,
            title TEXT NOT NULL,
            download_url TEXT NOT NULL,
            unprocessed_audio_path TEXT,
            processed_audio_path TEXT,
            release_date TEXT,
            duration REAL,
            whitelisted INTEGER NOT NULL,
            download_count INTEGER,
            chapter_data TEXT,
            bleep_windows TEXT,
            refined_ad_boundaries TEXT
        );
        CREATE TABLE processing_job (
            id TEXT PRIMARY KEY,
            post_guid TEXT NOT NULL,
            status TEXT NOT NULL,
            current_step INTEGER,
            step_name TEXT,
            total_steps INTEGER,
            progress_percentage REAL,
            started_at TEXT,
            completed_at TEXT,
            error_message TEXT,
            created_at TEXT,
            stage_history TEXT,
            ad_windows_count INTEGER,
            had_classification_parse_error INTEGER NOT NULL DEFAULT 0,
            auto_retry_attempted INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE model_call (
            id INTEGER PRIMARY KEY,
            post_id INTEGER NOT NULL,
            first_segment_sequence_num INTEGER NOT NULL,
            last_segment_sequence_num INTEGER NOT NULL,
            model_name TEXT NOT NULL,
            prompt TEXT NOT NULL,
            response TEXT,
            timestamp TEXT,
            status TEXT NOT NULL,
            error_message TEXT,
            retry_attempts INTEGER,
            service_tier TEXT
        );
        CREATE TABLE transcript_segment (
            id INTEGER PRIMARY KEY,
            post_id INTEGER NOT NULL,
            sequence_num INTEGER NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            text TEXT NOT NULL,
            speaker_label TEXT
        );
        CREATE TABLE audio_segment (
            id INTEGER PRIMARY KEY,
            post_id INTEGER NOT NULL,
            model_call_id INTEGER,
            label TEXT NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL
        );
        CREATE TABLE identification (
            id INTEGER PRIMARY KEY,
            transcript_segment_id INTEGER NOT NULL,
            model_call_id INTEGER NOT NULL,
            confidence REAL,
            label TEXT NOT NULL
        );

        INSERT INTO feed VALUES (1, 'Parity Feed', 'llm', NULL);
        INSERT INTO post VALUES (
            1, 1, 'parity-guid', 'Parity Episode',
            'https://example.com/audio.mp3',
            '/tmp/in.mp3', '/tmp/out.mp3',
            '2026-05-26 12:00:00.000000', 90.0, 1, 2, NULL, NULL, NULL
        );
        INSERT INTO processing_job VALUES (
            'job-parity', 'parity-guid', 'running',
            2, 'Identifying ads', 4, 50.0,
            '2026-05-26 12:00:30', NULL, NULL,
            '2026-05-26 12:00:00', NULL, NULL, 0, 0
        );

        -- Two ModelCall rows so the bulk tier summary picks up
        -- mixed=true. Latest (by timestamp) is 'flex' so jobs list shows
        -- the chip; the second row has no tier so it tests the NULL path.
        INSERT INTO model_call VALUES
            (1, 1, 0, 2363, 'gemini/gemini-3-flash-preview',
                'classify prompt', 'classify response',
                '2026-05-26 12:01:00', 'success', NULL, 1, 'flex'),
            (2, 1, -100, -100, 'gemini/gemini-3-flash-preview',
                'chapters prompt', 'chapters response',
                '2026-05-26 12:00:30', 'success', NULL, 1, NULL);

        INSERT INTO transcript_segment VALUES
            (1, 1, 0, 0.0, 10.0, 'hello', 'A'),
            (2, 1, 1, 10.0, 20.0, 'sponsored content', 'A');
        INSERT INTO audio_segment VALUES (1, 1, 1, 'speech', 0.0, 20.0);
        INSERT INTO identification VALUES (1, 2, 1, 0.95, 'ad');
        """
    )
    conn.commit()
    conn.close()


def _run_rust(rust_bin: Path, args: list[str]) -> dict:
    result = subprocess.run(
        [str(rust_bin), *args],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"podly_tools failed: stderr={result.stderr!r}"
    )
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def test_rust_jobs_list_includes_all_python_serializer_fields(
    tmp_path: Path, rust_bin: Path
) -> None:
    db_path = tmp_path / "parity.sqlite"
    _seed_fixture(db_path)

    payload = _run_rust(
        rust_bin, ["jobs", "active", "--db", str(db_path), "--limit", "10"]
    )
    jobs = payload.get("jobs")
    assert isinstance(jobs, list) and jobs, "expected at least one job in the fixture"

    for entry in jobs:
        missing = JOB_LIST_FIELDS - entry.keys()
        assert not missing, (
            f"Rust render_jobs is missing fields {missing} that the Python "
            f"list_active_jobs serializer emits. If either side added a field, "
            f"add it to the other path AND to JOB_LIST_FIELDS in this test."
        )


def test_rust_stats_model_calls_include_all_python_serializer_fields(
    tmp_path: Path, rust_bin: Path
) -> None:
    db_path = tmp_path / "parity.sqlite"
    log_path = tmp_path / "app.log"
    log_path.write_text("")
    _seed_fixture(db_path)

    payload = _run_rust(
        rust_bin,
        [
            "stats",
            "render",
            "--db",
            str(db_path),
            "--post-guid",
            "parity-guid",
            "--min-confidence",
            "0.8",
            "--min-ad-segment-separation-seconds",
            "60",
            "--enable-boundary-refinement",
            "true",
            "--stats-debug",
            "false",
            "--log-path",
            str(log_path),
            "--in-root",
            str(tmp_path / "in"),
            "--srv-root",
            str(tmp_path / "srv"),
        ],
    )
    # Rust nests the model_calls list inside `stats`; mirror that.
    model_calls = payload.get("stats", {}).get("model_calls")
    assert isinstance(model_calls, list) and model_calls, (
        "expected at least one model_call entry in the fixture"
    )

    for entry in model_calls:
        missing = MODEL_CALL_DETAIL_FIELDS - entry.keys()
        assert not missing, (
            f"Rust render_stats is missing fields {missing} on model_calls "
            f"entries that the Python /post/<guid>/debug serializer emits. "
            f"If either side added a field, add it to the other path AND to "
            f"MODEL_CALL_DETAIL_FIELDS in this test."
        )


def test_rust_stats_uses_sentinel_segment_range_labels(
    tmp_path: Path, rust_bin: Path
) -> None:
    """Sentinel chapter-LLM ranges (-100/-200/-201) must be rendered as
    friendly labels, not as the raw `-100--100` string. Locks the contract
    between chapter_fallback.py (which writes sentinels) and the Rust/Python
    serializers (which translate them).
    """
    db_path = tmp_path / "parity.sqlite"
    log_path = tmp_path / "app.log"
    log_path.write_text("")
    _seed_fixture(db_path)

    payload = _run_rust(
        rust_bin,
        [
            "stats",
            "render",
            "--db",
            str(db_path),
            "--post-guid",
            "parity-guid",
            "--min-confidence",
            "0.8",
            "--min-ad-segment-separation-seconds",
            "60",
            "--enable-boundary-refinement",
            "true",
            "--stats-debug",
            "false",
            "--log-path",
            str(log_path),
            "--in-root",
            str(tmp_path / "in"),
            "--srv-root",
            str(tmp_path / "srv"),
        ],
    )
    ranges = {entry["segment_range"] for entry in payload["stats"]["model_calls"]}
    # Real range from the classification row + sentinel-mapped chapter row.
    assert "0-2363" in ranges
    assert "chapter titles (LLM)" in ranges
    assert "-100--100" not in ranges, (
        "Rust render_stats leaked a raw sentinel range. format_segment_range_label "
        "should translate (-100,-100) to 'chapter titles (LLM)'."
    )
