# Administrative legacy-run closeout — retired

Issue #128 removed the legacy orchestration status, publication, active-run
registry, and administrative closeout lifecycle. The former closeout command,
manifest/status parser, and registry release operation are not available in
the current source tree. This page is a retirement notice only; it is not an
operational procedure or authorization to inspect or modify a run.

Historical run manifests, closeout records, reports, raw data, and checkpoints
remain immutable evidence. Do not rewrite, migrate, resume, close, or otherwise
operate on them based on this notice. The R5 `sawopt review export` path is a
separate future-only package exporter; it does not publish a GitHub review or
mutate legacy run state.

For current worktree limitations, see the
[worktree safety guide](worktree_safety.md). That utility checks a selected
Git checkout and its files only; it does not inventory external runs or
processes. Follow the current [experiment/data policy](../experiments.md) for
all authorization boundaries.
