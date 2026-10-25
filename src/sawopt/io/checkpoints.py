"""Atomic, bounded-retention storage for JSON optimizer checkpoints.

Checkpoint files are runtime recovery artifacts. Analysis history belongs in
the run's ordinary CSV/JSONL outputs and is not managed here.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from .lifecycle import RunDisposition


_T = TypeVar("_T")
_POLICY_VERSION = 1
_POLICY_NAME = "rolling_latest_previous"


class CheckpointLoadError(ValueError):
    """No retained checkpoint could be read and accepted by its validator."""


class CheckpointFinalizationError(ValueError):
    """A completed run could not safely promote a valid final checkpoint."""


@dataclass(frozen=True)
class LoadedCheckpoint:
    """A validated payload and the retained file it came from."""

    state: Mapping[str, Any]
    source: Path
    recovered_from_previous: bool


@dataclass(frozen=True)
class FinalizedCheckpoint:
    """Result of promoting a stream's last valid state."""

    path: Path
    source: Path
    removed_runtime_files: int
    write_count: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_json(path: Path, validator: Callable[[Mapping[str, Any]], Any] | None = None):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read checkpoint {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"checkpoint payload must be a JSON object: {path}")
    if validator is not None:
        validator(value)
    return value


class CheckpointStore:
    """One independent latest/previous/final checkpoint stream.

    The supplied writer remains responsible for the historical state format.
    It receives a same-directory temporary path, which is fully parsed and
    optionally validated before either retained generation is changed.
    """

    def __init__(self, directory: str | Path, *, run_directory: str | Path | None = None):
        self.directory = Path(directory).resolve()
        self.run_directory = Path(run_directory).resolve() if run_directory else None
        self.latest_path = self.directory / "latest.json"
        self.previous_path = self.directory / "previous.json"
        self.final_path = self.directory / "final.json"
        self.pinned_directory = self.directory / "pinned"
        self.retention_path = self.directory / "retention.json"

    @property
    def has_runtime_state(self) -> bool:
        return self.latest_path.is_file() or self.previous_path.is_file()

    @property
    def has_state(self) -> bool:
        return self.has_runtime_state or self.final_path.is_file()

    def _ensure_policy_metadata(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.retention_path.exists():
            _atomic_write_json(self.retention_path, {
                "format_version": _POLICY_VERSION,
                "policy": _POLICY_NAME,
                "runtime_retention_count": 2,
                "latest": self.latest_path.name,
                "previous": self.previous_path.name,
                "final": self.final_path.name,
                "pinned_directory": self.pinned_directory.name,
                "state": "ACTIVE",
            })
        if self.run_directory is not None:
            policy_path = self.run_directory / "metadata" / "recovery_policy.json"
            if not policy_path.exists():
                _atomic_write_json(policy_path, {
                    "policy_version": _POLICY_VERSION,
                    "checkpoint_policy": _POLICY_NAME,
                    "checkpoint_retention_count": 2,
                    "checkpoint_rotation_enabled": True,
                    "final_checkpoint_present": False,
                    "pinned_checkpoint_count": 0,
                    "history_artifacts": [],
                    "status": "ACTIVE",
                })

    def _mark_active(self) -> None:
        if self.retention_path.is_file():
            try:
                metadata = json.loads(self.retention_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                metadata = {}
            if metadata.get("state") != "ACTIVE":
                metadata.update({"state": "ACTIVE"})
                metadata.pop("finalized_at_utc", None)
                _atomic_write_json(self.retention_path, metadata)
        if self.run_directory is not None:
            marker_path = self.run_directory / "metadata" / "run_completion.json"
            if marker_path.is_file():
                marker_path.unlink()
            policy_path = self.run_directory / "metadata" / "recovery_policy.json"
            if policy_path.is_file():
                try:
                    policy = json.loads(policy_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    policy = {}
                if policy.get("status") != "ACTIVE":
                    policy.update({
                        "status": "ACTIVE",
                        "final_checkpoint_present": self.final_path.is_file(),
                    })
                    policy.pop("finalized_at_utc", None)
                    _atomic_write_json(policy_path, policy)

    def _validated_state(self, path: Path, validator=None, preflight_validator=None) -> dict[str, Any]:
        if preflight_validator is not None:
            preflight_validator(path)
        return _read_json(path, validator)

    def write(
        self,
        writer: Callable[[Path], Any],
        *,
        validator: Callable[[Mapping[str, Any]], Any] | None = None,
    ) -> Path:
        """Write one new generation without exposing partial data to readers."""
        self._ensure_policy_metadata()
        self._mark_active()
        temporary = self.directory / f".latest.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            writer(temporary)
            if not temporary.is_file():
                raise OSError(f"checkpoint writer did not create {temporary}")
            self._validated_state(temporary, validator)
            # Existing serializers may not fsync. Flush the completed file
            # before rotation so a process or power loss cannot publish a
            # buffered partial write as the new latest generation.
            with temporary.open("rb+") as stream:
                os.fsync(stream.fileno())

            if self.latest_path.is_file():
                try:
                    self._validated_state(self.latest_path, validator)
                except Exception:
                    # Preserve a known-good previous generation if latest is
                    # already damaged; the new complete generation replaces it.
                    pass
                else:
                    os.replace(self.latest_path, self.previous_path)
            os.replace(temporary, self.latest_path)
            try:
                stream_metadata = json.loads(self.retention_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                stream_metadata = {}
            stream_metadata["write_count"] = int(stream_metadata.get("write_count", 0)) + 1
            stream_metadata["state"] = "ACTIVE"
            _atomic_write_json(self.retention_path, stream_metadata)
            return self.latest_path
        finally:
            temporary.unlink(missing_ok=True)

    def load_state(
        self,
        *,
        validator: Callable[[Mapping[str, Any]], Any] | None = None,
        preflight_validator: Callable[[Path], Any] | None = None,
        include_final: bool = True,
    ) -> LoadedCheckpoint:
        """Load latest, then previous (and optionally final) after validation.

        ``validator`` must not mutate a live optimizer. Callers that need to
        validate optimizer compatibility should use a fresh backend instance.
        """
        candidates = [self.latest_path, self.previous_path]
        if include_final:
            candidates.append(self.final_path)
        failures = []
        for index, path in enumerate(candidates):
            if not path.is_file():
                continue
            try:
                state = self._validated_state(path, validator, preflight_validator)
            except Exception as exc:
                failures.append(f"{path.name}: {type(exc).__name__}: {exc}")
                continue
            return LoadedCheckpoint(
                state=state,
                source=path,
                recovered_from_previous=(path == self.previous_path),
            )
        if not failures:
            raise FileNotFoundError(f"no retained checkpoint in {self.directory}")
        raise CheckpointLoadError(
            "no valid retained checkpoint; " + "; ".join(failures)
        )

    def pin(self, label: str, *, source: str = "latest") -> Path:
        """Copy a named latest/previous/final state into durable pinned storage."""
        self._ensure_policy_metadata()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", str(label)):
            raise ValueError("pin label must be a short filesystem-safe name")
        sources = {
            "latest": self.latest_path,
            "previous": self.previous_path,
            "final": self.final_path,
        }
        if source not in sources:
            raise ValueError("source must be 'latest', 'previous', or 'final'")
        origin = sources[source]
        _read_json(origin)
        self.pinned_directory.mkdir(parents=True, exist_ok=True)
        target = self.pinned_directory / f"{label}.json"
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            shutil.copyfile(origin, temporary)
            _read_json(temporary)
            with temporary.open("rb+") as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        if self.run_directory is not None:
            policy_path = self.run_directory / "metadata" / "recovery_policy.json"
            policy = {}
            if policy_path.is_file():
                try:
                    policy = json.loads(policy_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    policy = {}
            policy["pinned_checkpoint_count"] = sum(
                1 for path in self.run_directory.rglob("pinned/*.json") if path.is_file()
            )
            _atomic_write_json(policy_path, policy)
        return target

    def finalize(
        self,
        *,
        validator: Callable[[Mapping[str, Any]], Any] | None = None,
    ) -> FinalizedCheckpoint:
        """Promote the newest valid payload and then remove runtime generations."""
        candidates = (self.latest_path, self.previous_path, self.final_path)
        failures = []
        selected = None
        for path in candidates:
            if not path.is_file():
                continue
            try:
                self._validated_state(path, validator)
            except Exception as exc:
                failures.append(f"{path.name}: {type(exc).__name__}: {exc}")
                continue
            selected = path
            break
        if selected is None:
            if failures:
                raise CheckpointFinalizationError(
                    "no valid state to finalize; " + "; ".join(failures)
                )
            raise CheckpointFinalizationError(
                f"no checkpoint state to finalize in {self.directory}"
            )

        source = selected
        if selected != self.final_path:
            os.replace(selected, self.final_path)
        # A failed verification leaves previous/runtime state available.
        self._validated_state(self.final_path, validator)

        removed = 0
        for path in (self.latest_path, self.previous_path):
            if path.exists():
                path.unlink()
                removed += 1
        for path in self.directory.glob(".latest.*.tmp"):
            path.unlink(missing_ok=True)
            removed += 1

        metadata = {}
        if self.retention_path.is_file():
            try:
                metadata = json.loads(self.retention_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                metadata = {}
        metadata.update({
            "state": "FINALIZED",
            "final": self.final_path.name,
            "finalized_at_utc": _utc_now(),
        })
        _atomic_write_json(self.retention_path, metadata)
        return FinalizedCheckpoint(
            self.final_path, source, removed, int(metadata.get("write_count", 0))
        )


def _history_artifacts(run_directory: Path) -> list[str]:
    paths = []
    for path in sorted(run_directory.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(run_directory)
        parts = relative.parts
        if any(part.casefold() in {"checkpoints", "pinned"} for part in parts):
            continue
        suffix = path.suffix.casefold()
        is_history_json = suffix == ".json" and any(
            part.casefold() in {"history", "results", "trials"} for part in parts[:-1]
        )
        if suffix in {".csv", ".jsonl"} or is_history_json:
            paths.append(relative.as_posix())
    return paths


def _successful_completion_record(run_directory: Path) -> bool:
    marker_path = run_directory / "metadata" / "run_completion.json"
    if not marker_path.is_file():
        return False
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if (marker.get("disposition") != RunDisposition.COMPLETED.value
            or marker.get("status") != RunDisposition.COMPLETED.value):
        return False
    return True


def finalize_run_checkpoints(run_directory: str | Path) -> dict[str, Any]:
    """Finalize only managed stores after durable successful run completion.

    Historical single-file checkpoints are never discovered or modified.
    """
    root = Path(run_directory).resolve()
    stores = []
    for path in sorted(root.rglob("retention.json")):
        if path.parent.name != "checkpoints":
            continue
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (not isinstance(metadata, dict)
                or metadata.get("policy") != _POLICY_NAME
                or metadata.get("format_version") != _POLICY_VERSION):
            continue
        stores.append(CheckpointStore(path.parent, run_directory=root))
    if not stores:
        return {"status": "NO_MANAGED_CHECKPOINTS", "finalized_streams": 0}
    if not _successful_completion_record(root):
        raise CheckpointFinalizationError(
            "runtime checkpoints are retained until a durable COMPLETED marker exists"
        )

    finalized = []
    for store in stores:
        result = store.finalize()
        finalized.append({
            "directory": store.directory.relative_to(root).as_posix(),
            "final": result.path.relative_to(root).as_posix(),
            "removed_runtime_files": result.removed_runtime_files,
            "checkpoint_write_count": result.write_count,
            "retained_full_checkpoint_count": 1 + len(
                list(store.pinned_directory.glob("*.json"))
                if store.pinned_directory.is_dir() else []
            ),
        })

    policy_path = root / "metadata" / "recovery_policy.json"
    policy = {}
    if policy_path.is_file():
        try:
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            policy = {}
    policy.update({
        "policy_version": _POLICY_VERSION,
        "checkpoint_policy": _POLICY_NAME,
        "checkpoint_retention_count": 2,
        "checkpoint_rotation_enabled": True,
        "final_checkpoint_present": any(store.final_path.is_file() for store in stores),
        "checkpoint_write_count": sum(item["checkpoint_write_count"] for item in finalized),
        "retained_full_checkpoint_count": sum(
            item["retained_full_checkpoint_count"] for item in finalized
        ),
        "pinned_checkpoint_count": sum(
            len(list(store.pinned_directory.glob("*.json")))
            for store in stores if store.pinned_directory.is_dir()
        ),
        "history_artifacts": _history_artifacts(root),
        "status": "FINALIZED",
        "finalized_at_utc": _utc_now(),
        "streams": finalized,
    })
    _atomic_write_json(policy_path, policy)
    completion_path = root / "metadata" / "run_completion.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    final_paths = [item["final"] for item in finalized]
    completion["final_checkpoints"] = final_paths
    if len(final_paths) == 1:
        completion["final_checkpoint"] = final_paths[0]
    _atomic_write_json(completion_path, completion)
    return {"status": "FINALIZED", "finalized_streams": len(finalized), "streams": finalized}


def complete_study_run(
    run_directory: str | Path,
    outcome: Any = None,
    *,
    disposition: RunDisposition | None = None,
) -> dict[str, Any]:
    """Persist an explicit lifecycle disposition and finalize completed runs.

    Managed checkpoints are finalized only with an explicit COMPLETED
    disposition. Missing or ambiguous disposition is UNKNOWN and keeps runtime
    recovery generations intact.
    """
    root = Path(run_directory).resolve()
    if disposition is None or not isinstance(disposition, RunDisposition):
        resolved = RunDisposition.UNKNOWN
    else:
        resolved = disposition
    record = {
        "status": resolved.value,
        "disposition": resolved.value,
        "source": "explicit_run_disposition",
        "outcome_status": (
            str(outcome.get("status")) if isinstance(outcome, Mapping)
            and outcome.get("status") is not None else None
        ),
        "recorded_at_utc": _utc_now(),
    }
    if resolved is RunDisposition.COMPLETED:
        record["completed_at_utc"] = _utc_now()
    _atomic_write_json(root / "metadata" / "run_completion.json", record)
    if resolved is not RunDisposition.COMPLETED:
        return {"status": resolved.value, "finalized_streams": 0}
    return finalize_run_checkpoints(root)


def finalize_direct_run(run_directory: str | Path) -> dict[str, Any]:
    """Compatibility convenience for test fixtures with an explicit success."""
    return complete_study_run(
        run_directory, {"status": "COMPLETED"},
        disposition=RunDisposition.COMPLETED,
    )


__all__ = [
    "CheckpointFinalizationError", "CheckpointLoadError", "CheckpointStore",
    "FinalizedCheckpoint", "LoadedCheckpoint", "RunDisposition", "finalize_direct_run",
    "complete_study_run", "finalize_run_checkpoints",
]
