#!/usr/bin/env bash
# _ops/bin/install-identity-guard.sh — install the per-repo commit-time guards (M2 identity-guard
# + R1 session-lock + T5 data-guard) into <repo>'s ACTIVE hooks path, NON-DESTRUCTIVELY, CHAINED,
# IDEMPOTENTLY.
#
#   • Copies the self-contained guards to  <hooks>/{identity-guard,session-lock,data-guard}
#   • Wires a tiny managed dispatcher at    <hooks>/pre-commit  that runs the session-lock first
#     (concurrency), then the identity-guard, then the data-guard, then chains any pre-existing
#     hook (preserved as pre-commit.local).
#   • Re-running makes no changes once current (idempotent) and NEVER duplicates or clobbers an
#     existing hook (e.g. chaos-labs' schema-registry-gate is preserved + still runs).
#
# core.hooksPath AWARENESS (R6 fix): if the repo sets core.hooksPath, writing .git/hooks/pre-commit
# is INERT — git would never run it. This installer detects that and installs into the ACTIVE hooks
# path instead. If that active path is managed by another tool (husky/lefthook) and cannot be owned
# safely, it FAILS LOUD rather than leaving a false sense of safety.
#
# Nothing here is tracked: hook dirs live outside version control, so installs do not dirty any
# repo. By default only KleinPerkins-owned repos are touched (use --force to override).
#
# Usage:  _ops/bin/install-identity-guard.sh <repo-path> [--force]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # _ops/bin
GUARD_SRC="$SCRIPT_DIR/../hooks/identity-guard"
LOCK_SRC="$SCRIPT_DIR/../hooks/session-lock"
DATA_SRC="$SCRIPT_DIR/../hooks/data-guard"
REG_SRC="$SCRIPT_DIR/../hooks/registration-guard"
DISPATCH_SRC="$SCRIPT_DIR/../hooks/pre-commit-dispatcher"
MARKER='managed-by: KleinPerkins/dev identity-guard'

REPO=""; FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
    -*) printf 'install-identity-guard: unknown flag: %s\n' "$1" >&2; exit 2 ;;
    *) REPO="$1" ;;
  esac
  shift
done
[ -n "$REPO" ] || { printf 'usage: install-identity-guard.sh <repo-path> [--force]\n' >&2; exit 2; }
[ -f "$GUARD_SRC" ] || { printf 'install-identity-guard: missing guard source %s\n' "$GUARD_SRC" >&2; exit 1; }
[ -f "$LOCK_SRC" ]  || { printf 'install-identity-guard: missing session-lock source %s\n' "$LOCK_SRC" >&2; exit 1; }
[ -f "$DATA_SRC" ]  || { printf 'install-identity-guard: missing data-guard source %s\n' "$DATA_SRC" >&2; exit 1; }
[ -f "$DISPATCH_SRC" ] || { printf 'install-identity-guard: missing dispatcher source %s\n' "$DISPATCH_SRC" >&2; exit 1; }
[ -f "$REG_SRC" ]   || { printf 'install-identity-guard: missing registration-guard source %s\n' "$REG_SRC" >&2; exit 1; }

REPO="$(cd "$REPO" 2>/dev/null && pwd)" || { printf 'install-identity-guard: no such dir: %s\n' "$REPO" >&2; exit 1; }
TOP="$(git -C "$REPO" rev-parse --show-toplevel 2>/dev/null)" || {
  printf 'install-identity-guard: not a git repo: %s\n' "$REPO" >&2; exit 1; }
GITDIR="$(git -C "$REPO" rev-parse --absolute-git-dir 2>/dev/null)"
COMMON_GITDIR="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
[ -n "$COMMON_GITDIR" ] || COMMON_GITDIR="$GITDIR"

# Scope: only KleinPerkins-owned repos unless --force (guard is a no-op elsewhere anyway).
origin="$(git -C "$REPO" config --get remote.origin.url 2>/dev/null || true)"
owner=""
case "$origin" in
  *github.com[:/]*) rest="${origin#*github.com}"; rest="${rest#[:/]}"; owner="${rest%%/*}" ;;
esac
owner_lc="$(printf '%s' "$owner" | tr '[:upper:]' '[:lower:]')"
if [ "$owner_lc" != "kleinperkins" ] && [ "$FORCE" -ne 1 ]; then
  printf 'SKIP  %s — origin owner is %s (not KleinPerkins); use --force to install anyway.\n' \
    "$REPO" "${owner:-<none>}"
  exit 0
fi

