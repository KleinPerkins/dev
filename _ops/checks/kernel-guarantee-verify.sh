#!/usr/bin/env bash
# kernel-guarantee-verify.sh — Phase 5 kernel guarantee (engine OFF) + degraded-mode env matrix.
#
# Proves the plan v2.1 kernel-guarantee capability: the local guard + kernel shims preserve work
# with the daemon dead/never-started, and cloud/Desktop hook surfaces degrade honestly.
# Invoked by copy-honesty via operator-copy.json verifier_cmd; also run from worktree-verify.
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "$SELF_DIR/../.." && pwd)"
# Never discover a HOME checkout implicitly. A caller may select a source tree;
# otherwise use only the exact installed runtime resolved below.
AWA_ENGINE_ROOT="${AWA_ENGINE_ROOT:-}"

fail=0
pass() { printf '  PASS  %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; fail=1; }
skip() { printf '  SKIP  %s\n' "$1"; }

# The ~/dev guard entry point is a THIN DELEGATOR to the installed AWA kernel (bound by the global
# tools/awa shelf). The primary-mutation "deny" UAT below (ASK_ON removed 2026-07-07 — an included
# primary mutation is now an ENFORCED deny, since Cursor treats `ask` as non-blocking) therefore
# requires the installed kernel; when AWA is absent (a CI runner without the private release) the
# delegator degrades-to-allow (by design — a soft backstop must never brick), so we SKIP the
# deny/allow row there. The degraded rows (cloud wrapper degrade, committed-hook failClosed) still
# run — they assert the honest engine-off behavior that must hold WITHOUT the kernel.
AWA_RUNTIME="${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}"
if [ -x "$AWA_RUNTIME/kernel/hooks/worktree-guard.sh" ]; then AWA_INSTALLED=1; else AWA_INSTALLED=0; fi
if [ "$AWA_INSTALLED" = 1 ]; then
  AWA_RUNTIME="$(cd "$AWA_RUNTIME" && pwd -P)"
  export AWA_HOME="$AWA_RUNTIME" AWA_ENGINE_HOME="$AWA_RUNTIME"
  [ -n "$AWA_ENGINE_ROOT" ] || AWA_ENGINE_ROOT="$AWA_RUNTIME"
fi
if [ -n "$AWA_ENGINE_ROOT" ] && [ ! -d "$AWA_ENGINE_ROOT/engine/tests" ]; then
  printf 'kernel-guarantee-verify: explicit engine test source unavailable\n' >&2
  exit 1
fi
export AWA_ENGINE_ROOT

# Also safe when invoked directly, outside worktree-verify's fixture boundary.
kernel_verify_owner="$(mktemp -d)" || exit 1
REPO=""; degrade_tmp=""
cleanup() {
  [ -z "$REPO" ] || rm -rf "$REPO"
  [ -z "$degrade_tmp" ] || rm -rf "$degrade_tmp"
  rm -rf "$kernel_verify_owner"
}
trap cleanup EXIT
if [ -z "${AWA_VERIFY_BASE:-}" ]; then
  export AWA_GOVERNED_ROOT="$kernel_verify_owner/governed"
  export AWA_VERIFY_BASE="$AWA_GOVERNED_ROOT/personal"
fi
export XDG_STATE_HOME="$kernel_verify_owner/xdg/state"
export XDG_DATA_HOME="$kernel_verify_owner/xdg/data"
export XDG_CONFIG_HOME="$kernel_verify_owner/xdg/config"
mkdir -p "$AWA_VERIFY_BASE" "$XDG_STATE_HOME" "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" || exit 1

json_permission='import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("permission")==sys.argv[1] else 1)'

echo "== AWA kernel guarantee (Phase 5 + env matrix) =="

# Hook GIT_DIR leak guard (same footgun as verify-operating-model.sh / worktree-verify.sh):
# test_guard spins throwaway repos whose `git commit` must not inherit a parent hook's GIT_DIR, AND
# it exercises the guard's primary-maintenance decision, which FAILS CLOSED on any git env var in
# engine/guard.py `_PRIMARY_MAINTENANCE_RISKY_GIT_ENV` — notably GIT_EXEC_PATH, which `git commit`
# exports to hooks. Unset the FULL risky set (defense-in-depth; verify-operating-model.sh already
# sanitizes the whole tree, but keep this self-sufficient for standalone/verifier_cmd invocations).
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
  GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_CONFIG GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM GIT_EXEC_PATH \
  GIT_NAMESPACE GIT_SHALLOW_FILE GIT_REPLACE_REF_BASE GIT_NO_REPLACE_OBJECTS \
  GIT_CEILING_DIRECTORIES GIT_DISCOVERY_ACROSS_FILESYSTEM 2>/dev/null || true

# Phase 5: engine-off guard suite — never starts daemon or opens SQLite.
if [ -n "$AWA_ENGINE_ROOT" ] && [ -d "$AWA_ENGINE_ROOT/engine/tests" ]; then
  if (cd "$AWA_ENGINE_ROOT" && env -u AWA_GOVERNED_ROOT -u AWA_VERIFY_BASE PYTHONPATH=. AWA_ENGINE_TESTS_ACTIVE=1 python3 -m unittest engine.tests.test_guard -q 2>/dev/null); then
    pass "engine guard degraded-mode suite (test_guard, engine OFF)"
  else
    bad "engine.tests.test_guard failed"
  fi
else
  pass "engine guard degraded-mode suite skipped (awa sibling absent — env-matrix only)"
fi

# Env matrix row: Engine unavailable — kernel guard DENIES a primary mutation (enforced), allows
# read-only. Deny (not ask) is the real protection: Cursor only honors `deny` on beforeShellExecution.
REPO="$(mktemp -d "$AWA_VERIFY_BASE/.awa-kg.XXXXXX" 2>/dev/null || true)"
if [ -z "${REPO:-}" ] || [ ! -d "$REPO" ]; then
  bad "could not create disposable scratch repo for kernel-guard UAT"
else
  (
    unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_EXEC_PATH 2>/dev/null || true
    git init -q "$REPO"
    printf '# uat\n' > "$REPO/README.md"
    git -C "$REPO" add README.md
    git -C "$REPO" -c user.email="49759187+KleinPerkins@users.noreply.github.com" -c user.name="KleinPerkins" commit -qm init
    git -C "$REPO" branch -M main
    git -C "$REPO" remote add origin "git@github.com:KleinPerkins/awa-verify-temp.git"
  )
  if [ "$AWA_INSTALLED" = 1 ]; then
    if printf '{"cwd":"%s","command":"git add README.md"}' "$REPO" \
       | "$ROOT/_ops/cursor-hooks/worktree-guard.sh" 2>/dev/null \
       | python3 -c "$json_permission" deny; then
      pass "env-matrix: primary shell mutation DENIES (engine unavailable row; enforced ON deny)"
    else
      bad "kernel guard did not deny on primary mutation"
    fi
    if printf '{"cwd":"%s","command":"git status"}' "$REPO" \
       | "$ROOT/_ops/cursor-hooks/worktree-guard.sh" 2>/dev/null \
       | python3 -c "$json_permission" allow; then
      pass "env-matrix: read-only shell allowed on primary"
    else
      bad "kernel guard did not allow read-only command"
    fi
  else
    skip "env-matrix: primary ask/allow rows (AWA not installed; delegator degrades-to-allow by design — verified in KleinPerkins/awa CI)"
  fi

  # Env matrix row: Cloud — wrapper degrades to allow when the kernel guard is unreachable.
  degrade_tmp="$kernel_verify_owner/degrade"
  mkdir -p "$degrade_tmp/.cursor/hooks" || { bad "could not create owned degraded-mode fixture"; exit 1; }
  if [ -x "$ROOT/.cursor/hooks/awa-cloud-guard.sh" ]; then
    cp "$ROOT/.cursor/hooks/awa-cloud-guard.sh" "$degrade_tmp/.cursor/hooks/"
    if printf '{"cwd":"/tmp","command":"rm -rf /"}' \
       | bash "$degrade_tmp/.cursor/hooks/awa-cloud-guard.sh" 2>/dev/null \
       | python3 -c "$json_permission" allow; then
      pass "env-matrix: cloud wrapper degrades to allow when kernel unreachable"
    else
      bad "cloud wrapper did not degrade to allow"
    fi
  else
    bad "awa-cloud-guard.sh missing"
  fi
fi

# failClosed:false on committed cloud hooks — hook failure must not brick the cloud VM.
if [ -f "$ROOT/.cursor/hooks.json" ]; then
  if CLOUD_HOOKS="$ROOT/.cursor/hooks.json" python3 - <<'PY'
import json, os, sys
data = json.load(open(os.environ["CLOUD_HOOKS"]))
hooks = data.get("hooks", {})
for event in ("beforeShellExecution", "sessionStart"):
    for e in (hooks.get(event) or []):
        if e.get("failClosed") is True:
            print(f"{event}: failClosed must be false", file=sys.stderr)
            sys.exit(1)
sys.exit(0)
PY
  then
    pass "env-matrix: committed cloud hooks failClosed false (hook-failure fails open)"
  else
    bad "committed cloud hooks have failClosed:true on a gating event"
  fi
else
  bad "committed .cursor/hooks.json missing"
fi

if [ "$fail" -eq 0 ]; then
  echo "kernel-guarantee-verify: OK"
else
  echo "kernel-guarantee-verify: FAILED"
fi
exit "$fail"
