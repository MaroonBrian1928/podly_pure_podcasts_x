"""LLM confirmation pass for deterministically-found repeat ads.

The deterministic finder (``repeat_ad_finder``) locates spans that match an
already-detected ad. Before we trust a match enough to cut it, this module asks
the LLM a narrow yes/no question on just that candidate window — "is this the
same sponsor ad, or ordinary content that happens to share a phrase?" — and
records the exchange as a ModelCall so it surfaces as its own refining call.

Boundary tightening is intentionally NOT done here: once we write ad
identifications for a confirmed window, the existing ``_refine_boundaries`` pass
in :class:`AdClassifier` refines them exactly like any other ad block, so there
is a single boundary-refinement implementation rather than two.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Template

from app.writer.client import writer_client
from podcast_processor.llm_model_call_utils import (
    apply_service_tier,
    call_litellm_with_tier_retry,
    extract_litellm_usage,
    record_service_tier_on_model_call,
    try_update_model_call,
)
from shared.config import Config

# Sentinel ``first_segment_sequence_num`` for the confirm ModelCall. The
# ModelCall unique index is (post_id, first_seq, last_seq, model_name). Using a
# sentinel here keeps the confirm row distinct from (a) the classification call
# (0..N) and (b) the boundary-refine call that later runs on the SAME new block
# with the real (first, last) range and the same model_name — which would
# otherwise collide on upsert.
REPEAT_AD_CONFIRM_FIRST_SEQ_SENTINEL = -500


@dataclass
class RepeatAdConfirmation:
    is_ad: bool
    confidence: float
    reason: str
    model_call_id: int | None


class RepeatAdRefiner:
    def __init__(self, config: Config, logger: logging.Logger | None = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("global_logger")
        self.template = self._load_template()

    def _load_template(self) -> Template:
        path = (
            Path(__file__).resolve().parent.parent  # project src root
            / "repeat_ad_confirmation_prompt.jinja"
        )
        if path.exists():
            return Template(path.read_text())
        return Template(
            """Confirm whether the candidate is the same ad.
Confirmed ad copy:
{{ reference_text }}
Candidate:
{% for seg in candidate_segments %}[{{ seg.start_time }}] {{ seg.text }}
{% endfor %}
Return only JSON: {"is_ad": true, "confidence": 0.0, "reason": ""}"""
        )

    def confirm(
        self,
        *,
        reference_text: str,
        candidate_segments: list[dict[str, Any]],
        candidate_first_seq: int,
        confidence_hint: float,
        post_id: int | None = None,
    ) -> RepeatAdConfirmation:
        """Ask the LLM whether ``candidate_segments`` are advertisement content.

        ``confidence_hint`` is the source ad's confidence, used as the result
        confidence when the LLM omits one. Records a ModelCall for the exchange
        and returns its id so the caller can attach identifications to it.
        """
        prompt = self.template.render(
            reference_text=reference_text,
            candidate_segments=candidate_segments,
        )

        model_call_id = self._upsert_model_call(prompt, candidate_first_seq, post_id)
        raw_response: str | None = None

        try:
            completion_args: dict[str, Any] = {
                "model": self.config.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 1024,
                "timeout": self.config.openai_timeout,
                "api_key": self.config.llm_api_key,
                "base_url": self.config.openai_base_url,
            }
            apply_service_tier(completion_args, self.config)
            record_service_tier_on_model_call(
                model_call_id,
                completion_args,
                logger=self.logger,
                log_prefix="Repeat ad confirm",
            )
            response = call_litellm_with_tier_retry(
                completion_args,
                config=self.config,
                logger=self.logger,
                model_call_id=model_call_id,
            )
            usage = extract_litellm_usage(response)

            choice = response.choices[0] if response.choices else None
            content = ""
            if choice:
                content = (
                    getattr(getattr(choice, "message", None), "content", None) or ""
                )
                if not content:
                    content = getattr(choice, "text", "") or ""
            raw_response = content

            self._update_model_call(
                model_call_id,
                status="received_response",
                response=raw_response,
                error_message=None,
                usage=usage,
                prompt=prompt,
            )

            parsed = self._parse_json(content)
            if parsed is not None:
                is_ad = bool(parsed.get("is_ad", False))
                confidence = self._coerce_confidence(
                    parsed.get("confidence"), default=confidence_hint
                )
                reason = str(parsed.get("reason", "") or "")
                self._update_model_call(
                    model_call_id,
                    status="success",
                    response=raw_response,
                    error_message=None,
                    usage=usage,
                    prompt=prompt,
                )
                self.logger.info(
                    "Repeat ad confirm: is_ad=%s confidence=%.2f",
                    is_ad,
                    confidence,
                    extra={"model_call_id": model_call_id},
                )
                return RepeatAdConfirmation(
                    is_ad=is_ad,
                    confidence=confidence,
                    reason=reason,
                    model_call_id=model_call_id,
                )

            # Unparseable response: do not guess an ad into existence. Treat as
            # "not confirmed" so we never cut on a parse failure.
            self.logger.warning(
                "Repeat ad confirm: no parseable JSON; treating as not-an-ad",
                extra={
                    "model_call_id": model_call_id,
                    "content_preview": (content or "")[:200],
                },
            )
            self._update_model_call(
                model_call_id,
                status="success_heuristic",
                response=raw_response,
                error_message="parse_failed",
            )
        except Exception as exc:  # noqa: BLE001
            self._update_model_call(
                model_call_id,
                status="failed_permanent",
                response=raw_response,
                error_message=str(exc),
            )
            self.logger.warning("Repeat ad confirm failed: %s", exc)

        return RepeatAdConfirmation(
            is_ad=False,
            confidence=0.0,
            reason="confirm_failed",
            model_call_id=model_call_id,
        )

    def _upsert_model_call(
        self, prompt: str, candidate_first_seq: int, post_id: int | None
    ) -> int | None:
        if post_id is None:
            return None
        try:
            res = writer_client.action(
                "upsert_model_call",
                {
                    "post_id": post_id,
                    "model_name": self.config.llm_model,
                    "first_segment_sequence_num": REPEAT_AD_CONFIRM_FIRST_SEQ_SENTINEL,
                    "last_segment_sequence_num": int(candidate_first_seq),
                    "prompt": prompt,
                },
                wait=True,
            )
            if res and res.success:
                return (res.data or {}).get("model_call_id")
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Repeat ad confirm: failed to upsert ModelCall: %s", exc
            )
        return None

    @staticmethod
    def _coerce_confidence(value: Any, *, default: float) -> float:
        try:
            confidence = float(value)
        except TypeError, ValueError:
            return float(default)
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any] | None:
        cleaned = re.sub(r"```json|```", "", (content or "").strip())
        for candidate in re.findall(r"\{.*?\}", cleaned, re.DOTALL):
            try:
                parsed = json.loads(candidate)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(parsed, dict) and "is_ad" in parsed:
                return parsed
        return None

    def _update_model_call(
        self,
        model_call_id: int | None,
        *,
        status: str,
        response: str | None,
        error_message: str | None,
        usage: dict[str, int | None] | None = None,
        prompt: str | None = None,
    ) -> None:
        if model_call_id is None:
            return
        try:
            try_update_model_call(
                int(model_call_id),
                status=status,
                response=response,
                error_message=error_message,
                logger=self.logger,
                log_prefix="Repeat ad confirm",
                usage=usage,
                model_name=getattr(self.config, "llm_model", None),
                service_tier=getattr(self.config, "llm_service_tier", None),
                prompt=prompt,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "Repeat ad confirm: failed to update ModelCall %s: %s",
                model_call_id,
                exc,
            )
