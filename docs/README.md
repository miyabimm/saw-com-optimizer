# Documentation index

This is the sole index of current project documentation. For each topic, use
the canonical source below; old plans and detailed guides are retained only as
evidence unless linked here as supporting references.

## Current sources of truth

- [Roadmap](roadmap.md) — product goal, stage gates, current scientific status,
  and interpretation limits.
- [Architecture](architecture.md) — current package ownership, dependency
  direction, target layout, and staged module migration.
- [Physics and numerical conventions](physics.md) — implemented COM equations,
  units/signs, network/port conventions, metrics, grids, and analytic tests.
- [Development](development.md) — Docs-first workflow, risk-based tests, PR
  responsibilities, environment commands, and CI status.
- [Experiments and data](experiments.md) — authorization, frozen conditions,
  historical preservation, raw storage, and the review schema.

## Authoritative supporting records

These records are authoritative only for their stated subject and do not
supersede the five current sources above:

- [Stage 5A-2 Q1 qualification matrix](plans/stage5a2_q1_qualification_matrix.md)
  is the sole formal Q1-01…Q1-23 gate list.
- [Stage 5A-2 Q1 execution plan](plans/stage5a2_q1_execution_plan.md) defines
  work-unit dependencies; it does not pass gates or authorize Q1-B/C/D/E.
- [Q0 closeout](history/stage5a2_q0_closeout_20261021.md) records the accepted
  comparison protocol and distinct approval/closure events.
- [Current historical baseline](history/current_baseline.md),
  [experiment register](history/experiment_register.md), and stage closeouts
  retain reviewed historical findings and limitations; they are not a new
  implementation plan.
- [R0 preflight inventory](../reports/restructure/r0_preflight_inventory_20261022.md),
  [reconstruction design](plans/repository_restructure_decisions_20261022.md),
  [migration plan](plans/repository_restructure_migration_plan_20261022.md),
  [R3 ownership/caller disposition](plans/restructure_r3_ownership_20261022.md),
  [R4 optimizer ownership inventory](plans/restructure_r4_ownership_20261022.md),
  [R6 software/evidence inventory](plans/restructure_r6_ownership_20261023.md),
  [R7 architecture/CI audit proposal](plans/r7_architecture_ci_audit_20261023.md),
  [Issue #77 async/resume design](plans/issue77_async_resume_design_20261023.md),
  [Issue #80 synthetic task contract](plans/issue80_synthetic_task_contract_20261023.md),
  [Issue #82 synthetic-recovery contract](plans/issue82_synthetic_recovery_contract_20261023.md),
  [Issue #84 mock-only Pi-session contract](plans/issue84_pi_session_mock_contract.md),
  [Issue #94 R6-C migration/three-continuity design](plans/issue94_r6c_three_resume_migration_design_20261024.md),
  [Issue #96 N1 transaction/recovery contract](plans/issue96_n1_synthetic_transaction_recovery_20261024.md),
  and [Issue #75 Codex retirement policy (2026-10-24)](plans/issue75_legacy_codex_retirement_decision_20261024.md)
  record staged reconstruction work. The [Issue #106 C0 static caller/evidence inventory](plans/issue106_r6c0_codex_removal_inventory_20261024.md)
  and [Issue #108 C1 disposition](plans/issue108_r6c1_codex_removal_20261024.md)
  are dated records; the old Codex queue/callback runtime and legacy Stage 4B/4C
  production entrypoints were retired in merged PR #109 at
  `604091d550c8fad302ed179e3e177d3a1ee3c7c1`. The [Issue #111 C2A disposition](plans/issue111_r6c2a_legacy_surface_disposition_20261024.md)
  records the project-local hook and current-facing documentation cleanup
  submitted in PR #112; its review and merge disposition are tracked by that
  PR, not by this index. The [Issue #113 C2B0 inventory](plans/issue113_r6c2b0_legacy_owner_caller_inventory_20261024.md)
  is a docs-only static caller/safety map; it authorizes no source deletion.
  The [Issue #118 Stage 4C execution retirement record](plans/issue118_r6c2b3a_stage4c_execution_retirement_20261024.md)
  documents the software-only removal of obsolete Stage 4C/WSL qualification
  executables and its preserved evidence; it does not authorize experiments.
  The [Issue #119 cutover record](plans/issue119_r6c2b2a_legacy_cli_cutover_20261024.md)
  documents the separately owner-approved old CLI/orchestration deletion;
  [PR #121](https://github.com/miyabimm/saw-com-optimizer/pull/121) merged to
  `main` at `06c71c29a3648f5e60015b3fbc06a375e2f2936d`, and [merged-main CI
  #40104807026](https://github.com/miyabimm/saw-com-optimizer/actions/runs/40104807026)
  passed on Haswell (721/721 tests). The [Issue #124 reporting owner
  disposition](plans/issue124_r6c2b5_reporting_owner_disposition_20261025.md)
  records the later removal of the old schema-v1–v4 review exporter while
  preserving the distinct R5 schema and historical evidence; it authorizes no
  scientific run or data operation. Other C2B follow-up work and R7 remain
  separate owner gates. Historical documents that describe earlier
  active paths remain dated evidence, not current instructions. The R3 and R4
  records are scoped to Issues #65 and #67; R6 is scoped to Issue #71's
  software/synthetic-only authorization; R7 is an audit/CI evidence and
  owner-decision proposal under Issue #74; Issue #77 is a design proposal;
  Issue #80 authorizes only isolated synthetic PR-A implementation; Issue #82
  authorizes only isolated synthetic countdown recovery; Issue #84 authorizes
  only a fake Pi-session adapter; Issue #94 records a docs-only/static design
  audit; and Issue #96 authorized only its bounded test-owned synthetic N1
  implementation. None authorizes real Pi runtime/session use or scientific
  work. The owner-approved retirement does not require Pi-session parity or
  historical Stage4B fingerprint reconstruction. No plan authorizes Q1
  qualification, real experiments, or production runs.

## Legacy paths

[`project_roadmap.md`](project_roadmap.md) and
[`architecture_overview.md`](architecture_overview.md) are retained as
compatibility pointers to [roadmap.md](roadmap.md) and
[architecture.md](architecture.md), respectively. Older guides, handoffs,
agent procedures, and stage plans are historical or supporting material, not
independent current policy. Do not follow an old operational procedure unless
it is explicitly re-authorized and consistent with the current sources above.
