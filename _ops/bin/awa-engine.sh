#!/usr/bin/env bash
# awa-engine.sh — dev-side launcher that delegates to the INSTALLED AWA engine release.
#
# The AWA engine software now lives in its OWN repo (KleinPerkins/awa), pinned by the global
# `tools/awa` shelf (a Flavor-2 release-descriptor). `~/dev` is the D3 host/override layer: it
# installs the AWA release and this shim finds it and delegates. It carries NO engine code.
#
# Resolution order:
#   1) $AWA_ENGINE_HOME                    — explicit override (a checkout of KleinPerkins/awa)
#   2) $AWA_HOME / $XDG_DATA_HOME/awa/current — the INSTALLED SSP runtime (primary)
#   3) $XDG_DATA_HOME/awa/checkout         — the pinned GCB clone
#   4) ~/dev/capabilities/awa              — a legacy dev-of-AWA checkout
# If none resolves to a runnable engine, exit non-zero with an honest note. Callers such as the
# dashboard probe degrade to "engine off — kernel guard active", which is CORRECT: the kernel
# safety guarantee holds with the engine OFF (kernel-first).
set -euo pipefail

find_engine() {
  local c
  if [ -n "${AWA_ENGINE_HOME:-}" ] && [ -x "$AWA_ENGINE_HOME/bin/awa-engine.sh" ]; then
    printf '%s\n' "$AWA_ENGINE_HOME/bin/awa-engine.sh"; return 0
  fi
  for c in \
    "${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}" \
    "${XDG_DATA_HOME:-$HOME/.local/share}/awa/current" \
    "${XDG_DATA_HOME:-$HOME/.local/share}/awa/checkout" \
    "$HOME/dev/capabilities/awa"; do
    if [ -x "$c/bin/awa-engine.sh" ]; then printf '%s\n' "$c/bin/awa-engine.sh"; return 0; fi
  done
  return 1
}

engine="$(find_engine || true)"
if [ -z "${engine:-}" ]; then
  echo "awa-engine: no installed AWA engine release found (set AWA_ENGINE_HOME or install KleinPerkins/awa;" >&2
  echo "            the kernel guarantee holds engine-off, so this is a degraded, non-fatal state)." >&2
  exit 3
fi

exec "$engine" "$@"
