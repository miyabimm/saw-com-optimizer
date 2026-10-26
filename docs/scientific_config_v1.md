# Scientific configuration v1 — validation-only contract

Issue #157 adds declarations, not an evaluator or permission to run. The only
scientific operation is `sawopt validate --config FILE`; scientific `run` fails
with `SCIENTIFIC_RUN_NOT_IMPLEMENTED` before source/data-root preflight. Schema
validity is neither physical/evaluator qualification nor run authorization.
Synthetic `schema_version: 1` remains a separate, unchanged format. Legacy study
YAML and cross-schema mixtures are rejected, never adapted.

## Exact fields and supported subset

All fields listed below are required; all other keys at every depth fail.
Numbers exclude booleans, NaN, infinity and overflow to binary64. No scientific
defaults are filled. `real` means a finite binary64 value (YAML integer input
is converted); `integer` means a YAML integer, not a float or boolean. Text is
nonempty, untrimmed text without surrounding whitespace. Lists retain order.

Root keys: `schema_id` (exact `sawopt.scientific_config/1`), `experiment_id`
(lowercase hyphenated R5 slug, at most 63 characters), and exactly `model`,
`design`, `specification`, `ports`, `grids`, `optimizer`, `resources`, `storage`,
`review_context`. No root `schema_version` or synthetic fallback is allowed.

### Model

`model` has `kind: fixed`, `material` (text identifying the user assumption),
`assumptions` (text describing provenance/limitations), `parameters` (input
wrapper below). Only existing `physics.com.FixedProvider` parameter meanings
are accepted, without constructing it. Literature/calibrated/dynamic providers
and model plugins are unsupported, not inferred from a name.

The parameter payload has exactly `reference_aperture_um` (positive real, µm),
`idt`, `reflector`, `gap`. Each region has `velocity_m_s` (positive real, m/s)
and `loss_db_per_lambda` (nonnegative real, amplitude dB per wavelength).
`idt` and `reflector` additionally require `kappa_lambda` (nonnegative real,
dimensionless magnitude), `kappa_phase_rad` (real, radians),
`alpha_sqrtS_per_m` (nonnegative real, √S/m magnitude), `alpha_phase_rad`
(real, radians), `capacitance_F_per_m` (nonnegative real, F/m). The gap has no
other fields: existing physics forces its coupling/transduction/capacitance to
zero. No global fallbacks or phase/loss defaults are accepted. The existing
provider's wavelength conversion, aperture scaling, +jωt convention, lack of
frequency/temperature interpolation and free-gap behavior in [physics.md](physics.md)
are unchanged. Explicit input is not proof of passivity or calibration.

### Design

`design` has `topology: filter_design`, `decoder: sawopt.design.space.decode`,
`center` (`grounded` or `floating`), `wiring: outer_ports`, `variables`,
`integer_indices`, `fixed`, `geometry`.

`variables` is exactly seven ordered records, each with `name`, `unit`,
`bounds`, `hard_bounds`. Both bounds are two-real, strictly increasing pairs;
active bounds must lie inside hard bounds. Units and order are:

| index | name | unit | hard-bound domain |
|---|---|---|---|
| 0 | wavelength_um | um | positive |
| 1 | io_idt_pairs | count | integer endpoints >=1 |
| 2 | center_idt_pairs | count | integer endpoints >=1 |
| 3 | reflector_electrodes | count | integer endpoints >=1 |
| 4 | idt_gap_lambda | lambda | nonnegative |
| 5 | reflector_gap_lambda | lambda | nonnegative |
| 6 | aperture_um | um | positive |

Integer active endpoints must also be integral. `integer_indices` is exactly
`[1, 2, 3]` (zero-based integers). The existing decoder rounds these with
`floor(x+0.5)` and does not clip. Bounds here are declarations, not modifications
to any historical bounds. `fixed` has `metallization_ratio` (real, strictly
between 0 and 1) and `thickness_over_lambda` (positive dimensionless real), so
the `FilterDesign` defaults are never implicit. `geometry` has positive real
`max_length_um`, `max_width_um`, `min_electrode_width_um`,
`min_electrode_gap_um`, and positive integer `max_electrodes`. These are the
legacy scalar geometry model's modeled limits, not a die-area model. Hybrid,
T0/T1/T2, arbitrary variable subsets and area/layout modes are unsupported.

### Specification and ports

