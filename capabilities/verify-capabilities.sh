#!/usr/bin/env bash
# verify-capabilities.sh — assert the capability dedup invariant holds.
#
# Invariant (see ~/dev/OPERATING-MANUAL.md §4):
#   - Home-policed Work/Affirm-shared skills are CANONICAL in ~/.cursor/skills as real
#     directories; every Claude/Codex copy of one of these is a SYMLINK into the Cursor
#     copy (never a second real directory). The home-policed set is the loop below:
#     affirm-app-setup, affirm-checkout-setup, affirm-design, latency.
#   - Skills in the KleinPerkins/skills repo live at
#     ~/dev/capabilities/skills/{global,local}/skills/<name>; every tool reference (Cursor/
#     Claude/Codex) is a SYMLINK into that repo. Global skills are eligible for
#     orchestrator->cpp vendoring; local skills are installed locally only.
#
# Excluded from home policing (cpp-surfaced; see OPERATING-MANUAL.md §4c):
#   # excluded: affirm-brand -- cpp-surfaced LINK/subscription wrapper (canonical = BOSS Notion)
#   # excluded: council      -- cpp-owned self-contained fork (cpp is the SOT)
#   # excluded: quickhost    -- cpp-owned fork (cpp is the SOT); not in the home loop anyway
# These three are surfaced into ~/.{cursor,claude,codex}/skills by cpp's _ops/bin/
# cpp-install-skills.sh and are NOT governed by this invariant.
#
# This script makes NO changes. It exits 0 if every expected entry is a resolving
# symlink and no un-deduped real-directory duplicate is found; otherwise exits 1.

set -u
CURSOR="$HOME/.cursor/skills"
CLAUDE="$HOME/.claude/skills"
CODEX="$HOME/.codex/skills"
GLOBAL="$HOME/dev/capabilities/skills/global"
LOCAL="$HOME/dev/capabilities/skills/local"
GLOBAL_SKILLS="$GLOBAL/skills"
LOCAL_SKILLS="$LOCAL/skills"

# Canonical resolved targets a tool-skill symlink may point at. Anything else (e.g. into
# cpp/quiver, a sibling project, /tmp, or a stale relocated path) is flagged: the symlink
# must resolve into the KleinPerkins/skills repo OR the Cursor canonical for home-policed
# Affirm-shared skills. Resolved-path prefixes (after `cd -P`) keep the check robust against
# `~` expansion and `/private/var/...` realpath rewrites on macOS.
ALLOWED_LINK_PREFIXES=()
[ -d "$GLOBAL" ] && ALLOWED_LINK_PREFIXES+=("$(cd -P "$GLOBAL" 2>/dev/null && pwd -P)")
[ -d "$LOCAL"  ] && ALLOWED_LINK_PREFIXES+=("$(cd -P "$LOCAL"  2>/dev/null && pwd -P)")
[ -d "$CURSOR" ] && ALLOWED_LINK_PREFIXES+=("$(cd -P "$CURSOR" 2>/dev/null && pwd -P)")

fail=0
pass() { printf "  PASS  %s\n" "$1"; }
warn() { printf "  WARN  %s\n" "$1"; }
bad()  { printf "  FAIL  %s\n" "$1"; fail=1; }

meta_exposes() {
  local meta="$1" e
  e="$(awk -F'expose:[[:space:]]*' '/^expose:/{print $2; exit}' "$meta" 2>/dev/null | tr -d '[]' | tr ',' ' ')"
  [ -n "$e" ] || e="cursor claude codex"
  printf '%s\n' "$e"
}

tool_dir_for() {
  case "$1" in
    cursor) printf '%s\n' "$CURSOR" ;;
    claude) printf '%s\n' "$CLAUDE" ;;
    codex) printf '%s\n' "$CODEX" ;;
    *) return 1 ;;
  esac
}

