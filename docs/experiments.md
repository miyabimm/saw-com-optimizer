# Experiments, data preservation, and authorization

## Authorization and immutable conditions

An issue, roadmap stage, design document, test pass, or software work-unit
acceptance is not authorization to run COM/FE calculations, an optimizer study,
a production workload, a resume, or a new seed/budget/topology. State purpose,
inputs, COM profile, frequency specification, topology/variables/bounds,
geometry/area constraints, independent `Zs`/`Zl`, optimizer/version, seed,
budget, search and validation grids, resource policy, source SHA, raw output
path, and review evidence before execution. Obtain separate explicit owner
authorization for every scientific/production run and material change.

A finite budget yields a **best-found** design under those frozen conditions,
not a proof of a global optimum. Infeasible best-found results are valid outputs;
report constraints, violations, incomplete work, and convergence limits without
silently relaxing the model. Every sampled impedance point in a user-facing
map must have independent filter re-optimization and validation. A fixed-design
termination sweep is a diagnostic only.

Current gates: Q0 is `CLOSED / ACCEPTED`; Q1-A is `WORK_UNIT_READY / CLOSED`;
all Q1-01…Q1-23 gates remain unpassed; Q1-B/C/D/E are
`NOT AUTHORIZED / NOT STARTED`. Q1 permission, if separately granted, would
cover only deterministic synthetic software qualification and never COM,
physics, actual SAW optimization, or production. See the sole formal
[Q1 matrix](plans/stage5a2_q1_qualification_matrix.md) and
[Q0 closeout](history/stage5a2_q0_closeout_20261021.md).

## Historical raw data and provenance

Historical raw runs/checkpoints are not to be rewritten to a new schema,
moved, deleted, repaired, resumed, or used to silently recompute conclusions.
Keep each run's recorded execution-source SHA, frozen config/protocol, grid,
seed, and review reference. Git history and compact review reports do not
substitute for raw-data preservation.

