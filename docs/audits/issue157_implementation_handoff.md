# Issue #157 — synthetic-task CI race diagnosed and test synchronized

## Current status — bounded repair complete; exact-head CI pending

The owner authorized a bounded, software-only investigation of the synthetic-task
identity-mismatch test failure on PR #158. The test-only repair is committed at
**`a5ecf0eda5b8b38cb65e5c964bba5df282cb6e7a`**. It changes only
`tests/integration/test_synthetic_task_worker.py`; no worker/ledger production
semantics, schema contracts, CI policy, COM physics, optimizer behavior or
research conditions changed.

### Diagnosis and deterministic fixture repair

The failing fixture changed the recorded worker identity while its live worker
continued polling at 100 ms intervals. A bounded local reproduction of the
`owner_boot_id` case observed the exact test-owned PID, boot ID and start ticks
in `/proc`, state `S`, and the expected worker argv both immediately before the
SQLite mutation and immediately before `get_status`; the test-owned log showed
spawn intent, claim, and progress `1/40`, with no worker-error entry at that
point. One such run returned `RECOVERY_REQUIRED` (reproducing the reported
assertion failure); another returned `PROCESS_IDENTITY_UNKNOWN` while the worker
remained live. This confirms the scheduling window: the worker can observe the
forged identity and exit between the parent’s last process check and its status
inspection. `RECOVERY_REQUIRED` is the existing dead-worker result, not a
relaxable alternative for the live identity-mismatch assertion. The exact
`/proc` state at the internal lookup in the failing local run was not captured,
so this record does not claim whether it was a zombie or already reaped.

The fixture now verifies the worker's exact PID, boot ID, start ticks and
expected argv, sends `SIGSTOP` only to that verified test-owned child, and
confirms the same identity remains live in stopped state before SQLite
mutation. It then retains the strict `PROCESS_IDENTITY_UNKNOWN` and stop
refusal assertions, verifies the stop API made zero intercepted `os.kill`
calls (no signal reached a foreign process) and the parent identity did not
change, and checks that the worker is still stopped
and exact-identity-owned afterward. A `try/finally` cleanup re-verifies the
worker identity/argv before `SIGKILL` and waits for exit/zombie state. The
separate dead-worker test still expects `RECOVERY_REQUIRED`. No production task
ledger or worker behavior was changed.

### Validation on implementation commit

- Bounded identity-mismatch variants plus the separate dead-worker case:
  **4 passed**.
- Relevant synthetic-task, scientific-config, R5 storage/review, public-import,
  synthetic CLI and Q1-A suites (combined focused command): **254 passed**.
- Official local full pytest, with CI's test-only BLAS dispatch:
  `OPENBLAS_CORETYPE=Haswell uv run --locked pytest` — **470 passed**.
- Fixed-input COM diagnostic:
  `uv run --locked --extra test --extra benchmark python tools/diagnostics/evaluation_repro.py`
  — **exit 0**. On the implementation commit, all four expected-hash groups
  matched and all four rank-input comparisons matched. This was ordinary fixed
  input software regression, not a research or optimizer qualification run.
