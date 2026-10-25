# Development and review workflow

## Working principles

Use **Docs-first → risk-based RED → minimum GREEN → REFACTOR**. Record the
intended behavior/contract before code. Add a focused test when it protects
observable behavior or risk; do not maximize test count or blanket-run expensive
numerical tests for a documentation-only change. Keep changes coherent and
small; apply KISS/YAGNI, avoid compatibility layers that are not an explicit
current requirement, and do not refactor unrelated code.

Separate these activities:

1. **Plan / owner decision — ChatGPT and user:** define scope and decide
   scientific-contract changes, experiment permissions, and project transitions.
2. **Implement / self-validation — Pi Code:** make the scoped change, run
   relevant local checks, and publish the exact branch/commit and evidence.
3. **Independent review — ChatGPT:** inspect the pushed GitHub diff, source and
   committed evidence; request focused corrections where needed.
4. **Accept / merge — ChatGPT within delegated scope; user at decision gates:**
   ChatGPT records review results and merges reviewed PRs where the owner has
   delegated that class of change. The user approves material scientific
   changes, experiments, and gated project-stage transitions.

Implementation self-validation is not external review. A passing test is not scientific
acceptance. Keep PRs focused; merge only within documented owner delegation and
do not start gated follow-up work without the applicable owner decision.

## Scientific risk gates

- **Docs / low-risk cleanup:** check links, terminology, statuses, rendered
  Markdown, and `git diff --check`; no numerical test is needed if no code or
  scientific condition changed.
- **Normal code:** write a focused behavioral RED test, implement the minimum
  GREEN change, run the focused tests and relevant smoke/integration checks.
- **Scientific core or comparison validity:** changes to COM equations/units,
  S-parameter or power conventions, ranking/objectives/constraints, mixed
  variable semantics, budget/accounting, RNG/replay, grids, checkpoint
  integrity, or experiment conditions require explicit owner review before
  changing behavior. Use analytic limits, relevant numerical regressions,
  parity/change analysis, and integration tests proportionate to risk. Preserve
  exact equality where identity, canonical keys, counts, or ordering are part
  of the contract; justify numerical tolerances before use.

The current CI is one locked full-pytest job, not the planned risk-lane system.
Issue #74's measured baseline, fixed selectors and lane recommendation are in
[R7 architecture/CI audit](plans/r7_architecture_ci_audit_20261023.md). That
report does not split or weaken the workflow: retain the full Haswell-pinned
pytest suite and fixed-evaluation diagnostic as exact-head checks and required
scientific/regression milestones. Any future fast/docs lane is additive and
must not create path-, label-, or docs-only bypasses. At the R7 audit, the Pi Code GitHub request reported a 404 for main branch
protection; independent GitHub App access returned 403 (insufficient access).
Required-check enforcement is therefore **not independently verified**. The
repository owner/admin must inspect branch protection and rulesets and require
the full CI check before treating it as an enforced merge gate. The
`KNOWN_BASELINE_FAILURE` for the obsolete agent/model routing assertion in the
R0 inventory is historical evidence; R1-B retires that non-product test
without changing scientific tests or CI.

## Environment and commands

The official environment is Ubuntu/WSL2 with project-locked uv and Python 3.12
(`/usr/bin/python3.12`). Do not install Node. Keep worktrees under `/home/...`;
track `.python-version` and `uv.lock`, never `.venv/`.

```bash
# New worktree setup
uv sync --locked --extra test

# Relevant validation
uv run --locked pytest tests/unit/<focused-path>
uv run --locked pytest
uv run --locked sawopt --help
uv run --locked python -m sawopt.cli --help
```

Use `uv run --locked` for project commands. Run the full suite when required by
the risk or release gate and avoid repeated full-suite runs without a reason.
The exact selected commands and skipped tests must be reported. See the
[development environment record](guides/development_environment.md) for
historical host details; this page owns current development policy.

## GitHub handoff

For meaningful work, push a focused branch and report branch, HEAD SHA, PR or
commit URL, changed files, checks run, known failures, assumptions, and open
issues. Docs-only work should stop at a Draft PR for independent review. Record
changes to scientific meaning as proposals until the user decides. Production
study implementation/config/preflight/source identity/review spec must be
available for review before a run, but this is not run authorization. For the
R1-A documentation cutover, stop at the Draft PR pending independent review and
acceptance within the owner's delegation; retain the separate owner decision
on Q1 continuation. Do not start R1-B or R2 until the applicable review and
stage/contract decision gates are complete.

## CI direction (not yet implemented)

The agreed future CI direction has separate documented checks for docs/static
consistency, focused normal-code behavior, scientific-core regressions, and
full-suite milestone/release gates. It must retain current assurance and should
be introduced only after duration/flakiness are measured and the change is
reviewed. Existing workflows remain authoritative until that migration lands.
