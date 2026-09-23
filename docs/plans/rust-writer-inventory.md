# Rust writer migration inventory

Verified against refreshed CodeGraph index (340 files, 5,795 nodes, 8,705
edges) and targeted caller inspection on checkout
`6a64893d1fc3d25fd3e25be44e93685165ab8667`. The registry contains 57 named
actions. `T` means `wait=True`; `F` means `wait=False`. Unless noted, IDs are
integers, timestamps cross the future JSON boundary as naive UTC ISO strings,
and failures are returned as `WriteResult(success=False, error=...)`.

## Transport and generic operations

`WriterClient.action/create/update/delete` call `submit`. The wrappers default
to `wait=True`; `submit` itself defaults to false. A waiting caller uses a
per-thread Manager reply queue, drains stale results, correlates command IDs,
and applies `PODLY_WRITER_TIMEOUT_SECONDS` (30 seconds by default). A nonwaiting
caller performs an unbounded queue put and returns `None`; execution failure is
visible only in writer logs. A single executor loop serializes commands and
normally commits once per top-level command or rolls back on failure.

| Operation | Production callers / mode | Parameters and result | Persistence and compatibility | Required parity cases | Port status |
| --- | --- | --- | --- | --- | --- |
| `submit` | wrappers only | UUID command; F returns `None` after put; T returns matching result; timeout is outcome-unknown | BaseManager/pickle; UTF-8 `PODLY_IPC_AUTHKEY`, default `podly_secret`; unbounded global queue | auth/connect, stale/late result, timeout after commit, concurrent threads, restart, no replay | Not started |
| Generic `CREATE` | none | model + data; returns `{id}` if present | no reachable caller; Rust rejects it before admission | inventory proves no caller; explicit non-port | Removed (no caller) |
| Generic `UPDATE` | Post/ModelCall/Feed; T except cost estimate backfill F | model, pk, data; success data is null; absent row fails; unknown fields ignored | static table/field/type allowlists; no wire value becomes an identifier | field codecs, absent row, ignored unknown, null vs missing, INTEGER/REAL | Ported |
| Generic `DELETE` | none | model + pk; absent succeeds | no reachable caller; Rust rejects it before admission | inventory proves no caller; explicit non-port | Removed (no caller) |
| Generic `TRANSACTION` | none | ordered commands; returns nested full result envelopes remotely | one outer commit; nested transactions unsupported; non-DB effects cannot roll back | order, failure after mutation, commit failure, mixed action/generic, nested rejection | Ported |

Reachable generic updates:

- `Post` (all T): processing managers and post/main routes update audio paths,
  duration, `transcript_word_timestamps`, whitelist state, refined boundaries and
  timestamps, plus processor-produced update maps.
- `ModelCall`: processing/LLM/token-usage callers update status, response,
  error, retry/service tier, token usage, and range fields (T). Estimated-cost
  backfill uses F and currently never increments its `updated` count because F
  always returns `None`.
- `Feed` (T): the settings route updates the validated strategy, filter string,
  fallback/profanity/auto-whitelist booleans, full-block text, and WhisperX
  confirmation fields.

## Named action registry

### Users

