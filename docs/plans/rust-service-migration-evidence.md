# Rust service migration evidence

Evidence is recorded against synthetic fixtures and isolated containers unless an
entry explicitly says it is a read-only observation of the existing local
container. No entry authorizes a deployment or a write to production data.

## 2026-09-23 P3/P4 isolated integration increment

2026-09-24 P4.5 first rollback rehearsal is not accepted:
`/tmp/podly-rust-migration-p4-rollback-ci-20260924.log` passed ordinary CI
(1028 Python tests/2 skipped, Rust checks/tests, registry) and built a unique
isolated image/volume. It persisted synthetic pending/running jobs through the
real Rust client, stopped the Rust stack, created a quiesced SQLite backup,
verified integrity/schema revision/ORM columns, and then exited 137 just after
starting the Python writer. No pending-job recovery result was recorded; the
script's cleanup trap removed its uniquely named resources. The next task is
to capture Python container state/OOM/exit diagnostics on failure, fix the
rehearsal, and rerun only through `./scripts/ci.sh --writer-rollback`. Do not
mark P4.5 from this partial run.

2026-09-24 P3 exit gate: the real Rust-writer post-commit response-loss case
passed in `/tmp/podly-rust-migration-p3-real-commit-ci-20260924-2.log` (Ruff,
ty, 1028 Python tests passed/2 skipped, Rust formatting/check/tests, registry
gate). A synthetic proxy forwards one authenticated action to the real
isolated Rust server, fully receives its success after SQLite commit, then
drops only the downstream response. The selected production `WriterClient`
reports an unknown outcome with the forwarded command ID; independent SQLite
inspection confirms exactly one committed mutation. A subsequent valid
command succeeds with a distinct ID and a second mutation; the proxy saw
exactly two requests, proving no transparent replay. Local Python execution
is trapped. Existing adapter cases cover stale/late/mismatched replies,
partial response, failed→valid sequence, concurrent correlation, and restart.
P3.3 is checked; with the earlier P3.1–P3.2/P3.4–P3.8 evidence, P3 exits on
isolated fixtures. The first CI attempt `...-20260924.log` passed all Python
tests but exited after a transient concurrent edit to `scripts/ci.sh`; the
stable rerun above is the acceptance evidence.

2026-09-24 P3 audit: the green
`/tmp/podly-rust-migration-p2-p3-audit-ci-20260924.log` also exercises selector,
Rust `WriterClient` transport, five documented admission-only `wait=False`
caller shapes, response protocol mismatch, no-local-fallback behavior, the
one-shot bootstrap tests, and a real Flask route plus synthetic job
create/progress/complete against an isolated Rust writer. The post-merge
`/tmp/podly-rust-migration-main-merge-container-ci-20260924.log` additionally
verified bootstrap→readiness→web ordering, no persistent bootstrap/Python
writer, sequential same-volume startup, non-root UID, and fail-closed
bootstrap. P3.1, P3.2, and P3.4–P3.8 pass their task gates. P3.3 remains open:
the current timeout-after-commit/no-replay adapter test uses a simulated HTTP
peer, not a real Rust writer with a committed SQLite row before the reply is
lost. An isolated real-server case is required before the P3 exit gate.

2026-09-24 P2 exit gate: `/tmp/podly-rust-migration-p2-p3-audit-ci-20260924.log`
passed Ruff, ty, 1027 Python tests (2 skipped), Rust formatting/check/tests,
and the dynamic registry gate. This includes later P2.3 missing/invalid user
inputs and P2.4 real feed-token authentication against tokens emitted by both
writers: invalid secret, wrong feed scope, nonmember denial, member access,
aggregate ownership, revocation, and async touch, plus refresh/settings
no-ops. Existing differential cases cover all registered user and feed
actions and compare the independent cloned databases. With the earlier group
evidence below, all P2.1–P2.9 checkboxes now pass. The Python feed deletion
caller's separate filesystem cleanup was not exercised here because the
writer action itself only performs database cascades; no real files were
removed. The P3/P4 release gates remain separate and unchecked where their
specific evidence is incomplete.

2026-09-24 P2 audit follow-up: `/tmp/podly-rust-migration-p2-audit-ci-20260924-2.log`
passed Ruff, ty, 1021 Python tests (2 skipped), Rust formatting/check/tests,
and the registry gate. The preceding `...-20260924.log` stopped at a Ruff
branch-count finding in the new jobs matrix, corrected before the green run.
P2.1's explicit absent-row DELETE contract is now implemented for the static
Post/ModelCall/Feed generic allowlist; the deleted-row count is intentionally
ignored, and a differential case confirms Python and Rust both report success
without changing rows. Together with ordered nested transactions, ignored
unknown fields, absent UPDATE failure, and deferred commit-time rollback, this
closes P2.1. New job cases cover partial-update rollback and empty dequeue;
feed-token tests call the actual Python authenticator against Rust-created
tokens. P2.6 also passes its group gate: all 12 registered processor actions
execute against both isolated writers; ordered/fractional transcript data,
9,000-word artifact imports, 64 MiB rejection, missing/malformed/symlink
artifact paths, duplicate/retry behavior, and per-RPC replacement success and
rollback are compared. The 64 MiB input limit bounds this writer path. These
tests prove the Rust writer's artifact path, not the legacy Python wrapper's
choice between its sidecar and fallback; no sidecar speedup is claimed.
P2.2's group gate is supported by combined-config/default/null/rollback
parity plus the real Rust-selected HTTP PUT/GET test proving web hydration,
processor reset, notifications setting visibility, and a fresh worker's
config read. P2.3's earlier verified cases include cross-language bcrypt
verification, defaults/roles/activity, billing and Discord edge cases, and
deletion relationship effects; a later audit added further invalid-input
cases, so its checkbox remains open until those new cases pass CI. P2.5's
group gate includes serial claim/requeue/cancel
semantics, stale-cutoff cases, empty dequeue, partial status-update rollback,
concurrent single-claim behavior, and cancellation-versus-late-completion.
P2.2 and P2.5 pass in the cited CI run. A later P2.4 audit added real
feed-token authentication checks and no-op branches, which are not yet in a
green run; P2.4 remains open. A green registry gate alone does not certify
these new branches. No live writer, database, or deployment was changed.

2026-09-24 P2 commit/recovery follow-up: the final
`/tmp/podly-rust-migration-p2-followup-ci-20260924-4.log` passed Ruff, ty,
1014 Python tests (2 skipped), Rust formatting/check/tests, and the live
registry gate. Earlier `...-2.log` exposed six new test comparator failures;
`...-3.log` passed all Python tests but stopped at Rust formatting, corrected
with `mise exec -- cargo fmt --manifest-path rust/Cargo.toml`. P2.1 now proves
ordered transaction results, allowlisted generic updates, unknown-field
ignore, explicit NULL, no-op, absent-row error, and full rollback at a real
deferred SQLite commit failure on both isolated clones. The deferred-FK test
mode is hidden and requires the existing test-actions flag; the production
writer still opens SQLite with foreign keys OFF, and a config unit test rejects
the FK flag alone. P2.7 now executes all six cleanup actions across isolated
path/predicate/missing-record/file cases, a 501-row relationship/chunk edge,
singleton recount, and a failed precommit unlink followed by Rust writer
restart and a successful retry. It compares DB rows and clone-local file
effects; no real audio path is used. P2.6 adds per-RPC success and failure
replacement sequences and symlink-escape artifact rejection, comparing every
stage and preserving exact parsed word-timestamp JSON despite the writers'
different JSON whitespace/escaping. The Python-side normalization wrapper's
sidecar execution path remains unproven by these cases, so no sidecar speedup
is claimed. P2.7 passes its group gate. P2.1 remains open while the plan's
explicit absent-row generic DELETE-success requirement is reconciled with the
current production-reachable generic allowlist; the P2 exit gate and P4
acceptance remain open.

2026-09-24 expanded P2 differential increment: three CodeGraph Explore agents
extended isolated generic/config, processor, and cleanup parity. The first
`/tmp/podly-rust-migration-p2-expanded-ci-20260924.log` stopped at Ruff
branch-count/style findings in new test comparators. The second `...-2.log`
passed Ruff/ty but found one invalid test fixture: an explicit-NULL generic
update targeted a non-nullable feed column. The case now seeds a non-null
nullable override on both clones and clears that value through both writers.
`/tmp/podly-rust-migration-p2-expanded-ci-20260924-3.log` passed the complete
wrapper (Ruff, ty, 1002 Python tests passed with 2 skipped, Rust
formatting/check/tests, registry gate).
New cases cover generic unknown-field/NULL/no-op/missing-row behavior,
config partial mutation and rollback, processor retry/artifact errors, and
cleanup selection, path/idempotence, relationship and restart/retry recovery.
P2.1/P2.6/P2.7 remain unchecked pending deferred commit-time rollback,
multi-RPC replacement/symlink artifact, and cleanup checklist audits. No live
data, audio path, or deployment was used.

