# Rust service migration implementation plan

Status: proposed implementation plan; no migration tasks below are complete.

Prepared: 2026-09-20. Revalidate file locations and inventories against the commit being implemented.

## 1. Outcome and migration order

Reduce steady-state RAM and request overhead by retiring persistent Python services, while retaining the React frontend and short-lived Python processing workers where needed.

Implement **the writer migration first**, then **the web/scheduler migration**. Do not start the second migration until the first has passed its acceptance gates. The writer is a narrower service boundary, not a trivial port: it owns generic database commands and approximately 57 named actions. The web migration covers approximately 77 routes across nine blueprints plus authentication, scheduling, and job supervision. These are snapshot counts, not substitutes for an inventory.

Observed Docker snapshot before migration:

| Component | Observed memory | Responsibility |
| --- | --- | --- |
| Python writer | Approximately 81 MiB RSS | Serialized SQLite writes, startup/bootstrap |
| Python web | Approximately 97 MiB RSS | Flask/Waitress, React assets, APIs, RSS, scheduler, job supervision |
| Whole container | Approximately 178–179 MiB in Docker stats | Includes both services; accounting differs from summed RSS |

These are observations, not promised savings. A Rust replacement still consumes memory. Measure the net container improvement; do not claim the full retired process RSS as savings. Existing local cleanup optimizations may change the baseline before implementation begins.

### Intended deployment states

| State | Persistent processes | Temporary Python processes |
| --- | --- | --- |
| Current | Python writer + Python web | Processing/pricing helpers and other existing workers |
| Writer migration complete | Rust writer + Python web | Startup migration/bootstrap, processing/pricing helpers |
| Web migration complete | Rust writer + Rust web | Startup migration/bootstrap and remaining processing/integration helpers |

Keep the Rust writer and web as separate processes initially. Combining them is an optional later optimization, not required by this plan. Preserve one authoritative database writer in either arrangement.

### Out of scope

- Rewriting React in Rust, changing frontend frameworks, or redesigning the UI.
- Replacing the database, redesigning the schema, or introducing a new broker.
- Porting every LLM, transcription, audio, or external integration at once.
- Removing Python from the container image before its remaining helpers are replaced.
- Changing podcast, authorization, subscription, billing, or job behavior as part of a performance port.

## 2. Instructions for the implementing agent

1. Read `AGENTS.md` and `CLAUDE.md` before changing code. Their current instructions govern execution.
2. Work on one numbered task at a time. Read its dependencies, implement it, verify it, then update its checkbox and evidence. Do not mark a phase complete because its happy path works.
3. Use CodeGraph/claude-context for code discovery. With `.codegraph/` present, main-session exploration must be delegated as specified by `AGENTS.md`. Respect the exploration budget and do not reread returned source sections.
4. Use `mise` for toolchains/dependencies, `uv` for Python, and `npm` with the existing lockfile for frontend work.
5. Run tests and lints only through `mise exec -- ./scripts/ci.sh`. Use its `--int` option when applicable. Extend that script to include new required checks instead of invoking test runners separately.
6. The existing CI script formats/fixes files and can mask an earlier command failure with a later successful exit. Inspect every section until task P0.4 makes failure propagation reliable. Review the diff after every run.
7. Add/update backend regression tests for behavioral changes. Keep shared Python/Rust/frontend payloads compatible.
8. Runtime database writes must continue through the selected writer service. Never work around missing Rust functionality with direct writes from web handlers or processing workers.
9. Do not generate Alembic migrations yourself. This plan aims to avoid schema changes. If one becomes necessary, document why and have the user generate it using the repository's prescribed script.
10. New environment settings must be documented. The current checked-in template is `.env.local.example`; `CLAUDE.md` calls it `.env.example`. Update the actual tracked template and document this naming discrepancy rather than creating an unused parallel template silently.
11. Do not log credentials, session cookies, feed-token secrets, transcripts, or complete RPC bodies. Use synthetic fixtures and private temporary database copies for comparisons.
12. Do not run old and new writers against the same database for comparison. Never mirror a production write to both implementations.
13. Preserve unrelated work. Do not deploy, restart the live instance, delete data, or change live configuration merely to complete this document's checklist. Follow the authorization applicable at implementation time.
14. If a task reveals an unlisted behavior, add it to the inventory and its parity cases before proceeding. Do not replace it with a guessed implementation.

### Required evidence entry for each completed task

```text
Task ID:
Commit/reference:
Files changed:
Behavior preserved or intentionally changed:
Tests added and CI log path:
Parity/benchmark evidence, if applicable:
Remaining limitations:
```

Store implementation evidence in `docs/plans/rust-service-migration-evidence.md` when work starts. Do not place secrets or real user records there. This plan's checkboxes remain unchecked until that evidence exists.

## 3. Source map

Paths are relative to the repository root. Verify exact symbols at task start.

