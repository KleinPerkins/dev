#!/usr/bin/env bash
# _ops/bin/install-hooks.sh — install the local git hooks for KleinPerkins/dev (idempotent).
# Symlinks .git/hooks/pre-commit -> _ops/hooks/pre-commit. Nothing here is committed; hooks
# live under .git/ which is never tracked.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
HOOK_SRC="$ROOT/_ops/hooks/pre-commit"
HOOK_DST="$ROOT/.git/hooks/pre-commit"

[ -f "$HOOK_SRC" ] || { printf 'install-hooks: missing %s\n' "$HOOK_SRC" >&2; exit 1; }
chmod +x "$HOOK_SRC"
mkdir -p "$(dirname "$HOOK_DST")"

if [ -L "$HOOK_DST" ] && [ "$(readlink "$HOOK_DST")" = "$HOOK_SRC" ]; then
  printf 'install-hooks: pre-commit already linked\n'
else
  [ -e "$HOOK_DST" ] && ! [ -L "$HOOK_DST" ] && mv "$HOOK_DST" "$HOOK_DST.bak.$(date +%Y%m%d%H%M%S)"
  ln -sfn "$HOOK_SRC" "$HOOK_DST"
  printf 'install-hooks: linked %s -> %s\n' "$HOOK_DST" "$HOOK_SRC"
fi
