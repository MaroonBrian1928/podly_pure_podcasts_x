from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from shared import rust_sidecar
from shared.rust_sidecar import RustSidecarError


def test_rust_feature_flags_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PODLY_RUST_AUDIO_ENABLED", raising=False)
    monkeypatch.delenv("PODLY_RUST_CHAPTERS_ENABLED", raising=False)
    monkeypatch.delenv("PODLY_RUST_FEED_REFRESH_ENABLED", raising=False)
    monkeypatch.delenv("PODLY_RUST_FEED_XML_ENABLED", raising=False)
    monkeypatch.delenv("PODLY_RUST_JOBS_ENABLED", raising=False)
    monkeypatch.delenv("PODLY_RUST_STATS_ENABLED", raising=False)
    monkeypatch.delenv("PODLY_RUST_TRANSCRIPT_ENABLED", raising=False)

    assert rust_sidecar.rust_audio_enabled() is False
    assert rust_sidecar.rust_chapters_enabled() is False
    assert rust_sidecar.rust_feed_refresh_enabled() is False
    assert rust_sidecar.rust_feed_xml_enabled() is False
    assert rust_sidecar.rust_jobs_enabled() is False
    assert rust_sidecar.rust_stats_enabled() is False
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
            "--feed-token",
            "token",
            "--feed-secret",
            "secret",
        ]
    ]


def test_try_render_feed_xml_passes_include_unprocessed_as_bare_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> dict[str, object]:
        calls.append(args)
        return {"xml": "<rss></rss>"}

    monkeypatch.setenv("PODLY_RUST_FEED_XML_ENABLED", "true")
    monkeypatch.setattr(rust_sidecar, "run_podly_tools", fake_run)

    rust_sidecar.try_render_feed_xml(
        db_path=Path("/tmp/db.sqlite"),
        feed_id=12,
        base_url="https://podly.example",
        include_unprocessed=True,
        feed_token=None,
        feed_secret=None,
    )

    assert "--include-unprocessed" in calls[0]
    idx = calls[0].index("--include-unprocessed")
    assert calls[0][idx + 1 : idx + 2] != ["true"]
    assert calls[0][idx + 1 : idx + 2] != ["false"]


def test_try_render_aggregate_feed_xml_passes_require_auth_as_bare_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> dict[str, object]:
        calls.append(args)
        return {"xml": "<rss></rss>"}

    monkeypatch.setenv("PODLY_RUST_FEED_XML_ENABLED", "true")
    monkeypatch.setattr(rust_sidecar, "run_podly_tools", fake_run)

    result = rust_sidecar.try_render_aggregate_feed_xml(
        db_path=Path("/tmp/db.sqlite"),
        user_id=7,
        base_url="https://podly.example",
        require_auth=True,
        limit_per_feed=25,
        feed_token=None,
        feed_secret=None,
    )

    assert result == b"<rss></rss>"
    assert calls == [
        [
            "feed",
            "render-aggregate",
            "--db",
            "/tmp/db.sqlite",
            "--user-id",
            "7",
            "--base-url",
            "https://podly.example",
            "--limit-per-feed",
            "25",
            "--require-auth",
        ]
    ]


def test_try_render_aggregate_feed_xml_omits_require_auth_when_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> dict[str, object]:
        calls.append(args)
        return {"xml": "<rss></rss>"}

    monkeypatch.setenv("PODLY_RUST_FEED_XML_ENABLED", "true")
    monkeypatch.setattr(rust_sidecar, "run_podly_tools", fake_run)

    rust_sidecar.try_render_aggregate_feed_xml(
        db_path=Path("/tmp/db.sqlite"),
        user_id=7,
        base_url="https://podly.example",
        require_auth=False,
        limit_per_feed=25,
        feed_token=None,
        feed_secret=None,
    )

    assert "--require-auth" not in calls[0]


def test_try_render_post_stats_returns_none_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PODLY_RUST_STATS_ENABLED", raising=False)

    assert (
        rust_sidecar.try_render_post_stats(
            db_path=Path("/tmp/db.sqlite"),
            post_guid="post-guid",
            min_confidence=0.8,
            min_ad_segment_separation_seconds=30.0,
            enable_boundary_refinement=True,
            stats_debug=False,
            log_path=Path("/tmp/app.log"),
            in_root=Path("/tmp/in"),
            srv_root=Path("/tmp/srv"),
        )
        is None
    )


