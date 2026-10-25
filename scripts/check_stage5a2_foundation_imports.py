#!/usr/bin/env python3
"""Fresh-process no-physics import proof for the Q1-A foundation modules."""
from __future__ import annotations

import importlib
import json
import sys

import numpy as np

MODULES = (
    "sawopt.design.canonicalization",
    "sawopt.studies.stage5a2.codec",
    "sawopt.studies.stage5a2.identity",
    "sawopt.studies.stage5a2.production_identity",
    "sawopt.studies.stage5a2.journal",
    "sawopt.studies.stage5a2.rng",
    "sawopt.studies.stage5a2.initialization",
)
for name in MODULES:
    importlib.import_module(name)

from sawopt.design.canonicalization import canonicalize_hybrid_vector

bounds = np.asarray([[0.0, 1.0], [2.0, 4.0]], dtype=np.float64)
vector, key = canonicalize_hybrid_vector(
    [0.25, 2.5], bounds=bounds, integer_indices=(1,), dimension=2, topology="P_D",
)
assert vector.tobytes() == np.asarray([0.25, 3.0], dtype=np.float64).tobytes()
assert key == (0.25, 3.0)
forbidden_prefixes = (
    "sawopt.problem",
    "sawopt.physics",
    "sawopt.evaluation",
    "sawopt.optimization",
    "sawopt.optimizers",
    "sawopt.core",
    "sawopt.io",
    "sawopt.studies.dms_topology_common",
    "sawopt.reporting",
    "sawopt.cli",
    "sawopt.orchestration",
    "sawopt.runtime",
)
loaded = sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden_prefixes)
)
if loaded:
    raise SystemExit(f"forbidden Q1-A runtime imports observed: {loaded}")
print(json.dumps({"modules_imported": list(MODULES), "forbidden_imports": loaded, "result": key}))
