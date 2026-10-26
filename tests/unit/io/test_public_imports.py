"""Fresh-process checks for lazy R5 public exports without identity wrappers."""
from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize("access", ["attributes", "from_import", "star_import", "direct_first"])
def test_lazy_public_api_in_fresh_process(access):
    code = '''
import importlib
import sys
import sawopt.io as api
names = [
    "ExperimentRun", "RunStorageError", "RunValidationError",
    "create_experiment_run", "read_experiment_manifest", "validate_data_root",
]
assert api.__all__ == names
assert "sawopt.io.experiment_store" not in sys.modules
import sawopt.io.cli_config
assert "sawopt.io.experiment_store" not in sys.modules
try:
    api.not_a_public_export
except AttributeError:
    pass
else:
    raise AssertionError("unknown attribute was accepted")
assert "sawopt.io.experiment_store" not in sys.modules
access = sys.argv[1]
if access == "attributes":
    exported = {name: getattr(api, name) for name in names}
elif access == "from_import":
    from sawopt.io import (
        ExperimentRun, RunStorageError, RunValidationError,
        create_experiment_run, read_experiment_manifest, validate_data_root,
    )
    exported = {name: globals()[name] for name in names}
elif access == "star_import":
    exported = {}
    exec("from sawopt.io import *", exported)
    assert set(exported) - {"__builtins__"} == set(names)
else:
    import sawopt.io.experiment_store as implementation
    exported = {name: getattr(api, name) for name in names}
implementation = importlib.import_module("sawopt.io.experiment_store")
for name in names:
    assert exported[name] is getattr(implementation, name)
    assert getattr(api, name) is exported[name]  # repeat access, no wrappers
assert issubclass(api.RunValidationError, ValueError)
assert issubclass(api.RunStorageError, OSError)
for name in ("RunValidationError", "RunStorageError"):
    try:
        raise getattr(implementation, name)("test-only exception")
    except getattr(api, name):
        pass
    else:
        raise AssertionError("exception class identity changed")
try:
    api.not_a_public_export
except AttributeError:
    pass
else:
    raise AssertionError("unknown attribute was accepted after loading R5")
'''
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, access],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
