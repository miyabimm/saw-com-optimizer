# Issue #155 — Stage 5A historical compatibility audit

**Disposition:** Q0 protocol and Q1-A software evidence remain usable for their
stated, bounded purposes. They do **not** establish an executable real-SAW path,
full numerical parity, Q1 gate passage, or authorization to run an experiment.
This read-only audit used checked-in source, documentation, fixtures, Git
metadata, and deterministic software tests only. No COM/FE calculation,
optimizer study, historical replay, production run, or external raw-data
inspection was performed.

**Audited source baseline:** `419d246` (`origin/main`, Issue #148 merge), the
base of the Issue #155 work branch. No repository source or scientific data was
changed for the audit.

## 1. Compatibility matrix

The three status columns are independent. `VALID_HISTORICAL_EVIDENCE` means the
retained artifact supports only the claim stated in its row. It is not a claim
of execution, scientific acceptance, or complete recovery. “Parity” means
numerical/behavioral equivalence of an integrated path, not merely matching a
configuration identity. “Execution compatibility” means a supported current
path can execute and persist the corresponding work.

| Contract / evidence | Historical evidence | Numerical parity | Execution compatibility | Finding and trace |
|---|---|---|---|---|
| Q0 protocol / Stage 5A-2 identity | **VALID_HISTORICAL_EVIDENCE** | **NUMERICAL_PARITY_NOT_YET_VERIFIED** | **EXECUTION_COMPATIBILITY_MISSING** | Q0 is a closed, accepted comparison *design*. It freezes unchanged Stage 4C MLIT/T1, real 50/50 Ω ports, `P_D`/`D_P`, roots `20261012`–`20261014`, 234 ordered initial members per arm, 4,096 unique search FEs per arm (including the initial 234), a 1,001-point search grid and a 9,113-point common validation grid. The Q0 closeout explicitly records no Q1 qualification or 12-cell experiment. See [`stage5a2_q0_closeout_20261021.md`](../history/stage5a2_q0_closeout_20261021.md), §§1, 5, 8–9; [`stage5a2_q1_qualification_matrix.md`](../plans/stage5a2_q1_qualification_matrix.md). |
| Q1-A identity, journal, RNG and initialization foundation | **VALID_HISTORICAL_EVIDENCE** (Q1-A `WORK_UNIT_READY / CLOSED` only) | **NUMERICAL_PARITY_NOT_YET_VERIFIED** for optimizer/evaluator integration | **EXECUTION_COMPATIBILITY_MISSING** | The Q1-A source, deterministic tests, frozen fixtures and closeout report remain tracked. `production_identity.py` validates the frozen identity preimage; `identity.py`, `rng.py`, `journal.py` and `initialization.py` implement reusable Phase-I/II, typed-RNG and common-population primitives. The initializer preserves 234 ordered representations and has synthetic-only scripted tests; the dispatch function deliberately rejects every evaluation request. The Q1-A report explicitly says no official Q1 gate passed and actual optimizer paths are pending. Its source/config/lock digests and `clean_tree` flag are caller-supplied identity claims, not independent workspace attestation; cross-CPU bitwise identity is not established. See [`reports/stage5a2_q1a_common_foundation_20261021.md`](../../reports/stage5a2_q1a_common_foundation_20261021.md), final closeout / A1–A3; [`tests/unit/studies/test_stage5a2_foundation.py`](../../tests/unit/studies/test_stage5a2_foundation.py). |
| Canonicalization extraction | **VALID_HISTORICAL_EVIDENCE**, for the frozen 92-case primitive corpus | **Verified for the public method and pure leaf against that corpus only**; Stage 4B/4C runtime parity not executed | **EXECUTION_COMPATIBILITY_MISSING** as an optimizer-run path | The tracked fixture SHA is `3763c5746f4bf800a54f310aeeb94f493520fc0962505b1eed85d3c32b589aa2`. In this audit, both `design` (public API) and `leaf` verification modes passed 92/92 at the audited source, with that SHA. This proves only the bounded canonicalization behavior represented by the fixture, not an optimizer trajectory or COM response. See [`canonicalization_legacy_golden.json`](../../tests/fixtures/stage5a2/canonicalization_legacy_golden.json), [`design/canonicalization.py`](../../src/sawopt/design/canonicalization.py), and the Q1-A report A0–A1. |
| Q0 common initialization and the 234-member seal | **VALID_HISTORICAL_EVIDENCE** for the frozen sampler contract; there is no historical Q0 population/output | **NUMERICAL_PARITY_NOT_YET_VERIFIED** for the actual 13-D L-SHADE and DE evaluator paths | **EXECUTION_COMPATIBILITY_MISSING** | The source fixes the sampler name, PCG64 seed namespace, 10,000-draw cap, ordered 234-member seal, representation hashes and both preflight interfaces. The checked-in end-to-end sampler tests use scripted/synthetic low-dimensional vectors; production metadata checks bind exact Q0 bounds, but Q1-A certificates are expressly synthetic and cannot authorize an FE. No historical Q0 234-member seal exists because Q0 never ran. See `initialization.py`, `production_identity.py`, tests `test_population_seal_preflights_attachments_and_no_evaluator_before_both_certs` and `test_production_metadata_mismatch_rejected_before_genesis_sampler_or_evaluator`, plus Q1-04 in the matrix. |
| 4,096-FE accounting, comparator, and the two optimizer packages | **VALID_HISTORICAL_EVIDENCE** for the Q0 design terms | **NUMERICAL_PARITY_NOT_YET_VERIFIED** for the combined Stage 5A-2 search | **EXECUTION_COMPATIBILITY_MISSING** | Q0 statically pins the 4,096 ceiling, 65,536 proposal watchdog, `GeometryFirstComparator.rank_key`, the full L-SHADE package and the controlled `DE/rand/1/bin` package. The retained `optimization.selection` comparator and general `LShadeBackend` are reusable components, not a Q0 adapter. There is no `controlled_de` implementation in `src/sawopt/optimization/`, no Stage 5A-2 optimizer runner, and Q1-B/C are not authorized or implemented. Q1-01…23 all remain unpassed. See `production_identity.py`, `optimization/selection.py`, `optimization/lshade.py`, and Q1-01…23. |
| RNG / journal / restart / checkpoint | **VALID_HISTORICAL_EVIDENCE** for Q0/Q1-A contracts and Q1-A local primitives | **NUMERICAL_PARITY_NOT_YET_VERIFIED** for optimizer trajectory/restart (physical parity is not applicable to identity serialization) | **EXECUTION_COMPATIBILITY_MISSING** for optimizer transactions and recovery | Q1-A tests exercise exact typed RNG calls, PCG64 state, G0–G4, hash chains, and sampler replay. They do not exercise optimizer transactions. The existing L-SHADE checkpoint uses `state_version=4` and `_jsonable` maps nonfinite floats to `null`; Q0 names a distinct lossless `stage5a2_lshade_state_v1`, but the live-state codec/adapter is Q1-C work and is absent. No raw-run resume or Q0 checkpoint conversion is supported. See `optimization/lshade.py`, `studies/stage5a2/{identity,journal,rng}.py`, Q1-14…18, and the Q1-A report. |
| COM/model, metrics and frequency grids | **VALID_HISTORICAL_EVIDENCE** for documented equations, frozen input identities and narrowly scoped prior audits | **NUMERICAL_PARITY_NOT_YET_VERIFIED** for a config-driven Stage 5A path | **EXECUTION_COMPATIBILITY_MISSING** from the supported CLI | The reusable COM, network, design and evaluation code remains; [`physics.md`](../physics.md) records conventions and limits. Q0's identity validator checks the frozen model/grid descriptors and hashes, not output parity. Stage 5A-1's prior 12/12 candidate-grid profiler parity is valid only for its sampled frozen cases and is not a general user-config or optimizer integration proof. Complex ports remain unsupported. See [`stage5a1_closeout_20261020.md`](../history/stage5a1_closeout_20261020.md), §§1, 4–5; `evaluation.py`; `problem/evaluator.py`; and Q1-20. |
| R5 raw storage and review export | **VALID_HISTORICAL_EVIDENCE** for future-only software contracts / synthetic tests | Scientific parity is **NOT APPLICABLE** to storage; real-run integration is **NOT YET VERIFIED** | **PARTIAL**: external R5 store/export exists, but no real scientific caller exists | `create_experiment_run` requires the new R5 schema, frozen config, model/search/validation inputs, cell roster, source SHA and an external `SAWOPT_DATA_ROOT`. `review export` is a closed-run postprocessor. The supported synthetic CLI is their only integrated caller. The R5 store does not migrate legacy manifests, and successful package integrity is not scientific acceptance. See [`experiments.md`](../experiments.md), “R5 future raw-run storage contract” and “review package”; `io/experiment_store.py`; `reporting/experiment_review.py`. |

## 2. Implemented versus missing dependency path

| Layer | Retained implementation | Missing for Issue #155 target |
|---|---|---|
| CLI and YAML | `sawopt validate`, `run`, `review export`, and `synthetic-task`; `io.cli_config` enforces an exact synthetic-only schema. The smoke config is one dimensionless scalar, synthetic response, L-SHADE, at most 64 search FEs, and at most 100 validation points. | No generic scientific config parser/resolver; `run` is not a COM path. Historical study YAML is deliberately rejected/not adapted. |
| Model / design | COM providers and simulation, `design.space` topology records/decoders, geometry, and design bounds are retained. | No one validated model/design object created from a user config and dispatched from the public CLI. No general provider/profile selection in the CLI. |
| Evaluation | `evaluation.evaluate_response`, `measure`, `search_grid`, `validation_grid`, and `problem.evaluator.dense` exist. `dense` evaluates a fixed design with adaptive/cache/counter behavior. | No single config-driven objective/evaluator adapter wired to candidate decoding, optimizer search, independent finalist validation, and violation export. `dense` is not itself that optimizer dispatch. |
| Optimizer | General L-SHADE and SciPy-DE strategy/services and shared selection/accounting/checkpoint modules remain. | No generic validated optimizer selection from config; controlled Q0 DE and Q1 B/C adapters are absent; no real-SAW run coordinator. |
| Persistence / review | R5 external raw store, checkpoint store, and review exporter exist. The R5 APIs are future-only and do not read legacy schema-v1–v4 runs. | No scientific execution caller that reconciles optimizer FE/result/checkpoint state into R5; no automatic legacy conversion or resume. |
| Stage 5A-2 | Q1-A foundation and frozen Q0 identity/golden contracts remain. | No B/C/D/E implementation, no Q0 run, no Q1 gate pass, no actual initial-population evaluator preflight, and no optimizer/recovery/report integration. |

The supported target direction remains `config → validated model/design/evaluation/optimizer → R5 raw store → review export`; it is a design target, not current behavior. No layer should become a hidden side-channel evaluator or stage-specific execution script.

## 3. Identity and preservation checks

The following local checks were against checked-in files only; these files remain
in the Git index:

| Tracked artifact | Current SHA-256 | Recorded identity / scope |
|---|---|---|
| `tests/fixtures/stage5a2/canonicalization_legacy_golden.json` | `3763c5746f4bf800a54f310aeeb94f493520fc0962505b1eed85d3c32b589aa2` | Q1-A 92-case canonicalization corpus |
| `tests/fixtures/stage5a2/q0_design_space_contract.json` | `c7902e30f7becf2e2c0aa280d8f51c25f31f524cbf06c3516252bf47b2faddc9` | Four-topology Stage 4A bounds contract; embeds the two source-config hashes below |
| `tests/fixtures/stage5a2/seed_derivation_golden.json` | `1a824a07a6e7d652f47388e6604889e612c2809704b7681df713bb9ec8c7087a` | 18 deterministic Q0 role/topology/root-seed vectors |
| `configs/studies/hybrid_stage4a_qualification.yaml` | `829c7860d1fdb062d740f50076b9a381b3b792bb47834c197d812440644c448a` | Matches the Q0 design-space fixture source fingerprint |
| `configs/studies/dms_topology_screening.yaml` | `84de326d28cff00119c25380f00228c217f0557db0e3370f01d99a9005b50402` | Matches the Q0 design-space fixture source fingerprint |
| `configs/studies/hybrid_stage4c_confirmatory.yaml` | `63b5bd6d371408542922330df21f76311472af4bf5ce2d92346cd1e233deb94f` | Frozen Stage 4C historical input; its 96,000-FE settings are not Q0's 4,096-FE comparison settings |

Q0 decision commit `9427b404d302932b27f50d31919bb3fb95fcfcd4`, Q1-A merge
`03d673052c7570d86b78b43849f649758bb7d3f4`, Q1-A tested source
`03b9a5495111a1f933f542682f76b5ec9bad4e53`, and the Q1-A baseline
`f32b8f8dac928f21c567b34593b1ed227a4c9c9e` are present in the local Git object
database. That establishes availability of Git objects only, not runtime
compatibility or raw-data recovery.

**External raw state is UNVERIFIED.** No `$SAWOPT_DATA_ROOT`, historical raw
run, checkpoint, or backup was probed. R0's verified copy and its limits remain
as recorded in [`experiments.md`](../experiments.md) and Issue #58. Do not infer
external redundancy, a complete historical payload, or local raw parity from
tracked documentation or Git history.

## 4. Retired execution owners and recoverability

The reconstruction intentionally retired the old scientific CLI/dispatcher,
Stage 3/4 study executors and report pipelines, and the uncalled
`optimization.runner` COM/run-store executor with its private persistence and
history helpers. The current architecture and R6-L4 closeout identify these as
removed capabilities, not preserved compatibility APIs. R5 is a new,
future-only schema and must not be treated as a replacement reader for old
formats.

Consequently:

- **Recoverable as design/software evidence:** accepted Q0 terms; Q1-A source,
  tests and fixtures; documented Stage 4C conditions; source/config hashes
  present in tracked records; and bounded parity results explicitly described
  in the historical closeouts.
- **Not established as historical execution evidence:** Q0 has no experiment
  or run results. Q1-A's unit evidence does not qualify any Q1 gate. Historical
  COM results remain bounded by their own reports and retained raw availability.
- **Missing and not to be reconstructed by compatibility shims:** a current
  generic scientific CLI dispatcher, the Stage 5A-2 DE/L-SHADE adapters and
  full runner, Q0 checkpoint/restart integration, and any legacy manifest
  reader/migration path. Future work must use shared current APIs and R5 rather
  than restore the retired execution-only owners.

## 5. Audit checks run

- `uv run --locked pytest -q tests/unit/studies/test_stage5a2_foundation.py` —
  **65 passed** (deterministic software fixtures only).
- `uv run --locked python scripts/verify_stage5a2_canonicalization_golden.py --mode design`
  and `--mode leaf` — **92/92 each**, expected fixture SHA.
- `uv run --locked python scripts/check_stage5a2_foundation_imports.py` and
  `scripts/check_stage5a2_pure_leaf_import.py` — no forbidden imports.
- `uv run --locked sawopt validate --config configs/examples/r6_synthetic_smoke.yaml`
  — `VALID`, synthetic-only, non-executing.
- `uv run --locked sawopt --help` — confirmed current command boundary.
- SHA checks and `git ls-files` for the artifacts in §3 — matched as listed.

No full test suite was run: this audit changed no code, and the selected
Q1-A/canonicalization checks directly cover its compatibility claims. No
scientific run or physics calculation was run.
