#!/usr/bin/env bash
# Register the released AWA integrity sweep through local-jobs' public APIs.
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "$SELF_DIR/../.." && pwd)"
TYPE="awa-integrity"
ID="awa-integrity"
LABEL="com.kleinperkins.awa-integrity"
INTERVAL_SECONDS=21600
OWNER="KleinPerkins/dev:awa-integrity-host/v1"
HANDLER="$ROOT/_ops/local-jobs/awa-integrity.sh"
BINDING_CHECKER="${DEV_AWA_BINDING_CHECKER:-$ROOT/_ops/bin/check-awa-release-binding.py}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"

log() { printf '[awa-integrity-job] %s\n' "$*"; }
die() { printf '[awa-integrity-job] ERROR: %s\n' "$*" >&2; exit 1; }

resolve_local_jobs() {
  local candidate
  if [ -n "${DEV_AWA_LOCAL_JOBS_CLI:-}" ]; then
    [ -x "$DEV_AWA_LOCAL_JOBS_CLI" ] || die "configured local-jobs CLI is not executable"
    printf '%s\n' "$DEV_AWA_LOCAL_JOBS_CLI"
    return
  fi
  for candidate in \
    "$ROOT/capabilities/skills/global/skills/local-jobs/scripts/local-jobs.sh" \
    "$HOME/.claude/skills/local-jobs/scripts/local-jobs.sh" \
    "$HOME/.cursor/skills/local-jobs/scripts/local-jobs.sh"
  do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return
    fi
  done
  die "local-jobs CLI is unavailable"
}

resolve_local_jobs_home() {
  if [ -n "${DEV_AWA_LOCAL_JOBS_HOME:-}" ]; then
    printf '%s\n' "$DEV_AWA_LOCAL_JOBS_HOME"
    return
  fi
  python3 - "$LOCAL_JOBS" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1]).expanduser().resolve()
if path.parent.name not in {"bin", "scripts"}:
    raise SystemExit(1)
print(path.parent.parent)
PY
}

resolve_local_jobs_python() {
  local candidate
  if [ -n "${DEV_AWA_LOCAL_JOBS_PYTHON:-}" ]; then
    [ -x "$DEV_AWA_LOCAL_JOBS_PYTHON" ] || die "configured local-jobs Python is unavailable"
    printf '%s\n' "$DEV_AWA_LOCAL_JOBS_PYTHON"
    return
  fi
  if [ -n "${LOCAL_JOBS_PYTHON:-}" ] && [ -x "$LOCAL_JOBS_PYTHON" ]; then
    printf '%s\n' "$LOCAL_JOBS_PYTHON"
    return
  fi
  candidate="$LOCAL_JOBS_HOME/../../../_ops/.venv/bin/python3"
  if [ -x "$candidate" ] && "$candidate" -c 'import yaml' >/dev/null 2>&1; then
    printf '%s\n' "$candidate"
    return
  fi
  if python3 -c 'import yaml' >/dev/null 2>&1; then
    command -v python3
    return
  fi
  die "a local-jobs Python with PyYAML is unavailable"
}

validate_source() {
  [ -x "$BINDING_CHECKER" ] || die "AWA release binding checker is unavailable"
  [ -f "$HANDLER" ] && [ ! -L "$HANDLER" ] && [ -x "$HANDLER" ] \
    || die "AWA integrity local-jobs handler is missing or unsafe"
  "$BINDING_CHECKER" --static >/dev/null
  if find "$ROOT/_ops" -type f -name '*awa-integrity*.plist' -print -quit \
      | grep -q .; then
    die "source tree must not ship an AWA integrity plist"
  fi
}

runtime_available() {
  [ -f "$DATA_HOME/awa/release-pointer.json" ] \
    || [ -f "${DEV_AWA_RELEASE_POINTER:-/nonexistent}" ]
}

validate_runtime() {
  "$BINDING_CHECKER" --runtime >/dev/null \
    || die "exact AWA v1.8.2 release binding is unavailable"
}

