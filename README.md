<h2 align="center">
<img width="50%" src="src/app/static/images/logos/logo_with_text.png" />

</h2>

<p align="center">
<p align="center">Ad-block for podcasts. Create an ad-free RSS feed.</p>
<p align="center">
  <a href="https://discord.gg/FRB98GtF6N" target="_blank">
      <img src="https://img.shields.io/badge/discord-join-blue.svg?logo=discord&logoColor=white" alt="Discord">
  </a>
</p>

## Overview

Podly transcribes each podcast episode, uses an LLM to find the ad segments, and
cuts them out — giving you back a clean, ad-free RSS feed. It is provider-neutral:
transcription runs on Groq or any OpenAI-compatible Whisper/Parakeet server, and
ad detection works with most LLMs (OpenAI, Anthropic, Gemini, Groq, or a local
model) — no OpenAI key required.

<img width="100%" src="docs/images/screenshot.png" />

## How To Run

You have a few options to get started:

> 🚀 **New to self-hosting?** Start with the
> [Ultimate Beginner's Guide](docs/how_to_run_beginners.md). It walks you through
> the Docker setup step by step — and even shows you how to have an AI assistant
> (Claude Code, Gemini CLI, Cursor, or Windsurf) run the whole setup for you.

- [![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/podly?referralCode=NMdeg5&utm_medium=integration&utm_source=template&utm_campaign=generic)
   - quick and easy setup in the cloud, follow our [Railway deployment guide](docs/how_to_run_railway.md). 
   - Use this if you want to share your Podly server with others.
- **Run Locally**: 
   - For local development and customization, 
   - see our [beginner's guide for running locally](docs/how_to_run_beginners.md). 
   - Use this for the most cost-optimal & private setup.

> ⚠️ **Enable authentication before exposing Podly to the internet.** Without it,
> anyone who can reach your URL can read and control your feeds. Auth is on by
> default in `.env.example` — set your own password and keep it enabled.
> Note that some podcast apps (e.g. **Pocket Casts**) fetch feeds from their own
> servers, so your feed URL must be **publicly reachable**; use the "Copy
> protected feed" button to share a public URL that stays token-protected. See
> the [beginner's guide](docs/how_to_run_beginners.md#recommended-enable-authentication)
> for details.


## How it works:

- You request an episode
- Podly downloads the requested episode
- A transcription model (Whisper or Parakeet) transcribes the episode
- An LLM labels the ad segments
- Podly removes the ad segments
- Podly delivers the ad-free version of the podcast to you

## Transcription (Whisper)

Podly does not run embedded local Whisper inside the app container. You point it
at a transcription backend instead. Two options:

- **Groq (easiest):** set `WHISPER_TYPE=groq` and add a `GROQ_API_KEY`. Works out
  of the box, nothing to self-host.
- **Self-hosted / local (most private):** set `WHISPER_TYPE=remote` and point
  `WHISPER_REMOTE_BASE_URL` at any OpenAI-compatible transcription server. We
  recommend running one of these on your own machine or GPU box:
  - [WhisperX API server](https://github.com/Nyralei/whisperx-api-server) —
    OpenAI-compatible WhisperX with word timestamps and diarization.
  - [ParakeetX](https://github.com/MaroonBrian1928/parakeetX) — fast
    OpenAI-compatible server built on NVIDIA Parakeet.

  Example:

  ```env
  WHISPER_TYPE=remote
  WHISPER_REMOTE_BASE_URL=http://localhost:8000/v1
  WHISPER_REMOTE_MODEL=whisper-1
  # WHISPER_REMOTE_API_KEY=   # only if your server requires one
  ```

If you are using `WHISPER_TYPE=remote`, Podly also supports OpenAI-compatible
transcription flags for diarization:

```env
WHISPER_REMOTE_DIARIZE=false
WHISPER_REMOTE_SPEAKER_EMBEDDINGS=false
```

Set `WHISPER_REMOTE_DIARIZE=true` to request speaker diarization from a
compatible remote Whisper endpoint. `WHISPER_REMOTE_SPEAKER_EMBEDDINGS=true`
adds speaker embeddings to the diarization payload and requires diarization to
be enabled. See [.env.local.example](.env.local.example) for the full set of
environment variables.

### Optional: INA audio segmentation (better ad boundaries)

The transcript only contains words — it can't "hear" the music stings, jingles,
and silence gaps that almost always wrap a podcast ad. INA
([inaSpeechSegmenter](https://github.com/ina-foss/inaSpeechSegmenter)) is an
audio classifier that tags time ranges as `speech`, `music`, `silence`, or
`noenergy`. Enabling it gives Podly that extra audio layer, which it uses to:

- **Feed audio cues to the LLM** — non-speech regions are injected into the
  transcript sent to the model (e.g. `[122.4] [MUSIC] (5.2s)`), a strong hint
  that an ad break starts or ends there.
- **Clean up the cut boundaries** — adjacent ad windows separated only by
  music/silence are bridged into one block, and ads at the start/end of an
  episode are extended to swallow the leading/trailing music sting. The result
  is fewer half-second jingles or dead-air gaps left behind after a cut.

The trade-off is that it runs a separate service and adds a full audio-analysis
pass per episode, so it is off by default.

```env
INA_ENABLED=false
INA_BASE_URL=http://localhost:8001
INA_TIMEOUT_SEC=3600
```

Set `INA_ENABLED=true` and point `INA_BASE_URL` at a service that exposes
`POST /segment`. For a ready-made local server, run
[InaFastAPI](https://github.com/MaroonBrian1928/InaFastAPI), which wraps
inaSpeechSegmenter behind that endpoint. INA analysis is best-effort:
processing still completes if the INA service is unavailable, but the extra
audio segment metadata (and the boundary cleanup above) will be missing. This is
separate from remote Whisper speaker diarization, which continues to use the
`WHISPER_REMOTE_*` flags above.

## Optional UI Flags

These environment variables let you hide specific UI surfaces without changing
the rest of the application behavior:

```env
PODLY_HIDE_DISCORD_INTEGRATION=false
PODLY_HIDE_REPORT_ISSUE_BUTTON=false
```

- `PODLY_HIDE_DISCORD_INTEGRATION=true` hides the Discord SSO/config integration
  UI, including the login button and the admin Discord config tab.
- `PODLY_HIDE_REPORT_ISSUE_BUTTON=true` hides the `Report issue` button from the
  desktop nav and mobile menu.

## Stripe Billing (Optional)

The admin cost dashboard can show Stripe subscription revenue alongside
compute cost (the `subscription_amount_cents` column). This is opt-in:

```env
PODLY_STRIPE_BILLING_ENABLED=false
STRIPE_SECRET_KEY=
```

- Default off. When off, Podly never imports the `stripe` SDK into the
  long-lived Flask/writer processes — saves several MB of RAM for
  deployments that don't track revenue.
- Set `PODLY_STRIPE_BILLING_ENABLED=true` and provide `STRIPE_SECRET_KEY`
  to enable the revenue-vs-cost view. Subscription amounts are cached
  in-process for 1 hour to limit Stripe API calls.

## Rust Sidecar

Several read-heavy and audio-heavy paths run in a short-lived Rust binary
(`podly_tools`) instead of the long-lived Python process. The sidecar reads
SQLite directly and returns the same JSON envelopes as the Python routes,
keeping large transient allocations out of the Flask heap. **These paths are
enabled by default** — the Docker image ships the binary and you don't need to
configure anything. On any sidecar error Podly silently falls back to the
Python implementation (look for `falling back to Python` in
`src/instance/logs/app.log`).

You only need these flags to **opt out** of a specific path (for debugging or
parity checks). Set any of them to `false` to force the Python implementation:

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
`/api/admin/costs/calls` off the Flask heap. Python still pre-resolves
LiteLLM token prices and passes them to the sidecar, and it enriches the
response with Stripe revenue afterwards if `PODLY_STRIPE_BILLING_ENABLED`
is on.

### Cost Breakdown
*Monthly cost breakdown for 5 podcasts*

| Cost    | Hosting  | Transcription | LLM    |
|---------|----------|---------------|--------|
| **$5**  | local    | remote        | remote |
| **$10** | public (railway)  | remote        | remote |


## Contributing

See [contributing guide](docs/contributors.md) for local setup & contribution instructions.
