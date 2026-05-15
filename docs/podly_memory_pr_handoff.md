# Podly Memory/Feed PR Handoff

Date written: 2026-05-08

This is a handoff summary of the conversation about reducing Podly idle memory,
merging feed-performance PRs, and re-measuring live Docker process usage.

## Current Repo State

- Repo: `/home/brianriste/git/podly_pure_podcasts`
- Branch during the work: `remove_local_whisper`
- As of writing this file, `git status --short --branch` reports a clean branch:
  `## remove_local_whisper...origin/remove_local_whisper`
- Current recent log:
  - `8acbced feat: integrate chapter data fetching and improve audio player functionality`
  - `e42cb15 Merge remote-tracking branch 'upstream/pr-209' into remove_local_whisper`
  - `d5af5f2 Merge remote-tracking branch 'upstream/pr-216' into remove_local_whisper`
  - `25a7fac Merge remote-tracking branch 'upstream/pr-218' into remove_local_whisper`
  - `0149de4 Merge remote-tracking branch 'upstream/pr-217' into remove_local_whisper`

## User Goal

The user asked whether moving the frontend/web server to Rust + Vite would reduce
memory after podcast processing was split into a separate worker. The discussion
shifted into live memory research because the running container was using roughly
`550 MiB` while apparently idle.

The main answer was: Rust would be more feasible after the worker split, but the
first concrete wins were likely in feed route behavior and avoiding repeated
heavy work from podcast-client polling. The React frontend is already Vite-built;
Flask is serving API routes, auth/session, static files, scheduler/job supervision,
feeds, and audio routes.

## Initial Architecture Findings

Current app shape observed from repo:

- `src/main.py` starts Waitress serving `create_web_app()`.
- `scripts/start_services.sh` starts:
  - writer service: `python3 -u -m app.writer`
  - web app: `python3 -u src/main.py`
- `create_web_app()` still owns Flask routes, auth/session, CORS, scheduler, DB reads,
  and jobs-manager worker thread.
- Heavy podcast processing itself is now launched as child processing workers from
  `src/app/jobs_manager.py`.
- Frontend is already a Vite React app under `frontend/`; at runtime Flask serves
  the built static assets and the API.

Conclusion from that stage:

- Moving only static frontend serving to Rust/nginx/Caddy would probably save little.
- Replacing Flask API with Rust would be a much larger lift and would touch auth,
  sessions, config, feed/audio routes, job status, billing/cost routes, CORS,
  health checks, Docker, and tests.
- Measuring real process RSS first was the better next step.

## Pre-Merge Memory Research

Initial live container snapshot before merging the feed PRs:

- Container: `516.8 MiB`
- Web process `python3 -u src/main.py`: about `294.6 MiB RSS`
- Writer process `python3 -u -m app.writer`: about `164.3 MiB RSS`

More detailed `/proc` status showed the memory was mostly anonymous heap, not file cache:

- Web:
  - `VmRSS`: `294576 kB`
  - `RssAnon`: `283588 kB`
  - `Threads`: `5`
- Writer:
  - `VmRSS`: `164336 kB`
  - `RssAnon`: `156900 kB`
  - `Threads`: `8`

Fresh-process probes inside the container showed:

- Clean `create_web_app()`: about `109 MiB RSS`
- Clean `create_writer_app()`: about `92 MiB RSS`
- Import costs:
  - `flask`: about `+29 MiB`
  - `sqlalchemy`: about `+12 MiB`
  - `flask_migrate`: about `+13 MiB`
  - `requests`: about `+5 MiB`
  - `openai`: about `+33 MiB`
  - `app.models`: about `+12 MiB`
  - `app.routes.post_routes`: about `+6 MiB`
  - `podcast_processor.podcast_processor`: about `+78 MiB`, total around `203 MiB`

Controlled route/work probes:

- `api_post_stats` added only about `9 MiB` in a fresh app process.
- Generating XML for one feed added about `33 MiB` and did not immediately drop after
  session removal.
- Generating XML for all feeds in a fresh process topped around `171 MiB`.
- `refresh_feed` for a feed added about `32 MiB`.

This made feed route/podcast-client polling a strong candidate for idle-adjacent
memory and latency bloat.

## PRs Researched And Merged

The user asked whether these PRs would help:

- <https://github.com/podly-pure-podcasts/podly_pure_podcasts/pull/217>
- <https://github.com/podly-pure-podcasts/podly_pure_podcasts/pull/218>

Later the user asked to also merge:

- <https://github.com/podly-pure-podcasts/podly_pure_podcasts/pull/209>
- <https://github.com/podly-pure-podcasts/podly_pure_podcasts/pull/216>

### PR #217

Title: `perf(feed): short-circuit unchanged feeds with ETag/Last-Modified 304s`

Purpose:

- Add `Feed.last_changed_at`.
- Emit `ETag`, `Last-Modified`, and `Cache-Control: public, max-age=60`.
- Honor `If-None-Match` and `If-Modified-Since`.
- Return `304 Not Modified` before upstream refresh/XML generation when possible.
- Use `last_changed_at` for `lastBuildDate`.

