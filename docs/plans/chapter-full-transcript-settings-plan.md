# Plan: Reuse Transcript LLM Settings for Chapter Topic Generation

## Goal

Let chapter topic generation optionally use the same transcript prompt shape and tuning knobs as ad classification:

- `processing.num_segments_to_input_to_prompt`
- `llm.openai_max_tokens` / `OPENAI_MAX_TOKENS`

This is meant for deployments where the LLM context window is large enough to send most or all transcript segments directly, avoiding topic-block truncation and reducing continuation retries.

## Current Behavior

Chapter topic generation currently:

- Converts transcript segments into roughly 60 topic blocks.
- Caps each block at `TOPIC_CHAPTER_MAX_CHARS_PER_BLOCK`.
- Sends a block-based JSON payload to the LLM.
- Uses a chapter-specific output token cap.
- Asks for `block_index`, `title`, and optionally `first_word`.
- Locally aligns generated chapters to word timestamps when `first_word` is available.

Ad classification currently:

- Sends transcript segments directly in chunks.
- Uses `processing.num_segments_to_input_to_prompt` to size the chunk.
- Uses `llm.openai_max_tokens` as the completion token cap.

## Proposed Behavior

Add a chapter topic context mode with two values:

- `blocks`: current behavior.
- `full_transcript`: send timestamped transcript segments directly, up to `processing.num_segments_to_input_to_prompt`.

In `full_transcript` mode, chapter topic generation should:

- Build a prompt from transcript segments instead of topic blocks.
- Reuse `config.processing.num_segments_to_input_to_prompt` as the max segment count.
- Reuse `config.openai_max_tokens` for `max_tokens` / `max_completion_tokens`.
- Ask the model for `start_segment_seq`, `title`, and `first_word`.
- Convert the returned `start_segment_seq` values into `Chapter` objects.
- Align starts locally using `first_word` and saved word timestamps.
- Fall back to block mode if the transcript exceeds the configured segment count or if the full-transcript response is unusable.

## Configuration

Prefer one new setting:

```text
PODLY_CHAPTER_TOPIC_CONTEXT_MODE=blocks|full_transcript
```

Default:

```text
blocks
```

Rationale:

- Avoids changing behavior for smaller-model deployments.
- Lets high-context deployments use their existing transcript LLM settings.
- Keeps prompt sizing mental model consistent with ad classification.

Add the new env flag to:

- `.env.example`
- Runtime config loading
- Any frontend/settings schema if this setting is user-visible

## Prompt Shape

For `full_transcript`, use compact timestamped segment JSON:

```json
[
  {"sequence_num":0,"start":0.0,"text":"..."},
  {"sequence_num":1,"start":8.4,"text":"..."}
]
```

Expected model response:

```json
{"chapter_count":2,"chapters":[
  {"start_segment_seq":0,"title":"Opening setup","first_word":"welcome"},
  {"start_segment_seq":42,"title":"Main investigation","first_word":"today"}
]}
```

Rules:

- First chapter must start at `start_segment_seq` 0.
- Preserve chronological order.
- Do not emit generic titles.
- `first_word` must be copied from the selected segment text.
- Keep JSON minified.

## Implementation Steps

1. Add config plumbing for `chapter_topic_context_mode`.
2. Thread `config` or the needed settings into `_refine_transcript_sourced_chapters` and `generate_topic_chapters_from_transcript_with_llm`.
3. Split topic generation into mode-specific prompt builders:
   - block prompt builder
   - full-transcript prompt builder
4. Add a parser for full-transcript topic plans:
   - parse `chapter_count`
   - parse `start_segment_seq`
   - salvage complete objects from truncated JSON where possible
5. Add a converter from full-transcript plan entries to `Chapter` objects.
6. Reuse existing local first-word alignment where possible, or add a small full-transcript alignment helper keyed by `start_segment_seq`.
7. Use `config.openai_max_tokens` for topic-plan calls when config is available.
8. Keep the existing continuation retry as a fallback, but prefer avoiding it by using the larger configured output cap.
9. Add logging:
   - selected chapter context mode
   - transcript segment count sent
   - prompt chars
   - max output tokens used
   - fallback reason when returning to block mode

## Tests

Add or update tests for:

- `full_transcript` mode prompt includes segment sequence numbers and no block indexes.
- Full-transcript parser handles valid JSON.
- Full-transcript parser salvages truncated complete objects.
- Generated chapters use returned `start_segment_seq` values.
- `first_word` alignment snaps starts to exact word timestamps.
- When transcript segment count exceeds `num_segments_to_input_to_prompt`, generation falls back to block mode.
- Topic generation uses `config.openai_max_tokens`.
- Existing block-mode behavior remains unchanged.

## Risks

- Very long full-transcript prompts can be more expensive than block prompts.
- Some models may produce less reliable JSON with very large input prompts.
- `start_segment_seq` is more precise than block indexes, but it depends on the model copying sequence numbers correctly.
- If `first_word` is not present in the selected segment, alignment should keep the segment start rather than failing the whole chapter plan.

## Rollout

1. Ship behind `PODLY_CHAPTER_TOPIC_CONTEXT_MODE=blocks` default.
2. Test locally with `full_transcript` on a known long episode.
3. Compare:
   - model calls per episode
   - prompt/completion tokens
   - continuation retry frequency
   - chapter count and boundary quality
4. If full-transcript mode works well for high-context models, consider exposing it in settings UI.
