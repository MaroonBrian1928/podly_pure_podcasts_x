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
