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

The tests compare recovered state to the interrupted in-memory trajectory, not
the complete uninterrupted baseline required by Q1-D. They do not establish
full RNG/proposal/trace or top-16 equivalence. More fault boundaries and
identity, terminal, malformed snapshot, checkpoint and corruption tests are
needed; hydration currently has not been qualified against arbitrary malformed
but hash-valid event sequences. In particular, this partial implementation
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

Both commands passed for both arms locally. Python 3.12.3, NumPy 2.5.3,
Ubuntu 24.04.5 / WSL2 x86_64; `uv.lock` SHA-256
`5dfd4435726518e40d5991fadc5af4099725cc0763af932e1f9015066aa1f0ff`,
fixture SHA-256 `e3bea6f09c05d28a61afc53ccab979dc42275d1de59a58182b45331f9569861c`.
The full suite was interrupted at the 900-second command limit after reaching
80%; it is not a pass. The existing fixed-input COM regression diagnostic
completed separately (not Q1 evidence); both CLI help commands and
`git diff --check` completed. This is synthetic software testing, not a
scientific SAW study. Exact source SHA is reported in the PR. Q1-E's 12-cell
comparison was not run.
