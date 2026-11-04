# Issue #169 — Q1-D recovery: partial local evidence

**Disposition: INCOMPLETE / NOT READY FOR REVIEW AS COMPLETE.** The owner
separately authorized Q1-D implementation and synthetic-only qualification in
Issue #169. Q1-E, scientific/production runs and formal gate closure remain
unauthorized. No Q1-01…23 `FULL_PASS` is claimed. This report records only
representative local checks, not the required full Q1-D matrix.

## Boundary and observations

| Boundary | Expected | Observed |
|---|---|---|
| Interrupted arm initialization | Retain the seal and prior committed results; retry only the pending evaluator attempt in a new session. | Fresh real SQLite fixture interrupts L-SHADE initialization at ordinal 10. Ordinals 1–9 are not redispatched, ordinal 10 is retried with identical physical bits, and both arms finish with 234 independent committed results/trace rows matching the seal. |
| New session after a committed search step | Restore the contiguous step prefix, including backend, RNG ordinal and watchdog state. | Both arms restored one committed step in the focused synthetic test. |
| Result committed, before next optimizer-step commit | Reconstruct the transition from its pre-state with the committed RNG and result; do not dispatch another evaluator call. | Both arms reproduced the interrupted backend snapshot and 236 unique FE/trace rows in a new session. |
| Candidate record mapping serialization | Stable snapshot bytes despite canonical journal decoding of mapping key order. | Candidate record mappings are serialized in canonical key order; cache/population ordering is not sorted. Existing same-session replay tests pass. |
| Uninterrupted vs fresh session, both arms | Match ordered logical RNG and proposal events, physical evaluator inputs, result/trace and optimizer state, rank/best/top-16. | Starting from the same isolated committed SQLite initialization prefix, two search steps match exact typed event bytes, complete live-state snapshot, trace and top-16; 236 FE. The crash is before the second step commit, after its result. For L-SHADE a synthetic zero-score search evaluator deliberately forces improvements, so the compared state includes nonempty archive/success batch and a shrunken population. This does not reach a memory flush or archive trim. |
| RNG STARTED / lost NumPy return | Pending call is regenerated from its pre-state under the same ID. | DE synthetic fixture interrupts before and after physical RNG invocation; one START and one COMMIT for the logical call on new-session replay. |
| Evaluator interruption | No FE until result; a repeated physical attempt is not a modeled physics failure. | DE fixture records two identical physical attempts, one infrastructure interruption and one committed 235th result/FE. |
| Pending intent / result identity | Require an ordered intent, attempt and matching result inside the current pending optimizer transition before hydration. | A schema- and rank-valid forged result without an intent previously reached restore; now it is rejected before either arm hydrates. Intent key/vector/ordinal/step and attempt numbering, event identities and matching result fields are checked on reload. |
| Proposal committed before intent | Generate the same intent without redrawing committed RNG. | DE fresh-session fixture reproduces the proposal's physical bits, does not invoke the RNG and commits one FE. |
| DE duplicate transaction | Replay a committed duplicate with its retry/counters exactly once and complete the pending target. | A forced first duplicate is interrupted after its atomic journal transaction; fresh-session replay records one duplicate, retry indices 0/1, two proposals, one pending target and one additional FE. |
| L-SHADE duplicate/fallback, zero-FE step | Replay all committed RNG and duplicate proposals, preserve zero FE, commit the step once. | An injected duplicate-only canonicalizer forces six normal and 256 fallback attempts; fresh-session replay reproduces the exact post-state with no new draw/evaluation, then rereading the commit leaves the journal head unchanged. This is a forced boundary fixture, not a normal canonicalizer trajectory. |
| Foreign pair identity | Fail before hydration/evaluation. | Altered config identity is rejected at genesis reconciliation. |
| Journal corruption | Fail before evaluator dispatch. | A modified event payload is rejected on journal reopen before geometry/evaluator call. |
| Hash-valid inconsistent snapshot/result | Check identity, FE/cache/RNG prefix and result rank/best before hydration. | A post-state with an extra FE, a separate forged result rank, and a cache result changed while preserving its key set are rejected before either arm hydrates or evaluates. Both arm caches and population/pending records in snapshot START/COMMIT states are compared against committed prefix results; result rows are schema/rank/best checked on reload. |
| Hash-valid pending-step pre-state | Require ordered START/COMMIT transitions and the exact immediately preceding committed snapshot, RNG ordinal and watchdog counter before hydration. | A DE snapshot with two population members swapped but valid cache, FE, results and RNG is rejected before either arm hydrates or evaluates; the baseline implementation failed this test. Genuine two-step two-arm parity and evaluator retry continue to pass. |
| Hash-valid L-SHADE history | Reconcile compact rank/vector/order index, incumbent record and stable top-16 against the exact FE ledger before hydration. | A forged post-step history rank previously reached restore; it is now rejected. Both trajectory parity cases, interrupted initialization and forced zero-FE fallback remain passing. |
| Checkpoint / journal prefix | Atomically snapshot only a committed optimizer boundary; verify identity, population, digest, sequence and prefix before hydration; replay a valid later journal tail. | Real SQLite DE fixture crashes before and after checkpoint insertion, confirms zero/one event, resumes with next sequence, adds a search step and verifies stale-checkpoint recovery. A hash-valid wrong-head checkpoint is refused before either arm hydrates. Resume currently rebuilds from verified optimizer events, not by loading the checkpoint as an acceleration. |
| 4096-FE step commit before terminal event | Restore without rerunning and seal one search-only terminal status. | Minimal mocked-state SQLite transition fixture verifies one durable terminal event, no extra state/FE/RNG; this is not a 4096-FE trajectory test. |

