from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def count_model_calls(
    model_calls: Iterable[Any],
) -> tuple[dict[str, int], dict[str, int]]:
    model_call_statuses: dict[str, int] = {}
    model_types: dict[str, int] = {}

    for call in model_calls:
        status = getattr(call, "status", None)
        model_name = getattr(call, "model_name", None)

        if status is not None:
            model_call_statuses[status] = model_call_statuses.get(status, 0) + 1
        if model_name is not None:
            model_types[model_name] = model_types.get(model_name, 0) + 1

    return model_call_statuses, model_types


def group_identifications_by_segment(
    identifications: Iterable[Any],
) -> dict[int, list[Any]]:
    grouped: dict[int, list[Any]] = {}
    for ident in identifications:
        seg_id = getattr(ident, "transcript_segment_id", None)
        if seg_id is None:
            continue
        grouped.setdefault(int(seg_id), []).append(ident)
    return grouped


def count_primary_labels(
    transcript_segments: Iterable[Any],
    identifications_by_segment: dict[int, list[Any]],
) -> tuple[int, int]:
    content_segments = 0
    ad_segments = 0
    for segment in transcript_segments:
        seg_id = getattr(segment, "id", None)
        if seg_id is None:
            continue
        segment_identifications = identifications_by_segment.get(int(seg_id), [])
        has_ad_label = any(
            getattr(ident, "label", None) == "ad" for ident in segment_identifications
        )
        if has_ad_label:
            ad_segments += 1
        else:
            content_segments += 1
    return content_segments, ad_segments


def build_speaker_breakdown(transcript_segments: Iterable[Any]) -> list[dict[str, Any]]:
    speaker_totals: dict[str | None, dict[str, Any]] = {}
    total_speaking_time_seconds = 0.0

    for segment in transcript_segments:
        start_raw = getattr(segment, "start_time", None)
        end_raw = getattr(segment, "end_time", None)
        if start_raw is None or end_raw is None:
            continue

        try:
            start_time = float(start_raw)
            end_time = float(end_raw)
        except (TypeError, ValueError):
            continue

        duration_seconds = end_time - start_time
        if duration_seconds <= 0:
            continue

        speaker_label_raw = getattr(segment, "speaker_label", None)
        speaker_label: str | None
        if isinstance(speaker_label_raw, str):
            speaker_label = speaker_label_raw.strip() or None
        elif speaker_label_raw is None:
            speaker_label = None
        else:
            speaker_label = str(speaker_label_raw)

        speaker_entry = speaker_totals.setdefault(
            speaker_label,
            {
                "speaker_label": speaker_label,
                "speaking_time_seconds": 0.0,
                "segment_count": 0,
            },
        )
        speaker_entry["speaking_time_seconds"] += duration_seconds
        speaker_entry["segment_count"] += 1
        total_speaking_time_seconds += duration_seconds

    speaker_breakdown = sorted(
        speaker_totals.values(),
        key=lambda entry: (
            -float(entry["speaking_time_seconds"]),
            entry["speaker_label"] is None,
            entry["speaker_label"] or "",
        ),
    )

    return [
        {
            "speaker_label": entry["speaker_label"],
            "speaking_time_seconds": round(float(entry["speaking_time_seconds"]), 1),
            "speaking_percentage": round(
                (
                    float(entry["speaking_time_seconds"])
                    / total_speaking_time_seconds
                    * 100
                )
                if total_speaking_time_seconds > 0
                else 0.0,
                1,
            ),
            "segment_count": int(entry["segment_count"]),
        }
        for entry in speaker_breakdown
    ]


def parse_refined_windows(raw_refined: Any) -> list[tuple[float, float]]:
    return parse_time_windows(
        raw_refined,
        start_key="refined_start",
        end_key="refined_end",
    )


def parse_time_windows(
    raw_windows: Any,
    *,
    start_key: str = "start_time",
    end_key: str = "end_time",
) -> list[tuple[float, float]]:
    parsed_windows: list[tuple[float, float]] = []
    if not isinstance(raw_windows, list):
        return parsed_windows

    for item in raw_windows:
        if not isinstance(item, dict):
            continue

        start_raw = item.get(start_key)
        end_raw = item.get(end_key)
        if start_raw is None or end_raw is None:
            continue

        try:
            start_v = float(start_raw)
            end_v = float(end_raw)
        except Exception:  # noqa: BLE001
            continue

        if end_v > start_v:
            parsed_windows.append((start_v, end_v))

    return parsed_windows


def merge_time_windows(
    windows: list[tuple[float, float]], gap_seconds: float = 1.0
) -> list[tuple[float, float]]:
    if not windows:
        return []

    windows_sorted = sorted(windows, key=lambda w: w[0])
    merged: list[tuple[float, float]] = []
    current_start, current_end = windows_sorted[0]

    for start, end in windows_sorted[1:]:
        if start <= current_end + gap_seconds:
            current_end = max(current_end, end)
        else:
            merged.append((current_start, current_end))
            current_start, current_end = start, end

    merged.append((current_start, current_end))
    return merged


def is_mixed_segment(
    *, seg_start: float, seg_end: float, refined_windows: list[tuple[float, float]]
) -> bool:
    for win_start, win_end in refined_windows:
        overlaps = seg_start <= win_end and seg_end >= win_start
        if not overlaps:
            continue

        fully_contained = seg_start >= win_start and seg_end <= win_end
        if not fully_contained:
            return True

    return False
