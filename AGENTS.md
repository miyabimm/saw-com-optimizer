# SAW COM Filter Optimization Project

## Goal and source of truth

Build a reusable filter-design flow for user-supplied COM parameters,
frequency-domain specifications, topology/design variables, geometry limits,
source/load impedances, and computing budgets. Report the best-found
constrained design, feasibility, violations, and convergence limits; finite
search does not prove a global optimum. Impedance maps require independent
filter re-optimization at every sampled port pair. Physical COM calibration is
optional; numerical correctness, units, COM conventions, consistent modeled
constraints, and reproducibility are mandatory.

The only active documentation index is [`docs/README.md`](docs/README.md).
It identifies the authoritative current documents:
[`docs/roadmap.md`](docs/roadmap.md),
[`docs/architecture.md`](docs/architecture.md),
[`docs/physics.md`](docs/physics.md),
[`docs/development.md`](docs/development.md), and
[`docs/experiments.md`](docs/experiments.md). Read the relevant documents
before changing code or contracts. Target architecture is not a claim that its
modules or APIs already exist.

## Development and review

Use **docs first → necessary focused RED test → minimum GREEN implementation
→ KISS/YAGNI cleanup**. Select tests by behavioral and scientific risk; do not
add speculative abstractions or refactor unrelated code.

- **Plan / material decisions:** ChatGPT and the user define task scope; the
  user decides scientific-contract changes, experiment authorization, and
  project transitions.
- **Implement / self-validate:** Pi Code makes the smallest scoped change,
  runs relevant checks, and publishes a review branch/commit or Draft PR.
- **Independent review:** ChatGPT reviews the pushed GitHub diff and evidence.
  Self-validation is not external acceptance.
- **Accept / merge:** ChatGPT records review outcomes and merges within
  owner-delegated scope. The user decides material scientific changes,
  experiment execution, and gated project-stage transitions.

For meaningful work, report branch, commit SHA, review URL, checks run, and
unresolved questions. Stop for an owner decision before changing scientific
meaning, optimizer/search/budget semantics, COM physics, comparison fairness,
or any expressly gated authorization.

## Scientific and data boundaries

Follow the roadmap's staged gates. Stage 4C remains
`STAGE4C_TOPOLOGY_SELECTION_UNRESOLVED`; B28 Rx at 50/50 ohm is a
diagnostic/regression case, not the universal product target. Q0 is
`CLOSED / ACCEPTED`; Q1-A is `WORK_UNIT_READY / CLOSED`, but **none of
Q1-01…Q1-23 has passed**. Q1-B/C/D/E are `NOT AUTHORIZED / NOT STARTED`.
Do not run COM/FE, optimizer qualification, a real SAW study, resume Stage 4C,
change a budget/bound/constraint, or launch production without the separate
authorization required by [`docs/experiments.md`](docs/experiments.md).

Historical source identities and scientific raw/evidence are immutable. Do not
move, delete, overwrite, repair, or migrate raw runs, checkpoints, configs, or
historical reports as part of routine restructuring. R0's copy is verified,
but off-device redundancy and one missing legacy payload remain unresolved
under Issue #58; do not overstate preservation completeness.

## Environment and basic commands

Use the project-locked Ubuntu/uv environment and Python 3.12. From a new
worktree root:

```bash
uv sync --locked --extra test
uv run --locked pytest
uv run --locked sawopt --help
uv run --locked python -m sawopt.cli --help
```

Use `uv run --locked` for project commands. Do not install Node or commit
`.venv/`; keep `.python-version` and `uv.lock` tracked. See
[`docs/development.md`](docs/development.md) for validation and handoff policy.
