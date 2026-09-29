# Rust service migration evidence

Evidence is recorded against synthetic fixtures and isolated containers unless an
entry explicitly says it is a read-only observation of the existing local
container. No entry authorizes a deployment or a write to production data.

## 2026-09-29 Live cutover to the Rust writer

Authorized by the user. Commit `45d8c0b` on `rust-migrate-v2`, built on the
live host via `docker compose build`; the image's `/app/bin/podly_writer` SHA-256
`656f29e84428b74aeddefcd8d89a0e045bbecafa4758a202a7ee646a7787e319` matches two
independent `--no-cache` builds, which rules out a baked bit flip on this RAM-fault host.

- Pre-checks: no pending/running jobs; live schema already at `080b5181e23a`
  (no migration at cutover). `.env.local` gained `PODLY_WRITER_BACKEND=rust`
  and a random `PODLY_IPC_AUTHKEY`.
- Backup: SQLite backup-API copy `src/instance/sqlite3.pre-rust-2026-09-29.db`
  (integrity ok, 886 jobs). Previous image tagged
  `podly_pure_podcasts-podly:pre-rust-rollback`.
- Result: healthy ~10 s after recreate. Processes: shell supervisor,
  `podly_writer` (11.5 MiB RSS, 4 threads), Python web; no `app.writer`.
  `podly_writer --probe` passes. A timestamp-only `update_user_last_active`
  through the real client committed. HTTP 200 on `/` and `/api/auth/status`.
  Container 111.8 MiB about one minute after start. No fallback,
  unobserved-failure, or traceback lines.
- Rollback: set `PODLY_WRITER_BACKEND=python` and `docker compose up -d`
  (same schema); the backup and the pre-rust image are retained.

## 2026-09-29 Pre-ship writer follow-ups

Task ID: P4 follow-up (release hardening; no checkbox change)

Files changed: `rust/src/writer/executor.rs`.

Behavior intentionally changed: a command whose result cannot be delivered
(`wait=false`, or a waiting caller that disconnected) now logs one
`[WRITER_UNOBSERVED_FAILURE]` JSON line on failure with command ID,
operation, action, error code, and outcome. Error messages and params are not
logged because messages can echo caller values. Previously these failures
were silently discarded, contrary to section 4.2. Successful commands and
delivered results log nothing new.

Tests added and CI log path: `unobserved_failure_log_is_redacted`.
`/tmp/podly-rust-migration-p4-unobserved-failure-ci-20260929-1.log` exit 0:
1094 Python passed/2 skipped, 60 writer + 97 existing + 3 transport Rust
tests, fmt/clippy/ty/Ruff, registry parity. The change touches only the
undelivered-failure path, which no accepted benchmark command exercised, so the
recovery-5 acceptance evidence is not re-measured for it.

Recovery headroom characterization (recovery-5 Rust runs): cooldown excess over
cold idle is ~7.5 MiB from the first HTTP burst and rises to 8.0–9.8 MiB by
the final phase, then stops; idle does not grow across runs. At final
cooldown the writer is ~+2.7 MiB over warmed idle, which is about the size of
SQLite's default 2 MiB page cache (inferred, not measured). The web heap is
~+3 MiB and the rest is the cold→warmed idle gap. No leak was found. Reducing
it further would mean shrinking caches, a performance trade-off rather than a
fix, so the thin margin is recorded as a known fragile gate.

Recovery reference: the comparator measures recovery against cold idle,
while the P0.7 text says warmed idle. This was an explicit earlier decision,
enforced by `test_cold_idle_recovery_gate_is_unchanged_when_warmed_idle_is_higher`:
warming must not raise the allowance. The stricter cold-idle reference is
retained and governs acceptance; the discrepancy with the P0.7 wording is
intentional.

## 2026-09-29 P4.6/P4.8 — web burst trim and passing matched pair

Task ID: P4.6, P4.8

Commit/reference: uncommitted worktree on `rust-migrate-v2` (HEAD `469baf5`);
isolated image `podly-rust-writer-p4:20260928-recovery-5`
(`sha256:a90093e1bd952bfcdc004989e14520774de0059d0d7ae0bd849d8346cda3e76c`).
No deployment; the default backend remains Python.

Files changed: `src/app/__init__.py`, `src/app/memory_pressure.py`,
`src/tests/test_database_pool_bounds.py`, `.env.local.example`, plus the
Rust post-action purge recorded in the entry below.

Behavior intentionally changed (user-approved web-side fix for the web-owned
residuals diagnosed below): the web counts in-flight requests with Flask's
`request_started` signal and a `g`-guarded `teardown_request`, which stays
balanced when a hook short-circuits or a handler raises. One daemon thread in
the scheduler-owning web process checks every 0.25 s; after a burst with no
in-flight request for 1 s it disposes the idle SQLAlchemy pool (closing the
SQLite descriptors deferred behind WAL read locks) and calls the existing
`release_memory_to_os`. Disabled by `PODLY_MEMORY_TRIM_ENABLED=false`. Pool
size/overflow and request concurrency are unchanged.

Tests added and CI log path: real-SQLite regression proving eight pinned db
descriptors return to zero after the burst trim and that it claims once;
quiet/idle claim logic; balanced counting under 401 short-circuit and 500.
`/tmp/podly-rust-migration-p4-web-burst-trim-ci-20260928-2.log` exit 0:
1094 Python passed/2 skipped, 59 writer + 97 existing + 3 transport Rust
tests, fmt/clippy/ty/Ruff, registry parity. Attempt `-1` failed on a ty
diagnostic for a WSGI-attribute wrapper, replaced rather than ignored.
`/tmp/podly-rust-migration-p4-container-rollback-ci-20260929.log` exit 0:
ordinary CI plus `Isolated Rust writer container lifecycle checks passed.`
and `Isolated rollback rehearsal passed: schema, backup, exclusivity,
pending recovery, and no replay.`

Parity/benchmark evidence: matched five-run pair on recovery-5, runner SHA
`03258c3df50e521dd97ea27fb53e4d58ec9a5e6bcf379cde2a634119adf2459e`.
Python baseline `/tmp/podly-writer-python-p0-20260928-recovery-5/report.json`
(SHA `4cab19ebd5ccdb71b34e43485ee356f4a26b871f554af83afb8b9d1193243d8c`,
log `/tmp/podly-rust-migration-p0-recovery-ci-20260928-5.log`, fixture source
recovery-1 report). Rust `/tmp/podly-rust-writer-p4-recovery-20260928-5`
(log `/tmp/podly-rust-migration-p4-recovery-ci-20260928-5.log`, exit 0,
`errors: []`); report `024a768231cf87e0b2db6770c2888c0e8e21098ed17d30f056f707ef7fd4399a`,
comparison `355be3d33b98697e3704c5a213ec078219a9df44af188e02bf1baedba662dc86`,
protocol `8ce87aafa2b5fa006337780faf4cf9aafd4af4a10b5a6841b46710a822849493`;
all three and the Python report/protocol made read-only. Thresholds unchanged
against the original P0 report `2ec8584b…`.

Every comparator gate passed. All five Rust runs recorded
`arena_purge=all rc=0`; Rust identity, no fallback. Warmed-idle container
median 101,580,800 B (limit 130,652,570; ~81.5 MiB below the P0 183,081,370 B
median). Rust writer RSS median 14,061,568 B (limit 49,753,293). Post-burst
recovery extra bytes by run 10,055,844 / 9,867,100 / 8,399,094 /
10,265,559 / 10,097,786 (limit 10,485,760). Thread/FD deltas 0/0 in every
run. Feed-posts p95 43.876 ms, 348.53 req/s; RSS p95 804.892 ms; writer
small/large/mixed p95 3.551/164.2/39.44 ms; all CPU efficiency ratios ≤ 1.016.

Remaining limitations: recovery headroom is thin (worst run ~215 KB under
10 MiB); treat a future regression there as a real failure, not noise. The
comparator still references cold `idle` rather than P0.7's warmed-idle text
(warmed idle is higher, so the recorded pass is not flattered by it). The
worktree's earlier changes were found staged in the index by an external
actor; nothing was lost. Making Rust the deployment default and the section 15
rollout remain separate, unauthorized steps. Web migration (P5+) not begun.

## 2026-09-28 P4.6 recovery-failure diagnosis and writer purge parity

Task ID: P4.6 (diagnosis/increment; remains unchecked)

Commit/reference: uncommitted worktree on `rust-migrate-v2` (HEAD `469baf5`);
isolated image `podly-rust-writer-p4:20260928-recovery-4`
(`sha256:10ece36968507a815c2619b1088e10431621c208803091da336b5f4e6fbca531`).

Files changed: `rust/src/writer/executor.rs`, `rust/src/writer/memory.rs`,
`.env.local.example`.

Diagnosis of the failed five-run comparison
(`/tmp/podly-rust-writer-p4-recovery-20260928-3`), from its reports plus
diagnostic-only isolated containers (pinned recovery-2 image, synthetic
fixture clone, no live mounts):

