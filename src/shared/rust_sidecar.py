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
RUST_AD_MERGE_ENABLED_ENV = "PODLY_RUST_AD_MERGE_ENABLED"
RUST_PROFANITY_ENABLED_ENV = "PODLY_RUST_PROFANITY_ENABLED"
RUST_FEED_POSTS_ENABLED_ENV = "PODLY_RUST_FEED_POSTS_ENABLED"
RUST_WORD_BOUNDARY_ENABLED_ENV = "PODLY_RUST_WORD_BOUNDARY_ENABLED"
RUST_CHAPTER_FALLBACK_ENABLED_ENV = "PODLY_RUST_CHAPTER_FALLBACK_ENABLED"


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


def rust_ad_merge_enabled() -> bool:
    return env_flag_enabled(RUST_AD_MERGE_ENABLED_ENV)


def rust_profanity_enabled() -> bool:
    return env_flag_enabled(RUST_PROFANITY_ENABLED_ENV)


def rust_feed_posts_enabled() -> bool:
    return env_flag_enabled(RUST_FEED_POSTS_ENABLED_ENV)


def rust_word_boundary_enabled() -> bool:
    return env_flag_enabled(RUST_WORD_BOUNDARY_ENABLED_ENV)


def rust_chapter_fallback_enabled() -> bool:
    return env_flag_enabled(RUST_CHAPTER_FALLBACK_ENABLED_ENV)


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
    cbr_bitrate_bps: int | None = None,
    vbr_quality: int | None = None,
) -> bool:
    if not rust_audio_enabled():
        return False

    with _windows_json_file(windows_ms) as windows_path:
        args = [
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
        ]
        if cbr_bitrate_bps is not None:
            args.extend(["--cbr-bitrate-bps", str(cbr_bitrate_bps)])
        if vbr_quality is not None:
            args.extend(["--vbr-quality", str(vbr_quality)])
        return _try_audio_command(
            args,
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
    fade_ms: int = 5,
    cbr_bitrate_bps: int | None = None,
    vbr_quality: int | None = None,
) -> bool:
    if not rust_audio_enabled():
        return False

    with _windows_json_file(windows_ms) as windows_path:
        args = [
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
            "--fade-ms",
            str(fade_ms),
            "--encoding",
            encoding,
        ]
        if cbr_bitrate_bps is not None:
            args.extend(["--cbr-bitrate-bps", str(cbr_bitrate_bps)])
        if vbr_quality is not None:
            args.extend(["--vbr-quality", str(vbr_quality)])
        return _try_audio_command(
            args,
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
    ]
    if include_unprocessed:
        args.append("--include-unprocessed")
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
        "--limit-per-feed",
        str(limit_per_feed),
    ]
    if require_auth:
        args.append("--require-auth")
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


def try_get_jobs_manager_status(*, db_path: Path) -> dict[str, Any] | None:
    """Read-only snapshot of the singleton jobs-manager run via the Rust
    sidecar. Returns the full ``{"run": <snapshot or null>}`` envelope so the
    Flask route can pass it through unchanged. Returns ``None`` only when the
    Rust path is disabled or the binary fails — the singleton-missing case
    still returns ``{"run": None}`` so the caller doesn't fall back to
    Python and re-query.
    """
    if not rust_jobs_enabled():
        return None

    try:
        return run_podly_tools(
            [
                "jobs",
                "status",
                "--db",
                str(db_path),
            ]
        )
    except RustSidecarError:
        LOGGER.exception("Rust jobs status failed; falling back to Python behavior")
        return None


def try_plan_feed_refresh(
    *,
    db_path: Path,
    feed_id: int,
    feed_xml: str | bytes,
    auto_whitelist_new_posts: bool,
) -> dict[str, Any] | None:
    if not rust_feed_refresh_enabled():
        return None

    raw_xml = feed_xml.encode("utf-8") if isinstance(feed_xml, str) else feed_xml
    with tempfile.NamedTemporaryFile(suffix=".xml") as feed_file:
        feed_file.write(raw_xml)
        feed_file.flush()
        try:
            payload = run_podly_tools(
                [
                    "feed",
                    "refresh-plan",
                    "--db",
                    str(db_path),
                    "--feed-id",
                    str(feed_id),
                    "--feed-xml",
                    feed_file.name,
                    "--auto-whitelist-new-posts",
                    "true" if auto_whitelist_new_posts else "false",
                ]
            )
        except RustSidecarError:
            LOGGER.exception(
                "Rust feed refresh planning failed; falling back to Python behavior"
            )
            return None

    if not _is_valid_feed_refresh_plan(payload):
        LOGGER.error("Rust feed refresh planning returned invalid payload: %r", payload)
        return None
    return payload


