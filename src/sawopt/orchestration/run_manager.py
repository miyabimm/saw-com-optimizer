"""Filesystem-backed run manifests, status transitions, and historical status reads."""
from __future__ import annotations

import json
import csv
import hashlib
import os
import re
import socket
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .models import RUN_STATES, RunManifest, RunStatus
from .pid_utils import pid_exists as _pid_exists


TRANSITIONS = {
    "CREATED": {"STARTING", "FAILED"},
    "STARTING": {"RUNNING", "FAILED", "ORPHANED", "ORPHANED_CHILD"},
    "RUNNING": {"COMPLETED", "REVIEW_WAITING", "FAILED", "ORPHANED", "ORPHANED_CHILD"},
    "COMPLETED": {"REVIEW_WAITING"},
    "FAILED": {"STARTING", "REVIEW_WAITING"},
    "CALLBACK_PENDING": set(),
    "CALLBACK_RUNNING": set(),
    "CALLBACK_FAILED": set(),
    "REVIEW_WAITING": set(),
    "REVIEWED": set(),
    "ORPHANED": {"STARTING"},
    "ORPHANED_CHILD": {"STARTING"},
}

LOCK_STALE_AFTER_S = 300.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """Write JSON with flush/fsync/replace so readers never see partial JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _read_lock_metadata(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def read_lock_metadata(path: Path) -> dict[str, Any] | None:
    """Read owner metadata for a durable orchestration lock."""
    return _read_lock_metadata(Path(path))


def lock_owner_pid(path: Path) -> int | None:
    """Return a lock owner's PID, including legacy text-PID locks."""
    metadata = _read_lock_metadata(Path(path))
    if metadata is not None:
        try:
            return int(metadata.get("pid"))
        except (TypeError, ValueError):
            return None
    try:
        return int(Path(path).read_text(encoding="ascii").strip())
    except (OSError, TypeError, ValueError):
        return None


def _lock_age_s(path: Path, metadata: dict[str, Any] | None) -> float:
    created_at = metadata.get("created_at") if metadata else None
    if created_at:
        try:
            created = datetime.fromisoformat(str(created_at))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - created).total_seconds())
        except ValueError:
            pass
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return 0.0


def _reclaim_stale_lock(path: Path, *, stale_after_s: float) -> bool:
    """Atomically quarantine a dead, old lock without deleting a new owner."""
    metadata = _read_lock_metadata(path)
    owner_pid = lock_owner_pid(path)
    if _lock_age_s(path, metadata) < stale_after_s or _pid_exists(owner_pid):
        return False
    quarantine = path.with_name(
        f".{path.name}.stale.{os.getpid()}.{time.monotonic_ns()}"
    )
    try:
        os.replace(path, quarantine)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    else:
        quarantine.unlink(missing_ok=True)
        return True


def reclaim_stale_lock(path: Path, *, stale_after_s: float = LOCK_STALE_AFTER_S) -> bool:
    """Atomically remove a dead, sufficiently old lock if still present."""
    return _reclaim_stale_lock(Path(path), stale_after_s=stale_after_s)


