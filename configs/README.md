# Configuration and test inputs

The supported CLI accepts the strict synthetic example at
[`examples/r6_synthetic_smoke.yaml`](examples/r6_synthetic_smoke.yaml). It does
not accept historical study YAML or launch COM/FE or optimizer research.

The following files remain fixed numerical-regression or Q1-A identity inputs,
not supported run configurations:

- `base/b28_dms_baseline.yaml`, `models/com_params_hypothetical.yaml`, and
  `studies/hybrid_50ohm.yaml` for current physics/evaluation regressions.
- `studies/dms_topology_screening.yaml`, `models/stage3_7b_r1_normalized_literature_profile.yaml`,
  and `reference/dms_topology_screening/` for retained DMS reference coverage.
- `studies/hybrid_stage4a_qualification.yaml` and
  `studies/hybrid_stage4c_confirmatory.yaml` as frozen Q1-A identity/contract
  inputs; their historical executors are not retained.

The old study configuration loader, Stage 3.9B/Stage 4B execution-only
configurations, and historical review/ZIP workflow are retired. Retained YAML
and reference inputs do not authorize re-execution. For authorization and
historical-data boundaries, see
[`docs/experiments.md`](../docs/experiments.md).
