#!/usr/bin/env bash
# _ops/bin/lib.sh — shared helpers for the KleinPerkins/dev operating-model tooling.
#
# Sourced by install-agent-rules.sh and checks/verify-operating-model.sh so the Cursor
# `.mdc`, the Codex/Claude managed blocks, and the verifier all agree byte-for-byte.
# Source it; do not execute it. Exposes both variable and function accessors for paths.

# Resolve repo paths relative to THIS file (works regardless of cwd).
OM_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # .../_ops/bin
OM_OPS_DIR="$(cd "$OM_LIB_DIR/.." && pwd)"                       # .../_ops
OM_REPO_ROOT="$(cd "$OM_OPS_DIR/.." && pwd)"                     # repo root (~/dev)

OM_AGENT_CONTEXT="$OM_OPS_DIR/rules/agent-context.md"
OM_MDC="$OM_OPS_DIR/rules/dev-operating-model.mdc"

# Versioned SOTs for mirrored global Cursor rules. Home-operating rules live flat
# here; reusable rule capabilities live in the skills repo's global rule shelf.
# The installer combines both sources before mirroring to Codex and Claude.
OM_GLOBAL_RULES_DIR="$OM_OPS_DIR/rules/global"
OM_CAPABILITY_RULES_DIR="${OM_CAPABILITY_RULES_DIR:-$OM_REPO_ROOT/capabilities/skills/global/rules}"

# Managed-block markers (Codex/Claude). Both name spellings are provided so either the
# installer or the verifier can reference them. Keep these strings stable.
OM_BLOCK_BEGIN='<!-- BEGIN dev-operating-model (managed by KleinPerkins/dev) -->'
OM_BLOCK_END='<!-- END dev-operating-model -->'
OM_BEGIN_MARK="$OM_BLOCK_BEGIN"
OM_END_MARK="$OM_BLOCK_END"

# Second managed block: the cross-tool MIRROR of Cursor's always-apply behavioral rules
# (terse-output, subagent-orchestration, …) so Codex/Claude share the same always-on behavior,
# not just the home context. Source = the deployed ~/.cursor/rules/*.mdc (overridable for tests).
OM_RULES_BLOCK_BEGIN='<!-- BEGIN cursor-rules-mirror (managed by KleinPerkins/dev) -->'
OM_RULES_BLOCK_END='<!-- END cursor-rules-mirror -->'
OM_CURSOR_RULES_DIR="${OM_CURSOR_RULES_DIR:-$HOME/.cursor/rules}"

# Third managed block: the CONDITIONAL MCP-safety guardrails (*-mcp-safety.mdc) mirrored from
# Cursor so Codex/Claude enforce the same MCP guardrails. Unlike the always-on behavioral block,
# each rule here is gated ("apply only when using the named MCP server") via its description.
OM_MCP_RULES_BLOCK_BEGIN='<!-- BEGIN cursor-mcp-safety-mirror (managed by KleinPerkins/dev) -->'
OM_MCP_RULES_BLOCK_END='<!-- END cursor-mcp-safety-mirror -->'

# Fixed Cursor rule frontmatter description (kept here so generate + verify agree).
OM_MDC_DESCRIPTION='KleinPerkins ~/dev home operating model: structure, conventions, git identity, and where the full manual lives. Auto-applied in every session.'

# Canonical personal identity (single source for the doctor / identity-guard / scaffolder).
# The copied-out .git/hooks/identity-guard hardcodes the same value (it must be self-contained),
# so keep these in sync if the canonical noreply ever changes.
OM_NOREPLY='49759187+KleinPerkins@users.noreply.github.com'
OM_GH_USER='KleinPerkins'

# Function accessors (used by the verifier; mirror the vars above).
om_repo_root()          { printf '%s\n' "$OM_REPO_ROOT"; }
om_ops_dir()            { printf '%s\n' "$OM_OPS_DIR"; }
om_mdc_path()           { printf '%s\n' "$OM_MDC"; }
om_agent_context_path() { printf '%s\n' "$OM_AGENT_CONTEXT"; }

# om_list_global_rules -> sorted paths of every versioned global rule SOT:
# home rules (_ops/rules/global/*.mdc) plus global rule capabilities
# (capabilities/skills/global/rules/<id>/*.mdc), when that sibling repo is present.
om_list_global_rules() {
  local f
  for f in "$OM_GLOBAL_RULES_DIR"/*.mdc \
           "$OM_CAPABILITY_RULES_DIR"/*/*.mdc; do
    [ -e "$f" ] || continue
    printf '%s\n' "$f"
  done | LC_ALL=C sort
}

