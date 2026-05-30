"""Write chapter metadata to processed MP3 files with adjusted timestamps."""

import logging
from pathlib import Path
from typing import cast

from mutagen.id3 import CHAP, CTOC, ID3, TIT2, TLEN
from mutagen.mp3 import MP3

from podcast_processor.chapter_reader import Chapter
from shared.rust_sidecar import rust_audio_enabled, try_write_chapters

logger = logging.getLogger("global_logger")


def recalculate_chapter_times(
    chapters: list[Chapter],
    removed_segments: list[tuple[float, float]],
) -> list[Chapter]:
    """
    Adjust chapter timestamps after ad segment removal.

    For each chapter, subtract the cumulative duration of all
    removed segments that came before it.

    Args:
        chapters: List of chapters to adjust
        removed_segments: List of (start_sec, end_sec) tuples that were removed

    Returns:
        New list of Chapter objects with adjusted timestamps
    """
    if not chapters:
        return []

    if not removed_segments:
        return chapters

    # Normalize removed segments to sorted, non-overlapping millisecond windows so
    # offset math always reflects unique removed audio time before each marker.
    sorted_segments_ms = _normalize_removed_segments_ms(removed_segments)

    adjusted_chapters: list[Chapter] = []

    for chapter in chapters:
        chapter_start_ms = chapter.start_time_ms
        chapter_end_ms = chapter.end_time_ms
        start_offset_ms = _removed_offset_ms_at_time(
            chapter_start_ms, sorted_segments_ms
        )
        end_offset_ms = _removed_offset_ms_at_time(chapter_end_ms, sorted_segments_ms)

        end_offset_ms = max(end_offset_ms, start_offset_ms)

        # Apply offsets independently so cuts inside a chapter shrink its duration.
        new_start_ms = max(0, chapter_start_ms - start_offset_ms)
        new_end_ms = max(new_start_ms, chapter_end_ms - end_offset_ms)

        adjusted_chapters.append(
            Chapter(
                element_id=chapter.element_id,
                title=chapter.title,
                start_time_ms=new_start_ms,
                end_time_ms=new_end_ms,
            )
        )

        logger.debug(
            "Adjusted chapter '%s': %d ms -> %d ms (offset: %d ms)",
            chapter.title,
            chapter_start_ms,
            new_start_ms,
            start_offset_ms,
        )

    return adjusted_chapters


def _normalize_removed_segments_ms(
    removed_segments: list[tuple[float, float]],
) -> list[tuple[int, int]]:
    """Convert to sorted, merged millisecond windows."""
    windows_ms: list[tuple[int, int]] = []
    for start_sec, end_sec in removed_segments:
        start_ms = round(start_sec * 1000)
        end_ms = round(end_sec * 1000)
        if end_ms <= start_ms:
            continue
        windows_ms.append((start_ms, end_ms))

    if not windows_ms:
        return []

    windows_ms.sort(key=lambda window: window[0])
    merged: list[tuple[int, int]] = [windows_ms[0]]

    for start_ms, end_ms in windows_ms[1:]:
        last_start_ms, last_end_ms = merged[-1]
        if start_ms <= last_end_ms:
            merged[-1] = (last_start_ms, max(last_end_ms, end_ms))
            continue
        merged.append((start_ms, end_ms))

    return merged


def fill_chapter_gaps(
    chapters: list[Chapter],
    audio_duration_ms: int,
) -> list[Chapter]:
    """Extend chapters so they cover [0, audio_duration_ms] with no gaps.

    Some podcast players silently drop chapter markup when the markers do not
    span the entire file. Stretching the first/last chapter outward (rather
    than inserting filler chapters) keeps the title set unchanged.
    """
    if not chapters:
        return chapters

    filled = list(chapters)
    first = filled[0]
    if first.start_time_ms > 0:
        filled[0] = Chapter(
            element_id=first.element_id,
            title=first.title,
            start_time_ms=0,
            end_time_ms=max(first.end_time_ms, 0),
        )

    if audio_duration_ms > 0:
        last = filled[-1]
        if last.end_time_ms < audio_duration_ms:
            filled[-1] = Chapter(
                element_id=last.element_id,
                title=last.title,
                start_time_ms=last.start_time_ms,
                end_time_ms=audio_duration_ms,
            )

    return filled


def _removed_offset_ms_at_time(
    time_ms: int,
    sorted_segments_ms: list[tuple[int, int]],
) -> int:
    """Return cumulative removed audio before a given original timestamp."""
    offset_ms = 0
    for seg_start_ms, seg_end_ms in sorted_segments_ms:
        if seg_end_ms <= time_ms:
            offset_ms += max(0, seg_end_ms - seg_start_ms)
            continue
        if seg_start_ms < time_ms:
            offset_ms += max(0, time_ms - seg_start_ms)
        break
    return offset_ms