| Area | Starting points | What must be preserved |
| --- | --- | --- |
| Writer messages | `src/app/writer/protocol.py` | Command/result envelopes and operation types |
| Writer client | `src/app/writer/client.py`, `WriterClient` | `wait=True/False`, configurable timeout, request correlation, caller-facing failures |
| Writer service | `src/app/writer/service.py`, `run_writer_service` | One command at a time, transaction ownership, cleanup, readiness |
| Writer executor/actions | `src/app/writer/executor.py`, `src/app/writer/actions/` | Generic operations, named actions, validation and side effects |
| Python IPC | `src/app/ipc.py` | Existing BaseManager authentication/connection assumptions |
| Startup/config | `src/app/__init__.py`, `create_writer_app`, runtime config code | Migrations, bootstrap, defaults, configuration hydration |
| Models/schema | `src/app/models.py`, `src/migrations/` | ORM defaults/hooks, relationships, cascades, JSON and numeric representations |
| HTTP routes | `src/app/routes/` | Methods, paths, response/status/header shapes, guards, side effects |
| Authentication | `src/app/auth/middleware.py`, `feed_tokens.py`, `service.py` | Session cookies, feed tokens, subscription/admin checks |
| RSS/refresh | `src/app/feeds.py`, `src/app/routes/feed_routes.py` | RSS bytes, ETags, access checks, refresh limits, write planning |
| Scheduling/jobs | `src/app/background.py`, `src/app/jobs_manager.py` | Scheduling, admission, recovery, cancellation, worker lifetime |
| Python processing | `src/podcast_processor/`, processing worker entrypoints | Work still requiring Python; writer-client use |
| Existing Rust | `rust/src/main.rs`, `rust/Cargo.toml` | CLI behavior and reusable query/compute implementations |
| Rust adapters | `src/shared/rust_sidecar.py` | Subprocess arguments/results, positive path evidence, existing fallback behavior |
| Container lifecycle | `scripts/start_services.sh`, `Dockerfile`, `docker-entrypoint.sh`, `compose.yml` | Permissions, migrations, readiness, supervision, healthcheck |

Existing Rust work includes RSS/aggregate rendering, refresh planning, feed-post queries, jobs queries/status, post statistics, cost aggregation, and portions of chapter/transcript/audio processing. Treat this as reusable implementation, not evidence that the corresponding complete HTTP or job lifecycle already exists in Rust.

## 4. Fixed architecture decisions

These decisions reduce open-ended design work for the implementing agent. Change them only with a documented reason and an updated plan.

### 4.1 Writer transport

- Add a Rust writer binary inside the existing Rust package. Keep the existing CLI binary and command compatibility.
- Use a versioned HTTP/JSON RPC on **loopback only**, initially `127.0.0.1:50001`, replacing the existing IPC listener at cutover. Do not publish the writer port through Docker.
- Use Axum/Tokio for the transport and `rusqlite` for SQLite. Pin resolved dependencies in the existing lockfile. Do not rewrite database access using a second ORM.
- Replace both ends of the Python `multiprocessing.BaseManager` protocol. Rust must not attempt to deserialize Python pickle or emulate Manager queue proxies.
- Preserve the public `WriterClient` API where practical so web/processing call sites do not all change together.
- Preserve local IPC authentication with a shared secret supplied through the existing configuration where suitable. Specify its encoding and comparison explicitly. Require authorization on command endpoints, redact it from logs, and do not rely on loopback alone as authentication.
- Do not create one async database task per incoming request. A single dedicated writer thread owns the connection and consumes a bounded queue. HTTP tasks only validate, enqueue, and await responses.
- Queue saturation must produce an explicit rejection before enqueue. Body size, queue count, aggregate queued payload bytes, connections, and request timeouts must be bounded. Choose limits using measured processing payloads in P0; do not invent a tiny limit that breaks transcription writes.

### 4.2 Request/result semantics

Define the complete schema in P1 before coding transport. Suggested envelope shape:

```json
{
  "version": 1,
  "command_id": "unique-client-generated-id",
  "operation": "action",
  "action": "touch_feed_access_token",
  "params": {},
  "wait": true
}
```

The empty `params` above illustrates the envelope only; it is not a valid token-touch fixture. Each action's real parameters come from the action inventory. Generic commands and transactions need separately documented fields.

- `wait=true`: reply only after commit or rollback. Return the matching command ID, success flag, result or structured error. Adapt this to the existing `WriteResult` shape in Python.
- `wait=false`: return an admission acknowledgement after the command enters the queue, not a false claim that it committed. Python's public method still returns `None` on successful admission. Execution errors must be observable in structured logs/metrics. This is not a durable queue guarantee.
- Retain `PODLY_WRITER_TIMEOUT_SECONDS` behavior, including the current default of 30 seconds, until intentionally changed. Include admission/network/reply waiting in a documented deadline; do not wait indefinitely while establishing a connection or enqueueing.
- A timeout or dropped connection after admission means **outcome unknown**. It does not mean rollback. A request ID provides correlation, not exactly-once execution.
- Disable automatic retries for writes whose admission/commit status is unknown. Do not replay them on reconnect or service restart. Retry only explicit pre-admission rejections when safe, or actions proven idempotent by an individual contract and test.
- Do not advertise exactly-once delivery or durable deduplication. Adding a durable command ledger would be a separate schema/design change, not an implied feature of this plan.
- Unknown protocol versions, actions, models, malformed envelopes, unauthorized requests, and exhausted capacity must fail explicitly. Specify allowed envelope fields. Preserve existing domain field/error behavior through the adapter: generic model mutations currently ignore unknown model fields, DELETE succeeds for an absent row, and UPDATE fails for an absent row. Do not silently tighten those behaviors while porting.
- Do not return raw SQL, database paths, or sensitive payloads in public-facing errors.