# om_sha256 <file> -> lowercase hex digest on stdout (portable: sha256sum/shasum/openssl).
om_sha256() {
  local f="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$f" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$f" | awk '{print $1}'
  else
    openssl dgst -sha256 "$f" | awk '{print $NF}'
  fi
}

# om_gen_mdc [agent-context-path] -> full Cursor .mdc content on stdout.
# = fixed YAML frontmatter + a blank line + the exact agent-context.md body.
om_gen_mdc() {
  local ctx="${1:-$OM_AGENT_CONTEXT}"
  printf -- '---\n'
  printf 'description: %s\n' "$OM_MDC_DESCRIPTION"
  printf 'alwaysApply: true\n'
  printf -- '---\n\n'
  cat "$ctx"
}

# om_build_block [agent-context-path] -> the managed block (BEGIN..END) on stdout.
# Embeds sha256(agent-context.md) so drift is detectable without re-parsing the body.
om_build_block() {
  local ctx="${1:-$OM_AGENT_CONTEXT}"
  local h; h="$(om_sha256 "$ctx")"
  printf '%s\n' "$OM_BLOCK_BEGIN"
  printf '<!-- sha256:%s | generated from KleinPerkins/dev _ops/rules/agent-context.md — do NOT edit inside this block; edit that file and re-run _ops/bin/install-agent-rules.sh -->\n' "$h"
  cat "$ctx"
  printf '%s\n' "$OM_BLOCK_END"
}

# om_extract_block <file> -> the managed block region (BEGIN..END inclusive) on stdout,
# or nothing if absent. Used by the verifier to compare against om_build_block.
om_extract_block() {
  local file="$1"
  [ -f "$file" ] || return 0
  awk -v b="$OM_BLOCK_BEGIN" -v e="$OM_BLOCK_END" '
    index($0,b){inblk=1}
    inblk{print}
    index($0,e){inblk=0}
  ' "$file"
}

# --- Cross-tool behavioral-rule mirror (Cursor alwaysApply rules -> Codex/Claude) ----------
om_cursor_rules_dir() { printf '%s\n' "$OM_CURSOR_RULES_DIR"; }

