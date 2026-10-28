# Issue #167 — Q1-B/C local synthetic engineering evidence

## Disposition and authority

**Implementation: `IMPLEMENTED / LOCAL_REVIEW_PENDING`.** One integrated Draft
PR, not separate B and C units. Q0 remains `CLOSED / ACCEPTED`; Q1-A remains
`WORK_UNIT_READY / CLOSED`. **All Q1-01…Q1-23 official gates remain unpassed.**
No `FULL_PASS` is claimed. Independent review and owner acceptance are pending.

The owner explicitly confirmed authorization after the implementation agent
asked about the exact scope: B/C implementation, deterministic COM-free
synthetic unit/integration verification, and one Draft PR. That confirmation
is not D/E authorization, permission for the 12-cell synthetic matrix, official
qualification closure, scientific COM/FE search or production execution.

Base: `a94bd649ffaf2f3a259f951f6ce83c396e2ff5bc`. Exact implementation/test-file,
config and environment hashes are in
[`stage5a2_q1bc_fingerprints.json`](stage5a2_q1bc_fingerprints.json).
The fixture identity fields explicitly use `synthetic_test` placeholder
source/evaluator/environment labels; they are not production attestations.
The adjacent hashes identify the actual reviewed software and local environment.
Final common-fingerprint qualification belongs to the separately gated D/E work.

## Changed owners and contracts

| Owner | Responsibility / protected boundary |
|---|---|
| `optimization/controlled_de.py` | Dedicated fixed DE/rand/1/bin; not SciPy DE. Immutable synchronous parents, ordered pending trials and target/retry cursors; direct physical initialization and canonical-phenotype remap. |
| `studies/stage5a2/pair.py` | Q0-frozen 13-variable metadata/settings; A genesis/seal/attachment consumption; both complete actual backend-input preflights and certificate readback before either arm's first FE. An already sealed population is loaded without re-entering the sampler. |
| `studies/stage5a2/arm.py` | Injected synthetic-only evaluator, A typed PCG64 service, proposal/duplicate/retry transaction, intent/attempt/result/FE/trace ledger, complete source-step transaction, result-store/backend-cache separation. |
| `studies/stage5a2/live_state.py` | Direct live fields and PCG64 state, not `state_dict`/`_jsonable`; exact arrays, tuple keys, cache/history, population/archive/memory/batches/cursors/traces. Rejects foreign config/horizon, nullified v4 envelopes, NaN/-Inf and invalid failure-rank tokens. |
| `studies/stage5a2/candidates.py` | Strict search record schema before the unchanged GeometryFirst comparator; explicit invalid-return quarantine/FE and no arbitrary exception-to-modeled-failure conversion. No physical evaluator resolution. |
| `optimization/lshade.py` | Inert opt-in observations only: initialization member, parameter/proposal/fallback boundaries. Normal-proposal observation repeats the pure canonical transform without substituting its result into the original evaluation path. No operator, RNG method/order, adaptation, fallback or v4 serializer change. |

The controlled reflection applies the stated periodic formula to excursions;
in-range binary64 words are copied unchanged as explicitly required by Q0-R1
§3.1. Golden tests pin the actual IEEE-754 words, not rounded decimal answers.
The existing L-SHADE latent genotype and normal repair remain unchanged.
No seven-variable/FeasibilityFirst configured-search or R5 fixture path is used.

`ArmSession.transition` is the local replay seam. An uncommitted source step
restores its live pre-state and RNG ordinal, replays A's committed RNG tape and
supplies durable results as original logical first evaluations. It never
preloads later journal results into the pre-step backend cache. A committed
step loads its post-state without re-executing survivor/memory/shrink/trace
updates. The same mechanism handles initialization; durable member rows expose
the cursor, while reconstruction replays the complete original initialization
source using stored results, not guessed Python locals.

The result event contains the unique key, ordinal, record/status, rank (or
explicit absence), best-so-far key/rank and pending DE target/next cursor in
one transaction. Duplicate proposal, watchdog and retry cursor projections
commit together. Backend FE count may remain at its pre-step value after an
invalid returned record; the terminal journal FE ledger is authoritative.
`SEARCH_BUDGET_REACHED` is **search-only**, not overall Q0 `COMPLETED`:
terminal validation is not implemented or authorized here.

## Compact clause-level evidence map

`LOCAL_EVIDENCE_READY` below labels only the named local clauses, conditional
on the recorded self-validation checks. Every official gate still has
`PENDING_DEPENDENCY` for final pinning, review and the applicable D/E clauses.