Merge notes:

- Conflict in `src/app/models.py`.
- Resolution: keep both current branch fields:
  - `enable_profanity_bleeping`
  - `confirm_whisperx_endpoint`
  and PR #217 field:
  - `last_changed_at`
- Added migration `src/migrations/versions/8a4d0c2f3e91_feed_last_changed_at.py`.
- Adjusted migration `down_revision` from old branch point `3e5eebc6b3b1` to current
  branch head at the time, `0cd8f1e2d228`, to keep Alembic single-headed.

### PR #218

Title: `perf(feed): drop synchronous refresh_feed from GET /feed/<id>`

Purpose:

- Remove blocking `refresh_feed(feed)` from `GET /feed/<id>`.
- Use scheduled refresh as the primary freshness source.
- Opportunistically trigger a background refresh with a per-feed 60-second debounce.

Merge notes:

- Conflict in `src/app/routes/feed_routes.py` because #217 also changed `get_feed`.
- Resolution combined both semantics:
  - compute cached ETag/last-modified;
  - return `304` immediately when client has current version;
  - otherwise use `_should_kickoff_async_refresh()` and `_spawn_async_refresh()`;
  - generate XML from current DB state;
  - attach cache headers.
- Test updates were needed because #217 tests expected first GET to call
  `refresh_feed` synchronously, but #218 intentionally removes that behavior.
- Final combined tests assert that the first request renders/schedules and the second
  conditional request returns `304` without regenerating XML or scheduling refresh.

### PR #216

Title: `fix(feeds): trust upstream <guid> verbatim and self-heal legacy rows`

Purpose:

- Stop replacing non-UUID upstream `<guid>` values with UUIDv5 hashes of enclosure URLs.
- Return upstream `entry.id`/`entry.guid` verbatim when present and non-empty.
- Fall back to URL hash only when no usable upstream id exists.
- Self-heal legacy rows by matching existing posts by `download_url` and updating the
  stored GUID to the upstream GUID.

Merge notes:

- Conflicts in:
  - `src/app/feeds.py`
  - `src/app/writer/actions/feeds.py`
- Resolution in `src/app/feeds.py`:
  - kept current refactored helper structure around `_build_refresh_feed_payload`;
  - added `existing_posts_by_url`;
  - when `existing_posts.get(entry.id)` misses, fallback to `find_audio_link(entry)`
    and `existing_posts_by_url.get(audio_url)`;
  - added `repaired_guid`;
  - passed `repaired_guid` into `_existing_post_refresh_payload`;
  - `_existing_post_refresh_payload(..., repaired_guid=None)` now includes `"guid"` in
    the update payload when repair is needed.
- Resolution in `src/app/writer/actions/feeds.py`:
  - kept `_apply_existing_post_updates`;
  - allowed `"guid"` in the list of writable post fields;
  - preserved #217 behavior where changes bump `feed.last_changed_at`.

### PR #209

Title: `fix: scope post guid and download_url uniqueness per feed`

Purpose:

- Remove global unique constraints from `Post.guid` and `Post.download_url`.
- Add composite unique constraints:
  - `(feed_id, guid)`
  - `(feed_id, download_url)`
- Fix `_get_most_recent_posts_per_feed` tie behavior with stable `post.id` tiebreaker.

Merge notes:

- No textual conflict.
- Added migration:
  - `src/migrations/versions/d4e7f8a9b2c1_scope_post_guid_and_download_url_per_feed.py`
- Adjusted its `down_revision` from `3e5eebc6b3b1` to `8a4d0c2f3e91` so it chains
  after #217 and keeps Alembic single-headed.
- Cleaned up #216 GUID tests to use `feedparser.FeedParserDict` instead of
  `SimpleNamespace`, so `ty` passes.

## Verification Performed

Required project CI command:

```bash
mise exec -- ./scripts/ci.sh
```

After merging #217 and #218:

- ruff format/check: clean
- ty: clean
- pytest: `403 passed, 2 skipped`

After also merging #216 and #209:

- ruff format/check: clean
- ty: clean
- pytest: `411 passed, 2 skipped`

The CI script may run formatting/autofixes. Working tree was reviewed after runs.

## Runtime After Merges

After rebuild/restart, Docker logs confirmed migrations ran:

```text
Running upgrade 0cd8f1e2d228 -> 8a4d0c2f3e91, feed last_changed_at
Running upgrade 8a4d0c2f3e91 -> d4e7f8a9b2c1, scope post guid and download_url unique constraints per feed
```

Post-merge live memory snapshot:

- Container total: about `277-281 MiB`
- Web process `python3 -u src/main.py`: about `209.6 MiB RSS`
- Writer process `python3 -u -m app.writer`: about `95.9 MiB RSS`
- Bash supervisor: about `3.2 MiB`

Detailed latest process breakdown:

