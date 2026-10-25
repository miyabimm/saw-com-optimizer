# Current helper scripts

Scripts here are verification and diagnostic utilities, not study launchers.
The current CLI (`sawopt` / `python -m sawopt.cli`) is synthetic/injected-only; no
script authorizes COM/FE, optimizer qualification, production, or historical
raw/checkpoint access. Follow the active policies in
[`docs/README.md`](../docs/README.md), especially
[`docs/development.md`](../docs/development.md) and
[`docs/experiments.md`](../docs/experiments.md).

Retained utilities include:

- `verify_r2_physics_parity.py`: deterministic fixed-input digests through the
  current physics/evaluation owners; it contains no historical-module fallback.
- `verify_stage5a2_canonicalization_golden.py`: checks all 92 frozen cases
  through the canonical `design.space` API and the pure
  `design.canonicalization` leaf.
- `check_stage5a2_foundation_imports.py` and
  `check_stage5a2_pure_leaf_import.py`: preserve the Q1-A import boundaries.

Stage 3/4 study execution, historical audit/report generation, legacy
PowerShell launchers, and one-off power/plot scripts were retired under Issue
#129. Their historical reports and source/evidence identities remain records;
no old entrypoint or replacement compatibility layer is provided.
