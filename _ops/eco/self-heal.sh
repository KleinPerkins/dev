#!/usr/bin/env bash
# _ops/eco/self-heal.sh — bounded verifier-driven self-heal retry loop (reorg-v2 WS-4 / D-14).
#
# Runs a verifier set; if any fail, applies idempotent heal actions and retries, up to N attempts
# (default 3), then SURFACES the remaining failures. Compose of existing verify-* + eco checks.
#   N override: ECO_HEAL_RETRIES=<n>
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib.sh
. "$SELF_DIR/lib.sh"
ROOT="$ECO_REPO_ROOT"
N="${ECO_HEAL_RETRIES:-3}"
# Guard against a non-numeric / zero override that would otherwise loop forever or never run.
case "$N" in ''|*[!0-9]*) eco_warn "ECO_HEAL_RETRIES not a positive integer ('$N'); using 3"; N=3 ;; esac
[ "$N" -ge 1 ] 2>/dev/null || N=3

# Verifier set: name|command. Each must exit 0 = healthy.
run_verifiers() {
  local failed=()
  _v() { local name="$1"; shift; if "$@" >/tmp/eco-heal.$$ 2>&1; then printf '  ok   %s\n' "$name"; else printf '  FAIL %s\n' "$name"; failed+=("$name"); fi; }
  # Full (NOT --ci) operating-model verify: the --ci variant skips the live install checks, so it
  # would mask a broken install (missing/ drifted .mdc + tool symlinks) that self-heal must catch+heal.
  _v "operating-model"      bash "$ROOT/_ops/checks/verify-operating-model.sh"
  _v "manifests"            bash "$SELF_DIR/verify-manifests.sh"
  # Zero-link across ALL managed roots (Decision C), not just skills/global — scan each that exists.
  for _r in $(eco_managed_roots); do
    [ -d "$ROOT/$_r" ] && _v "zero-link($_r)" bash "$SELF_DIR/verify-zero-link.sh" --mode global "$ROOT/$_r"
  done
  [ -f "$ROOT/capabilities/verify-capabilities.sh" ] && _v "capabilities-dedup" bash "$ROOT/capabilities/verify-capabilities.sh"
  # AWA (Standalone System Package) overlay health. Only gate this when AWA is installed OR the
  # global tools/awa GCB shelf is present (skills sibling checked out) — otherwise AWA cannot be
  # installed here (e.g. offline without the sibling) and there is nothing to heal.
  local awa_rt="${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}"
  if [ -x "$awa_rt/kernel/bin/dev-worktree.sh" ] || [ -f "$ROOT/capabilities/skills/global/tools/awa/install.sh" ]; then
    _v "awa-overlay" bash "$ROOT/_ops/bin/install-dev-awa-overlay.sh" --doctor
  fi
  HEAL_FAILED="${failed[*]:-}"
  [ -z "$HEAL_FAILED" ]
}

# Idempotent heal actions (NEVER destructive): regenerate the .mdc, relink skills, re-surface skills.
heal() {
  # FULL install-agent-rules (NOT --gen-only): --gen-only only regenerates the .mdc/managed blocks and
  # never (re)creates the tool symlinks, so it could not actually fix a missing/broken install — the
  # loop would spin and surface forever. The full installer is idempotent + symlink-installing.
  eco_log "heal: (re)install agent rules (full) + relink + re-surface skills + repair AWA overlay"
  bash "$ROOT/_ops/bin/install-agent-rules.sh" >/dev/null 2>&1 || true
  bash "$ROOT/capabilities/bootstrap.sh"        >/dev/null 2>&1 || true
  bash "$ROOT/_ops/bin/install-skills.sh"        >/dev/null 2>&1 || true
  # Heal AWA via the global tools/awa shelf --repair (through the ~/dev overlay, which force
  # re-places the runtime at the pin and re-wires the delegator hooks + host policy). Offline/auth
  # failures degrade (kernel guarantee holds engine-off), so heal never hard-fails on network.
  bash "$ROOT/_ops/bin/install-dev-awa-overlay.sh" --repair >/dev/null 2>&1 || true
}

attempt=1
while :; do
  eco_log "self-heal attempt $attempt/$N"
  if run_verifiers; then
    eco_log "self-heal: GREEN on attempt $attempt"
    exit 0
  fi
  eco_warn "failing: $HEAL_FAILED"
  if [ "$attempt" -ge "$N" ]; then
    eco_err "self-heal: exhausted $N attempts; remaining failures: $HEAL_FAILED"
    exit 1
  fi
  heal
  attempt=$((attempt+1))
done
