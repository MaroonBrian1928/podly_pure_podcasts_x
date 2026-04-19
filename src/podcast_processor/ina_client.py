"""Client for the INA speech segmenter HTTP API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class AudioSegmentResult:
    label: str
    start_time: float
    end_time: float


def _parse_segment_payload(item: Any) -> AudioSegmentResult | None:
    if not isinstance(item, dict):
        return None

    label = item.get("label")
    start = item.get("start")
    end = item.get("end")
    if label is None or start is None or end is None:
        return None

    try:
        start_time = float(start)
        end_time = float(end)
    except (TypeError, ValueError):
        return None

    if end_time <= start_time:
        return None

    return AudioSegmentResult(
        label=str(label),
        start_time=start_time,
        end_time=end_time,
    )


def analyze_audio(
    audio_path: str,
    base_url: str,
    timeout: int = 3600,
) -> tuple[list[AudioSegmentResult], str]:
    """Send audio to INA and return parsed segments plus the raw JSON payload."""
    url = f"{base_url.rstrip('/')}/segment"

    with open(audio_path, "rb") as audio_file:
        response = requests.post(
            url,
            files={"file": audio_file},
            timeout=timeout,
        )

    response.raise_for_status()
    data = response.json()
    raw_response = json.dumps(data, ensure_ascii=True, default=str, indent=2)

    if not isinstance(data, list):
        raise ValueError("INA response must be a list of segments")

    results = [
        parsed
        for parsed in (_parse_segment_payload(item) for item in data)
        if parsed is not None
    ]
    return results, raw_response
