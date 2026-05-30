# Contributor Guide

## Quick Start (Docker - recommended for local setup)

1. Make the script executable and run:

```bash
chmod +x run_podly_docker.sh
./run_podly_docker.sh --production # foreground with logs
./run_podly_docker.sh --production -d # or detached
```

This uses the single Podly Docker image. Transcription always runs outside the
container — there is no embedded Whisper — so the image stays lightweight (no GPU
or CUDA needed for Podly itself). See [Transcription Options](#transcription-options).

After the server starts:

- Open `http://localhost:5001` in your browser
- Configure settings at `http://localhost:5001/config`
- Add podcast feeds and start processing

## Usage

Once the server is running:

1. Open `http://localhost:5001`
2. Configure settings in the Config page at `http://localhost:5001/config`
3. Add podcast RSS feeds through the web interface
4. Open your podcast app and subscribe to the Podly endpoint (e.g., `http://localhost:5001/feed/1`)
5. Select an episode and download

## Transcription Options

Podly supports multiple options for audio transcription:

1. **OpenAI-compatible remote Whisper**
   - Configure `WHISPER_TYPE=remote` and `WHISPER_REMOTE_BASE_URL`
   - Works with any OpenAI-compatible transcription server. For a self-hosted
     backend we recommend [WhisperX API server](https://github.com/Nyralei/whisperx-api-server)
     or [ParakeetX](https://github.com/MaroonBrian1928/parakeetX).
2. **Groq Hosted Whisper**
   - Configure `WHISPER_TYPE=groq` with a `GROQ_API_KEY`
   - Fast and cost-effective; billed by Groq based on usage

Select your preferred method in the Config page (`/config`).

## Running Podly with Docker

Podly runs from a single standard image via `run_podly_docker.sh`, the one entry
point for both local builds and the published image.

### Run Modes

```bash
./run_podly_docker.sh --dev          # build local image and start for local changes
./run_podly_docker.sh --production   # use published images (default)
./run_podly_docker.sh --dev --build  # build local image only
./run_podly_docker.sh --test-build   # test build
./run_podly_docker.sh -d             # detached
```

Common flags:

- `--production` — use the pre-built published image (default)
- `--dev` — build a local image with your code changes
- `--build`, `--test-build`, `--branch=BRANCH` — Docker build helpers
- `-d/--detach` (or `-b/--background`) — run in the background
- `-h/--help` — show all options

**Development mode** (`--dev`) uses local Docker builds, mounts the instance
directory, and rebuilds after code changes — good for development, testing, and
customization. **Production mode** (`--production`, the default) pulls pre-built
images from the GitHub Container Registry with the same volume mounts — good for
deployment and quick, consistent setups.

### Application Port & Frontend

- The app runs on port 5001 (configurable via the web UI at `/config`) and serves
  both the web interface and the API.
- The frontend is built to static assets and served by the Flask backend, so
  there is no separate frontend server. After changing frontend code, restart
  `./run_podly_docker.sh` to rebuild the assets.

### Docker Environment Configuration

**Environment Variables**:

- `PUID`/`PGID`: User/group IDs for file permissions (automatically set by run script)
- `CORS_ORIGINS`: Backend CORS configuration (defaults to accept requests from any origin)

**Env Var Precedence for Config Settings**:

Environment variables for Podly config settings (e.g. `LLM_MODEL`, `WHISPER_TYPE`, `GROQ_API_KEY`) always take precedence over values stored in the database or set through the web UI. This follows the [12-factor app](https://12factor.net/config) principle:

- At runtime, env vars are overlaid on top of database values — the database is never mutated by env vars.
- The API strips env-controlled fields from incoming config updates to prevent the UI from overwriting operator intent.
- In the web UI, env-controlled fields appear as read-only with a visual indicator.
- To give control back to the UI, simply remove the env var and restart the container.

See `.env.local.example` for all available environment variables.

## Remote Setup

Podly automatically detects reverse proxies and generates appropriate URLs via request headers.

### Reverse Proxy Examples

**Nginx:**

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
    }
}
```

**Traefik (docker-compose.yml):**

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.podly.rule=Host(`your-domain.com`)"
  - "traefik.http.routers.podly.tls.certresolver=letsencrypt"
  - "traefik.http.services.podly.loadbalancer.server.port=5001"
```

> **Note**: Most modern reverse proxies automatically set the required headers. No manual configuration is needed in most cases.

### Built-in Authentication

Podly ships with built-in authentication so you can secure feeds without relying on a reverse proxy.

- Set `REQUIRE_AUTH=true` to enable protection. The code default is `false` (preserving existing behaviour), but the shipped `.env.local.example` sets it to `true` since auth is strongly recommended for any exposed deployment.
- When auth is enabled, Podly fails fast on startup unless `PODLY_ADMIN_PASSWORD` is supplied and meets the strength policy (≥12 characters with upper, lower, digit, symbol). Override the initial username with `PODLY_ADMIN_USERNAME` (default `podly_admin`).
- Provide a long, random `PODLY_SECRET_KEY` so Flask sessions remain valid across restarts. If you omit it, the app generates a new key on each boot and all users are signed out.
- On first boot with an empty database, Podly seeds an admin user using the supplied credentials. **If you are enabling auth on an existing install, start from a fresh data volume.**
- After signing in, open the Config page to rotate your password and manage additional users. When you change the admin password, update the corresponding environment variable in your deployment platform so restarts continue to succeed.
- Use the "Copy protected feed" button to generate feed-specific access tokens that are embedded in subscription URLs so podcast clients can authenticate without your primary password. Rate limiting is still applied to repeated authentication failures.

## Ubuntu Service

Add a service file to /etc/systemd/system/podly.service

```
[Unit]
Description=Podly Podcast Service
After=network.target

[Service]
User=yourusername
Group=yourusername
WorkingDirectory=/path/to/your/app
ExecStart=/usr/bin/env uv run python src/main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

enable the service

```
sudo systemctl daemon-reload
sudo systemctl enable podly.service
```

## FAQ

Q: What does "whitelisted" mean in the UI?

A: It means an episode is eligible for download and ad removal. By default, new episodes are automatically whitelisted (`automatically_whitelist_new_episodes`), and only a limited number of old episodes are auto-whitelisted (`number_of_episodes_to_whitelist_from_archive_of_new_feed`). Adjust these settings in the Config page (/config).

Q: How can I run transcription outside the Podly container?

A: Run an OpenAI-compatible transcription server such as
[WhisperX API server](https://github.com/Nyralei/whisperx-api-server),
[ParakeetX](https://github.com/MaroonBrian1928/parakeetX), or a hosted provider,
then set `WHISPER_TYPE=remote` and `WHISPER_REMOTE_BASE_URL` to that service.

## Contributing

We welcome contributions to Podly! Here's how you can help:

### Development Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/yourusername/podly.git
   ```
3. Create a new branch for your feature:
   ```bash
   git checkout -b feature/your-feature-name
   ```
4. Create a pull request

### Running Tests

Before submitting a pull request, you can run the same tests that run in CI:

To prep your local uv environment to run this script, you will need to first run:

```bash
uv sync --extra dev
```

Then, to run the checks,

```bash
scripts/ci.sh
```

This will run all the necessary checks including:

- Code formatting and linting with ruff
- Type checking with ty
- Unit tests

### Database Migrations

The database auto-migrates on launch.

To add a migration after a data model change, use the helper script. It points
Flask at the repo-local instance directory, generates the migration, and offers
to apply it:

```bash
./scripts/create_migration.sh "[change description]"
```

On next launch, the database updates automatically.

### Releases and Commit Messages

This repo uses `semantic-release` to automate versioning and GitHub releases. It relies on
Conventional Commits to determine the next version.

For pull requests, include **at least one** commit that follows the Conventional Commit format:

- `feat: add new episode filter`
- `fix(api): handle empty feed`
- `chore: update dependencies`

If no Conventional Commit is present, the release pipeline will have nothing to publish.

### Keep Pull Requests Focused

Please keep each pull request scoped to a **single, self-contained feature or
fix**. Focused PRs are far easier to review, test, and reason about, so they get
merged faster.

Avoid wide-sweeping PRs that bundle many unrelated changes at once — a large
change that adds several features, refactors, and fixes together is hard to
review and **unlikely to be accepted**. If your work spans multiple concerns,
split it into a series of smaller PRs (and open an issue first if you want to
discuss the overall direction).

A good rule of thumb: a reviewer should be able to summarize what your PR does in
a single sentence.

### Pull Request Process

1. Ensure all tests pass locally
2. Update the documentation if needed
3. Keep the change focused and self-contained (see above)
4. Create a Pull Request with a clear description of the changes
5. Link any related issues

### Code Style

- We use ruff for code formatting
- Type hints are required for all new code
- Follow existing patterns in the codebase