- Missing `arena_purge=all rc=0`: the purge never executed; capture and parsing
  were correct. Rust purged only after `PODLY_WRITER_IDLE_TRIM_INTERVAL_SEC`
  (900 s in the benchmark and default) of quiescence, while each cooldown is
  30 s. Not even the first-call `jemalloc_mallctl=available` line appeared.
  With the interval forced to 5 s, both lines reached `docker logs` and the
  parser, and writer RSS fell 70 → 13 MiB, so the retained writer memory
  was reclaimable jemalloc dirty memory.
- Parity gap: the Python writer purges (gc + all-arena jemalloc purge) after
  every named action except `dequeue_job`, `touch_feed_access_token`, and
  `update_user_last_active` (`src/app/writer/service.py`); the idle tick
  covers only those. The Rust port had implemented only the idle tick.
- Web FD owners: after the c=8 feed-posts burst the Python web gains +7
  `sqlite3.db` and +2 `sqlite3.db-wal` descriptors (14 → 23), unchanged after a
  further request. In WAL mode each open SQLAlchemy connection keeps a SHARED
  lock on the database file, so SQLite's unix VFS defers closing descriptors
  of closed overflow connections while any pooled connection remains open.
  The retained count is bounded by peak concurrency, not a leak. The frozen
  Python pair shows the identical web 17 → 26 (+9) growth, so the
  `thread_fd_recovery` failure is web-owned and independent of writer backend;
  the Rust writer stays at 4 threads/13 FDs.
- Web memory: the feed-posts API route has no post-request purge (the RSS XML
  routes do). Web RSS stays ~+23 MiB after cooldown; one existing RSS-route
  purge reduced it 132 → 114 MiB. Every Rust run's `cooldown_http_feed_posts`
  is already +17–25 MiB over idle, and every frozen Python run fails the same
  recovery gate by 25–34 MiB.
- Comparator note (unchanged): P0.7 text specifies own **warmed-idle** median
  + 10 MiB; `scripts/bench_service_migration.py` compares against the cold
  `idle` median. The difference is ~0–4 MiB and cannot flip these results;
  it was left unchanged pending an explicit decision.

Behavior intentionally changed: the Rust writer now calls the all-arena purge
on its SQLite owner thread after each named action's payload/result is
released, except the three deferred actions above, honoring
`PODLY_MEMORY_TRIM_ENABLED`. Transaction boundaries, single-writer ownership,
and reply-before-purge ordering are unchanged; no thread is added.

Tests added and CI log path: Rust unit test
`named_actions_purge_except_deferred_timestamp_touches`.
`/tmp/podly-rust-migration-p4-post-action-purge-ci-20260928-2.log` exit 0:
Ruff/ty, 1091 Python passed/2 skipped, Rust fmt/clippy, 59 writer + 97
existing + 3 transport tests, registry parity. (Attempt `-1` failed only on
Rust fmt line wrapping of the new test.)

Parity/benchmark evidence: diagnostic probe on recovery-4 with the default
900 s interval: writer RSS 13 MiB immediately after the 12-command large
burst (previously 33–47 MiB after cooldown), `arena_purge=all rc=0` recorded.
Container remained +27 MiB over idle solely from the Python web residual
(web 107 → 132 MiB, 14 → 23 FDs). This is a diagnostic, not a benchmark.

Remaining limitations: no matched five-run pair has been captured on
recovery-4. Based on the web-owned residuals present in both arms, the
unchanged recovery memory and FD gates are expected to keep failing until
the Python web behavior is addressed or the gate decision is revisited by
the user. P4.6/P4.8 remain unchecked; no web migration or live change.

## 2026-09-28 recovery baseline — live verification follow-up

Session 50642 remains live (polled via its original exec handle); log:
`/tmp/podly-rust-migration-p0-recovery-ci-20260928-3.log`. Run 1 in
`/tmp/podly-writer-python-p0-20260928-recovery-1/run-1.json` is complete and
run 2 has started. All eleven resource phases have positive sample counts.
Each of the five workload phases has positive cumulative CPU seconds
(feed 88.457835, RSS 33.972682, small 3.007241, large 4.075468,
mixed 3.781611). Python backend/process identity agree; fallback logs are
empty; write successes/timing counts are exactly 1000/12/100, with zero
client or writer failures. This is an intermediate observation, not a
completed baseline or acceptance result. Preserve the active run and hold
runtime/benchmark edits until terminal completion.

Read-only Luna allocator audit identified a concrete difference to investigate
if the paired recovery run still fails RSS: the image's system-wide jemalloc
preload applies to both writers, but only the Python writer invokes the existing
idle all-arena purge. The idle-trim environment setting does not implement a
Rust purge. This does not yet prove that the Rust retained bytes are reclaimable;
do not claim causation or add an unmeasured allocator workaround. P4.6 and P4.8
remain unchecked; no web migration or live changes were performed.

The independent CPU-gate audit confirms both ratios are checked separately:
current Rust CPU/throughput efficiency versus historical P0 and versus paired
Python must each be at most 1.15. Historical P0 used periodic Docker CPU;
the recovery pair uses cumulative cgroup CPU divided by client duration.
The old report cannot be retroactively recomputed without raw cumulative
counters. Its published numerical constraint remains enforced in addition to
the aligned cumulative paired gate, but the historical CPU comparison is not
claimed as a like-for-like sampling-policy comparison. Periodic CPU remains
diagnostic in the recovery reports; idle-only samples must not replace actual
workload CPU to manufacture a passing gate.

Recovery baseline completed: session 50642 terminal exit 0; CI log ends with
`errors: []`. Ordinary CI passed 1066 Python tests/2 skipped, Rust formatting,
clippy, 52 writer + 97 existing + 3 transport tests, and registry parity.
All three runs have eleven sampled phases, positive cumulative CPU for all
five workloads, Python backend/environment identity, HTTP 200 only, no fallback,
and exactly 1000/12/100 successful writes with matching successful timing counts.
The report and protocol were made read-only before the matching Rust run.
Report SHA-256: `85ea9a13231a74c0c3c45085285a6479204b2a399422048066d33737cb5684a7`.
Protocol SHA-256: `713dff0ad866c8220c586ba9750834b9eec59fa23a282bdf2017f34d34e9e84e`.
DB SHA-256: `851273de0f0b149969e0eccc5da319c04f6c70e0283a29bfcf2a652688b33718`.
Runner SHA-256: `83664a3e0c2dfb67518e3d422ebc95767d5e3779296fab7028a6615f390cc19d`.
Image ID: `sha256:4f453c2bfda12f0c6e81e7e25a75a53f7ef5fced184e3a4578fcea0708d61906`.
Sampling policy: `periodic-phase-end-cumulative-cpu-v2`. Original P0 report
remains the mandatory historical threshold reference. No P4 checkbox advances
solely because the Python baseline completed.

Matching Rust CI/benchmark started on exec session **72795**; log
`/tmp/podly-rust-migration-p4-recovery-ci-20260928-1.log`, output
`/tmp/podly-rust-writer-p4-recovery-20260928-1`. It uses the frozen recovery
Python report above, the same isolated `20260928-recovery-1` image, and the
unchanged original P0 threshold report. Poll this original handle; do not restart
because observation times out. Hold runtime/benchmark source edits and competing
workloads until terminal completion. Next: inspect all three Rust runs and the
comparison, retain failed evidence if any, expand both matched arms to five
repetitions if the spread gate requires it, and only then assess P4.6/P4.8.

Session 72795 passed ordinary CI (1066 Python passed/2 skipped, 52 writer,
97 existing Rust, 3 transport tests; formatting/type/clippy/registry passed)
and entered Rust measurement. Its protocol confirms exact equality of the
recovery image ID, runner SHA, cumulative-v2 policy, canonical fixture SHA,
environment fingerprint, and three-repetition profile. It pins the frozen
Python report SHA above and original historical report SHA
`2ec8584b9070e1326dabf4f02b343fc15351055e04004f3b236774cd58dc9af1`.
Post-CI `git diff --check` passed and the runner/report hashes remain unchanged.
Measurement remains active; performance acceptance is not established yet.

Rust recovery run 1 completed while session 72795 continues with run 2.
All eleven resource phases have samples (including two for each short write
burst); backend process identity/readiness confirms Rust; all HTTP statuses are
200; fallback logs and writer/client failures are empty; write/timing counts
are 1000/12/100. Small/large/mixed client p95: 3.433/134.526/38.885 ms.
Writer RSS is 10,485,760 bytes after ready and 34,680,832 after cooldown,
with four threads and thirteen FDs at both observations. Container idle median
127,401,984 bytes; final cooldown median 141,767,475; large cooldown median
178,048,205. These recovery values still exceed own idle + 10 MiB, so run 1
does not establish acceptance despite the lower writer RSS. Web FD snapshots
are 14 after ready and 23 after cooldown; the aggregate resource snapshots
must be evaluated by the unchanged gate rather than guessing a pass from
individual process counts. Await all matched runs and the full comparison.

