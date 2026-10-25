# GitHub review workflow

This guide defines the current software-change review path for
`saw-com-optimizer`. GitHub branches, commits, and pull requests are the review
surface. Pi Code implements scoped software changes, validates them, and
publishes a Draft PR; ChatGPT independently reviews the pushed diff and
committed evidence. The user retains decisions on scientific meaning,
experiments, and gated project transitions. See the [development
workflow](../development.md), [current documentation index](../README.md), and
[experiment authorization boundary](../experiments.md).

## Roles and stop points

- **Pi Code:** implement the approved software scope, run relevant checks in
the locked environment, publish a Draft PR, and stop for independent review.
- **ChatGPT:** inspect the exact pushed source, tests, docs, and evidence; request
  focused corrections or accept within delegated scope.
- **User:** decide material scientific changes, experiments, and gated stage
  transitions; authorize merges or work outside delegated scope.
- **GitHub:** canonical record of the branch, exact commits, review discussion,
  checks, and disposition.

A passing test or local self-review is not independent acceptance. A Draft PR
is not production or experiment authorization.

## Software-change sequence

```text
scope and contract decision
→ focused RED test where behavior changes
→ minimum implementation and relevant validation
→ commit and push a dedicated branch
→ Draft PR with exact base/head and check evidence
→ independent review of the pushed GitHub diff
→ focused correction if requested
→ review/acceptance and separately authorized merge
```

Keep one coherent work unit per PR. Report the branch, base and head SHAs, PR
URL, changed files, commands run, skipped or blocked checks, and unresolved
questions. Do not rewrite historical evidence as part of routine cleanup.

## Current software boundary

The supported R6 user-facing CLI is `sawopt` / `python -m sawopt.cli` for strict
synthetic configuration validation and explicitly injected synthetic fixtures.
Issue #124 retired the separate `python -m sawopt` dispatcher and old
schema-v1–v4 `export-review` / `reporting.github_review` capability. This is an
intentional capability break, not an alias or migration for R5. The separately
installed `sawopt` console script and R5 `sawopt.review/1` package remain. The
old scientific CLI and detached orchestration launch/resume/recover/worker
path, Codex queue/callback runtime, and project-local C2C/Codex hook utilities
are also retired; there is no automatic agent handoff or session-continuation
fallback.

The synthetic task Worker/ledger is a separate software-only path. It does not
qualify scientific optimizer/FE recovery, authorize a real run, or replace the
R5 raw/review store. R5 storage and review-export APIs are future-only and are
not wired to a production experiment runner. Do not infer production readiness
from a synthetic test or this review workflow.

## Scientific and evidence gates

Before any real COM/FE, optimizer, qualification, or production work, follow
[`../experiments.md`](../experiments.md) and obtain the required separate owner
authorization. Freeze the applicable source, config, protocol, seed, budget,
grids, output location, resource policy, and review evidence before execution.
The Stage 4C topology-selection outcome remains unresolved; the former Stage
4B/4C production entrypoints are unsupported.

R5 review packages use the schema and paths in
[`../experiments.md`](../experiments.md). Package integrity and
`READY_FOR_REVIEW` are not scientific acceptance. Keep historical Stage 4B/4C
reports, raw data, checkpoints, configurations, and source identities as
immutable evidence; do not migrate or repair them in this workflow.

## Retired procedures

Do not use or recreate the former Codex/C2C queue, callback, `confirm-queue`,
legacy orchestration launch/resume/recovery, or detached worker procedures.
The recorded `status` and guarded `mark-review-published` commands remain for
historical status and publication semantics; administrative closeout and
independent non-agent safety APIs also remain separately gated and must not be
used to infer active-run absence or authorize a new run.
The dated [Issue #108 C1 disposition](../plans/issue108_r6c1_codex_removal_20261024.md)
records what was removed; the [Issue #111 C2A disposition](../plans/issue111_r6c2a_legacy_surface_disposition_20261024.md)
records the remaining project-local hook/document cleanup and its explicit
boundaries. Historical plan text and old manifests are not executable
instructions or evidence of current support.
