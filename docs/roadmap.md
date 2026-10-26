# Product roadmap and current status

**Status:** Active product roadmap. Current status reviewed against the
2026-10-08 roadmap and the Q0/Q1/R0 records through 2026-10-22.

## Product goal

Build a reusable SAW filter design flow for user-provided COM parameters,
frequency-domain specifications, topology and design variables, geometry/area
limits, independent source/load impedances, and a finite computing budget.
Report the best-found constrained design, its feasibility and individual
violations, and convergence limitations. A finite search is not proof of a
global optimum; an infeasible best-found design is not proof of mathematical
infeasibility.

The long-term impedance deliverable is a Smith-chart heatmap of validated
performance from **independent filter re-optimization at each sampled source /
load impedance pair**. Sweeping terminations on one fixed design is an internal
diagnostic only. Complex passive ports require the separate numerical gate in
Stage 5C. B28 Rx at 50/50 ohm is a regression/diagnostic case, not the
universal product objective. DMS and DMS-plus-ladder hybrid structures remain
candidate topologies, not assumed winners.

The tool must accept hypothetical or measured COM inputs. Physical calibration,
material attribution, manufacturability certification, and device correlation
are not project gates. Numerical correctness, explicit units and conventions,
modeled-constraint consistency, and reproducibility are required.

**Current implementation boundary:** the repository contains reusable COM,
design, evaluation, and optimization components, but its supported design/run
path is synthetic/injected-only. The R5 `review export` subcommand only
postprocesses an existing closed raw run. The integrated configurable real-SAW
design and impedance-map workflow described above is not yet available. R5
storage/review software and synthetic task execution are software contracts,
not run authorization or scientific qualification.

Issue #157's [scientific configuration v1](scientific_config_v1.md) is a
**validation-only, single-filter seven-variable declaration subset**. It does
not accept Stage 5A hybrid `P_D`/`D_P` Q0 inputs, implement configured scientific
execution or establish Stage 5A readiness. Its source-Git `optimizer.version`
is not the Q0 semantic algorithm-package identity. Any integrated evaluator,
non-default fixed-design adapter or Q0 compatibility remains separate gated
work, not a consequence of schema validation.

## Historical baseline and limits

- Stage 4A qualified bounded hybrid implementation/protocol behavior, not a
  scientific topology ranking.
- Stage 4B completed 20/20 matched cells under its frozen protocol; none was
  feasible and no unique topology won. `P_D` and `D_P` were the practical
  shortlist, not a globally selected pair.
- Stage 4C completed 10/10 cells at 96,000 unique evaluations each with
  integrity PASS. `P_D` and `D_P` were both infeasible 0/5; all ten terminal
  cells were immature/still improving, and three had unresolved terminal
  `resonator_0_pairs` upper-bound hits. The outcome remains
  **`STAGE4C_TOPOLOGY_SELECTION_UNRESOLVED`**. Execution completion is not
  convergence or topology selection.
- The resonator-pair coordinate probe was diagnostic only: it found a mixed
  bound signal and did not authorize expanding bounds or running production.
- The cause of the 50/50-ohm shortfall remains unresolved. Plausible causes
  include optimizer/parameterization, finite search, bounds and geometry,
  topology/design degrees of freedom, and trade-offs under supplied COM
  parameters. Do not infer a primary cause without evidence.

See [current baseline](history/current_baseline.md),
[experiment register](history/experiment_register.md), and the Stage 4B/4C
closeouts for the detailed historical evidence and caveats.

## Active roadmap and exit gates

| Stage | Purpose and required evidence | Status / exit gate |
|---|---|---|
| **5A — Diagnose and simplify 50-ohm optimization** | Quantify generic high-dimensional optimizer quality/time; audit objective/network, accounting, constraints and geometry; diagnose design-space causes; assess classical SAW-guided starts without deleting the full-space fallback. | Active next stage. No new production run is authorized by this roadmap. |
| **5A-1 — Read-only audit** | Integrity, saved-candidate/comparator checks, dense-validation selection, limits, and measured cost envelope. | Closed 2026-10-20, evidence-limited. Does not establish convergence or an algorithm winner. |
| **5A-2 — Generic optimizer viability** | Controlled matched-budget and wall-clock quality comparison under frozen Q0 terms, only after the applicable Q1/experiment gates. | Q0 protocol `CLOSED / ACCEPTED`. Q1-A `WORK_UNIT_READY / CLOSED`. **All Q1-01…Q1-23 gates are unpassed; Q1-B/C/D/E are NOT AUTHORIZED / NOT STARTED.** No real 12-cell comparison is authorized. |
| **5A-3 — Constraint/design-space cause isolation** | Read-only boundary/correlation diagnosis first; any bound or constraint re-optimization requires separately reviewed authorization and controlled comparisons. | Not started. No bound/constraint change authorized. |
| **5A-4 — Classical SAW design guidance** | Document applicability and use as diversified initialization/reparameterization before considering reduced spaces. | Not started. |
| **5A-5 — Small controlled method comparison** | Compare generic baseline, same-space algorithm improvements, and justified SAW-guided methods with common validation, seeds, resource metrics, and explicit limits. | Not started; separate approval required before any study. |
| **5B — General-purpose design optimization** | User-configurable COM/spec/topology/ports/budget, mixed variables, constraints, diagnostics, and reproducible best-found outputs. | Future gate. |
| **5C — Complex source/load support** | Positive-real parity, passive complex-port power/reflection conventions, and analytic network checks. | Future gate; current evaluator is real-positive-only. |
| **5D — Impedance-wise re-optimization** | Independently search and validate at every sampled source/load pair with per-point design, violations, budget, seed, and status. | Future gate. |
| **5E — Re-optimized Smith heatmaps** | Named impedance slices; distinguish evaluated, interpolated, infeasible, incomplete, and insufficiently converged points. | Future gate. |
| **5F — Runtime/memory scaling** | Profile and show quality-preserving gains, reuse only where mathematically valid, and measure concurrency/resource effects. | Future gate. |
| **5G — Integrated design tool** | Reproducible model→design→impedance map→plot/export workflow within agreed resource limits. | Future gate. |

Completion is a best-found engineering deliverable with validated response and
transparent constraints, not a universal guarantee of feasibility or optimality.

## Interpretation and authorization

Every result is conditional on its exact COM input, specification, topology,
bounds/geometry, port references, search and validation grids, optimizer,
seed, budget, source identity, and numerical conventions. Preserve metric-by-
metric results and the declared feasibility-first ordering; do not silently
substitute a weighted objective, relax constraints, widen bounds, or upgrade a
finite search into a proof.

A roadmap stage, planning document, issue, software gate, or successful test is
not authorization for a new scientific COM/FE study, optimizer experiment,
production run, budget extension, or changed scientific condition. Existing
bounded fixed-input COM regression and deterministic optimizer unit/integration
tests are ordinary software verification, not scientific qualification. See
[experiments.md](experiments.md) for the approval boundary.
