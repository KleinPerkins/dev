#!/usr/bin/env bash
# _ops/bin/session-lock.sh — human/agent-facing management CLI for the working-tree session
# lock (the R1 concurrency guard). Thin shim over the canonical, self-contained implementation
# in _ops/hooks/session-lock so there is ONE source of truth. Operates on the CURRENT repo
# (cwd), exactly like the commit-time hook does.
#
# Usage (run from inside the repo you mean):
#   ~/dev/_ops/bin/session-lock.sh status     # who holds the lock? (read-only)
#   ~/dev/_ops/bin/session-lock.sh acquire    # take/refresh it for this session
#   ~/dev/_ops/bin/session-lock.sh release    # drop it if this session holds it
#   ~/dev/_ops/bin/session-lock.sh steal      # force take-over (only if you're sure it's dead)
#   ~/dev/_ops/bin/session-lock.sh check      # acquire-or-block (what pre-commit runs)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # _ops/bin
exec bash "$SCRIPT_DIR/../hooks/session-lock" "${@:-status}"
