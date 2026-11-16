#!/usr/bin/env bash
set -euo pipefail

# Pre-commit runs with GIT_DIR/GIT_INDEX_FILE and friends set for the parent repo. The
# disposable fixture repos below must use their own git metadata, not the parent's --
# otherwise `git init` here silently re-initializes the parent repo instead (see
# worktree-verify.sh for the same guard).
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES 2>/dev/null || true

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
DEV_ROOT="$(cd "$HERE/../../../../.." && pwd)"
PROFILE="$HERE/profile.py"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

workspace_allows_exec() {
  local probe=""
  probe="$(mktemp "$TMP/exec-probe.XXXXXX")"
  printf '#!/bin/sh\n' >"$probe"
  chmod +x "$probe"
  if "$probe" >/dev/null 2>&1; then
    rm -f "$probe"
    return 0
  fi
  rm -f "$probe"
  return 1
}

# Historical validators and mocked protocol transitions remain useful regression
# coverage. They do not qualify a running controller or permit CLI restoration.
# Original runtime acceptance was deliberately omitted from the fresh root.
# Refusal is expected; pure schema/authority tests below use synthetic inputs.
if python3 -B "$PROFILE" verify-control-plane >"$TMP/old-control-plane.log" 2>&1; then
  echo "old controller evidence unexpectedly qualified as current" >&2
  exit 1
fi
grep -q 'canary-evidence.json' "$TMP/old-control-plane.log"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$HERE" -p 'test_profile.py'
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s "$HERE" -p 'test_prepare_candidate_tuple.py'
python3 -B "$DEV_ROOT/_ops/tests/test_successor_delivery.py"
if workspace_allows_exec; then
  bash "$HERE/bypass-drift-test.sh"
else
  echo "retirement tests require executable fixtures" >&2
  exit 1
fi
echo "historical v3 validation and retirement fences: PASS"
