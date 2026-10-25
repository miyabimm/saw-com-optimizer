# DMS topology reference inputs

These immutable inputs preserve the validation grid and initial-design
identities used by historical Stage 3.8C/DMS work and retained numerical parity
tests. Their purpose is reference/evidence coverage; the former DMS screening
optimizer and report workflow were retired under Issue #129. These files do
not constitute a supported study configuration or authorize a run.

- `common_validation_grid_hz.csv` has 9,113 points and canonical LF-content
  SHA-256 `54c1daf67dd2bb9242f95e638d7bd801db536acc2c7d6f00c1f62a788bead554`.
  Its grid identity is
  `2e24c4ce3f96c38baba44dc83bc60f95954a6b677cb2a37d63078e78c4cea42f`.
  The source run file and metadata hashes are recorded in
  `common_validation_grid.json`.
- `initial_designs/M0.json` and `initial_designs/MLIT.json` preserve the exact
  design dictionaries used as reference inputs. Their source run files and
  SHA-256 values are in `initial_design_origins.json`.

The archived run directories, reports, and evidence remain untouched. Do not
recreate the old runner or interpret these fixtures as permission to access
historical raw data or launch new work.