def _is_valid_feed_refresh_plan(payload: dict[str, Any]) -> bool:
    updates = payload.get("updates")
    new_posts = payload.get("new_posts")
    existing_post_updates = payload.get("existing_post_updates")
    return (
        isinstance(updates, dict)
        and isinstance(new_posts, list)
        and all(isinstance(post, dict) for post in new_posts)
        and isinstance(existing_post_updates, list)
        and all(isinstance(post, dict) for post in existing_post_updates)
    )


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
    if not _chapters_are_monotonic(parsed):
        LOGGER.error("Rust chapters read returned out-of-order chapters: %r", parsed)
        return None
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
        if not _chapters_are_monotonic(chapters):
            return False
    return True


def _is_valid_chapter_payload(chapter: object) -> bool:
    if not isinstance(chapter, dict):
        return False
    chapter_dict = cast(dict[str, Any], chapter)
    if not (
        isinstance(chapter_dict.get("element_id"), str)
        and isinstance(chapter_dict.get("title"), str)
        and isinstance(chapter_dict.get("start_time_ms"), int)
        and isinstance(chapter_dict.get("end_time_ms"), int)
    ):
        return False
    # A chapter whose end precedes its start is meaningless and breaks
    # downstream players. We treat the payload as bad rather than silently
    # clamping so a Rust regression surfaces in the fallback log.
    if chapter_dict["end_time_ms"] < chapter_dict["start_time_ms"]:
        return False
    if chapter_dict["start_time_ms"] < 0:
        return False
    return True


def _chapters_are_monotonic(chapters: list[dict[str, Any]]) -> bool:
    """Reject Rust chapter lists that aren't sorted by start_time_ms.

    Both the reader and detector paths assume chapters arrive in playback
    order; out-of-order entries point to a sidecar bug we want to fall back on
    rather than silently propagate.
    """
    last_start: int | None = None
    for chapter in chapters:
        start = chapter["start_time_ms"]
        if last_start is not None and start < last_start:
            return False
        last_start = start
    return True


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


class _text_file:
    """Write a string payload to a temp file and unlink on exit.

    Matches `_json_file` / `_windows_json_file` but for raw text (LLM responses
    handed to the Rust sidecar's parse subcommands). Keeps the temp-file
    lifetime tied to a `with` block so ruff's SIM115 stays happy and OS-level
    cleanup happens even on raised exceptions.
    """

    def __init__(self, payload: str, *, suffix: str = ".txt") -> None:
        self._payload = payload
        self._suffix = suffix
        self._temp_file: Any = None

    def __enter__(self) -> Path:
        self._temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=self._suffix,
            delete=False,
        )
        self._temp_file.write(self._payload or "")
        self._temp_file.close()
        return Path(self._temp_file.name)

    def __exit__(self, *_args: object) -> None:
        if self._temp_file is not None:
            Path(self._temp_file.name).unlink(missing_ok=True)


def try_merge_ad_segments(
    *,
    db_path: Path,
    post_guid: str,
    min_confidence: float,
    max_gap: float,
    enable_boundary_refinement: bool,
) -> list[tuple[float, float]] | None:
    """Run Rust ad merger. Returns list of (start_seconds, end_seconds) tuples, or None.

    None means: flag off, sidecar failed, or returned an unexpected payload.
    Callers should fall back to the Python AdMerger pipeline.
    """
    if not rust_ad_merge_enabled():
        return None

    try:
        payload = run_podly_tools(
            [
                "transcript",
                "ad-merge",
                "--db",
                str(db_path),
                "--post-guid",
                post_guid,
                "--min-confidence",
                str(min_confidence),
                "--max-gap",
                str(max_gap),
                "--enable-boundary-refinement",
                "true" if enable_boundary_refinement else "false",
            ]
        )
    except RustSidecarError:
        LOGGER.exception("Rust ad-merge failed; falling back to Python implementation")
        return None

    raw = payload.get("ad_segments")
    if not isinstance(raw, list):
        LOGGER.error("Rust ad-merge returned invalid payload: %r", payload)
        return None

    result: list[tuple[float, float]] = []
    for item in raw:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(v, int | float) for v in item)
        ):
            LOGGER.error("Rust ad-merge returned bad segment: %r", item)
            return None
        result.append((float(item[0]), float(item[1])))
    return result


