import logging
from types import SimpleNamespace
from typing import Any

import pytest

from podcast_processor.llm_model_call_utils import (
    apply_service_tier,
    call_litellm_with_tier_retry,
    extract_litellm_finish_reason,
    extract_litellm_usage,
    model_supports_service_tier,
    try_update_model_call,
)


def test_extract_litellm_finish_reason_from_object_choice() -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(finish_reason="length", message=None)]
    )

    assert extract_litellm_finish_reason(response) == "length"


def test_extract_litellm_finish_reason_from_dict_choice() -> None:
    response = SimpleNamespace(choices=[{"finish_reason": "stop"}])

    assert extract_litellm_finish_reason(response) == "stop"


def test_extract_litellm_usage_handles_object_and_numeric_strings() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens="101",
            prompt_tokens_details=SimpleNamespace(cached_tokens="33"),
            completion_tokens=22,
            total_tokens=123,
        )
    )

    assert extract_litellm_usage(response) == {
        "prompt_tokens": 101,
        "cached_prompt_tokens": 33,
        "completion_tokens": 22,
        "total_tokens": 123,
    }


def test_extract_litellm_usage_handles_dict_response() -> None:
    response = {
        "usage": {
            "prompt_tokens": 5,
            "prompt_tokens_details": {"cached_tokens": 2},
            "completion_tokens": 9,
            "total_tokens": 14,
        }
    }

    assert extract_litellm_usage(response) == {
        "prompt_tokens": 5,
        "cached_prompt_tokens": 2,
        "completion_tokens": 9,
        "total_tokens": 14,
    }


def test_extract_litellm_usage_handles_cache_read_input_tokens_fallback() -> None:
    response = {
        "usage": {
            "prompt_tokens": 5,
            "cache_read_input_tokens": 2,
            "completion_tokens": 9,
            "total_tokens": 14,
        }
    }

    assert extract_litellm_usage(response)["cached_prompt_tokens"] == 2


def test_extract_litellm_usage_leaves_cached_prompt_tokens_null_when_missing() -> None:
    response = {
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 9,
            "total_tokens": 14,
        }
    }

    assert extract_litellm_usage(response) == {
        "prompt_tokens": 5,
        "cached_prompt_tokens": None,
        "completion_tokens": 9,
        "total_tokens": 14,
    }


def test_try_update_model_call_forwards_token_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When usage is supplied, the writer payload must include token counts so
    the debug modal can render tokens alongside service tier. Missing fields
    must be omitted (not stored as None) so older responses don't overwrite
    existing values.
    """
    captured: dict[str, Any] = {}

    def fake_update(
        model: str, pk: Any, data: dict[str, Any], wait: bool = True
    ) -> Any:
        captured["model"] = model
        captured["pk"] = pk
        captured["data"] = data
        return SimpleNamespace(success=True, error=None)

    from podcast_processor import llm_model_call_utils

    monkeypatch.setattr(llm_model_call_utils.writer_client, "update", fake_update)

    try_update_model_call(
        42,
        status="success",
        response="hi",
        error_message=None,
        logger=logging.getLogger("test"),
        log_prefix="t",
        usage={
            "prompt_tokens": 10,
            "cached_prompt_tokens": 4,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    )

    assert captured["model"] == "ModelCall"
    assert captured["pk"] == 42
    assert captured["data"]["prompt_tokens"] == 10
    assert captured["data"]["cached_prompt_tokens"] == 4
    assert captured["data"]["completion_tokens"] == 5
    assert captured["data"]["total_tokens"] == 15

    # Now without usage: token keys must not appear at all.
    captured.clear()
    try_update_model_call(
        42,
        status="success",
        response="hi",
        error_message=None,
        logger=logging.getLogger("test"),
        log_prefix="t",
    )
    assert "prompt_tokens" not in captured["data"]
    assert "cached_prompt_tokens" not in captured["data"]
    assert "total_tokens" not in captured["data"]

    # Missing cached token data must not be coerced to zero or forwarded.
    captured.clear()
    try_update_model_call(
        42,
        status="success",
        response="hi",
        error_message=None,
        logger=logging.getLogger("test"),
        log_prefix="t",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    assert "cached_prompt_tokens" not in captured["data"]


def test_try_update_model_call_persists_estimated_cost_usd_for_llm_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On success, the writer payload must include ``estimated_cost_usd``
    so the web process never has to import litellm to render a stats page.
    The processing worker already has litellm loaded — computing the cost
    here is essentially free and is short-lived (worker exits after job).
    """
    captured: dict[str, Any] = {}

    def fake_update(
        model: str, pk: Any, data: dict[str, Any], wait: bool = True
    ) -> Any:
        captured["data"] = data
        return SimpleNamespace(success=True, error=None)

    from podcast_processor import llm_model_call_utils

    monkeypatch.setattr(llm_model_call_utils.writer_client, "update", fake_update)
    # Mock the price lookup so the test doesn't depend on litellm's price
    # table being shipped with the installed wheel.
    monkeypatch.setattr("app.llm_pricing.compute_model_call_cost", lambda _call: 0.0042)

    try_update_model_call(
        7,
        status="success",
        response="ok",
        error_message=None,
        logger=logging.getLogger("test"),
        log_prefix="t",
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
        model_name="gpt-4o-mini",
        service_tier=None,
        prompt="classify",
    )

    assert captured["data"]["estimated_cost_usd"] == 0.0042