| Action | Callers / mode | Parameters, result, tables/defaults | Non-DB effects and parity cases | Port status |
| --- | --- | --- | --- | --- |
| `create_user` | bootstrap, auth, default aggregate user (T) | normalized username, password, role; `{user_id}`; User ORM timestamps/defaults | compatible randomized password hash; duplicates, invalid role/password, commit failure | Not started |
| `update_user_password` | auth (T) | user id/password; `{user_id}`; User | compatible hash verification; missing/empty/rollback | Not started |
| `delete_user` | auth (T) | user id; `{deleted}`; tokens then User/cascades | absent, memberships/relationships, tokens; last-admin guard remains caller-side | Not started |
| `set_user_role` | auth (T) | user id + `admin|user`; `{user_id}` | both roles, invalid/missing; last-admin guard remains caller-side | Not started |
| `set_manual_feed_allowance` | auth (T) | user id + int-coercible/null allowance; `{user_id}` | missing vs null, strings, invalid, missing user | Not started |
| `upsert_discord_user` | Discord callback (T) | Discord id/name, allow-registration; `{user_id,created}`; User defaults/unique suffix | collision/truncation, rename, disabled creation, duplicate race; Discord HTTP caller-side | Not started |
| `set_user_billing_fields` | billing summary/subscription/webhook (T) | user id + supplied billing fields; `{user_id}` | partial/null/zero, missing user; Stripe effects caller-side | Not started |
| `set_user_billing_by_customer_id` | Stripe webhook (T) | customer id + optional billing fields; `{updated,user_id?}` | unknown customer no-op, partial/null/zero | Not started |
| `update_user_last_active` | login/feed/audio (F) | user id; executor returns id/time | admission and async error visibility, timestamp, missing user | Not started |

### Feeds, memberships, and tokens

| Action | Callers / mode | Parameters, result, tables/defaults | Non-DB effects and parity cases | Port status |
| --- | --- | --- | --- | --- |
| `refresh_feed` | refresh pipeline (T) | feed id, updates/new/existing posts/dates; counts; Feed/Post/Job/Run | new/update/no-op, job creation, duplicate/constraint, fractional duration, rollback | Not started |
| `add_feed` | add-or-refresh (T) | feed map/posts/dates; `{feed_id}`; Feed/Post/Job, UUID/stage defaults | empty/full, whitelisted jobs, bad date, uniqueness rollback | Not started |
| `update_feed_settings` | no production client | feed id + optional auto-whitelist; `{feed_id}` | explicit reachability/removal decision; missing/null/bool | Not started |
| `increment_download_count` | audio/download helper (F) | post id; executor `{post_id,updated}`; atomic coalesce + 1 | null/missing/concurrent increments; async error | Not started |
| `whitelist_post` | auto-process-on-download (T) | post id; `{post_id,updated}` | missing/already true/false | Not started |
| `ensure_user_feed_membership` | feed utilities (T) | feed/user ids; `{created,previous_count}`; UserFeed | existing/new, prior count, FK/race | Not started |
| `remove_user_feed_membership` | exit/leave (T) | feed/user ids; `{removed}` | absent/present | Not started |
| `whitelist_latest_post_for_feed` | first-member helper (T) | feed id; `{updated,post_guid?}` | empty, already true, null/equal dates | Not started |
| `toggle_whitelist_all_for_feed` | main/post routes (T) | feed id + required bool-coerced status; count | true/false, empty, missing vs null | Not started |
| `create_dev_test_feed` | dev helper (T) | RSS/title/metadata/count/prefixes; `{feed_id,created}` | repeat idempotence, count zero/default, UUID/job history, uniqueness | Not started |
| `delete_feed_cascade` | feed DELETE T; admin cleanup F | feed id; `{deleted,feed_id?}`; ordered child/feed batch deletes | caller unlinks files/directories first; absent, large batches, FK rollback, partial filesystem/DB | Not started |
| `create_feed_access_token` | auth/share/aggregate routes (T) | user id + nullable feed id; token id/secret | CSPRNG, UUID, SHA-256, persisted secret; reuse/aggregate/FK/hash | Not started |
| `touch_feed_access_token` | token auth (F) | token id + optional secret; executor `{updated}` | active/revoked/missing; timestamp/secret backfill; async error | Not started |

### Jobs