CPU timing follow-up requested from the read-only Luna auditor: short writer
phases report about 596–642% because cumulative counters surround the load
helper while the denominator is its client-measured workload duration. Audit
whether helper initialization/setup outside that timer is included in the
counter delta; do not interpret those percentages as measured steady-state
Rust core utilization or silently weaken/rewrite CPU constraints.

Luna timing audit confirmed the scope: corrected counters exclude container
startup/readiness/warmup, but bracket the full `writer_workload()` helper call.
The numerator includes in-container helper interpreter startup, connection,
payload construction, serialization, client execution, and result/report work;
host Docker CLI CPU is not in the container cgroup. `client.elapsed_seconds`
includes only the helper's thread-pool execution window. Consequently the
reported short-write CPU percentage is client-duration-normalized CPU, not
same-window utilization. Dividing it by throughput cancels that duration and
measures approximately 100 * invocation CPU seconds / successful writes.
The aligned pair uses the same runner/helper envelope; interpret the efficiency
gate as charged invocation CPU per operation, not pure steady-state writer
CPU. Phase-end periodic sampling occurs after this counter bracket. Keep this
limitation explicit alongside the historical periodic-policy mismatch; neither
audit authorizes changing the 1.15 limit or discarding a failed gate.

Rust recovery run 2 also completed with all eleven sampled phases, Rust
identity, no fallback, and 1000/12/100 successful writes (small/large/mixed
p95 3.596/139.018/42.291 ms). Writer final RSS 44,040,192 bytes, four threads,
thirteen FDs; web final RSS 117,104,640 and twenty-three FDs. Container idle
median 96,526,664; large cooldown 161,795,277; final cooldown 137,992,602 bytes.
Cooldown recovery again fails own idle + 10 MiB. Run 3 is active on the same
session 72795; do not alter source during measurement.

Next focused increments after terminal capture: align writer cumulative CPU
counters with the helper's actual thread-pool timing window, excluding startup,
payload construction and reporting (the current paired invocation scope is
not same-window utilization); independently implement/test a quiescence-aware
Rust allocator purge if the complete capture confirms retained freed memory
as a candidate. Preserve the current reports and original numerical caps.
Any runner/runtime/image change requires a newly frozen matched Python/Rust
pair; do not reuse this baseline across changed measurement policy or image.

Recovery comparison terminal result: session 72795 exited 1. All three runs
completed; the full comparator evaluated rather than failing on missing phases.
It rejected `cpu_efficiency_small_historical` (1.775 > 1.15),
`post_burst_memory_recovery` (worst phase extra bytes by run
51,170,509 / 66,107,474 / 69,064,459 > 10,485,760), and
`paired_baseline_spread` (idle uncertainty can reverse a gate; requires five
matched repetitions). Other comparator gates passed, including writer RSS,
idle memory, HTTP/write latency, queue time, paired CPU, errors and resource
bounds. This does not waive the three failed gates. The mismatched CPU timing
scope identified above remains a measurement defect to correct, not a reason
to remove the historical constraint.

Frozen failed-capture hashes:
report `5bce37d01b9994aa0b011ff8eaebeaf170a6997f89b467581cd880d218e0cf8f`;
comparison `e2d63b252cd1ff436d81d55fef3a7d961d3f53cc79a76193929553a169e6142a`;
protocol `a66a40522f5203b9adbda3a052c47c8e3a1effd8ac9cf6dc07634979b6afd0d0`.
Those three artifacts were made read-only. Original P0 and paired Python
artifacts remain unchanged. No benchmark process is active after this terminal
result. Luna agents are now implementing two disjoint focused increments:
same-window helper CPU measurement, and Rust quiescence-aware optional jemalloc
purging on the existing SQLite owner thread. Root must review both and run CI
before rebuilding an isolated image and capturing a new five-run Python/Rust
pair. P4.6/P4.8 remain unchecked. No P5 or live changes.

Focused recovery increments are implemented, not yet CI-verified:

- `scripts/bench_writer_service.py` measures cgroup v2/v1 CPU around the existing
  thread-pool request window when explicitly requested by migration CI; bad or
  unavailable counters fail visibly. `scripts/bench_service_migration.py` uses
  these helper fields for writer phases, keeps HTTP host brackets and periodic
  CPU diagnostics, and requires the new helper-window sampling policy for the
  accepted pair. Historical numerical limits remain unchanged.
- `rust/src/writer/memory.rs`, `executor.rs`, `transport.rs`, `mod.rs` and
  `Cargo.toml` add optional dynamic jemalloc arena purging on the existing
  SQLite owner thread. No thread or transaction is added. The existing master
  trim switch and idle interval are honored; integer parse/default/disable
  behavior matches Python for ordinary settings, with extreme positive Rust
  intervals capped at one year. New handler RAII tracking and existing work
  reservations protect payload/result lifetimes at the idle decision.
- Quiescence is checked at the decision via atomic snapshots, not exclusive
  throughout purge: a newly arriving request may overlap a thread-safe allocator
  purge. No mutex is held across purge, no maintenance rejection is introduced,
  and Tokio never executes the blocking purge. Attempts consume activity even
  when the optional hook is missing or fails; diagnostics are bounded once per
  availability/success/failure category. Purge cannot reclaim live SQLite/runtime
  allocations and is not yet proven to fix cooldown memory.

Tests added cover strict counter parsing/failures, CPU source/window selection,
paired-policy rejection, interval/master-switch behavior, fake hook key/errors,
idle eligibility, and a real command-handler RAII lifetime test. Root is reviewing
the small diagnostic-capture follow-up, then must run CI. No successful runtime
purge or new acceptance result is claimed before that verification.

Focused source review complete. The benchmark now records only allowlisted
structured `writer_memory_trim` diagnostics; Rust runs require exact successful
`arena_purge=all rc=0` evidence, while Python does not require the optional hook.
Regression tests distinguish v2 reports usable solely as frozen fixture sources
for new Python baselines from v2 reports rejected as v3 paired references.
Full CI started in `/tmp/podly-rust-migration-p4-idle-window-ci-20260928-1.log`.
Do not rebuild or capture the next pair until this CI is terminal and passes;
review formatter changes and record the exact result. Next image/run artifacts
must use fresh paths and five matched repetitions, preserving all failed data.

First focused CI session 24267 exited 1: Ruff auto-fixed one finding, ty and
Rust prerequisite build passed, Python tests 1085 passed/2 skipped, then Rust
fmt rejected three line-wrap differences in executor/transport. Root applied
exact fmt output via patch and started full rerun in
`/tmp/podly-rust-migration-p4-idle-window-ci-20260928-2.log`. Clippy/new Rust
unit tests/registry completion are not claimed by the first attempt. A litellm
interpreter-exit logging error followed successful pytest and is recorded as a
diagnostic, not the CI exit cause; the fail-fast stage was Rust formatting.

Focused CI rerun session 47414 terminal exit 0:
`/tmp/podly-rust-migration-p4-idle-window-ci-20260928-2.log` proves Ruff,
ty, shell syntax, Rust prerequisite build, 1085 Python passed/2 skipped,
Rust fmt/clippy, 58 writer + 97 existing + 3 transport tests, registry parity.
The six additional writer tests cover idle settings/hook/quiescence and handler
lifetime; Python tests cover helper-window CPU and diagnostic capture. Root
reviewed changed source and `git diff --check` is clean. Runtime reclamation
and full acceptance remain unproven until the matched container run.

Read-only Docker metadata confirmed the tag
`podly-rust-writer-p4:20260928-recovery-2` was unused. A new isolated image build
started, log `/tmp/podly-rust-migration-p4-idle-window-image-20260928.log`.
Next, once build succeeds: capture five Python repetitions through
`./scripts/ci.sh --writer-baseline`, using the frozen recovery-1 report solely
as fixture source; freeze/audit its new v3 report. Then capture five Rust
repetitions against that exact image, runner/policy/environment/fixture and the
original historical thresholds. Preserve all earlier artifacts and hold source
edits/competing workloads during measurement. No acceptance checkbox advances
from successful unit CI or an image build alone.

Build exec session **52722** was polled live; do not restart on observation
timeout. Current post-CI runner SHA-256 is
`6482b5bd0a5c4cb69f41176c5f9cbd5f4be7a895627e6767ea0b03965d14684d`.
Recovery-1 Python and Rust report hashes were rechecked unchanged. Once build
52722 exits 0, the next command (after confirming the output path is unused) is:

