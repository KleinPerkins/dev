#!/usr/bin/env bash
# Advisory session-start shim. It is fail-open and delegates only to read-only views.
set -u
umask 077

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
SOURCE_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd -P)"
PYTHONPATH_VALUE="$SOURCE_ROOT/_ops/doc-warden/v2"

if output="$(
  cd "$SOURCE_ROOT" &&
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    PYTHONSAFEPATH=1 \
    PYTHONPATH="$PYTHONPATH_VALUE" \
      python3 -m doc_warden.cli hook session-start 2>/dev/null
)"; then
  printf '%s\n' "$output"
else
  printf '{}\n'
fi

exit 0
