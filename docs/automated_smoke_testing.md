# Automated Smoke Testing

Two Playwright scripts in `frontend/smoke/` drive a real Podly instance in a browser and record what they see. Use them to check a change end to end before opening a pull request, and to capture screenshots and video for it.

- `walkthrough.mjs` signs in (a wrong password first), tours Settings, adds a feed, processes its newest episode, inspects every Stats tab, opens Jobs, and checks the phone layout.
- `enable-and-process.mjs` enables the feed's second episode by hand, confirms processing, waits for it, and opens its stats. Run it after `walkthrough.mjs`.

Each run writes numbered screenshots, a video and a log to the output directory. A run fails (exit code 1) on a failed step, a page error or a 5xx response. 4xx responses are logged but don't fail the run, because some are expected: the session check before sign-in, the wrong password, and the Settings connection probes when a provider is unreachable or fake.

The scripts add a feed and process episodes, so run them against a fresh, disposable instance, never one you use.

## Two modes

- **Keyless (default).** `DEVELOPER_MODE=true` with a test feed (`http://test-feed/<id>`). Podly creates a five-episode feed without fetching anything, and processing copies a bundled sample MP3 instead of downloading, transcribing and classifying. Free and fast, and it covers every screen, but the stats are empty: no transcript, model calls or ad breaks.
- **Real providers.** A real feed with your transcription and LLM settings. Use it when a change touches transcripts, ad detection or the stats they feed. One run costs a few cents.

## 1. Build an image

From the repository root, build the branch you want to test. The lite build skips local Whisper, which neither mode needs:

```bash
docker build --build-arg LITE_BUILD=true -t podly:smoke .
```

## 2. Write an env file

Create `smoke.env` in the repository root. It is in `.gitignore`; keep it readable only by you.

**Keyless:**

```bash
umask 077
{
  echo "DEVELOPER_MODE=true"
  echo "WHISPER_TYPE=test"
  # Processing is refused without an LLM key; test feeds never call the LLM.
  echo "LLM_API_KEY=smoke-placeholder"
  echo "REQUIRE_AUTH=true"
  echo "PODLY_ADMIN_USERNAME=admin"
  echo "PODLY_ADMIN_PASSWORD=$(openssl rand -hex 16)"
  echo "PODLY_SECRET_KEY=$(openssl rand -hex 32)"
} > smoke.env
```

**Real providers:** copy the provider settings from your `.env.local` instead of the first three lines:

```bash
umask 077
{
  grep -E '^(LLM_API_KEY|LLM_MODEL|OPENAI_BASE_URL|WHISPER_TYPE|WHISPER_REMOTE_API_KEY|WHISPER_REMOTE_BASE_URL|WHISPER_REMOTE_MODEL|GROQ_API_KEY|GROQ_WHISPER_MODEL|GROQ_MAX_RETRIES)=' .env.local
  echo "REQUIRE_AUTH=true"
  echo "PODLY_ADMIN_USERNAME=admin"
  echo "PODLY_ADMIN_PASSWORD=$(openssl rand -hex 16)"
  echo "PODLY_SECRET_KEY=$(openssl rand -hex 32)"
} > smoke.env
```

`LLM_MODEL` has to be a model the backend sends the right token-limit parameter for. Models listed in `model_uses_max_completion_tokens` (`src/shared/llm_utils.py`) get `max_completion_tokens`; everything else gets `max_tokens`, which newer OpenAI models reject. When that happens every LLM call fails and episodes are published without ad removal.

## 3. Start a fresh instance

Start the image with an empty instance directory, so migrations run from scratch and nothing from a real install is reused:

```bash
mkdir -p smoke-instance
docker run -d --name podly-smoke -p 5099:5001 \
  --env-file smoke.env \
  -e PUID="$(id -u)" -e PGID="$(id -g)" \
  -v "$PWD/smoke-instance:/app/src/instance" \
  podly:smoke

until curl -sf -o /dev/null http://localhost:5099/; do sleep 3; done
```

The app log is in `smoke-instance/logs/app.log`.

## 4. Run the scripts

Install the frontend dependencies and Playwright's Chromium once:

```bash
cd frontend
npm ci
npx playwright install chromium
```

Each script takes the base URL, an output directory and, optionally, the env file to read the admin credentials from (otherwise they come from `PODLY_ADMIN_USERNAME` and `PODLY_ADMIN_PASSWORD` in the environment).

**Keyless:** point the feed at a test feed:

```bash
export SMOKE_FEED_URL=http://test-feed/smoke
npm run smoke -- http://localhost:5099 ../smoke-output ../smoke.env
npm run smoke:enable -- http://localhost:5099 ../smoke-output ../smoke.env
```

**Real providers:** leave `SMOKE_FEED_URL` unset to use the default, NPR News Now, which has five-minute episodes with sponsor messages at the start and end, so each episode processes in under a minute. Set it to any RSS URL to test another feed.

## 5. Review the output

`smoke-output/` holds the screenshots in run order, `video/` and `video-manual/` recordings, and a log for each script with every step, timing and non-2xx response.

Settings fields are blurred in every screenshot and recording, because they show API keys, key previews and server addresses. Check the rest before sharing it: screenshots also show feed titles, episode text and the admin username.

## 6. Tear down

```bash
docker rm -f podly-smoke
rm -rf smoke-instance smoke-output
rm smoke.env
```
