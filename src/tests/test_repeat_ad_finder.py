"""Tests for the deterministic repeat-ad candidate finder."""

from __future__ import annotations

from typing import Any

from podcast_processor.repeat_ad_finder import (
    DEFAULT_SIMILARITY_THRESHOLD,
    find_repeat_candidates,
    repeat_ad_detection_enabled,
    similarity,
    tokenize,
)

AD_TEXT = [
    "Elevate your gaming performance with Alienware deals.",
    "Buy any Alienware PC and get fifty percent off.",
    "Head over to alienware dot com slash deals today.",
    "Back to the show.",
]


def _seg(seq: int, start: float, text: str) -> dict[str, Any]:
    return {
        "sequence_num": seq,
        "start_time": start,
        "end_time": start + 4.0,
        "text": text,
    }


def _transcript_with_two_ad_copies() -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    # First ad copy at seqs 10-13 (the "detected" one).
    for offset, text in enumerate(AD_TEXT):
        segments.append(_seg(10 + offset, 100.0 + offset * 4, text))
    # Filler content.
    for seq in range(14, 30):
        segments.append(_seg(seq, 200.0 + seq, "Just regular show conversation here."))
    # Second, identical ad copy at seqs 30-33 (the repeat we want to find).
    for offset, text in enumerate(AD_TEXT):
        segments.append(_seg(30 + offset, 500.0 + offset * 4, text))
    return segments


def test_similarity_identical_and_disjoint() -> None:
    assert similarity(tokenize("alpha beta gamma"), tokenize("alpha beta gamma")) == 1.0
    assert similarity(tokenize("alpha beta"), tokenize("totally other words")) == 0.0


def test_finds_verbatim_repeat() -> None:
    segments = _transcript_with_two_ad_copies()
    candidates = find_repeat_candidates(
        segments, target_first_seq=10, target_last_seq=13
    )
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.first_seq == 30
    assert cand.last_seq == 33
    assert cand.similarity >= DEFAULT_SIMILARITY_THRESHOLD


def test_tolerates_small_transcription_drift() -> None:
    segments = _transcript_with_two_ad_copies()
    # Introduce a couple of transcription errors into the repeat copy.
    segments[-4]["text"] = "Elevate your gaming performances with Alienware deal."
    segments[-1]["text"] = "Back to the shows."
    candidates = find_repeat_candidates(
        segments, target_first_seq=10, target_last_seq=13
    )
    assert len(candidates) == 1
    assert candidates[0].first_seq == 30


def test_rejects_unrelated_text() -> None:
    segments = _transcript_with_two_ad_copies()
    # Replace the repeat with unrelated content sharing only "back to the show".
    for seq in range(30, 34):
        segments[seq - 30 + 20]["text"] = "And now back to the show with our guest."
    candidates = find_repeat_candidates(
        segments, target_first_seq=10, target_last_seq=13
    )
    assert candidates == []


def test_excludes_provided_ranges() -> None:
    segments = _transcript_with_two_ad_copies()
    candidates = find_repeat_candidates(
        segments,
        target_first_seq=10,
        target_last_seq=13,
        exclude_ranges=[(30, 33)],
    )
    assert candidates == []


def test_ignores_trivially_short_ads() -> None:
    segments = [
        _seg(1, 0.0, "buy now"),
        _seg(2, 5.0, "unrelated"),
        _seg(3, 10.0, "buy now"),
    ]
    candidates = find_repeat_candidates(segments, target_first_seq=1, target_last_seq=1)
    assert candidates == []


def test_feature_flag_env(monkeypatch: Any) -> None:
    monkeypatch.delenv("ENABLE_REPEAT_AD_DETECTION", raising=False)
    assert repeat_ad_detection_enabled() is False
    monkeypatch.setenv("ENABLE_REPEAT_AD_DETECTION", "true")
    assert repeat_ad_detection_enabled() is True
    monkeypatch.setenv("ENABLE_REPEAT_AD_DETECTION", "0")
    assert repeat_ad_detection_enabled() is False