The uninterrupted comparison is deliberately bounded to two search steps;
it does not establish full-horizon equivalence, a memory flush or archive trim,
or a real 4096-FE terminal trajectory. The separately forced fallback and
duplicate/no-FE probes below are not full coverage of those paths. More
fault boundaries and identity, malformed snapshot, checkpoint and corruption
tests are needed; the prefix checks do not yet prove every possible malformed
but hash-valid event sequence, pending proposal/cursor transition, or checkpoint. In particular, this partial implementation
must not be used as evidence of fail-closed recovery for all Q0 cases.
Q1-12/16/19 and dependent Q1-03/05/06/07/14/15/17/18 remain
`PENDING_DEPENDENCY`; independent review and final Q1-E fingerprint are also
outstanding.

## Local clause disposition

| Primary gate | Local evidence | Still pending; not `LOCAL_EVIDENCE_READY` |
|---|---|---|
| Q1-12 | Typed modeled/invalid outcomes, infrastructure retry, partial initialization and selected mismatch refusals. | Full failure taxonomy, checkpoint/journal mismatch and exhaustion paths. |
| Q1-16 | Selected genesis/RNG foundation cases, partial initialization, proposal/duplicate/result replay, forced zero-FE fallback, committed-step prefix and checkpoint before/after-commit recovery. | Complete distinct transaction table, remaining cursor/checkpoint/validation paths, memory flush/archive trim and terminal full-horizon recovery. |
| Q1-19 | Two-step both-arm typed event/state/trace/top-16 comparison; durable FE/result/rank consistency checks. | Complete trace/counter reconciliation and actual full-horizon both-arm parity. |

## Reproducible bounded trajectory fingerprints

