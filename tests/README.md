# Test layout

- `unit/physics/`, `unit/design/`, `unit/evaluation/`, and retained `unit/core/`
  coverage: current COM/network, topology, canonical design, evaluation, and
  material-profile/composition regressions.
- `unit/problem/test_dms_topologies.py`: fixed-input DMS topology identities,
  reference parity, and numerical metrics; it does not launch a study.
- `unit/optimization/`: search strategy, adaptive-frequency, cache, unique-FE,
  accounting, and rolling checkpoint behavior.
- `unit/io/`, `unit/reporting/`: checkpoint, R5 external-store and review-package
  contracts.
- `unit/runtime/`: BLAS thread-environment override and restoration.
- `unit/studies/test_stage5a2_foundation.py`: Q1-A software foundation and the
  frozen 92-case canonicalization golden; it does not pass a formal Q1 gate.
- `unit/orchestration/` and synthetic-task tests: bounded synthetic Worker and
  independent path/worktree safety; no historical study lifecycle.
- `integration/`: synthetic CLI and test-owned synthetic recovery fixtures.

Official validation uses the project-locked environment:

```bash
uv sync --locked --extra test
uv run --locked pytest
```

The current CLI is synthetic-only. Historical Stage 3/4 execution, saved-run
reporting/ZIP workflows, and their exclusive tests were retired under Issue
#129; historical reports and source/evidence identities remain unchanged.
R5 output under `reports/experiments/<experiment_id>/<run_id>/` is a future-only
schema verified with synthetic fixtures, not production approval. See
[`docs/experiments.md`](../docs/experiments.md) and
[`docs/development.md`](../docs/development.md).