2026-09-24 main integration: fetched current `origin/main` (`5a0c283`) and
merged it into `rust-migrate-v2` as `9de04b3`, then restored the verified
uncommitted Rust increment. Conflicts in dependencies, startup/config,
writer client/service, and tests were resolved to keep both main's Apprise,
LiteLLM/GPT-6, and late-reply behavior and this branch's Rust adapter and
timing instrumentation. `uv.lock` was regenerated with `mise exec -- uv lock`
from the merged constraints. The first post-merge CI log
`/tmp/podly-rust-migration-main-merge-ci-20260924.log` stopped at three ty
redundant-cast diagnostics in an existing test. After removing those casts,
`/tmp/podly-rust-migration-main-merge-ci-20260924-2.log` passed the full
`mise exec -- ./scripts/ci.sh` wrapper: Ruff, ty, 983 Python tests (2
skipped), Rust formatting/check/tests, and the registry gate. CI also removed
14 obsolete `noqa: BLE001` comments in unrelated files; those mechanical
auto-fixes remain visible in the worktree for review. The pre-merge stash is
retained as a safety copy, and no push or deployment was performed.
The follow-up `/tmp/podly-rust-migration-main-merge-container-ci-20260924.log`
also passed the full wrapper plus the isolated Docker lifecycle gate after the
merge. It rebuilt the image from the combined tree, verified fresh bootstrap,
non-default UID, Rust executor readiness before web startup, same-volume
restart, dependent shutdown on writer death, and bootstrap fail-closed. The
script removed its uniquely named test image, containers, and volumes.
Next writer task: complete P2.6 artifact/processor negative and retry parity,
then P2.7 cleanup missing-file/interruption parity, re-run the full wrapper,
and only then audit P3 checkboxes. P4.4 still needs older-schema upgrade and
interrupted-command rehearsal; P4.5 rollback and P4.6 P0-comparable benchmark
remain unverified. No P4 acceptance checkbox was changed by this merge.

2026-09-24 parity follow-up: `/tmp/podly-rust-migration-parity-ci-20260924-7.log`
passed the complete `mise exec -- ./scripts/ci.sh` wrapper: Ruff/ty,
974 Python tests (2 skipped), Rust formatting/check/tests, and the registry
gate. The new isolated users, feeds, and jobs differential cases now pass.
The preceding `...-3.log` through `...-6.log` runs exposed fixture mistakes
and one genuine behavior mismatch: Rust-created pending jobs from feed refresh
had `step_name="Queued"` while Python persists SQL NULL (both retain the queue
label in stage history). The Rust field was corrected; completed developer
test jobs retain their completed step name. The eight-caller Python dequeue
comparison now models the production Python writer's serial execution loop;
without that ownership, direct parallel test sessions could claim several jobs
and were not a faithful baseline. No P2.6/P2.7 completion is claimed; further
branch and failure coverage is still required.

The later `/tmp/podly-rust-migration-p3-synthetic-ci.log` run passed Ruff and
ty, and the real-client integration test passed after extending it to create,
advance, and complete a synthetic processing job through the selected Rust
writer. Full CI did not pass: six newly added P2 jobs parity cases were picked
up while their case builder was still being edited and failed as `Unknown job
parity case`. Those in-progress cases must be finished and the full wrapper
rerun before any new checkbox is marked. The Python fallback trap and cloned
database isolation remain in the integration test.

Checkout `46bc812` plus current uncommitted changes; production backend
remains Python. `/tmp/podly-rust-migration-p3-launch-ci-4.log` passed Ruff,
ty, shell syntax, 935 Python tests (2 skipped), Rust formatting/check/tests,
and the live-registry gate. The new cases exercise a real Flask feed-settings
route and processing-status mutation through `WriterClient` and an isolated
Rust writer, with Python fallback trapped and the Python fixture clone
unchanged. A separate config test exercises the real PUT/GET route, web
in-place refresh and processor reset, and config hydration in a fresh Python
worker process. One-shot bootstrap subprocess tests passed sequential
idempotence, persisted-setting preservation, invalid auth/config, wrong DB
target, unknown schema revision, and non-root permission handling.

The first `mise exec -- ./scripts/ci.sh --writer-container` attempt is logged
at `/tmp/podly-rust-migration-p4-isolated-container-ci.log`. Ordinary CI
stages passed, the unique isolated image built, and fresh bootstrap migrated
the isolated database under UID/GID 12001. Rust writer started but readiness
correctly stayed HTTP 503 because `ActionRegistry::production_complete()` was
hardcoded `false`. This is a real P1.5/P4 lifecycle gate, not an accepted P4
result. The registry completeness check has since been changed to validate
all compiled action groups at runtime; the later CI/container run below passed.
The first test used a host `/tmp` bind mount; its fixture remains at
`/tmp/podly-rust-writer-container.lFABbi` because files are owned by the
container's remapped UID. The test now uses uniquely named Docker volumes so
future runs can remove their exact test resources without host-permission
workarounds. No production container, volume, port, or data was touched.
P2.1–P2.7, P3, and P4 remain unchecked pending their full gates.

The completed isolated rehearsal is
`/tmp/podly-rust-migration-p4-isolated-container-ci-4.log`: Ruff, ty, shell
syntax, 935 Python tests (2 skipped), Rust checks/tests, registry gate, and
the separate container lifecycle script all passed. The script built a
uniquely tagged image with both Rust binaries, used no host port or network,
and mounted only uniquely named disposable Docker volumes. It verified fresh
bootstrap under UID/GID 12001, full Rust executor readiness (not merely TCP),
Python-web startup after readiness, one-shot bootstrap and Python-writer
process retirement, same-volume restart without duplicate admin, dependent
container shutdown after Rust writer death, and failure before writer/web
startup when bootstrap lacks its admin password. The named test containers,
volumes, and image were removed by the script. P4.4 remains incomplete because
an older-schema upgrade and interrupted command have not been rehearsed in
the container; P4.5 rollback and P4.6 baseline-comparable benchmarks also
remain open. P4 checkboxes remain unchecked until the P0–P3 dependency gate
and each P4 task's full scope are accepted. No live deployment changed.

## P2 verification audit — differential parity still required

Task ID: P2.1–P2.8 audit (2026-09-22)

Commit/reference: Current uncommitted migration worktree; no deployment.

Files changed: This evidence file and the P2.1–P2.7 plan checkboxes.

Behavior preserved or intentionally changed: No runtime behavior changed. The
P2.1–P2.7 checkboxes were cleared because their existing entries prove isolated
Rust implementation tests, but not the plan's required execution of each
production-reachable operation against both Python and Rust on separate copies
of the same fixture. The current `test_writer_parity_fixtures.py` checks fixture
creation and cloning only; it does not execute either writer or compare results,
database rows, or side effects. The earlier CI logs remain valid for the narrower
claims stated in their entries, not for cross-backend parity or P2 acceptance.

Tests added and CI log path: Differential parity and registry-gate drafts were
added after this audit. The first coordinated `mise exec -- ./scripts/ci.sh` run
is recorded at `/tmp/podly-rust-migration-p2-early-ci.log`. It stopped at Ruff
with 16 remaining new-file lint errors after auto-fixing six; no parity tests
ran and this log is not acceptance evidence. An initial sandboxed CI attempt
failed before Ruff because `uv` could not write its home-directory cache; the
same command was rerun with approved escalation. Existing earlier CI logs are
listed in the individual P2 entries below.

Follow-up CI logs: `/tmp/podly-rust-migration-p2-early-ci-2.log` stopped at one
Ruff undefined name, and `...-3.log` passed Ruff but stopped at two `ty` errors
in the differential runner. `/tmp/podly-rust-migration-p2-early-ci-4.log` passed
Ruff and `ty`, then had 824 Python tests pass, 2 skip, and 66 new parity/race
tests fail at one shared harness error: `db.session.remove()` ran outside a Flask
application context before any Python action executed. That setup defect is
being fixed; the log does not prove a Rust/Python behavior difference and did
not reach Rust/registry CI stages.

`/tmp/podly-rust-migration-p2-early-ci-5.log` passed Ruff and `ty`, then
reached real differential execution. Pytest reported 17 failures in the new
feed/job/processor cases, while the other Python tests and many new parity cases
passed. The failures are under triage; some involve fixture aliasing and
incorrect projection-column assumptions, while processor state differences
still require investigation. CI stopped before the Rust and registry stages.

`/tmp/podly-rust-migration-p2-early-ci-6.log` passed Ruff and `ty`; pytest
reported 886 passed, 2 skipped, and 11 differential failures. Job parity and
the concurrent dequeue race now pass. Remaining failures are one feed case,
six processor cases, and four cleanup cases. Rust/registry stages were not
reached. The CI process is no longer running; the next task is to resolve these
specific failures and rerun the full wrapper.

