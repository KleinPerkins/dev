#!/usr/bin/env bash
# Operator-private local-jobs type for AWA's released integrity schedule.
# local-jobs remains the sole launchd/plist writer; this handler only declares
# the singleton contract and invokes the dev host wrapper.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEV_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
LOCAL_JOBS_PYTHON="${LOCAL_JOBS_PYTHON:-python3}"
LOCAL_JOBS_HOME="${LOCAL_JOBS_HOME:-}"
[ -n "$LOCAL_JOBS_HOME" ] \
  || { printf 'awa-integrity: LOCAL_JOBS_HOME is required\n' >&2; exit 2; }
[ -f "$LOCAL_JOBS_HOME/lib/handler_lib.sh" ] \
  || { printf 'awa-integrity: local-jobs handler chassis is missing\n' >&2; exit 2; }

# The released host schedule fixes the launchd label independently from the
# operator's neutral local-jobs label root.
export LOCAL_JOBS_LABEL_ROOT="com.kleinperkins"
# shellcheck disable=SC1091
. "$LOCAL_JOBS_HOME/lib/handler_lib.sh"

HANDLER_TYPE="awa-integrity"
HANDLER_CARDINALITY="singleton"
HANDLER_LABEL_TOKEN="awa-integrity"
HANDLER_SINGLETON_ID="awa-integrity"
HANDLER_SCHEMA_VERSION=1
HANDLER_STORE_FILE="${LOCAL_JOBS_AWA_INTEGRITY_CONFIG:-$LOCAL_JOBS_STATE/jobs/awa-integrity.yml}"
# shellcheck disable=SC2034
HANDLER_FIELD_DEFAULTS='{"enabled":false}'
# shellcheck disable=SC2034
HANDLER_REQUIRED_FIELDS='["schedule","owner"]'
HANDLER_ADD_SCHEMA='[
  {"flag":"--interval-seconds","field":"schedule","kind":"interval_seconds","required":true,"help":"repeat every 3600-43200 seconds"},
  {"flag":"--enabled","field":"enabled","kind":"bool","default":false,"help":"true | false"},
  {"flag":"--owner","field":"owner","kind":"scalar","required":true,"help":"source ownership marker"}
]'

handler_describe() {
  HANDLER_TYPE="$HANDLER_TYPE" HANDLER_CARDINALITY="$HANDLER_CARDINALITY" \
  HANDLER_LABEL_TOKEN="$HANDLER_LABEL_TOKEN" HANDLER_SCHEMA_VERSION="$HANDLER_SCHEMA_VERSION" \
  HANDLER_STORE_FILE="$HANDLER_STORE_FILE" HANDLER_ADD_SCHEMA="$HANDLER_ADD_SCHEMA" \
  HANDLER_LABEL_TEMPLATE="$(_hl_label_template)" \
    "$LOCAL_JOBS_PYTHON" -c 'import json, os
print(json.dumps({
    "type": os.environ["HANDLER_TYPE"],
    "cardinality": os.environ["HANDLER_CARDINALITY"],
    "label_token": os.environ["HANDLER_LABEL_TOKEN"],
    "label_template": os.environ["HANDLER_LABEL_TEMPLATE"],
    "schema_version": int(os.environ["HANDLER_SCHEMA_VERSION"]),
    "config_file": os.environ["HANDLER_STORE_FILE"],
    "add_schema": json.loads(os.environ["HANDLER_ADD_SCHEMA"]),
}, indent=2))'
}

# Narrow the generic interval syntax to the product-owned released bounds.
_hl_validate_schedule() {
  local value="$1"
  SCHEDULE_VALUE="$value" "$LOCAL_JOBS_PYTHON" - <<'PY' \
    || hl_die "interval schedule must stay within released bounds (3600-43200 seconds)"
import json
import os

try:
    value = json.loads(os.environ["SCHEDULE_VALUE"])
except (TypeError, json.JSONDecodeError):
    raise SystemExit(1)
if (
    not isinstance(value, dict)
    or set(value) != {"kind", "seconds"}
    or value.get("kind") != "interval"
    or isinstance(value.get("seconds"), bool)
    or not isinstance(value.get("seconds"), int)
    or not 3600 <= value["seconds"] <= 43200
):
    raise SystemExit(1)
PY
}

handler_launchd_env() {
  AWA_RUNTIME="${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}" \
  AWA_WRAPPER="${DEV_AWA_INTEGRITY_WRAPPER:-$DEV_ROOT/_ops/bin/awa-integrity-host-sweep.sh}" \
    "$LOCAL_JOBS_PYTHON" - <<'PY'
import json
import os

print(json.dumps({
    "AWA_HOME": os.environ["AWA_RUNTIME"],
    "DEV_AWA_INTEGRITY_WRAPPER": os.environ["AWA_WRAPPER"],
}, separators=(",", ":")))
PY
}

handler_working_dir() {
  printf '%s' "$DEV_ROOT"
}

handler_doctor_extra() {
  local wrapper="${DEV_AWA_INTEGRITY_WRAPPER:-$DEV_ROOT/_ops/bin/awa-integrity-host-sweep.sh}"
  local runtime="${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}"
  local issues=0
  if [ -f "$wrapper" ] && [ ! -L "$wrapper" ] && [ -x "$wrapper" ]; then
    printf 'host wrapper: ok\n'
  else
    printf 'host wrapper: INVALID\n'
    issues=$((issues + 1))
  fi
  if [ -f "$runtime/kernel/bin/awa-integrity-sweep.sh" ] \
      && [ ! -L "$runtime/kernel/bin/awa-integrity-sweep.sh" ] \
      && [ -x "$runtime/kernel/bin/awa-integrity-sweep.sh" ]; then
    printf 'released sweep: ok\n'
  else
    printf 'released sweep: INVALID\n'
    issues=$((issues + 1))
  fi
  return "$issues"
}

