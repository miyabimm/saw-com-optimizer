# Issue #155 — reusable config-driven scientific CLI design

**Status:** audit/design proposal only. This file defines no new scientific
contract, implementation permission, Q1 authorization, or experiment approval.
No executable Stage 5A config is added. The target flow is:

```text
sawopt validate --config <file>     # strict, non-executing resolution
sawopt run --config <file>          # future execution, only after separate gates
       validated model/design/evaluation/optimizer
       → R5 external raw store → sawopt review export
```

The current `sawopt run` remains the synthetic/injected-evaluator fixture
identified in [`architecture.md`](../architecture.md), not this future
scientific path. Stage 5A-2 Q0 conditions and the Q1 gate matrix remain
unchanged and authoritative for their scope.

## 1. Minimal reusable config contract (proposal)

Use one versioned, strict YAML schema for a scientific design request. Reject
unknown fields, missing required fields, implicit defaults that affect results,
nonfinite values, invalid units, and ambiguous topology/variable ordering. The
validated config resolves once into a detached effective-config snapshot and
stable input identities; every consuming layer uses that snapshot rather than
re-reading YAML or relying on process-global defaults.

| Section | Required meaning to freeze | Current gap / guard |
|---|---|---|
| `schema_version`, `experiment_id` | Exact schema identifier/version and R5-safe experiment slug. | The current strict schema is specifically synthetic. A schema version must not silently reinterpret historical YAML. |
| `model` | Provider/profile identity; complete user COM parameters or a pinned input reference with content hash; units, region/material identity, and explicit model assumptions. | `FixedProvider` and hypothetical/literature inputs exist; `CalibratedProvider` is unimplemented. No dynamic module/provider loading. A config identity is not physical calibration. |
| `design` | Named topology, ordered variable names, explicit units, active bounds and integer coordinates; geometry/area limits and any hard-bound identity. | Reuse current topology/decoder/geometry owners. Do not infer topology winners, alter bounds, or use a topology-specific hidden runner. Mixed-variable meaning must match the selected design space. |
| `specification` | Pass/stop bands and named metric limits with units and feasibility rules. | Reuse existing metric/constraint semantics unless a separately reviewed scientific decision changes them. No silent scalar objective or limit substitution. |
| `ports` | Independent source and load impedances, each with explicit units and supported-domain declaration. | Initial supported domain is positive real scalar ports. Complex/passive port support waits for Stage 5C; reject it rather than approximate it. |
| `grids` | Distinct search and independent validation grids, units, construction rules, and content identities. Report/plot grids are separate and never substitute for validation. | Current helpers exist, but no config resolution or CLI dispatch. Q0's frozen grid hashes/counts cannot be recomputed or replaced implicitly. |
| `optimizer` | Exact method/version, resolved method settings, unique-FE budget, proposal/watchdog policy, RNG/seed policy, and checkpoint/resume policy. | L-SHADE is reusable but not Q0-integrated; controlled DE and Q1-B/C are absent. Budget/accounting semantics are method-specific and must be frozen/reviewed, not guessed by the CLI. |
| `resources` | Worker/process/thread limits, memory/time ceilings, stop policy and environment identity required for reproducibility. | No parallelism/resource policy should be inferred from the host. Preserve R5 runtime provenance. |
| `storage` / `review_context` | R5 external data-root requirement, positive free-space estimate, exact expected-cell roster, purpose/conditions/limitations and review requirements. | No repository-local fallback. R5 review readiness is integrity only, not scientific acceptance. |

This is a schema outline, **not** a new accepted science format. Field names,
normalization, units, provider model, objective semantics, budget semantics and
config compatibility must be reviewed before implementation. It is not
necessary to expose every internal optimizer option: include only settings
with defined, tested behavior and identity. No live scientific YAML example
should be created before the owner approves the exact conditions and its
authorization status is unambiguous.

## 2. Intended dataflow and layer responsibilities

1. **Parse and validate.** `sawopt validate --config ...` reads only the
   explicit config, validates exact schema/version, units, ranges, file
   references and hashes, and prints a deterministic summary plus resolved
   identity hashes. It does not instantiate a physics provider, calculate a
   response, initialize an optimizer, create an R5 run, or write to a data
   root. It must not accept old Stage 3/4 configs through a legacy adapter.