def test_try_render_post_stats_returns_valid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run(args: list[str]) -> dict[str, object]:
        calls.append(args)
        return {"stats": {"post": {"guid": "post-guid"}}}

    monkeypatch.setenv("PODLY_RUST_STATS_ENABLED", "true")
    monkeypatch.setattr(rust_sidecar, "run_podly_tools", fake_run)

    result = rust_sidecar.try_render_post_stats(
        db_path=Path("/tmp/db.sqlite"),
        post_guid="post-guid/with/slash",
        min_confidence=0.8,
        min_ad_segment_separation_seconds=30.0,
        enable_boundary_refinement=True,
        stats_debug=False,
        log_path=Path("/tmp/app.log"),
        in_root=Path("/tmp/in"),
        srv_root=Path("/tmp/srv"),
    )

    assert result == {"post": {"guid": "post-guid"}}
    assert calls == [
        [
            "stats",
            "render",
            "--db",
            "/tmp/db.sqlite",
            "--post-guid",
            "post-guid/with/slash",
            "--min-confidence",
            "0.8",
            "--min-ad-segment-separation-seconds",
            "30.0",
            "--enable-boundary-refinement",
            "true",
            "--stats-debug",
            "false",
            "--log-path",
            "/tmp/app.log",
            "--in-root",
            "/tmp/in",
            "--srv-root",
            "/tmp/srv",
        ]
    ]


def test_try_render_post_stats_falls_back_on_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PODLY_RUST_STATS_ENABLED", "true")
    monkeypatch.setattr(rust_sidecar, "run_podly_tools", lambda args: {"stats": []})

    assert (
        rust_sidecar.try_render_post_stats(
            db_path=Path("/tmp/db.sqlite"),
            post_guid="post-guid",
            min_confidence=0.8,
            min_ad_segment_separation_seconds=30.0,
            enable_boundary_refinement=True,
            stats_debug=False,
            log_path=Path("/tmp/app.log"),
            in_root=Path("/tmp/in"),
            srv_root=Path("/tmp/srv"),
        )
        is None
    )


def test_try_render_post_stats_falls_back_on_process_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(args: list[str]) -> dict[str, object]:
        raise RustSidecarError("boom")

    monkeypatch.setenv("PODLY_RUST_STATS_ENABLED", "true")
    monkeypatch.setattr(rust_sidecar, "run_podly_tools", fake_run)

    assert (
        rust_sidecar.try_render_post_stats(
            db_path=Path("/tmp/db.sqlite"),
            post_guid="post-guid",
            min_confidence=0.8,
            min_ad_segment_separation_seconds=30.0,
            enable_boundary_refinement=True,
            stats_debug=False,
            log_path=Path("/tmp/app.log"),
            in_root=Path("/tmp/in"),
            srv_root=Path("/tmp/srv"),
        )
        is None
    )


def test_try_list_active_jobs_returns_valid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_run(args: list[str]) -> dict[str, object]:
        calls.append(args)
        return {"jobs": [{"job_id": "job-1"}]}

    monkeypatch.setenv("PODLY_RUST_JOBS_ENABLED", "true")
    monkeypatch.setattr(rust_sidecar, "run_podly_tools", fake_run)

    assert rust_sidecar.try_list_active_jobs(
        db_path=Path("/tmp/db.sqlite"),
        limit=12,
    ) == [{"job_id": "job-1"}]
    assert calls == [
        [
            "jobs",
            "active",
            "--db",
            "/tmp/db.sqlite",
            "--limit",
            "12",
        ]
    ]


def test_try_list_all_jobs_falls_back_on_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PODLY_RUST_JOBS_ENABLED", "true")
    monkeypatch.setattr(rust_sidecar, "run_podly_tools", lambda args: {"jobs": {}})

    assert (
        rust_sidecar.try_list_all_jobs(
            db_path=Path("/tmp/db.sqlite"),
            limit=12,
        )
        is None
    )


