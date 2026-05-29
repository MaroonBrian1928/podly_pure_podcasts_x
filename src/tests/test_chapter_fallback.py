import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

from podcast_processor.chapter_fallback import (
    TOPIC_CHAPTER_CAP_WINDOW_SECONDS,
    TOPIC_CHAPTER_MAX_BLOCK_SECONDS,
    TOPIC_CHAPTER_MAX_CHARS_PER_BLOCK,
    TOPIC_CHAPTER_SHORT_EPISODE_CAP,
    TOPIC_CHAPTER_SHORT_EPISODE_SECONDS,
    TOPIC_CHAPTER_TARGET_BLOCK_COUNT,
    _build_topic_blocks,
    _build_topic_chapter_generation_prompt,
    _chapters_from_topic_plan,
    _parse_topic_chapter_response,
    _topic_chapter_count_cap_for_duration,
    generate_chapters_from_transcript,
    generate_topic_chapters_from_transcript_with_llm,
    refine_description_chapters_with_word_refiner,
    refine_generated_chapter_titles_with_llm,
    refine_transcript_chapters_with_word_refiner,
    resolve_llm_path_chapters,
)
from podcast_processor.chapter_reader import Chapter
from shared.test_utils import create_standard_test_config


def test_resolve_llm_path_chapters_prefers_embedded() -> None:
    embedded = [
        Chapter("chp0", "Intro", 0, 10_000),
        Chapter("chp1", "Topic", 10_000, 20_000),
    ]

    with (
        patch(
            "podcast_processor.chapter_fallback.read_chapters",
            return_value=embedded,
        ),
        patch(
            "podcast_processor.chapter_fallback.parse_chapters_from_description"
        ) as parse_mock,
        patch(
            "podcast_processor.chapter_fallback.generate_chapters_from_transcript"
        ) as gen_mock,
    ):
        chapters, source = resolve_llm_path_chapters(
            unprocessed_audio_path="/tmp/test.mp3",
            description="00:00 Intro\n00:10 Topic",
            transcript_segments=[],
        )

    assert chapters == embedded
    assert source == "embedded"
    parse_mock.assert_not_called()
    gen_mock.assert_not_called()


def test_resolve_llm_path_chapters_falls_back_to_description() -> None:
    parsed = [
        Chapter("desc0", "Intro", 0, 120_000),
        Chapter("desc1", "Topic", 120_000, 300_000),
    ]

    segments = [
        SimpleNamespace(start_time=0.0, end_time=10.0, text="Intro"),
        SimpleNamespace(start_time=299.0, end_time=300.0, text="Wrap"),
    ]

    with (
        patch("podcast_processor.chapter_fallback.read_chapters", return_value=[]),
        patch(
            "podcast_processor.chapter_fallback.parse_chapters_from_description",
            return_value=parsed,
        ) as parse_mock,
        patch(
            "podcast_processor.chapter_fallback.generate_chapters_from_transcript"
        ) as gen_mock,
    ):
        chapters, source = resolve_llm_path_chapters(
            unprocessed_audio_path="/tmp/test.mp3",
            description="ignored",
            transcript_segments=segments,
        )

    assert chapters == parsed
    assert source == "description"
    parse_mock.assert_called_once()
    gen_mock.assert_not_called()


def test_generate_chapters_from_transcript_splits_windows_and_titles() -> None:
    segments = [
        SimpleNamespace(start_time=0.0, end_time=20.0, text="Intro and setup"),
        SimpleNamespace(start_time=310.0, end_time=330.0, text="Main topic one"),
        SimpleNamespace(start_time=630.0, end_time=650.0, text="Main topic two"),
    ]

    chapters = generate_chapters_from_transcript(
        segments,
        total_duration_ms=900_000,
        target_chapter_seconds=300,
        min_remaining_seconds_for_split=0,
    )

    assert [c.start_time_ms for c in chapters] == [0, 310_000, 630_000]
    assert [c.end_time_ms for c in chapters] == [310_000, 630_000, 900_000]
    assert [c.title for c in chapters] == [
        "Intro and setup",
        "Main topic one",
        "Main topic two",
    ]


