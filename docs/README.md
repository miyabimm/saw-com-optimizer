# Documentation index

This is the sole index of current project documentation. Use the five current
sources below for operating policy. Dated plans and reconstruction records are
retained as audit evidence, not as current implementation instructions.

## Current sources of truth

- [Roadmap](roadmap.md) — product goal, stage gates, scientific status, and
  interpretation limits.
- [Architecture](architecture.md) — checked-in package ownership, supported
  CLI boundary, and future target ownership.
- [Physics and numerical conventions](physics.md) — implemented COM equations,
  units/signs, network/port conventions, metrics, grids, and analytic tests.
- [Development](development.md) — Docs-first workflow, risk-based tests, review
  responsibilities, environment commands, and CI status.
- [Experiments and data](experiments.md) — authorization, frozen conditions,
  historical preservation, raw storage, and review schema.

## Scoped and historical records

These records preserve evidence or define a specific gate; they do not replace
the five current sources above or independently authorize implementation or
execution:

- [Issue #146 M0 dependency and caller audit](../reports/restructure/m0_dependency_audit_20261025.md)
  is a static-only, exact-base inventory and unapproved M1–M4 proposal; it does
  not authorize source moves/deletions or execution.
- [Stage 5A-2 Q1 qualification matrix](plans/stage5a2_q1_qualification_matrix.md)
  is the sole formal Q1-01…Q1-23 gate list. The [Q1 execution plan](plans/stage5a2_q1_execution_plan.md)
  describes work-unit dependencies but does not pass a gate or authorize
  Q1-B/C/D/E.
- [Q0 closeout](history/stage5a2_q0_closeout_20261021.md) records the accepted
  comparison protocol. The [historical baseline](history/current_baseline.md),
  [experiment register](history/experiment_register.md), and stage closeouts
  preserve reviewed findings and limitations.
- [R0 preservation inventory](../reports/restructure/r0_preflight_inventory_20261022.md)
  records the verified copy and its limits. [R6-L4 reconstruction closeout](history/r6_l4_closeout_20261025.md)
  records the software inventory, CI disposition, deferred work, and proposed
  issue closeout; it is an audit record, not a new product or scientific gate.
- [Issue #155 compatibility audit](audits/issue155_stage5a_compatibility_audit.md)
  and [config-driven CLI design](plans/issue155_config_driven_cli_design.md)
  record a scoped Stage 5A evidence audit and implementation proposal only;
  they do not authorize code changes to scientific behavior or any run.

Older reconstruction plans, handoffs, and issue-specific designs remain in
Git where useful for audit. They are dated evidence, not current operating
instructions. The five current sources above govern general policy; the listed
Q1 matrix and historical records remain authoritative only for their named
scope.

## Legacy paths

[`project_roadmap.md`](project_roadmap.md) and
[`architecture_overview.md`](architecture_overview.md) are retained as
compatibility pointers to [roadmap.md](roadmap.md) and
[architecture.md](architecture.md), respectively. Older guides, handoffs,
agent procedures, and stage plans are historical material, not independent
current policy. Do not follow old operational procedures unless separately
re-authorized and consistent with the current sources above.
