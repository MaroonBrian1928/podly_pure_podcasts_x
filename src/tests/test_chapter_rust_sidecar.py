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
