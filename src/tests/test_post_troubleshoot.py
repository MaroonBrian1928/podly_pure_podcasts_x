from types import SimpleNamespace
from unittest import mock
from urllib.parse import quote

from app.extensions import db
from app.failure_explainer import (
    build_troubleshoot_context,
    select_troubleshoot_entries,
)
from app.models import Feed, Post
from app.routes.post_routes import post_bp
from app.runtime_config import config as runtime_config


def _encoded_guid(guid: str) -> str:
    return quote(guid, safe="")


def _make_post(app) -> str:
    with app.app_context():
        feed = Feed(title="Feed", rss_url="https://example.com/feed.xml")
        db.session.add(feed)
        db.session.commit()

        post = Post(
            feed_id=feed.id,
            guid="tag:example.com,2026:/posts/1",
            download_url="https://example.com/audio.mp3",
            title="Failing Episode",
            whitelisted=True,
        )
        db.session.add(post)
        db.session.commit()
        return post.guid


def _fake_completion_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


# A trimmed but structurally faithful copy of a real remote-Whisper connection
# failure: a multi-line traceback (no timestamp prefix) followed by the
# post/job-tagged JOB_STATUS lines. Plus a benign API poll afterwards that also
# mentions the guid -- the context builder must NOT anchor on it.
_GUID = "tag:example.com,2026:/posts/1"
_JOB_ID = "job-abc-123"
_FAKE_LOG = f"""2026-06-04 17:37:00,000 INFO [WHISPER_REMOTE] Starting remote whisper transcription | extra={{"taskName": null}}
2026-06-04 17:37:21,980 ERROR Unexpected error during processing | extra={{"taskName": null}}
Traceback (most recent call last):
  File "/app/src/podcast_processor/transcribe.py", line 429, in get_segments_for_chunk
    transcription = self.openai_client.audio.transcriptions.create()
httpx.ConnectError: [Errno 111] Connection refused
openai.APIConnectionError: Connection error. | extra={{"taskName": null}}
2026-06-04 17:37:21,988 INFO [JOB_STATUS_UPDATE] job_id={_JOB_ID} status=failed step_name=Unexpected error: Connection error. | extra={{"taskName": null}}
2026-06-04 17:37:21,995 ERROR [JOB_STATUS_ERROR] job_id={_JOB_ID} post_guid={_GUID} status=failed | extra={{"taskName": null}}
2026-06-04 17:51:19,341 INFO [API] GET /api/posts/{_GUID}/status status=200 | extra={{"taskName": null}}
"""


def test_select_troubleshoot_entries_prefers_flagged_levels():
    related = {
        "entries": [
            {"level": "INFO", "message": "starting"},
            {"level": "ERROR", "message": "boom"},
            {"level": "WARNING", "message": "careful"},
        ]
    }
    selected = select_troubleshoot_entries(related)
    assert [e["message"] for e in selected] == ["boom", "careful"]


def test_select_troubleshoot_entries_falls_back_when_no_flagged():
    related = {
        "entries": [{"level": "INFO", "message": f"line {i}"} for i in range(20)]
    }
    selected = select_troubleshoot_entries(related)
    # Falls back to the tail of available entries (15) when nothing is flagged.
    assert len(selected) == 15
    assert selected[-1]["message"] == "line 19"


def test_troubleshoot_context_captures_traceback(app, tmp_path):
    log_file = tmp_path / "app.log"
    log_file.write_text(_FAKE_LOG)

    with app.app_context():
        # No jobs passed: the synthetic failure line is tagged with post_guid,
        # so anchoring works off the post guid alone.
        with mock.patch(
            "app.failure_explainer.get_app_log_path", return_value=log_file
        ):
            context = build_troubleshoot_context(
                post_guid=_GUID, post_id=1, job_ids=set()
            )

    assert context is not None
    # The root cause (traceback + underlying exception) must be present --
    # exactly the lines `_build_related_logs` drops because they have no
    # timestamp prefix / post tag.
    assert "APIConnectionError: Connection error." in context
    assert "Connection refused" in context
    assert "get_segments_for_chunk" in context
    # The failure line we anchored on is included.
    assert "JOB_STATUS_ERROR" in context
    # The noisy extra suffix is stripped to save tokens.
    assert "| extra=" not in context


