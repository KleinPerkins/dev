#!/usr/bin/env bash
# ~/dev/bootstrap.sh — new-machine / refresh orchestrator for the home operating model.
#
# Idempotent. Safe to re-run. Steps:
#   1. Run the capabilities skills-hub bootstrap (clone KleinPerkins/skills if missing + relink).
#   2. Immediately resolve the AWA external runtime + Dev host-hook transaction.
#   3. Install/refresh the agent rules into Cursor/Codex/Claude (+ mirror alwaysApply Cursor rules).
#   4. Mirror shareable MCP servers from Cursor into Codex/Claude (best-effort).
#   5. Run the capabilities MCP bootstrap (clone kp-mcp if missing + uv sync; stops at OAuth).
#   6. Ensure the ecosystem orchestrator is present for lockkit/consistency wrappers.
#   7. Surface this repo's /dev-* skills to Cursor/Codex/Claude.
#   8. Run the read-only verify check.
#
# New machine:  git clone git@github.com:KleinPerkins/dev.git ~/dev && cd ~/dev && bash bootstrap.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$ROOT"

# Personal setup must dispatch before *any* legacy installer or host mutation.
# This lane reconstructs allowlisted sources and reports owner-gated capabilities;
# it never falls through to the work-machine bootstrap on an error.
if [ "${1:-}" = "--profile" ]; then
  case "${2:-}" in
    personal|personal-codex)
      shift 2
      exec env PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/_ops/portability/engine.py" "$@"
      ;;
    *)
      echo "[bootstrap] ERROR: supported explicit profile: personal-codex" >&2
      exit 2
      ;;
  esac
fi
if [ "$#" -gt 0 ]; then
  echo "[bootstrap] ERROR: use --profile personal-codex followed by a personal operation" >&2
  exit 2
fi

verify_bootstrap_source() {
  env PYTHONDONTWRITEBYTECODE=1 python3 \
    "$ROOT/_ops/interoperability/original_sources.py" KleinPerkins/skills --checkout "$1" >/dev/null
}
# The overlay may select another original Skills checkout. Qualify that actual
# source before any capability can run, rather than trusting a path override.
if [ -n "${DEV_AWA_SKILLS_ROOT:-}" ]; then
  verify_bootstrap_source "$DEV_AWA_SKILLS_ROOT" || exit 78
fi

echo "[bootstrap] 1/8 — capabilities skills hub"
capabilities_rc=0
if [ -f "$ROOT/capabilities/bootstrap.sh" ]; then
  # Select external ownership at the first possible SSP invocation. Guard the command explicitly:
  # top-level set -e must not prevent the transaction barrier below from resolving AWA host state.
  AWA_HOOK_OWNER=external \
  AWA_POLICY="$ROOT/_ops/policy/worktree-policy.yml" \
  AWA_GOVERNED_ROOT="$ROOT" \
    bash "$ROOT/capabilities/bootstrap.sh" || capabilities_rc=$?
else
  echo "[bootstrap] FATAL: capabilities/bootstrap.sh not present" >&2
  capabilities_rc=78
fi

# A pre-use source refusal means no capability was executed. The overlay must
# not execute the same rejected Skills source. Ordinary reconcile failures still
# reach the repair barrier below after any partial capability changes.
if [ "$capabilities_rc" -eq 78 ]; then
  echo "[bootstrap] source checkout refused before use; existing host state preserved" >&2
  exit 78
fi

# Recheck the actual overlay source immediately before its separate use. Source
# changes during reconciliation are preserved, never executed as repair code.
verify_bootstrap_source "${DEV_AWA_SKILLS_ROOT:-$ROOT/capabilities/skills}" || exit 78

echo "[bootstrap] 2/8 — AWA external runtime + Dev host-hook transaction barrier"
# Capabilities may install AWA and then fail on unrelated work. Always resolve the complete Dev
# overlay exactly once before any later bootstrap step. Overlay failure takes exit precedence;
# capabilities failure is returned only after AWA reaches a complete or honestly deferred state.
overlay_rc=0
if [ -x "$ROOT/_ops/bin/install-dev-awa-overlay.sh" ]; then
  bash "$ROOT/_ops/bin/install-dev-awa-overlay.sh" || overlay_rc=$?
