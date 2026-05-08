from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, cast

LOGGER = logging.getLogger(__name__)

DEFAULT_RUST_TOOLS_BIN = "/app/bin/podly_tools"

RUST_TOOLS_BIN_ENV = "PODLY_RUST_TOOLS_BIN"
RUST_AUDIO_ENABLED_ENV = "PODLY_RUST_AUDIO_ENABLED"
RUST_FEED_XML_ENABLED_ENV = "PODLY_RUST_FEED_XML_ENABLED"
RUST_CHAPTERS_ENABLED_ENV = "PODLY_RUST_CHAPTERS_ENABLED"
RUST_FEED_REFRESH_ENABLED_ENV = "PODLY_RUST_FEED_REFRESH_ENABLED"
RUST_JOBS_ENABLED_ENV = "PODLY_RUST_JOBS_ENABLED"
RUST_STATS_ENABLED_ENV = "PODLY_RUST_STATS_ENABLED"
RUST_TRANSCRIPT_ENABLED_ENV = "PODLY_RUST_TRANSCRIPT_ENABLED"


class RustSidecarError(RuntimeError):
    """Raised when the Rust helper exits unsuccessfully or returns bad JSON."""


def env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def rust_tools_bin() -> Path:
    return Path(os.environ.get(RUST_TOOLS_BIN_ENV, DEFAULT_RUST_TOOLS_BIN))


def rust_audio_enabled() -> bool:
    return env_flag_enabled(RUST_AUDIO_ENABLED_ENV)


def rust_feed_xml_enabled() -> bool:
    return env_flag_enabled(RUST_FEED_XML_ENABLED_ENV)


def rust_feed_refresh_enabled() -> bool:
    return env_flag_enabled(RUST_FEED_REFRESH_ENABLED_ENV)


def rust_chapters_enabled() -> bool:
    return env_flag_enabled(RUST_CHAPTERS_ENABLED_ENV)


def rust_jobs_enabled() -> bool:
    return env_flag_enabled(RUST_JOBS_ENABLED_ENV)


def rust_stats_enabled() -> bool:
    return env_flag_enabled(RUST_STATS_ENABLED_ENV)


def rust_transcript_enabled() -> bool:
    return env_flag_enabled(RUST_TRANSCRIPT_ENABLED_ENV)


