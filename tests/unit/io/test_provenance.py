import tempfile
import unittest
from pathlib import Path

from sawopt.io.provenance import (
    build_fingerprint_metadata,
    computation_gate_matches,
)


class FingerprintV2(unittest.TestCase):
    def _root(self, directory):
        root = Path(directory)
        (root / "src" / "sawopt").mkdir(parents=True)
        (root / "src" / "sawopt" / "numerics.py").write_bytes(b"result = 1\n")
        (root / "src" / "sawopt" / "report.py").write_bytes(b"title = 'one'\n")
        return root

    def _fingerprints(self, root, configuration=None):
        return build_fingerprint_metadata(
            root,
            configuration or {"bounds": [1, 4]},
            computation_paths=["src/sawopt/numerics.py"],
            reporting_paths=["src/sawopt/report.py"],
        )

    def _build(self, root, configuration, computation_paths=("src/sawopt/numerics.py",)):
        return build_fingerprint_metadata(
            root, configuration, computation_paths=list(computation_paths),
            reporting_paths=["src/sawopt/report.py"],
        )

    def test_reporting_edit_changes_only_reporting_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            before = self._fingerprints(root)
            (root / "src" / "sawopt" / "report.py").write_text("title = 'two'\n", encoding="utf-8")
            after = self._fingerprints(root)
            self.assertEqual(before["computation_fingerprint"], after["computation_fingerprint"])
            self.assertNotEqual(before["reporting_fingerprint"], after["reporting_fingerprint"])
            self.assertTrue(computation_gate_matches(before, after))

    def test_numerical_source_and_configuration_edits_change_computation_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            before = self._fingerprints(root)
            (root / "src" / "sawopt" / "numerics.py").write_text("result = 2\n", encoding="utf-8")
            source_changed = self._fingerprints(root)
            self.assertNotEqual(before["computation_fingerprint"], source_changed["computation_fingerprint"])
            self.assertFalse(computation_gate_matches(before, source_changed))
            config_changed = self._fingerprints(root, {"bounds": [1, 5]})
            self.assertNotEqual(source_changed["computation_fingerprint"], config_changed["computation_fingerprint"])

    def test_repository_local_absolute_paths_are_independent_of_worktree_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root_a = self._root(Path(temp) / "worktree-a" / "repo")
            root_b = self._root(Path(temp) / "worktree-b" / "repo")
            for root in (root_a, root_b):
                resource = root / "artifacts" / "profile.yaml"
                resource.parent.mkdir(parents=True)
                resource.write_text("velocity: 1\n", encoding="utf-8")

            config_a = {"material": {"source": str((root_a / "artifacts/profile.yaml").resolve())}}
            config_b = {"material": {"source": str((root_b / "artifacts/profile.yaml").resolve())}}
            before = self._build(root_a, config_a)
            after = self._build(root_b, config_b)

            self.assertEqual(before["computation_fingerprint"], after["computation_fingerprint"])
            self.assertEqual(config_a["material"]["source"], str((root_a / "artifacts/profile.yaml").resolve()))

    def test_repository_local_absolute_path_separators_are_canonical(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            resource = root / "artifacts" / "profile.yaml"
            resource.parent.mkdir(parents=True)
            resource.write_text("velocity: 1\n", encoding="utf-8")
            path = str(resource.resolve())
            slash = self._build(root, {"profile": {"source": path}})
            backslash = self._build(root, {"profile": {"source": path.replace("/", "\\")}})
            self.assertEqual(slash["computation_fingerprint"], backslash["computation_fingerprint"])

    def test_external_absolute_paths_remain_distinct_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            first = self._build(root, {"external_source": "Z:/shared/profile.yaml"})
            second = self._build(root, {"external_source": "Z:/other/profile.yaml"})
            self.assertNotEqual(first["computation_fingerprint"], second["computation_fingerprint"])

    def test_text_dependency_line_endings_are_canonical_but_content_is_not(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            yaml_path = root / "configs" / "study.yaml"
            json_path = root / "configs" / "grid.json"
            yaml_path.parent.mkdir(parents=True)
            yaml_path.write_bytes(b"budget: 8\nname: test\n")
            json_path.write_bytes(b'{\n  "points": 3\n}\n')
            paths = ("src/sawopt/numerics.py", "configs/study.yaml", "configs/grid.json")

            lf = self._build(root, {"budget": 8}, paths)
            for relative in paths:
                file_path = root / Path(relative)
                file_path.write_bytes(file_path.read_bytes().replace(b"\n", b"\r\n"))
            crlf = self._build(root, {"budget": 8}, paths)
            self.assertEqual(lf["computation_fingerprint"], crlf["computation_fingerprint"])
            self.assertEqual(
                [row["sha256"] for row in lf["dependency_manifest"]["computation"]],
                [row["sha256"] for row in crlf["dependency_manifest"]["computation"]],
            )
            self.assertEqual(
                [row["bytes"] for row in lf["dependency_manifest"]["computation"]],
                [row["bytes"] for row in crlf["dependency_manifest"]["computation"]],
            )

            yaml_path.write_bytes(yaml_path.read_bytes().replace(b"budget: 8", b"budget: 9"))
            content_changed = self._build(root, {"budget": 8}, paths)
            self.assertNotEqual(crlf["computation_fingerprint"], content_changed["computation_fingerprint"])

    def test_dependency_set_and_binary_bytes_remain_fingerprint_sensitive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            (root / "src/sawopt/alternate.py").write_text("result = 1\n", encoding="utf-8")
            original = self._build(root, {"budget": 8})
            added = self._build(root, {"budget": 8}, ("src/sawopt/numerics.py", "src/sawopt/alternate.py"))
            replaced = self._build(root, {"budget": 8}, ("src/sawopt/alternate.py",))
            self.assertNotEqual(original["computation_fingerprint"], added["computation_fingerprint"])
            self.assertNotEqual(original["computation_fingerprint"], replaced["computation_fingerprint"])

            binary = root / "src/sawopt/input.bin"
            binary.write_bytes(b"a\r\nb")
            binary_lf = self._build(root, {"budget": 8}, ("src/sawopt/input.bin",))
            binary.write_bytes(b"a\nb")
            binary_changed = self._build(root, {"budget": 8}, ("src/sawopt/input.bin",))
            self.assertNotEqual(binary_lf["computation_fingerprint"], binary_changed["computation_fingerprint"])

    def test_scientific_configuration_value_changes_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            budget = self._build(root, {"budget": 8, "material": {"velocity": 3480.0}})
            changed = self._build(root, {"budget": 9, "material": {"velocity": 3480.0}})
            self.assertNotEqual(budget["computation_fingerprint"], changed["computation_fingerprint"])

    def test_dependency_paths_are_explicit_and_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self._root(temp)
            with self.assertRaises(FileNotFoundError):
                build_fingerprint_metadata(
                    root, {}, computation_paths=["missing.py"], reporting_paths=[]
                )
            with self.assertRaises(ValueError):
                build_fingerprint_metadata(
                    root, {}, computation_paths=["src/sawopt/numerics.py"] * 2,
                    reporting_paths=[],
                )


if __name__ == "__main__":
    unittest.main()
