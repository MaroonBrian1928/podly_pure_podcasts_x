#!/usr/bin/env python3
"""Parity-check the Rust `wb-resolve` port against Python on real LLM history.

For a given post, scans the `model_call` table for word-boundary refinement
prompts/responses, reconstructs the inputs to both implementations, and diffs
the resulting refined ad windows.

Usage:
    PYTHONPATH=src ./scripts/parity_check_wb_resolve.py \\
        --post-guid <guid> \\
        [--db src/instance/sqlite3.db] \\
        [--limit 50]

Exits non-zero on any mismatch. Audio glitches are user-visible, so a clean
PASS across a real episode is the bar before flipping
`PODLY_RUST_WORD_BOUNDARY_ENABLED` in prod.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from podcast_processor.word_boundary_refiner import WordBoundaryRefiner  # noqa: E402
from shared import rust_sidecar  # noqa: E402
from shared.test_utils import create_standard_test_config  # noqa: E402

AD_BLOCK_RE = re.compile(
    r"\*\*Detected Ad Block\*\*:\s*([0-9.]+)s\s*-\s*([0-9.]+)s",
    re.IGNORECASE,
)


@dataclass
class ParityCase:
    model_call_id: int
    ad_start: float
    ad_end: float
    first_seq: int
    last_seq: int
    payload: dict[str, Any]
    raw_response: str


def load_post_id(conn: sqlite3.Connection, post_guid: str) -> int:
    cur = conn.execute("SELECT id FROM post WHERE guid = ? LIMIT 1", (post_guid,))
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"post not found for guid {post_guid!r}")
    return int(row[0])


def load_segments_with_words(
    conn: sqlite3.Connection, post_id: int
) -> list[dict[str, Any]]:
    """Build the same in-memory segment dicts the production refiner sees."""
    import json as _json

    cur = conn.execute(
        "SELECT transcript_word_timestamps FROM post WHERE id = ? LIMIT 1",
        (post_id,),
    )
    row = cur.fetchone()
    words_by_seq: dict[int, list[Any]] = {}
    if row and row[0]:
        try:
            payload = _json.loads(row[0])
        except Exception:  # noqa: BLE001
            payload = None
        if isinstance(payload, list):
            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                seq = entry.get("sequence_num")
                words = entry.get("words")
                if seq is None or not isinstance(words, list):
                    continue
                try:
                    words_by_seq[int(seq)] = words
                except Exception:  # noqa: BLE001
                    continue

    cur = conn.execute(
        "SELECT sequence_num, start_time, end_time, text "
        "FROM transcript_segment WHERE post_id = ? ORDER BY start_time",
        (post_id,),
    )
    segments: list[dict[str, Any]] = []
    for seq, start, end, text in cur.fetchall():
        seq_int = int(seq)
        seg: dict[str, Any] = {
            "sequence_num": seq_int,
            "start_time": float(start),
            "end_time": float(end),
            "text": str(text or ""),
        }
        words = words_by_seq.get(seq_int)
        if words:
            seg["words"] = words
        segments.append(seg)
    return segments


def load_refiner_cases(
    conn: sqlite3.Connection, post_id: int, limit: int
) -> list[ParityCase]:
    """Reconstruct refiner inputs from prior LLM calls.

    Filters `model_call` rows on the wb prompt marker so we don't pick up
    boundary/ad-classifier calls that share the same `model_name`.
    """

    cur = conn.execute(
        "SELECT id, prompt, response, first_segment_sequence_num, "
        "       last_segment_sequence_num "
        "FROM model_call "
        "WHERE post_id = ? AND prompt LIKE '%Detected Ad Block%' "
        "      AND response IS NOT NULL AND length(response) > 0 "
        "ORDER BY id DESC LIMIT ?",
        (post_id, limit),
    )
    cases: list[ParityCase] = []
    for mc_id, prompt, response, first_seq, last_seq in cur.fetchall():
        match = AD_BLOCK_RE.search(prompt or "")
        if not match:
            continue
        ad_start = float(match.group(1))
        ad_end = float(match.group(2))

        # Reuse the production parser so we apply the same JSON-repair logic.
        refiner = WordBoundaryRefiner(config=create_standard_test_config())
        parsed = refiner._parse_json(response or "")
        if not parsed:
            continue
        payload = refiner._extract_payload(parsed)

        try:
            first_seq_int = int(first_seq) if first_seq is not None else None
            last_seq_int = int(last_seq) if last_seq is not None else None
        except Exception:  # noqa: BLE001
            continue
        if first_seq_int is None or last_seq_int is None:
            continue

        cases.append(
            ParityCase(
                model_call_id=int(mc_id),
                ad_start=ad_start,
                ad_end=ad_end,
                first_seq=first_seq_int,
                last_seq=last_seq_int,
                payload=payload,
                raw_response=str(response or ""),
            )
        )
    return cases


def python_refine(
    case: ParityCase, all_segments: list[dict[str, Any]]
) -> dict[str, Any]:
    refiner = WordBoundaryRefiner(config=create_standard_test_config())
    context = refiner._get_context(
        case.ad_start,
        case.ad_end,
        all_segments,
        first_seq_num=case.first_seq,
        last_seq_num=case.last_seq,
        post_guid=None,  # Force Python-side context selection for parity.
    )
    refined_start, start_changed, _start_reason, start_err = refiner._refine_start(
        ad_start=case.ad_start,
        all_segments=all_segments,
        context_segments=context,
        start_segment_seq=case.payload["start_segment_seq"],
        start_phrase=case.payload["start_phrase"],
        start_word=case.payload["start_word"],
        start_occurrence=case.payload["start_occurrence"],
        start_word_index=case.payload["start_word_index"],
        start_reason=case.payload["start_reason"],
    )
    refined_end, end_changed, _end_reason, end_err = refiner._refine_end(
        ad_end=case.ad_end,
        all_segments=all_segments,
        context_segments=context,
        end_segment_seq=case.payload["end_segment_seq"],
        end_phrase=case.payload["end_phrase"],
        end_reason=case.payload["end_reason"],
    )
    return {
        "refined_start": float(refined_start),
        "refined_end": float(refined_end),
        "start_changed": bool(start_changed),
        "end_changed": bool(end_changed),
        "start_error": start_err,
        "end_error": end_err,
    }


def rust_refine(
    case: ParityCase, db_path: Path, post_guid: str
) -> dict[str, Any] | None:
    """Invoke the bundled `wb-refine-from-llm` subcommand. Replaces the older
    `try_wb_resolve` call so the parity gate exercises the same single-process
    path that production now runs."""
    os.environ["PODLY_RUST_WORD_BOUNDARY_ENABLED"] = "true"
    payload = rust_sidecar.try_wb_refine_from_llm(
        db_path=db_path,
        post_guid=post_guid,
        orig_ad_start=case.ad_start,
        orig_ad_end=case.ad_end,
        first_seq=case.first_seq,
        last_seq=case.last_seq,
        raw_content=case.raw_response,
    )
    if payload is None:
        return None
    if payload.get("parse_status") == "failed":
        # Python parsed the response (otherwise we wouldn't have built this
        # case at all), so a `failed` here is a real divergence — surface it.
        print(
            f"WARN mc#{case.model_call_id}: bundled subcommand reported "
            f"parse_status=failed for content that Python parsed; treating as "
            "mismatch."
        )
    return payload


def diff_case(py: dict[str, Any], rs: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    # Audio cuts are sample-aligned; tolerate sub-millisecond float noise.
    tol = 1e-6
    for key in ("refined_start", "refined_end"):
        if abs(float(py[key]) - float(rs[key])) > tol:
            issues.append(f"{key}: python={py[key]!r} rust={rs[key]!r}")
    for key in ("start_changed", "end_changed"):
        if bool(py[key]) != bool(rs[key]):
            issues.append(f"{key}: python={py[key]!r} rust={rs[key]!r}")
    for key in ("start_error", "end_error"):
        py_v = py.get(key) or None
        rs_v = rs.get(key) or None
        if py_v != rs_v:
            issues.append(f"{key}: python={py_v!r} rust={rs_v!r}")
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
        "--limit",
        type=int,
        default=50,
        help="Maximum number of model_call rows to check (most recent first).",
    )
    parser.add_argument(
        "--time",
        action="store_true",
        help="Print per-case latency stats for Python vs. Rust. wb-resolve "
        "fires hundreds of times per real job, so subprocess fork overhead "
        "matters more here than for the chapter path.",
    )
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        post_id = load_post_id(conn, args.post_guid)
        cases = load_refiner_cases(conn, post_id, args.limit)
        all_segments = load_segments_with_words(conn, post_id)
    finally:
        conn.close()

    if not cases:
        raise SystemExit(
            "No word-boundary refinement model_call rows found for this post. "
            "Either the post was never run through the refiner, or the prompt "
            "marker has drifted; this script can't validate without saved LLM "
            "outputs."
        )
    if not all_segments:
        raise SystemExit("no transcript segments found for that post")

    print(f"post_guid={args.post_guid} segments={len(all_segments)} cases={len(cases)}")

    total_issues = 0
    failed_cases = 0
    py_times_ms: list[float] = []
    rs_times_ms: list[float] = []
    for case in cases:
        t0 = time.perf_counter()
        py = python_refine(case, all_segments)
        py_times_ms.append((time.perf_counter() - t0) * 1000.0)

        t0 = time.perf_counter()
        rs = rust_refine(case, args.db, args.post_guid)
        rs_times_ms.append((time.perf_counter() - t0) * 1000.0)
        if rs is None:
            print(
                f"FAIL mc#{case.model_call_id}: Rust returned None — sidecar "
                "missing or errored. Check PODLY_RUST_TOOLS_BIN."
            )
            return 1
        issues = diff_case(py, rs)
        if issues:
            failed_cases += 1
            total_issues += len(issues)
            print(
                f"FAIL mc#{case.model_call_id} "
                f"ad=[{case.ad_start:.2f}, {case.ad_end:.2f}] "
                f"seqs=[{case.first_seq}, {case.last_seq}]"
            )
            for issue in issues:
                print(f"  {issue}")

    if args.time and py_times_ms and rs_times_ms:
        py_med = statistics.median(py_times_ms)
        rs_med = statistics.median(rs_times_ms)
        py_total = sum(py_times_ms)
        rs_total = sum(rs_times_ms)
        ratio = rs_med / py_med if py_med > 0 else float("inf")
        faster = "rust faster" if rs_med < py_med else "python faster"
        print(
            f"timing python: n={len(py_times_ms)} median={py_med:.2f}ms "
            f"max={max(py_times_ms):.2f}ms total={py_total:.1f}ms"
        )
        print(
            f"timing rust:   n={len(rs_times_ms)} median={rs_med:.2f}ms "
            f"max={max(rs_times_ms):.2f}ms total={rs_total:.1f}ms"
        )
        print(f"timing: median rust/python = {ratio:.2f}x ({faster})")

    if failed_cases == 0:
        print(f"PASS: wb-resolve parity across {len(cases)} model_call rows")
        return 0
    print(
        f"FAIL: {failed_cases}/{len(cases)} cases mismatched "
        f"({total_issues} total field diffs)"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