R0 PR #57 records a read-only copy of 12 historical run trees and five related
manifests: 798 files / 9,996,102,874 bytes. Its external inventory-manifest
SHA-256 is
`d0bfc7189d0c8f35aa46875b4f7de4d64727ef6b570e2a157b8da900898d9c7d`.
The report verifies the copied destination contents, but its logical reference
is not itself the raw or a file-by-file manifest. **Physical/off-device
redundancy remains unverified**, and the scientific impact of one missing old
payload is unclassified; both remain open in [Issue #58](https://github.com/MasayaTakagi/saw-com-optimizer/issues/58).
Do not claim all historical evidence is independently recoverable or execute
an additional copy without owner authorization. R0 inventory uses privacy-safe
aliases and intentionally omits absolute paths.

The four principal historical source identities (where recorded) are:

| Evidence | Frozen execution/audit source SHA | Interpretation |
|---|---|---|
| Stage 4A qualification | Legacy records do not establish one common execution SHA. | Protocol/implementation qualification only; see R0 inventory and experiment register. |
| Stage 4B production | `c44798266067fa4b8b7d3b2873a798b7a1600ae8` | 20 completed cells; 0/20 feasible; no unique topology. |
| Stage 4C production | `65e1815db1cc18d74ff0dcee20ffd5e9098709df` | 10 completed cells; 0/10 feasible; immature, still improving; topology unresolved. |
| Stage 5A-1 read-only audit | `c0ab7cc5ad93569c1828f812cf90655e89c5cc8f` | Saved-evidence/cost audit only; no complete proposal replay or COM recalculation. |
| Q0 accepted protocol | PR #50 commit `9427b404d302932b27f50d31919bb3fb95fcfcd4` | Frozen 234-member initialization, 4,096 unique FE/arm, Q0 identity/RNG/replay and comparison rules; design acceptance, not software qualification. |
| Q1-A work unit | Reviewed source head `ba0d13f69a34422669fee9dd88819dfbab45d392`; PR #54 merge `03d673052c7570d86b78b43849f649758bb7d3f4`; tested source `03b9a5495111a1f933f542682f76b5ec9bad4e53`. | Work-unit `WORK_UNIT_READY`, not an official Q1 gate pass. |

Historical status and caveats are traceable here:

- **Stage 4A:** [experiment register — Stage 4A](history/experiment_register.md#stage-4a--hybrid-protocol-qualification)
  records the bounded protocol qualification and four 256-FE smoke cells;
  [R0 inventory §4](../reports/restructure/r0_preflight_inventory_20261022.md)
  points to the preserved qualification records and confirms no shared
  execution source SHA is established in legacy metadata.
- **Stage 4B:** [closeout](history/stage4b_closeout_20261004.md) and
  [production review package](../reports/stage4b_production_review/20261003_20261003_014817_ea08db/)
  record 20 completed matched cells, 0 feasible, and unresolved topology
  selection.
- **Stage 4C:** [current baseline](history/current_baseline.md),
  [production review package](../reports/experiment_reviews/stage4c/20261006_124153_ed50ba/),
  and [Stage 5A-1 audit closeout](history/stage5a1_closeout_20261020.md)
  record 10 completed cells, 0 feasible, immature/still improving; the saved
  audit checked 80 search finalist pools and 80 common-grid selection pools,
  not every proposal or an independent recalculation of all COM ranks.
- **R0 preservation:** [preflight inventory](../reports/restructure/r0_preflight_inventory_20261022.md)
  records the external-copy verification and its explicit limits.

Stage 4C remains `STAGE4C_TOPOLOGY_SELECTION_UNRESOLVED`; do not infer physical
infeasibility, convergence, or topology selection.

## R5 future raw-run storage contract (implemented; future-only)

PR #70 implements the future raw store and review package and verifies them with
synthetic fixtures. This does **not** authorize launching a run, COM/FE or
optimizer research/qualification, production work, checkpoint replay, migration,
or historical-data operation. Issue #71 separately authorizes only the R6
software/synthetic CLI integration using temporary fixtures. The target is an
explicitly configured absolute `SAWOPT_DATA_ROOT` outside all registered
worktrees and repository roots:

```text
$SAWOPT_DATA_ROOT/runs/<experiment_id>/<run_id>/
```

The software API is separate in `sawopt.io.experiment_store`; compact export is
`sawopt.reporting.experiment_review`. Issue #124 retired the separate legacy
schema-v1–v4 CLI/exporter; R5 is integrated only with the synthetic/injected R6
CLI slice, not a real research runner. The raw tree is unsafe against a
non-cooperating concurrent writer that changes
files during review export; do not claim concurrent-writer safety. A run caller
can register full cell outputs and logs under `cells/<cell_id>/`, `logs/`,
`arrays/`, `populations/`, `caches/`, and `replay/`; checkpoint lifecycle files
remain under `checkpoints/` and retain their existing schema. The review
exporter validates the external root read-only and streams hashes for raw files
it does not copy.

`experiment_id` is a lowercase hyphenated slug; `run_id` is a UTC timestamp
plus random lowercase hex suffix. Reject missing/empty/relative roots, malformed
IDs, unresolved or symlink/reparse path components, any worktree/repository
containment, collisions, insufficient permissions, and inadequate declared
free-space requirements. Run initialization requires a positive caller-declared
free-space estimate. Worktree-discovery uses the package repository's Git
inventory and cannot be overridden by the caller. Worktree-discovery or
path-trust uncertainty is a validation failure, not permission to fall back.
Create the run exclusively and race-aware; on initialization failure, leave no
partial manifest or misleading run. Preflight must not mutate a rejected
destination. If an artifact becomes visible but its manifest transaction fails,
retain the orphan and the prior successful artifacts unchanged; do not auto-delete
or repair it. Review export fails closed on the unregistered file/hash mismatch.
Treat that raw run as invalid evidence and preserve it for incident review; use a
new unique run ID for any separately authorized future work.

The new versioned raw manifest freezes experiment/run identity, immutable
execution source SHA (not a later PR HEAD), effective-config and model/search /
validation-grid SHA-256 identities, runtime/package and numerical-dispatch
identity, method/topology/seed/budget limits, distinct search and validation
counts, the exact expected cell roster and each cell's explicit state, creation
and finish times, raw-artifact hashes, checkpoint/recovery consistency, and
complete failure/error records. Method/topology summaries are derived from
the roster (using `MULTIPLE` for mixed designs), and each cell remains the
authoritative identity. Each expected cell exists from initialization; failed,
not-started, and incomplete work remains visible. A cell is successful only
when the caller records an observed success. Missing or nonfinite numeric
values use explicit null/status information; nonstandard JSON NaN/Infinity is
not permitted. Checkpoint schema and FE accounting remain unchanged.

Legacy `io.run_store.initialize`, the Stage-specific `external_persistent_v1`
manifests, and existing runners are not silently reinterpreted as this schema.
This contract creates no old-checkpoint reader and migrates no historical raw
run.

## R5 future GitHub review package (review schema v1)

Compact review evidence uses the same IDs at
`reports/experiments/<experiment_id>/<run_id>/`. The required package contains
exactly:

- `README.md`: purpose, conditions, observed findings, limitations, review
  instructions, and scientific disposition as a claim awaiting review.
- `manifest.json`: schema and exactly matching IDs, immutable execution source
  SHA, creation/finish times and run/cell statuses, runtime and numerical
  dispatch identity, method/topology/seeds/budget, full expected cell roster,
  config/model/search-grid/validation-grid hashes, raw artifact hashes, review
  artifact hashes (excluding the manifest's self-hash), completeness, and
  redaction status.
- `config.yaml`: exact effective frozen input with credentials and private
  absolute paths removed.
- `cells.json`: every planned cell, including failed/incomplete cells, with
  status/reason, design/geometry, search FE and proposal/failure accounting,
  metrics, feasibility/individual violations, and separate validation results.
- `convergence.csv`: only observed common-budget checkpoints; never forward-fill
  missing measurements.
- `checks.json`: expected/present cells, hash/config/source consistency,
  counters, redaction, and checks run/not run. Its frozen `comparison_required`
  declaration is true for paired-arm claims and false for explicitly non-paired
  screening; topology multiplicity alone does not imply a paired comparison.
  Required evidence presence is reported separately. The package must not claim
  `READY_FOR_REVIEW` unless required evidence, ID correlation, integrity,
  redaction, and size checks all pass.
- `comparison.csv` for paired comparisons; `validation.csv` when response
  claims require independent metric recomputation; optional `plots/`.
  These are the only optional top-level entries; the required package has no
  unlisted files.

Use explicit units, named columns, and explicit statuses/nulls for missing or
nonfinite values. Include enough response data to reproduce cited metrics when
required. Target ≤2 MiB per run; enforce a strict 10 MiB default hard cap after
all files are serialized. An exception requires separate explicit approval and
must not be met by deleting indispensable evidence. Do not commit full
checkpoints/populations/caches/raw arrays/full logs, secrets, or personal paths.
Sanitize allowlisted fields and paths, then scan the complete package as a
backstop; fail closed on secrets or user-specific paths. Verify raw and review
IDs and SHA-256 correlations before atomic publication; never overwrite an
existing package. A package-ready state is not scientific acceptance; stop at
`REVIEW_WAITING` for independent review. Raw deletion/archival requires a
separate lifecycle decision after review and closeout.

## Experiment review and lifecycle

For each future run, freeze implementation/source/config/protocol identity,
seed and budget, expected cells, common validation, external raw destination,
resource/abort policy, and review spec on GitHub before launch. Preserve all
cell states and explain non-comparable/missing data. Reviewer acceptance and
owner acceptance are distinct from numerical completion and package integrity.
Never automatically extend a budget, alter bounds, seed, constraints, or
specification, resume a closed/failed historical run, or start a follow-up run.
