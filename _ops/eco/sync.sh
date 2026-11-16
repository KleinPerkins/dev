#!/usr/bin/env bash
# _ops/eco/sync.sh — 3-mode sync/refresh engine (reorg-v2 WS-3 / D-12, DD-5).
#
# Modes (scope = a bootstrap-managed root; in-scope = entries under the root not in the source set):
#   repair  (default)  non-destructive: add only MISSING declared entries. Never overwrites/deletes.
#   replace            backup out-of-tree FIRST, then add missing + overwrite DRIFTED (non-byte-identical).
#                      Never deletes undeclared entries.
#   rebuild            replace + DELETE in-scope undeclared entries. Requires backup + --confirm + the
#                      .eco-managed sentinel (so a shared dir can never be nuked).
#
# Two forms:
#   sync.sh <mode> --from <src> --to <root> [--confirm]   mirror a source into a managed root
#   sync.sh repair                                          safe local refresh (re-run bootstrap + verify)
#
# The mirror core (_eco_mirror) is reused by the orchestrator to build cpp vendored payloads.
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib.sh
. "$SELF_DIR/lib.sh"

MODE="${1:-repair}"; shift || true
FROM=""; TO=""; CONFIRM=0
while [ $# -gt 0 ]; do case "$1" in
  --from) shift; FROM="${1:-}" ;;
  --to)   shift; TO="${1:-}" ;;
  --confirm) CONFIRM=1 ;;
  -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
  *) eco_err "sync: unknown arg $1"; exit 2 ;;
esac; shift; done
case "$MODE" in repair|replace|rebuild) : ;; *) eco_err "mode must be repair|replace|rebuild"; exit 2 ;; esac
# Normalize: strip a trailing slash so rel-path stripping can't misfire. A trailing-slash --to
# previously made rebuild compute every file as "undeclared" and delete the entire mirror.
FROM="${FROM%/}"; TO="${TO%/}"

# _eco_mirror <src> <dst> <mode> <confirm> — the reusable reconciler.
_eco_mirror() {
  local src="$1" dst="$2" mode="$3" confirm="$4"
  src="${src%/}"; dst="${dst%/}"                 # defensive: a trailing slash breaks rel-stripping
  [ -d "$src" ] || { eco_err "source not a dir: $src"; return 2; }

  if [ "$mode" = replace ] || [ "$mode" = rebuild ]; then
    # Resolve dst to an absolute path for the scope guards.
    local dstabs; dstabs="$(cd "$(dirname "$dst")" 2>/dev/null && printf '%s/%s\n' "$PWD" "$(basename "$dst")")"; dstabs="${dstabs:-$dst}"
    # Scope guard: an IN-REPO destructive target MUST sit under a configured managed root, so a
    # destructive sync can never nuke repo control files or an arbitrary in-repo directory. Out-of-repo
    # scratch dirs (tests, orchestrator payload builds) are allowed (sentinel + backup still apply).
    if [ "${ECO_SYNC_ALLOW_ANY_ROOT:-0}" != 1 ] && eco_is_in_managed_tree "$dstabs" && ! eco_under_managed_root "$dstabs"; then
      eco_err "refusing $mode: $dst is inside the repo but not under a managed root (override: ECO_SYNC_ALLOW_ANY_ROOT=1)"; return 3
    fi
    # Never mutate a nested git repo through a destructive sync.
    if [ -e "$dst/.git" ]; then eco_err "refusing $mode: $dst contains a nested .git (won't mutate a nested repo)"; return 3; fi
    # Per-dir bless marker: refuse to touch an EXISTING dir that was never explicitly blessed managed.
    if [ -e "$dst" ] && [ ! -f "$dst/.eco-managed" ]; then
      eco_err "refusing $mode: $dst has no .eco-managed sentinel (safety: won't touch an unmanaged dir)"; return 3
    fi
    if [ "$mode" = rebuild ] && [ "$confirm" != 1 ]; then
      eco_err "rebuild is destructive (deletes undeclared in-scope files): re-run with --confirm"; return 3
    fi
    # Out-of-tree backup is a HARD precondition: abort if it fails or can't be verified.
    if [ -d "$dst" ]; then
      local b
      if ! b="$(eco_backup_outoftree "$dst" "sync-${mode}-$(basename "$dst")")"; then
        eco_err "refusing $mode: out-of-tree backup FAILED for $dst (no mutation performed)"; return 4
      fi
      eco_log "backup (out-of-tree): $b"
    fi
  fi

  mkdir -p "$dst"
  # Plant the bless marker ONLY for destructive modes — never in repair, so a non-destructive refresh
  # can never silently bless a directory as managed (which would let a later rebuild delete it).
  if [ "$mode" != repair ]; then
    [ -f "$dst/.eco-managed" ] || printf 'source: %s\n' "$src" > "$dst/.eco-managed"
  fi

  local added=0 replaced=0 deleted=0 rel s d
  # add missing (+ replace drifted for replace/rebuild)
  while IFS= read -r s; do
    rel="${s#"$src"/}"
    d="$dst/$rel"
    if [ ! -e "$d" ]; then
      mkdir -p "$(dirname "$d")"; cp -p "$s" "$d"; added=$((added+1))
    elif [ "$mode" != repair ]; then
      if ! cmp -s "$s" "$d"; then cp -p "$s" "$d"; replaced=$((replaced+1)); fi
    fi
  done < <(find "$src" -type f 2>/dev/null)

  # rebuild: delete in-scope entries not present in source (preserve the sentinel)
  if [ "$mode" = rebuild ]; then
    while IFS= read -r d; do
      rel="${d#"$dst"/}"
      [ "$rel" = ".eco-managed" ] && continue
      [ -e "$src/$rel" ] || { rm -f "$d"; deleted=$((deleted+1)); }
    done < <(find "$dst" -type f 2>/dev/null)
    # prune now-empty dirs
    find "$dst" -type d -empty -delete 2>/dev/null || true
  fi

  eco_log "mirror($mode) $src -> $dst : +$added added, ~$replaced replaced, -$deleted deleted"
  return 0
}

# --- Form A: explicit source -> managed root ---
if [ -n "$FROM" ] || [ -n "$TO" ]; then
  [ -n "$FROM" ] && [ -n "$TO" ] || { eco_err "both --from and --to required for mirror mode"; exit 2; }
  _eco_mirror "$FROM" "$TO" "$MODE" "$CONFIRM"; exit $?
fi

# --- Form B: safe local refresh (no --to). Only 'repair' is allowed (destructive needs a target). ---
if [ "$MODE" != repair ]; then
  eco_err "$MODE without --to is unsafe; destructive modes require an explicit --to <managed root>"; exit 2
fi
eco_log "repair: refreshing local install state from masters"
if [ -f "$ECO_REPO_ROOT/capabilities/bootstrap.sh" ]; then
  bash "$ECO_REPO_ROOT/capabilities/bootstrap.sh" || eco_warn "capabilities/bootstrap.sh non-zero (continuing)"
fi
bash "$SELF_DIR/verify-manifests.sh" || { eco_err "manifest verification failed after repair"; exit 1; }
eco_log "repair: done"
