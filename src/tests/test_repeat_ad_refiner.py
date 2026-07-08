"""Tests for the repeat-ad LLM confirmation pass."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from podcast_processor.repeat_ad_refiner import RepeatAdConfirmation, RepeatAdRefiner
from shared.test_utils import create_standard_test_config


def _response(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    response.usage = SimpleNamespace(
        prompt_tokens=5,
        prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        completion_tokens=3,
        total_tokens=8,
    )
    return response


def _make_refiner() -> RepeatAdRefiner:
    refiner = RepeatAdRefiner(config=create_standard_test_config())
    # Avoid touching the writer for status updates.
    refiner._update_model_call = MagicMock()  # type: ignore[method-assign]
    return refiner


def _confirm(refiner: RepeatAdRefiner, content: str) -> RepeatAdConfirmation:
    action_res = SimpleNamespace(success=True, data={"model_call_id": 7})
    with (
        patch(
            "podcast_processor.repeat_ad_refiner.writer_client.action",
            return_value=action_res,
        ),
        patch("litellm.completion", return_value=_response(content)),
    ):
        return refiner.confirm(
            reference_text="Alienware sponsor read",
            candidate_segments=[{"start_time": 1.0, "text": "Elevate your gaming"}],
            candidate_first_seq=100,
            confidence_hint=0.8,
            post_id=5,
        )


def test_confirm_accepts_ad() -> None:
    out = _confirm(
        _make_refiner(),
        '{"is_ad": true, "confidence": 0.93, "reason": "same alienware ad"}',
    )
    assert out.is_ad is True
    assert out.confidence == 0.93
    assert out.model_call_id == 7


def test_confirm_rejects_non_ad() -> None:
    out = _confirm(
        _make_refiner(),
        '{"is_ad": false, "confidence": 0.1, "reason": "coincidental phrase"}',
    )
    assert out.is_ad is False
    assert out.confidence == 0.1


def test_confirm_uses_hint_when_confidence_missing() -> None:
    out = _confirm(_make_refiner(), '{"is_ad": true, "reason": "no confidence field"}')
    assert out.is_ad is True
    assert out.confidence == 0.8  # falls back to confidence_hint


def test_confirm_parse_failure_is_not_an_ad() -> None:
    out = _confirm(_make_refiner(), "this is not json at all")
    assert out.is_ad is False
    assert out.reason == "confirm_failed"


def test_parse_json_extracts_object_from_fences() -> None:
    parsed = RepeatAdRefiner._parse_json(
        '```json\n{"is_ad": true, "confidence": 0.5}\n```'
    )
    assert parsed == {"is_ad": True, "confidence": 0.5}


def test_coerce_confidence_clamps_and_defaults() -> None:
    assert RepeatAdRefiner._coerce_confidence("0.5", default=0.1) == 0.5
    assert RepeatAdRefiner._coerce_confidence(2.0, default=0.1) == 1.0
    assert RepeatAdRefiner._coerce_confidence(None, default=0.42) == 0.42
