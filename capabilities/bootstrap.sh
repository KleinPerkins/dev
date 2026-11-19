#!/usr/bin/env bash
# ~/dev/capabilities/bootstrap.sh — set up the capability skills hub on a new machine.
#
# STATUS: ACTIVE. Idempotent and conservative:
#   - never clobbers a real directory,
#   - never pushes to any remote.
#
# What it does:
#   1. Clone the global capabilities skills repo to ~/dev/capabilities/skills (if missing).
#   2. (Re)create the per-tool symlinks that point Cursor/Claude/Codex at the global skills.
#
# Repo scope is DECIDED: the global skills live in the PRIVATE repo KleinPerkins/skills
#   (git@github.com:KleinPerkins/skills.git); the home operating model lives in KleinPerkins/dev.
#   See ~/dev/OPERATING-MANUAL.md (§4 + the "Home operating model" section).
#
# Usage:  bash bootstrap.sh        (override CAP_SKILLS_REPO_URL=... only if ever needed)
#         bash bootstrap.sh --codex-skill-migration preview|apply|verify|rollback ...
#         bash bootstrap.sh --codex-imported-skill-isolation preview|apply|verify|rollback ...

set -euo pipefail

CAP_SKILLS_REPO_URL="${CAP_SKILLS_REPO_URL:-}"
# Derive paths from THIS script's location so it runs anywhere (e.g. a clean-room clone), not just ~/dev.
CAP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
DEV_ROOT="$(cd "$CAP_ROOT/.." && pwd)"
SKILLS_DIR="$CAP_ROOT/skills"
GLOBAL_DIR="$SKILLS_DIR/global"
LOCAL_DIR="$SKILLS_DIR/local"
SHELVES="skills rules sub-agents tools"

# Per-tool exposure (intentional; Cursor is the complete hub). name -> tool dirs.
# Each curated list mixes global- and local-scope skills — exposure is independent
# of orchestrator->cpp eligibility (which is determined solely by global/ vs local/).
CURSOR_SKILLS=(agent-route prompt-architect frontend-design session-close update-skills)
CLAUDE_SKILLS=(agent-route session-close update-skills)
CODEX_SKILLS=(agent-route frontend-design)

log() { printf '[bootstrap] %s\n' "$*"; }

# INT-008 is a deliberately separate, fixed-allowlist transaction.  Dispatch it
# before clone detection, Skills bootstrap delegation, or any broad reconcile /
# prune path so a required-skill migration cannot mutate unrelated capabilities.
if [ "${1:-}" = "--codex-skill-migration" ]; then
  if [ $# -lt 2 ]; then
    log "ERROR: --codex-skill-migration requires preview|apply|verify|rollback"
    exit 2
  fi
  migration_operation="$2"
  shift 2
  case "$migration_operation" in
    preview|apply|verify|rollback) ;;
    *)
      log "ERROR: unsupported Codex skill migration operation '$migration_operation'"
      exit 2 ;;
  esac
  exec env PYTHONDONTWRITEBYTECODE=1 python3 \
    "$DEV_ROOT/_ops/interoperability/skill_migration.py" "$migration_operation" "$@"
fi

# The remaining INT-008 imported-utility disposition is a second, disjoint
# transaction. It can only append exact path-specific disable rows for the
# three reviewed SKILL.md selectors. Dispatch before clone/reconcile so this
# bounded config operation never invokes broad capability management.
if [ "${1:-}" = "--codex-imported-skill-isolation" ]; then
  if [ $# -lt 2 ]; then
    log "ERROR: --codex-imported-skill-isolation requires preview|apply|verify|rollback"
    exit 2
  fi
  isolation_operation="$2"
  shift 2
  case "$isolation_operation" in
    preview|apply|verify|rollback) ;;
    *)
      log "ERROR: unsupported Codex imported-skill isolation operation '$isolation_operation'"
      exit 2 ;;
  esac
  exec env PYTHONDONTWRITEBYTECODE=1 python3 \
    "$DEV_ROOT/_ops/interoperability/imported_skill_isolation.py" "$isolation_operation" "$@"
fi

RESET_LOCAL_CONFIG=0
for arg in "$@"; do
  case "$arg" in
    --reset-local-config) RESET_LOCAL_CONFIG=1 ;;
  esac
