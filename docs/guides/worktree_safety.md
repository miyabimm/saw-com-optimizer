# Worktree operations policy

The standalone project-local worktree audit/removal utility was retired under
Issue #143. This repository does not provide a replacement wrapper or claim
feature parity with the removed guard. The R5 `io.experiment_store` data-root
validator remains unchanged: it rejects repository/worktree containment, but
it is not a worktree cleanup tool and does not inspect ignored checkout data or
active processes.

The 13 registered worktrees present for Issue #143 remain untouched. The
accepted Gate A metadata inventory was not deletion permission; no existing
checkout, ignored file, virtual environment, result, raw artifact, log, or
checkpoint is thereby classified as disposable. Do not infer that
`git status --short` reveals all local data.

Before any future, separately authorized worktree removal, require a
**target-specific** review of data ownership and preservation, a refreshed
inspection of ignored data, confirmation that no Pi/agent/other process is
using the checkout, and a known interactive TUI workflow. Do not use Pi Web for
destructive confirmations until generic UI response support is verified.

Avoid `git clean`, forced removal, blind `prune`, symlink traversal, and
removal of ignored results. This is a procedure and an explicit safety
tradeoff—not an equivalent replacement for the retired guard. It does not
authorize any worktree or local-data operation.
