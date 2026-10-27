# Architecture: current implementation and target ownership

**Current status:** R2–R5 and the authorized synthetic R6 components are
merged. R6-L1, L2, and L3 are merged in PRs #132, #133, and #135. Issue #131
tracks the final L4 documentation, CI-assurance, and closeout review. The
supported design/run path is synthetic/injected-only; `review export` only
postprocesses a closed R5 raw run. The product's integrated, user-configurable
real-SAW design workflow is a future goal. The ownership map
below describes the checked-in source at the L4 starting baseline
`cf426e8b5a86213cbc16c677671f5b6f69e2d4ed`; exact counts and validation
evidence are in the [R6-L4 closeout record](history/r6_l4_closeout_20261025.md).

The reconstruction retired the old Codex queue/callback, legacy scientific
CLI and detached orchestration launch/worker, schema-v1–v4 lifecycle and
exporter, historical Stage 3/4 study executors and exclusive report pipelines,
and the uncalled COM optimization runner with its private run-store/writer/
history helpers. These were capability removals, not changes to historical
reports, raw data, scientific conclusions, COM equations, optimizer semantics,
Q0/Q1 status, or run authorization. The retained and deferred boundaries are
listed below; old plans remain audit records, not current work instructions.

## Issue #157 validation-only extension

The [scientific config v1 contract](scientific_config_v1.md) adds strict
scientific declarations and non-executing `validate` dispatch. Scientific CLI
`run` fails closed with `SCIENTIFIC_RUN_NOT_IMPLEMENTED`; no configured
scientific CLI or R5 execution lifecycle is supported. `io.cli_config` owns
safe YAML/schema dispatch; `io.scientific_config` owns the pure resolver,
separated to avoid importing physics/design/evaluation/optimizer/R5 during
validation. Issue #159 adds the library-only `ConfiguredCandidateEvaluator`,
and Issue #161 adds explicit-callback single-cell L-SHADE orchestration under
`optimization.configured_search`. These APIs do not add CLI execution, R5
storage, source/environment attestation, Q0 compatibility, or run authorization.
The baseline inventory below remains a historical snapshot.

## Target dependency direction

This is the intended product layering, not a claim that every current package
has already been reduced to these owners.

```text
cli / plotting / io
          ↓
optimization → evaluation → design + physics
```

- **`physics/`** — COM sections/elements, acoustic and electrical network,
  and S-parameter calculations. Must not depend on optimizer, study, CLI,
  reporting, GitHub, or run lifecycle.
- **`design/`** — topology, bounds, variable representation, canonicalization,
  and geometry. Must not invoke COM evaluation or optimization.
- **`evaluation.py`** — the single response/metrics/constraint bridge from
  design plus physics. It reports feasibility and the existing scalar search
  surrogate; `optimization.selection` is the sole candidate comparator after
  the R4 source consolidation. The existing `problem.evaluator.dense`
  adaptive/cache/counter orchestration remains explicitly deferred and
  unchanged.
- **`optimization/`** — L-SHADE/DE strategies with shared unique-FE budget,
  cache, counter, and checkpoint services. The current synthetic CLI invokes
  L-SHADE directly; the historical COM optimization runner is retired.
  Algorithm-specific proposal rules remain within their strategies.
- **`io/`** — current strict synthetic CLI config, checkpoint/provenance
  services, future-only R5 external raw storage, and an isolated synthetic
  countdown-task ledger. No old v1–v4 run-manifest reader or agent-session
  continuation is retained.
- **`cli.py`** — current console and module entrypoint. `validate`, `run`, and
  `synthetic-task` are software-only; `review export` postprocesses an existing
  closed R5 raw run. No old dispatcher or COM/FE evaluation command exists.

