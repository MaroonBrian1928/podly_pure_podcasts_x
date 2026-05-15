import json
import logging
import re
from typing import Literal

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AdSegmentPrediction(BaseModel):
    segment_offset: float
    confidence: float


class AdSegmentPredictionList(BaseModel):
    ad_segments: list[AdSegmentPrediction]
    content_type: (
        Literal[
            "technical_discussion",
            "educational/self_promo",
            "promotional_external",
            "transition",
        ]
        | None
    ) = None
    confidence: float | None = None


def _attempt_json_repair(json_str: str) -> str:
    """
    Attempt to repair truncated JSON by adding missing closing brackets.

    This handles cases where the LLM response was cut off mid-JSON,
    e.g., '{"ad_segments":[{"segment_offset":10.5,"confidence":0.92}'
    """
    # Count opening and closing brackets/braces
    open_braces = json_str.count("{")
    close_braces = json_str.count("}")
    open_brackets = json_str.count("[")
    close_brackets = json_str.count("]")

    # If brackets are balanced, no repair needed
    if open_braces == close_braces and open_brackets == close_brackets:
        return json_str

    logger.warning(
        f"Detected unbalanced JSON: {open_braces} '{{' vs {close_braces} '}}', "
        f"{open_brackets} '[' vs {close_brackets} ']'. Attempting repair."
    )

    # Remove any trailing incomplete key-value pair
    # e.g., '..."confidence":0.9' or '..."key":"val' or '..."key":'
    # First, try to find the last complete value
    repaired = json_str.rstrip()

    # If ends with a comma, remove it (incomplete next element)
    repaired = repaired.rstrip(",")

    # If ends with a colon or incomplete string, try to truncate to last complete element
    # Pattern: ends with "key": or "key":"incomplete or similar
    incomplete_patterns = [
        r',"[^"]*":\s*$',  # ,"key":
        r',"[^"]*":\s*"[^"]*$',  # ,"key":"incomplete
    ]

    for pattern in incomplete_patterns:
        match = re.search(pattern, repaired)
        if match:
            repaired = repaired[: match.start()]
            logger.debug(f"Removed incomplete trailing content: {match.group()}")
            break

    # Recount after cleanup
    open_braces = repaired.count("{")
    close_braces = repaired.count("}")
    open_brackets = repaired.count("[")
    close_brackets = repaired.count("]")

    # Add missing closing brackets/braces in the right order
    # We need to determine the order based on the structure
    # Typically for our schema it's: ]} to close ad_segments array and outer object
    missing_brackets = close_brackets - open_brackets  # negative means we need more ]
    missing_braces = close_braces - open_braces  # negative means we need more }

    if missing_brackets < 0:
        repaired += "]" * abs(missing_brackets)
    if missing_braces < 0:
        repaired += "}" * abs(missing_braces)

    logger.info("Repaired JSON by adding missing closing brackets/braces")

    return repaired


def _merge_duplicate_ad_segments(text: str) -> str:
    """Merge duplicate ``"ad_segments"`` keys that some local LLMs produce.

    Python's ``json.loads`` silently keeps only the *last* value for duplicate
    keys, so ``{"ad_segments":[A], "ad_segments":[B]}`` would lose ``[A]``.
    """
    if text.count('"ad_segments"') <= 1:
        return text

    def _merge_pairs(pairs: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key == "ad_segments" and key in result:
                if isinstance(result[key], list) and isinstance(value, list):
                    result[key].extend(value)
                else:
                    result[key] = value
            else:
                result[key] = value
        return result

    try:
        merged = json.loads(text, object_pairs_hook=_merge_pairs)
        logger.warning(
            "Merged duplicate ad_segments keys (%d occurrences)",
            text.count('"ad_segments"'),
        )
        return json.dumps(merged)
    except json.JSONDecodeError, ValueError:
        return text


def _truncate_after_balanced_root(text: str) -> str:
    """Return ``text`` truncated to the end of the first balanced top-level
    ``{...}`` object. Trailing non-JSON garbage (which LLMs occasionally
    append, e.g. duplicate ``}0.98}`` tails) is discarded.

    String literals are respected so braces inside string values don't
    perturb the depth counter. If the input never reaches depth zero (likely
    a truncated response), the original string is returned untouched so the
    repair pass can take its own crack at it.
    """
    depth = 0
    in_string = False
    escape = False
    for index, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if in_string:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[: index + 1]
    return text


def clean_and_parse_model_output(model_output: str) -> AdSegmentPredictionList:
    start_marker = "{"

    assert model_output.count(start_marker) >= 1, (
        f"No opening brace found in: {model_output[:200]}"
    )

    start_idx = model_output.index(start_marker)
    model_output = model_output[start_idx:]

    # Truncate after the first balanced root object. Previously this used
    # ``rindex('}')`` which picks the *rightmost* close brace — wrong when
    # the LLM emits garbage like ``…"confidence":0.98}98}0.98}`` after the
    # real close, since the rightmost ``}`` belongs to that garbage and the
    # resulting string still fails to parse. Walking the brace depth (with
    # string awareness) finds the real end of the root JSON object.
    model_output = _truncate_after_balanced_root(model_output)

    model_output = model_output.replace("'", '"')
    model_output = model_output.replace("\n", "")
    model_output = model_output.strip()

    model_output = _merge_duplicate_ad_segments(model_output)

    # First attempt: try to parse as-is
    try:
        return AdSegmentPredictionList.model_validate_json(model_output)
    except Exception as first_error:  # noqa: BLE001
        logger.debug(f"Initial parse failed: {first_error}")

        # Second attempt: try to repair truncated JSON
        try:
            repaired_output = _attempt_json_repair(model_output)
            result = AdSegmentPredictionList.model_validate_json(repaired_output)
            logger.info("Successfully parsed model output after JSON repair")
            return result
        except Exception as repair_error:
            logger.error(
                f"JSON repair also failed. Original output (first 500 chars): {model_output[:500]}"
            )
            # Re-raise the original error with more context
            raise first_error from repair_error
