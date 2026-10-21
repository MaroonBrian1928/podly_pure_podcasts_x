# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
A self-hosting admin running Podly on their own server, plus a small group of people they invite. They add podcast feeds, check that episodes processed correctly, and copy the ad-free RSS link into their podcast app. They often do this from a phone.

## Product Purpose
Ad-block for podcasts. Podly transcribes each episode, asks an LLM to find the ads, cuts them out, and serves an ad-free RSS feed. It works when people subscribe once in their podcast app and get clean episodes without thinking about it. The web UI is for setting that up, checking on it and fixing it when needed.

## Positioning
A performance-focused fork of upstream Podly Pure Podcasts. Three things set it apart:
- **Speed and footprint:** database writes and the busiest read paths run in Rust. Idle memory is about a fifth of upstream's, and feeds are served hundreds of times faster.
- **Accurate, explained cuts:** with boundary refinement on, cuts land on exact word boundaries. The processing stats match the cuts actually made, so users can see what was removed and why.
- **More detection signals:** optional speaker diarization and INA music/silence detection give the LLM more cues for finding ads. Profanity bleeping can be turned on per feed.

## Operating Context
- Usually runs with Docker Compose on a homelab. Access is behind admin login (`REQUIRE_AUTH=true`), with users invited by the admin.
- Feeds are consumed in third-party podcast apps such as PocketCasts through per-user feed links.
- People open the UI on a phone as often as on a desktop, usually to add a feed, copy a link or check a stuck episode.

## Capabilities and Constraints
- Main surfaces: feed list and feed detail with episodes, playback, download and reprocess; the jobs/processing queue; per-episode processing stats and stage logs; config (LLM, transcription, detection, UI flags); diagnostics; login.
- Optional: Stripe billing (`PODLY_STRIPE_BILLING_ENABLED`, off by default) and an admin cost dashboard.
- The landing page exists in code but is disabled. It is out of scope for design work.
- The frontend is React, Vite and Tailwind. Shared data shapes must stay in sync across the frontend, the Python backend and the Rust sidecar.

## Brand Commitments
- The product name is Podly, and the existing logo assets are in `src/app/static/images/logos/`.
- The README's voice is plain, factual and benchmark-backed, with no hype.

## Evidence on Hand
- Benchmarks against upstream: `docs/benchmarks.md`, with a summary table in `README.md`.
- App screenshot: `docs/images/screenshot.png`.
- There are no testimonials, user counts or hosted-service claims. Do not invent them.

## Product Principles
1. Set-and-forget: the UI's main job is to get a feed working and then stay out of the way.
2. Show the work: what was cut, why and how confidently should be visible and accurate, never approximated.
3. Phone-ready: the core tasks (add a feed, copy a link, check status, reprocess) must work well on a phone.
4. Earn the claims: performance and accuracy statements must be backed by real measurements.
