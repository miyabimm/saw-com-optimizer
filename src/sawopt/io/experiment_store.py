"""Fail-closed, future-only external experiment run storage.

This module is deliberately separate from historical run-directory and
orchestration schemas. It initializes only new runs and never reads, migrates,
or repairs historical raw data.
"""
from __future__ import annotations

import csv
import ctypes
import errno
import fcntl
import hashlib
import importlib.metadata
import io
import json
import os
import platform
import re
import secrets
import shutil
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

from .checkpoints import CheckpointStore


EXPERIMENT_SCHEMA_VERSION = 1
EXPERIMENT_SCHEMA_ID = "sawopt.raw_run/1"
EXPERIMENT_ID_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
RUN_ID_RE = re.compile(r"(\d{8}T\d{6}Z)-([0-9a-f]{8})\Z")
CELL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
CHECKPOINT_STREAM_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")

CELL_STATUSES = {"NOT_STARTED", "RUNNING", "COMPLETED", "FAILED", "INCOMPLETE", "NOT_RUN"}
TERMINAL_CELL_STATUSES = {"COMPLETED", "FAILED", "INCOMPLETE", "NOT_RUN"}
FAILURE_CLASSES = {"VALIDATION", "IO", "INFRASTRUCTURE", "MODEL", "BUDGET", "CANCELLED", "UNKNOWN"}
REVIEW_CONTEXT_FIELDS = {
    "purpose", "conditions", "findings", "limitations", "review_instructions",
    "scientific_disposition", "requires_comparison", "requires_validation",
}
_REQUIRED_SCIENTIFIC_INPUTS = {"model", "search_grid", "validation_grid"}
_RENAME_NOREPLACE = 1
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CONVERGENCE_COLUMNS = (
    "cell_id", "phase", "search_fes", "validation_points", "metric_name",
    "metric_value", "metric_status", "unit", "observed_at_utc",
)
_CONVERGENCE_HEADER = b"cell_id,phase,search_fes,validation_points,metric_name,metric_value,metric_status,unit,observed_at_utc\n"


class RunValidationError(ValueError):
    """Run request or external-storage preflight failed closed."""


class RunStorageError(OSError):
    """Raw-run initialization or persistence failed with a classified IO error."""


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RunValidationError(f"value is not finite canonical JSON data: {exc}") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _yaml_bytes(value: Any) -> bytes:
    _canonical_json(value)
    try:
        text = yaml.safe_dump(value, sort_keys=True, allow_unicode=True, default_flow_style=False)
    except (yaml.YAMLError, TypeError, ValueError) as exc:
        raise RunValidationError(f"value cannot be serialized as safe YAML: {exc}") from exc
    return text.encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_run_id(value: str) -> str:
    if not isinstance(value, str):
        raise RunValidationError("run_id must be a UTC timestamp plus eight lowercase hex characters")
    match = RUN_ID_RE.fullmatch(value)
    if match is None:
        raise RunValidationError("run_id must match YYYYMMDDTHHMMSSZ-<8 lowercase hex characters>")
    try:
        datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ")
    except ValueError as exc:
        raise RunValidationError("run_id contains an invalid UTC timestamp") from exc
    return value


def _validate_experiment_id(value: str) -> str:
    if not isinstance(value, str) or EXPERIMENT_ID_RE.fullmatch(value) is None:
        raise RunValidationError("experiment_id must be a lowercase hyphenated slug")
    return value


def _validate_source_sha(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value) is None:
        raise RunValidationError("execution source SHA must be an explicit full lowercase Git SHA")
    return value


