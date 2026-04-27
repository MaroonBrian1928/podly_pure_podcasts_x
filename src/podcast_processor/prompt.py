from dataclasses import dataclass
from typing import Any

from podcast_processor.cue_detector import CueDetector
from podcast_processor.model_output import AdSegmentPrediction, AdSegmentPredictionList
from podcast_processor.transcribe import Segment
from shared.audio_segment_utils import prompt_audio_marker_label

DEFAULT_SYSTEM_PROMPT_PATH = "src/system_prompt.txt"
DEFAULT_USER_PROMPT_TEMPLATE_PATH = "src/user_prompt.jinja"

_cue_detector = CueDetector()


@dataclass(frozen=True)
class PromptAudioMarker:
    start: float
    end: float
    label: str


def _format_segment_prefix(segment: Segment) -> str:
    prefix = f"[{segment.start}]"
    if segment.speaker_label:
        prefix += f"[speaker={segment.speaker_label}]"
    return prefix


def build_prompt_audio_markers(audio_segments: list[Any]) -> list[PromptAudioMarker]:
    markers: list[PromptAudioMarker] = []

    for audio_segment in audio_segments:
        label = prompt_audio_marker_label(getattr(audio_segment, "label", None))
        if label is None:
            continue

        start_raw = getattr(audio_segment, "start_time", None)
        end_raw = getattr(audio_segment, "end_time", None)
        if start_raw is None or end_raw is None:
            continue

        try:
            start_time = float(start_raw)
            end_time = float(end_raw)
        except TypeError, ValueError:
            continue

        if end_time <= start_time:
            continue

        markers.append(PromptAudioMarker(start=start_time, end=end_time, label=label))

    return markers


def transcript_excerpt_for_prompt(
    segments: list[Segment],
    includes_start: bool,
    includes_end: bool,
    audio_markers: list[PromptAudioMarker] | None = None,
) -> str:
    entries: list[tuple[float, int, str]] = []

    for audio_marker in audio_markers or []:
        duration_seconds = max(0.0, float(audio_marker.end) - float(audio_marker.start))
        entries.append(
            (
                float(audio_marker.start),
                0,
                f"[{audio_marker.start}] [{audio_marker.label}] ({duration_seconds:.1f}s)",
            )
        )

    for segment in segments:
        entries.append(
            (
                float(segment.start),
                1,
                f"{_format_segment_prefix(segment)} "
                f"{_cue_detector.highlight_cues(segment.text)}",
            )
        )

    excerpts = [
        entry[2] for entry in sorted(entries, key=lambda item: (item[0], item[1]))
    ]
    if includes_start:
        excerpts.insert(0, "[TRANSCRIPT START]")
    if includes_end:
        excerpts.append("[TRANSCRIPT END]")

    return "\n".join(excerpts)


def build_speaker_context_for_prompt(segments: list[Segment]) -> str:
    speaker_stats: dict[str, dict[str, float | int]] = {}

    for segment in segments:
        speaker_label = (segment.speaker_label or "").strip()
        if not speaker_label:
            continue

        stats = speaker_stats.setdefault(
            speaker_label, {"duration": 0.0, "segments": 0}
        )
        stats["duration"] += max(0.0, float(segment.end) - float(segment.start))
        stats["segments"] += 1

    if not speaker_stats:
        return ""

    ranked_speakers = sorted(
        speaker_stats.items(),
        key=lambda item: (float(item[1]["duration"]), int(item[1]["segments"])),
        reverse=True,
    )

    total_duration = sum(float(stats["duration"]) for _, stats in ranked_speakers)
    total_segments = sum(int(stats["segments"]) for _, stats in ranked_speakers)
    use_duration = total_duration > 0.0
    total_basis = total_duration if use_duration else float(total_segments)

    speaker_summaries = []
    for speaker_label, stats in ranked_speakers[:2]:
        basis_value = (
            float(stats["duration"]) if use_duration else int(stats["segments"])
        )
        share_pct = round((basis_value / total_basis) * 100) if total_basis else 0
        speaker_summaries.append(f"{speaker_label} ({share_pct}%)")

    if len(speaker_summaries) == 1:
        dominant_summary = f"the dominant labeled speaker is {speaker_summaries[0]}"
    else:
        dominant_summary = "the dominant labeled speakers are " + " and ".join(
            speaker_summaries
        )

    return (
        "Speaker context: "
        f"{dominant_summary} across this transcript. "
        "A short switch to a less-common speaker is only a weak ad hint and must "
        "still be supported by normal promotional cues."
    )