@contextmanager
def exclusive_lock(path: Path, timeout_s: float = 10.0,
                   stale_after_s: float = LOCK_STALE_AFTER_S):
    """Cross-platform lock with owner metadata and stale-lock recovery."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    fd = None
    while time.monotonic() < deadline:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            metadata = {
                "pid": os.getpid(),
                "created_at": utc_now(),
                "hostname": socket.gethostname(),
            }
            os.write(fd, json.dumps(metadata, ensure_ascii=True).encode("utf-8"))
            os.fsync(fd)
            break
        except FileExistsError:
            if not _reclaim_stale_lock(path, stale_after_s=stale_after_s):
                time.sleep(0.01)
        except BaseException:
            if fd is not None:
                os.close(fd)
                path.unlink(missing_ok=True)
                fd = None
            raise
    if fd is None:
        raise TimeoutError(f"timed out acquiring lock: {path}")
    try:
        yield
    finally:
        os.close(fd)
        path.unlink(missing_ok=True)


_exclusive_lock = exclusive_lock


def manifest_path(run_dir: Path) -> Path:
    return Path(run_dir) / "run_manifest.json"


def status_path(run_dir: Path) -> Path:
    return Path(run_dir) / "status.json"


def continuation_delivery_path(run_dir: Path) -> Path:
    return Path(run_dir) / "continuation_delivery.json"


def optimizer_completion_path(run_dir: Path) -> Path:
    return Path(run_dir) / "optimizer_completion.json"


def load_manifest(run_dir: Path) -> RunManifest:
    path = manifest_path(Path(run_dir))
    return RunManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_status(run_dir: Path) -> dict[str, Any]:
    path = status_path(Path(run_dir))
    value = json.loads(path.read_text(encoding="utf-8"))
    RunStatus.from_dict(value)
    return value


def _mutate_status(run_dir: Path, mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    run_dir = Path(run_dir)
    with exclusive_lock(run_dir / ".status.lock"):
        value = load_status(run_dir)
        mutator(value)
        value["updated_at"] = utc_now()
        RunStatus.from_dict(value)
        atomic_write_json(
            status_path(run_dir),
            {key: item for key, item in value.items() if not key.startswith("_")},
        )
        return value


def update_status_fields(run_dir: Path, **updates: Any) -> dict[str, Any]:
    """Update non-state fields while retaining the state-machine authority."""
    return _mutate_status(Path(run_dir), lambda value: value.update(updates))


def transition(run_dir: Path, new_state: str, **updates: Any) -> dict[str, Any]:
    """Apply one validated state transition and persist it atomically."""
    if new_state not in RUN_STATES:
        raise ValueError(f"unknown run state: {new_state}")

    def mutate(value: dict[str, Any]) -> None:
        old_state = value["state"]
        if old_state != new_state and new_state not in TRANSITIONS[old_state]:
            raise ValueError(f"invalid run state transition: {old_state} -> {new_state}")
        value.update(updates)
        value["state"] = new_state
        now = utc_now()
        if new_state == "RUNNING" and value.get("started_at") is None:
            value["started_at"] = now
        if new_state in {"COMPLETED", "FAILED", "ORPHANED", "ORPHANED_CHILD", "REVIEW_WAITING"}:
            value["finished_at"] = value.get("finished_at") or now
            if new_state in {"COMPLETED", "FAILED"}:
                value["optimizer_state"] = new_state
            elif new_state == "ORPHANED":
                value["optimizer_state"] = "UNKNOWN"
        if new_state == "CALLBACK_RUNNING" and value.get("callback_started_at") is None:
            value["callback_started_at"] = now
        if new_state in {"REVIEWED", "CALLBACK_FAILED"}:
            value["callback_finished_at"] = now

    return _mutate_status(Path(run_dir), mutate)


def record_optimizer_completion(run_dir: Path, *, disposition: str,
                                exit_code: int | None, error: str | None = None) -> dict[str, Any]:
    """Persist terminal optimizer evidence before attempting continuation."""
    run_dir = Path(run_dir).resolve()
    manifest = load_manifest(run_dir)
    if disposition not in {"COMPLETED", "FAILED"}:
        raise ValueError(f"invalid optimizer completion disposition: {disposition}")
    result = {
        "schema_version": 1, "run_id": manifest.run_id,
        "disposition": disposition, "exit_code": exit_code, "error": error,
        "result_reference": str(run_dir),
        "optimizer_run_dir": manifest.effective_optimizer_run_dir,
        "completed_at": utc_now(),
    }
    atomic_write_json(optimizer_completion_path(run_dir), result)
    return result


def _read_delivery(run_dir: Path) -> dict[str, Any] | None:
    path = continuation_delivery_path(run_dir)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Existing path means the one-shot slot may have been consumed. Never
        # convert an unreadable ledger into permission to send again.
        raise ValueError("continuation ledger exists but is unreadable; resend forbidden") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("invalid continuation delivery ledger; resend forbidden")
    if value.get("attempt_count") != 1:
        raise ValueError("continuation delivery ledger violates one-attempt contract")
    return value


def load_continuation_delivery(run_dir: Path) -> dict[str, Any] | None:
    """Read the authoritative one-shot ledger; status.json is only a mirror."""
    return _read_delivery(Path(run_dir))


def _git_output(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, encoding="utf-8", errors="replace",
        stderr=subprocess.STDOUT,
    ).strip()


def mark_review_published(run_dir: Path, *, review_path: str, branch: str,
                          commit: str) -> dict[str, Any]:
    """Finalize publication only after canonical committed evidence is upstream."""
    root = Path(run_dir).resolve()
    manifest = load_manifest(root)
    if manifest.uses_retired_agent_transport:
        raise RuntimeError("publication finalization for legacy Codex-linked runs is retired")
    if manifest.schema_version != 4 or not manifest.review_output_dir:
        raise ValueError("publication finalization requires a schema-v4 run")
    expected_path = manifest.review_output_dir.replace("\\", "/").strip("/")
    if review_path.replace("\\", "/").strip("/") != expected_path:
        raise ValueError("review path differs from the manifest canonical directory")
    repo = Path(manifest.project_root).resolve()
    package = (repo / expected_path).resolve()
    try:
        package.relative_to(repo)
    except ValueError as exc:
        raise ValueError("review path escapes repository root") from exc
    if not package.is_dir() or not (package / "review_manifest.json").is_file():
        raise ValueError("canonical review package is missing or incomplete")
    review_manifest = json.loads((package / "review_manifest.json").read_text(encoding="utf-8"))
    if (review_manifest.get("run_id") != manifest.run_id
            or review_manifest.get("canonical_review_directory") != expected_path
            or review_manifest.get("package_complete") is not True
            or review_manifest.get("redaction_scan") != "PASS"
            or review_manifest.get("completed_cell_count") != review_manifest.get("expected_cell_count")):
        raise ValueError("review manifest fails run identity/completeness/redaction checks")
    if (review_manifest.get("production_execution_source_sha") != manifest.source_commit_sha
            or review_manifest.get("computation_fingerprint") != (manifest.experiment_metadata or {}).get("computation_fingerprint")):
        raise ValueError("review manifest provenance differs from the frozen run manifest")
    artifact_manifest = package / "artifact_manifest.csv"
    if not artifact_manifest.is_file():
        raise ValueError("review artifact manifest is missing")
    artifact_digest = hashlib.sha256(artifact_manifest.read_bytes()).hexdigest()
    readme_path = package / "README.md"
    if (artifact_digest != review_manifest.get("artifact_manifest_sha256")
            or not readme_path.is_file()
            or hashlib.sha256(readme_path.read_bytes()).hexdigest() != review_manifest.get("readme_sha256")):
        raise ValueError("review package generated-file hash mismatch")
    with artifact_manifest.open("r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("included", "").casefold() != "true":
                continue
            member = (package / row["destination_path"]).resolve()
            member.relative_to(package)
            if not member.is_file():
                raise ValueError(f"review package member is missing: {row['destination_path']}")
            digest = hashlib.sha256(member.read_bytes()).hexdigest()
            if digest != row.get("source_sha256") or digest != row.get("destination_sha256"):
                raise ValueError(f"review package hash mismatch: {row['destination_path']}")
    total_bytes = sum(path.stat().st_size for path in package.rglob("*") if path.is_file())
    if (total_bytes != review_manifest.get("package_total_bytes")
            or total_bytes >= int(review_manifest.get("hard_size_bytes", 0))):
        raise ValueError("review package total size fails its frozen size gate")
    forbidden = {"stdout.log", "stderr.log", "callback.log"}
    if any(path.name.casefold() in forbidden or re.fullmatch(r"B\d+\.json", path.name, re.IGNORECASE)
           or any(part.casefold() in {"checkpoint", "checkpoints"} for part in path.parts)
           for path in package.rglob("*")):
        raise ValueError("review package contains a default-excluded runtime artifact")
    if _git_output(repo, "branch", "--show-current") != branch:
        raise ValueError("current branch does not match publication branch")
    commit = _git_output(repo, "rev-parse", "--verify", f"{commit}^{{commit}}")
    _git_output(repo, "merge-base", "--is-ancestor", commit, "HEAD")
    listed = _git_output(repo, "ls-tree", "-r", "--name-only", commit, "--", expected_path)
    if not listed:
        raise ValueError("publication commit does not contain the review directory")
    dirty = _git_output(repo, "status", "--porcelain", "--", expected_path)
    if dirty:
        raise ValueError("review directory has uncommitted changes")
    upstream = _git_output(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream != f"origin/{branch}":
        raise ValueError("branch upstream is not the matching origin branch")
    _git_output(repo, "merge-base", "--is-ancestor", commit, upstream)
    status = load_status(root)
    if status.get("optimizer_state") not in {"COMPLETED", "FAILED"}:
        raise ValueError("optimizer is not in a terminal state")
    if status.get("review_evidence_state") == "PUBLISHED":
        if status.get("review_publication_commit") == commit and status.get("review_publication_branch") == branch:
            _release_published_active_run(repo, manifest)
            return status
        raise ValueError("review publication was already finalized differently")
    if status.get("review_evidence_state") != "EXPORTED":
        raise ValueError("review evidence has not passed export completeness/redaction gates")
    published = transition(
        root, "REVIEW_WAITING", review_evidence_state="PUBLISHED",
        review_output_dir=expected_path, review_publication_branch=branch,
        review_publication_commit=commit, review_published_at=utc_now(),
    )
    _release_published_active_run(repo, manifest)
    return published


def _release_published_active_run(repository_root: Path, manifest: RunManifest) -> None:
    """Release a production worktree marker only after publication is durable."""
    if manifest.run_storage_policy != "external_persistent_v1":
        return
    from .active_runs import release_active_run

    release_active_run(repository_root, run_id=manifest.run_id)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_status(run_dir: Path) -> str:
    """Render recorded status; historical callback/queue fields are not verified."""
    run_dir = Path(run_dir).resolve()
    manifest = load_manifest(run_dir)
    status = load_status(run_dir)
    try:
        delivery = load_continuation_delivery(run_dir)
        delivery_state = delivery.get("state") if delivery else status.get("continuation_state", "DISABLED")
        delivery_attempts = delivery.get("attempt_count", 0) if delivery else status.get("continuation_attempt_count", 0)
        delivery_id = delivery.get("delivery_id") if delivery else status.get("continuation_delivery_id")
    except (OSError, ValueError, json.JSONDecodeError):
        delivery_state, delivery_attempts, delivery_id = "AMBIGUOUS", 1, "unreadable-ledger"
    started = parse_timestamp(status.get("started_at")) or parse_timestamp(manifest.created_at)
    elapsed = max(0.0, (datetime.now(timezone.utc) - started).total_seconds()) if started else 0.0
    callback = (
        "review-waiting" if status.get("state") == "REVIEW_WAITING" else
        "completed" if status.get("callback_completed") else
        "failed" if status.get("state") == "CALLBACK_FAILED" else
        "running" if status.get("state") == "CALLBACK_RUNNING" else
        "pending" if manifest.callback_enabled else "disabled"
    )
    worker_pid = status.get("worker_pid")
    optimizer_pid = status.get("optimizer_pid")
    worker_liveness = "alive" if _pid_exists(worker_pid) else "dead/unknown"
    optimizer_liveness = "alive" if _pid_exists(optimizer_pid) else "dead/unknown"
    return "\n".join([
        f"run_id: {manifest.run_id}",
        f"overall_state: {status['state']}",
        f"optimizer.state: {status.get('optimizer_state') or 'UNKNOWN'}",
        f"optimizer.exit_code: {status.get('exit_code')}",
        f"callback.state: {callback}",
        f"callback.attempts: {status.get('callback_attempts', 0)}",
        f"continuation.mode: {manifest.continuation_mode or 'legacy_resume'}",
        f"continuation.state: {delivery_state}",
        f"continuation.attempts: {delivery_attempts}",
        f"continuation.delivery_id: {delivery_id}",
        f"review.evidence: {status.get('review_evidence_state', 'PENDING')}",
        f"worker_pid: {worker_pid} ({worker_liveness})",
        f"optimizer_pid: {optimizer_pid} ({optimizer_liveness})",
        f"elapsed: {elapsed:.1f}s",
        f"run_dir: {run_dir}",
    ])


__all__ = [
    "atomic_write_json", "continuation_delivery_path",
    "exclusive_lock", "format_status", "load_continuation_delivery",
    "load_manifest", "load_status", "lock_owner_pid", "manifest_path",
    "mark_review_published", "optimizer_completion_path",
    "read_lock_metadata", "reclaim_stale_lock", "record_optimizer_completion",
    "status_path", "transition", "update_status_fields", "utc_now",
]