The following are **local synthetic software evidence**, not full-horizon Q1
qualification. Source tested: `6bf0039b7f0f546308ac91f27ae67b391f15a9b2`;
Python 3.12.3, NumPy 2.5.3, Linux WSL2 x86_64/glibc 2.39; locked dependency
SHA-256 `5dfd4435726518e40d5991fadc5af4099725cc0763af932e1f9015066aa1f0ff`;
fixture source SHA-256 `e3bea6f09c05d28a61afc53ccab979dc42275d1de59a58182b45331f9569861c`.
The fixture's declared synthetic config SHA-256 is
`c7375948cc05269ff8643754615d605a6a54c7f5a0ef83c118a8f3adb7245e0a` and its
declared environment SHA-256 is
`ed803ebaf5e6802cca2132164095a8cd8e61b613c53b7f8de1d7c1e37aa6dc12`.
These are synthetic identity tokens, not hashes of the actual host or source.
The L-SHADE search fixture uses a forced zero score after the shared baseline.

| Role | SHA-256 of typed ordered events + snapshot + trace + best/top-16 | RNG START/COMMIT | Proposals | FE / trace |
|---|---|---:|---:|---:|
| L-SHADE | `433e223fd0da7d2eeecb4c233cffa56c4f587bc52f7969b1d1c4403e0c1454df` | 16 / 16 | 2 | 236 / 236 |
| DE | `35549cdeee01f73d0f7c05b07e3e815eda3c55f1630d0a2fc7215af5dd298187` | 6 / 6 | 2 | 236 / 236 |

Reproduce with `uv run --locked pytest -s -q tests/unit/studies/test_stage5a2_q1d_recovery.py::test_uninterrupted_and_fresh_session_scientific_trajectory_match`.
Both resumed trajectories are compared byte-for-byte to their uninterrupted
reference; at-least-once physical attempts are excluded from these digests.
The observed local run passed both cases in 128.85 s including baseline setup.

## Reproduction and limits

Base `1f7da215fd2cd1b1901192b93e16ae0feb11d4f3`; synthetic fixture identity,
configuration and deterministic objective are defined in
`tests/unit/studies/q1bc_fixture.py`. Use the exact PR HEAD for source and the
locked `uv.lock` for dependencies. No raw SQLite journals or checkpoints are
committed. Run:

```sh
uv run --locked pytest -q tests/unit/studies/test_stage5a2_q1d_recovery.py
uv run --locked pytest -q tests/unit/studies/test_stage5a2_q1bc_behavior.py::test_pre_step_result_before_update_replay_does_not_recommit_fe_or_redraw
```

The initial two commands passed for both arms locally. Additional focused
tests `test_uninterrupted_and_fresh_session_scientific_trajectory_match` (2),
`test_pending_rng_call_restarts_from_durable_pre_state` (2),
`test_pending_evaluator_retry_in_new_session_is_not_a_physics_failure` (1),
`test_corrupt_arm_journal_fails_before_recovery_evaluator` (1), and
`test_recovery_seals_terminal_after_step_commit_before_status` (1) passed.
At exact HEAD `638ca1a72605878ab65c2f1a5b67f3ebe514f70b`, GitHub Actions
run 40722256267 passed the full suite (623 passed) and fixed-input COM regression;
new changes require their own exact-HEAD CI. After adding prefix validation,
the focused Q1-BC/D files passed locally: 34 tests in 607.20 s. Two later
focused proposal/identity tests passed in 68.32 s. Python 3.12.3, NumPy 2.5.3,
Ubuntu 24.04.5 / WSL2 x86_64; `uv.lock` SHA-256
`5dfd4435726518e40d5991fadc5af4099725cc0763af932e1f9015066aa1f0ff`,
fixture SHA-256 `e3bea6f09c05d28a61afc53ccab979dc42275d1de59a58182b45331f9569861c`.
The full suite was interrupted at the 900-second command limit after reaching
80%; it is not a pass. The existing fixed-input COM regression diagnostic
completed separately (not Q1 evidence); both CLI help commands and
`git diff --check` completed. This is synthetic software testing, not a
scientific SAW study. Exact source SHA is reported in the PR. Q1-E's 12-cell
comparison was not run.

## Test cost reduction (owner instruction)

