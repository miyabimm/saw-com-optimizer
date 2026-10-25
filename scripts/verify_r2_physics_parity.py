#!/usr/bin/env python3
"""Emit deterministic physics-output digests through the current owners."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

import numpy as np
import scipy
import yaml


ROOT = Path.cwd().resolve()
from sawopt.design.space import FilterDesign
from sawopt.design.topology import ResonatorDesign
from sawopt.evaluation import resonator_admittance
from sawopt.physics.com import FixedProvider, block, simulate_filter
from sawopt.physics.elements import AcousticSection, circuit_y, simulate_section_chain
from sawopt.physics.network import evaluate


def one_port(design, provider, frequencies):
    return resonator_admittance(design, provider, frequencies)


def _head_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def _array_record(value):
    array = np.asarray(value)
    little_endian_dtype = array.dtype.newbyteorder("<")
    canonical = np.ascontiguousarray(array.astype(little_endian_dtype, copy=False))
    return {
        "shape": list(canonical.shape),
        "dtype": canonical.dtype.str,
        "serialization": "C-order, little-endian, contiguous raw ndarray bytes",
        "sha256": hashlib.sha256(canonical.tobytes(order="C")).hexdigest(),
    }


config_path = ROOT / "configs/models/com_params_hypothetical.yaml"
config_bytes = config_path.read_bytes()
config = yaml.safe_load(config_bytes)
provider = FixedProvider(config)
frequencies = np.linspace(730e6, 830e6, 21, dtype=np.float64)
design = FilterDesign()
filtered = simulate_filter(design, provider, frequencies, center="floating")
network = evaluate(filtered.y_parameters, 37.0, 91.0)
resonator = one_port(ResonatorDesign(), provider, frequencies)
composed = circuit_y(filtered.y_parameters, [(0, -1, resonator)])
sections = (
    AcousticSection("left reflector", "reflector", 20.0, 5.0, 80.0),
    AcousticSection("left gap", "gap", 0.5, 5.0, 80.0),
    AcousticSection("left IDT", "idt", 24.0, 5.0, 80.0, port=0),
    AcousticSection("center IDT", "idt", 16.0, 5.0, 80.0, port=1),
    AcousticSection("right reflector", "reflector", 20.0, 5.0, 80.0),
)
chain = simulate_section_chain(
    sections, provider, frequencies, ((1.0, 0.0), (0.0, 1.0)),
    topology_id="r2-deterministic-parity",
)
block_parameters = {
    "velocity": 3900.0,
    "kappa": 3500.0 + 700.0j,
    "alpha": 900.0 - 100.0j,
    "capacitance": 1e-8,
    "loss": 120.0,
}
p_matrix = block(frequencies, 24 * 5e-6, 5e-6, block_parameters)
arrays = {
    "p_matrix": p_matrix,
    "filter_y": filtered.y_parameters,
    "network_s": network["s"],
    "network_gt": network["gt"],
    "resonator_y": resonator,
    "composed_y": composed,
    "section_chain_y": chain.y_parameters,
}

print(json.dumps({
    "head_sha": _head_sha(),
    "python": sys.version.split()[0],
    "platform": platform.platform(),
    "numpy": np.__version__,
    "scipy": scipy.__version__,
    "pyyaml": yaml.__version__,
    "random_seed": None,
    "inputs": {
        "com_config_path": "configs/models/com_params_hypothetical.yaml",
        "com_config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "filter_design": vars(design),
        "frequency_grid_hz": {
            "start": float(frequencies[0]),
            "stop": float(frequencies[-1]),
            "points": len(frequencies),
            "dtype": frequencies.dtype.str,
            "construction": "numpy.linspace(730e6, 830e6, 21, dtype=float64)",
        },
        "network_terminations_ohm": {"source": 37.0, "load": 91.0},
        "p_matrix_section": {
            "length_m": 24 * 5e-6,
            "wavelength_m": 5e-6,
            "parameters": {
                key: [float(value.real), float(value.imag)] if np.iscomplexobj(value)
                else float(value)
                for key, value in block_parameters.items()
            },
        },
        "resonator_design": vars(ResonatorDesign()),
        "section_chain": [section.__dict__ for section in sections],
        "optimizer_or_experiment": "not run; deterministic software parity check only",
    },
    "outputs": {name: _array_record(value) for name, value in arrays.items()},
    "diagnostics": {
        "max_acoustic_solve_residual": filtered.diagnostics["max_acoustic_solve_residual"],
        "chain_reciprocity_error": chain.diagnostics["reciprocity_error"],
        "max_transducer_gain": float(network["gt"].max()),
    },
}, sort_keys=True, indent=2))