# chk_symlink <path> <label> [<extra_allowed_prefix>]
# A symlink must exist, resolve, AND point into one of the canonical prefixes above (plus an
# optional caller-supplied prefix when the call site has a tighter expectation than the global
# allow-list, e.g. "must resolve into the Cursor canonical specifically"). A stray target — e.g.
# into cpp/quiver/, a sibling project, /tmp, or a relocated dev tree — fails instead of passing,
# closing the silent-broken-symlink / wrong-target landmine that "is it a symlink at all" misses.
chk_symlink() {
  local p="$1" label="$2" extra="${3:-}"
  if [ ! -e "$p" ] && [ ! -L "$p" ]; then
    warn "$label: not present (skipped)"
    return
  fi
  if [ ! -L "$p" ]; then
    bad "$label is a REAL path (expected a symlink — dedup not applied)"
    return
  fi
  if [ ! -e "$p" ]; then
    bad "$label is a BROKEN symlink -> $(readlink "$p")"
    return
  fi
  # Resolve to a real path so realpath rewrites (e.g. macOS /var -> /private/var) line up.
  local target
  target="$(cd -P "$(dirname "$p")" 2>/dev/null && cd -P "$(readlink "$p")" 2>/dev/null && pwd -P)" || target=""
  if [ -z "$target" ]; then
    bad "$label: cannot resolve symlink target -> $(readlink "$p")"
    return
  fi
  local matched=0 pref
  for pref in "${ALLOWED_LINK_PREFIXES[@]}"; do
    [ -n "$pref" ] || continue
    case "$target/" in "$pref/"*) matched=1; break ;; esac
  done
  if [ "$matched" = 0 ] && [ -n "$extra" ]; then
    local epref; epref="$(cd -P "$extra" 2>/dev/null && pwd -P)"
    [ -n "$epref" ] && case "$target/" in "$epref/"*) matched=1 ;; esac
  fi
  if [ "$matched" = 1 ]; then
    pass "$label -> $(readlink "$p")"
  else
    bad "$label: symlink target NOT under an allowed prefix (got $(readlink "$p"))"
  fi
}

echo "== Claude skills that must symlink into the Cursor canonical (~/.cursor/skills) =="
# affirm-brand, council, quickhost are cpp-surfaced (see header excluded list / OPERATING-MANUAL §4c).
for s in affirm-app-setup affirm-checkout-setup affirm-design latency; do
  chk_symlink "$CLAUDE/$s" "claude/$s"
done

echo "== KleinPerkins/skills repo exposed skills must symlink into the repo =="
found_skill=0
for meta in "$GLOBAL_SKILLS"/*/meta.yml "$LOCAL_SKILLS"/*/meta.yml; do
  [ -f "$meta" ] || continue
  found_skill=1
  src="$(dirname "$meta")"
  s="$(basename "$src")"
  if [ -d "$src" ]; then pass "${src#"$HOME/dev/capabilities/skills/"} present"; else bad "${src#"$HOME/dev/capabilities/skills/"} MISSING"; fi
  # expose: none = kept in the repo, never installed locally (skills ADR 0007): no tool may link it.
  case " $(meta_exposes "$meta") " in
    *" none "*)
      linked=0
      for tdir in "$CURSOR" "$CLAUDE" "$CODEX"; do
        if [ -L "$tdir/$s" ] || [ -e "$tdir/$s" ]; then
          linked=1
          bad "$tdir/$s present but $s is expose: none (run ~/dev/capabilities/skills/bootstrap.sh --reconcile)"
        fi
      done
      [ "$linked" = 1 ] || pass "$s not installed locally (expose: none)"
      continue ;;
  esac
  for tool in $(meta_exposes "$meta"); do
    tdir="$(tool_dir_for "$tool" || true)"
    [ -n "$tdir" ] || { bad "$meta expose lists unknown tool '$tool'"; continue; }
    chk_symlink "$tdir/$s" "$tool/$s"
  done
done
[ "$found_skill" = 1 ] || bad "no skill meta.yml files found under global|local/skills/"

echo "== No un-deduped real-directory duplicates in Claude/Codex (excluding Claude-managed extras) =="
# Any real dir in ~/.claude/skills or ~/.codex/skills whose name also exists as a real
# canonical in ~/.cursor/skills is a dedup violation. (.system is Codex-managed; allowed.)
for base in "$CLAUDE" "$CODEX"; do
  [ -d "$base" ] || continue
  for entry in "$base"/*; do
    [ -e "$entry" ] || continue
    name="$(basename "$entry")"
    [ "$name" = ".system" ] && continue
    if [ -d "$entry" ] && [ ! -L "$entry" ]; then
      if [ -d "$CURSOR/$name" ] && [ ! -L "$CURSOR/$name" ]; then
        bad "$base/$name is a REAL dir duplicating canonical ~/.cursor/skills/$name"
      else
        warn "$base/$name is a real dir (no Cursor canonical; tool-local — review)"
      fi
    fi
  done
done

echo
if [ "$fail" -eq 0 ]; then
  echo "verify-capabilities: OK (all expected entries are resolving symlinks; no dedup violations)"
else
  echo "verify-capabilities: FAILED (see FAIL lines above)"
fi
exit "$fail"
