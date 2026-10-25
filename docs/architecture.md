# Architecture: current implementation and target ownership

**Status:** R2 physics extraction, R3 design/evaluation separation, R4 optimizer
consolidation, and R5 future-only raw/review storage are merged. R6-A's
synthetic CLI and the separately scoped synthetic task/recovery and mock-only
Pi protocol are also merged; they do not qualify scientific optimizer/FE
recovery or real Pi exact-session continuation. R6-C1 retired the active legacy
Codex queue/callback runtime and unsupported Stage 4B/4C production entrypoints
in PR #109, merged at `604091d550c8fad302ed179e3e177d3a1ee3c7c1`. Issue #111
C2A retired the remaining project-local C2C/Codex hook utilities under PR #112.
Issue #118 retired the obsolete Stage 4C execution and qualification tools under
PR #120. Issue #119 removed the legacy scientific CLI and detached
orchestration launch/worker. Issue #124 retires the remaining schema-v1–v4
`export-review` module dispatcher and GitHub exporter; the separate R5 package
and independently used safety/reporting owners remain. Other C2B cleanup and
R7 remain separate gates.
The former Stage4B fingerprint reconstruction stop gate in Issue #106 is
superseded; the frozen fingerprint, source commit, and reports remain historical
facts only. See the [C1
scope](plans/issue108_r6c1_codex_removal_20261024.md), [Issue #75 owner
policy](plans/issue75_legacy_codex_retirement_decision_20261024.md), [Issue #106
inventory](plans/issue106_r6c0_codex_removal_inventory_20261024.md), and
[Issue #111 C2A disposition](plans/issue111_r6c2a_legacy_surface_disposition_20261024.md).
The R7 audit is recorded in [its proposal](plans/r7_architecture_ci_audit_20261023.md);
it does not itself authorize unrelated legacy cleanup. See the [R3
inventory](plans/restructure_r3_ownership_20261022.md), [R4
inventory](plans/restructure_r4_ownership_20261022.md), and [R6
inventory](plans/restructure_r6_ownership_20261023.md). The R0 inventory counted 94 Python modules at main
`a4b3807d399cc78b10c280d41ee8cea476ade329` (pre-R2 baseline). Target APIs not
yet implemented must not be treated as current.

## Target dependency direction

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
- **`optimization/`** — L-SHADE/DE strategies and a bounded shared runner for
  search, unique-FE budget, cache, counters, and required checkpoint state.
  Algorithm-specific proposal rules remain within their strategies.
- **`io/`** — user configuration, results, frozen provenance, external raw
  storage, and only the checkpoint lifecycle required by the approved current
  design; no agent-session continuation.
- **`cli.py` / `plotting.py`** — user entry points and scientific visualization;
  lower-level packages do not import them.

These ownership statements describe target ownership and the R3/R4-authorized
subsets; they do not imply that the entire repository has reached that target.
Avoid duplicate implementations and blanket compatibility layers. R3 retains
the operational seven-variable `core.hybrid.response` path and the narrow
`problem.hybrid` public import needed by Q1-A golden verification; moved
`core.models`, `core.metrics`, and mixed `problem/` implementations are
removed rather than retained as proxy modules. Current R2 parity and Stage
3.9B source recipes import the new owners directly. R4 consolidates algorithm
strategies, selection and shared optimization services under one package, but
leaves `problem.evaluator.dense` adaptive/cache/counter orchestration unchanged;
no old-checkpoint reader is introduced.

## Current → target responsibility map

| Current code (exists) | Current role / observed coupling | Target owner (future) |
|---|---|---|
| `src/sawopt/physics/com.py`, `network.py`, `literature_com.py`; former `src/sawopt/core/models.py` | R2 owns COM P-matrix propagation/global acoustic solve, COM providers and result record, and the real-positive-port network evaluator. R3 moves the complete provider-visible `FilterDesign` record and decoder to `design.space`, updates current callers, and removes the duplicate `core.models` module. | Physics remains in `physics/`; design records/decoding in `design/`, response and RF metrics in `evaluation.py`. |
| `src/sawopt/physics/elements.py`; `src/sawopt/core/hybrid.py` | R2 owns reusable acoustic-section, IDT-port, one-port resonator, parallel-track, and electrical nodal composition in `physics/`. The seven-variable-root `core.hybrid.response` and its live `studies.hybrid`/test callers are expressly retained as operational legacy evidence; it is not the new canonical evaluator. | Reusable physical composition in `physics/`; new design ownership in `design/`. `core.hybrid.response` remains until an R6 disposition after replacement/evidence review. |
| Former `src/sawopt/core/metrics.py` | Legacy owner of frequency grids, response metrics, geometry and a scalar search surrogate; candidate comparison is separately owned by `optimization.selection`. R3 moves callers and removes the duplicate module. | Pure geometry to `design.geometry`; grids/metrics/feasibility and the unchanged scalar surrogate to `evaluation.py`. |
| Former `src/sawopt/problem/design_space.py`, `dms_topologies.py`, `validation.py`; current `released_dms.py`, `hybrid.py`, `evaluator.py` | Mixed design/topology/geometry/evaluation responsibilities; `problem.evaluator.dense` owns adaptive/cache/counter orchestration. R3 moves design/geometry/evaluation owners and removes the duplicated mixed modules. `ReleasedFilterDesign` / `simulate_released_filter` remain exclusively as T0 parity evidence; ordinary T0 design/evaluation now uses `design.topology.ThreeIdtDesign` and the generalized evaluator. `problem.hybrid` remains only for the Q1-A public golden import path. | Pure records/spaces/canonicalization/geometry to `design/`; one-design response and metrics to `evaluation.py`. Preserve the `problem.evaluator.dense` adaptive/cache/counter orchestration and behavior for explicit R4 follow-up; the point-response dependency now delegates to evaluation. Released DMS code remains parity-only. |
| `src/sawopt/optimization/` | After the Issue #67 source consolidation, owns L-SHADE/SciPy-DE strategies, the sole comparator, shared budget/cache/accounting/runner services, and the backend-specific checkpoint session. The separate `optimizers/` package is retired; overlapping polish APIs are owned here. | Keep the unified strategy/service owner; preserve `problem.evaluator.dense` as the deferred orchestration boundary and IO as durable checkpoint-store owner. |
| `src/sawopt/io/` | Config, serialization, legacy run stores, provenance, checkpoints and lifecycle. Issue #69 adds the separate future-only `io.experiment_store` API; Issue #80 adds `io.synthetic_task_ledger` for one isolated synthetic countdown worker, not a raw store or scientific-run ledger. Neither reinterprets legacy manifests or wires a research runner. | `io/` config/results/checkpoint and external raw ownership; the Issue #80 ledger remains synthetic-only and local to an explicit private test root. |
| `src/sawopt/studies/` | Live adapters, historical audits, stage-specific studies, Q1-A foundation. | Config-driven experiment inputs and only thin reusable orchestration; retire stage-specific runtime after explicit disposition. |
| `src/sawopt/reporting/` | Historical/ad-hoc reports, ZIP bundles, integrity, and R5 `reporting.experiment_review`. Issue #124 removes the old schema-v1–v4 `github_review` exporter; retained ZIP/report helpers have independent callers and tests. | Compact R5 review export remains separate from historical reporting; plots in `plotting.py`; retain no agent coupling. |
| `src/sawopt/orchestration/`, `runtime/` | The obsolete detached legacy launch/resume/recover/worker path was removed in Issue #119. Retained responsibilities include historical status and guarded publication, administrative closeout, run-state records, active-run/worktree/persistent-path/PID safety, and execution-environment helpers. | Preserve independently used non-agent safety and historical/reporting behavior. Do not restore the retired launcher/worker or change run-state semantics as incidental cleanup. |
| `src/sawopt/cli.py`; retired `src/sawopt/__main__.py` | The `sawopt` console entry point and `python -m sawopt.cli` provide strict synthetic config validation/run through injected response metrics, optimizer, and R5 storage/export. Issue #80 adds only an explicit Linux/WSL2 `synthetic-task launch/status/attach/stop` group using the isolated countdown worker/SQLite ledger. Issue #124 removes `python -m sawopt` and its old `export-review` capability; this is not an alias or migration to R5. | Keep the new paths synthetic/injected-only; the task ledger is not scientific task/optimizer resume. Preserve R5 schema v1 and keep old reports/data immutable. |

The concrete inventory, module list, configs/tests, and observed package edges
are recorded in the [R0 preflight inventory](../reports/restructure/r0_preflight_inventory_20261022.md).

## Current dependency risks and migration prerequisites

R0's static package import scan found these existing edges:

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
`problem.evaluator.dense` still uses optimization cache/adaptive-frequency and
counter services by the explicit R3/R4 disposition. Studies/reporting/
orchestration retain legacy runtime cycles for later stages. The architecture
refactor must move ownership and invert dependencies intentionally; renaming
directories alone will not meet the target.

R2–R5 and the authorized synthetic/mock R6 increments are merged. R3's
ownership choices and evidence-only dispositions are explicit in the [R3
inventory](plans/restructure_r3_ownership_20261022.md). R4 consolidates
optimization source ownership while leaving the dense boundary unchanged; its
merge does not qualify Q1 or establish cross-CPU bitwise identity. R5
implements only future raw/review storage contracts. The R6 inventories and
[#94 design](plans/issue94_r6c_three_resume_migration_design_20261024.md)
document the limited synthetic/mock evidence. C1 removed the old agent
transport; C2A retired the project-local hook/probe surface; Issue #118 retired
Stage 4C execution and qualification tools; and Issue #119 removed the old
scientific CLI and detached orchestration launch/worker. Issue #124 then
retired the old schema-v1–v4 `export-review` path and exporter; this does not
remove existing review evidence or the separate R5 exporter. Independently
used status, guarded publication, closeout, and worktree/storage/process safety
responsibilities remain. The [R7 audit
proposal](plans/r7_architecture_ci_audit_20261023.md) records owner decisions
and is not authorization for unrelated cleanup. Each stage remains a separate
gate in the [migration plan](plans/repository_restructure_migration_plan_20261022.md).
No stage grants permission to change equations, ranking, bounds, Q0/Q1
semantics, or run conditions.

## Q1-A implementation and evidence boundary

Q1-A code currently lives under `studies/stage5a2/` and a shared
`design/canonicalization.py` leaf. Its work unit is closed as
`WORK_UNIT_READY`, but no formal Q1 gate passed. The target design removes
stage-specific runtime folders; it does **not** decide whether Q1-A source is
to be replaced, retired, or reused. R3 preserves the 92-case Q1-A public/leaf
golden corpus and the canonicalizer's exact behavior; the legacy public import
surface remains only for its explicit verifier/capture callers. The explicit
contract disposition and owner decision boundary are in
[Q1 contract disposition](plans/restructure_q1_contract_disposition_20261022.md).
Do not begin Q1-B/C/D/E or claim the existing foundation is generally
production-qualified.