| Action | Callers / mode | Parameters, result, tables/defaults | Non-DB effects and parity cases | Port status |
| --- | --- | --- | --- | --- |
| `dequeue_job` | JobsManager (T) | optional run id; null or job/post; FIFO pending to running | empty, running blocks, FIFO, concurrent claim, run assignment | Not started |
| `cleanup_stale_jobs` | JobsManager (T) | numeric age default 3600; count | cutoff boundary, related rows/FKs, rollback | Not started |
| `clear_all_jobs` | uncalled manager method (T if used) | no args; bare count | reachability decision, empty/mixed | Not started |
| `clear_active_jobs` | web startup (T) | no args; bare count; pending/running delete + run recount | terminal preservation, empty, counters | Not started |
| `create_job` | status manager/auto-retry (T) | job map + optional ISO time; `{job_id}`; UUID/stage defaults | minimal/full, supplied history, bad date/FK, duplicate | Not started |
| `create_job_if_missing` | no production client | job map + post GUID; `{job_id,skipped}` | active/terminal existing, absent, reachability decision | Not started |
| `cancel_existing_jobs` | status manager (T) | post/current job ids; deleted count; active jobs + ModelCalls | none/current exclusion, pending/running, model-call statuses | Not started |
| `update_job_attribution` | JobManager (T) | job id + optional run/requested/billing ids; `{changed}` | idempotent partial/null, requested-only-if-null, missing/FK | Not started |
| `update_job_status` | status manager (T) | status/step/name/progress/total/error; status result | timestamps, stage-history only on step change, run recount; all states/repeat/zero/errors | Not started |
| `mark_cancelled` | status manager (T) | job id + default/custom reason; cancelled result | default/custom, repeat, missing | Not started |
| `mark_classification_parse_error` | processor (T) | job id; `{job_id}` | idempotent/missing | Not started |
| `record_ad_windows_count` | processor (T) | job id + optional int count; `{job_id}` | null/zero/positive/invalid/missing | Not started |
| `mark_auto_retry_attempted` | processor (T) | job id; `{job_id}` | idempotent/missing | Not started |
| `reassign_pending_jobs` | JobsManager (T) | run id; bare count | falsey run, none/mixed/already assigned, recount | Not started |

### Processor persistence

| Action | Callers / mode | Parameters, result, tables/defaults | Non-DB effects and parity cases | Port status |
| --- | --- | --- | --- | --- |
| `upsert_model_call` | classifier/LLM/refiners/INA (T) | post/model/range/prompt; `{model_call_id}`; unique ModelCall | uniqueness race internally rolls back; create/reuse states and prior-transaction interaction | Not started |
| `delete_model_calls_for_post_by_model_name` | INA (T) | post/model; deleted count | none/multiple, required fields, dependents | Not started |
| `upsert_whisper_model_call` | transcription manager (T) | post/model/ranges/prompt/reset map; id | `hasattr` reset fields; uniqueness race internally rolls back; default/custom/reuse | Not started |
| `replace_transcription` | no production client/composite | post/segments/model id/word JSON; counts | delete+insert+finish; empty/malformed, partial rollback, precision, reachability | Not started |
| `start_transcription_replace` | transcription manager (T) | post + optional call; deleted count | deletes identifications/segments, clears words/resets call; missing cases/rollback | Not started |
| `insert_transcript_segments` | transcription batches (T) | post + segments; inserted count | batch size env, skip nondicts, GC; empty/large/order/Unicode/floats/FK/rollback | Not started |
| `finish_transcription_replace` | dynamic finish action (T) | post/call/count/normalized words; counts | Post JSON + ModelCall success/range; zero/large/malformed/missing | Not started |
| `finish_transcription_replace_from_artifact` | dynamic finish action (T) | above + artifact path | allowed-root validation, JSON read, Rust normalize helper, temp unlink; traversal/missing/bad JSON/fallback/cleanup | Not started |
| `mark_model_call_failed` | transcription/processor (T) | call id/status/error; `{updated,...}` | absent, default/custom, null/Unicode | Not started |
| `insert_identifications` | classifier (T) | list of segment/call/label/confidence; inserted | batched insert-or-ignore + GC; empty/nondict/duplicate/FK/large/numeric | Not started |
| `replace_identifications` | classifier (T) | delete ids/new rows; requested-delete count + inserted | requested rather than actual delete count; duplicates/invalid/rollback-after-delete | Not started |
| `replace_audio_segments` | INA (T) | post/list label/start/end/call; count | delete+batch, skips end<=start, GC; empty/invalid/large/fractional/rollback | Not started |

