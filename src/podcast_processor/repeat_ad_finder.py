"""Deterministic repeat-ad candidate finder.

Dynamic ad insertion stitches the *same* ad copy into an episode multiple
times, verbatim. The LLM classifier occasionally flags only some of those
insertions (a recall miss on one of several identical repeats inside a large
prompt), leaving an undetected — and therefore un-removed — copy in the output.

This module finds the *other* occurrences of an already-detected ad by
near-exact text matching, so a downstream LLM ``confirm`` pass can validate
each candidate before we write ad identifications for it. Finding is
deterministic and exhaustive on purpose: matching identical copy in code never
suffers the LLM recall miss that created the gap.

This is the Python source of truth. A Rust mirror (``transcript
repeat-ad-candidates``) implements the same token-LCS matcher and is used when
the sidecar is enabled, falling back here on any error — so the two MUST stay
behaviourally identical (same normalization, same similarity metric, same
greedy windowing).
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

# Allow ~15% token drift between an ad and its repeat to tolerate transcription
# misses while still rejecting unrelated text that merely shares a stock phrase.
DEFAULT_SIMILARITY_THRESHOLD = 0.85

# The first segment of a candidate must look like the ad's first segment before
# we bother accumulating a full window from it. Looser than the full-window
# threshold because a single segment is short and noisier.
ANCHOR_SIMILARITY_THRESHOLD = 0.70

# Ignore trivially short "ads": too few tokens to match distinctively, so they
# would generate false positives on common filler phrases.
MIN_TARGET_TOKENS = 6

# When accumulating a candidate window we allow this many extra segments beyond
# the target's segment count to absorb minor re-segmentation drift.
MAX_WINDOW_SEGMENT_SLACK = 2

# Feature flag (orchestration-level): the whole repeat-ad pass is opt-in.
REPEAT_AD_DETECTION_ENV = "ENABLE_REPEAT_AD_DETECTION"
_TRUTHY = {"1", "true", "yes", "on"}


def repeat_ad_detection_enabled() -> bool:
    return os.environ.get(REPEAT_AD_DETECTION_ENV, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class RepeatAdCandidate:
    """A span elsewhere in the transcript that matches a detected ad."""

    first_seq: int
    last_seq: int
    start_time: float
    end_time: float
    similarity: float


def _normalize_token(token: str) -> str:
    # Lowercase, strip leading/trailing punctuation, keep internal apostrophes.
    # Mirrors WordBoundaryRefiner._normalize_token so phrase semantics match the
    # rest of the pipeline.
    return re.sub(r"(^[^a-z0-9']+)|([^a-z0-9']+$)", "", token.lower())


def tokenize(text: str) -> list[str]:
    raw_tokens = [t for t in re.split(r"\s+", (text or "").strip()) if t]
    return [t for t in (_normalize_token(t) for t in raw_tokens) if t]


def _lcs_length(a: list[str], b: list[str]) -> int:
    """Length of the longest common subsequence of two token lists.

    Plain O(n*m) DP with a rolling row. Implemented identically in the Rust
    sidecar so similarity scores agree across the two paths.
    """
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for token_a in a:
        cur = [0] * (len(b) + 1)
        for j, token_b in enumerate(b):
            if token_a == token_b:
                cur[j + 1] = prev[j] + 1
            else:
                cur[j + 1] = prev[j + 1] if prev[j + 1] >= cur[j] else cur[j]
        prev = cur
    return prev[len(b)]


def similarity(a: list[str], b: list[str]) -> float:
    """Token-LCS ratio in [0, 1]: 2*LCS / (len(a) + len(b))."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    lcs = _lcs_length(a, b)
    return (2.0 * lcs) / (len(a) + len(b))


def _seq(segment: dict[str, Any]) -> int:
    return int(segment.get("sequence_num", -1))


