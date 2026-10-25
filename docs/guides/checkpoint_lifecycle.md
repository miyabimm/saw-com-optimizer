# Optimizer checkpoint ownership

This is a technical description of the current rolling optimizer checkpoint
owner, not a production/resume procedure. Current authorization and data
boundaries are in [`../experiments.md`](../experiments.md). Do not start,
resume, migrate, inspect, or alter a historical run based on this guide.

## Rolling storage

`CheckpointStore` retains a bounded stream under a `checkpoints/` directory:

```text
latest.json
previous.json
final.json          # only after explicitly completed finalization
pinned/<label>.json # only when explicitly requested
retention.json
```

The store writes a temporary file in the same directory, validates it, rotates
the previous `latest.json` to `previous.json`, and atomically promotes the new
state. A failed write preserves valid retained generations. Analysis history
belongs in ordinary CSV/JSONL outputs, not full population dumps.

`LShadeCheckpointSession` uses this rolling store only. It validates candidate
checkpoint state with a fresh backend before loading it into the live backend;
latest falls back to a valid previous generation. The historical single-file
checkpoint fallback and its format-specific reader have been removed. No
checkpoint migration or compatibility path is provided.

## State and completion

The existing optimizer serializer and state payload remain canonical. Checkpoint
loads preserve optimizer population, archive, RNG, proposal and unique-FE
accounting, frequency-grid version, and compact finalist/index state. Do not
reconstruct those fields by replaying historical evaluator output. A final
checkpoint is eligible only when the existing completion metadata records an
explicit successful disposition; missing or ambiguous completion does not
imply success.

Historical checkpoints keep their recorded schema and source identity. They
are immutable evidence; no old file reader, source-fingerprint bypass, repair,
resume, or migration is supported by this guide.

## Review boundary

R5 raw storage and `sawopt.reporting.experiment_review` are separate
future-only contracts verified with synthetic fixtures. Their schema and
authorization limits are described in [`../experiments.md`](../experiments.md).
Full checkpoint state, populations, and raw arrays do not belong in compact
review packages. Package integrity is not scientific acceptance. The former
Stage-specific report and ZIP bundle pipelines have been retired under Issue
#129; historical reports remain unchanged.
