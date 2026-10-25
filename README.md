# SAW COM Filter Optimizer

Python prototype for modeling and optimizing SAW filters with Coupling-of-Modes
(COM) inputs. The checked-in COM parameters are engineering/evaluation
assumptions, not calibrated production values.

The product target is a user-configurable constrained design flow and, later,
a Smith-chart heatmap built from an **independent filter re-optimization at
each sampled source/load impedance pair**. B28 Rx at 50/50 ohm is a regression
and diagnostic case. A finite-budget result is best-found, not a proof of a
global optimum. Physical COM calibration is optional; numerical correctness,
units/conventions, modeled-constraint consistency, and reproducibility remain
required.

## Current status

Stage 4C remains `STAGE4C_TOPOLOGY_SELECTION_UNRESOLVED`. Q0 is
`CLOSED / ACCEPTED`; Q1-A is `WORK_UNIT_READY / CLOSED`; no formal Q1 gate
Q1-01…Q1-23 has passed, and Q1-B/C/D/E are `NOT AUTHORIZED / NOT STARTED`.
The target `physics/design/evaluation/optimization/io` architecture remains
in migration. R5's future-only external raw-store and review schema-v1 software
was merged in PR #70. Issue #71 authorizes only the R6 synthetic/injected CLI
slice and software tests; it does not authorize real COM/FE, optimizer research
or qualification, production, Q1 work, or historical-data operations.

## Documentation

Start with the [current documentation index](docs/README.md), which identifies
the authoritative [roadmap](docs/roadmap.md), [architecture](docs/architecture.md),
[physics conventions](docs/physics.md), [development workflow](docs/development.md),
and [experiment/data policy](docs/experiments.md). The [historical baseline](docs/history/current_baseline.md)
and [experiment register](docs/history/experiment_register.md) preserve prior
evidence and limitations.

## Existing prototype

The current source remains under `src/sawopt/`. The `sawopt` console entry
point (`uv run --locked sawopt`) and `python -m sawopt.cli` provide only strict
synthetic config validation and the R6 synthetic vertical slice. They do not
load COM data or support real SAW evaluation. The old `python -m sawopt
export-review` dispatcher and schema-v1–v4 GitHub exporter were retired under
Issue #124. `python -m sawopt` is intentionally unavailable; this is not a
migration or alias for R5. R5's future-only `sawopt.review/1` package remains
separate and is automatically produced only by the synthetic CLI run path.

```bash
uv run --locked sawopt --help
uv run --locked python -m sawopt.cli --help
uv run --locked sawopt validate --config configs/examples/r6_synthetic_smoke.yaml
```

No command above authorizes a scientific or production run. The explicit
synthetic `run` command also requires an external `SAWOPT_DATA_ROOT` and a
clean committed source tree. Use the locked Ubuntu/uv environment documented in
[`docs/development.md`](docs/development.md).