def test_refine_description_chapters_with_word_refiner_adjusts_starts() -> None:
    config = create_standard_test_config()
    config.enable_word_level_boundary_refinder = True

    chapters = [
        Chapter("desc0", "First story", 5_000, 310_000),
        Chapter("desc1", "Second story", 310_000, 650_000),
    ]
    transcript_segments = [
        SimpleNamespace(sequence_num=0, start_time=0.0, end_time=4.0, text="Cold open"),
        SimpleNamespace(
            sequence_num=1,
            start_time=12.0,
            end_time=20.0,
            text="First story starts right now",
        ),
        SimpleNamespace(
            sequence_num=2,
            start_time=300.0,
            end_time=307.0,
            text="A quick transition",
        ),
        SimpleNamespace(
            sequence_num=3,
            start_time=318.0,
            end_time=328.0,
            text="Second story begins with an update",
        ),
    ]

    refined = refine_description_chapters_with_word_refiner(
        chapters,
        transcript_segments,
        config=config,
    )

    assert [ch.start_time_ms for ch in refined] == [12_000, 318_000]
    assert [ch.end_time_ms for ch in refined] == [318_000, 650_000]
    assert [ch.title for ch in refined] == ["First story", "Second story"]


def test_refine_transcript_chapters_falls_back_to_original_on_collision() -> None:
    """When the phrase matcher would pull a chapter back to or before the
    previous chapter's start, the refinement must be abandoned (use the
    original start) instead of nudging by 1 ms — a 1 ms offset still renders
    as the same MM:SS label in the UI and inside MP3 chapter tags.
    """
    config = create_standard_test_config()

    chapters = [
        Chapter("t0", "Intro to the case", 60_000, 250_000),
        Chapter("t1", "Life in the home", 250_000, 260_000),
        Chapter("t2", "Fire investigation", 260_000, 700_000),
    ]
    transcript_segments = [
        SimpleNamespace(
            sequence_num=0, start_time=0.0, end_time=20.0, text="Cold open"
        ),
        SimpleNamespace(
            sequence_num=1,
            start_time=240.0,
            end_time=246.0,
            text="Life in the home was modest",
        ),
        SimpleNamespace(
            sequence_num=2,
            start_time=235.0,
            end_time=239.0,
            text="Fire investigation begins early",
        ),
    ]

    # Force the refiner to return the phrase times that previously triggered
    # the 1 ms collision in the production log: chapter 2 pulled to 240 s and
    # chapter 3 pulled to 235 s (i.e. *before* chapter 2's refined start).
    def fake_estimate_phrase_time(
        self,
        *,
        all_segments,
        context_segments,
        preferred_segment_seq,
        phrase,
        direction,
    ) -> float | None:
        if phrase == "Life in the home":
            return 240.0
        if phrase == "Fire investigation":
            return 235.0
        return None

    with patch(
        "podcast_processor.word_boundary_refiner.WordBoundaryRefiner._estimate_phrase_time",
        new=fake_estimate_phrase_time,
    ):
        refined = refine_transcript_chapters_with_word_refiner(
            chapters,
            transcript_segments,
            config=config,
        )

    starts = [ch.start_time_ms for ch in refined]
    # Chapter 1 unchanged (idx 0 never refines), chapter 2 refined back to
    # 240 s, chapter 3 falls back to its original 260 s because 235 s would
    # collide with chapter 2.
    assert starts == [60_000, 240_000, 260_000]
    # The end of chapter 2 must equal the next chapter's start, not the
    # refined-but-rejected 235 000 value.
    assert refined[1].end_time_ms == 260_000


def test_chapter_title_refinement_prompt_forbids_generic_titles() -> None:
    """The title-refinement prompt must explicitly forbid generic
    placeholder titles like 'Intro' or 'Conclusion'. Without this rule the
    refinement step would happily "polish" content titles back into generics.
    """
    from podcast_processor.chapter_fallback import (
        _build_chapter_title_refinement_prompt,
    )

    chapters = [
        Chapter("c0", "Hello everybody", 0, 300_000),
        Chapter("c1", "Gold challenge", 300_000, 600_000),
    ]
    transcript_segments = [
        SimpleNamespace(start_time=0.0, end_time=20.0, text="Hello everybody"),
        SimpleNamespace(start_time=310.0, end_time=330.0, text="Gold challenge"),
    ]

    prompt = _build_chapter_title_refinement_prompt(chapters, transcript_segments)

    assert "Do NOT use" in prompt
    assert "'Intro'" in prompt
    assert "'Conclusion'" in prompt