Same local host, environment and `pytest -q --durations=15` on the two Q1-BC/D
behavior files: **32 passed, 1470.50 s before; 32 passed, 523.90 s after**.
Before, individual trajectory cases took 266.19/134.22 s, and repeated
initializations dominated many tests. After, those calls took 33.80/28.96 s;
one of these timings is a CI benchmark. The first shared setup took 44.86 s.

`tests/unit/studies/conftest.py` makes one complete synthetic 234-member
per-arm baseline and restores its three SQLite databases via SQLite backup to
private worker-owned identity-bound paths before each consuming test. It does
not share backend instances or mutable journal state between tests. Q0 roster
locators are immutable, so reset uses the original paths rather than copying a
pair to a different locator; each worker has its own directory. The standalone
full two-arm bitwise preflight/initialization and fresh-process import guard
remain, as do real SQLite fresh-session tests, G0–G4 and RNG foundation tests,
4,096-FE arithmetic and corruption/failure coverage. No production durability
setting or scientific condition was changed.

### Additional initialization-state reuse (local, same host)

At `c1b095f86675a6da70f3882f107bd07944d38f5e` the current two-file
`uv run --locked pytest tests/unit/studies/test_stage5a2_q1bc_behavior.py tests/unit/studies/test_stage5a2_q1d_recovery.py --durations=15 -q`
readout was **36 passed in 765.61 s**. After this increment it was **37 passed
in 572.03 s** (193.58 s / 25.3% lower; one additional isolation test).
Host and filesystem variability limit the precision of this comparison; neither
is a CI measurement. Examples: both-arm trajectory DE call 52.55→42.76 s,
L-SHADE call 31.01→22.83 s; fresh full preflight test 72.18→81.85 s.

The baseline now also deep-copies its initialized in-process arms on each
reset, rather than running `prepare_pair` on the restored journals merely to
set up a test. A focused test checks independent arm/backend/journal objects,
bound callbacks, exact initial snapshots, and restoration of journal heads and
234-row traces after mutations. Identity-bound SQLite backups and per-worker
paths are unchanged. Fresh-session crash tests still explicitly reconstruct
via `prepare_pair` **after** interruption, and the real two-arm 234-input
bitwise preflight, independent ledgers, fresh-process no-COM guard, G0–G4,
RNG/replay, full 4,096-FE DE arithmetic and corruption checks remain. No
production code or SQLite durability policy changed. This optimization does
not close any of the remaining Q1-D qualification gaps.

### Snapshot result consistency increment

The new cache-result corruption test was first run against `8136e99` and
failed: a hash-valid, same-key altered DE cache proceeded to hydration. After
the prefix-result check, both role variants and both fresh-session
committed-step recovery cases passed (**4 passed in 138.85 s**). The two
uninterrupted-versus-restarted trajectory variants and the original DE
corruption case also passed (**3 passed in 145.27 s**). These focused checks
are not a full fault matrix; rank-index, transition/cursor and checkpoint
consistency require further work. Final exact-HEAD CI is still required.
A separate fresh 234-member-per-arm initialization interruption test passed
in 61.68 s; it does not establish every genesis or initialization boundary.
The forced zero-FE fallback fresh-session test passed in 93.94 s including
baseline setup; it does not cover successful fallback or later adaptation. The
forced DE duplicate transaction recovery test passed in 74.23 s including
baseline setup; it does not cover the full watchdog or retry-cap matrix.
The pending-prestate corruption RED test failed at `1059619` by reaching
restore. After the transition-prefix check, it and the existing FE mismatch,
both two-step trajectory cases and evaluator retry passed (5 in 140.68 s).
This is not proof of all pending cursor, checkpoint, or terminal consistency.
The expanded two-arm parity test passed (2 in 131.21 s including setup); the
L-SHADE check explicitly requires nonempty archive/success batch and shrink.
The Q1-D file passed 20 tests in 487.10 s before expanding the checkpoint
fault test. The expanded checkpoint test then passed in 138.49 s including
setup. Checkpoints are optional journal records at committed boundaries; other
checkpoint/validation recovery and actual full-horizon parity remain pending.
The missing-intent corruption check was RED at `34ada98`; after adding the
intent/attempt/result prefix checks it, rank mismatch, evaluator retry, partial
initialization and both trajectory cases passed (6 tests in 236.24 s).