done

capability_local_helper() {
  if [ -f "$SKILLS_DIR/scripts/capability-local.py" ]; then
    printf '%s\n' "$SKILLS_DIR/scripts/capability-local.py"
  fi
}

reset_local_config_if_requested() {
  [ "$RESET_LOCAL_CONFIG" = "1" ] || return 0
  local helper
  helper="$(capability_local_helper || true)"
  if [ -z "$helper" ]; then
    log "ERROR: --reset-local-config requested but capability-local.py is unavailable"
    return 1
  fi
  log "reset  machine-local capability opt-out registry"
  python3 "$helper" reset
}

skills_bootstrap_supports_reset() {
  [ -f "$SKILLS_DIR/bootstrap.sh" ] || return 1
  grep -q -- '--reset-local-config' "$SKILLS_DIR/bootstrap.sh"
}

# 1. Clone if the skills repo is missing (never clobber an existing real dir).
if [ -e "$SKILLS_DIR/.git" ]; then
  python3 "$DEV_ROOT/_ops/interoperability/original_sources.py" KleinPerkins/skills --repository "$SKILLS_DIR" >/dev/null
  log "skills repo already present at $SKILLS_DIR (leaving as-is)"
elif [ -e "$SKILLS_DIR" ]; then
  log "REFUSING: $SKILLS_DIR exists but is not a git repo; not clobbering. Resolve manually."
  exit 1
else
  if [ -z "$CAP_SKILLS_REPO_URL" ]; then
    CAP_SKILLS_REPO_URL="$(python3 "$DEV_ROOT/_ops/interoperability/original_sources.py" KleinPerkins/skills)"
  else
    python3 "$DEV_ROOT/_ops/interoperability/original_sources.py" KleinPerkins/skills --url "$CAP_SKILLS_REPO_URL" >/dev/null
  fi
  log "cloning $CAP_SKILLS_REPO_URL -> $SKILLS_DIR"
  git clone "$CAP_SKILLS_REPO_URL" "$SKILLS_DIR"
  python3 "$DEV_ROOT/_ops/interoperability/original_sources.py" KleinPerkins/skills --repository "$SKILLS_DIR" >/dev/null
fi