def test_refine_generated_chapter_titles_with_llm_updates_titles() -> None:
    chapters = [
        Chapter("gen0", "Hello everybody and welcome...", 0, 300_000),
        Chapter("gen1", "You have to go find gold...", 300_000, 600_000),
    ]
    transcript_segments = [
        SimpleNamespace(start_time=0.0, end_time=20.0, text="Hello everybody"),
        SimpleNamespace(start_time=310.0, end_time=330.0, text="Gold challenge"),
    ]

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        '{"titles":[{"index":0,"title":"Episode intro"},'
                        '{"index":1,"title":"Gold mission"}]}'
                    )
                )
            )
        ]
    )

    with patch(
        "litellm.completion",
        return_value=response,
    ) as completion_mock:
        refined = refine_generated_chapter_titles_with_llm(
            chapters,
            transcript_segments,
            llm_model="test-model",
            llm_api_key="test-key",
            openai_base_url="https://llm.example.com/v1",
            openai_timeout_sec=30,
        )

    assert [c.title for c in refined] == ["Episode intro", "Gold mission"]
    assert [c.start_time_ms for c in refined] == [0, 300_000]
    assert completion_mock.call_args.kwargs["api_key"] == "test-key"
    assert completion_mock.call_args.kwargs["base_url"] == "https://llm.example.com/v1"


def test_generate_topic_chapters_from_transcript_with_llm_uses_llm_boundaries() -> None:
    transcript_segments = [
        SimpleNamespace(start_time=0.0, end_time=20.0, text="Host intro and recap"),
        SimpleNamespace(
            start_time=310.0,
            end_time=330.0,
            text="Castle challenge starts",
        ),
        SimpleNamespace(
            start_time=630.0,
            end_time=650.0,
            text="Roundtable and banishment",
        ),
    ]

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        '{"chapters":['
                        '{"block_index":0,"title":"Opening recap"},'
                        '{"block_index":1,"title":"Challenge begins"},'
                        '{"block_index":2,"title":"Roundtable fallout"}'
                        "]}"
                    )
                )
            )
        ]
    )

    with patch(
        "litellm.completion",
        return_value=response,
    ) as completion_mock:
        chapters = generate_topic_chapters_from_transcript_with_llm(
            transcript_segments,
            llm_model="test-model",
            llm_api_key="test-key",
            openai_base_url="https://llm.example.com/v1",
            total_duration_ms=900_000,
            openai_timeout_sec=30,
            min_chapter_seconds=0,
        )

    assert [c.start_time_ms for c in chapters] == [0, 310_000, 630_000]
    assert [c.end_time_ms for c in chapters] == [310_000, 630_000, 900_000]
    assert [c.title for c in chapters] == [
        "Opening recap",
        "Challenge begins",
        "Roundtable fallout",
    ]
    assert completion_mock.call_args.kwargs["api_key"] == "test-key"
    assert completion_mock.call_args.kwargs["base_url"] == "https://llm.example.com/v1"


def test_generate_topic_chapters_from_transcript_with_llm_retries_remaining_blocks() -> (
    None
):
    transcript_segments = [
        SimpleNamespace(start_time=0.0, end_time=20.0, text="Opening recap"),
        SimpleNamespace(start_time=600.0, end_time=620.0, text="Mission setup"),
        SimpleNamespace(start_time=1200.0, end_time=1220.0, text="Castle conflict"),
        SimpleNamespace(start_time=1800.0, end_time=1820.0, text="Roundtable vote"),
    ]

    prompts: list[str] = []

    def _mock_response(content: str, *, finish_reason: str) -> SimpleNamespace:
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    finish_reason=finish_reason,
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=100,
                completion_tokens=100,
                total_tokens=200,
            ),
        )

    first_response = _mock_response(
        (
            '{"chapter_count":4,"chapters":['
            '{"block_index":0,"title":"Opening recap"},'
            '{"block_index":1,"title":"Mission setup"},'
            '{"block_index":'
        ),
        finish_reason="length",
    )
    second_response = _mock_response(
        (
            '{"chapter_count":3,"chapters":['
            '{"block_index":1,"title":"Different duplicate title"},'
            '{"block_index":2,"title":"Castle conflict"},'
            '{"block_index":3,"title":"Roundtable vote"}'
            "]}"
        ),
        finish_reason="stop",
    )

    def _completion_side_effect(**kwargs):
        prompts.append(kwargs["messages"][-1]["content"])
        if len(prompts) == 1:
            return first_response
        return second_response

    with patch(
        "litellm.completion",
        side_effect=_completion_side_effect,
    ) as completion_mock:
        chapters = generate_topic_chapters_from_transcript_with_llm(
            transcript_segments,
            llm_model="test-model",
            total_duration_ms=2_400_000,
            openai_timeout_sec=30,
            min_chapter_seconds=0,
        )

    assert completion_mock.call_count == 2
    assert len(prompts) == 2
    assert "Return only chapters with block_index > 1" in prompts[1]
    assert "Do not repeat existing chapter block_index values: [0, 1]" in prompts[1]

    retry_payload = json.loads(prompts[1].split("Transcript blocks:\n", 1)[1])
    assert [block["block_index"] for block in retry_payload] == [1, 2, 3]

    assert [c.start_time_ms for c in chapters] == [0, 600_000, 1_200_000, 1_800_000]
    assert [c.end_time_ms for c in chapters] == [
        600_000,
        1_200_000,
        1_800_000,
        2_400_000,
    ]
    assert [c.title for c in chapters] == [
        "Opening recap",
        "Mission setup",
        "Castle conflict",
        "Roundtable vote",
    ]