```sh
PODLY_WRITER_BENCH_IMAGE=podly-rust-writer-p4:20260928-recovery-2 \
PODLY_WRITER_BENCH_BASELINE=/tmp/podly-writer-python-p0-20260928-recovery-1/report.json \
PODLY_WRITER_BENCH_REPETITIONS=5 \
PODLY_WRITER_BENCH_OUTPUT=/tmp/podly-writer-python-p0-20260928-recovery-2 \
mise exec -- ./scripts/ci.sh --writer-baseline \
  > /tmp/podly-rust-migration-p0-idle-window-ci-20260928.log 2>&1
```

Audit/freeze the resulting report before Rust. The paired Rust command must
use that new report as `PODLY_WRITER_BENCH_BASELINE`, the same image, five
repetitions, original historical threshold report, and a fresh output path.
Require recorded purge success plus the actual cooldown-memory gate; neither
one substitutes for the other. No image was deployed or live container stopped.

Image build session 52722 terminal exit 0; image inspection records
`sha256:6ae6e5c610485ff185942e643529f87859bc1a3cdd7fbce90814aeca4a965fed`
(Docker inspect `.Id`, not the exported config blob digest).
The new baseline output path was confirmed absent. The five-run Python baseline
command above has now started in the specified CI log. It reuses recovery-1
solely as the frozen synthetic fixture source, not as a performance reference.
Hold source edits, builds, tests and competing workloads after CI enters
measurement; audit all five resulting runs and freeze their report before the
matching Rust invocation. P4.6/P4.8 remain unchecked.

Baseline exec session **63664** is the active handle; poll it rather than
restarting on observation timeout. Build session 52722 is terminal. Current
baseline log is `/tmp/podly-rust-migration-p0-idle-window-ci-20260928.log`;
output `/tmp/podly-writer-python-p0-20260928-recovery-2`. Once this session is
terminal, record exact CI result, all five run checks and report/protocol hashes.

Baseline session 63664 passed ordinary CI (1085 Python passed/2 skipped,
58 writer + 97 existing + 3 transport tests, Ruff/ty/fmt/clippy/registry) and
entered run 1. Protocol pins five repetitions, Docker image ID above, runner
`6482b5bd0a5c4cb69f41176c5f9cbd5f4be7a895627e6767ea0b03965d14684d`,
`periodic-phase-end-helper-window-cumulative-cpu-v3`, and
`writer_cpu_window=helper-threadpool-cgroup-cpu-v1`. Canonical DB/tree and
environment fingerprint are unchanged from recovery-1. `git diff --check`
passes after CI. No completed report or acceptance result yet; hold the
measurement environment fixed through terminal completion.

### Warmed-idle audit correction and controlled interruption

Read-only Luna audit identified a real P0.6 gap: `wait_ready` exercises auth and
`/feeds`, and the direct sidecar probe runs in another process. Neither warms
the measured feed-post/RSS HTTP routes. The runner's ten requests per target
route occur after its recorded idle window. Prior idle captures are cold, not
proof of the explicitly required warmed idle. P0.6 is reopened; other completed
writer parity/lifecycle tasks are not erased, and P4.6/P4.8 remain unchecked.

To avoid completing a knowingly insufficient five-run reference, root resolved
the exact driver via anchored Python/script/mode and output-path matching:
PID 147231, Python3, matching recovery-2 output. Only that PID received SIGINT.
Session 63664 terminated with exit 130/KeyboardInterrupt; its `finally` cleanup
ran. A scoped Docker query for `podly-writer-python-147231` returned no remaining
containers. No live process/container or production data was targeted.

Completed run 1 and protocol are retained read-only; no final report exists.
Run-1 SHA: `42df5c8141040645c32004b593ed57521e75f10c33ddc56e51f561eab2adfd00`.
Protocol SHA: `cd23cd5b5b38b709092b1cf2f9063cf728184799320dcf1efc474444479d63f2`.
Run 1 has all eleven original phases and positive same-window helper CPU for
all three writer workloads. This is intermediate evidence, not an accepted
baseline. Do not resume/reuse the interrupted directory as a paired reference.

Next focused change is additive: retain original cold idle and its existing
absolute/net-memory/resource/recovery gates, then sample a separate warmed idle
for thirty seconds after the existing target-route warmups. Warmed idle must
also meet the original absolute idle-memory cap and paired 50 MiB/25% reduction.
All cooldowns still must recover to cold idle + 10 MiB; warming does not raise
that allowance. New protocol policy requires the extra phase and pins its
duration. Historical reports/caps are not rewritten. Luna is implementing
runner/tests only; root must review and run CI before a new five-run pair.
Runtime image/helper are unchanged, so the same exact recovery-2 image may be
used with a new host-runner SHA in both arms; its bundled migration orchestrator
is not executed by the benchmark. No competing measurement remains active.

Current handoff: `/root/cpu_gate_audit` owns the additive warmed-idle runner/test
edits and has not run CI. Review `_warm_idle_window` ordering (close cold idle,
mark warmup, issue target HTTP warmups, quiet two seconds, warmed idle thirty
seconds, per-process snapshot, then loads), v4 protocol rejection, additional
warm memory gates, and unchanged cold recovery/resource gates. Once files are
stable, run full `mise exec -- ./scripts/ci.sh` in a fresh warmed-idle CI log.
Then capture five Python repetitions in a new recovery-3 directory using the
complete immutable recovery-1 report solely as fixture source and pinned
recovery-2 image. Do not use interrupted recovery-2 as a baseline. Freeze/audit
the new reference before its five matching Rust runs. P0.6 may only be checked
after warmed baseline evidence passes; P4.6/P4.8 require full Rust acceptance.

Warmed-idle runner verification follow-up: ordinary CI log
`/tmp/podly-rust-migration-p0-warmed-idle-ci-20260928-1.log` exited 1 at Ruff
because the new recovery regression test omitted the `P0_ACCEPTANCE` import.
The import was added. Retry log
`/tmp/podly-rust-migration-p0-warmed-idle-ci-20260928-2.log` exited 1 at `ty`:
the test fake sampler did not satisfy the declared `Sampler` type, and a
resource dictionary inferred as `object` used `.pop`. Ruff passed on this
retry; tests had not run. Luna is correcting only these test typing issues.
No checkboxes advanced and no benchmark restarted on either failure.
Luna corrected the test-only typing (`cast(Sampler, FakeSampler())` and
`_complete_run` returning `dict[str, Any]`). Full CI retry is session **28082**,
log `/tmp/podly-rust-migration-p0-warmed-idle-ci-20260928-3.log`.
Ruff, type checking, shell syntax, and Rust binary build passed; pytest is
running. Post-edit `git diff --check` passed. This is not a terminal CI result.
Preflight reconfirmed recovery-2 image ID
`sha256:6ae6e5c610485ff185942e643529f87859bc1a3cdd7fbce90814aeca4a965fed`
and the immutable recovery-1 source report SHA
`85ea9a13231a74c0c3c45085285a6479204b2a399422048066d33737cb5684a7`.
The new policy is `periodic-phase-end-helper-window-warmed-idle-v4`.
The warmed-idle edits are host-runner/report logic only; reuse this exact
runtime image for both arms, pin the post-CI host runner SHA, and do not use
the interrupted recovery-2 output as a paired baseline.

Warmed-idle ordinary CI session 28082 completed with **exit 0**:
1091 Python passed/2 skipped; Rust formatting/clippy, 58 writer + 97 existing
Rust + 3 transport tests, and writer registry differential parity passed.
`git diff --check` passed after CI. Host runner SHA-256 is
`03258c3df50e521dd97ea27fb53e4d58ec9a5e6bcf379cde2a634119adf2459e`.
No runtime/source changes are permitted while the matched measurements run.

Five-repetition warmed Python baseline launched via
`mise exec -- ./scripts/ci.sh --writer-baseline`, exec session **91784**,
log `/tmp/podly-rust-migration-p0-warmed-baseline-ci-20260928.log`, output
`/tmp/podly-writer-python-p0-20260928-recovery-3`. Environment selects pinned
image `podly-rust-writer-p4:20260928-recovery-2`, the complete immutable
recovery-1 report solely as fixture source, and repetitions=5. The output
directory was absent before launch. Poll original session 91784; do not
restart on observation timeout. This is not yet a verified baseline.
Next task: await terminal completion; audit all five runs for thirteen sampled
phases, thirty-second warmed idle, positive helper-window CPU, exact write
counts, Python process identity, HTTP 200 only, and zero errors/fallback;
freeze/hash report and protocol. Only then recheck P0.6 and start the matched
five-run Rust benchmark with the unchanged original threshold report.
P4.6/P4.8 remain unchecked. No deployment, production data, or web migration
changes were performed.

Baseline session 91784 remains live after its CI preflight passed (1091 Python
passed/2 skipped, 58 writer + 97 existing Rust + 3 transport tests, registry).
Run 1 has started. The actual output protocol confirms five repetitions,
Python backend, v4 sampling, helper-threadpool CPU v1, separate warmed and cold
idle windows of thirty seconds each, and exact runner/image/DB hashes above.
Fixture-tree SHA is
`18938fd962d9e2191d2f7f0395f88d275b70fda20e0224a706b7d6dce73fc2b2`.
No final report exists yet; P0.6 remains unchecked. Continue polling session
91784 and hold source/build/test workloads during measurement.

