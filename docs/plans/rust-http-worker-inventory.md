# Rust web and worker migration inventory

Verified against the refreshed CodeGraph index and route decorators on checkout
`6a64893d1fc3d25fd3e25be44e93685165ab8667`. Flask declares 77 method/path rows
across nine blueprints: main 5, feed 17, auth 9, Discord 5, billing 4, config 6,
costs 6, jobs 7, and posts 18. Automatic HEAD/OPTIONS and static serving are
common behavior, not extra declared route rows.

Access legend: `Public`; `Session/open` (session only when auth is configured);
`Token/session` (scoped feed token or session); `Admin/open` (`require_admin`
deliberately permits no-auth deployments); and `Auth-only` (an auth-enabled
session is always required).

## Common HTTP behavior

- Flask cookie name defaults to `podly_session`; it is HttpOnly, SameSite=Lax,
  not Secure, and permanent after login. Missing `PODLY_SECRET_KEY` generates an
  ephemeral secret.
- Public routes include `/`, static assets, auth/Discord status and login,
  landing status, and Stripe webhook. Token patterns include RSS and processed
  or original audio/download paths. Failed auth is rate-limited and may return
  `Retry-After`.
- Feed token secrets use SHA-256 and constant-time comparison, enforce
  membership/scope, and asynchronously touch token usage.
- CORS allows configured origins with credentials, Content-Type,
  Authorization, Range, and GET/POST/PUT/DELETE/OPTIONS. PATCH is absent from
  the declared CORS methods. No separate CSRF token/origin enforcement was
  found beyond SameSite and CORS.
- Existing Rust-backed reads silently fall back to Python: RSS/aggregate
  rendering and refresh planning, feed posts, post statistics, jobs/status, and
  cost views. Every benchmark must positively prove the Rust path.
- `/health` is auth-public in middleware but has no explicit route and can fall
  into SPA/static handling. The current container health check probes only `/`.

## Route inventory

### Main blueprint (5)

| Method/path | Access | Request and response/headers | Writes/background/external | Existing Rust | Port status |
| --- | --- | --- | --- | --- | --- |
| GET `/` | Public | React index, template fallback | fallback feed read | none | Not started |
| GET `/api/landing/status` | Public | auth/landing flags and user slots | DB read | none | Not started |
| GET `/<path:path>` | middleware | static or SPA; API miss 404; guarded filesystem path | file read | none | Not started |
| POST `/feed/<f_id>/toggle-whitelist-all/<val>` | Admin/open | path bool; 200 or busy 503 | toggle action T | none | Not started |
| GET `/set_whitelist/<guid>/<val>` | Session/open | path bool; React index or 404/503 | generic Post update T | none | Not started |

### Feed blueprint (17)

