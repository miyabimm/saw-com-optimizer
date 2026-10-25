# M0 — dependency, caller, and module-independence audit

**Tracking:** [Issue #146](https://github.com/miyabimm/saw-com-optimizer/issues/146), the bounded first work order under [Issue #145](https://github.com/miyabimm/saw-com-optimizer/issues/145).

**Disposition:** `M0_DOCS_STATIC_ONLY / DECISION_PROPOSAL / M1–M4_IMPLEMENTATION_NOT_AUTHORIZED`.

**Source baseline:** `main` at `4a672c7e345c0e0006a0410a861a5b0c339d0b80` (PR #144 merge). The source worktree was created from this exact SHA on a new branch; no existing worktree was switched, removed, pruned, cleaned, or inspected for ignored data. GitHub reported zero open PRs at preflight. PRs #132, #133, #135, #136, #138, #140, and #144 are ancestors of the baseline; these include R6-L1–L4 and reuse-first M1/M2/M5. Reuse-first M3 issue #141 is a closed read-only audit (not a source-removal PR); #142 remains open/deferred; #143 is the closed code-retirement work item implemented by PR #144. The exact-head `test` Actions check completed successfully; see validation below.

This is a repository-local static inventory, not a claim that static absence proves runtime or external absence. No source, test, config, script, tool, CI, scientific input, historical evidence, external raw data, checkpoint, or existing worktree was changed. No project test, worker, COM/FE calculation, optimizer study, real Pi/RPC operation, or publication was run.

## 1. Exact-base inventory and assurance evidence

Counts are reproducible from `git ls-files` at the baseline. `*.py` and `test_*.py` counts are distinct; directory counts include all tracked file types.

| Tracked inventory | Count | Counting rule |
|---|---:|---|
| `src/sawopt/**/*.py` | 53 | Tracked Python source beneath `src/sawopt/` |
| `tests/**/*.py` | 45 | Includes test helpers and package initializers |
| Test modules | 35 | `tests/**/test_*.py` |
| `configs/` | 15 | All tracked files beneath `configs/` |
| `scripts/` | 5 | All tracked files beneath `scripts/` |
| `tools/` | 5 | All tracked files beneath `tools/` |
| `.github/workflows/` | 1 | `ci.yml` |
| `docs/` | 83 | Includes historical plans, handoffs, guides, and records |
| Current authoritative docs | 5 | Roadmap, architecture, physics, development, experiments; `docs/README.md` is their index |
| Other tracked source-layout docs | 2 | `src/README.md`, `tests/README.md` (not in the active docs index) |

`pyproject.toml` declares Python `>=3.12,<3.13`, setuptools package discovery under `src`, and exactly one console entrypoint: `sawopt = sawopt.cli:main`. Runtime dependencies are NumPy, SciPy, Matplotlib, and PyYAML; the `test` extra is pytest and the `benchmark` extra is threadpoolctl. The tracked lock and Python-version files are `uv.lock` and `.python-version`.

The single `.github/workflows/ci.yml` job runs on Ubuntu 24.04 for pushes to `main`/`master` and pull requests. It installs locked test and benchmark extras, runs `tools/diagnostics/evaluation_repro.py`, then runs the full pytest suite; only pytest sets `OPENBLAS_CORETYPE=Haswell`.

**Exact-base remote evidence:** the GitHub Actions `test` check on `4a672c7e345c0e0006a0410a861a5b0c339d0b80` concluded `success` ([run #40186212121](https://github.com/miyabimm/saw-com-optimizer/actions/runs/40186212121/job/121147429666)). Its log reports **360 passed, 0 skipped**. This is prior CI evidence at the exact source SHA, not a test run performed for M0 and not an assurance-equivalence claim. The workflow check succeeds, but branch-protection/required-check enforcement was not established by this audit. The earlier L4 total of 459 tests was measured at `cf426e8`, and is not the current baseline.

## 2. Supported entrypoints and observable routes

`pyproject.toml` exposes `sawopt`; the equivalent public module invocation is `python -m sawopt.cli`. There is no `python -m sawopt` dispatcher, no old `export-review` alias, and no real-SAW/COM/FE execution command.

| Route | Current behavior and concrete caller evidence |
|---|---|
| `sawopt validate --config …` | Validates the strict synthetic YAML contract without running work. `configs/examples/r6_synthetic_smoke.yaml` is the supported example. `io.cli_config` owns validation; `tests/integration/test_synthetic_cli.py` checks it. |
| `sawopt run --config … [--data-root …]` | Runs one explicitly configured synthetic/injected-evaluator software slice through L-SHADE, the future-only R5 raw store, and local review export. The synthetic metric is not `evaluation.py`/COM evaluation. Normal CLI use requires a clean committed source identity. It is not research, qualification, or production authorization. |
| `sawopt review export --run …` | Postprocesses an existing closed `sawopt.raw_run/1` directory into the local canonical R5 review-package location. `reporting.experiment_review` validates and hashes raw evidence; this route does not run the optimizer or start a worker. `READY_FOR_REVIEW` is an integrity/evidence state, not scientific acceptance. |
| `sawopt synthetic-task launch/status/attach/resume/stop` | An explicit private-root, bounded countdown fixture on Linux/WSL2. `status` and `attach` are observational; `stop` is cooperative; `resume` requires a verified-dead exact predecessor attempt. It is not scientific task or optimizer resume. |
| `python -m sawopt.synthetic_worker` | Internal subprocess target only. The CLI starts it with a fixed argv, `shell=False`, detached session, and redirected standard streams. `tests/integration/test_synthetic_task_worker.py` and `tests/unit/test_synthetic_task_cli.py` cover the boundary. |

The CLI's synthetic-task SQLite ledger/attempt lineage, scientific optimizer checkpoints/RNG/FE accounting, and R5 raw/review evidence are three distinct contracts. The N1 test-owned synthetic recovery composition (`tests/unit/test_n1_synthetic_recovery.py`) exercises optimizer/R5 transaction behavior but does not turn the countdown worker into a science worker. No current CLI route publishes to GitHub or invokes a Pi provider/RPC session.

The remaining YAML/reference files under `configs/` are fixed numerical, DMS-reference, or Q1-A identity inputs. `configs/README.md` and current experiment policy state they are not study launch contracts; their presence authorizes no execution.

## 3. Method and static import/caller map

The audit enumerated tracked source paths and parsed the Python source imports with `ast`: `import`, `from` imports, absolute and relative imports, and statically named `importlib.import_module` / `__import__` calls. A separate targeted search looked for function-local imports, subprocess construction, CLI/module names, config dispatch, script invocations, tests, and reference-fixture/test-only callers. The scan does not treat a missing import as proof of dead code.

### Current static cross-package DAG

```text
cli               → io, optimization, reporting
optimization      → design, evaluation, io
evaluation        → design, physics
problem           → evaluation, optimization, physics
studies           → design, physics, reporting
reporting         → io
synthetic_worker  → io

physics.elements  → physics.com       (within-package module edge)
```

Package-internal imports, third-party dependencies, and standard-library imports are omitted. The CLI's optimizer/store/review imports are in function scope and therefore remain deferred until the relevant command path is called. `SyntheticTaskLedger` also lazily selects the schema-v2 `SyntheticTaskRecoveryLedger` for v2 roots; schema-v1 remains on the v1 implementation. This is explicit local dispatch, not a plugin registry.

No dynamic Python module-import call was found in `src/sawopt/` by the AST scan. There is no discovered entry-point registry or general plugin loader. Other concrete dynamic/external boundaries are:

- `cli.py` constructs the synthetic-worker command as `sys.executable -m sawopt.synthetic_worker` and starts it with `subprocess.Popen(..., shell=False)`.
- `io.experiment_store._discover_worktree_roots` invokes `git worktree list --porcelain -z` to validate an external raw-data root against repository/worktree containment. This is an R5 path-trust check, not a worktree lifecycle tool; Issue #143 removed the standalone worktree safety utility.
- `runtime.parallel` may query Windows processor metadata through a fixed PowerShell expression; it does not dispatch application work.
- DMS helper material/topology selection uses explicit branches; the synthetic YAML loader validates a fixed schema and the synthetic CLI selects L-SHADE. No general config-to-scientific-study dispatch remains.
- Test-only dynamic import coverage includes the physics import-boundary test importing four named physics modules. Historical plans may mention retired module names, but they are archival evidence and not current callers.

### Required current exceptions and retained edges

- **`problem.evaluator.dense` → `optimization.adaptive_frequency` / `optimization.cache`:** `dense` is a documented deferred adaptive-grid/cache/counter evaluation boundary. It calls the response evaluator, refines frequencies, uses `IncrementalFrequencyCache`, and returns metrics/network/simulation. The current CLI does not dispatch it. `tests/unit/optimization/test_adaptive_search.py::test_incremental_dense_evaluation_matches_full_metrics` compares its incremental result with full-grid metrics. Keep the boundary unchanged in M0; absence of a current production caller is not deletion evidence.
- **`studies.dms_topology_common` → `reporting.material_metadata`:** a narrow M0/MLIT provenance/display helper, separate from the R5 exporter. It records the selected material profile used by retained DMS reference/provider helpers. Evidence: `tests/unit/reporting/test_material_metadata.py` and `tests/unit/problem/test_dms_topologies.py`. Do not remove this edge just to satisfy a simplified drawing.
- **`optimization.checkpoint_session` → `io.checkpoints` / `io.lifecycle`:** the current scientific checkpoint-session owns backend checkpoint state while IO owns durable storage/finalization; the narrow dependency is explicitly allowed by #145. Preserve exact checkpoint schema, RNG/replay, counters, and fail-closed behavior.
- **Q1-A and DMS parity:** `studies.stage5a2` is a retained identity/RNG/journal/initialization software foundation and imports canonicalization from `design`; `studies.dms_topology_common` is retained reference/grid/provider/initial-design code. Neither is a current historical study executor. Q1-A remains `WORK_UNIT_READY / CLOSED`; none of Q1-01…Q1-23 passed, and Q1-B/C/D/E remain unauthorized/not started.
- **`problem.released_dms`:** an independent released-geometry/port-wiring reference for parity against generalized T0. `tests/unit/problem/test_dms_topologies.py` compares geometry and admittance (`rtol=1e-10`, `atol=1e-12`). It is preserved scientific evidence, not an obsolete runner.

## 4. File/function responsibility and disposition matrix

Dispositions are exact M0 recommendations, not deletion authorization. A `NEEDS_OWNER_DECISION` row means “retain pending a separately scoped decision,” not “delete.” Git rollback is available for any future reviewed source PR; it does not substitute for preserving historical or scientific evidence. Every test path below identifies checked-in evidence, not a test run in this audit. For every row, the target logical owner remains the current path owner unless an exception is named: physics/design/evaluation/optimization/problem and retained DMS/Q1-A references → Scientific Core; optimizer checkpoint storage/lifecycle → the explicitly allowed Core IO seam; CLI config, task ledger/recovery, CLI and worker → Execution Harness; R5 `experiment_store` plus the review exporter/metadata → Experiment Data & Review. Runtime helpers remain supporting runtime behavior under Harness unless a separate contract decision says otherwise. No source move is proposed.

### Package roots, CLI, and design/evaluation

| Concrete path / symbol | Current owner, caller, and behavior/test evidence | M0 disposition; risk if changed |
|---|---|---|
| `src/sawopt/__init__.py` | `sawopt` package root for both console/module paths; no scientific initialization is assigned here. | **KEEP_CURRENT** — removal/exports could affect import/package discovery; no simplification shown. |
| `src/sawopt/cli.py::{build_parser,main,run_experiment}` | Public console entrypoint and `python -m sawopt.cli`; imports strict config directly and loads optimizer/store/review by operation. See `pyproject.toml`, `tests/integration/test_synthetic_cli.py`, `tests/integration/test_review_export_cli.py`, `tests/unit/test_synthetic_task_cli.py`. | **KEEP_CURRENT** — changes could alter documented routes, source identity, or trigger execution. |
| `src/sawopt/synthetic_worker.py::main` | Exact internal countdown child invoked by CLI; claims/fences one ledger attempt and records bounded progress. See `tests/integration/test_synthetic_task_worker.py`, `tests/unit/io/test_synthetic_task_resume.py`. | **KEEP_CURRENT** — argv/path is also part of process identity/source hashing; do not move or re-name absent an independently reviewed contract. |
| `src/sawopt/design/__init__.py` | Design package initializer; no separate execution route. | **KEEP_CURRENT** — no deletion or relocation benefit established. |
| `src/sawopt/design/canonicalization.py` | Canonical design-vector leaf consumed by `studies.stage5a2.initialization`; Q1-A 92-case golden and pure-leaf import checks are in `tests/unit/studies/test_stage5a2_foundation.py`, `scripts/check_stage5a2_pure_leaf_import.py`, and `scripts/verify_stage5a2_canonicalization_golden.py`. | **KEEP_CURRENT** — identity/key changes can invalidate replay and golden parity. |
| `src/sawopt/design/geometry.py` | Pure geometry owner consumed by `evaluation.py` and `optimization.polish`; covered by `tests/unit/design/` and `tests/unit/test_evaluation_contracts.py`. | **KEEP_CURRENT** — geometry/constraint semantics are scientific contract. |
| `src/sawopt/design/space.py` | `FilterDesign`, bounds, variable decoder/canonical space; consumed by evaluation and retained DMS/Q1-A helpers. Covered by design tests and Stage 5A-2 golden checks. | **KEEP_CURRENT** — decoding/canonical keys and exact design identity are contract-sensitive. |
| `src/sawopt/design/topology.py` | Topology/design-section representation and T0/T1/T2 decode used by evaluation and DMS reference helpers. Evidence: design tests and `tests/unit/problem/test_dms_topologies.py`. | **KEEP_CURRENT** — topology and section geometry change physics input identity. |
| `src/sawopt/evaluation.py` | Response/network/metric/constraint bridge from design to physics; used by `problem.evaluator` and current regression tests, not by the injected CLI response metric. Evidence: `tests/unit/evaluation/`, `tests/unit/test_evaluation_contracts.py`. | **KEEP_CURRENT** — units, metric grids, constraints, and feasibility meaning must not be altered by modularization. |

### Physics and reusable optimizer components

| Concrete path / symbol | Current owner, caller, and behavior/test evidence | M0 disposition; risk if changed |
|---|---|---|
| `src/sawopt/physics/__init__.py` | Physics package root; direct import checks enumerate current physics modules. | **KEEP_CURRENT** — preserves reusable module package identity. |
| `src/sawopt/physics/com.py` | COM section equations/providers and filter simulation; consumed by `evaluation.py`, DMS reference helpers, and standalone numerical tests. See `docs/physics.md`, `tests/unit/core/test_physics.py`, `test_reference.py`, and `tests/unit/physics/`. | **KEEP_CURRENT** — equation, sign, units, and numerical identities are high risk. |
| `src/sawopt/physics/elements.py` | Acoustic/electrical section elements; its concrete module edge is `elements → com`; composition tests and full COM reference tests exercise it. | **KEEP_CURRENT** — P-matrix/network parity is scientific core. |
| `src/sawopt/physics/literature_com.py` | Evaluation-only normalized literature material profile/provider; called by DMS common helpers and tests. See `tests/unit/core/test_literature_com.py`, `test_material_profiles.py`. | **KEEP_SCIENTIFIC_EVIDENCE** — profile/provenance semantics must remain intact. |
| `src/sawopt/physics/network.py` | Real-positive-port network, S-parameter and power/reflection calculations used by evaluation; see `docs/physics.md` and `tests/unit/physics/test_topology_evaluation.py`, core/evaluation regressions. | **KEEP_CURRENT** — power-wave and network conventions are scientific contract. |
| `src/sawopt/optimization/__init__.py` | Unified optimizer package root after R4; no second `optimizers/` owner exists. | **KEEP_CURRENT** — avoid compatibility packages or duplicate strategy owners. |
| `src/sawopt/optimization/accounting.py::validate_checkpoint_lattice` | Validates checkpoint/evaluation counter lattices; its only current in-repo caller found is `tests/unit/optimization/test_accounting.py`; no source runtime caller was found. | **NEEDS_OWNER_DECISION** for this validator’s ongoing owner/use, not delete. Removing it loses a tested accounting contract; a moved/replaced use must preserve exact counts. |
| `src/sawopt/optimization/adaptive_frequency.py` | Refinement helpers are imported by `problem.evaluator.dense`; adaptive search tests exercise frequency refinement. Other helpers (`common_validation_grid`, `adaptive_exchange`, `adaptive_settings`) have test/reference callers but no general dispatch registry. | **KEEP_CURRENT** — preserve exact search-vs-validation grid separation and deferred evaluator behavior. |
| `src/sawopt/optimization/base.py` | `OptimizerBackend` protocol and backend naming support L-SHADE/DE implementations; covered by optimizer tests and `tests/unit/test_architecture.py`. | **KEEP_CURRENT** — strategy interface contract; no alternate backend framework needed. |
| `src/sawopt/optimization/budget.py::{adaptive_budget_limits,PlateauStopper}` | Finite/adaptive budget and plateau rules; tested by `tests/unit/optimization/test_adaptive_search.py`, with no current production source caller found. | **NEEDS_OWNER_DECISION** on whether these test-pinned standalone policies remain supported. Do not alter budget semantics or delete based on call-graph absence. |
| `src/sawopt/optimization/cache.py::IncrementalFrequencyCache` | Imported by `problem.evaluator.dense`; tested by adaptive-search parity. | **KEEP_CURRENT** — cache key/count behavior affects scientific evaluation accounting. |
| `src/sawopt/optimization/checkpoint_session.py::LShadeCheckpointSession` | Optimizer-owned adapter over `io.checkpoints` and `RunDisposition`; used in checkpoint and N1 synthetic recovery tests. | **KEEP_CURRENT** — exact rolling state/RNG/replay must remain independent of countdown resume. |
| `src/sawopt/optimization/convergence_evidence.py::{derive_checkpoint_evidence,apply_checkpoint_evidence}` | Pure checkpoint evidence interpretation; currently test-only caller `tests/unit/optimization/test_convergence_evidence.py`; no current runtime source caller found. | **NEEDS_OWNER_DECISION** on current product ownership. Do not delete its regression evidence or infer study execution from its existence. |
| `src/sawopt/optimization/counters.py::{EvaluationCounters,GeometryGateCounters}` | Evaluation/accounting counters used by the response/evaluation path; exercised by optimization/evaluation tests. | **KEEP_CURRENT** — search, validation, geometry-gate, and FE counts are distinct contract data. |
| `src/sawopt/optimization/lshade.py::LShadeBackend` | Current synthetic CLI strategy and retained general backend; checkpoint/state tests exercise deterministic resume and unique-FE behavior. `FixedDEReferenceBackend` is also defined here as a reference subclass. | **KEEP_CURRENT** — preserve RNG, unique-FE budget, cache, checkpoint, and candidate identity behavior. |
| `src/sawopt/optimization/polish.py::{mixed_variable_polish,powell_continuous_polish}` | `mixed_variable_polish` has focused optimizer tests; no in-tree production source caller was found. `powell_continuous_polish` has no in-tree caller found. | **NEEDS_OWNER_DECISION** for the no-runtime-caller polish functions. Keep the tested contract pending scoped owner review; never silently alter comparison fairness or FE accounting. |
| `src/sawopt/optimization/population.py::{scaled_population,independent_uniform_candidate,sample_independent_uniform_population}` | `scaled_population` is directly tested in `tests/unit/optimization/test_search_primitives.py`; no in-tree source caller was found for the independent-uniform helpers. | **NEEDS_OWNER_DECISION** for the two uncalled public helpers. Retain the tested scaling contract and do not change Q0 initialization/replay. |
| `src/sawopt/optimization/scipy_de.py::ScipyDELegacyBackend` | A separate SciPy DE implementation; no in-tree runtime/test caller was found beyond `tests/unit/test_architecture.py` asserting the file exists. Current architecture describes the optimizer owner as including L-SHADE/SciPy-DE, but no current CLI dispatches this backend. | **NEEDS_OWNER_DECISION** before retirement or move; it may be a comparison/reference strategy. Do not infer that implementation is dead merely from no current dispatch. |
| `src/sawopt/optimization/selection.py::{FeasibilityFirstComparator,GeometryFirstComparator}` | Sole candidate comparator after R4; used by L-SHADE/polish and pinned by `tests/unit/optimization/test_selection.py`. | **KEEP_CURRENT** — ranking/order is explicitly frozen and scientific. |

### IO, problem/evaluation references, reporting, runtime, and studies

| Concrete path / symbol | Current owner, caller, and behavior/test evidence | M0 disposition; risk if changed |
|---|---|---|
| `src/sawopt/io/__init__.py` | Package-level R5 API surface consumed by review/export code. | **KEEP_CURRENT** — no duplicate raw-store owner or compatibility facade. |
| `src/sawopt/io/checkpoints.py::CheckpointStore` | Optimizer checkpoint persistence, validation, rolling/latest/previous/final rotation, and finalization. Used by `optimization.checkpoint_session` and the R5 run-bound wrapper. See `tests/unit/io/test_checkpoints.py`, `test_n1_synthetic_recovery.py`. | **KEEP_CURRENT** — scientific checkpoint schema and failure retention are high-risk contracts. |
| `src/sawopt/io/cli_config.py::{load_synthetic_config,validate_synthetic_config}` | Strict current synthetic CLI configuration; called by `cli.py`; tested by `tests/integration/test_synthetic_cli.py`. | **KEEP_CURRENT** — no historical study YAML loader or COM configuration dispatch. |
| `src/sawopt/io/experiment_store.py::{validate_data_root,create_experiment_run,ExperimentRun}` | Future-only R5 raw-run schema, path containment, immutable identities, cell roster, artifact hashes, and run-bound checkpoints. Called by synthetic run/test fixtures and read by the R5 exporter. Tests: `tests/unit/io/test_experiment_store.py`, `tests/integration/test_review_export_cli.py`. | **KEEP_CURRENT** — preserve schema v1, hashes, no-overwrite, redaction boundary, and fail-closed path checks; never migrate historical raw. |
| `src/sawopt/io/lifecycle.py::RunDisposition` | Imported by `io.checkpoints` and optimizer checkpoint session; lifecycle tests pin completion/review/failed/unknown behavior. Its module docstring still mentions retired study/orchestration callers; no such current package exists. | **KEEP_CURRENT** for symbol. A future source-comment correction is a documentation-only cleanup candidate; deleting the enum would break finalization behavior. |
| `src/sawopt/io/provenance.py::{build_fingerprint_metadata,read_fingerprint_metadata,computation_gate_matches}` | Fingerprint API with `tests/unit/io/test_provenance.py`; no current `src/sawopt` runtime caller found. Historical plans mention its retired legacy use, which is not a current caller. | **NEEDS_OWNER_DECISION** on retaining this tested, externally importable API; do not delete or rewrite it in M0. |
| `src/sawopt/io/synthetic_task_ledger.py::SyntheticTaskLedger` | SQLite ledger, strict root/identity validation, v1 routing, and explicit API facade; called by CLI and worker. | **KEEP_CURRENT** — idempotency, process fencing, and fail-closed recovery are safety contracts. |
| `src/sawopt/io/synthetic_task_recovery.py::SyntheticTaskRecoveryLedger` | Lazily loaded v2 countdown attempt lineage, source/runtime identity and verified-dead recovery; tests in `tests/unit/io/test_synthetic_task_resume.py` and integration worker tests. | **KEEP_CURRENT** — countdown-only recovery; not scientific optimizer resume. |
| `src/sawopt/problem/__init__.py` | Package root for retained evaluator and parity reference. | **KEEP_CURRENT** — no redundant alias or compatibility API identified. |
| `src/sawopt/problem/evaluator.py::dense` | Deferred adaptive/cache/counter response evaluator; exact caller/test and boundary described above. | **KEEP_CURRENT** — retain even without CLI dispatch; changing it affects grid, response and count semantics. |
| `src/sawopt/problem/released_dms.py::{ReleasedFilterDesign,simulate_released_filter}` | Independent DMS numerical/geometry parity reference. Caller: `tests/unit/problem/test_dms_topologies.py`. | **KEEP_SCIENTIFIC_EVIDENCE** — do not replace with implementation-under-test or delete its independent check. |
| `src/sawopt/reporting/__init__.py` | Reporting package initializer; R5 exporter is a current owner. | **KEEP_CURRENT** — no wrapper or second publisher needed. |
| `src/sawopt/reporting/experiment_review.py::export_review_package` | Local R5 closed-run verifier/exporter, called by CLI and R5 integration/unit fixtures; no GitHub publishing. | **KEEP_CURRENT** — exact schema, source/raw hashes, status, redaction, size, and no-overwrite contracts. |
| `src/sawopt/reporting/material_metadata.py::material_profile_metadata` | Narrow profile provenance/display helper called by DMS common helper and direct metadata tests. | **KEEP_CURRENT** — preserve M0/MLIT provenance distinction; not an R5 review helper. |
| `src/sawopt/runtime/__init__.py` | Exposes the tested thread-environment helper. | **KEEP_CURRENT** — package still owns this runtime-level behavior. |
| `src/sawopt/runtime/parallel.py::single_blas_thread_environment` | Tested environment override/restoration in `tests/unit/runtime/test_parallel.py`. Same file defines `local_runtime_metadata`, for which no in-tree caller was found. | **KEEP_CURRENT** for tested helper; **NEEDS_OWNER_DECISION** for `local_runtime_metadata` only. Do not remove the whole module based on one symbol’s missing caller. |
| `src/sawopt/studies/__init__.py` | Package root for retained DMS reference and Q1-A foundation. | **KEEP_CURRENT** — not a restored study executor. |
| `src/sawopt/studies/dms_topology_common.py::{load_common_validation_grid,decode_design,provider_for_material,initial_design}` | Retained reference grid/provider/decoder/initial-design utilities; imports design/physics and metadata helper. Called from `tests/unit/problem/test_dms_topologies.py` with frozen reference fixtures. | **KEEP_SCIENTIFIC_EVIDENCE** — grid identity, MLIT/M0 source attribution, and parity are regression inputs, not authorization to run a study. |
| `src/sawopt/studies/stage5a2/__init__.py` | Q1-A package root. | **KEEP_CURRENT** — software work-unit foundation only; no Q1 gate passed. |
| `src/sawopt/studies/stage5a2/codec.py::{encode_typed,decode_typed,canonical_json_bytes}` | Deterministic typed serialization used by Q1-A identity/journal contracts; `tests/unit/studies/test_stage5a2_foundation.py`. | **KEEP_CURRENT** — canonical bytes/digests and replay identity are exact contracts. |
| `src/sawopt/studies/stage5a2/identity.py::{PairIdentity,CellIdentity,GenesisCoordinator}` | Q0 identity, roster and genesis/journal reconciliation foundation; direct Q1-A tests. | **KEEP_CURRENT** — preserve IDs, source SHA correlation, roster, and readiness gates. |
| `src/sawopt/studies/stage5a2/initialization.py::{sample_initial_population,attach_population,preflight_lshade,preflight_controlled_de,dispatch_initial_evaluation}` | Deterministic sealed population and Q1-A initialization/preflight logic; tested by foundation suite and import/golden scripts. | **KEEP_CURRENT** — preserve the frozen initialization, canonicalization, and certification contract; no permission to execute Q1. |
| `src/sawopt/studies/stage5a2/journal.py::SQLiteJournal` | Durable append-only hash-chained Q1-A event/immutable-record journal; foundation tests. | **KEEP_CURRENT** — integrity and recovery records are exact; do not migrate or reuse historical evidence. |
| `src/sawopt/studies/stage5a2/production_identity.py::Q0ProductionIdentityManifest` | Strict Q0 frozen production-identity representation/validation; exercised by Q1-A foundation tests. | **KEEP_CURRENT** — source/config/grid identity changes require separate reviewed scientific decision. |
| `src/sawopt/studies/stage5a2/rng.py::{RNGCallService,derive_seed32}` | Deterministic RNG state/call identity and journal reconciliation; foundation tests. | **KEEP_CURRENT** — preserve seed derivation, call order, state/replay and count semantics. |

No file/function in this matrix has a supported M0 **`DELETE_UNUSED`** or **`MOVE_TO_OWNER`** disposition. The `NEEDS_OWNER_DECISION` items are concrete no-source-caller or no-runtime-caller candidates to resolve only in a later owner-reviewed work order. They must not be deleted just because static callers are absent. `src/sawopt/orchestration/` has **no tracked source file** at this baseline; historical plans naming it are not evidence of a current owner to resurrect.

## 5. Non-source inventory and evidence dispositions

### Configuration inputs

| Tracked path(s) | Current role | M0 disposition |
|---|---|---|
| `configs/examples/r6_synthetic_smoke.yaml` | Supported strict synthetic CLI example. | **KEEP_CURRENT**; software validation only. |
| `configs/base/b28_dms_baseline.yaml`, `configs/models/com_params_hypothetical.yaml`, `configs/studies/hybrid_50ohm.yaml` | Fixed physics/evaluation regression inputs. | **KEEP_SCIENTIFIC_EVIDENCE**; not a run request. |
| `configs/studies/dms_topology_screening.yaml`, `configs/models/stage3_7b_r1_normalized_literature_profile.yaml`, `configs/reference/dms_topology_screening/{README.md,common_validation_grid.json,common_validation_grid_hz.csv,initial_design_origins.json,initial_designs/M0.json,initial_designs/MLIT.json}` | Retained DMS reference/material/grid/initial-design fixtures. | **KEEP_SCIENTIFIC_EVIDENCE**; preserve identity and parity inputs. |
| `configs/studies/hybrid_stage4a_qualification.yaml`, `configs/studies/hybrid_stage4c_confirmatory.yaml` | Frozen Q1-A identity/contract inputs; old executors are retired. | **KEEP_SCIENTIFIC_EVIDENCE**; presence is not authorization to re-execute. |
| `configs/README.md` | Explains supported synthetic configuration vs fixed historical/reference inputs. | **KEEP_CURRENT**. |

### Scripts, tools, tests, docs, and CI

- `scripts/README.md`, `scripts/check_stage5a2_foundation_imports.py`, `scripts/check_stage5a2_pure_leaf_import.py`, `scripts/verify_r2_physics_parity.py`, and `scripts/verify_stage5a2_canonicalization_golden.py` are verification/parity helpers. Current foundation tests call the relevant scripts; none is a study launcher. **Disposition: KEEP_CURRENT / KEEP_SCIENTIFIC_EVIDENCE** according to whether the path verifies a current software contract or a frozen numerical parity identity.
- `src/README.md` is outside the active docs index but describes current package ownership. Its phrase “Independent worktree/path safety utilities” is imprecise after PR #144 retired the standalone worktree tool; the independent R5 external-root validator remains in `io.experiment_store`. This is a documentation correction candidate only, not evidence for a code move or deletion; no source-layout README is edited in M0.
- `tools/diagnostics/evaluation_repro.py` is the fixed-array CI diagnostic; four `tools/wsl/*.ps1` files are setup/preflight/diagnostic helpers. The single CI workflow invokes the diagnostic and pytest; it does not launch science. **Disposition: KEEP_CURRENT**; do not split/bypass assurance from M0.
- All 35 `test_*.py` modules are test contracts or parity evidence, not dead runtime modules. Their tracked files are: `tests/integration/{test_review_export_cli.py,test_synthetic_cli.py,test_synthetic_task_worker.py}`; `tests/unit/core/{test_literature_com.py,test_material_profiles.py,test_physics.py,test_reference.py,test_stage4a_hybrid_composition.py}`; `tests/unit/design/{test_design_contracts.py,test_hybrid_design_space.py}`; `tests/unit/evaluation/test_physical_composition.py`; `tests/unit/io/{test_checkpoints.py,test_experiment_store.py,test_provenance.py,test_synthetic_task_ledger.py,test_synthetic_task_resume.py}`; `tests/unit/optimization/{test_accounting.py,test_adaptive_search.py,test_convergence_evidence.py,test_lshade.py,test_lshade_compact_bounds_policy.py,test_lshade_compact_history.py,test_search_primitives.py,test_selection.py}`; `tests/unit/physics/{test_import_boundaries.py,test_topology_evaluation.py}`; `tests/unit/problem/test_dms_topologies.py`; `tests/unit/reporting/{test_experiment_review.py,test_material_metadata.py}`; `tests/unit/runtime/test_parallel.py`; `tests/unit/studies/test_stage5a2_foundation.py`; and top-level `tests/unit/{test_architecture.py,test_evaluation_contracts.py,test_n1_synthetic_recovery.py,test_synthetic_task_cli.py}`. These assertions protect numerical conventions, canonical identity, optimizer/checkpoint accounting, raw/review integrity, worker fencing, and non-dispatch behavior. **Disposition: KEEP_CURRENT / KEEP_SCIENTIFIC_EVIDENCE**; no test is removed by this audit.
- `docs/README.md` and the five authoritative documents set current operating policy. `docs/history/`, dated `docs/plans/`, reports, and retained handoffs are scoped or archival evidence, not current APIs; do not overwrite or treat their old command names as callers. **Disposition: KEEP_CURRENT** for the active docs and **KEEP_SCIENTIFIC_EVIDENCE** for historical records.

## 6. Logical ownership proposal and package-split tradeoff

### Minimum logical contract (recommended; no physical package split)

```text
Scientific Core (logical)
  evaluation ─────────→ physics / design
  optimization ──────→ design / evaluation
  optimization ──────→ io.checkpoints + io.lifecycle (narrow persistence exception)
  problem.evaluator.dense ──→ evaluation + optimization.adaptive_frequency/cache (deferred exception)
  studies.stage5a2 ──→ design.canonicalization (Q1-A foundation; no execution)
  studies.dms_topology_common ──→ design / physics + reporting.material_metadata
                                      (retained reference/provenance exception)

Execution Harness (logical)
  cli ──→ strict config + injected optimizer/store/review composition
  cli ──→ synthetic task ledger / recovery
  cli ──→ synthetic_worker subprocess (fixed argv; worker also uses ledger)

Experiment Data & Review (logical)
  R5 raw store (io.experiment_store) ──→ validated closed-run evidence
  review exporter (reporting.experiment_review) ──→ local compact R5 package
  no GitHub/Pi publisher; no scientific job dispatch
```

The **Scientific Core must not depend on** GitHub, Pi/provider sessions, the CLI, the synthetic worker/task lifecycle, review publication, or an experiment runner. The two documented `problem → optimization` and `studies → reporting.material_metadata` edges, plus optimizer checkpoint IO, remain explicit exceptions until an independent decision demonstrates a safe simplification. The harness may call core contracts through the existing explicit CLI; it does not own scientific RNG/FE/checkpoint identity. R5 storage validates and stores raw runs; the R5 exporter validates closed evidence and writes the compact local package. Neither is GitHub publication, science execution, historical-run migration, or scientific acceptance.

### Option comparison

| Option | Concrete impact | Assessment |
|---|---|---|
| **A — retain one `sawopt` package; enforce logical ownership/import contracts** | No path moves. Extend `tests/unit/test_architecture.py` only if a focused guard is justified; retain `tests/unit/physics/test_import_boundaries.py`. Keep current console/module and worker paths. Preserve the explicit exception allowlist. | **Recommended (KISS).** Lowest caller churn; a static import test can protect the actual architectural rule without new packages, wrappers, or generic DI. Logical boundaries suffice for this stage. |
| **B — move into `sawopt_harness` / `sawopt_review` packages** | A tracked-text scan found **16 unique files under `pyproject.toml`, `src/`, and `tests/`** referring to one or more of the CLI, worker, R5 store, or exporter names; module-pattern subtotals overlap (CLI 8, worker 7, raw store 9, exporter 5 files). Moving owners would affect these callers plus docs, worker argv/process identity, and the synthetic source-hash allowlist. Preserving `sawopt.cli`, `python -m sawopt.cli`, `sawopt.synthetic_worker`, and `sawopt review export` would require wrappers/aliases or public-contract changes. The current store/exporter boundary is already explicit and tested. Counts use tracked `git grep` path matches, not a count of all edits; external callers remain unknown. | **Not justified.** Package churn adds new compatibility and source-identity risks without removing the observed logical edges. No separate repository or package distribution is proposed. |

No import move or new architecture framework is authorized by this proposal. Unknown external imports, shell invocations, and user wrappers cannot be ruled out by repository scans.

## 7. Staged follow-up proposal — not work orders

Each stage below is **`PROPOSAL / IMPLEMENTATION_NOT_YET_AUTHORIZED`**. Issue #145 requires a concrete, separately owner-reviewed work order before code changes. A successful software test would not authorize a science run or stage transition.

| Proposed stage | Candidate files/scope | Required evidence/tests and stop conditions | Rollback |
|---|---|---|---|
| **M1 — Scientific Core logical-boundary stabilization** | Candidate focused work only in `tests/unit/test_architecture.py`, `tests/unit/physics/test_import_boundaries.py`, and, if reviewed, source-level docstrings. Keep `physics/`, `design/`, `evaluation.py`, `optimization/`, `problem.evaluator.dense`, `problem.released_dms`, Q1-A, DMS references and existing optimizer→checkpoint IO. Decide separately whether test-only/no-runtime candidates in §4 have an actual supported owner. | Focused AST/import tests; physics analytic/reference tests; design canonicalization 92-case golden; optimizer comparator, budget, unique-FE/RNG/checkpoint/replay tests; adaptive dense parity and DMS T0 reference parity. Stop on any proposed change to equation, units, metric/ranking, bounds, grid, FE/RNG semantics, checkpoint identity, Q1 status, or unresolved external caller. No full-space reduction or algorithm qualification. | One self-contained PR; revert that PR if an import/API or exact parity identity changes. Retain old reports/configs/raw evidence unchanged. |
| **M2 — Harness boundary stabilization / narrowly justified pruning** | `src/sawopt/cli.py`, `synthetic_worker.py`, `io/cli_config.py`, `io/synthetic_task_ledger.py`, `io/synthetic_task_recovery.py`; only change current software contracts after test/caller evidence. Do not add a Pi, GitHub, scheduler, or science Worker adapter. | CLI/module/worker help and import non-dispatch; synthetic CLI/config integration tests; launch/idempotency/status/attach/stop/resume process-identity and attempt-fencing tests; manual recovery/fail-closed scenarios. Stop before any science task/optimizer integration (#104), automatic host restart, real Pi, or changes to task identity/recovery. | One focused PR, with unchanged worker argv/source hash and state contract unless explicitly reviewed; Git revert; no existing task roots/worktrees manipulated. |
| **M3 — R5 Data & Review boundary stabilization** | `io.experiment_store`, `reporting.experiment_review`, `sawopt review export`, and only exact owner/caller-proven helper candidates. Leave optimizer checkpoint persistence in its existing owner unless a separately tested design proves a simpler safe boundary. | Synthetic temporary fixtures only; unit/integration checks for raw/source/config/grid identity, expected cells, statuses, no-overwrite, artifact/checkpoint hashes, path containment, redaction, size, fail-closed export, and no run/evaluation dispatch. Stop before raw/checkpoint mutation, schema migration, concurrent-writer claims, GitHub publication (#98), scientific acceptance, or historical-data operation. | One self-contained PR; byte/schema identity tests; revert source change; never “roll back” by rewriting raw data or an existing review package. |
| **M4 — independent final audit / closeout proposal** | Static DAG and supported command inventory, all dispositions/exceptions, test/inventory counts, active docs links. Candidate deletions require the per-symbol evidence standard in #145. | Review all prior exact-head diffs and CI evidence. Run the locked full regression suite and fixed-array diagnostic where required by an authorized software work order; these are software regression checks, not COM/FE experiments. Any new COM/FE evaluation, optimizer study, Q1 official qualification, or production run requires separate explicit owner authorization and must not be smuggled into this audit. Stop on unresolved owner decisions or unverified branch-protection claims. | No blanket cleanup commit; revert a discrete change only. Preserve historical records and all external raw/checkpoint data. |

No follow-up issues were opened from M0. The `NEEDS_OWNER_DECISION` symbols stay in place until a separate owner-approved decision records current/external callers and replacement or explicit retirement scope.

## 8. Separate open gates and interpretation limits

- [#58](https://github.com/miyabimm/saw-com-optimizer/issues/58) remains open: off-device redundancy is unverified and one missing legacy payload remains unresolved/unclassified. No completeness claim or additional raw copy is authorized.
- [#142](https://github.com/miyabimm/saw-com-optimizer/issues/142) remains open/deferred: local worktree/data Gate B is not authorized here. M0 neither inspects ignored content nor performs cleanup.
- [#77](https://github.com/miyabimm/saw-com-optimizer/issues/77) is a plan-only future asynchronous/resume design; no production integration is approved.
- [#97–#102](https://github.com/miyabimm/saw-com-optimizer/issues/97) remain plan-only workflow/publication/recovery proposals. No Pi, GitHub publisher, repair, or next-run loop is implemented or authorized here.
- [#103](https://github.com/miyabimm/saw-com-optimizer/issues/103) is only the test-owned synthetic transaction/recovery composition. [#104](https://github.com/miyabimm/saw-com-optimizer/issues/104) remains plan-only for Worker ↔ synthetic optimizer/R5 integration.
- [#86](https://github.com/miyabimm/saw-com-optimizer/issues/86) and [#91](https://github.com/miyabimm/saw-com-optimizer/issues/91) remain blocked real-Pi gates. No session/provider was touched.
- Roadmap/experiment status is unchanged: Stage 4C topology selection is unresolved; Q0 is closed/accepted; Q1-A is work-unit-ready/closed; no Q1-01…Q1-23 gate passed; Q1-B/C/D/E remain unauthorized/not started.

A module with no in-repository runtime caller may be an externally imported API, a test-only scientific reference, a deferred integration point, or genuinely unnecessary code. The scan cannot prove which without owner context and consumer evidence. M0 therefore recommends **no source deletion and no package relocation**. Finite static analysis does not establish global absence, scientific acceptance, optimality, authorization, or branch-protection enforcement.

## 9. Validation and handoff record

- Exact source base verified: `4a672c7e345c0e0006a0410a861a5b0c339d0b80`; it contains PR #144 and the required preceding removals.
- Open-PR list checked through GitHub API: 0 at preflight.
- Exact-base inventory and import/caller analysis: tracked `git ls-files`, Python AST for direct/from/relative imports and literal dynamic-import calls, plus targeted source/test/config/script/workflow searches.
- GitHub Actions exact-head check #40186212121: `test` successful; log reports 360 passed, 0 skipped. This is remote evidence, not locally reproduced.
- **Not run:** local pytest/full suite, pytest collection, CLI commands, fixed-evaluation diagnostic, COM/FE, optimizer/qualification task, Worker/Pi session, or any experiment. Reason: this work order is explicitly docs/static only and has a successful exact-base CI check; no project code changed.
- `git diff --check` and local Markdown link/trailing-whitespace sanity passed for the docs/report changes. No branch-protection setting was inferred.
