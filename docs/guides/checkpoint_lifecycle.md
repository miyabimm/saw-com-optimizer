# Checkpoint lifecycle

For current authorization and storage policy, see
[`../experiments.md`](../experiments.md). This page records technical
checkpoint-owner behavior; it is not a production or resume procedure. R5
storage is future-only and tested synthetically. Do not start, resume, migrate,
or alter a historical run based on this page. Full checkpoint state, when
separately authorized, belongs with external raw data.

## Storage classes

Full optimizer state is a runtime recovery artifact by default. Each managed
optimizer stream lives under its own `checkpoints/` directory and keeps:

```text
latest.json
previous.json
final.json          # only after successful completion
pinned/<label>.json # only when explicitly requested
retention.json
```

Analysis history stays in ordinary CSV/JSONL outputs. Do not write full
population dumps to history as a substitute for resumable state. Existing
convergence traces, counter summaries, and milestone accounting remain the
canonical analysis records.

For new production runs this checkpoint directory is part of the external
persistent run, not a disposable Git worktree.

## Writes and recovery

Use `sawopt.io.checkpoints.CheckpointStore` for filesystem lifecycle. A store
accepts the existing serializer as a writer callback, writes to a temporary
file in the same directory, parses and validates it, rotates the previous
latest to `previous.json`, then atomically promotes the temporary file to
`latest.json`. It does not change checkpoint state fields or serialization.

Resume validates `latest.json` first, then `previous.json`. Optimizer-specific
validation must use a fresh backend instance so a failed load cannot leave the
live optimizer partially mutated. The L-SHADE study adapter
`LShadeCheckpointSession` provides this behavior and preserves the legacy
single-file `save_checkpoint`/`load_checkpoint` API.

Historical checkpoints retain their original schema and source identity; this
page does not authorize their inspection, resume, or migration. PR #109 retired
the old Codex-linked orchestration resume paths. Any historical run resume
requires a separate explicit owner authorization. A legacy run whose `manifest.json`
uses the historical v1 `run_store.initialize` fingerprint still requires its
matching source checkout: that contract hashes every Python file and rejects a
changed source tree. The checkpoint adapter does not bypass that manifest check
or migrate old runs. Legacy file-path selection remains available for state
versions accepted by the owning optimizer; it does not bypass the current
state-version check. In particular, L-SHADE v3 payloads are rejected by the
v4 loader rather than migrated. This does not promise that a legacy run can
resume under a changed source tree.

### Compact L-SHADE historical cache

L-SHADE checkpoints use state version 4. Cache identity stores each canonical
design key and its last frequency-grid version. A separate compact rank index
stores only the comparator key, finalist vector, and original insertion order
needed to reproduce the exact cumulative shortlist. Full evaluator mappings
remain with the active population/incumbent and bounded retained finalist
records (16 for Stage 4C). The shortlist ranks all evaluated designs, including
rejected proposals, and preserves the original stable insertion order for ties;
it does not substitute the live population for historical finalists.

A same-grid hit remains a cache hit and duplicate proposal: it does not invoke
the evaluator or enter the active population. A design last evaluated on an
older frequency-grid version is reevaluated when proposed, without incrementing
the unique-design count. Grid exchange, RNG, proposal counters, population,
archive, incumbent, schedule, bounds, and ranking state remain checkpointed
independently of the compact historical index.

Compact mode deliberately does not re-introduce an unretained historical design
through `update_bounds()` population injection. Its full evaluator result is no
longer available, so a same-grid historical collision is skipped and injection
continues with another proposal instead of reconstructing or reevaluating that
old result. This can consume an additional injection RNG draw compared with the
legacy full-result cache when such a collision occurs. It is therefore a
compact-mode bounds-expansion policy, not a general claim of full-cache
trajectory parity across `update_bounds()`. The frozen Stage 4C confirmatory
protocol does not perform bounds expansion, so this policy is outside the
Stage 4C production trajectory.

Study accounting counters are stored atomically with the optimizer state.
They must not be reconstructed by scanning historical evaluator results because
those payloads are intentionally no longer present. State version 3 checkpoints
are not migrated or resumed by this format. The loader checks the small state
header before materializing a checkpoint JSON document and rejects version 3;
the retained legacy file path does not bypass this compatibility boundary.

Failed or incomplete runs keep their runtime generations. Historical run
directories are read-only unless a user explicitly asks for a separate,
reviewable cleanup operation; no repository-wide cleanup is provided.
When a previously finalized run is resumed, its older `final.json` remains
available until the next successful finalization replaces it.

Managed result artifacts refer to the logical stream directory and policy,
not to a future `final.json` file. The stream reference remains valid while
the run is active and while review or recovery is pending. A final checkpoint
path is added to completion metadata only after finalization succeeds. Legacy
direct-file mode continues to record its actual checkpoint file path.

## Completion and retention

Checkpoint finalization is controlled by an explicit `RunDisposition`, not by
the absence of an error status or by a study's scientific gate result. The
generic lifecycle API supports `COMPLETED`, `REVIEW_WAITING`, `FAILED`, and
`UNKNOWN`. Missing or unknown disposition retains runtime recovery state.

`COMPLETED` allows a direct CLI run to finalize immediately. An orchestrated
run finalizes only after its durable optimizer status records successful
completion and exit code zero. `REVIEW_WAITING`, `FAILED`, and `UNKNOWN` keep
`latest` and `previous`. Finalization validates and promotes the newest valid
state to `final.json` before removing runtime and temporary files. Pinned
states survive finalization.

The compatibility adapter in `sawopt.io.legacy_lifecycle` maps the historical
Stage review markers to `REVIEW_WAITING` at legacy entrypoint boundaries. The
generic checkpoint store does not inspect Stage marker names. New studies
should supply an explicit disposition and must not add Stage-specific markers
to the generic checkpoint core. A later closeout after human review requires
a dedicated reviewed-closeout action that records `COMPLETED` and updates the
durable optimizer disposition. A historical callback/continuation success or `REVIEWED` marker is a recorded
value only; it is not current completion evidence and does not authorize raw
run deletion.

Direct Python calls to a study function do not imply successful completion.
Call the shared completion/finalization API only after the study has written
its successful closeout artifacts.

`metadata/recovery_policy.json` records the retention policy, final checkpoint
presence, explicit pin count, and history artifact paths.
`metadata/run_completion.json` records the explicit disposition and, after a
successful finalization, the existing final checkpoint path or paths.

Publication of lightweight GitHub evidence does not by itself delete the raw
checkpoint store. Keep the raw run at least through independent review and
closeout; later archive/deletion is a separate explicit lifecycle operation.

## GitHub review evidence

Issue #124 removed the old schema-v1–v4 GitHub exporter and
`python -m sawopt export-review` command. Existing `reports/experiment_reviews/...`
packages remain immutable historical evidence and are not the R5 schema. For
any future authorized run, follow the future-only R5 store/review contract in
[`../experiments.md`](../experiments.md); do not regenerate or migrate old
packages. Keep full checkpoints and raw arrays out of review packages; package
integrity is not scientific acceptance.

The separate historical/ad-hoc `ReviewBundleSpec` / `build_review_bundle`
utility remains for existing code callers and explicitly authorized saved-run
packaging. Its checkpoint filter excludes files in
dedicated `checkpoints/` directories and checkpoint-named JSON/binary payloads,
while retaining lifecycle documentation, source code, and CSV accounting. See
[`review_bundles.md`](review_bundles.md).
