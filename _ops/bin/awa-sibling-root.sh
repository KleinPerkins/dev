#!/usr/bin/env bash
# awa-sibling-root.sh — print the KleinPerkins/awa engine tree root if present (read-only).
#
# AWA now ships as a Standalone System Package installed to ~/.local/share/awa/current (the RUNTIME
# subset) alongside ~/.local/share/awa/checkout (the FULL pinned clone), bound by the global
# `tools/awa` shelf. This helper prints the "engine tree" root — the full source tree, which carries
# engine/tests + hook-probe/ + live-verify/ (the runtime `current/` is only a subset and omits the
# dev-only hook-probe/live-verify evidence). So the full CHECKOUT is the primary resolution; the
# runtime and legacy sibling checkouts remain fallbacks.
# Resolution order: AWA_ENGINE_ROOT, $XDG checkout (full clone), AWA_HOME / $XDG current (runtime),
#                   legacy capabilities/awa checkouts.
set -euo pipefail

# CI source verification must not resolve or probe any installed/home checkout.
if [ "${DEV_AWA_SOURCE_ONLY:-0}" = 1 ]; then
  exit 1
fi

if [ -n "${AWA_ENGINE_ROOT:-}" ] && [ -d "${AWA_ENGINE_ROOT}/engine" ]; then
  printf '%s\n' "$AWA_ENGINE_ROOT"
  exit 0
fi

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
DEV_ROOT="$(cd "$SELF_DIR/../.." && pwd)"
XDG_DATA="${XDG_DATA_HOME:-$HOME/.local/share}"

for candidate in \
  "$XDG_DATA/awa/checkout" \
  "${AWA_HOME:-$XDG_DATA/awa/current}" \
  "$XDG_DATA/awa/current" \
  "$DEV_ROOT/capabilities/awa" \
  "$HOME/dev/capabilities/awa"; do
  if [ -d "$candidate/engine" ]; then
    printf '%s\n' "$candidate"
    exit 0
  fi
done

exit 1
