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
The repository reconstruction has merged R2–R5 and R6-L1/L2/L3; Issue #131
R6-L4 is the current docs/CI/closeout review. These are software and
architecture changes, not a roadmap-stage transition or scientific
qualification.

The checked-in COM model, design, evaluation, and optimizer components are
reusable software, but the supported CLI is **not** an integrated real-SAW
research runner. The long-term configurable design and impedance-map goals
remain future product work. No COM/FE, optimizer qualification, production,
Q1, or historical-data operation is authorized by a software merge or test.

## Documentation

Start with the [current documentation index](docs/README.md), which identifies
the authoritative [roadmap](docs/roadmap.md), [architecture](docs/architecture.md),
[physics conventions](docs/physics.md), [development workflow](docs/development.md),
and [experiment/data policy](docs/experiments.md). The [historical baseline](docs/history/current_baseline.md)
and [experiment register](docs/history/experiment_register.md) preserve prior
evidence and limitations.

## Current software surface

The `sawopt` console entry point (`uv run --locked sawopt`) and
`python -m sawopt.cli` expose strict synthetic-config validation, one synthetic
injected-evaluator run path, closed-run R5 review export, and an isolated
synthetic countdown-task group. They do not load user COM inputs or provide a
real-SAW research/production runner. A synthetic run can create an R5
`sawopt.review/1` package; `sawopt review export` separately postprocesses an
existing closed R5 raw run and does not launch or evaluate work.

The old `python -m sawopt` dispatcher, `python -m sawopt export-review`, and
schema-v1–v4 exporter were retired. There is no compatibility alias or old
schema reader; R5 is a distinct raw/review schema, not a historical migration.
See
[`docs/architecture.md`](docs/architecture.md) for current package ownership
and [`docs/experiments.md`](docs/experiments.md) for data/run boundaries.

```bash
uv run --locked sawopt --help
uv run --locked python -m sawopt.cli --help
uv run --locked sawopt validate --config configs/examples/r6_synthetic_smoke.yaml
uv run --locked sawopt review export --help
uv run --locked sawopt synthetic-task --help
```

Help and validation do not run an experiment. The explicit synthetic `run`
command requires an external `SAWOPT_DATA_ROOT` and a clean committed source
tree; the countdown task is synthetic software behavior only. No command above
authorizes COM/FE, optimizer research/qualification, production, Q1 work, or
historical-data operations. Use the locked Ubuntu/uv environment documented in
[`docs/development.md`](docs/development.md).