def try_wb_context(
    *,
    db_path: Path,
    post_guid: str,
    ad_start: float,
    ad_end: float,
    first_seq: int | None,
    last_seq: int | None,
) -> list[dict[str, Any]] | None:
    """Run the Rust word-boundary context selector.

    Mirrors `WordBoundaryRefiner._get_context` in Python: returns the slice of
    transcript segments the caller should use as LLM prompt context for an ad
    window. None means: flag off, sidecar failed, or returned an unexpected
    payload — the caller falls back to the Python implementation.
    """
    if not rust_word_boundary_enabled():
        return None

    args: list[str] = [
        "transcript",
        "wb-context",
        "--db",
        str(db_path),
        "--post-guid",
        post_guid,
        "--ad-start",
        repr(float(ad_start)),
        "--ad-end",
        repr(float(ad_end)),
    ]
    if first_seq is not None:
        args += ["--first-seq", str(int(first_seq))]
    if last_seq is not None:
        args += ["--last-seq", str(int(last_seq))]

    try:
        payload = run_podly_tools(args)
    except RustSidecarError:
        LOGGER.exception(
            "Rust wb-context failed; falling back to Python implementation"
        )
        return None

    raw = payload.get("context_segments")
    if not isinstance(raw, list):
        LOGGER.error("Rust wb-context returned invalid payload: %r", payload)
        return None

    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            LOGGER.error("Rust wb-context returned non-dict segment: %r", item)
            return None
        result.append(item)
    return result


def try_wb_resolve(  # noqa: PLR0912 — branches mirror the Python `_refine_*` arg surface; splitting just hides the contract.
    *,
    db_path: Path,
    post_guid: str,
    orig_ad_start: float,
    orig_ad_end: float,
    first_seq: int | None,
    last_seq: int | None,
    start_segment_seq: int | None,
    start_phrase: str | None,
    start_word: str | None,
    start_occurrence: str | None,
    start_word_index: int | None,
    end_segment_seq: int | None,
    end_phrase: str | None,
) -> dict[str, Any] | None:
    """Run the Rust word-boundary resolver.

    Mirrors `WordBoundaryRefiner._refine_start` + `_refine_end` in Python:
    given the LLM-extracted phrases / word hints, return the refined ad-start
    and ad-end times along with `start_changed` / `end_changed` flags and any
    `*_phrase_not_found` errors. None means: flag off, sidecar failed, or
    returned an unexpected payload — the caller falls back to Python.
    """
    if not rust_word_boundary_enabled():
        return None

    args: list[str] = [
        "transcript",
        "wb-resolve",
        "--db",
        str(db_path),
        "--post-guid",
        post_guid,
        "--orig-ad-start",
        repr(float(orig_ad_start)),
        "--orig-ad-end",
        repr(float(orig_ad_end)),
    ]
    if first_seq is not None:
        args += ["--first-seq", str(int(first_seq))]
    if last_seq is not None:
        args += ["--last-seq", str(int(last_seq))]
    if start_segment_seq is not None:
        args += ["--start-segment-seq", str(int(start_segment_seq))]
    if start_phrase is not None and str(start_phrase).strip():
        args += ["--start-phrase", str(start_phrase)]
    if start_word is not None and str(start_word).strip():
        args += ["--start-word", str(start_word)]
    if start_occurrence is not None and str(start_occurrence).strip():
        args += ["--start-occurrence", str(start_occurrence)]
    if start_word_index is not None:
        args += ["--start-word-index", str(int(start_word_index))]
    if end_segment_seq is not None:
        args += ["--end-segment-seq", str(int(end_segment_seq))]
    if end_phrase is not None and str(end_phrase).strip():
        args += ["--end-phrase", str(end_phrase)]

    try:
        payload = run_podly_tools(args)
    except RustSidecarError:
        LOGGER.exception(
            "Rust wb-resolve failed; falling back to Python implementation"
        )
        return None

    required_keys = {
        "refined_start",
        "refined_end",
        "start_changed",
        "end_changed",
    }
    if not required_keys.issubset(payload.keys()):
        LOGGER.error("Rust wb-resolve returned invalid payload: %r", payload)
        return None
    if not isinstance(payload["refined_start"], (int, float)) or not isinstance(
        payload["refined_end"], (int, float)
    ):
        LOGGER.error("Rust wb-resolve returned non-numeric times: %r", payload)
        return None
    return payload