Baseline session 91784 remains live; run 1 completed and run 2 started.
Run 1 has positive samples in all thirteen phases, only HTTP 200 responses
(10756 feed-post requests, 399 RSS requests), no fallback or write failures,
and successful writer/timing counts exactly 1000/12/100. Helper-window CPU
seconds/duration: small 1.878207/1.696942, large 3.059168/3.218148,
mixed 2.597346/2.719560. Resource CPU fields agree with helper fields.
Cold/warmed idle memory medians are 193147699/197551718 bytes. Warmed process
snapshot confirms Python writer and web; this is intermediate evidence only.

Read-only Luna release audit used CodeGraph to verify the current container
harness. P4.4 is **reopened**, not erased: existing fresh/upgrade/restart,
non-root, rollback-on-kill, bootstrap failure, writer death, and retirement
evidence stands, but startup race prevention is currently supported by serial
source ordering and successful readiness/postconditions, not a runtime
assertion while writer readiness is withheld. `await_ready()` waits for the
full healthcheck, then `assert_retired_python_writer()` inspects processes.
The bootstrap failure test never reaches writer startup. Next required
isolated CI increment after measurements: hold/delay Rust protocol readiness,
assert web process/listener absent while not ready, then release readiness
and verify normal startup. Do not alter runtime or run competing CI during
the active baseline; preserve existing verified scenarios and gates.
P4.8 must include this additional dynamic startup proof as well as the full
performance comparison. No P5+ work is authorized by this audit.

Baseline session 91784 continues live with run 3 after run 2 completed.
Run 2 has all thirteen positive resource phases, Python backend/environment/
process identity, no fallback or writer/client failures, HTTP 200 only
(10773 feed-post requests, 396 RSS requests), and matching successful
write/timing counts of 1000/12/100. Helper CPU seconds/window durations are
small 1.829706/1.661705, large 2.851392/2.989126, mixed 2.595543/2.703008.
Cold/warmed idle medians are 183920230/184968806 bytes. The host runner hash
remains unchanged. Full five-run baseline acceptance is still pending.
Luna is implementing only the isolated startup harness's missing withheld-
readiness assertion; no runtime, image, CI script, or benchmark source edits
or competing workload runs are permitted during this measurement.

Baseline session 91784 remains live with run 4 after run 3 completed.
Run 3 again has all thirteen sampled phases, matching Python backend/
environment/process identity, no fallback or writer/client failures, and
HTTP 200 only (10575 feed-post requests, 402 RSS requests). Successful
write/timing counts match 1000/12/100. Helper CPU seconds/window durations:
small 1.845138/1.670526, large 2.947998/3.090648, mixed 2.583009/2.691804.
Cold/warmed idle medians are 170288742/174692762 bytes. Three complete runs
are intermediate data only: this protocol requires five and the final report
is not yet available. Poll original handle 91784, preserve the fixed host
runner/image/fixture, and audit/freeze only after terminal completion.

P4.4 readiness follow-up implemented by Luna in
`scripts/test_rust_writer_container.sh` and the executable test-only fixture
`scripts/writer_readiness_gate.py`. A dedicated non-root isolated container
runs its real Rust binary on loopback port 50002 behind a proxy on 50001.
The real binary's `--probe --port 50002` must pass first. While a marker is
absent, the proxy returns test-generated HTTP 503; repeated real launcher
probe and healthcheck failures plus `/proc` and refused port-5001 assertions
prove web is not started. Opening the marker forwards actual Rust responses,
then the existing health/process-retirement assertions must pass. This tests
launcher readiness gating, not the Rust handler's internal readiness
transition. No production flags/source or pinned benchmark image changed.
Root review caught a child-reaping gap on proxy bind/marker failure; Luna
included those operations inside protected cleanup. Containers/volumes and
the validated mktemp directory are uniquely scoped. No tests/build/container
commands ran during active measurement; `git diff --check` passed and runner
SHA remains unchanged. P4.4 stays unchecked pending
`mise exec -- ./scripts/ci.sh --writer-container` after baseline session 91784
terminates and before the paired Rust measurement begins.

Baseline session 91784 remains live with the fifth/final repetition after
run 4 completed. Run 4 has all thirteen positive resource phases, matching
Python selection/environment/process identity, no fallback or write failures,
HTTP 200 only (10586 feed-post requests, 393 RSS requests), and exact matching
write/timing counts 1000/12/100. Helper CPU seconds/window durations:
small 1.817736/1.645834, large 3.116073/3.245202, mixed 2.589691/2.693778.
Cold/warmed idle medians are 175321907/176265626 bytes. Do not freeze or accept
the reference until session 91784 terminates with all five runs and errors=[];
then audit/hash report and protocol, recheck P0.6 only if complete, run the
pending CI-owned delayed-readiness test, and start matched Rust measurements.
P4.4 remains reopened until that new runtime assertion passes.

P0.6 warmed-baseline re-verification complete: session **91784** terminated
with exit 0. The CI log ends with `errors: []` (the report itself contains
protocol/runs, not a top-level errors field). All five runs have thirteen
positive resource phases, HTTP 200 only at concurrency 8, correct Python
selection/environment/process identity, no fallback or client/writer failures,
exact successful write/timing counts 1000/12/100, and positive helper-window
and HTTP cumulative CPU. Separate warm process snapshots include RSS,
threads, and FDs; actual Rust feed/RSS probes return nonempty bytes in every
run. Cold/warmed/cooldown windows are fixed thirty seconds. Source DB/tree
and environment/runner/image hashes match the pinned protocol; successful
completion includes the driver's source-integrity checks. P0.6 is checked
again; original historical thresholds are unchanged.

Frozen mode-444 reference:
`/tmp/podly-writer-python-p0-20260928-recovery-3/report.json`, SHA-256
`95725e8de3cfbd4c3979ae55a5d8f68b6bdebd924ad2e10b425185fd0af256ad`;
protocol SHA-256
`d83b679db26c023155a3cb61de825f5d775c753111fc46fc4eac6519a904781d`.
Five repetitions satisfy the previously observed spread-required expansion;
this does not waive performance/CPU/memory gates for the Rust arm.

P4.4 delayed-readiness verification launched after baseline terminal via
`mise exec -- ./scripts/ci.sh --writer-container`, session **66486**, log
`/tmp/podly-rust-migration-p4-delayed-readiness-ci-20260928.log`.
Poll original handle; no benchmark is active now. Inspect formatting/type
changes and all existing plus new container scenarios. P4.4 remains unchecked
until this run passes. Afterward run the five matched Rust repetitions using
the frozen recovery-3 reference, unchanged recovery-2 image and host-runner
hash/policy, plus original P0 threshold report. P4.6/P4.8 remain open.

P4.4 dynamic readiness follow-up passed: session **66486**, terminal exit 0,
log `/tmp/podly-rust-migration-p4-delayed-readiness-ci-20260928.log`.
Ordinary CI passed 1091 Python/2 skipped, 58 writer + 97 existing Rust + 3
transport tests, formatting/type/clippy/shell checks, and registry parity.
The isolated lifecycle log advances through withheld readiness, prior-schema
upgrade, persistent restart, interrupted transaction rollback (write lock
confirmed), writer-death dependent shutdown, and bootstrap failure to the
final passed line. Since the shell gate is fail-fast, all eight repeated
closed-gate probe/health failures, absent web process/refused listener checks,
and post-release actual probe/health/process assertions passed. P4.4 is
checked again. Caveat: closed-gate 503 is test-generated; actual Rust's full
probe succeeds behind the proxy and after release. The test does not claim
to delay Rust's own executor initialization. CI formatted the new fixture;
post-CI diff check passed, and host benchmark runner SHA is unchanged.
Fixture SHA-256:
`8e6afb975936f5b6cddf6bb1411e9e1e5304e767a0edf2abf96ddfa984f50f70`.

Matched five-run Rust comparison launched via
`mise exec -- ./scripts/ci.sh --writer-benchmark`, session **23399**, log
`/tmp/podly-rust-migration-p4-warmed-comparison-ci-20260928.log`, fresh output
`/tmp/podly-rust-writer-p4-recovery-20260928-3`. It selects the same recovery-2
image, frozen recovery-3 Python report SHA
`95725e8de3cfbd4c3979ae55a5d8f68b6bdebd924ad2e10b425185fd0af256ad`,
five repetitions, and original P0 threshold report SHA
`2ec8584b9070e1326dabf4f02b343fc15351055e04004f3b236774cd58dc9af1`.
Both report hashes were revalidated before launch. Poll original session
23399; hold source/build/test workloads after preflight enters measurement.
Next: audit all five runs for actual Rust identity/readiness/retirement,
thirteen resource phases, positive helper-window CPU, exact write counts,
zero failures/fallback, and real all-arena purge success. Freeze final report,
protocol, and comparison, then inspect **every** historical/paired gate and
resource/spread/recovery constraint. Purge log success does not prove memory
recovery. P4.6/P4.8 remain unchecked until full acceptance; no P5+ work or
live deployment is authorized.

