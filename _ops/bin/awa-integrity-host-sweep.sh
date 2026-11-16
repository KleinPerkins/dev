#!/usr/bin/env bash
# local-jobs host adapter for the released, session-independent AWA deep sweep.
# AWA owns evaluation and severity; this wrapper only normalizes expected
# evaluator exits for launchd while exposing the real result to local-jobs.
set -uo pipefail

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
AWA_HOME="${AWA_HOME:-$DATA_HOME/awa/current}"
SWEEP="$AWA_HOME/kernel/bin/awa-integrity-sweep.sh"
CLOCK="${DEV_AWA_CLOCK:-}"
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "$SELF_DIR/../.." && pwd)"
BINDING_CHECKER="${DEV_AWA_BINDING_CHECKER:-$ROOT/_ops/bin/check-awa-release-binding.py}"
export AWA_POLICY="${AWA_POLICY:-$ROOT/_ops/policy/worktree-policy.yml}"
export AWA_GOVERNED_ROOT="${AWA_GOVERNED_ROOT:-$ROOT}"
export AWA_INTEGRITY_PROBE_REPO="${AWA_INTEGRITY_PROBE_REPO:-$ROOT/capabilities/awa}"

fail() {
  printf 'awa-integrity-host-sweep: %s\n' "$*" >&2
  exit 70
}

[ -x "$BINDING_CHECKER" ] || fail "AWA release binding checker is unavailable"
[ -f "$SWEEP" ] && [ ! -L "$SWEEP" ] && [ -x "$SWEEP" ] \
  || fail "released AWA deep-sweep executable is missing or unsafe"
"$BINDING_CHECKER" --runtime >/dev/null \
  || fail "released AWA v1.8.2 runtime validation failed"

# A periodic host trigger is not an agent session and must never acquire or
# inherit AWA's session identity, lease, or lock context.
unset DEV_SESSION_ID CURSOR_SESSION_ID AWA_SESSION_ID
unset AWA_LEASE_ID AWA_LOCK_ID

evaluator_exit=0
"$SWEEP" || evaluator_exit=$?

case "$evaluator_exit" in
  0) severity="green"; scheduler_exit=0; expected=true ;;
  1) severity="degraded"; scheduler_exit=0; expected=true ;;
  2) severity="red"; scheduler_exit=0; expected=true ;;
  *) severity="red"; scheduler_exit="$evaluator_exit"; expected=false ;;
esac

if [ -n "$CLOCK" ]; then
  [ -x "$CLOCK" ] || fail "configured clock is not executable"
  checked_at="$("$CLOCK")" || fail "configured clock failed"
else
  checked_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')" || fail "clock failed"
fi

AWA_HOST_SEVERITY="$severity" \
AWA_HOST_EVALUATOR_EXIT="$evaluator_exit" \
AWA_HOST_SCHEDULER_EXIT="$scheduler_exit" \
AWA_HOST_EXPECTED="$expected" \
AWA_HOST_CHECKED_AT="$checked_at" \
python3 - <<'PY'
import json
import os

print(
    "@@AWA_INTEGRITY_HOST_SWEEP@@ "
    + json.dumps(
        {
            "schema": "dev-awa-integrity-host-sweep/v1",
            "severity": os.environ["AWA_HOST_SEVERITY"],
            "evaluator_exit": int(os.environ["AWA_HOST_EVALUATOR_EXIT"]),
            "scheduler_exit": int(os.environ["AWA_HOST_SCHEDULER_EXIT"]),
            "expected_evaluator_exit": os.environ["AWA_HOST_EXPECTED"] == "true",
            "checked_at": os.environ["AWA_HOST_CHECKED_AT"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
)
PY

exit "$scheduler_exit"
