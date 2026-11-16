#!/usr/bin/env bash
# _ops/bin/install-agent-rules.sh — install the ~/dev operating-model context into every
# AI tool, idempotently and without ever clobbering unrelated content.
#
#   Cursor : symlink ~/.cursor/rules/dev-operating-model.mdc -> repo .mdc
#   Codex  : inject/update a managed block in ~/.codex/AGENTS.md
#   Claude : inject/update a managed block in ~/.claude/CLAUDE.md (created if missing)
#
# Single source: _ops/rules/agent-context.md. The Cursor .mdc is regenerated from it when
# stale. A second run with nothing changed writes nothing (idempotent).
#
# Usage: _ops/bin/install-agent-rules.sh   (or: make install-rules)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"

RULES_HOME="${OM_RULES_HOME:-$HOME}"
CURSOR_RULES_DIR="$RULES_HOME/.cursor/rules"
OM_CURSOR_RULES_DIR="$CURSOR_RULES_DIR"
CURSOR_LINK="$CURSOR_RULES_DIR/dev-operating-model.mdc"
CODEX_FILE="$RULES_HOME/.codex/AGENTS.md"
CLAUDE_FILE="$RULES_HOME/.claude/CLAUDE.md"

# INT-007B is an explicit bounded instruction operation, separate from full rollout.
if [ "${1:-}" = "--codex-native" ]; then
  shift
  exec python3 "$OM_OPS_DIR/interoperability/native_rules.py" "$@"
fi
# Existing native selection is preserved while the other hosts reconcile normally.
NATIVE_CODEX=0
if [ -f "$CODEX_FILE" ] && grep -qF 'native-entry-routing/v1' "$CODEX_FILE"; then
  NATIVE_CODEX=1
fi

changed=0
log()    { printf '[install-agent-rules] %s\n' "$*"; }
mark()   { changed=1; }

# Modes: (no args) full install; --gen-only just (re)generates the Cursor .mdc from the SOT.
GEN_ONLY=0
case "${1:-}" in
  --gen-only)        GEN_ONLY=1 ;;
  ""|--all|--full)   GEN_ONLY=0 ;;
  -h|--help)         sed -n '2,15p' "$0"; exit 0 ;;
  *) log "unknown argument: '$1' (use --gen-only or no args)"; exit 2 ;;
esac

if [ "$GEN_ONLY" -eq 0 ] && [ -f "$CODEX_FILE" ] && grep -qF 'codex-work-dispatch/v1' "$CODEX_FILE"; then
  log "personal Codex work profile selected; broad install refused before mutation; use an exact --codex-native operation"
  exit 1
fi

[ -f "$OM_AGENT_CONTEXT" ] || { log "FATAL: missing $OM_AGENT_CONTEXT"; exit 1; }

# ---------------------------------------------------------------------------
# 1) (Re)generate the Cursor .mdc from agent-context.md, only if it drifted.
# ---------------------------------------------------------------------------
gen_tmp="$(mktemp)"
om_gen_mdc > "$gen_tmp"
if [ -f "$OM_MDC" ] && cmp -s "$gen_tmp" "$OM_MDC"; then
  rm -f "$gen_tmp"
  log "cursor rule source up to date: $OM_MDC"
else
  mv "$gen_tmp" "$OM_MDC"
  log "regenerated cursor rule source from agent-context.md: $OM_MDC"
  mark
fi

if [ "$GEN_ONLY" -eq 1 ]; then
  if [ "$changed" -eq 0 ]; then log "--gen-only: .mdc already current."; else log "--gen-only: regenerated .mdc."; fi
  exit 0
fi

# The replacement subagent policy is load-bearing for the full install. Validate
# its rule + single catalog before touching installed links, so retirement can
# never leave a fresh machine with neither policy.
SUBAGENT_RULE_DIR="$OM_CAPABILITY_RULES_DIR/subagent-orchestration"
for required in \
  "$SUBAGENT_RULE_DIR/subagent-orchestration.mdc" \
  "$SUBAGENT_RULE_DIR/model-tiers.json" \
  "$SUBAGENT_RULE_DIR/verify_model_tiers.py"; do
  [ -f "$required" ] || { log "FATAL: required subagent policy artifact missing: $required"; exit 1; }
