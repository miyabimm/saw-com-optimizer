"""Read-only worktree inventory and fail-closed removal support."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import socket
import stat
import subprocess
import time
from typing import Any, Iterator

from .pid_utils import pid_exists


@dataclass(frozen=True)
class WorktreeIdentity:
    path: str
    head: str
    branch: str | None
    is_bare: bool = False


@dataclass(frozen=True)
class WorktreeAudit:
    path: str
    classification: str
    deletion_allowed: bool
    registered: bool
    primary_checkout: bool
    identity: WorktreeIdentity | None
    tracked_changes: tuple[str, ...] = ()
    untracked_files: tuple[str, ...] = ()
    ignored_files: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = ()
    reparse_points: tuple[str, ...] = ()
    file_count: int = 0
    total_bytes: int = 0
    filesystem_inventory_complete: bool = False
    inaccessible_paths: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorktreeRemoval:
    classification: str
    deletion_allowed: bool
    remove_invoked: bool
    path_exists_after: bool
    registered_after: bool | None
    detail: str = ""
    audit: WorktreeAudit | None = None


PROTECTED_COMPONENTS = {
    "runs", "checkpoint", "checkpoints", "logs", ".pytest-tmp", ".pytest_cache",
}
LOCK_STALE_AFTER_S = 300.0
LOCK_NAME = ".sawopt-worktree-safety.lock"


def git_common_dir(repository_root: str | Path) -> Path:
    root = Path(repository_root).resolve(strict=True)
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], cwd=root,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"cannot resolve Git common directory: {detail}")
    value = result.stdout.decode("utf-8", errors="strict").strip()
    common = Path(value)
    if not common.is_absolute():
        common = root / common
    return common.resolve(strict=True)


def _read_lock_metadata(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


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
    metadata = _read_lock_metadata(path)
    try:
        owner_pid = int(metadata.get("pid")) if metadata is not None else None
    except (TypeError, ValueError):
        owner_pid = None
    if _lock_age_s(path, metadata) < stale_after_s or pid_exists(owner_pid):
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
    quarantine.unlink(missing_ok=True)
    return True


@contextmanager
def _exclusive_lock(
    path: Path, *, timeout_s: float = 30.0,
    stale_after_s: float = LOCK_STALE_AFTER_S,
) -> Iterator[None]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    descriptor = None
    while time.monotonic() < deadline:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            metadata = {
                "pid": os.getpid(),
                "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "hostname": socket.gethostname(),
            }
            os.write(descriptor, json.dumps(metadata, ensure_ascii=True).encode("utf-8"))
            os.fsync(descriptor)
            break
        except FileExistsError:
            if not _reclaim_stale_lock(path, stale_after_s=stale_after_s):
                time.sleep(0.01)
        except BaseException:
            if descriptor is not None:
                os.close(descriptor)
                path.unlink(missing_ok=True)
                descriptor = None
            raise
    if descriptor is None:
        raise TimeoutError(f"timed out acquiring lock: {path}")
    try:
        yield
    finally:
        os.close(descriptor)
        path.unlink(missing_ok=True)


@contextmanager
def worktree_safety_lock(repository_root: str | Path) -> Iterator[Path]:
    """Serialize concurrent safety audits/removals for one Git repository."""
    common = git_common_dir(repository_root)
    with _exclusive_lock(common / LOCK_NAME):
        yield common


def _path_equal(left: str | Path, right: str | Path, *, windows: bool | None = None) -> bool:
    if windows is None:
        windows = os.name == "nt"
    if windows:
        a, b = PureWindowsPath(str(left)), PureWindowsPath(str(right))
        return tuple(part.casefold() for part in a.parts) == tuple(part.casefold() for part in b.parts)
    return os.path.normcase(os.path.abspath(os.fspath(left))) == os.path.normcase(os.path.abspath(os.fspath(right)))


def _git(cwd: Path, args: list[str]) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=cwd, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace") if isinstance(result.stderr, bytes) else str(result.stderr)
        raise RuntimeError(f"git {' '.join(args)} failed ({result.returncode}): {detail.strip()}")
    output = result.stdout
    return output if isinstance(output, bytes) else str(output).encode("utf-8")


def _worktree_identities(repository_root: Path) -> tuple[WorktreeIdentity, ...]:
    output = _git(repository_root, ["worktree", "list", "--porcelain", "-z"])
    text = output.decode("utf-8", errors="strict")
    records: list[WorktreeIdentity] = []
    fields: list[str] = []
    for token in text.split("\0"):
        if not token:
            if fields:
                first = fields[0]
                if not first.startswith("worktree "):
                    raise ValueError("malformed git worktree list record")
                root = first[len("worktree "):]
                head = next((x[len("HEAD "):] for x in fields if x.startswith("HEAD ")), "")
                branch = next((x[len("branch "):] for x in fields if x.startswith("branch ")), None)
                if not root or not head:
                    raise ValueError("git worktree identity is incomplete")
                records.append(WorktreeIdentity(
                    str(Path(root).resolve(strict=False)), head, branch, "bare" in fields,
                ))
                fields = []
            continue
        fields.append(token)
    if fields:
        first = fields[0]
        if not first.startswith("worktree "):
            raise ValueError("malformed final git worktree record")
        root = first[len("worktree "):]
        head = next((x[len("HEAD "):] for x in fields if x.startswith("HEAD ")), "")
        branch = next((x[len("branch "):] for x in fields if x.startswith("branch ")), None)
        if not root or not head:
            raise ValueError("git worktree identity is incomplete")
        records.append(WorktreeIdentity(
            str(Path(root).resolve(strict=False)), head, branch, "bare" in fields,
        ))
    if not records:
        raise ValueError("git worktree discovery returned no records")
    return tuple(records)


def _main_worktree_identity(identities: tuple[WorktreeIdentity, ...]) -> WorktreeIdentity:
    """Return Git's first, main-worktree record; reject bare/unknown identity.

    Git emits the main working tree first in `worktree list --porcelain`. This
    is independent of the checkout from which the command is run.
    """
    if not identities or identities[0].is_bare or not identities[0].path:
        raise ValueError("Git did not provide a non-bare main worktree identity")
    return identities[0]


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _disposable_uv_environment(root: Path) -> bool:
    """Recognize only a real root uv environment; never follow its links."""
    try:
        environment = root / ".venv"
        info = environment.lstat()
        if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
            return False
        config = environment / "pyvenv.cfg"
        info = config.lstat()
        if _is_reparse(info) or not stat.S_ISREG(info.st_mode):
            return False
        if not shutil.rmtree.avoids_symlink_attacks:
            return False
        descriptor = os.open(config, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor) as stream:
            return any(line.strip() == "uv = 0.12.23" for line in stream)
    except (OSError, ValueError):
        return False


def _filesystem_inventory(root: Path) -> dict[str, Any]:
    count = 0
    total_bytes = 0
    protected: list[str] = []
    reparse_points: list[str] = []
    inaccessible: list[str] = []
    git_metadata = root / ".git"
    try:
        metadata_info = git_metadata.lstat()
        if _is_reparse(metadata_info):
            reparse_points.append(".git")
        elif not stat.S_ISREG(metadata_info.st_mode):
            inaccessible.append(f"{git_metadata}: linked worktree .git marker is not a regular file")
    except FileNotFoundError:
        inaccessible.append(f"{git_metadata}: registered worktree has no .git marker")
    except OSError as exc:
        inaccessible.append(f"{git_metadata}: {exc}")
    disposable = _disposable_uv_environment(root)
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    if _path_equal(path, root / ".git"):
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                        relative = path.relative_to(root).as_posix()
                        components = [part.casefold() for part in Path(relative).parts]
                        if any(part in PROTECTED_COMPONENTS for part in components) or Path(relative).suffix.casefold() in {".log", ".ckpt", ".checkpoint"}:
                            protected.append(relative)
                        if _is_reparse(info):
                            if not (disposable and relative.startswith(".venv/")
                                    and stat.S_ISLNK(info.st_mode) and os.name == "posix"):
                                reparse_points.append(relative)
                            count += 1
                            if not entry.is_dir(follow_symlinks=False):
                                total_bytes += int(info.st_size)
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if components[0] == ".venv" and os.path.ismount(path):
                                inaccessible.append(f"{path}: mounted environment directory")
                            else:
                                stack.append(path)
                        elif entry.is_file(follow_symlinks=False):
                            count += 1
                            total_bytes += int(info.st_size)
                        else:
                            inaccessible.append(f"{path}: not an ordinary file or directory")
                    except (OSError, ValueError) as exc:
                        inaccessible.append(f"{path}: {exc}")
        except OSError as exc:
            inaccessible.append(f"{directory}: {exc}")
    return {
        "file_count": count, "total_bytes": total_bytes,
        "protected_paths": tuple(sorted(set(protected))),
        "reparse_points": tuple(sorted(set(reparse_points))),
        "inaccessible_paths": tuple(inaccessible),
        "complete": not inaccessible,
    }


def audit_worktree(
    worktree: str | Path, *, repository_root: str | Path, _lock_held: bool = False,
) -> WorktreeAudit:
    if not _lock_held:
        try:
            with worktree_safety_lock(repository_root):
                return audit_worktree(worktree, repository_root=repository_root, _lock_held=True)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            return WorktreeAudit(
                str(worktree), "FAIL_WORKTREE_SAFETY_LOCK", False, False, False, None,
                errors=(str(exc),),
            )
    requested = Path(worktree)
    if not requested.is_absolute():
        return WorktreeAudit(str(requested), "FAIL_RELATIVE_PATH", False, False, False, None,
                             errors=("worktree path must be absolute",))
    try:
        root = Path(repository_root).resolve(strict=True)
        target = requested.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return WorktreeAudit(str(requested), "FAIL_WORKTREE_DISCOVERY", False, False, False, None,
                             errors=(str(exc),))
    try:
        identities = _worktree_identities(root)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        return WorktreeAudit(str(target), "FAIL_WORKTREE_DISCOVERY", False, False, False, None,
                             errors=(str(exc),))
    try:
        main_identity = _main_worktree_identity(identities)
    except (OSError, RuntimeError, ValueError) as exc:
        return WorktreeAudit(str(target), "FAIL_PRIMARY_WORKTREE_IDENTITY_UNKNOWN", False,
                             False, False, None, errors=(str(exc),))
    identity = next((item for item in identities if _path_equal(item.path, target)), None)
    if identity is None:
        return WorktreeAudit(str(target), "FAIL_UNREGISTERED_WORKTREE", False, False, False, None,
                             errors=("path is not a registered Git worktree",))
    primary = _path_equal(main_identity.path, target)
    if primary:
        return WorktreeAudit(str(target), "FAIL_PRIMARY_WORKTREE", False, True, True, identity,
                             errors=("primary checkout cannot be removed",))
    errors: list[str] = []
    try:
        status_records = tuple(x for x in _git(
            target, ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        ).split(b"\0") if x)
        tracked = tuple(x.decode("utf-8", errors="replace") for x in status_records
                        if not x.startswith(b"?? "))
        untracked = tuple(x.decode("utf-8", errors="replace") for x in _git(target, ["ls-files", "--others", "--exclude-standard", "-z"]).split(b"\0") if x)
        ignored = tuple(x.decode("utf-8", errors="replace") for x in _git(target, ["ls-files", "--others", "--ignored", "--exclude-standard", "-z"]).split(b"\0") if x)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        tracked, untracked, ignored = (), (), ()
        errors.append(str(exc))
    try:
        inventory = _filesystem_inventory(target)
    except BaseException as exc:
        inventory = {"file_count": 0, "total_bytes": 0, "protected_paths": (),
                     "reparse_points": (), "inaccessible_paths": (str(exc),), "complete": False}
    errors.extend(inventory["inaccessible_paths"])
    disposable = _disposable_uv_environment(target)
    # Keep the full Git inventory in the report; exempt only this exact root.
    other_untracked = tuple(x for x in untracked if not (disposable and x.startswith(".venv/")))
    other_ignored = tuple(x for x in ignored if not (disposable and x.startswith(".venv/")))
    allowed = not any((tracked, other_untracked, other_ignored, inventory["protected_paths"],
                       inventory["reparse_points"], errors)) and inventory["complete"]
    if not inventory["complete"]:
        classification = "FAIL_INCOMPLETE_FILESYSTEM_INVENTORY"
    elif errors:
        classification = "FAIL_GIT_OR_INVENTORY"
    elif inventory["reparse_points"]:
        classification = "WORKTREE_REMOVE_BLOCKED_REPARSE_POINT"
    elif tracked:
        classification = "WORKTREE_REMOVE_BLOCKED_TRACKED_CHANGES"
    elif other_untracked or other_ignored or inventory["protected_paths"]:
        classification = "WORKTREE_REMOVE_BLOCKED_NONTRACKED_DATA"
    else:
        classification = "WORKTREE_REMOVE_ALLOWED"
    return WorktreeAudit(
        str(target), classification, allowed, True, False, identity, tracked, untracked,
        ignored, inventory["protected_paths"], inventory["reparse_points"],
        inventory["file_count"], inventory["total_bytes"], inventory["complete"],
        inventory["inaccessible_paths"], tuple(errors),
    )


def remove_worktree(worktree: str | Path, *, repository_root: str | Path) -> WorktreeRemoval:
    """Remove only while holding the safety lock through final Git removal."""
    try:
        with worktree_safety_lock(repository_root):
            first = audit_worktree(worktree, repository_root=repository_root, _lock_held=True)
            if not first.deletion_allowed or first.identity is None:
                return WorktreeRemoval(first.classification, False, False, Path(worktree).exists(), first.registered,
                                       "initial audit did not allow removal", first)
            try:
                middle = next((item for item in _worktree_identities(Path(repository_root).resolve(strict=True))
                               if _path_equal(item.path, first.path)), None)
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                return WorktreeRemoval("FAIL_WORKTREE_DISCOVERY", False, False, Path(first.path).exists(), None, str(exc), first)
            if middle != first.identity:
                return WorktreeRemoval("WORKTREE_REMOVE_BLOCKED_IDENTITY_CHANGED", False, False,
                                       Path(first.path).exists(), middle is not None, "identity changed after audit", first)
            second = audit_worktree(first.path, repository_root=repository_root, _lock_held=True)
            if not second.deletion_allowed or second.identity != first.identity:
                classification = ("WORKTREE_REMOVE_BLOCKED_IDENTITY_CHANGED" if second.identity != first.identity
                                  else second.classification)
                return WorktreeRemoval(classification, False, False, Path(first.path).exists(), second.registered,
                                       "immediate pre-removal audit did not match initial audit", second)
            environment = Path(first.path) / ".venv"
            if environment.exists():
                if not shutil.rmtree.avoids_symlink_attacks:
                    return WorktreeRemoval("FAIL_UNSAFE_ENVIRONMENT_REMOVER", False, False,
                                           True, True, "symlink-safe rmtree unavailable", second)
                try:
                    # Anchor deletion to an opened worktree directory, not a resolved link.
                    descriptor = os.open(first.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        shutil.rmtree(".venv", dir_fd=descriptor)
                    finally:
                        os.close(descriptor)
                except OSError as exc:
                    return WorktreeRemoval("FAIL_ENVIRONMENT_CLEANUP", False, False,
                                           True, True, str(exc), second)
                final = audit_worktree(first.path, repository_root=repository_root, _lock_held=True)
                if not final.deletion_allowed or final.identity != first.identity:
                    return WorktreeRemoval("WORKTREE_REMOVE_BLOCKED_AFTER_ENVIRONMENT_CLEANUP", False,
                                           False, True, final.registered, "post-cleanup audit failed", final)
                second = final
            result = subprocess.run(
                ["git", "worktree", "remove", first.path], cwd=Path(repository_root),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            try:
                remaining = next((item for item in _worktree_identities(Path(repository_root).resolve(strict=True))
                                  if _path_equal(item.path, first.path)), None)
            except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                return WorktreeRemoval("FAIL_POST_REMOVE_DISCOVERY", False, True, Path(first.path).exists(), None,
                                       str(exc), second)
            exists = Path(first.path).exists()
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            if remaining is None and exists:
                return WorktreeRemoval("WORKTREE_DEREGISTERED_RESIDUAL_DIRECTORY_REMAINS", False, True,
                                       True, False, detail, second)
            if result.returncode != 0:
                return WorktreeRemoval("WORKTREE_REMOVE_FAILED", False, True, exists, remaining is not None,
                                       f"git worktree remove exited {result.returncode}: {detail}", second)
            if remaining is not None or exists:
                return WorktreeRemoval("WORKTREE_REMOVE_POSTCONDITION_FAILED", False, True, exists,
                                       remaining is not None, detail, second)
            return WorktreeRemoval("WORKTREE_REMOVED", True, True, False, False, detail, second)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        return WorktreeRemoval("FAIL_WORKTREE_SAFETY_LOCK", False, False,
                               Path(worktree).exists(), None, str(exc))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Fail-closed Git worktree safety auditor")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("audit", "remove"):
        item = sub.add_parser(command)
        item.add_argument("worktree")
        item.add_argument("--repository-root", default=str(Path(__file__).resolve().parents[3]))
    args = parser.parse_args(argv)
    if args.command == "audit":
        result: Any = audit_worktree(args.worktree, repository_root=args.repository_root)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0 if result.deletion_allowed else 1
    result = remove_worktree(args.worktree, repository_root=args.repository_root)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.classification == "WORKTREE_REMOVED" else 1


__all__ = [
    "WorktreeAudit", "WorktreeIdentity", "WorktreeRemoval", "audit_worktree",
    "git_common_dir", "main", "remove_worktree", "worktree_safety_lock",
]