def _path_is_below(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _raw_path_parts(value: str | os.PathLike[str]) -> tuple[Path, str]:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or raw != raw.strip():
        raise RunValidationError("SAWOPT_DATA_ROOT must be a non-empty absolute path without surrounding whitespace")
    candidate = Path(raw)
    if not candidate.is_absolute():
        raise RunValidationError("SAWOPT_DATA_ROOT must be absolute")
    if ".." in candidate.parts:
        raise RunValidationError("SAWOPT_DATA_ROOT must not contain parent traversal")
    return candidate, raw


def _assert_no_symlink_components(path: Path, *, allow_missing_leaf: bool) -> None:
    """Reject symlinks/reparse points in every existing path component."""
    if not _O_NOFOLLOW or not _O_DIRECTORY:
        raise RunValidationError("safe directory-fd path operations are unavailable on this platform")
    components = list(reversed(path.parents)) + [path]
    for index, component in enumerate(components):
        try:
            info = component.lstat()
        except FileNotFoundError:
            if allow_missing_leaf and index == len(components) - 1:
                continue
            raise RunValidationError(f"data-root parent does not exist: {component}")
        except OSError as exc:
            raise RunStorageError(f"cannot inspect data-root path component {component}: {exc}") from exc
        if component.is_symlink() or (getattr(info, "st_file_attributes", 0) & 0x400):
            raise RunValidationError(f"data-root contains a symlink or reparse component: {component}")
        if index < len(components) - 1 and not component.is_dir():
            raise RunValidationError(f"data-root parent is not a directory: {component}")
    if path.exists() and not path.is_dir():
        raise RunValidationError("SAWOPT_DATA_ROOT exists but is not a directory")
    if not path.parent.is_dir():
        raise RunValidationError("SAWOPT_DATA_ROOT parent must already exist as a directory")


def _discover_worktree_roots(repository_root: Path) -> tuple[Path, ...]:
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain", "-z"],
            cwd=repository_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise RunValidationError(f"cannot discover Git worktrees: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RunValidationError(f"Git worktree discovery failed: {detail}")
    try:
        tokens = result.stdout.decode("utf-8", errors="strict").split("\0")
    except UnicodeError as exc:
        raise RunValidationError("Git worktree inventory is not valid UTF-8") from exc
    roots = [Path(token[len("worktree "):]) for token in tokens if token.startswith("worktree ")]
    if not roots:
        raise RunValidationError("Git returned no registered worktrees")
    roots.append(repository_root)
    try:
        return tuple(sorted({path.resolve(strict=True) for path in roots}, key=lambda path: str(path)))
    except (OSError, RuntimeError, ValueError) as exc:
        raise RunValidationError(f"registered worktree identity cannot be resolved: {exc}") from exc


def _probe_writable(directory: Path) -> None:
    directory_fd = _open_directory_chain(directory)
    descriptor = None
    probe_name = None
    owned_identity = None
    failure = None
    cleanup_failure = None
    try:
        for _attempt in range(16):
            candidate = f".sawopt-write-probe-{secrets.token_hex(8)}"
            try:
                descriptor = os.open(
                    candidate,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
            except FileExistsError:
                # Never remove an entry this probe failed to create.
                continue
            probe_name = candidate
            owned_identity = os.fstat(descriptor)
            os.fsync(descriptor)
            break
        if descriptor is None:
            raise RunStorageError("could not reserve a unique temporary storage probe after 16 collisions")
    except OSError as exc:
        failure = exc
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                cleanup_failure = RunStorageError(f"could not close the temporary storage probe: {exc}")
            if probe_name is not None and owned_identity is not None:
                try:
                    current = os.stat(probe_name, dir_fd=directory_fd, follow_symlinks=False)
                    if (stat.S_ISREG(current.st_mode)
                            and current.st_dev == owned_identity.st_dev
                            and current.st_ino == owned_identity.st_ino):
                        os.unlink(probe_name, dir_fd=directory_fd)
                        os.fsync(directory_fd)
                    else:
                        cleanup_failure = RunStorageError(
                            "temporary storage probe identity changed; unrelated entry left untouched"
                        )
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    cleanup_failure = RunStorageError(f"could not remove the owned temporary storage probe: {exc}")
        try:
            os.close(directory_fd)
        except OSError as exc:
            cleanup_failure = RunStorageError(f"could not close the temporary storage directory: {exc}")
    if failure is not None:
        raise RunStorageError(f"external data location is not writable: {failure}") from failure
    if cleanup_failure is not None:
        raise cleanup_failure


def validate_data_root(
    data_root: str | os.PathLike[str] | None = None,
    *,
    required_free_bytes: int = 0,
    read_only: bool = False,
) -> Path:
    """Validate an external raw-data root without creating it.

    Production callers omit ``data_root`` and must set ``SAWOPT_DATA_ROOT``.
    Worktree/repository identities always come from this package's Git worktree
    inventory; callers cannot override or weaken that trust boundary.
    """
    if data_root is None:
        if "SAWOPT_DATA_ROOT" not in os.environ:
            raise RunValidationError("SAWOPT_DATA_ROOT is required; there is no repository-local fallback")
        data_root = os.environ["SAWOPT_DATA_ROOT"]
    candidate, _raw = _raw_path_parts(data_root)
    if isinstance(required_free_bytes, bool) or not isinstance(required_free_bytes, int) or required_free_bytes < 0:
        raise RunValidationError("required_free_bytes must be a non-negative integer")
    if not isinstance(read_only, bool):
        raise RunValidationError("read_only must be a boolean")
    try:
        repo = Path(__file__).resolve().parents[3].resolve(strict=True)
        if not repo.is_dir():
            raise RunValidationError("package repository root must resolve to a directory")
    except (OSError, RuntimeError, ValueError) as exc:
        if isinstance(exc, RunValidationError):
            raise
        raise RunValidationError(f"package repository root cannot be trusted: {exc}") from exc

    _assert_no_symlink_components(candidate, allow_missing_leaf=True)
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RunValidationError(f"SAWOPT_DATA_ROOT cannot be resolved safely: {exc}") from exc
    if resolved != candidate.absolute():
        # Even an alias that resolves outside a worktree is not a stable data identity.
        raise RunValidationError("SAWOPT_DATA_ROOT has an unresolved or aliased path identity")

    roots = _discover_worktree_roots(repo)
    for worktree in roots:
        if _path_is_below(resolved, worktree):
            raise RunValidationError(f"SAWOPT_DATA_ROOT is inside a Git worktree or repository: {worktree}")

    probe_dir = resolved if resolved.exists() else resolved.parent
    for parent in (probe_dir, *probe_dir.parents):
        if (parent / ".git").exists():
            raise RunValidationError(f"SAWOPT_DATA_ROOT is inside another Git repository: {parent}")
    if not probe_dir.is_dir():
        raise RunValidationError("SAWOPT_DATA_ROOT parent must already exist as a directory")
    try:
        free_bytes = shutil.disk_usage(probe_dir).free
    except OSError as exc:
        raise RunStorageError(f"cannot inspect free space for external data root: {exc}") from exc
    if free_bytes <= 0 or free_bytes < required_free_bytes:
        raise RunValidationError(
            f"external data root has {free_bytes} free bytes; {required_free_bytes} are required"
        )
    if not read_only:
        _probe_writable(probe_dir)
    return resolved


def _open_directory_chain(path: Path, *, create_leaf: bool = False) -> int:
    """Open an absolute directory chain with O_NOFOLLOW, optionally making its leaf."""
    if not _O_NOFOLLOW or not _O_DIRECTORY:
        raise RunValidationError("safe directory-fd path operations are unavailable on this platform")
    if not path.is_absolute() or ".." in path.parts:
        raise RunValidationError("internal storage path is not canonical and absolute")
    descriptor = os.open(path.anchor, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
    try:
        parts = path.parts[1:]
        for index, part in enumerate(parts):
            try:
                child = os.open(part, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=descriptor)
            except FileNotFoundError:
                if not create_leaf or index != len(parts) - 1:
                    raise
                os.mkdir(part, 0o700, dir_fd=descriptor)
                os.fsync(descriptor)
                child = os.open(part, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _mkdir_at(parent_fd: int, name: str) -> tuple[int, bool]:
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        created = True
        os.fsync(parent_fd)
    except FileExistsError:
        created = False
    except OSError as exc:
        raise RunStorageError(f"cannot create raw storage directory {name!r}: {exc}") from exc
    try:
        descriptor = os.open(name, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as exc:
        raise RunValidationError(f"raw storage path is not a trusted directory: {name!r}: {exc}") from exc
    return descriptor, created


def _write_new_file_at(directory_fd: int, name: str, data: bytes) -> None:
    descriptor = None
    try:
        descriptor = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    except OSError as exc:
        raise RunStorageError(f"cannot initialize raw artifact {name!r}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_file_at(directory_fd: int, name: str) -> bytes:
    descriptor = None
    try:
        descriptor = os.open(
            name, os.O_RDONLY | _O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory_fd,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RunValidationError(f"raw artifact is not a regular file: {name}")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise RunStorageError(f"cannot read raw artifact {name!r}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_file_path(path: Path) -> bytes:
    parent_fd = _open_directory_chain(Path(path).parent)
    try:
        return _read_file_at(parent_fd, Path(path).name)
    finally:
        os.close(parent_fd)


def _write_temp_at(directory_fd: int, data: bytes, *, prefix: str) -> str:
    name = f".{prefix}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    _write_new_file_at(directory_fd, name, data)
    return name


def _replace_regular_file_at(directory_fd: int, name: str, data: bytes, *, prefix: str) -> None:
    try:
        info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError as exc:
        raise RunStorageError(f"cannot inspect existing raw artifact {name!r}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise RunValidationError(f"raw artifact is not a regular file: {name}")
    temporary = _write_temp_at(directory_fd, data, prefix=prefix)
    try:
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _convergence_csv_bytes(observations: Sequence[Mapping[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_CONVERGENCE_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for item in observations:
        writer.writerow({column: item.get(column, "") for column in _CONVERGENCE_COLUMNS})
    return output.getvalue().encode("utf-8")


def _validate_checkpoint_observations(manifest: Mapping[str, Any]) -> None:
    cells = {cell["cell_id"]: cell for cell in manifest["cells"]}
    seen = set()
    for item in manifest["observed_checkpoints"]:
        cell = cells.get(item.get("cell_id")) if isinstance(item, Mapping) else None
        if cell is None or cell.get("executed") is not True:
            raise RunValidationError("checkpoint observation is not tied to an executed expected cell")
        phase = item.get("phase")
        search_fes = item.get("search_fes")
        validation_points = item.get("validation_points")
        if phase not in {"SEARCH", "VALIDATION"}:
            raise RunValidationError("checkpoint observation phase is invalid")
        if (isinstance(search_fes, bool) or not isinstance(search_fes, int) or search_fes < 0
                or search_fes > manifest["search_fe_limit_per_cell"]):
            raise RunValidationError("checkpoint observation search FE is outside its limit")
        if (isinstance(validation_points, bool) or not isinstance(validation_points, int)
                or validation_points < 0 or validation_points > manifest["validation_point_limit_per_cell"]):
            raise RunValidationError("checkpoint observation validation count is outside its limit")
        if phase == "SEARCH" and validation_points != 0:
            raise RunValidationError("search checkpoint cannot claim validation points")
        if phase == "VALIDATION" and validation_points == 0:
            raise RunValidationError("validation checkpoint requires validation points")
        if (not isinstance(item.get("metric_name"), str) or not item["metric_name"].strip()
                or not isinstance(item.get("unit"), str) or not item["unit"].strip()):
            raise RunValidationError("checkpoint observation lacks metric name or unit")
        value = item.get("metric_value")
        if value is None:
            if (item.get("metric_status") != "NOT_AVAILABLE"
                    or not isinstance(item.get("unavailable_reason"), str)
                    or not item["unavailable_reason"].strip()):
                raise RunValidationError("unavailable checkpoint metric lacks status/reason")
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RunValidationError("checkpoint metric is not a numeric value or explicit null")
            _canonical_json(value)
            if item.get("metric_status") != "OBSERVED":
                raise RunValidationError("numeric checkpoint metric lacks OBSERVED status")
        try:
            timestamp = datetime.fromisoformat(str(item.get("observed_at_utc", "")).replace("Z", "+00:00"))
        except ValueError as exc:
            raise RunValidationError("checkpoint observation timestamp is invalid") from exc
        if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
            raise RunValidationError("checkpoint observation timestamp is not UTC")
        if search_fes > cell["search_fes"] or validation_points > cell["validation_points"]:
            raise RunValidationError("checkpoint observation counters exceed their cell's recorded work")
        key = (item["cell_id"], phase, search_fes, validation_points)
        if key in seen:
            raise RunValidationError("duplicate observed checkpoint record")
        seen.add(key)


def _rename_noreplace_at(directory_fd: int, source: str, destination: str) -> None:
    """Publish one file/directory atomically without replacing any destination."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = libc.renameat2
    except (OSError, AttributeError) as exc:
        raise RunStorageError("atomic no-replace rename is unavailable; refusing non-atomic publication") from exc
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        directory_fd, os.fsencode(source), directory_fd, os.fsencode(destination), _RENAME_NOREPLACE,
    )
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError(destination)
        raise RunStorageError(f"atomic no-replace publication failed for {destination!r}: {os.strerror(error)}")
    os.fsync(directory_fd)


def _remove_tree_at(parent_fd: int, name: str) -> None:
    """Remove only the caller-owned staging tree, never following links."""
    try:
        directory_fd = os.open(name, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=parent_fd)
    except FileNotFoundError:
        return
    try:
        for child_name in os.listdir(directory_fd):
            info = os.stat(child_name, dir_fd=directory_fd, follow_symlinks=False)
            if info.st_mode & 0o170000 == 0o040000:
                _remove_tree_at(directory_fd, child_name)
            else:
                os.unlink(child_name, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
    os.rmdir(name, dir_fd=parent_fd)
    os.fsync(parent_fd)


def _runtime_identity() -> dict[str, Any]:
    packages = {}
    for package in ("sawopt", "numpy", "scipy", "matplotlib", "PyYAML"):
        packages[package] = importlib.metadata.version(package)
    dispatch_text = ""
    dispatch_status = "UNAVAILABLE"
    try:
        from contextlib import redirect_stdout
        from io import StringIO

        output = StringIO()
        show_runtime = getattr(np, "show_runtime", None)
        if callable(show_runtime):
            with redirect_stdout(output):
                show_runtime()
            dispatch_text = output.getvalue().strip()
            if dispatch_text:
                dispatch_status = "CAPTURED"
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        dispatch_text = f"capture_failed:{type(exc).__name__}"
    return {
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "packages": packages,
        "dispatch_identity": {"status": dispatch_status, "report": dispatch_text},
        "dispatch_overrides": {
            name: os.environ[name]
            for name in ("OPENBLAS_CORETYPE", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
            if name in os.environ
        },
    }


def _validate_review_context(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RunValidationError("review_context must be a mapping")
    if set(value) != REVIEW_CONTEXT_FIELDS:
        missing = sorted(REVIEW_CONTEXT_FIELDS - set(value))
        extra = sorted(set(value) - REVIEW_CONTEXT_FIELDS)
        raise RunValidationError(f"review_context fields mismatch; missing={missing}, extra={extra}")
    for key in REVIEW_CONTEXT_FIELDS - {"requires_comparison", "requires_validation"}:
        if not isinstance(value[key], str) or not value[key].strip():
            raise RunValidationError(f"review_context.{key} must be non-empty text")
    for key in ("requires_comparison", "requires_validation"):
        if not isinstance(value[key], bool):
            raise RunValidationError(f"review_context.{key} must be a boolean")
    if value["scientific_disposition"] != "CLAIM_PENDING_REVIEW":
        raise RunValidationError("scientific_disposition must remain CLAIM_PENDING_REVIEW")
    normalized = dict(value)
    _canonical_json(normalized)
    return normalized


def _validate_expected_cells(cells: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(cells, Sequence) or isinstance(cells, (str, bytes)) or not cells:
        raise RunValidationError("expected_cells must be a non-empty exact roster")
    result = []
    seen = set()
    for raw in cells:
        if not isinstance(raw, Mapping):
            raise RunValidationError("each expected cell must be a mapping")
        cell = dict(raw)
        cell_id = cell.get("cell_id")
        if not isinstance(cell_id, str) or CELL_ID_RE.fullmatch(cell_id) is None:
            raise RunValidationError("each expected cell requires a safe unique cell_id")
        if cell_id in seen:
            raise RunValidationError(f"duplicate expected cell id: {cell_id}")
        seen.add(cell_id)
        for key in ("topology", "method"):
            if not isinstance(cell.get(key), str) or not cell[key].strip():
                raise RunValidationError(f"each expected cell requires a non-empty {key}")
        if ("seed" not in cell or isinstance(cell["seed"], bool)
                or not isinstance(cell["seed"], (str, int))
                or (isinstance(cell["seed"], str) and not cell["seed"].strip())):
            raise RunValidationError("each expected cell requires a non-empty integer or string seed")
        for reserved in ("status", "executed", "search_fes", "validation_points", "result", "reason", "failure_class"):
            if reserved in cell:
                raise RunValidationError(f"expected cell identity may not define runtime field {reserved}")
        _canonical_json(cell)
        result.append({
            **cell, "status": "NOT_STARTED", "executed": False,
            "search_fes": 0, "validation_points": 0, "result": None,
        })
    return result


def _validate_artifact_relative(path: str) -> tuple[str, ...]:
    if not isinstance(path, str) or not path.startswith("artifacts/") or "\\" in path:
        raise RunValidationError("raw artifact path must be repository-independent under artifacts/")
    parts = Path(path).parts
    if len(parts) < 2 or any(part in ("", ".", "..") for part in parts):
        raise RunValidationError("raw artifact path contains traversal or an empty component")
    if parts[0] != "artifacts" or parts[-1].startswith("."):
        raise RunValidationError("raw artifact path is not allowed")
    if path not in {"artifacts/comparison.csv", "artifacts/validation.csv"}:
        if not (len(parts) == 3 and parts[1] == "plots" and parts[2].lower().endswith((".png", ".svg"))):
            raise RunValidationError("only comparison.csv, validation.csv, and compact plots may be registered")
    return tuple(parts)


def _artifact_digest(path: Path) -> dict[str, Any]:
    parent_fd = _open_directory_chain(Path(path).parent)
    descriptor = None
    try:
        descriptor = os.open(
            Path(path).name,
            os.O_RDONLY | _O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
            dir_fd=parent_fd,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RunValidationError(f"artifact is not a regular file: {path}")
        digest = hashlib.sha256()
        byte_count = 0
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
            byte_count += len(block)
        return {"sha256": digest.hexdigest(), "bytes": byte_count}
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_fd)


def _validate_raw_relative(path: str, *, cell_ids: set[str]) -> tuple[str, ...]:
    if not isinstance(path, str) or "\\" in path:
        raise RunValidationError("raw artifact path must use safe relative POSIX components")
    parts = Path(path).parts
    if len(parts) < 2:
        raise RunValidationError("raw artifact must be under cells/, logs/, arrays/, populations/, caches/, replay/, or artifacts/")
    if any(part in ("", ".", "..") or part.startswith(".") for part in parts):
        raise RunValidationError("raw artifact path contains traversal, hidden, or empty components")
    roots = {"cells", "logs", "arrays", "populations", "caches", "replay", "artifacts"}
    if parts[0] not in roots:
        raise RunValidationError("raw artifact must be under cells/, logs/, arrays/, populations/, caches/, replay/, or artifacts/")
    if any(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", part) is None for part in parts):
        raise RunValidationError("raw artifact path contains an unsafe component")
    if parts[0] == "cells" and parts[1] not in cell_ids:
        raise RunValidationError("raw artifact cell directory is not in the expected roster")
    if parts[0] == "artifacts":
        _validate_artifact_relative(path)
    return tuple(parts)


def _read_manifest_path(path: Path) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.is_absolute():
        raise RunValidationError("run path must be absolute")
    _assert_no_symlink_components(resolved, allow_missing_leaf=False)
    directory_fd = _open_directory_chain(resolved)
    try:
        raw = _read_file_at(directory_fd, "manifest.json")
    finally:
        os.close(directory_fd)
    try:
        manifest = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RunStorageError(f"raw run manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RunStorageError("raw run manifest must be a JSON object")
    if manifest.get("schema_id") != EXPERIMENT_SCHEMA_ID or manifest.get("schema_version") != EXPERIMENT_SCHEMA_VERSION:
        raise RunValidationError("unsupported future raw-run schema; legacy manifests are not migrated")
    try:
        _verify_frozen_provenance(manifest)
    except RunValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise RunValidationError(f"raw run manifest is missing frozen identity fields: {exc}") from exc
    return manifest


def _frozen_provenance_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    context = manifest["review_context"]
    return {
        "schema_id": manifest["schema_id"],
        "schema_version": manifest["schema_version"],
        "experiment_id": manifest["experiment_id"],
        "run_id": manifest["run_id"],
        "execution_source_sha": manifest["execution_source_sha"],
        "scientific_config_sha256": manifest["scientific_config_sha256"],
        "config_file_sha256": manifest["config_file_sha256"],
        "scientific_input_sha256": manifest["scientific_input_sha256"],
        "runtime": manifest["runtime"],
        "method": manifest["method"],
        "topology": manifest["topology"],
        "seeds": manifest["seeds"],
        "search_fe_limit_per_cell": manifest["search_fe_limit_per_cell"],
        "validation_point_limit_per_cell": manifest["validation_point_limit_per_cell"],
        "expected_cells": manifest["expected_cells"],
        "review_contract": {
            "purpose": context["purpose"],
            "conditions": context["conditions"],
            "requires_comparison": context["requires_comparison"],
            "requires_validation": context["requires_validation"],
        },
    }


def _verify_frozen_provenance(manifest: Mapping[str, Any]) -> None:
    expected = manifest.get("frozen_provenance_sha256")
    actual = _sha256(_canonical_json(_frozen_provenance_payload(manifest)))
    if not isinstance(expected, str) or expected != actual:
        raise RunValidationError("frozen provenance identity/hash mismatch")


class _RunBoundCheckpointStore(CheckpointStore):
    """Existing checkpoint contract guarded by the owning raw-run lifecycle."""

    def __init__(self, run: "ExperimentRun", name: str):
        super().__init__(run.path / "checkpoints" / name, run_directory=run.path)
        self._run = run

    @contextmanager
    def _write_guard(self):
        with self._run._locked_manifest() as (_fd, manifest):
            if manifest["status"] in {"COMPLETED", "FAILED", "INCOMPLETE"}:
                raise RunValidationError("closed raw runs cannot mutate checkpoint state")
            yield

    def write(self, writer, *, validator=None):
        with self._write_guard():
            return super().write(writer, validator=validator)

    def pin(self, label: str, *, source: str = "latest"):
        with self._write_guard():
            return super().pin(label, source=source)

    def finalize(self, *, validator=None):
        with self._write_guard():
            return super().finalize(validator=validator)


class ExperimentRun:
    """Handle to a single new external raw run."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path).resolve(strict=True)
        self._manifest = _read_manifest_path(self.path)

    @property
    def experiment_id(self) -> str:
        return self._manifest["experiment_id"]

    @property
    def run_id(self) -> str:
        return self._manifest["run_id"]

    @property
    def manifest(self) -> dict[str, Any]:
        return _read_manifest_path(self.path)

    @contextmanager
    def _locked_manifest(self):
        _assert_no_symlink_components(self.path, allow_missing_leaf=False)
        directory_fd = _open_directory_chain(self.path)
        lock_fd = None
        try:
            lock_fd = os.open(
                ".manifest.lock", os.O_CREAT | os.O_RDWR | _O_NOFOLLOW, 0o600,
                dir_fd=directory_fd,
            )
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            current = json.loads(_read_file_at(directory_fd, "manifest.json"))
            _verify_frozen_provenance(current)
            yield directory_fd, current
            payload = (json.dumps(
                current, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False,
            ) + "\n").encode("utf-8")
            temporary = _write_temp_at(directory_fd, payload, prefix="manifest")
            try:
                os.replace(
                    temporary, "manifest.json", src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
                os.fsync(directory_fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
        except (RunValidationError, RunStorageError, FileExistsError):
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise RunStorageError(f"atomic raw manifest update failed: {exc}") from exc
        finally:
            if lock_fd is not None:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            os.close(directory_fd)

    def record_cell(
        self,
        cell_id: str,
        *,
        status: str,
        executed: bool | None = None,
        search_fes: int | None = None,
        validation_points: int | None = None,
        reason: str | None = None,
        failure_class: str | None = None,
        result: Mapping[str, Any] | None = None,
        **details: Any,
    ) -> None:
        if status not in CELL_STATUSES or status == "NOT_STARTED":
            raise RunValidationError(f"unsupported cell status: {status}")
        if executed is not None and not isinstance(executed, bool):
            raise RunValidationError("cell executed must be an explicit boolean")
        if search_fes is not None and (isinstance(search_fes, bool) or not isinstance(search_fes, int) or search_fes < 0):
            raise RunValidationError("search_fes must be a non-negative integer")
        if validation_points is not None and (isinstance(validation_points, bool) or not isinstance(validation_points, int) or validation_points < 0):
            raise RunValidationError("validation_points must be a non-negative integer")
        if status in {"RUNNING", "COMPLETED"} and executed is not True:
            raise RunValidationError(f"a {status.lower()} cell requires an explicit executed=true record")
        if status == "NOT_RUN" and executed is True:
            raise RunValidationError("NOT_RUN cell cannot claim that execution occurred")
        if status in {"FAILED", "INCOMPLETE", "NOT_RUN"} and (not isinstance(reason, str) or not reason.strip()):
            raise RunValidationError(f"{status} cell requires an explicit reason")
        if status == "FAILED" and failure_class not in FAILURE_CLASSES:
            raise RunValidationError("FAILED cell requires a deterministic failure_class")
        if failure_class is not None and failure_class not in FAILURE_CLASSES:
            raise RunValidationError(f"unknown failure_class: {failure_class}")
        if result is not None and not isinstance(result, Mapping):
            raise RunValidationError("cell result must be a mapping or null")
        cell_payload = dict(details)
        if set(cell_payload) & {"cell_id", "topology", "method", "seed", "status", "executed", "search_fes", "validation_points", "reason", "failure_class"}:
            raise RunValidationError("cell outcome may not overwrite frozen identity or status fields")
        if result is not None:
            cell_payload["result"] = dict(result)
        _canonical_json(cell_payload)

        with self._locked_manifest() as (_fd, manifest):
            if manifest["status"] in TERMINAL_CELL_STATUSES or manifest["status"] in {"COMPLETED", "FAILED", "INCOMPLETE"}:
                raise RunValidationError("closed raw runs cannot accept cell commits")
            cell = next((item for item in manifest["cells"] if item["cell_id"] == cell_id), None)
            if cell is None:
                raise RunValidationError(f"cell is not in the frozen expected roster: {cell_id}")
            if cell["status"] in TERMINAL_CELL_STATUSES:
                raise RunValidationError(f"cell is already terminal/committed: {cell_id}")
            identity_fields = set(cell) - {"status", "executed", "search_fes", "validation_points", "result", "reason", "failure_class"}
            if set(cell_payload) & identity_fields:
                raise RunValidationError("cell outcome may not overwrite frozen expected-cell fields")
            if cell["status"] == "RUNNING" and status == "RUNNING":
                pass
            elif cell["status"] == "NOT_STARTED" and status in {"RUNNING", *TERMINAL_CELL_STATUSES}:
                pass
            elif cell["status"] == "RUNNING" and status in TERMINAL_CELL_STATUSES:
                pass
            else:
                raise RunValidationError(f"invalid cell status transition {cell['status']} -> {status}")
            search_count = cell["search_fes"] if search_fes is None else search_fes
            validation_count = cell["validation_points"] if validation_points is None else validation_points
            if search_count < cell["search_fes"] or validation_count < cell["validation_points"]:
                raise RunValidationError("cell search/validation counters may not move backwards")
            if status == "COMPLETED" and search_count <= 0:
                raise RunValidationError("a completed cell must record at least one observed unique search FE")
            if status == "NOT_RUN" and (search_count != 0 or validation_count != 0):
                raise RunValidationError("NOT_RUN cell cannot claim search or validation work")
            if search_count > manifest["search_fe_limit_per_cell"]:
                raise RunValidationError("cell search FEs exceed the frozen unique-FE limit")
            if validation_count > manifest["validation_point_limit_per_cell"]:
                raise RunValidationError("cell validation count exceeds the frozen validation-grid limit")
            cell.update({
                "status": status,
                "executed": cell["executed"] if executed is None else executed,
                "search_fes": search_count,
                "validation_points": validation_count,
            })
            if reason is not None:
                cell["reason"] = reason
            if failure_class is not None:
                cell["failure_class"] = failure_class
            cell.update(cell_payload)
            _canonical_json(cell)
            manifest["search_fe_count"] = sum(item["search_fes"] for item in manifest["cells"])
            manifest["validation_point_count"] = sum(item["validation_points"] for item in manifest["cells"])
            if status == "RUNNING":
                manifest["status"] = "RUNNING"
            manifest["cell_roster_sha256"] = _sha256(_canonical_json(manifest["cells"]))

    def record_checkpoint(
        self,
        cell_id: str,
        *,
        phase: str,
        search_fes: int,
        validation_points: int,
        metric_name: str,
        metric_value: float | None,
        unit: str,
        observed_at_utc: str,
        unavailable_reason: str | None = None,
    ) -> None:
        if phase not in {"SEARCH", "VALIDATION"}:
            raise RunValidationError("checkpoint phase must be SEARCH or VALIDATION")
        if isinstance(search_fes, bool) or not isinstance(search_fes, int) or search_fes < 0:
            raise RunValidationError("checkpoint search_fes must be a non-negative integer")
        if isinstance(validation_points, bool) or not isinstance(validation_points, int) or validation_points < 0:
            raise RunValidationError("checkpoint validation_points must be a non-negative integer")
        if not isinstance(metric_name, str) or not metric_name.strip() or not isinstance(unit, str) or not unit.strip():
            raise RunValidationError("checkpoint metric name and unit are required")
        try:
            timestamp = datetime.fromisoformat(observed_at_utc.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise RunValidationError("checkpoint observation time must be ISO-8601 with UTC offset") from exc
        if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
            raise RunValidationError("checkpoint observation time must be UTC")
        if metric_value is None:
            if not isinstance(unavailable_reason, str) or not unavailable_reason.strip():
                raise RunValidationError("a null checkpoint metric requires an explicit unavailable_reason")
            value_status = "NOT_AVAILABLE"
        elif isinstance(metric_value, bool) or not isinstance(metric_value, (int, float)):
            raise RunValidationError("checkpoint metric must be a finite number or explicit null")
        else:
            _canonical_json(metric_value)
            value_status = "OBSERVED"
        observation = {
            "cell_id": cell_id, "phase": phase, "search_fes": search_fes,
            "validation_points": validation_points, "metric_name": metric_name,
            "metric_value": metric_value, "metric_status": value_status,
            "unavailable_reason": unavailable_reason, "unit": unit,
            "observed_at_utc": observed_at_utc,
        }
        _canonical_json(observation)
        with self._locked_manifest() as (_fd, manifest):
            if manifest["status"] in {"COMPLETED", "FAILED", "INCOMPLETE"}:
                raise RunValidationError("closed raw runs cannot accept checkpoint observations")
            cell = next((item for item in manifest["cells"] if item["cell_id"] == cell_id), None)
            if cell is None:
                raise RunValidationError(f"checkpoint cell is not in the expected roster: {cell_id}")
            if cell.get("executed") is not True:
                raise RunValidationError("checkpoint observation requires an executed expected cell")
            if search_fes > manifest["search_fe_limit_per_cell"] or validation_points > manifest["validation_point_limit_per_cell"]:
                raise RunValidationError("checkpoint exceeds the frozen search or validation budget")
            if phase == "SEARCH" and validation_points != 0:
                raise RunValidationError("search checkpoint cannot claim validation points")
            if phase == "VALIDATION" and validation_points == 0:
                raise RunValidationError("validation checkpoint requires observed validation points")
            key = (cell_id, phase, search_fes, validation_points)
            if any((item["cell_id"], item["phase"], item["search_fes"], item["validation_points"]) == key
                   for item in manifest["observed_checkpoints"]):
                raise RunValidationError("duplicate observed checkpoint; observations are not overwritten")
            new_observations = [*manifest["observed_checkpoints"], observation]
            convergence = _convergence_csv_bytes(new_observations)
            _replace_regular_file_at(_fd, "convergence.csv", convergence, prefix="convergence")
            manifest["observed_checkpoints"] = new_observations
            manifest["raw_artifact_sha256"]["convergence.csv"] = {
                "sha256": _sha256(convergence), "bytes": len(convergence),
            }

    def record_error(self, *, classification: str, message: str, cell_id: str | None = None) -> None:
        if classification not in FAILURE_CLASSES or not isinstance(message, str) or not message:
            raise RunValidationError("run error requires a known classification and complete message")
        error = {"classification": classification, "message": message}
        if cell_id is not None:
            error["cell_id"] = cell_id
        _canonical_json(error)
        with self._locked_manifest() as (_fd, manifest):
            if manifest["status"] in {"COMPLETED", "FAILED", "INCOMPLETE"}:
                raise RunValidationError("closed raw runs cannot accept errors")
            if cell_id is not None and cell_id not in {cell["cell_id"] for cell in manifest["cells"]}:
                raise RunValidationError("run error cell_id is not in the expected roster")
            manifest["errors"].append(error)

    def update_review_context(self, **updates: Any) -> None:
        if set(updates) - {"findings", "limitations", "review_instructions", "scientific_disposition"}:
            raise RunValidationError("review context updates may change findings/limitations/instructions only")
        with self._locked_manifest() as (_fd, manifest):
            manifest["review_context"].update(updates)
            manifest["review_context"] = _validate_review_context(manifest["review_context"])
            _verify_frozen_provenance(manifest)

    def write_raw_artifact(self, relative_path: str, data: bytes | bytearray | memoryview) -> dict[str, Any]:
        """Atomically persist a new, hash-registered raw result without overwrite."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise RunValidationError("raw artifact content must be bytes")
        payload = bytes(data)
        with self._locked_manifest() as (run_fd, manifest):
            if manifest["status"] in {"COMPLETED", "FAILED", "INCOMPLETE"}:
                raise RunValidationError("closed raw runs cannot accept artifacts")
            cell_ids = {cell["cell_id"] for cell in manifest["expected_cells"]}
            parts = _validate_raw_relative(relative_path, cell_ids=cell_ids)
            relative = "/".join(parts)
            if relative in manifest["raw_artifact_sha256"]:
                raise FileExistsError(relative)
            parent_fd = os.dup(run_fd)
            try:
                for part in parts[:-1]:
                    child_fd, _created = _mkdir_at(parent_fd, part)
                    os.close(parent_fd)
                    parent_fd = child_fd
                temporary = _write_temp_at(parent_fd, payload, prefix="artifact")
                try:
                    _rename_noreplace_at(parent_fd, temporary, parts[-1])
                finally:
                    try:
                        os.unlink(temporary, dir_fd=parent_fd)
                    except FileNotFoundError:
                        pass
                manifest["raw_artifact_sha256"][relative] = {
                    "sha256": _sha256(payload), "bytes": len(payload),
                }
            finally:
                os.close(parent_fd)
        return {"sha256": _sha256(payload), "bytes": len(payload)}

    def write_artifact(self, relative_path: str, data: bytes | bytearray | memoryview) -> dict[str, Any]:
        """Persist an allowlisted compact review input in the raw run."""
        _validate_artifact_relative(relative_path)
        return self.write_raw_artifact(relative_path, data)

    def checkpoint_store(self, name: str = "default") -> CheckpointStore:
        if CHECKPOINT_STREAM_RE.fullmatch(name) is None:
            raise RunValidationError("checkpoint stream name must be a safe lowercase identifier")
        with self._locked_manifest() as (_fd, manifest):
            if manifest["status"] in {"COMPLETED", "FAILED", "INCOMPLETE"}:
                raise RunValidationError("closed raw runs cannot open a mutable checkpoint stream")
            streams = manifest["checkpoint_state"]["streams"]
            if name not in {item["name"] for item in streams}:
                streams.append({"name": name, "run_id": manifest["run_id"], "status": "REGISTERED", "files": {}})
            manifest["checkpoint_state"]["status"] = "ACTIVE"
        return _RunBoundCheckpointStore(self, name)

    def refresh_checkpoint_state(self) -> None:
        with self._locked_manifest() as (_fd, manifest):
            if manifest["status"] in {"COMPLETED", "FAILED", "INCOMPLETE"}:
                raise RunValidationError("closed raw runs cannot refresh checkpoint state")
            checkpoint_root = self.path / "checkpoints"
            if not checkpoint_root.exists() and not checkpoint_root.is_symlink():
                manifest["checkpoint_state"] = {"status": "NONE", "streams": [], "recovery_artifacts": {}}
                return
            if checkpoint_root.is_symlink() or not checkpoint_root.is_dir():
                raise RunValidationError("checkpoint root is not a trusted directory")
            streams = []
            for stream_path in sorted(checkpoint_root.iterdir(), key=lambda path: path.name):
                if (CHECKPOINT_STREAM_RE.fullmatch(stream_path.name) is None
                        or stream_path.is_symlink() or not stream_path.is_dir()):
                    raise RunValidationError("checkpoint directory contains an unsafe stream entry")
                retention = stream_path / "retention.json"
                if not retention.is_file() or retention.is_symlink():
                    raise RunValidationError(f"checkpoint stream {stream_path.name} has no safe retention metadata")
                try:
                    retention_bytes = _read_file_path(retention)
                    retention_value = json.loads(retention_bytes)
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise RunStorageError(f"checkpoint retention metadata cannot be read: {exc}") from exc
                if not isinstance(retention_value, dict) or retention_value.get("format_version") != 1:
                    raise RunValidationError("checkpoint retention schema is inconsistent")
                if retention_value.get("policy") != "rolling_latest_previous" or retention_value.get("state") not in {"ACTIVE", "FINALIZED"}:
                    raise RunValidationError("checkpoint policy or lifecycle state is inconsistent")
                if any(retention_value.get(key) != filename for key, filename in (("latest", "latest.json"), ("previous", "previous.json"), ("final", "final.json"))):
                    raise RunValidationError("checkpoint retention filenames do not match the active schema")
                files = {}
                for candidate in sorted(stream_path.rglob("*"), key=lambda path: path.as_posix()):
                    if candidate.is_symlink():
                        raise RunValidationError("checkpoint stream contains a symlink")
                    if candidate.is_file():
                        relative = candidate.relative_to(stream_path).as_posix()
                        files[relative] = _artifact_digest(candidate)
                    elif not candidate.is_dir():
                        raise RunValidationError("checkpoint stream contains a non-file artifact")
                streams.append({
                    "name": stream_path.name,
                    "run_id": manifest["run_id"],
                    "status": str(retention_value.get("state", "UNKNOWN")),
                    "policy": retention_value.get("policy"),
                    "files": files,
                })
            recovery_artifacts = {}
            metadata_dir = self.path / "metadata"
            if metadata_dir.exists() or metadata_dir.is_symlink():
                if metadata_dir.is_symlink() or not metadata_dir.is_dir():
                    raise RunValidationError("checkpoint recovery metadata directory is unsafe")
                for filename in ("recovery_policy.json", "run_completion.json"):
                    artifact = metadata_dir / filename
                    if artifact.exists() or artifact.is_symlink():
                        if artifact.is_symlink() or not artifact.is_file():
                            raise RunValidationError("checkpoint recovery metadata artifact is unsafe")
                        recovery_artifacts[filename] = _artifact_digest(artifact)
            policy_path = metadata_dir / "recovery_policy.json"
            if policy_path.is_file():
                policy = json.loads(_read_file_path(policy_path))
                final_present = any("final.json" in stream["files"] for stream in streams)
                pinned_count = sum(
                    relative.startswith("pinned/") and relative.endswith(".json")
                    for stream in streams for relative in stream["files"]
                )
                if (policy.get("checkpoint_retention_count") != 2
                        or policy.get("final_checkpoint_present") is not final_present
                        or policy.get("pinned_checkpoint_count") != pinned_count):
                    raise RunValidationError("checkpoint recovery policy disagrees with retained stream files")
            manifest["checkpoint_state"] = {
                "status": "ACTIVE" if streams else "NONE", "streams": streams,
                "recovery_artifacts": recovery_artifacts,
            }

    def close(
        self,
        *,
        status: str | None = None,
        errors: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        if self.manifest["status"] in {"COMPLETED", "FAILED", "INCOMPLETE"}:
            raise RunValidationError("run is already closed; double commit is not allowed")
        for error in errors:
            if not isinstance(error, Mapping):
                raise RunValidationError("run errors must be structured mappings")
            self.record_error(
                classification=str(error.get("classification", "")),
                message=str(error.get("message", "")),
                cell_id=error.get("cell_id"),
            )
        self.refresh_checkpoint_state()
        with self._locked_manifest() as (_fd, manifest):
            if manifest["status"] in {"COMPLETED", "FAILED", "INCOMPLETE"}:
                raise RunValidationError("run is already closed; double commit is not allowed")
            _validate_checkpoint_observations(manifest)
            statuses = [cell["status"] for cell in manifest["cells"]]
            if status is None:
                if any(item in {"NOT_STARTED", "RUNNING", "INCOMPLETE"} for item in statuses):
                    resolved_status = "INCOMPLETE"
                elif any(item in {"FAILED", "NOT_RUN"} for item in statuses) or manifest["errors"]:
                    resolved_status = "FAILED"
                else:
                    resolved_status = "COMPLETED"
            else:
                resolved_status = status
            if resolved_status not in {"COMPLETED", "FAILED", "INCOMPLETE"}:
                raise RunValidationError("run close status must be COMPLETED, FAILED, or INCOMPLETE")
            if resolved_status == "COMPLETED" and manifest["errors"]:
                raise RunValidationError("run cannot be successful while run-level errors are recorded")
            if resolved_status == "COMPLETED" and any(item != "COMPLETED" for item in statuses):
                raise RunValidationError("run cannot be successful unless every expected cell completed")
            if resolved_status == "FAILED" and not (any(item in {"FAILED", "NOT_RUN"} for item in statuses) or manifest["errors"]):
                raise RunValidationError("FAILED run requires a failed cell or recorded error")
            if resolved_status == "INCOMPLETE" and not any(item in {"NOT_STARTED", "RUNNING", "INCOMPLETE"} for item in statuses):
                raise RunValidationError("INCOMPLETE run requires an incomplete or not-started cell")
            manifest["status"] = resolved_status
            manifest["finished_at_utc"] = _utc_now()
        return self.manifest


def create_experiment_run(
    experiment_id: str,
    *,
    effective_config: Mapping[str, Any],
    scientific_inputs: Mapping[str, Any],
    expected_cells: Sequence[Mapping[str, Any]],
    source_sha: str,
    search_fe_limit: int,
    validation_point_limit: int,
    review_context: Mapping[str, Any],
    run_id: str | None = None,
    data_root: str | os.PathLike[str] | None = None,
    required_free_bytes: int,
    method: str | None = None,
    topology: str | None = None,
) -> ExperimentRun:
    """Exclusively initialize a new versioned raw run under the configured root."""
    experiment_id = _validate_experiment_id(experiment_id)
    source_sha = _validate_source_sha(source_sha)
    if isinstance(search_fe_limit, bool) or not isinstance(search_fe_limit, int) or search_fe_limit <= 0:
        raise RunValidationError("search_fe_limit must be a positive unique-FE ceiling")
    if isinstance(validation_point_limit, bool) or not isinstance(validation_point_limit, int) or validation_point_limit <= 0:
        raise RunValidationError("validation_point_limit must be a positive point ceiling")
    if isinstance(required_free_bytes, bool) or not isinstance(required_free_bytes, int) or required_free_bytes <= 0:
        raise RunValidationError("run initialization requires a positive declared required_free_bytes estimate")
    if not isinstance(effective_config, Mapping) or not isinstance(scientific_inputs, Mapping):
        raise RunValidationError("effective_config and scientific_inputs must be mappings")
    if set(scientific_inputs) != _REQUIRED_SCIENTIFIC_INPUTS:
        raise RunValidationError(f"scientific_inputs must contain exactly {sorted(_REQUIRED_SCIENTIFIC_INPUTS)}")
    _canonical_json(effective_config)
    for value in scientific_inputs.values():
        _canonical_json(value)
    cells = _validate_expected_cells(expected_cells)
    context = _validate_review_context(review_context)
    if method is not None and (not isinstance(method, str) or not method.strip()):
        raise RunValidationError("method must be non-empty text when specified")
    if topology is not None and (not isinstance(topology, str) or not topology.strip()):
        raise RunValidationError("topology must be non-empty text when specified")
    cell_methods = sorted({cell["method"] for cell in cells})
    cell_topologies = sorted({cell["topology"] for cell in cells})
    if method is not None and method not in cell_methods and not (method == "MULTIPLE" and len(cell_methods) > 1):
        raise RunValidationError("method summary must match the frozen expected-cell roster")
    if topology is not None and topology not in cell_topologies and not (topology == "MULTIPLE" and len(cell_topologies) > 1):
        raise RunValidationError("topology summary must match the frozen expected-cell roster")
    method = method or (cell_methods[0] if len(cell_methods) == 1 else "MULTIPLE")
    topology = topology or (cell_topologies[0] if len(cell_topologies) == 1 else "MULTIPLE")

    root = validate_data_root(data_root, required_free_bytes=required_free_bytes)
    if run_id is not None:
        run_id = _validate_run_id(run_id)
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{timestamp}-{secrets.token_hex(4)}"

    config_yaml = _yaml_bytes(dict(effective_config))
    scientific_sha = {
        name: _sha256(_canonical_json(value)) for name, value in scientific_inputs.items()
    }
    input_files = {
        f"inputs/{name}.yaml": _yaml_bytes(value)
        for name, value in scientific_inputs.items()
    }
    environment = _runtime_identity()
    config_identity_sha = _sha256(_canonical_json(effective_config))
    config_file_sha = _sha256(config_yaml)
    now = _utc_now()
    expected_cell_identities = [
        {key: value for key, value in cell.items() if key not in {"status", "executed", "search_fes", "validation_points", "result"}}
        for cell in cells
    ]
    manifest = {
        "schema_id": EXPERIMENT_SCHEMA_ID,
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "status": "INITIALIZED",
        "created_at_utc": now,
        "finished_at_utc": None,
        "execution_source_sha": source_sha,
        "scientific_config_sha256": config_identity_sha,
        "config_file_sha256": config_file_sha,
        "scientific_input_sha256": scientific_sha,
        "raw_artifact_sha256": {
            "config.yaml": {"sha256": config_file_sha, "bytes": len(config_yaml)},
            "convergence.csv": {"sha256": _sha256(_CONVERGENCE_HEADER), "bytes": len(_CONVERGENCE_HEADER)},
            **{name: {"sha256": _sha256(data), "bytes": len(data)} for name, data in input_files.items()},
        },
        "runtime": environment,
        "method": method,
        "topology": topology,
        "seeds": sorted({cell["seed"] for cell in cells}, key=lambda item: (type(item).__name__, str(item))),
        "search_fe_limit_per_cell": search_fe_limit,
        "validation_point_limit_per_cell": validation_point_limit,
        "search_fe_count": 0,
        "validation_point_count": 0,
        "expected_cells": expected_cell_identities,
        "cells": cells,
        "cell_roster_sha256": _sha256(_canonical_json(cells)),
        "observed_checkpoints": [],
        "checkpoint_state": {"status": "NONE", "streams": [], "recovery_artifacts": {}},
        "errors": [],
        "review_context": context,
    }
    manifest["frozen_provenance_sha256"] = _sha256(_canonical_json(_frozen_provenance_payload(manifest)))
    _canonical_json(manifest)

    root_fd = None
    runs_fd = experiment_fd = stage_fd = None
    stage_name = f".r5-{secrets.token_hex(12)}.tmp"
    stage_published = False
    try:
        root_fd = _open_directory_chain(root, create_leaf=not root.exists())
        runs_fd, _ = _mkdir_at(root_fd, "runs")
        experiment_fd, _ = _mkdir_at(runs_fd, experiment_id)
        # Staging-name collisions retry; a final run-ID collision fails closed without overwrite.
        while True:
            try:
                os.mkdir(stage_name, 0o700, dir_fd=experiment_fd)
                break
            except FileExistsError:
                stage_name = f".r5-{secrets.token_hex(12)}.tmp"
        stage_fd = os.open(stage_name, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=experiment_fd)
        os.mkdir("inputs", 0o700, dir_fd=stage_fd)
        inputs_fd = os.open("inputs", os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=stage_fd)
        try:
            for name, data in input_files.items():
                _write_new_file_at(inputs_fd, Path(name).name, data)
            os.fsync(inputs_fd)
        finally:
            os.close(inputs_fd)
        _write_new_file_at(stage_fd, "config.yaml", config_yaml)
        _write_new_file_at(stage_fd, "convergence.csv", _CONVERGENCE_HEADER)
        _write_new_file_at(stage_fd, "manifest.json", (json.dumps(
            manifest, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False,
        ) + "\n").encode("utf-8"))
        os.fsync(stage_fd)
        os.close(stage_fd)
        stage_fd = None
        _rename_noreplace_at(experiment_fd, stage_name, run_id)
        stage_published = True
    except FileExistsError:
        raise
    except (RunValidationError, RunStorageError):
        raise
    except OSError as exc:
        raise RunStorageError(f"raw run initialization failed: {exc}") from exc
    finally:
        if stage_fd is not None:
            os.close(stage_fd)
        if experiment_fd is not None and not stage_published:
            try:
                _remove_tree_at(experiment_fd, stage_name)
            except OSError as cleanup_error:
                raise RunStorageError(f"raw initialization failed and staging cleanup failed: {cleanup_error}") from cleanup_error
        for descriptor in (experiment_fd, runs_fd, root_fd):
            if descriptor is not None:
                os.close(descriptor)

    return ExperimentRun(root / "runs" / experiment_id / run_id)


def read_experiment_manifest(run_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read a supported new-schema manifest without interpreting legacy schemas."""
    return _read_manifest_path(Path(run_path))


__all__ = [
    "CELL_STATUSES", "EXPERIMENT_SCHEMA_ID", "EXPERIMENT_SCHEMA_VERSION",
    "ExperimentRun", "RunStorageError", "RunValidationError",
    "create_experiment_run", "read_experiment_manifest", "validate_data_root",
]
