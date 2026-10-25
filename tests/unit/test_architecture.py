import ast
import importlib.util
from pathlib import Path
import unittest


SRC = Path(__file__).parents[2] / 'src' / 'sawopt'
FORBIDDEN_EXTERNAL_IMPORT_ROOTS = {'github', 'github3', 'githubkit', 'PyGithub', 'pi'}


def _absolute_import(package, node):
    if isinstance(node, ast.Import):
        return [(alias.name, None) for alias in node.names]
    relative = '.' * node.level + (node.module or '')
    name = importlib.util.resolve_name(relative, package) if relative else package
    return [(name, alias.name) for alias in node.names]


def _dynamic_import_target(node):
    if not isinstance(node, ast.Call) or not node.args:
        return None
    function = node.func
    is_import = isinstance(function, ast.Name) and function.id == '__import__'
    is_import_module = (
        isinstance(function, ast.Name) and function.id == 'import_module'
    ) or (
        isinstance(function, ast.Attribute) and function.attr == 'import_module'
    )
    argument = node.args[0]
    if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
        return None
    target = argument.value
    if is_import:
        return None if target.startswith('.') else target
    if not is_import_module:
        return None
    if not target.startswith('.'):
        return target
    package_argument = next(
        (keyword.value for keyword in node.keywords if keyword.arg == 'package'),
        node.args[1] if len(node.args) > 1 else None,
    )
    if isinstance(package_argument, ast.Constant) and isinstance(package_argument.value, str):
        try:
            return importlib.util.resolve_name(target, package_argument.value)
        except ImportError:
            return None
    return None


def _import_targets(package, node):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        for imported, imported_name in _absolute_import(package, node):
            if imported_name and imported in {'sawopt', 'sawopt.io'}:
                imported = f'{imported}.{imported_name}'
            yield imported, imported_name
    else:
        imported = _dynamic_import_target(node)
        if imported is not None:
            yield imported, None


def _matches_module(imported, prefix):
    return imported == prefix or imported.startswith(f'{prefix}.')


def _architecture_violations(module, path_name, source):
    parts = module.split('.')
    package = '.'.join(parts[:-1])
    owner = parts[1] if len(parts) > 1 else ''
    violations = []
    tree = ast.parse(source, filename=path_name)
    for node in ast.walk(tree):
        for imported, imported_name in _import_targets(package, node):
            root = imported.split('.', 1)[0]
            forbidden = (
                owner in {'physics', 'design', 'evaluation', 'optimization'}
                and root in FORBIDDEN_EXTERNAL_IMPORT_ROOTS
            )
            if owner == 'core' and any(_matches_module(imported, prefix) for prefix in (
                'sawopt.optimization', 'sawopt.optimizers', 'sawopt.problem', 'sawopt.studies',
            )):
                forbidden = True
            if owner == 'physics' and any(_matches_module(imported, f'sawopt.{root}') for root in (
                'core', 'design', 'evaluation', 'problem', 'optimization', 'optimizers', 'studies',
                'reporting', 'orchestration', 'runtime', 'io', 'cli', 'synthetic_worker',
            )):
                forbidden = True
            if owner == 'design' and any(_matches_module(imported, f'sawopt.{root}') for root in (
                'core', 'problem', 'physics', 'evaluation', 'optimization', 'optimizers',
                'studies', 'io', 'reporting', 'orchestration', 'runtime', 'cli',
                'synthetic_worker',
            )):
                forbidden = True
            if owner == 'evaluation' and _matches_module(imported, 'sawopt') and not any(
                _matches_module(imported, allowed) for allowed in ('sawopt.design', 'sawopt.physics')
            ):
                forbidden = True
            if owner == 'optimization':
                if any(_matches_module(imported, prefix) for prefix in (
                    'sawopt.studies', 'sawopt.reporting', 'sawopt.orchestration',
                    'sawopt.runtime', 'sawopt.cli', 'sawopt.synthetic_worker',
                )):
                    forbidden = True
                if _matches_module(imported, 'sawopt.io') and not any(
                    _matches_module(imported, allowed)
                    for allowed in ('sawopt.io.checkpoints', 'sawopt.io.lifecycle')
                ):
                    forbidden = True
            if owner == 'problem' and _matches_module(imported, 'sawopt.studies'):
                forbidden = True
            if owner == 'studies' and _matches_module(imported, 'sawopt.studies') and imported_name and imported_name.startswith('_'):
                violations.append(f'{module} imports private {imported}.{imported_name}')
            if forbidden:
                kind = 'dynamically imports' if isinstance(node, ast.Call) else 'imports'
                violations.append(f'{module} {kind} {imported}')
    return violations


