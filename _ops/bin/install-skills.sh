#!/usr/bin/env bash
# _ops/bin/install-skills.sh — surface the repo's /dev-* skills to Cursor / Claude / Codex (N1).
#
# Mirrors the discovery convention the workspace already uses (capabilities/bootstrap.sh relink):
# the skills live in-repo under _ops/skills/<name>/SKILL.md (cpp-style) and are exposed by an
# idempotent, NON-CLOBBERING symlink into each tool's skills dir. Nothing here is tracked; the
# symlinks live under ~/.cursor /.claude /.codex, like the agent-rule symlink.
#
# Usage:  _ops/bin/install-skills.sh [--only doc-warden | --personal-codex dev-doctor]   (or: make install-skills)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # _ops/bin
SKILLS_DIR="$(cd "$SCRIPT_DIR/../skills" && pwd)"               # _ops/skills

# A personal Codex caller uses the scoped doctor and preserves existing client slots.
if [ "${1:-}" = "--personal-codex" ]; then
  if [ "$#" -ne 2 ] || [ "$2" != "dev-doctor" ]; then
    printf 'usage: install-skills.sh --personal-codex dev-doctor\n' >&2
    exit 2
  fi
  python3 -I -B "$SCRIPT_DIR/link-personal-codex-skill.py" "$SKILLS_DIR/personal/$2" "${CODEX_HOME:-$HOME/.codex}/skills/$2"
  exit 0
fi

# Which /dev-* skills go to which tools. Cursor is the complete hub; the action skills are
# useful in all three tools an agent might land in.
DEV_SKILLS=(dev-doctor dev-new-repo dev-remove-repo doc-warden)
CURSOR_SKILLS=(dev-doctor dev-new-repo dev-remove-repo doc-warden)
CLAUDE_SKILLS=(dev-doctor dev-new-repo dev-remove-repo doc-warden)
CODEX_SKILLS=(dev-doctor dev-new-repo dev-remove-repo doc-warden)
if [ "$#" -ne 0 ]; then
  if [ "$#" -ne 2 ] || [ "$1" != "--only" ] || [ "$2" != "doc-warden" ]; then
    printf 'usage: install-skills.sh [--only doc-warden | --personal-codex dev-doctor]\n' >&2
    exit 2
  fi
  DEV_SKILLS=(doc-warden)
  CURSOR_SKILLS=(doc-warden)
  CLAUDE_SKILLS=(doc-warden)
  CODEX_SKILLS=(doc-warden)
fi

log() { printf '[install-skills] %s\n' "$*"; }

# relink <target> <link> — idempotent; leaves a correct symlink untouched, only replaces an
# existing symlink, and never deletes/overwrites a real directory.
relink() {
  local target="$1" link="$2"
  if [ ! -e "$target" ]; then log "skip $link -> $target (target missing)"; return; fi
  if [ -L "$link" ]; then
    if [ "$(readlink "$link")" = "$target" ]; then return; fi
    rm -f "$link"
  elif [ -e "$link" ]; then
    log "skip $link (real path exists — not clobbering)"; return
  fi
  mkdir -p "$(dirname "$link")"
  ln -s "$target" "$link"
  log "linked $link -> $target"
}

for s in "${CURSOR_SKILLS[@]}"; do relink "$SKILLS_DIR/$s" "$HOME/.cursor/skills/$s"; done
for s in "${CLAUDE_SKILLS[@]}"; do relink "$SKILLS_DIR/$s" "$HOME/.claude/skills/$s"; done
for s in "${CODEX_SKILLS[@]}";  do relink "$SKILLS_DIR/$s" "$HOME/.codex/skills/$s"; done

log "done (${#DEV_SKILLS[@]} skills: ${DEV_SKILLS[*]}). Re-run anytime; idempotent."
