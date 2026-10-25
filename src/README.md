# Python source layout (current status)

The current ownership map and dependency rules are maintained in
[`docs/architecture.md`](../docs/architecture.md). Reusable COM and network
physics live under `sawopt.physics`; design/topology/canonicalization under
`sawopt.design`; response and metrics under `sawopt.evaluation`; and optimizer,
accounting, RNG, and rolling checkpoint services under `sawopt.optimization`.

The supported user CLI is the synthetic/injected-only `sawopt` command and
`python -m sawopt.cli`. R5 raw/review APIs are future-only. Stage 3/4 study
executors, historical audits, old report/ZIP pipelines, the legacy study YAML
loader, and their compatibility imports were removed by Issue #129. Retained
DMS reference/grid/provider helpers live in `sawopt.studies.dms_topology_common`
with the independent `sawopt.problem.released_dms` parity reference; neither is
a study runner. The Q1-A foundation remains under `sawopt.studies.stage5a2`; its
92-case canonicalization golden is checked through `sawopt.design.space` and
the pure leaf API. Independent worktree/path safety utilities and the bounded
synthetic task worker remain separate from scientific execution.
