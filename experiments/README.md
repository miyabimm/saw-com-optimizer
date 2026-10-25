# Experiment and software boundaries

No Stage 3/4 study runner, historical audit pipeline, or production experiment
entry point is supported by the current tree. The installed `sawopt` CLI and
`python -m sawopt.cli` provide synthetic/injected software fixtures only; R5
raw/review storage and the bounded synthetic task Worker/ledger are not
scientific-run launchers or optimizer qualification.

Reusable topology/evaluation/optimizer behavior lives in `sawopt.design`,
`physics`, `evaluation`, and `optimization`; retained DMS reference/grid/provider
helpers and the released-model parity reference are separate numerical coverage,
not study executors. Historical Stage 3/4 conditions, source identities,
reports, and outcomes remain recorded in `docs/history/` and `reports/`; their
former executable study adapters and report-generation pipelines were retired
under Issue #129. Do not infer that retained historical evidence can be
regenerated or that a missing runner should be restored.

Before any COM/FE, optimizer qualification, real SAW study, production run,
resume, or scientific-condition change, follow the authoritative
[`docs/experiments.md`](../docs/experiments.md) policy and obtain the required
separate owner authorization.
