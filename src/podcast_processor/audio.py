import logging
import math
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import ffmpeg

from shared.rust_sidecar import (
    try_bleep_audio,
    try_cut_audio,
    try_probe_audio_duration_ms,
    try_split_audio,
)

logger = logging.getLogger("global_logger")


def get_audio_duration_ms(file_path: str) -> int | None:
    rust_duration_ms = try_probe_audio_duration_ms(Path(file_path))
    if rust_duration_ms is not None:
        return rust_duration_ms

    try:
        logger.debug("[FFMPEG_PROBE] Probing audio file: %s", file_path)
        probe = ffmpeg.probe(file_path)
        format_info = probe["format"]
        duration_seconds = float(format_info["duration"])
        duration_milliseconds = duration_seconds * 1000
        logger.debug("[FFMPEG_PROBE] Duration: %.2f seconds", duration_seconds)
        return int(duration_milliseconds)
    except ffmpeg.Error as e:
        logger.error(
            "[FFMPEG_PROBE] Error probing file %s: %s",
            file_path,
            e.stderr.decode() if e.stderr else str(e),
        )
        return None


def _get_encoding_args(
    use_vbr: bool = False, vbr_quality: int = 2, cbr_bitrate: str = "192k"
) -> dict[str, Any]:
    """Return ffmpeg encoding arguments for VBR or CBR."""
    if use_vbr:
        return {"q:a": vbr_quality}
    return {"b:a": cbr_bitrate}


def clip_segments_with_fade(
    ad_segments_ms: list[tuple[int, int]],
    fade_ms: int,
    in_path: str,
    out_path: str,
    use_vbr: bool = False,
    vbr_quality: int = 2,
    cbr_bitrate: str = "192k",
) -> None:
    if try_cut_audio(
        windows_ms=ad_segments_ms,
        input_path=Path(in_path),
        output_path=Path(out_path),
        mode="fade",
        fade_ms=fade_ms,
        encoding="vbr" if use_vbr else "cbr",
    ):
        return

    audio_duration_ms = get_audio_duration_ms(in_path)
    assert audio_duration_ms is not None

    encoding_args = _get_encoding_args(use_vbr, vbr_quality, cbr_bitrate)

    # Try the complex filter approach first, fall back to simple if it fails
    # Catch both ffmpeg.Error (runtime) and broader exceptions (filter graph construction)
    try:
        _clip_segments_complex(
            ad_segments_ms, fade_ms, in_path, out_path, audio_duration_ms, encoding_args
        )
    except ffmpeg.Error as e:
        err_msg = e.stderr.decode() if getattr(e, "stderr", None) else str(e)
        logger.warning(
            "Complex filter failed (ffmpeg error), trying simple approach: %s", err_msg
        )
        _clip_segments_simple(
            ad_segments_ms, in_path, out_path, audio_duration_ms, encoding_args
        )
    except Exception as e:  # noqa: BLE001
        # Catches filter graph construction errors like "multiple outgoing edges"
        logger.warning(
            "Complex filter failed (graph error), trying simple approach: %s", e
        )
        _clip_segments_simple(
            ad_segments_ms, in_path, out_path, audio_duration_ms, encoding_args
        )


def _clip_segments_complex(
    ad_segments_ms: list[tuple[int, int]],
    fade_ms: int,
    in_path: str,
    out_path: str,
    audio_duration_ms: int,
    encoding_args: dict[str, Any],
) -> None:
    """Original complex approach with fades."""

    trimmed_list = []

    last_end = 0
    for start_ms, end_ms in ad_segments_ms:
        trimmed_list.extend(
            [
                ffmpeg.input(in_path).filter(
                    "atrim", start=last_end / 1000.0, end=start_ms / 1000.0
                ),
                ffmpeg.input(in_path)
                .filter(
                    "atrim", start=start_ms / 1000.0, end=(start_ms + fade_ms) / 1000.0
                )
                .filter("afade", t="out", ss=0, d=fade_ms / 1000.0),
                ffmpeg.input(in_path)
                .filter("atrim", start=(end_ms - fade_ms) / 1000.0, end=end_ms / 1000.0)
                .filter("afade", t="in", ss=0, d=fade_ms / 1000.0),
            ]
        )

        last_end = end_ms

    if last_end != audio_duration_ms:
        trimmed_list.append(
            ffmpeg.input(in_path).filter(
                "atrim", start=last_end / 1000.0, end=audio_duration_ms / 1000.0
            )
        )

    logger.info(
        "[FFMPEG_CONCAT] Starting audio concatenation: %s -> %s (%d segments)",
        in_path,
        out_path,
        len(trimmed_list),
    )
    (
        ffmpeg.concat(*trimmed_list, v=0, a=1)
        .output(out_path, acodec="libmp3lame", **encoding_args)
        .overwrite_output()
        .run()
    )
    logger.info("[FFMPEG_CONCAT] Completed audio concatenation: %s", out_path)