def test_try_plan_feed_refresh_returns_valid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> dict[str, object]:
        calls.append(args)
        feed_xml_path = Path(args[args.index("--feed-xml") + 1])
        assert feed_xml_path.read_text() == "<rss />"
        return {
            "updates": {"image_url": "https://example.com/feed.png"},
            "new_posts": [{"guid": "new-guid"}],
            "existing_post_updates": [{"post_id": 1, "title": "Updated"}],
        }

    monkeypatch.setenv("PODLY_RUST_FEED_REFRESH_ENABLED", "true")
    monkeypatch.setattr(rust_sidecar, "run_podly_tools", fake_run)

    assert rust_sidecar.try_plan_feed_refresh(
        db_path=Path("/tmp/db.sqlite"),
        feed_id=12,
        feed_xml="<rss />",
        auto_whitelist_new_posts=True,
    ) == {
        "updates": {"image_url": "https://example.com/feed.png"},
        "new_posts": [{"guid": "new-guid"}],
        "existing_post_updates": [{"post_id": 1, "title": "Updated"}],
    }
    assert calls
    assert calls[0][:6] == [
        "feed",
        "refresh-plan",
        "--db",
        "/tmp/db.sqlite",
        "--feed-id",
        "12",
    ]
    assert calls[0][-2:] == ["--auto-whitelist-new-posts", "true"]


def test_try_plan_feed_refresh_falls_back_on_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PODLY_RUST_FEED_REFRESH_ENABLED", "true")
    monkeypatch.setattr(rust_sidecar, "run_podly_tools", lambda args: {"updates": []})

    assert (
        rust_sidecar.try_plan_feed_refresh(
            db_path=Path("/tmp/db.sqlite"),
            feed_id=12,
            feed_xml=b"<rss />",
            auto_whitelist_new_posts=False,
        )
        is None
    )


def test_try_read_chapters_returns_valid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PODLY_RUST_CHAPTERS_ENABLED", "true")
    monkeypatch.setattr(
        rust_sidecar,
        "run_podly_tools",
        lambda args: {
            "chapters": [
                {
                    "element_id": "chp0",
                    "title": "Intro",
                    "start_time_ms": 0,
                    "end_time_ms": 1000,
                }
            ]
        },
    )

    assert rust_sidecar.try_read_chapters(Path("/tmp/audio.mp3")) == [
        {
            "element_id": "chp0",
            "title": "Intro",
            "start_time_ms": 0,
            "end_time_ms": 1000,
        }
    ]


def test_try_read_chapters_falls_back_on_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PODLY_RUST_CHAPTERS_ENABLED", "true")
    monkeypatch.setattr(
        rust_sidecar,
        "run_podly_tools",
        lambda args: {"chapters": [{"element_id": "chp0"}]},
    )

    assert rust_sidecar.try_read_chapters(Path("/tmp/audio.mp3")) is None


def test_try_detect_chapter_ads_returns_valid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "ad_segments": [[1.0, 2.0]],
        "chapters_to_keep": [
            {
                "element_id": "chp0",
                "title": "Intro",
                "start_time_ms": 0,
                "end_time_ms": 1000,
            }
        ],
        "chapters_to_remove": [
            {
                "element_id": "chp1",
                "title": "Sponsor",
                "start_time_ms": 1000,
                "end_time_ms": 2000,
            }
        ],
    }
    monkeypatch.setenv("PODLY_RUST_CHAPTERS_ENABLED", "true")
    monkeypatch.setattr(rust_sidecar, "run_podly_tools", lambda args: payload)

    assert (
        rust_sidecar.try_detect_chapter_ads(Path("/tmp/audio.mp3"), "sponsor")
        == payload
    )


def test_try_detect_chapter_ads_falls_back_on_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PODLY_RUST_CHAPTERS_ENABLED", "true")
    monkeypatch.setattr(
        rust_sidecar,
        "run_podly_tools",
        lambda args: {"ad_segments": ["not-a-window"]},
    )

    assert (
        rust_sidecar.try_detect_chapter_ads(Path("/tmp/audio.mp3"), "sponsor") is None
    )
