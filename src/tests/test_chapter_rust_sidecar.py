from podcast_processor.chapter_ad_detector import ChapterAdDetector
from podcast_processor.chapter_reader import Chapter, read_chapters


def test_read_chapters_uses_rust_when_available(monkeypatch) -> None:
    monkeypatch.setattr(
        "podcast_processor.chapter_reader.try_read_chapters",
        lambda path: [
            {
                "element_id": "chp0",
                "title": "Intro",
                "start_time_ms": 0,
                "end_time_ms": 1000,
            }
        ],
    )

    assert read_chapters("/tmp/audio.mp3") == [Chapter("chp0", "Intro", 0, 1000)]


def test_chapter_detector_uses_rust_when_available(monkeypatch) -> None:
    monkeypatch.setattr(
        "podcast_processor.chapter_ad_detector.try_detect_chapter_ads",
        lambda path, filter_strings_csv: {
            "ad_segments": [[1.0, 2.5]],
            "chapters_to_keep": [
                {
                    "element_id": "chp0",
                    "title": "Intro",
                    "start_time_ms": 0,
                    "end_time_ms": 1000,
                }
            ],
            "chapters_to_remove": [
                {
                    "element_id": "chp1",
                    "title": "Sponsor",
                    "start_time_ms": 1000,
                    "end_time_ms": 2500,
                }
            ],
        },
    )

    ad_segments, keep, remove = ChapterAdDetector.from_csv("sponsor").detect(
        "/tmp/audio.mp3"
    )

    assert ad_segments == [(1.0, 2.5)]
    assert keep == [Chapter("chp0", "Intro", 0, 1000)]
    assert remove == [Chapter("chp1", "Sponsor", 1000, 2500)]


def test_read_chapters_rejects_invalid_payload(monkeypatch) -> None:
    """A chapter whose end precedes its start is meaningless and must be
    rejected by the validator so the wrapper falls back to Python."""
    from shared.rust_sidecar import _is_valid_chapter_payload

    bad = {
        "element_id": "chp0",
        "title": "Backwards",
        "start_time_ms": 5000,
        "end_time_ms": 1000,
    }
    assert _is_valid_chapter_payload(bad) is False

    bad_negative = {
        "element_id": "chp0",
        "title": "Negative",
        "start_time_ms": -10,
        "end_time_ms": 1000,
    }
    assert _is_valid_chapter_payload(bad_negative) is False

    good = {
        "element_id": "chp0",
        "title": "Intro",
        "start_time_ms": 0,
        "end_time_ms": 1000,
    }
    assert _is_valid_chapter_payload(good) is True


def test_chapter_list_monotonic_check() -> None:
    """Out-of-order chapter lists from the sidecar must be rejected so the
    reader and detector wrappers fall back rather than propagate a sidecar
    regression silently."""
    from shared.rust_sidecar import _chapters_are_monotonic

    ordered = [
        {"start_time_ms": 0, "end_time_ms": 1000},
        {"start_time_ms": 1000, "end_time_ms": 2000},
    ]
    assert _chapters_are_monotonic(ordered) is True

    out_of_order = [
        {"start_time_ms": 1000, "end_time_ms": 2000},
        {"start_time_ms": 500, "end_time_ms": 1500},
    ]
    assert _chapters_are_monotonic(out_of_order) is False