### 4.3 Transaction and serialization rules

- One top-level command is one transaction unless its existing contract explicitly says otherwise. Document exceptions before porting them.
- A transaction containing subcommands commits once, after all succeed. Failure in any subcommand rolls back all of them. Action helpers never commit independently.
- Reply with success only after commit succeeds, including commit-time constraint failures.
- Match current SQLite foreign-key enforcement, busy timeout, journal mode, and durability settings. Measure/document current values; do not turn off durability to win a benchmark.
- Explicitly reproduce ORM-generated defaults, timestamps, UUIDs, password/token hashes, relationships, cascades, and hooks. SQL column defaults alone may not match SQLAlchemy behavior.
- Specify a codec for every nontrivial value: datetime timezone/format, enum, UUID, bytes, null/missing, JSON columns, integers/floats, and nested transaction results. Reject or explicitly encode non-finite numbers; JSON cannot safely carry arbitrary Python objects.
- SQLite numeric columns can contain both INTEGER and REAL storage classes. Reuse tolerant readers, preserve existing integer-versus-real response shapes, and test fractional durations.
- Preserve distinctions such as missing field versus explicit `null`, empty list versus absent list, and merge versus replace semantics.
- Bound large payload lifetimes. Release command bodies/results after completion; avoid unnecessary JSON copies and unbounded caches in the long-lived server.
- Filesystem/network side effects are not undone by SQLite rollback. Inventory them per action and retain their ordering/recovery semantics. Do not label an action fully atomic merely because its SQL is transactional.

### 4.4 Backend selection and fallback

- Introduce one explicit startup backend selector, proposed `PODLY_WRITER_BACKEND=python|rust`, defaulting to Python until the writer acceptance gate passes. Document it in the actual environment template.
- Select the backend once per process. Do not switch databases or backends per request or per action.
- During development, run Rust and Python against **separate database copies** for differential tests.
- A partially ported Rust service must not be selected for production. All reachable operations must pass the inventory gate first.
- In Rust mode, connection/action failures fail visibly. No fallback to the Python writer or local SQLAlchemy writes is permitted in production.
- Existing unit-test local execution may remain for legacy tests, but Rust integration tests must explicitly disable/bypass it. `PYTEST_CURRENT_TEST` must not accidentally make a supposed RPC test execute locally.

## 5. Phase P0 — inventory, baseline, and test harness

Dependency: none. Deliverables: inventories, reproducible baseline, trustworthy CI.

- [x] **P0.1 — Record baseline revision and deployment.** Record git revision, current changes, image revision, enabled Rust paths, toolchain versions, process roles, and configuration names without secrets. Distinguish checked-out code from the deployed image.
- [x] **P0.2 — Build the writer inventory.** Enumerate every registered action and every caller of generic create/update/delete/transaction commands. Trace `wait` usage, result handling, transaction boundaries, defaults, validation, side effects, and return shapes. Include startup/bootstrap commands. Do not infer the contract only from the registry.
- [x] **P0.3 — Build the HTTP/worker inventory.** List every method/path, blueprint, auth guard, request/response schema, headers/cookies, Rust backing, writes, background work, and external integration. Identify actual worker entrypoints and any persistent supervisor outside Flask.
- [x] **P0.4 — Make CI trustworthy.** Update `scripts/ci.sh` so a failed stage cannot be hidden by later success. Preserve existing checks and `--int` support. Ensure new writer transport/contract tests run through this script. Verify an intentionally failing fixture/check causes failure, then remove the intentional failure and obtain a clean run.
- [x] **P0.5 — Create isolated parity fixtures.** Use small synthetic SQLite snapshots, including foreign-key relationships, completed/active/cancelled jobs, tokens, large processing JSON, missing records, and mixed numeric storage. Each backend gets an independent clone and temporary data directories. Never use live credentials or writable live database mounts.
- [x] **P0.6 — Record baseline performance.** Measure warmed idle and concurrent load: container memory, per-process RSS, CPU, thread/FD counts, queue latency, end-to-end latency, and post-burst memory after a fixed cooldown. Use concurrency at least 8 for HTTP endpoints, including RSS. Confirm positive Rust execution or absence of fallback for each Rust-backed measurement.
- [x] **P0.7 — Record acceptance thresholds.** Put workload sizes, sampling interval, run duration, cooldown, repetition count, and allowable latency/error regressions in the evidence file before comparing implementations. Use at least three comparable runs. Set a measurable net-memory reduction target from this baseline; do not substitute a theoretical Rust footprint.

Writer inventory template (one row per action or generic operation):

| Action/operation | Callers and wait mode | Parameters/codecs | Result/errors | Tables/defaults/hooks | Non-DB effects | Parity cases | Port status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Fill from current code | | | | | | | Not started |

HTTP inventory template (one row per method/path, not merely per file):

| Method/path | Auth/access rules | Request | Response/headers | Writer actions | Background/external work | Existing Rust reuse | Parity cases | Port status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fill from current code | | | | | | | | Not started |

**P0 exit gate:** no unknown production writer callers; initial web/worker ownership map exists; CI failure propagation is reliable; baseline and isolated fixtures are reproducible.

## 6. Phase P1 — writer contract and isolated Rust service

Dependency: P0. Do not change the production default backend.

