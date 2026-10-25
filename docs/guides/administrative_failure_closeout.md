# Administrative legacy-run failure closeout

> **Narrow safety procedure, not a production workflow.** PR #109 retired the
> old orchestration production launcher and Codex continuation. This document
> describes a retained administrative safety owner for an already-existing
> legacy run only. It does not authorize inspection or operation of a run; an
> explicit owner-approved scope is required before every use.

This procedure applies only to a legacy run whose detached worker can no
longer report a durable terminal optimizer result and whose worker and
optimizer processes are both confirmed dead. It is not a scientific review,
resume, or relaunch path, and does not apply to R5 synthetic fixtures or a
future production runner.

## Why this path is separate

A scientific review package must never be fabricated for an orphaned run that
lacks a complete terminal cell matrix. R5's future-only exporter is a distinct
schema and is not wired to a production runner. Issue #124 removed the old
schema-v1–v4 `export-review` command/exporter; do not regenerate historical
packages or represent an administrative closeout as a completed experiment.

Administrative closeout only records that the old run is abandoned as failed, preserves the raw run/checkpoints for investigation, and releases its active-run registry entry after a reviewed GitHub closeout record has been merged.

## Required GitHub record

Before changing the run, add and review a committed record at:

```text
reports/administrative_run_closeouts/<run_id>.json
```

The record is an allowlist authorization for one exact run and must contain at least:

- `schema_version: 1`;
- `action: administrative_failure_closeout`;
- exact `run_id`;
- exact production `source_commit_sha`;
- exact absolute `expected_run_dir`;
- recorded worker and optimizer PIDs;
- the allowed pre-closeout orchestration state(s);
- a bounded failure classification/reason;
- a statement that the record does not authorize resume or relaunch.

The authoritative record is the blob committed in the current clean Git `HEAD`. A working-tree-only file is not sufficient.

## Finalizer contract

The finalizer is invoked explicitly:

```bash
uv run --locked python -m sawopt.orchestration.administrative_closeout \
  --run-dir <ABSOLUTE_RUN_DIR> \
  --evidence reports/administrative_run_closeouts/<RUN_ID>.json \
  --confirm-abandon
```

Before mutating the run it verifies:

1. the evidence path is under `reports/administrative_run_closeouts/` and exists in current `HEAD`;
2. the repository worktree is clean;
3. evidence `run_id`, source SHA and absolute run directory match the immutable run manifest;
4. the current orchestration state is explicitly allowed by the evidence record and is a normal `STARTING`/`RUNNING` state that can transition to `FAILED`;
5. the recorded worker and optimizer PIDs match the evidence record;
6. both PIDs are currently dead;
7. the run uses external persistent storage;
8. the matching active-run registry record exists and has the same run directory and source SHA for the first closeout.

If any check fails, the command makes no state transition and does not release the registry entry.

On success it performs the following durable sequence:

1. write `administrative_failure_closeout.json` into the external run directory, including the reviewed evidence path, evidence SHA-256, current Git `HEAD`, prior status snapshot and closeout timestamp;
2. write `optimizer_completion.json` with disposition `FAILED`, preserving a recorded exit code if one exists and otherwise leaving it unknown;
3. transition orchestration state to `FAILED` while retaining existing diagnostic fields and checkpoints;
4. release the exact active-run registry entry.

The command does not delete or rewrite checkpoints, cell artifacts, logs, authorization claims, or the original manifest. It does not send queue continuation and does not mark the run scientifically reviewed.

The operation is idempotent only for the same reviewed evidence: rerunning after a successful closeout may confirm/release an already-closed matching run, but conflicting evidence must fail closed.

## Resume policy

A run closed through this path must not be resumed. Any replacement production execution is a new cold-start run with its own qualified source SHA, computation fingerprint, readiness review and explicit production authorization.