`/tmp/podly-rust-migration-p2-early-ci-7.log` stopped at two Ruff B905 findings
in new diagnostics. After correcting them, `...-8.log` passed Ruff and `ty`
and reported 11 differential failures again. Value-free diagnostics narrowed
them to feed `post.release_date`, processor `post.transcript_word_timestamps`,
segment numeric values, and identification confidence, and cleanup differences
in one `post` row per failing case. Rust binary build provenance is under audit:
pytest runs before the Rust build stage, so the parity subprocess may have used
a stale binary after Rust source/feature changes. No acceptance checkbox changed.

`/tmp/podly-rust-migration-p2-fresh-binaries-ci.log` is the first run to build
both Rust binaries before pytest and pin their paths for parity execution. Ruff
and `ty` passed; all six prior processor failures and job/race cases passed.
Pytest stopped with five failures: feed creation's `post.release_date` and four
cleanup actions' JSON-backed `Post` columns. Rust/registry stages were not
reached. These are current-source parity findings, not stale-binary evidence.

On 2026-09-23, `/tmp/podly-rust-migration-p2-system-ci.log` built fresh Rust
binaries and ran 903 Python tests. It stopped with two differential failures:
the synthetic combined-config fixture omitted its required notifications row,
and the cleanup assertion expected SQL NULL where SQLAlchemy persists JSON
`"null"`. After correcting those test defects,
`/tmp/podly-rust-migration-p2-system-ci-2.log` passed 901 Python tests (2
skipped), including all differential cases, but stopped at Rust formatting.
`/tmp/podly-rust-migration-p2-system-ci-3.log` passed Ruff, ty, the same Python
suite, Rust formatting/checks/tests, then stopped at the deliberately
fail-closed registry coverage gate. The gate reports unmapped production
actions/generic operations and a dynamic action call at
`src/podcast_processor/transcription_manager.py:261`. These are coverage
metadata and inventory gaps, not parity test failures. CI is not yet green;
P2 checkboxes remain open until the manifest and remaining required gates pass.

`/tmp/podly-rust-migration-p2-registry-ci.log` is the first clean full CI run
after mapping the live registry and generic operations to executed differential
case IDs. Ruff, ty, 902 Python tests (2 skipped), Rust checks/tests, and the
fail-closed registry gate all passed. The checker now resolves the two literal
branches of the dynamic transcription finish action and still rejects any
nonliteral reassignment; a new unit test covers that boundary. P2.8 is checked.
P2.1–P2.7 remain unchecked pending a per-action checklist audit, and P2.9
mixed-client stress is not yet complete. No production backend was selected.

P2.9 partial (2026-09-23): `src/tests/test_writer_mixed_client_stress.py`
uses one isolated Rust writer and eight client threads to submit 32 real
web-like download-count and processing-like transcript-insert actions. It
asserts 32 distinct correlated command IDs, successful responses, and exact
persisted effects (+16 downloads and +16 segments). The first CI attempt
stopped at a test-only Ruff import error; the second stopped at a fixture
attribute error before issuing requests. After correcting both,
`/tmp/podly-rust-migration-p2-mixed-ci-3.log` passed Ruff, ty, 903 Python
tests (2 skipped), Rust checks/tests, and the registry gate. P2.9 remains
unchecked: bounded Rust memory under concurrent large payloads, explicit
SQLite lock contention, and combined restart/timeout stress still need
verification. No live service or database was touched.

Handoff at checkout `9ad73ae` plus the uncommitted worktree (2026-09-23): P0
and P1 remain verified; P2.8 has a clean gate and checkbox; P2.1–P2.7 and
P2.9 are not accepted; P3/P4 have not begun. The immediate next task is to
complete P2.9's mixed-operation memory, SQLite lock, and restart/timeout
cases through `mise exec -- ./scripts/ci.sh`, then audit each P2.1–P2.7
action against the plan's per-action checklist and record any coverage gaps
before advancing those checkboxes. After P2 acceptance, implement the explicit
Python/Rust selector and `WriterClient` transport adapter in P3; relevant
entrypoints are `src/app/writer/client.py`, `src/app/writer/protocol.py`,
`src/app/__init__.py::_run_app_startup`,
`src/app/auth/bootstrap.py::bootstrap_admin_user`, `docker-entrypoint.sh`,
and `rust/src/bin/podly_writer.rs`. No Rust backend cutover, deployment,
restart of the live instance, or production-data mutation has occurred.

P2.1–P2.7 follow-up audit (2026-09-23): the differential runner proves at
least one executed case per reachable action and compares results plus full
database projections, but its registry mapping does not prove the required
per-action branch matrix. Priority gaps are generic transaction ordering,
rollback and commit-constraint parity (P2.1); web-process config visibility
after Rust writes (P2.2); additional missing/repeat/boundary user, token,
feed, job, processor artifact, and cleanup failure cases (P2.3–P2.7).
Specifically, artifact failures need missing/malformed/disallowed/oversize
comparison, and cleanup needs interrupted recovery. None of these port-group
checkboxes was advanced. This audit is read-only evidence, not a passing gate.

P3.5 bootstrap draft (2026-09-23): `create_bootstrap_app()` and
`src/bootstrap.py` provide a one-shot role that initializes migrations, admin
and settings without HTTP, scheduler, or writer IPC; bootstrap settings errors
are fail-closed, while the existing writer app behavior is retained. The
bootstrap role uses exclusive direct DB writes only before the runtime writer
starts. Focused tests passed through the combined CI log above, but this does
not establish P3.6 ordering/exclusivity or P3.7 idempotence. P3.5 remains
unchecked until verification and lifecycle checks pass.

Additional unverified P2 drafts (2026-09-23): P2.9 tests now include an
eight-client 4,096-segment synthetic burst with post-burst RSS check,
deterministic queue saturation, SQLite lock timeout/unknown outcome followed
by exactly one commit, rollback, and restart. P2.1 adds five differential
cases for reachable generic UPDATE and ordered/rollback transactions,
including a NOT NULL constraint. The latter surfaced a Rust/Python transaction
result-envelope mismatch; the Rust fix and differential cases subsequently
passed coordinated CI. P2.1 remains unchecked pending the full action audit.

P3 adapter draft (2026-09-23): a shared `PODLY_WRITER_BACKEND` parser and
Rust branch in `WriterClient` were added with isolated fake-loopback tests.
The intended behavior is Python by default; unknown backend fails, Rust mode
never executes Python local fallback, `wait=False` returns admission only,
and timeouts after admission are unknown outcomes without replay. This code
passed fake-loopback CI, but has not yet been exercised against the real Rust
writer; P3.1–P3.4 remain unchecked.

Full CI after the transaction and stress increments:
`/tmp/podly-rust-migration-p2-p3-combined-ci-6.log` passed Ruff, ty, 926
Python tests (2 skipped), Rust format/check/tests, and the registry gate.
The five new P2.9 tests passed on isolated fixture DBs: eight concurrent
real action clients with 32 unique replies and exact counts; 4,096 large
synthetic transcript rows at concurrency eight with less than 48 MiB
post-burst RSS growth; bounded admission rejects saturation while preserving
the active reply; a 150 ms deadline under SQLite `BEGIN IMMEDIATE` reports an
unknown outcome, then commits exactly once after unlock; and a mixed-command
rollback followed by restart accepts a fresh write. Ordered subcommand result
and rollback parity are also checked by five new P2.1 differential cases.
P2.9 is checked. P2.1 stays open because the wider per-operation checklist
audit remains incomplete. The fake-loopback Rust adapter and bootstrap tests
pass, but P3 remains unchecked pending real-client/bootstrap lifecycle gates.

Remaining limitations: Finish the P2.1–P2.7 branch audit;
then finish actual-client P3 integration and isolated bootstrap sequencing.
P4 packaging, lifecycle, rollback, and benchmarks have not begun.

## P0.1 — Baseline revision and deployment

Task ID: P0.1

Commit/reference: Checkout `6a64893d1fc3d25fd3e25be44e93685165ab8667`
(`rust-migrate-v2`, commit timestamp 2026-09-20T12:21:23-05:00). The only
pre-existing working-tree change was the untracked
`docs/plans/rust-service-migration-plan.md` supplied for this migration.

Files changed: `docs/plans/rust-service-migration-evidence.md` and the P0.1
checkbox in `docs/plans/rust-service-migration-plan.md`.

Behavior preserved or intentionally changed: Documentation only; no runtime
behavior changed. The checked-out source and deployed image are recorded as
separate artifacts:

- Local container `podly-pure-podcasts` was healthy and running image
  `sha256:7939367617b995585977e7fb379972743d0ccfae46766c9bb7a0358b4b00c426`,
  created 2026-09-20T12:28:08-05:00. The image has no source-revision label.
- Deployed copies of `app/writer/service.py`, `app/writer/client.py`, and
  `scripts/start_services.sh` matched checkout SHA-256 checksums. This is useful
  provenance evidence but is not a claim that every image file matches the
  checkout.
