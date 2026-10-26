"""PR #158 F1–F4: declaration contracts only; never create a scientific run."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest
import yaml

from sawopt.io.cli_config import CliConfigError, load_cli_config, load_synthetic_config
from sawopt.io.scientific_config import canonical_bytes

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "configs/examples/scientific_validation_only.yaml"
SYNTHETIC = ROOT / "configs/examples/r6_synthetic_smoke.yaml"
FINDINGS = "NOT_EVALUATED: no experimental findings; declaration only."


def save(tmp_path, config):
    path = tmp_path / "declaration.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def config():
    return yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))


def test_review_context_passes_existing_r5_contract_without_adapter(tmp_path, config):
    # Test-only structural comparison with existing R5 owner, NOT run creation.
    from sawopt.io.experiment_store import REVIEW_CONTEXT_FIELDS, _validate_review_context

    config["review_context"]["findings"] = FINDINGS
    effective = load_cli_config(save(tmp_path, config))["effective_config"]
    context = effective["review_context"]
    assert set(context) == REVIEW_CONTEXT_FIELDS
    assert context["findings"] == FINDINGS
    assert _validate_review_context(context) == context


@pytest.mark.parametrize("value", [None, "", "Best feasible design found", "NOT_EVALUATED", True])
def test_findings_rejects_missing_or_observed_claim(tmp_path, config, value):
    if value is None:
        config["review_context"].pop("findings", None)
    else:
        config["review_context"]["findings"] = value
    with pytest.raises(CliConfigError):
        load_cli_config(save(tmp_path, config))


@pytest.mark.parametrize("text", ["hypothetical material", "仮想材料", "e\u0301 / é / 🧪"])
def test_exact_canonical_bytes_match_r5_including_binary64_and_order(text):
    from sawopt.io.experiment_store import _canonical_json

    probe = {"z": text, "a": [-0.0, 0.0, 1.0000000000000002, 5e-324, 1e100], "integer": 17}
    expected = json.dumps(probe, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    assert canonical_bytes(probe) == expected == _canonical_json(probe)
    assert canonical_bytes(dict(reversed(list(probe.items())))) == expected
    assert b"-0.0" in expected
    changed = copy.deepcopy(probe)
    changed["a"][0] = 0.0
    assert canonical_bytes(changed) != expected
    assert hashlib.sha256(canonical_bytes(changed)).digest() != hashlib.sha256(expected).digest()


@pytest.mark.parametrize("text", ["hypothetical material", "仮想材料"])
def test_effective_identity_is_r5_scientific_identity(tmp_path, config, text):
    from sawopt.io.experiment_store import _canonical_json

    config["model"]["material"] = text
    config["model"]["assumptions"] = text + ": declaration only"
    config["review_context"]["limitations"] = text + ": no response evaluated"
    config["review_context"]["findings"] = FINDINGS
    result = load_cli_config(save(tmp_path, config))
    effective = result["effective_config"]
    assert result["effective_config_sha256"] == hashlib.sha256(_canonical_json(effective)).hexdigest()
    phase = effective["model"]["parameters"]["idt"]["kappa_phase_rad"]
    assert struct.pack(">d", phase) == struct.pack(">d", -0.0)
    for name, payload in (("model", effective["model"]["parameters"]),
                          ("search_grid", effective["grids"]["search"]),
                          ("validation_grid", effective["grids"]["validation"])):
        assert result["input_sha256"][name] == hashlib.sha256(_canonical_json(payload)).hexdigest()
    reordered = dict(reversed(list(config.items())))
    reordered["model"] = dict(reversed(list(config["model"].items())))
    other_path = save(tmp_path, reordered)
    assert load_cli_config(other_path)["effective_config_sha256"] == result["effective_config_sha256"]
    # Fresh CLI process confirms the same Unicode identity, not module state.
    proc = subprocess.run([sys.executable, "-B", "-m", "sawopt.cli", "validate", "--config", str(other_path)], capture_output=True, text=True, check=True)
    assert json.loads(proc.stdout)["effective_config_sha256"] == result["effective_config_sha256"]


def test_accepted_fixed_values_match_unmodified_decoder(tmp_path, config):
    from sawopt.design.space import canonical_design, decode

    result = load_cli_config(save(tmp_path, config))["effective_config"]
    vector = [5.0, 24.2, 16.3, 40.4, 0.5, 0.5, 80.0]
    design = decode(vector)
    assert result["design"]["fixed"] == {
        "metallization_ratio": design.metallization_ratio,
        "thickness_over_lambda": design.thickness_over_lambda,
    } == {"metallization_ratio": 0.5, "thickness_over_lambda": 0.04}
    _, canonical, key = canonical_design(vector)
    assert list(canonical) == [5.0, 24.0, 16.0, 40.0, 0.5, 0.5, 80.0]
    assert key == tuple(canonical)


@pytest.mark.parametrize("name,value", [("metallization_ratio", 0.6), ("thickness_over_lambda", 0.05)])
def test_nondefault_fixed_values_fail_closed(tmp_path, config, name, value):
    config["design"]["fixed"][name] = value
    with pytest.raises(CliConfigError, match="design.fixed"):
        load_cli_config(save(tmp_path, config))


def synthetic_alias_text():
    text = SYNTHETIC.read_text(encoding="utf-8")
    text = text.replace("offset: 0.0", "offset: &offset 0.0")
    text = text.replace("points: [-0.5, 0.0, 0.5]", "points: [-0.5, *offset, 0.5]")
    return text


def test_synthetic_aliases_preserve_both_loaders_and_cli_output(tmp_path):
    text = synthetic_alias_text()
    path = tmp_path / "synthetic.yaml"
    path.write_text(text, encoding="utf-8")
    expected = load_synthetic_config(SYNTHETIC)
    assert load_synthetic_config(path) == expected
    assert load_cli_config(path) == expected
    proc = subprocess.run([sys.executable, "-B", "-m", "sawopt.cli", "validate", "--config", str(path)], capture_output=True, text=True, check=True)
    assert json.loads(proc.stdout) == {
        "experiment_id": "r6-synthetic-smoke", "method": "lshade",
        "search_fe_limit": 8, "status": "VALID", "synthetic_only": True,
        "validation_points": 3,
    }


def test_synthetic_alias_run_and_review_remain_supported(tmp_path, capsys):
    from sawopt.cli import main
    from sawopt.io.experiment_store import read_experiment_manifest

    path = tmp_path / "synthetic.yaml"
    path.write_text(synthetic_alias_text(), encoding="utf-8")
    repository = tmp_path / "test-repository"
    repository.mkdir()
    assert main(
        ["run", "--config", str(path)], source_sha="a" * 40,
        data_root=tmp_path / "test-external-data", repository_root=repository,
        run_id="20261026T000000Z-00000158",
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "COMPLETED"
    manifest = read_experiment_manifest(result["raw_run_directory"])
    assert manifest["search_fe_count"] == 8
    assert manifest["validation_point_count"] == 3
    assert main(["review", "export", "--run", result["raw_run_directory"],
                 "--repository-root", str(repository)]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["status"] == "ALREADY_VALID"
    assert exported["package_status"] == "READY_FOR_REVIEW"


@pytest.mark.parametrize("variant", ["scalar_alias", "grid_alias", "merge", "duplicate", "duplicate_discriminator", "mixed"])
def test_scientific_dispatch_never_falls_back_to_permissive_yaml(tmp_path, config, variant):
    text = yaml.safe_dump(config, sort_keys=False)
    if variant == "scalar_alias":
        text = text.replace("source: 50.0", "source: &port 50.0").replace("load: 75.0", "load: *port")
    elif variant == "grid_alias":
        # SafeLoader would accept alias sharing, scientific loader must reject.
        config["grids"]["validation"] = config["grids"]["search"]
        text = yaml.safe_dump(config, sort_keys=False)
        assert "&id" in text and "*id" in text
    elif variant == "merge":
        text = text.replace("ports:\n", "ports:\n  <<: {source: 50.0}\n")
    elif variant == "duplicate":
        text += "ports: {domain: positive_real, unit: ohm, source: 50, load: 75}\n"
    elif variant == "duplicate_discriminator":
        text += "schema_id: null\n"
    else:
        text = synthetic_alias_text() + "schema_id: sawopt.scientific_config/1\n"
    path = tmp_path / "bad-scientific.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(CliConfigError):
        load_cli_config(path)
