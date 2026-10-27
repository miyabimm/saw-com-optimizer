# Issue #161 — configured L-SHADE library orchestration (S2-B1)

**Status:** bounded library-only software work unit. This contract adds no
scientific CLI route, experiment permission, R5 integration, or source/environment
attestation. It does not alter the scientific configuration v1 schema, Q0/Q1,
COM semantics, or optimizer policy.

## Scope and call boundary

The public entry point is `sawopt.optimization.configured_search.run_configured_lshade`.
It receives one in-memory successful `sawopt.scientific_config/1` resolved
snapshot, an explicit injected SEARCH evaluator, and an explicit injected
VALIDATION evaluator. There is no default evaluator. The function reuses the
S2-A verified `ConfiguredEvaluationContext`, does not reopen YAML/references,
and accepts only the declared one-cell `filter_design` / `lshade` /
`FeasibilityFirstComparator` request. `checkpoint_policy: disabled` means no
checkpoint or resume. The result is bounded and in-memory; this module does not
import or write R5 storage, create a run, or expose CLI execution.

The backend continues to own normalized population vectors. Its existing
canonicalizer boundary converts those into physical coordinates and applies
`design.space.canonical_design` (half-up integer rounding, physical bounds,
canonical key and signed-zero behavior). Injected callbacks receive the
physical canonical vector and the exact phase (`SEARCH` or `VALIDATION`). A
returned record must agree exactly with the supplied proposal, decoded
canonical vector/key, phase, model/config/grid identities, existing metric and
objective checks, and `FeasibilityFirstComparator.rank_key`. Compact history's
optional `candidate_vector` is required to equal that canonical physical vector.

## Search mapping and accounting

Every accepted `optimizer.settings` field maps explicitly to its same-named
`LShadeBackend` option; the v1 schema resolver remains the authority for field
ranges and equality constraints. The runner explicitly sets the declared
active/hard bounds, integer coordinates `(1, 2, 3)`, PCG64 seed, existing
canonicalizer, and feasibility-first comparator. The backend's existing
proposal, RNG, duplicate, retry, population-schedule and stopping behavior is
not wrapped in new policies. Initialization counts against the strict declared
unique-search budget. No retry is added by orchestration.

Backend `unique_evaluations`, `proposals_total`, `raw_offspring_count`,
`duplicate_count`, and `cache_hits` remain their original authoritative
counters. In a fixed-grid successful run, every backend proposal resolves to a
returned new record or a cache hit; `duplicate_count` is a subset/classification
of proposals and must not be added to cache hits. Do not infer identities beyond
those demonstrated by the exact path.

A callback invocation and a successfully validated returned record are tracked
separately from the backend's committed `unique_evaluations`. The existing
backend increments its unique counter only after an evaluator returns and the
record is accepted into backend state. An exception/invalid record therefore
fails closed and reports attempts, accepted records, and backend-committed
unique evaluations separately; it is not silently assigned an FE charge, made
into a penalty result, or retried. This leaves the scientific FE treatment of
failed model attempts unresolved for a future explicitly reviewed
qualification/policy gate.

## Validation and result disposition

After a search incumbent exists, the single documented finalist is that
search-space incumbent. It is evaluated once with the exact declared validation
grid by the explicit VALIDATION callback, outside the L-SHADE budget/cache.
Validation never changes or reranks the search incumbent. Result fields retain
the search record and validation record separately, the exact grid SHA-256 and
point count, callback/request counters, resolved identity declarations, the
one-cell roster, search summary/counters, and failure/incomplete reasons. Large
response arrays, full history, checkpoints, files, or R5 artifacts are not
returned.

A validation exception yields `VALIDATION_FAILED`, not a completed result. A
search callback exception, record-reconciliation error, optimizer failure, or
exhausted search retains its own explicit disposition and counters. Any source
or environment hashes in the result are caller-declared values from the
snapshot, not runtime attestations. A finite or exhausted search is only a
best-found software-fixture outcome, not a scientific result or global claim.

Tests use small test-owned validated v1 snapshots and deterministic injected
synthetic records only. They compare direct `LShadeBackend` behavior under the
same declared settings/canonicalizer/callback/seed, and exercise duplicates,
failures, budget exhaustion, validation separation, and fail-closed identities.
No real COM evaluator, research workload, Q1 qualification, R5 writer, or new
CLI path is part of this work unit.
