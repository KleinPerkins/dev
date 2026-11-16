# Native Codex workspace entry

Before mutation, identify the repository by its Git remote and read its current
owner instructions. Inspect this chat's attachments with `list_artifacts` and
reuse a suitable native managed worktree. Otherwise use `create_worktree` or
`attach_worktree`. Explicitly use the returned workspace directory in this turn;
check the active workspace root, command cwd, Git common directory, per-worktree
Git directory, branch, cleanliness, and writer ownership before editing.
A printed helper path or shell `cd` does not establish that this chat moved.

Preserve existing dirty and unrelated work. One writer owns each tree and index;
independent writers need separate worktrees. Set a unique `DEV_SESSION_ID` and
use the owner-prescribed writer guard. Do not steal a live foreign writer's lock
or treat a fail-open guard warning as verified exclusion. A detached native
worktree needs its own delivery branch before source changes.

{{shared_worktree_behavior}}

Native attachment establishes workspace placement only. AWA registration and
protection remain unsupported under the current owner identity contract; defer
to KleinPerkins/awa's accepted decisions. Do not manufacture authority from cwd,
PID, environment, receipts, or native attachment. Native archive is separate from
AWA Close and delivery. AWA's kernel and exact consequence approvals still apply.

Workspace entry does not authorize automatic installation or destructive cleanup.
