# Issue #165 — S2-C integration working record

**Status: implemented as a test-only library slice; not scientific evidence or
approval for a scientific run.**

## Baseline before Issue #165

- `ConfiguredCandidateEvaluator` calls `evaluate_design` once for each request,
  but discards the returned network and simulation. Its result identifies the
  phase, canonical design, effective config, model and grid; it contains metrics,
  not the physical-response samples needed for review.
- `run_configured_lshade` accepts explicit SEARCH and VALIDATION callbacks,
  snapshots search accounting before the single finalist validation call, and
  projects records into bounded summaries. Search FEs are backend committed
  unique evaluations; validation calls and requested points are separate.
- `configured_persistence` verifies an already finished result and creates an
  R5 run afterward. Its export helper refuses with
  `VALIDATION_EVIDENCE_UNAVAILABLE`; R5 review requires a registered
  `artifacts/validation.csv` when the frozen context requires validation.
  Metric summaries must not be substituted for samples.
- `R5_REPRESENTATION_GAP` remains fail-closed for values that cannot be
  faithfully encoded as canonical JSON. Failed-attempt physical FE accounting
  remains an owner decision, not a rule established by a software fixture.

## Implemented fixture flow and limits

`ConfiguredCandidateEvaluator(..., capture_validation_response=True)` adds a
`validation_response` only to VALIDATION calls. It copies the already computed
frequency, admittance, S, gain, IL and VSWR arrays, along with the canonical
vector, config/model/grid hashes and port references. The default remains
metric-only. A mismatching simulation grid, mutated frequency argument,
nonfinite or wrongly shaped arrays fail the callback. No additional COM solve is
performed. An injected evaluator is trusted software test input, not attestation
that physical samples were produced.

`io.configured_fixture.run_configured_fixture` verifies the detached v1 snapshot,
explicit execution SHA, run ID, callbacks and fresh absolute test-owned raw
root, then creates R5 before running the injected search. It checks R5's config,
input and roster identities. The existing search calls the validation callback
once on the selected canonical incumbent; before accepting captured samples the
fixture checks the identities, exact grid and ports, recomputes the network
from the captured admittances, and recomputes the validation metrics and
violations. The existing search record checks and persistence plan then verify
the final record and finalist. A mismatch is a validation failure; no response
is invented. Published raw data is retained on write/close incidents.

The registered `artifacts/validation.csv` has one row per validation point:
classification, frequency in Hz, dimensionless transducer gain, IL in dB,
input/output VSWR (dimensionless), complex two-port Y in siemens and S
(dimensionless), with real and imaginary components in separate columns.
Optional explicitly supplied return-loss columns are in dB. The associated
canonical finalist, configuration/model/grid hashes and port values are in the
registered configured result and frozen R5 config/inputs; the cell result and
CSV are labelled `TEST_ONLY / NOT_SCIENTIFIC_EVIDENCE`. The existing R5
exporter checks hashes and its unchanged review contract; package readiness is
not scientific acceptance. `export_fixture_review` refuses a metric-only run
with `VALIDATION_EVIDENCE_UNAVAILABLE`. The caller must use a disposable
test-owned review repository; root freshness is not ownership attestation.

Search FE counts are backend committed unique evaluations, not attempted or
failed callbacks; accepted validation records count separately as grid points.
A failed validation callback records no observed validation points. A metric-only
record's accepted count is a fixture accounting convention, not independent
proof of a physical trace. R5's runtime identity is recorded independently of
the declared source/environment and the caller-supplied test execution SHA;
none establishes production attestation. The scientific CLI run guard remains
in place.

A smallest next gated step is owner review of source/environment attestation,
failed-attempt FE policy, numerical parity and a separately specified and
authorized scientific execution protocol. These fixture tests do not grant
that authorization.

The generic v1 single-filter subset is not the Q0 hybrid `P_D`/`D_P`
234-member protocol. Q0 remains accepted, all Q1-01…Q1-23 remain unpassed,
and Q1-B/C/D/E remain unauthorized. Scientific execution, numerical parity,
and qualification require separate owner-gated work; no real COM-based L-SHADE
study is authorized here.