- Exact-head GitHub CI on published head
  `dc97536f5ab75d935819098d62030c3780245e8f` is **PASS**:
  [CI #40356185505](https://github.com/miyabimm/saw-com-optimizer/actions/runs/40356185505)
  completed both the fixed-evaluation diagnostic and full pytest job. This is
  remote CI evidence, not independent scientific-schema acceptance.
- A later documentation-only evidence update may trigger the normal automatic
  workflow; its final exact-head result is recorded in the PR notes. Keep PR
  #158 Draft and unmerged pending independent review. No scientific run, Q1
  qualification, replay or data mutation was performed.

## Prior exact-head CI blocker (historical evidence; now addressed below)

Implementation HEAD `64da58ee7c07bceacc932438d9a85f88fedf8719`:
[CI #40344621589](https://github.com/miyabimm/saw-com-optimizer/actions/runs/40344621589)
**FAILURE**. Fixed-input COM diagnostic PASS; pytest **469 passed / 1 failed**
in 56.26 s. The new 22 F1–F4 cases, original scientific-config fresh-process
guards, lazy public-API, synthetic CLI, R5 and Q1-A suites passed in this run.

Exact failing test:
`tests/integration/test_synthetic_task_worker.py::test_pid_reuse_or_boot_mismatch_fails_closed_and_stop_never_signals_foreign_pid[owner_boot_id]`
at line 285. `ledger.get_status(run_id).state` returned `RECOVERY_REQUIRED`;
the assertion expected `PROCESS_IDENTITY_UNKNOWN`. That test and the task-ledger implementation were not changed by this revision. Local full
pytest passed 470/470, but that did not override the observed CI failure. Cause
and reproducibility were **unclassified at the time of this
record**; the later bounded diagnosis and deterministic test-only repair are
documented at the top of this handoff. The failed CI remains historical
failure evidence and is not erased by subsequent local checks.

At that time, the failure-stop instruction prevented changes or diagnosis.
Subsequent owner authorization permitted only the bounded software test
investigation recorded above. This historical stopped state is superseded; PR
#158 remains Draft and unmerged pending exact-head CI and independent review.
The F1–F4 repairs below remain separate from this synthetic-task test repair.
No scientific execution or policy change is involved.

## Current revision: PR #158 independent-review corrections

The independent review of HEAD `8a8200f5bbdbfbb9cf97566feed6c9e5461c5992`
required F1–F4 changes; the owner instructed correction on this same Draft PR.
The following results supersede the earlier import-repair handoff **for the
current revision**. The earlier evidence below is retained as historical
context, not as the current example identity or current test count. Exact
revised HEAD and new-head CI are reported in the PR after push.

### Corrections and bounded decisions

- **F1 — R5 context:** require the eighth field `findings` with the exact
  config-author-supplied status `NOT_EVALUATED: no experimental findings;
  declaration only.` No experimental findings are fabricated. The effective
  context passes existing `REVIEW_CONTEXT_FIELDS` / `_validate_review_context`
  unchanged; a structural test checks this without creating a scientific run.
  There is no future adapter implemented or implicitly required to fill a
  missing field. Full configured evaluator/R5 integration and result-reporting
  lifecycle are still unimplemented and separately gated.
- **F2 — identity:** match R5's UTF-8 `ensure_ascii=False` canonical JSON bytes,
  with unchanged key sorting, array order, finite binary64 rendering and signed
  zero. Tests compare exact bytes and digests with R5 for ASCII, Japanese,
  combining characters/emoji, finite binary64 cases, signed zero and reordered
  mappings; Unicode effective snapshots are also checked across a fresh CLI
  process. The validator's `effective_config_sha256` equals R5's
  `scientific_config_sha256` **only for the identical effective mapping**.
  R5's implementation/history is untouched; this corrects the unaccepted v1
  proposal rather than adding a second identity namespace.
- **F3 — fixed design:** narrow accepted `design.fixed` to the named decoder's
  exact defaults (0.5 metallization ratio, 0.04 thickness/wavelength). Nondefault
  values fail closed. Pure decode/canonical-vector tests cross-check the
  declarations against the unchanged decoder. No design/physics adapter or
  source-decoder change was introduced. Future nondefault support requires
  separately specified/qualified mapping; this does not enable execution.
- **F4 — YAML:** restore original `yaml.safe_load` behavior for synthetic files.
  Dispatch safe-loads once to identify a root `schema_id`, then reparses the
  **same bytes** with the strict scientific loader if that key is present.
  There is no scientific parse-failure fallback. New tests prove synthetic
  scalar aliases work through both loaders and CLI validate/run/review, while
  scientific scalar/grid aliases, merges, duplicate fields/discriminators and
  mixed-schema alias requests fail. No historical study adapter was added.

Specs were updated before new tests/implementation in
`docs/scientific_config_v1.md`. `docs/roadmap.md` now explicitly states that
this seven-variable single-filter subset does not accept hybrid P_D/D_P Q0
inputs, establish Stage 5A readiness, or treat source-Git optimizer version as
Q0's semantic algorithm identity. No broader scientific-policy decision was
needed: these choices follow the review's explicit bounded repair alternatives.

### Current local checks

- Focused RED: `uv run --locked pytest -q tests/integration/test_scientific_config_contracts.py`
  — **9 failed / 12 passed**, reproducing all four findings before implementation.
- Initial GREEN (before adding synthetic alias run/review case):
  `uv run --locked pytest -q tests/integration/test_scientific_config_contracts.py tests/integration/test_scientific_config.py tests/unit/io/test_public_imports.py`
  — **107 passed**.
- Final focused command: the seven suites listed in the earlier GREEN command
  below **plus** `tests/integration/test_scientific_config_contracts.py`:
  **224 passed**, 68.15 s. The new file has 22 cases.
- `OPENBLAS_CORETYPE=Haswell uv run --locked pytest` — **470 passed**, 120.17 s,
  no failures/skips. This BLAS setting is CI's test-only dispatch precondition.
- `uv run --locked --extra test --extra benchmark python tools/diagnostics/evaluation_repro.py`
  — **exit 0** (stdout parsed by a piped `uv run --locked python -c` JSON
  summarizer under `set -o pipefail`). All expected hash checks matched in four
  subprocess variants, repeat rank inputs matched, and all three cross-process/
  BLAS comparison groups reported zero changed array cells locally.
- Both Q1-A import guard scripts and both CLI help commands listed below pass.
- `git diff --exit-code 8a8200f -- src/sawopt/io/__init__.py tests/integration/test_scientific_config.py`
  — PASS: lazy public API implementation and **the entire original scientific
  config test file, including both fresh-process guards, remain unchanged**.
- `git diff --check` — PASS.

No actual scientific R5 run was created by structural tests. The alias run is
only the existing tiny synthetic fixture, under test-owned temporary external
storage/review roots. Fixed-input COM / deterministic optimizer calculations
remain ordinary software regression, not research or qualification evidence.

### Current observed CLI output

The real scientific `validate` CLI succeeds with `schema_valid: true`,
`qualification: NOT_EVALUATED`, `run_authorized: false`,
`scientific_run_implemented: false`. The example now explicitly includes
pre-run findings, so its config/effective identities change:

| field | current SHA-256 |
|---|---|
| config_file_sha256 | `7039ec1cc577b37cd40dcb44744bec8af39fe249fc7e7b97f049efda46f30f7c` |
| effective_config_sha256 | `d0a5146dcdada34dd912577dbf9eabf30cd849cd7e8ca08115ae4d3c501e5236` |

The three input payloads/hashes remain unchanged from the earlier evidence.
The synthetic example's validate JSON remains byte-for-byte unchanged. The
real scientific `run` still returns exit 2 with
`error.code: SCIENTIFIC_RUN_NOT_IMPLEMENTED`. CLI commands are the same as
below; scientific validate stdout was piped through a JSON display-only
summarizer omitting `effective_config` (no file writes).

No known local failures remain. Keep Draft/unmerged: independent re-review of
F1–F4, scientific declaration semantics and complete diff is still required.
Scientific run remains unavailable; no research study, Q0/Q1 qualification,
historical replay/migration or scientific authorization change was performed.

## Earlier import-repair handoff (historical, superseded above)

### Baseline, authorization and disposition

- Baseline: `a215c2a0a96c9ce2670e38e1901d49ea0b9c9cab` (PR #156).
- Branch: `issue157-scientific-config`; [Draft PR #158](https://github.com/miyabimm/saw-com-optimizer/pull/158).
- Initial draft: `5c344f1a30c98ec296d885982392fde9f93b3f72`.
- Import-repair code/test commit: `3f08fb7a9cb2d22331542aa2fd087c51b14f0a6b`.
  The final handoff HEAD is reported in the PR; later documentation-only
  commits do not change the tested code.
- The [reviewer decision](https://github.com/miyabimm/saw-com-optimizer/pull/158#issuecomment-6418334945)
  and owner's continuation instruction authorize only the narrow software import
  repair and bounded regressions. They do not accept the scientific schema or
  authorize configured scientific execution.

The prior stopped state is **superseded**: the import blocker is repaired and
local checks pass. Independent full schema/code review is still required. Keep
this PR Draft; do not merge or advance configured execution from this handoff.
No new scientific/optimizer study, Q0 experiment, Q1 qualification, production,
historical replay or raw-data migration was performed. Fixed-input COM and tiny
deterministic optimizer calculations ran only as authorized software checks.

## Draft implementation and minimal repair

- Normative field/unit/subset/identity draft: `docs/scientific_config_v1.md`.
- Strict safe YAML dispatch in `io.cli_config`, pure scientific validator and
  read-only hash-pinned input resolver in `io.scientific_config`.
- CLI scientific validation snapshot/identities and rejected scientific run.
- Validation-only hypothetical example, not an executable research config.
- Supported subset excludes hybrid/Q0, calibrated/literature providers,
  complex ports, comparison rosters and scientific execution.

Originally `io/__init__.py` eagerly imported R5 storage before the CLI could
reach validation. The repair changes only that initializer's import behavior:
PEP 562 `__getattr__` checks the existing six-name `__all__` allowlist, uses
absolute `import_module("sawopt.io.experiment_store")` to avoid recursive package
attribute resolution, and returns the original implementation object. Unknown
attributes raise `AttributeError` before importing R5. No object wrappers,
duplicate implementations, plugins or storage-semantic changes were added.
Public exports and `__all__` remain unchanged. No optional introspection API was
needed. There is no dependency from `cli_config` to `experiment_store`.

`tests/unit/io/test_public_imports.py` verifies in four fresh processes:
attribute access, explicit from-import, star import, and direct implementation
import before public-symbol access; all six objects and both exception classes
retain exact identity. Merely importing `io` or `io.cli_config`, or looking up an
unknown attribute, does not import R5. Exception catch behavior is checked for
both `RunValidationError` (ValueError) and `RunStorageError` (OSError).

Both original scientific fresh-process guards are unchanged **byte-for-byte**:
`git diff --exit-code 5c344f1 -- tests/integration/test_scientific_config.py`
passes. They reject physics/design/evaluation/problem/optimizer/studies/R5/
reporting/checkpoint imports and filesystem writes, environment mutation and
subprocess creation. They now pass for validate and rejected run with an invalid
`SAWOPT_DATA_ROOT`, without source/data-root preflight or raw-store creation.

## Local verification — exact commands/results

Tests ran on Ubuntu/WSL2, locked uv, Python 3.12.3. Full pytest uses CI's
**test-only** `OPENBLAS_CORETYPE=Haswell`; production environment policy is
unchanged. The full suite and diagnostic ran against the worktree changes
subsequently committed as `3f08fb7`; the diagnostic's Git revision field still
reported prior HEAD `5c344f1` at execution time, not a clean-tree attestation.

### RED and test-authoring correction

- Initial implementation RED (before resolver):
  `uv run --locked pytest -q tests/integration/test_scientific_config.py::test_snapshot_and_normalization`
  — **1 failed**, missing `load_cli_config`.
- Initial implementation suite: `uv run --locked pytest -q tests/integration/test_scientific_config.py`
  — **80 passed / 2 failed**, the eager-import blocker; implementation stopped.
- Authorized repair RED: `uv run --locked pytest -q tests/unit/io/test_public_imports.py`
  — **4 failed** at the expected eager-import assertion.
- First repair focused run: **198 passed / 4 failed**. The four failures were an
  incorrect assertion in the *new test* that `RunValidationError` subclasses
  `RunStorageError`. Source inspection confirmed the existing independent
  ValueError/OSError bases. Corrected the new test to assert those existing bases
  and identity/catch behavior for both classes; no production exception/API or
  original guard was changed. No deeper public-API regression was observed.

### GREEN

```bash
uv run --locked pytest -q \
  tests/unit/io/test_public_imports.py \
  tests/integration/test_scientific_config.py \
  tests/integration/test_synthetic_cli.py \
  tests/unit/io/test_experiment_store.py \
  tests/integration/test_review_export_cli.py \
  tests/unit/studies/test_stage5a2_foundation.py \
  tests/unit/physics/test_import_boundaries.py
```

**202 passed**, 64.94 s. This includes 82 scientific-config cases, four new
public-import cases, synthetic validate/run/review, R5 storage/export, Q1-A
foundation and physics import-boundary regressions.

```bash
OPENBLAS_CORETYPE=Haswell uv run --locked pytest
```

**448 passed**, 127.64 s. No skipped or failing tests. This includes remaining
architecture, synthetic-task, R5 review, checkpoint and numerical unit fixtures.
It is not formal Q1 qualification or integrated scientific parity acceptance.

```bash
uv run --locked --extra test --extra benchmark python tools/diagnostics/evaluation_repro.py
```

**Exit 0**. Existing fixed-input COM numerical reproducibility diagnostic;
expected hash checks matched in all four subprocess variants, same-process
repeat arrays/rank inputs matched, and default-versus-forced-Haswell array
comparisons had zero changed cells locally. No new research study was executed.
No diagnostic output was committed as a raw/scientific artifact.

Additional checks, all successful:

```bash
uv run --locked python scripts/check_stage5a2_foundation_imports.py
uv run --locked python scripts/check_stage5a2_pure_leaf_import.py
uv run --locked sawopt --help
uv run --locked python -m sawopt.cli --help
git diff --exit-code 5c344f1 -- tests/integration/test_scientific_config.py
git diff --check
```

Both Q1-A import scripts report `forbidden_imports: []`. Help lists only the
supported validate/run/review/synthetic-task boundary; no scientific executor.

## Observed CLI behavior and identities

`uv run --locked sawopt validate --config configs/examples/r6_synthetic_smoke.yaml`
returns the existing JSON unchanged:

```json
{"experiment_id":"r6-synthetic-smoke","method":"lshade","search_fe_limit":8,"status":"VALID","synthetic_only":true,"validation_points":3}
```

Scientific validate is exercised through the real CLI by repeat-process and
unchanged fresh-process guard tests. It returns `status: VALID`, `schema_valid:
true`, `qualification: NOT_EVALUATED`, `run_authorized: false`,
`scientific_run_implemented: false`, the effective snapshot and these observed
example identities (also manually read through `load_cli_config`):

| field | SHA-256 |
|---|---|
| config_file_sha256 | `dd7301c5f867677c0e95f23abe46cf59b539edf6cb71a39290d69fd731f33f79` |
| effective_config_sha256 | `e85d07b426bb66d7150245393e1695cf32d44336df22ac637a40793f70b4df33` |
| input_sha256.model | `691536cdb91bf38cf2140ab6241ac704a8f93abeb47de60e5d8e067ff8c42692` |
| input_sha256.search_grid | `a0b906309b671b8c403c6de47a9a2afcd5cda58c6f581a3fd5826dfab6bc9fa6` |
| input_sha256.validation_grid | `3aae08f44a030aa5f583d7bc19f0a6999d56914c73e48e72cd91a52c2c741778` |

`uv run --locked sawopt run --config configs/examples/scientific_validation_only.yaml`
returns **exit 2**, stderr:

```json
{"error":{"code":"SCIENTIFIC_RUN_NOT_IMPLEMENTED","message":"scientific declarations support validation only; no execution is available"}}
```

No manual synthetic research run was launched. Existing synthetic run/review
contracts were checked by tests using test-owned temporary external roots.

## CI versus local evidence / review limits

The reviewer recorded initial-head CI [#40298364210](https://github.com/miyabimm/saw-com-optimizer/actions/runs/40298364210)
as diagnostic success and **442 passed / 2 failed** (both original import guards).
That is historical initial-head evidence, not the repaired-head CI result.
New-head CI status and exact final HEAD are published in the PR after push;
local results above must not be represented as GitHub CI or independent review.

The scientific schema remains draft and needs independent review of supported
subset, scientific identity, nested-field/order/hash mutation coverage, strict
failure behavior and compatibility limits. No schema semantics were expanded
in this repair. Source/version/environment hashes are caller declarations, not
attestation; config hashes establish neither Q0 parity nor physical validity.
Q0/Q1-A/Q1 gates and all experiment authorizations remain unchanged. No known
local test failure or import blocker remains; independent full acceptance is
unresolved. This work does not enable scientific `run`.