if [ -f "$SKILLS_DIR/bootstrap.sh" ]; then
  RESET_ARGS=()
  if [ "$RESET_LOCAL_CONFIG" = "1" ]; then
    if skills_bootstrap_supports_reset; then
      RESET_ARGS+=(--reset-local-config)
    else
      reset_local_config_if_requested || exit 1
    fi
  fi
  log "delegating shelf-aware surfacing to $SKILLS_DIR/bootstrap.sh --reconcile"
  # bash 3.2 + set -u: empty "${array[@]}" is an unbound-variable error on macOS.
  if [ ${#RESET_ARGS[@]} -gt 0 ]; then
    bash "$SKILLS_DIR/bootstrap.sh" --reconcile "${RESET_ARGS[@]}"
  else
    bash "$SKILLS_DIR/bootstrap.sh" --reconcile
  fi
  log "done. Run 'make verify' to assert the invariant."
  exit 0
fi

reset_local_config_if_requested || exit 1

# 2. (Re)link per-tool symlinks into the global repo. Idempotent: leaves a correct symlink
#    untouched, only ever replaces an existing symlink, and never deletes a real directory.
relink() {
  local target="$1" link="$2"
  if [ ! -e "$target" ]; then
    log "skip $link -> $target (target missing in repo)"; return
  fi
  if [ -L "$link" ]; then
    if [ "$(readlink "$link")" = "$target" ]; then
      return   # already correct — idempotent no-op
    fi
    rm -f "$link"
  elif [ -e "$link" ]; then
    log "skip $link (real path exists — not clobbering)"; return
  fi
  mkdir -p "$(dirname "$link")"
  ln -s "$target" "$link"
  log "linked $link -> $target"
}

# meta.yml reader (flat key: value; require a space before an inline # so values keep a literal '#').
meta_get() { awk -v k="$2" '/^[[:space:]]*#/{next}{l=$0;sub(/[[:space:]]+#.*$/,"",l);if(match(l,/^[A-Za-z0-9_]+:[[:space:]]*/)){key=l;sub(/:.*$/,"",key);if(key==k){v=l;sub(/^[A-Za-z0-9_]+:[[:space:]]*/,"",v);gsub(/^"|"$/,"",v);print v;exit}}}' "$1"; }
in_list() { local n="$1"; shift; local x; for x in "$@"; do [ "$x" = "$n" ] && return 0; done; return 1; }

# Manifest-aware Flavor-1 exposure: iterate EVERY skill under global/ AND local/. Honor an optional
# `expose:` list (space-separated cursor/claude/codex) in meta.yml; otherwise fall back to the
# curated default maps above; warn on a skill exposed nowhere (so a newly-added skill is never
# silently invisible). Local-scope skills are still exposed to tools — only orchestrator->cpp
# vendoring eligibility differs between global/ and local/.
expose_scope_dir() {
  local scope_dir="$1"
  [ -d "$scope_dir" ] || return 0
  local d s expose tool shelf kind
  for shelf in $SHELVES; do
  for d in "$scope_dir/$shelf"/*/; do
    [ -d "$d" ] || continue
    [ -f "${d}meta.yml" ] || continue
    kind="$(meta_get "${d}meta.yml" kind)"
    [ "$kind" = "skill" ] || continue
    s="$(basename "${d%/}")"
    expose="$(meta_get "${d}meta.yml" expose)"
    if [ -n "$expose" ]; then
      for tool in $expose; do case "$tool" in
        cursor) relink "$d" "$HOME/.cursor/skills/$s" ;;
        claude) relink "$d" "$HOME/.claude/skills/$s" ;;
        codex)  relink "$d" "$HOME/.codex/skills/$s" ;;
        *) log "WARN: $s meta.yml expose lists unknown tool '$tool'" ;;
      esac; done
    else
      in_list "$s" "${CURSOR_SKILLS[@]}" && relink "$d" "$HOME/.cursor/skills/$s"
      in_list "$s" "${CLAUDE_SKILLS[@]}" && relink "$d" "$HOME/.claude/skills/$s"
      in_list "$s" "${CODEX_SKILLS[@]}"  && relink "$d" "$HOME/.codex/skills/$s"
      in_list "$s" "${CURSOR_SKILLS[@]}" || in_list "$s" "${CLAUDE_SKILLS[@]}" || in_list "$s" "${CODEX_SKILLS[@]}" || \
        log "NOTE: skill '$s' is exposed to no tool (add an expose: line to its meta.yml or the curated map)"
    fi
  done
  done
}
expose_scope_dir "$GLOBAL_DIR"
expose_scope_dir "$LOCAL_DIR"

# 3. Manifest-driven pass (reorg-v2 WS-1/WS-2): the per-tool relink above handles Flavor-1 symlink
#    exposure; here we read each artifact's meta.yml and run its install.sh for anything that needs
#    post-management (post_mgmt != none) or is a Flavor-2 pointer (clone/pull). Idempotent. Covers
#    both global/ and local/ subtrees.
ECO_MANIFEST="$DEV_ROOT/_ops/eco/manifest.sh"
if [ -x "$ECO_MANIFEST" ] || [ -f "$ECO_MANIFEST" ]; then
  for scope_dir in "$GLOBAL_DIR" "$LOCAL_DIR"; do
    [ -d "$scope_dir" ] || continue
    for shelf in $SHELVES; do
    for d in "$scope_dir/$shelf"/*/; do
      [ -f "${d}meta.yml" ] || continue
      flavor="$(meta_get "${d}meta.yml" flavor)"; post="$(meta_get "${d}meta.yml" post_mgmt)"
      if [ "$flavor" = "2" ] || { [ -n "$post" ] && [ "$post" != "none" ]; }; then
        if [ -x "${d}install.sh" ]; then
          log "manifest install (flavor=$flavor post_mgmt=$post): $(basename "${d%/}")"
          bash "${d}install.sh" >/dev/null 2>&1 || log "WARN: install.sh non-zero for $(basename "${d%/}") (continuing)"
        fi
      fi
    done
    done
  done
else
  log "(skip) manifest pass — _ops/eco/manifest.sh not found"
fi

log "done. Run 'make verify' to assert the invariant."