done
python3 "$SUBAGENT_RULE_DIR/verify_model_tiers.py" >/dev/null || {
  log "FATAL: shared subagent model-tier catalog is invalid"
  exit 1
}

# ---------------------------------------------------------------------------
# 2) Cursor: absolute symlink into the repo .mdc.
# ---------------------------------------------------------------------------
mkdir -p "$CURSOR_RULES_DIR"
if [ -L "$CURSOR_LINK" ]; then
  if [ "$(readlink "$CURSOR_LINK")" = "$OM_MDC" ]; then
    log "cursor: symlink already current ($CURSOR_LINK)"
  else
    ln -sfn "$OM_MDC" "$CURSOR_LINK"; log "cursor: relinked $CURSOR_LINK -> $OM_MDC"; mark
  fi
elif [ -e "$CURSOR_LINK" ]; then
  bak="$CURSOR_LINK.bak.$(date +%Y%m%d%H%M%S)"
  mv "$CURSOR_LINK" "$bak"
  ln -s "$OM_MDC" "$CURSOR_LINK"
  log "cursor: backed up pre-existing real file -> $bak; linked $CURSOR_LINK -> $OM_MDC"; mark
else
  ln -s "$OM_MDC" "$CURSOR_LINK"; log "cursor: linked $CURSOR_LINK -> $OM_MDC"; mark
fi

# ---------------------------------------------------------------------------
# 2b) Cursor: deploy every versioned GLOBAL rule (home rules + reusable rule capabilities)
#     as symlinks into ~/.cursor/rules, so the cross-tool mirror (step 3) has a reproducible
#     source on a fresh machine. Bootstrap ensures the skills hub exists before this runs.
#     Idempotent: a correct symlink is left alone; a byte-identical real file is adopted in
#     place (no .bak); anything else is backed up before linking. Stale symlinks that point
#     into either managed source are pruned after their source is retired.
# ---------------------------------------------------------------------------
rule_is_desired() {
  local candidate="$1" source
  while IFS= read -r source; do
    [ -n "$source" ] || continue
    [ "$(basename "$source")" = "$candidate" ] && return 0
  done <<EOF
$(om_list_global_rules)
EOF
  return 1
}

while IFS= read -r sot; do
  [ -n "$sot" ] || continue
  link="$CURSOR_RULES_DIR/$(basename "$sot")"
  name="$(basename "$sot" .mdc)"
  if [ -L "$link" ] && [ "$(readlink "$link")" = "$sot" ]; then
    continue
  elif [ -e "$link" ] && [ ! -L "$link" ] && cmp -s "$link" "$sot"; then
    ln -sfn "$sot" "$link"; log "cursor: adopted identical real file -> global SOT symlink ($name)"; mark
  elif [ -e "$link" ] || [ -L "$link" ]; then
    bak="$link.bak.$(date +%Y%m%d%H%M%S)"; mv "$link" "$bak"; ln -s "$sot" "$link"
    log "cursor: backed up $name -> $(basename "$bak"); linked to global SOT"; mark
  else
    ln -s "$sot" "$link"; log "cursor: linked global rule $name -> managed SOT"; mark
  fi
done <<EOF
$(om_list_global_rules)
EOF

