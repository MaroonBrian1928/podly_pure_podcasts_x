#!/usr/bin/env python3
"""Parity-check the Rust chapter `topic-blocks` port against Python.

Loads `transcript_segment` rows for a post from the SQLite DB, runs both
implementations on the same input, and diffs the resulting block list
field-by-field. Exits non-zero on any mismatch so the script is safe to wire
into a manual pre-flight before flipping `PODLY_RUST_CHAPTER_FALLBACK_ENABLED`
in prod.

Usage:
    PYTHONPATH=src ./scripts/parity_check_chapter_topic_blocks.py \\
        --post-guid <guid> \\
        [--db src/instance/sqlite3.db] \\
        [--removed-windows-json /path/to/windows.json]

The `--removed-windows-json` flag accepts the same shape Python uses internally
(a JSON list of `[start_ms, end_ms]` pairs) and exercises the Phase 1.5
filter parity.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

# Make `src/` importable without requiring caller to set PYTHONPATH.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# These imports must come after the sys.path tweak.
from podcast_processor.chapter_fallback import (  # noqa: E402
    TOPIC_CHAPTER_MAX_BLOCK_SECONDS,
    TOPIC_CHAPTER_MAX_CHARS_PER_BLOCK,
    TOPIC_CHAPTER_MIN_BLOCK_SECONDS,
    TOPIC_CHAPTER_TARGET_BLOCK_COUNT,
    _build_topic_blocks,
    _transcript_duration_ms,
)
from shared import rust_sidecar  # noqa: E402


def load_segments(db_path: Path, post_guid: str) -> list[SimpleNamespace]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = conn.execute("SELECT id FROM post WHERE guid = ? LIMIT 1", (post_guid,))
        row = cur.fetchone()
        if row is None:
            raise SystemExit(f"post not found for guid {post_guid!r}")
        post_id = int(row[0])

        cur = conn.execute(
            "SELECT sequence_num, start_time, end_time, text "
            "FROM transcript_segment WHERE post_id = ? ORDER BY start_time",
            (post_id,),
        )
        return [
            SimpleNamespace(
                sequence_num=int(seq),
                start_time=float(start),
                end_time=float(end),
                text=str(text or ""),
            )
            for seq, start, end, text in cur.fetchall()
        ]
    finally:
        conn.close()


def python_filter(
    segments: list[SimpleNamespace],
    removed_windows_ms: list[tuple[int, int]],
) -> list[SimpleNamespace]:
    """Reproduce `_filter_transcript_segments_for_chapters` standalone."""
    if not segments or not removed_windows_ms:
        return segments
    sorted_windows = sorted(removed_windows_ms, key=lambda w: w[0])

    def overlaps(seg_start_ms: int, seg_end_ms: int) -> bool:
        for r_start, r_end in sorted_windows:
            if r_end <= seg_start_ms:
                continue
            if r_start >= seg_end_ms:
                return False
            return True
        return False

    kept: list[SimpleNamespace] = []
    for seg in segments:
        seg_start_ms = int(seg.start_time * 1000)
        seg_end_ms = max(seg_start_ms, int(seg.end_time * 1000))
        if overlaps(seg_start_ms, seg_end_ms):
            continue
        kept.append(seg)
    return kept or segments  # mirror "empty after filter → fall back" rule


def _time_calls(callable_fn, repeat: int):
    """Run `callable_fn` `repeat` times, capture timings in ms, and return
    `(last_result, timings_ms)`."""
    timings_ms: list[float] = []
    last_result = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        last_result = callable_fn()
        timings_ms.append((time.perf_counter() - t0) * 1000.0)
    return last_result, timings_ms


def _print_timing(label: str, timings_ms: list[float]) -> None:
    if not timings_ms:
        return
    sorted_t = sorted(timings_ms)
    median = statistics.median(sorted_t)
    p95_idx = max(0, round(0.95 * (len(sorted_t) - 1)))
    p95 = sorted_t[p95_idx]
    mn = sorted_t[0]
    mx = sorted_t[-1]
    print(
        f"{label}: n={len(timings_ms)} median={median:.2f}ms "
        f"p95={p95:.2f}ms min={mn:.2f}ms max={mx:.2f}ms"
    )


def diff_blocks(python_blocks: list[dict], rust_blocks: list[dict]) -> list[str]:
    issues: list[str] = []
    if len(python_blocks) != len(rust_blocks):
        issues.append(
            f"block count mismatch: python={len(python_blocks)} rust={len(rust_blocks)}"
        )

    keys = ("block_index", "start_ms", "end_ms", "timestamp", "text")
    for idx, (py, rs) in enumerate(zip(python_blocks, rust_blocks, strict=False)):
        for key in keys:
            py_val = py.get(key)
            rs_val = rs.get(key)
            if py_val != rs_val:
                issues.append(
                    f"block #{idx} field {key!r} mismatch: "
                    f"python={py_val!r} rust={rs_val!r}"
                )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post-guid", required=True)
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "src/instance/sqlite3.db",
        help="Path to the Podly SQLite database (read-only).",
    )
    parser.add_argument(
        "--removed-windows-json",
        type=Path,
        default=None,
        help="Optional JSON file containing [[start_ms, end_ms], ...] windows.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Re-run each implementation N times and print latency stats. "
        "Use to compare wall-clock between Python and Rust; subprocess "
        "fork overhead means Rust is not always faster on small inputs.",
    )
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")

    removed_windows_ms: list[tuple[int, int]] = []
    if args.removed_windows_json is not None:
        raw = json.loads(args.removed_windows_json.read_text())
        for entry in raw:
            if isinstance(entry, list) and len(entry) >= 2:
                removed_windows_ms.append((int(entry[0]), int(entry[1])))
            elif isinstance(entry, dict):
                removed_windows_ms.append(
                    (int(entry["start_ms"]), int(entry["end_ms"]))
                )

    segments = load_segments(args.db, args.post_guid)
    if not segments:
        raise SystemExit("no transcript segments found for that post")

    total_duration_ms = _transcript_duration_ms(segments)
    if total_duration_ms is None or total_duration_ms <= 0:
        raise SystemExit("could not compute total_duration_ms from segments")

    filtered_segments = python_filter(segments, removed_windows_ms)

    def call_python() -> list[dict]:
        return _build_topic_blocks(
            filtered_segments,
            total_duration_ms=total_duration_ms,
            target_block_count=TOPIC_CHAPTER_TARGET_BLOCK_COUNT,
            min_block_seconds=TOPIC_CHAPTER_MIN_BLOCK_SECONDS,
            max_chars_per_block=TOPIC_CHAPTER_MAX_CHARS_PER_BLOCK,
        )

    # Force the rust path on for this run regardless of caller env.
    os.environ["PODLY_RUST_CHAPTER_FALLBACK_ENABLED"] = "true"

    def call_rust() -> list[dict] | None:
        return rust_sidecar.try_chapter_topic_blocks(
            db_path=args.db,
            post_guid=args.post_guid,
            total_duration_ms=total_duration_ms,
            target_block_count=TOPIC_CHAPTER_TARGET_BLOCK_COUNT,
            min_block_seconds=TOPIC_CHAPTER_MIN_BLOCK_SECONDS,
            max_block_seconds=TOPIC_CHAPTER_MAX_BLOCK_SECONDS,
            max_chars_per_block=TOPIC_CHAPTER_MAX_CHARS_PER_BLOCK,
            removed_windows_ms=removed_windows_ms or None,
        )

    python_blocks, py_times_ms = _time_calls(call_python, max(1, args.repeat))
    rust_blocks_obj, rs_times_ms = _time_calls(call_rust, max(1, args.repeat))
    rust_blocks = rust_blocks_obj
    if rust_blocks is None:
        raise SystemExit(
            "Rust topic-blocks returned None — sidecar binary missing or failed. "
            "Check PODLY_RUST_TOOLS_BIN and rerun with stderr visible."
        )

    issues = diff_blocks(python_blocks, rust_blocks)
    print(f"post_guid={args.post_guid}")
    print(f"segments={len(segments)} filtered={len(filtered_segments)}")
    print(f"python_blocks={len(python_blocks)} rust_blocks={len(rust_blocks)}")
    if args.repeat > 1:
        _print_timing("python", py_times_ms)
        _print_timing("rust  ", rs_times_ms)
        py_med = statistics.median(py_times_ms)
        rs_med = statistics.median(rs_times_ms)
        ratio = rs_med / py_med if py_med > 0 else float("inf")
        faster = "rust faster" if rs_med < py_med else "python faster"
        print(f"timing: median rust/python = {ratio:.2f}x ({faster})")
    if not issues:
        print("PASS: chapter topic-blocks parity")
        return 0

    print(f"FAIL: {len(issues)} mismatch(es)")
    for issue in issues[:50]:
        print(f"  {issue}")
    if len(issues) > 50:
        print(f"  ... and {len(issues) - 50} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())