def clip_segments_exact(
    ad_segments_ms: list[tuple[int, int]],
    in_path: str,
    out_path: str,
    cbr_bitrate: str = "192k",
) -> None:
    """Remove segments with exact cuts at boundaries, no fades.

    Used by chapter-based ad detection. Always uses CBR encoding because VBR
    causes seeking inaccuracy with chapter markers.
    """
    if try_cut_audio(
        windows_ms=ad_segments_ms,
        input_path=Path(in_path),
        output_path=Path(out_path),
        mode="exact",
        fade_ms=0,
        encoding="cbr",
    ):
        return

    audio_duration_ms = get_audio_duration_ms(in_path)
    assert audio_duration_ms is not None
    # Chapter strategy always uses CBR for accurate chapter marker seeking
    encoding_args = _get_encoding_args(use_vbr=False, cbr_bitrate=cbr_bitrate)
    _clip_segments_simple(
        ad_segments_ms, in_path, out_path, audio_duration_ms, encoding_args
    )


def overlay_beeps_with_ducking(
    censor_windows_ms: list[tuple[int, int]],
    in_path: str,
    out_path: str,
    *,
    beep_frequency_hz: int = 1000,
    beep_volume: float = 0.65,
    duck_volume: float = 0.08,
    use_vbr: bool = False,
    vbr_quality: int = 2,
    cbr_bitrate: str = "192k",
) -> None:
    if try_bleep_audio(
        windows_ms=censor_windows_ms,
        input_path=Path(in_path),
        output_path=Path(out_path),
        beep_frequency_hz=beep_frequency_hz,
        beep_volume=beep_volume,
        duck_volume=duck_volume,
        encoding="vbr" if use_vbr else "cbr",
    ):
        return

    if not censor_windows_ms:
        shutil.copyfile(in_path, out_path)
        return

    encoding_args = _get_encoding_args(use_vbr, vbr_quality, cbr_bitrate)
    merged_windows = _merge_time_windows_ms(censor_windows_ms)
    window_condition = _build_window_condition_expression(merged_windows)
    audio_duration_ms = get_audio_duration_ms(in_path)
    assert audio_duration_ms is not None

    main_audio = ffmpeg.input(in_path).audio
    ducked_audio = main_audio.filter(
        "volume",
        volume=f"if(gt({window_condition},0),{duck_volume},1)",
        eval="frame",
    )
    beep_stream = ffmpeg.input(
        (
            "sine="
            f"frequency={beep_frequency_hz}:"
            f"duration={audio_duration_ms / 1000.0:.3f}:"
            "sample_rate=44100"
        ),
        f="lavfi",
    ).audio.filter(
        "volume",
        volume=f"if(gt({window_condition},0),{beep_volume},0)",
        eval="frame",
    )

    mixed_audio = ffmpeg.filter(
        [ducked_audio, beep_stream],
        "amix",
        inputs=2,
        duration="first",
        dropout_transition=0,
        normalize=0,
    )

    (
        mixed_audio.output(out_path, acodec="libmp3lame", **encoding_args)
        .overwrite_output()
        .run(quiet=True)
    )

    logger.info(
        "[FFMPEG_BLEEP] Applied %d censor windows: %s -> %s",
        len(merged_windows),
        in_path,
        out_path,
    )


def _clip_segments_simple(
    ad_segments_ms: list[tuple[int, int]],
    in_path: str,
    out_path: str,
    audio_duration_ms: int,
    encoding_args: dict[str, Any],
) -> None:
    """Simpler approach without fades - more reliable for many segments."""

    # Build list of segments to keep (inverse of ad segments)
    keep_segments: list[tuple[int, int]] = []
    last_end = 0

    for start_ms, end_ms in ad_segments_ms:
        if start_ms > last_end:
            keep_segments.append((last_end, start_ms))
        last_end = end_ms

    if last_end < audio_duration_ms:
        keep_segments.append((last_end, audio_duration_ms))

    if not keep_segments:
        raise ValueError("No audio segments to keep after ad removal")

    logger.info(
        "[FFMPEG_SIMPLE] Starting simple concat with %d segments", len(keep_segments)
    )

    # Create temp directory for intermediate files
    with tempfile.TemporaryDirectory() as temp_dir:
        segment_files = []

        # Extract each segment to keep
        for i, (start_ms, end_ms) in enumerate(keep_segments):
            segment_path = os.path.join(temp_dir, f"segment_{i}.mp3")
            start_sec = start_ms / 1000.0
            duration_sec = (end_ms - start_ms) / 1000.0

            (
                ffmpeg.input(in_path)
                .output(
                    segment_path,
                    ss=start_sec,
                    t=duration_sec,
                    acodec="libmp3lame",
                    **encoding_args,
                )
                .overwrite_output()
                .run(quiet=True)
            )

            segment_files.append(segment_path)

        # Create concat file list
        concat_list_path = os.path.join(temp_dir, "concat_list.txt")
        with open(concat_list_path, "w", encoding="utf-8") as file_list:
            for seg_file in segment_files:
                file_list.write(f"file '{seg_file}'\n")

        # Concatenate all segments
        (
            ffmpeg.input(concat_list_path, format="concat", safe=0)
            .output(out_path, acodec="libmp3lame", **encoding_args)
            .overwrite_output()
            .run(quiet=True)
        )

    logger.info("[FFMPEG_SIMPLE] Completed simple audio concatenation: %s", out_path)