class ArchitectureBoundaries(unittest.TestCase):
    def test_optimizer_services_have_one_canonical_package(self):
        self.assertFalse((SRC / 'optimizers').exists())
        for module in ('base.py', 'lshade.py', 'scipy_de.py', 'selection.py', 'checkpoint_session.py'):
            self.assertTrue((SRC / 'optimization' / module).is_file(), module)

        violations = []
        for path in SRC.rglob('*.py'):
            relative = path.relative_to(SRC).with_suffix('')
            module = '.'.join(('sawopt',) + relative.parts)
            package = '.'.join(module.split('.')[:-1])
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for imported, _name in _absolute_import(package, node):
                        if imported == 'sawopt.optimizers' or imported.startswith('sawopt.optimizers.'):
                            violations.append(f'{module} imports retired optimizer package {imported}')
                if isinstance(node, ast.Call) and node.args:
                    function = node.func
                    dynamic_import = (
                        isinstance(function, ast.Name) and function.id == '__import__'
                    ) or (
                        isinstance(function, ast.Attribute) and function.attr == 'import_module'
                    )
                    argument = node.args[0]
                    if (dynamic_import and isinstance(argument, ast.Constant)
                            and isinstance(argument.value, str)
                            and (argument.value == 'sawopt.optimizers'
                                 or argument.value.startswith('sawopt.optimizers.'))):
                        violations.append(f'{module} dynamically imports retired optimizer package')
        self.assertEqual([], violations)

    def test_layer_import_boundaries_and_public_cross_study_imports(self):
        violations = []
        for path in SRC.rglob('*.py'):
            relative = path.relative_to(SRC).with_suffix('')
            parts = ('sawopt',) + relative.parts
            module = '.'.join(parts)
            violations.extend(_architecture_violations(
                module, str(path), path.read_text(encoding='utf-8')
            ))
        self.assertEqual([], violations)

    def test_core_import_boundaries_reject_forbidden_edges(self):
        cases = (
            ('sawopt.physics.fixture', 'from sawopt import cli\nfrom .. import evaluation\n',
             ('sawopt.cli', 'sawopt.evaluation')),
            ('sawopt.physics.fixture', 'import github, github3, githubkit, PyGithub, pi\n',
             ('github', 'github3', 'githubkit', 'PyGithub', 'pi')),
            (
                'sawopt.design.fixture',
                'from sawopt import synthetic_worker\nfrom .. import cli\n',
                ('sawopt.synthetic_worker', 'sawopt.cli'),
            ),
            (
                'sawopt.optimization.fixture',
                'def deferred():\n    from sawopt.io import synthetic_task_recovery\n',
                ('sawopt.io.synthetic_task_recovery',),
            ),
            (
                'sawopt.optimization.fixture',
                'import importlib\n'
                'importlib.import_module("sawopt.reporting.experiment_review")\n'
                '__import__("pi")\n',
                ('sawopt.reporting.experiment_review', 'pi'),
            ),
        )
        for module, source, expected_targets in cases:
            with self.subTest(module=module, expected_targets=expected_targets):
                violations = _architecture_violations(module, 'negative-fixture.py', source)
                for expected_target in expected_targets:
                    self.assertTrue(
                        any(expected_target in violation for violation in violations),
                        f'{module} did not reject {expected_target}: {violations}',
                    )

    def test_intentional_core_import_exceptions_remain_permitted(self):
        cases = (
            (
                'sawopt.optimization.fixture',
                'from sawopt.io.checkpoints import CheckpointStore\n'
                'from sawopt.io.lifecycle import RunDisposition\n',
            ),
            (
                'sawopt.problem.evaluator.fixture',
                'from sawopt.optimization.adaptive_frequency import adaptive_exchange\n',
            ),
            (
                'sawopt.studies.dms_topology_common',
                'from sawopt.reporting.material_metadata import material_profile_metadata\n',
            ),
        )
        for module, source in cases:
            with self.subTest(module=module):
                self.assertEqual([], _architecture_violations(module, 'allowed-fixture.py', source))

    def test_relative_and_absolute_cross_study_private_imports_are_rejected(self):
        relative = _architecture_violations(
            'sawopt.studies.fixture', 'fixture.py',
            'from .other import _private_helper\n',
        )
        absolute = _architecture_violations(
            'sawopt.studies.fixture', 'fixture.py',
            'from sawopt.studies.other import _private_helper\n',
        )
        self.assertTrue(relative)
        self.assertTrue(absolute)
        self.assertIn('sawopt.studies.other._private_helper', relative[0])
        self.assertIn('sawopt.studies.other._private_helper', absolute[0])