def test_try_update_model_call_omits_cost_for_whisper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whisper transcription rows are not billable LLM calls; the worker
    must leave ``estimated_cost_usd`` out of the payload so the writer
    keeps the column NULL (dashboard treats NULL as 0 without importing
    litellm)."""
    captured: dict[str, Any] = {}

    def fake_update(
        model: str, pk: Any, data: dict[str, Any], wait: bool = True
    ) -> Any:
        captured["data"] = data
        return SimpleNamespace(success=True, error=None)

    from podcast_processor import llm_model_call_utils

    monkeypatch.setattr(llm_model_call_utils.writer_client, "update", fake_update)

    try_update_model_call(
        9,
        status="success",
        response="ok",
        error_message=None,
        logger=logging.getLogger("test"),
        log_prefix="t",
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        model_name="whisper-large-v3-turbo",
        prompt="Whisper transcription job",
    )

    assert "estimated_cost_usd" not in captured["data"]


def test_try_update_model_call_omits_cost_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-success transitions shouldn't compute or persist a cost."""
    captured: dict[str, Any] = {}

    def fake_update(
        model: str, pk: Any, data: dict[str, Any], wait: bool = True
    ) -> Any:
        captured["data"] = data
        return SimpleNamespace(success=True, error=None)

    from podcast_processor import llm_model_call_utils

    monkeypatch.setattr(llm_model_call_utils.writer_client, "update", fake_update)

    try_update_model_call(
        9,
        status="failed_retries",
        response=None,
        error_message="boom",
        logger=logging.getLogger("test"),
        log_prefix="t",
        usage={
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
        model_name="gpt-4o-mini",
    )

    assert "estimated_cost_usd" not in captured["data"]


# --------------------------------------------------------------------------
# service_tier helper tests
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gemini/gemini-2.5-flash", True),
        ("openai/gpt-4o-mini", True),
        ("anthropic/claude-3-5-sonnet", False),
        ("groq/openai/gpt-oss-120b", False),
        ("gpt-4o", False),
        (None, False),
        ("", False),
    ],
)
def test_model_supports_service_tier(model: str | None, expected: bool) -> None:
    assert model_supports_service_tier(model) is expected


def test_apply_service_tier_noop_when_default() -> None:
    args: dict[str, Any] = {"model": "gemini/gemini-2.5-flash"}
    apply_service_tier(args, SimpleNamespace(llm_service_tier="default"))
    assert "service_tier" not in args


def test_apply_service_tier_noop_for_unsupported_provider() -> None:
    args: dict[str, Any] = {"model": "anthropic/claude-3-5-sonnet"}
    apply_service_tier(args, SimpleNamespace(llm_service_tier="flex"))
    assert "service_tier" not in args


def test_apply_service_tier_sets_flex_for_gemini() -> None:
    args: dict[str, Any] = {"model": "gemini/gemini-2.5-flash"}
    apply_service_tier(args, SimpleNamespace(llm_service_tier="flex"))
    assert args["service_tier"] == "flex"


