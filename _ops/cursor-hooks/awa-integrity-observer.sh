#!/usr/bin/env bash
# Host-policy delegator for AWA v2's non-blocking stop observer.
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || {
  cat >/dev/null 2>&1 || true
  printf '{}\n'
  exit 0
}
ROOT="$(cd "$SELF_DIR/../.." 2>/dev/null && pwd)" || {
  cat >/dev/null 2>&1 || true
  printf '{}\n'
  exit 0
}

export AWA_POLICY="${AWA_POLICY:-$ROOT/_ops/policy/worktree-policy.yml}"
export AWA_GOVERNED_ROOT="${AWA_GOVERNED_ROOT:-$ROOT}"
export AWA_INTEGRITY_PROBE_REPO="${AWA_INTEGRITY_PROBE_REPO:-$ROOT/capabilities/awa}"

RUNTIME="${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}"
TARGET="$RUNTIME/kernel/hooks/awa-integrity-observer.sh"
if [ -x "$TARGET" ]; then
  exec "$TARGET" "$@"
fi

cat >/dev/null 2>&1 || true
printf '{}\n'
exit 0