- [x] **P1.1 — Write the protocol specification.** Add a versioned schema/spec and shared request/result fixtures. Specify every error/admission state, limits, authentication, codec, deadline, transaction form, and `wait=false` semantics from section 4. Distinguish strict envelope validation from existing model-field compatibility behavior.
- [x] **P1.2 — Add the Rust binary/modules.** Add a writer entrypoint and focused protocol/transport/database/action modules. Preserve the current CLI target and flags. Extract only code needed for reuse; do not make a wholesale rewrite of `rust/src/main.rs` a prerequisite.
- [x] **P1.3 — Add the single-owner database executor.** One dedicated thread/connection, bounded admission, explicit transaction wrapper, rollback on action failure, commit-time error handling, deterministic shutdown behavior. Keep blocking SQLite work off async executor threads.
- [x] **P1.4 — Implement authenticated RPC admission.** Validate the envelope before enqueue; enforce limits; correlate response IDs; prevent a disconnected client from growing retained result state. Unsupported actions fail without changing the database.
- [x] **P1.5 — Implement readiness and lifecycle.** Ready only after the expected database/schema is open, required actions are registered, and the executor is accepting work. Report backend/protocol/schema identity without secrets. Reject schema incompatibility rather than silently creating a fresh database at a wrong path.
- [x] **P1.6 — Add transport integration tests.** Launch an isolated writer subprocess on a temporary port and DB. Cover auth failures, malformed/oversized requests, capacity rejection, wrong version, deadlines, dropped clients, out-of-order completion responses, restart/reconnect, and unknown outcomes. Prove the tests cannot reach Python local fallback.
- [x] **P1.7 — Add graceful shutdown.** Stop admission, drain accepted work within a documented shutdown grace, then close the connection. If force-terminated, uncommitted SQLite work must roll back; do not claim all acknowledged asynchronous work survived. Test SIGTERM and abrupt death separately.

**P1 exit gate:** transport and lifecycle work on isolated fixtures; no production cutover; no unbounded queue or per-request thread creation; CI passes.

## 7. Phase P2 — port all writer operations

Dependency: P1. Implement groups sequentially. The exact registry from P0 is authoritative.

### Required procedure for every action

Copy this checklist into its inventory/evidence entry:

- [ ] Read the Python implementation, its callers, model behavior, and relevant tests.
- [ ] Specify valid/missing/invalid parameters, authorization assumptions, result shape, and errors.
- [ ] Write fixtures for success, no-op/missing record, boundary values, repeat invocation where relevant, and failure after a partial mutation.
- [ ] Run Python and Rust against separate copies of the same fixture through the CI-owned parity harness.
- [ ] Compare returned values AND resulting table rows/relationships. Compare timestamps/IDs using controlled clocks/ID sources where feasible; normalize only documented nondeterministic fields without discarding semantic assertions.
- [ ] Compare filesystem/config/notification effects when the action has them.
- [ ] Implement Rust through the central transaction wrapper; no helper-level commits.
- [ ] Prove rollback behavior, including constraint failures at commit.
- [ ] Add the action to the Rust registry and machine-checked registry coverage list.
- [ ] Record evidence and only then mark the action port complete.

### Port groups

- [ ] **P2.1 — Generic commands and transactions.** Implement only currently reachable model operations with explicit model/field allowlists. Preserve nested result order and error behavior, including ignored unknown model fields, absent-row DELETE success, and absent-row UPDATE failure. Ignore unsupported model fields as today; never interpolate them as SQL identifiers. Do not remove generic operations until all their callers have migrated.
- [ ] **P2.2 — System/config/startup-related actions.** Preserve configuration serialization, mutation visibility, defaults, cache invalidation, and reload/notification behavior. `update_combined_config` currently hydrates the writer while the web settings handler also hydrates its own configuration and resets its processor. Preserve both responsibilities and their ordering; a successful Rust response alone does not update another process's memory. Prove Python web/workers observe updates after replacing the writer.
- [ ] **P2.3 — Users/authentication actions.** Preserve password hash formats and verification compatibility, account defaults, roles, activity timestamps, and user deletion effects. Use compatible hashing rather than treating hashes as interchangeable strings.
- [ ] **P2.4 — Feeds, subscriptions, and feed-token actions.** Preserve ownership/access, token hash/secret handling and rotation/revocation, episode identity/deduplication, refresh merge rules, whitelist settings, and deletion cascades.
- [ ] **P2.5 — Job lifecycle actions.** Preserve singleton-run ownership, enqueue/dequeue rules, claim/requeue/cancel/finish transitions, stale job recovery, and progress/error semantics. Race tests must show no duplicate job claim and no cancelled job silently becoming successful.
- [ ] **P2.6 — Processing persistence actions.** Port transcript segments, identifications, model calls, audio segments, replacement workflows, and artifact-backed imports. Test realistic large documents without unbounded buffering, preserved order/numeric precision, partial failure, and duplicate/retry semantics.
- [ ] **P2.7 — Cleanup actions.** Preserve selection predicates, deletion order, relationship effects, path handling, missing-file behavior, and interrupted-cleanup recovery. Never run cleanup parity cases against real audio paths.
- [x] **P2.8 — Registry completeness gate.** Compare the current Python registry and generic-call inventory to Rust coverage automatically. Every production-reachable operation must have a parity case or an explicitly removed caller. A hardcoded historical count of 57 is not sufficient.
- [x] **P2.9 — Mixed-client stress/failure tests.** Concurrent web-like and processing-like clients submit real fixture operations at concurrency 8 or greater. Verify ordering requirements, bounded memory, no lost/misrouted replies, rollback, SQLite lock behavior, saturation, restart, and long-running command timeouts.

