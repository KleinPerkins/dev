#!/usr/bin/env bash
# awa-engine-smoke.sh — thin dev-side smoke check for the INSTALLED AWA engine release.
#
# The AWA engine software lives in its own repo (KleinPerkins/awa), pinned by the global
# `tools/awa` shelf. `~/dev` no longer carries an in-tree engine copy; it installs the release
# and this smoke verifies the installed engine is present + runnable via the dev launcher.
#
# It is intentionally LIGHT (the full 85-test suite runs in the AWA repo's own CI):
#   - resolves the dev launcher (_ops/bin/awa-engine.sh -> installed release)
#   - asserts `awa-engine doctor` returns valid JSON with ok=true
#   - asserts `awa-engine daemon status` returns valid JSON (the dashboard's read-only probe)
#
# When NO release is installed (fresh machine / a CI runner without the private repo) the dev
# launcher exits 3; this smoke SKIPS cleanly (exit 0). The kernel guarantee holds engine-off, so
# a missing engine is a degraded, non-fatal state — dev's gates must not depend on an in-tree copy.
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "$SELF_DIR/../.." && pwd)"       # repo root
LAUNCHER="$ROOT/_ops/bin/awa-engine.sh"

echo "== AWA engine smoke (installed release) =="

if [ ! -x "$LAUNCHER" ]; then
  echo "  FAIL  dev launcher missing/not executable: $LAUNCHER"
  echo "awa-engine-smoke: FAILED"; exit 1
fi

# Probe resolution: the launcher exits 3 when no release is installed.
status_out="$("$LAUNCHER" daemon status 2>/dev/null)"; rc=$?
if [ "$rc" = "3" ]; then
  echo "  SKIP  no AWA engine release installed (set AWA_ENGINE_HOME or install KleinPerkins/awa)"
  echo "awa-engine-smoke: OK (skipped — engine-off is a valid degraded state)"; exit 0
fi

fail=0
if printf '%s' "$status_out" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if isinstance(d.get("daemon",{}).get("running"), bool) else 1)' 2>/dev/null; then
  echo "  PASS  installed engine: daemon status probe returns valid JSON"
else
  echo "  FAIL  installed engine daemon status probe returned invalid JSON"; fail=1
fi

doctor_out="$("$LAUNCHER" doctor 2>/dev/null || true)"
if printf '%s' "$doctor_out" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("ok") is True else 1)' 2>/dev/null; then
  echo "  PASS  installed engine: doctor ok"
else
  echo "  FAIL  installed engine doctor did not return ok=true"; fail=1
fi

if [ "$fail" = 0 ]; then echo "awa-engine-smoke: OK"; else echo "awa-engine-smoke: FAILED"; fi
exit "$fail"
