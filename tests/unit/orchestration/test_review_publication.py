import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sawopt.orchestration.active_runs import (
    active_runs_for_worktree,
    initialize_active_run_registry,
    register_active_run,
)
from sawopt.orchestration.models import RunManifest, RunStatus
from sawopt.orchestration.run_manager import atomic_write_json, mark_review_published


RUN_ID = "synthetic-review-publication"
SOURCE_SHA = "f" * 40
COMPUTATION_FINGERPRINT = "e" * 64


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repository, check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    return result.stdout.strip()


def _write_fixture_package(repository: Path, review_path: str) -> None:
    package = repository / review_path
    package.mkdir(parents=True)
    readme = package / "README.md"
    readme.write_text("Synthetic publication-guard fixture.\n", encoding="utf-8")
    artifacts = package / "artifact_manifest.csv"
    with artifacts.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(("included", "destination_path", "source_sha256", "destination_sha256"))

    manifest = {
        "run_id": RUN_ID,
        "canonical_review_directory": review_path,
        "package_complete": True,
        "redaction_scan": "PASS",
        "completed_cell_count": 1,
        "expected_cell_count": 1,
        "production_execution_source_sha": SOURCE_SHA,
        "computation_fingerprint": COMPUTATION_FINGERPRINT,
        "artifact_manifest_sha256": hashlib.sha256(artifacts.read_bytes()).hexdigest(),
        "readme_sha256": hashlib.sha256(readme.read_bytes()).hexdigest(),
        "hard_size_bytes": 1024 * 1024,
        "package_total_bytes": 0,
    }
    path = package / "review_manifest.json"
    for _ in range(4):
        path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        total_bytes = sum(item.stat().st_size for item in package.rglob("*") if item.is_file())
        if manifest["package_total_bytes"] == total_bytes:
            break
        manifest["package_total_bytes"] = total_bytes
    else:
        raise AssertionError("synthetic package byte count did not stabilize")
    path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")


def test_publication_requires_committed_package_and_releases_matching_active_run(tmp_path):
    repository = tmp_path / "repo"
    persistent_root = tmp_path / "persistent-runs"
    repository.mkdir()
    persistent_root.mkdir()
    run = persistent_root / RUN_ID
    run.mkdir()
    review_path = f"reports/experiment_reviews/qualification/{RUN_ID}"
    review_spec = {"spec_id": "qualification", "study_types": ["qualification"]}
    review_spec_sha = hashlib.sha256(json.dumps(
        review_spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    manifest = RunManifest(
        schema_version=4,
        run_id=RUN_ID,
        experiment_name="synthetic-qualification",
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        project_root=str(repository),
        run_dir=str(run),
        optimizer_run_dir=str(run / "optimizer"),
        command=["synthetic-fixture"],
        config_path=None,
        codex_session_id=None,
        codex_model=None,
        callback_enabled=False,
        review_after_completion=False,
        continuation_mode="disabled",
        review_stage="qualification",
        review_contract_version="1",
        review_output_dir=review_path,
        review_spec_id="qualification",
        review_spec=review_spec,
        review_spec_sha256=review_spec_sha,
        source_commit_sha=SOURCE_SHA,
        source_branch="review-publication-test",
        study_type="qualification",
        run_storage_policy="external_persistent_v1",
        persistent_run_root=str(persistent_root),
        repository_root_at_launch=str(repository),
        source_worktree_at_launch=str(repository),
        experiment_metadata={"computation_fingerprint": COMPUTATION_FINGERPRINT},
    )
    atomic_write_json(run / "run_manifest.json", manifest.to_dict())
    atomic_write_json(run / "status.json", RunStatus(
        state="COMPLETED",
        updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        optimizer_state="COMPLETED",
        continuation_mode="disabled",
        review_evidence_state="EXPORTED",
        review_output_dir=review_path,
    ).to_dict())
    _write_fixture_package(repository, review_path)

    _git(repository, "init", "-b", "review-publication-test")
    _git(repository, "config", "user.name", "Test User")
    _git(repository, "config", "user.email", "test@example.invalid")
    _git(repository, "add", review_path)
    _git(repository, "commit", "-m", "source and synthetic review package")
    initial_head = _git(repository, "rev-parse", "HEAD")

    initialize_active_run_registry(repository, confirm_no_unregistered_active_runs=True)
    register_active_run(
        repository, run_id=RUN_ID, run_dir=run, source_worktree=repository,
        source_head=initial_head, source_branch="review-publication-test",
    )
    with pytest.raises(subprocess.CalledProcessError):
        mark_review_published(
            run, review_path=review_path,
            branch="review-publication-test", commit="missing-commit",
        )
    assert json.loads((run / "status.json").read_text(encoding="utf-8"))["state"] == "COMPLETED"

    commit = _git(repository, "rev-parse", "HEAD")
    _git(repository, "config", "remote.origin.url", str(repository / "remote.git"))
    _git(repository, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    _git(repository, "update-ref", "refs/remotes/origin/review-publication-test", commit)
    _git(repository, "branch", "--set-upstream-to=origin/review-publication-test")

    status = mark_review_published(
        run, review_path=review_path,
        branch="review-publication-test", commit=commit,
    )
    assert status["state"] == "REVIEW_WAITING"
    assert status["review_evidence_state"] == "PUBLISHED"
    assert status["optimizer_state"] == "COMPLETED"
    assert active_runs_for_worktree(repository, repository) == ()

    repeated = mark_review_published(
        run, review_path=review_path,
        branch="review-publication-test", commit=commit,
    )
    assert repeated["state"] == "REVIEW_WAITING"
    assert active_runs_for_worktree(repository, repository) == ()