**P2 exit gate:** every reachable write operation has parity evidence; no partial per-action production routing; all CI stages pass.

## 8. Phase P3 — Python client adapter and one-shot bootstrap

Dependency: P2 for final cutover; the adapter may be developed on isolated fixtures during P2.

- [ ] **P3.1 — Add the explicit backend selector.** Default remains Python. Use one authoritative configuration source shared by launcher and client. Validate unknown values and prevent mismatched client/server protocol selections.
- [ ] **P3.2 — Implement the Rust transport adapter in `WriterClient`.** Preserve call signatures, result/error adaptation, `wait=False` return behavior, and timeout configuration. Known asynchronous callers include token touches, download counts, user activity, cost backfill, and feed deletion. Admission acknowledgement must not turn them into commit-waiting calls or expose asynchronous execution errors as synchronous domain responses. Preserve visible connection/admission failures. Bound connection reuse/pools and release responses. Do not import the Python executor on the Rust production path.
- [ ] **P3.3 — Preserve correlation/recovery semantics.** Test stale/late results, one failed request followed by a valid one, concurrent threads, server restart, partial response, and a timeout after commit. Disable transparent write retries, including HTTP-library retries.
- [ ] **P3.4 — Remove production write fallback in Rust mode.** Explicit local-fallback settings must not silently override Rust mode. Legacy local tests may remain separate, but the integration suite must fail if the Rust writer is unavailable. Assert this behavior directly.
- [ ] **P3.5 — Extract a one-shot Python bootstrap entrypoint.** Reuse existing migrations/bootstrap logic without starting writer IPC, scheduler, or HTTP. Ensure it exits after completion and does not leave background children. Do not port Alembic to Rust in this phase.
- [ ] **P3.6 — Prove bootstrap ordering/exclusivity.** Stop runtime writers before migration. Run bootstrap once, wait for success, then start Rust writer, wait for readiness, then start web. The migration tool is an exclusive pre-service schema owner, not a second runtime writer. Resolve any bootstrap action that currently expects live writer IPC before cutover.
- [ ] **P3.7 — Prove bootstrap/config idempotence.** Two sequential startup runs on the same fixture do not duplicate users/defaults or reset settings. Missing/invalid config, permission failures, wrong DB paths, and incompatible schema revisions fail startup clearly.
- [ ] **P3.8 — Exercise actual Python clients.** Run HTTP mutations and a synthetic processing job through the adapter with the Rust writer selected. Verify committed data and writer identity; a valid response shape alone is not proof of the selected path.

**P3 exit gate:** real clients work through Rust; no Python writer is needed except the explicitly selected legacy mode; bootstrap exits; no hidden local execution.

## 9. Phase P4 — retire the persistent Python writer

Dependency: P0–P3 complete. This is the first RAM-saving deployment milestone.

- [ ] **P4.1 — Package the writer.** Update Docker build/copy paths for both Rust binaries without breaking existing sidecar discovery. Preserve non-root UID/GID behavior, instance paths, file permissions, and existing allocator setup until measured otherwise.
- [ ] **P4.2 — Update startup/supervision.** Select exactly one writer backend. For Rust mode, run one-shot bootstrap, then Rust writer readiness, then Python web. Propagate SIGTERM, reap children, stop dependent processes when the writer fails, and return a useful failure status. Do not rely only on a TCP-open probe.
- [ ] **P4.3 — Update readiness/health checks.** Health must verify the intended backend and executor readiness, not only that React's `/` page returns 200. Do not expose secret RPC details publicly. Use an available lightweight probe; do not assume `curl` is installed or introduce Python polling loops as the final steady-state solution.
- [ ] **P4.4 — Test fresh start, upgrade, and restart in an isolated container.** Include an existing database, empty deployment, non-default UID/GID, persistent volume, interrupted command, bootstrap failure, and writer death. Confirm no startup race lets web accept work before the writer is ready.
- [ ] **P4.5 — Run rollback rehearsal.** Stop clients/new writer before selecting the Python backend. Use the same unchanged schema only after verifying compatibility; otherwise restore the tested backup with an explicit data-loss assessment. Do not start the old writer beside the new one. Verify pending-job recovery and avoid replaying unknown-outcome commands.
- [ ] **P4.6 — Benchmark against P0.** Repeat the same idle, concurrent HTTP, RSS, write-burst, and processing scenarios. Confirm the actual Rust writer path and absence of local fallback. Measure total container memory plus per-process RSS, latency, CPU, errors, threads, FDs, and post-burst recovery.
- [ ] **P4.7 — Verify process retirement.** After bootstrap exits and with no job running, process inspection shows Rust writer + Python web, and no `python -m app.writer`, bootstrap daemon, or compatibility proxy. Process removal is mandatory, even if request benchmarks are green.
- [ ] **P4.8 — Complete the writer release gate.** All parity/failure tests pass, rollback is rehearsed, measured memory reduction meets P0 thresholds, and request/job behavior does not regress beyond agreed thresholds. Record evidence before making Rust the deployment default.

