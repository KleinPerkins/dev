#!/usr/bin/env bash
# worktree-session.sh — THIN DELEGATOR (host overlay) to the installed AWA sessionStart hook.
#
# The lightweight worktree-context sessionStart hook now ships GENERIC in KleinPerkins/awa and
# installs to ~/.local/share/awa/current. This shim keeps the historical
# `_ops/cursor-hooks/worktree-session.sh` path (referenced by ~/.cursor/hooks.json) and forwards to
# the installed session hook with the ~/dev HOST POLICY OVERLAY injected.
#
# DEGRADE (never break a session): if AWA is not installed, emit a minimal valid JSON and exit 0.
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || { printf '{}\n'; exit 0; }
ROOT="$(cd "$SELF_DIR/../.." && pwd)"                           # repo root (~/dev)

export AWA_POLICY="${AWA_POLICY:-$ROOT/_ops/policy/worktree-policy.yml}"
export AWA_GOVERNED_ROOT="${AWA_GOVERNED_ROOT:-$ROOT}"

RUNTIME="${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}"
SESSION="$RUNTIME/kernel/hooks/worktree-session.sh"

if [ -x "$SESSION" ]; then
  exec "$SESSION" "$@"
fi

cat >/dev/null 2>&1 || true
printf '{}\n'
exit 0
