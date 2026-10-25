from pathlib import Path

import numpy as np
import yaml

from sawopt.design.geometry import layout
from sawopt.design.space import FilterDesign
from sawopt.design.topology import (
    ResonatorDesign,
    STAGE4A_TOPOLOGIES,
    TOPOLOGIES,
    decode_resonator,
)
from sawopt.evaluation import compose_stage4a_y, resonator_admittance
from sawopt.physics.com import FixedProvider, acoustic_admittance, simulate_filter
from sawopt.physics.elements import circuit_y
from sawopt.physics.network import evaluate


ROOT = Path(__file__).resolve().parents[3]


def _config():
    base = yaml.safe_load((ROOT / "configs/base/b28_dms_baseline.yaml").read_text())
    hybrid = yaml.safe_load((ROOT / "configs/studies/hybrid_50ohm.yaml").read_text())
    com = yaml.safe_load((ROOT / "configs/models/com_params_hypothetical.yaml").read_text())
    return {**base, **hybrid, "com": com}


def test_series_and_shunt_analytic():
    y = np.array([[[1, -1], [-1, 1]]], complex) / 25
    np.testing.assert_allclose(
        circuit_y(y, [(0, 2, np.array([1 / 30]))], dms_nodes=(2, 1), node_count=3),
        y * 25 / 55,
        atol=1e-12,
    )
    expected = y.copy()
    expected[:, 0, 0] += 1 / 80
    np.testing.assert_allclose(circuit_y(y, [(0, -1, np.array([1 / 80]))]), expected)
    np.testing.assert_allclose(circuit_y(y, []), y)


def test_resonator_static_limit():
    config = _config()
    frequencies = np.linspace(750e6, 810e6, 10)
    config["com"]["idt"]["alpha_sqrtS_per_m"] = 0
    admittance = resonator_admittance(
        ResonatorDesign(), FixedProvider(config["com"]), frequencies,
    )
    capacitance = 1e-8 * (70 / 80) * 25 * 5e-6
    np.testing.assert_allclose(admittance, 1j * 2 * np.pi * frequencies * capacitance, atol=1e-12)


def test_resonator_provider_sees_full_filter_design_geometry():
    fixed = FixedProvider(_config()["com"])
    observed = []

    class GeometryAwareProvider:
        def parameters(self, region, geometry, frequency, temperature_c=25):
            assert isinstance(geometry, FilterDesign)
            observed.append(vars(geometry).copy())
            assert geometry.io_idt_pairs == 23
            assert geometry.metallization_ratio == 0.5
            return fixed.parameters(region, geometry, frequency, temperature_c)

    resonator = ResonatorDesign(wavelength_um=5.1, pairs=23, aperture_um=71.0)
    frequencies = np.asarray([780e6, 800e6])
    response = resonator_admittance(resonator, GeometryAwareProvider(), frequencies)
    expected = FilterDesign(
        wavelength_um=resonator.wavelength_um,
        io_idt_pairs=resonator.pairs,
        aperture_um=resonator.aperture_um,
    )
    assert observed == [vars(expected)] * 5
    assert np.isfinite(response).all()


def test_wiring_transform_matches_three_port_and_symmetric_odd_mode_cancels():
    config = _config()
    provider = FixedProvider(config["com"])
    frequencies = np.linspace(730e6, 830e6, 101)
    design = FilterDesign()
    regions = [
        ("reflector", 20, None), ("gap", 0.5, None), ("idt", 24, 0),
        ("gap", 0.5, None), ("idt", 16, 1), ("gap", 0.5, None),
        ("idt", 24, 2), ("gap", 0.5, None), ("reflector", 20, None),
    ]
    full = acoustic_admittance(design, provider, frequencies, regions, 3)
    for wiring, sign in (("center_outer_same", 1), ("center_outer_opposite", -1)):
        transform = np.array([[0, 1], [1, 0], [0, sign]])
        output = simulate_filter(design, provider, frequencies, wiring=wiring).y_parameters
        np.testing.assert_allclose(output, transform.T @ full @ transform, atol=1e-12)
    odd = simulate_filter(design, provider, frequencies, wiring="center_outer_opposite").y_parameters
    np.testing.assert_allclose(odd[:, 0, 1], 0, atol=1e-12)


def test_current_hybrid_topologies_are_passive_and_layout_checked():
    config = _config()
    provider = FixedProvider(config["com"])
    frequencies = np.unique(np.r_[np.linspace(10e6, 1000e6, 301), [758e6, 803e6]])
    dms = FilterDesign()
    dms_y = simulate_filter(
        dms, provider, frequencies, config["center"], wiring="center_outer_same",
    ).y_parameters

    for topology in STAGE4A_TOPOLOGIES:
        terminals = TOPOLOGIES[topology][1]
        resonators = [decode_resonator([5.1, 15, 60]) for _ in terminals]
        admittances = [resonator_admittance(item, provider, frequencies) for item in resonators]
        combined = compose_stage4a_y(dms_y, topology, admittances)
        network = evaluate(combined, 50.0, 50.0)
        assert network["gt"].max() <= 1 + 1e-10
        dimensions, violation = layout(dms, resonators, config)
        assert violation == 0.0
        assert dimensions["total_electrodes"] <= 500

    _, violation = layout(dms, [ResonatorDesign(pairs=60)] * 2, config)
    assert violation > 0.0
