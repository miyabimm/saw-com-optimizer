# Stage 5A-2 Q1 synthetic qualification — execution plan

**Status (2026-10-22):** Q1-A is `WORK_UNIT_READY / CLOSED`: [PR #54](https://github.com/MasayaTakagi/saw-com-optimizer/pull/54) merged at `03d673052c7570d86b78b43849f649758bb7d3f4` and [Issue #52](https://github.com/MasayaTakagi/saw-com-optimizer/issues/52) closed as completed after independent review and explicit user acceptance. Q1-B/C are now one authorized engineering unit under Issue #167 (see the authorization update below); Q1-D/E remain `NOT AUTHORIZED / NOT STARTED`. No official Q1 gate has passed.

**Q0:** `CLOSED / ACCEPTED` under the user decision recorded in the [Q0 closeout](../history/stage5a2_q0_closeout_20261021.md).

**Authority:** [Q0-approved comparison contract](stage5a2_minimum_fair_comparison.md), the sole official [Q1-01…Q1-23 qualification matrix](stage5a2_q1_qualification_matrix.md), and the accepted [Q0-R3 protocol](../../reports/escalation_packets/stage5a2_q0_protocol_revision_r3_20261021.md), together with retained Q0-R2 terms and the [project roadmap](../project_roadmap.md).

**Scope:** Issue [#52](https://github.com/MasayaTakagi/saw-com-optimizer/issues/52) separately authorizes Q1-A implementation and deterministic synthetic/unit tests, including its narrow legacy `canonicalize` characterization. It does not authorize Q1-B/C/D/E, synthetic integration, COM/network/physics evaluation, real SAW optimization, Stage 4C mutation, or production orchestration/run.

**Issue #167 authorization update:** After an explicit scope confirmation, the owner authorized Q1-B/C implementation, deterministic COM-free synthetic unit/integration verification, and one integrated Draft PR in the implementation conversation. This supersedes the earlier B/C start prohibition only within that scope. B/C implementation is `IMPLEMENTED / LOCAL_REVIEW_PENDING`, not `WORK_UNIT_READY`. Q1-D exhaustive recovery, Q1-E 12-cell integration, official gate closure and scientific/production execution remain unauthorized. Local evidence and remaining dependencies are recorded in [the Q1-BC report](../../reports/stage5a2_q1bc_local_evidence.md).

Q1 is deterministic, COM-free software qualification. Its synthetic objective is a software fixture, not a SAW proxy or a scientific comparison. Q1 must not resolve or change Q0 decisions. Q1 passing does not authorize a real COM comparison, pilot, or production run; each remains a separate user-reviewed authorization.

## 1. Work-unit model and order

Q1-A…Q1-E are **implementation work units**, not qualification gates and not additional IDs. The only formal qualification IDs are Q1-01…Q1-23 in the existing matrix. An official gate has exactly one primary work-unit owner below; related work units may supply interfaces or fault cases but do not duplicate gate ownership.

Use four distinct planning dispositions, none of which add a qualification gate: **`WORK_UNIT_READY`** means the work unit's own API/code/evidence is reviewed and may unblock the next unit; **`LOCAL_EVIDENCE_READY`** means only the locally testable clauses named below have evidence; **`PENDING_DEPENDENCY`** means one or more required cross-unit clauses remain and the official gate is not passed; **`FULL_PASS`** is recorded only by that gate's primary owner after every matrix clause and dependent A–D evidence passes on the final pinned Q1 source/config/environment fingerprint and is independently reviewed. Local tests, per-unit PR acceptance, or partial gate evidence are never reported as an official Q1 gate pass.

```text
Q1-A: identity/journal/RNG/population foundation
             ├── Q1-B: controlled DE ──┐
             └── Q1-C: L-SHADE adapter ├── Q1-D: cross-cutting recovery/determinism
                                        └── Q1-E: synthetic integration/reporting
```

Q1-B and Q1-C depend on the accepted Q1-A contracts and are implemented as **one integrated engineering work unit / one Draft PR** under Issue #167. Their separate cards and primary gate ownership below remain contract subdivisions, not separate PR requirements. Q1-D requires the integrated A/B/C transitions. Q1-E consumes the qualified interfaces, statuses, traces and comparison rules from A–D. Every boundary change must preserve the Q0 data/identity/event semantics; if a Q0 design decision would need to change, stop and return to governance rather than deciding it in implementation.

## 2. Frozen Q0 contract carried through Q1

- **Common initialization:** exactly 234 ordered candidates from `independent_uniform_rejection_lshade_image_v2`; preserve raw draw, provisional canonical vector, L-SHADE input genotype, its reconstructed physical vector, sealed actual canonical physical evaluator vector/key, and DE's direct physical input/genotype separately. Seal all members before either arm's first FE. Both full 234-member pure evaluator-input preflights and durable certificates must match the seal bitwise, by key, and in order before either arm evaluates. Mismatch fails both arms before FEs. No fitness-driven selection, redraw-until-round-trip, tolerance, or seed substitution.
- **RNG/replay:** explicit PCG64; `stage5a2_rng_call_v1`; exact versioned owner/role/step/cursor/ordinal/method/typed arguments, full lossless pre/post state and typed result; durable `STARTED` then `COMMITTED`; a committed output is replayed without redrawing; a pending call is regenerated from its verified pre-state under the same logical ID. L-SHADE restarts its existing control flow from complete pre-step state; no partial-local-state guessing.
- **Evaluation/accounting:** 4,096 unique search FEs per arm/cell including 234 initial FEs. Duplicate/cache hit and sampler rejection add no FE. Search geometry reject, typed modeled failure and invalid returned record retain their specified separate classification and accounting. Validation is separate. No dispatch past 4,096; no comparator change.
- **Scientific boundary:** synthetic-only, deterministic, no COM/provider/network physics and no production orchestration. No change to Stage 4C scientific behavior, Stage 4C-specific study source, saved data, checkpoint bytes, or state schema; only the narrowly scoped, parity-qualified shared-source canonicalization extraction and inert L-SHADE observation hooks described below may change shared files. Do not change optimizer search rules, objective/ranking, seeds, bounds, topology, constraints, evaluation budget, failure taxonomy or Q0 censoring/reporting rules.
- **Interpretation:** Q1 proves bounded software behavior only. It does not establish COM determinism, physical correctness, search convergence, feasibility, a best method/topology or permission to perform the 12-cell SAW comparison.

The complete normative contract, including the initializer pushforward effect, G0–G4, schemas, failure states, budgets and comparison rules, remains in the linked Q0 records. This summary does not supersede them.

## 3. Cross-phase interface contract (freeze before implementation)

The following conceptual interfaces are to be agreed at Q1-A review before Q1-B/C code is written. Concrete Python class/function names may be selected during implementation, but data ownership, schema meaning, lifecycle and failure semantics below may not change without reopening Q0.

### 3.1 Identity and attachment lifecycle

1. **Phase I:** pair identity + immutable expected-arm roster, then immutable L-SHADE and controlled-DE cell identities, reconciled by the pair coordinator through G0–G4. G4 is the durable all-identities-ready barrier. There are no sampled population hashes in Phase-I identity bytes. No sampler method may be invoked before G4.
2. **Phase II:** the pair-owned population seal stores the ordered 234 actual evaluator physical vectors/keys and sampler evidence. A distinct representation attachment stores each representation path and hash. Each arm's post-seal `POPULATION_ATTACHMENT_ATTACHED` record/execution envelope references both hashes and its unchanged Phase-I cell identity ID. Never rewrite Phase-I IDs to add sampled data.
3. **Phase III:** mutable journal sequence/head, checkpoints, RNG cursors, results/cache, FE ledger, traces and validation cursors are integrity/recovery state, not scientific identity. Snapshots may be used only against an exact verified journal prefix.

### 3.2 Population and canonicalization boundary

Q1-A supplies an immutable ordered population object with 234 member records, the two seals, and an explicit representation record for raw/provisional/L-SHADE/decode/sealed/DE forms. Canonicalization comes from one planned physics-free dependency leaf, `sawopt.design.canonicalization`, containing the exact moved implementation of `HybridDesignSpace.canonicalize`; the existing public method becomes a same-signature delegate. Q1 code imports the leaf by its normal package path and does not import `sawopt.problem` or `sawopt.problem.hybrid`. Frozen bounds, coordinate ordering, integer indices, dimensions and topology labels must be checked against the authoritative Q0 design-space contract; the shared function does not prove metadata identity. Q1-C applies the existing `_normalize`/`_physical` operations and this shared canonicalization primitive; Q1-B receives the sealed physical vector directly on its initial evaluator path and separately records the normalized canonical phenotype genotype used after initialization. Both paths expose a **pure preflight** that computes actual evaluator inputs without calling an evaluator or physics. Their complete certificates are persisted before either initialization FE. The arms have separate caches and independently evaluate all 234 members.

### 3.3 RNG/journal/evaluation boundary

Q1-A provides one lossless typed RNG journal facade. Its call identity is checked before generator invocation; committed results are returned without an underlying draw. Pair-sampler stream and each optimizer-role stream have separate ownership/cursors. An arm adapter can distinguish: RNG event, proposal, duplicate/retry, evaluation intent, external evaluation attempt, durable result/FE/cache commit, backend state update, and optimizer-step commit.

The journal result store is **not** a restored optimizer backend cache. If a result committed after the optimizer's pre-step snapshot, replay supplies it as the original logical first evaluation so the backend reconstruction is correct, while not recommitting or recounting the already durable result/FE/cache row. An optimizer transition, including a zero-FE L-SHADE step, commits exactly once.

### 3.4 No-COM integration seam and compatibility characterization boundary

All Q1 runners receive an evaluator implementation by dependency injection. The synthetic Q1 runtime/integration must not import or resolve a COM/provider/network-physics evaluator or production orchestrator. Its import-isolation check runs in a fresh process and observes normal imports plus deferred imports reached during execution. A distinct, one-time legacy canonicalization compatibility characterization may import the public `HybridDesignSpace` path (which transitively imports COM modules) **solely** to call its pure `canonicalize` method; it must make no decode, geometry, provider, evaluator, network or physics call. This is not the synthetic optimizer/integration runtime and is excluded from its no-import proof. This narrow import-only exception was explicitly authorized for Q1-A by Issue #52 A0; it does not relax the synthetic runtime import boundary.

## 4. Proposed module ownership and protected boundaries

The paths below are implementation targets. Keep Stage 5A-2 additions in a study-scoped package (recommended `src/sawopt/studies/stage5a2/`) and a dedicated controlled optimizer backend; do not repurpose Stage 4C production state or broadly modify shared numerical behavior. The shared-source extraction is a bounded candidate seam; its implementation is authorized only within Q1-A Issue #52 and remains subject to the stated parity/protection evidence. Do not move or refactor any decoder's separate rounding logic.

| Module/location | Intended responsibility in Q1 | Protected boundary |
|---|---|---|
| New `src/sawopt/studies/stage5a2/identity.py` | Strict typed identity schemas, pair coordinator G0–G4, Phase-II seal/attachment references and resume identity validation. | Phase-I bytes stay immutable; no cross-database atomicity claim. |
| New `.../journal.py` | SQLite transaction/event envelope, hash chain, idempotency, durable counters/result store and checkpoint-to-journal prefix checks. | Preserve Q0 event grouping and exactly-once durable result/FE semantics. |
| New `.../rng.py` | PCG64 codec, `stage5a2_rng_call_v1`, typed call tape, call facade, START/COMMITTED and replay. | No hidden draws, coercions, changed source draw order, or committed-call redraw. |
| New `src/sawopt/design/__init__.py`, `src/sawopt/design/canonicalization.py` | Dependency-leaf package and the sole production implementation of the current hybrid vector canonicalization primitive. The new leaf is NumPy/typing-only; `HybridDesignSpace.canonicalize` delegates without signature or result changes. | Every parent initializer is physics-free; preserve conversion/check/order/clip/half-up/clip/key construction, output ownership, input non-mutation and error behavior bit-for-bit. No decoder/geometry/physics logic is moved. |
| New `.../initialization.py` | Representation-aware physical sampler, 234-member seal, lossless representation rows, both pure arm preflights and certificates; imports the new design leaf directly. | No fitness information, COM/provider import or call; exact Q0 sampler law and fail-closed equality. |
| New `src/sawopt/optimization/controlled_de.py` | Dedicated fixed `DE/rand/1/bin` backend and complete generation/target state interface. | No legacy-backend relabeling; no adaptation/archive/shrink/polish/fallback or changed operator semantics. |
| New `src/sawopt/studies/stage5a2/lshade_adapter.py` | Transaction-aware evaluator/RNG seams and full live-state codec/restore adapter around existing L-SHADE. | Retain existing search path and Stage 4C state version; do not use null-coercing payload as lossless source. |
| New `.../recovery.py` / `runner.py` | Synthetic-only coordination of private arm journals, phase transitions, restart, status and fault injection. | No COM/provider import, no production orchestration, no Stage 4C reader/writer. |
| New `.../reporting.py` | Qualified synthetic integration records, resource/time ledger and exact Q0 censored-comparison reporting. | No imputation, survivor-only aggregation or newly invented ranking/reporting rule. |
| Existing `src/sawopt/optimization/lshade.py` | Minimal observation hooks only where unavoidable to preserve RNG/evaluation/step boundaries. | No arithmetic, branch, method/argument order, retry, fallback, adaptation, cache or survivor behavior change. |
| Existing `src/sawopt/optimizers/selection.py`; `src/sawopt/problem/hybrid.py` | Read-only reuse of `GeometryFirstComparator`; the existing public `HybridDesignSpace.canonicalize` signature delegates to the new shared leaf after the gated extraction. Q1 runtime imports the leaf, not the physics-dependent problem package. | Do not change rank tuples/ties or canonicalization semantics; preserve Stage 4A/4B/4C caller and state behavior with explicit parity evidence. |
| Existing `src/sawopt/studies/hybrid_stage4b.py`; `src/sawopt/optimizers/checkpoint_session.py` | Read-only evidence/reference for existing sampler and checkpoint ownership. | No Stage 4B/4C protocol, saved state, or historical data mutation. New Stage 5A-2 persistence is separate. |
| New focused test files under `tests/optimizers/` and `tests/studies/` | Synthetic, deterministic unit/fault/replay/integration fixtures per official gates, plus separately labeled legacy canonicalization compatibility characterization. | Q1 runtime/integration must not import/call COM or launch production orchestration. The isolated characterization may import the legacy path only under explicit Q1-A user authorization and must never invoke physics. |

Q1-A preserved the pre-extraction baseline before changing canonicalization and produced the affected-caller review recorded in its evidence report. The extracted operation must retain the original expression and statement order, metadata must remain unchanged, and both the public delegate and new leaf must match the independent pre-extraction baseline. The no-COM import check applies to the actual Q1 runtime; the separately authorized characterization is isolated and calls no physics. If implementation discovery shows the seam cannot meet exact replay or requires changing a Q0 rule, do not silently refactor or approximate: stop with concrete evidence and request governance review.

## 5. Work-unit execution cards

### Q1-A — Common Identity / RNG / Population Infrastructure

**Purpose.** Build the pair/cell identity coordinator, append-only SQLite journal primitives, lossless typed PCG64 call service, one shared 234-member representation-aware population, and pure pre-FE arm identity checks. Extract the existing canonicalization primitive once into a physics-free dependency leaf so the Q1 runtime can preserve the exact Stage 4A/4B/4C behavior without importing physics-dependent problem packages. This unit establishes stable interfaces before either optimizer integration.

**Q0 contract linkage.** Q0-R3 §§2–5; Q0-R2 identity/journal/codec requirements; all initial-population, PCG64, Phase-I/II/III and exact-input requirements in §2 above. The explicit initialization pushforward and immutable Phase-I/Phase-II separation are retained without alternative selection.

**Modules/responsibilities.** New `identity.py`, `journal.py`, `rng.py`, `initialization.py`, and `src/sawopt/design/canonicalization.py` (with a physics-free package initializer). Move the existing `HybridDesignSpace.canonicalize` method body unchanged into one pure helper; change the existing public method into a thin same-signature delegate passing the exact existing bounds, integer-index order, dimension and topology label. Q1 imports the leaf directly and never imports `sawopt.problem` to canonicalize. Provide typed pair/cell identities, G0–G4 coordinator, `PopulationMember`/seal/representation records, pair and arm journal APIs, typed PCG64 state/call DTOs, pure preflight certificates and validated frozen design-space metadata. No COM/evaluator/Stage 4B implementation changes.

**Inputs, outputs, state, persistence.** Inputs are frozen source/config/design-space/environment identities, the exact ordered active physical bounds/integer-index/dimension/topology metadata, fixed pair/root-seed/role, and injected pure geometry predicate. Outputs: exact pair/cell identities; lossless sampler journal and counters; one ordered seal with 234 actual evaluator vectors/keys plus representation hash; each cell's Phase-II attachment reference; shared pure canonicalization API; per-arm preflight API/certificates as each actual path becomes available. Pair-owned sampler state and per-cell attachment records persist in their SQLite stores. No fitness/result field participates in sampling.

**Dependencies.** Q0 closure is complete and Issue #52 authorizes only Q1-A. The independent pre-extraction compatibility baseline was captured before moving the method under the explicitly authorized no-physics characterization scope. Q1-B/C cannot begin their integration against moving data/journal/RNG/canonicalization interfaces until Q1-A is independently reviewed and accepted as `WORK_UNIT_READY`.

**Required tests / abnormal cases.** Before extraction, generate a source-SHA/NumPy-version-tagged, exact-byte/key characterization corpus using the legacy public method, without any evaluator/geometry/physics call. Cover all four supported topologies/dimensions, every integer coordinate, active lower/upper clips, integer ties and adjacent representable values, bounds that clip rounded integers, continuous coordinates, signed zero, input non-mutation, returned-array independence, output dtype/shape/key ordering, malformed shapes, finite valid vectors succeeding, nonfinite inputs rejecting, and conversion failures with exception class/message. After extraction, compare the legacy delegate and new leaf independently to this pre-extraction corpus; review source operation order and unchanged metadata. Run the new leaf through normal imports in a fresh process and prove no COM/provider/network import. Separately, when explicitly authorized, characterize the old public method in a distinct process that may import its transitive COM modules but calls only `canonicalize`; do not call decode, geometry, evaluator, provider, network or physics. Do not move or consolidate separate rounding in `decode_resonator`, `decode_t1`, or any other decoder. Also test golden seed derivation and PCG64 state/call codec; every allowed method and exact bytes; request/cursor/ordinal/pre-state mismatch; START before draw; pending-call regeneration and committed-call no-redraw; crash after each G0–G4 boundary; orphan/conflicting/corrupt DB; pre-barrier draw attempt; post-G4 identity loss; 10,000-draw initialization shortfall; sampler resume; duplicate-before-geometry; ULP/representation mismatch; either-arm preflight mismatch/order/key/vector/copy mismatch; zero evaluator calls before both certificates.

**Acceptance (work-unit readiness; not full gate pass).** The pair/cell identity, sampler/journal/PCG64 interfaces and shared canonicalization leaf are reviewed and ready for B/C; baseline fixtures prove the extracted helper and legacy delegate retain exact old outputs/errors; metadata is checked against the Q0 design-space identity; no production rounding copy remains; the Q1 leaf/runtime import check is physics-free; the separately authorized compatibility characterization (if used) makes no physics call; no sampler RNG occurs before G4. A readiness does **not** mark Q1-03/04/05/14/15 as `FULL_PASS`: proposal-stream parity waits for B/C/D (Q1-03); both actual evaluator paths wait for B/C (Q1-04); arm initialization/recovery waits for B/C/D (Q1-05); the live L-SHADE state codec waits for C (Q1-14); and optimizer/checkpoint hydration and crash validation wait for B/C/D (Q1-15). Those gates remain `PENDING_DEPENDENCY` until all clauses pass under the final pinned fingerprint.

**Stage 4A/4B/4C caller protection.** The extraction must preserve these current call paths and observables:

| Caller | Current use | Required preservation evidence |
|---|---|---|
| Stage 4A `HybridDesignSpace` (`src/sawopt/problem/hybrid.py`) | Public `canonicalize(vector)` used by `decode`; returns canonical NumPy vector and Python-float key. | Same signature, conversion/validation/error order, output dtype/shape/ownership, vector bytes, key bytes, and no input mutation. |
| Stage 4B (`src/sawopt/studies/hybrid_stage4b.py::_sample_stage4b_population`, `_run_cell`) | Samples candidates through `space.canonicalize`; passes `space.canonicalize` as L-SHADE canonicalizer. | Preserve candidate vectors/keys, seeded sampler outcomes, duplicate/cache identity and accounting for the frozen no-physics corpus. |
| Stage 4C (`src/sawopt/studies/hybrid_stage4c.py` → Stage 4B `run_matched_cell`) | Reuses Stage 4B cell execution and therefore the same design-space canonicalizer. | Preserve source/evaluator/optimizer behavior and saved record/checkpoint interpretation; no historical data/checkpoint/state-version edits. |

**Evidence.** Pre-extraction source SHA, pinned NumPy/build and characterization-fixture provenance; exact bytes/keys/exception results; post-extraction comparisons for both public delegate and leaf; source-order/metadata review; the caller matrix above; normal-import leaf and current Q1-A package isolation; separate no-physics legacy-characterization authorization; identity schemas/hashes, journal excerpts, G0–G4 fault matrix, sampler counter reconciliation and per-arm preflight status. Record which Q1 gates are `PENDING_DEPENDENCY`; do not publish a full-pass claim for incomplete gates. No large raw population dump in Git; publish compact certificate summaries/hashes only. See [Q1-A evidence](../../reports/stage5a2_q1a_common_foundation_20261021.md).

**PR artifact.** One focused Q1-A implementation PR: new infrastructure modules, limited tests and compact synthetic evidence, explicit touched-file/import report, source/config/environment identity, and an interface compatibility table for B/C. No Stage 4C data. Do not merge without independent review/user acceptance.

**Exit to Q1-B/C (Q1-A exit accepted).** The merged Q1-A foundation is `WORK_UNIT_READY`; it enables planning, not unauthorized implementation, of B/C. Q1-A's preflight certificates remain synthetic/non-authoritative and its evaluator dispatch is disabled. Actual 234-member per-arm evaluator input paths must be checked under B/C before FE is allowed. Q1-03/04/05/14/15 remain `PENDING_DEPENDENCY`; Q1-16 is owned by D. No gate is `FULL_PASS` until final pinned-fingerprint qualification.

### Q1-B — Controlled DE implementation

**Purpose.** Implement the dedicated controlled DE arm exactly as frozen and connect it to Q1-A interfaces without weakening accounting or replay identity.

**Q0 contract linkage.** Q0-R1/R2 controlled-DE proposal/donor/crossover/reflection/survivor/retry rules; Q0-R2 transaction and evaluation accounting; Q0-R3 RNG call tape, shared initialization and pre-FE identity contract.

**Modules/responsibilities.** New `src/sawopt/optimization/controlled_de.py`; Q1-A journal/RNG/identity APIs; minimal integration in `runner.py`; new DE-focused synthetic tests. Do not use/relabel `ScipyDELegacyBackend` or `FixedDEReferenceBackend`. Do not edit comparator/canonicalizer.

**Inputs, outputs, state, persistence.** Inputs are a ready pair/cell identity, validated attached population, exact DE initial physical vectors, injected deterministic synthetic evaluator, PCG64 facade and 4,096 terminal budget. Persist generation-start parent snapshot, target order/cursor, ordered pending trials/results, retry cursor, proposal and evaluation events, private canonical cache, counters, trace and generation checkpoint. Outputs include exact search status and a complete backend/journal state suitable for replay.

**Dependencies.** Q1-A stable interfaces; Q1-C may proceed in parallel once A is accepted. Q1-D consumes this generation state and journal behavior.

**Required tests / abnormal cases.** Fixed-RNG golden donor exclusion/order, exact `rand/1`, forced coordinate/mask draw sequence, F/CR, reflection and canonical remap; duplicate retry against immutable generation snapshot; exact tie keeps parent; geometry reject ends target; max 4,096 proposal boundary with no extra draw; shared 65,536 watchdog; no evaluator beyond 4,096 FE; exact 16×234 + 118 partial-generation arithmetic; crashes at pending generation, target cursor, duplicate, RNG/evaluator intent/result, result-before-survivor and terminal FE.

**Acceptance (work-unit readiness; not final gate closure).** Fixed N=234, F=.5, CR=.9 and synchronous frozen-parent semantics match the Q0 proposal exactly; per-target proposal cap and global watchdog stop at exact boundaries; the DE-local 4,096 FE/counter ledger reconciles; canonical duplicate/cache never incurs an evaluator call/FE; restart probes produce local evidence against uninterrupted DE state; no comparator change, COM/provider call or production route. Q1-02/08/09/10 become `LOCAL_EVIDENCE_READY`; Q1-06/07/13 await L-SHADE/common-ledger evidence, and Q1-17 remains `PENDING_DEPENDENCY` on D's fault harness. No official gate is yet labeled `FULL_PASS` at this phase exit.

**Evidence.** Golden input/output fixtures, proposal and call-identity trace, FE/counter ledger, final partial-generation proof, duplicate/failure boundary cases, checkpoint/replay digest, source/config/environment fingerprint and focused-test summary.

**PR artifact (Issue #167 grouping).** One integrated Q1-B/C Draft PR with dedicated backend, adapter use, gate-linked synthetic tests and compact replay evidence. No COM evaluation or real study outputs.

**Exit to Q1-D/E.** Q1-B PR independently reviewed/accepted as `WORK_UNIT_READY`; DE state/trace/replay interface is stable for Q1-D and E. Carry local evidence for Q1-02/08/09/10 forward; Q1-06/07/13/17 remain `PENDING_DEPENDENCY` until their L-SHADE, integrated transaction and recovery clauses are covered. Do not report those gates as full passes at this exit.

### Q1-C — L-SHADE integration

**Purpose.** Attach transaction, RNG-tape and restart instrumentation to the existing L-SHADE package while preserving its actual search behavior and complete pre-step state.

**Q0 contract linkage.** Frozen Q0 L-SHADE resolved settings, source operator/update/fallback behavior, 4,096 cold horizon, versioned lossless state/RNG contracts, Q0-R3 full pre-step replay and Q1 result-store/backend-cache separation.

**Modules/responsibilities.** New `lshade_adapter.py` and stage-specific codec/state boundary; minimal, reviewed observation hooks in `src/sawopt/optimization/lshade.py` only if required. Continue use of the existing `GeometryFirstComparator` unchanged. Do not alter Stage 4C `state_version=4`, `checkpoint_session.py`, historical readers or saved checkpoints.

**Inputs, outputs, state, persistence.** Inputs are the immutable cell identity, Phase-II-attached common population and L-SHADE genotype, lossless RNG facade, private journal/result adapter and deterministic synthetic evaluator. Persist complete live pre-step state, event-tape cursor, proposal/evaluation events, result/cache/FE state, fallback and memory batch state, and exactly one post-step commit (including FE delta zero). On restore, replay existing `_generation` control flow from the pre-step; rebuild locals from recorded RNG/results, never partial values.

**Dependencies.** Q1-A interfaces; can proceed in parallel with Q1-B. Q1-D verifies cross-cutting crashes and complete scientific trajectory equivalence.

**Required tests / abnormal cases.** Assert all resolved settings and reject 96,000 horizon; no-crash hooked/unhooked proposal/state parity; F/CR Cauchy retries, donor and crossover order, repair, duplicate retries; first-`None` fallback exit and fallback candidate accounting; interrupted evaluator and result-before-update; memory flush, archive trim, population shrink; zero-FE unsuccessful offspring; backend historical cache/FE restoration distinct from journal result store; crash before/after optimizer-step commit; direct-live-field lossless codec and reject nullified v4 payload as source.

**Acceptance (work-unit readiness; not final gate closure).** Existing L-SHADE decisions, arithmetic, branches, RNG calls/order, proposal sequence and comparator semantics are unchanged; cold horizon/settings match Q0; journal replay reconstructs local values from source/tape; each no-FE transition commits once; durable result is replayed as original logical first evaluation where appropriate and never recommitted/recounted. Minimal shared `lshade.py` observation hooks are permitted only as Q1-specific, inert instrumentation when absent/disabled and with bitwise no-crash hooked/unhooked trajectory parity. This may change the shared source file/hash; it must not change Stage 4C scientific behavior, config/wiring, `state_version=4`, historical readers, checkpoint bytes or saved data. Q1-01/11 become `LOCAL_EVIDENCE_READY`; Q1-18 remains `PENDING_DEPENDENCY` until D's restart/fault matrix, with the live-state portion of Q1-14 supplied here. No official dependent gate is labeled `FULL_PASS` at this phase exit.

**Evidence.** Uninstrumented-versus-hooked parity artifact; complete pre/post state and per-step replay digest; fallback and no-FE trace; codec round-trip/negative cases; separate backend and journal counter ledger; pinned source/config/environment identity and focused tests.

**PR artifact (Issue #167 grouping).** The same integrated Q1-B/C Draft PR, with minimal hook diff, adapter/state codec, isolated synthetic tests and explicit historical-protection diff; no COM runs and no migration of Stage 4C states.

**Exit to Q1-D/E.** Q1-C PR independently reviewed/accepted as `WORK_UNIT_READY`; the L-SHADE interface and shared-source parity evidence are stable. Carry local evidence for Q1-01/11 and the live-state portion of Q1-14 forward; Q1-18 remains `PENDING_DEPENDENCY` until D completes crash/restart qualification. No full-gate claim is made here.

### Q1-D — Crash Recovery / Determinism Qualification

**Purpose.** Cross the integration boundary and establish fail-closed, exactly-once durable accounting and scientific trajectory equivalence under synthetic fault injection.

**Q0 contract linkage.** Entire Q0-R2 transition/failure/censor contract and Q0-R3 genesis/RNG/pre-step replay requirements. This unit validates implementation against the fixed rules; it does not invent recovery states or redefine evaluator determinism.

**Modules/responsibilities.** New/reused `recovery.py` test harness and shared fault-injection fixtures; exercise Q1-A journal, Q1-B DE and Q1-C L-SHADE. Keep operational-attempt history separate from scientific trajectory fields.

**Inputs, outputs, state, persistence.** Inputs are versioned pair/cell identities, persisted SQLite journals/checkpoints, deterministic synthetic evaluator and explicit fault-point schedule. Outputs are per-fault recovery verdicts, exact event-chain and state digests, durable FE/result ledgers, trajectory comparisons and terminal failure status where appropriate.

**Dependencies.** Q1-A, Q1-B and Q1-C reviewed interfaces/implementations. Q1-D is not a substitute for a failing unit gate in A/B/C; fix at owner, then rerun only the bounded affected qualification and D matrix.

**Required tests / abnormal cases.** Inject crash before/after every genesis, RNG START/COMMITTED, PCG64 return, proposal, intent, evaluator start/return, result, duplicate/cursor, fallback `None`, zero-FE step, memory/archive/shrink/trace, DE generation, checkpoint and validation boundary. Test corrupt/truncated journals/checkpoints, hash/sequence mismatch, wrong identity/environment/config, post-G4 loss, pending evaluation, repeated physical attempt, committed result, and stale/missing snapshots. Verify exact result/FE/cache/trace once, logical RNG calls no skip/double, and unchanged science state after restart.

**Acceptance (D work-unit readiness).** The integrated Q1-12/Q1-16/Q1-19 fault matrices produce exact, reproducible evidence: restarted scientific proposal/RNG/population/cache/rank/trace/top-16 fields equal the uninterrupted reference for both algorithms; operational retries, journal recovery and downtime are separate; committed draws/results are not redrawn/recounted; pending calls/transactions follow only Q0 rules; corrupted or identity-mismatched state fails before hydration/evaluator call. D returns its primary gate evidence to `LOCAL_EVIDENCE_READY`; primary owners of Q1-03/04/05/06/07/14/15/17/18 reconcile their dependent clauses. Those official gates remain `PENDING_DEPENDENCY` until final common-fingerprint closure.

**Evidence.** Fault-injection matrix (boundary × expected state × observed state), event hash-chain and prefix reconciliation, uninterrupted/recovered bitwise digests, FE/result/cache/trace uniqueness report, invalid-state rejection records, environment fingerprint and test summary.

**PR artifact.** One focused Q1-D recovery/qualification PR with fault fixtures, reproducible compact synthetic evidence, per-gate pass table and no production or COM evidence.

**Exit to Q1-E.** Q1-D PR independently reviewed/accepted as `WORK_UNIT_READY`; its full fault/recovery evidence has no unresolved integrity mismatch and the primary owners have reconciled dependent evidence. All official gates remain pending final rerun/closure on the pinned Q1 release-candidate source/config/environment fingerprint; Q1-E performs that final qualification and integration.

### Q1-E — Synthetic Integration / Comparison Reporting

**Purpose.** Exercise the full fixed matrix only as a synthetic software integration and generate reproducible, censored comparison records using Q0 rules.

**Q0 contract linkage.** Fixed 2 topologies × 2 algorithms × 3 matched roots, private arm caches, exact shared 234-member starts, 4,096 unique search FE/cell, top-16 validation, serial order, exact timing/resource ledger, and Q0-R2 seven paper-only censored cases. The integration objective is synthetic and makes no physical or SAW claim.

**Modules/responsibilities.** New `runner.py` orchestration restricted to injected synthetic evaluator; `reporting.py` consumes gate-qualified journal traces and emits deterministic JSON/CSV/report. Tests enforce no COM/provider/physics import or call and no production orchestration. Never call a COM evaluator, the real Stage 4C evaluator or launch APIs.

**Inputs, outputs, state, persistence.** Inputs are pinned source/config/environment fingerprints, fixture topologies/design spaces, exact matched roots, one synthetic objective, 12 isolated cell journals and fixed resource policy. Outputs: 12 visible cell records including incomplete/invalid cells; immutable input/identity hashes; validated synthetic top-16 records; phase-separated timing/resource counters; complete synthetic comparison summary and censored-case fixtures. Any raw synthetic journals remain outside Git if bulky; committed PR evidence is compact and deterministic.

**Dependencies.** A–D acceptance and stable public APIs; no Q1 run before separate authorization. The integration itself remains Q1 synthetic-only.

**Required tests / abnormal cases.** Exactly 12 planned cells and fixed order; shared initialization hash per pair and independent arm evaluation/caches; all complete/incomplete statuses; stable top-16 distinct search-history candidates and validation isolation; time/resource counter disjointness; all seven paper-only censored examples including initialization-only/asymmetric failure; valid contiguous common prefixes, exact tuple paired outcomes, six pairs always visible, no forward-fill/survivor-only summary; missing/invalid trace support; import/call guard proving no COM/provider/network and no production orchestration.

**Acceptance.** Q1-20…23 all pass. Every cell and pair is visible; all aggregation obeys the frozen comparator/support/endpoint/status rules; synthetic search FE never exceeds 4,096 per arm; validation is excluded; report hashes reproduce; no physical evaluator or production path is imported or invoked. Results are labeled synthetic qualification only, not SAW outcomes.

**Evidence.** Matrix manifest and 12 cell-status ledger, population/preflight hashes, top-16 and validation digest, comparison/censor report, FE/time/resource reconciliation, import/call-boundary evidence, pinned source/config/environment fingerprint, deterministic report checksum and focused-test summary.

**PR artifact.** One focused Q1-E integration/reporting PR with compact synthetic evidence, Q1-20…23 dispositions, exact report reproduction and explicit no-COM/no-production boundary proof.

**Exit / overall Q1 close.** Q1-E PR independently reviewed and accepted; all 23 official gates pass in one pinned implementation/config/environment provenance set and reproducible evidence is published. Stop at review. A Q1 pass does not authorize a real optimizer comparison, COM evaluation, Stage 4C change or production launch.

## 6. Sole official Q1 gate ownership and coverage

This is a **one-to-one primary ownership map** to the existing matrix only. The work-unit gate associations requested in the project plan may overlap as dependencies (in particular Q1-16); that does not duplicate or redefine an official gate. Full pass conditions remain solely in the [Q1 matrix](stage5a2_q1_qualification_matrix.md).

### 6.1 Evidence maturity at work-unit exits

Unit-level results and official-gate results are different records. A unit may be `WORK_UNIT_READY` when its own implementation/API, local tests and PR are accepted, while a dependent official gate stays `PENDING_DEPENDENCY`. `LOCAL_EVIDENCE_READY` means only that listed clauses have evidence; it is not a gate `FULL_PASS`. No gate gets `FULL_PASS` until all its clauses, dependent work-unit evidence, final pinned source/config/environment fingerprint and independent review are complete. Its unique primary owner records that closure. Gate IDs are not duplicated by these maturity labels.

| Work-unit exit | Local evidence that can be established here | Must remain `PENDING_DEPENDENCY` until integrated/final qualification |
|---|---|---|
| Q1-A `WORK_UNIT_READY` | Identity/RNG/schema components, population/seal construction, pure canonicalization leaf characterization and metadata checks. | Q1-03 proposal-stream/no-hidden-draw parity (B/C/D); Q1-04 both actual arm evaluator paths (B/C); Q1-05 arm initialization/recovery (B/C/D); Q1-14 live L-SHADE codec (C); Q1-15 optimizer/checkpoint hydration and recovery (B/C/D). |
| Q1-B `WORK_UNIT_READY` | DE-local Q1-02, Q1-08, Q1-09, Q1-10 fixtures and local state/trace evidence. | Q1-06/07/13 require C and integrated accounting; Q1-17 requires D crash/restart harness; Q1-04/05 require arm initialization evidence. |
| Q1-C `WORK_UNIT_READY` | L-SHADE-local Q1-01 and Q1-11 fixtures, live-state codec component, hooked/unhooked trajectory comparison. | Q1-18 requires D crash/restart harness; Q1-14/15 and common initialization/accounting gates require A/B/D integration. |
| Q1-D `WORK_UNIT_READY` | Integrated recovery/failure/trace evidence for its primary Q1-12/16/19 responsibilities; recovery clauses for A/B/C gates. | Other primary owners reconcile all dependencies; Q1-17/18 are not reassigned from B/C. Final full-gate closure still waits for the final pinned fingerprint and Q1-E run. |
| Q1-E final qualification | Runs the authorized synthetic integration and final pinned evidence set; primary owners record `FULL_PASS` only for gates whose complete requirements pass. | Any failed, incomplete, unpinned or unreviewed gate remains pending/failed; Q1 cannot be accepted partially. |

| Official gate | Primary owner | Cross-unit dependency / note |
|---|---|---|
| Q1-01 | Q1-C | Uses A RNG/state codec. |
| Q1-02 | Q1-B | Uses A RNG and canonicalization. |
| Q1-03 | Q1-A | Shared facade supports B/C/D. |
| Q1-04 | Q1-A | B/C supply actual-input paths; both certificates before any FE. |
| Q1-05 | Q1-A | D fault-injects coordinator; A owns initial population/genesis qualification. |
| Q1-06 | Q1-B | C participates in private L-SHADE cache behavior. |
| Q1-07 | Q1-B | D independently fault-tests reconciliation. |
| Q1-08 | Q1-B | Synchronous DE semantics. |
| Q1-09 | Q1-B | Exact final partial generation. |
| Q1-10 | Q1-B | Proposal/stall boundaries. |
| Q1-11 | Q1-C | Existing L-SHADE fallback behavior. |
| Q1-12 | Q1-D | Cross-component failure taxonomy. |
| Q1-13 | Q1-B | DE and shared schema validation; C must preserve existing comparator behavior. |
| Q1-14 | Q1-A | Lossless shared codecs; C supplies live state payload. |
| Q1-15 | Q1-A | Identity/attachment lifecycle; D tests corruption/recovery. |
| Q1-16 | Q1-D | One integrated transaction-transition/recovery matrix; A/B/C supply transitions. |
| Q1-17 | Q1-B | DE restart; D supplies crash harness. |
| Q1-18 | Q1-C | L-SHADE restart; D supplies crash harness. |
| Q1-19 | Q1-D | Cross-algorithm scientific trace integrity. |
| Q1-20 | Q1-E | Dense finalist validation. |
| Q1-21 | Q1-E | Synthetic-only 12-cell integration. |
| Q1-22 | Q1-E | Timing/resources/storage reporting. |
| Q1-23 | Q1-E | Frozen censored comparison report and seven paper-only examples. |

**Coverage check:** 23 distinct primary assignments; Q1-01 through Q1-23 each appear once; no new qualification ID is introduced. Work-unit gate associations (which can overlap) are: Q1-A touches Q1-03/04/05/14/15 and provides transaction primitives for Q1-16; Q1-B touches Q1-02/06–10/13/17 and supplies transitions for Q1-16; Q1-C touches Q1-01/11/16/18; Q1-D touches Q1-12/16–19 and provides the integrated crash/recovery qualification, while Q1-17 and Q1-18 remain primarily owned by Q1-B and Q1-C respectively; Q1-E owns Q1-20–23. Cross-unit mentions are dependencies, not additional gate instances.

## 7. Shared evidence, PR and governance requirements

Each implementation PR must include: changed-module/responsibility list; exact Q0 contracts/gate IDs; focused synthetic test commands/results; abnormal-case evidence; source/config/environment fingerprint; machine-readable compact evidence or hashes; and explicit statement that no COM/network/physics, real SAW optimization, Stage 4C mutation or production orchestration was run. Review the PR on GitHub; a passing test or Codex self-review is not external acceptance. Keep each PR scoped to its work unit and do not merge automatically.

Q1 qualification artifacts must be sufficient for an independent reader to reproduce the checks, while large journals/checkpoints/populations remain outside the repository under the project storage policy. Only compact deterministic summaries/hashes belong in the PR.

## 8. Start gate and stop conditions

### Start gate — met for the bounded Issue #167 B/C unit only

Q0 closeout and Q1-A acceptance remain recorded. The owner explicitly authorized the Issue #167 B/C implementation and deterministic synthetic-only unit/integration scope after confirmation in the implementation conversation. This is not Q1-D/E authorization, a full Q1 qualification launch, scientific experiment permission or acceptance of this implementation. The earlier plan/Issue alone did not grant permission.

### Stop/fail-closed conditions

Stop the affected work unit and do not choose a workaround if any of the following occurs:

- A Q0 identity, sampler, RNG, optimizer, evaluation, failure, comparator, budget, censoring or reporting rule cannot be implemented as written.
- Either actual initial population preflight differs by one bit, key, order or evaluator boundary before FE.
- Journal/checkpoint identity, sequence/hash, typed value, event, RNG cursor, result or FE ledger is missing/mismatched/corrupt.
- A committed RNG result would be redrawn, a committed result/FE/cache/trace would be duplicated, or a zero-FE optimizer step would be skipped/doubled.
- L-SHADE instrumentation changes its original uninterrupted scientific trajectory or uses a lossy/nullified historical state payload.
- An unexpected/infrastructure failure is being classified as modeled physics failure, or a censored/invalid cell is about to be ranked as complete.
- A COM/provider/physics import or call, production orchestration, Stage 4C write, actual SAW optimizer run, changed budget or other prohibited action is reached or proposed.

Record concrete evidence and impact, preserve journals/source, and request the appropriate independent review/user decision. Do not automatically escalate to Sol unless a Q0 design contradiction or high-risk change requires it under project policy. Do not spawn a successor implementation/run from a completion continuation.

## 9. Q1 acceptance and what remains out of scope

Q1 acceptance requires all Q1-01…Q1-23 mandatory gates passed in a pinned environment with reproducible evidence and a common source/config/environment fingerprint, independent GitHub review of the implementation/evidence, and user acceptance. Any mandatory failure leaves Q1 incomplete; no partial pass can be represented as authorization for a later stage.

Even after Q1 acceptance, **separate user-reviewed authorization** is still required before COM/network/physics evaluation, the 12-cell real comparison, an optimizer pilot/benchmark, production orchestration, any budget/bound/topology/specification/constraint change, or Stage 4C data changes. This plan authorizes none of them.
