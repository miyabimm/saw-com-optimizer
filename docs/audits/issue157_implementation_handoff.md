# Issue #157 — partial implementation / STOPPED

## Baseline and scope

- Baseline: `a215c2a0a96c9ce2670e38e1901d49ea0b9c9cab` (PR #156).
- Branch: `issue157-scientific-config`.
- This is unfinished software work, not accepted schema, external review,
  scientific qualification or run authorization. No scientific run, Q0/Q1
  qualification, new COM study or historical raw-data operation was performed.
- No executable scientific research config was added. The new example is
  explicitly validation-only and uses hypothetical parameters and sparse grids.

## Implemented draft

- Normative field/unit/subset/identity proposal: `docs/scientific_config_v1.md`.
- Strict safe YAML dispatch in `io.cli_config`, pure scientific validator and
  read-only hash-pinned input resolver in `io.scientific_config`.
- CLI scientific validation result/snapshot and early rejected scientific run.
- Focused schema, identity, path/reference and fresh-process side-effect tests.
- Supported subset intentionally excludes hybrid/Q0, calibrated/literature
  providers, complex ports, comparison rosters and scientific execution.
  No scientific contract or existing numerical backend was changed.

## Commands and actual results

1. `uv run --locked pytest -q tests/integration/test_scientific_config.py::test_snapshot_and_normalization`
   — focused RED: **1 failed**, missing `load_cli_config` API before implementation.
2. `uv run --locked pytest -q tests/integration/test_scientific_config.py`
   — after minimum implementation: **80 passed, 2 failed** in 3.02 s.

The 80 passing cases cover positive snapshot checks, canonical hash calculation,
real int/float normalization, mapping order/repeat-process identity, signed-zero
identity change, scientific-field identity changes, strict keys/YAML, invalid
values/modes/units, legacy/cross-schema rejection, pinned reference success and
bad hash/path/type/payload rejection. Repeat-process `python -B -m sawopt.cli
validate` returned successfully and produced identical JSON, but that test does
NOT establish import safety.

## Exact blocker and stop decision

Both failures are `test_fresh_process_no_science_no_writes[validate/run]`.
The fresh-process audit hook raises before CLI dispatch:

```text
src/sawopt/cli.py:22 → .io.cli_config
src/sawopt/io/__init__.py:3 → .experiment_store
AssertionError: forbidden import: sawopt.io.experiment_store
```

Python executes the existing `io/__init__.py` before loading `cli_config`.
That initializer eagerly re-exports six R5 symbols. Splitting the resolver
alone cannot meet Issue #157's explicit **no R5 import** requirement. No guard
was weakened and no exception/alternate hidden import path was introduced.
Per the issue's test-failure stop instruction, implementation stopped here.

Proposed next correction, pending direction: preserve the current six public
`io` exports but make their import lazy, then rerun both fresh-process guards
and relevant R5/synthetic/import-boundary regressions. This requires touching
`src/sawopt/io/__init__.py`, beyond the parser/CLI files initially selected.
No such change has been made in this partial handoff.

## Evidence limits / remaining work

- No successful fresh-process safety evidence exists yet; no claim that the
  acceptance conditions pass. Both guarded validate and rejected run currently
  fail at import, not at their intended CLI behavior.
- Unguarded repeat-process validation succeeds; the intended scientific-run
  rejection JSON has not yet been independently smoke-tested.
- Existing synthetic/R5/Q1-A regressions, help entrypoints, full pytest and the
  fixed-input CI diagnostic have not been run locally for this implementation.
- Further nested-field/order/hash mutation coverage and existing synthetic
  output backward-compatibility checks should be reviewed before completion.
- Schema/code are draft and require independent scientific-identity and scope
  review. Source/version/environment hashes are declarations, not attestation;
  no Q0 parity is claimed.
- The initial general `git fetch origin` failed because the local remote fetch
  configuration names a deleted branch. Explicit `git fetch origin main`
  succeeded and the branch was fast-forwarded to the required baseline. No
  remote configuration was changed.

Draft PR is for visibility and independent direction only. Do not merge or
advance configured scientific execution from this partial implementation.
