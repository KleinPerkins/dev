#!/usr/bin/env bash
# _ops/bin/doc-warden.sh — doc-warden CLI
#
# Operator-facing v2 commands with a legacy structural compatibility surface.
# Policy: _ops/doc-warden/POLICY.md §8
# Execution plan: _ops/plans/doc-warden-execution-plan-v1.md §18 WI-M1-03
#
# USAGE:
#   doc-warden.sh check <repo>
#   doc-warden.sh repair <repo> --dry-run
#   doc-warden.sh repair <repo> --approve --revision <sha> --plan-digest <digest>
#   doc-warden.sh repair <repo> --approve --greenfield
#   doc-warden.sh --help
#
# EXIT CODES:
#   check:
#     0 = fully CONFORMANT
#     1 = MISSING / DRIFTED / NEEDS_AUTHORING (known, describable, human-PR-repairable)
#     3 = NEEDS_OPERATOR / CONTRADICTORY (stop and ask)
#   repair --dry-run:
#     0 = plan computed (including empty "already conformant" plan)
#     1 = refused (precondition failure)
#   repair --approve --revision --plan-digest:
#     0 = applied cleanly
#     1 = refused (HEAD mismatch, digest mismatch, or other precondition)
#     2 = applied but created NEEDS_AUTHORING skeletons (human follow-up needed)
#   repair --approve --greenfield:
#     0 = applied cleanly
#     1 = refused (non-MISSING/CONFORMANT item found, or other precondition failure)
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # _ops/bin

# M1-T05 activates the compatible v2 verbs while keeping the explicit preview
# spelling and a named v1 compatibility namespace.
if [ "${1:-}" = "legacy-v1" ]; then
  shift
elif [ "${1:-}" = "v2-preview" ]; then
  shift
  V2_ROOT="$SELF_DIR/../doc-warden/v2"
  exec env PYTHONPATH="$V2_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -B -m doc_warden.cli "$@"
else
  case "${1:-}" in
    doctor|view|intent|draft|adr|prioritize|sequence|reconcile|migrate|runtime|prepare-authoring|validate-authoring|checkpoint|handoff|pause-with-continuity|resume-authoring|verify|apply)
      V2_ROOT="$SELF_DIR/../doc-warden/v2"
      exec env PYTHONPATH="$V2_ROOT${PYTHONPATH:+:$PYTHONPATH}" \
        python3 -B -m doc_warden.cli "$@"
      ;;
  esac
fi

# shellcheck source=doc-warden-lib.sh
source "$SELF_DIR/doc-warden-lib.sh"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

usage() {
  cat >&2 <<'USAGE'
Usage:
  doc-warden.sh doctor|view|intent|draft|adr|prioritize|sequence|reconcile|migrate ...
      Active v2 governance commands.

  doc-warden.sh checkpoint|handoff|pause-with-continuity|resume-authoring ...
      Governed authoring continuity previews.

  doc-warden.sh prepare-authoring|validate-authoring|verify|runtime|apply ...
      Authoring import, runtime qualification and transaction apply commands.

  doc-warden.sh v2-preview <v2-command> ...
      Compatibility spelling retained for pre-activation scripts.

  doc-warden.sh legacy-v1 check|repair|status ...
      Explicit compatibility access to the prior v1 surface.

  doc-warden.sh check <repo> [--reconstruct]
      Read-only classification. Prints one line per taxonomy item.
      --reconstruct adds provenance evidence records (POC 3c / thin-docs repos).
      Exit 0: CONFORMANT. Exit 1: MISSING/DRIFTED/NEEDS_AUTHORING. Exit 3: NEEDS_OPERATOR/CONTRADICTORY.

  doc-warden.sh check --cross-repo <profile> [--owner <path>] [--dependent <path>]
      Read-only cross-repo authority map (M4 / POC 3d). Prints YAML ownership map.
      Exit 0: OWNED_CORRECTLY. Exit 1: DUPLICATE_AUTHORITY/DEPENDENT_ONLY. Exit 3: CONTRADICTORY/UNRESOLVED.

  doc-warden.sh repair <repo> [--reconstruct] --dry-run
      Read-only. Prints the action plan + per-file diffs + plan digest. No writes.
      Exit 0: plan computed. Exit 1: refused.

  doc-warden.sh repair <repo> --trigger <id> --slug <slug> --dry-run
      Read-only. Fire a specific trigger (must be in triggers.yml) for a new artifact.
      Prints the action plan + rendered skeleton + plan digest. No writes.
      Exit 0: plan computed. Exit 1: refused (including trigger not in catalog).

  doc-warden.sh repair <repo> [--reconstruct] --approve --revision <sha> --plan-digest <digest>
      Mutating. Refuses on HEAD or digest mismatch. Structural actions only. Writes receipt.
      --reconstruct refuses when unresolved CONTRADICTORY claims remain.
      Exit 0: applied. Exit 1: refused. Exit 2: applied with NEEDS_AUTHORING skeletons.

  doc-warden.sh repair <repo> --trigger <id> --slug <slug> --approve --revision <sha> --plan-digest <digest>
      Mutating. Fire a specific trigger and apply its structural skeleton. Writes receipt.
      Exit 0: applied. Exit 1: refused. Exit 2: applied with NEEDS_AUTHORING skeletons.

  doc-warden.sh repair <repo> --approve --greenfield
      Mutating, narrow path. Valid only for brand-new repos (all items MISSING/CONFORMANT).
      Re-validates before writing. Creates baseline inheritance structure only.
      Exit 0: applied. Exit 1: refused.
USAGE
  exit 2
}

