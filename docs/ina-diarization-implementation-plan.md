# INA Diarization Implementation Plan

## Goal

Add INA audio segmentation alongside the existing transcript pipeline so Podly can:

- persist non-speech audio regions such as `music`, `noise`, and `noEnergy`
- expose those segments in the episode stats API
- visualize them in the processing stats UI
- keep the analysis non-fatal so podcast processing still succeeds if INA is unavailable

## What Already Exists

The current codebase already supports the speaker-diarization half of the original design:

- remote Whisper requests can include `diarize`, `align`, and `speaker_embeddings`
- transcript segments already persist `speaker_label`
- the stats API already exposes speaker breakdown data
- the frontend already renders speaker badges and speaker summaries

That means this implementation focuses on the missing INA segmenter path rather than redoing the Whisper speaker work.

## Scope

### Backend

- add an `AudioSegment` SQLAlchemy model
- add a writer action to replace stored audio segments for a post
- add an INA HTTP client that posts audio to `POST {INA_BASE_URL}/segment`
- run INA analysis as an optional background task during processing
- store a dedicated `ModelCall` for INA runs
- clean up INA rows when processing data is cleared

### API

- expose `audio_segments` from `/api/posts/<guid>/stats`
- keep the payload shape compatible with existing transcript and speaker stats

### Frontend

- add an `Audio Segments` tab to stats modals when INA data exists
- show non-speech markers inline in the LLM transcript view to make music/noise timing easier to inspect

### Tests

- cover audio-segment persistence
- cover post-stats payload exposure
- cover cleanup behavior
- cover processor-side INA persistence orchestration

## Non-Goals

- no Alembic migration file in this change
  - project policy requires migrations to be generated separately with `./scripts/create_migration.sh "<message>"`
- no attempt to redesign runtime config storage around INA
  - this implementation uses environment variables directly: `INA_ENABLED`, `INA_BASE_URL`, and optional `INA_TIMEOUT_SEC`
- no replacement of the existing Whisper integration model
  - Whisper diarization remains on the current `remote` transcription path

## Rollout Plan

1. Land model + writer support for `audio_segment`.
2. Add optional INA client + processor integration.
3. Expose data in stats responses.
4. Render data in the frontend stats modals.
5. Run CI and inspect any formatter/autofix changes.
6. Generate a migration separately after review.

## Risks

- INA API contract is external and may vary by deployment.
  - mitigation: keep parsing simple and log warnings rather than failing processing
- background analysis can outlive transcription if the external service is slow.
  - mitigation: wait for the INA future before processing completes, but treat failures as warnings
- cleanup/reprocess flows can leave stale INA rows if not updated everywhere.
  - mitigation: remove `audio_segment` rows in both full-clear and keep-transcript cleanup flows

## Validation

- processing succeeds when INA is disabled
- processing succeeds when INA is enabled and the endpoint works
- processing still succeeds when INA is enabled but the endpoint fails
- stats API returns `audio_segments`
- stats modal shows the new tab and inline non-speech markers when data exists
