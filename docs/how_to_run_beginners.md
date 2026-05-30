# How To Run: Ultimate Beginner's Guide

This guide will walk you through setting up Podly from scratch using Docker. Podly creates ad-free RSS feeds for podcasts by automatically detecting and removing advertisement segments.

## Highly Recommended: Let an AI agent set this up for you

The easiest way to get Podly running is to let an AI coding assistant do it
alongside you — it can run the commands, read the output, and fix problems as
they come up. Any of these work:

- **Agentic command-line tools** — [Claude Code](https://www.anthropic.com/claude-code)
  (Anthropic) or [Gemini CLI](https://github.com/google-gemini/gemini-cli)
  (Google). Install one, then run it in a terminal inside the project folder.
- **AI-powered IDEs** — [Cursor](https://www.cursor.com/) or
  [Windsurf](https://windsurf.com/). Open the project, open the AI chat panel,
  and turn on "Agent" mode if it's available.

Most of these have a free tier to get started, and many let you bring your own
LLM API key (for example, [API keys in Cursor](https://docs.cursor.com/settings/api-keys)).

Whichever you choose, make sure agent / command-execution mode is enabled so the
assistant can run commands, view their output, and debug or take corrective
steps for you. Then paste one of the prompts below into the chat.

If you don't have the repo downloaded:

```
Help me install docker and run Podly https://github.com/podly-pure-podcasts/podly_pure_podcasts
After the project is cloned, help me:
- install docker & docker compose
- run `./run_podly_docker.sh --production -d`
- configure the app via the web UI at http://localhost:5001/config
Be sure to check if a dependency is already installed before downloading.
We recommend Docker because installing ffmpeg and the app runtime can be difficult.
For transcription, configure Groq (easiest) or a self-hosted OpenAI-compatible
server like WhisperX API server or ParakeetX in the web UI.
Podly works with many different LLMs, it does not require an OpenAI key.
Check your work by retrieving the index page from localhost:5001 at the end.
```

If you do have the repo pulled, open this file and prompt:

```
Review this project, follow this guide and start Podly on my computer.
Briefly, help me:
- install docker & docker compose
- run `./run_podly_docker.sh --production -d`
- configure the app via the web UI at http://localhost:5001/config
Be sure to check if a dependency is already installed before downloading.
We recommend docker because installing ffmpeg and the app runtime can be difficult.
For transcription, configure Groq (easiest) or a self-hosted OpenAI-compatible
server like WhisperX API server or ParakeetX in the web UI.
Podly works with many different LLMs; it does not need to work with OpenAI.
Check your work by retrieving the index page from localhost:5001 at the end.
```

## Prerequisites

### Install Docker and Docker Compose

#### On Windows:

1. Download and install [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/)
2. During installation, make sure "Use WSL 2 instead of Hyper-V" is checked
3. Restart your computer when prompted
4. Open Docker Desktop and wait for it to start completely

#### On macOS:

1. Download and install [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/)
2. Drag Docker to your Applications folder
3. Launch Docker Desktop from Applications
4. Follow the setup assistant

#### On Linux (Ubuntu/Debian):

```bash
# Update package index
sudo apt update

# Install Docker
sudo apt install docker.io docker-compose-v2

# Add your user to the docker group
sudo usermod -aG docker $USER

# Log out and log back in for group changes to take effect
```

#### Verify Installation:

Open a terminal/command prompt and run:

```bash
docker --version
docker compose version
```

You should see version information for both commands.

### 2. Get API Keys for Transcription and the LLM

Podly is provider-neutral. You need two things, and they can come from the same
provider or different ones:

- **Transcription:** the easiest option is a [Groq](https://console.groq.com/)
  API key (free tier available). Alternatively, self-host an OpenAI-compatible
  transcription server such as
  [WhisperX API server](https://github.com/Nyralei/whisperx-api-server) or
  [ParakeetX](https://github.com/MaroonBrian1928/parakeetX) and use no key at all.
- **Ad detection (LLM):** any of the major providers work — OpenAI, Anthropic
  (Claude), Google (Gemini), Groq, or a local/self-hosted model. Pick one,
  create an API key in its dashboard, and you're set. Podly does **not** require
  an OpenAI key.

To create a key, sign in to your chosen provider, find its "API Keys" page,
create a new key, and copy it somewhere safe — most providers only show it once.

> **Note**: Hosted API usage is paid per-use. Set up billing and usage limits in
> your provider's dashboard to avoid unexpected charges. Groq and self-hosted
> transcription keep costs low.

## Setup Podly

### Download the Project

```bash
git clone https://github.com/podly-pure-podcasts/podly_pure_podcasts.git
cd podly_pure_podcasts
```

## Running Podly

### Run the Application via Docker

```bash
chmod +x run_podly_docker.sh
./run_podly_docker.sh --production      # foreground, published image
./run_podly_docker.sh --production -d   # detached, published image
./run_podly_docker.sh --dev --build     # build local image after code changes
```

### Recommended: Enable Authentication

> ⚠️ **Strongly recommended, especially for any internet-exposed deployment.**
> Without authentication, anyone who can reach your Podly URL can read and
> control your feeds. The example config (`.env.local.example`) ships with
> `REQUIRE_AUTH=true` for this reason — keep it on and set your own password.

The Docker image reads environment variables from `.env.local` files or your shell. To require login:

1. Export the variables before running Podly, or add them to `config/.env.local`:

```bash
export REQUIRE_AUTH=true
export PODLY_ADMIN_USERNAME='podly_admin'
export PODLY_ADMIN_PASSWORD='SuperSecurePass!2024'      # use your own strong password
export PODLY_SECRET_KEY='replace-with-a-strong-64-char-secret'
```

   Generate a strong secret key with:
   `python -c "import secrets; print(secrets.token_hex(32))"`

2. Start Podly as usual. On first boot with auth enabled and an empty database, the admin account is created automatically. If you are turning auth on for an existing volume, clear the `sqlite3.db` file so the bootstrap can succeed.

3. Sign in at `http://localhost:5001`, then visit the Config page to change your password, add users, and copy RSS URLs with the "Copy protected feed" button. Podly generates feed-specific access tokens and embeds them in the link so podcast players can subscribe without exposing your main password. Remember to update your environment variables whenever you rotate the admin password.

### Subscribing in a podcast app (public feeds & PocketCasts)

Some podcast apps fetch your RSS feed from **their own servers** rather than
your phone, so the feed URL must be reachable from the public internet — a
`localhost` or LAN-only address won't work. **Pocket Casts is the most common
example**;
To use Podly with these apps:

1. Host Podly somewhere publicly reachable (for example, the
   [Railway deployment](how_to_run_railway.md), or your own server with a public
   URL / reverse proxy).
2. Keep authentication enabled (above) and use the **"Copy protected feed"**
   button on the Config page. The copied URL contains a per-feed access token,
   so the app can fetch the feed over the public internet **without** exposing
   your admin login. This gives you a publicly *reachable* feed that is still
   *protected* by a secret token.

Apps that fetch the feed directly on-device (e.g. some self-hosting-friendly
players) can use a LAN address, but for Pocket Casts and similar a public,
token-protected URL is the way to go.

### First Run

1. Docker will download and build the necessary image (this may take 5-15 minutes)
2. Look for "Running on http://0.0.0.0:5001"
3. Open your browser to `http://localhost:5001`
4. Configure settings at `http://localhost:5001/config`
   - Alternatively, set secrets via Docker env file `.env.local` in the project root and restart the container. See .env.local.example

## Advanced Options

```bash
# Just build the container without running
./run_podly_docker.sh --dev --build

# Test build from scratch (useful for troubleshooting)
./run_podly_docker.sh --test-build
```

## Using Podly

### Adding Your First Podcast

1. In the web interface, look for an "Add Podcast" or similar button
2. Paste the RSS feed URL of your podcast
3. Podly will start processing new episodes automatically
4. Processed episodes will have advertisements removed

### Getting Your Ad-Free RSS Feed

1. After adding a podcast, Podly will generate a new RSS feed URL
2. Use this new URL in your podcast app instead of the original
3. Your podcast app will now download ad-free versions!

## Troubleshooting

### "Docker command not found"

- Make sure Docker Desktop is running
- On Windows, restart your terminal after installing Docker
- On Linux, make sure you logged out and back in after adding yourself to the docker group

### Cannot connect to the Docker daemon. Is the docker daemon running?

- If using docker desktop, open up the app, otherwise start the daemon

### "Permission denied" errors

- On macOS/Linux, make sure the script is executable: `chmod +x run_podly_docker.sh`
- On Windows, try running Command Prompt as Administrator

### API / LLM errors

- Double-check your API key in the Config page at `/config`
- Make sure billing is set up in your provider's account (OpenAI, Anthropic, Groq, etc.)
- Check your usage limits or rate limits haven't been exceeded

### Port 5001 already in use

- Another application is using port 5001
- **Docker users**: Either stop that application or modify the port in `compose.yml`
- **Native users**: Change the port in the Config page under App settings
- To kill processes on that port run `lsof -i :5001 | grep LISTEN | awk '{print $2}' | xargs kill -9`

### Out of memory errors

- Close other applications to free up RAM
- Use a remote transcription service instead of running transcription on the same machine

## Stopping Podly

To stop the application:

If you have launched it in the foreground by omitting the `-d` parameter:
1. In the terminal where Podly is running, press `Ctrl+C`
2. Wait for the container to stop gracefully

If you have launched it in the background using the `-d` parameter:
1. In the terminal where Podly is running, execute `docker compose down`
2. Wait for the container to stop gracefully

In both cases this output should appear to indicate that it has stopped:

```sh
[+] Running 2/2
 ✔ Container podly-pure-podcasts        Removed
 ✔ Network podly-pure-podcasts-network  Removed
```

## Upgrading Podly

To upgrade the application while you are in the terminal where it is running:
1. [Stop it](#stopping-podly)
2. Execute `git pull`
3. [Run it again](#running-podly)

## Getting Help

If you encounter issues ask in our discord, we're friendly!

https://discord.gg/FRB98GtF6N

## What's Next?

Once you have Podly running:

- Explore the web interface to add more podcasts
- Configure settings in the Config page
- Consider setting up automatic background processing
- Enjoy your ad-free podcasts!