def find_repeat_candidates(
    segments: list[dict[str, Any]],
    *,
    target_first_seq: int,
    target_last_seq: int,
    exclude_ranges: list[tuple[int, int]] | None = None,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[RepeatAdCandidate]:
    """Find non-overlapping repeats of the ad spanning ``[first, last]`` seqs.

    Args:
        segments: transcript segments as dicts with ``sequence_num``,
            ``start_time``, ``end_time``, ``text``. Order does not matter; the
            function sorts by sequence number.
        target_first_seq / target_last_seq: inclusive seq range of the detected
            ad whose repeats we are searching for.
        exclude_ranges: additional inclusive seq ranges to skip (e.g. other
            already-detected ad blocks) so we never re-propose a known ad.
        similarity_threshold: minimum token-LCS ratio for a full window match.
    """
    segs = sorted(segments, key=_seq)
    if not segs:
        return []

    target_segs = [s for s in segs if target_first_seq <= _seq(s) <= target_last_seq]
    if not target_segs:
        return []

    target_tokens = tokenize(" ".join(str(s.get("text", "")) for s in target_segs))
    if len(target_tokens) < MIN_TARGET_TOKENS:
        return []

    target_first_tokens = tokenize(str(target_segs[0].get("text", "")))
    max_window_segments = len(target_segs) + MAX_WINDOW_SEGMENT_SLACK

    excluded: set[int] = set(range(target_first_seq, target_last_seq + 1))
    for range_first, range_last in exclude_ranges or []:
        excluded.update(range(int(range_first), int(range_last) + 1))

    candidates: list[RepeatAdCandidate] = []
    i = 0
    while i < len(segs):
        seg = segs[i]
        anchor_tokens = tokenize(str(seg.get("text", "")))
        if _seq(seg) in excluded or (
            similarity(anchor_tokens, target_first_tokens) < ANCHOR_SIMILARITY_THRESHOLD
        ):
            i += 1
            continue

        window, acc_tokens, j = _accumulate_window(
            segs, i, excluded, len(target_tokens), max_window_segments
        )
        window_similarity = similarity(acc_tokens, target_tokens)
        if window and window_similarity >= similarity_threshold:
            candidates.append(
                RepeatAdCandidate(
                    first_seq=_seq(window[0]),
                    last_seq=_seq(window[-1]),
                    start_time=float(window[0].get("start_time", 0.0)),
                    end_time=float(window[-1].get("end_time", 0.0)),
                    similarity=window_similarity,
                )
            )
            excluded.update(_seq(matched) for matched in window)
            i = j
        else:
            i += 1

    return candidates


def _accumulate_window(
    segs: list[dict[str, Any]],
    start_idx: int,
    excluded: set[int],
    target_token_count: int,
    max_window_segments: int,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Greedily grow a candidate window from ``start_idx``.

    Returns the accumulated segments, their tokens, and the index just past the
    window (the caller's next scan position on a match).
    """
    window: list[dict[str, Any]] = []
    acc_tokens: list[str] = []
    j = start_idx
    while j < len(segs) and (j - start_idx) < max_window_segments:
        seg_j = segs[j]
        if _seq(seg_j) in excluded:
            break
        window.append(seg_j)
        acc_tokens.extend(tokenize(str(seg_j.get("text", ""))))
        j += 1
        if len(acc_tokens) >= target_token_count:
            break
    return window, acc_tokens, j


def find_repeat_candidates_with_fallback(
    segments: list[dict[str, Any]],
    *,
    post_guid: str | None,
    target_first_seq: int,
    target_last_seq: int,
    exclude_ranges: list[tuple[int, int]] | None = None,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    logger: logging.Logger | None = None,
) -> list[RepeatAdCandidate]:
    """Find repeats via the Rust sidecar, falling back to the Python matcher.

    The Rust path reads transcript segments straight from SQLite by
    ``post_guid``; the Python fallback uses the in-memory ``segments``. Both
    implement the identical token-LCS matcher, so results agree.
    """
    log = logger or logging.getLogger("global_logger")
    ranges = list(exclude_ranges or [])

    if post_guid:
        rust_candidates = _try_rust_candidates(
            post_guid=post_guid,
            target_first_seq=target_first_seq,
            target_last_seq=target_last_seq,
            exclude_ranges=ranges,
            similarity_threshold=similarity_threshold,
            logger=log,
        )
        if rust_candidates is not None:
            return rust_candidates

    return find_repeat_candidates(
        segments,
        target_first_seq=target_first_seq,
        target_last_seq=target_last_seq,
        exclude_ranges=ranges,
        similarity_threshold=similarity_threshold,
    )


def _try_rust_candidates(
    *,
    post_guid: str,
    target_first_seq: int,
    target_last_seq: int,
    exclude_ranges: list[tuple[int, int]],
    similarity_threshold: float,
    logger: logging.Logger,
) -> list[RepeatAdCandidate] | None:
    from shared.processing_paths import get_instance_dir
    from shared.rust_sidecar import try_repeat_ad_candidates

    try:
        db_path = get_instance_dir() / "sqlite3.db"
        raw = try_repeat_ad_candidates(
            db_path=db_path,
            post_guid=post_guid,
            target_first_seq=target_first_seq,
            target_last_seq=target_last_seq,
            exclude_ranges=exclude_ranges,
            similarity_threshold=similarity_threshold,
        )
    except Exception:
        logger.exception("Rust repeat-ad-candidates bootstrap failed; using Python")
        return None

    if raw is None:
        return None

    try:
        return [
            RepeatAdCandidate(
                first_seq=int(item["first_seq"]),
                last_seq=int(item["last_seq"]),
                start_time=float(item["start_time"]),
                end_time=float(item["end_time"]),
                similarity=float(item.get("similarity", 0.0)),
            )
            for item in raw
        ]
    except KeyError, TypeError, ValueError:
        logger.exception("Rust repeat-ad-candidates returned bad rows; using Python")
        return None