2. **Resolve model/design.** Use current `design/` topology, variable decoding,
   bounds and geometry owners plus the selected existing COM provider. Resolve
   independent ports and the frozen specification/grids. Keep physics
   independent of optimizer, CLI, and run lifecycle. Fail closed for unsupported
   profiles, complex ports, or invalid constraints.
3. **Build one evaluation boundary.** Compose the canonical candidate decoder,
   `physics/` response, network conversion and `evaluation.measure` into one
   tested candidate evaluator returning the existing metrics, feasibility and
   individual violations. Search evaluation and dense/common-grid validation
   remain separate. `problem.evaluator.dense` currently handles a fixed design
   and adaptive/cache/counter work; it is not by itself an optimizer callback or
   finalist-validation coordinator. Reuse/extend shared owners only when needed;
   do not create a parallel evaluator implementation.
4. **Run the selected reusable optimizer.** Inject the candidate evaluator into
   a supported optimizer and use shared selection, unique-FE accounting, cache,
   and checkpoint services. The CLI must not replace the comparator, silently
   charge validation to search, dispatch beyond the frozen unique-FE budget, or
   claim convergence/global optimality. Every cell/result/status remains
   visible, including failures and incomplete work.
5. **Persist before execution.** After config resolution and source/environment
   preflight, create a new R5 raw run under
   `$SAWOPT_DATA_ROOT/runs/<experiment_id>/<run_id>/`, registering the full
   roster, immutable execution source SHA, exact effective config and input
   hashes before evaluation. Record observed search FEs separately from
   validation points. Keep checkpoints, replay, arrays, populations, caches,
   and logs outside Git. Do not overwrite, repair, migrate, resume, or clean up
   historical raw runs.
6. **Review export only after close.** Reuse the existing
   `sawopt review export` path to publish the R5 compact package at
   `reports/experiments/<experiment_id>/<run_id>/`. Preserve its exact-file,
   hash, redaction, status and size checks. Do not equate `READY_FOR_REVIEW`
   with a feasible design, numerical validity, or scientific acceptance.

R5 schema v1 currently hashes the effective config and exactly three named
scientific inputs (`model`, `search_grid`, `validation_grid`), plus the expected
cell roster and registered artifacts. The future resolver must ensure the
complete topology, bounds, ports, constraints, seed, optimizer and resource
conditions are in the exact effective-config identity. If a required review
field cannot be represented, stop and propose a separately versioned R5 change;
do not alter or migrate v1 in place.

## 3. Placement, naming, and artifact lifecycle

- `configs/examples/`: documented examples only; clearly label synthetic
  fixtures versus future schema examples. Keep the current
  `r6_synthetic_smoke.yaml` as a synthetic-only example.
- `configs/experiments/stage5a/`: proposed location for future version-controlled
  approved Stage 5A experiment inputs. **Do not create this directory/config
  as an executable study request until separately approved.** A checked-in
  config is never run authorization.
- `$SAWOPT_DATA_ROOT/runs/<experiment_id>/<run_id>/`: external R5 raw manifest,
  config/input snapshots, checkpoints, replay, arrays, populations, caches and
  logs. Use R5 IDs and exclusive creation. No raw/intermediate artifacts in a
  worktree.
- `reports/experiments/<experiment_id>/<run_id>/`: compact package from the
  existing review exporter; no hand-built duplicate report or legacy export
  path.
- `tests/`: focused deterministic pytest coverage over shared APIs and
  test-owned fixtures. Do not introduce ad hoc experiment scripts or a
  Stage 5A-only runner.

After independent review and scientific closeout, raw retention/deletion or
archival is a separate lifecycle decision. Never move or rewrite historical
configs, checkpoints, source identities, raw runs, or reports as part of this
work.

## 4. Acceptance criteria for a future implementation (not authorized here)

A successor implementation proposal should be reviewable against these
criteria before any real execution capability is merged:

- The strict schema resolves the same config bytes to the same canonical
  effective identity; unknown/missing values and unsupported units fail closed.
