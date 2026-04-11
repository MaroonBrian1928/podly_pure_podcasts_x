from podcast_processor.profanity_filter import extract_profanity_windows
from podcast_processor.transcribe import Segment, WordTimestamp


def test_extract_profanity_windows_uses_word_timestamps_and_merges_close_hits() -> None:
    windows, saw_word_timestamps = extract_profanity_windows(
        [
            Segment(
                start=0.0,
                end=2.0,
                text="clean words",
                words=[
                    WordTimestamp(word="clean", start=0.0, end=0.2, score=0.9),
                    WordTimestamp(word="fuck", start=0.21, end=0.45, score=0.9),
                    WordTimestamp(word="shit", start=0.47, end=0.7, score=0.9),
                ],
            )
        ]
    )

    assert saw_word_timestamps is True
    assert windows == [(170, 740)]


def test_extract_profanity_windows_reports_missing_word_timestamps() -> None:
    windows, saw_word_timestamps = extract_profanity_windows(
        [Segment(start=0.0, end=1.0, text="plain segment")]
    )

    assert windows == []
    assert saw_word_timestamps is False
