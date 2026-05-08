from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from shared import rust_sidecar
from shared.rust_sidecar import RustSidecarError


def test_rust_feature_flags_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PODLY_RUST_AUDIO_ENABLED", raising=False)
    monkeypatch.delenv("PODLY_RUST_FEED_XML_ENABLED", raising=False)
    monkeypatch.delenv("PODLY_RUST_TRANSCRIPT_ENABLED", raising=False)

    assert rust_sidecar.rust_audio_enabled() is False
    assert rust_sidecar.rust_feed_xml_enabled() is False
    assert rust_sidecar.rust_transcript_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_env_flag_enabled_accepts_truthy_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("PODLY_RUST_AUDIO_ENABLED", value)

    assert rust_sidecar.rust_audio_enabled() is True


def test_run_podly_tools_uses_configured_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setenv("PODLY_RUST_TOOLS_BIN", "/tmp/podly_tools")
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert rust_sidecar.run_podly_tools(["audio", "probe", "--input", "x.mp3"]) == {
        "ok": True
    }
    assert calls == [["/tmp/podly_tools", "audio", "probe", "--input", "x.mp3"]]


def test_run_podly_tools_rejects_failed_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RustSidecarError, match="boom"):
        rust_sidecar.run_podly_tools(["audio", "probe", "--input", "x.mp3"])


def test_try_probe_audio_duration_falls_back_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PODLY_RUST_AUDIO_ENABLED", raising=False)

    assert rust_sidecar.try_probe_audio_duration_ms(Path("x.mp3")) is None


def test_try_probe_audio_duration_returns_valid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PODLY_RUST_AUDIO_ENABLED", "true")
    monkeypatch.setattr(
        rust_sidecar, "run_podly_tools", lambda args: {"duration_ms": 1234}
    )

    assert rust_sidecar.try_probe_audio_duration_ms(Path("x.mp3")) == 1234


def test_try_probe_audio_duration_falls_back_on_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PODLY_RUST_AUDIO_ENABLED", "true")
    monkeypatch.setattr(
        rust_sidecar, "run_podly_tools", lambda args: {"duration_ms": "1234"}
    )

    assert rust_sidecar.try_probe_audio_duration_ms(Path("x.mp3")) is None


def test_try_render_feed_xml_uses_rust_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run(args: list[str]) -> dict[str, object]:
        calls.append(args)
        return {"xml": "<rss></rss>"}

    monkeypatch.setenv("PODLY_RUST_FEED_XML_ENABLED", "true")
    monkeypatch.setattr(rust_sidecar, "run_podly_tools", fake_run)

    result = rust_sidecar.try_render_feed_xml(
        db_path=Path("/tmp/db.sqlite"),
        feed_id=12,
        base_url="https://podly.example",
        include_unprocessed=False,
        feed_token="token",
        feed_secret="secret",
    )

    assert result == b"<rss></rss>"
    assert calls == [
        [
            "feed",
            "render",
            "--db",
            "/tmp/db.sqlite",
            "--feed-id",
            "12",
            "--base-url",
            "https://podly.example",
            "--include-unprocessed",
            "false",
            "--feed-token",
            "token",
            "--feed-secret",
            "secret",
        ]
    ]
