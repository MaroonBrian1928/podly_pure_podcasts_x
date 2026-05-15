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

Podly uses Whisper and Chat GPT to remove ads from podcasts.

<img width="100%" src="docs/images/screenshot.png" />

## How To Run

You have a few options to get started:

- [![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/podly?referralCode=NMdeg5&utm_medium=integration&utm_source=template&utm_campaign=generic)
   - quick and easy setup in the cloud, follow our [Railway deployment guide](docs/how_to_run_railway.md). 
   - Use this if you want to share your Podly server with others.
- **Run Locally**: 
   - For local development and customization, 
   - see our [beginner's guide for running locally](docs/how_to_run_beginners.md). 
   - Use this for the most cost-optimal & private setup.
- **[Join The Preview Server](https://podly.up.railway.app/)**: 
   - pay what you want (limited sign ups available)


## How it works:

- You request an episode
- Podly downloads the requested episode
- Whisper transcribes the episode
- LLM labels ad segments
- Podly removes the ad segments
- Podly delivers the ad-free version of the podcast to you

## Whisper Configuration

Podly does not run embedded local Whisper inside the app container. Use Groq or
set `WHISPER_TYPE=remote` with `WHISPER_REMOTE_BASE_URL` pointed at an
OpenAI-compatible transcription service such as `whisper-x-fastapi`,
`speaches.ai`, or another compatible endpoint.

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

Podly can also optionally call a separate INA-compatible audio segmenter to
detect non-speech regions such as music, noise, and silence-like gaps:

```env
INA_ENABLED=false
INA_BASE_URL=http://localhost:8001
INA_TIMEOUT_SEC=3600
```

Set `INA_ENABLED=true` and point `INA_BASE_URL` at a service that exposes
`POST /segment`. INA analysis is best-effort: processing still completes if the
INA service is unavailable, but the extra audio segment metadata will be
missing from stats/debug views. This is separate from remote Whisper
speaker diarization, which continues to use the `WHISPER_REMOTE_*` flags above.

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

### Cost Breakdown
*Monthly cost breakdown for 5 podcasts*

| Cost    | Hosting  | Transcription | LLM    |
|---------|----------|---------------|--------|
| **$5**  | local    | remote        | remote |
| **$10** | public (railway)  | remote        | remote |
| **Pay What You Want** | [preview server](https://podly.up.railway.app/)    | n/a         | n/a  |
| **$5.99/mo** | https://zeroads.ai/ | production fork of podly | |


## Contributing

See [contributing guide](docs/contributors.md) for local setup & contribution instructions.