Five-run Rust recovery-3 comparison is terminal and **failed acceptance**.
Session 23399 no longer exists in the process tool; no exact matching
benchmark process remains, and the log ends with the complete report/error
JSON. Its exit status was not returned by the expired handle, so it is not
recorded as observed. All five run files, final report, protocol, and comparison
exist. Actual protocol pins the expected image/runner/fixture/env, five runs,
Python reference SHA95725..., and original historical SHA2ec858... .
The final error JSON lists missing `arena_purge=all rc=0` evidence in every
run plus failing memory and thread/FD recovery gates. Other historical and
paired latency/throughput/CPU/idle/warmed-idle/writer-RSS/identity/fallback/
spread/equivalence gates pass; no failure is waived because writes are fast.
Memory extra bytes by run: 64697139, 64969769, 69373788, 72509030, 65515028
versus the unchanged 10485760 allowance. Threads delta is zero in every run;
FD deltas are 9/8/9/9/9 versus allowance 8. Rust writer itself stays at four
threads/thirteen FDs; web grows from fourteen FDs to twenty-three. Every
trim evidence record is missing/empty; this does not establish whether the
purge failed to execute or its log was not captured.

Failed artifacts preserved mode444:
report SHA `9cbeead06bddd315833d0ba78f34cd00c66871621c944b606c64fbcb6d865901`;
protocol SHA `03376ae4554dd39ce19e8a70ba5749b8fa5ef2045ca0847d04f740e440aa9a3b`;
comparison SHA `653d28d5a03761cba63899794dcaa8b3f7927566acc7318dbdbd0243a15f318d`.
Next: Luna CodeGraph diagnosis of purge scheduling/config/log extraction and
separate web FD ownership/lifecycle audit. No benchmark remains active, so
implement verified causes with regression tests and required CI, then rebuild
and measure an appropriately matched pair without changing thresholds.
P4.6/P4.8 remain unchecked; P4.4 dynamic readiness verification stands.

Recovery diagnosis follow-up: CodeGraph's targeted `_docker_env` source and
the current file confirm benchmark `PODLY_WRITER_IDLE_TRIM_INTERVAL_SEC=900`,
not two seconds. The 30-second cooldown cannot establish idle all-arena purge
under that interval. This corrects any earlier assumption of a short benchmark
override; no source/threshold change has been made to manufacture a purge.
Luna confirms Docker stdout/stderr is captured before container removal, so
Python volume `app.log` alone is not the trim parser's input. Investigate the
actual Python/Rust release/allocator scheduling contract and retain the original
profile/config until a justified implementation decision is documented.

FD audit confirms artifact counts cannot identify descriptor targets. The
existing read pool already retains three connections and allows seven overflow
(total ceiling ten); another reduction is not justified by counts alone.
Luna is implementing synthetic-only FD classification and an explicit one-run
CI recovery diagnostic that cannot masquerade as a valid paired reference.
This changes measurement instrumentation, not runtime pool behavior or gates.
Root must review and run CI; no builds/tests/containers are currently active.

## 2026-09-23 P3/P4 isolated integration increment

## 2026-09-28 stopping-point handoff — P4 baseline provenance decision

Replacement Python P0 verification completed after user approval:
`/tmp/podly-rust-migration-p0-replacement-ci-20260928.log` exited 0;
1047 Python tests passed/2 skipped, Rust fmt/clippy and 52 writer + 97 existing
+ 3 transport tests passed, and the registry gate passed. The subsequent
three baseline runs completed with `errors: []`. Every run has all eleven
resource phases, exclusively HTTP 200 responses, 1000/12/100 successful
small/large/mixed writes with matching timing counts, no writer failures,
and no fallback logs. Environment and process identity both confirm Python.

Frozen replacement report:
`/tmp/podly-writer-python-p0-20260928/report.json`, SHA-256
`9923709f6513837c6ddd18a5e50aab0665ae9fc1cea0103df48d9bfa66988854`.
Report and protocol were made read-only before any Rust measurement.
Canonical source DB SHA remains
`851273de0f0b149969e0eccc5da319c04f6c70e0283a29bfcf2a652688b33718`;
protocol pins source-tree SHA
`18938fd962d9e2191d2f7f0395f88d275b70fda20e0224a706b7d6dce73fc2b2`.
Runner verified the frozen source before/after clones and runs. Paired image
ID is `sha256:c072a50c4585d771c0873b95c0a96c419018950b0a7d95d1cc3a9dd7127538c8`
(`podly-rust-writer-p4:20260928-acceptance-2`). Original artifacts remain intact.
Next task is the dual-reference comparator verification and paired Rust runs
using this exact source/image. No P4.6/P4.8 checkbox is advanced by this baseline.

Independent read-only audit reconfirmed report/DB hashes, read-only source,
absence of WAL/SHM sidecars, backend/process identity, HTTP probes and exact
write/timing counts. Idle medians (201.3/173.6/173.3 MB) and feed P95
(45.279/39.321/40.665 ms) exceed 10% spread. Proceed with three matched Rust
runs, but require five matched runs if that spread could reverse a gate;
retain all three initial samples. Provenance limitations: protocol records
environment names rather than effective values (backend is captured per run),
and pins image ID rather than source Git/build-context hashes. Python readiness
is evidenced by process lists and successful HTTP probes, not a dedicated
writer readiness payload. These limitations do not waive any acceptance gate.

Dual-reference comparator review found and corrected a potentially false-green
spread test: uncertainty must recompute derived gates at observed extrema,
including Rust spread, and CPU uncertainty must match ratio-of-medians gates.
A second audit found that reconstructing old environment values from today's
runner could not prove equality. The fingerprint-less capture above remains
preserved as evidence, but is not sufficient for final paired acceptance.
Next: regenerate Python with an environment fingerprint using the same frozen
source and image, then require exact fingerprint equality for paired Rust.
No legacy reconstruction bypass is accepted. Original P0 caps/CPU constraints
remain mandatory.

Comparator verification attempts: default-sandbox CI exited 2 before tests
(read-only uv cache); escalated CI log
`/tmp/podly-rust-migration-dual-baseline-ci-20260928-2.log` exited 1 on Ruff
branch/closure/unused-variable findings. After fixes, `...-3.log` exited 1 on
new test-helper type annotations; Ruff passed. These are tooling verification
failures, not measured Rust performance regressions. No Rust measurement exists
at this point; subsequent CI must pass before measurement.

Current verified continuation: comparator CI passed in
`/tmp/podly-rust-migration-p0-fingerprinted-ci-20260928-2.log`: 1052 Python
passed/2 skipped, Ruff/type checks, Rust fmt/clippy and 52 + 97 + 3 tests,
registry differential gate. Prior fingerprinted attempt exited 1 on four
benchmark-test assertions (1048 passed/2 skipped); corrected and rerun, no
baseline measurement occurred in that failed attempt.
The successful CI invocation is now measuring fingerprinted Python P0 in
`/tmp/podly-writer-python-p0-20260928-fingerprinted`; exec session **42758**
was polled live after CI and run 1 started. Do not restart on observation timeout.
Protocol reconfirms the identical image/DB/tree hashes recorded above and pins
environment fingerprint
`b166c8b9c2132cf269bb3e52174d45491651798db0b3ed03a626330708a094ee`.
The report is not yet complete. Hold benchmark source edits and competing
workloads until this session is terminal; then audit/freeze the resulting
report and use it as `PODLY_WRITER_BENCH_BASELINE` for Rust CI benchmark mode.
Use the original report as `PODLY_WRITER_BENCH_THRESHOLD_REPORT` so both original
and stricter paired constraints are enforced. P4.6/P4.8 remain unverified.

Fingerprint-complete baseline finished: session 42758 terminal exit 0,
`/tmp/podly-rust-migration-p0-fingerprinted-ci-20260928-2.log` ends with
`errors: []`. All three runs have eleven resource phases, Python backend
environment/process identity, only HTTP 200, exactly 1000/12/100 successful
writes with matching successful timing records and no fallback/failure logs.
Report SHA-256:
`0f5a6bc9d92ad10d995f62f14890c30a0c732038562d124d6d0eb4927fb94642`;
protocol SHA-256:
`24f31ced2734285b6cb4483ca210a71bfe2f3a3528ed016df90344d0f77596f3`.
Both files are read-only before Rust measurement. DB SHA remains
`851273de0f0b149969e0eccc5da319c04f6c70e0283a29bfcf2a652688b33718`.
This fingerprint-complete report supersedes the prior replacement capture as
the paired reference; historical artifacts and original absolute/CPU limits
remain intact. CI autoformat changes reviewed; `git diff --check` passes.