validate_framework() {
  LOCAL_JOBS="$(resolve_local_jobs)"
  LOCAL_JOBS_HOME="$(resolve_local_jobs_home)" \
    || die "cannot resolve local-jobs home"
  AUTHORING="${DEV_AWA_LOCAL_JOBS_AUTHORING:-$LOCAL_JOBS_HOME/lib/authoring.py}"
  [ -f "$AUTHORING" ] && [ ! -L "$AUTHORING" ] \
    || die "local-jobs authoring engine is unavailable"
  LOCAL_JOBS_PYTHON_BIN="$(resolve_local_jobs_python)"
  LOCAL_JOBS_STATE="${LOCAL_JOBS_STATE:-$HOME/.local-jobs}"
  LOCAL_JOBS_OVERLAY_DIR="${LOCAL_JOBS_OVERLAY_DIR:-$LOCAL_JOBS_STATE/registry.d}"
  LOCAL_JOBS_REGISTRY="${LOCAL_JOBS_REGISTRY:-$LOCAL_JOBS_HOME/config/registry.yml}"
  export LOCAL_JOBS_HOME LOCAL_JOBS_STATE LOCAL_JOBS_OVERLAY_DIR LOCAL_JOBS_REGISTRY
  export LOCAL_JOBS_PYTHON="$LOCAL_JOBS_PYTHON_BIN"
}

local_jobs() {
  "$LOCAL_JOBS" "$@"
}

type_is_registered() {
  local output status
  output="$(local_jobs list-types --json)" \
    || die "cannot inspect registered local-jobs types"
  set +e
  LOCAL_JOBS_TYPES="$output" "$LOCAL_JOBS_PYTHON_BIN" - "$TYPE" <<'PY'
import json
import os
import sys

target = sys.argv[1]
try:
    catalog = json.loads(os.environ["LOCAL_JOBS_TYPES"])
except (json.JSONDecodeError, KeyError):
    raise SystemExit(2)
if not isinstance(catalog, list):
    raise SystemExit(2)
slugs = []
for item in catalog:
    if not isinstance(item, dict):
        raise SystemExit(2)
    slug = item.get("slug")
    if not isinstance(slug, str) or not slug:
        raise SystemExit(2)
    slugs.append(slug)
if len(slugs) != len(set(slugs)):
    raise SystemExit(3)
raise SystemExit(0 if target in slugs else 1)
PY
  status=$?
  set -e
  case "$status" in
    0) return 0 ;;
    1) return 1 ;;
    *) die "registered local-jobs type catalog is malformed or ambiguous" ;;
  esac
}

registered_handler() {
  local_jobs handler-path --type "$TYPE" 2>/dev/null
}

same_path() {
  python3 - "$1" "$2" <<'PY'
import sys
from pathlib import Path
raise SystemExit(0 if Path(sys.argv[1]).resolve() == Path(sys.argv[2]).resolve() else 1)
PY
}

read_instance() {
  local view
  view="$(local_jobs view-jobs --json)" || return
  LOCAL_JOBS_VIEW="$view" python3 - "$TYPE" "$ID" <<'PY'
import json
import os
import sys

job_type, job_id = sys.argv[1:]
try:
    view = json.loads(os.environ["LOCAL_JOBS_VIEW"])
except json.JSONDecodeError:
    raise SystemExit(2)
instances = view.get("instances") if isinstance(view, dict) else None
if not isinstance(instances, list):
    raise SystemExit(2)
matches = [
    item for item in instances
    if isinstance(item, dict)
    and (item.get("id") == job_id or item.get("type") == job_type)
]
if not matches:
    print("absent")
    raise SystemExit(0)
if len(matches) != 1:
    raise SystemExit(3)
item = matches[0]
schedule = item.get("schedule")
seconds = schedule.get("seconds") if isinstance(schedule, dict) else None
values = (
    "present",
    item.get("owner"),
    item.get("enabled"),
    item.get("launchd_loaded"),
    seconds,
    item.get("launchd_label"),
)
if any(value is None or "\t" in str(value) or "\n" in str(value) for value in values):
    raise SystemExit(4)
print("\t".join(str(value).lower() if isinstance(value, bool) else str(value)
                for value in values))
PY
}

assert_owned_instance() {
  local snapshot="${1:-}"
  local state owner enabled loaded seconds label
  IFS=$'\t' read -r state owner enabled loaded seconds label <<<"$snapshot"
  [ "$state" = "present" ] || die "AWA integrity job is not registered"
  [ "$owner" = "$OWNER" ] || die "refusing local-jobs instance owned by another source"
  [ "$label" = "$LABEL" ] || die "refusing local-jobs instance with unexpected label"
}

authoring() {
  "$LOCAL_JOBS_PYTHON_BIN" "$AUTHORING" "$@"
}