`specification` has `metric_contract: sawopt.evaluation.measure`,
`frequency_unit: MHz`, `passband` (two positive increasing reals), `stopbands`
(nonempty ordered list of `[lower_MHz, upper_MHz, minimum_attenuation_dB]`),
`il_db` and `ripple_db` (positive reals), `vswr` (real >1),
`feasibility_tolerance: 1.0e-10`, and
`comparator: sawopt.optimization.selection.FeasibilityFirstComparator`.
Bands must be disjoint (including boundaries); stopband order is preserved.
Metrics/normalized violations/geometry aggregation/feasibility tolerance are
exactly those in `evaluation.measure` and [physics.md](physics.md), not newly
defined metrics. IL/ripple/VSWR are maxima, stop attenuation is a minimum.
No return-loss/group-delay/area constraint or scalar-objective substitution is
accepted. Schema validation does not evaluate feasibility.

`ports` has `domain: positive_real`, `unit: ohm`, `source`, `load` (independent
positive reals). Complex impedances, lists and implicit shared ports fail.

### Grids and external input wrappers

`grids` has separate `search` and `validation` input wrappers. Each payload has
`kind: explicit_points`, `unit: Hz`, `points` (at least two positive, strictly
increasing reals). Both grids must contain at least two passband samples and
at least one sample in every stopband. No sorting, deduplication, interpolation,
adaptive refinement, default broad grid or implicit densification occurs.
Separation of roles does not assert statistical independence or sufficient
resolution; the two point sets may overlap. No plot grid substitutes for them.

All three input wrappers (`model.parameters`, `grids.search`,
`grids.validation`) have exactly one of these forms:

- `{inline: PAYLOAD}`; or
- `{path: RELATIVE_POSIX_PATH, sha256: LOWERCASE_64_HEX}`.

References are UTF-8 strict YAML payloads, not whole configs, arbitrary Python
or opaque unvalidated data. Paths resolve relative to the config's containing
directory, never cwd/data root/environment/home. Only regular files in that
directory tree are accepted: no absolute paths, `.`/`..`/empty components,
backslashes, symlink components, directories, FIFOs or URLs. Read bytes once,
verify the explicit SHA-256 over those exact bytes, then parse and validate the
same bytes. Nested references are unsupported. This is local read-only input
checking, not a hostile concurrent-writer sandbox or filesystem attestation.
YAML duplicate/non-string keys, merge keys, anchors/aliases, custom tags and
multiple documents fail (also in referenced payloads). A plain legacy config
is not reinterpreted. The source config itself may be located outside the repo.

### Optimizer

`optimizer` is a declaration of the current reusable backend, not a Q0 adapter.
It has `name: lshade`, `version` (full lowercase 40/64-hex Git source ID, equal
to `resources.source_commit_sha`), `seed` (nonnegative integer),
`rng: numpy.random.default_rng/PCG64`, `comparator` (same exact comparator as
specification), `search_fe_limit` (integer >=4), `proposal_policy: backend`,
`checkpoint_policy: disabled`, and `settings` with exactly:

| setting | type/range and meaning |
|---|---|
| initial_population | integer >=4, <= search FE limit |
| min_population | integer >=4, <= initial_population |
| history_size | positive integer |
| pbest_max_fraction | real in (0,1] |
| archive_rate | nonnegative real |
| max_duplicate_retries | nonnegative integer |
| total_budget | integer equal to search FE limit |
| hard_max_budget | integer equal to search FE limit |
| population_schedule_terminal_budget | integer equal to search FE limit |
| requested_unique_budget | integer equal to search FE limit |
| canonical_space_size | explicit null (mixed continuous space) |
| compact_history_cache | boolean |
| historical_finalist_count | positive integer |
| exhaustion_duplicate_streak | null or positive integer |
| memory_update_batch_size | nonnegative integer |

These are current `LShadeBackend` options, not new budget semantics. All search
unique FEs include initialization; validation points are separate. `backend`
explicitly declares existing duplicate retry/exhaustion behavior, NOT Q0's
65,536 proposal watchdog or any global proposal cap. The pinned source version
owns hard-coded backend behavior (including memory initialization/repair).
Controlled DE, Q0 sampler/identity/RNG/checkpoint packages, resume, adaptive grid
exchange, external watchdog policies and version aliases are unsupported.
Version/source IDs are caller declarations, not Git existence/clean-tree or
algorithm qualification attestations. Validation performs no Git subprocess.

### Resources, storage, review