These ownership statements describe target ownership and the R3/R4-authorized
subsets; they do not imply that the entire repository has reached that target.
Avoid duplicate implementations and blanket compatibility layers. Issue #129
removes the seven-variable `core.hybrid.response` and the `problem.hybrid`
compatibility import after moving canonicalization verification to
`design.space`; the independent `problem.released_dms` T0 parity reference
remains. The 92-case Q1-A golden is verified through `design.space` and the
physics-free `design.canonicalization` leaf. DMS reference-grid, material-provider,
and initial-design helpers remain for numerical parity coverage; the historical
DMS screening executor and Stage 3.9B source-reconstruction workflow do not.
The current R2 deterministic parity recipe imports the new owners directly. R4
consolidates algorithm strategies, selection and shared optimization services
under one package, leaves `problem.evaluator.dense` adaptive/cache/counter
orchestration unchanged, and Issue #129 removes the single-file historical
checkpoint fallback while preserving rolling checkpoint/RNG state.

## Current → target responsibility map

| Current code (exists) | Current role / observed coupling | Target owner (future) |
|---|---|---|
| `src/sawopt/physics/com.py`, `network.py`, `literature_com.py`; former `src/sawopt/core/models.py` | R2 owns COM P-matrix propagation/global acoustic solve, COM providers and result record, and the real-positive-port network evaluator. R3 moves the complete provider-visible `FilterDesign` record and decoder to `design.space`, updates current callers, and removes the duplicate `core.models` module. | Physics remains in `physics/`; design records/decoding in `design/`, response and RF metrics in `evaluation.py`. |
| Former `src/sawopt/core/metrics.py` | Legacy owner of frequency grids, response metrics, geometry and a scalar search surrogate; candidate comparison is separately owned by `optimization.selection`. R3 moves callers and removes the duplicate module. | Pure geometry to `design.geometry`; grids/metrics/feasibility and the unchanged scalar surrogate to `evaluation.py`. |
| `src/sawopt/problem/evaluator.py`; `src/sawopt/problem/released_dms.py` | `dense` remains the independently tested adaptive/cache/counter evaluation boundary; the synthetic CLI injects response metrics and does not dispatch it. `released_dms.py` remains an independent T0 parity reference. The `problem.hybrid` compatibility alias is removed. | Preserve `problem.evaluator.dense` and released-DMS parity behavior; canonical design and reusable response/evaluation remain owned by `design/`, `physics/`, and `evaluation.py`. |
| `src/sawopt/optimization/` | After Issue #67, owns L-SHADE/SciPy-DE strategies, the sole comparator, shared budget/cache/accounting services, and backend-specific checkpoint session. Issue #130 removes the uncalled historical `optimization.runner` COM/run-store executor; the current synthetic CLI selects L-SHADE. Issue #161 adds `configured_search` as an in-memory single-cell L-SHADE orchestrator with explicit injected SEARCH/VALIDATION callbacks; it does not own R5 lifecycle or CLI dispatch. The separate `optimizers/` package is retired; overlapping polish APIs are owned here. | Keep the unified strategy/service owner; preserve `problem.evaluator.dense` as the deferred evaluation boundary and IO as durable checkpoint-store owner. |
| `src/sawopt/io/` | Current checkpoint/provenance services, future-only `io.experiment_store`, and the isolated Issue #80 `io.synthetic_task_ledger`. Issue #130 removes `io.run_store` and its legacy `io.serialization` writer with the COM executor; neither R5 storage nor the task ledger reads or rewrites legacy manifests. | Keep current checkpoint and external raw ownership; the countdown ledger remains synthetic-only and local to an explicit private test root. |
| `src/sawopt/studies/` | Q1-A under `stage5a2/` and reusable DMS reference/grid/provider/initial-design helpers in `dms_topology_common.py` remain. Historical Stage 3/4 executors, DMS screening runtime, and Stage 3.9B/5A-1 audits are removed under Issue #129. | Keep Q1-A identity/canonicalization/RNG/journal/initialization and DMS reference parity unchanged; no retired study runner/audit API remains. |
| `src/sawopt/reporting/` | R5 `experiment_review` and the material-profile metadata helper used by DMS reference code remain. Old saved-run reports, Stage 4 candidate-integrity adapters, material HTML rendering, and ZIP review workflows are removed with exclusive callers/tests. | Keep R5 schema v1 and DMS metadata semantics unchanged; historical reports remain immutable records, not executable pipelines. |
| `src/sawopt/runtime/` | Owns the retained runtime-level environment behavior. The standalone worktree-safety utility was retired under Issue #143; R5 external-data-root validation remains independently owned by `io.experiment_store`. | Keep runtime behavior separate from IO and scientific ownership; no project-local worktree lifecycle tool is supported. |
| `src/sawopt/cli.py`; retired `src/sawopt/__main__.py` | The `sawopt` console entry point and `python -m sawopt.cli` expose synthetic `validate`/`run`, `review export` for an existing closed R5 raw run, and `synthetic-task` launch/status/attach/resume/stop. The synthetic run injects response metrics and is not COM/FE evaluation; review export is a postprocessor and does not launch work. Issue #161 adds no scientific CLI route; scientific `run` remains fail-closed. There is no `python -m sawopt` dispatcher or old `export-review` alias. | Keep each path within its documented software-only contract. The task ledger is not scientific task/optimizer resume; R5 review readiness is not scientific acceptance. |

