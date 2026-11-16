#!/usr/bin/env bash
# _ops/bin/baseline-lib.sh — shared helpers for the uniform repo control baseline.
#
# Sourced by repo-baseline.sh and dev-doctor.sh so repo classification and per-file compliance
# checks are defined exactly once. See _ops/baseline/README.md for the control-set spec.
# Source it; do not execute it. bash 3.2 compatible (no associative arrays, no namerefs).

BL_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # _ops/bin
# shellcheck source=lib.sh
. "$BL_LIB_DIR/lib.sh"

BL_REPO_ROOT="$OM_REPO_ROOT"
BL_BASELINE_DIR="$OM_OPS_DIR/baseline"
BL_TEMPLATE_DIR="$BL_BASELINE_DIR/template"

BL_MARK_HTML_BEGIN='<!-- BEGIN KleinPerkins/dev baseline (managed by KleinPerkins/dev; do not hand-edit — see _ops/baseline/README.md in KleinPerkins/dev) -->'
BL_MARK_HTML_END='<!-- END KleinPerkins/dev baseline -->'
BL_MARK_HASH_BEGIN='# BEGIN KleinPerkins/dev baseline (managed by KleinPerkins/dev; do not hand-edit — see _ops/baseline/README.md in KleinPerkins/dev)'
BL_MARK_HASH_END='# END KleinPerkins/dev baseline'

# Commit-time guard marker (mirrors dev-doctor.sh's GUARD_MARKER; kept identical intentionally).
BL_GUARD_MARKER='managed-by: KleinPerkins/dev identity-guard'

# ---------------------------------------------------------------------------
# v2: GitHub-side ruleset enforcement (the mutating half — see `enforce` in repo-baseline.sh).
# Reserved, stable ruleset names so `enforce` can find-and-update its own rulesets idempotently
# without colliding with anything hand-created. Never adopt a same-named ruleset blindly — the
# committed state record (BL_STATE_DIR) is the fingerprint `enforce` diffs against.
# ---------------------------------------------------------------------------
BL_RULESET_NAME='kleinperkins-dev-baseline'
BL_RULESET_TAG_NAME='kleinperkins-dev-baseline-tags'
BL_STATE_DIR="$BL_BASELINE_DIR/state"

# ---------------------------------------------------------------------------
# D3 (2026-07-30): runnerless pr-automation v3 merge-safety ruleset + its PERMANENT repo-admin
# break-glass bypass. Distinct from the baseline history ruleset above (different name, different
# per-repo id). profile.py's shared resolver applies repository overlays to the one template and
# verifies controller.json's base/override pins. The admin bypass (RepositoryRole admin = actor_id
# 5, bypass_mode pull_request) is app-redacted — the verifier/reviewer App tokens never see it, so
# changing only that bypass leaves the app-visible layer unchanged.
# These helpers therefore run only from the operator/dev-doctor context (owner `gh` auth), which
# CAN read bypass_actors, never from a headless App token.
# ---------------------------------------------------------------------------
BL_V3_DIR="$BL_BASELINE_DIR/profiles/pr-automation/v3"
BL_MERGE_SAFETY_NAME='kleinperkins-merge-safety'
BL_MERGE_SAFETY_BYPASS_ROLE_ID=5

# ---------------------------------------------------------------------------
# D4 BRIDGE (2026-07-31): kleinperkins-review-gate DISABLED placeholder. The DEPLOYED controller
# binary (v0.3.1) requires TWO managed branch rulesets (merge-safety + review-gate) at its
# ruleset_ownership preflight; D1(b) excised review-gate, which broke EVERY non-draft PR fleet-wide.
# Until Path A (a controller release that accepts a single merge-safety ruleset) ships, we retain a
# DISABLED review-gate: it satisfies the binary's 2-ruleset COUNT while only merge-safety enforces
# (a disabled managed ruleset is counted for ownership but EXCLUDED from the ACTIVE fingerprint set,
# so the app-visible set stays {903f} with NO config/base-doc change). Named distinctly from the
# retired ACTIVE review-gate template; this bridge NEVER creates an enforcing review-gate. Remove
# the whole bridge (constants + the two helpers below + the reconcile call site) when Path A lands.
# ---------------------------------------------------------------------------
BL_REVIEW_GATE_NAME='kleinperkins-review-gate'
BL_REVIEW_GATE_PLACEHOLDER_TMPL="$BL_V3_DIR/review-gate.placeholder.ruleset.json.tmpl"

# ---------------------------------------------------------------------------
# Origin parsing (duplicated in miniature from dev-doctor.sh's ownerrepo_of/owner_of on purpose —
# small, stable, and keeps this library standalone-sourceable without reshaping dev-doctor.sh).
# ---------------------------------------------------------------------------
bl_ownerrepo_of() {
  local url="$1" rest
  case "$url" in
    *github.com[:/]*) rest="${url#*github.com}"; rest="${rest#[:/]}" ;;
    *) printf ''; return ;;
  esac
  rest="${rest%.git}"
  printf '%s' "$rest" | awk -F/ 'NF>=2{print $1"/"$2; next}{print $0}'
}
bl_owner_of() { bl_ownerrepo_of "$1" | awk -F/ '{print $1}'; }

# Delivery is orthogonal to baseline eligibility. Only exact approved product
# identities may use native delivery; no owner-wide/public-repository exemption.
bl_delivery_class() {
  python3 "$BL_BASELINE_DIR/delivery-policy.py" classify "$1"
}

