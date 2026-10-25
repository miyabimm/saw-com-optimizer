# Historical run closeout — retired

The former schema-v1–v4 administrative run-closeout and active-run lifecycle
were removed under Issue #128. No legacy run status, publication, closeout,
resume, or migration API is supported. Historical manifests, checkpoints, and
reports remain unchanged evidence; do not operate on them using this repository.

R5's external-data-root validation does not enumerate active external runs;
the separate project-local worktree-safety utility was retired under Issue
#143. For current authorization and preservation policy, see
[`../experiments.md`](../experiments.md) and the
[worktree operations policy](worktree_safety.md).