The detailed pre-R2 inventory, module list, configs/tests, and observed package
edges are in the [R0 preflight inventory](../reports/restructure/r0_preflight_inventory_20261022.md);
it is historical baseline evidence, not a current source inventory.

## Historical dependency scan and current remaining boundary

R0's pre-R2 static package import scan found these edges:

- `__main__ → core, io, optimization, reporting, studies`;
- `problem → core, design, optimization`;
- `optimization → core, io, optimizers, problem`;
- `optimizers → io`;
- `studies → core, design, io, optimization, optimizers, orchestration, problem, reporting`;
- `reporting → core, optimization, optimizers, orchestration, studies`;
- `orchestration → io, reporting, studies`.

These are the pre-R2 software dependencies, not proof that a module is dead.
The R2 extraction now has `physics.elements → physics.com`; the other physics
modules import only external numerical libraries or standard-library modules.
`problem.evaluator.dense` remains the retained adaptive/cache/counter evaluation
boundary and its numerical behavior is exercised by the adaptive-search tests;
the synthetic CLI does not invoke it. Issue #129 removes old study execution
and report/export pipelines rather than retaining callable compatibility paths.
Issue #130 also removes the uncalled historical COM optimizer runner and its
exclusive persistence/history helpers. The standalone SciPy-DE strategy,
optimizer services, and narrow DMS material-profile metadata helper remain for
their distinct current ownership/contracts. Issue #143 retired the separate
worktree-safety utility; R5 external-data-root validation remains owned by
`io.experiment_store` and does not provide worktree lifecycle operations.

The current source is the result of staged R2–R6 changes. Reusable COM,
design/evaluation, optimizer/checkpoint, Q1-A, R5 external-data-root validation,
synthetic-task, and retained DMS reference/parity responsibilities remain.
Issue #143 retired the separate worktree-safety utility without changing R5
root validation. R6-L1 through L3 retired the legacy lifecycle, historical
execution surfaces, and uncalled COM runner; the L4 closeout record gives their
scope and before/after counts. The old scientific entrypoints, compatibility
readers, and removed APIs are not supported, aliased, or retained as rejection
stubs.
The R3/R4/R6 and R7 documents linked elsewhere in this repository are dated
evidence for their specific reviews, not instructions to resume old work.

R4's optimizer consolidation did not qualify Q1 or establish cross-CPU bitwise
identity. R5 implements only future raw/review storage contracts. The external
data-root validator rejects repository/worktree containment but does not
inventory active runs or process state; no standalone worktree-safety tool is
retained. No software stage authorizes a change to equations, ranking, bounds,
Q0/Q1 semantics, run conditions, or scientific execution.

## Q1-A implementation and evidence boundary

Q1-A code currently lives under `studies/stage5a2/` and the shared
`design/canonicalization.py` leaf. Its work unit is closed as
`WORK_UNIT_READY`, but no formal Q1 gate passed. The stage-specific foundation
and exact 92-case golden corpus remain; the removed `problem.hybrid` alias is
replaced in verification by the canonical `design.space` API, with the leaf
also checked directly. The explicit contract disposition and owner decision
boundary are in
[Q1 contract disposition](plans/restructure_q1_contract_disposition_20261022.md).
Do not begin Q1-B/C/D/E or claim the existing foundation is generally
production-qualified.