### 254-FE journal capacity attribution (owner-authorized diagnostic)

**Conclusion:** the dominant cost is full pre- and post-step optimizer states,
not `CHECKPOINT_SNAPSHOT`: the latter was absent in this fixture. At 20 steps
and 254 FE, START + COMMIT represent **98.91% of L-SHADE** and **97.17% of
DE** event payload bytes. The one DE generation snapshot adds 2.34%. This is
one early synthetic fixture, not an estimate of later state growth.

Reproduce from the repository root using
`uv run --locked python -m tools.diagnostics.q1d_storage_probe`. The probe
creates and deletes only its private temporary SQLite files, takes up to 20
steps/arm and retains the 2,000,000,000-byte and 5,000,000,000-byte
free-space checks between steps (not an instantaneous write quota). It reads
journal events with a read-only SQLite connection; it never saves compressed
payloads or changes the journal. The `SUMMARY` JSON includes every event type,
count, total/average/maximum payload bytes, percentage, last-snapshot fields,
file sizes and compression data. Code under test was `c223214` plus the
probe extension in this commit; measured probe SHA-256
`d8484c235a38338db73cd00a16b6ceef2236f6f9e7be4fff0d31a9a3afd9b1ad`;
fixture and lock hashes are recorded above. Python 3.12.3, NumPy 2.5.3,
Linux WSL2 x86_64/glibc 2.39; free space initially 1,007,161,815,040 bytes.
Each arm independently evaluated 234 initial members and 20 search steps.
The 21 START and 21 COMMIT events per arm include initialization.

Event statistics below are **payload bytes only**, with percentage relative to
that arm's total event payload, not total file size. Averages are rounded to
whole bytes; zero rows are included explicitly for the requested event types.