def _merge_time_windows_ms(
    windows: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    if not windows:
        return []

    merged: list[tuple[int, int]] = []
    for raw_start_ms, raw_end_ms in sorted(windows):
        start_ms = max(0, int(raw_start_ms))
        end_ms = max(start_ms, int(raw_end_ms))

        if not merged:
            merged.append((start_ms, end_ms))
            continue

        prev_start_ms, prev_end_ms = merged[-1]
        if start_ms <= prev_end_ms:
            merged[-1] = (prev_start_ms, max(prev_end_ms, end_ms))
            continue

        merged.append((start_ms, end_ms))

    return merged


def _build_window_condition_expression(windows: list[tuple[int, int]]) -> str:
    if not windows:
        return "0"

    expressions = [
        f"between(t,{start_ms / 1000.0:.3f},{end_ms / 1000.0:.3f})"
        for start_ms, end_ms in windows
        if end_ms > start_ms
    ]
    if not expressions:
        return "0"
    return "+".join(expressions)


def trim_file(in_path: Path, out_path: Path, start_ms: int, end_ms: int) -> None:
    duration_ms = end_ms - start_ms

    if duration_ms <= 0:
        return

    start_sec = max(start_ms, 0) / 1000.0
    duration_sec = duration_ms / 1000.0

    logger.debug(
        "[FFMPEG_TRIM] Trimming %s -> %s (start=%.2fs, duration=%.2fs)",
        in_path,
        out_path,
        start_sec,
        duration_sec,
    )
    (
        ffmpeg.input(str(in_path))
        .output(
            str(out_path),
            ss=start_sec,
            t=duration_sec,
            acodec="copy",
            vn=None,
        )
        .overwrite_output()
        .run()
    )


def split_audio(
    audio_file_path: Path,
    audio_chunk_path: Path,
    chunk_size_bytes: int,
) -> list[tuple[Path, int]]:

    audio_chunk_path.mkdir(parents=True, exist_ok=True)

    rust_chunks = try_split_audio(
        input_path=audio_file_path,
        output_dir=audio_chunk_path,
        chunk_size_bytes=chunk_size_bytes,
    )
    if rust_chunks is not None:
        return rust_chunks

    logger.info(
        "[FFMPEG_SPLIT] Splitting audio file: %s into chunks of %d bytes",
        audio_file_path,
        chunk_size_bytes,
    )
    duration_ms = get_audio_duration_ms(str(audio_file_path))
    assert duration_ms is not None
    if chunk_size_bytes <= 0:
        raise ValueError("chunk_size_bytes must be a positive integer")

    file_size_bytes = audio_file_path.stat().st_size
    if file_size_bytes == 0:
        raise ValueError("Cannot split zero-byte audio file")

    chunk_ratio = chunk_size_bytes / file_size_bytes
    chunk_duration_ms = max(1, math.ceil(duration_ms * chunk_ratio))

    num_chunks = max(1, math.ceil(duration_ms / chunk_duration_ms))
    logger.info(
        "[FFMPEG_SPLIT] Will create %d chunks (duration per chunk: %d ms)",
        num_chunks,
        chunk_duration_ms,
    )

    chunks: list[tuple[Path, int]] = []

    for i in range(num_chunks):
        start_offset_ms = i * chunk_duration_ms
        if start_offset_ms >= duration_ms:
            break

        end_offset_ms = min(duration_ms, (i + 1) * chunk_duration_ms)

        export_path = audio_chunk_path / f"{i}.mp3"
        logger.debug(
            "[FFMPEG_SPLIT] Creating chunk %d/%d: %s", i + 1, num_chunks, export_path
        )
        trim_file(audio_file_path, export_path, start_offset_ms, end_offset_ms)
        chunks.append((export_path, start_offset_ms))

    logger.info("[FFMPEG_SPLIT] Split complete: created %d chunks", len(chunks))
    return chunks