Do not continue to web migration to hide a failed writer acceptance gate. Diagnose the failure first.

## 10. Phase P5 — build the Rust web foundation

Dependency: P4 accepted. Python web remains the production server until P8.

- [ ] **P5.1 — Refresh the complete HTTP/ownership inventory.** Recount method/path combinations, guards, frontend clients, settings schemas, file routes, callbacks/integrations, and background responsibilities. Identify any behavior implemented by middleware/error handlers rather than route functions.
- [ ] **P5.2 — Add a separate Rust web binary.** Reuse the runtime/protocol modules where appropriate but keep writer ownership separate. Web database connections are read-only; all mutations go through the Rust writer RPC.
- [ ] **P5.3 — Extract existing Rust read/compute handlers incrementally.** Give CLI and HTTP adapters shared functions. Preserve existing CLI tests and subprocess compatibility for Python workers. Do not invoke the old Rust CLI as a subprocess from each new Rust HTTP request when its function can be called directly.
- [ ] **P5.4 — Bound long-lived resources.** Set measured limits for blocking work, read connections, subprocesses, feed refresh concurrency, queues, caches, request bodies, and timeouts. `rusqlite`, XML work, filesystem access, and child-process waiting must not block async executor threads.
- [ ] **P5.5 — Serve existing React build assets.** Preserve SPA history fallback, asset MIME/cache rules, and API-versus-SPA 404 behavior. Reject path traversal. Keep the existing npm build/lockfile; do not rewrite UI components.
- [ ] **P5.6 — Implement common HTTP behavior.** Preserve error JSON/statuses, request limits, relevant CORS/CSRF/origin behavior, trusted-proxy rules, URL generation, cookie attributes, and conditional/range responses where applicable. Only trust forwarding headers under the current deployment's intended proxy policy.

**P5 exit gate:** Rust web runs against isolated fixtures, CLI compatibility remains intact, static/common HTTP behavior has tests, no production traffic cutover.

## 11. Phase P6 — authentication and route parity

Dependency: P5. This phase is complete only when every inventory row is covered.

- [ ] **P6.1 — Specify authentication compatibility.** Document Flask signed-cookie format/signing settings, expiry, secret configuration, user loading, login/logout, rate limits, and existing CSRF behavior. Reproduce session verification and issuance with cross-language fixtures. Do not silently force logout or weaken validation; an intentional session-format change requires an explicit revised cutover plan.
- [ ] **P6.2 — Port access middleware.** Preserve anonymous/user/admin distinctions, disabled/revoked users, subscription checks, feed-token hashing, token rotation/revocation, and scope checks. Denial cases need as much coverage as successful login.
- [ ] **P6.3 — Port existing Rust-backed read routes.** Feed-post listings, job/status reads, statistics, and costs are initial candidates. Preserve sorting, pagination, nulls, numeric shapes, visibility filters, missing-record behavior, and access checks. Reusing SQL is not enough to prove route parity.
- [ ] **P6.4 — Port RSS routes and rendering.** Preserve authenticated URLs, ordering/filtering, enclosure URLs, GUIDs, XML escaping/content type, weak ETags, `If-None-Match` precedence, GET/HEAD behavior, and refresh triggers. Confirm the direct Rust path and memory behavior at concurrency 8 or greater with large feeds.
- [ ] **P6.5 — Port remaining reads/file responses.** Cover original/processed audio, range requests, content length, streaming cancellation, download headers, config/settings, admin diagnostics, and any remaining inventory endpoints. Never read an entire large audio file into memory just to serve it.
- [ ] **P6.6 — Port mutation routes.** Authentication/account management, feed/subscription/token settings, processing controls, cancellation/requeue, runtime configuration, and all remaining mutations must call the writer and preserve response/error contracts.
- [ ] **P6.7 — Port remaining external integration routes.** Inventory billing/notification/provider calls actually present. Preserve callback signature checks, idempotency, timeouts, and response behavior. Use provider fixtures/mocks through CI; do not send real notifications or charges during parity testing.
- [ ] **P6.8 — Make HTTP inventory coverage executable.** Compare registered Python method/path pairs and required middleware behavior with Rust coverage. Every discrepancy requires a documented intentional removal or completed parity case; a count match alone is insufficient.
- [ ] **P6.9 — Exercise the unchanged React client.** Verify login, feed browsing, episode actions, status/progress, settings, admin access, and logout against Rust. Integrate required automated checks into `scripts/ci.sh`. Record any manual smoke steps separately.

**P6 exit gate:** all production HTTP behavior is accounted for; credentials/session compatibility is tested; no route is proxied to Flask as a hidden requirement for final acceptance.

## 12. Phase P7 — move scheduling and job supervision

Dependency: P5 and relevant P6 routes; must finish before removing Flask.

