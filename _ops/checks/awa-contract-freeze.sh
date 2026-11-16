#!/usr/bin/env bash
# awa-contract-freeze.sh — THIN DELEGATOR (host overlay) to the installed AWA freeze checker.
#
# The frozen behavior contract (CLI verbs/flags, awa-worktree/v1 JSON shape, guard permission schema,
# awa-lease/v1 shape) and its freeze checker now live in KleinPerkins/awa (kernel/checks/), where the
# contract is the SINGLE authoritative copy and the checker resolves the CLI/hook BY ROLE (AWA_HOME).
# `~/dev` no longer carries a contract copy; this shim runs the INSTALLED checker against the INSTALLED
# kernel.
#
# When AWA is not installed (a dev-only CI runner without the private release), SKIP with exit 0 —
# the contract is frozen + verified in the AWA repo's own CI; ~/dev's gates must not depend on an
# in-repo kernel copy.
#
# Invoked by worktree-verify.sh (hence by `make verify-ci` and the pre-commit gate).
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"    # _ops/checks
ROOT="$(cd "$SELF_DIR/../.." && pwd)"                            # repo root (~/dev)
RUNTIME="${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}"
CHECKER="$RUNTIME/kernel/checks/awa-contract-freeze.sh"

echo "== AWA kernel contract freeze (delegated to installed AWA) =="
if [ ! -x "$CHECKER" ]; then
  echo "  SKIP  AWA not installed at $RUNTIME (contract frozen + verified in KleinPerkins/awa CI)"
  echo "awa-contract-freeze: OK (skipped — installed AWA absent)"
  exit 0
fi

exec env AWA_HOME="$RUNTIME" "$CHECKER" "$@"