- The observed persistent process roles were Bash supervisor
  (`scripts/start_services.sh`), Python writer (`python3 -u -m app.writer`), and
  Python web/scheduler (`python3 -u src/main.py`). Read-only process inspection
  observed about 97,600 KiB writer RSS and 117,232 KiB web RSS. A separate
  `docker stats --no-stream` sample reported 188.7 MiB container memory, 51
  PIDs, and 4.97% CPU. These single observations are not the P0.6 benchmark.
- Docker Compose publishes only web port 5001. The writer uses the existing
  loopback IPC port 50001. Health currently probes only HTTP `/` with Python.
- All currently configured `PODLY_RUST_*_ENABLED` flags were `true`: audio,
  chapters, chapter fallback, costs, feed posts, feed refresh, feed XML, jobs,
  profanity, statistics, transcript, word boundary, and ad merge. The deployed
  helper is `/app/bin/podly_tools`; its SHA-256 is
  `6a7d9763ff3bbb3a663d48d1213703f770465cf7bc2d6e855872b4fea6a2fdba`.
- Other relevant non-secret deployment settings were `SERVER_THREADS=32` and
  `PODLY_WRITER_IDLE_TRIM_INTERVAL_SEC=900`. Configuration names were captured
  from the container without recording credentials or their values.
- Checkout tools resolved through mise: mise 2026.9.10, rustc 1.98.1, Cargo
  1.98.1, Python 3.14.4, uv 0.10.2, Node 20.20.2, and npm 10.8.2. The runtime
  image reports Python 3.14.7. The Dockerfile currently uses floating builder
  tags (`rust:1-slim`, `node:18-alpine`) and pins uv 0.11.26 in the image.

Tests added and CI log path: No tests were required for this documentation-only
task. Commands were read-only (`git`, mise-managed version probes, Docker
inspect/top/stats/exec checksum probes); no CI run yet.

Parity/benchmark evidence, if applicable: Not applicable. The process RSS and
container stats above are identification samples only. P0.6 will establish the
reproducible multi-run baseline.

Remaining limitations: The deployed image does not identify its Git revision,
and no claim is made that it was built from the full checkout despite the three
matching source checksums. Builder toolchain patch versions are not recoverable
from the final image. Add immutable source-revision/build-toolchain labels during
packaging if required for P4 operational provenance.

## P0.4 — Trustworthy CI failure propagation

Task ID: P0.4

Commit/reference: Working tree based on
`6a64893d1fc3d25fd3e25be44e93685165ab8667`.

Files changed: `scripts/ci.sh`,
`docs/plans/rust-service-migration-plan.md`, and this evidence file.

Behavior preserved or intentionally changed: Added Bash fail-fast, unset-variable,
ERR-trap, and pipeline propagation (`set -Eeuo pipefail`) at the CI entrypoint.
All existing formatting, lint, type, Python test, Rust format/clippy/test, and
optional `--int` stages remain in their existing order. Future Python writer
contract tests under pytest and Rust writer tests under Cargo therefore run
through this entrypoint without another runner path.

Tests added and CI log path: A temporary `false` immediately after the Ruff
format stage produced exit status 1 in
`/tmp/podly-rust-migration-p0.4-intentional-failure.log`; the log contains no
Ruff-check-stage banner, proving later success cannot mask that failure. The
temporary probe was removed. A clean `mise exec -- ./scripts/ci.sh` run exited 0
and is recorded at `/tmp/podly-rust-migration-p0.4-clean.log`: Ruff and ty passed,
pytest reported 794 passed/2 skipped, and Cargo reported 97 passed.

Parity/benchmark evidence, if applicable: Not applicable.

Remaining limitations: Integration workflow checks remain opt-in through the
preserved `--int` argument. Rust writer subprocess/container checks added in P1
and later must be wired into the appropriate default or integration section as
their contracts are introduced.

## P0.2 — Writer inventory

Task ID: P0.2

Commit/reference: Working tree based on
`6a64893d1fc3d25fd3e25be44e93685165ab8667`; refreshed CodeGraph index of 340
files, 5,795 nodes, and 8,705 edges.

Files changed: `docs/plans/rust-writer-inventory.md`,
`docs/plans/rust-service-migration-plan.md`, and this evidence file.

Behavior preserved or intentionally changed: Documentation only. The inventory
records every registered action, transport/generic semantics, production caller
and wait mode, result/error shape, affected state/defaults, non-database effects,
parity cases, transaction exceptions, and startup/bootstrap ownership.

Tests added and CI log path: No runtime test was needed. A refreshed CodeGraph
registry query and targeted AST caller validation found exactly 57 registered
actions, 51 literal action references plus one dynamic transcription finish
action, and five reachability gaps. A table-row check found 57 named actions plus
the separately inventoried `submit` row, with no duplicate action rows.

Parity/benchmark evidence, if applicable: The inventory identifies the required
per-action parity cases for P2. It confirms production generic mutation is
UPDATE-only on Post, ModelCall, and Feed; there are no production callers of
generic CREATE, DELETE, TRANSACTION, or direct `submit`.

Remaining limitations: Five registered actions lack direct production callers:
`update_feed_settings`, `create_job_if_missing`, `replace_transcription`,
`cleanup_processed_post`, and `clear_all_jobs` behind an otherwise uncalled
manager method. P2.8 must make each retention/removal decision executable. The
document also records current non-atomic and non-database side effects; the Rust
port must preserve documented behavior unless the plan is explicitly revised.

## P0.3 — HTTP and worker inventory

Task ID: P0.3

Commit/reference: Working tree based on
`6a64893d1fc3d25fd3e25be44e93685165ab8667`; refreshed CodeGraph index followed
by targeted decorator and worker-entrypoint validation where the graph omitted
requested app-factory/background source.

Files changed: `docs/plans/rust-http-worker-inventory.md`,
`docs/plans/rust-service-migration-plan.md`, and this evidence file.

Behavior preserved or intentionally changed: Documentation only. The inventory
contains all 77 declared method/path combinations across nine blueprints with
access rules, request/response and important header behavior, writer/background
or external effects, existing Rust reuse/fallback, and parity risks. It also maps
the actual shell supervisor, writer, web, APScheduler callbacks, JobsManager,
opportunistic/request threads, processing/pricing/Rust/ffmpeg/INA helpers, and
their lifecycle and recovery semantics.

Tests added and CI log path: No runtime test was required. An AST decorator
recount through mise produced exactly 77 route decorators and 77 method/path
rows: auth 9, billing 4, config 6, costs 6, Discord 5, feed 17, jobs 7, main 5,
and posts 18. CodeGraph discovery and targeted entrypoint inspection supplied
the worker ownership map.

Parity/benchmark evidence, if applicable: Not applicable. Existing Rust-backed
read paths and their silent fallback behavior are called out per route so P0.6
and later gates require positive execution evidence.

Remaining limitations: The inventory intentionally records current weak spots
rather than changing them: `/health` is not explicit, shutdown is not graceful,
startup deletes active jobs and the scheduler store, processing descendants lack
process-group ownership, and explicit refresh threads are unbounded. These become
P4/P7 lifecycle requirements. External provider contracts require mocks rather
than live calls in parity testing.

## P0.5 — Isolated parity fixtures

Task ID: P0.5

Commit/reference: Working tree based on
`6a64893d1fc3d25fd3e25be44e93685165ab8667`.

Files changed: `src/tests/writer_parity_fixtures.py`,
`src/tests/test_writer_parity_fixtures.py`, `src/tests/conftest.py`,
`docs/plans/rust-service-migration-plan.md`, and this evidence file.

Behavior preserved or intentionally changed: Added test-only, migration-built
writer parity fixtures. A session snapshot applies the current Alembic schema to
an absolute pytest-temporary database, enables foreign keys, seeds deterministic
synthetic ORM records, checkpoints/closes SQLite, and exposes a manifest of
present and deliberately missing IDs. A function-scoped pair clones the source
into independent Python/Rust databases using SQLite's backup API and gives each
backend separate instance, input, service-output, and artifact paths. It never
uses `src/instance`, live credentials, or a writable live mount.

The seed covers two feeds, membership, active/aggregate/revoked tokens, two
posts, linked transcript/model-call/identification/audio rows, a run with
completed/running/cancelled jobs, more than 512 KiB of processing JSON, smaller
JSON boundary/history/context fields, missing-record sentinels, and both INTEGER
and REAL storage classes in `post.duration`.

Tests added and CI log path: Three fixture tests verify schema/integrity/FKs and
required content, source/Python/Rust path and mutation isolation, and normalized
logical equivalence after backend-specific path rebasing. The first CI attempt
exposed and corrected pytest 9's nested `pytest_plugins` restriction; fixtures
are now explicitly re-exported by the existing conftest. Final
`mise exec -- ./scripts/ci.sh` log:
`/tmp/podly-rust-migration-p0.5-clean.log` — Ruff and ty passed, pytest 797
passed/2 skipped, Cargo 97 passed.

Parity/benchmark evidence, if applicable: SQLite `integrity_check` is `ok`,
`foreign_key_check` is empty, `alembic_version` is present, the two clone
projections match after path normalization, and a committed Python-only mutation
and artifact are absent from both the Rust clone and source snapshot.