else
  echo "[bootstrap] FATAL: install-dev-awa-overlay.sh not present/executable" >&2
  overlay_rc=1
fi
if [ "$overlay_rc" -ne 0 ]; then exit "$overlay_rc"; fi
if [ "$capabilities_rc" -ne 0 ]; then exit "$capabilities_rc"; fi

echo "[bootstrap] 3/8 — agent rules (Cursor/Codex/Claude)"
bash "$ROOT/_ops/bin/install-agent-rules.sh"

echo "[bootstrap] 4/8 — MCP mirror (Cursor -> Codex/Claude)"
if [ "${ECO_BOOTSTRAP_OFFLINE:-0}" = 1 ]; then
  echo "[bootstrap] (offline) skip MCP mirror"
else
  mirror_rc=0
  bash "$ROOT/_ops/bin/install-mcp.sh" || mirror_rc=$?
  if [ "$mirror_rc" -eq 73 ]; then
    echo "[bootstrap] MCP handoff refused; later writers were not started" >&2
    exit "$mirror_rc"
  elif [ "$mirror_rc" -ne 0 ]; then
    echo "[bootstrap] WARN: install-mcp.sh returned non-zero (continuing)"
  fi
fi

echo "[bootstrap] 5/8 — capabilities MCP bootstrap (kp-mcp + uv sync; stops at OAuth)"
if [ "${ECO_BOOTSTRAP_OFFLINE:-0}" = 1 ]; then
  echo "[bootstrap] (offline) skip MCP clone/sync (network)"
elif [ -f "$ROOT/capabilities/mcp-bootstrap.sh" ]; then
  lifecycle_rc=0
  bash "$ROOT/capabilities/mcp-bootstrap.sh" || lifecycle_rc=$?
  if [ "$lifecycle_rc" -eq 73 ]; then
    echo "[bootstrap] MCP lifecycle handoff refused; later steps were not started" >&2
    exit "$lifecycle_rc"
  elif [ "$lifecycle_rc" -ne 0 ]; then
    echo "[bootstrap] WARN: capabilities/mcp-bootstrap.sh returned non-zero (continuing)"
  fi
else
  echo "[bootstrap] (skip) capabilities/mcp-bootstrap.sh not present"
fi

echo "[bootstrap] 6/8 — ecosystem orchestrator (lockkit + consistency)"
ORCH_DIR="$ROOT/personal/ecosystem-orchestrator"
if [ -d "$ORCH_DIR/.git" ]; then
  echo "[bootstrap] orchestrator present: $ORCH_DIR"
elif [ "${ECO_BOOTSTRAP_OFFLINE:-0}" = 1 ]; then
  echo "[bootstrap] WARN: orchestrator missing; offline mode degrades eco-lockkit-* and eco-consistency wrappers"
else
  echo "[bootstrap] cloning KleinPerkins/ecosystem-orchestrator -> $ORCH_DIR"
  mkdir -p "$(dirname "$ORCH_DIR")"
  if command -v gh >/dev/null 2>&1; then
    gh repo clone KleinPerkins/ecosystem-orchestrator "$ORCH_DIR" || echo "[bootstrap] WARN: orchestrator clone failed; eco-lockkit-* and eco-consistency wrappers degraded"
  else
    git clone git@github.com:KleinPerkins/ecosystem-orchestrator.git "$ORCH_DIR" || echo "[bootstrap] WARN: orchestrator clone failed; eco-lockkit-* and eco-consistency wrappers degraded"
  fi
fi

echo "[bootstrap] 7/8 — /dev-* skills"
bash "$ROOT/_ops/bin/install-skills.sh"

echo "[bootstrap] 8/8 — verify"
bash "$ROOT/_ops/checks/verify-operating-model.sh"

echo "[bootstrap] done."
