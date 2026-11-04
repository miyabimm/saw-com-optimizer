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
| Proposal committed before intent | Generate the same intent without redrawing committed RNG. | DE fresh-session fixture reproduces the proposal's physical bits, does not invoke the RNG and commits one FE. |
| DE duplicate transaction | Replay a committed duplicate with its retry/counters exactly once and complete the pending target. | A forced first duplicate is interrupted after its atomic journal transaction; fresh-session replay records one duplicate, retry indices 0/1, two proposals, one pending target and one additional FE. |
| L-SHADE duplicate/fallback, zero-FE step | Replay all committed RNG and duplicate proposals, preserve zero FE, commit the step once. | An injected duplicate-only canonicalizer forces six normal and 256 fallback attempts; fresh-session replay reproduces the exact post-state with no new draw/evaluation, then rereading the commit leaves the journal head unchanged. This is a forced boundary fixture, not a normal canonicalizer trajectory. |
| Foreign pair identity | Fail before hydration/evaluation. | Altered config identity is rejected at genesis reconciliation. |
| Journal corruption | Fail before evaluator dispatch. | A modified event payload is rejected on journal reopen before geometry/evaluator call. |
| Hash-valid inconsistent snapshot/result | Check identity, FE/cache/RNG prefix and result rank/best before hydration. | A post-state with an extra FE, a separate forged result rank, and a cache result changed while preserving its key set are rejected before either arm hydrates or evaluates. Both arm caches and population/pending records in snapshot START/COMMIT states are compared against committed prefix results; result rows are schema/rank/best checked on reload. |
| Hash-valid pending-step pre-state | Require ordered START/COMMIT transitions and the exact immediately preceding committed snapshot, RNG ordinal and watchdog counter before hydration. | A DE snapshot with two population members swapped but valid cache, FE, results and RNG is rejected before either arm hydrates or evaluates; the baseline implementation failed this test. Genuine two-step two-arm parity and evaluator retry continue to pass. |
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
