#!/usr/bin/env bash
# AWA committed CLOUD sessionStart wrapper (project hook). Fire-and-forget context injection.
#
# Cloud agents run only committed project hooks, so this is the committed entrypoint that gives a
# cloud agent the AWA worktree-policy context the local installer wires up
# (`_ops/cursor-hooks/worktree-session.sh`). `sessionStart` is `failClosed:false` (context, never
# a gate), so a failure here can never block — but we still degrade cleanly to an EMPTY, valid
# JSON object when the committed session hook or python3 is absent, so nothing is emitted noisily.
set -uo pipefail

input="$(cat 2>/dev/null || true)"

emit_empty() { printf '{}\n'; exit 0; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd)" || emit_empty
SESSION="$SCRIPT_DIR/../../_ops/cursor-hooks/worktree-session.sh"

[ -x "$SESSION" ] || emit_empty
command -v python3 >/dev/null 2>&1 || emit_empty

printf '%s' "$input" | "$SESSION"