| Method/path | Access | Request and response/headers | Writes/background/external | Existing Rust | Port status |
| --- | --- | --- | --- | --- | --- |
| POST `/feed` | Session/open | form URL; 302, 400, or 500 | add/refresh, membership, latest whitelist; daemon enqueue; upstream RSS | optional refresh plan | Not started |
| POST `/api/feeds/<feed_id>/share-link` | Auth-only | 201 URL/token/secret/feed | token T; no route-level membership precheck | none | Not started |
| GET `/api/feeds/search?term=` | Session/open | transformed results; 400/502 | PodcastIndex HTTP timeout 10; dev mock | none | Not started |
| GET `/feed/<f_id>` | Token/session | RSS bytes, XML type, ETag, Last-Modified, Cache-Control, 304 | last-active F; bounded refresh thread, upstream RSS | optional RSS/refresh, fallback | Not started |
| DELETE `/feed/<f_id>` | token/session + admin in auth | 204 or text 500 | unlink audio/directories then cascade T | none | Not started |
| POST `/api/feeds/<f_id>/refresh` | Session/open | 202 | last-active F; unbounded daemon refresh thread; upstream/enqueue | optional refresh plan | Not started |
| PATCH `/api/feeds/<feed_id>/settings` | Admin/open | validated strategy/filter/bools; serialized feed; 400/404/500 | generic Feed update T | none | Not started |
| GET `/api/feeds/<feed_id>/subscribers` | Admin/open | subscriber identity/role/status/joined | read | none | Not started |
| POST `/api/feeds/refresh-all` | Session/open | counts | synchronous full refresh/cleanup/enqueue/upstream | optional refresh plan | Not started |
| GET `/<path:something_or_rss>` | middleware | static first, else RSS by exact URL; XML or 404 | filesystem/DB read | optional RSS renderer | Not started |
| GET `/feeds` | Session/open | membership-filtered/all feed array | read | none | Not started |
| POST `/api/feeds/<feed_id>/join` | Auth-only | feed or allowance 402 | membership T; optional latest-whitelist T | none | Not started |
| POST `/api/feeds/<feed_id>/exit` | Auth-only | serialized feed | remove membership T | none | Not started |
| POST `/api/feeds/<feed_id>/leave` | Auth-only | status/feed id | remove membership T | none | Not started |
| GET `/feed/user/<user_id>` | Token/session | aggregate RSS + validators/cache, 304 | read; owner/admin | optional aggregate renderer | Not started |
| GET `/feed/aggregate` | Token/session or open no-auth | redirect or 401 | read | none | Not started |
| POST `/api/user/aggregate-link` | Session/open no-auth | 201 aggregate URL/token/secret | token T; no-auth may create random-password admin T | none | Not started |

### Authentication blueprint (9)

| Method/path | Access | Request and response/headers | Writes/background/external | Existing Rust | Port status |
| --- | --- | --- | --- | --- | --- |
| GET `/api/auth/status` | Public | auth/landing/UI flags | config read | none | Not started |
| POST `/api/auth/login` | Public, auth enabled | username/password; user + cookie; 400/401/404/429, Retry-After | session, last-active F | none | Not started |
| POST `/api/auth/logout` | Session | 204 or 401/404 | clear session | none | Not started |
| GET `/api/auth/me` | Auth-only | user allowance/status | read | none | Not started |
| POST `/api/auth/change-password` | Auth-only | current/new; status 400/401/500 | password T | none | Not started |
| GET `/api/auth/users` | Admin/auth-enabled | users/timestamps/allowances | read | none | Not started |
| POST `/api/auth/users` | Admin/auth-enabled | username/password/role; 201/400/409 | create user T | none | Not started |
| PATCH `/api/auth/users/<username>` | Admin/auth-enabled | optional role/password/allowance | up to three T actions; partial commit possible | none | Not started |
| DELETE `/api/auth/users/<username>` | Admin/auth-enabled | status; missing/last-admin errors | delete user T | none | Not started |

### Discord blueprint (5)

| Method/path | Access | Request and response/headers | Writes/background/external | Existing Rust | Port status |
| --- | --- | --- | --- | --- | --- |
| GET `/api/auth/discord/status` | Public | enabled | settings read | none | Not started |
| GET `/api/auth/discord/config` | Admin/open | masked config/env overrides | read | none | Not started |
| PUT `/api/auth/discord/config` | Admin/open | optional settings; masked reloaded config | settings T, reload web config | none | Not started |
| GET `/api/auth/discord/login?prompt=` | Public | auth URL; OAuth state/prompt session | CSPRNG | none | Not started |
| GET `/api/auth/discord/callback` | Public | code/state/error; redirect or errors | Discord token/user/guild HTTP without explicit timeout; upsert T; login | none | Not started |

### Billing blueprint (4)

| Method/path | Access | Request and response/headers | Writes/background/external | Existing Rust | Port status |
| --- | --- | --- | --- | --- | --- |
| GET `/api/billing/summary` | Auth-only | allowance/usage/subscription/product/amount | Stripe list/retrieve; may attach billing T | none | Not started |
| POST `/api/billing/subscription` | Auth-only | amount/ids/URLs; checkout/current state | Stripe customer/subscription/price/checkout; multiple billing T | none | Not started |
| POST `/api/billing/portal-session` | Auth-only | portal URL | Stripe portal | none | Not started |
| POST `/api/billing/stripe-webhook` | Public + signature | raw body/signature; status or 400 | Stripe verify; billing T for events | none | Not started |

