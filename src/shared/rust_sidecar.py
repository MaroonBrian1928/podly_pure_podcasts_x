from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

DEFAULT_RUST_TOOLS_BIN = "/app/bin/podly_tools"

RUST_TOOLS_BIN_ENV = "PODLY_RUST_TOOLS_BIN"
RUST_AUDIO_ENABLED_ENV = "PODLY_RUST_AUDIO_ENABLED"
RUST_FEED_XML_ENABLED_ENV = "PODLY_RUST_FEED_XML_ENABLED"
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