handler_do_run() {
  local id="" dry=0
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --id) shift; id="${1:-}" ;;
      --dry-run) dry=1 ;;
      *) hl_die "unknown run option: $1" ;;
    esac
    shift
  done
  [ -z "$id" ] || [ "$id" = "$HANDLER_SINGLETON_ID" ] \
    || hl_die "run id must be $HANDLER_SINGLETON_ID"

  local wrapper="${DEV_AWA_INTEGRITY_WRAPPER:-$DEV_ROOT/_ops/bin/awa-integrity-host-sweep.sh}"
  [ -f "$wrapper" ] && [ ! -L "$wrapper" ] && [ -x "$wrapper" ] \
    || hl_die "host wrapper is missing or unsafe"
  if [ "$dry" -eq 1 ]; then
    printf '@@RUNLOG@@ {"status":"dry-run","fields":{"severity":"unknown","evaluator_exit":null,"scheduler_exit":0}}\n'
    return 0
  fi

  local output rc=0
  output="$("$wrapper" 2>&1)" || rc=$?
  [ -z "$output" ] || printf '%s\n' "$output"
  AWA_HOST_OUTPUT="$output" AWA_HOST_RC="$rc" "$LOCAL_JOBS_PYTHON" - <<'PY'
import json
import os

prefix = "@@AWA_INTEGRITY_HOST_SWEEP@@ "
lines = [
    line[len(prefix):]
    for line in os.environ.get("AWA_HOST_OUTPUT", "").splitlines()
    if line.startswith(prefix)
]
rc = int(os.environ["AWA_HOST_RC"])
payload = None
if len(lines) == 1:
    try:
        candidate = json.loads(lines[0])
    except json.JSONDecodeError:
        candidate = None
    if isinstance(candidate, dict):
        payload = candidate
if payload is None:
    payload = {
        "severity": "red",
        "evaluator_exit": rc,
        "scheduler_exit": rc,
        "expected_evaluator_exit": False,
        "checked_at": "unknown",
    }
severity = payload.get("severity")
# local-jobs has no warning status, so a degraded sweep (e.g. unleased linked
# worktrees, which is the normal state) is recorded as success and flagged via
# the severity field plus a warning note. Only green/degraded succeed; red and
# anything unknown fail closed.
if rc != 0:
    status = "failure"
elif severity in ("green", "degraded"):
    status = "success"
else:
    status = "completed_with_failures"
fields = {
    "severity": severity if severity in {"green", "degraded", "red"} else "red",
    "evaluator_exit": payload.get("evaluator_exit"),
    "scheduler_exit": payload.get("scheduler_exit", rc),
    "expected_evaluator_exit": bool(payload.get("expected_evaluator_exit")),
    "checked_at": payload.get("checked_at", "unknown"),
}
if status == "success" and severity == "degraded":
    FALLBACK = "degraded (reasons unavailable; see run log)"

    def _count(value):
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def _clean(text):
        text = "".join(ch for ch in str(text) if ch not in '{}[]"\\')
        return " ".join(text.split())[:80]

    def sweep_reasons(output):
        # The sweep prints its pretty-printed status JSON, then our marker line.
        body = "\n".join(
            line for line in output.splitlines() if not line.startswith(prefix)
        )
        start = body.find("{")
        if start < 0:
            return []
        status_doc, _ = json.JSONDecoder().raw_decode(body[start:])
        if not isinstance(status_doc, dict):
            return []
        reasons = []
        worktrees = status_doc.get("worktrees")
        used_worktrees = False
        if isinstance(worktrees, dict):
            unleased = _count(worktrees.get("unleased"))
            linked = _count(worktrees.get("discovered_linked"))
            conflicts = _count(worktrees.get("conflicts"))
            if unleased:
                used_worktrees = True
                reasons.append(
                    f"{unleased} of {linked} linked worktrees unleased"
                    if linked
                    else f"{unleased} linked worktrees unleased"
                )
            if conflicts:
                used_worktrees = True
                reasons.append(f"{conflicts} conflict" + ("" if conflicts == 1 else "s"))
        for item in status_doc.get("invariants") or []:
            if not isinstance(item, dict) or item.get("severity") in (None, "green"):
                continue
            # The lifecycle invariant only restates the worktree counts above.
            if item.get("id") == "lifecycle" and used_worktrees:
                continue
            evidence = _clean(item.get("evidence") or item.get("id") or "")
            if evidence:
                reasons.append(evidence)
        return reasons

    try:
        reasons = sweep_reasons(os.environ.get("AWA_HOST_OUTPUT", ""))
    except (ValueError, TypeError, AttributeError):
        reasons = []
    warning = ("degraded: " + "; ".join(reasons[:6])) if reasons else FALLBACK
    fields["warning"] = warning[:300]
    print("awa-integrity: WARNING " + fields["warning"])
print("@@RUNLOG@@ " + json.dumps(
    {"status": status, "fields": fields},
    sort_keys=True,
    separators=(",", ":"),
))
PY
  return "$rc"
}

handler_main "$@"