- [ ] **P7.1 — Inventory every scheduled/background task.** Record interval/trigger, coalescing, missed-run handling, maximum instances, startup invocation, shutdown behavior, and owner. Include RSS refresh, cleanup, job discovery/dispatch, configuration refresh, and any periodic tasks found in P0/P5.
- [ ] **P7.2 — Port scheduling semantics.** Preserve coalescing and non-overlap; do not queue an unbounded catch-up burst after downtime. Use monotonic time for elapsed-time deadlines and wall time only where required by the schedule.
- [ ] **P7.3 — Port feed-refresh orchestration.** Reuse Rust planning but preserve upstream fetch limits, explicit connect/read/overall timeouts, bounded concurrency, per-feed cooldowns, failure isolation, and application of plans through the writer. No unbounded fallback network fetch.
- [ ] **P7.4 — Port job supervision.** Claim work through the writer, launch the existing Python worker entrypoint, bound concurrency, stream/drain stdout/stderr without retaining unlimited output, propagate cancellation, kill/reap child process groups on shutdown, and record progress/exit results through the writer.
- [ ] **P7.5 — Preserve job recovery.** Test crash after claim/before spawn, during processing, and after worker completion/before supervisor acknowledgement. Reconcile writer state and process state without double-running a job or inventing success. Retain the current restart policy unless deliberately revised and tested.
- [ ] **P7.6 — Preserve short-lived Python helpers.** Inventory pricing/config/processing helpers; define their request/result/exit contracts, deadlines, environment, and file permissions. Ensure they exit when work ends and do not initialize Flask HTTP, APScheduler, or a second writer.
- [ ] **P7.7 — Reassign periodic maintenance.** Retain useful business/database cleanup. Remove Python-specific GC/allocator-purge scheduling from Rust rather than mechanically translating it. Measure Rust allocator behavior before adding replacement maintenance.
- [ ] **P7.8 — Enforce a single active scheduler.** Isolated tests may use separate DBs. At cutover, stop Python scheduler/supervisor before Rust takes ownership. Never run both against the same production queue as a migration shortcut.
- [ ] **P7.9 — Run lifecycle integration scenarios.** Scheduled refresh with failures, large feeds, concurrent user reads, cancellation during processing, abrupt supervisor death, restart, and configuration changes must pass through the real Rust web/writer pair and synthetic Python workers.

**P7 exit gate:** Flask is no longer required for scheduling or supervision, and Python workers have bounded lifetimes.

## 13. Phase P8 — retire the persistent Python web process

Dependency: P6 and P7 accepted; P4 writer remains the only runtime writer.

- [ ] **P8.1 — Package and select Rust web.** Use one startup-level web backend selector during rollback support. Bind the existing external port 5001, preserve volume/asset paths, and update readiness/health checks to exercise Rust services.
- [ ] **P8.2 — Rehearse cutover in an isolated container.** Bootstrap exits, Rust writer becomes ready, Rust web starts, and only one scheduler runs. Test fresh/existing DBs, non-default UID/GID, reverse-proxy deployment, job cancellation, and shutdown.
- [ ] **P8.3 — Rehearse rollback.** Stop Rust web/scheduler and drain/reconcile jobs before restarting Python web. Keep Rust writer only if the tested Python client supports it. Preserve schema/session/config compatibility and avoid overlapping supervisors.
- [ ] **P8.4 — Repeat all performance workloads.** Same data/config/toolchain conditions and concurrency at least 8. Compare idle, RSS bursts, API reads, mixed writes, large file streaming, active processing, and cooldown. Report container-level net savings, p50/p95/p99 latency, throughput, CPU, queue time, errors, threads, FDs, and transient worker peaks.
- [ ] **P8.5 — Verify web process retirement.** Idle process inspection shows Rust web + Rust writer only, except explicitly documented non-Python infrastructure. No Waitress/Flask process, Python scheduler, writer compatibility proxy, or idle processing helper remains. A lightweight probe does not leave a daemon behind.
- [ ] **P8.6 — Run a representative soak.** Exercise multiple schedule intervals, repeated job lifecycles, token/session use, config changes, and database maintenance. Record memory high-water and post-burst baseline, thread/FD counts, failure/recovery behavior, and log volume. Investigate growth instead of hiding it with restarts.
- [ ] **P8.7 — Complete the web release gate.** All inventory rows covered, authorization parity established, process retirement proven, rollback tested, performance thresholds met, and documentation updated before changing the default deployment.

## 14. Mandatory regression matrix

Each row needs evidence through the repository CI entrypoint. Existing tests are starting points, not proof of Rust service coverage.

| Concern | Required cases |
| --- | --- |
| Write semantics | Success, validation failure, missing record, no-op, default values, commit failure, full rollback |
| Transactions | Ordered results, subcommand failure after earlier mutation, constraints, no intermediate commit |
| IPC | Auth, wrong version, malformed/oversized payload, capacity rejection, asynchronous admission, correlation |
| Timeout/restart | Pre-admission failure, post-admission unknown outcome, late response, no blind replay, reconnect |
| SQLite representation | INTEGER/REAL duration, null/missing, JSON, datetime, Unicode, large records, FK/cascades |
| Jobs | Concurrent claims, cancellation, requeue, stale recovery, worker crash, supervisor crash |
| Side effects | Artifact import failure, missing file, safe temporary paths, partial cleanup, config visibility |
| Web/auth | Signed sessions, expiry/logout, password compatibility, role denial, token scope/revocation, subscription guards |
| RSS/files | XML parity, escaping, ETags/HEAD, range/streaming, access checks, bounded refreshes |
| Lifecycle | Fresh/upgrade startup, exclusive bootstrap, readiness failure, SIGTERM, abrupt death, rollback |
| Memory/resources | Large requests, concurrency 8+, post-burst recovery, connection/thread/FD bounds, no hidden Python service |

