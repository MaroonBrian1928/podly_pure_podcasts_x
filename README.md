<p align="center">
  <img width="50%" src="src/app/static/images/logos/logo_with_text.png" alt="Podly" />
</p>

<p align="center">Ad-free versions of the podcasts you already listen to.</p>

<p align="center">
  <a href="https://discord.gg/FRB98GtF6N"><img src="https://img.shields.io/badge/discord-join-blue.svg?logo=discord&logoColor=white" alt="Discord"></a>
</p>

Podly is a self-hosted server that removes ads from podcasts. You give it a
podcast's RSS feed, and it gives you back a new feed you can add to your podcast
app. When your app downloads an episode, Podly transcribes it, has an LLM find
the sponsor reads, and cuts them out.

<img width="100%" src="docs/images/screenshot.png" alt="Podly web interface showing a podcast and its episodes" />

## What you need

- [Docker](https://docs.docker.com/get-docker/) with Docker Compose.
- A [Groq](https://console.groq.com/) API key for transcription. Groq has a
  free tier. You can run your own transcription server instead; see
  [configuration](docs/configuration.md#transcription-backend).
- An API key for an LLM to find the ads. OpenAI, Anthropic, Gemini, Groq and
  local models all work.

## Quick start

```bash
git clone https://github.com/MaroonBrian1928/podly_pure_podcasts_x.git podly
cd podly
cp .env.local.example .env.local
```

Open `.env.local` and set these values:

```env
GROQ_API_KEY=your-groq-key

LLM_API_KEY=your-llm-key
LLM_MODEL=anthropic/claude-3.5-sonnet   # or gpt-4o, gemini/gemini-2.0-flash, ...

PODLY_ADMIN_USERNAME=admin
PODLY_ADMIN_PASSWORD=pick-a-real-password
PODLY_SECRET_KEY=paste-a-random-string-here
```

To use Groq for the ads too, put your Groq key in `LLM_API_KEY` and set
`LLM_MODEL=groq/openai/gpt-oss-120b`. To generate a secret key, run
`python3 -c "import secrets; print(secrets.token_hex(32))"`.

Start Podly:

```bash
docker compose up -d --build
```

The first build takes a few minutes. When it's done, open
<http://localhost:5001> and sign in with the username and password you set.

## Add your first podcast

1. Click **Add Feed** and search for a podcast, or paste its RSS URL.
2. Open the podcast and click the RSS button to copy its Podly feed URL.
3. In your podcast app, add a show by URL and paste that link. Apple Podcasts,
   Overcast, Pocket Casts, AntennaPod and most other apps support this.
   Spotify does not.

Podly processes new episodes in the background as they come out, which takes a
few minutes each. Your app can download an episode once Podly has finished it.

## Using Podly away from home

Your podcast app has to reach Podly to download episodes. On your home network,
`http://<your-server-ip>:5001` works. To listen anywhere else, put Podly behind a
public URL (a reverse proxy, a tunnel, or [Railway](docs/how_to_run_railway.md)).

Pocket Casts downloads feeds from its own servers, so it needs that public URL
even at home.

Keep the login turned on when Podly is public. The feed links Podly copies for
you carry their own access token, so your podcast app never sees your password.

## Updating

```bash
git pull
docker compose up -d --build
```

Your feeds, episodes and settings live in `src/instance/` and survive updates.

## More

- [Beginner's guide](docs/how_to_run_beginners.md): installing Docker,
  getting API keys, troubleshooting, and having an AI assistant do the setup.
- [Configuration](docs/configuration.md): self-hosted transcription, better ad
  boundaries with audio analysis, the Rust sidecar, and other settings.
- [Contributing](docs/contributors.md): running Podly for development.
- Questions and help: [Discord](https://discord.gg/FRB98GtF6N) or
  [GitHub issues](https://github.com/MaroonBrian1928/podly_pure_podcasts_x/issues).

## License

MIT. See [LICENCE](LICENCE).