def test_build_topic_blocks_reduces_prompt_payload_for_long_transcript() -> None:
    segments = [
        SimpleNamespace(
            start_time=float(i * 60),
            end_time=float(i * 60 + 20),
            text=("word " * 120).strip(),
        )
        for i in range(120)
    ]

    blocks = _build_topic_blocks(
        segments,
        total_duration_ms=7_200_000,  # 2h
    )

    assert 1 < len(blocks) <= TOPIC_CHAPTER_TARGET_BLOCK_COUNT
    for block in blocks:
        assert isinstance(block["text"], str)
        assert len(block["text"]) <= TOPIC_CHAPTER_MAX_CHARS_PER_BLOCK


def test_build_topic_blocks_default_budget_preserves_expanded_context() -> None:
    lead_in = "a" * 700
    topic_signal = " riverfront search at 2 a.m."
    segments = [
        SimpleNamespace(
            start_time=0.0,
            end_time=45.0,
            text=lead_in + topic_signal + (" b" * 100),
        )
    ]

    blocks = _build_topic_blocks(
        segments,
        total_duration_ms=45_000,
    )

    assert TOPIC_CHAPTER_MAX_CHARS_PER_BLOCK == 1000
    assert len(blocks) == 1
    assert len(blocks[0]["text"]) <= TOPIC_CHAPTER_MAX_CHARS_PER_BLOCK
    assert topic_signal.strip() in blocks[0]["text"]


def test_build_topic_blocks_captures_mid_block_signal_via_split() -> None:
    """When a block's content overflows the char budget, the truncation must
    include a window around the block's midpoint, not just the front — that's
    where substantive discussion (and thus chapter-title signal) typically
    sits in a 2-minute topic block.
    """
    from podcast_processor.chapter_fallback import (
        TOPIC_CHAPTER_MAX_CHARS_PER_BLOCK as budget,
    )

    lead = "a" * 600
    signal = " RIVERFRONT_SIGNAL "
    tail = "b" * 600
    segments = [
        SimpleNamespace(
            start_time=0.0,
            end_time=45.0,
            text=lead + signal + tail,
        )
    ]

    blocks = _build_topic_blocks(segments, total_duration_ms=45_000)

    assert len(blocks) == 1
    text = blocks[0]["text"]
    assert len(text) <= budget
    assert text.startswith("a")
    assert " ... " in text
    assert "RIVERFRONT_SIGNAL" in text


def test_build_topic_blocks_returns_full_text_when_under_budget() -> None:
    segments = [
        SimpleNamespace(start_time=0.0, end_time=10.0, text="short block content"),
    ]
    blocks = _build_topic_blocks(segments, total_duration_ms=10_000)
    assert len(blocks) == 1
    assert blocks[0]["text"] == "short block content"
    assert " ... " not in blocks[0]["text"]


def test_build_topic_blocks_caps_long_episode_window_at_two_minutes() -> None:
    segments = [
        SimpleNamespace(
            start_time=float(i * 60),
            end_time=float(i * 60 + 20),
            text=f"segment {i}",
        )
        for i in range(180)
    ]

    blocks = _build_topic_blocks(
        segments,
        total_duration_ms=10_800_000,  # 3h
    )

    assert len(blocks) > TOPIC_CHAPTER_TARGET_BLOCK_COUNT
    assert len(blocks) <= 10_800_000 // (TOPIC_CHAPTER_MAX_BLOCK_SECONDS * 1000) + 1
    assert blocks[0]["start_ms"] == 0
    assert blocks[1]["start_ms"] - blocks[0]["start_ms"] <= (
        TOPIC_CHAPTER_MAX_BLOCK_SECONDS * 1000
    )