Active paired Rust invocation: exec session **71361**, log
`/tmp/podly-rust-migration-p4-paired-ci-20260928.log`, output
`/tmp/podly-rust-writer-p4-paired-20260928`. It runs normal CI first, then
`--writer-benchmark` with the fingerprint-complete Python report and original
P0 threshold report. Poll this handle to terminal; no comparison result exists
yet. Do not restart solely on timeout or edit measurement source mid-run.

Paired Rust session 71361 is now terminal, exit 1. Ordinary CI passed
(1052 Python passed/2 skipped, Rust fmt/clippy/tests 52 + 97 + 3, registry).
All three runs proved Rust writer identity/readiness, had no write failures
or fallback logs, and completed the prescribed workloads. Median end-to-end
write P95: small 3.531 ms vs Python 12.840; large 143.821 vs 2060.692;
mixed 40.815 vs 446.652. This proves faster writes, not overall acceptance.

Performance acceptance failed measurement completeness: all three fast
large-write bursts fell between periodic Docker resource samples, so
`writer_large` is absent. Comparison reports `complete_measurements: false`
with `KeyError`; remaining gate calculation is masked, not proven passing.
Do not fill missing CPU samples with zero or accept this report.
Independently observed writer RSS after cooldown is
68,382,720 / 67,624,960 / 60,534,784 bytes, above the original 49,753,293 cap.
Container idle medians 127,087,411 / 102,299,075 / 101,953,044 become final
187,904,819 / 160,641,844 / 153,826,100 bytes: every run exceeds idle + 10 MiB.
Rust writer accounts for most growth (ready about 12 MB; final 61–68 MB),
with stable 14 threads/13 FDs; Python web RSS increases about 4 MB.
Python web FD counts rise by 11 in both backends, suggesting common read-pool
retention rather than Rust-only transport leakage; root cause is not yet proven.

Report SHA `b85decf40c0f397a267c1ba2d650447c290ad75a780acb349f881c6cf33a074a`;
comparison SHA `b34f7bb9384672ffbd7204d44a36be65d579259423c06c7d192282be54ec232f`.
Next increments: repair short-phase sampling without changing workload or
relaxing original CPU limits, investigate bounded Rust runtime/JSON allocation
retention and shared FD growth, run CI, rebuild an isolated image after runtime
changes, and repeat same-image Python/Rust baselines. No gate checkbox advanced.

Recovery implementation increment (not yet rebenchmarked): Rust Tokio I/O
workers fixed at two, separate from the single SQLite owner; the real-binary
transport test now asserts four Linux threads while retaining its eight-client
correlation test. Sampler phase changes synchronize with in-flight sampling
and explicitly sample the outgoing phase, so fast bursts cannot disappear;
workload latency/throughput timers remain outside boundary probes. Database
pool retains three idle connections instead of five, with overflow seven
instead of five: the total ten-connection ceiling and 60-second timeout are
unchanged. A fresh isolated SQLite test checks ten checked-out connections,
then only three retained after release. This targets common descriptor
retention; its measured benefit and latency effects remain unproven.

Verification: `/tmp/podly-rust-migration-p4-runtime-sampling-ci-20260928.log`
passed 1054 Python tests/2 skipped, then exited 1 on Rust assertion formatting.
After correction and the pool regression test,
`/tmp/podly-rust-migration-p4-runtime-sampling-ci-20260928-2.log` exited 0:
1055 Python passed/2 skipped, Ruff/type checks, Rust fmt/clippy and 52 + 97 + 3
tests, registry gate. Reviewed formatter changes; `git diff --check` passes.
A Luna agent reported a usage-limit failure during follow-up; root continued
with approved targeted CodeGraph query/node/impact lookups, not main-session
explore/context calls. No deployment or production data action occurred.

Subsequent tooling edits pending verification: record and require matching
runner SHA and `periodic-and-phase-end-v1` sampling policy in paired reports;
permit a refreshed Python baseline to reuse a frozen fixture from an older
image, while Rust comparisons still require exact same-image pairing. Added
two regression cases for that image rule. Thus older periodic-only reports
are historical artifacts, not valid new paired references. Original P0
absolute/CPU limits remain enforced; Docker CPU percentages remain sampled
averages rather than exact per-command CPU-cycle counters.

Current isolated image build: exec session **46796**, tag
`podly-rust-writer-p4:20260928-recovery-1`, log
`/tmp/podly-rust-migration-p4-recovery-image-20260928.log`; polled live while
Rust compilation was underway. Next: poll to terminal, run CI baseline mode
using this image and the fingerprinted source report to reuse the exact
immutable DB, then freeze its report and repeat Rust with both old thresholds
and the new same-image baseline. Do not infer memory acceptance from the code
changes. P4.6/P4.8 remain unchecked and P5+ has not started.

Image build 46796 finished exit 0. A recovery-baseline CI attempt failed type
checking on a new test's `SimpleNamespace` argument; corrected to
`argparse.Namespace`. The next attempt, session 46972/log
`/tmp/podly-rust-migration-p0-recovery-ci-20260928-2.log`, was deliberately
stopped before benchmark startup (exit 143). Root verified process group
4107617 contained only that CI, pytest and its resource tracker, then stopped
that exact isolated group. No container or production process was stopped.
Reason: a phase-end Docker CPU percentage can sample only idle time after a
fast burst, falsely suggesting zero execution CPU. Memory boundary sampling
is retained, but it cannot serve as short-burst CPU evidence.

Current CPU correction: read cumulative cgroup CPU counters immediately before
and after each HTTP/write workload; normalize the positive CPU delta by the
client's measured workload duration. Retain periodic CPU averages separately
for diagnostics. Original P0 CPU comparison remains enforced, as does the new
same-image paired comparison; no historical value is rewritten. V2 accounting
uses `usage_usec`, V1 uses `cpuacct.usage`; permissions/malformed/non-increasing
counters fail explicitly rather than becoming zeros. New paired protocol
policy is `periodic-phase-end-cumulative-cpu-v2`, with matching runner SHA.
Tests cover both counter formats, permission denial, invalid/zero deltas, and
short-workload accounting. CI is currently exec session **24014**, log
`/tmp/podly-rust-migration-p4-cumulative-cpu-ci-20260928.log`; poll to terminal.
No new baseline measurement is underway. After CI, capture a new baseline
against `podly-rust-writer-p4:20260928-recovery-1` using the prior frozen source,
then repeat Rust on the same image/policy/runner. Do not reuse old CPU reports
as the paired reference. Decoder inspection also shows owned JSON values are
consumed and action parameters moved; multiple representations alone do not
prove deep-copy duplication. No decoder rewrite was made on that hypothesis.

CPU-correction CI 24014 finished exit 0: 1065 Python passed/2 skipped,
Ruff/type checks, Rust fmt/clippy and 52 + 97 + 3 tests, registry. Original P0
CPU metrics were rechecked and are positive for all five workloads in all
three historical runs; the old guard is calculable and remains mandatory.
An additional summary regression now verifies that the cumulative workload
CPU result replaces a zero post-burst periodic average while retaining that
average separately for diagnostics.

Latest continuation handle: exec session **50642**, log
`/tmp/podly-rust-migration-p0-recovery-ci-20260928-3.log`, expected output
`/tmp/podly-writer-python-p0-20260928-recovery-1`. It is currently in normal CI,
then will run three Python baselines against the completed recovery image,
using the prior immutable fingerprinted report solely as the fixture source.
Poll this exact session to terminal; do not restart on timeout. Hold runtime
and benchmark source edits/competing workloads once measurement begins.
After success, audit positive cumulative CPU deltas and all eleven resource
phases, record report/protocol/source hashes, make the report read-only, then
use it for same-image Rust runs with the unchanged original threshold report.
P4 memory/recovery/FD effects remain unverified; no acceptance checkbox advanced.

Latest CI portion passed: 1066 Python tests/2 skipped, Ruff/type checks,
Rust fmt/clippy and 52 + 97 + 3 tests, registry. Session 50642 remains live
and recovery Python run 1 has begun. Its protocol pins image ID
`sha256:4f453c2bfda12f0c6e81e7e25a75a53f7ef5fced184e3a4578fcea0708d61906`,
the unchanged DB/tree/environment hashes above, and runner SHA
`83664a3e0c2dfb67518e3d422ebc95767d5e3779296fab7028a6615f390cc19d`.
The sampling policy is cumulative-CPU v2. No completed recovery report exists
yet. Preserve the pending session and all historical reports for handoff.

User decision received: approved establishment of a fresh immutable P0
baseline without relaxing existing acceptance thresholds. The provenance
blocker below is resolved by that authorization, not by changing the old
fixture hash. Retain the original artifacts/results and fixed P0.7 limits;
freeze/checkpoint the replacement source before hashing, verify it remains
unchanged across baseline and paired runs, and enforce the original CPU limits
as well as any stricter replacement-baseline-derived limits. P4.6/P4.8 stay
unchecked until the measurements and full release audit pass.

