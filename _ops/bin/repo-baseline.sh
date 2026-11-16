#!/usr/bin/env bash
# _ops/bin/repo-baseline.sh — idempotent CLI for the uniform repo control baseline.
#
# Verbs:
#   repo-baseline.sh list                        eligible/excluded repos + reasons (read-only)
#   repo-baseline.sh verify <repo-path>           read-only baseline status for one repo
#   repo-baseline.sh apply <repo-path> --dry-run  exact file actions + GitHub-control status, no writes
#   repo-baseline.sh apply <repo-path>            render/merge the baseline + install commit-time guards
#   repo-baseline.sh profile pr-automation <verb> explicit opt-in PR-automation lifecycle
#
# See _ops/baseline/README.md for the control-set spec and the hard-exclusion list.
# Style mirrors dev-new-repo.sh / install-identity-guard.sh: set -euo pipefail, lib.sh sourcing,
# clear usage, idempotent re-runs, non-destructive merges. `apply` never commits.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # _ops/bin
# shellcheck source=lib.sh
. "$SCRIPT_DIR/lib.sh"
# shellcheck source=baseline-lib.sh
. "$SCRIPT_DIR/baseline-lib.sh"

usage() {
  cat <<'EOF'
usage:
  repo-baseline.sh list
  repo-baseline.sh verify <repo-path>
  repo-baseline.sh apply <repo-path> [--dry-run]
  repo-baseline.sh native-activation-preflight <repo-path>
  repo-baseline.sh profile pr-automation verify|status <repo-path>
  repo-baseline.sh profile pr-automation phase-b inventory|verify|status|credential-status [repo-path]
  repo-baseline.sh profile pr-automation v3 --help

list/verify observe; apply writes the eligible local file floor only and preserves
repository-owned workflows. Native preflight observes identity and merged sharding.
Historical profile parsers/observations remain available but establish no current
successor qualification. All legacy profile mutation commands, top-level enforce
and reconcile-merge-safety refuse, including dry-run and resume-style invocations.
Repository-owned successor settings/CI/App admission is a separate gate.
See _ops/baseline/README.md for current source policy.
EOF
}

VERB="${1:-}"
[ $# -gt 0 ] && shift

case "$VERB" in
  ""|-h|--help)
    usage
    [ "$VERB" = "" ] && exit 2 || exit 0
    ;;
  native-activation-preflight)
    [ $# -eq 1 ] || { printf 'usage: repo-baseline.sh native-activation-preflight <repo>\n' >&2; exit 2; }
    [ "$(bl_repo_delivery_class "$1")" = native-github ] || { printf 'native identity required\n' >&2; exit 1; }
    bl_verify_native_identity "$1" || { printf 'native identity observation refused\n' >&2; exit 1; }
    ownerrepo="$(bl_ownerrepo_of "$(git -C "$1" remote get-url origin)")"
    sharding_flags=()
    [ "$ownerrepo" != KleinPerkins/machine-monitor ] || sharding_flags=(--require)
    exec python3 "$OM_OPS_DIR/bin/test-sharding.py" verify-remote --repository "$ownerrepo" --ref main --aggregate ci-required "${sharding_flags[@]}"
    ;;
  enforce|reconcile-merge-safety)
    printf 'repo-baseline: REFUSED — retired controller reconciliation and generic settings mutation are disabled; successor controls require repository-owned admission\n' >&2
    exit 1 ;;
  list|verify|apply) : ;;
  profile)
    profile="${1:-}"; [ $# -gt 0 ] && shift
    if [ "$profile" != "pr-automation" ]; then
      printf 'repo-baseline profile: unknown profile: %s\n' "${profile:-<missing>}" >&2
      usage >&2
      exit 2
    fi
    if [ "${1:-}" = "phase-b" ]; then
      shift
      exec python3 "$OM_OPS_DIR/baseline/profiles/pr-automation/fleet.py" "$@"
    fi
    if [ "${1:-}" = "v3" ]; then
      shift
      exec python3 "$OM_OPS_DIR/baseline/profiles/pr-automation/v3/profile.py" "$@"
    fi
    exec python3 "$OM_OPS_DIR/baseline/profiles/pr-automation/profile.py" "$@"
    ;;
  *)
    printf 'repo-baseline: unknown verb: %s\n' "$VERB" >&2
    usage >&2
    exit 2
    ;;