| Process | RSS | Anonymous | File-backed | Threads | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| `/bin/bash ./scripts/start_services.sh` | `3.2 MiB` | tiny | tiny | 1 | supervisor |
| `python3 -u -m app.writer` | `95.9 MiB` | `76.2 MiB` | `19.7 MiB` | 6 | writer IPC/service |
| `python3 -u src/main.py` | `209.6 MiB` | `189.6 MiB` | `20.0 MiB` | 4 | Flask/Waitress web, scheduler, jobs loop |

The current total is significantly lower than the original `516.8 MiB`.

Important caveats:

- The web process high-water mark was about `491 MiB`, likely from startup/migration
  or route activity, but it returned to about `209 MiB`.
- Fresh clean `create_web_app()` baseline is still about `109.5 MiB`.
- Live web around `209 MiB` closely matches the cost of importing heavier processing
  modules (`podcast_processor.podcast_processor` fresh-process total around `203.5 MiB`).
- So web has likely loaded heavier route/processing-adjacent modules at some point, but
  current RSS is not showing obvious ongoing growth.
- An unauthenticated test request to `/feed/10` returned `401`, so it did not exercise
  the feed XML/304 path live. It only nudged container RSS by a few MiB.

## Useful Commands From The Investigation

Container total:

```bash
docker stats --no-stream podly-pure-podcasts
```

Process RSS:

```bash
docker top podly-pure-podcasts -eo pid,ppid,comm,args,rss,vsz
```

Per-process `/proc` memory:

```bash
docker exec podly-pure-podcasts sh -lc 'for d in /proc/[0-9]*; do p=${d#/proc/}; cmd=$(tr "\0" " " <$d/cmdline 2>/dev/null || true); case "$cmd" in *"python3 -u"*) echo PID=$p CMD=$cmd; cat $d/status | egrep "^(Name|VmRSS|VmHWM|VmSize|Threads|RssAnon|RssFile|RssShmem|VmData|VmStk|VmExe|VmLib):"; echo;; esac; done'
```

FD/thread counts:

```bash
docker exec podly-pure-podcasts sh -lc 'for d in /proc/[0-9]*; do p=${d#/proc/}; cmd=$(tr "\0" " " <$d/cmdline 2>/dev/null || true); case "$cmd" in *"python3 -u"*) echo PID=$p CMD=$cmd; echo fds=$(find $d/fd -maxdepth 1 -type l 2>/dev/null | wc -l); echo threads=$(ls $d/task 2>/dev/null | wc -l); echo; esac; done'
```

Recent logs:

```bash
tail -n 220 src/instance/logs/app.log
docker logs --tail 120 podly-pure-podcasts
```

Fresh baseline probe for web app:

```bash
docker exec podly-pure-podcasts sh -lc 'PYTHONPATH=/app/src /app/.venv/bin/python - <<'"'"'PY'"'"'
import gc

def rss():
    with open("/proc/self/status") as f:
        vals = {}
        for line in f:
            if line.startswith(("VmRSS:", "VmHWM:", "RssAnon:", "RssFile:", "Threads:")):
                vals[line.split(":", 1)[0]] = line.split(":", 1)[1].strip()
        return vals

def mark(name):
    gc.collect()
    print(name, rss(), flush=True)

mark("start")
import app
mark("import app")
from app import create_web_app
mark("import create_web_app")
a = create_web_app()
mark("create_web_app")
print("routes", len(a.url_map._rules))
PY'
```

Fresh import-cost probe:

```bash
docker exec podly-pure-podcasts sh -lc 'PYTHONPATH=/app/src /app/.venv/bin/python - <<'"'"'PY'"'"'
import gc
mods = [
    "flask", "sqlalchemy", "flask_migrate", "flask_apscheduler", "feedparser",
    "requests", "openai", "groq", "app.models", "app.routes.feed_routes",
    "app.routes.post_routes", "app.jobs_manager", "podcast_processor.podcast_processor",
]

def rss():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])

last = rss()
print(f"start: {last/1024:.1f} MiB")
for m in mods:
    before = rss()
    try:
        __import__(m)
    except Exception as e:
        print(f"{m}: ERROR {type(e).__name__}: {e}", flush=True)
        continue
    gc.collect()
    now = rss()
    print(f"{m}: {now/1024:.1f} MiB (+{(now-before)/1024:.1f})", flush=True)
PY'
```

## Suggested Next Steps

If continuing the memory work in a fresh conversation:

1. Re-check current `docker stats` and `docker top` first; do not assume the numbers
   above are still current.
2. Use authenticated feed URLs or feed access tokens to test the new `ETag`/`304` path
   live. The unauthenticated `/feed/10` test returned `401`.
3. Watch memory after real podcast-client polling over time. The PRs should reduce
   repeated feed-refresh/XML work, but the durable proof is a long soak.
4. If web remains around `210 MiB`, inspect which request path imports
   `podcast_processor.podcast_processor` or other heavy processing modules into the
   web process. Fresh probes suggest that import stack explains much of the remaining
   difference between clean web baseline (`~109 MiB`) and live web (`~210 MiB`).
5. The writer process is now close to its clean baseline, so further easy memory wins
   are more likely in the web process than the writer.