for link in "$CURSOR_RULES_DIR"/*.mdc; do
  [ -L "$link" ] || continue
  target="$(readlink "$link")"
  case "$target" in
    "$OM_GLOBAL_RULES_DIR"/*|"$OM_CAPABILITY_RULES_DIR"/*)
      if ! rule_is_desired "$(basename "$link")"; then
        rm -f "$link"
        log "cursor: pruned retired global rule $(basename "$link" .mdc)"
        mark
      fi
      ;;
  esac
done

gr_n="$(om_list_global_rules | wc -l | tr -d ' ')"
[ "${gr_n:-0}" -gt 0 ] && log "cursor: $gr_n versioned global rule(s) in sync"

# ---------------------------------------------------------------------------
# 3) Codex / Claude: idempotent managed-block injection (never clobber other content).
#    Three managed blocks are kept, ALWAYS in this fixed order so re-runs are stable:
#      (a) dev-operating-model    — the home context (SOT = agent-context.md)
#      (b) cursor-rules-mirror    — the alwaysApply Cursor behavioral rules (omitted if none)
#      (c) cursor-mcp-safety-mirror — the *-mcp-safety conditional guardrails (omitted if none)
# ---------------------------------------------------------------------------
# Strip ALL managed blocks from a file and trim trailing blank lines -> stdout.
strip_managed_blocks() {
  awk -v b1="$OM_BLOCK_BEGIN"       -v e1="$OM_BLOCK_END" \
      -v b2="$OM_RULES_BLOCK_BEGIN" -v e2="$OM_RULES_BLOCK_END" \
      -v b3="$OM_MCP_RULES_BLOCK_BEGIN" -v e3="$OM_MCP_RULES_BLOCK_END" '
    index($0,b1){inblk=1; next}
    index($0,e1){inblk=0; next}
    index($0,b2){inblk=1; next}
    index($0,e2){inblk=0; next}
    index($0,b3){inblk=1; next}
    index($0,e3){inblk=0; next}
    inblk{next}
    {print}
  ' "$1" \
  | awk 'NF{last=NR} {buf[NR]=$0} END{for(i=1;i<=last;i++) print buf[i]}'
}

inject_blocks() {
  local file="$1" label="$2"
  local stripped final dob rules mcp
  stripped="$(mktemp)"; final="$(mktemp)"; dob="$(mktemp)"; rules="$(mktemp)"; mcp="$(mktemp)"
  om_build_block           > "$dob"
  om_build_rules_block     > "$rules" || true   # empty when there are no alwaysApply rules
  om_build_mcp_rules_block > "$mcp"   || true   # empty when there are no *-mcp-safety rules

  mkdir -p "$(dirname "$file")"
  if [ -f "$file" ]; then strip_managed_blocks "$file" > "$stripped"; else : > "$stripped"; fi

  # Assemble: [preserved] + [dev-operating-model] + [cursor-rules-mirror?] + [mcp-safety-mirror?].
  if [ -s "$stripped" ]; then cat "$stripped" > "$final"; printf '\n' >> "$final"; else : > "$final"; fi
  cat "$dob" >> "$final"
  if [ -s "$rules" ]; then printf '\n' >> "$final"; cat "$rules" >> "$final"; fi
  if [ -s "$mcp" ];   then printf '\n' >> "$final"; cat "$mcp"   >> "$final"; fi

  if [ -f "$file" ] && cmp -s "$final" "$file"; then
    log "$label: managed blocks already current ($file)"
    rm -f "$stripped" "$final" "$dob" "$rules" "$mcp"
  else
    local existed="no"; [ -f "$file" ] && existed="yes"
    mv "$final" "$file"
    rm -f "$stripped" "$dob" "$rules" "$mcp"
    if [ "$existed" = "yes" ]; then
      log "$label: updated managed blocks in $file"
    else
      log "$label: created $file with managed blocks"
    fi
    mark
  fi
}

native_status=0
if [ "$NATIVE_CODEX" -eq 1 ]; then
  if python3 "$OM_OPS_DIR/interoperability/native_rules.py" verify --home "$RULES_HOME"; then
    log "codex: native managed blocks already current; preserved"
  else
    log "codex: native projection needs an explicit --codex-native preview/apply; preserved"
    native_status=1
  fi
else
  inject_blocks "$CODEX_FILE" "codex"
fi
inject_blocks "$CLAUDE_FILE" "claude"

names() { xargs -n1 basename 2>/dev/null | sed 's/\.mdc$//' | paste -sd' ' -; }
rules_n="$(om_list_mirror_rules | wc -l | tr -d ' ')"
mcp_n="$(om_list_mcp_safety_rules | wc -l | tr -d ' ')"
if [ "${rules_n:-0}" -gt 0 ]; then
  log "mirrored $rules_n alwaysApply behavioral rule(s): $(om_list_mirror_rules | names)"
else
  log "no alwaysApply Cursor rules found to mirror (only the home context block installed)"
fi
if [ "${mcp_n:-0}" -gt 0 ]; then
  log "mirrored $mcp_n conditional MCP-safety rule(s): $(om_list_mcp_safety_rules | names)"
fi

# ---------------------------------------------------------------------------
echo
if [ "$changed" -eq 0 ]; then
  log "OK — everything already current (no changes made)."
else
  log "OK — agent rules installed/updated."
fi
log "context source: $OM_AGENT_CONTEXT (sha256 $(om_sha256 "$OM_AGENT_CONTEXT"))"

exit "$native_status"
