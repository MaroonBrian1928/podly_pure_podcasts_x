#!/usr/bin/env python3
"""Parity-check the Rust `chapters detect` path against the Python fallback.

Runs both implementations against the same MP3 + filter-strings CSV and diffs
the resulting (ad_segments, chapters_to_keep, chapters_to_remove) tuple. Exits
non-zero on any mismatch so the script is safe to wire into a manual
pre-flight before flipping `PODLY_RUST_CHAPTERS_ENABLED` in prod.

Usage:
    PYTHONPATH=src ./scripts/parity_check_chapter_detect.py \\
        --audio /path/to/episode.mp3 \\
        --filter-strings-csv "sponsor,ad,promo" \\
        [--repeat 5]

The script forces `PODLY_RUST_CHAPTERS_ENABLED=true` for the Rust call so it
runs regardless of how the caller's environment is set, mirroring
`parity_check_chapter_topic_blocks.py`.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import statistics
import sys
import time
from pathlib import Path

# Make `src/` importable without requiring caller to set PYTHONPATH.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# These imports must come after the sys.path tweak.
from podcast_processor.chapter_filter import (  # noqa: E402
    filter_chapters_by_strings,
    parse_filter_strings,
)
from podcast_processor.chapter_reader import Chapter, read_chapters  # noqa: E402
from shared import rust_sidecar  # noqa: E402


def python_detect(
    audio_path: Path,
    filter_strings_csv: str,
) -> tuple[list[tuple[float, float]], list[Chapter], list[Chapter]]:
    """Reproduce the Python fallback in `ChapterAdDetector.detect` without
    re-entering the Rust path. We call `read_chapters` directly so we exercise
    whichever read path the caller's env enables; if `PODLY_RUST_CHAPTERS_ENABLED`
    is set, this still goes through Rust for reading — which is fine, since the
    point of *this* script is parity of the `chapters detect` subcommand."""
    filter_strings = parse_filter_strings(filter_strings_csv)
    chapters = read_chapters(str(audio_path))
    if not chapters:
        raise SystemExit(f"no chapters found in {audio_path}")
    keep, remove = filter_chapters_by_strings(
        chapters=chapters,
        filter_strings=filter_strings,
    )
    ad_segments = [(c.start_time_ms / 1000.0, c.end_time_ms / 1000.0) for c in remove]
    return ad_segments, keep, remove


def rust_detect(
    audio_path: Path,
    filter_strings_csv: str,
) -> tuple[list[tuple[float, float]], list[Chapter], list[Chapter]]:
    payload = rust_sidecar.try_detect_chapter_ads(audio_path, filter_strings_csv)
    if payload is None:
        raise SystemExit(
            "Rust chapter detect returned None — sidecar binary missing, "
            "flag off, or returned an invalid payload. Check "
            "PODLY_RUST_TOOLS_BIN and rerun with stderr visible."
        )
    keep = [
        Chapter(
            element_id=c["element_id"],
            title=c["title"],
            start_time_ms=c["start_time_ms"],
            end_time_ms=c["end_time_ms"],
        )
        for c in payload["chapters_to_keep"]
    ]
    remove = [
        Chapter(
            element_id=c["element_id"],
            title=c["title"],
            start_time_ms=c["start_time_ms"],
            end_time_ms=c["end_time_ms"],
        )
        for c in payload["chapters_to_remove"]
    ]
    ad_segments = [(float(s[0]), float(s[1])) for s in payload["ad_segments"]]
    return ad_segments, keep, remove


def _time_calls(callable_fn, repeat: int):
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
    print(
        f"{label}: n={len(timings_ms)} median={median:.2f}ms "
        f"p95={p95:.2f}ms min={sorted_t[0]:.2f}ms max={sorted_t[-1]:.2f}ms"
    )


def _chapter_tuple(c: Chapter) -> tuple[str, str, int, int]:
    # element_id often differs cosmetically (Rust uses `chp{i}`, Python may
    # echo whatever was on disk). Compare on the structural fields only.
    return (c.title, c.start_time_ms, c.end_time_ms)


def diff_results(py, rs) -> list[str]:
    issues: list[str] = []
    py_ads, py_keep, py_remove = py
    rs_ads, rs_keep, rs_remove = rs

    if len(py_ads) != len(rs_ads):
        issues.append(
            f"ad_segment count mismatch: python={len(py_ads)} rust={len(rs_ads)}"
        )
    for idx, (a, b) in enumerate(zip(py_ads, rs_ads, strict=False)):
        if abs(a[0] - b[0]) > 1e-3 or abs(a[1] - b[1]) > 1e-3:
            issues.append(f"ad_segment #{idx} mismatch: python={a} rust={b}")

    for label, py_list, rs_list in (
        ("keep", py_keep, rs_keep),
        ("remove", py_remove, rs_remove),
    ):
        if len(py_list) != len(rs_list):
            issues.append(
                f"{label} count mismatch: python={len(py_list)} rust={len(rs_list)}"
            )
        for idx, (a, b) in enumerate(zip(py_list, rs_list, strict=False)):
            if _chapter_tuple(a) != _chapter_tuple(b):
                issues.append(
                    f"{label} #{idx} mismatch: "
                    f"python={dataclasses.asdict(a)!r} rust={dataclasses.asdict(b)!r}"
                )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument(
        "--filter-strings-csv",
        default="",
        help="Comma-separated chapter-title substrings treated as ads.",
    )
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()

    if not args.audio.exists():
        raise SystemExit(f"audio not found: {args.audio}")

    # Force the Rust path on for this run regardless of caller env.
    os.environ["PODLY_RUST_CHAPTERS_ENABLED"] = "true"

    def call_python():
        # Temporarily disable the Rust path so read_chapters / detector run
        # in pure Python — otherwise we'd be comparing rust-to-rust.
        prev = os.environ.get("PODLY_RUST_CHAPTERS_ENABLED")
        os.environ["PODLY_RUST_CHAPTERS_ENABLED"] = ""
        try:
            return python_detect(args.audio, args.filter_strings_csv)
        finally:
            if prev is None:
                os.environ.pop("PODLY_RUST_CHAPTERS_ENABLED", None)
            else:
                os.environ["PODLY_RUST_CHAPTERS_ENABLED"] = prev

    def call_rust():
        return rust_detect(args.audio, args.filter_strings_csv)

    py_result, py_times = _time_calls(call_python, max(1, args.repeat))
    rs_result, rs_times = _time_calls(call_rust, max(1, args.repeat))

    print(f"audio={args.audio}")
    print(f"filter_strings_csv={args.filter_strings_csv!r}")
    py_ads, py_keep, py_remove = py_result
    rs_ads, rs_keep, rs_remove = rs_result
    print(
        f"python: ad_segments={len(py_ads)} keep={len(py_keep)} remove={len(py_remove)}"
    )
    print(
        f"rust:   ad_segments={len(rs_ads)} keep={len(rs_keep)} remove={len(rs_remove)}"
    )
    if args.repeat > 1:
        _print_timing("python", py_times)
        _print_timing("rust  ", rs_times)
        py_med = statistics.median(py_times)
        rs_med = statistics.median(rs_times)
        ratio = rs_med / py_med if py_med > 0 else float("inf")
        faster = "rust faster" if rs_med < py_med else "python faster"
        print(f"timing: median rust/python = {ratio:.2f}x ({faster})")

    issues = diff_results(py_result, rs_result)
    if not issues:
        print("PASS: chapter detect parity")
        return 0

    print(f"FAIL: {len(issues)} mismatch(es)")
    for issue in issues[:50]:
        print(f"  {issue}")
    if len(issues) > 50:
        print(f"  ... and {len(issues) - 50} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())