### Configuration blueprint (6)

| Method/path | Access | Request and response/headers | Writes/background/external | Existing Rust | Port status |
| --- | --- | --- | --- | --- | --- |
| GET `/api/config` | Admin/open | masked combined config/env overrides | read | none | Not started |
| PUT `/api/config` | Admin/open | nested JSON; payload or 400 details | combined-config T (multi-commit), web hydration/reset/scheduler | none | Not started |
| POST `/api/config/test-notification` | Admin/open | notification URLs; result | sends real provider test | none | Not started |
| POST `/api/config/test-llm` | Admin/open | model/key/base/timeout; probe result | synchronous one-token LiteLLM call | none | Not started |
| POST `/api/config/test-whisper` | Admin/open | Whisper config; probe result | OpenAI/Groq models-list network | none | Not started |
| GET `/api/config/api_configured_check` | Admin/open | configured bool | read plus runtime hydration | none | Not started |

### Costs/admin blueprint (6)

| Method/path | Access | Request and response/headers | Writes/background/external | Existing Rust | Port status |
| --- | --- | --- | --- | --- | --- |
| GET `/api/admin/costs?year&month` | Admin/open | aggregates; invalid date 400 | Stripe pricing cache/helper | optional Rust aggregate + enrichment | Not started |
| GET `/api/admin/costs/calls?page&per_page` | Admin/open | paged calls/tokens/costs | disposable pricing helper | optional Rust aggregate | Not started |
| POST `/api/admin/costs/backfill-estimated-cost` | Admin/open | apply/positive limit; report | pricing; ModelCall update F, current updated count stays zero | none | Not started |
| POST `/api/admin/costs/backfill-token-usage` | Admin/open | apply/limit; report | tokenizer; ModelCall update T | optional Rust token counting | Not started |
| POST `/api/admin/costs/cleanup/cancelled-feeds` | Admin/open | admitted feed ids | cascade F; response precedes commit | none | Not started |
| POST `/api/admin/costs/cleanup/orphan-feeds` | Admin/open | admitted feed ids | cascade F; response precedes commit | none | Not started |

### Jobs blueprint (7)

| Method/path | Access | Request and response/headers | Writes/background/external | Existing Rust | Port status |
| --- | --- | --- | --- | --- | --- |
| GET `/api/jobs/active?limit=` | Session/open | active jobs | singleton fallback can start worker thread | optional Rust query/fallback | Not started |
| GET `/api/jobs/all?limit=` | Session/open | all jobs | same | optional Rust query/fallback | Not started |
| GET `/api/job-manager/status` | Session/open | run snapshot | read | optional Rust query/fallback | Not started |
| POST `/api/jobs/<job_id>/cancel` | Session/open | cancel/error status | cancelled T; supervisor terminates child | none | Not started |
| POST `/api/jobs/cancel-queued` | Session/open | count/status | cancelled T per pending | none | Not started |
| GET `/api/jobs/cleanup/preview?retention_days=` | Admin/open | count/cutoff/retention | filesystem mtime + reads | none | Not started |
| POST `/api/jobs/cleanup/run?retention_days=` | Admin/open | removed/remaining | synchronous unlink then files-only cleanup T | none | Not started |

### Posts blueprint (18)