`resources` has positive integers `workers`, `processes`, `threads`,
`memory_bytes`, positive real `wall_time_seconds`, `stop_policy: fail_closed`,
`source_commit_sha` (full lowercase 40/64-hex Git ID), `environment_sha256`
(lowercase 64-hex digest of the caller's frozen environment declaration).
The initial supported concurrency is exactly 1/1/1. Resource values are frozen
ceilings/identity declarations only; no execution scheduler/enforcement is
implemented or implied. Environment contents are not inspected or attested.

`storage` has `kind: r5_external`, `data_root_env: SAWOPT_DATA_ROOT`,
positive integer `required_free_bytes`, and `expected_cells`: exactly one record
with `cell_id` (R5-safe slug), `topology: filter_design`, `method: lshade`,
`seed` (same integer as optimizer). This first version is a single request,
not a comparison roster. No literal data-root path is accepted. `validate`
does not read/change that environment variable, test free space, create raw or
review storage, or import R5. Future authorized runs belong exclusively under
`$SAWOPT_DATA_ROOT/runs/<experiment_id>/<run_id>/`; compact reviews exclusively
under `reports/experiments/<experiment_id>/<run_id>/`.

`review_context` has text `purpose`, `conditions`, `limitations`,
`review_instructions`, `scientific_disposition: CLAIM_PENDING_REVIEW`, and
booleans `requires_comparison: false`, `requires_validation: true`. No pre-run
findings are fabricated; this is not an R5 manifest/review schema change.

## Snapshot and identities (exact bytes)

The resolver returns a detached JSON-compatible `effective_config`. Real fields
are normalized to Python 3.12 binary64 floats, integers remain integers, text
is unchanged. `1` and `1.0` in real fields therefore normalize equally; integer
fields reject `1.0`. Float negative zero is preserved; the YAML integer token
`-0` is integer zero, so use `-0.0` when declaring negative zero. No floating
arithmetic other than binary64 conversion is used to form identities.

Input wrappers are replaced in the snapshot by the validated payload itself.
Thus identical inline and referenced effective declarations hash identically;
reference spelling/location/comments/mapping key order are not science inputs.
No absolute local paths or host-derived defaults enter the snapshot. Arrays
(including variables/bands/points/rosters) retain source order, never sorted.

Canonical bytes are Python 3.12 `json.dumps(value, sort_keys=True,
ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('utf-8')`,
with no BOM/newline. Standard Python finite float rendering is used, including
`-0.0` versus `0.0`. SHA-256 of these bytes is `effective_config_sha256`.
`input_sha256` contains exactly `model`, `search_grid`, `validation_grid`, each
SHA-256 of its effective payload's canonical bytes (model means the parameter
payload, not metadata). These are content IDs, not Q0 codecs, Q0 grid-byte
hashes or promises of numerical parity. Q0 typed/bitwise identity remains
unchanged and cannot be substituted with these hashes.

Separate `config_file_sha256` hashes exact source YAML bytes; `references`
records each logical input name, declared relative path and verified exact-byte
`sha256`. Neither enters effective identity. A change in scientific fields
changes effective identity; formatting changes may change source-file identity
only. All other declared fields, including source/version/environment/seed/
resources/review, also enter effective identity. No execution source identity
is inferred from the current CLI checkout.

Successful scientific `validate` emits JSON: `status: VALID`, `schema_valid:
true`, `schema_id`, `experiment_id`, `qualification: NOT_EVALUATED`,
`run_authorized: false`, `scientific_run_implemented: false`,
`effective_config`, `effective_config_sha256`, `config_file_sha256`,
`input_sha256`, `references`. Validation errors return exit 2 with the existing
CLI JSON error envelope (no status implying scientific acceptance). A valid
scientific `run` returns exit 2 and `error.code: SCIENTIFIC_RUN_NOT_IMPLEMENTED`;
malformed declarations fail validation before reaching that error.

## Ownership and examples

`io.cli_config` owns strict YAML dispatch and preserves synthetic APIs.
`io.scientific_config` is a small standard-library-only validator/resolver,
separate to keep scientific declarations independent of physics, optimizer and
R5 imports. It has no dynamic plugins or runtime integrations.

[The validation-only example](../configs/examples/scientific_validation_only.yaml)
is a hypothetical software fixture, not an approved SAW experiment or runnable
research input. Test-only fixtures belong under `tests/fixtures/`. Future
separately authorized canonical Stage 5A inputs belong at
`configs/experiments/stage5a/<experiment_id>.yaml`; this issue adds none.
Review does not advance Stage 4C/Q0/Q1 gates or authorize configured execution.