regression_fingerprint() {
  AUTHORING_RESULT="$1" python3 - <<'PY'
import json
import os

value = json.loads(os.environ["AUTHORING_RESULT"])
results = value.get("results")
if not isinstance(results, list):
    raise SystemExit(1)
normalized = []
for result in results:
    if not isinstance(result, dict) or not isinstance(result.get("type"), str):
        raise SystemExit(1)
    normalized.append({
        "type": result["type"],
        "ok": result.get("ok") is True,
        "errors": result.get("errors") if isinstance(result.get("errors"), list) else [],
    })
print(json.dumps(sorted(normalized, key=lambda item: item["type"]), sort_keys=True))
PY
}

extract_backup() {
  AUTHORING_RESULT="$1" python3 - <<'PY'
import json
import os
value = json.loads(os.environ["AUTHORING_RESULT"])
backup = value.get("backup")
if not isinstance(backup, str) or not backup:
    raise SystemExit(1)
print(backup)
PY
}

register_type() {
  local result
  result="$(authoring register \
    --type "$TYPE" \
    --handler "$HANDLER" \
    --description "AWA integrity surveillance host schedule")"
  REGISTER_BACKUP="$(extract_backup "$result")"
}

restore_registration() {
  [ -n "${REGISTER_BACKUP:-}" ] || return 0
  authoring restore-registry --backup "$REGISTER_BACKUP" >/dev/null
  REGISTER_BACKUP=""
}

commit_registration() {
  [ -n "${REGISTER_BACKUP:-}" ] || return 0
  rm -f -- "$REGISTER_BACKUP"
  REGISTER_BACKUP=""
}

ensure_owned_type() {
  local current
  if type_is_registered; then
    current="$(registered_handler)" \
      || die "registered AWA integrity type has no resolvable handler"
    same_path "$current" "$HANDLER" \
      || die "refusing local-jobs type owned by another handler"
    return 0
  fi
  local baseline
  baseline="$(authoring regression --exclude "$TYPE" || true)"
  REGRESSION_BASELINE="$(regression_fingerprint "$baseline")" \
    || die "cannot establish local-jobs regression baseline"
  register_type
  REGISTERED_THIS_RUN=1
}

rollback_stage() {
  local rc="$1"
  set +e
  if [ "${ADDED_THIS_RUN:-0}" -eq 1 ]; then
    local_jobs delete-job --id "$ID" --confirm >/dev/null 2>&1
  fi
  if [ "${REGISTERED_THIS_RUN:-0}" -eq 1 ]; then
    restore_registration >/dev/null 2>&1
  fi
  set -e
  return "$rc"
}

stage() {
  validate_source
  validate_runtime
  validate_framework

  REGISTER_BACKUP=""
  REGISTERED_THIS_RUN=0
  ADDED_THIS_RUN=0
  trap 'rc=$?; rollback_stage "$rc"; exit "$rc"' EXIT

  ensure_owned_type
  [ "${DEV_AWA_JOB_TEST_FAIL_STAGE:-}" != "after-register" ] \
    || die "injected failure after type registration"

  local snapshot state owner enabled loaded seconds label
  snapshot="$(read_instance)" || die "cannot inspect local-jobs instances"
  if [ "$snapshot" = "absent" ]; then
    local_jobs add-job \
      --type "$TYPE" \
      --interval-seconds "$INTERVAL_SECONDS" \
      --enabled false \
      --owner "$OWNER"
    ADDED_THIS_RUN=1
  else
    assert_owned_instance "$snapshot"
    IFS=$'\t' read -r state owner enabled loaded seconds label <<<"$snapshot"
    if [ "$seconds" != "$INTERVAL_SECONDS" ]; then
      local_jobs update-job \
        --id "$ID" \
        --interval-seconds "$INTERVAL_SECONDS" \
        --owner "$OWNER"
    fi
  fi

  [ "${DEV_AWA_JOB_TEST_FAIL_STAGE:-}" != "after-add" ] \
    || die "injected failure after job registration"
  authoring verify --type "$TYPE" >/dev/null \
    || die "AWA integrity local-jobs type verification failed"
  if [ "$REGISTERED_THIS_RUN" -eq 1 ]; then
    local after after_fingerprint
    after="$(authoring regression --exclude "$TYPE" || true)"
    after_fingerprint="$(regression_fingerprint "$after")" \
      || die "cannot evaluate local-jobs cross-type regression"
    [ "$after_fingerprint" = "$REGRESSION_BASELINE" ] \
      || die "local-jobs registration introduced a cross-type regression"
  fi
  commit_registration
  trap - EXIT
  log "staged disabled schedule through local-jobs"
}