def try_wb_refine_from_llm(
    *,
    db_path: Path,
    post_guid: str,
    orig_ad_start: float,
    orig_ad_end: float,
    first_seq: int | None,
    last_seq: int | None,
    raw_content: str,
) -> dict[str, Any] | None:
    """Run the bundled Rust word-boundary refiner.

    Replaces the previous `try_wb_json_parse` + `try_wb_resolve` pair so each
    refinement spawns a single sidecar process instead of two. Mirrors
    `WordBoundaryRefiner._parse_json` + `_extract_payload` + `_refine_start` +
    `_refine_end` end-to-end. Returns the payload (with `parse_status` set to
    `"ok"`, `"salvaged"`, or `"failed"`) or None to signal the caller should
    fall back to the Python chain (flag off, sidecar error, or unexpected
    payload).
    """
    if not rust_word_boundary_enabled():
        return None

    with _text_file(raw_content or "") as raw_content_path:
        args: list[str] = [
            "transcript",
            "wb-refine-from-llm",
            "--db",
            str(db_path),
            "--post-guid",
            post_guid,
            "--orig-ad-start",
            repr(float(orig_ad_start)),
            "--orig-ad-end",
            repr(float(orig_ad_end)),
            "--raw-content-file",
            str(raw_content_path),
        ]
        if first_seq is not None:
            args += ["--first-seq", str(int(first_seq))]
        if last_seq is not None:
            args += ["--last-seq", str(int(last_seq))]

        try:
            payload = run_podly_tools(args)
        except RustSidecarError:
            LOGGER.exception(
                "Rust wb-refine-from-llm failed; falling back to Python implementation"
            )
            return None

    parse_status = payload.get("parse_status")
    if parse_status not in {"ok", "salvaged", "failed"}:
        LOGGER.error(
            "Rust wb-refine-from-llm returned invalid parse_status: %r", payload
        )
        return None
    required_keys = {
        "refined_start",
        "refined_end",
        "start_changed",
        "end_changed",
        "start_reason",
        "end_reason",
    }
    if not required_keys.issubset(payload.keys()):
        LOGGER.error("Rust wb-refine-from-llm returned invalid payload: %r", payload)
        return None
    if not isinstance(payload["refined_start"], (int, float)) or not isinstance(
        payload["refined_end"], (int, float)
    ):
        LOGGER.error("Rust wb-refine-from-llm returned non-numeric times: %r", payload)
        return None
    return payload


def try_chapter_topic_blocks(
    *,
    db_path: Path,
    post_guid: str,
    total_duration_ms: int | None = None,
    target_block_count: int = 60,
    min_block_seconds: int = 60,
    max_block_seconds: int = 120,
    max_chars_per_block: int = 220,
    removed_windows_ms: list[tuple[int, int]] | None = None,
) -> list[dict[str, Any]] | None:
    """Run the Rust chapter topic-block builder.

    Mirrors `_build_topic_blocks` in `src/podcast_processor/chapter_fallback.py`.
    Returns the list of block dicts on success, or None to signal the caller
    should fall back to the Python implementation (flag off, sidecar failed, or
    bad payload).

    When `removed_windows_ms` is supplied, Rust filters segments overlapping
    those windows before block-building (mirrors
    `_filter_transcript_segments_for_chapters`). Parity rule: if the filter
    would empty the segment list, the unfiltered set is used instead.
    """
    if not rust_chapter_fallback_enabled():
        return None

    base_args: list[str] = [
        "chapters",
        "topic-blocks",
        "--db",
        str(db_path),
        "--post-guid",
        post_guid,
        "--target-block-count",
        str(int(target_block_count)),
        "--min-block-seconds",
        str(int(min_block_seconds)),
        "--max-block-seconds",
        str(int(max_block_seconds)),
        "--max-chars-per-block",
        str(int(max_chars_per_block)),
    ]
    if total_duration_ms is not None:
        base_args += ["--total-duration-ms", str(int(total_duration_ms))]

    def _invoke(args: list[str]) -> dict[str, Any] | None:
        try:
            return run_podly_tools(args)
        except RustSidecarError:
            LOGGER.exception(
                "Rust chapter topic-blocks failed; falling back to Python "
                "implementation"
            )
            return None

    if removed_windows_ms:
        with _windows_json_file(list(removed_windows_ms)) as windows_path:
            payload = _invoke([*base_args, "--removed-windows-json", str(windows_path)])
    else:
        payload = _invoke(base_args)

    if payload is None:
        return None

    raw = payload.get("blocks")
    if not isinstance(raw, list):
        LOGGER.error("Rust chapter topic-blocks returned invalid payload: %r", payload)
        return None
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            LOGGER.error("Rust chapter topic-blocks returned non-dict block: %r", item)
            return None
        result.append(item)
    return result


