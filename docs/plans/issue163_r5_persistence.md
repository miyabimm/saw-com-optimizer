# Issue #163 — configured result persistence (S2-B2), initial contract

**Status: design in progress; not an implementation or scientific authorization.**
This software-only work concerns an already finished, explicitly injected,
single-cell S2-B1 result. It does not run an optimizer or COM evaluator, add a
CLI route, enable optimizer checkpoint/resume, or qualify Q0/Q1.

## Owner boundaries and proposed status mapping

S2-A verifies the detached resolved v1 snapshot; S2-B1 owns search and record
validation; R5 owns raw transactions and the review exporter owns package
integrity. A persistence adapter must preflight the result and identities
before creating a run. It must not reinterpret rejected inputs or modify R5's
frozen schema.

| S2-B1 disposition | R5 cell disposition | Counts |
|---|---|---|
| `COMPLETED`, search `BUDGET_REACHED`, validation `VALIDATED`, no failure | `COMPLETED`, executed | Backend committed `unique_evaluations`; accepted validation record's grid point count |
| `EXHAUSTED` before budget, with consistent validated result | `INCOMPLETE`, with reason | Committed unique evaluations and accepted validation points |
| Search/evaluator/record failure | `FAILED`, with mapped failure and error | Preserve committed unique evaluations; failed attempts are supplementary, not silently charged |
| `VALIDATION_FAILED` | `FAILED`, with mapped failure and error | Preserve committed search count and incumbent; no validation points inferred from requests |
| Unsupported or inconsistent combinations, including unrepresentable `INCOMPLETE` | Reject before run creation | No invented work or status |

An accepted validation record represents the declared number of grid points
only as a **test-fixture callback record**, not independent evidence that a
physical response was solved. A failed callback's requested points are not
observed validation points. Backend unique evaluations are software committed
counts, not a decision on physical FE failure accounting. Other callback and
proposal counts remain labelled supplementary fixture details. S2-B1 snapshots
its search counters before the validation callback; the three validation
counters nested there remain zero even after validation. The separate
`validation.evaluator_calls`, `requested_grid_points` and accepted record are
the relevant validation-phase fields; never treat those pre-validation zeros
as evidence that the validation callback did not run.

## Review evidence gap

The v1 review context freezes `requires_validation=true` and the R5 exporter
requires `artifacts/validation.csv` for physical-response review
(`src/sawopt/reporting/experiment_review.py`). S2-B1 retains bounded metric
summaries, not the response samples needed for independent recomputation
(`docs/experiments.md`). A summary must not be presented as a physical trace;
export is disabled for this adapter. An explicit export request fails with a
local `VALIDATION_EVIDENCE_UNAVAILABLE` error before package publication; it
does not reopen or modify an already closed raw run. Do not change the frozen
review declaration or weaken the exporter. Package
`READY_FOR_REVIEW` would indicate integrity only, not scientific acceptance.

## Identity and remaining gates

The exact effective mapping hashes identically as S2-A
`effective_config_sha256` and R5 `scientific_config_sha256`; source YAML bytes
and R5's serialized `config.yaml` artifact occupy separate hash namespaces.
The three model/search-grid/validation-grid identities must be checked again
against the R5 manifest. Declared source and environment hashes are not
attestation; fixture persistence must receive a separate explicit test-only
execution SHA and label its evidence `TEST_ONLY / NOT_SCIENTIFIC_EVIDENCE`.
Production source/environment attestation, execution authorization, numerical
parity and physical FE accounting remain separate owner gates. No Q1 gate has
passed; Q1-B/C/D/E remain unauthorized.

## Lifecycle and failures

Pure plan assembly performs no filesystem access, including no root validation.
Persistence requires an explicit external root and validates it using R5, whose
writable probe is permitted only at that stage. The fixture adapter rejects any
pre-existing root, including historical roots, and requires a fresh test-owned
leaf; this does not attest ownership or provide a hostile concurrent-writer
sandbox. R5 can record a terminal cell
directly from `NOT_STARTED`; do not invent a live `RUNNING` transition. Failed
cells require a reason and R5 failure class, and their error must be recorded
before close. Run closure must agree with cell statuses and errors. Once a run
is published, preserve prior artifacts on any incident, report the failure and
record an error only when safely possible; never automatically remove, repair,
retry or reopen it. A collision fails without overwriting the existing run.

The S2-B1 summary's initial population is the retained canonical population
after successful initialization, not necessarily the configured maximum; on
initialization failure it remains the configured value. Preflight checks the
applicable bounds without changing backend behavior. It pins the S2-B1
accounting declarations, including the descriptive unresolved failed-FE policy;
this does not settle that policy. An S2-B1 record may legitimately contain
infinite return-loss metrics. R5 canonical JSON cannot faithfully represent them:
the pure plan fails with `R5_REPRESENTATION_GAP` before filesystem access,
without clipping or inventing a measurement.

A structurally `COMPLETED` test-only raw run is not scientific evidence and is
not `READY_FOR_REVIEW`. Declared hashes and the supplied test execution SHA are
not runtime attestations. Fresh-root checking is not an ownership attestation or
a defense against non-cooperating concurrent writers.

S2-B1 has no observed checkpoint timestamps, so omit observation rows rather
than inventing them. The R5 empty convergence artifact remains required and is
not an optimizer checkpoint or resume facility.

This initial mapping is subject to review against all R5 lifecycle and failure
transactions before implementation; it is not evidence that the adapter or
review handoff exists.