| Method/path | Access | Request and response/headers | Writes/background/external | Existing Rust | Port status |
| --- | --- | --- | --- | --- | --- |
| POST `/api/posts/<guid>/troubleshoot` | Admin/open | optional job; explanation/none, 400/502 | logs/traceback + synchronous LLM | none | Not started |
| GET `/api/feeds/<feed_id>/posts?page&page_size&whitelisted_only` | Session/open | page envelope; size 1..200; 404 | read | optional Rust raw JSON/fallback | Not started |
| GET `/api/posts/<guid>/processing-estimate` | Admin/open | can-process/minutes/reason | read | none | Not started |
| GET `/post/<guid>/json` | Session/open | diagnostic post/transcript/calls | read | none | Not started |
| GET `/post/<guid>/debug` | Session/open | diagnostic counts/status | read | none | Not started |
| GET `/api/posts/<guid>/stats` | Session/open | stats/segments/cost/log JSON | DB/files/log/pricing | optional Rust stats + enrichment | Not started |
| POST `/api/posts/<guid>/whitelist` | Admin/open | whitelist/trigger; state/message | Post update T; optional manager start | none | Not started |
| POST `/api/feeds/<feed_id>/toggle-whitelist-all` | Admin/open | computes new state; counts/message | toggle T; optional enqueue; 503 busy | none | Not started |
| POST `/api/posts/<guid>/process` | Admin/open | manager/download state | run/create/attribution/dequeue writer actions; wake supervisor | none | Not started |
| POST `/api/posts/<guid>/reprocess` | Admin/open | manager state | cancel T, full clear T, start | none | Not started |
| POST `/api/posts/<guid>/reprocess/keep-transcript` | Admin/open | state or no-reusable code | compatibility read; cancel/keep-clear/start | none | Not started |
| GET `/api/posts/<guid>/status` | Session/open | status/stage/tier/download | read | none | Not started |
| GET `/api/posts/<guid>/audio` | Token/session | processed MP3, conditional/range, Accept-Ranges | activity F; optional whitelist T/process; count F | none | Not started |
| GET `/api/posts/<guid>/chapters` | Session/open | chapter array/errors | MP3 metadata read | existing chapter CLI adapter | Not started |
| GET `/api/posts/<guid>/download` | Token/session | attachment MP3, range/conditional/filename | same auto-process/count behavior | none | Not started |
| GET `/api/posts/<guid>/download/original` | Token/session | original attachment; different range behavior | whitelist required; count F | none | Not started |
| GET `/post/<guid>.mp3` | Token/session | delegates processed audio | same | none | Not started |
| GET `/post/<guid>/original.mp3` | Token/session | delegates original | same | none | Not started |

## Known parity risks

- Mutating routes that are Session/open rather than admin include whitelist via
  legacy URL, refresh-all, and job cancellation. Preserve them unless an
  explicit security change is separately approved.
- User PATCH can commit multiple independent writer actions. Billing combines
  irreversible provider operations with database mutations. Cost cleanup reports
  asynchronous admission as removal. These are current contracts, not atomicity
  claims.
- PodcastIndex has a 10-second timeout. Stripe route calls and Discord callback
  HTTP had no explicit per-route timeout. Provider test routes and troubleshooting
  intentionally perform external calls and require mocks in parity tests.
- Processed audio uses conditional/range behavior; original download differs.
  Preserve Content-Length, Content-Disposition, MIME, range, and cancellation
  behavior instead of treating all file routes alike.

## Worker and scheduler ownership

| Owner / entrypoint | Start / cadence | Shutdown / recovery | Writes and effects | Service isolation |
| --- | --- | --- | --- | --- |
| `scripts/start_services.sh` under Docker entrypoint | starts Python writer, polls TCP 50001 for up to 30s, starts web, then `wait -n` | Docker restart policy; no signal trap, sibling termination, or explicit reap | supervision only | actual persistent supervisor outside Flask |
| `app.writer` / `run_writer_service` | shell-owned; serialized infinite queue, IPC daemon thread, activity-gated idle-trim daemon (default 900s) | process exit only; no graceful stop/join | sole DB writer plus startup migration/bootstrap; allocator trim | writer only; no scheduler/HTTP |
| `src/main.py` / Waitress web | after writer TCP readiness; `SERVER_THREADS` (default 1 in code, deployed 32) | process exit only | HTTP/read sessions; owns scheduler and job supervisor | no migration/bootstrap/writer server |
| APScheduler `_start_scheduler_and_jobs` | web startup; deletes `/tmp/jobs.sqlite*`; shared one-thread executor; clears active jobs | no explicit shutdown; persisted store erased on startup | owns callbacks below | resident inside Flask web |
| scheduled feed refresh | configured interval; startup substitutes 10m when null; coalesce, unlimited misfire grace, max one | in-process coalescing only; scheduler store reset on restart | sequential RSS fetch, optional Rust plan, writer refresh/cleanup/run/job/reassign actions | existing web app context |
| scheduled processed-post cleanup | retention >0; first +15m then every 24h; coalesce/max one | removal when disabled; no filesystem/DB atomic recovery | unlinks audio before files-only writer cleanup | existing web app context |
| scheduled memory trim | default/bad value 15m unless disabled; coalesced/max one | stateless | allocator trim/log | no additional service |
| JobsManager `jobs-manager-worker` | constructed at scheduler startup or lazily by routes; daemon polls every 5s/event; one child | stop event never set; no shutdown/join; startup deletes active jobs instead of reconciliation | run/job actions; claims and supervises one processor | lives in Flask; no second scheduler/writer |
| GET-RSS opportunistic refresh | daemon; globally max two; per-feed 60s monotonic cooldown and de-duplication | no join/recovery; memory limits reset on restart | upstream fetch and refresh/job writer actions | existing app context |
| explicit refresh/add-feed enqueue | daemon per request | no join/cancel; explicit refresh is unbounded | refresh/writer work or enqueue | existing app context |

