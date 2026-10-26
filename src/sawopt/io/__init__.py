"""IO services with lazy public R5 exports for non-executing config imports."""

from importlib import import_module as _import_module

__all__ = [
    "ExperimentRun", "RunStorageError", "RunValidationError",
    "create_experiment_run", "read_experiment_manifest", "validate_data_root",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(_import_module("sawopt.io.experiment_store"), name)
