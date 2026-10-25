from __future__ import annotations

import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sawopt.io.experiment_store import (
    ExperimentRun,
    RunValidationError,
    create_experiment_run,
    validate_data_root,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SOURCE_SHA = "a" * 40


def _cells():
    return [
        {"cell_id": "t0-de-seed1", "topology": "t0", "method": "de", "seed": 1},
        {"cell_id": "t1-de-seed1", "topology": "t1", "method": "de", "seed": 1},
    ]


def _create(tmp_path, *, data_root=None, run_id="20261023T120000Z-0123abcd", **kwargs):
    root = Path(data_root) if data_root is not None else Path(tmp_path) / "external-data"
    root.parent.mkdir(parents=True, exist_ok=True)
    return create_experiment_run(
        "synthetic-review-test",
        data_root=root,
        required_free_bytes=1024 * 1024,
        run_id=run_id,
        source_sha=SOURCE_SHA,
        effective_config=kwargs.pop("effective_config", {
            "model": {"velocity_m_s": 3480.0}, "api_token": "secret-value"
        }),
        scientific_inputs={
            "model": {"velocity_m_s": 3480.0},
            "search_grid": {"frequencies_hz": [1.0, 2.0]},
            "validation_grid": {"frequencies_hz": [1.0, 1.5, 2.0]},
        },
        expected_cells=_cells(),
        search_fe_limit=128,
        validation_point_limit=3,
        review_context={
            "purpose": "Synthetic store and package contract test",
            "conditions": "No physics or optimizer execution",
            "findings": "Only fixture records were written",
            "limitations": "Does not qualify any scientific behavior",
            "review_instructions": "Inspect hashes and cell statuses",
            "scientific_disposition": "CLAIM_PENDING_REVIEW",
            "requires_comparison": False,
            "requires_validation": False,
        },
        **kwargs,
    )


def test_data_root_requires_explicit_absolute_external_location(tmp_path, monkeypatch):
    monkeypatch.delenv("SAWOPT_DATA_ROOT", raising=False)
    with pytest.raises(RunValidationError, match="SAWOPT_DATA_ROOT"):
        validate_data_root()
    with pytest.raises(RunValidationError, match="absolute"):
        validate_data_root("relative/data")
    with pytest.raises(RunValidationError, match="worktree|repository"):
        validate_data_root(REPOSITORY_ROOT / "nested-data")
    assert not (REPOSITORY_ROOT / "nested-data").exists()


def test_data_root_rejects_linked_worktree(tmp_path, monkeypatch):
    from sawopt.io import experiment_store

    repository = tmp_path / "repository"
    repository.mkdir()
    package_dir = repository / "src" / "sawopt" / "io"
    package_dir.mkdir(parents=True)
    module_path = package_dir / "experiment_store.py"
    module_path.touch()
    linked_worktree = tmp_path / "linked-worktree"

    def git(*args):
        subprocess.run(
            ["git", *args], cwd=repository, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    git("init", "-b", "main")
    git("config", "user.name", "Storage Test")
    git("config", "user.email", "storage@example.invalid")
    (repository / "tracked.txt").write_text("fixture\n", encoding="utf-8")
    git("add", "tracked.txt", "src/sawopt/io/experiment_store.py")
    git("commit", "-m", "fixture")
    git("worktree", "add", "--detach", str(linked_worktree), "HEAD")
    monkeypatch.setattr(experiment_store, "__file__", str(module_path))

    candidate = linked_worktree / "external-data"
    with pytest.raises(RunValidationError, match="inside a Git worktree"):
        validate_data_root(candidate)
    assert not candidate.exists()


def test_data_root_reads_explicit_environment_without_creating_missing_root(tmp_path, monkeypatch):
    configured = tmp_path / "configured-data-root"
    monkeypatch.setenv("SAWOPT_DATA_ROOT", str(configured))
    assert validate_data_root(required_free_bytes=1) == configured
    assert not configured.exists()


def test_data_root_rejects_symlink_and_missing_worktree_inventory(tmp_path, monkeypatch):
    target = tmp_path / "real"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(RunValidationError, match="symlink|reparse"):
        validate_data_root(alias)


def test_data_root_rejects_nested_repository_and_obvious_capacity_shortfall(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from sawopt.io import experiment_store

    nested_repo = tmp_path / "nested-repository"
    (nested_repo / ".git").mkdir(parents=True)
    with pytest.raises(RunValidationError, match="another Git repository"):
        validate_data_root(
            nested_repo / "data",
        )

    monkeypatch.setattr(experiment_store.shutil, "disk_usage", lambda _path: SimpleNamespace(free=0))
    with pytest.raises(RunValidationError, match="free bytes"):
        validate_data_root(
            tmp_path / "capacity-data", required_free_bytes=1,
        )


def test_worktree_discovery_uncertainty_fails_closed_without_mutating_destination(tmp_path, monkeypatch):
    from sawopt.io import experiment_store

    monkeypatch.setattr(
        experiment_store, "_discover_worktree_roots",
        lambda _repo: (_ for _ in ()).throw(RunValidationError("inventory unavailable")),
    )
    destination = tmp_path / "untrusted-data"
    with pytest.raises(RunValidationError, match="inventory unavailable"):
        validate_data_root(destination)
    assert not destination.exists()


def test_write_probe_collision_never_deletes_or_changes_preexisting_file(tmp_path, monkeypatch):
    from sawopt.io import experiment_store

    sentinel = tmp_path / ".sawopt-write-probe-0123456789abcdef"
    sentinel.write_bytes(b"owned by another process")
    original_stat = sentinel.stat()
    names = iter(("0123456789abcdef", "fedcba9876543210"))
    monkeypatch.setattr(experiment_store.secrets, "token_hex", lambda _size: next(names))

    assert validate_data_root(tmp_path / "external-data", required_free_bytes=1) == tmp_path / "external-data"
    assert sentinel.read_bytes() == b"owned by another process"
    current_stat = sentinel.stat()
    assert (current_stat.st_dev, current_stat.st_ino) == (original_stat.st_dev, original_stat.st_ino)
    assert not (tmp_path / ".sawopt-write-probe-fedcba9876543210").exists()


def test_write_probe_fsync_failure_cleans_only_its_owned_probe(tmp_path, monkeypatch):
    from sawopt.io import experiment_store

    monkeypatch.setattr(
        experiment_store.os, "fsync",
        lambda _fd: (_ for _ in ()).throw(OSError("injected fsync failure")),
    )
    with pytest.raises(experiment_store.RunStorageError, match="injected fsync failure"):
        validate_data_root(tmp_path / "external-data", required_free_bytes=1)
    assert not list(tmp_path.glob(".sawopt-write-probe-*"))
    assert not (tmp_path / "external-data").exists()


def test_data_root_permission_probe_failure_is_a_classified_io_error(tmp_path, monkeypatch):
    from sawopt.io import experiment_store

    monkeypatch.setattr(
        experiment_store, "_probe_writable",
        lambda _path: (_ for _ in ()).throw(experiment_store.RunStorageError("denied")),
    )
    with pytest.raises(experiment_store.RunStorageError, match="denied"):
        validate_data_root(
            tmp_path / "not-created",
        )
    assert not (tmp_path / "not-created").exists()


def test_data_root_rejects_file_collision_and_run_id_traversal(tmp_path):
    root_file = tmp_path / "data-file"
    root_file.write_text("not a directory", encoding="utf-8")
    with pytest.raises(RunValidationError, match="not a directory"):
        validate_data_root(root_file)
    with pytest.raises(RunValidationError, match="run_id"):
        _create(tmp_path, run_id="../20261023T120000Z-0123abcd")
    assert not (tmp_path / "external-data" / "runs").exists()


def test_run_creation_freezes_config_source_and_all_expected_cells(tmp_path):
    run = _create(tmp_path)
    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["experiment_id"] == "synthetic-review-test"
    assert manifest["run_id"] == "20261023T120000Z-0123abcd"
    assert manifest["execution_source_sha"] == SOURCE_SHA
    assert manifest["status"] == "INITIALIZED"
    assert [cell["cell_id"] for cell in manifest["cells"]] == ["t0-de-seed1", "t1-de-seed1"]
    assert all(cell["status"] == "NOT_STARTED" for cell in manifest["cells"])
    assert manifest["search_fe_limit_per_cell"] == 128
    assert manifest["validation_point_limit_per_cell"] == 3
    assert set(manifest["scientific_input_sha256"]) == {"model", "search_grid", "validation_grid"}
    raw_config = (run.path / "config.yaml").read_bytes()
    assert manifest["config_file_sha256"] == hashlib.sha256(raw_config).hexdigest()
    assert "api_token: secret-value" in raw_config.decode()


def test_raw_artifact_persistence_is_binary_safe_hash_registered_and_path_scoped(tmp_path):
    from sawopt.io.experiment_store import read_experiment_manifest

    run = _create(tmp_path)
    existing_payload = b"existing successful artifact"
    run.write_raw_artifact("arrays/known.bin", existing_payload)
    with pytest.raises(FileExistsError):
        run.write_raw_artifact("arrays/known.bin", b"must not replace")
    assert (run.path / "arrays/known.bin").read_bytes() == existing_payload
    payload = b"\x00\xffsynthetic raw cell payload"
    record = run.write_raw_artifact("cells/t0-de-seed1/result.bin", payload)
    assert record == {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}
    assert (run.path / "cells/t0-de-seed1/result.bin").read_bytes() == payload
    manifest = read_experiment_manifest(run.path)
    assert manifest["raw_artifact_sha256"]["cells/t0-de-seed1/result.bin"] == record
    with pytest.raises(RunValidationError, match="cell directory"):
        run.write_raw_artifact("cells/unknown/result.bin", b"x")
    with pytest.raises(RunValidationError, match="under cells"):
        run.write_raw_artifact("manifest.json", b"overwrite")


def test_invalid_ids_and_bad_inputs_fail_before_creating_a_run(tmp_path):
    for experiment_id in ("../escape", "Uppercase", "bad_slug-"):
        with pytest.raises(RunValidationError):
            create_experiment_run(
                experiment_id,
                data_root=tmp_path / "external-data",
                required_free_bytes=1024 * 1024,
                run_id="20261023T120000Z-0123abcd",
                source_sha=SOURCE_SHA,
                effective_config={},
                scientific_inputs={"model": {}, "search_grid": {}, "validation_grid": {}},
                expected_cells=_cells(),
                search_fe_limit=4,
                validation_point_limit=2,
                review_context={},
            )
    assert not (tmp_path / "external-data" / "runs").exists()


def test_existing_run_collision_is_never_overwritten(tmp_path):
    first = _create(tmp_path)
    before = (first.path / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        _create(tmp_path)
    assert (first.path / "manifest.json").read_bytes() == before


def test_concurrent_same_run_creation_has_exactly_one_winner(tmp_path):
    def attempt(_):
        try:
            return _create(tmp_path).path
        except FileExistsError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    assert sum(path is not None for path in outcomes) == 1
    winner = next(path for path in outcomes if path is not None)
    assert (winner / "manifest.json").is_file()
    assert not list(winner.parent.glob(".r5-*.tmp"))


def test_cell_status_is_fail_closed_and_terminal_cells_cannot_be_committed_twice(tmp_path):
    run = _create(tmp_path)
    run.record_cell("t0-de-seed1", status="COMPLETED", executed=True, search_fes=32,
                    validation_points=3, result={"feasible": False, "worst_il_db": None})
    with pytest.raises(ValueError, match="terminal|committed"):
        run.record_cell("t0-de-seed1", status="FAILED", reason="late overwrite",
                        failure_class="INFRASTRUCTURE")
    with pytest.raises(ValueError, match="executed"):
        run.record_cell("t1-de-seed1", status="COMPLETED", executed=False)
    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cells"][0]["status"] == "COMPLETED"
    assert manifest["cells"][1]["status"] == "NOT_STARTED"


def test_nonfinite_values_are_rejected_but_explicit_null_with_status_is_preserved(tmp_path):
    with pytest.raises(RunValidationError):
        _create(tmp_path, effective_config={"bad": float("nan")})
    run = _create(tmp_path / "valid")
    run.record_cell("t0-de-seed1", status="FAILED", reason="metric unavailable",
                    failure_class="MODEL", result={"worst_il_db": None})
    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cells"][0]["result"]["worst_il_db"] is None
    assert manifest["cells"][0]["status"] == "FAILED"


def test_artifact_manifest_update_failure_leaves_auditable_orphan_and_preserves_prior_file(tmp_path, monkeypatch):
    from sawopt.io import experiment_store
    from sawopt.io.experiment_store import read_experiment_manifest
    from sawopt.reporting.experiment_review import ReviewPackageError, export_review_package

    run = _create(tmp_path)
    prior = b"old registered artifact"
    run.write_raw_artifact("arrays/prior.bin", prior)
    original_manifest = run.manifest
    original_replace = experiment_store.os.replace

    def fail_manifest_replace(source, destination, *args, **kwargs):
        if destination == "manifest.json":
            raise OSError("injected manifest publication failure")
        return original_replace(source, destination, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(experiment_store.os, "replace", fail_manifest_replace)
        with pytest.raises(experiment_store.RunStorageError, match="injected manifest publication failure"):
            run.write_raw_artifact("arrays/orphan.bin", b"published before manifest failure")

    after_failure = read_experiment_manifest(run.path)
    assert after_failure["raw_artifact_sha256"] == original_manifest["raw_artifact_sha256"]
    assert (run.path / "arrays/prior.bin").read_bytes() == prior
    assert (run.path / "arrays/orphan.bin").read_bytes() == b"published before manifest failure"
    assert "arrays/orphan.bin" not in after_failure["raw_artifact_sha256"]
    run.close()
    repository = tmp_path / "review-repository"
    repository.mkdir()
    with pytest.raises(ReviewPackageError, match="missing its manifest hash"):
        export_review_package(run.path, repository_root=repository)
    assert (run.path / "arrays/prior.bin").read_bytes() == prior


def test_checkpoint_manifest_update_failure_leaves_stale_convergence_for_fail_closed_export(tmp_path, monkeypatch):
    from sawopt.io import experiment_store
    from sawopt.reporting.experiment_review import ReviewPackageError, export_review_package

    run = _create(tmp_path)
    run.record_cell("t0-de-seed1", status="COMPLETED", executed=True,
                    search_fes=12, validation_points=3)
    old_manifest = run.manifest
    old_convergence = (run.path / "convergence.csv").read_bytes()
    original_replace = experiment_store.os.replace

    def fail_manifest_replace(source, destination, *args, **kwargs):
        if destination == "manifest.json":
            raise OSError("injected manifest publication failure")
        return original_replace(source, destination, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(experiment_store.os, "replace", fail_manifest_replace)
        with pytest.raises(experiment_store.RunStorageError, match="injected manifest publication failure"):
            run.record_checkpoint(
                "t0-de-seed1", phase="SEARCH", search_fes=10, validation_points=0,
                metric_name="objective", metric_value=-1.0, unit="score",
                observed_at_utc="2026-10-23T12:02:00Z",
            )

    assert run.manifest["observed_checkpoints"] == old_manifest["observed_checkpoints"]
    assert (run.path / "convergence.csv").read_bytes() != old_convergence
    run.close()
    repository = tmp_path / "review-repository"
    repository.mkdir()
    with pytest.raises(ReviewPackageError, match="hash mismatch: convergence.csv"):
        export_review_package(run.path, repository_root=repository)
    assert (run.path / "convergence.csv").read_bytes() != old_convergence


def test_checkpoint_observations_require_execution_and_reconcile_to_final_cell_counters(tmp_path):
    run = _create(tmp_path)
    with pytest.raises(RunValidationError, match="executed"):
        run.record_checkpoint(
            "t0-de-seed1", phase="SEARCH", search_fes=1, validation_points=0,
            metric_name="objective", metric_value=1.0, unit="score",
            observed_at_utc="2026-10-23T12:00:00Z",
        )
    run.record_cell("t0-de-seed1", status="RUNNING", executed=True, search_fes=1)
    run.record_checkpoint(
        "t0-de-seed1", phase="SEARCH", search_fes=2, validation_points=0,
        metric_name="objective", metric_value=1.0, unit="score",
        observed_at_utc="2026-10-23T12:00:00Z",
    )
    run.record_cell("t0-de-seed1", status="FAILED", executed=True, search_fes=1,
                    reason="synthetic early failure", failure_class="MODEL")
    with pytest.raises(RunValidationError, match="exceed their cell"):
        run.close()


@pytest.mark.parametrize("pass_error_to_close", [False, True])
def test_completed_run_rejects_recorded_run_errors(tmp_path, pass_error_to_close):
    run = _create(tmp_path)
    for cell_id in ("t0-de-seed1", "t1-de-seed1"):
        run.record_cell(cell_id, status="COMPLETED", executed=True, search_fes=1)
    error = {"classification": "MODEL", "message": "synthetic run-level failure"}
    if not pass_error_to_close:
        run.record_error(**error)
        with pytest.raises(RunValidationError, match="run-level errors"):
            run.close(status="COMPLETED")
    else:
        with pytest.raises(RunValidationError, match="run-level errors"):
            run.close(status="COMPLETED", errors=[error])
    manifest = run.manifest
    assert manifest["status"] != "COMPLETED"
    assert manifest["errors"] == [error]


def test_automatic_close_with_all_completed_cells_and_no_errors_is_completed(tmp_path):
    run = _create(tmp_path)
    for cell_id in ("t0-de-seed1", "t1-de-seed1"):
        run.record_cell(cell_id, status="COMPLETED", executed=True, search_fes=1)
    assert run.close()["status"] == "COMPLETED"


def test_automatic_close_with_all_completed_cells_and_run_error_is_failed(tmp_path):
    run = _create(tmp_path)
    for cell_id in ("t0-de-seed1", "t1-de-seed1"):
        run.record_cell(cell_id, status="COMPLETED", executed=True, search_fes=1)
    run.record_error(classification="MODEL", message="synthetic run-level failure")
    assert run.close()["status"] == "FAILED"


def test_manifest_updates_are_atomic_and_concurrent_cell_commits_do_not_overwrite(tmp_path):
    run = _create(tmp_path)

    def fail_cell(cell_id):
        run.record_cell(cell_id, status="FAILED", reason="fixture failure",
                        failure_class="MODEL", search_fes=3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(fail_cell, ("t0-de-seed1", "t1-de-seed1")))
    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["search_fe_count"] == 6
    assert [cell["status"] for cell in manifest["cells"]] == ["FAILED", "FAILED"]
    assert not list(run.path.glob(".manifest.*.tmp"))
    run.close()
    with pytest.raises(RunValidationError, match="double commit"):
        run.close()


def test_recorded_checkpoint_stream_is_bound_to_run_and_hashes_observed_files(tmp_path):
    run = _create(tmp_path)
    store = run.checkpoint_store("lshade")
    store.write(lambda path: path.write_text('{"state": "fixture"}', encoding="utf-8"))
    run.refresh_checkpoint_state()
    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    stream = manifest["checkpoint_state"]["streams"][0]
    assert stream["name"] == "lshade"
    assert stream["files"]["latest.json"]["sha256"] == hashlib.sha256(
        (run.path / "checkpoints/lshade/latest.json").read_bytes()
    ).hexdigest()
    assert stream["run_id"] == manifest["run_id"]


def test_checkpoint_handles_cannot_mutate_a_closed_raw_run(tmp_path):
    run = _create(tmp_path)
    checkpoints = run.checkpoint_store("lshade")
    checkpoints.write(lambda path: path.write_text('{"fixture": true}', encoding="utf-8"))
    run.close(status="INCOMPLETE")
    before = (run.path / "checkpoints/lshade/latest.json").read_bytes()
    with pytest.raises(RunValidationError, match="closed raw runs"):
        checkpoints.write(lambda path: path.write_text('{"fixture": false}', encoding="utf-8"))
    with pytest.raises(RunValidationError, match="closed raw runs"):
        run.checkpoint_store("other")
    assert (run.path / "checkpoints/lshade/latest.json").read_bytes() == before


def test_failed_creation_cleans_staging_directory_without_partial_manifest(tmp_path, monkeypatch):
    from sawopt.io import experiment_store

    monkeypatch.setattr(experiment_store, "_rename_noreplace_at", lambda *_: (_ for _ in ()).throw(OSError("publish failed")))
    with pytest.raises(OSError, match="publish failed"):
        _create(tmp_path)
    experiment_dir = tmp_path / "external-data/runs/synthetic-review-test"
    assert not list(experiment_dir.glob(".r5-*.tmp"))
    assert not list(experiment_dir.glob("20261023T120000Z-0123abcd"))
