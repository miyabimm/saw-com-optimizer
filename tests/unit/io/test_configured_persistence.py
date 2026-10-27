"""RED contract tests: synthetic callback records only, never a COM search."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


_FIXTURE_PATH = Path(__file__).resolve().parents[1] / "optimization/test_configured_search.py"
_spec = importlib.util.spec_from_file_location("configured_search_test_fixtures", _FIXTURE_PATH)
_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixtures)

RUN_ID = "20261027T000000Z-00000001"
TEST_SOURCE = "a" * 40


def result_fixture(*, search_fail=None, validation_fail=None):
    snapshot = _fixtures.make_snapshot(budget=8)
    search = _fixtures.synthetic_evaluator(snapshot, fail_at=search_fail)
    validation = _fixtures.synthetic_evaluator(snapshot, fail_at=validation_fail)
    return snapshot, _fixtures.run(snapshot, search, validation)


def build(snapshot, result, *, run_id=RUN_ID, source=TEST_SOURCE):
    from sawopt.io.configured_persistence import build_persistence_plan

    return build_persistence_plan(snapshot, result, run_id=run_id, execution_source_sha=source)


def test_pure_completed_plan_and_defensive_detachment(monkeypatch):
    import sawopt.io.experiment_store as store

    snapshot, result = result_fixture()
    monkeypatch.setattr(store, "validate_data_root", lambda *a, **kw: pytest.fail("filesystem preflight in pure plan"))
    plan = build(snapshot, result)
    snapshot["effective_config"]["experiment_id"] = "changed"
    result["search"]["counters"]["unique_evaluations"] = 0
    assert plan["cell_status"] == "COMPLETED"
    assert plan["search_fes"] == 8
    assert plan["validation_points"] > 0
    assert plan["snapshot"]["effective_config"]["experiment_id"] != "changed"


@pytest.mark.parametrize("search_fail,validation_fail,search_fes", [(1, None, 0), (5, None, 4), (None, 1, 8)])
def test_failure_mapping_keeps_committed_counts_and_does_not_charge_requested_validation(search_fail, validation_fail, search_fes):
    snapshot, result = result_fixture(search_fail=search_fail, validation_fail=validation_fail)
    plan = build(snapshot, result)
    assert plan["cell_status"] == "FAILED"
    assert plan["search_fes"] == search_fes
    assert plan["validation_points"] == 0
    assert plan["reason"]
    assert plan["failure_class"] in {"MODEL", "VALIDATION", "UNKNOWN", "INFRASTRUCTURE"}


@pytest.mark.parametrize("damage", [
    "schema", "seed", "roster", "source", "config_hash", "input_hash", "status",
    "phase", "rank", "objective", "canonical", "counter", "validation_count", "finalist",
])
def test_inconsistent_results_are_rejected(damage):
    snapshot, result = result_fixture()
    result = copy.deepcopy(result)
    if damage == "schema": result["schema_id"] = "wrong"
    elif damage == "seed": result["identity"]["seed"] += 1
    elif damage == "roster": result["identity"]["expected_cells"][0]["cell_id"] = "wrong"
    elif damage == "source": result["identity"]["declared_source_commit_sha"] = "0" * 40
    elif damage == "config_hash": result["identity"]["effective_config_sha256"] = "0" * 64
    elif damage == "input_hash": result["identity"]["input_sha256"].pop("model")
    elif damage == "status": result["search"]["status"] = "EXHAUSTED"
    elif damage == "phase": result["validation"]["record"]["evaluation_phase"] = "SEARCH"
    elif damage == "rank": result["search"]["incumbent"]["rank_key"] = [999]
    elif damage == "objective": result["search"]["incumbent"]["objective"] += 1
    elif damage == "canonical": result["search"]["incumbent"]["canonical_vector"][0] += 0.01
    elif damage == "counter": result["search"]["counters"]["unique_evaluations"] += 1
    elif damage == "validation_count": result["validation"]["requested_grid_points"] += 1
    else: result["validation"]["record"]["canonical_vector"][0] += 0.01
    with pytest.raises(ValueError):
        build(snapshot, result)


def test_persist_completed_fixture_and_reject_run_id_reuse(tmp_path):
    from sawopt.io.configured_persistence import persist_persistence_plan
    from sawopt.io.experiment_store import read_experiment_manifest

    snapshot, result = result_fixture()
    plan = build(snapshot, result)
    root = tmp_path / "external-data"
    path = persist_persistence_plan(plan, data_root=root)
    manifest = read_experiment_manifest(path)
    assert manifest["status"] == "COMPLETED"
    assert manifest["cells"][0]["search_fes"] == 8
    assert manifest["scientific_config_sha256"] == snapshot["effective_config_sha256"]
    assert manifest["scientific_input_sha256"] == snapshot["input_sha256"]
    assert manifest["execution_source_sha"] == TEST_SOURCE
    assert manifest["expected_cells"] == snapshot["effective_config"]["storage"]["expected_cells"]
    assert manifest["search_fe_limit_per_cell"] == 8
    assert manifest["validation_point_limit_per_cell"] == result["validation"]["grid_point_count"]
    assert manifest["observed_checkpoints"] == []
    assert manifest["checkpoint_state"]["status"] == "NONE"
    assert yaml.safe_load((path / "config.yaml").read_bytes()) == snapshot["effective_config"]
    for role, section in (("model", snapshot["effective_config"]["model"]["parameters"]),
                          ("search_grid", snapshot["effective_config"]["grids"]["search"]),
                          ("validation_grid", snapshot["effective_config"]["grids"]["validation"])):
        assert yaml.safe_load((path / "inputs" / f"{role}.yaml").read_bytes()) == section
    assert not (path / "artifacts" / "validation.csv").exists()
    artifact = f"cells/{manifest['expected_cells'][0]['cell_id']}/configured_result.json"
    content = (path / artifact).read_bytes()
    assert hashlib.sha256(content).hexdigest() == manifest["raw_artifact_sha256"][artifact]["sha256"]
    saved = json.loads(content)
    assert saved["classification"] == "TEST_ONLY / NOT_SCIENTIFIC_EVIDENCE"
    assert saved["configured_result"] == result
    assert result["identity"]["declared_source_commit_sha"] != TEST_SOURCE
    before = (path / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        persist_persistence_plan(plan, data_root=root)
    assert (path / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("search_fail,validation_fail,expected_fes", [(1, None, 0), (5, None, 4), (None, 1, 8)])
def test_persist_failed_fixture(tmp_path, search_fail, validation_fail, expected_fes):
    from sawopt.io.configured_persistence import persist_persistence_plan
    from sawopt.io.experiment_store import read_experiment_manifest

    snapshot, result = result_fixture(search_fail=search_fail, validation_fail=validation_fail)
    path = persist_persistence_plan(build(snapshot, result), data_root=tmp_path / "raw")
    manifest = read_experiment_manifest(path)
    assert manifest["status"] == "FAILED"
    assert manifest["cells"][0]["status"] == "FAILED"
    assert manifest["cells"][0]["executed"] is True
    assert manifest["cells"][0]["search_fes"] == expected_fes
    assert manifest["cells"][0]["validation_points"] == 0
    assert len(manifest["errors"]) == 1


@pytest.mark.parametrize("point", ["write", "record_cell", "close"])
def test_persistence_failure_retains_raw_and_never_closes_success(tmp_path, monkeypatch, point):
    from sawopt.io.configured_persistence import persist_persistence_plan
    from sawopt.io.experiment_store import ExperimentRun, read_experiment_manifest

    snapshot, result = result_fixture()
    plan = build(snapshot, result)
    def fail(*args, **kwargs):
        raise OSError("injected incident")
    monkeypatch.setattr(ExperimentRun, {"write": "write_raw_artifact", "record_cell": "record_cell", "close": "close"}[point], fail)
    root = tmp_path / "raw"
    with pytest.raises(OSError, match="injected incident"):
        persist_persistence_plan(plan, data_root=root)
    path = root / "runs" / snapshot["experiment_id"] / RUN_ID
    manifest = read_experiment_manifest(path)
    assert manifest["status"] != "COMPLETED"
    assert manifest["errors"][-1]["classification"] == "IO"
    for relative, digest in manifest["raw_artifact_sha256"].items():
        assert hashlib.sha256((path / relative).read_bytes()).hexdigest() == digest["sha256"]
    before = (path / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        persist_persistence_plan(plan, data_root=root)
    assert (path / "manifest.json").read_bytes() == before


def test_existing_data_root_is_rejected_without_writes(tmp_path):
    from sawopt.io.configured_persistence import persist_persistence_plan

    snapshot, result = result_fixture()
    root = tmp_path / "existing"
    root.mkdir()
    marker = root / "historical-evidence"
    marker.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        persist_persistence_plan(build(snapshot, result), data_root=root)
    assert list(root.iterdir()) == [marker]
    assert marker.read_bytes() == b"preserve"


def test_explicit_review_request_is_denied_without_creating_package(tmp_path):
    from sawopt.io.configured_persistence import ReviewEvidenceUnavailable, export_persistence_review

    with pytest.raises(ReviewEvidenceUnavailable, match="VALIDATION_EVIDENCE_UNAVAILABLE"):
        export_persistence_review(run_path=tmp_path / "run", repository_root=tmp_path / "report-repo")
    assert list(tmp_path.iterdir()) == []


def test_duplicate_initial_population_exhaustion_is_persisted_exactly(tmp_path):
    from sawopt.io.configured_persistence import persist_persistence_plan
    from sawopt.io.experiment_store import read_experiment_manifest

    snapshot = _fixtures.make_snapshot(budget=40, initial_population=8, compact=True, exhaustion_duplicate_streak=1, narrow=True)
    result = _fixtures.run(snapshot, _fixtures.synthetic_evaluator(snapshot))
    assert result["status"] == "EXHAUSTED"
    assert 4 <= result["search"]["summary"]["initial_population"] < 8
    assert result["search"]["counters"]["duplicate_count"] > 0
    plan = build(snapshot, result)
    assert plan["cell_status"] == "INCOMPLETE"
    path = persist_persistence_plan(plan, data_root=tmp_path / "raw")
    manifest = read_experiment_manifest(path)
    assert manifest["status"] == manifest["cells"][0]["status"] == "INCOMPLETE"
    assert manifest["cells"][0]["search_fes"] == result["search"]["counters"]["unique_evaluations"]
    assert manifest["cells"][0]["validation_points"] == result["validation"]["grid_point_count"]
    artifact = path / "cells" / manifest["cells"][0]["cell_id"] / "configured_result.json"
    assert json.loads(artifact.read_bytes())["configured_result"] == result


@pytest.mark.parametrize("damage", ["source", "outside", "overlap", "policy", "extra_summary", "repairs", "population", "attempts"])
def test_forged_accounting_and_summary_rejected_before_storage(tmp_path, damage):
    snapshot, result = result_fixture(search_fail=5 if damage == "attempts" else None)
    if damage == "source": result["accounting"]["unique_evaluations_source"] = "other"
    elif damage == "outside": result["accounting"]["validation_outside_search_budget"] = False
    elif damage == "overlap": result["accounting"]["duplicate_count_overlaps_cache_hits"] = False
    elif damage == "policy": result["accounting"]["failed_attempt_policy"] = "charged"
    elif damage == "extra_summary": result["search"]["summary"]["unexpected"] = 1
    elif damage == "repairs": result["search"]["summary"]["boundary_repair_counts"]["lower"][0] = -1
    elif damage == "population": result["search"]["summary"]["current_population"] = 0
    else:
        c = result["search"]["counters"]
        c["search_evaluator_records_returned"] = c["proposals_total"]
        c["search_evaluator_attempts"] = c["proposals_total"] + 1
        c["search_grid_points_requested"] = c["search_evaluator_attempts"] * c["search_grid_points_per_call"]
    with pytest.raises(ValueError):
        build(snapshot, result)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("phase,value", [("search", float("inf")), ("validation", float("-inf"))])
def test_nonfinite_accepted_return_loss_has_explicit_representation_gap(tmp_path, phase, value):
    snapshot, result = result_fixture()
    record = result["search"]["incumbent"] if phase == "search" else result["validation"]["record"]
    record["metrics"]["source_return_loss_db_min"] = value
    with pytest.raises(ValueError, match="R5_REPRESENTATION_GAP"):
        build(snapshot, result)
    assert list(tmp_path.iterdir()) == []


def test_record_error_failure_preserves_raw_without_success(tmp_path, monkeypatch):
    from sawopt.io.configured_persistence import persist_persistence_plan
    from sawopt.io.experiment_store import ExperimentRun, read_experiment_manifest

    snapshot, result = result_fixture(search_fail=1)
    def fail(*args, **kwargs):
        raise OSError("record error failed")
    monkeypatch.setattr(ExperimentRun, "record_error", fail)
    root = tmp_path / "raw"
    with pytest.raises(ExceptionGroup) as error:
        persist_persistence_plan(build(snapshot, result), data_root=root)
    assert len(error.value.exceptions) == 2
    path = root / "runs" / snapshot["experiment_id"] / RUN_ID
    manifest = read_experiment_manifest(path)
    assert manifest["status"] == "INITIALIZED"
    assert manifest["errors"] == []
    for relative, digest in manifest["raw_artifact_sha256"].items():
        assert hashlib.sha256((path / relative).read_bytes()).hexdigest() == digest["sha256"]
    with pytest.raises(FileExistsError):
        persist_persistence_plan(build(snapshot, result), data_root=root)


@pytest.mark.parametrize("point", ["readback", "manifest_update", "validation", "wrapped_integrity"])
def test_manifest_incidents_preserve_prior_artifacts_and_classify(tmp_path, monkeypatch, point):
    import sawopt.io.configured_persistence as adapter
    import sawopt.io.experiment_store as store

    snapshot, result = result_fixture()
    plan = build(snapshot, result)
    original_create = adapter.create_experiment_run
    original_replace = store.os.replace
    prior = {}
    def create(*args, **kwargs):
        run = original_create(*args, **kwargs)
        manifest = store.read_experiment_manifest(run.path)
        prior.update({name: (run.path / name).read_bytes() for name in manifest["raw_artifact_sha256"]})
        if point == "readback":
            def fail_read(*args, **kwargs):
                raise OSError("readback incident")
            monkeypatch.setattr(adapter, "read_experiment_manifest", fail_read)
        elif point == "manifest_update":
            def fail_replace(*args, **kwargs):
                raise OSError("manifest incident")
            monkeypatch.setattr(store.os, "replace", fail_replace)
        else:
            def fail_validation(*args, **kwargs):
                if point == "wrapped_integrity":
                    raise store.RunStorageError("manifest decode incident") from ValueError("bad JSON")
                raise store.RunValidationError("integrity incident")
            monkeypatch.setattr(adapter, "read_experiment_manifest", fail_validation)
        return run
    monkeypatch.setattr(adapter, "create_experiment_run", create)
    root = tmp_path / "raw"
    with pytest.raises((OSError, ValueError, ExceptionGroup)):
        adapter.persist_persistence_plan(plan, data_root=root)
    monkeypatch.setattr(store.os, "replace", original_replace)
    path = root / "runs" / snapshot["experiment_id"] / RUN_ID
    manifest = store.read_experiment_manifest(path)
    assert manifest["status"] != "COMPLETED"
    for name, contents in prior.items():
        assert (path / name).read_bytes() == contents
        assert hashlib.sha256(contents).hexdigest() == manifest["raw_artifact_sha256"][name]["sha256"]
    if point == "manifest_update":
        orphan = path / "cells" / manifest["cells"][0]["cell_id"] / "configured_result.json"
        assert orphan.is_file()
        assert str(orphan.relative_to(path)) not in manifest["raw_artifact_sha256"]
    else:
        assert manifest["errors"][-1]["classification"] == ("VALIDATION" if point in ("validation", "wrapped_integrity") else "IO")
    with pytest.raises(FileExistsError):
        adapter.persist_persistence_plan(plan, data_root=root)


def test_root_trust_rejects_symlink_worktree_relative_and_unknown_inventory(tmp_path, monkeypatch):
    import sawopt.io.experiment_store as store
    from sawopt.io.configured_persistence import persist_persistence_plan

    snapshot, result = result_fixture()
    plan = build(snapshot, result)
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(target, target_is_directory=True)
    worktree_root = Path(store.__file__).resolve().parents[3]
    for root in (link, link / "raw", worktree_root / "test-only-never-created", Path("relative")):
        with pytest.raises((ValueError, FileExistsError)):
            persist_persistence_plan(plan, data_root=root)
    assert list(target.iterdir()) == []
    def fail_discovery(*args):
        raise store.RunValidationError("worktree inventory unavailable")
    monkeypatch.setattr(store, "_discover_worktree_roots", fail_discovery)
    root = tmp_path / "raw"
    with pytest.raises(ValueError, match="inventory"):
        persist_persistence_plan(plan, data_root=root)
    assert not root.exists()


def test_fresh_root_check_is_not_concurrent_writer_ownership_attestation(tmp_path, monkeypatch):
    import sawopt.io.configured_persistence as adapter

    snapshot, result = result_fixture()
    root = tmp_path / "raw"
    create = adapter.create_experiment_run
    def concurrent_creation(*args, **kwargs):
        root.mkdir()
        (root / "other-writer-marker").write_bytes(b"preserve")
        return create(*args, **kwargs)
    monkeypatch.setattr(adapter, "create_experiment_run", concurrent_creation)
    path = adapter.persist_persistence_plan(build(snapshot, result), data_root=root)
    assert path.is_dir()
    assert (root / "other-writer-marker").read_bytes() == b"preserve"


def test_adapter_fresh_import_has_no_write_or_execution_side_effects(tmp_path):
    guard = r'''
import sys

def audit(event, args):
    if event == "open":
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (1 | 2 | 64 | 512 | 1024)):
            raise AssertionError("filesystem write")
    if event in ("os.mkdir", "os.remove", "os.rename", "os.rmdir", "subprocess.Popen"):
        raise AssertionError("side effect: " + event)
sys.addaudithook(audit)
from sawopt.io.configured_persistence import build_persistence_plan
assert callable(build_persistence_plan)
'''
    subprocess.run([sys.executable, "-B", "-c", guard], cwd=tmp_path,
                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, check=True)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("run_id,source", [(None, TEST_SOURCE), ("../unsafe", TEST_SOURCE), (RUN_ID, None), (RUN_ID, "bad")])
def test_invalid_identifiers_are_rejected(run_id, source):
    snapshot, result = result_fixture()
    with pytest.raises(ValueError):
        build(snapshot, result, run_id=run_id, source=source)