# om_list_mirror_rules [dir] -> sorted paths of the Cursor .mdc rules to mirror:
# every rule with `alwaysApply: true` EXCEPT dev-operating-model (already its own block).
om_list_mirror_rules() {
  local dir="${1:-$OM_CURSOR_RULES_DIR}"
  [ -d "$dir" ] || return 0
  local f
  for f in "$dir"/*.mdc; do
    [ -e "$f" ] || continue
    case "$(basename "$f")" in dev-operating-model.mdc) continue ;; esac
    if grep -Eqi '^[[:space:]]*alwaysApply:[[:space:]]*true[[:space:]]*$' "$f"; then
      printf '%s\n' "$f"
    fi
  done | LC_ALL=C sort
}

# om_strip_frontmatter <file> -> file body with a leading `--- … ---` YAML block removed.
om_strip_frontmatter() {
  awk 'BEGIN{fm=0}
       NR==1 && $0=="---" {fm=1; next}
       fm==1 && $0=="---" {fm=2; next}
       fm==1 {next}
       {print}' "$1"
}

# om_build_rules_block [dir] -> the cursor-rules-mirror managed block (BEGIN..END) on stdout,
# or NOTHING when there are no alwaysApply rules to mirror (e.g. CI / a fresh machine). The
# block is deterministic (rules sorted; each body frontmatter-stripped and blank-trimmed) so the
# verifier can rebuild and diff it; an embedded sha256 of the assembled body stamps drift.
om_build_rules_block() {
  local dir="${1:-$OM_CURSOR_RULES_DIR}"
  local files; files="$(om_list_mirror_rules "$dir")"
  [ -n "$files" ] || return 0
  local body; body="$(mktemp)"
  local f name
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    name="$(basename "$f" .mdc)"
    printf '### %s\n\n' "$name" >> "$body"
    om_strip_frontmatter "$f" \
      | awk 'NF{started=1} started{print}' \
      | awk 'NF{last=NR} {b[NR]=$0} END{for(i=1;i<=last;i++) print b[i]}' >> "$body"
    printf '\n' >> "$body"
  done <<EOF
$files
EOF
  local h; h="$(om_sha256 "$body")"
  printf '%s\n' "$OM_RULES_BLOCK_BEGIN"
  printf '<!-- sha256:%s | mirrored from ~/.cursor/rules alwaysApply rules by KleinPerkins/dev _ops/bin/install-agent-rules.sh — do NOT edit here; edit the source .mdc and re-run the installer -->\n' "$h"
  printf 'Always-on behavioral rules mirrored from Cursor so this tool behaves consistently with it (equivalent to Cursor `alwaysApply` rules).\n\n'
  cat "$body"
  printf '%s\n' "$OM_RULES_BLOCK_END"
  rm -f "$body"
}

# om_extract_rules_block <file> -> the cursor-rules-mirror block (BEGIN..END inclusive), or nothing.
om_extract_rules_block() {
  local file="$1"
  [ -f "$file" ] || return 0
  awk -v b="$OM_RULES_BLOCK_BEGIN" -v e="$OM_RULES_BLOCK_END" '
    index($0,b){inblk=1}
    inblk{print}
    index($0,e){inblk=0}
  ' "$file"
}

# --- Conditional MCP-safety mirror (Cursor *-mcp-safety rules -> Codex/Claude) --------------
# om_list_mcp_safety_rules [dir] -> sorted paths of ~/.cursor/rules/*-mcp-safety.mdc (auto-detected).
om_list_mcp_safety_rules() {
  local dir="${1:-$OM_CURSOR_RULES_DIR}"
  [ -d "$dir" ] || return 0
  local f
  for f in "$dir"/*-mcp-safety.mdc; do
    [ -e "$f" ] || continue
    printf '%s\n' "$f"
  done | LC_ALL=C sort
}

# om_rule_description <file> -> the single-line `description:` value from a .mdc frontmatter.
om_rule_description() {
  grep -m1 '^description:' "$1" 2>/dev/null | sed 's/^description:[[:space:]]*//'
}

# om_build_mcp_rules_block [dir] -> the cursor-mcp-safety-mirror managed block, or NOTHING when
# there are no *-mcp-safety rules. Each rule is prefixed with its gating description so the
# guardrail is applied only when the relevant MCP is in use. Deterministic (sorted) for diffing.
om_build_mcp_rules_block() {
  local dir="${1:-$OM_CURSOR_RULES_DIR}"
  local files; files="$(om_list_mcp_safety_rules "$dir")"
  [ -n "$files" ] || return 0
  local body; body="$(mktemp)"
  local f name desc
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    name="$(basename "$f" .mdc)"
    desc="$(om_rule_description "$f")"
    printf '### %s\n\n' "$name" >> "$body"
    [ -n "$desc" ] && printf '**Apply only when:** %s\n\n' "$desc" >> "$body"
    om_strip_frontmatter "$f" \
      | awk 'NF{started=1} started{print}' \
      | awk 'NF{last=NR} {b[NR]=$0} END{for(i=1;i<=last;i++) print b[i]}' >> "$body"
    printf '\n' >> "$body"
  done <<EOF
$files
EOF
  local h; h="$(om_sha256 "$body")"
  printf '%s\n' "$OM_MCP_RULES_BLOCK_BEGIN"
  printf '<!-- sha256:%s | mirrored from ~/.cursor/rules *-mcp-safety rules by KleinPerkins/dev _ops/bin/install-agent-rules.sh — do NOT edit here; edit the source .mdc and re-run the installer -->\n' "$h"
  printf 'Conditional MCP guardrails mirrored from Cursor. Each block applies ONLY when you are using the named MCP server, so Codex/Claude enforce the same safety Cursor does.\n\n'
  cat "$body"
  printf '%s\n' "$OM_MCP_RULES_BLOCK_END"
  rm -f "$body"
}

# om_extract_mcp_rules_block <file> -> the cursor-mcp-safety-mirror block (BEGIN..END), or nothing.
om_extract_mcp_rules_block() {
  local file="$1"
  [ -f "$file" ] || return 0
  awk -v b="$OM_MCP_RULES_BLOCK_BEGIN" -v e="$OM_MCP_RULES_BLOCK_END" '
    index($0,b){inblk=1}
    inblk{print}
    index($0,e){inblk=0}
  ' "$file"
}
