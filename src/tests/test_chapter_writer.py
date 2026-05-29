from podcast_processor.chapter_reader import Chapter
from podcast_processor.chapter_writer import (
    fill_chapter_gaps,
    recalculate_chapter_times,
    write_adjusted_chapters,
)


def test_fill_chapter_gaps_extends_first_chapter_to_zero() -> None:
    chapters = [
        Chapter("c1", "Intro", 5_000, 60_000),
        Chapter("c2", "Body", 60_000, 120_000),
    ]

    filled = fill_chapter_gaps(chapters, audio_duration_ms=120_000)

    assert filled[0].start_time_ms == 0
    assert filled[0].end_time_ms == 60_000
    assert filled[1].start_time_ms == 60_000
    assert filled[1].end_time_ms == 120_000


def test_fill_chapter_gaps_extends_last_chapter_to_audio_end() -> None:
    chapters = [
        Chapter("c1", "Intro", 0, 60_000),
        Chapter("c2", "Body", 60_000, 100_000),
    ]

    filled = fill_chapter_gaps(chapters, audio_duration_ms=180_000)

    assert filled[-1].end_time_ms == 180_000


def test_fill_chapter_gaps_no_op_when_already_spans_file() -> None:
    chapters = [
        Chapter("c1", "Intro", 0, 60_000),
        Chapter("c2", "Body", 60_000, 120_000),
    ]

    filled = fill_chapter_gaps(chapters, audio_duration_ms=120_000)

    assert filled == chapters


def test_fill_chapter_gaps_handles_unknown_audio_duration() -> None:
    chapters = [
        Chapter("c1", "Intro", 5_000, 60_000),
    ]

    filled = fill_chapter_gaps(chapters, audio_duration_ms=0)

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
        "podcast_processor.chapter_writer.rust_audio_enabled", lambda: True
    )
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


def test_write_adjusted_chapters_skips_rust_payload_when_flag_off(monkeypatch) -> None:
    """When the Rust audio flag is off we shouldn't waste cycles serializing
    the chapter list into a dict payload that the wrapper would immediately
    discard. Tracks the regression behind the chapter-writer cleanup."""

    def fail_if_called(**_kwargs) -> bool:
        raise AssertionError("try_write_chapters must not run when flag is off")

    written: list[tuple[str, list]] = []

    def fake_write_chapters(path, chapters) -> None:
        written.append((path, chapters))

    monkeypatch.setattr(
        "podcast_processor.chapter_writer.rust_audio_enabled", lambda: False
    )
    monkeypatch.setattr(
        "podcast_processor.chapter_writer.try_write_chapters", fail_if_called
    )
    monkeypatch.setattr(
        "podcast_processor.chapter_writer.write_chapters", fake_write_chapters
    )

    write_adjusted_chapters(
        "/tmp/audio.mp3",
        [Chapter("c1", "Intro", 0, 120_000)],
        [(10.0, 20.0)],
    )

    assert written == [
        ("/tmp/audio.mp3", [Chapter("c1", "Intro", 0, 110_000)]),
    ]


def test_serialize_chapters_for_output_spans_full_audio(monkeypatch) -> None:
    """`chapter_data["chapters_for_output"]` must always span the processed
    audio file. Otherwise the UI shows a first chapter that starts mid-speech
    (e.g. 00:02 instead of 00:00) and players that require gap-free chapters
    silently drop the markup.
    """
    from podcast_processor.podcast_processor import _serialize_chapters_for_output

    monkeypatch.setattr(
        "podcast_processor.podcast_processor.get_audio_duration_ms",
        lambda _path: 600_000,
    )

    chapters = [
        Chapter("c1", "Intro to the case", 1_960, 182_960),
        Chapter("c2", "Later", 182_960, 540_000),
    ]

    result = _serialize_chapters_for_output(chapters, "/tmp/processed.mp3")

    assert result == [
        {"title": "Intro to the case", "start_time": 0.0, "end_time": 183.0},
        {"title": "Later", "start_time": 183.0, "end_time": 600.0},
    ]


def test_chapter_clamps_end_before_start() -> None:
    """Reading a malformed CHAP frame shouldn't propagate an end < start state
    that later breaks mutagen on write-back. We clamp end up to start instead
    of raising so existing files keep loading."""
    c = Chapter("c1", "Backwards", 60_000, 10_000)
    assert c.start_time_ms == 60_000
    assert c.end_time_ms == 60_000