bl_repo_delivery_class() {
  local origins origin count=0 repository="" parsed
  origins="$(git -C "$1" config --get-all remote.origin.url 2>/dev/null || true)"
  while IFS= read -r origin; do
    [ -n "$origin" ] || continue
    count=$((count + 1))
    case "$origin" in
      git@github.com:KleinPerkins/*.git|https://github.com/KleinPerkins/*|ssh://git@github.com/KleinPerkins/*.git)
        parsed="$(bl_ownerrepo_of "$origin")"
        case "$origin" in
          "git@github.com:$parsed.git"|"https://github.com/$parsed"|"https://github.com/$parsed.git"|"ssh://git@github.com/$parsed.git") repository="$parsed" ;;
          *) printf 'identity-unverified\n'; return ;;
        esac ;;
      *) printf 'identity-unverified\n'; return ;;
    esac
  done <<<"$origins"
  if [ "$count" -eq 1 ]; then bl_delivery_class "$repository"
  else printf 'identity-unverified\n'; fi
}

# Before native-target GitHub mutation, bind live identity to the born-v2 receipt
# projection. This reads configuration only, never secret values or product data.
bl_verify_native_identity() {
  local live repository
  [ "$(bl_repo_delivery_class "$1")" = native-github ] || return 1
  [ "${GH_HOST:-github.com}" = github.com ] || return 1
  repository="$(bl_ownerrepo_of "$(git -C "$1" remote get-url origin)")"
  live="$(gh api --hostname github.com "repos/$repository" 2>/dev/null)" || return 1
  bl_validate_native_identity "$1" "$live"
}

bl_validate_native_identity() {
  local repository
  [ "$(bl_repo_delivery_class "$1")" = native-github ] || return 1
  repository="$(bl_ownerrepo_of "$(git -C "$1" remote get-url origin)")"
  python3 - "$1" "$2" "$repository" <<'NATIVE_IDENTITY'
import json, os, stat, sys
from pathlib import Path

def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result

try:
    root = Path(sys.argv[1])
    if (root / ".planning").is_symlink():
        raise ValueError("symlinked profile directory")
    fd = os.open(root / ".planning/doc-warden.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "r") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("profile is not a regular file")
        profile = json.load(handle, object_pairs_hook=unique)
    live = json.loads(sys.argv[2], object_pairs_hook=unique)
    identity = profile.get("github_repository_id")
    if (type(identity) is not int or identity <= 0
            or type(live.get("id")) is not int or live["id"] != identity
            or live.get("full_name") != sys.argv[3]
            or sys.argv[3] not in {"KleinPerkins/shadow-sync", "KleinPerkins/machine-monitor"}
            or identity != {"KleinPerkins/shadow-sync": 1442961455, "KleinPerkins/machine-monitor": 1449284973}[sys.argv[3]]
            or live.get("visibility") != "public"):
        raise ValueError("identity mismatch")
except (OSError, ValueError, TypeError, AttributeError):
    raise SystemExit(1)
NATIVE_IDENTITY
}

# A successful PATCH/PUT is not an observation. Bind the read-back to the same
# recorded repository and compare all intended settings/rules before success.
bl_verify_native_applied_settings() {
  local repo="$1" branch="$2" branch_id="$3" tag_id="${4:-}" live rules tag_rules="null" expected expected_tag="null" repository
  [ "$(bl_repo_delivery_class "$repo")" = native-github ] || return 1
  [ "${GH_HOST:-github.com}" = github.com ] || return 1
  repository="$(bl_ownerrepo_of "$(git -C "$repo" remote get-url origin)")"
  live="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api --hostname github.com "repos/$repository")" || return 1
  bl_validate_native_identity "$repo" "$live" || return 1
  case "$branch_id" in ''|*[!0-9]*|0*) return 1 ;; esac
  rules="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api --hostname github.com "repos/$repository/rulesets/$branch_id")" || return 1
  expected="$(bl_render_ruleset_branch "$branch")"
  if [ -n "$tag_id" ]; then
    case "$tag_id" in *[!0-9]*|0*) return 1 ;; esac
    tag_rules="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api --hostname github.com "repos/$repository/rulesets/$tag_id")" || return 1
    expected_tag="$(bl_render_ruleset_tag)"
  fi
  python3 - "$live" "$branch" "$branch_id" "$rules" "$expected" "$tag_id" "$tag_rules" "$expected_tag" <<'NATIVE_READBACK'
import json, sys

def normalize(value):
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return sorted((normalize(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    return value

def ruleset(observed, expected, identity):
    if type(observed.get('id')) is not int or observed['id'] != int(identity):
        raise ValueError('ruleset identity mismatch')
    actual = {key: observed.get(key) for key in expected}
    if normalize(actual) != normalize(expected):
        raise ValueError('ruleset semantics mismatch')
    return {'id': observed['id'], **normalize(actual)}

try:
    live, observed, expected = map(json.loads, (sys.argv[1], sys.argv[4], sys.argv[5]))
    settings = dict(allow_squash_merge=True, allow_merge_commit=False,
                    allow_rebase_merge=False, allow_auto_merge=True,
                    delete_branch_on_merge=True)
    if live.get('default_branch') != sys.argv[2] or sys.argv[2] != 'main':
        raise ValueError('default branch mismatch')
    if any(type(live.get(key)) is not bool or live[key] != value for key, value in settings.items()):
        raise ValueError('merge settings mismatch')
    receipt = dict(schema='dev-native-delivery-readback/v1', repository_id=live['id'],
                   repository=live['full_name'], visibility=live['visibility'],
                   default_branch=live['default_branch'], settings=settings,
                   branch_ruleset=ruleset(observed, expected, sys.argv[3]))
    if sys.argv[6]:
        receipt['tag_ruleset'] = ruleset(json.loads(sys.argv[7]), json.loads(sys.argv[8]), sys.argv[6])
    print(json.dumps(receipt, sort_keys=True, separators=(',', ':')))
except (ValueError, KeyError, TypeError, AttributeError) as error:
    print('native settings read-back refused: ' + str(error), file=sys.stderr)
    raise SystemExit(1)
NATIVE_READBACK
}

# Inert runnerless contracts are still contradictory in the native product.
bl_native_contracts_absent() {
  local relative
  for relative in .github/pr-automation.json .github/pr-verification.json .github/pr-recipe.json .github/pr-automation.lock.json; do
    [ ! -e "$1/$relative" ] && [ ! -L "$1/$relative" ] || return 1
  done
  # A partial stage may leave only the managed ownership block behind.
  if [ -L "$1/.github/CODEOWNERS" ]; then return 1; fi
  if [ -e "$1/.github/CODEOWNERS" ]; then
    [ -f "$1/.github/CODEOWNERS" ] || return 1
    ! grep -F -x -q -e '# BEGIN kleinperkins runnerless PR automation v3' \
      -e '# END kleinperkins runnerless PR automation v3' "$1/.github/CODEOWNERS" || return 1
  fi
}

bl_check_delivery_review_policy() {
  python3 "$BL_BASELINE_DIR/delivery-policy.py" observe "$1"
}

# Protect the supported legacy/v3 dispatcher too, including --name overrides.
bl_refuse_native_profile_targets() {
  local argument candidate="" awaiting=""
  for argument in "$@"; do
    if [ "$awaiting" = path ]; then candidate="$argument"; awaiting=""
    elif [ "$awaiting" = repository ]; then
      awaiting=""
      if [ "$(bl_delivery_class "$argument")" != runnerless-default ]; then
        printf 'repo-baseline: REFUSING runnerless profile for native delivery identity\n' >&2
        return 1
      fi
      continue
    else
      case "$argument" in
        --repo-root|--target-root) awaiting=path; continue ;;
        --repo) awaiting=repository; continue ;;
        --repo-root=*|--target-root=*) candidate="${argument#*=}" ;;
        --repo=*)
          [ "$(bl_delivery_class "${argument#*=}")" = runnerless-default ] || return 1
          continue ;;
        -*) continue ;;
        *) [ -d "$argument/.git" ] || [ -f "$argument/.git" ] || continue; candidate="$argument" ;;
      esac
    fi
    if [ "$(bl_repo_delivery_class "$candidate")" != runnerless-default ]; then
      printf 'repo-baseline: REFUSING runnerless profile for native delivery identity\n' >&2
      return 1
    fi
  done
}

# ---------------------------------------------------------------------------
# Repo discovery — mirrors dev-doctor.sh's list_repos() (bounded-depth find, heavy-dir pruning,
# plus linked worktrees discovered from each known repo's `git worktree list`).
# ---------------------------------------------------------------------------
bl_discover_repos() {
  local root="${1:-$BL_REPO_ROOT}"
  {
    find "$root" -maxdepth 6 \
      \( -name node_modules -o -name .venv -o -name venv -o -name .next -o -name dist -o -name build -o -name target \) -prune \
      -o -type d -name .git -print 2>/dev/null \
    | while IFS= read -r gd; do dirname "$gd"; done

    find "$root" -maxdepth 6 \
      \( -name node_modules -o -name .venv -o -name venv -o -name .next -o -name dist -o -name build -o -name target \) -prune \
      -o -type d -name .git -print 2>/dev/null \
    | while IFS= read -r gd; do
        repo="$(dirname "$gd")"
        git -C "$repo" worktree list --porcelain 2>/dev/null \
          | awk '/^worktree /{sub(/^worktree /,""); print}'
      done
  } | sort -u
}

# bl_classify_repo <repo-abs-path> <root-abs-path>
# -> "STATUS\trel\townerrepo\treason" (STATUS: ELIGIBLE|EXCLUDED). Read-only; no writes, no network.
bl_classify_repo() {
  local repo="$1" root="$2"
  local rel; if [ "$repo" = "$root" ]; then rel="."; else rel="${repo#"$root"/}"; fi

  local origin ownerrepo owner owner_lc ownerrepo_lc
  origin="$(git -C "$repo" config --get remote.origin.url 2>/dev/null || true)"
  ownerrepo="$(bl_ownerrepo_of "$origin")"
  owner="$(bl_owner_of "$origin")"
  owner_lc="$(printf '%s' "$owner" | tr '[:upper:]' '[:lower:]')"
  ownerrepo_lc="$(printf '%s' "$ownerrepo" | tr '[:upper:]' '[:lower:]')"

  if [ "$rel" = "." ]; then
    printf 'EXCLUDED\t%s\t%s\t%s\n' "$rel" "${ownerrepo:-<none>}" "umbrella repo (~/dev itself)"
    return
  fi
  case "$rel" in
    affirm/vendor/*)
      printf 'EXCLUDED\t%s\t%s\t%s\n' "$rel" "${ownerrepo:-<none>}" "affirm/vendor — reference-only, read-only clone"
      return
      ;;
  esac
  if [ "$ownerrepo_lc" = "affirm/card-platform-product" ]; then
    printf 'EXCLUDED\t%s\t%s\t%s\n' "$rel" "$ownerrepo" "cpp — already governed by its own _ops model; do not alter"
    return
  fi
  if [ "$ownerrepo_lc" = "kleinperkins/chaos-scheduler" ]; then
    printf 'EXCLUDED\t%s\t%s\t%s\n' "$rel" "$ownerrepo" "chaos-scheduler — hard-excluded by the baseline plan"
    return
  fi
  if [ -z "$origin" ]; then
    printf 'EXCLUDED\t%s\t%s\t%s\n' "$rel" "<none>" "no origin remote"
    return
  fi
  if [ "$owner_lc" != "kleinperkins" ]; then
    printf 'EXCLUDED\t%s\t%s\t%s\n' "$rel" "$ownerrepo" "external origin (owner=${owner:-<none>} != KleinPerkins)"
    return
  fi
  local status_out
  status_out="$(git -C "$repo" status --porcelain 2>/dev/null || true)"
  if [ -n "$status_out" ]; then
    printf 'EXCLUDED\t%s\t%s\t%s\n' "$rel" "$ownerrepo" "dirty working tree"
    return
  fi
  # symbolic-ref (not rev-parse --abbrev-ref) so a brand-new unborn-HEAD repo (e.g. mid dev-new-repo
  # scaffolding, before the first commit) correctly resolves to its target branch instead of "HEAD".
  local branch
  branch="$(git -C "$repo" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
  if [ -z "$branch" ]; then
    printf 'EXCLUDED\t%s\t%s\t%s\n' "$rel" "$ownerrepo" "detached HEAD"
    return
  fi
  if [ "$branch" != "main" ]; then
    printf 'EXCLUDED\t%s\t%s\t%s\n' "$rel" "$ownerrepo" "not on a clean main checkout (branch=$branch)"
    return
  fi
  printf 'ELIGIBLE\t%s\t%s\t%s\n' "$rel" "$ownerrepo" "eligible"
}

# bl_discover_and_classify [root] -> classify every discovered repo, sorted by rel path.
bl_discover_and_classify() {
  local root="${1:-$BL_REPO_ROOT}"
  local repo
  while IFS= read -r repo; do
    [ -n "$repo" ] || continue
    bl_classify_repo "$repo" "$root"
  done < <(bl_discover_repos "$root") | sort -t$'\t' -k2,2
}

# ---------------------------------------------------------------------------
# Render functions — one static payload per managed file (no per-repo variables except README).
# ---------------------------------------------------------------------------
bl_render_security_md()    { cat "$BL_TEMPLATE_DIR/SECURITY.md"; }
bl_render_codeowners()     { cat "$BL_TEMPLATE_DIR/CODEOWNERS"; }
bl_render_dependabot()     { cat "$BL_TEMPLATE_DIR/dependabot.yml"; }

# bl_render_ruleset_branch <default_branch> -> the branch-ruleset JSON payload, on stdout.
bl_render_ruleset_branch() {
  local branch="${1:-}"
  [ -n "$branch" ] || return 2
  sed "s/{{DEFAULT_BRANCH}}/$branch/g" "$BL_TEMPLATE_DIR/github/ruleset-branch.json.tmpl"
}
# bl_render_ruleset_tag -> the tag-ruleset JSON payload (no substitution needed), on stdout.
bl_render_ruleset_tag() { cat "$BL_TEMPLATE_DIR/github/ruleset-tag.json.tmpl"; }

# bl_render_merge_safety <default_branch> <repository_id> <owner/repo> -> the v3 merge-safety payload
# (rulesets-API shape, incl. the permanent RepositoryRole:5 pull_request admin bypass), on stdout.
# profile.py's one repository resolver derives the base template overlay and both fingerprints; this
# shell layer never forks the projection logic.
bl_render_merge_safety() {
  local branch="${1:-}" repository_id="${2:-}" ownerrepo="${3:-}"
  [ -n "$branch" ] && [ -n "$repository_id" ] && [ -n "$ownerrepo" ] || return 2
  python3 "$BL_V3_DIR/profile.py" resolve-merge-safety \
    --repository-id "$repository_id" \
    --repo "$ownerrepo" \
    --default-branch "$branch" \
    --output ruleset
}

# bl_describe_merge_safety_payload <payload-file> -> operator-facing, deterministic description of
# the already-resolved payload. This never selects or synthesizes Checks: profile.py's shared
# repository resolver remains the sole projection authority, and this helper only renders its JSON.
bl_describe_merge_safety_payload() {
  local payload="$1"
  python3 - "$payload" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    ruleset = json.load(handle)

rules = ruleset.get("rules")
if not isinstance(rules, list):
    raise SystemExit("resolved ruleset has no rules list")
required = [
    rule for rule in rules
    if isinstance(rule, dict) and rule.get("type") == "required_status_checks"
]
if len(required) != 1:
    raise SystemExit("resolved ruleset must contain exactly one required-status rule")
checks = (required[0].get("parameters") or {}).get("required_status_checks")
if not isinstance(checks, list) or not checks:
    raise SystemExit("resolved ruleset has no required Check set")

print("  resolved required Check set (full replacement):")
for check in checks:
    if (
        not isinstance(check, dict)
        or not isinstance(check.get("context"), str)
        or not isinstance(check.get("integration_id"), int)
    ):
        raise SystemExit("resolved ruleset contains an invalid required Check")
    print(f"    - context={check['context']} integration_id={check['integration_id']}")

print("  resolved non-required protections preserved by projection and written by full PUT:")
non_required = sorted(
    (rule for rule in rules if isinstance(rule, dict) and rule.get("type") != "required_status_checks"),
    key=lambda rule: (
        str(rule.get("type")),
        json.dumps(rule, sort_keys=True, separators=(",", ":")),
    ),
)
for rule in non_required:
    line = f"    - type={rule.get('type')}"
    if "parameters" in rule:
        line += " parameters=" + json.dumps(
            rule["parameters"], sort_keys=True, separators=(",", ":")
        )
    print(line)

print(
    "  resolved scope preserved by projection and written by full PUT: "
    f"target={ruleset.get('target')} enforcement={ruleset.get('enforcement')}"
)
print(
    "    conditions="
    + json.dumps(ruleset.get("conditions"), sort_keys=True, separators=(",", ":"))
)
print(
    "    bypass_actors="
    + json.dumps(ruleset.get("bypass_actors"), sort_keys=True, separators=(",", ":"))
)
PY
}

# --- D4 BRIDGE helpers (2026-07-31) — remove when Path A lands (see BL_REVIEW_GATE_NAME note). ---
# bl_render_review_gate_placeholder <branch> -> the DISABLED review-gate bridge body. enforcement is
# "disabled" in the template, so this ruleset never enforces; it exists only to satisfy the deployed
# controller's two-managed-ruleset ownership count.
bl_render_review_gate_placeholder() {
  local branch="${1:-}"
  [ -n "$branch" ] || return 2
  sed "s/{{DEFAULT_BRANCH}}/$branch/g" "$BL_REVIEW_GATE_PLACEHOLDER_TMPL"
}

# bl_ensure_review_gate_placeholder <owner/repo> <branch> -> idempotently ensure a DISABLED
# kleinperkins-review-gate exists so the controller's ruleset_ownership preflight (which requires the
# merge-safety + review-gate PAIR) passes. SKIP-IF-PRESENT: an existing review-gate of any
# enforcement is left untouched (we never PUT a possibly-intentional active one back to disabled);
# only a MISSING one is POST-created disabled. Prints one status line.
bl_ensure_review_gate_placeholder() {
  local ownerrepo="$1" branch="${2:-}" existing payload resp new_id
  [ -n "$ownerrepo" ] && [ -n "$branch" ] || {
    printf 'review-gate bridge: owner/repo and verified default branch are required\n'
    return 1
  }
  existing="$(bl_ruleset_find "$ownerrepo" "$BL_REVIEW_GATE_NAME")"
  if [ -n "$existing" ]; then
    printf 'review-gate bridge: present (id %s) — skipped\n' "$existing"
    return 0
  fi
  payload="$(mktemp)"
  bl_render_review_gate_placeholder "$branch" > "$payload"
  if ! resp="$(bl_gh_timeout "${BL_GH_TIMEOUT:-15}" gh api -X POST "repos/$ownerrepo/rulesets" --input "$payload" 2>&1)"; then
    printf 'review-gate bridge: FAILED to create disabled placeholder: %s\n' "$(printf '%s' "$resp" | head -1)"
    rm -f "$payload"; return 1
  fi
  rm -f "$payload"
  new_id="$(printf '%s' "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)"
  printf 'review-gate bridge: created DISABLED placeholder (id %s)\n' "$new_id"
}

# bl_app_visible_fingerprints <repository_id> <owner/repo> <default_branch> -> resolved compact JSON.
bl_app_visible_fingerprints() {
  [ -n "${1:-}" ] && [ -n "${2:-}" ] && [ -n "${3:-}" ] || return 2
  python3 "$BL_V3_DIR/profile.py" resolve-merge-safety \
    --repository-id "$1" --repo "$2" --default-branch "$3" \
    --output runtime-app-visible 2>/dev/null
}

# bl_operator_full_fingerprints <repository_id> <owner/repo> <default_branch> -> resolved compact JSON.
bl_operator_full_fingerprints() {
  [ -n "${1:-}" ] && [ -n "${2:-}" ] && [ -n "${3:-}" ] || return 2
  python3 "$BL_V3_DIR/profile.py" resolve-merge-safety \
    --repository-id "$1" --repo "$2" --default-branch "$3" \
    --output operator-full 2>/dev/null
}

bl_render_gitignore_block() {
  printf '%s\n' "$BL_MARK_HASH_BEGIN"
  cat "$BL_TEMPLATE_DIR/gitignore-block.txt"
  printf '%s\n' "$BL_MARK_HASH_END"
}
bl_render_readme() {
  local name="$1"
  sed "s/{{REPO_NAME}}/$name/g" "$BL_TEMPLATE_DIR/README.md.tmpl"
}

# ---------------------------------------------------------------------------
# Compliance checks — MISSING | CURRENT | STALE | CUSTOM (managed files);
#                      MISSING | PRESENT              (create-if-missing files).
# ---------------------------------------------------------------------------

# bl_check_managed_file <repo> <relpath> <render_fn_name> <html|hash>
bl_check_managed_file() {
  local repo="$1" relpath="$2" render_fn="$3" markerstyle="$4"
  local f="$repo/$relpath"
  [ -f "$f" ] || { echo MISSING; return; }
  local mark
  if [ "$markerstyle" = html ]; then mark="$BL_MARK_HTML_BEGIN"; else mark="$BL_MARK_HASH_BEGIN"; fi
  if grep -qF "$mark" "$f" 2>/dev/null; then
    if diff -q <("$render_fn") "$f" >/dev/null 2>&1; then echo CURRENT; else echo STALE; fi
  else
    echo CUSTOM
  fi
}

# bl_check_create_only <repo> <relpath> -> MISSING | PRESENT
bl_check_create_only() {
  local repo="$1" relpath="$2"
  if [ -f "$repo/$relpath" ]; then echo PRESENT; else echo MISSING; fi
}

# bl_extract_block <file> <begin> <end> -> the block region (BEGIN..END inclusive), or nothing.
bl_extract_block() {
  local file="$1" b="$2" e="$3"
  [ -f "$file" ] || return 0
  awk -v b="$b" -v e="$e" '
    index($0,b){inblk=1}
    inblk{print}
    index($0,e){inblk=0}
  ' "$file"
}

# bl_check_gitignore_block <repo> -> MISSING | CURRENT | STALE
bl_check_gitignore_block() {
  local repo="$1" f="$repo/.gitignore"
  [ -f "$f" ] || { echo MISSING; return; }
  if ! grep -qF "$BL_MARK_HASH_BEGIN" "$f" 2>/dev/null; then echo MISSING; return; fi
  local extracted expected
  extracted="$(bl_extract_block "$f" "$BL_MARK_HASH_BEGIN" "$BL_MARK_HASH_END")"
  expected="$(bl_render_gitignore_block)"
  if [ "$extracted" = "$expected" ]; then echo CURRENT; else echo STALE; fi
}

# bl_merge_gitignore_block <repo> — writes/refreshes the managed block, preserving everything else.
bl_merge_gitignore_block() {
  local repo="$1" f="$repo/.gitignore" stripped trimmed
  stripped="$(mktemp)"; trimmed="$(mktemp)"
  if [ -f "$f" ]; then
    awk -v b="$BL_MARK_HASH_BEGIN" -v e="$BL_MARK_HASH_END" '
      index($0,b){inblk=1; next}
      index($0,e){inblk=0; next}
      inblk{next}
      {print}
    ' "$f" > "$stripped"
  else
    : > "$stripped"
  fi
  awk 'NF{last=NR} {buf[NR]=$0} END{for(i=1;i<=last;i++) print buf[i]}' "$stripped" > "$trimmed"
  {
    if [ -s "$trimmed" ]; then cat "$trimmed"; printf '\n'; fi
    bl_render_gitignore_block
  } > "$f"
  rm -f "$stripped" "$trimmed"
}

# bl_overall_verdict <sec> <codeowners> <gitignore> <readme> <dependabot>
# -> COMPLIANT | PARTIAL | MISSING
bl_overall_verdict() {
  local sec="$1" co="$2" gi="$3" rd="$4" db="${5:-CURRENT}"
  local core_total=3 core_missing=0 core_bad=0 v
  for v in "$sec" "$gi" "$db"; do
    case "$v" in
      MISSING) core_missing=$((core_missing+1)) ;;
      STALE|CUSTOM) core_bad=$((core_bad+1)) ;;
    esac
  done
  local aux_missing=0 v
  for v in "$co" "$rd"; do
    [ "$v" = MISSING ] && aux_missing=$((aux_missing+1))
  done
  # MISSING = none of the baseline-specific artifacts exist yet (never applied here). README/
  # CODEOWNERS presence is incidental (most repos already have a README) so it does not, by
  # itself, prevent a MISSING verdict — only the three baseline-authored core files do.
  if [ "$core_missing" -eq "$core_total" ]; then
    echo MISSING
  elif [ "$core_missing" -eq 0 ] && [ "$core_bad" -eq 0 ] && [ "$aux_missing" -eq 0 ]; then
    echo COMPLIANT
  else
    echo PARTIAL
  fi
}

# bl_baseline_verdict <repo> -> convenience wrapper running all five checks + the overall verdict.
bl_baseline_verdict() {
  local repo="$1"
  local sec co gi rd db
  sec="$(bl_check_managed_file "$repo" "SECURITY.md" bl_render_security_md html)"
  co="$(bl_check_create_only "$repo" ".github/CODEOWNERS")"
  gi="$(bl_check_gitignore_block "$repo")"
  rd="$(bl_check_create_only "$repo" "README.md")"
  db="$(bl_check_managed_file "$repo" ".github/dependabot.yml" bl_render_dependabot hash)"
  bl_overall_verdict "$sec" "$co" "$gi" "$rd" "$db"
}

# ---------------------------------------------------------------------------
# Commit-time guard state — mirrors dev-doctor.sh's guard_state() (kept separate on purpose: this
# copy is standalone-sourceable by repo-baseline.sh without reshaping dev-doctor.sh's internals).
# ---------------------------------------------------------------------------
bl_guard_state() {
  local repo="$1" hp gd hooks
  git -C "$repo" rev-parse --show-toplevel >/dev/null 2>&1 || { printf 'na'; return; }
  gd="$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"
  hp="$(git -C "$repo" config --get core.hooksPath 2>/dev/null || true)"
  if [ -n "$hp" ]; then
    case "$hp" in /*) hooks="$hp" ;; *) hooks="$repo/$hp" ;; esac
    if grep -qF "$BL_GUARD_MARKER" "$hooks/pre-commit" 2>/dev/null; then printf 'active'; return; fi
    case "$hp" in *.husky*|*lefthook*) printf 'foreign-hookspath:%s' "$hp" ;; *) printf 'inert-hookspath:%s' "$hp" ;; esac
    return
  fi
  if grep -qF "$BL_GUARD_MARKER" "$gd/hooks/pre-commit" 2>/dev/null; then printf 'active'; else printf 'missing'; fi
}

# ---------------------------------------------------------------------------
# GitHub branch-protection controls — READ-ONLY reporting via `gh api`. Never mutates settings.
# Bounded by a python3 subprocess timeout (mirrors dev-doctor.sh's git_quick) so an offline/slow
# network can't hang list/verify/apply.
# ---------------------------------------------------------------------------
bl_gh_timeout() {
  local t="$1"; shift
  python3 - "$t" "$@" <<'PY'
import subprocess, sys
timeout = float(sys.argv[1])
args = sys.argv[2:]
try:
    proc = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
except subprocess.TimeoutExpired:
    sys.exit(124)
except FileNotFoundError:
    sys.exit(127)
sys.stdout.write(proc.stdout)
sys.stderr.write(proc.stderr)
sys.exit(proc.returncode)
PY
}

# bl_github_controls <owner/repo> -> "STATUS\tdetail"
#   STATUS: ENFORCED | REQUIRED | UNENFORCED_PLAN_LIMIT | UNKNOWN
#
# v2: primary signal is the modern Rulesets API (what `enforce` actually creates), not the legacy
# classic branch-protection endpoint (what v1 only ever read). A private free-plan repo 403s on
# `GET rulesets` exactly like it did on classic protection — GitHub Pro is what turns that into a
# real (even if empty) list. Read-only: this function only ever GETs.
bl_github_controls() {
  local ownerrepo="$1"
  if [ -z "$ownerrepo" ]; then printf 'UNKNOWN\tno origin remote to check\n'; return; fi
  if ! command -v gh >/dev/null 2>&1; then printf 'UNKNOWN\tgh CLI not found\n'; return; fi
  if ! bl_gh_timeout 5 gh auth status >/dev/null 2>&1; then
    printf 'UNKNOWN\tgh not authenticated (run: gh auth login)\n'; return
  fi
  local out rc
  out="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api "repos/$ownerrepo/rulesets" 2>&1)"; rc=$?
  if [ "$rc" -eq 124 ]; then
    printf 'UNKNOWN\tgh api timed out\n'; return
  fi
  if [ "$rc" -ne 0 ]; then
    if printf '%s' "$out" | grep -qi 'Upgrade to GitHub Pro'; then
      printf 'UNENFORCED_PLAN_LIMIT\t403 — private free-plan repo; rulesets unavailable\n'
    else
      printf 'UNKNOWN\tgh api error: %s\n' "$(printf '%s' "$out" | head -1)"
    fi
    return
  fi
  local match
  match="$(printf '%s' "$out" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = []
for r in data:
    if r.get('name') == '$BL_RULESET_NAME':
        print(str(r.get('id', '')) + ' ' + str(r.get('enforcement', '')))
        break
" 2>/dev/null)"
  if [ -n "$match" ]; then
    local rs_id="${match%% *}" rs_enf="${match#* }"
    if [ "$rs_enf" = "active" ]; then
      printf 'ENFORCED\truleset "%s" active on its configured branch target (id %s)\n' "$BL_RULESET_NAME" "$rs_id"
    else
      printf 'REQUIRED\truleset "%s" present but not active (enforcement=%s) — re-run enforce\n' "$BL_RULESET_NAME" "$rs_enf"
    fi
  else
    printf 'REQUIRED\trulesets settable, not yet applied (run: repo-baseline.sh enforce)\n'
  fi
}

# ---------------------------------------------------------------------------
# D2 (2026-07-30): review-policy drift detector — READ-ONLY. Independent of ruleset NAME or
# provenance: queries GitHub's EFFECTIVE branch-rules endpoint (the same aggregated view GitHub
# itself merges from every active ruleset that targets the branch) and flags ANY `pull_request`
# rule requiring human approval, from ANY source ruleset. This is deliberately not a check for a
# specific reserved ruleset name (contrast `bl_github_controls` above, which looks for our own
# `kleinperkins-dev-baseline` by name) — it is defense-in-depth against a required-review control
# reappearing via ANY path: a hand-created ruleset, classic branch protection, or a frozen/legacy
# tool re-run (see D1(b), _ops/baseline/profiles/pr-automation/v3/README.md — the review-gate
# ruleset that used to impose this was excised fleet-wide precisely because it blocks the
# reviewer App's squash auto-merge; this is the tripwire that catches it coming back).
#
# bl_check_no_required_reviews <owner/repo> -> "STATUS\tdetail"
#   STATUS: CLEAN | REVIEW_DRIFT | UNKNOWN
bl_check_no_required_reviews() {
  local ownerrepo="$1"
  if [ -z "$ownerrepo" ]; then printf 'UNKNOWN\tno origin remote to check\n'; return; fi
  if ! command -v gh >/dev/null 2>&1; then printf 'UNKNOWN\tgh CLI not found\n'; return; fi
  if ! bl_gh_timeout 5 gh auth status >/dev/null 2>&1; then
    printf 'UNKNOWN\tgh not authenticated (run: gh auth login)\n'; return
  fi
  local branch; branch="$(bl_default_branch "$ownerrepo")"
  if [ -z "$branch" ]; then
    printf 'UNKNOWN\tlive default branch lookup failed\n'
    return
  fi
  local out rc
  out="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api "repos/$ownerrepo/rules/branches/$branch" 2>&1)"; rc=$?
  if [ "$rc" -eq 124 ]; then
    printf 'UNKNOWN\tgh api timed out\n'; return
  fi
  if [ "$rc" -ne 0 ]; then
    if printf '%s' "$out" | grep -qi 'Upgrade to GitHub Pro'; then
      printf 'UNKNOWN\t403 — private free-plan repo; branch rules unavailable\n'
    else
      printf 'UNKNOWN\tgh api error: %s\n' "$(printf '%s' "$out" | head -1)"
    fi
    return
  fi
  printf '%s' "$out" | python3 -c "
import json, sys
try:
    rules = json.load(sys.stdin)
except Exception:
    print('UNKNOWN\tcould not parse rules/branches response')
    sys.exit(0)
if not isinstance(rules, list):
    print('UNKNOWN\tunexpected rules/branches response shape')
    sys.exit(0)
offenders = []
for rule in rules:
    if not isinstance(rule, dict) or rule.get('type') != 'pull_request':
        continue
    params = rule.get('parameters') or {}
    count = params.get('required_approving_review_count')
    if isinstance(count, (int, float)) and not isinstance(count, bool) and count > 0:
        source = rule.get('ruleset_source') or '?'
        rid = rule.get('ruleset_id', '?')
        offenders.append('%s (ruleset %s, required_approving_review_count=%s)' % (source, rid, count))
if offenders:
    print('REVIEW_DRIFT\t' + '; '.join(offenders))
else:
    print('CLEAN\tno ruleset requires human approval on this branch')
" 2>/dev/null || printf 'UNKNOWN\tcould not evaluate rules/branches response\n'
}

# ---------------------------------------------------------------------------
# D3 (2026-07-30): merge-safety admin-bypass + fingerprint drift detectors — READ-ONLY. Both mirror
# bl_check_no_required_reviews's shape ("STATUS\tdetail"; gh presence/auth-gated; bounded by
# bl_gh_timeout; graceful UNKNOWN on plan-limit/timeout/parse failure). They are the symmetric
# tripwires that keep the permanent admin bypass (BYPASS_MISSING) and the post-#92 app-visible
# fingerprint (STALE_FINGERPRINT) from silently drifting fleet-wide.
# ---------------------------------------------------------------------------

# bl_check_bypass_missing <owner/repo> -> "STATUS\tdetail"
#   STATUS: CLEAN | BYPASS_MISSING | NOT_ENROLLED | UNKNOWN
# Flags an enrolled repo whose live kleinperkins-merge-safety ruleset's bypass_actors lacks the
# permanent RepositoryRole:5 admin bypass. Owner `gh` auth CAN see bypass_actors (App tokens redact
# them), so this is meaningful here. Self-healed by `repo-baseline.sh reconcile-merge-safety`.
bl_check_bypass_missing() {
  local ownerrepo="$1"
  if [ -z "$ownerrepo" ]; then printf 'UNKNOWN\tno origin remote to check\n'; return; fi
  if ! command -v gh >/dev/null 2>&1; then printf 'UNKNOWN\tgh CLI not found\n'; return; fi
  if ! bl_gh_timeout 5 gh auth status >/dev/null 2>&1; then
    printf 'UNKNOWN\tgh not authenticated (run: gh auth login)\n'; return
  fi
  local authority fields id
  authority="$(bl_live_fleet_authority "$ownerrepo" 2>/dev/null)" || {
    printf 'UNKNOWN\trepository identity does not resolve one enrolled fleet target\n'
    return
  }
  fields="$(printf '%s' "$authority" | python3 -c '
import json, sys
value = json.load(sys.stdin)
print(value.get("merge_safety_ruleset_id"))
' 2>/dev/null)" || {
    printf 'UNKNOWN\tcould not parse fleet ruleset authority\n'
    return
  }
  id="$fields"
  if [ "$id" = "None" ] || [ "$id" = "null" ] || [ -z "$id" ]; then
    printf 'NOT_ENROLLED\tfleet authority has no current %s ruleset id\n' "$BL_MERGE_SAFETY_NAME"
    return
  fi
  local detail drc
  detail="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api "repos/$ownerrepo/rulesets/$id" 2>&1)"; drc=$?
  if [ "$drc" -eq 124 ]; then printf 'UNKNOWN\tgh api timed out reading ruleset %s\n' "$id"; return; fi
  if [ "$drc" -ne 0 ]; then printf 'UNKNOWN\tgh api error reading ruleset %s: %s\n' "$id" "$(printf '%s' "$detail" | head -1)"; return; fi
  if ! bl_validate_merge_safety_ruleset_identity "$ownerrepo" "$id" "$detail" 2>/dev/null; then
    printf 'UNKNOWN\truleset identity differs from central authority for id %s\n' "$id"
    return
  fi
  printf '%s' "$detail" | BL_ROLE_ID="$BL_MERGE_SAFETY_BYPASS_ROLE_ID" BL_RS_ID="$id" python3 -c '
import json, os, sys
rid = os.environ.get("BL_RS_ID", "?")
role = int(os.environ.get("BL_ROLE_ID", "5"))
try:
    rs = json.load(sys.stdin)
except Exception:
    print("UNKNOWN\tcould not parse ruleset %s" % rid); sys.exit(0)
actors = rs.get("bypass_actors")
if actors is None:
    actors = []
if not isinstance(actors, list):
    print("UNKNOWN\tunexpected bypass_actors shape on ruleset %s" % rid); sys.exit(0)
admin = [a for a in actors if isinstance(a, dict) and a.get("actor_type") == "RepositoryRole" and a.get("actor_id") == role]
if admin:
    modes = ",".join(sorted({str(a.get("bypass_mode")) for a in admin}))
    print("CLEAN\tRepositoryRole:%d admin bypass present on ruleset %s (bypass_mode=%s)" % (role, rid, modes))
else:
    seen = ",".join(sorted({str(a.get("actor_type")) + ":" + str(a.get("actor_id")) for a in actors})) or "(none)"
    print("BYPASS_MISSING\truleset %s bypass_actors lacks RepositoryRole:%d admin (present: %s)" % (rid, role, seen))
' 2>/dev/null || printf 'UNKNOWN\tcould not evaluate ruleset %s bypass_actors\n' "$id"
}

# bl_check_stale_fingerprint <owner/repo> -> "STATUS\tdetail"
#   STATUS: CLEAN | STALE_FINGERPRINT | NOT_STAGED | UNKNOWN
# Flags a deployed .github/pr-automation.json whose ruleset_fingerprints (the app-visible list the
# repo pins for the verifier/reviewer Apps) no longer equals the current APP_VISIBLE set — the
# fleet-wide drift #92 introduced when it dropped the excised review-gate fingerprint. Reads the
# REMOTE default-branch committed file (covers targets not cloned locally). Self-healed by
# re-staging that one repo (`repo-baseline.sh profile pr-automation v3 stage …`), never in bulk.
bl_check_stale_fingerprint() {
  local ownerrepo="$1"
  if [ -z "$ownerrepo" ]; then printf 'UNKNOWN\tno origin remote to check\n'; return; fi
  if ! command -v gh >/dev/null 2>&1; then printf 'UNKNOWN\tgh CLI not found\n'; return; fi
  if ! bl_gh_timeout 5 gh auth status >/dev/null 2>&1; then
    printf 'UNKNOWN\tgh not authenticated (run: gh auth login)\n'; return
  fi
  local authority fields repository_id full_name branch expected
  authority="$(bl_live_fleet_authority "$ownerrepo" 2>/dev/null)" || {
    printf 'UNKNOWN\trepository identity does not resolve one enrolled fleet target\n'
    return
  }
  fields="$(printf '%s' "$authority" | python3 -c '
import json, sys
value = json.load(sys.stdin)
print(
    value.get("repository_id", ""),
    value.get("repo", ""),
    value.get("default_branch", ""),
    sep="\t",
)
' 2>/dev/null)" || {
    printf 'UNKNOWN\tcould not parse live fleet authority\n'
    return
  }
  IFS=$'\t' read -r repository_id full_name branch <<<"$fields"
  if [ -z "$repository_id" ] || [ "$full_name" != "$ownerrepo" ] || [ -z "$branch" ]; then
    printf 'UNKNOWN\tlive fleet authority is incomplete\n'; return
  fi
  expected="$(bl_app_visible_fingerprints "$repository_id" "$ownerrepo" "$branch")"
  if [ -z "$expected" ]; then printf 'UNKNOWN\tcould not read authoritative app-visible fingerprints from controller.json\n'; return; fi
  local out rc
  out="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api "repos/$ownerrepo/contents/.github/pr-automation.json?ref=$branch" 2>&1)"; rc=$?
  if [ "$rc" -eq 124 ]; then printf 'UNKNOWN\tgh api timed out\n'; return; fi
  if [ "$rc" -ne 0 ]; then
    if printf '%s' "$out" | grep -qi 'Upgrade to GitHub Pro'; then
      printf 'UNKNOWN\t403 — private free-plan repo; contents unavailable\n'
    elif printf '%s' "$out" | grep -qiE 'Not Found|404'; then
      printf 'NOT_STAGED\tno deployed .github/pr-automation.json (repo not staged into pr-automation v3)\n'
    else
      printf 'UNKNOWN\tgh api error: %s\n' "$(printf '%s' "$out" | head -1)"
    fi
    return
  fi
  printf '%s' "$out" | \
    BL_EXPECTED="$expected" \
    BL_EXPECTED_REPOSITORY_ID="$repository_id" \
    BL_EXPECTED_REPO="$ownerrepo" \
    BL_EXPECTED_DEFAULT_BRANCH="$branch" \
    python3 -c '
import base64, json, os, sys
expected = json.loads(os.environ["BL_EXPECTED"])
try:
    data = json.load(sys.stdin)
    policy = json.loads(base64.b64decode(data["content"]))
except Exception:
    print("UNKNOWN\tcould not decode deployed .github/pr-automation.json"); sys.exit(0)
expected_identity = {
    "repository_id": int(os.environ["BL_EXPECTED_REPOSITORY_ID"]),
    "owner": os.environ["BL_EXPECTED_REPO"].split("/", 1)[0],
    "name": os.environ["BL_EXPECTED_REPO"].split("/", 1)[1],
    "default_branch": os.environ["BL_EXPECTED_DEFAULT_BRANCH"],
}
observed_identity = {key: policy.get(key) for key in expected_identity}
if observed_identity != expected_identity:
    print(
        "UNKNOWN\tdeployed policy repository identity differs from live fleet authority: "
        "observed=%s expected=%s"
        % (json.dumps(observed_identity, sort_keys=True), json.dumps(expected_identity, sort_keys=True))
    )
    sys.exit(0)
deployed = policy.get("ruleset_fingerprints")
if isinstance(deployed, list) and sorted(deployed) == sorted(expected):
    print("CLEAN\truleset_fingerprints match current APP_VISIBLE (%s)" % json.dumps(expected))
else:
    print("STALE_FINGERPRINT\tdeployed=%s expected=%s (re-stage this repo)" % (json.dumps(deployed), json.dumps(expected)))
' 2>/dev/null || printf 'UNKNOWN\tcould not evaluate deployed ruleset_fingerprints\n'
}

# ---------------------------------------------------------------------------
# v2: name-discovered ruleset mutation helpers — used ONLY by `repo-baseline.sh enforce` for the
# baseline history ruleset. Merge-safety reconciliation is centrally ID-bound and does not call
# these helpers. Every other consumer (list/verify/apply, dev-doctor) stays strictly read-only.
# ---------------------------------------------------------------------------

# bl_default_branch <owner/repo> -> the repo's actual default branch, or empty on lookup failure.
# Callers must fail closed; there is deliberately no branch fallback.
bl_default_branch() {
  local ownerrepo="$1" out
  [ -n "$ownerrepo" ] || return 0
  out="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api "repos/$ownerrepo" --jq '.default_branch' 2>/dev/null || true)"
  if [ -n "$out" ] && [ "$out" != "null" ]; then printf '%s' "$out"; fi
}

# bl_live_fleet_authority <owner/repo> -> one compact central authority JSON object.
# Fetches repository metadata exactly once, then cross-binds its immutable ID, full name, and
# default branch through profile.py's fleet resolver. Empty output means fail closed.
bl_live_fleet_authority() {
  local ownerrepo="$1" metadata fields repository_id full_name default_branch
  [ -n "$ownerrepo" ] || return 2
  metadata="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api "repos/$ownerrepo" 2>/dev/null)" \
    || return 1
  fields="$(printf '%s' "$metadata" | python3 -c '
import json, re, sys
try:
    value = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
repository_id = value.get("id")
full_name = value.get("full_name")
default_branch = value.get("default_branch")
if (
    not isinstance(repository_id, int)
    or isinstance(repository_id, bool)
    or repository_id < 1
    or not isinstance(full_name, str)
    or not re.fullmatch(r"KleinPerkins/[A-Za-z0-9._-]+", full_name)
    or not isinstance(default_branch, str)
    or not re.fullmatch(r"[A-Za-z0-9._-]+", default_branch)
    or len(default_branch.encode("ascii")) > 100
):
    raise SystemExit(1)
print(repository_id, full_name, default_branch, sep="\t")
' 2>/dev/null)" || return 1
  IFS=$'\t' read -r repository_id full_name default_branch <<<"$fields"
  [ "$full_name" = "$ownerrepo" ] || return 1
  python3 "$BL_V3_DIR/profile.py" resolve-fleet-target \
    --repository-id "$repository_id" \
    --repo "$full_name" \
    --default-branch "$default_branch"
}

# bl_validate_remote_policy_identity <owner/repo> <repository-id> <default-branch>
# Cross-checks the deployed policy at the already-verified live default branch. This performs no
# metadata lookup, so mutation boundaries still fetch repository metadata exactly once.
bl_validate_remote_policy_identity() {
  local ownerrepo="$1" repository_id="$2" default_branch="$3" out
  [ -n "$ownerrepo" ] && [ -n "$repository_id" ] && [ -n "$default_branch" ] || return 2
  out="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" \
    gh api "repos/$ownerrepo/contents/.github/pr-automation.json?ref=$default_branch" \
    2>/dev/null)" || return 1
  BL_EXPECTED_REPO="$ownerrepo" \
    BL_EXPECTED_REPOSITORY_ID="$repository_id" \
    BL_EXPECTED_DEFAULT_BRANCH="$default_branch" \
    python3 -c '
import base64, json, os, sys
try:
    envelope = json.load(sys.stdin)
    policy = json.loads(base64.b64decode(envelope["content"]))
except Exception:
    raise SystemExit(1)
owner, name = os.environ["BL_EXPECTED_REPO"].split("/", 1)
expected = {
    "repository_id": int(os.environ["BL_EXPECTED_REPOSITORY_ID"]),
    "owner": owner,
    "name": name,
    "default_branch": os.environ["BL_EXPECTED_DEFAULT_BRANCH"],
}
if {key: policy.get(key) for key in expected} != expected:
    raise SystemExit(1)
' <<<"$out"
}

# bl_validate_merge_safety_ruleset_identity <owner/repo> <expected-id> <ruleset-json>
bl_validate_merge_safety_ruleset_identity() {
  local ownerrepo="$1" expected_id="$2" ruleset_json="$3"
  BL_EXPECTED_REPO="$ownerrepo" BL_EXPECTED_RULESET_ID="$expected_id" \
    python3 -c '
import json, os, sys
try:
    value = json.load(sys.stdin)
except Exception:
    raise SystemExit("ruleset response is not valid JSON")
expected = {
    "id": int(os.environ["BL_EXPECTED_RULESET_ID"]),
    "name": "kleinperkins-merge-safety",
    "target": "branch",
    "enforcement": "active",
    "source_type": "Repository",
    "source": os.environ["BL_EXPECTED_REPO"],
}
observed = {key: value.get(key) for key in expected}
if observed != expected:
    raise SystemExit(
        "ruleset identity changed: expected=%s observed=%s"
        % (json.dumps(expected, sort_keys=True), json.dumps(observed, sort_keys=True))
    )
' <<<"$ruleset_json"
}

# bl_list_all_rulesets <owner/repo> -> one flattened JSON array from every API page.
bl_list_all_rulesets() {
  local ownerrepo="$1" tmp page file count rc
  [ -n "$ownerrepo" ] || return 2
  tmp="$(mktemp -d)" || return 1
  page=1
  while [ "$page" -le 1000 ]; do
    file="$tmp/$page.json"
    if ! bl_gh_timeout "${BL_GH_TIMEOUT:-8}" \
      gh api "repos/$ownerrepo/rulesets?per_page=100&page=$page" >"$file"; then
      rm -rf "$tmp"
      return 1
    fi
    count="$(python3 -c '
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
if not isinstance(value, list):
    raise SystemExit(1)
print(len(value))
' "$file" 2>/dev/null)" || {
      rm -rf "$tmp"
      return 1
    }
    if [ "$count" -lt 100 ]; then
      break
    fi
    page=$((page + 1))
  done
  if [ "$page" -gt 1000 ]; then
    rm -rf "$tmp"
    return 1
  fi
  python3 -c '
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
last = int(sys.argv[2])
pages = [json.loads((root / ("%d.json" % page)).read_text()) for page in range(1, last + 1)]
print(json.dumps([item for values in pages for item in values], separators=(",", ":")))
' "$tmp" "$page"
  rc=$?
  rm -rf "$tmp"
  return "$rc"
}

# bl_validate_managed_ruleset_listing <owner/repo> <expected-id> <ruleset-list-json>
bl_validate_managed_ruleset_listing() {
  local ownerrepo="$1" expected_id="$2" listed_json="$3"
  BL_EXPECTED_REPO="$ownerrepo" BL_EXPECTED_RULESET_ID="$expected_id" \
    python3 -c '
import json, os, sys
try:
    value = json.load(sys.stdin)
except Exception:
    raise SystemExit("ruleset list is not valid JSON")
if not isinstance(value, list):
    raise SystemExit("ruleset list is not an array")
name = "kleinperkins-merge-safety"
matching = [item for item in value if isinstance(item, dict) and item.get("name") == name]
expected = {
    "id": int(os.environ["BL_EXPECTED_RULESET_ID"]),
    "name": name,
    "target": "branch",
    "enforcement": "active",
}
if len(matching) != 1 or {key: matching[0].get(key) for key in expected} != expected:
    raise SystemExit(
        "%s must have exactly one active %s ruleset with central id %s; observed=%s"
        % (
            os.environ["BL_EXPECTED_REPO"],
            name,
            os.environ["BL_EXPECTED_RULESET_ID"],
            json.dumps(matching, sort_keys=True),
        )
    )
' <<<"$listed_json"
}

# bl_verify_applied_merge_safety <repository-id> <owner/repo> <branch> <ruleset-id> <observed-file>
bl_verify_applied_merge_safety() {
  [ "$#" -eq 5 ] || return 2
  python3 "$BL_V3_DIR/profile.py" verify-applied-ruleset \
    --repository-id "$1" \
    --repo "$2" \
    --default-branch "$3" \
    --ruleset-id "$4" \
    --observed-ruleset "$5" \
    >/dev/null
}

# bl_repo_remote_id <owner/repo> -> immutable numeric GitHub repository id, or empty.
bl_repo_remote_id() {
  local ownerrepo="$1"
  [ -n "$ownerrepo" ] || return 0
  local repository_id
  repository_id="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api "repos/$ownerrepo" --jq '.id' 2>/dev/null)" \
    || return 0
  case "$repository_id" in
    ''|*[!0-9]*|0*) return 0 ;;
    *) printf '%s\n' "$repository_id" ;;
  esac
}

# bl_repo_remote_owner <owner/repo> -> the actual owner login GitHub reports for this repo, or
# empty on failure. Independent of the local git remote parse — a defense against a local
# misconfigured/spoofed origin URL pointing `enforce` at the wrong account.
bl_repo_remote_owner() {
  local ownerrepo="$1"
  [ -n "$ownerrepo" ] || return 0
  bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api "repos/$ownerrepo" --jq '.owner.login' 2>/dev/null || true
}

# bl_ruleset_find <owner/repo> <name> -> the numeric id of an existing ruleset with this exact
# name, or empty if none exists (or the call fails). Rulesets are id-keyed, not name-keyed, so
# idempotent upsert requires this list-then-match step.
bl_ruleset_find() {
  local ownerrepo="$1" name="$2" out
  out="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api "repos/$ownerrepo/rulesets" 2>/dev/null || true)"
  [ -n "$out" ] || return 0
  printf '%s' "$out" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    data = []
for r in data:
    if r.get('name') == '$name':
        print(r.get('id',''))
        break
" 2>/dev/null
}

# bl_ruleset_upsert <owner/repo> <payload-file> <name> -> prints the ruleset id on success (exit
# 0), or prints nothing and returns non-zero on failure. PUT is a full replace (no partial-diff
# risk); POST is used only when no same-named ruleset exists yet.
bl_ruleset_upsert() {
  local ownerrepo="$1" payload="$2" name="$3" id out
  id="$(bl_ruleset_find "$ownerrepo" "$name")"
  if [ -n "$id" ]; then
    out="$(bl_gh_timeout "${BL_GH_TIMEOUT:-15}" gh api -X PUT "repos/$ownerrepo/rulesets/$id" --input "$payload" 2>&1)" || return 1
  else
    out="$(bl_gh_timeout "${BL_GH_TIMEOUT:-15}" gh api -X POST "repos/$ownerrepo/rulesets" --input "$payload" 2>&1)" || return 1
  fi
  printf '%s' "$out" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null
}

# bl_ensure_repo_settings <owner/repo> -> idempotently PATCHes the FIVE repo settings that make a
# repo match the fleet-uniform merge posture: SQUASH-ONLY merge buttons (allow_squash_merge=true,
# allow_merge_commit=false, allow_rebase_merge=false) plus the "ship via PR + auto-merge, delete the
# branch afterward" norm (allow_auto_merge=true, delete_branch_on_merge=true). On a freshly-created
# GitHub repo all three merge methods default ON and auto-merge/delete-branch default OFF — silent,
# easy-to-miss footguns: `gh pr merge --auto` fails until allow_auto_merge is on, and merge-commit +
# rebase buttons stay live (contradicting the fleet's squash-only standard) until turned off. This is
# what makes a NEW repo born-uniform (the merge-safety ruleset's allowed_merge_methods:["squash"]
# only takes effect at explicit post-canary remote activation; these repo settings are the day-one,
# button-level control). Idempotent (a PATCH to an already-correct value is a no-op); uses -F so
# `false` is sent as a JSON boolean, not the truthy string "false". Prints what changed, nothing else.
bl_ensure_repo_settings() {
  local ownerrepo="$1" cur out
  cur="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api "repos/$ownerrepo" --jq '[.allow_auto_merge, .delete_branch_on_merge, .allow_squash_merge, .allow_merge_commit, .allow_rebase_merge] | @tsv' 2>/dev/null || true)"
  [ -n "$cur" ] || { printf 'unknown (gh api failed)\n'; return 1; }
  local aam dbom asm amc arm
  aam="$(printf '%s' "$cur" | awk -F'\t' '{print $1}')"
  dbom="$(printf '%s' "$cur" | awk -F'\t' '{print $2}')"
  asm="$(printf '%s' "$cur" | awk -F'\t' '{print $3}')"
  amc="$(printf '%s' "$cur" | awk -F'\t' '{print $4}')"
  arm="$(printf '%s' "$cur" | awk -F'\t' '{print $5}')"
  if [ "$aam" = "true" ] && [ "$dbom" = "true" ] && [ "$asm" = "true" ] && [ "$amc" = "false" ] && [ "$arm" = "false" ]; then
    printf 'already set (squash-only + auto-merge + delete-branch)\n'
    return 0
  fi
  out="$(bl_gh_timeout "${BL_GH_TIMEOUT:-8}" gh api -X PATCH "repos/$ownerrepo" \
    -F allow_squash_merge=true -F allow_merge_commit=false -F allow_rebase_merge=false \
    -F allow_auto_merge=true -F delete_branch_on_merge=true 2>&1)" || {
    printf 'FAILED: %s\n' "$(printf '%s' "$out" | head -1)"; return 1
  }
  printf 'set squash-only (allow_squash_merge=true, allow_merge_commit=false, allow_rebase_merge=false) + allow_auto_merge=true + delete_branch_on_merge=true\n'
}

# bl_state_path <owner/repo> -> the committed state-record path for this repo under BL_STATE_DIR.
bl_state_path() {
  local ownerrepo="$1" slug
  slug="$(printf '%s' "$ownerrepo" | tr '/' '__' | tr '[:upper:]' '[:lower:]')"
  printf '%s/%s.enforced.json\n' "$BL_STATE_DIR" "$slug"
}

# bl_write_state <owner/repo> <default_branch> <branch_ruleset_id> [tag_ruleset_id]
# Writes a small committed audit record — the traceability substitute for a GitHub Settings
# mutation that can't itself be a reviewable PR diff. `verify`/`dev-doctor` can diff this against
# live `gh api rulesets` state to flag drift (e.g. someone edited/removed the ruleset by hand).
bl_write_state() {
  local ownerrepo="$1" branch="$2" branch_id="$3" tag_id="${4:-}"
  local path; path="$(bl_state_path "$ownerrepo")"
  mkdir -p "$BL_STATE_DIR"
  local gh_ver; gh_ver="$(gh --version 2>/dev/null | head -1 | tr -d '"')"
  {
    printf '{\n'
    printf '  "owner_repo": "%s",\n' "$ownerrepo"
    printf '  "default_branch": "%s",\n' "$branch"
    printf '  "branch_ruleset_name": "%s",\n' "$BL_RULESET_NAME"
    printf '  "branch_ruleset_id": %s,\n' "${branch_id:-null}"
    if [ -n "$tag_id" ]; then
      printf '  "tag_ruleset_name": "%s",\n' "$BL_RULESET_TAG_NAME"
      printf '  "tag_ruleset_id": %s,\n' "$tag_id"
    else
      printf '  "tag_ruleset_name": null,\n'
      printf '  "tag_ruleset_id": null,\n'
    fi
    printf '  "rules": ["deletion", "non_fast_forward"],\n'
    printf '  "bypass_actors": [{"actor_type": "RepositoryRole", "actor_id": 5, "bypass_mode": "always"}],\n'
    printf '  "applied_at": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '  "applied_by_gh_version": "%s"\n' "$gh_ver"
    printf '}\n'
  } > "$path"
}

# ---------------------------------------------------------------------------
# D3 (2026-07-30): merge-safety reconcile helpers — mirror bl_state_path/bl_write_state but for the
# pr-automation kleinperkins-merge-safety ruleset. It has a DISTINCT per-repo id from the baseline
# history ruleset, so it gets its own `<owner>__<repo>.merge-safety.json` record; the two never
# collide. The reconcile verb (repo-baseline.sh reconcile-merge-safety) writes this record so a
# later drift-guard/verify can diff the live ruleset id against what this tool last reconciled.
# ---------------------------------------------------------------------------
bl_merge_safety_state_path() {
  local ownerrepo="$1" slug
  slug="$(printf '%s' "$ownerrepo" | tr '/' '__' | tr '[:upper:]' '[:lower:]')"
  printf '%s/%s.merge-safety.json\n' "$BL_STATE_DIR" "$slug"
}

# bl_write_merge_safety_state <owner/repo> <default_branch> <ruleset_id> <repository_id>
bl_write_merge_safety_state() {
  local ownerrepo="$1" branch="$2" rs_id="$3" repository_id="$4"
  local path; path="$(bl_merge_safety_state_path "$ownerrepo")"
  mkdir -p "$BL_STATE_DIR"
  local gh_ver; gh_ver="$(gh --version 2>/dev/null | head -1 | tr -d '"')"
  local op_fp
  op_fp="$(bl_operator_full_fingerprints "$repository_id" "$ownerrepo" "$branch" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)[0])' 2>/dev/null)"
  {
    printf '{\n'
    printf '  "owner_repo": "%s",\n' "$ownerrepo"
    printf '  "default_branch": "%s",\n' "$branch"
    printf '  "ruleset_name": "%s",\n' "$BL_MERGE_SAFETY_NAME"
    printf '  "ruleset_id": %s,\n' "${rs_id:-null}"
    printf '  "bypass_actors": [{"actor_type": "RepositoryRole", "actor_id": %s, "bypass_mode": "pull_request"}],\n' "$BL_MERGE_SAFETY_BYPASS_ROLE_ID"
    printf '  "operator_full_fingerprint": "%s",\n' "$op_fp"
    printf '  "reconciled_at": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '  "reconciled_by_gh_version": "%s"\n' "$gh_ver"
    printf '}\n'
  } > "$path"
}