- `validate` is proven non-executing in a fresh process: no COM/provider/network
  calls, optimizer construction, evaluator calls, data-root writes or raw-run
  creation. Static import safety and output/error behavior have focused tests.
- There is one shared, dependency-injected evaluator boundary from validated
  design through physics/network/metrics to optimizer records. Existing
  comparator, individual constraints and named units are retained.
- Search FE, proposal, duplicate/cache, modeled-failure, infrastructure and
  independent validation counts reconcile exactly to tested budgets and raw
  records. Budget/checkpoint/RNG semantics are not changed by a generic CLI
  refactor.
- Every planned cell is recorded, and complete, failed, not-started and
  incomplete statuses remain visible in R5/review outputs. Frozen input,
  source, environment, grid, roster, checkpoint and artifact hashes correlate.
- Raw creation requires an explicit external root and positive free-space
  declaration; all intermediates stay external; review export is the existing
  postprocessor. No legacy manifest reader, automatic migration, hidden resume
  route, old alias, one-off script, or stage-specific dispatcher is introduced.
- Tests separate deterministic software contracts from scientific evaluation.
  Any real COM/FE, optimizer qualification, changed comparison condition, or
  production run remains separately gated and is not inferred from a schema,
  unit test, issue, or successful export.

## 5. Test and scientific-parity plan

### Software checks (future implementation PRs)

- Strict schema positive/negative cases, units and identity/hash stability;
  prove no implicit defaults or legacy config conversion.
- Fresh-process import/call guards for `validate`; assert no physics, provider,
  optimizer, R5 or filesystem-run side effects.
- Injected deterministic evaluator tests for candidate decoding, constraint
  records, cache/duplicate accounting, exact FE ceilings, failure classification,
  separate validation, checkpoint/raw manifest reconciliation and review export.
- Shared API tests for each supported design-space/topology and optimizer
  package. Q1-A foundation tests do not substitute for Q1-B/C/D/E gates.
- R5 contract tests with temporary external roots only. No actual study data or
  real persistent root in tests.

### Numerical parity (a separate future issue and authorization)

After an integrated evaluator exists, a separate, reviewed parity work unit
must freeze source/config/environment, chosen designs, inputs, grids, ports,
metrics and justified comparison tolerances before it runs. Compare at minimum:

- decoded/canonical candidate vectors and keys;
- COM admittance and network response arrays on identical search and validation
  grids;
- each metric, constraint, feasibility flag, violation and comparator rank;
- independent finalist/common-grid results and exact FE/validation accounting;
- response/grid/model/input hashes and failure behavior.

Use retained analytic regressions and the explicitly bounded Stage 5A-1 parity
records as references, not as proof for untested inputs. Establish each tolerance
before comparing; require exact bytes where canonical identity/order is the
contract. This is numerical software qualification, not physical calibration,
optimizer convergence evidence or a real SAW study. Because it may call COM/FE
or evaluate optimizer candidates, obtain the required separate explicit owner
authorization before running it. Do not run any of these checks under Issue
#155.

## 6. Proposed successor issues (not created or authorized by this document)

1. **Config schema and validate-only resolver.** Agree and implement the
   versioned generic schema, typed resolved snapshot and side-effect-free
   `validate` behavior. Software fixtures only; no scientific evaluator,
   optimizer, R5 run creation, COM/FE, or experiment config. Owner approval is
   required before issue creation/implementation.
2. **Shared configured evaluation/optimizer-to-R5 integration.** After the
   schema is accepted, design one reusable injected evaluator/optimizer path,
   constrained-result handling, search/validation accounting, checkpoint and
   R5 registration. Begin with deterministic software fixtures. Any new
   runnable scientific capability needs separate review and explicit owner
   approval; its tests do not authorize a run.
3. **Numerical parity qualification.** Open separately after implementation
   review, with a frozen parity matrix and predeclared tolerances. Get explicit
   authorization before any COM/FE or optimizer-candidate calculation; do not
   combine it with an optimizer study or production launch.

Q1-B/C/D/E remain `NOT AUTHORIZED / NOT STARTED`, all Q1-01…Q1-23 gates remain
unpassed, and the Stage 5A-2 comparison is not authorized. No successor issue,
architecture proposal, test pass, or Draft PR changes those states.