esac

resolve_repo() {
  local arg="$1" repo
  repo="$(cd "$arg" 2>/dev/null && pwd)" || { printf 'repo-baseline: no such directory: %s\n' "$arg" >&2; exit 1; }
  git -C "$repo" rev-parse --show-toplevel >/dev/null 2>&1 || { printf 'repo-baseline: not a git repo: %s\n' "$repo" >&2; exit 1; }
  git -C "$repo" rev-parse --show-toplevel
}

# ---------------------------------------------------------------------------
cmd_list() {
  printf 'repo-baseline: scanning repos under %s\n\n' "$BL_REPO_ROOT"
  printf '%-9s  %-42s  %-32s  %s\n' STATUS PATH OWNER/REPO REASON
  printf '%-9s  %-42s  %-32s  %s\n' --------- ---- ---------- ------
  local n_elig=0 n_excl=0
  while IFS=$'\t' read -r status rel ownerrepo reason; do
    [ -n "$status" ] || continue
    if [ "$status" = ELIGIBLE ]; then n_elig=$((n_elig+1)); else n_excl=$((n_excl+1)); fi
    printf '%-9s  %-42s  %-32s  %s\n' "$status" "$rel" "${ownerrepo:-<none>}" "$reason"
  done < <(bl_discover_and_classify)
  printf '\nSummary: %d eligible, %d excluded.\n' "$n_elig" "$n_excl"
  printf 'Eligible ≠ approved — review this list before running `apply` on any existing repo.\n'
}

# ---------------------------------------------------------------------------
cmd_verify() {
  local repo_arg="${1:-}"
  [ -n "$repo_arg" ] || { printf 'usage: repo-baseline.sh verify <repo-path>\n' >&2; exit 2; }
  local repo; repo="$(resolve_repo "$repo_arg")"
  local delivery_class
  delivery_class="$(bl_repo_delivery_class "$repo")"
  if [ "$delivery_class" = identity-unverified ] ||
      { [ "$delivery_class" = native-github ] && ! bl_native_contracts_absent "$repo"; }; then
    printf 'repo-baseline verify: REFUSED — ambiguous native identity or contradictory runnerless contracts\n' >&2
    return 1
  fi

  local status rel ownerrepo reason
  IFS=$'\t' read -r status rel ownerrepo reason <<<"$(bl_classify_repo "$repo" "$BL_REPO_ROOT")"

  printf 'repo-baseline verify — %s\n' "$rel"
  printf '  origin:      %s\n' "${ownerrepo:-<none>}"
  printf '  eligibility: %s (%s)\n' "$status" "$reason"
  echo
  echo "== Baseline files =="
  local sec_st co_st gi_st rd_st db_st
  sec_st="$(bl_check_managed_file "$repo" "SECURITY.md" bl_render_security_md html)"
  printf '  %-40s %s\n' "SECURITY.md" "$sec_st"
  co_st="$(bl_check_create_only "$repo" ".github/CODEOWNERS")"
  printf '  %-40s %s\n' ".github/CODEOWNERS" "$co_st"
  gi_st="$(bl_check_gitignore_block "$repo")"
  printf '  %-40s %s\n' ".gitignore (managed block)" "$gi_st"
  rd_st="$(bl_check_create_only "$repo" "README.md")"
  printf '  %-40s %s\n' "README.md (create-if-missing)" "$rd_st"
  db_st="$(bl_check_managed_file "$repo" ".github/dependabot.yml" bl_render_dependabot hash)"
  printf '  %-40s %s\n' ".github/dependabot.yml" "$db_st"

  echo
  echo "== Commit-time guard (identity-guard chain) =="
  printf '  %s\n' "$(bl_guard_state "$repo")"

  echo
  echo "== GitHub ruleset controls (read-only) =="
  local gh_status gh_detail
  IFS=$'\t' read -r gh_status gh_detail <<<"$(bl_github_controls "${ownerrepo:-}")"
  printf '  %s — %s\n' "$gh_status" "$gh_detail"
  : # Repository-owned successor settings admission is separate from this observation.

  echo
  printf '== Delivery policy: %s ==\n' "$delivery_class"
  local delivery_status delivery_detail
  IFS=$'\t' read -r delivery_status delivery_detail <<<"$(bl_check_delivery_review_policy "$repo")"
  printf '  %s — %s\n' "$delivery_status" "$delivery_detail"
  printf 'Local baseline files only (not CI/App qualification)\n'
  printf 'Overall: %s\n' "$(bl_overall_verdict "$sec_st" "$co_st" "$gi_st" "$rd_st" "$db_st")"

}

