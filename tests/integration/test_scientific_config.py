"""Validation-only declarations: no scientific execution or qualification."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from sawopt.io.cli_config import CliConfigError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "configs/examples/scientific_validation_only.yaml"


def load(path):
    from sawopt.io.cli_config import load_cli_config
    return load_cli_config(path)


@pytest.fixture
def config():
    return yaml.safe_load(EXAMPLE.read_text())


def save(tmp_path, config):
    path = tmp_path / "declaration.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    return path


def test_snapshot_and_normalization(tmp_path, config):
    result = load(EXAMPLE)
    effective = result["effective_config"]
    assert result["schema_valid"] is True
    assert result["qualification"] == "NOT_EVALUATED"
    assert result["run_authorized"] is False
    assert effective["ports"] == {"domain": "positive_real", "unit": "ohm", "source": 50.0, "load": 75.0}
    assert effective["design"] == config["design"]
    assert effective["optimizer"] == config["optimizer"]
    assert effective["resources"] == config["resources"]
    assert effective["specification"] == config["specification"]
    assert effective["model"]["parameters"] == config["model"]["parameters"]["inline"]
    assert effective["grids"]["search"] == config["grids"]["search"]["inline"]
    canonical = json.dumps(effective, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
    assert result["effective_config_sha256"] == hashlib.sha256(canonical).hexdigest()
    assert result["config_file_sha256"] == hashlib.sha256(EXAMPLE.read_bytes()).hexdigest()
    for name, payload in (("model", effective["model"]["parameters"]), ("search_grid", effective["grids"]["search"]), ("validation_grid", effective["grids"]["validation"])):
        assert result["input_sha256"][name] == hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()
    reordered = dict(reversed(list(config.items())))
    reordered["ports"]["source"] = 50  # real-field int and float normalize equally
    assert load(save(tmp_path, reordered))["effective_config_sha256"] == result["effective_config_sha256"]
    effective["ports"]["source"] = 999  # detached, no persistent mutable cached value
    assert load(EXAMPLE)["effective_config"]["ports"]["source"] == 50.0


@pytest.mark.parametrize("location,value", [
    (("ports", "source"), 51),
    (("ports", "load"), 76),
    (("optimizer", "seed"), 18),
    (("resources", "memory_bytes"), 200000000),
    (("design", "center"), "floating"),
    (("specification", "il_db"), 4),
    (("model", "parameters", "inline", "idt", "kappa_phase_rad"), 0.0),  # signed zero
])
def test_scientific_identity_changes(tmp_path, config, location, value):
    parent = config
    for key in location[:-1]:
        parent = parent[key]
    parent[location[-1]] = value
    if location == ("optimizer", "seed"):
        config["storage"]["expected_cells"][0]["seed"] = value
    assert load(save(tmp_path, config))["effective_config_sha256"] != load(EXAMPLE)["effective_config_sha256"]


@pytest.mark.parametrize("section", [None, "model", "design", "specification", "ports", "grids", "optimizer", "resources", "storage", "review_context"])
@pytest.mark.parametrize("action", ["missing", "unknown"])
def test_exact_keys_every_section(tmp_path, config, section, action):
    target = config if section is None else config[section]
    if action == "missing":
        target.pop(next(iter(target)))
    else:
        target["unknown"] = 1
    with pytest.raises(CliConfigError):
        load(save(tmp_path, config))


@pytest.mark.parametrize("location,value", [
    (("schema_id",), "sawopt.scientific_config/2"),
    (("schema_version",), 1),
    (("experiment_id",), "UPPER"),
    (("model", "kind"), "calibrated"),
    (("design", "topology"), "P_D"),
    (("design", "integer_indices"), [True, 2, 3]),
    (("design", "fixed", "metallization_ratio"), 1),
    (("design", "geometry", "max_electrodes"), True),
    (("ports", "source"), True),
    (("ports", "load"), 0),
    (("ports", "source"), {"real": 50, "imag": 1}),
    (("ports", "unit"), "Ohm"),
    (("ports", "domain"), "complex"),
    (("resources", "wall_time_seconds"), float("inf")),
    (("resources", "threads"), 2),
    (("optimizer", "seed"), 17.0),
    (("optimizer", "version"), "main"),
    (("optimizer", "settings", "total_budget"), 9),
    (("optimizer", "proposal_policy"), "q0_watchdog"),
    (("specification", "il_db"), float("nan")),
    (("specification", "feasibility_tolerance"), 0),
    (("grids", "search", "inline", "unit"), "MHz"),
    (("grids", "search", "inline", "points"), [2, 1]),
    (("grids", "search", "inline", "points"), [1, 2]),
    (("model", "parameters", "inline", "gap", "velocity_m_s"), 10**400),
])
def test_reject_bad_declarations(tmp_path, config, location, value):
    parent = config
    for key in location[:-1]:
        parent = parent[key]
    parent[location[-1]] = value
    with pytest.raises(CliConfigError):
        load(save(tmp_path, config))


@pytest.mark.parametrize("text", [
    "schema_id: sawopt.scientific_config/1\nschema_id: sawopt.scientific_config/1\n",
    "x: &x {a: 1}\ny: *x\n",
    "x: {<<: {a: 1}}\n",
    "true: 1\n", "[]", "!!python/object:foo {}", "x: 1\n---\nx: 2\n",
])
def test_strict_yaml(tmp_path, text):
    path = tmp_path / "bad.yaml"
    path.write_text(text)
    with pytest.raises(CliConfigError):
        load(path)


def test_reference_resolution_and_hash(tmp_path, config, monkeypatch):
    original = load(EXAMPLE)
    references = {}
    for name, wrapper in (("model", config["model"]["parameters"]), ("search_grid", config["grids"]["search"]), ("validation_grid", config["grids"]["validation"])):
        payload = wrapper.pop("inline")
        path = tmp_path / f"{name}.yaml"
        path.write_text(yaml.safe_dump(payload))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        wrapper.update(path=path.name, sha256=digest)
        references[name] = dict(wrapper)
    path = save(tmp_path, config)
    monkeypatch.chdir(tmp_path.parent)
    result = load(path)
    assert result["effective_config_sha256"] == original["effective_config_sha256"]
    assert result["references"] == references
    (tmp_path / "model.yaml").write_text("tampered: true")
    with pytest.raises(CliConfigError, match="SHA-256"):
        load(path)


@pytest.mark.parametrize("path", ["/tmp/no.yaml", "../no.yaml", "./no.yaml", "a//b", "a/../b", "https://example.com/x", "a\\b", "missing.yaml", ""])
def test_reference_paths_fail_closed(tmp_path, config, path):
    config["model"]["parameters"] = {"path": path, "sha256": "a" * 64}
    with pytest.raises(CliConfigError):
        load(save(tmp_path, config))


@pytest.mark.parametrize("mode", ["symlink", "directory", "fifo", "bad_hash", "missing_hash", "bad_payload", "duplicate", "unknown"])
def test_reference_failures(tmp_path, config, mode):
    payload = yaml.safe_dump(config["model"]["parameters"]["inline"])
    path = tmp_path / "model.yaml"
    if mode == "symlink":
        target = tmp_path / "target.yaml"
        target.write_text(payload)
        path.symlink_to(target)
    elif mode == "directory":
        path.mkdir()
    elif mode == "fifo":
        os.mkfifo(path)
    else:
        if mode == "bad_payload":
            payload = "legacy: true\n"
        if mode == "duplicate":
            payload += "reference_aperture_um: 80\n"
        if mode == "unknown":
            payload += "unknown: 1\n"
        path.write_text(payload)
    ref = {"path": path.name, "sha256": hashlib.sha256(payload.encode()).hexdigest()}
    if mode == "bad_hash":
        ref["sha256"] = "bad"
    if mode == "missing_hash":
        ref.pop("sha256")
    config["model"]["parameters"] = ref
    with pytest.raises(CliConfigError):
        load(save(tmp_path, config))


@pytest.mark.parametrize("command", ["validate", "run"])
def test_fresh_process_no_science_no_writes(tmp_path, command):
    # Audit hooks prohibit imports and ALL filesystem writes, including pyc and
    # subprocesses. The CLI runs in a fresh process, not a pre-imported test.
    guard = r'''
import sys
forbidden = ("sawopt.physics", "sawopt.design", "sawopt.evaluation", "sawopt.problem", "sawopt.optimization", "sawopt.studies", "sawopt.reporting", "sawopt.io.experiment_store", "sawopt.io.checkpoint")
def audit(event, args):
    if event == "import" and any(args[0] == p or args[0].startswith(p + ".") for p in forbidden):
        raise AssertionError("forbidden import: " + args[0])
    if event == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (1 | 2 | 64 | 512 | 1024)):
            raise AssertionError("filesystem write")
    if event in ("os.mkdir", "os.remove", "os.rename", "os.rmdir", "os.putenv", "os.unsetenv", "subprocess.Popen"):
        raise AssertionError("side effect: " + event)
sys.addaudithook(audit)
from sawopt.cli import main
status = main(sys.argv[1:])
assert not any(any(n == p or n.startswith(p + ".") for p in forbidden) for n in sys.modules)
raise SystemExit(status)
'''
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "SAWOPT_DATA_ROOT": str(tmp_path / "invalid-root")}
    before = sorted(tmp_path.rglob("*"))
    proc = subprocess.run([sys.executable, "-B", "-c", guard, command, "--config", str(EXAMPLE)], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert sorted(tmp_path.rglob("*")) == before
    if command == "validate":
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout) == load(EXAMPLE)
    else:
        assert proc.returncode == 2, proc.stderr
        assert json.loads(proc.stderr)["error"]["code"] == "SCIENTIFIC_RUN_NOT_IMPLEMENTED"


def test_repeat_process_identity():
    command = [sys.executable, "-B", "-m", "sawopt.cli", "validate", "--config", str(EXAMPLE)]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    second = subprocess.run(command, capture_output=True, text=True, check=True)
    assert first.stdout == second.stdout


def test_no_legacy_or_cross_schema_fallback(tmp_path, config):
    with pytest.raises(CliConfigError):
        load(ROOT / "configs/studies/hybrid_stage4c_confirmatory.yaml")
    config["schema_version"] = 1
    with pytest.raises(CliConfigError):
        load(save(tmp_path, config))
    config.pop("schema_id")
    with pytest.raises(CliConfigError):
        load(save(tmp_path, config))