def test_parse_topic_chapter_response_salvages_truncated_json(caplog) -> None:
    truncated = (
        '{"chapter_count":4,"chapters":[{"block_index":0,'
        '"title":"Intro and breakfast drama"},'
        '{"block_index":3,"title":"Mission and strategy breakdown"},'
        '{"block_index":7,"title":"Conflict at the round table"},'
        '{"block_index":'
    )

    test_logger = logging.getLogger("global_logger")
    original_level = test_logger.level
    test_logger.addHandler(caplog.handler)
    test_logger.setLevel(logging.WARNING)
    try:
        parsed = _parse_topic_chapter_response(truncated)
    finally:
        test_logger.removeHandler(caplog.handler)
        test_logger.setLevel(original_level)

    assert parsed == [
        (0, "Intro and breakfast drama"),
        (3, "Mission and strategy breakdown"),
        (7, "Conflict at the round table"),
    ]
    assert "Recovered partial topic chapter plan is incomplete" in caplog.text


def test_build_topic_chapter_generation_prompt_requests_minified_and_hard_cap() -> None:
    blocks = [
        {"block_index": 0, "timestamp": "00:00", "text": "intro block"},
        {"block_index": 1, "timestamp": "08:00", "text": "mission block"},
        {"block_index": 2, "timestamp": "16:00", "text": "roundtable block"},
    ]

    prompt = _build_topic_chapter_generation_prompt(
        blocks=blocks,
        total_duration_ms=2_160_000,  # 36 min
        target_chapter_seconds=8 * 60,
        min_chapter_seconds=2 * 60,
    )

    assert "Return minified JSON only on a single line" in prompt
    assert '{"chapter_count":2,"chapters":[' in prompt
    assert "Put chapter_count first in the JSON object" in prompt
    assert (
        f"Hard cap: at most {TOPIC_CHAPTER_SHORT_EPISODE_CAP} chapters total" in prompt
    )
    assert "ceiling, not a target" in prompt
    # The example titles must not include the generic placeholder words the
    # rule below forbids — LLMs anchor heavily on examples, so an "Intro"
    # example would directly cause the very problem the rule is trying to
    # prevent. Keep this check in sync with both the example and the rule.
    assert '"title":"Intro"' not in prompt
    assert '"title":"Main topic"' not in prompt
    # Explicit prohibition of generic placeholder titles.
    assert "Do NOT use" in prompt
    assert "'Intro'" in prompt
    assert "'Conclusion'" in prompt


def test_topic_chapter_count_cap_for_duration_matches_configured_policy() -> None:
    assert _topic_chapter_count_cap_for_duration(120 * 60) == (
        (120 * 60 + TOPIC_CHAPTER_CAP_WINDOW_SECONDS - 1)
        // TOPIC_CHAPTER_CAP_WINDOW_SECONDS
    )
    assert (
        _topic_chapter_count_cap_for_duration(36 * 60)
        == TOPIC_CHAPTER_SHORT_EPISODE_CAP
    )
    assert (
        _topic_chapter_count_cap_for_duration(59 * 60)
        == TOPIC_CHAPTER_SHORT_EPISODE_CAP
    )
    assert _topic_chapter_count_cap_for_duration(
        TOPIC_CHAPTER_SHORT_EPISODE_SECONDS
    ) == (
        (TOPIC_CHAPTER_SHORT_EPISODE_SECONDS + TOPIC_CHAPTER_CAP_WINDOW_SECONDS - 1)
        // TOPIC_CHAPTER_CAP_WINDOW_SECONDS
    )