| Existing gate(s) | Local clauses / focused test evidence | Remaining dependency |
|---|---|---|
| Q1-02 | `LOCAL_EVIDENCE_READY`: ordered distinct target-excluding donors; permutation → forced coordinate → mask; F=.5/CR=.9; reflection golden words; decode and canonical remap exercised by pair/backend. | D replay matrix; final common fingerprint/review. |
| Q1-08 | `LOCAL_EVIDENCE_READY`: every donor pool equals the immutable generation-start snapshot; pending trials do not replace parents early; strict better replacement and parent-on-tie in ordered survivor commit. | D interrupted-generation certification. |
| Q1-09 | `LOCAL_EVIDENCE_READY`: duplicate-free DE unit fixture reaches exactly 234 + 16×234 + 118 = 4,096; 3,862 post-init proposals; zero duplicate FE and no terminal extra state/draw. | D terminal/partial-generation restart; E complete ledger/report. |
| Q1-10 | `LOCAL_EVIDENCE_READY`: exactly 4,096 duplicate proposals for one target; pending generation retained; aggregate 65,536 boundary checked before another draw. | D crash/retry cursor coverage. |
| Q1-01 | `LOCAL_EVIDENCE_READY`: cold resolved 234/4/6/.5/.20/archive/batch/retry settings and 4,096 horizon; rejects foreign 96,000 state; eight uninterrupted hooked/unhooked offspring have identical live bytes. | D/E broader source/state qualification; independent review. |
| Q1-11 | `LOCAL_EVIDENCE_READY`: six normal duplicates + one fallback invocation + 256 internal draws; first None ends source step; no extra evaluator/FE; zero-FE step commits generation/batch state; exact external watchdog stops before another RNG call. | D interruption matrix and broader accepted-fallback/success-memory coverage. |
| Q1-03/04/05/15 | `LOCAL_EVIDENCE_READY` clauses: existing A G4/seed tests retained; both actual 234-member input paths checked bitwise/key/order; both durable certificates precede first FE; mismatch blocks both; independent 234-FE ledgers; sealed resume does not resample/evaluate committed results. | D full genesis/partial-init/hydration corruption matrix; final identity attestation. |
| Q1-06/07/13 | `LOCAL_EVIDENCE_READY` clauses: private caches; duplicate no-FE; geometry/modeled failures consume one new FE; invalid return charged/quarantined with no rank; unexpected exception remains infrastructure interruption; strict schema/status/type/summary checks before comparator. | D full transaction/failure matrix; E full-budget journal reconciliation. |
| Q1-14 | `LOCAL_EVIDENCE_READY` live-state clause: direct-field roundtrip retains signed zero and permitted +Inf; serializer trap proves v4 JSON is not the source; malformed numeric state rejected. Existing A typed-key/PCG64 tests retained. | D corruption/hydration/final-fingerprint qualification. |
| Q1-17/18 | `LOCAL_EVIDENCE_READY` representative clauses for both arms: crash before step commit and immediately after durable result/before backend cache/update; replay uses no underlying RNG/evaluator call, no duplicate FE/result; committed step reload is not reapplied. | `PENDING_DEPENDENCY`: D exhaustive restart/fault certification, including pending calls/attempts, accepted fallback, memory flush/archive/shrink and terminal budget. |
| Q1-19…23 | No gate closure or comparison-report claim. Local FE rows support later work only. | `PENDING_DEPENDENCY`: D scientific trace certification; E top-16 validation, 12-cell integration, resource/time ledger and censored reporting. |

## Verification and limits

Final check counts and pinned implementation commit are recorded at handoff.
Reproduction commands (Ubuntu, locked Python 3.12 environment):

```bash
# Focused local clauses; tests only, not a qualification-study launcher:
uv run --locked pytest tests/unit/studies/test_stage5a2_q1bc*.py

# Full ordinary software verification, including unrelated numerical regressions:
OPENBLAS_CORETYPE=Haswell OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
MKL_NUM_THREADS=1 BLIS_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 uv run --locked pytest

# SEPARATE fixed-input COM diagnostic, NOT Q1 synthetic evidence:
uv run --locked --extra test --extra benchmark python tools/diagnostics/evaluation_repro.py
uv run --locked sawopt --help
uv run --locked python -m sawopt.cli --help
git diff --check
```

The synthetic import/call guard runs in a fresh process and blocks physics,
problem, evaluation, IO and reporting imports throughout pair construction,
initialization and one source step in each arm. It calls only explicitly
injected fixture evaluators. The full ordinary suite and separately labeled
fixed-input COM diagnostic do import/call physics; they are not part of the
Q1 no-physics proof. No new scientific COM/FE study, real SAW optimization,
production dispatch, historical replay or 12-cell comparison was run.

No historical raw/config/checkpoint/report was changed. The L-SHADE v4
serializer/loader and comparator source are unchanged. Temporary synthetic
journals are test-owned, not a new production raw-store contract; no raw
population, checkpoint, journal or full diagnostic output is committed here.
Early RED intentionally failed on the missing controlled-DE module. Some
intermediate test runs were stopped/time-limited while iterating; they are not
counted as passes. Only completed checks listed at final handoff are evidence.
