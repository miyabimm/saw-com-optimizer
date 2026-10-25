# Historical post-run review contract — retired

The former schema-v1–v4 GitHub review/export and orchestration publication
contract was retired under Issues #124 and #128. Historical
`reports/experiment_reviews/...` packages remain immutable records, not input to
a current exporter or schema migration. No old review bundle or report
pipeline is supported.

The future-only R5 compact package uses
`sawopt.reporting.experiment_review` and the schema/path documented in
[`../experiments.md`](../experiments.md). Its integrity status is not scientific
acceptance and does not authorize historical or production raw-data access.
