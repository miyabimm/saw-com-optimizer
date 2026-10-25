from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import yaml

from sawopt.design.space import FilterDesign
from sawopt.design.topology import FiveIdtDesign, ParallelThreeIdtDesign, T1, T2
from sawopt.evaluation import evaluate_design, report_grid, search_grid, simulate_topology, validation_grid
from sawopt.physics.com import FixedProvider


ROOT = Path(__file__).resolve().parents[2]


def _array_sha256(values, dtype):
    array = np.ascontiguousarray(np.asarray(values, dtype=dtype))
    return hashlib.sha256(array.tobytes()).hexdigest()


def test_frozen_search_grid_and_separate_validation_report_grids():
    # Retain the frozen grid contract without loading a retired study config.
    baseline = yaml.safe_load((ROOT / "configs/base/b28_dms_baseline.yaml").read_text())
    spec = baseline["spec"]
    search = search_grid(spec)
    validation = validation_grid(spec)
    report = report_grid(spec)

    assert len(search) == 1001
    assert _array_sha256(search, "<f8") == (
        "212dd2b0b71ddeffb7a8865937d132ee596870f25c989ac7d90c5dab6fd7faa0"
    )
    assert len(validation) == 8352
    assert _array_sha256(validation, "<f8") == (
        "f9dd32ad1586266f107320c7cd9f7e69b57dbd5d80ae4606b9ea127c98fcf28f"
    )
    assert len(report) == 7454
    assert _array_sha256(report, "<f8") == (
        "cebcd16fcc94dca1f928f15e05215f407c6f84c619fc95e1a20a2dbacac027d7"
    )
    assert np.array_equal(search, np.unique(search))
    assert np.array_equal(validation, np.unique(validation))
    # Legacy report_grid uniquifies MHz construction points before converting
    # to Hz, so five post-scaling duplicates are part of the frozen grid.
    assert len(report) - len(np.unique(report)) == 5
    assert not np.array_equal(search, validation)
    assert not np.array_equal(validation, report)


def test_filter_evaluation_matches_pinned_baseline_arrays_and_metrics():
    base = yaml.safe_load((ROOT / "configs/base/b28_dms_baseline.yaml").read_text())
    hybrid = yaml.safe_load((ROOT / "configs/studies/hybrid_50ohm.yaml").read_text())
    cfg = {**base, **hybrid}
    cfg["com"] = yaml.safe_load((ROOT / "configs/models/com_params_hypothetical.yaml").read_text())
    frequencies = search_grid(cfg["spec"], cfg)

    record, network, simulation = evaluate_design(FilterDesign(), cfg, frequencies, 37.0, 91.0)

    assert len(frequencies) == 1001
    assert _array_sha256(simulation.y_parameters, "<c16") == (
        "6c21974996f08352b09f19d32f403cd13d5dc831d42cebe3157c7dbfa0ca49a5"
    )
    assert _array_sha256(network["s"], "<c16") == (
        "eee9da5fd0a706293f343faa2c20be72da71adc4791f72d7d136d9af8e273cdc"
    )
    assert _array_sha256(network["gt"], "<f8") == (
        "7c5a8e47cfddf62be58261225824d29839eee8123d92fd3d2320b2777c4ffd19"
    )
    assert record["metrics"]["worst_il_db"] == 16.361589714409646
    assert record["metrics"]["ripple_db"] == 11.753714283126023
    assert record["violations"]["output_vswr"] == 4.028196829407298
    assert record["search_scalar_objective"] == record["objective"]


def test_t1_and_t2_evaluation_adapters_preserve_exact_response_arrays():
    values = yaml.safe_load((ROOT / "configs/models/com_params_hypothetical.yaml").read_text())
    provider = FixedProvider(values)
    frequencies = np.asarray([730e6, 758e6, 780e6, 803e6, 830e6], dtype=np.float64)

    t1 = simulate_topology(FiveIdtDesign(), provider, frequencies, T1)
    t2 = simulate_topology(ParallelThreeIdtDesign(), provider, frequencies, T2)

    assert _array_sha256(t1.y_parameters, "<c16") == (
        "4ee60a4ae1831825d46fdbc7d82ab54264235642e02e54e0b639962a9d51dbdc"
    )
    assert _array_sha256(t2.y_parameters, "<c16") == (
        "1f5a5bb278d35cc3070adf0f499c92705ba9b38f7dde57ffd8f09de13d22d3fd"
    )
    assert t1.diagnostics["port_matrix"] == [
        [1.0, 0.0], [0.0, -1.0], [1.0, 0.0], [0.0, -1.0], [1.0, 0.0],
    ]
    assert t2.diagnostics["track_count"] == 2
