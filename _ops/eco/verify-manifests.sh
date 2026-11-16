#!/usr/bin/env bash
# _ops/eco/verify-manifests.sh — validate EVERY artifact manifest under the managed roots (WS-1).
# Read-only. Exit 0 if all manifests valid (and at least one found), else 1.
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib.sh
. "$SELF_DIR/lib.sh"
MANIFEST="$SELF_DIR/manifest.sh"

fail=0; found=0
echo "== Manifest validation (kp-capability/v1) under managed roots =="
for stale in "$ECO_REPO_ROOT"/capabilities/skills/global/*/meta.yml "$ECO_REPO_ROOT"/capabilities/skills/local/*/meta.yml; do
  [ -f "$stale" ] || continue
  printf '  FAIL  stale flat capability path: %s\n' "${stale#"$ECO_REPO_ROOT"/}"
  fail=1; found=1
done
while IFS= read -r rel; do
  root="$ECO_REPO_ROOT/$rel"
  [ -d "$root" ] || { printf '  (skip) %s (root absent)\n' "$rel"; continue; }
  for d in "$root"/*/; do
    [ -d "$d" ] || continue
    if [ ! -f "${d}meta.yml" ]; then
      # An ARTIFACT dir (carries a SKILL.md or install.sh) MUST declare a manifest. A missing
      # manifest on an artifact is a FAIL (not a silent skip); non-artifact dirs are ignored.
      if [ -f "${d}SKILL.md" ] || [ -f "${d}install.sh" ]; then
        found=1; printf -- '-- %s\n' "${d#"$ECO_REPO_ROOT"/}"
        printf '  FAIL  missing meta.yml (artifact dir without a manifest)\n'; fail=1
      fi
      continue
    fi
    found=1
    printf -- '-- %s\n' "${d#"$ECO_REPO_ROOT"/}"
    if ! bash "$MANIFEST" validate "${d%/}"; then fail=1; fi
  done
done < <(eco_managed_roots)

echo
if [ "$found" -eq 0 ]; then
  echo "verify-manifests: NO manifests found under managed roots (FAIL)"; exit 1
fi
if [ "$fail" -eq 0 ]; then echo "verify-manifests: OK"; else echo "verify-manifests: FAILED"; fi
exit "$fail"
