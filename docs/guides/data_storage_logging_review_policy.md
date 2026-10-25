# Data storage, logging, and review policy

This page is a navigation summary, not run authorization or an independent
storage contract. The authoritative rules for scientific experiments,
historical preservation, the future-only R5 store/review schema, and required
approvals are in [`../experiments.md`](../experiments.md).

## Current status

R5 raw storage (`sawopt.io.experiment_store`) and compact review export
(`sawopt.reporting.experiment_review`) are verified with synthetic fixtures.
They are not wired to a scientific optimizer or production runner. The
`sawopt` CLI / `python -m sawopt.cli` path is synthetic/injected-only. The
bounded synthetic task Worker/SQLite ledger is a separate software path, not a
scientific-run lifecycle or optimizer-resume service.

Issue #129 removes the historical study runners, saved-run report/ZIP
pipelines, and old study-config loader. Historical execution does not remain
reachable through compatibility APIs. A passing test, software work unit, or
package-ready status does not authorize COM/FE, optimizer qualification, a real
SAW study, production work, resume, or changed scientific conditions.

## Storage and evidence boundaries

- Keep historical raw runs, checkpoints, run manifests, frozen configuration
  snapshots, reports, and source identities immutable; software pruning must not
  rewrite or regenerate those records. The Issue #129 software-only scope may
  retire obsolete tracked execution templates without modifying frozen run
  snapshots or evidence.
- Any future R5 run requires an explicitly configured external
  `SAWOPT_DATA_ROOT`; rejected paths fail closed. Worktree/repository
  containment and independent path/worktree safeguards remain separate.
- Keep raw numerical data and recovery-heavy artifacts outside Git. Compact
  future review packages belong under the R5 path and schema documented in
  `experiments.md`; they do not replace raw preservation or independent review.
- Never infer completion, feasibility, acceptance, or successful publication
  from a missing artifact, historical status label, or package-integrity check.
  Report explicit statuses, violations, failures, and limits.
- Do not include secrets, private credentials, user-specific absolute paths, or
  full raw checkpoints/populations/caches in a review package.

For checkout-safety details, use the
[worktree safety guide](worktree_safety.md). It protects Git identity and
checkout contents; it does not inventory external run roots or process state.
The existence of retained safety tools does not authorize or enable a run.
