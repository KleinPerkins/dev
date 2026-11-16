#!/usr/bin/env bash
# AWA committed CLOUD gate wrapper (project hook: beforeShellExecution + afterFileEdit).
#
# WHY THIS EXISTS. Cloud agents run ONLY committed project hooks (`.cursor/hooks.json` in the
# repo) — they do NOT read the operator's user-level `~/.cursor/hooks.json`. This wrapper is the
# committed entrypoint that gives a cloud agent the SAME AWA kernel gate the local installer wires
# up (`_ops/cursor-hooks/worktree-guard.sh`), by delegating to it.
#
# GRACEFUL DEGRADATION (critical). Even when `beforeShellExecution` is failClosed, this wrapper
# MUST NOT brick shell: degrade to ALLOW (valid JSON, exit 0) when the kernel guard is absent,
# python3 is missing, the guard crashes, times out, or returns invalid/empty JSON. The kernel
# guard itself is also fail-safe (SIGTERM/ERR -> allow). failClosed on the project hook is kept
# false in `.cursor/hooks.json` so timeout cannot machine-brick; this wrapper adds defense-in-depth.
set -uo pipefail

input="$(cat 2>/dev/null || true)"

allow() { printf '{ "permission": "allow" }\n'; exit 0; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || allow
# The committed AWA kernel guard lives at the repo root under _ops/cursor-hooks/. From
# .cursor/hooks/ that is two levels up. Resolving via SCRIPT_DIR is cwd-independent.
GUARD="$SCRIPT_DIR/../../_ops/cursor-hooks/worktree-guard.sh"

# No committed AWA guard in this checkout, or no python3 -> ALLOW (never block the cloud agent).
[ -x "$GUARD" ] || allow
command -v python3 >/dev/null 2>&1 || allow

# Guard present: delegate; if the guard fails or returns invalid JSON, degrade to ALLOW.
out=""
if ! out="$(printf '%s' "$input" | "$GUARD" 2>/dev/null)"; then
  allow
fi
if [ -z "$out" ]; then
  allow
fi
if ! printf '%s' "$out" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>/dev/null; then
  allow
fi
printf '%s\n' "$out"
exit 0