def test_generate_topic_chapters_uses_rust_topic_blocks_when_enabled(
    monkeypatch,
) -> None:
    """When the chapter Rust flag is on and a post_guid is threaded through,
    `_build_topic_blocks` is skipped in favour of the sidecar call. The Rust
    payload is used verbatim for the LLM prompt; Python parsing/chapter
    assembly downstream is unchanged."""
    from types import SimpleNamespace

    transcript_segments = [
        SimpleNamespace(start_time=0.0, end_time=20.0, text="Intro segment"),
        SimpleNamespace(start_time=310.0, end_time=330.0, text="Mid segment"),
        SimpleNamespace(start_time=630.0, end_time=650.0, text="End segment"),
    ]

    rust_blocks = [
        {
            "block_index": 0,
            "start_ms": 0,
            "end_ms": 300_000,
            "timestamp": "00:00",
            "text": "Intro from Rust",
        },
        {
            "block_index": 1,
            "start_ms": 300_000,
            "end_ms": 600_000,
            "timestamp": "05:00",
            "text": "Mid from Rust",
        },
        {
            "block_index": 2,
            "start_ms": 600_000,
            "end_ms": 900_000,
            "timestamp": "10:00",
            "text": "End from Rust",
        },
    ]

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        '{"chapters":['
                        '{"block_index":0,"title":"From Rust 0"},'
                        '{"block_index":1,"title":"From Rust 1"},'
                        '{"block_index":2,"title":"From Rust 2"}'
                        "]}"
                    )
                )
            )
        ]
    )

    monkeypatch.setenv("PODLY_RUST_CHAPTER_FALLBACK_ENABLED", "true")

    with (
        patch("litellm.completion", return_value=response),
        patch(
            "shared.rust_sidecar.try_chapter_topic_blocks",
            return_value=rust_blocks,
        ) as rust_mock,
        patch(
            "podcast_processor.chapter_fallback._build_topic_blocks",
            side_effect=AssertionError("python _build_topic_blocks must not run"),
        ),
    ):
        chapters = generate_topic_chapters_from_transcript_with_llm(
            transcript_segments,
            llm_model="test-model",
            llm_api_key="test-key",
            openai_base_url="https://llm.example.com/v1",
            total_duration_ms=900_000,
            openai_timeout_sec=30,
            min_chapter_seconds=0,
            post_guid="post-abc",
        )

    assert rust_mock.called
    assert rust_mock.call_args.kwargs["post_guid"] == "post-abc"
    assert rust_mock.call_args.kwargs["total_duration_ms"] == 900_000
    assert (
        rust_mock.call_args.kwargs["max_chars_per_block"]
        == TOPIC_CHAPTER_MAX_CHARS_PER_BLOCK
    )
    assert [c.title for c in chapters] == [
        "From Rust 0",
        "From Rust 1",
        "From Rust 2",
    ]


def test_generate_topic_chapters_falls_back_to_python_when_rust_disabled(
    monkeypatch,
) -> None:
    """Rust wrapper must not be called when the chapter flag is off."""
    from types import SimpleNamespace

    transcript_segments = [
        SimpleNamespace(start_time=0.0, end_time=20.0, text="Host intro"),
        SimpleNamespace(start_time=310.0, end_time=330.0, text="Mid talk"),
    ]
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"chapters":[{"block_index":0,"title":"x"}]}'
                )
            )
        ]
    )

    monkeypatch.delenv("PODLY_RUST_CHAPTER_FALLBACK_ENABLED", raising=False)

    def boom(**_kwargs):
        raise AssertionError("try_chapter_topic_blocks invoked with flag disabled")

    with (
        patch("litellm.completion", return_value=response),
        patch("shared.rust_sidecar.try_chapter_topic_blocks", side_effect=boom),
    ):
        chapters = generate_topic_chapters_from_transcript_with_llm(
            transcript_segments,
            llm_model="test-model",
            llm_api_key="test-key",
            total_duration_ms=600_000,
            openai_timeout_sec=30,
            min_chapter_seconds=0,
            post_guid="post-abc",
        )

    assert chapters  # Python path produced at least one chapter.


def test_generate_topic_chapters_falls_back_when_rust_returns_none(
    monkeypatch,
) -> None:
    """Rust wrapper returning None (sidecar failed / bad payload) must trigger
    the Python fallback rather than empty chapters."""
    from types import SimpleNamespace

    transcript_segments = [
        SimpleNamespace(start_time=0.0, end_time=20.0, text="Intro talk"),
        SimpleNamespace(start_time=310.0, end_time=330.0, text="Mid talk"),
    ]
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"chapters":[{"block_index":0,"title":"From Python"}]}'
                )
            )
        ]
    )

    monkeypatch.setenv("PODLY_RUST_CHAPTER_FALLBACK_ENABLED", "true")

    with (
        patch("litellm.completion", return_value=response),
        patch(
            "shared.rust_sidecar.try_chapter_topic_blocks", return_value=None
        ) as rust_mock,
    ):
        chapters = generate_topic_chapters_from_transcript_with_llm(
            transcript_segments,
            llm_model="test-model",
            llm_api_key="test-key",
            total_duration_ms=600_000,
            openai_timeout_sec=30,
            min_chapter_seconds=0,
            post_guid="post-abc",
        )

    assert rust_mock.called
    assert chapters  # Python path produced at least one chapter.


