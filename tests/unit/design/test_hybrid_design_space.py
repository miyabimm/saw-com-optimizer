import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from sawopt.design.geometry import hybrid_geometry
from sawopt.design.space import HybridDesignSpace
from sawopt.design.topology import decode_t1
from sawopt.evaluation import resonator_admittance
from sawopt.physics.com import FixedProvider


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/stage5a2/q0_design_space_contract.json"


def _space(topology):
    fixture = json.loads(FIXTURE.read_text())
    record = next(item for item in fixture["topologies"] if item["topology"] == topology)
    bounds = np.frombuffer(bytes.fromhex(record["bounds_le_f64_hex"]), dtype="<f8")
    bounds = bounds.reshape(record["dimension"], 2)[:10].copy()
    return HybridDesignSpace.from_contract(topology, bounds, bounds)


def _layout_config():
    return {
        "constraints": {
            "max_length_um": 750,
            "max_width_um": 250,
            "min_electrode_width_um": 0.8,
            "min_electrode_gap_um": 0.8,
            "max_electrodes": 500,
        },
        "hybrid": {
            "resonator_aperture_bounds_um": [30, 150],
            "layout": {
                "die_um": [900, 700],
                "length_margin_um": 60,
                "width_margin_um": 60,
                "max_total_electrodes": 500,
            },
        },
    }


def test_t1_decode_uses_canonical_design_and_topology_owners():
    space = _space("D")
    vector = np.mean(space.bounds, axis=1)
    candidate = space.decode(vector, reflector_electrodes=40)
    expected = decode_t1(candidate.vector[:10], reflector_electrodes=40)
    assert candidate.dms_design == expected


def test_resonator_rounding_preserves_canonical_identity():
    space = _space("P_D")
    vector = np.mean(space.bounds, axis=1)
    vector[11] = 21.1
    first, first_key = space.canonicalize(vector)
    vector[11] = 21.49
    second, second_key = space.canonicalize(vector)
    assert first[11] == second[11] == 21
    assert first_key == second_key == tuple(first)
    vector[11] = 21.5
    rounded, _ = space.canonicalize(vector)
    assert rounded[11] == 22
    assert space.decode(first).resonator_designs[0].pairs == 21


def test_bounds_validate_against_the_canonical_hard_contract():
    space = _space("D")
    active = space.bounds.copy()
    hard = space.bounds.copy()
    active[0, 0] -= 0.1
    with pytest.raises(ValueError):
        HybridDesignSpace.from_contract("D", active, hard)
    with pytest.raises(ValueError):
        HybridDesignSpace.from_contract("S_D", space.bounds, space.bounds)


def test_combined_layout_checks_electrode_overflow_separately():
    space = _space("P_D_P")
    vector = np.mean(space.bounds, axis=1)
    vector[11] = vector[14] = 60
    candidate = space.decode(vector)
    result = hybrid_geometry(candidate, _layout_config())
    assert result["dms"]["max_violation"] == 0.0
    assert [item["max_violation"] for item in result["resonators"]] == [0.0, 0.0]
    assert result["combined"]["violations"]["max_total_electrodes"] > 0.0
    assert result["max_violation"] > 0.0


def test_resonator_response_is_deterministic_finite_and_passive():
    values = yaml.safe_load((ROOT / "configs/models/com_params_hypothetical.yaml").read_text())
    provider = FixedProvider(values)
    space = _space("P_D")
    vector = np.r_[np.mean(space.bounds[:10], axis=1), 5.0, 20.0, 90.0]
    design = space.decode(vector).resonator_designs[0]
    frequencies = np.asarray([758e6, 780e6, 803e6])
    first = resonator_admittance(design, provider, frequencies)
    second = resonator_admittance(design, provider, frequencies)
    np.testing.assert_array_equal(first, second)
    assert np.isfinite(first).all()
    assert float(np.min(np.real(first))) >= -1e-8