def try_chapter_topic_plan_parse(*, raw_content: str) -> dict[str, Any] | None:
    """Run the Rust topic-plan response parser.

    Mirrors `_parse_topic_chapter_response` (+ salvage helpers) in
    `src/podcast_processor/chapter_fallback.py`. Returns a dict with shape:
        {
          "entries": [(block_index, title), ...],
          "expected_count": int | None,
          "salvaged": bool,
          "count_mismatch": bool,
        }
    or None on flag-off / sidecar error so the caller falls back to Python.
    """
    if not rust_chapter_fallback_enabled():
        return None

    with _text_file(raw_content or "") as raw_content_path:
        try:
            payload = run_podly_tools(
                [
                    "chapters",
                    "topic-plan-parse",
                    "--input",
                    str(raw_content_path),
                ]
            )
        except RustSidecarError:
            LOGGER.exception(
                "Rust chapter topic-plan-parse failed; falling back to Python"
            )
            return None

    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        LOGGER.error(
            "Rust chapter topic-plan-parse returned invalid entries: %r", payload
        )
        return None

    entries: list[tuple[int, str]] = []
    for item in raw_entries:
        if not isinstance(item, list) or len(item) != 2:
            LOGGER.error("Rust topic-plan-parse bad entry: %r", item)
            return None
        try:
            entries.append((int(item[0]), str(item[1])))
        except Exception:  # noqa: BLE001
            LOGGER.error("Rust topic-plan-parse uncoercible entry: %r", item)
            return None

    expected_count = payload.get("expected_count")
    if expected_count is not None and not isinstance(expected_count, int):
        LOGGER.error("Rust topic-plan-parse bad expected_count: %r", expected_count)
        return None

    return {
        "entries": entries,
        "expected_count": expected_count,
        "salvaged": bool(payload.get("salvaged", False)),
        "count_mismatch": bool(payload.get("count_mismatch", False)),
    }


def try_chapter_topic_plan_apply(
    *,
    plan: list[tuple[int, str]],
    blocks: list[dict[str, Any]],
    total_duration_ms: int,
    min_chapter_gap_ms: int,
) -> list[dict[str, Any]] | None:
    """Run the Rust topic-plan applier.

    Mirrors `_chapters_from_topic_plan` and friends in
    `src/podcast_processor/chapter_fallback.py`. Returns a list of
    `{element_id, title, start_time_ms, end_time_ms}` dicts on success or None
    so the caller falls back to Python.
    """
    if not rust_chapter_fallback_enabled():
        return None

    payload = {
        "plan": [[int(idx), str(title)] for idx, title in plan],
        "blocks": [
            {
                "block_index": int(b.get("block_index", -1)),
                "start_ms": int(b.get("start_ms", 0)),
                "text": str(b.get("text", "") or ""),
            }
            for b in blocks
        ],
        "total_duration_ms": int(total_duration_ms),
        "min_chapter_gap_ms": int(min_chapter_gap_ms),
    }

    with _json_file(payload) as payload_path:
        try:
            result = run_podly_tools(
                [
                    "chapters",
                    "topic-plan-apply",
                    "--input",
                    str(payload_path),
                ]
            )
        except RustSidecarError:
            LOGGER.exception(
                "Rust chapter topic-plan-apply failed; falling back to Python"
            )
            return None

    raw_chapters = result.get("chapters")
    if not isinstance(raw_chapters, list):
        LOGGER.error(
            "Rust chapter topic-plan-apply returned invalid chapters: %r", result
        )
        return None

    out: list[dict[str, Any]] = []
    for item in raw_chapters:
        if not isinstance(item, dict):
            LOGGER.error("Rust topic-plan-apply bad chapter: %r", item)
            return None
        out.append(item)
    return out