Remaining limitations: This is the common seed/clone layer, not per-action P2
parity coverage. P1/P2 tests must launch each implementation against only its
assigned clone and extend the manifest for newly discovered action-specific
edges without weakening isolation.

## P0.6 — Baseline performance

Task ID: P0.6

Commit/reference: Instrumented local image
`sha256:0877199bf9794c93cd52b2006d1c5274a931ce9254d2b09b62ed4e2904994322`,
built from checkout `6a64893d1fc3d25fd3e25be44e93685165ab8667` plus the
measurement-only working-tree changes recorded here. Synthetic fixture SHA-256:
`2ff695d7df8c86cca670890122d95a962a7da63a44006bd1ef3261ae1d7d3323`.

Files changed: `scripts/bench_service_migration.py`,
`scripts/bench_writer_service.py`, `scripts/create_service_migration_fixture.py`,
`src/app/writer/protocol.py`, `src/app/writer/client.py`,
`src/app/writer/service.py`, `.env.local.example`, fixture/benchmark tests,
`docs/plans/rust-service-migration-plan.md`, and this evidence file.

Behavior preserved or intentionally changed: Added opt-in, redacted writer
timing (`PODLY_WRITER_TIMING_LOG=false` by default). Each command records only
command ID, operation/action name, admission-to-dequeue time, executor time,
total time, and success; bodies, paths, SQL, and credentials are never logged.
The benchmark exporter and runner are test/operations tooling. Normal writer,
web, and sidecar behavior is unchanged when timing is disabled.

Benchmark isolation and protocol: Three independent containers used fresh
SQLite-backup clones and distinct temporary artifact trees under
`/tmp/podly-rust-writer-p0-baseline-20260920`; none mounted `src/instance` or
shared a database. Container names were unique, restart policy was disabled,
web ports were ephemeral loopback bindings, provider hostnames resolved to
loopback, and only synthetic credentials were supplied. Each container was
removed after its run. The live `podly-pure-podcasts` container was not
restarted or mutated.

Each run used c=8, 32 Waitress threads, a 200-post feed-post response, a
201-item aggregate RSS response, 30 seconds warmed idle, 30 seconds per HTTP
workload, 1,000 small writes, 12 large 2,000-segment/512+ KiB transcription
replacements, 100 mixed writes (90% small/10% large), and a fixed 30-second
cooldown after every workload. Resource sampling was configured at one-second
intervals via Docker stats plus host `/proc`; blocking stats calls yielded 17
idle samples per 30-second interval on this host. Metrics include container
memory/CPU/PIDs and per-process RSS/thread/FD identity.

Median-of-three results:

| Workload | Throughput | p50 | p95 | p99 | Errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Feed posts HTTP | 355.637 req/s | 18.772 ms | 44.210 ms | 67.857 ms | 0 |
| Aggregate RSS HTTP | 12.373 req/s | 645.967 ms | 848.228 ms | 925.342 ms | 0 |
| Small writer client E2E | 604.761 cmd/s | 11.400 ms | 12.313 ms | 19.341 ms | 0 |
| Large writer client E2E | 3.873 cmd/s | 1727.518 ms | 1993.871 ms | 2065.243 ms | 0 |
| Mixed writer client E2E | 36.497 cmd/s | 244.905 ms | 445.037 ms | 478.645 ms | 0 |

Writer admission-to-dequeue p95/p99 medians were 10.440/11.947 ms (small),
1688.453/1698.308 ms (large), and 268.161/474.790 ms (mixed). Executor p95
medians were 1.173, 217.105, and 196.373 ms respectively. Timing record counts
exactly matched submitted counts in every run and reported zero failures.

Warmed-idle container memory median was 183,081,370 bytes (174.6 MiB). Median
final post-cooldown process observations were:

| Process | RSS | Threads | FDs |
| --- | ---: | ---: | ---: |
| Python writer | 124,383,232 B | 8 | 14 |
| Python web | 121,827,328 B | 35 | 28 |
| Shell supervisor | 5,963,776 B | 1 | 4 |

Container-memory median/max-by-phase medians were 210,763,776/215,062,938 B
(feed posts), 190,526,259/192,308,838 B (RSS), 226,492,416/262,773,146 B
(small writes), 260,361,421/317,823,386 B (large writes), and
296,380,006/308,281,344 B (mixed writes). After 30 seconds the corresponding
cooldown medians were 206,674,330; 187,904,819; 189,163,110; 213,385,216; and
211,288,064 B. Median sampled CPU percentages for the active phases were
300.813, 105.604, 62.865, 69.375, and 87.885. Peak median thread/FD totals were
47/69 for feed posts and 61/55 for writer bursts.

Tests added and CI log path: Benchmark parsing, unit conversion, quantiles,
writer timestamping, structured timing (including logger suffixes), exporter
paths, contents, and isolation are covered through CI. Final
`mise exec -- ./scripts/ci.sh` log is
`/tmp/podly-rust-migration-p0.6-clean.log`: Ruff and ty passed, pytest 805
passed/2 skipped, and Cargo 97 passed. Image build log:
`/tmp/podly-rust-migration-p0.6-image-build.log`. Raw benchmark report:
`/tmp/podly-rust-writer-p0-baseline-20260920/report.json` (SHA-256
`2ec8584b9070e1326dabf4f02b343fc15351055e04004f3b236774cd58dc9af1`).

Parity/benchmark evidence, if applicable: Before measured traffic, direct calls
to `try_render_feed_posts` and `try_render_aggregate_feed_xml` returned bytes in
all three containers. All measured HTTP responses were 200. No feed/posts Rust
fallback line occurred. Final process lists contained only the shell supervisor,
Python writer, and Python web; transient benchmark clients exited before final
cooldown inspection.

Remaining limitations: Docker stats collection is blocking, so effective sample
cadence was slower than the configured one second. CPU is container-level;
per-process resource identity covers RSS, threads, and FDs. The fixture excludes
real provider latency and audio transcoding by design. Mixed-writer p95 varied
more than 10% across three runs; P4 must use at least three paired runs and expand
to five if that variability could change a gate decision.

## P0.7 — Writer acceptance thresholds

Task ID: P0.7

Commit/reference: Thresholds fixed after baseline characterization and before
any Rust-writer comparison or production-default change.

Files changed: `docs/plans/rust-service-migration-evidence.md` and
`docs/plans/rust-service-migration-plan.md`.

Behavior preserved or intentionally changed: Documentation only. P4 must repeat
the same image configuration, fixture checksum/profile, three fresh clones,
c=8, workload counts/durations, sampling configuration, cooldowns, and positive
path checks. Use paired medians. Expand to five runs when more than 10% spread in
a gating metric could reverse pass/fail.

Acceptance thresholds:

- Correctness: zero unexpected/non-200 HTTP responses, writer failures,
  timeouts, correlation errors, or relevant fallback lines; exact semantic and
  process-identity gates remain mandatory regardless of performance.
- Memory: P4 median warmed-idle total container memory must fall by at least
  50 MiB **and** 25% from 183,081,370 B (therefore at most 130,887,680 B and,
  due to the absolute target, at most 130,652,570 B). Rust-writer RSS must be at
  least 60% below the 124,383,232 B Python-writer median (at most 49,753,293 B).
- Feed-post HTTP: p95 at most 49.210 ms, p99 at most 81.428 ms, and throughput at
  least 320.073 req/s.
- Aggregate RSS HTTP: p95 at most 933.051 ms, p99 at most 1,110.410 ms, and
  throughput at least 11.136 req/s.
- Writer E2E: small p95/p99 at most 22.313/39.341 ms; large at most
  2,392.645/2,581.554 ms; mixed at most 534.044/598.306 ms. Large p95 may regress
  no more than 20%.
- Admission-to-dequeue: small p95/p99 at most 20.440/31.947 ms; large at most
  2,026.144/2,122.885 ms; mixed at most 321.793/593.488 ms. These are queue
  measurements, not aliases for client E2E latency.
- CPU efficiency: sampled container CPU normalized by completed request/command
  throughput may regress no more than 15% for each comparable workload.
- Recovery/resources: after each 30-second cooldown, P4 memory must be no more
  than its own warmed-idle median plus 10 MiB, final threads no more than idle +2,
  and final FDs no more than idle +8, with no monotonic growth across repetitions.
- Process retirement: after bootstrap and benchmark clients exit, the process
  list must show Rust writer + Python web (and shell supervisor if still used),
  with no `python -m app.writer`, bootstrap daemon, compatibility proxy, or
  lingering benchmark/processing helper. This gate cannot be traded for better
  latency or memory.

Tests added and CI log path: Documentation threshold review; no additional test.
The P0.6 clean CI and report above are the numeric source.

Parity/benchmark evidence, if applicable: Threshold arithmetic is based on the
median-of-three P0 values above, using absolute floors for small latencies as
specified. No Rust-writer result was consulted when choosing these thresholds.

