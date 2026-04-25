from __future__ import annotations

from collections.abc import Iterable
from typing import Any

PROMPT_AUDIO_LABELS: dict[str, str] = {
    "music": "MUSIC",
    "silence": "SILENCE",
    "noenergy": "NOENERGY",
}

BRIDGEABLE_AUDIO_LABELS = frozenset({"music", "silence", "noenergy"})
EDGE_EXPANSION_AUDIO_LABELS = frozenset({"music", "silence", "noenergy", "speech"})
EDGE_AUDIO_COVERAGE_TOLERANCE_SECONDS = 0.75
EPISODE_EDGE_EXPANSION_WINDOW_SECONDS = 30.0


def normalize_audio_segment_label(label: Any) -> str | None:
    if label is None:
        return None

    normalized = str(label).strip()
    if not normalized:
        return None

    return normalized.replace("_", "").lower()


def prompt_audio_marker_label(label: Any) -> str | None:
    normalized = normalize_audio_segment_label(label)
    if normalized is None:
        return None

    return PROMPT_AUDIO_LABELS.get(normalized)


def extract_audio_windows(
    audio_segments: Iterable[Any],
    *,
    allowed_labels: frozenset[str] | None = None,
) -> list[tuple[float, float]]:
    allowed = allowed_labels or BRIDGEABLE_AUDIO_LABELS
    windows: list[tuple[float, float]] = []

    for segment in audio_segments:
        normalized_label = normalize_audio_segment_label(
            getattr(segment, "label", None)
        )
        if normalized_label not in allowed:
            continue

        start_raw = getattr(segment, "start_time", None)
        end_raw = getattr(segment, "end_time", None)
        if start_raw is None or end_raw is None:
            continue

        try:
            start_time = float(start_raw)
            end_time = float(end_raw)
        except (TypeError, ValueError):
            continue

        if end_time <= start_time:
            continue

        windows.append((start_time, end_time))

    return _merge_time_windows(windows, gap_seconds=0.75)


def extract_edge_audio_windows(
    audio_segments: Iterable[Any],
) -> list[tuple[float, float]]:
    return extract_audio_windows(
        audio_segments,
        allowed_labels=EDGE_EXPANSION_AUDIO_LABELS,
    )


def bridge_ad_windows_with_audio(
    ad_windows: Iterable[tuple[float, float]],
    audio_windows: Iterable[tuple[float, float]],
    *,
    adjacency_tolerance: float = 0.75,
) -> list[tuple[float, float]]:
    merged_ads = _merge_time_windows(list(ad_windows), gap_seconds=0.0)
    if not merged_ads:
        return []

    merged_audio = _merge_time_windows(
        list(audio_windows),
        gap_seconds=adjacency_tolerance,
    )
    if not merged_audio or len(merged_ads) == 1:
        return merged_ads

    bridged_windows = [merged_ads[0]]

    for next_start, next_end in merged_ads[1:]:
        current_start, current_end = bridged_windows[-1]

        if _gap_is_covered_by_audio(
            gap_start=current_end,
            gap_end=next_start,
            audio_windows=merged_audio,
            adjacency_tolerance=adjacency_tolerance,
        ):
            bridged_windows[-1] = (current_start, next_end)
            continue

        bridged_windows.append((next_start, next_end))

    return bridged_windows


def expand_episode_edge_ad_windows_with_audio(
    ad_windows: Iterable[tuple[float, float]],
    edge_audio_windows: Iterable[tuple[float, float]],
    *,
    edge_window_seconds: float = EPISODE_EDGE_EXPANSION_WINDOW_SECONDS,
    coverage_tolerance_seconds: float = EDGE_AUDIO_COVERAGE_TOLERANCE_SECONDS,
) -> list[tuple[float, float]]:
    expanded = sorted(ad_windows)
    if not expanded:
        return []

    merged_audio = _merge_time_windows(
        list(edge_audio_windows),
        gap_seconds=coverage_tolerance_seconds,
    )
    if not merged_audio:
        return expanded

    first_start, first_end = expanded[0]
    if first_start <= edge_window_seconds:
        leading_start = _covered_audio_start(
            target_start=first_start,
            edge_audio_windows=merged_audio,
            edge_window_seconds=edge_window_seconds,
            coverage_tolerance_seconds=coverage_tolerance_seconds,
        )
        if leading_start is not None:
            expanded[0] = (leading_start, first_end)

    return expanded


def _covered_audio_start(
    *,
    target_start: float,
    edge_audio_windows: list[tuple[float, float]],
    edge_window_seconds: float,
    coverage_tolerance_seconds: float,
) -> float | None:
    coverage_start = float(target_start)
    changed = False

    for audio_start, audio_end in sorted(edge_audio_windows, reverse=True):
        if audio_end < coverage_start - coverage_tolerance_seconds:
            break
        if audio_start > coverage_start + coverage_tolerance_seconds:
            continue
        coverage_start = min(coverage_start, audio_start)
        changed = True

    if changed and coverage_start <= edge_window_seconds:
        return max(0.0, coverage_start)
    return None


def _gap_is_covered_by_audio(
    *,
    gap_start: float,
    gap_end: float,
    audio_windows: list[tuple[float, float]],
    adjacency_tolerance: float,
) -> bool:
    if gap_end <= gap_start:
        return True

    coverage = gap_start

    for audio_start, audio_end in audio_windows:
        if audio_end < coverage - adjacency_tolerance:
            continue

        if audio_start > coverage + adjacency_tolerance:
            return False

        coverage = max(coverage, audio_end)
        if coverage >= gap_end - adjacency_tolerance:
            return True

    return False


def _merge_time_windows(
    windows: list[tuple[float, float]],
    *,
    gap_seconds: float,
) -> list[tuple[float, float]]:
    parsed = [(start, end) for start, end in windows if end > start]
    if not parsed:
        return []

    windows_sorted = sorted(parsed, key=lambda item: item[0])
    merged: list[tuple[float, float]] = []
    current_start, current_end = windows_sorted[0]

    for start_time, end_time in windows_sorted[1:]:
        if start_time <= current_end + gap_seconds:
            current_end = max(current_end, end_time)
            continue

        merged.append((current_start, current_end))
        current_start, current_end = start_time, end_time

    merged.append((current_start, current_end))
    return merged