### Cleanup

| Action | Callers / mode | Parameters, result, tables/defaults | Non-DB effects and parity cases | Port status |
| --- | --- | --- | --- | --- |
| `cleanup_missing_audio_paths` | JobsManager refresh (T) | no args; changed count; Post/latest terminal Job | filesystem existence/legacy candidates; existing/missing, job states, large JSON | Not started |
| `clear_post_processing_data` | full reprocess (T) | post id; `{post_id}`; chunk deletes and clears all derived fields | files remain; full graph/large chunks/missing/rollback | Not started |
| `clear_post_processing_data_keep_transcript` | keep-transcript reprocess (T) | post id; preserves transcript/Whisper/words, clears other output | mixed calls, reusable transcript, large graph, rollback | Not started |
| `prepare_post_for_auto_retry` | zero-ad retry (T) | post id; clears non-Whisper/derived state | deletes processed-audio candidates before commit; missing/unlink error/DB failure after unlink | Not started |
| `cleanup_processed_post` | no production client | post id; full clear + unwhitelist/recount | despite name does not unlink; reachability/graph/files remain/rollback | Not started |
| `cleanup_processed_post_files_only` | scheduled/manual cleanup (T) | post id; clears paths/unwhitelists | unlinks both paths first; missing/same/invalid/unlink error/DB failure after unlink | Not started |

### System/configuration

| Action | Callers / mode | Parameters, result, tables/defaults | Non-DB effects and parity cases | Port status |
| --- | --- | --- | --- | --- |
| `ensure_active_run` | JobsManager init/start/enqueue (T) | trigger/context JSON; `{run_id}`; singleton run | logs context keys; absent/existing/stale/concurrent/context | Ported |
| `update_discord_settings` | Discord config PUT (T) | supplied config fields; `{updated}`; singleton id 1/now | web separately reloads; create/partial/null/env filtering/secret redaction | Ported |
| `update_combined_config` | config PUT (T) | six optional nested sections; current config/result | **current explicit multi-commit exception** preserved; web owns runtime hydration/reset and now reconciles scheduler state after every attempted save | Ported |

## Transaction and bootstrap exceptions

- `update_combined_config` is not atomic today: each section commits separately.
  A later failure can leave earlier sections committed. The writer process
  hydrates its configuration, may reschedule/remove jobs, and resets a loaded
  processor singleton. The web route separately hydrates and resets its process.
- `upsert_model_call` and `upsert_whisper_model_call` catch a flush uniqueness
  error and call `session.rollback()` before re-querying. If composed inside a
  generic transaction this can erase prior subcommand work.
- Filesystem effects precede commit for auto-retry and files-only cleanup. Feed
  deletion callers remove audio/directories before the writer cascade. Artifact
  transcription reads files and creates/removes a normalized temporary file.
- Local-test transaction fallback returns only subcommand `.data`; the remote
  executor returns full nested result envelopes.
- `create_writer_app()` runs Alembic, bootstraps the admin, then initializes and
  hydrates configuration before the executor loop. Fresh authenticated bootstrap
  can call `create_user` through the writer queue before that loop consumes,
  leading to a timeout. P3 must extract this into an exclusive one-shot owner.

## Reachability gate

Refreshed CodeGraph plus AST caller validation found 52 named-action references
(51 literals plus the dynamic transcription `finish_action`). The five registry
gaps are `update_feed_settings`, `create_job_if_missing`,
`replace_transcription`, `cleanup_processed_post`, and `clear_all_jobs` behind an
otherwise uncalled manager method. Generic CREATE, DELETE, TRANSACTION, and
direct `submit` have no production callers. These remain inventory rows until
P2.8 makes their retention or removal explicit and machine-checkable.
