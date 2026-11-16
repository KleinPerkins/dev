#!/usr/bin/env bash
# worktree-guard.sh — THIN DELEGATOR (host overlay) to the installed AWA kernel guard.
#
# The Cursor mutation backstop (beforeShellExecution + afterFileEdit) now ships GENERIC in
# KleinPerkins/awa and installs to ~/.local/share/awa/current. This shim keeps the historical
# `_ops/cursor-hooks/worktree-guard.sh` path (referenced by ~/.cursor/hooks.json and the committed
# cloud wrapper) and forwards to the installed guard with the ~/dev HOST POLICY OVERLAY injected, so
# the guard classifies with the org/host literals (cpp excluded, personal/* included, ...).
#
# DEGRADE-TO-ALLOW (never brick Cursor): if AWA is not installed — or anything fails — read+discard
# stdin, emit valid allow JSON, and exit 0. A soft backstop must never block a shell/edit.
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || { printf '{ "permission": "allow" }\n'; exit 0; }
ROOT="$(cd "$SELF_DIR/../.." && pwd)"                           # repo root (~/dev)

export AWA_POLICY="${AWA_POLICY:-$ROOT/_ops/policy/worktree-policy.yml}"
export AWA_GOVERNED_ROOT="${AWA_GOVERNED_ROOT:-$ROOT}"

RUNTIME="${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}"
GUARD="$RUNTIME/kernel/hooks/worktree-guard.sh"

if [ -x "$GUARD" ]; then
  exec "$GUARD" "$@"
fi

# AWA not installed -> degrade to allow (consume stdin so the caller never sees a broken pipe).
cat >/dev/null 2>&1 || true
printf '{ "permission": "allow" }\n'
exit 0
