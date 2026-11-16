#!/usr/bin/env bash
# Observation-only shim for afterFileEdit and stop; it cannot block the action.
set -u
umask 077

event="${1:-}"
case "$event" in
  after-file-edit|stop) ;;
  *)
    printf '{}\n'
    exit 0
    ;;
esac

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
SOURCE_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd -P)"
PYTHONPATH_VALUE="$SOURCE_ROOT/_ops/doc-warden/v2"

if output="$(
  cd "$SOURCE_ROOT" &&
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    PYTHONSAFEPATH=1 \
    PYTHONPATH="$PYTHONPATH_VALUE" \
      python3 -m doc_warden.cli hook "$event" 2>/dev/null
)"; then
  printf '%s\n' "$output"
else
  printf '{}\n'
fi

exit 0