def run_podly_tools(args: list[str], timeout_sec: int = 300) -> dict[str, Any]:
    command = [str(rust_tools_bin()), *args]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_sec,
        )
    except OSError as exc:
        raise RustSidecarError(f"failed to start podly_tools: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RustSidecarError(f"podly_tools timed out after {timeout_sec}s") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RustSidecarError(
            f"podly_tools exited with {result.returncode}: {stderr or '<no stderr>'}"
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RustSidecarError("podly_tools returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise RustSidecarError("podly_tools returned a non-object JSON payload")

    return payload


def try_probe_audio_duration_ms(input_path: Path) -> int | None:
    if not rust_audio_enabled():
        return None

    try:
        payload = run_podly_tools(["audio", "probe", "--input", str(input_path)])
    except RustSidecarError:
        LOGGER.exception("Rust audio probe failed; falling back to Python behavior")
        return None

    duration_ms = payload.get("duration_ms")
    if not isinstance(duration_ms, int) or duration_ms < 0:
        LOGGER.error("Rust audio probe returned invalid duration_ms: %r", duration_ms)
        return None
    return duration_ms


def try_cut_audio(
    *,
    windows_ms: list[tuple[int, int]],
    input_path: Path,
    output_path: Path,
    mode: str,
    fade_ms: int,
    encoding: str,
) -> bool:
    if not rust_audio_enabled():
        return False

    with _windows_json_file(windows_ms) as windows_path:
        return _try_audio_command(
            [
                "audio",
                "cut",
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--windows-json",
                str(windows_path),
                "--mode",
                mode,
                "--fade-ms",
                str(fade_ms),
                "--encoding",
                encoding,
            ],
            "cut",
        )


def try_bleep_audio(
    *,
    windows_ms: list[tuple[int, int]],
    input_path: Path,
    output_path: Path,
    beep_frequency_hz: int,
    beep_volume: float,
    duck_volume: float,
    encoding: str,
) -> bool:
    if not rust_audio_enabled():
        return False

    with _windows_json_file(windows_ms) as windows_path:
        return _try_audio_command(
            [
                "audio",
                "bleep",
                "--input",
                str(input_path),
                "--output",
                str(output_path),
                "--windows-json",
                str(windows_path),
                "--beep-frequency-hz",
                str(beep_frequency_hz),
                "--beep-volume",
                str(beep_volume),
                "--duck-volume",
                str(duck_volume),
                "--encoding",
                encoding,
            ],
            "bleep",
        )


def try_split_audio(
    *,
    input_path: Path,
    output_dir: Path,
    chunk_size_bytes: int,
) -> list[tuple[Path, int]] | None:
    if not rust_audio_enabled():
        return None

    try:
        payload = run_podly_tools(
            [
                "audio",
                "split",
                "--input",
                str(input_path),
                "--out-dir",
                str(output_dir),
                "--chunk-size-bytes",
                str(chunk_size_bytes),
            ]
        )
    except RustSidecarError:
        LOGGER.exception("Rust audio split failed; falling back to Python behavior")
        return None

    chunks = payload.get("chunks")
    if not isinstance(chunks, list):
        LOGGER.error("Rust audio split returned invalid chunks: %r", chunks)
        return None

    parsed_chunks: list[tuple[Path, int]] = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            LOGGER.error("Rust audio split returned non-object chunk: %r", chunk)
            return None
        path = chunk.get("path")
        offset_ms = chunk.get("offset_ms")
        if not isinstance(path, str) or not isinstance(offset_ms, int):
            LOGGER.error("Rust audio split returned invalid chunk: %r", chunk)
            return None
        parsed_chunks.append((Path(path), offset_ms))

    return parsed_chunks


def normalize_word_timestamps_artifact(input_path: Path, output_path: Path) -> bool:
    try:
        payload = run_podly_tools(
            [
                "transcript",
                "normalize-word-timestamps",
                "--input",
                str(input_path),
                "--output",
                str(output_path),
            ]
        )
    except RustSidecarError:
        LOGGER.exception("Rust transcript normalization failed")
        return False

    if payload.get("ok") is not True:
        LOGGER.error(
            "Rust transcript normalization returned invalid payload: %r", payload
        )
        return False
    return True


def try_render_feed_xml(
    *,
    db_path: Path,
    feed_id: int,
    base_url: str,
    include_unprocessed: bool,
    feed_token: str | None,
    feed_secret: str | None,
) -> bytes | None:
    if not rust_feed_xml_enabled():
        return None

    args = [
        "feed",
        "render",
        "--db",
        str(db_path),
        "--feed-id",
        str(feed_id),
        "--base-url",
        base_url,
        "--include-unprocessed",
        "true" if include_unprocessed else "false",
    ]
    if feed_token:
        args.extend(["--feed-token", feed_token])
    if feed_secret:
        args.extend(["--feed-secret", feed_secret])
    return _try_feed_xml_command(args, "feed render")


def try_render_aggregate_feed_xml(
    *,
    db_path: Path,
    user_id: int,
    base_url: str,
    require_auth: bool,
    limit_per_feed: int,
    feed_token: str | None,
    feed_secret: str | None,
) -> bytes | None:
    if not rust_feed_xml_enabled():
        return None

    args = [
        "feed",
        "render-aggregate",
        "--db",
        str(db_path),
        "--user-id",
        str(user_id),
        "--base-url",
        base_url,
        "--require-auth",
        "true" if require_auth else "false",
        "--limit-per-feed",
        str(limit_per_feed),
    ]
    if feed_token:
        args.extend(["--feed-token", feed_token])
    if feed_secret:
        args.extend(["--feed-secret", feed_secret])
    return _try_feed_xml_command(args, "feed render-aggregate")


def try_render_post_stats(
    *,
    db_path: Path,
    post_guid: str,
    min_confidence: float,
    min_ad_segment_separation_seconds: float,
    enable_boundary_refinement: bool,
    stats_debug: bool,
    log_path: Path,
    in_root: Path,
    srv_root: Path,
) -> dict[str, Any] | None:
    if not rust_stats_enabled():
        return None

    try:
        payload = run_podly_tools(
            [
                "stats",
                "render",
                "--db",
                str(db_path),
                "--post-guid",
                post_guid,
                "--min-confidence",
                str(min_confidence),
                "--min-ad-segment-separation-seconds",
                str(min_ad_segment_separation_seconds),
                "--enable-boundary-refinement",
                "true" if enable_boundary_refinement else "false",
                "--stats-debug",
                "true" if stats_debug else "false",
                "--log-path",
                str(log_path),
                "--in-root",
                str(in_root),
                "--srv-root",
                str(srv_root),
            ]
        )
    except RustSidecarError:
        LOGGER.exception("Rust stats render failed; falling back to Python behavior")
        return None

    stats = payload.get("stats")
    if not isinstance(stats, dict):
        LOGGER.error("Rust stats render returned invalid stats payload: %r", payload)
        return None
    return stats


def try_list_active_jobs(*, db_path: Path, limit: int) -> list[dict[str, Any]] | None:
    return _try_list_jobs(db_path=db_path, active_only=True, limit=limit)


def try_list_all_jobs(*, db_path: Path, limit: int) -> list[dict[str, Any]] | None:
    return _try_list_jobs(db_path=db_path, active_only=False, limit=limit)


def _try_list_jobs(
    *,
    db_path: Path,
    active_only: bool,
    limit: int,
) -> list[dict[str, Any]] | None:
    if not rust_jobs_enabled():
        return None

    try:
        payload = run_podly_tools(
            [
                "jobs",
                "active" if active_only else "all",
                "--db",
                str(db_path),
                "--limit",
                str(limit),
            ]
        )
    except RustSidecarError:
        LOGGER.exception("Rust jobs list failed; falling back to Python behavior")
        return None

    jobs = payload.get("jobs")
    if not isinstance(jobs, list) or not all(isinstance(job, dict) for job in jobs):
        LOGGER.error("Rust jobs list returned invalid payload: %r", payload)
        return None
    return cast(list[dict[str, Any]], jobs)


def try_write_chapters(
    *,
    audio_path: Path,
    chapters: list[dict[str, object]],
    removed_windows: list[tuple[float, float]],
) -> bool:
    if not rust_audio_enabled():
        return False

    with _json_file(chapters) as chapters_path:
        with _json_file(removed_windows) as removed_windows_path:
            return _try_audio_command(
                [
                    "chapters",
                    "write",
                    "--audio",
                    str(audio_path),
                    "--chapters-json",
                    str(chapters_path),
                    "--removed-windows-json",
                    str(removed_windows_path),
                ],
                "chapters write",
            )


def try_read_chapters(audio_path: Path) -> list[dict[str, Any]] | None:
    if not rust_chapters_enabled():
        return None

    try:
        payload = run_podly_tools(["chapters", "read", "--audio", str(audio_path)])
    except RustSidecarError:
        LOGGER.exception("Rust chapters read failed; falling back to Python behavior")
        return None

    chapters = payload.get("chapters")
    if not isinstance(chapters, list):
        LOGGER.error("Rust chapters read returned invalid payload: %r", payload)
        return None

    parsed: list[dict[str, Any]] = []
    for chapter in chapters:
        if not _is_valid_chapter_payload(chapter):
            LOGGER.error("Rust chapters read returned invalid chapter: %r", chapter)
            return None
        parsed.append(chapter)
    return parsed


def try_detect_chapter_ads(
    audio_path: Path,
    filter_strings_csv: str,
) -> dict[str, Any] | None:
    if not rust_chapters_enabled():
        return None

    try:
        payload = run_podly_tools(
            [
                "chapters",
                "detect",
                "--audio",
                str(audio_path),
                "--filter-strings-csv",
                filter_strings_csv,
            ]
        )
    except RustSidecarError:
        LOGGER.exception("Rust chapters detect failed; falling back to Python behavior")
        return None

    if not _is_valid_chapter_detection_payload(payload):
        LOGGER.error("Rust chapters detect returned invalid payload: %r", payload)
        return None
    return payload


def _is_valid_chapter_detection_payload(payload: dict[str, Any]) -> bool:
    ad_segments = payload.get("ad_segments")
    if not isinstance(ad_segments, list):
        return False
    for segment in ad_segments:
        if (
            not isinstance(segment, list)
            or len(segment) != 2
            or not all(isinstance(value, int | float) for value in segment)
        ):
            return False

    for key in ("chapters_to_keep", "chapters_to_remove"):
        chapters = payload.get(key)
        if not isinstance(chapters, list):
            return False
        if not all(_is_valid_chapter_payload(chapter) for chapter in chapters):
            return False
    return True


def _is_valid_chapter_payload(chapter: object) -> bool:
    if not isinstance(chapter, dict):
        return False
    chapter_dict = cast(dict[str, Any], chapter)
    return (
        isinstance(chapter_dict.get("element_id"), str)
        and isinstance(chapter_dict.get("title"), str)
        and isinstance(chapter_dict.get("start_time_ms"), int)
        and isinstance(chapter_dict.get("end_time_ms"), int)
    )


def _try_audio_command(args: list[str], label: str) -> bool:
    try:
        payload = run_podly_tools(args)
    except RustSidecarError:
        LOGGER.exception("Rust audio %s failed; falling back to Python behavior", label)
        return False

    if payload.get("ok") is not True:
        LOGGER.error(
            "Rust audio %s returned invalid success payload: %r", label, payload
        )
        return False
    return True


def _try_feed_xml_command(args: list[str], label: str) -> bytes | None:
    try:
        payload = run_podly_tools(args)
    except RustSidecarError:
        LOGGER.exception("Rust %s failed; falling back to Python behavior", label)
        return None

    xml = payload.get("xml")
    if not isinstance(xml, str):
        LOGGER.error("Rust %s returned invalid xml payload: %r", label, payload)
        return None
    return xml.encode("utf-8")


class _windows_json_file:
    def __init__(self, windows_ms: list[tuple[int, int]]) -> None:
        self._windows_ms = windows_ms
        self._temp_file: Any = None

    def __enter__(self) -> Path:
        self._temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            delete=False,
        )
        json.dump(self._windows_ms, self._temp_file)
        self._temp_file.close()
        return Path(self._temp_file.name)

    def __exit__(self, *_args: object) -> None:
        if self._temp_file is not None:
            Path(self._temp_file.name).unlink(missing_ok=True)


class _json_file:
    def __init__(self, payload: object) -> None:
        self._payload = payload
        self._temp_file: Any = None

    def __enter__(self) -> Path:
        self._temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            delete=False,
        )
        json.dump(self._payload, self._temp_file)
        self._temp_file.close()
        return Path(self._temp_file.name)

    def __exit__(self, *_args: object) -> None:
        if self._temp_file is not None:
            Path(self._temp_file.name).unlink(missing_ok=True)