| Arm / event type | Count | Total bytes | Mean bytes | Max bytes | Payload % |
|---|---:|---:|---:|---:|---:|
| L-SHADE CELL_IDENTITY_COMMITTED | 1 | 687 | 687 | 687 | 0.0003 |
| L-SHADE CHECKPOINT_SNAPSHOT | 0 | 0 | 0 | 0 | 0 |
| L-SHADE EVALUATION_INTENT | 254 | 212,848 | 838 | 839 | 0.1067 |
| L-SHADE EVALUATION_RESULT_COMMITTED | 254 | 1,262,776 | 4,972 | 4,973 | 0.6333 |
| L-SHADE EVALUATOR_ATTEMPT_STARTED | 254 | 136,144 | 536 | 536 | 0.0683 |
| L-SHADE GENERATION_SNAPSHOT_COMMITTED | 0 | 0 | 0 | 0 | 0 |
| L-SHADE INITIALIZATION_MEMBER_COMMITTED | 234 | 31,498 | 135 | 136 | 0.0158 |
| L-SHADE INITIALIZATION_PREFLIGHT_CERTIFICATE | 1 | 798 | 798 | 798 | 0.0004 |
| L-SHADE OPTIMIZER_STEP_COMMITTED | 21 | 101,037,193 | 4,811,295 | 4,918,502 | 50.6730 |
| L-SHADE OPTIMIZER_STEP_STARTED | 21 | 96,186,715 | 4,580,320 | 4,918,502 | 48.2403 |
| L-SHADE POPULATION_ATTACHMENT_ATTACHED | 1 | 649 | 649 | 649 | 0.0003 |
| L-SHADE PROPOSAL_ATTEMPT | 20 | 25,207 | 1,260 | 1,261 | 0.0126 |
| L-SHADE RNG_DRAW_COMMITTED | 162 | 158,190 | 976 | 1,151 | 0.0793 |
| L-SHADE RNG_DRAW_STARTED | 162 | 337,904 | 2,086 | 6,365 | 0.1695 |
| DE CELL_IDENTITY_COMMITTED | 1 | 694 | 694 | 694 | 0.0002 |
| DE CHECKPOINT_SNAPSHOT | 0 | 0 | 0 | 0 | 0 |
| DE EVALUATION_INTENT | 254 | 212,848 | 838 | 839 | 0.0518 |
| DE EVALUATION_RESULT_COMMITTED | 254 | 1,269,557 | 4,998 | 5,306 | 0.3091 |
| DE EVALUATOR_ATTEMPT_STARTED | 254 | 136,144 | 536 | 536 | 0.0331 |
| DE GENERATION_SNAPSHOT_COMMITTED | 1 | 9,628,882 | 9,628,882 | 9,628,882 | 2.3442 |
| DE INITIALIZATION_MEMBER_COMMITTED | 234 | 31,498 | 135 | 136 | 0.0077 |
| DE INITIALIZATION_PREFLIGHT_CERTIFICATE | 1 | 805 | 805 | 805 | 0.0002 |
| DE OPTIMIZER_STEP_COMMITTED | 21 | 204,643,223 | 9,744,915 | 10,172,211 | 49.8222 |
| DE OPTIMIZER_STEP_STARTED | 21 | 194,475,206 | 9,260,724 | 10,145,047 | 47.3467 |
| DE POPULATION_ATTACHMENT_ATTACHED | 1 | 656 | 656 | 656 | 0.0002 |
| DE PROPOSAL_ATTEMPT | 20 | 34,705 | 1,735 | 1,738 | 0.0084 |
| DE RNG_DRAW_COMMITTED | 60 | 127,860 | 2,131 | 4,283 | 0.0311 |
| DE RNG_DRAW_STARTED | 60 | 184,680 | 3,078 | 6,421 | 0.0450 |

At the quiescent measurement, L-SHADE SQLite main/WAL/SHM were
200,540,160 / 0 / 0 bytes and payloads totaled 199,390,609; DE was
411,959,296 / 0 / 0 and payloads totaled 410,746,758. Thus the respective
main-file minus payload differences were 1,149,551 and 1,212,538 bytes; those
include SQLite pages/indexes, immutable records and other non-payload content,
not just pure filesystem overhead. WAL absence at this instant is not a claim
that WAL is never used. The separate pair DB was 2,191,360 bytes.

**Last committed live-state field attribution:** Each number is the canonical
JSON size of one complete packed field entry including its key/wrappers;
shared envelope and separators are excluded, so fields do not quite sum to the
snapshot length. L-SHADE snapshot 3,655,926 bytes: `_population` 2,306,096;
`_history_rank_index` 798,378; `_cache_frequency_versions` 318,180; `_cache`
158,455; `_historical_finalist_keys` 18,857; `population_trace` 12,004;
`archive_trace` 11,896; `best_so_far_trace` 2,006. DE snapshot 7,629,061:
`cache` 2,513,120; `population` 2,451,898; `parents` 2,451,895;
`pending` 209,711. DE has no snapshot fields named history or trace, and
L-SHADE has no `parents` or `pending` fields; the arm's separate journal/trace
ledger is not silently counted as a snapshot field. The DE cache/population/
parents structures each contain candidate data; their sizes are reported
separately, not assumed bitwise identical.

