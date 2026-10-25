# Legacy ZIP review bundles — retired

The `sawopt.reporting.review_bundle` ZIP builder and its Stage-specific callers
were removed under Issue #129. No ZIP compatibility layer, saved-run report
generator, or historical schema adapter remains. Historical ZIP/review evidence
and source identities remain immutable records; do not regenerate, migrate, or
rewrite them.

The separate R5 compact review exporter is
`sawopt.reporting.experiment_review`. Its schema, canonical output path, and
future-only authorization boundary are documented in
[`../experiments.md`](../experiments.md). R5 package readiness is not
scientific acceptance and does not authorize access to a historical or
production raw run.