def write_chapters(
    audio_path: str,
    chapters: list[Chapter],
) -> None:
    """
    Write chapter metadata to an MP3 file.

    Overwrites any existing chapter data in the file.

    Args:
        audio_path: Path to the MP3 file
        chapters: List of Chapter objects to write
    """
    if not chapters:
        logger.info("No chapters to write to %s", audio_path)
        return

    # Sort chapters by start time to ensure correct order
    sorted_chapters = sorted(chapters, key=lambda c: c.start_time_ms)

    try:
        audio = MP3(audio_path)

        # Clamp chapter end_times to the real audio duration. Some readers
        # (notably Pocket Casts) silently drop chapters whose end_time exceeds
        # the file length, which can happen after ad-removal recalculation if
        # the cut math and ffmpeg's reported duration disagree by even a few ms.
        audio_duration_ms = (
            int(audio.info.length * 1000) if audio.info and audio.info.length else 0
        )
        if audio_duration_ms > 0:
            clamped: list[Chapter] = []
            for chapter in sorted_chapters:
                if chapter.start_time_ms >= audio_duration_ms:
                    logger.warning(
                        "Dropping chapter '%s' starting past audio end (%d >= %d)",
                        chapter.title,
                        chapter.start_time_ms,
                        audio_duration_ms,
                    )
                    continue
                end_ms = min(chapter.end_time_ms, audio_duration_ms)
                clamped.append(
                    Chapter(
                        element_id=chapter.element_id,
                        title=chapter.title,
                        start_time_ms=chapter.start_time_ms,
                        end_time_ms=end_ms,
                    )
                )
            sorted_chapters = clamped

        # Players (e.g. Apple Podcasts, Overcast) ignore chapter markup unless the
        # chapters cover the entire file. Extend the first chapter back to 0 and
        # the last chapter forward to the audio end so there are no gaps.
        sorted_chapters = fill_chapter_gaps(sorted_chapters, audio_duration_ms)

        # Create ID3 tags if they don't exist
        if audio.tags is None:
            audio.add_tags()
        tags = cast(ID3, audio.tags)

        # Remove existing chapter frames
        keys_to_remove = [
            key for key in tags.keys() if key.startswith(("CHAP", "CTOC"))
        ]
        for key in keys_to_remove:
            del tags[key]

        # Add new chapter frames. Encoding 1 (UTF-16) inside TIT2 matches what
        # widely-compatible podcast feeds (e.g. Nextlander) ship and is what
        # Pocket Casts parses most reliably.
        chapter_ids = []
        for i, chapter in enumerate(sorted_chapters):
            element_id = f"chp{i}"
            chapter_ids.append(element_id)

            tit2 = TIT2(encoding=1, text=[chapter.title])

            chap = CHAP(
                element_id=element_id,
                start_time=chapter.start_time_ms,
                end_time=chapter.end_time_ms,
                start_offset=0xFFFFFFFF,
                end_offset=0xFFFFFFFF,
                sub_frames=[tit2],
            )
            tags.add(chap)

        if chapter_ids:
            ctoc = CTOC(
                element_id="toc",
                flags=3,
                child_element_ids=chapter_ids,
                sub_frames=[],
            )
            tags.add(ctoc)

        # TLEN keeps readers from discarding chapters whose end_time exceeds
        # the file duration when no explicit length is otherwise advertised.
        total_duration_ms = audio_duration_ms or max(
            (chapter.end_time_ms for chapter in sorted_chapters), default=0
        )
        if total_duration_ms > 0:
            tags.delall("TLEN")
            tags.add(TLEN(encoding=0, text=[str(total_duration_ms)]))

        # ID3v2.3 (not v2.4) is the de-facto podcast chapters standard;
        # Pocket Casts and other readers parse it most reliably.
        audio.save(v2_version=3)

        logger.info("Wrote %d chapters to %s", len(chapters), audio_path)

    except Exception as e:
        logger.error("Failed to write chapters to %s: %s", audio_path, e)
        raise


def write_adjusted_chapters(
    audio_path: str,
    chapters_to_keep: list[Chapter],
    removed_segments: list[tuple[float, float]],
) -> None:
    """
    Write chapters to an MP3 file with timestamps adjusted for removed segments.

    Convenience function that combines recalculation and writing.

    Args:
        audio_path: Path to the MP3 file
        chapters_to_keep: List of chapters that were not removed as ads
        removed_segments: List of (start_sec, end_sec) tuples that were removed
    """
    adjusted_chapters = recalculate_chapter_times(chapters_to_keep, removed_segments)
    if rust_audio_enabled():
        chapter_payload: list[dict[str, object]] = [
            {
                "title": chapter.title,
                "start_time_ms": chapter.start_time_ms,
                "end_time_ms": chapter.end_time_ms,
            }
            for chapter in adjusted_chapters
        ]
        if try_write_chapters(
            audio_path=Path(audio_path),
            chapters=chapter_payload,
            removed_windows=removed_segments,
        ):
            return
    write_chapters(audio_path, adjusted_chapters)