# resolve_repo <repo-arg> → absolute path, or exits with error
resolve_repo() {
  local repo_arg="$1"
  local repo_abs
  if ! repo_abs="$(resolve_repo_optional "$repo_arg")"; then
    printf 'ERROR: repo directory not found: %s\n' "${repo_arg/#\~/$HOME}" >&2
    exit 1
  fi
  printf '%s' "$repo_abs"
}

# resolve_repo_optional <repo-arg> → absolute path, or return 1 (no exit)
resolve_repo_optional() {
  local repo_arg="$1"
  local repo_abs
  repo_abs="${repo_arg/#\~/$HOME}"
  if [[ "$repo_abs" != /* ]]; then
    repo_abs="$(pwd)/$repo_abs"
  fi
  repo_abs="${repo_abs%/}"
  if [ ! -d "$repo_abs" ]; then
    return 1
  fi
  printf '%s' "$repo_abs"
}

# repo_head_sha <repo> → git HEAD SHA or "no-git"
repo_head_sha() {
  git -C "$1" rev-parse HEAD 2>/dev/null || printf 'no-git'
}

# run_execute_plan <repo> <actions> — abort CLI on execution refusal (return 2)
run_execute_plan() {
  local repo="$1" actions="$2"
  local exec_rc=0
  dwl_execute_plan "$actions" "$repo" || exec_rc=$?
  if [ "$exec_rc" -eq 2 ]; then
    printf 'REFUSED: plan execution aborted.\n' >&2
    exit 1
  fi
  return "$exec_rc"
}

# exit_code_for_classification <classification>
exit_code_for_classification() {
  local cls="$1"
  case "$cls" in
    CONFORMANT|OWNED_CORRECTLY|OWNER_ONLY) printf 0 ;;
    MISSING|DRIFTED|NEEDS_AUTHORING|DUPLICATE_AUTHORITY|DEPENDENT_ONLY) printf 1 ;;
    NEEDS_OPERATOR|CONTRADICTORY)    printf 3 ;;
    *) printf 1 ;;
  esac
}

# exit_code_for_cross_repo <exit_classification>
exit_code_for_cross_repo() {
  local cls="$1"
  case "$cls" in
    OWNED_CORRECTLY) printf 0 ;;
    DUPLICATE_AUTHORITY|DEPENDENT_ONLY) printf 1 ;;
    CONTRADICTORY|UNRESOLVED|NEEDS_OPERATOR) printf 3 ;;
    *) printf 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# check verb
# ---------------------------------------------------------------------------
cmd_check() {
  local repo="$1" reconstruct=0
  shift || true
  while [ $# -gt 0 ]; do
    case "$1" in
      --reconstruct) reconstruct=1 ;;
      *) printf 'ERROR: unknown check flag: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
  done
  repo="$(resolve_repo "$repo")"
  local plans_rel adr_rel
  plans_rel="$(dwl_plans_dir "$repo")"
  adr_rel="$(dwl_adr_dir "$repo")"

  printf 'doc-warden check: %s\n' "$repo"
  printf '  plans_dir: %s\n' "$plans_rel"
  printf '  adr_dir:   %s\n' "$adr_rel"
  printf '\n'

  local classifications
  classifications="$(dwl_classify_repo "$repo")"

  local exit_cls="$DWL_CONFORMANT"
  while IFS=: read -r key cls; do
    if [ "$key" = "exit_classification" ]; then
      exit_cls="$cls"
      continue
    fi
    printf '  %-40s %s\n' "$key" "$cls"
  done <<< "$classifications"

  printf '\n'
  printf 'Overall: %s\n' "$exit_cls"

  if [ "$reconstruct" -eq 1 ]; then
    local profile
    profile="$(dwl_reconstruct_profile_for_repo "$repo")"
    if [ -z "$profile" ]; then
      printf '\nRECONSTRUCT: no profile for this repo — NEEDS_OPERATOR co-design required.\n'
      exit 3
    fi
    printf '\n== Provenance reconstruction (profile: %s) ==\n' "$profile"
    dwl_reconstruct_emit_records "$repo" "$profile"
    if dwl_reconstruct_has_unresolved_contradictory "$repo"; then
      printf '\nCONTRADICTORY: at least one claim has contested/conflicting evidence — resolve before repair --approve.\n'
      exit_cls="$DWL_CONTRADICTORY"
    fi
  fi

  # NEEDS_OPERATOR / CONTRADICTORY: print escalation message (zero writes)
  if [ "$exit_cls" = "$DWL_NEEDS_OPERATOR" ]; then
    printf '\n'
    printf 'NEEDS_OPERATOR: An observed condition has no matching triggers.yml entry.\n'
    printf 'Action required: describe the unmatched condition to the operator;\n'
    printf '  do NOT attempt repair. Update triggers.yml first, then repair.\n'
    printf 'See: _ops/doc-warden/POLICY.md §6 (Unknown-case behavior)\n'
  elif [ "$exit_cls" = "$DWL_CONTRADICTORY" ]; then
    printf '\n'
    printf 'CONTRADICTORY: Two authoritative signals conflict in this repository.\n'
    printf 'Action required: inspect the contradiction hint lines above and resolve\n'
    printf '  the conflict manually before running repair.\n'
    printf 'Common cause: duplicate doc-warden block markers in AGENTS.md (e.g. from\n'
    printf '  a bad merge). Edit AGENTS.md to retain exactly one block.\n'
    printf 'See: _ops/doc-warden/POLICY.md §5 (Classification ladder)\n'
  fi

  local exit_code
  exit_code="$(exit_code_for_classification "$exit_cls")"
  exit "$exit_code"
}

# ---------------------------------------------------------------------------
# check --cross-repo verb (M4 / POC 3d)
# ---------------------------------------------------------------------------
cmd_check_cross_repo() {
  local profile_id="$1" owner_override="$2" dep_override="$3"
  if ! dwl_cross_repo_profile_exists "$profile_id"; then
    printf 'ERROR: unknown cross-repo profile: %s\n' "$profile_id" >&2
    printf 'See: _ops/doc-warden/cross-repo-profiles.yml\n' >&2
    exit 3
  fi
  local owner_repo dep_repo
  if [ -n "$owner_override" ]; then
    if ! owner_repo="$(resolve_repo_optional "$owner_override")"; then
      printf 'ERROR: owner repo not found for profile %s (use --owner <path>)\n' "$profile_id" >&2
      exit 3
    fi
  else
    owner_repo="$(dwl_cross_repo_default_owner_path "$profile_id")"
  fi
  if [ -n "$dep_override" ]; then
    if ! dep_repo="$(resolve_repo_optional "$dep_override")"; then
      printf 'ERROR: dependent repo not found for profile %s (use --dependent <path>)\n' "$profile_id" >&2
      exit 3
    fi
  else
    dep_repo="$(dwl_cross_repo_default_dependent_path "$profile_id")"
  fi
  if [ -z "$owner_repo" ] || [ ! -d "$owner_repo" ]; then
    printf 'ERROR: owner repo not found for profile %s (use --owner <path>)\n' "$profile_id" >&2
    exit 3
  fi
  if [ -z "$dep_repo" ] || [ ! -d "$dep_repo" ]; then
    printf 'ERROR: dependent repo not found for profile %s (use --dependent <path>)\n' "$profile_id" >&2
    exit 3
  fi

  printf 'doc-warden check --cross-repo %s\n' "$profile_id"
  printf '  owner:     %s\n' "$owner_repo"
  printf '  dependent: %s\n' "$dep_repo"
  printf '\n'

  local map_yaml map_meta exit_cls
  map_meta="$(mktemp)"
  map_yaml="$(dwl_cross_repo_emit_ownership_map "$profile_id" "$owner_repo" "$dep_repo" 2>"$map_meta")"
  local map_rc=$?
  if [ "$map_rc" -ne 0 ]; then
    cat "$map_meta" >&2
    printf '%s\n' "$map_yaml" >&2
    rm -f "$map_meta"
    exit 2
  fi

  while IFS=: read -r prefix tid cls; do
    [ "$prefix" = "map" ] || continue
    printf '  %-40s %s\n' "cross_repo:${tid}" "$cls"
  done < "$map_meta"

  exit_cls="$(printf '%s' "$map_yaml" | python3 -c "
import sys, yaml
raw = sys.stdin.read()
docs = list(yaml.safe_load_all(raw))
doc = docs[-1] if docs else {}
print(doc.get('exit_classification', 'CONTRADICTORY'))
" 2>/dev/null)"
  [ -z "$exit_cls" ] && exit_cls="$DWL_CONTRADICTORY"
  rm -f "$map_meta"

  printf '\nOverall: %s\n\n' "$exit_cls"
  printf '== Ownership map ==\n'
  printf '%s\n' "$map_yaml"

  if [ "$exit_cls" = "$DWL_DUPLICATE_AUTHORITY" ]; then
    printf '\nDUPLICATE_AUTHORITY: agreeing canonical copies in both repos — repair converts dependent to pointer (trigger #6).\n'
    printf 'Operator gate required before repair --approve on either repo.\n'
  elif [ "$exit_cls" = "$DWL_CONTRADICTORY" ]; then
    printf '\nCONTRADICTORY: conflicting canonical statements — resolve manually before repair.\n'
  fi

  local exit_code
  exit_code="$(exit_code_for_cross_repo "$exit_cls")"
  exit "$exit_code"
}

# ---------------------------------------------------------------------------
# repair --dry-run verb
# ---------------------------------------------------------------------------
cmd_repair_dry_run() {
  local repo="$1" reconstruct=0
  shift || true
  while [ $# -gt 0 ]; do
    case "$1" in
      --reconstruct) reconstruct=1 ;;
      *) printf 'ERROR: unknown repair flag: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
  done
  repo="$(resolve_repo "$repo")"

  if [ "$reconstruct" -eq 1 ]; then
    printf 'doc-warden repair --reconstruct --dry-run: %s\n' "$repo"
  else
    printf 'doc-warden repair --dry-run: %s\n' "$repo"
  fi
  printf '\n'

  # Classify first
  local classifications
  classifications="$(dwl_classify_repo "$repo")"
  local exit_cls
  exit_cls="$(echo "$classifications" | grep "^exit_classification:" | cut -d: -f2)"

  if [ "$exit_cls" = "$DWL_NEEDS_OPERATOR" ] || [ "$exit_cls" = "$DWL_CONTRADICTORY" ]; then
    printf 'REFUSED: exit_classification is %s — resolve via check and operator approval first.\n' "$exit_cls" >&2
    exit 1
  fi

  # Compute plan
  local actions plan_rc=0
  if [ "$reconstruct" -eq 1 ]; then
    actions="$(dwl_plan_reconstruct_repair "$repo" 2>&1)" || plan_rc=$?
    if [ "$plan_rc" -ne 0 ]; then
      printf '%s\n' "$actions" >&2
      exit "$plan_rc"
    fi
    printf '\n== Evidence records (attach to operator review) ==\n'
    dwl_reconstruct_emit_records "$repo" "$(dwl_reconstruct_profile_for_repo "$repo")"
    if dwl_reconstruct_has_unresolved_contradictory "$repo"; then
      printf '\nNote: CONTRADICTORY claim(s) present — repair --approve will refuse until resolved.\n'
    fi
  else
    actions="$(dwl_plan_repair "$repo")"
  fi

  if [ -z "$actions" ]; then
    printf 'Plan: empty — repo is already conformant.\n'
    local digest="empty-plan"
    printf 'plan-digest: %s\n' "$digest"
    exit 0
  fi

  printf 'Planned actions:\n'
  local has_semantic=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local action path detail
    action="${line%%:*}"
    path="$(echo "$line" | cut -d: -f2)"
    detail="${line#*:*:}"
    case "$action" in
      create)        printf '  CREATE  %s  (%s)\n' "$path" "$detail" ;;
      append_block)  printf '  APPEND  %s  (%s)\n' "$path" "$detail" ;;
      patch)         printf '  PATCH   %s  (%s)\n' "$path" "$detail" ;;
      DRIFTED)       printf '  DRIFT   %s  (manual review required — semantic item)\n' "$path"; has_semantic=1 ;;
      move)          printf '  MOVE    %s  (%s)\n' "$path" "$detail" ;;
      *)             printf '  %s  %s\n' "$action" "$path" ;;
    esac
  done <<< "$actions"

  if [ "$has_semantic" -eq 1 ]; then
    printf '\nNote: DRIFTED items require manual review. They are excluded from --approve.\n'
  fi

  # Per-file rendered diffs (POLICY.md §8 / acceptance test #7 — A4 fix):
  # Show the rendered template content (what would actually be written) for each
  # create/append action so the operator can inspect before --approve.
  local repo_slug
  repo_slug="$(basename "$repo")"
  local plans_rel adr_rel
  plans_rel="$(dwl_plans_dir "$repo")"
  adr_rel="$(dwl_adr_dir "$repo")"
  local printed_diff_header=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local action path detail
    action="${line%%:*}"
    path="$(echo "$line" | cut -d: -f2)"
    detail="${line#*:*:}"
    if [ "$action" = "append_block" ] && echo "$detail" | grep -q "from-template:"; then
      local tmpout tmpl_rendered
      tmpout="$(mktemp)"
      if dwl_render_template "agents-md-pointer-block.md" "$tmpout" \
          "PLANS_DIR=$plans_rel" "ADR_DIR=$adr_rel" "REPO_SLUG=$repo_slug" 2>/dev/null; then
        tmpl_rendered="$(cat "$tmpout" 2>/dev/null)"
      fi
      rm -f "$tmpout"
      if [ -n "${tmpl_rendered:-}" ]; then
        if [ "$printed_diff_header" -eq 0 ]; then
          printf '\nRendered content preview:\n'
          printed_diff_header=1
        fi
        printf '\n--- %s (existing)\n+++ %s (with appended block)\n' "$path" "$path"
        while IFS= read -r rline; do
          printf '+%s\n' "$rline"
        done <<< "$tmpl_rendered"
      fi
    elif [ "$action" = "patch" ]; then
      local readme_abs="$repo/$path"
      local tmp_before tmp_after drift_ids_preview
      tmp_before="$(mktemp)"
      tmp_after="$(mktemp)"
      cp "$readme_abs" "$tmp_before" 2>/dev/null || : > "$tmp_before"
      drift_ids_preview="$(dwl_policy_drift_ids_for_plans_readme "$readme_abs")"
      dwl_render_patched_plans_readme "$repo" "$plans_rel" "$drift_ids_preview" > "$tmp_after" 2>/dev/null
      if ! cmp -s "$tmp_before" "$tmp_after" 2>/dev/null; then
        if [ "$printed_diff_header" -eq 0 ]; then
          printf '\nRendered content preview:\n'
          printed_diff_header=1
        fi
        printf '\n--- %s (existing)\n+++ %s (after policy patches)\n' "$path" "$path"
        diff -u "$tmp_before" "$tmp_after" 2>/dev/null | tail -n +3 | while IFS= read -r dline; do
          printf '%s\n' "$dline"
        done
      fi
      rm -f "$tmp_before" "$tmp_after"
    elif [ "$action" = "create" ] && echo "$detail" | grep -q "from-template:"; then
      local tmpl_raw="${detail#from-template:}"
      local tmpl_name="${tmpl_raw%%:*}"
      local tmpl_extra="${tmpl_raw#*:}"
      [ "$tmpl_extra" = "$tmpl_raw" ] && tmpl_extra=""
      local kv_args=("PLANS_DIR=$plans_rel" "ADR_DIR=$adr_rel" "REPO_SLUG=$repo_slug")
      if [ -n "$tmpl_extra" ]; then
        IFS=: read -ra extra_kvs <<< "$tmpl_extra"
        for ekv in "${extra_kvs[@]}"; do
          [ -n "$ekv" ] && kv_args+=("$ekv")
        done
      fi
      local tmpout rendered
      tmpout="$(mktemp)"
      if dwl_render_template "$tmpl_name" "$tmpout" "${kv_args[@]}" 2>/dev/null; then
        rendered="$(cat "$tmpout" 2>/dev/null)"
      fi
      rm -f "$tmpout"
      if [ -n "${rendered:-}" ]; then
        if [ "$printed_diff_header" -eq 0 ]; then
          printf '\nRendered content preview:\n'
          printed_diff_header=1
        fi
        printf '\n--- /dev/null\n+++ %s\n' "$path"
        while IFS= read -r rline; do
          printf '+%s\n' "$rline"
        done <<< "$rendered"
      fi
    fi
  done <<< "$actions"

  # Compute digest
  local digest
  digest="$(dwl_plan_digest "$actions" "$repo")"
  printf '\nplan-digest: %s\n' "$digest"

  local head_sha
  head_sha="$(repo_head_sha "$repo")"
  printf 'head-revision: %s\n' "$head_sha"

  if dwl_plan_has_structural_actions "$actions"; then
    if [ "$reconstruct" -eq 1 ]; then
      printf '\nTo approve: doc-warden.sh repair %s --reconstruct --approve --revision %s --plan-digest %s\n' \
        "$repo" "$head_sha" "$digest"
    else
      printf '\nTo approve: doc-warden.sh repair %s --approve --revision %s --plan-digest %s\n' \
        "$repo" "$head_sha" "$digest"
    fi
  else
    printf '\nNo structural actions to approve — resolve DRIFTED items manually.\n'
  fi

  exit 0
}

# ---------------------------------------------------------------------------
# repair --trigger <id> --slug <slug> --dry-run verb
# ---------------------------------------------------------------------------
cmd_repair_trigger_dry_run() {
  local repo="$1" trigger_id="$2" slug="$3"
  repo="$(resolve_repo "$repo")"

  printf 'doc-warden repair --trigger %s --slug %s --dry-run: %s\n' "$trigger_id" "$slug" "$repo"
  printf '\n'

  # Compute trigger action plan
  local actions plan_rc=0
  actions="$(dwl_plan_trigger "$repo" "$trigger_id" "$slug" 2>&1)" || plan_rc=$?
  if [ "$plan_rc" -ne 0 ]; then
    printf '%s\n' "$actions" >&2
    exit "$plan_rc"
  fi

  if [ -z "$actions" ]; then
    printf 'Plan: empty — already applied.\n'
    printf 'plan-digest: empty-plan\n'
    exit 0
  fi

  printf 'Planned actions (trigger #%s):\n' "$trigger_id"
  local has_semantic=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local action path detail
    action="${line%%:*}"
    path="$(echo "$line" | cut -d: -f2)"
    detail="${line#*:*:}"
    case "$action" in
      create)        printf '  CREATE  %s  (%s)\n' "$path" "$detail" ;;
      index_row)     printf '  INDEX_ROW  %s  (row for %s, status: %s)\n' "$path" "${detail%%:*}" "${detail#*:}" ;;
      *)             printf '  %s  %s\n' "$action" "$path" ;;
    esac
  done <<< "$actions"

  # Per-file rendered diffs
  local repo_slug
  repo_slug="$(basename "$repo")"
  local printed_diff_header=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local action path detail
    action="${line%%:*}"
    path="$(echo "$line" | cut -d: -f2)"
    detail="${line#*:*:}"
    if [ "$action" = "create" ] && echo "$detail" | grep -q "from-template:"; then
      # Extract template name and any extra kv pairs (e.g. SLUG=foo:NNNN=0001)
      local tmpl_and_kv="${detail#from-template:}"
      local tmpl_name="${tmpl_and_kv%%:*}"
      local extra_kv_str="${tmpl_and_kv#*:}"
      [ "$extra_kv_str" = "$tmpl_name" ] && extra_kv_str=""
      local tmpout
      tmpout="$(mktemp)"
      local kv_args=("PLANS_DIR=$(dwl_plans_dir "$repo")" "ADR_DIR=$(dwl_adr_dir "$repo")" "REPO_SLUG=$repo_slug")
      if [ -n "$extra_kv_str" ]; then
        IFS=: read -ra extra_kv_arr <<< "$extra_kv_str"
        for ekv in "${extra_kv_arr[@]}"; do
          [ -n "$ekv" ] && kv_args+=("$ekv")
        done
      fi
      dwl_render_template "$tmpl_name" "$tmpout" "${kv_args[@]}" 2>/dev/null
      local rendered
      rendered="$(cat "$tmpout" 2>/dev/null)"
      rm -f "$tmpout"
      if [ -n "$rendered" ]; then
        if [ "$printed_diff_header" -eq 0 ]; then
          printf '\nRendered content preview:\n'
          printed_diff_header=1
        fi
        printf '\n--- /dev/null\n+++ %s\n' "$path"
        while IFS= read -r rline; do
          printf '+%s\n' "$rline"
        done <<< "$rendered"
      fi
    elif [ "$action" = "append_block" ] && echo "$detail" | grep -q "from-template:"; then
      local tmpl_and_kv_ab="${detail#from-template:}"
      local tmpl_name_ab="${tmpl_and_kv_ab%%:*}"
      local extra_kv_str_ab="${tmpl_and_kv_ab#*:}"
      [ "$extra_kv_str_ab" = "$tmpl_name_ab" ] && extra_kv_str_ab=""
      local tmpout_ab
      tmpout_ab="$(mktemp)"
      local kv_args_ab=("PLANS_DIR=$(dwl_plans_dir "$repo")" "ADR_DIR=$(dwl_adr_dir "$repo")" "REPO_SLUG=$repo_slug")
      if [ -n "$extra_kv_str_ab" ]; then
        IFS=: read -ra extra_kv_arr_ab <<< "$extra_kv_str_ab"
        for ekv_ab in "${extra_kv_arr_ab[@]}"; do
          [ -n "$ekv_ab" ] && kv_args_ab+=("$ekv_ab")
        done
      fi
      dwl_render_template "$tmpl_name_ab" "$tmpout_ab" "${kv_args_ab[@]}" 2>/dev/null
      local rendered_ab
      rendered_ab="$(cat "$tmpout_ab" 2>/dev/null)"
      rm -f "$tmpout_ab"
      if [ -n "$rendered_ab" ]; then
        if [ "$printed_diff_header" -eq 0 ]; then
          printf '\nRendered content preview:\n'
          printed_diff_header=1
        fi
        printf '\n--- %s (existing)\n+++ %s (with appended block)\n' "$path" "$path"
        while IFS= read -r rline_ab; do
          printf '+%s\n' "$rline_ab"
        done <<< "$rendered_ab"
      fi
    elif [ "$action" = "index_row" ]; then
      local fname_d="${detail%%:*}" status_d="${detail#*:}" today_d row_d
      today_d="$(date +%Y-%m-%d)"
      row_d="$(dwl_index_row_format "$path" "$fname_d" "$status_d" "$today_d")"
      if [ "$printed_diff_header" -eq 0 ]; then
        printf '\nRendered content preview:\n'
        printed_diff_header=1
      fi
      printf '\n--- %s (existing)\n+++ %s (with new index row)\n' "$path" "$path"
      printf '+%s\n' "$row_d"
    elif [ "$action" = "append_glossary_term" ]; then
      local slug_d="${detail#SLUG=}" term_d
      term_d="$(dwl_glossary_term_title "$slug_d")"
      if [ "$printed_diff_header" -eq 0 ]; then
        printf '\nRendered content preview:\n'
        printed_diff_header=1
      fi
      printf '\n--- %s (existing)\n+++ %s (with appended term)\n' "$path" "$path"
      printf '+\n'
      printf '+## %s\n+\n' "$term_d"
      printf '+<!-- TODO: author — definition for %s -->\n+\n' "$slug_d"
      printf '+*Source: <!-- TODO: author -->\n'
    fi
  done <<< "$actions"

  # Compute digest
  local digest
  digest="$(dwl_plan_digest "$actions" "$repo")"
  printf '\nplan-digest: %s\n' "$digest"

  local head_sha
  head_sha="$(repo_head_sha "$repo")"
  printf 'head-revision: %s\n' "$head_sha"

  printf '\nTo approve: doc-warden.sh repair %s --trigger %s --slug %s --approve --revision %s --plan-digest %s\n' \
    "$repo" "$trigger_id" "$slug" "$head_sha" "$digest"

  exit 0
}

# ---------------------------------------------------------------------------
# repair --trigger <id> --slug <slug> --approve verb
# ---------------------------------------------------------------------------
cmd_repair_trigger_approve() {
  local repo="$1" trigger_id="$2" slug="$3" expected_rev="$4" expected_digest="$5"
  repo="$(resolve_repo "$repo")"

  printf 'doc-warden repair --trigger %s --slug %s --approve: %s\n' "$trigger_id" "$slug" "$repo"
  printf '  expected-revision: %s\n' "$expected_rev"
  printf '  expected-digest:   %s\n' "$expected_digest"
  printf '\n'

  # HEAD check
  local actual_rev
  actual_rev="$(repo_head_sha "$repo")"
  if [ "$actual_rev" != "$expected_rev" ]; then
    printf 'REFUSED: HEAD revision mismatch.\n' >&2
    printf '  Expected: %s\n' "$expected_rev" >&2
    printf '  Actual:   %s\n' "$actual_rev" >&2
    exit 1
  fi

  # Compute trigger plan
  local actions plan_rc=0
  actions="$(dwl_plan_trigger "$repo" "$trigger_id" "$slug" 2>&1)" || plan_rc=$?
  if [ "$plan_rc" -ne 0 ]; then
    printf '%s\n' "$actions" >&2
    exit "$plan_rc"
  fi

  # Digest check
  local actual_digest
  actual_digest="$(dwl_plan_digest "$actions" "$repo")"
  if [ "$actual_digest" != "$expected_digest" ]; then
    printf 'REFUSED: plan-digest mismatch.\n' >&2
    printf '  Expected: %s\n' "$expected_digest" >&2
    printf '  Actual:   %s\n' "$actual_digest" >&2
    exit 1
  fi

  # Execute
  printf 'Executing trigger plan...\n'
  local has_needs_authoring=0
  run_execute_plan "$repo" "$actions" && true
  has_needs_authoring=$?

  printf 'Actions applied.\n'

  # Write receipt
  local receipt_file
  receipt_file="$(dwl_write_receipt "$repo" "repair-trigger-${trigger_id}" "$expected_rev" "$actions" "applied")"
  printf 'Receipt: %s\n' "$receipt_file"

  if [ "$has_needs_authoring" -ne 0 ]; then
    printf '\nNEEDS_AUTHORING: skeleton file(s) created — fill in <!-- TODO: author --> sections.\n'
    exit 2
  fi

  exit 0
}

# ---------------------------------------------------------------------------
# repair --approve --revision --plan-digest verb
# ---------------------------------------------------------------------------
cmd_repair_approve() {
  local repo="$1" expected_rev="$2" expected_digest="$3" reconstruct=0
  shift 3 || true
  while [ $# -gt 0 ]; do
    case "$1" in
      --reconstruct) reconstruct=1 ;;
      *) printf 'ERROR: unknown repair flag: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
  done
  repo="$(resolve_repo "$repo")"

  if [ "$reconstruct" -eq 1 ]; then
    printf 'doc-warden repair --reconstruct --approve: %s\n' "$repo"
  else
    printf 'doc-warden repair --approve: %s\n' "$repo"
  fi
  printf '  expected-revision: %s\n' "$expected_rev"
  printf '  expected-digest:   %s\n' "$expected_digest"
  printf '\n'

  # Safety check: HEAD must match expected revision
  local actual_rev
  actual_rev="$(repo_head_sha "$repo")"
  if [ "$actual_rev" != "$expected_rev" ]; then
    printf 'REFUSED: HEAD revision mismatch.\n' >&2
    printf '  Expected: %s\n' "$expected_rev" >&2
    printf '  Actual:   %s\n' "$actual_rev" >&2
    printf 'Re-run --dry-run to get a fresh plan and digest.\n' >&2
    exit 1
  fi

  # Classify and refuse on NEEDS_OPERATOR/CONTRADICTORY
  local classifications
  classifications="$(dwl_classify_repo "$repo")"
  local exit_cls
  exit_cls="$(echo "$classifications" | grep "^exit_classification:" | cut -d: -f2)"
  if [ "$exit_cls" = "$DWL_NEEDS_OPERATOR" ] || [ "$exit_cls" = "$DWL_CONTRADICTORY" ]; then
    printf 'REFUSED: exit_classification is %s — operator approval required first.\n' "$exit_cls" >&2
    exit 1
  fi

  # Recompute plan and digest; verify digest matches
  local actions plan_rc=0
  if [ "$reconstruct" -eq 1 ]; then
    if dwl_reconstruct_has_unresolved_contradictory "$repo"; then
      printf 'REFUSED: unresolved CONTRADICTORY reconstruction claim(s) — operator resolution required.\n' >&2
      exit 1
    fi
    actions="$(dwl_plan_reconstruct_repair "$repo" 2>&1)" || plan_rc=$?
    if [ "$plan_rc" -ne 0 ]; then
      printf '%s\n' "$actions" >&2
      exit "$plan_rc"
    fi
  else
    actions="$(dwl_plan_repair "$repo")"
  fi
  local actual_digest
  actual_digest="$(dwl_plan_digest "$actions" "$repo")"
  if [ "$actual_digest" != "$expected_digest" ]; then
    printf 'REFUSED: plan-digest mismatch (templates or policy may have changed).\n' >&2
    printf '  Expected: %s\n' "$expected_digest" >&2
    printf '  Actual:   %s\n' "$actual_digest" >&2
    printf 'Re-run --dry-run to get a fresh plan and digest.\n' >&2
    exit 1
  fi

  if ! dwl_plan_has_structural_actions "$actions"; then
    printf 'REFUSED: plan contains no structural actions (DRIFTED-only — manual review required).\n' >&2
    exit 1
  fi

  # Execute structural actions only
  printf 'Executing plan...\n'
  local has_needs_authoring=0
  run_execute_plan "$repo" "$actions" && true
  has_needs_authoring=$?

  printf 'Actions applied.\n'

  # Write receipt
  local receipt_file
  receipt_file="$(dwl_write_receipt "$repo" "repair-approve" "$expected_rev" "$actions" "applied")"
  printf 'Receipt: %s\n' "$receipt_file"

  if [ "$has_needs_authoring" -ne 0 ]; then
    printf '\nNEEDS_AUTHORING: one or more skeleton files were created.\n'
    printf 'Human follow-up required: fill in the <!-- TODO: author --> sections\n'
    printf 'in a separate, human-reviewed PR before the repo is fully conformant.\n'
    exit 2
  fi

  exit 0
}

# ---------------------------------------------------------------------------
# repair --approve --greenfield verb
# ---------------------------------------------------------------------------
cmd_repair_greenfield() {
  local repo="$1"
  repo="$(resolve_repo "$repo")"

  printf 'doc-warden repair --approve --greenfield: %s\n' "$repo"
  printf '\n'

  # Mandatory self-validation: re-run classification (POLICY.md §8)
  local classifications
  classifications="$(dwl_classify_repo "$repo")"
  local exit_cls
  exit_cls="$(echo "$classifications" | grep "^exit_classification:" | cut -d: -f2)"
  if [ "$exit_cls" = "$DWL_NEEDS_OPERATOR" ] || [ "$exit_cls" = "$DWL_CONTRADICTORY" ]; then
    printf 'REFUSED: exit_classification is %s — operator approval required first.\n' "$exit_cls" >&2
    exit 1
  fi
  local non_baseline_found=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local key cls
    cls="${line##*:}"
    key="${line%:$cls}"
    case "$key" in
      exit_classification|hint:*|plan:*|adr:*|unknown:*) continue ;;
    esac
    case "$cls" in
      MISSING|CONFORMANT) ;;  # OK for greenfield baseline items
      *)
        printf 'REFUSED: item "%s" is classified "%s" (expected MISSING or CONFORMANT only).\n' "$key" "$cls" >&2
        non_baseline_found=1
        ;;
    esac
  done <<< "$classifications"

  if [ "$non_baseline_found" -ne 0 ]; then
    printf 'REFUSED: greenfield repair is only valid when all items are MISSING or CONFORMANT.\n' >&2
    printf 'Run: doc-warden.sh check %s to see the full classification.\n' "$repo" >&2
    exit 1
  fi

  # Compute and execute greenfield plan
  local actions
  actions="$(dwl_plan_greenfield "$repo")"

  if [ -z "$actions" ]; then
    printf 'Already conformant — no actions needed.\n'
    exit 0
  fi

  printf 'Executing greenfield plan...\n'
  run_execute_plan "$repo" "$actions" && true
  local has_needs_authoring=$?

  printf 'Greenfield baseline applied.\n'

  # Write receipt (no HEAD sha for greenfield — it may be the very first commit context)
  local head_sha
  head_sha="$(repo_head_sha "$repo")"
  local receipt_file
  receipt_file="$(dwl_write_receipt "$repo" "repair-greenfield" "$head_sha" "$actions" "applied")"
  printf 'Receipt: %s\n' "$receipt_file"

  if [ "$has_needs_authoring" -ne 0 ]; then
    printf '\nNEEDS_AUTHORING: greenfield skeleton file(s) created — fill in <!-- TODO: author --> sections.\n'
    exit 2
  fi

  exit 0
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
[ $# -eq 0 ] && usage

VERB="${1:-}"
shift

case "$VERB" in
  --help|-h) usage ;;
  check)
    if [ $# -ge 1 ] && [ "$1" = "--cross-repo" ]; then
      shift
      [ $# -lt 1 ] && { printf 'ERROR: check --cross-repo requires <profile>\n' >&2; usage; }
      PROFILE_ID="$1"; shift
      OWNER_OVERRIDE=""; DEP_OVERRIDE=""
      while [ $# -gt 0 ]; do
        case "$1" in
          --owner) shift; OWNER_OVERRIDE="${1:-}"; shift ;;
          --dependent) shift; DEP_OVERRIDE="${1:-}"; shift ;;
          *) break ;;
        esac
      done
      cmd_check_cross_repo "$PROFILE_ID" "$OWNER_OVERRIDE" "$DEP_OVERRIDE"
      exit $?
    fi
    [ $# -lt 1 ] && { printf 'ERROR: check requires <repo>\n' >&2; usage; }
    REPO="$1"; shift
    cmd_check "$REPO" "$@"
    ;;
  repair)
    [ $# -lt 1 ] && { printf 'ERROR: repair requires <repo>\n' >&2; usage; }
    REPO="$1"; shift
    RECONSTRUCT=0
    while [ $# -gt 0 ]; do
      case "$1" in
        --reconstruct) RECONSTRUCT=1; shift ;;
        --dry-run)
          if [ "$RECONSTRUCT" -eq 1 ]; then
            cmd_repair_dry_run "$REPO" --reconstruct
          else
            cmd_repair_dry_run "$REPO"
          fi
          exit $?
          ;;
        --trigger|--approve)
          break
          ;;
        *)
          printf 'ERROR: repair requires --dry-run or --approve or --trigger\n' >&2
          usage
          ;;
      esac
    done
    [ $# -lt 1 ] && { printf 'ERROR: repair requires --dry-run or --approve or --trigger\n' >&2; usage; }
    MODE="$1"; shift

    case "$MODE" in
      --dry-run)
        if [ "$RECONSTRUCT" -eq 1 ]; then
          cmd_repair_dry_run "$REPO" --reconstruct
        else
          cmd_repair_dry_run "$REPO"
        fi
        ;;
      --trigger)
        # repair <repo> --trigger <id> --slug <slug> --dry-run | --approve --revision <sha> --plan-digest <digest>
        [ $# -lt 1 ] && { printf 'ERROR: --trigger requires a trigger id\n' >&2; usage; }
        TRIGGER_ID="$1"; shift
        [ $# -lt 1 ] || [ "$1" != "--slug" ] && { printf 'ERROR: --trigger requires --slug <slug>\n' >&2; usage; }
        shift  # consume --slug
        [ $# -lt 1 ] && { printf 'ERROR: --slug requires a slug value\n' >&2; usage; }
        TRIGGER_SLUG="$1"; shift
        [ $# -lt 1 ] && { printf 'ERROR: --trigger requires --dry-run or --approve\n' >&2; usage; }
        TRIGGER_MODE="$1"; shift
        case "$TRIGGER_MODE" in
          --dry-run)
            cmd_repair_trigger_dry_run "$REPO" "$TRIGGER_ID" "$TRIGGER_SLUG"
            ;;
          --approve)
            [ $# -lt 1 ] && { printf 'ERROR: --approve requires --revision\n' >&2; usage; }
            [ "$1" != "--revision" ] && { printf 'ERROR: expected --revision after --approve\n' >&2; usage; }
            shift
            [ $# -lt 1 ] && { printf 'ERROR: --revision requires a <sha>\n' >&2; usage; }
            REVISION="$1"; shift
            [ $# -lt 1 ] || [ "$1" != "--plan-digest" ] && { printf 'ERROR: --revision requires --plan-digest <digest>\n' >&2; usage; }
            shift
            [ $# -lt 1 ] && { printf 'ERROR: --plan-digest requires a value\n' >&2; usage; }
            DIGEST="$1"; shift
            cmd_repair_trigger_approve "$REPO" "$TRIGGER_ID" "$TRIGGER_SLUG" "$REVISION" "$DIGEST"
            ;;
          *)
            printf 'ERROR: unknown mode after --slug: %s\n' "$TRIGGER_MODE" >&2; usage ;;
        esac
        ;;
      --approve)
        [ $# -lt 1 ] && { printf 'ERROR: --approve requires --revision or --greenfield\n' >&2; usage; }
        APPROVE_MODE="$1"; shift

        case "$APPROVE_MODE" in
          --greenfield)
            cmd_repair_greenfield "$REPO"
            ;;
          --revision)
            [ $# -lt 1 ] && { printf 'ERROR: --revision requires a <sha> argument\n' >&2; usage; }
            REVISION="$1"; shift
            [ $# -lt 1 ] && { printf 'ERROR: --revision requires --plan-digest <digest>\n' >&2; usage; }
            [ "$1" != "--plan-digest" ] && { printf 'ERROR: expected --plan-digest after revision\n' >&2; usage; }
            shift
            [ $# -lt 1 ] && { printf 'ERROR: --plan-digest requires a <digest> argument\n' >&2; usage; }
            DIGEST="$1"; shift
            if [ "$RECONSTRUCT" -eq 1 ]; then
              cmd_repair_approve "$REPO" "$REVISION" "$DIGEST" --reconstruct
            else
              cmd_repair_approve "$REPO" "$REVISION" "$DIGEST"
            fi
            ;;
          *)
            printf 'ERROR: unknown option after --approve: %s\n' "$APPROVE_MODE" >&2
            usage
            ;;
        esac
        ;;
      *)
        printf 'ERROR: unknown repair mode: %s\n' "$MODE" >&2
        usage
        ;;
    esac
    ;;
  *)
    printf 'ERROR: unknown verb: %s\n' "$VERB" >&2
    usage
    ;;
esac
