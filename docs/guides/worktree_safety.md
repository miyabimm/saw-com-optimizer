# Git worktree safety

Git worktrees are disposable source checkouts. `git status --short` only reports
Git-visible changes; it does not prove that ignored raw runs, test state, logs,
or other local files are absent.

This guide documents retained worktree and data-safety mechanisms, not a
supported production launcher. The old orchestration launch, status,
publication, active-run registry, and administrative closeout lifecycle have
been removed. R5 raw/review storage is future-only and tested synthetically; it
is not wired to a production runner. Follow [`../experiments.md`](../experiments.md)
for current storage contracts and authorization. For the overview, see
[`data_storage_logging_review_policy.md`](data_storage_logging_review_policy.md).

## Durable run storage

The legacy persistent run-destination validator was retired with the old
launcher; no standalone persistent-path validation API is supported. The
worktree utility audits checkout identity and contents, not external data
roots. Any future R5 store use must follow the external `SAWOPT_DATA_ROOT`,
containment, identity, exclusivity, and fail-closed rules in `experiments.md`;
it must not fall back to repository `runs/`.

Historical `external_persistent_v1` fields and review paths remain immutable
records, not a current R5 schema or production-run procedure. Do not rewrite,
migrate, or resume them under this guide.

## Worktree protection

The standalone worktree utility protects Git identity and the filesystem
contents of a selected checkout. It does **not** inventory external run roots
or process state, and cannot establish that no external job uses a checkout.
Do not infer global run absence or use this utility as a substitute for the
separate authorization required for any run or worktree cleanup.

Audit and removal serialize through one lock in Git's common directory. There
is no active-run registration or publication-driven release in the current
product.

## Audit before removal

Use the repository utility before considering a worktree removable:

```bash
uv run --locked python scripts/worktree_safety.py audit <absolute-worktree-path>
uv run --locked python scripts/worktree_safety.py remove <absolute-worktree-path>
```

The removal command repeats its full audit and worktree-identity check
immediately before calling plain `git worktree remove`. Tracked modifications,
untracked files, ignored files (including caches), protected raw-data paths,
reparse points, inaccessible paths, incomplete inventories, primary checkouts,
and unregistered residual directories block removal. If Git removal errors or
leaves a deregistered directory, the utility does not perform filesystem
cleanup. Preserve the residual and investigate separately. Do not use
`git clean` as a cleanup shortcut.

## Disposable uv environment

Only the worktree root `.venv/` is disposable. It must be a real directory with
an ordinary `pyvenv.cfg` containing the pinned uv marker (`uv = 0.12.23`).
Unrecognized environments remain nontracked-data blockers. Audit never deletes.
The full inventory still blocks inaccessible entries, mount points, protected
runs/checkpoints/logs, tracked changes, and every other ignored or untracked
path (including nested `.venv` directories).

Inside this verified subtree, POSIX symlinks are leaf entries: inventory never
follows them, and fd-safe `shutil.rmtree` unlinks them without deleting their
file or directory targets. No per-link allowlist is needed. The `.venv` root
itself and every link/reparse point outside it still block; Windows reparse
points remain blocked. Platforms without symlink-safe removal fail closed.
After two successful audits and identity checks under the shared worktree
safety lock, remove deletes only `.venv`, then re-audits before plain Git
worktree removal. A cleanup failure preserves the worktree and prevents Git
removal.
