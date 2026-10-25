# Future experiment implementation notes — not an execution guide

> **No current production runner is authorized by this page.** R5 raw/review
> storage and R6 CLI/Worker behavior are synthetic-only; former Codex
> queue/callback and Stage 4B/4C production routes are retired. Issue #124 also
> removed the old schema-v1–v4 `export-review` command/exporter. Do not invoke
> an old `run-study`, checkpoint, or launcher command based on this
> forward-looking note. Before implementation or execution, follow the
> current [roadmap](../roadmap.md) and [experiment/data policy](../experiments.md)
> and obtain every required owner decision.

The architectural guidance below is retained for future design review only; it
does not designate currently supported entrypoints or production capabilities.

Use the shared checkpoint lifecycle in
[`checkpoint_lifecycle.md`](checkpoint_lifecycle.md) for full-state recovery,
rolling retention, and successful-run finalization. Keep analysis history in
CSV/JSONL outputs and do not add per-study checkpoint rotation code.

For any separately authorized future study design, use the storage and review
contracts in [`../experiments.md`](../experiments.md). The R5 future-only raw
store and review package paths/schema are defined there; they are not the old
`reports/experiment_reviews/<stage>/<run_id>/` convention and are not wired to
a production runner.

Every new study entry point must pass a `RunDisposition` explicitly to
`sawopt.io.checkpoints.complete_study_run`. Use `COMPLETED` only when the study
execution and its required closeout artifacts are complete; use
`REVIEW_WAITING` while human review remains, and `FAILED` when execution or
execution infrastructure validation failed. A scientific gate may finish
normally with either pass or fail; do not use its result as lifecycle state.
Missing or ambiguous evidence must remain `UNKNOWN`, which preserves recovery
checkpoints. Historical marker translation belongs in
`sawopt.io.legacy_lifecycle`; new studies should not add marker-name checks to
the checkpoint core.

Any future publication adapter needs a separately reviewed owner and contract.
The old generic `export-review` flow has been removed; R5's compact exporter is
distinct and future-only. Keep integrity, redaction,
size limits, and publication semantics in their approved owners.

`ReviewBundleSpec` / `build_review_bundle` is a historical/ad-hoc saved-run ZIP
utility, not the canonical publication path for a new production study. See
[`review_bundles.md`](review_bundles.md).

For any separately approved future numerical-study implementation, the
existing fingerprint-schema-v2 contract below remains unchanged. This guidance
does not revive the retired Stage 4B fingerprint or production-verification
path. Enumerate the full numerical source dependency set explicitly, including
the study's numerical implementation, COM/network dependencies, topology,
optimizer selection, counters, initializer, and exact input configuration.
Enumerate reporting code, plots, templates, and review-spec/export schema only
in the reporting dependency set.

The schema-v2 `computation_fingerprint` identifies the scientific and
computational inputs to the same numerical calculation. Scientific
configuration values and the complete computation dependency set and contents
must affect it. Repository-local absolute paths in configuration are represented
as repository-relative POSIX paths in the fingerprint; their actual absolute
values may remain in diagnostic provenance. Absolute paths outside the
repository are preserved because they may identify distinct inputs. Text
dependencies normalize only CRLF/CR line endings to LF before hashing; binary
dependencies retain their original bytes. Worktree location, path separators,
checkout line endings, reporting-only source changes, and environment-only
provenance must not change the computation fingerprint. Do not normalize other
text content or omit scientific inputs.

> Reporting-only changes do not invalidate computation fingerprints.

New computation gates should call
`sawopt.io.provenance.computation_gate_matches`; compare schema-v2 computation
fingerprints and ignore a reporting fingerprint mismatch for optimizer
execution. A reporting mismatch can require regenerating review artifacts.
Historical schema-v1 manifests and gates must remain readable and unchanged.

Prefer role-based module names such as `topology_screening`, `hybrid`, or
`impedance_sweep`; keep experiment chronology in configuration, external run
directories, and result metadata.