Remaining limitations: The memory target is intentionally strict relative to
the isolated baseline; missing it blocks P4 acceptance rather than authorizing a
web migration to hide the shortfall. Provider/audio workloads remain separate
from this writer milestone.

## P1.1 — Writer RPC v1 specification

Task ID: P1.1

Commit/reference: Working tree based on
`6a64893d1fc3d25fd3e25be44e93685165ab8667` after the accepted P0 gate.

Files changed: `docs/contracts/writer-rpc-v1.md`, request/response/readiness JSON
Schemas, ten shared fixtures under `docs/contracts/writer-rpc/v1/`,
`src/tests/test_writer_rpc_contract.py`, `pyproject.toml`, `uv.lock`,
`docs/plans/rust-service-migration-plan.md`, and this evidence file.

Behavior preserved or intentionally changed: Documentation/contracts only. The
v1 contract fixes loopback endpoints, Base64URL UTF-8 shared-secret encoding and
constant-time comparison, strict operation-specific envelopes, request/queue/
connection/deadline/drain limits, wait true/false behavior, admission versus
execution states, unknown outcomes/no blind retry, transaction form, stable
sanitized errors, codecs, readiness/schema identity, exact HTTP mappings, and
graceful drain. Pre-envelope failures may omit the command ID; a deadline after
admission has an explicit HTTP 504 unknown-outcome response. The
16 MiB body/64 MiB aggregate queue limits are based on the measured 1,228,431
byte P0 processing payload rather than an arbitrary small limit.

Tests added and CI log path: Shared action/update/transaction requests and
accepted/success/failure/rejected responses validate against Draft 2020-12 JSON
Schemas. Negative tests reject extra envelope fields, nested transactions, and
duplicate object keys before validation. `jsonschema` is now a direct dev
dependency. `/tmp/podly-rust-migration-p1.1-contract-fix.log`: Ruff/ty passed,
pytest 818 passed/2 skipped, Cargo 97 passed.

Parity/benchmark evidence, if applicable: The fixtures explicitly cover async
admission, fractional numeric data, ignored legacy update fields, ordered mixed
transactions, rolled-back domain failure, pre-admission capacity rejection,
pre-envelope rejection without an ID, admitted timeout, and readiness identity.

Remaining limitations: Per-action parameter schemas remain governed by the P0
inventory and executable P2 parity cases; v1 intentionally specifies a strict
envelope rather than embedding 57 large action schemas in the transport schema.

## P1.2 — Rust writer binary and module boundaries

Task ID: P1.2

Commit/reference: Working tree after the verified P1.1 contract.

Files changed: `rust/Cargo.toml`, `rust/Cargo.lock`, `rust/src/lib.rs`,
`rust/src/bin/podly_writer.rs`, and focused modules under `rust/src/writer/` for
configuration, protocol, transport, database, actions, executor, and lifecycle.

Behavior preserved or intentionally changed: The existing implicit
`podly_tools` binary and its flags remain in `rust/src/main.rs` without a
wholesale refactor. A distinct `podly_writer` entrypoint now owns the service
namespace. It fails closed while transport is still incomplete. Configuration
binds loopback only, requires a nonempty IPC key, and resolves an explicit
existing database path; no production selector or default has changed.

Tests added and CI log path:
`/tmp/podly-rust-migration-p1.2.log`: Ruff/ty passed, pytest 818 passed/2
skipped, the existing `podly_tools` 97 Rust tests passed, and every new
library/binary test target compiled and passed.

Parity/benchmark evidence, if applicable: Not applicable to this structural
increment; the executable deliberately cannot accept commands yet.

Remaining limitations: Executor, authenticated admission, readiness, transport
tests, and shutdown remain P1.3-P1.7 and are not claimed by this checkpoint.

## P1.3 — Single-owner database executor

Task ID: P1.3

Commit/reference: Working tree after the verified P1.2 module boundary.

Files changed: `rust/src/writer/executor.rs`,
`rust/src/writer/actions.rs`, and strict operation decoding in
`rust/src/writer/protocol.rs`.

Behavior preserved or intentionally changed: One named OS thread opens and owns
the only SQLite connection. Async callers can only use bounded nonblocking
admission. A synchronous channel bounds entry count, an atomic mutex-protected
reservation bounds aggregate serialized bytes, and RAII releases byte capacity
on execution or rejected enqueue. Each top-level command gets an explicit
transaction; action failure rolls back and commit failure is returned as a
sanitized error. Reply ownership is a per-request one-shot sender, so a dropped
receiver creates no retained result map. Stop admission, sender closure, and
thread join are deterministic.

Tests added and CI log path: Rust unit tests prove a committed insert is visible,
a later transaction subcommand failure rolls back an earlier insert, and an
oversized command is rejected before admission. The first CI attempt stopped on
`cargo fmt --check`; after `mise exec -- cargo fmt --manifest-path
rust/Cargo.toml`, `/tmp/podly-rust-migration-p1.3.log` passed Ruff/ty, pytest 818
passed/2 skipped, 3 writer library tests, and 97 existing Rust tests.

Parity/benchmark evidence, if applicable: Tests use only a temporary SQLite
file and a test-only registry; no Python fallback or production database is
reachable.

Remaining limitations: The registry is intentionally not production-complete;
P1.4-P1.7 add authenticated HTTP admission, schema readiness, subprocess tests,
and deadline-bounded graceful shutdown.

## P1.4 — Authenticated bounded RPC admission

Task ID: P1.4

Files changed: `rust/src/writer/protocol.rs`, `transport.rs`, `config.rs`,
`actions.rs`, `executor.rs`, `rust/Cargo.toml`, and `rust/Cargo.lock`.

Behavior preserved or intentionally changed: Authentication precedes body
allocation and uses Base64URL/no-padding decoding plus constant-time secret
comparison. A duplicate-aware JSON decoder and explicit wire structs enforce
operation-specific envelopes. HTTP body, body-read, initial-header, connection,
request-concurrency, queue-entry, and aggregate-byte limits are bounded.
Validation occurs before enqueue; unsupported actions/models/operations return
422 without touching SQLite. Each waiting HTTP task owns one one-shot receiver;
dropped clients create no retained response table. Test actions require the
hidden `--enable-test-actions` switch and are off by default.

Tests and verification: Unit tests cover duplicate decoding and 401/403 auth.
The isolated subprocess cases recorded under P1.6 exercise the full mappings.
`/tmp/podly-rust-migration-p1.6.log` is the clean combined gate.

Remaining limitations: The production action registry remains deliberately
incomplete and therefore production-mode readiness remains false until P2.8.

## P1.5 — Readiness, schema, and lifecycle identity

Task ID: P1.5

Files changed: `rust/src/writer/database.rs`, `executor.rs`, `lifecycle.rs`,
`transport.rs`, `.env.local.example`, and the v1 contract.

Behavior preserved or intentionally changed: SQLite opens READ_WRITE without
CREATE only after the path is an existing regular file. Startup requires the
exact Alembic head `080b5181e23a`, applies WAL, synchronous NORMAL, 90-second
busy timeout, autocheckpoint 1000, and 64 MiB journal limit. Foreign-key
enforcement remains explicitly OFF to match the measured Python writer
connection; changing that is deferred to a separate compatibility decision.
Readiness reports only backend/protocol/schema, live bounded capacity, executor
state, and lifecycle. A partial production registry returns 503; isolated test
mode becomes ready only after DB/schema/executor initialization.

Tests and verification: Rust tests prove a wrong path is not created, an
incompatible revision is rejected, and compatible pragmas are applied. The
subprocess readiness response identifies Rust and the exact revision.

Remaining limitations: Draining transitions and signal behavior are P1.7.

## P1.6 — Isolated transport integration tests

Task ID: P1.6

Files changed: `rust/tests/writer_transport.rs` and hidden test-only CLI
overrides in `rust/src/writer/config.rs`.

Behavior and evidence: The test launches `CARGO_BIN_EXE_podly_writer` on
`127.0.0.1:0` with a temporary SQLite file containing only the expected Alembic
revision and a synthetic event table. It covers readiness identity, missing and
wrong auth, malformed and duplicate-key JSON, oversized bodies, wrong protocol
version, unsupported action/no mutation, capacity rejection, admitted timeout
with unknown outcome, dropped clients, a later async response preceding an
earlier completion, concurrent command-ID correlation, and process
restart/reconnect on the same isolated DB. The executable and test link only
Rust code, so Python local fallback is unreachable.

Tests added and CI log path: `/tmp/podly-rust-migration-p1.6.log`: Ruff/ty
passed, pytest 818 passed/2 skipped, 9 writer library tests passed, 97 existing
Rust tests passed, and the isolated subprocess integration test passed in 0.86s.

Remaining limitations: SIGTERM drain and SIGKILL rollback are P1.7.

## P1.7 — Graceful shutdown and abrupt-death rollback

Task ID: P1.7

Files changed: `rust/src/writer/transport.rs`, `executor.rs`,
`rust/tests/writer_transport.rs`, `rust/Cargo.toml`, and `rust/Cargo.lock`.