# ---------------------------------------------------------------------------
cmd_apply() {
  local repo_arg="" dry=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) dry=1 ;;
      -h|--help) usage; exit 0 ;;
      -*) printf 'repo-baseline apply: unknown flag: %s\n' "$1" >&2; exit 2 ;;
      *) repo_arg="$1" ;;
    esac
    shift
  done
  [ -n "$repo_arg" ] || { printf 'usage: repo-baseline.sh apply <repo-path> [--dry-run]\n' >&2; exit 2; }
  local repo; repo="$(resolve_repo "$repo_arg")"
  local delivery_class
  delivery_class="$(bl_repo_delivery_class "$repo")"
  if [ "$delivery_class" = identity-unverified ]; then
    printf 'repo-baseline: REFUSING ambiguous native repository identity\n' >&2
    return 1
  fi

  if [ "$delivery_class" = native-github ] && ! bl_native_contracts_absent "$repo"; then
    printf 'repo-baseline: REFUSING native mutation with contradictory runnerless contracts\n' >&2
    return 1
  fi
  case "$delivery_class" in
    retired|excluded) printf 'repo-baseline: REFUSED retired/excluded target\n' >&2; return 1 ;;
  esac
  local status rel ownerrepo reason
  IFS=$'\t' read -r status rel ownerrepo reason <<<"$(bl_classify_repo "$repo" "$BL_REPO_ROOT")"
  if [ "$status" != ELIGIBLE ]; then
    printf 'repo-baseline apply: REFUSING — %s is not eligible (%s)\n' "$rel" "$reason" >&2
    exit 1
  fi

  local sec_st co_st gi_st rd_st db_st
  sec_st="$(bl_check_managed_file "$repo" "SECURITY.md" bl_render_security_md html)"
  co_st="$(bl_check_create_only "$repo" ".github/CODEOWNERS")"
  gi_st="$(bl_check_gitignore_block "$repo")"
  rd_st="$(bl_check_create_only "$repo" "README.md")"
  db_st="$(bl_check_managed_file "$repo" ".github/dependabot.yml" bl_render_dependabot hash)"

  # Real conflicts: a same-named managed whole-file exists without our marker. SECURITY.md CUSTOM
  # is a soft, non-blocking skip (we simply never touch a repo's own custom SECURITY.md).
  local hard_conflicts=()
  [ "$db_st" = CUSTOM ] && hard_conflicts+=(".github/dependabot.yml")

  if [ "${#hard_conflicts[@]}" -gt 0 ] && [ "$dry" -eq 0 ]; then
    printf 'repo-baseline apply: REFUSING — real conflict(s) detected in %s:\n' "$rel" >&2
    local c
    for c in "${hard_conflicts[@]}"; do
      printf '    %s already exists and is not KleinPerkins/dev-managed (no marker found)\n' "$c" >&2
    done
    printf '  Resolve manually (rename/remove the existing file, or add the managed marker) and re-run.\n' >&2
    exit 3
  fi

  echo "repo-baseline apply — $rel"
  [ "$dry" -eq 1 ] && echo "(dry-run — no changes will be made)"
  echo

  plan_action() { printf '  %-42s %s\n' "$1" "$2"; }

  case "$sec_st" in
    MISSING) plan_action "SECURITY.md" "create" ;;
    STALE)   plan_action "SECURITY.md" "refresh (managed, stale)" ;;
    CURRENT) plan_action "SECURITY.md" "skip (current)" ;;
    CUSTOM)  plan_action "SECURITY.md" "skip (exists, not ours — left untouched)" ;;
  esac
  case "$co_st" in
    MISSING) plan_action ".github/CODEOWNERS" "create (default: * @KleinPerkins)" ;;
    PRESENT) plan_action ".github/CODEOWNERS" "skip (already present)" ;;
  esac
  case "$gi_st" in
    MISSING) plan_action ".gitignore (managed block)" "append" ;;
    STALE)   plan_action ".gitignore (managed block)" "refresh (stale)" ;;
    CURRENT) plan_action ".gitignore (managed block)" "skip (current)" ;;
  esac
  case "$rd_st" in
    MISSING) plan_action "README.md" "create (generic placeholder — replace with real docs)" ;;
    PRESENT) plan_action "README.md" "skip (already present)" ;;
  esac
  case "$db_st" in
    MISSING) plan_action ".github/dependabot.yml" "create" ;;
    STALE)   plan_action ".github/dependabot.yml" "refresh (managed, stale)" ;;
    CURRENT) plan_action ".github/dependabot.yml" "skip (current)" ;;
    CUSTOM)  plan_action ".github/dependabot.yml" "CONFLICT — refusing to overwrite" ;;
  esac
  plan_action "commit-time guards" "install-identity-guard.sh (idempotent)"

  echo
  local gh_status gh_detail
  IFS=$'\t' read -r gh_status gh_detail <<<"$(bl_github_controls "${ownerrepo:-}")"
  printf 'GitHub ruleset controls: %s — %s\n' "$gh_status" "$gh_detail"
  printf '(this is a LOCAL-FILE-ONLY apply — it never mutates GitHub settings; repository-owned settings admission remains pending)\n'

  if [ "$dry" -eq 1 ]; then
    echo
    echo "[dry-run] no files were written."
    return 0
  fi

  # Belt-and-suspenders re-check right before writing (classify already gates this; guards against
  # a TOCTOU race with a concurrent session — see the one-writer-per-tree rule).
  if [ -n "$(git -C "$repo" status --porcelain 2>/dev/null)" ]; then
    printf 'repo-baseline apply: REFUSING — %s became dirty since classification; re-run.\n' "$rel" >&2
    exit 1
  fi

  mkdir -p "$repo/.github"

  if [ "$sec_st" = MISSING ] || [ "$sec_st" = STALE ]; then
    bl_render_security_md > "$repo/SECURITY.md"
  fi
  if [ "$co_st" = MISSING ]; then
    bl_render_codeowners > "$repo/.github/CODEOWNERS"
  fi
  if [ "$gi_st" = MISSING ] || [ "$gi_st" = STALE ]; then
    bl_merge_gitignore_block "$repo"
  fi
  if [ "$rd_st" = MISSING ]; then
    bl_render_readme "$(basename "$repo")" > "$repo/README.md"
  fi
  if [ "$db_st" = MISSING ] || [ "$db_st" = STALE ]; then
    bl_render_dependabot > "$repo/.github/dependabot.yml"
  fi

  bash "$SCRIPT_DIR/install-identity-guard.sh" "$repo"

  echo
  echo "repo-baseline apply: files rendered for $rel. Review and commit when ready:"
  printf '  git -C "%s" status\n' "$repo"
  printf '  git -C "%s" add -A && git -C "%s" commit -m "chore: apply uniform repo baseline"\n' "$repo" "$repo"
}

# ---------------------------------------------------------------------------
# Settings admission is repository-owned. Keep legacy function names refusing
# even for shell consumers that source the definitions instead of using the CLI.
cmd_enforce() {
  printf 'repo-baseline: REFUSED retired generic settings mutation; repository-owned admission required\n' >&2
  return 1
}
cmd_reconcile_merge_safety() {
  printf 'repo-baseline: REFUSED retired controller reconciliation\n' >&2
  return 1
}

case "$VERB" in
  list)    cmd_list "$@" ;;
  verify)  cmd_verify "$@" ;;
  apply)   cmd_apply "$@" ;;
  enforce) cmd_enforce "$@" ;;
  reconcile-merge-safety) cmd_reconcile_merge_safety "$@" ;;
esac