def test_generate_topic_chapters_forwards_removed_windows_to_rust(
    monkeypatch,
) -> None:
    """When the caller threads ad-removal windows through to the Rust path, the
    wrapper receives them so the sidecar can reproduce the filter the Python
    `_filter_transcript_segments_for_chapters` call would have applied."""
    from types import SimpleNamespace

    transcript_segments = [
        SimpleNamespace(start_time=0.0, end_time=20.0, text="Intro"),
        SimpleNamespace(start_time=310.0, end_time=330.0, text="Mid"),
    ]
    rust_blocks = [
        {
            "block_index": 0,
            "start_ms": 0,
            "end_ms": 600_000,
            "timestamp": "00:00",
            "text": "Block 0",
        },
    ]
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"chapters":[{"block_index":0,"title":"t0"}]}'
                )
            )
        ]
    )
    removed_windows = [(100_000, 150_000), (200_000, 250_000)]

    monkeypatch.setenv("PODLY_RUST_CHAPTER_FALLBACK_ENABLED", "true")

    with (
        patch("litellm.completion", return_value=response),
        patch(
            "shared.rust_sidecar.try_chapter_topic_blocks",
            return_value=rust_blocks,
        ) as rust_mock,
    ):
        chapters = generate_topic_chapters_from_transcript_with_llm(
            transcript_segments,
            llm_model="test-model",
            llm_api_key="test-key",
            total_duration_ms=600_000,
            openai_timeout_sec=30,
            min_chapter_seconds=0,
            post_guid="post-abc",
            removed_windows_ms=removed_windows,
        )

    assert rust_mock.called
    forwarded = rust_mock.call_args.kwargs["removed_windows_ms"]
    assert forwarded == removed_windows
    assert chapters  # End-to-end success path.


def test_parse_topic_chapter_response_uses_rust_when_enabled(monkeypatch) -> None:
    """`_parse_topic_chapter_response` short-circuits to the Rust wrapper when
    the chapter flag is on. The wrapper return shape is normalized back to the
    Python `list[tuple[int, str]]` contract callers rely on."""
    monkeypatch.setenv("PODLY_RUST_CHAPTER_FALLBACK_ENABLED", "true")

    fake_payload = {
        "entries": [(0, "Opening"), (3, "Closing")],
        "expected_count": 2,
        "salvaged": False,
        "count_mismatch": False,
    }

    with patch(
        "shared.rust_sidecar.try_chapter_topic_plan_parse",
        return_value=fake_payload,
    ) as rust_mock:
        result = _parse_topic_chapter_response(
            '{"chapter_count": 2, "chapters": [...]}'
        )

    assert rust_mock.called
    assert result == [(0, "Opening"), (3, "Closing")]


def test_parse_topic_chapter_response_falls_back_when_rust_returns_none(
    monkeypatch,
) -> None:
    """A Rust None return triggers the Python parse path; same valid input
    still produces the same `(block_index, title)` list."""
    monkeypatch.setenv("PODLY_RUST_CHAPTER_FALLBACK_ENABLED", "true")

    with patch(
        "shared.rust_sidecar.try_chapter_topic_plan_parse", return_value=None
    ) as rust_mock:
        result = _parse_topic_chapter_response(
            '{"chapter_count": 1, "chapters": [{"block_index": 0, "title": "X"}]}'
        )

    assert rust_mock.called
    assert result == [(0, "X")]


def test_parse_topic_chapter_response_skips_rust_for_empty_input(
    monkeypatch,
) -> None:
    """Empty content should never invoke the Rust wrapper — Python handles the
    WARN log path for that case."""
    monkeypatch.setenv("PODLY_RUST_CHAPTER_FALLBACK_ENABLED", "true")

    def boom(**_kwargs):
        raise AssertionError("Rust wrapper called for empty content")

    with patch("shared.rust_sidecar.try_chapter_topic_plan_parse", side_effect=boom):
        assert _parse_topic_chapter_response("") == []
        assert _parse_topic_chapter_response("   \n  ") == []


def test_chapters_from_topic_plan_uses_rust_when_enabled(monkeypatch) -> None:
    """`_chapters_from_topic_plan` short-circuits to the Rust wrapper when the
    chapter flag is on, and the wrapper output is materialized into Chapter
    objects the rest of the pipeline expects."""
    monkeypatch.setenv("PODLY_RUST_CHAPTER_FALLBACK_ENABLED", "true")

    rust_chapters = [
        {
            "element_id": "tgen0",
            "title": "Intro",
            "start_time_ms": 0,
            "end_time_ms": 300_000,
        },
        {
            "element_id": "tgen1",
            "title": "Outro",
            "start_time_ms": 300_000,
            "end_time_ms": 900_000,
        },
    ]
    plan = [(0, "Intro"), (5, "Outro")]
    blocks = [
        {"block_index": 0, "start_ms": 0, "end_ms": 250_000, "text": "a"},
        {"block_index": 5, "start_ms": 300_000, "end_ms": 900_000, "text": "b"},
    ]

    with patch(
        "shared.rust_sidecar.try_chapter_topic_plan_apply",
        return_value=rust_chapters,
    ) as rust_mock:
        result = _chapters_from_topic_plan(
            plan,
            blocks=blocks,
            total_duration_ms=900_000,
            min_chapter_gap_ms=60_000,
        )

    assert rust_mock.called
    forwarded = rust_mock.call_args.kwargs
    assert forwarded["plan"] == plan
    assert forwarded["total_duration_ms"] == 900_000
    assert forwarded["min_chapter_gap_ms"] == 60_000
    assert [c.title for c in result] == ["Intro", "Outro"]
    assert [c.start_time_ms for c in result] == [0, 300_000]
    assert [c.end_time_ms for c in result] == [300_000, 900_000]


