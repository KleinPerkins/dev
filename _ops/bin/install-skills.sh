#!/usr/bin/env bash
# _ops/bin/install-skills.sh — surface the repo's /dev-* skills to Cursor / Claude / Codex (N1).
#
# Mirrors the discovery convention the workspace already uses (capabilities/bootstrap.sh relink):
# the skills live in-repo under _ops/skills/<name>/SKILL.md (cpp-style) and are exposed by an
# idempotent, NON-CLOBBERING symlink into each tool's skills dir. Nothing here is tracked; the
# symlinks live under ~/.cursor /.claude /.codex, like the agent-rule symlink.
#
# Usage:  _ops/bin/install-skills.sh   (or: make install-skills)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # _ops/bin
SKILLS_DIR="$(cd "$SCRIPT_DIR/../skills" && pwd)"               # _ops/skills

# Which /dev-* skills go to which tools. Cursor is the complete hub; the action skills are
# useful in all three tools an agent might land in.
DEV_SKILLS=(dev-doctor dev-new-repo dev-remove-repo doc-warden)
CURSOR_SKILLS=(dev-doctor dev-new-repo dev-remove-repo doc-warden)
CLAUDE_SKILLS=(dev-doctor dev-new-repo dev-remove-repo doc-warden)
CODEX_SKILLS=(dev-doctor dev-new-repo dev-remove-repo doc-warden)

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