Existing test starting points include `test_writer_client_reply_routing.py`, `test_writer_processor_actions.py`, `test_writer_cleanup_actions.py`, `test_writer_service_memory.py`, `test_chapter_writer.py`, `test_ad_classifier_writer_batches.py`, `test_session_auth.py`, `test_feed_etag.py`, `test_rust_python_parity.py`, and Rust's existing tests. P0 must discover additional relevant tests for the actual inventory.

## 15. Rollout and rollback checklist for either service

Use this runbook only when deployment is authorized; documenting it does not authorize live changes.

- [ ] Confirm exact image/commit, selected backends, schema revision, and rollback image.
- [ ] Take a tested SQLite-consistent backup (SQLite backup API or a quiesced database). Do not copy only the `.db` file while WAL writes are active. Include necessary config and artifact/audio state according to existing backup policy.
- [ ] Stop admission and quiesce/reconcile processing as required; record active jobs and unknown-outcome commands.
- [ ] Stop the old service before starting its replacement. Never overlap runtime writers or schedulers on the same database.
- [ ] Run exclusive bootstrap when required; abort if it fails.
- [ ] Wait for protocol/schema-aware readiness, then allow dependent services/traffic.
- [ ] Verify login/access checks, a representative read, a safe controlled write, RSS, and job status on the intended backend.
- [ ] Verify process list, logs, health, and memory; monitor for the agreed observation window.
- [ ] Roll back if correctness, availability, or performance gates fail. Stop the new owner first; do not replay ambiguous writes blindly.
- [ ] Record results, including any user-visible interruption or compatibility limitation.

## 16. Completion and handoff

The migration is complete only when:

- [ ] All runtime writes use the Rust writer with single-owner transaction semantics.
- [ ] React/API/RSS traffic and scheduling/job supervision use Rust without a resident Python web process.
- [ ] Remaining Python execution is explicitly inventoried, short-lived, and exercised in integration tests.
- [ ] Existing data, auth/session/token behavior, frontend contracts, and processing results remain compatible.
- [ ] Startup, readiness, shutdown, recovery, and rollback have recorded evidence.
- [ ] Concurrent benchmarks show a measured net memory reduction without unacceptable correctness or latency regression.
- [ ] All required CI sections pass; diffs and formatter changes have been reviewed.
- [ ] Operational docs explain backend selection, remaining Python helpers, troubleshooting, and the measured results.

Future work such as merging Rust processes, eliminating Python bootstrap, or porting remaining ML integrations is a separate proposal. Do not expand this migration until these completion gates are satisfied.

## Appendix A — verified writer action checklist

Snapshot: 57 actions verified from the current registry. Reconcile this list against the implementation revision in P0 and automatically at P2.8. These groups reflect the existing modules, not a guarantee that each action only touches that domain. Every checkbox requires the per-action procedure in P2, including result and side-effect parity.

### Users — 9

- [ ] `create_user`
- [ ] `update_user_password`
- [ ] `delete_user`
- [ ] `set_user_role`
- [ ] `set_manual_feed_allowance`
- [ ] `upsert_discord_user`
- [ ] `set_user_billing_fields`
- [ ] `set_user_billing_by_customer_id`
- [ ] `update_user_last_active`

### Feeds — 13

- [ ] `refresh_feed`
- [ ] `add_feed`
- [ ] `update_feed_settings`
- [ ] `increment_download_count`
- [ ] `whitelist_post`
- [ ] `ensure_user_feed_membership`
- [ ] `remove_user_feed_membership`
- [ ] `whitelist_latest_post_for_feed`
- [ ] `toggle_whitelist_all_for_feed`
- [ ] `create_dev_test_feed`
- [ ] `delete_feed_cascade`
- [ ] `create_feed_access_token`
- [ ] `touch_feed_access_token`

### Jobs — 14

- [ ] `dequeue_job`
- [ ] `cleanup_stale_jobs`
- [ ] `clear_all_jobs`
- [ ] `clear_active_jobs`
- [ ] `create_job`
- [ ] `create_job_if_missing`
- [ ] `cancel_existing_jobs`
- [ ] `update_job_attribution`
- [ ] `update_job_status`
- [ ] `mark_cancelled`
- [ ] `mark_classification_parse_error`
- [ ] `record_ad_windows_count`
- [ ] `mark_auto_retry_attempted`
- [ ] `reassign_pending_jobs`

### Processor — 12

- [ ] `upsert_model_call`
- [ ] `delete_model_calls_for_post_by_model_name`
- [ ] `upsert_whisper_model_call`
- [ ] `replace_transcription`
- [ ] `start_transcription_replace`
- [ ] `insert_transcript_segments`
- [ ] `finish_transcription_replace`
- [ ] `finish_transcription_replace_from_artifact`
- [ ] `mark_model_call_failed`
- [ ] `insert_identifications`
- [ ] `replace_identifications`
- [ ] `replace_audio_segments`

### Cleanup — 6

- [ ] `cleanup_missing_audio_paths`
- [ ] `clear_post_processing_data`
- [ ] `clear_post_processing_data_keep_transcript`
- [ ] `prepare_post_for_auto_retry`
- [ ] `cleanup_processed_post`
- [ ] `cleanup_processed_post_files_only`

### System — 3

- [ ] `ensure_active_run`
- [ ] `update_discord_settings`
- [ ] `update_combined_config`