Behavior preserved or intentionally changed: SIGTERM atomically changes the
lifecycle to draining, stops executor admission, initiates Axum graceful
shutdown, drains all accepted channel work on the sole connection, closes the
connection, and joins the writer thread. HTTP drain plus executor join share the
documented 30-second grace; exceeding it forces process exit so SQLite owns
rollback of any uncommitted transaction. No claim is made that an accepted
`wait=false` command survives abrupt process death.

Tests added and CI log path: One subprocess case admits an insert-plus-sleep
transaction, sends SIGTERM, waits for clean exit, and verifies the insert
committed. A separate fresh process is killed during the same transaction and
the isolated DB verifies zero inserted rows. `/tmp/podly-rust-migration-p1.7.log`:
Ruff/ty passed, pytest 818 passed/2 skipped, 9 writer library tests, 97 existing
Rust tests, and 2 Rust subprocess tests passed.

Parity/benchmark evidence, if applicable: Both signal cases use temporary
SQLite files and the test-only Rust registry. No live process, database, or
Python fallback is reachable.

Remaining limitations: P1 intentionally remains production-not-ready because
the 57-action registry has not passed P2.8. The P1 exit gate is satisfied:
transport/lifecycle operate on isolated fixtures, capacity is bounded, SQLite
has one owner thread, and the full CI wrapper passes.

## P2.1 — Generic commands and transactions

Task ID: P2.1

Files changed: `rust/src/writer/actions.rs`, `executor.rs`, the plan, and writer
inventory.

Behavior preserved or intentionally changed: The only production-reachable
generic operation is UPDATE for `Post`, `ModelCall`, and `Feed`. Rust now uses
static table, column, and codec allowlists for exactly those models; no wire
string is interpolated as an identifier. Unknown legacy data fields are ignored,
missing rows fail, null remains distinct, booleans become SQLite integers, JSON
is serialized without losing list order, and numeric values preserve INTEGER
versus REAL storage. Transaction subcommands remain ordered under one outer
transaction with full nested result envelopes. Generic CREATE and DELETE have
no current callers and are explicitly not ported; they fail pre-admission
rather than widening the model surface.

Tests added and CI log path: A Rust executor test updates a fractional value in
an INTEGER-declared column, verifies SQLite `typeof(...) == 'real'`, checks bool
and nested JSON codecs, ignores an unknown field, and proves an absent-row update
returns `not_found`. Existing executor tests cover ordered transaction results
and rollback after a prior mutation. `/tmp/podly-rust-migration-p2.1.log`:
Ruff/ty passed, pytest 818 passed/2 skipped, 10 writer library tests, 97 existing
Rust tests, and 2 subprocess tests passed.

Parity/benchmark evidence, if applicable: All cases use isolated temporary DBs.
The field/model allowlists are reconciled from current callers and the P0
inventory; P2.8 still performs the automatic final registry/caller gate.

Remaining limitations: Named action groups P2.2-P2.7 are not yet ported, so
production readiness stays false.

## P2.2 — System/config/startup actions

Task ID: P2.2

Files changed: `rust/src/writer/system.rs`, `settings.rs`, `actions.rs`,
`executor.rs`, `mod.rs`, `src/app/config_store.py`,
`src/app/routes/config_routes.py`, and
`src/tests/test_config_store_scheduler_side_effects.py`.

Behavior preserved or intentionally changed: `ensure_active_run` creates the
fixed singleton with zero counters/timestamps/context metadata and updates an
existing row without resetting its status or counters. Discord settings retain
singleton defaults, partial/null mutation, and updated timestamp behavior.
Combined config updates keep the explicit section order and commit each present
section independently, including the earlier-section-survives-later-failure
exception. Rust returns the complete six-section database shape, preserves
empty-secret handling, Whisper backend mappings, notification truthiness and
URL normalization, and never claims to mutate Python memory. Generic
transactions reject nesting this non-atomic action because there are no current
transaction callers and pretending it is atomic would be unsafe.

The web config handler still hydrates effective runtime configuration and resets
its loaded processor after persistence. It now also snapshots/re-reads app
settings in a `finally` block and reconciles refresh/cleanup scheduler state in
the web process, including when a later config section fails after the app
section committed. This preserves cross-process visibility when the Python
writer process is retired.

Tests added and CI log path: Rust tests cover singleton creation/update without
counter reset, Discord defaults/partial updates, full combined serialization,
secret preservation, Whisper mapping, notification coercion, and the deliberate
partial-commit failure. Python coverage proves both scheduler effects receive
old/new values. `/tmp/podly-rust-migration-p2.2.log`: Ruff/ty passed, pytest 819
passed/2 skipped, 14 writer library tests, 97 existing Rust tests, and 2
subprocess tests passed.

Parity/benchmark evidence, if applicable: Tests use in-memory or temporary
SQLite only. Production readiness remains false pending the remaining action
groups and automatic registry gate.

Remaining limitations: Rust startup must ensure singleton config defaults before
admission; that exclusive bootstrap ordering remains a P3 responsibility.

## P2.3 — Users/authentication actions

Task ID: P2.3

Files changed: `rust/src/writer/users.rs`, `actions.rs`, `mod.rs`,
`rust/Cargo.toml`, and `rust/Cargo.lock`.

Behavior preserved or intentionally changed: Rust now implements all nine
registered user actions. User creation keeps username normalization, roles,
account defaults, and bcrypt cost 12; password updates generate fresh standard
bcrypt hashes rather than comparing nondeterministic hash strings. Role and
manual-allowance coercion, Discord registration/collision behavior, partial
billing field updates, customer lookup no-ops, and naive-UTC activity timestamps
match the Python action contract. User deletion explicitly removes feed tokens
and memberships and nulls both processing-job user references before deleting
the account, reproducing SQLAlchemy relationship effects even though the writer
connection deliberately runs with SQLite foreign keys disabled. Every action
runs within the central transaction wrapper and performs no helper-level commit.

Tests added and CI log path: Rust tests cover normalized/defaulted creation and
bcrypt verification/cost, password/role/allowance/activity updates including a
numeric-string ID, Discord creation plus billing-by-user/customer partial
updates, deletion relationship effects, and validation failure without a
persisted mutation. `/tmp/podly-rust-migration-p2.3-rerun2.log`: Ruff and ty
passed, pytest 819 passed/2 skipped, 19 writer library tests, 97 existing Rust
tests, and 2 subprocess transport tests passed. The two earlier attempts are
retained at `/tmp/podly-rust-migration-p2.3.log` (Clippy-only failure) and
`/tmp/podly-rust-migration-p2.3-rerun.log` (test compile-only failure); neither
was used as acceptance evidence.

Parity/benchmark evidence, if applicable: All database cases use isolated
in-memory SQLite. Password assertions verify the resulting hash with the bcrypt
algorithm and cost consumed by Python rather than asserting a salted string.
Invalid mutation coverage rolls the enclosing transaction back and verifies the
original row.

Remaining limitations: Higher-level authorization, total-user limits, and
last-admin guards remain in the Python service layer by design. Production
readiness remains false until all action groups and the automatic registry gate
pass.

## P2.4 — Feeds, subscriptions, and feed-token actions

Task ID: P2.4

Files changed: `rust/src/writer/feeds.rs`, `actions.rs`, `mod.rs`,
`rust/Cargo.toml`, and `rust/Cargo.lock`.

Behavior preserved or intentionally changed: Rust implements all 13 registered
feed, membership, whitelist/download, developer-fixture, cascade, and token
actions through the central transaction. Feed/Post constructors supply the
Python-side defaults explicitly, tolerate INTEGER/REAL episode durations, parse
ISO release dates, enforce static field allowlists, create jobs with UUIDv4 and
stage history, merge only the five supported existing-post fields, and advance
`last_changed_at` only for a real refresh payload. Singleton run recounting
matches the Python helper, including the fact that newly created unassigned jobs
are not counted. Membership counts/idempotence and whitelist ordering/no-job
behavior are preserved.

Token IDs are lowercase UUIDv4 hex, secrets contain 18 CSPRNG bytes encoded as
24 unpadded Base64URL characters, and persisted hashes are lowercase SHA-256.
Existing credentials are reused, legacy null/empty secrets rotate in place,
revoked rows are ignored, aggregate null-feed tokens remain distinct, and touch
does not re-authenticate a secret already checked by its caller. Feed deletion
uses the Python action's explicit relationship order. It intentionally preserves
the current legacy behavior that leaves `audio_segment` rows orphaned with
foreign keys disabled; changing that cleanup policy is outside this migration.
Filesystem cleanup remains caller-side and outside the transaction as today.

Tests added and CI log path: Isolated Rust tests cover add/refresh defaults,
fractional duration storage, job creation, merge/no-op rules, duplicate rollback
after a prior feed mutation, membership idempotence/counts, latest whitelist and
download behavior, token format/hash/reuse/rotation/touch, and the complete
documented deletion graph including the audio-orphan compatibility assertion.
`/tmp/podly-rust-migration-p2.4-final2.log`: Ruff and ty passed, pytest 819
passed/2 skipped, 24 writer library tests, 97 existing Rust tests, and 2
subprocess transport tests passed. Earlier P2.4 logs contain corrected fixture
or compile-only failures and are not acceptance evidence.