def generate_system_prompt() -> str:
    valid_empty_example = AdSegmentPredictionList(ad_segments=[]).model_dump_json(
        exclude_none=True
    )

    output_for_one_shot_example = AdSegmentPredictionList(
        ad_segments=[
            AdSegmentPrediction(segment_offset=59.8, confidence=0.95),
            AdSegmentPrediction(segment_offset=64.8, confidence=0.9),
            AdSegmentPrediction(segment_offset=73.8, confidence=0.92),
            AdSegmentPrediction(segment_offset=77.8, confidence=0.98),
            AdSegmentPrediction(segment_offset=79.8, confidence=0.9),
        ],
        content_type="promotional_external",
        confidence=0.96,
    ).model_dump_json(exclude_none=True)

    example_output_for_prompt = output_for_one_shot_example.strip()

    one_shot_transcript_example = transcript_excerpt_for_prompt(
        [
            Segment(start=53.8, end=-1, text="That's all coming after the break."),
            Segment(
                start=59.8,
                end=-1,
                text="On this week's episode of Wildcard, actor Chris Pine tells "
                "us, it's okay not to be perfect.",
            ),
            Segment(
                start=64.8,
                end=-1,
                text="My film got absolutely decimated when it premiered, which "
                "brings up for me one of my primary triggers or whatever it was "
                "like, not being liked.",
            ),
            Segment(
                start=73.8,
                end=-1,
                text="I'm Rachel Martin, Chris Pine on How to Find Joy in Imperfection.",
            ),
            Segment(
                start=77.8,
                end=-1,
                text="That's on the new podcast, Wildcard.",
            ),
            Segment(
                start=79.8,
                end=-1,
                text="The Game Where Cards control the conversation.",
            ),
            Segment(
                start=83.8,
                end=-1,
                text="And welcome back to the show, today we're talking to Professor Hopkins",
            ),
        ],
        includes_start=False,
        includes_end=False,
    )

    technical_example = transcript_excerpt_for_prompt(
        [
            Segment(
                start=4762.7,
                end=-1,
                text="Our brains are configured differently.",
            ),
            Segment(
                start=4765.6,
                end=-1,
                text="My brain is configured perfectly for Ruby, perfectly for a dynamically typed language.",
            ),
            Segment(
                start=4831.3,
                end=-1,
                text="Shopify exists at a scale most programmers never touch, and it still runs on Rails.",
            ),
            Segment(start=4933.2, end=-1, text="Shopify.com has supported this show."),
        ],
        includes_start=False,
        includes_end=False,
    )

    return f"""Your job is to identify advertisements in podcast transcript excerpts with high precision, continuity awareness, and content-context sensitivity.

CRITICAL: distinguish external sponsor ads from technical discussion and self-promotion.

CONTENT-AWARE TAXONOMY:
- technical_discussion: Educational content, case studies, implementation details. Company names may appear as examples; do not mark as ads.
- educational/self_promo: Host discussing their own products, newsletters, funds, or courses (may include CTAs but are first-party).
- promotional_external: True sponsor ads for external companies with sales intent, URLs, promo codes, or explicit offers.
- transition: Brief bumpers that connect to or from ads; include if they are part of an ad block.

JSON CONTRACT (strict):
- Always respond with: {{"ad_segments": [...], "content_type": "<taxonomy>", "confidence": <0.0-1.0>}}
- Each ad_segments item must be: {{"segment_offset": <seconds.float>, "confidence": <0.0-1.0>}}
- If there are no ads, respond with: {valid_empty_example} (no extra keys).

DURATION AND CUE GUIDANCE:
- Ads are typically 15–120 seconds and contain CTAs, URLs/domains, promo/discount codes, phone numbers, or phrases like "brought to you by".
- Integrated ads can be longer but maintain sales intent; continuous mention of the same sponsor for >3 minutes without CTAs is likely educational/self_promo.
- Pre-roll/mid-roll/post-roll intros ("a word from our sponsor") and quick outros ("back to the show") belong to the ad block.

DECISION RULES:
1) Continuous ads: once an ad starts, follow it to its natural conclusion; include 1–5 second transitions.
2) Strong cues: treat URLs/domains, promo/discount language, and phone numbers as strong sponsor indicators.
3) Self-promotion guardrail: host promoting their own products/platforms → classify as educational/self_promo with lower confidence unless explicit external sponsorship language is present.
4) Boundary bias: if later segments clearly form an ad for a sponsor, pull in the prior two intro/transition lines as ad content.
5) Prefer labeling as content unless multiple strong ad cues appear with clear external branding.
6) Speaker labels: some segments may include [speaker=...] metadata. Treat a brief switch to a less-common speaker as only a weak ad hint; do not mark ads from speaker changes alone because host-read ads and guest segments are common.

This transcript excerpt is broken into segments starting with a timestamp [X] (seconds), and some lines may also include optional [speaker=Y] metadata. Output every segment that is advertisement content.

Example (external sponsor with CTA):
{one_shot_transcript_example}
Output: {example_output_for_prompt}

Example (technical mention, not an ad):
{technical_example}
Output: {{"ad_segments": [{{"segment_offset": 4933.2, "confidence": 0.75}}], "content_type": "technical_discussion", "confidence": 0.45}}
\n\n"""
