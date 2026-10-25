import ast
import importlib
from pathlib import Path

import pytest


PHYSICS_MODULES = ("com", "elements", "network", "literature_com")
FORBIDDEN_ROOTS = {
    "core", "design", "evaluation", "problem", "optimization", "optimizers", "studies",
    "reporting", "orchestration", "runtime", "io", "cli", "synthetic_worker",
}
FORBIDDEN_EXTERNAL_ROOTS = {"github", "github3", "githubkit", "PyGithub", "pi"}


def _import_targets(node, package):
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []
    if node.level == 0:
        base = node.module or ""
        if base in {"sawopt", "sawopt.io"}:
            return [f"{base}.{alias.name}" for alias in node.names]
        return [base]

    package_parts = package.split(".")
    parent_count = node.level - 1
    if parent_count >= len(package_parts):
        raise ImportError(f"relative import escapes package: {ast.unparse(node)}")
    prefix = ".".join(package_parts[:len(package_parts) - parent_count])
    base = f"{prefix}.{node.module}" if node.module else prefix
    if node.module:
        return [base]
    return [f"{base}.{alias.name}" for alias in node.names]


def _upward_roots(tree, package="sawopt.physics"):
    roots = set()
    for node in ast.walk(tree):
        for target in _import_targets(node, package):
            parts = target.split(".")
            if len(parts) > 1 and parts[0] == "sawopt" and parts[1] in FORBIDDEN_ROOTS:
                roots.add(parts[1])
            elif target == "sawopt.*":
                roots.update(FORBIDDEN_ROOTS)
            elif parts[0] in FORBIDDEN_EXTERNAL_ROOTS:
                roots.add(parts[0])
    return roots


def _assert_no_upward_imports(tree, path):
    roots = _upward_roots(tree)
    forbidden_roots = FORBIDDEN_ROOTS | FORBIDDEN_EXTERNAL_ROOTS
    assert roots.isdisjoint(forbidden_roots), (
        f"{path} imports an upward package: {sorted(roots & forbidden_roots)}"
    )


def test_physics_modules_are_importable_without_upward_dependencies():
    package_dir = Path(__file__).parents[3] / "src" / "sawopt" / "physics"
    for module_name in PHYSICS_MODULES:
        module_path = package_dir / f"{module_name}.py"
        importlib.import_module(f"sawopt.physics.{module_name}")
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        _assert_no_upward_imports(tree, module_path)


def test_boundary_guard_resolves_and_rejects_relative_upward_imports():
    tree = ast.parse(
        "from ..design.space import FilterDesign as Design\n"
        "from .. import evaluation as response_layer\n"
        "from .. import core as legacy_core\n"
        "from .. import problem as problem_layer\n"
        "from sawopt import cli, synthetic_worker\n"
        "from sawopt.io import experiment_store\n"
        "import github, github3, githubkit, PyGithub, pi\n"
        "from .com import block\n"
    )
    assert _upward_roots(tree) == {
        "core", "design", "evaluation", "problem", "cli", "synthetic_worker", "io",
        "github", "github3", "githubkit", "PyGithub", "pi",
    }
    with pytest.raises(AssertionError, match="core.*problem"):
        _assert_no_upward_imports(tree, Path("relative-import-fixture.py"))
    with pytest.raises(AssertionError, match="github.*pi"):
        _assert_no_upward_imports(ast.parse("import github, github3, githubkit, PyGithub, pi"), Path("external-fixture.py"))