def test_chapters_from_topic_plan_falls_back_when_rust_returns_none(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PODLY_RUST_CHAPTER_FALLBACK_ENABLED", "true")
    plan = [(0, "Intro"), (5, "Middle")]
    blocks = [
        {"block_index": 0, "start_ms": 0, "end_ms": 250_000, "text": "a"},
        {"block_index": 5, "start_ms": 300_000, "end_ms": 600_000, "text": "b"},
    ]

    with patch(
        "shared.rust_sidecar.try_chapter_topic_plan_apply", return_value=None
    ) as rust_mock:
        result = _chapters_from_topic_plan(
            plan,
            blocks=blocks,
            total_duration_ms=600_000,
            min_chapter_gap_ms=0,
        )

    assert rust_mock.called
    # Python path produces the same two chapters.
    assert [c.title for c in result] == ["Intro", "Middle"]


def test_chapters_from_topic_plan_skips_rust_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("PODLY_RUST_CHAPTER_FALLBACK_ENABLED", raising=False)

    def boom(**_kwargs):
        raise AssertionError("Rust apply wrapper invoked while flag disabled")

    plan = [(0, "Intro")]
    blocks = [
        {"block_index": 0, "start_ms": 0, "end_ms": 100_000, "text": "a"},
    ]
    with patch("shared.rust_sidecar.try_chapter_topic_plan_apply", side_effect=boom):
        result = _chapters_from_topic_plan(
            plan,
            blocks=blocks,
            total_duration_ms=100_000,
            min_chapter_gap_ms=0,
        )
    assert [c.title for c in result] == ["Intro"]


def test_segment_index_nearest_segment_seq() -> None:
    """The bisect-backed index must return the same seq the linear scan did
    for the three boundary cases: t inside a segment, t before any segment,
    t after the last segment."""
    from podcast_processor.chapter_fallback import _SegmentIndex

    segments = [
        {"sequence_num": 1, "start_time": 0.0, "end_time": 5.0, "text": "a"},
        {"sequence_num": 2, "start_time": 10.0, "end_time": 15.0, "text": "b"},
        {"sequence_num": 3, "start_time": 20.0, "end_time": 25.0, "text": "c"},
    ]
    idx = _SegmentIndex(segments)

    assert idx.nearest_segment_seq_for_time(12_000) == 2  # inside seg 2
    assert idx.nearest_segment_seq_for_time(-1_000) == 1  # before any
    assert idx.nearest_segment_seq_for_time(100_000) == 3  # after last
    # Gap between segments — closer to seg 1's end (5.0) than seg 2's start (10.0)
    assert idx.nearest_segment_seq_for_time(6_000) == 1
    # Gap between segments — closer to seg 2's start (10.0) than seg 1's end
    assert idx.nearest_segment_seq_for_time(9_000) == 2


def test_segment_index_context_window() -> None:
    from podcast_processor.chapter_fallback import _SegmentIndex

    segments = [
        {"sequence_num": 1, "start_time": 0.0, "end_time": 5.0, "text": "a"},
        {"sequence_num": 2, "start_time": 10.0, "end_time": 15.0, "text": "b"},
        {"sequence_num": 3, "start_time": 20.0, "end_time": 25.0, "text": "c"},
        {"sequence_num": 4, "start_time": 30.0, "end_time": 35.0, "text": "d"},
    ]
    idx = _SegmentIndex(segments)

    selected = idx.context_segments_around_time(time_seconds=12.0, window_seconds=10.0)
    seqs = [s["sequence_num"] for s in selected]
    # Window is [2, 22] — covers seg 1 (overlap on right edge), seg 2 (fully),
    # seg 3 (overlap on left edge); seg 4 is past the right edge.
    assert seqs == [1, 2, 3]

    # Falls outside all segments — falls back to first segment per existing
    # behavior so the refiner doesn't get an empty context list.
    selected = idx.context_segments_around_time(
        time_seconds=1_000.0, window_seconds=1.0
    )
    assert [s["sequence_num"] for s in selected] == [1]