**Encoding and repetition:** snapshot bytes are already typed JSON from
`_pack`, and the event's typed JSON encodes these bytes again as Base64. Across
the 42 L-SHADE state-bearing events, 147,913,887 raw snapshot bytes became
197,218,564 Base64 characters (+49,304,677, about 33.3%); across DE's 43,
306,556,408 became 408,741,932 (+102,185,524). This excludes event wrapper
bytes. On the first actual committed candidate from each journal, directly
encoded typed candidate data was 2,916 bytes, while its recursively packed
snapshot representation was 8,703 bytes (2.98×); its 104-byte binary64 vector
alone was 203 bytes as a typed ndarray JSON value. These are representative
examples, not a decomposition of every field's semantic information. All 20
post-initialization START snapshots were **byte-identical** to the immediately
preceding COMMIT in each arm: 72,119,946 raw state bytes repeated for L-SHADE
and 145,851,338 for DE, before outer Base64. Across all state-bearing events,
there were 22/42 and 23/43 distinct SHA-256 values respectively. Exact
pre-state durability remains required; this measurement does not authorize
omitting or weakening it.

**One recommended proposal, not implemented:** investigate versioned,
lossless per-event physical compression, reconstructing and verifying the exact
original canonical typed event bytes before the existing logical hash-chain and
prefix checks. First require owner/independent review of the precise physical
format, hash coverage, decompression limits, corruption/fault handling and
compatibility: a change to journal format or hash meaning is not automatically
Q0-compatible, and historical journals must not be rewritten. In this diagnostic
only, zlib level 1 was applied **independently in memory** to each existing
payload and each decompressed result was checked byte-for-byte. Total payloads
would be 20,511,232 / 46,082,607 bytes instead of 199,390,609 / 410,746,758
(89.71% / 88.78% payload reduction). This is not an actual SQLite file-size
result, excludes format/index overhead, and says nothing conclusive about the
full horizon. Compression consumed 0.66 / 1.48 s and decompression 0.26 / 0.68 s
for one pass over L-SHADE/DE payloads on this host. The actual uncompressed
both-arm restart at this point took 207.02 s; a compressed restart was **not**
implemented or timed. Lower I/O could help, but repeated typed decoding,
prefix reconciliation and added decompression may dominate; speedup is
unproven. Q0's exact complete pre-state, typed RNG, immutable results, hash
integrity, atomicity/durability and state-v4 isolation must all remain intact.
No Q1-D completion, Q1-E, scientific COM/SAW run or merge is claimed.

### Bounded storage and restart feasibility probe (latest review)

**Disposition: full-horizon execution blocked pending a bounded resource plan
and contract-safe acceleration; not a Q1-D pass.** At source
`d89161978ed3c6194bd942413acc7b5a994c5b05`, the synthetic fixture was run for
at most 20 post-initialization steps per arm, with a fresh `prepare_pair` at
0, 5, 10 and 20 steps. Run with
`uv run --locked python -m tools.diagnostics.q1d_storage_probe`. It uses a
private temporary directory, a 2,000,000,000-byte between-step stop and a
5,000,000,000-byte free-space floor, and removes only its own temporary data.
It has no COM/SAW/production calls. Step 0 means both real 234-member arms
were initialized; this is not a full-horizon parity check. The measured script
SHA-256 was `94b21cfa45d8ad7e1612a8bae3fad57b32c722858bb99fef76404ecad2440a50`;
the checked-in version replaces the `assert arm.step()` with an explicit
failure check (so optimized Python cannot skip the call). The measured source
fixture and lock hashes are the hashes recorded above. Python 3.12.3, NumPy
2.5.3, Linux 6.18.54.1 WSL2 x86_64/glibc 2.39; starting free space
1,007,172,345,856 bytes. Initialization took 65.62 s. Sizes include main
SQLite file and any WAL/SHM sidecars at each quiescent sampling point.

| Steps / FE per arm | L-SHADE bytes / chain verify s | DE bytes / chain verify s | Both-arm fresh-session `prepare_pair` s |
|---|---:|---:|---:|
| 0 / 234 | 7,065,600 / 0.139 | 8,486,912 / 0.160 | 9.76 |
| 5 / 239 | 55,091,200 / 0.618 | 112,087,040 / 1.172 | 58.43 |
| 10 / 244 | 103,223,296 / 0.763 | 210,690,048 / 1.680 | 96.23 |
| 20 / 254 | 200,540,160 / 1.448 | 411,959,296 / 3.392 | 193.83 |