def test_troubleshoot_context_returns_none_without_failure(app, tmp_path):
    log_file = tmp_path / "app.log"
    log_file.write_text(
        '2026-06-04 17:37:00,000 INFO all good here | extra={"taskName": null}\n'
    )
    with app.app_context():
        with mock.patch(
            "app.failure_explainer.get_app_log_path", return_value=log_file
        ):
            assert (
                build_troubleshoot_context(post_guid=_GUID, post_id=1, job_ids=set())
                is None
            )


def test_troubleshoot_returns_explanation_from_traceback(app, tmp_path):
    app.testing = True
    app.register_blueprint(post_bp)
    guid = _make_post(app)

    log_file = tmp_path / "app.log"
    log_file.write_text(_FAKE_LOG)

    original_key = getattr(runtime_config, "llm_api_key", None)
    runtime_config.llm_api_key = "sk-test"
    try:
        with (
            mock.patch("app.failure_explainer.get_app_log_path", return_value=log_file),
            mock.patch(
                "litellm.completion",
                return_value=_fake_completion_response(
                    "Your remote Whisper server refused the connection."
                ),
            ) as mock_completion,
        ):
            response = app.test_client().post(
                f"/api/posts/{_encoded_guid(guid)}/troubleshoot"
            )
    finally:
        runtime_config.llm_api_key = original_key

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["used_traceback"] is True
    assert "Whisper" in payload["explanation"]

    # The traceback + root exception must actually reach the LLM prompt.
    _, kwargs = mock_completion.call_args
    user_msg = kwargs["messages"][-1]["content"]
    assert "APIConnectionError: Connection error." in user_msg
    assert "Connection refused" in user_msg


def test_troubleshoot_falls_back_to_structured_entries(app):
    app.testing = True
    app.register_blueprint(post_bp)
    guid = _make_post(app)

    related = {
        "latest_job_id": "job-1",
        "entries": [
            {
                "timestamp": "2026-06-04 10:00:00,000",
                "level": "ERROR",
                "stage": "transcription",
                "message": "AuthenticationError: invalid api key (401)",
            }
        ],
    }

    original_key = getattr(runtime_config, "llm_api_key", None)
    runtime_config.llm_api_key = "sk-test"
    try:
        with (
            mock.patch(
                "app.routes.post_routes.build_troubleshoot_context",
                return_value=None,
            ),
            mock.patch(
                "app.routes.post_routes._build_related_logs", return_value=related
            ),
            mock.patch(
                "litellm.completion",
                return_value=_fake_completion_response(
                    "Your API key was rejected. Update it in Settings."
                ),
            ) as mock_completion,
        ):
            response = app.test_client().post(
                f"/api/posts/{_encoded_guid(guid)}/troubleshoot"
            )
    finally:
        runtime_config.llm_api_key = original_key

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["used_traceback"] is False
    _, kwargs = mock_completion.call_args
    assert "invalid api key (401)" in kwargs["messages"][-1]["content"]


def test_troubleshoot_without_api_key_returns_400(app):
    app.testing = True
    app.register_blueprint(post_bp)
    guid = _make_post(app)

    original_key = getattr(runtime_config, "llm_api_key", None)
    runtime_config.llm_api_key = None
    try:
        with mock.patch(
            "app.routes.post_routes.build_troubleshoot_context",
            return_value="some traceback",
        ):
            response = app.test_client().post(
                f"/api/posts/{_encoded_guid(guid)}/troubleshoot"
            )
    finally:
        runtime_config.llm_api_key = original_key

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["ok"] is False
    assert "API key" in payload["error"]


def test_troubleshoot_with_no_logs_reports_nothing_to_diagnose(app):
    app.testing = True
    app.register_blueprint(post_bp)
    guid = _make_post(app)

    with (
        mock.patch(
            "app.routes.post_routes.build_troubleshoot_context", return_value=None
        ),
        mock.patch(
            "app.routes.post_routes._build_related_logs",
            return_value={"latest_job_id": None, "entries": []},
        ),
    ):
        response = app.test_client().post(
            f"/api/posts/{_encoded_guid(guid)}/troubleshoot"
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["explanation"] is None
    assert "nothing to diagnose" in payload["message"]


def test_troubleshoot_missing_post_returns_404(app):
    app.testing = True
    app.register_blueprint(post_bp)

    response = app.test_client().post("/api/posts/does-not-exist/troubleshoot")
    assert response.status_code == 404