Scheduler configuration details: all recurring jobs coalesce; refresh and cleanup
set `misfire_grace_time=None` and `max_instances=1`; memory trim inherits the
single-instance default. Scheduled RSS uses a one-thread executor and sequential
feeds. `requests` has a 30-second timeout, while feedparser's URL fallback is not
explicitly bounded. Runtime null refresh configuration removes the job, whereas
startup treats null as ten minutes. Cleanup config can remove but does not add or
retime an absent job.

## Short-lived helper inventory

| Helper | Owner / contract | Deadline / termination | Effects and isolation |
| --- | --- | --- | --- |
| `python -m app.processing_worker --job-id ... --post-guid ...` | JobsManager claims then `Popen`; inherits stdio/environment and ensured PYTHONPATH | no job deadline; poll default 2s; on DB cancellation terminate, wait default 10s, then kill; no process group | `create_processing_app` creates an app context but no HTTP/scheduler/migration/writer server; reads DB, writes only through WriterClient; network/audio/artifact/Rust/ffmpeg effects |
| `python -m app.pricing_worker` | pricing client sends JSON pairs on stdin and receives triples on stdout; cache TTL 1h/max 256 | `subprocess.run` timeout 60s/check; errors yield uncached zero rates | loads pricing metadata; no intended DB/file write and no app factory/services |
| Rust `podly_tools` | synchronous sidecar wrappers, stdout protocol/stderr capture | default 300s; audio timeout configurable; `subprocess.run` reaps | read-only SQLite and compute/file/audio work; temp cleanup; wrappers currently fall back to Python on error; no services |
| `ffmpeg` | synchronous audio bleep child | no timeout; check/reap on return | reads/writes audio; no services |
| INA executor | optional one-thread pool inside processing child | HTTP default 3600s; future +30s; nonwaiting executor shutdown | audio upload plus writer actions; executor thread can extend child lifetime |
| Docker health probe Python | every 30s | Docker timeout 10s | GET 5001; imports no app/services |

## Lifecycle and recovery risks

- Neither APScheduler nor JobsManager has a graceful shutdown hook. Processing
  children lack process-group ownership, so descendants are not explicitly
  terminated by cancellation or shell shutdown.
- The shell's `wait -n` does not forward signals or stop the surviving sibling.
- Active jobs are deleted on web startup rather than reconciled. Crash windows
  around claim/spawn and child completion/observation are not recovered. Stale
  cleanup helpers exist but have no production callers.
- Explicit feed refresh can create unbounded daemon threads, unlike the bounded
  GET-RSS refresh path. The single scheduler executor means one long refresh
  delays every scheduled task.
- The scheduler job store is erased at startup, so cross-restart missed runs are
  not retained despite using a persistent-store implementation.
- Pricing and processing helpers do not start a writer or scheduler. There is no
  separate configuration helper; each app process hydrates configuration.
