# Configuration

Podly reads its settings from `.env.local` in the project root. Copy
[`.env.local.example`](../.env.local.example) to get started; it lists every
variable with comments. Restart the container after you change the file.

Most of what follows is optional. A first install only needs the values in the
README's [quick start](../README.md#quick-start).

## Transcription backend

Podly sends audio to a transcription backend you run or rent; the app container
doesn't bundle Whisper. Pick one:

- **Groq (easiest):** set `WHISPER_TYPE=groq` and add a `GROQ_API_KEY`. You have
  nothing to host.
- **Self-hosted / local (most private):** set `WHISPER_TYPE=remote` and point
  `WHISPER_REMOTE_BASE_URL` at any OpenAI-compatible transcription server. We
  recommend one of these on your own machine or GPU box:
  - [WhisperX API server](https://github.com/Nyralei/whisperx-api-server):
    OpenAI-compatible WhisperX with word timestamps and diarization.
  - [ParakeetX](https://github.com/MaroonBrian1928/parakeetX): an
    OpenAI-compatible server built on NVIDIA Parakeet.

  Example:

  ```env
  WHISPER_TYPE=remote
  WHISPER_REMOTE_BASE_URL=http://localhost:8000/v1
  WHISPER_REMOTE_MODEL=whisper-1
  # WHISPER_REMOTE_API_KEY=   # only if your server requires one
  ```

With `WHISPER_TYPE=remote`, two more flags control speaker diarization:

```env
WHISPER_REMOTE_DIARIZE=false
WHISPER_REMOTE_SPEAKER_EMBEDDINGS=false
```

Set `WHISPER_REMOTE_DIARIZE=true` to have your remote Whisper server label
speakers. Set `WHISPER_REMOTE_SPEAKER_EMBEDDINGS=true` as well to get speaker
embeddings in that output; it needs diarization on.
[.env.local.example](../.env.local.example) lists every environment variable.

## INA audio segmentation (better ad boundaries)

A transcript records words and misses the music stings and silence that
bracket most podcast ads. INA
([inaSpeechSegmenter](https://github.com/ina-foss/inaSpeechSegmenter)) analyzes
the audio and tags time ranges as `speech`, `music`, `silence`, or
`noenergy`. Podly uses those tags in two places:

- **Audio cues for the LLM:** Podly writes non-speech regions into the transcript
  it sends to the model (e.g. `[122.4] [MUSIC] (5.2s)`). The model reads a music
  block as a likely edge of an ad break.
- **Cleaner cuts:** Podly merges ad windows with nothing but music or silence
  between them, and stretches ads at the start or end of an episode to take the
  music sting with them. You hear fewer half-second jingles and dead-air gaps after a cut.

INA costs you a separate service and a full audio-analysis pass per episode, so
Podly ships with it off.

```env
INA_ENABLED=false
INA_BASE_URL=http://localhost:8001
INA_TIMEOUT_SEC=3600
```

Set `INA_ENABLED=true` and point `INA_BASE_URL` at a service that exposes
`POST /segment`. [InaFastAPI](https://github.com/MaroonBrian1928/InaFastAPI)
wraps inaSpeechSegmenter behind that endpoint and runs locally. If the INA
service is down, Podly finishes the episode without the audio tags or the
boundary cleanup. INA has no effect on speaker diarization; the
`WHISPER_REMOTE_*` flags above control that.

## Hiding parts of the UI

Two flags hide parts of the UI and leave everything else alone:

```env
PODLY_HIDE_DISCORD_INTEGRATION=false
PODLY_HIDE_REPORT_ISSUE_BUTTON=false
```

- `PODLY_HIDE_DISCORD_INTEGRATION=true` hides the Discord SSO/config integration
  UI, including the login button and the admin Discord config tab.
- `PODLY_HIDE_REPORT_ISSUE_BUTTON=true` hides the `Report issue` button from the
  desktop nav and mobile menu.

## Stripe revenue in the cost dashboard

The admin cost dashboard can show Stripe subscription revenue next to compute
cost, in the `subscription_amount_cents` column. You opt in with:

```env
PODLY_STRIPE_BILLING_ENABLED=false
STRIPE_SECRET_KEY=
```

- Off by default. With billing off, Podly keeps the `stripe` SDK out of the
  long-lived Flask and writer processes and saves several MB of RAM.
- Set `PODLY_STRIPE_BILLING_ENABLED=true` and add `STRIPE_SECRET_KEY` to turn on
  the revenue-vs-cost view. Podly caches subscription amounts in memory for an
  hour to limit Stripe API calls.

## Rust sidecar

Podly runs several read-heavy and audio-heavy paths in a short-lived Rust binary,
`podly_tools`, to keep large temporary allocations out of the long-lived Flask
heap. The binary reads SQLite itself and returns the same JSON as the Python
routes. **The Docker image ships it and turns it on**; you configure nothing.

If the binary errors, Podly falls back to the Python code for that call and logs
`falling back to Python` to `src/instance/logs/app.log`. The call still
succeeds, so that log line is your one signal that the Rust path didn't run.

Each flag below turns off one path. Set it to `false` to debug that path or
compare it against Python:

```env
PODLY_RUST_AUDIO_ENABLED=true
PODLY_RUST_FEED_XML_ENABLED=true
PODLY_RUST_CHAPTERS_ENABLED=true
PODLY_RUST_FEED_REFRESH_ENABLED=true
PODLY_RUST_JOBS_ENABLED=true
PODLY_RUST_STATS_ENABLED=true
PODLY_RUST_TRANSCRIPT_ENABLED=true
PODLY_RUST_AD_MERGE_ENABLED=true
PODLY_RUST_PROFANITY_ENABLED=true
PODLY_RUST_FEED_POSTS_ENABLED=true
PODLY_RUST_WORD_BOUNDARY_ENABLED=true
PODLY_RUST_CHAPTER_FALLBACK_ENABLED=true
PODLY_RUST_COSTS_ENABLED=true
```

`PODLY_RUST_COSTS_ENABLED=true` moves `/api/admin/costs` and
`/api/admin/costs/calls` to the binary. Python looks up LiteLLM token prices
first and hands them over, then adds Stripe revenue to the response when
`PODLY_STRIPE_BILLING_ENABLED` is on.