Replacement-pair gate rules fixed before new Rust measurements: run the same
immutable image and exact P0 workload/environment profile (only the writer
selector differs). Require every original P0.7 absolute limit and its original
CPU-efficiency comparison. Also require CPU efficiency within 15% of the fresh
Python backend. Idle memory must satisfy the minimum of the original cap,
fresh Python idle minus 50 MiB, and 75% of fresh Python idle; writer RSS must
satisfy the minimum of the original cap and 40% of fresh Python writer RSS.
For maximum latency/queue limits, preserve the original regression budget:
the paired cap is the minimum of the old cap and fresh Python median plus
(old cap minus old Python median). Throughput floors are the maximum of the
old floor and fresh Python median minus (old Python median minus old floor).
Recovery/resource/correctness/process-retirement gates remain unchanged.
Use at least three repetitions and expand to five if gating spread can change
the decision. Freeze and checksum the replacement report before Rust runs.

Completed in this resume: P4.5's full isolated rollback gate, stricter legacy
action registry coverage, composite transcription empty/rollback parity,
benchmark CI mode and verification tests, inventory/Appendix reconciliation,
and CI-only benchmark controls in `.env.local.example`. Branch remains
`rust-migrate-v2`, base `469baf5`, with these changes uncommitted; preserve them.
Current main was already merged at `9de04b3`. No web migration/deployment/live
restart/production write was performed. P4.6 and P4.8 remain unchecked.

Exact verification: rollback
`/tmp/podly-rust-migration-p4-rollback-ci-20260928-2.log` exit 0 (1028 Python
passed/2 skipped, Rust checks/tests, registry, full container rehearsal).
Final verification snapshot
`/tmp/podly-rust-migration-p4-acceptance-ci-20260928.log` passed ordinary CI
(1044 Python passed/2 skipped; Rust fmt/clippy, 52 writer + 97 existing +
3 transport tests; registry) but the overall command exited 2 at benchmark
preflight. No measured P4 container run or performance result exists.
`git diff --check` passes. Reviewed CI auto-format changes are included.

Blocking evidence: the original P0 report SHA still matches
`2ec8584b9070e1326dabf4f02b343fc15351055e04004f3b236774cd58dc9af1`.
Both report and protocol record fixture SHA
`2ff695d7df8c86cca670890122d95a962a7da63a44006bd1ef3261ae1d7d3323`,
but the retained source database hashes
`81acf319252a7a212bf403e495934d638d23e6b8d6f4c0957612d77633176230`.
Protocol was written at Sep 20 20:25:12.776; database mtime is 20:39:16.858,
48 ms after the final report. It is WAL mode with valid integrity/schema;
the original WAL bytes are unavailable. Current source has 341 4096-byte pages,
header counter/version-valid-for 2, freelist 134 pages. A bounded read-only
in-memory attempt of 300 plausible journal/header/page-count variants did not
recover the recorded SHA. No retained P0 database matches it; run clones are
post-workload snapshots, not immutable initial fixtures. The original image
predates fixture generation. Checkpointing is plausible but unproven; neither
logical equivalence nor the original bytes can be asserted from these artifacts.
Original main DB bytes were not modified during investigation. SQLite's
read-only WAL inspection may create shared-memory sidecars; none supplies the
missing original WAL. Do not rewrite the expected hash or bypass preflight.

Prior blocking next task (now resolved by user approval): obtain user direction to provide an immutable fixture matching the
recorded SHA, or establish a replacement immutable/checkpointed P0 baseline
without relaxing existing acceptance thresholds. Before any Rust comparison,
freeze and verify the replacement fixture and protocol, run at least three
Python baselines, and record any new stricter thresholds. Then repeat paired
Rust workloads via `mise exec -- ./scripts/ci.sh --writer-benchmark`; keep old
absolute/CPU/resource acceptance limits as well, rather than making a weaker
gate. Current isolated image is `podly-rust-writer-p4:20260928-acceptance-2`,
build log `/tmp/podly-rust-migration-p4-acceptance-image-20260928-2.log`.
CI requires `PODLY_WRITER_BENCH_IMAGE`; optional baseline/output overrides are
documented in the environment template. Disposable images remain available for
resume; no live image/tag was overwritten. Benchmark output preflight directory
`/tmp/podly-rust-writer-p4-benchmark.nJaJT1` contains no measured report.

## Earlier integration evidence

2026-09-28 final parity/documentation audit increment:

Task IDs: P2.6/P2.8 audit follow-up and Appendix A reconciliation.
Files: registry checker/coverage manifest, registry regression test, processor
parity cases, writer inventory, plan Appendix A, benchmark runner/CI/tests.
All four retained non-production actions now pin their existing differential
cases without losing their unreachable-caller rationale. The registry gate
validates every supplied case, including unreachable rows; a regression test
rejects an unexecuted supplied case. Composite `replace_transcription` adds
empty replacement and failure-after-delete/partial-insert cases with complete
rollback projection checks. These pass the same independent live-writer clone
harness as production actions. `clear_all_jobs` is conservatively referenced
by its literal call in an uninvoked manager API, explaining the P0 five-gap
versus manifest four-exception distinction. Inventory statuses and all 57
Appendix A entries are reconciled only after this verification.
CI: `/tmp/podly-rust-migration-p4-acceptance-ci-20260928.log` passed Ruff/ty,
shell syntax, 1044 Python tests (2 skipped), Rust fmt/clippy and 52 writer,
97 existing, 3 transport tests, and the registry gate. The benchmark preflight
then exited 2 before launching measured containers because the retained P0
fixture hash was `81acf319252a7a212bf403e495934d638d23e6b8d6f4c0957612d77633176230`,
not the recorded `2ff695d7df8c86cca670890122d95a962a7da63a44006bd1ef3261ae1d7d3323`.
P4.6/P4.8 remain unchecked; investigate fixture/hash semantics without relaxing
the fixed P0 profile. Earlier tooling logs record corrected lint findings and
the registry-test manifest-wrapper fixture failure (1043 passed/1 failed).
No live service/data or default backend changed.

2026-09-28 P4.5 acceptance:

Task ID: P4.5.
Commit/reference: `469baf5` plus the reviewed reconciliation-audit correction.
Files changed: `scripts/test_rust_writer_rollback.sh`.
Behavior preserved: an isolated one-shot bootstrap exits before the sole Rust
writer starts. Real Rust RPC commits one pending and one interrupted running
job; read-only inspection confirms the mounted database. All clients and Rust
stop before a quiesced SQLite backup and integrity/schema/all-ORM checks.
Only then does the Python writer start against that same unchanged schema.
Its actual IPC readiness precedes two intentional commands: explicitly mark
the known interrupted job failed, then claim the pending job once. No unknown
Rust command is replayed. Every processing-job column is compared with the
backup: only the pending claim's status/start time and the reconciliation's
status/completion/error/exact step-name marker may change. Table counts match.
Tests/CI: `mise exec -- ./scripts/ci.sh --writer-rollback`,
`/tmp/podly-rust-migration-p4-rollback-ci-20260928-2.log`, exit 0. Ruff/ty,
shell syntax, 1028 Python tests (2 skipped), Rust fmt/clippy and 52 writer,
97 existing, 3 transport tests, registry gate, and the complete isolated
rollback rehearsal passed. Unique disposable image/containers/volume were
cleaned by the test. No live data, deployment, or restart was involved.
Remaining limitations: P4.6 paired measurements and P4.8 release audit remain
open; Python remains the default backend. The earlier run's extra `step_name`
delta was the explicitly requested reconciliation value, now asserted exactly.

2026-09-28 main-fold audit: current `main` (`5a0c283`) is already an ancestor
of migration HEAD through merge `9de04b3`; `HEAD..main` contains no commits.
Notification settings, chapter overrides, job total-steps, and permanent-failure
retry changes from main have Rust equivalents and differential coverage. No
additional merge or production mutation was required.

2026-09-28 resume: the checkout was clean on `main` (`5a0c283`), then
switched with approval to the existing migration branch (`469baf5`). No
uncommitted user work was present. Fresh `mise exec -- ./scripts/ci.sh
--writer-rollback` logged to
`/tmp/podly-rust-migration-p4-rollback-ci-20260928.log`: ordinary CI and the
registry gate passed. The isolated rehearsal verified committed Rust rows,
quiesced backup/integrity/schema/ORM compatibility, exclusive Python startup,
interrupted-job reconciliation, pending-job claim, and no command replay.
The wrapper exited 1 at its final field-delta audit because reconciliation
also changed `step_name`; this is not accepted P4.5 evidence. The next task
is to verify that field against the submitted action and Python contract,
assert its exact intended value, then rerun the complete gate. P4.6/P4.8
remain open. No live instance or production data was modified.

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
