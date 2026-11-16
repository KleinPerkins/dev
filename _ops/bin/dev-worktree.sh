#!/usr/bin/env bash
# dev-worktree.sh — THIN DELEGATOR (host overlay) to the installed AWA kernel CLI.
#
# The AWA kernel now ships GENERIC (zero-link) in KleinPerkins/awa and installs to
# ~/.local/share/awa/current (bound by the global `tools/awa` shelf). This shim keeps the historical
# `_ops/bin/dev-worktree.sh` path — the always-applied worktree rules reference it — and forwards to
# the installed kernel CLI with the ~/dev HOST POLICY OVERLAY injected (AWA_POLICY + AWA_GOVERNED_ROOT),
# so classification uses the org/host literals from _ops/policy/worktree-policy.yml (cpp excluded, etc.).
#
# If AWA is not installed yet, this exits non-zero with an honest instruction (the kernel guarantee
# holds engine-off; a missing install is a degraded, recoverable state — run the overlay installer).
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # _ops/bin
ROOT="$(cd "$SELF_DIR/../.." && pwd)"                           # repo root (~/dev)

# Inject the host overlay policy + governed root (respect an explicit caller override).
export AWA_POLICY="${AWA_POLICY:-$ROOT/_ops/policy/worktree-policy.yml}"
export AWA_GOVERNED_ROOT="${AWA_GOVERNED_ROOT:-$ROOT}"

RUNTIME="${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}"
KCLI="$RUNTIME/kernel/bin/dev-worktree.sh"

if [ ! -x "$KCLI" ]; then
  printf 'dev-worktree (delegator): AWA is not installed at %s\n' "$RUNTIME" >&2
  printf '  Install it:  bash %s/_ops/bin/install-dev-awa-overlay.sh\n' "$ROOT" >&2
  printf '  (the kernel guarantee holds engine-off; this is a degraded, recoverable state)\n' >&2
  exit 3
fi

exec "$KCLI" "$@"
