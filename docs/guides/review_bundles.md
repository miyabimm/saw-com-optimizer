# Review bundle usage — historical / ad-hoc packaging

> This describes a retained ZIP utility used by selected older study/report
> code, not a new-run workflow. No production run or historical-data access is
> authorized here. Issue #124 removed the schema-v1–v4
> `python -m sawopt export-review` / `reporting.github_review` exporter. Existing
> `reports/experiment_reviews/...` packages remain immutable historical
> evidence; they are not R5 and must not be regenerated or migrated.

`artifacts/review_bundles/` and `sawopt.reporting.review_bundle` remain because
current study/report code and tests use this separate ZIP utility. It is not an
alias or fallback for R5. Use it only with test fixtures or a specifically
owner-authorized saved-run operation. Follow
[`../experiments.md`](../experiments.md) for authorization, data boundaries,
and the future-only R5 package contract.

## When this legacy/manual utility is appropriate

The ZIP builder is an implementation utility for the existing older
study/report callers and isolated fixtures. Any use with saved run data still
requires the separate data-access and lifecycle authorization in
[`../experiments.md`](../experiments.md). It is not a recovery or migration
route for the retired exporter.

This ZIP helper is not a replacement for the future-only R5 exporter and does
not establish scientific review readiness or authorize reading a raw run.

## Builder usage

Create a JSON specification that identifies the saved artifacts and source
files:

```json
{
  "study_type": "my_dms_study",
  "required_artifacts": [
    "run_manifest.json",
    "input_config.yaml",
    "results.csv",
    "REVIEW_ME.md"
  ],
  "optional_artifacts": ["responses.npz"],
  "source_paths": [
    "src/sawopt/design/topology.py",
    "src/sawopt/evaluation.py",
    "src/sawopt/studies/my_study.py"
  ],
  "review_me_path": "REVIEW_ME.md"
}
```

Then run from the project root using the project virtual environment:

```bash
uv run --locked python -m sawopt.reporting.review_bundle \
  --run <saved-run-dir> \
  --output my_saved_run_review.zip \
  --spec configs/review/my_saved_run.json
```

The ZIP is written under `artifacts/review_bundles/`. Required files are
validated before packaging. Optional files can be omitted with
`include_optional=False` in Python or by setting
`max_optional_artifact_bytes` in the JSON specification.

Checkpoint payloads are excluded from generic bundle archives. When a run uses
rolling retention, include its neutral `metadata/recovery_policy.json` file to
show retention and final-checkpoint metadata; do not include intermediate
full-state payloads by default. See
[`checkpoint_lifecycle.md`](checkpoint_lifecycle.md).

The builder includes a recorded `source_snapshot/` from the run when one is
available. Explicit `source_paths` are captured separately under
`source_snapshot/current_repository/`; they are not substituted for the
recorded snapshot. The bundle records current Git state and environment
metadata, hashes every included file, and verifies the ZIP contents after
creation.

For Python callers:

```python
from sawopt.reporting.review_bundle import ReviewBundleSpec, build_review_bundle

spec = ReviewBundleSpec(
    study_type="my_dms_study",
    required_artifacts=("run_manifest.json", "input_config.yaml", "results.csv", "REVIEW_ME.md"),
    optional_artifacts=("responses.npz",),
    source_paths=("src/sawopt/design/topology.py", "src/sawopt/evaluation.py"),
)
build_review_bundle("<saved-run-dir>", "artifacts/review_bundles/my_saved_run_review.zip", spec)
```

The CLI requires a `ReviewBundleSpec`; there is no study-specific bundle
contract in the reporting module.

## Storage warning

Do not copy large raw production runs into `artifacts/review_bundles/` or any
Git worktree merely to build a bundle. Raw production data belongs in external
persistent storage. Package directly from the saved run where possible.