class FeedPostsNotFound:
    """Sentinel signaling the feed doesn't exist (Flask should return 404)."""


FEED_POSTS_NOT_FOUND = FeedPostsNotFound()


def try_render_feed_posts(
    *,
    db_path: Path,
    feed_id: int,
    page: int,
    page_size: int,
    whitelisted_only: bool,
) -> bytes | FeedPostsNotFound | None:
    """Render the /api/feeds/<id>/posts envelope via the Rust sidecar.

    Returns the raw JSON bytes the sidecar emitted on stdout — these are
    passed straight through to the HTTP response without a Python json.loads
    / flask.jsonify round-trip. Bypassing that round-trip is the whole point
    of this port: parsing a ~290 KB envelope into a Python dict graph just
    to re-serialize it would allocate the same heap the original endpoint
    did, defeating the memory win.

    Returns FEED_POSTS_NOT_FOUND when the feed is missing (mirroring
    Flask's get_or_404), or None when the Rust path is disabled / failed
    so the caller falls back to the Python query.
    """
    if not rust_feed_posts_enabled():
        return None

    command = [
        str(rust_tools_bin()),
        "posts",
        "feed-list",
        "--db",
        str(db_path),
        "--feed-id",
        str(feed_id),
        "--page",
        str(page),
        "--page-size",
        str(page_size),
        "--whitelisted-only",
        "true" if whitelisted_only else "false",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=300,
        )
    except OSError, subprocess.TimeoutExpired:
        LOGGER.exception(
            "Rust feed-posts subprocess failed; falling back to Python implementation"
        )
        return None

    if result.returncode != 0:
        LOGGER.error(
            "Rust feed-posts exited with %s: %s",
            result.returncode,
            result.stderr.decode("utf-8", errors="replace").strip() or "<no stderr>",
        )
        return None

    stripped = result.stdout.strip()

    # Rust's print_json uses compact serde_json::to_string, so the
    # missing-feed sentinel is exactly this byte sequence — match without
    # parsing to keep Python heap allocations to a minimum.
    if stripped == b'{"not_found":true}':
        return FEED_POSTS_NOT_FOUND

    # Cheap sanity check that the payload looks like our envelope.
    # render_feed_posts orders keys with "items" first, so a valid response
    # always starts with this prefix. If it doesn't, fall back rather than
    # forward garbage to the HTTP client.
    if not stripped.startswith(b'{"items":'):
        LOGGER.error(
            "Rust feed-posts returned unexpected payload prefix: %r",
            stripped[:80],
        )
        return None

    return stripped


def try_extract_profanity_windows(
    *,
    words: list[dict[str, Any]],
    profanity_terms: list[str],
    pad_start_ms: int,
    pad_end_ms: int,
    merge_gap_ms: int,
) -> list[tuple[int, int]] | None:
    """Run Rust profanity-windows. Returns list of (start_ms, end_ms) tuples.

    None means: flag off, sidecar failed, or invalid payload. Callers should
    fall back to the Python implementation.

    `words` is a list of dicts: {"word": str, "start": float_seconds, "end": float_seconds}.
    """
    if not rust_profanity_enabled():
        return None

    request_payload = {
        "words": words,
        "profanity_terms": profanity_terms,
        "pad_start_ms": pad_start_ms,
        "pad_end_ms": pad_end_ms,
        "merge_gap_ms": merge_gap_ms,
    }
    try:
        with _json_file(request_payload) as input_path:
            payload = run_podly_tools(
                [
                    "transcript",
                    "profanity-windows",
                    "--input",
                    str(input_path),
                ]
            )
    except RustSidecarError:
        LOGGER.exception(
            "Rust profanity-windows failed; falling back to Python implementation"
        )
        return None

    raw = payload.get("windows_ms")
    if not isinstance(raw, list):
        LOGGER.error("Rust profanity-windows returned invalid payload: %r", payload)
        return None

    result: list[tuple[int, int]] = []
    for item in raw:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(v, int) for v in item)
        ):
            LOGGER.error("Rust profanity-windows returned bad window: %r", item)
            return None
        result.append((int(item[0]), int(item[1])))
    return result