The pair journal was 2,191,360 bytes at each point. For steps 1–5, 6–10,
11–20 respectively, L-SHADE grew 9.61/9.63/9.73 MB per step and averaged
3.01/1.73/1.75 s per step; DE grew 20.72/19.72/20.13 MB per step and
averaged 3.81/3.49/4.48 s. The restart measurement includes both-arm
verification, full prefix reconciliation, initialization replay and hydration;
it is not merely the separately timed chain hash verification. The checkpoint
restarts themselves do not inject faults.

**Illustrative linear sensitivity, not a forecast or resource upper bound:**
assuming one FE per step all the way to 4,096 and extending the three measured
slopes yields roughly 34.6–35.0 GiB L-SHADE and 70.9–74.5 GiB DE for one
pair, or 211–219 GiB for two simultaneous independent reference/restart
copies, excluding pair journals, temporary overhead and validation. Available
space at the start was approximately 938 GiB, so these early estimates do
**not** show an immediate disk-capacity failure. Step-time slopes alone suggest
about 11–16 hours for both trajectories of both arms; extending the observed
restart increments (7.56–9.76 seconds per additional step for the pair)
suggests another 8–10.5 hours for one near-terminal restart. These figures
ignore initialization, final comparison, fault setup, memory pressure and
changes in state size or the number of zero-FE steps. In particular, 20 steps
cannot establish late-horizon growth or bound runtime/storage; full-horizon
execution has not been attempted.

The concrete blocker is that the required independent full-horizon parity
would demand a many-hour resource allocation with unbounded later growth and
expensive verified restart, while this environment has no approved long-run
resource/abort plan. Do not reinterpret that as insufficient disk or a Q0
contradiction. A minimum candidate remedy is to reduce repeated decoding and
exact comparison of identical committed snapshot material during recovery,
while still verifying the entire hash chain and each prefix, plus investigate
lossless physical storage compression without changing logical event bytes,
transaction boundaries or historical journals. Neither remedy is implemented
or shown sufficient. Any changed journal envelope, snapshot representation or
relaxation of exact prefix checking requires contract review; do not change
budget, fidelity, durability or Q0 semantics to make the probe finish. The
owner/reviewer should decide a bounded full-horizon resource policy after a
measured, independently reviewed improvement. Memory flush/archive trim,
remaining fault boundaries and both 4,096-FE parities remain pending.

### Large-journal recovery memory

A bounded local COM-free fixture cost probe (not a full-horizon run) measured
57.20 s to initialize; 10 search steps took 24.29 s for L-SHADE and 34.66 s
for DE. The respective SQLite main files were 103,223,296 and 210,690,048
bytes after those steps. Host available memory was about 5.9 GiB. These are
observations at 244 FE, not a forecast or a substitute for the requested
4,096-FE parity. They exposed the existing full-journal `fetchall()`/tuple
materialization as a concrete recovery memory risk.

Journal open, identity/preflight validation, RNG reload, arm reload and step
hydration now consume the complete hash-verified chain incrementally. The
public `events()` still returns the original tuple, and the verified append tail
is updated only after the iterator is exhausted; corruption remains fail
closed. This does not reduce SQLite durability, snapshot content, or scientific
checks. A proxy-based RED/GREEN test rejects `fetchall`, then checks detection
of mid-chain corruption and prevention of further append. The foundation suite,
checkpoint recovery and both trajectory cases passed (69 tests / 253.14 s).
The time and storage needed for full-horizon parity remain unmeasured and the
large-journal change alone does not establish that parity.

A separate hash-valid L-SHADE history-rank corruption test was RED at `eeae8a1`.
After index, finalist and incumbent reconciliation, it, both two-step parity
cases, interrupted initialization and forced fallback passed (5 in 251.70 s).
This does not prove every possible malformed optimizer state or full-horizon
history.