Parity/benchmark evidence, if applicable: Every database case uses a fresh
in-memory SQLite database. Generated UUIDs, secrets, and timestamps are checked
by format, relationship, hash, and shared-timestamp semantics rather than exact
nondeterministic values. Duplicate insertion explicitly rolls back an earlier
mutation in the same transaction.

Remaining limitations: Route-level authorization and pre-commit filesystem
effects remain in Python. Production readiness remains false pending P2.5-P2.9.

## P2.5 — Job lifecycle actions

Task ID: P2.5

Files changed: `rust/src/writer/jobs.rs`, `executor.rs`, `actions.rs`, `mod.rs`,
`feeds.rs`, `src/app/writer/actions/jobs.py`, and
`src/tests/test_cleanup_requeue_and_cancel.py`.

Behavior preserved or intentionally changed: Rust implements all 14 registered
job actions under the one-owner transaction executor: global FIFO dequeue,
stale/active/all clearing, constructor defaults and stage-history seeding,
serialized create-if-missing, superseded-job/model-call cancellation,
idempotent partial attribution, status/timestamp/history transitions, the three
processor flags/counts, and pending-run reassignment. Singleton recount behavior
is shared with the feed actions. Bare integer results and null dequeue responses
remain unchanged.

One narrow safety correction is intentional and implemented identically in
Python and Rust: after `mark_cancelled`, a late non-cancelled
`update_job_status` is an idempotent no-op returning the persisted cancelled
status. It preserves reason, completion timestamp, progress, and history. This
closes the supervisor/worker race required by the plan without making other
terminal states immutable or interfering with explicit requeue workflows.

Tests added and CI log path: Rust action tests cover job defaults/UUID/history,
serialized create-if-missing, FIFO/run attribution, running-job exclusion,
cancelled-state ownership, stage deduplication, flags/counts, model-call status
matrix, attribution/reassignment, and terminal preservation during active clear.
Executor tests issue eight concurrent dequeue commands and prove one claim plus
seven nulls, and race cancellation against completion in both possible serial
orders with cancellation always final. Python regression coverage proves the
same late-worker guard. `/tmp/podly-rust-migration-p2.5-final.log`: Ruff and ty
passed, pytest 820 passed/2 skipped, 32 writer library tests, 97 existing Rust
tests, and 2 subprocess transport tests passed.

Parity/benchmark evidence, if applicable: All fixtures use fresh in-memory or
temporary SQLite databases. Concurrent cases execute through the actual bounded
Rust executor and its sole SQLite owner, rather than calling action helpers
directly.

Remaining limitations: P2.6-P2.9 remain, so production readiness is still
false and Python remains the selected writer.

## P2.6 — Processing persistence actions

Task ID: P2.6

Files changed: `rust/src/writer/processor.rs`, `actions.rs`, and `mod.rs`.

Behavior preserved or intentionally changed: Rust implements all 12 registered
processing-persistence actions. Model-call upserts use the four-column identity,
reset only retryable/failed/cancelled states, reuse success rows, and use
`INSERT OR IGNORE` plus re-query for serialized race recovery without an inner
commit. Whisper upserts preserve default and custom reset fields. Transcript
start/insert/finish and composite replacement preserve deletion order, retry
recovery, caller-visible multi-RPC boundaries, stage order, Unicode, full f64
precision, and word-timestamp filtering. Identification retries remain
`OR IGNORE`; replacement still reports requested rather than actual deletion
count. Audio replacement rejects malformed numeric fields, skips non-positive
ranges, and rolls deletion back on later failure.

Artifact-backed finish validates canonical paths against the instance and
podcast-data roots, rejects symlink escape, reads through a buffered reader,
normalizes natively in Rust, preserves the original artifact, and caps artifacts
at 64 MiB so this path cannot grow memory without a bound. This intentionally
removes the legacy Python action's temporary normalized file and nested Rust
sidecar call; the persisted normalization contract and error-before-DB-mutation
ordering remain the same.

Tests added and CI log path: Rust tests cover model-call reset/reuse matrices,
custom Whisper fields, atomic transcription replacement, old identification
cleanup, order/Unicode/f64 precision, malformed word filtering, equal word
boundaries, audio rollback after deletion, identification duplicate retries and
reported delete semantics, canonical artifact containment/original preservation,
and a realistic 10,000-segment insert with complete ordering. The transport's
16 MiB request limit and the artifact's 64 MiB file limit provide explicit
bounds. `/tmp/podly-rust-migration-p2.6-final.log`: Ruff and ty passed, pytest
820 passed/2 skipped, 39 writer library tests, 97 existing Rust tests, and 2
subprocess transport tests passed.

Parity/benchmark evidence, if applicable: All DB tests use fresh in-memory
SQLite; artifact cases use temporary roots only. Nondeterministic timestamps and
IDs are asserted by semantics/shape. No live artifacts or production paths are
read or changed.

Remaining limitations: P2.7 cleanup, P2.8 registry completeness, and P2.9 mixed
stress remain; production readiness stays false.

## P2.7 — Cleanup actions

Task ID: P2.7

Files changed: `rust/src/writer/cleanup.rs`, `actions.rs`, and `mod.rs`.

Behavior preserved or intentionally changed: Rust implements all six cleanup
actions. Missing-path scanning selects only needed columns, resolves/deduplicates
stored and legacy/modern derived candidates, requires a nonempty regular
processed file, independently checks the unprocessed path, and resets only the
latest non-active job with a fresh stage-history seed. Full clear preserves the
Python child-before-parent order; keep-transcript and auto-retry preserve
transcript rows, transcript JSON, and every Whisper predicate while deleting
classification output. Files-only cleanup retains duration and all processing
metadata. Full processed cleanup also unwhitelists and recalculates the singleton
run.

Filesystem behavior remains deliberately non-transactional where the current
contract requires it: auto-retry and files-only unlink before the database
commit, missing files succeed, directories and unlink errors are skipped, and a
later rollback cannot restore removed files. Clear-all and keep-transcript still
perform no internal unlink because their callers own those file effects.

Tests added and CI log path: Fresh SQLite/temp-directory tests cover missing
stored paths plus latest-job reset, a 501-segment graph deletion, identification
ordering, transcript/word preservation, all three Whisper recognition forms,
auto-retry's processed-only deletion, explicit file-deleted/DB-rolled-back
interruption evidence, files-only graph/duration preservation, full cleanup
unwhitelisting, and singleton recount. `/tmp/podly-rust-migration-p2.7.log`:
Ruff and ty passed, pytest 820 passed/2 skipped, 45 writer library tests, 97
existing Rust tests, and 2 subprocess transport tests passed.

Parity/benchmark evidence, if applicable: Every path used by tests is created
under a temporary directory. No production or repository audio path is touched.

Remaining limitations: Registry completeness and mixed-client stress remain;
production readiness stays false.

## P4.4 — Isolated container lifecycle upgrade and interruption follow-up

Task ID: P4.4 follow-up

Commit/reference: Current migration worktree; no deployment.

Files changed: `scripts/test_rust_writer_container.sh` and
`scripts/writer_container_test_helpers.py`.

Behavior preserved or intentionally changed: The disposable container gate
now seeds a database by applying real Alembic migrations through
`88710a0fe69c`, then starts the normal Rust deployment path and confirms
bootstrap reaches `080b5181e23a`, creates `notification_settings`, and leaves
one synthetic admin. A separate named volume exercises an admitted
multi-command transaction: its first test-only action inserts a synthetic row,
the second holds the transaction open, and the test confirms SQLite's write
lock before killing the isolated Rust writer container. Normal startup on the
same volume then proves the uncommitted insert was rolled back and did not
duplicate the admin. All test containers use `--network none`, no host ports,
unique disposable Docker volumes, and no live instance/database mount.

Tests added and CI log path: `/tmp/podly-rust-migration-p4-container-upgrade-ci-20260924.log`
exited 0 with final line `Isolated Rust writer container lifecycle checks
passed.` It verified the older-schema upgrade, interrupted transaction lock,
rollback after restart, fresh deployment, persistent-volume restart,
non-default UID, readiness, process retirement, dependent shutdown, and
bootstrap failure behavior.

Parity/benchmark evidence, if applicable: The interruption uses only a
synthetic `writer_test_events` table and a Rust test-actions flag. The startup
sequence remains serial in `start_services.sh` (bootstrap, writer readiness,
then web), and the healthcheck verifies writer executor readiness plus web
availability. The container run does not artificially delay writer readiness
to force a startup race; such a forced-delay test is not claimed here.

Remaining limitations: No live data or services were touched. P4.4's listed
older-schema and interrupted-command scenarios pass in isolation; the
checklist remains subject to the root agent's complete P4 gate audit.