preview() {
  validate_source
  if [ "${DEV_AWA_PREVIEW_STATIC:-0}" = "1" ]; then
    log "runtime and host-state validation intentionally deferred in source-only preview"
  elif runtime_available; then
    validate_runtime
  else
    log "runtime validation deferred: no installed AWA release pointer"
  fi
  validate_framework

  PREVIEW_TMP="$(mktemp -d "${TMPDIR:-/tmp}/awa-integrity-preview.XXXXXX")"
  trap 'rm -rf -- "$PREVIEW_TMP"' EXIT
  PREVIEW_HANDLER="$HANDLER" PREVIEW_DIR="$PREVIEW_TMP" python3 - <<'PY'
import json
import os
from pathlib import Path

target = Path(os.environ["PREVIEW_DIR"]) / "awa-integrity.yml"
target.write_text(
    json.dumps(
        {
            "id": "awa-integrity",
            "handler": os.environ["PREVIEW_HANDLER"],
            "description": "AWA integrity surveillance host schedule",
        },
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY
  LOCAL_JOBS_OVERLAY_DIR="$PREVIEW_TMP" local_jobs add-job \
    --type "$TYPE" \
    --interval-seconds "$INTERVAL_SECONDS" \
    --enabled false \
    --owner "$OWNER" \
    --dry-run >/dev/null
  log "preview: register type through local-jobs authoring engine"
  log "preview: stage $LABEL disabled at ${INTERVAL_SECONDS}s"
  log "preview: no hook, plist, LaunchAgent, runtime, or credential mutation"
  rm -rf -- "$PREVIEW_TMP"
  trap - EXIT
}

check_source() {
  validate_source
  log "runtime and host-state validation intentionally deferred in source-only check"
  log "source check passed"
}

doctor() {
  validate_source
  validate_runtime
  validate_framework
  local current snapshot
  current="$(registered_handler)" \
    || die "AWA integrity local-jobs type is not registered"
  same_path "$current" "$HANDLER" \
    || die "AWA integrity local-jobs type points to another handler"
  snapshot="$(read_instance)" || die "cannot inspect local-jobs instances"
  assert_owned_instance "$snapshot"
  local state owner enabled loaded seconds label
  IFS=$'\t' read -r state owner enabled loaded seconds label <<<"$snapshot"
  [ "$enabled" = "$loaded" ] \
    || die "AWA integrity local-jobs launchd state is drifted"
  authoring verify --type "$TYPE" >/dev/null \
    || die "AWA integrity local-jobs type verification failed"
  log "doctor passed"
}

activate() {
  stage
  local_jobs enable-job --id "$ID"
  log "activated through local-jobs"
}

repair() {
  stage
  local_jobs repair-job --id "$ID"
  log "repaired through local-jobs"
}

deactivate() {
  validate_source
  validate_runtime
  validate_framework
  local snapshot
  snapshot="$(read_instance)" || die "cannot inspect local-jobs instances"
  assert_owned_instance "$snapshot"
  local_jobs disable-job --id "$ID"
  log "deactivated through local-jobs"
}

remove_job() {
  validate_source
  validate_runtime
  validate_framework
  local snapshot current
  snapshot="$(read_instance)" || die "cannot inspect local-jobs instances"
  assert_owned_instance "$snapshot"
  current="$(registered_handler)" \
    || die "AWA integrity local-jobs type is not registered"
  same_path "$current" "$HANDLER" \
    || die "refusing local-jobs type owned by another handler"
  local_jobs disable-job --id "$ID"
  local_jobs delete-job --id "$ID" --confirm
  authoring unregister --type "$TYPE" >/dev/null
  log "removed owned job and type through local-jobs"
}

usage() {
  printf 'usage: %s --preview|--check|--stage|--activate|--repair|--deactivate|--remove|--doctor\n' "$0" >&2
  exit 2
}

case "${1:-}" in
  --preview) preview ;;
  --check) check_source ;;
  --stage) stage ;;
  --activate) activate ;;
  --repair) repair ;;
  --deactivate) deactivate ;;
  --remove) remove_job ;;
  --doctor) doctor ;;
  *) usage ;;
esac
