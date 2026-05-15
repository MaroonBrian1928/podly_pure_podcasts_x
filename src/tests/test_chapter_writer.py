from podcast_processor.chapter_reader import Chapter
from podcast_processor.chapter_writer import (
    _fill_chapter_gaps,
    recalculate_chapter_times,
    write_adjusted_chapters,
)


def test_fill_chapter_gaps_extends_first_chapter_to_zero() -> None:
    chapters = [
        Chapter("c1", "Intro", 5_000, 60_000),
        Chapter("c2", "Body", 60_000, 120_000),
    ]

    filled = _fill_chapter_gaps(chapters, audio_duration_ms=120_000)

    assert filled[0].start_time_ms == 0
    assert filled[0].end_time_ms == 60_000
    assert filled[1].start_time_ms == 60_000
    assert filled[1].end_time_ms == 120_000


def test_fill_chapter_gaps_extends_last_chapter_to_audio_end() -> None:
    chapters = [
        Chapter("c1", "Intro", 0, 60_000),
        Chapter("c2", "Body", 60_000, 100_000),
    ]

    filled = _fill_chapter_gaps(chapters, audio_duration_ms=180_000)

    assert filled[-1].end_time_ms == 180_000


def test_fill_chapter_gaps_no_op_when_already_spans_file() -> None:
    chapters = [
        Chapter("c1", "Intro", 0, 60_000),
        Chapter("c2", "Body", 60_000, 120_000),
    ]

    filled = _fill_chapter_gaps(chapters, audio_duration_ms=120_000)

    assert filled == chapters


def test_fill_chapter_gaps_handles_unknown_audio_duration() -> None:
    chapters = [
        Chapter("c1", "Intro", 5_000, 60_000),
    ]

    filled = _fill_chapter_gaps(chapters, audio_duration_ms=0)

    # First chapter is still pulled back to 0 even without a known duration.
    assert filled[0].start_time_ms == 0
    # Last chapter end is left alone when duration is unknown.
    assert filled[0].end_time_ms == 60_000


def test_recalculate_chapter_times_shrinks_chapter_when_cut_occurs_inside() -> None:
    chapters = [
        Chapter("c1", "Long section", 0, 600_000),
        Chapter("c2", "Later section", 600_000, 900_000),
    ]

    adjusted = recalculate_chapter_times(chapters, removed_segments=[(100.0, 130.0)])

    assert [c.start_time_ms for c in adjusted] == [0, 570_000]
    assert [c.end_time_ms for c in adjusted] == [570_000, 870_000]


def test_recalculate_chapter_times_offsets_each_marker_by_prior_removed_audio() -> None:
    chapters = [
        Chapter("c1", "Intro", 0, 120_000),
        Chapter("c2", "Segment A", 120_000, 240_000),
        Chapter("c3", "Segment B", 240_000, 360_000),
    ]

    adjusted = recalculate_chapter_times(
        chapters,
        removed_segments=[
            (30.0, 40.0),
            (150.0, 170.0),
        ],
    )

    assert [c.start_time_ms for c in adjusted] == [0, 110_000, 210_000]
    assert [c.end_time_ms for c in adjusted] == [110_000, 210_000, 330_000]


def test_recalculate_chapter_times_merges_overlapping_removed_windows() -> None:
    chapters = [
        Chapter("c1", "Part 1", 0, 400_000),
        Chapter("c2", "Part 2", 400_000, 800_000),
    ]

    adjusted = recalculate_chapter_times(
        chapters,
        removed_segments=[
            (100.0, 180.0),
            (150.0, 220.0),
        ],
    )

    # Unique removed duration is 120 seconds, not 150 seconds.
    assert [c.start_time_ms for c in adjusted] == [0, 280_000]
    assert [c.end_time_ms for c in adjusted] == [280_000, 680_000]


def test_write_adjusted_chapters_uses_rust_when_enabled(monkeypatch) -> None:
    calls = []

    def fake_write_chapters(**kwargs) -> bool:
        calls.append(kwargs)
        return True

    monkeypatch.setattr(
        "podcast_processor.chapter_writer.try_write_chapters", fake_write_chapters
    )

    write_adjusted_chapters(
        "/tmp/audio.mp3",
        [Chapter("c1", "Intro", 0, 120_000)],
        [(10.0, 20.0)],
    )

    assert calls[0]["chapters"] == [
        {"title": "Intro", "start_time_ms": 0, "end_time_ms": 110_000}
    ]