# ---------------------------------------------------------------------------
# Determine the ACTIVE hooks path (R6: honor core.hooksPath).
# ---------------------------------------------------------------------------
hooks_path_cfg="$(git -C "$REPO" config --get core.hooksPath 2>/dev/null || true)"
if [ -n "$hooks_path_cfg" ]; then
  case "$hooks_path_cfg" in
    /*) HOOKS="$hooks_path_cfg" ;;                 # absolute
    *)  HOOKS="$TOP/$hooks_path_cfg" ;;            # relative to repo top (git's rule)
  esac
  # If the custom path is managed by another hook framework we can't safely own, FAIL LOUD.
  case "$hooks_path_cfg" in
    *.husky*|*lefthook*|*pre-commit*)
      cat >&2 <<EOF

  ✖ install-identity-guard: REFUSING to install into a foreign-managed hooks path.

      repo:           $TOP
      core.hooksPath: $hooks_path_cfg  (managed by husky/lefthook/pre-commit)

  WHY: this repo routes git hooks to a tool-managed directory, so a guard written to
  .git/hooks would be INERT (a false sense of safety), and a guard written INTO that
  directory would be clobbered the next time that tool reinstalls its hooks.

  WHAT TO DO NEXT — pick one:
    1) Add the guards to the framework's own pre-commit entry, e.g. for husky append to
       "$TOP/.husky/pre-commit":
         "$GITDIR/../_ops/hooks/session-lock" check || exit \$?   # if dev layer is reachable
         # and an identity-guard line; or copy both guard scripts in and call them.
    2) If you don't need that framework's hooks here, unset the override and re-run:
         git -C "$TOP" config --unset core.hooksPath
         $0 "$TOP"

  Not installed. (Exiting non-zero so callers/dev-doctor surface this loudly.)
EOF
      exit 4
      ;;
  esac
  hookspath_note=" (honoring core.hooksPath=$hooks_path_cfg)"
else
  # In a linked worktree, --absolute-git-dir points at .git/worktrees/<name>,
  # whose hooks/ directory is inert. Git executes hooks from the common git dir.
  HOOKS="$COMMON_GITDIR/hooks"
  hookspath_note=""
fi
mkdir -p "$HOOKS"

guard_action="current"; lock_action="current"; data_action="current"; reg_action="current"; dispatch_action="current"

# 1) guard bodies (copy only if changed)
if [ ! -f "$HOOKS/identity-guard" ] || ! cmp -s "$GUARD_SRC" "$HOOKS/identity-guard"; then
  cp "$GUARD_SRC" "$HOOKS/identity-guard"; guard_action="installed"
fi
chmod +x "$HOOKS/identity-guard"
if [ ! -f "$HOOKS/session-lock" ] || ! cmp -s "$LOCK_SRC" "$HOOKS/session-lock"; then
  cp "$LOCK_SRC" "$HOOKS/session-lock"; lock_action="installed"
fi
chmod +x "$HOOKS/session-lock"
if [ ! -f "$HOOKS/data-guard" ] || ! cmp -s "$DATA_SRC" "$HOOKS/data-guard"; then
  cp "$DATA_SRC" "$HOOKS/data-guard"; data_action="installed"
fi
chmod +x "$HOOKS/data-guard"
if [ ! -f "$HOOKS/registration-guard" ] || ! cmp -s "$REG_SRC" "$HOOKS/registration-guard"; then
  cp "$REG_SRC" "$HOOKS/registration-guard"; reg_action="installed"
fi
chmod +x "$HOOKS/registration-guard"

# 2) managed dispatcher pre-commit (chains a preserved prior hook via pre-commit.local)
disp_tmp="$(mktemp)"
cp "$DISPATCH_SRC" "$disp_tmp"

PC="$HOOKS/pre-commit"
if [ -e "$PC" ] || [ -L "$PC" ]; then
  if grep -qF "$MARKER" "$PC" 2>/dev/null; then
    # already our dispatcher → idempotent refresh only (NEVER re-move pre-commit.local)
    if ! cmp -s "$disp_tmp" "$PC"; then cp "$disp_tmp" "$PC"; dispatch_action="refreshed"; fi
    chmod +x "$PC"
  else
    # foreign pre-existing hook → preserve by chaining
    if [ -e "$HOOKS/pre-commit.local" ] || [ -L "$HOOKS/pre-commit.local" ]; then
      printf 'WARN  %s — foreign pre-commit AND pre-commit.local both exist; refusing to clobber. Resolve manually.\n' "$REPO" >&2
      rm -f "$disp_tmp"
      exit 3
    fi
    mv "$PC" "$HOOKS/pre-commit.local"      # preserves a symlink or a real script
    cp "$disp_tmp" "$PC"; chmod +x "$PC"
    dispatch_action="chained (prior hook → pre-commit.local)"
  fi
else
  cp "$disp_tmp" "$PC"; chmod +x "$PC"
  dispatch_action="created"
fi
rm -f "$disp_tmp"

printf 'OK    %s — guard:%s session-lock:%s data-guard:%s registration-guard:%s dispatcher:%s%s\n' \
  "$REPO" "$guard_action" "$lock_action" "$data_action" "$reg_action" "$dispatch_action" "$hookspath_note"
