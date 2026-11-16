#!/usr/bin/env bash
# Focused regression for kernel-guarantee-verify.sh scrubbing poisoned GIT_EXEC_PATH.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
SCRIPT="$ROOT/_ops/checks/kernel-guarantee-verify.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { printf 'kernel-guarantee-git-exec-path: FAIL: %s\n' "$*" >&2; exit 1; }

FAKE_ENGINE="$TMP/fake-engine"
mkdir -p "$FAKE_ENGINE/engine/tests"
cat >"$FAKE_ENGINE/engine/__init__.py" <<'PY'
# test package marker
PY
cat >"$FAKE_ENGINE/engine/tests/__init__.py" <<'PY'
# test package marker
PY
cat >"$FAKE_ENGINE/engine/tests/test_guard.py" <<'PY'
import os
import unittest


class GuardEnvScrubTest(unittest.TestCase):
    def test_poisoned_git_exec_path_is_scrubbed(self):
        self.assertNotIn(
            "GIT_EXEC_PATH",
            os.environ,
            "poisoned GIT_EXEC_PATH leaked into engine.tests.test_guard",
        )


if __name__ == "__main__":
    unittest.main()
PY

BASE_COPY="$TMP/kernel-guarantee-base.sh"
python3 - "$SCRIPT" "$BASE_COPY" "$ROOT" <<'PY'
from pathlib import Path
import shlex
import sys

src = Path(sys.argv[1]).read_text(encoding="utf-8")
root = sys.argv[3]
patched = src.replace(
    'ROOT="$(cd "$SELF_DIR/../.." && pwd)"',
    f"ROOT={shlex.quote(root)}",
    1,
)
patched = patched.replace(" GIT_EXEC_PATH", "")
Path(sys.argv[2]).write_text(patched, encoding="utf-8")
PY
chmod +x "$BASE_COPY"

run_variant() {
  local label="$1"
  local script_path="$2"
  local expected_rc="$3"
  local out="$TMP/$label.out"
  local rc=0

  (
    export AWA_HOME="$TMP/absent-runtime"
    export AWA_ENGINE_ROOT="$FAKE_ENGINE"
    export GIT_EXEC_PATH="$TMP/poisoned-git-exec-path"
    bash "$script_path"
  ) >"$out" 2>&1 || rc=$?

  if [ "$rc" -ne "$expected_rc" ]; then
    printf '%s\n' "--- $label output ---" >&2
    cat "$out" >&2
    fail "$label exit code $rc (expected $expected_rc)"
  fi
  LAST_OUT="$out"
}

assert_output() {
  local needle="$1"
  grep -Fq "$needle" "$LAST_OUT" || {
    printf '%s\n' '--- output ---' >&2
    cat "$LAST_OUT" >&2
    fail "missing output: $needle"
  }
}

run_variant base "$BASE_COPY" 1
assert_output "FAIL  engine.tests.test_guard failed"
assert_output "kernel-guarantee-verify: FAILED"

run_variant current "$SCRIPT" 0
assert_output "PASS  engine guard degraded-mode suite (test_guard, engine OFF)"
assert_output "kernel-guarantee-verify: OK"

printf 'kernel-guarantee-git-exec-path: OK\n'