def test_apply_service_tier_sets_priority_for_openai() -> None:
    args: dict[str, Any] = {"model": "openai/gpt-4o-mini"}
    apply_service_tier(args, SimpleNamespace(llm_service_tier="priority"))
    assert args["service_tier"] == "priority"


def test_apply_service_tier_rejects_invalid_value() -> None:
    args: dict[str, Any] = {"model": "gemini/gemini-2.5-flash"}
    apply_service_tier(args, SimpleNamespace(llm_service_tier="bogus"))
    assert "service_tier" not in args


# --------------------------------------------------------------------------
# call_litellm_with_tier_retry tests (patch litellm.completion directly)
# --------------------------------------------------------------------------


class _FakeCompletion:
    def __init__(self, side_effects: list[Any]) -> None:
        self.side_effects = side_effects
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        result = self.side_effects.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _patch_litellm(monkeypatch: pytest.MonkeyPatch, fake: _FakeCompletion) -> None:
    import litellm

    monkeypatch.setattr(litellm, "completion", fake)


def test_tier_retry_passthrough_when_no_service_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeCompletion(["ok"])
    _patch_litellm(monkeypatch, fake)

    result = call_litellm_with_tier_retry(
        {"model": "gemini/gemini-2.5-flash"},
        config=SimpleNamespace(llm_service_tier="default"),
        logger=logging.getLogger("test"),
        sleep=lambda _s: None,
    )
    assert result == "ok"
    assert len(fake.calls) == 1
    assert "service_tier" not in fake.calls[0]


def test_tier_retry_succeeds_on_first_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeCompletion(["ok"])
    _patch_litellm(monkeypatch, fake)

    result = call_litellm_with_tier_retry(
        {"model": "gemini/gemini-2.5-flash", "service_tier": "flex"},
        config=SimpleNamespace(llm_service_tier="flex"),
        logger=logging.getLogger("test"),
        sleep=lambda _s: None,
    )
    assert result == "ok"
    assert len(fake.calls) == 1
    assert fake.calls[0]["service_tier"] == "flex"


def test_tier_retry_backs_off_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeCompletion(
        [
            RuntimeError("503 Service Unavailable"),
            RuntimeError("429 rate limit"),
            "ok",
        ]
    )
    _patch_litellm(monkeypatch, fake)
    sleeps: list[float] = []

    result = call_litellm_with_tier_retry(
        {"model": "gemini/gemini-2.5-flash", "service_tier": "flex"},
        config=SimpleNamespace(llm_service_tier="flex"),
        logger=logging.getLogger("test"),
        max_retries=5,
        base_delay=1.0,
        sleep=sleeps.append,
    )
    assert result == "ok"
    assert len(fake.calls) == 3
    assert sleeps == [1.0, 2.0]
    # All retries kept service_tier=flex
    for call in fake.calls:
        assert call["service_tier"] == "flex"


def test_tier_retry_falls_back_to_standard_on_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeCompletion(
        [
            RuntimeError("503 Service Unavailable"),
            RuntimeError("503 Service Unavailable"),
            RuntimeError("503 Service Unavailable"),
            "ok-standard",
        ]
    )
    _patch_litellm(monkeypatch, fake)

    result = call_litellm_with_tier_retry(
        {"model": "gemini/gemini-2.5-flash", "service_tier": "flex"},
        config=SimpleNamespace(llm_service_tier="flex"),
        logger=logging.getLogger("test"),
        max_retries=3,
        base_delay=0.0,
        sleep=lambda _s: None,
    )
    assert result == "ok-standard"
    # 3 flex attempts (all 503) + 1 standard-tier fallback.
    assert len(fake.calls) == 4
    assert fake.calls[0]["service_tier"] == "flex"
    assert fake.calls[1]["service_tier"] == "flex"
    assert fake.calls[2]["service_tier"] == "flex"
    assert "service_tier" not in fake.calls[3]


def test_tier_retry_reraises_non_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeCompletion([ValueError("bad request 400")])
    _patch_litellm(monkeypatch, fake)

    with pytest.raises(ValueError, match="bad request 400"):
        call_litellm_with_tier_retry(
            {"model": "gemini/gemini-2.5-flash", "service_tier": "flex"},
            config=SimpleNamespace(llm_service_tier="flex"),
            logger=logging.getLogger("test"),
            sleep=lambda _s: None,
        )
    assert len(fake.calls) == 1
