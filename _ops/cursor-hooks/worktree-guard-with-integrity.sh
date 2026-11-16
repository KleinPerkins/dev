#!/usr/bin/env bash
# Host-policy delegator for AWA v2's composite beforeShellExecution guard.
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || {
  printf '{ "permission": "allow" }\n'
  exit 0
}
ROOT="$(cd "$SELF_DIR/../.." 2>/dev/null && pwd)" || {
  printf '{ "permission": "allow" }\n'
  exit 0
}

export AWA_POLICY="${AWA_POLICY:-$ROOT/_ops/policy/worktree-policy.yml}"
export AWA_GOVERNED_ROOT="${AWA_GOVERNED_ROOT:-$ROOT}"
export AWA_INTEGRITY_PROBE_REPO="${AWA_INTEGRITY_PROBE_REPO:-$ROOT/capabilities/awa}"

RUNTIME="${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}"
TARGET="$RUNTIME/kernel/hooks/worktree-guard-with-integrity.sh"
if [ -x "$TARGET" ]; then
  exec "$TARGET" "$@"
fi

cat >/dev/null 2>&1 || true
printf '{ "permission": "allow" }\n'
exit 0
