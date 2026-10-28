# Issue #169 — Q1-D recovery: partial local evidence

**Disposition: INCOMPLETE / NOT READY FOR REVIEW AS COMPLETE.** The owner
separately authorized Q1-D implementation and synthetic-only qualification in
Issue #169. Q1-E, scientific/production runs and formal gate closure remain
unauthorized. No Q1-01…23 `FULL_PASS` is claimed. This report records only
representative local checks, not the required full Q1-D matrix.

## Boundary and observations

| Boundary | Expected | Observed |
|---|---|---|
| New session after a committed search step | Restore the contiguous step prefix, including backend, RNG ordinal and watchdog state. | Both arms restored one committed step in the focused synthetic test. |
| Result committed, before next optimizer-step commit | Reconstruct the transition from its pre-state with the committed RNG and result; do not dispatch another evaluator call. | Both arms reproduced the interrupted backend snapshot and 236 unique FE/trace rows in a new session. |
| Candidate record mapping serialization | Stable snapshot bytes despite canonical journal decoding of mapping key order. | Candidate record mappings are serialized in canonical key order; cache/population ordering is not sorted. Existing same-session replay tests pass. |
| Uninterrupted vs fresh session, both arms | Match ordered logical RNG and proposal events, physical evaluator inputs, result/trace and optimizer state, rank/best/top-16. | Independent deterministic initializations and two search steps match exact typed event bytes, complete live-state snapshot, trace and top-16; 236 FE. The crash is before the second step commit, after its result. |
| RNG STARTED / lost NumPy return | Pending call is regenerated from its pre-state under the same ID. | DE synthetic fixture interrupts before and after physical RNG invocation; one START and one COMMIT for the logical call on new-session replay. |
| Evaluator interruption | No FE until result; a repeated physical attempt is not a modeled physics failure. | DE fixture records two identical physical attempts, one infrastructure interruption and one committed 235th result/FE. |
| Journal corruption | Fail before evaluator dispatch. | A modified event payload is rejected on journal reopen before geometry/evaluator call. |
| 4096-FE step commit before terminal event | Restore without rerunning and seal one search-only terminal status. | Minimal mocked-state SQLite transition fixture verifies one durable terminal event, no extra state/FE/RNG; this is not a 4096-FE trajectory test. |

The uninterrupted comparison is deliberately bounded to two search steps;
it does not establish full-horizon equivalence or exercise adaptation/shrink,
fallback, duplicate/no-FE steps or a real 4096-FE terminal trajectory. More
fault boundaries and identity, malformed snapshot, checkpoint and corruption
tests are needed; hydration currently has not been qualified against arbitrary
malformed but hash-valid event sequences or reconciled against the FE ledger
before hydration. In particular, this partial implementation
must not be used as evidence of fail-closed recovery for all Q0 cases.
Q1-12/16/19 and dependent Q1-03/05/06/07/14/15/17/18 remain
`PENDING_DEPENDENCY`; independent review and final Q1-E fingerprint are also
outstanding.

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
At prior exact HEAD `b2490cd24976b6074587e08065f2237386411da8`, GitHub Actions
run 40716561372 passed the full suite (616 passed) and fixed-input COM regression;
new changes require their own exact-HEAD CI. Python 3.12.3, NumPy 2.5.3,
Ubuntu 24.04.5 / WSL2 x86_64; `uv.lock` SHA-256
`5dfd4435726518e40d5991fadc5af4099725cc0763af932e1f9015066aa1f0ff`,
fixture SHA-256 `e3bea6f09c05d28a61afc53ccab979dc42275d1de59a58182b45331f9569861c`.
The full suite was interrupted at the 900-second command limit after reaching
80%; it is not a pass. The existing fixed-input COM regression diagnostic
completed separately (not Q1 evidence); both CLI help commands and
`git diff --check` completed. This is synthetic software testing, not a
scientific SAW study. Exact source SHA is reported in the PR. Q1-E's 12-cell
comparison was not run.
