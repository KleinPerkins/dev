#!/usr/bin/env bash
# _ops/bin/doc-warden-lib.sh — doc-warden shared engine
#
# The one normalizer: evidence gathering → normalized model → classification →
# action-planner → receipt writer.
#
# Source this file; do not execute it. bash 3.2 compatible.
# Policy source: _ops/doc-warden/POLICY.md
# Execution plan: _ops/plans/doc-warden-execution-plan-v1.md §7, §18 WI-M1-02

set -uo pipefail

DWL_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # _ops/bin
DWL_OPS_DIR="$(dirname "$DWL_LIB_DIR")"                            # _ops
DWL_DEV_ROOT="$(dirname "$DWL_OPS_DIR")"                           # ~/dev

DWL_DOC_WARDEN_DIR="$DWL_OPS_DIR/doc-warden"
DWL_POLICY_FILE="$DWL_DOC_WARDEN_DIR/POLICY.md"
DWL_TRIGGERS_FILE="$DWL_DOC_WARDEN_DIR/triggers.yml"
DWL_TEMPLATES_DIR="$DWL_DOC_WARDEN_DIR/templates"
DWL_STATE_DIR="$DWL_DOC_WARDEN_DIR/state"

# Classification values (§3 ladder, POLICY.md)
DWL_CONFORMANT="CONFORMANT"
DWL_MISSING="MISSING"
DWL_NEEDS_AUTHORING="NEEDS_AUTHORING"
DWL_DRIFTED="DRIFTED"
DWL_NEEDS_OPERATOR="NEEDS_OPERATOR"
DWL_CONTRADICTORY="CONTRADICTORY"
DWL_DUPLICATE_AUTHORITY="DUPLICATE_AUTHORITY"
DWL_OWNED_CORRECTLY="OWNED_CORRECTLY"
DWL_OWNER_ONLY="OWNER_ONLY"
DWL_DEPENDENT_ONLY="DEPENDENT_ONLY"

DWL_CROSS_REPO_PROFILES_FILE="$DWL_DOC_WARDEN_DIR/cross-repo-profiles.yml"

# Cached python with PyYAML (system /usr/bin/python3 on macOS often lacks yaml).
DWL_PYTHON_CACHED=""

# dwl_python — print path to a Python that can import yaml; non-zero if none.
# Override with DOC_WARDEN_PYTHON. Tries Homebrew before bare python3.
dwl_python() {
  if [ -n "$DWL_PYTHON_CACHED" ]; then
    printf '%s\n' "$DWL_PYTHON_CACHED"
    return 0
  fi
  local p
  for p in "${DOC_WARDEN_PYTHON:-}" /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    [ -n "$p" ] || continue
    command -v "$p" >/dev/null 2>&1 || continue
    if "$p" -c "import yaml" 2>/dev/null; then
      DWL_PYTHON_CACHED="$p"
      printf '%s\n' "$DWL_PYTHON_CACHED"
      return 0
    fi
  done
  return 1
}

# Grep-based trigger-id extraction when PyYAML is unavailable (verify sandbox parity).
dwl_trigger_ids_grep() {
  grep -E '^[[:space:]]+- id:' "$DWL_TRIGGERS_FILE" 2>/dev/null \
    | sed -E 's/^[[:space:]]+- id:[[:space:]]*//' \
    | sort -n
}

# dwl_run_python — invoke resolved python, or python3 as last resort.
dwl_run_python() {
  local py
  if py="$(dwl_python 2>/dev/null)"; then
    "$py" "$@"
  else
    python3 "$@"
  fi
}

# Action types for the action planner
DWL_ACTION_CREATE="create"
DWL_ACTION_MOVE="move"
DWL_ACTION_APPEND_BLOCK="append_block"

# Markers for AGENTS.md pointer block (POLICY.md §10 rule 6)
DWL_BLOCK_BEGIN='<!-- doc-warden:begin -->'
DWL_BLOCK_END='<!-- doc-warden:end -->'

# ---------------------------------------------------------------------------
# Policy digest — used in receipts and for change detection
# ---------------------------------------------------------------------------
dwl_policy_digest() {
  sha256sum "$DWL_POLICY_FILE" 2>/dev/null | awk '{print $1}' \
    || shasum -a 256 "$DWL_POLICY_FILE" 2>/dev/null | awk '{print $1}' \
    || echo "no-sha256"
}

# dwl_content_digest <file>
dwl_content_digest() {
  sha256sum "$1" 2>/dev/null | awk '{print $1}' \
    || shasum -a 256 "$1" 2>/dev/null | awk '{print $1}' \
    || echo "no-sha256"
}

# dwl_receipt_content_digest_for_path <repo_root> <rel_path>
# Prints the content_digest from the newest receipt covering rel_path, or nothing.
# Skips sentinel digests (n/a, index_row). POLICY.md §12 step 5.
dwl_receipt_content_digest_for_path() {
  local repo="$1" rel_path="$2"
  local repo_name
  repo_name="$(basename "$repo")"
  DWL_STATE_DIR="$DWL_STATE_DIR" python3 -c "
import glob, os, sys, yaml
state_dir = os.environ['DWL_STATE_DIR']
repo_name, rel_path = sys.argv[1], sys.argv[2]
receipt_dir = os.path.join(state_dir, repo_name)
if not os.path.isdir(receipt_dir):
    sys.exit(0)
skip = {'n/a', 'index_row'}
for rf in sorted(glob.glob(os.path.join(receipt_dir, '*.yml')), reverse=True):
    try:
        doc = yaml.safe_load(open(rf)) or {}
    except Exception:
        continue
    for action in doc.get('approved_actions') or []:
        if action.get('path') != rel_path:
            continue
        digest = action.get('content_digest', '')
        if digest and digest not in skip:
            print(digest)
            sys.exit(0)
" "$repo_name" "$rel_path" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Override resolution — reads <repo>/.doc-warden.yml for plans_dir / adr_dir
# Returns defaults if file absent or key missing.
# ---------------------------------------------------------------------------

# dwl_validate_rel_dir <repo_root> <relative_dir> — reject traversal and absolute overrides
# (calls dwl_path_under_repo; defined after path-safety helpers below)
dwl_validate_rel_dir() {
  local repo="$1" rel="$2"
  [ -n "$rel" ] || return 1
  case "$rel" in
    /*|*..*) return 1 ;;
  esac
  dwl_path_under_repo "$repo" "$rel"
}
# dwl_plans_dir <repo_root>
dwl_plans_dir() {
  local repo="$1" override_file="$1/.doc-warden.yml"
  local default="docs/plans"
  if [ -f "$override_file" ]; then
    local val
    val="$(grep -E '^plans_dir:' "$override_file" 2>/dev/null | head -1 | sed 's/^plans_dir:[[:space:]]*//' | tr -d '"' | tr -d "'")"
    if [ -n "$val" ]; then
      if dwl_validate_rel_dir "$repo" "$val"; then
        printf '%s' "$val"
        return
      fi
      printf 'WARN: invalid plans_dir in .doc-warden.yml (using default): %s\n' "$val" >&2
    fi
  fi
  printf '%s' "$default"
}

# dwl_adr_dir <repo_root>
dwl_adr_dir() {
  local repo="$1" override_file="$1/.doc-warden.yml"
  local default="docs/adr"
  if [ -f "$override_file" ]; then
    local val
    val="$(grep -E '^adr_dir:' "$override_file" 2>/dev/null | head -1 | sed 's/^adr_dir:[[:space:]]*//' | tr -d '"' | tr -d "'")"
    if [ -n "$val" ]; then
      if dwl_validate_rel_dir "$repo" "$val"; then
        printf '%s' "$val"
        return
      fi
      printf 'WARN: invalid adr_dir in .doc-warden.yml (using default): %s\n' "$val" >&2
    fi
  fi
  printf '%s' "$default"
}

# dwl_incidents_dir <repo_root>
# Repos that already keep both plans and ADRs under docs/ keep incidents there too.
dwl_incidents_dir() {
  local repo="$1" plans_rel adr_rel
  plans_rel="$(dwl_plans_dir "$repo")"
  adr_rel="$(dwl_adr_dir "$repo")"
  case "$plans_rel:$adr_rel" in
    docs/*:docs/*) printf '%s' "docs/incidents" ;;
    *) printf '%s' "_ops/incidents" ;;
  esac
}

# ---------------------------------------------------------------------------
# Local governance (M2 / POC 3b — preserve stronger repo-specific conventions)
# When a repo declares its own plans convention README, skip generic per-file
# normalization and only flag known policy drifts against doc-warden POLICY.
# ---------------------------------------------------------------------------

# dwl_has_local_convention_authority <repo_root> <plans_dir_rel>
# True when plans_dir/README.md is an authored local convention (not a greenfield template).
dwl_has_local_convention_authority() {
  local repo="$1" plans_rel="$2"
  local readme_abs="$repo/$plans_rel/README.md"
  [ -f "$readme_abs" ] || return 1
  grep -qE '(## The convention|The convention \(already|planning-document convention)' \
    "$readme_abs" 2>/dev/null
}

# dwl_hand_authored_agents_md_ok <repo_root> <plans_dir_rel>
# Repos with a mature hand-authored AGENTS.md pointing at the local convention are CONFORMANT
# without the doc-warden marker block (POC 3b acceptance test #9).
dwl_hand_authored_agents_md_ok() {
  local repo="$1" plans_rel="$2"
  local agents_abs="$repo/AGENTS.md"
  [ -f "$agents_abs" ] || return 1
  grep -qF "${plans_rel}/README.md" "$agents_abs" 2>/dev/null \
    && grep -qE '(Planning documents|planning-document|execution/design plan)' "$agents_abs" 2>/dev/null
}

# dwl_plans_readme_has_index_table <readme_abs>
dwl_plans_readme_has_index_table() {
  local readme_abs="$1"
  grep -qE '\|\s*(Plan|File)\s*\|' "$readme_abs" 2>/dev/null \
    && grep -qE '^\|[-[:space:]|]+\|' "$readme_abs" 2>/dev/null
}

# dwl_policy_drift_ids_for_plans_readme <readme_abs>
# Prints one drift id per line (closed catalog for M2 POC 3b).
dwl_policy_drift_ids_for_plans_readme() {
  local readme_abs="$1"
  [ -f "$readme_abs" ] || return 0
  # Drift #2 (POC 3b): status-bullet edit allowance — looser than byte-identical-forever (§13)
  if grep -qF 'now frozen historical' "$readme_abs" 2>/dev/null \
     && grep -qF 'superseded file' "$readme_abs" 2>/dev/null \
     && grep -qF '**Status:**' "$readme_abs" 2>/dev/null; then
    printf 'status_bullet_exception\n'
  fi
  # Drift #1 (POC 3b): stale cross-reference claiming docs/adr/ lacks an index
  if grep -qE '(no index/README of its own yet|has the same gap|lacks an index)' "$readme_abs" 2>/dev/null; then
    printf 'stale_adr_index_crossref\n'
  fi
}

# dwl_apply_policy_patch <readme_abs> <drift_id> <output_file>
# Applies one closed-catalog policy patch; returns 0 if changed, 1 if no-op/not found.
dwl_apply_policy_patch() {
  local readme_abs="$1" drift_id="$2" out_file="$3"
  DWL_PATCH_README="$readme_abs" DWL_PATCH_OUT="$out_file" DWL_PATCH_ID="$drift_id" \
  python3 <<'PY'
import os, sys
src = os.environ['DWL_PATCH_README']
out = os.environ['DWL_PATCH_OUT']
drift_id = os.environ['DWL_PATCH_ID']
txt = open(src).read()
patches = {
    'status_bullet_exception': (
        "   explicitly in the new file's `**Supersedes:**` bullet and, where practical, add a one-line\n"
        '   "now frozen historical" note to the superseded file\'s own `**Status:**` bullet (its body stays\n'
        '   untouched).',
        "   explicitly in the new file's `**Supersedes:**` bullet and update the index file's row; the\n"
        '   superseded file itself is never modified (byte-identical-forever — no status-line edits).',
    ),
    'stale_adr_index_crossref': (
        "- `docs/adr/` (architecture decision records) has its own equivalent convention/index file —\n"
        "  but no index/README of its own yet.",
        "- `docs/adr/` (architecture decision records) has its own equivalent convention/index file —\n"
        "  [`docs/adr/README.md`](../adr/README.md).",
    ),
}
if drift_id not in patches:
    sys.exit(1)
old, new = patches[drift_id]
if old not in txt:
    sys.exit(1)
open(out, 'w').write(txt.replace(old, new, 1))
sys.exit(0)
PY
}

# dwl_render_patched_plans_readme <repo_root> <plans_rel> <drift_ids_newline>
# Renders post-patch content for digest computation (canonical order of drift ids).
dwl_render_patched_plans_readme() {
  local repo="$1" plans_rel="$2" drift_ids="$3"
  local readme_abs="$repo/$plans_rel/README.md"
  local tmp
  tmp="$(mktemp)"
  cp "$readme_abs" "$tmp"
  while IFS= read -r drift_id; do
    [ -n "$drift_id" ] || continue
    local next_tmp
    next_tmp="$(mktemp)"
    if dwl_apply_policy_patch "$tmp" "$drift_id" "$next_tmp"; then
      mv "$next_tmp" "$tmp"
    else
      rm -f "$next_tmp"
    fi
  done <<< "$drift_ids"
  cat "$tmp"
  rm -f "$tmp"
}

# ---------------------------------------------------------------------------
# Evidence gathering (POLICY.md §7)
# M1 implements: agents_md, plan, adr, code
# M3+ stubs: git_history, issue_pr, runbook, historical_doc, cross_repo_ref, transcript
# ---------------------------------------------------------------------------

# dwl_gather_agents_md <repo_root> → prints "present" or "absent"
dwl_gather_agents_md() {
  local repo="$1"
  [ -f "$repo/AGENTS.md" ] && printf 'present' || printf 'absent'
}

# dwl_gather_agents_md_block <repo_root> → prints "present" or "absent" for the pointer block
dwl_gather_agents_md_block() {
  local repo="$1"
  [ -f "$repo/AGENTS.md" ] && grep -qF "$DWL_BLOCK_BEGIN" "$repo/AGENTS.md" 2>/dev/null \
    && printf 'present' || printf 'absent'
}

# dwl_gather_plans <repo_root> <plans_dir_rel> → prints plan filenames (one per line), or empty
dwl_gather_plans() {
  local repo="$1" plans_rel="$2"
  local plans_abs="$repo/$plans_rel"
  [ -d "$plans_abs" ] || return 0
  if git -C "$repo" rev-parse --show-toplevel >/dev/null 2>&1; then
    git -C "$repo" ls-files -- "$plans_rel" 2>/dev/null \
      | awk -v prefix="$plans_rel/" '
          index($0, prefix) == 1 {
            rel = substr($0, length(prefix) + 1)
            if (rel !~ /\// && rel ~ /\.md$/ && rel != "README.md") print rel
          }
        ' | sort
  else
    find "$plans_abs" -maxdepth 1 -name "*.md" ! -name "README.md" 2>/dev/null \
      | while IFS= read -r f; do basename "$f"; done | sort
  fi
}

# dwl_superseded_plans_on_active_surface <repo_root> <plans_dir_rel>
# Prints superseded plan basenames still on the active surface (index and/or AGENTS.md routing).
# Acceptance test #10 / §9 archival model.
dwl_superseded_plans_on_active_surface() {
  local repo="$1" plans_rel="$2"
  DWL_SUPER_REPO="$repo" DWL_SUPER_PLANS="$plans_rel" python3 <<'PY'
import glob, os, re

repo = os.environ['DWL_SUPER_REPO']
plans_rel = os.environ['DWL_SUPER_PLANS']
plans_abs = os.path.join(repo, plans_rel)
if not os.path.isdir(plans_abs):
    raise SystemExit(0)

plan_files = [
    os.path.basename(p)
    for p in glob.glob(os.path.join(plans_abs, '*.md'))
    if os.path.basename(p) != 'README.md'
]

supersedes_re = re.compile(
    r'\*\*Supersedes:\*\*\s*`?([a-z0-9-]+-v[0-9]+\.md)`?', re.I
)
superseded = set()
for pf in plan_files:
    txt = open(os.path.join(plans_abs, pf), encoding='utf-8', errors='replace').read()
    for m in supersedes_re.finditer(txt):
        superseded.add(m.group(1))

readme = os.path.join(plans_abs, 'README.md')
index_txt = open(readme, encoding='utf-8', errors='replace').read() if os.path.isfile(readme) else ''
agents = os.path.join(repo, 'AGENTS.md')
agents_txt = open(agents, encoding='utf-8', errors='replace').read() if os.path.isfile(agents) else ''

for fname in sorted(superseded):
    src = os.path.join(plans_abs, fname)
    if not os.path.isfile(src):
        continue
    in_index = fname in index_txt and '|' in index_txt
    in_agents = fname in agents_txt
    if in_index or in_agents:
        print(fname)
PY
}

# dwl_index_row_remove <abs_path> <fname> — remove table row referencing fname; returns 0 if changed
dwl_index_row_remove() {
  local abs_path="$1" fname="$2"
  DWL_INDEX_ABS="$abs_path" DWL_INDEX_FNAME="$fname" python3 <<'PY'
import os, sys
abs_path = os.environ['DWL_INDEX_ABS']
fname = os.environ['DWL_INDEX_FNAME']
txt = open(abs_path).read()
lines = txt.splitlines(keepends=True)
out = []
removed = False
for line in lines:
    if fname in line and line.strip().startswith('|') and not line.strip().startswith('|---'):
        removed = True
        continue
    out.append(line)
if not removed:
    sys.exit(1)
open(abs_path, 'w').writelines(out)
sys.exit(0)
PY
}

# dwl_agents_md_remove_plan_ref <abs_path> <fname> — strip routing lines citing fname; returns 0 if changed
dwl_agents_md_remove_plan_ref() {
  local abs_path="$1" fname="$2"
  DWL_AGENTS_ABS="$abs_path" DWL_AGENTS_FNAME="$fname" python3 <<'PY'
import os, sys
abs_path = os.environ['DWL_AGENTS_ABS']
fname = os.environ['DWL_AGENTS_FNAME']
txt = open(abs_path).read()
lines = txt.splitlines(keepends=True)
out = []
removed = False
for line in lines:
    if fname in line:
        removed = True
        continue
    out.append(line)
if not removed:
    sys.exit(1)
open(abs_path, 'w').writelines(out)
sys.exit(0)
PY
}

# dwl_gather_adrs <repo_root> <adr_dir_rel> → prints ADR filenames (one per line), or empty
dwl_gather_adrs() {
  local repo="$1" adr_rel="$2"
  local adr_abs="$repo/$adr_rel"
  [ -d "$adr_abs" ] || return 0
  find "$adr_abs" -maxdepth 1 -name "[0-9][0-9][0-9][0-9]-*.md" 2>/dev/null \
    | while IFS= read -r f; do basename "$f"; done | sort
}

# dwl_gather_git_history <repo_root> [path_glob] — recent commit one-liners (sanitized)
dwl_gather_git_history() {
  local repo="$1" path="${2:-}"
  if ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
    printf 'no_git'
    return
  fi
  if [ -n "$path" ]; then
    git -C "$repo" log --oneline -10 -- "$path" 2>/dev/null | head -10
  else
    git -C "$repo" log --oneline -10 2>/dev/null | head -10
  fi
}

# dwl_gather_issue_pr <repo_root> — PR references from commit subjects (no API/token)
dwl_gather_issue_pr() {
  local repo="$1"
  if ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
    printf 'no_git'
    return
  fi
  git -C "$repo" log --oneline -30 --grep='#[0-9]' 2>/dev/null | head -8
}

# dwl_gather_historical_doc <repo_root> — top-level docs/*.md basenames
dwl_gather_historical_doc() {
  local repo="$1"
  [ -d "$repo/docs" ] || return 0
  find "$repo/docs" -maxdepth 2 -name '*.md' 2>/dev/null \
    | while IFS= read -r f; do printf '%s\n' "${f#$repo/}"; done | sort
}

# dwl_gather_cross_repo_ref <repo_root> — paths citing ~/dev or OPERATING-MANUAL
dwl_gather_cross_repo_ref() {
  local repo="$1"
  grep -rEl '(OPERATING-MANUAL|~/dev/)' "$repo" \
    --include='*.md' --include='*.yml' --include='*.sh' 2>/dev/null \
    | while IFS= read -r f; do printf '%s\n' "${f#$repo/}"; done | sort | head -12
}

# dwl_gather_transcript <repo_root> — never copies transcript content (POLICY §7)
dwl_gather_transcript() {
  printf 'unavailable_private_evidence'
}

# ---------------------------------------------------------------------------
# M3 / POC 3c — provenance reconstruction (POLICY.md §7, plan §17 POC 3c)
# Closed profile: ecosystem-orchestrator only. Other repos require operator co-design.
# ---------------------------------------------------------------------------

# dwl_reconstruct_profile_for_repo <repo_root> — prints profile id or empty
dwl_reconstruct_profile_for_repo() {
  local repo="$1"
  case "$(basename "$repo")" in
    ecosystem-orchestrator|poc3c) printf 'ecosystem-orchestrator' ;;
    *) ;;
  esac
}

# dwl_reconstruct_has_unresolved_contradictory <repo_root> — 0 if any contested claim
dwl_reconstruct_has_unresolved_contradictory() {
  local repo="$1"
  local profile
  profile="$(dwl_reconstruct_profile_for_repo "$repo")"
  [ -n "$profile" ] || return 1
  dwl_reconstruct_emit_records "$repo" "$profile" 2>/dev/null \
    | python3 -c "
import sys, yaml
for doc in yaml.safe_load_all(sys.stdin.read()):
    if not doc:
        continue
    if doc.get('resolution') == 'escalated_to_operator' and doc.get('confidence') == 'contested':
        sys.exit(0)
sys.exit(1)
" 2>/dev/null
}

# dwl_reconstruct_emit_records <repo_root> <profile> — YAML evidence records to stdout
dwl_reconstruct_emit_records() {
  local repo="$1" profile="$2"
  local dev_root="$DWL_DEV_ROOT"
  local om="$dev_root/OPERATING-MANUAL.md"
  local head_sha vendor_head rel_head readme_head
  head_sha="$(git -C "$repo" rev-parse HEAD 2>/dev/null || echo 'no-git')"
  vendor_head="$(git -C "$repo" log -1 --format='%h' -- lib/vendor.sh 2>/dev/null || echo 'none')"
  rel_head="$(git -C "$repo" log -1 --format='%h' -- config/relationship.yml 2>/dev/null || echo 'none')"
  readme_head="$(git -C "$repo" log -1 --format='%h' -- README.md 2>/dev/null || echo 'none')"
  local issue_sample hist_docs cross_refs
  issue_sample="$(dwl_gather_issue_pr "$repo" | head -3 | tr '\n' '; ')"
  hist_docs="$(dwl_gather_historical_doc "$repo" | tr '\n' ', ')"
  cross_refs="$(dwl_gather_cross_repo_ref "$repo" | tr '\n' ', ')"

  DWL_RECON_REPO="$repo" \
  DWL_RECON_PROFILE="$profile" \
  DWL_RECON_HEAD="$head_sha" \
  DWL_RECON_VENDOR_HEAD="$vendor_head" \
  DWL_RECON_REL_HEAD="$rel_head" \
  DWL_RECON_README_HEAD="$readme_head" \
  DWL_RECON_OM="$om" \
  DWL_RECON_ISSUES="$issue_sample" \
  DWL_RECON_HIST="$hist_docs" \
  DWL_RECON_CROSS="$cross_refs" \
  python3 <<'PY'
import os, yaml

repo = os.environ['DWL_RECON_REPO']
profile = os.environ['DWL_RECON_PROFILE']
head = os.environ['DWL_RECON_HEAD']
vendor_head = os.environ['DWL_RECON_VENDOR_HEAD']
rel_head = os.environ['DWL_RECON_REL_HEAD']
readme_head = os.environ['DWL_RECON_README_HEAD']
om = os.environ['DWL_RECON_OM']
issues = os.environ.get('DWL_RECON_ISSUES', '')
hist = os.environ.get('DWL_RECON_HIST', '')
cross = os.environ.get('DWL_RECON_CROSS', '')

def emit(doc):
    print('---')
    print(yaml.safe_dump(doc, sort_keys=False, default_flow_style=False).rstrip())

if profile != 'ecosystem-orchestrator':
    emit({
        'claim': 'unsupported profile',
        'source_type': 'code',
        'source_ref': profile,
        'confidence': 'verified',
        'conflicting_evidence': [],
        'resolution': 'escalated_to_operator',
    })
    raise SystemExit(0)

emit({
    'claim': 'This repo is the single sanctioned writer of the ld→cpp data-plane edge (orchestrator vendoring).',
    'source_type': 'code',
    'source_ref': f'{repo}/lib/vendor.sh@{vendor_head}',
    'confidence': 'verified',
    'conflicting_evidence': [],
    'resolution': 'accepted',
})
emit({
    'claim': 'INV-zero-link: the ld↔cpp relationship is defined only in config/relationship.yml.',
    'source_type': 'code',
    'source_ref': f'{repo}/config/relationship.yml@{rel_head}',
    'confidence': 'verified',
    'conflicting_evidence': [],
    'resolution': 'accepted',
})
emit({
    'claim': 'Registry enrollment and cpp delivery are separate workflows with a hard boundary.',
    'source_type': 'code',
    'source_ref': f'{repo}/README.md@{readme_head}',
    'confidence': 'verified',
    'conflicting_evidence': [],
    'resolution': 'accepted',
})
if os.path.isfile(om):
    emit({
        'claim': 'Cross-repo authority for orchestrator role defers to ~/dev OPERATING-MANUAL §10h.',
        'source_type': 'cross_repo_ref',
        'source_ref': f'{om}#§10h',
        'confidence': 'verified',
        'conflicting_evidence': [],
        'resolution': 'accepted',
    })
if hist:
    emit({
        'claim': 'Historical organic docs exist under docs/ and remain discoverable but are not governed plans/ADRs.',
        'source_type': 'historical_doc',
        'source_ref': hist.strip(', '),
        'confidence': 'inferred',
        'conflicting_evidence': [],
        'resolution': 'accepted',
    })
if issues:
    emit({
        'claim': 'Recent remediation and feature landings are traceable via PR references in git history.',
        'source_type': 'issue_pr',
        'source_ref': issues.strip('; '),
        'confidence': 'inferred',
        'conflicting_evidence': [],
        'resolution': 'accepted',
    })
emit({
    'claim': 'Git history anchors the vendor/auto-merge governance evolution (Decision B).',
    'source_type': 'git_history',
    'source_ref': f'{repo}@HEAD={head} lib/vendor.sh@{vendor_head}',
    'confidence': 'inferred',
    'conflicting_evidence': [],
    'resolution': 'accepted',
})
# Dual-regime auto-merge scope (README fleet carve-out vs cpp vendoring path — Decision B)
emit({
    'claim': 'Fleet repos gated by pr-automation / verify: never arm native auto-merge at PR create time.',
    'source_type': 'historical_doc',
    'source_ref': f'{repo}/README.md@{readme_head} (PR authoring — fleet-governed repos)',
    'confidence': 'verified',
    'conflicting_evidence': [],
    'resolution': 'accepted',
})
emit({
    'claim': 'Cpp vendoring path (Decision B): lib/vendor.sh correctly opens --auto PRs after local cpp-integrity is green.',
    'source_type': 'code',
    'source_ref': f'{repo}/lib/vendor.sh@{vendor_head} README.md@{readme_head} (fleet-vs-cpp carve-out)',
    'confidence': 'verified',
    'conflicting_evidence': [],
    'resolution': 'accepted',
})
PY
}

# ---------------------------------------------------------------------------
# M4 / POC 3d — cross-repo authority (POLICY.md §3 DUPLICATE_AUTHORITY, §8 --cross-repo)
# Closed profiles in cross-repo-profiles.yml. Live authority profiles plus regression fixture.
# ---------------------------------------------------------------------------

# dwl_cross_repo_default_owner_path <profile_id>
dwl_cross_repo_default_owner_path() {
  local profile_id="$1"
  case "$profile_id" in
    poc3d)
      if [ -d "$DWL_DEV_ROOT/capabilities/awa" ]; then
        printf '%s' "$DWL_DEV_ROOT/capabilities/awa"
      elif [ -d "$HOME/dev/capabilities/awa" ]; then
        printf '%s' "$HOME/dev/capabilities/awa"
      fi
      ;;
    poc3d-fixture)
      printf '%s' "$DWL_DOC_WARDEN_DIR/fixtures/poc3d/owner"
      ;;
    pr-automation-required-checks)
      if [ -d "$DWL_DEV_ROOT/personal/pr-automation-controller" ]; then
        printf '%s' "$DWL_DEV_ROOT/personal/pr-automation-controller"
      elif [ -d "$HOME/dev/personal/pr-automation-controller" ]; then
        printf '%s' "$HOME/dev/personal/pr-automation-controller"
      fi
      ;;
  esac
}

# dwl_cross_repo_default_dependent_path <profile_id>
dwl_cross_repo_default_dependent_path() {
  local profile_id="$1"
  case "$profile_id" in
    poc3d) printf '%s' "$DWL_DEV_ROOT" ;;
    poc3d-fixture) printf '%s' "$DWL_DOC_WARDEN_DIR/fixtures/poc3d/dependent" ;;
    pr-automation-required-checks) printf '%s' "$DWL_DEV_ROOT" ;;
  esac
}

# dwl_cross_repo_profile_exists <profile_id> → 0 if present
dwl_cross_repo_profile_exists() {
  local profile_id="$1"
  [ -f "$DWL_CROSS_REPO_PROFILES_FILE" ] || return 1
  dwl_run_python -c "
import yaml, sys
doc = yaml.safe_load(open('$DWL_CROSS_REPO_PROFILES_FILE')) or {}
print('yes' if sys.argv[1] in (doc.get('profiles') or {}) else 'no')
" "$profile_id" 2>/dev/null | grep -qxF yes
}

# dwl_cross_repo_owner_github_repo <profile_id> → e.g. KleinPerkins/awa
dwl_cross_repo_owner_github_repo() {
  local profile_id="$1"
  [ -f "$DWL_CROSS_REPO_PROFILES_FILE" ] || return 1
  dwl_run_python -c "
import yaml, sys
doc = yaml.safe_load(open('$DWL_CROSS_REPO_PROFILES_FILE')) or {}
p = (doc.get('profiles') or {}).get(sys.argv[1]) or {}
print((p.get('owner') or {}).get('repo', ''))
" "$profile_id" 2>/dev/null
}

# dwl_cross_repo_dependent_slug <profile_id> → e.g. dev
dwl_cross_repo_dependent_slug() {
  local profile_id="$1"
  [ -f "$DWL_CROSS_REPO_PROFILES_FILE" ] || return 1
  dwl_run_python -c "
import yaml, sys
doc = yaml.safe_load(open('$DWL_CROSS_REPO_PROFILES_FILE')) or {}
p = (doc.get('profiles') or {}).get(sys.argv[1]) or {}
print((p.get('dependent') or {}).get('slug', ''))
" "$profile_id" 2>/dev/null
}

# dwl_cross_repo_topic_ids_csv <profile_id> → comma-separated topic ids from profile
dwl_cross_repo_topic_ids_csv() {
  local profile_id="$1"
  [ -f "$DWL_CROSS_REPO_PROFILES_FILE" ] || return 1
  dwl_run_python -c "
import yaml, sys
doc = yaml.safe_load(open('$DWL_CROSS_REPO_PROFILES_FILE')) or {}
topics = (doc.get('profiles') or {}).get(sys.argv[1], {}).get('topics') or []
print(','.join(t.get('id', '') for t in topics if t.get('id')))
" "$profile_id" 2>/dev/null
}

# dwl_cross_repo_dependent_paths_csv <profile_id> → newline-separated unique dependent_paths
dwl_cross_repo_dependent_paths_csv() {
  local profile_id="$1"
  [ -f "$DWL_CROSS_REPO_PROFILES_FILE" ] || return 1
  dwl_run_python -c "
import yaml, sys
doc = yaml.safe_load(open('$DWL_CROSS_REPO_PROFILES_FILE')) or {}
topics = (doc.get('profiles') or {}).get(sys.argv[1], {}).get('topics') or []
paths = sorted({p for t in topics for p in (t.get('dependent_paths') or []) if p})
print('\n'.join(paths))
" "$profile_id" 2>/dev/null
}

# dwl_git_common_dir_abs <repo_root> → absolute git common dir (worktree-safe)
dwl_git_common_dir_abs() {
  local repo="$1" common
  common="$(git -C "$repo" rev-parse --git-common-dir 2>/dev/null)" || return 1
  if [ "${common#/}" != "$common" ]; then
    (cd "$common" && pwd -P)
  else
    (cd "$repo/$common" && pwd -P)
  fi
}

# dwl_cross_repo_repos_match <candidate_repo> <configured_repo> → 0 when same checkout/worktree
dwl_cross_repo_repos_match() {
  local candidate="$1" configured="$2"
  local candidate_real configured_real
  candidate_real="$(cd "$candidate" 2>/dev/null && pwd -P || printf '%s' "$candidate")"
  configured_real="$(cd "$configured" 2>/dev/null && pwd -P || printf '%s' "$configured")"
  [ "$candidate_real" = "$configured_real" ] && return 0
  # Worktree alias: only when both paths are git checkout roots (not in-repo subdirs)
  local configured_top candidate_top
  configured_top="$(git -C "$configured" rev-parse --show-toplevel 2>/dev/null)" || return 1
  configured_top="$(cd "$configured_top" && pwd -P)"
  [ "$configured_real" = "$configured_top" ] || return 1
  candidate_top="$(git -C "$candidate" rev-parse --show-toplevel 2>/dev/null)" || return 1
  candidate_top="$(cd "$candidate_top" && pwd -P)"
  [ "$candidate_real" = "$candidate_top" ] || return 1
  local ca cc
  ca="$(dwl_git_common_dir_abs "$candidate" 2>/dev/null)" || return 1
  cc="$(dwl_git_common_dir_abs "$configured" 2>/dev/null)" || return 1
  [ -n "$ca" ] && [ "$ca" = "$cc" ]
}

# dwl_cross_repo_profile_for_dependent_repo <repo_root> → profile_id when repo is the configured dependent
dwl_cross_repo_profile_for_dependent_repo() {
  local repo="$1" pid dep_path repo_real dep_real
  repo_real="$(cd "$repo" 2>/dev/null && pwd -P || printf '%s' "$repo")"
  for pid in poc3d-fixture poc3d; do
    dep_path="$(dwl_cross_repo_default_dependent_path "$pid")"
    [ -n "$dep_path" ] || continue
    dep_real="$(cd "$dep_path" 2>/dev/null && pwd -P || printf '%s' "$dep_path")"
    if [ "$repo_real" = "$dep_real" ]; then
      printf '%s' "$pid"
      return 0
    fi
  done
  for pid in poc3d-fixture poc3d; do
    dep_path="$(dwl_cross_repo_default_dependent_path "$pid")"
    [ -n "$dep_path" ] || continue
    if dwl_cross_repo_repos_match "$repo" "$dep_path"; then
      printf '%s' "$pid"
      return 0
    fi
  done
  return 1
}

# dwl_cross_repo_owner_adr_path_for_slug <owner_repo> <slug> → relative ADR path (existing or next slot)
dwl_cross_repo_owner_adr_path_for_slug() {
  local owner_repo="$1" slug="$2"
  local adr_rel existing next_num nnnn
  adr_rel="$(dwl_adr_dir "$owner_repo")"
  existing=""
  while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    local base
    base="$(basename "$candidate")"
    if [[ "$base" =~ ^[0-9]{4}-${slug}\.md$ ]]; then
      existing="$candidate"
      break
    fi
  done < <(find "$owner_repo/$adr_rel" -maxdepth 1 -name '????-*.md' ! -name 'README.md' 2>/dev/null)
  if [ -n "$existing" ]; then
    printf '%s/%s' "$adr_rel" "$(basename "$existing")"
    return 0
  fi
  next_num=1
  if [ -d "$owner_repo/$adr_rel" ]; then
    local last_num
    last_num="$(find "$owner_repo/$adr_rel" -maxdepth 1 -name '????-*.md' ! -name 'README.md' 2>/dev/null \
      | sed 's|.*/\([0-9][0-9][0-9][0-9]\)-.*|\1|' | sort -n | tail -1)"
    [ -n "$last_num" ] && next_num=$((10#$last_num + 1))
  fi
  nnnn="$(printf '%04d' "$next_num")"
  printf '%s/%s-%s.md' "$adr_rel" "$nnnn" "$slug"
}

# dwl_cross_repo_profile_for_repo <repo_root> → profile_id when repo is the configured owner
dwl_cross_repo_profile_for_repo() {
  local repo="$1" pid owner_path repo_real owner_real
  repo_real="$(cd "$repo" 2>/dev/null && pwd -P || printf '%s' "$repo")"
  for pid in poc3d-fixture poc3d; do
    owner_path="$(dwl_cross_repo_default_owner_path "$pid")"
    [ -n "$owner_path" ] || continue
    owner_real="$(cd "$owner_path" 2>/dev/null && pwd -P || printf '%s' "$owner_path")"
    if [ "$repo_real" = "$owner_real" ]; then
      printf '%s' "$pid"
      return 0
    fi
  done
  for pid in poc3d-fixture poc3d; do
    owner_path="$(dwl_cross_repo_default_owner_path "$pid")"
    [ -n "$owner_path" ] || continue
    if dwl_cross_repo_repos_match "$repo" "$owner_path"; then
      printf '%s' "$pid"
      return 0
    fi
  done
  return 1
}

# dwl_cross_repo_emit_ownership_map <profile_id> <owner_repo> <dependent_repo>
# Prints YAML ownership map to stdout; also emits topic:CLASSIFICATION hint lines on stderr prefix map:
dwl_cross_repo_emit_ownership_map() {
  local profile_id="$1" owner_repo="$2" dependent_repo="$3"
  DWL_XR_PROFILE="$profile_id" \
  DWL_XR_OWNER="$owner_repo" \
  DWL_XR_DEPENDENT="$dependent_repo" \
  DWL_XR_PROFILES="$DWL_CROSS_REPO_PROFILES_FILE" \
  python3 <<'PY'
import glob, os, sys, yaml

profile_id = os.environ['DWL_XR_PROFILE']
owner_root = os.environ['DWL_XR_OWNER']
dep_root = os.environ['DWL_XR_DEPENDENT']
profiles_path = os.environ['DWL_XR_PROFILES']

doc = yaml.safe_load(open(profiles_path)) or {}
profile = (doc.get('profiles') or {}).get(profile_id)
if not profile:
    print('error: unknown profile', profile_id, file=sys.stderr)
    sys.exit(2)

def read_paths(root, rel_paths):
    hits = []
    for rel in rel_paths or []:
        abs_p = os.path.join(root, rel)
        if os.path.isfile(abs_p):
            try:
                txt = open(abs_p, encoding='utf-8', errors='replace').read()
            except OSError:
                continue
            hits.append({'path': rel, 'abs': abs_p, 'text': txt})
    return hits

def markers_found(hits, markers):
    found = []
    for m in markers or []:
        ml = m.lower()
        for h in hits:
            if ml in h['text'].lower():
                found.append(m)
                break
    return found

def contested_check(hits, side, contested):
    if not contested:
        return False
    key = 'owner' if side == 'owner' else 'dependent'
    needle = contested.get(key, '')
    if not needle:
        return False
    nl = needle.lower()
    return any(nl in h['text'].lower() for h in hits)

topics_out = []
topic_classes = []

for topic in profile.get('topics') or []:
    tid = topic['id']
    owner_hits = read_paths(owner_root, topic.get('owner_paths'))
    dep_hits = read_paths(dep_root, topic.get('dependent_paths'))
    owner_markers = markers_found(owner_hits, topic.get('markers'))
    dep_markers = markers_found(dep_hits, topic.get('markers'))
    owner_active = len(owner_markers) > 0
    dep_active = len(dep_markers) > 0
    contested = topic.get('contested') or {}
    is_contra = False
    if contested and owner_active and dep_active:
        if contested_check(owner_hits, 'owner', contested) and contested_check(dep_hits, 'dependent', contested):
            is_contra = True
    if is_contra:
        cls = 'CONTRADICTORY'
    elif owner_active and dep_active:
        cls = 'DUPLICATE_AUTHORITY'
    elif owner_active:
        cls = 'OWNED_CORRECTLY'
    elif dep_active:
        cls = 'DEPENDENT_ONLY'
    else:
        cls = 'UNRESOLVED'
    topic_classes.append(cls)
    entry = {
        'topic_id': tid,
        'claim': topic.get('claim', ''),
        'classification': cls,
        'owner_repo': profile.get('owner', {}).get('repo', ''),
        'owner_paths_found': [h['path'] for h in owner_hits if any(m.lower() in h['text'].lower() for m in (topic.get('markers') or []))],
        'dependent_repo': profile.get('dependent', {}).get('repo', ''),
        'dependent_paths_found': [h['path'] for h in dep_hits if any(m.lower() in h['text'].lower() for m in (topic.get('markers') or []))],
        'markers_matched': sorted(set(owner_markers + dep_markers)),
        'recommended_owner': profile.get('owner', {}).get('repo', ''),
        'recommended_action': (
            'convert dependent copy to cross-repo pointer (trigger #6)' if cls == 'DUPLICATE_AUTHORITY'
            else 'resolve conflicting canonical statements before repair' if cls == 'CONTRADICTORY'
            else 'verify configured paths and markers; no authority detected in either repo' if cls == 'UNRESOLVED'
            else 'no action' if cls == 'OWNED_CORRECTLY'
            else 'add canonical copy in owner repo; dependent should pointer-only'
        ),
    }
    if contested and cls == 'CONTRADICTORY':
        entry['contested'] = contested
    topics_out.append(entry)
    print(f'map:{tid}:{cls}', file=sys.stderr)

if 'CONTRADICTORY' in topic_classes:
    exit_classification = 'CONTRADICTORY'
elif 'UNRESOLVED' in topic_classes:
    exit_classification = 'UNRESOLVED'
elif 'DUPLICATE_AUTHORITY' in topic_classes:
    exit_classification = 'DUPLICATE_AUTHORITY'
elif 'DEPENDENT_ONLY' in topic_classes:
    exit_classification = 'DEPENDENT_ONLY'
else:
    exit_classification = 'OWNED_CORRECTLY'

result = {
    'schema': 'doc-warden-ownership-map/v1',
    'profile': profile_id,
    'label': profile.get('label', ''),
    'scope_note': (profile.get('scope_note') or '').strip(),
    'owner_root': owner_root,
    'dependent_root': dep_root,
    'exit_classification': exit_classification,
    'topics': topics_out,
}
print('---')
print(yaml.safe_dump(result, sort_keys=False, default_flow_style=False).rstrip())
PY
}

# dwl_cross_repo_exit_classification <profile_id> <owner_repo> <dependent_repo>
dwl_cross_repo_exit_classification() {
  local profile_id="$1" owner_repo="$2" dependent_repo="$3"
  dwl_cross_repo_emit_ownership_map "$profile_id" "$owner_repo" "$dependent_repo" 2>/dev/null \
    | python3 -c "
import sys, yaml
raw = sys.stdin.read()
docs = list(yaml.safe_load_all(raw))
doc = docs[-1] if docs else {}
print(doc.get('exit_classification', 'CONTRADICTORY'))
" 2>/dev/null
}

# dwl_plan_trigger_cross_repo_owner — trigger #6 owner-repo ADR skeleton only (single-repo apply)
# Called via: dwl_plan_trigger_cross_repo_owner <owner_repo> <slug> <profile_id> [topic_ids_csv]
dwl_plan_trigger_cross_repo_owner() {
  local owner_repo="$1" slug="$2" profile_id="$3" topic_ids="${4:-}"
  if ! dwl_validate_slug "$slug"; then
    printf 'REFUSED: invalid slug: %s\n' "$slug" >&2
    return 1
  fi
  if ! dwl_trigger_in_catalog 6; then
    printf 'NEEDS_OPERATOR: trigger #6 is not in triggers.yml.\n' >&2
    return 1
  fi
  if [ -z "$topic_ids" ]; then
    topic_ids="$(dwl_cross_repo_topic_ids_csv "$profile_id")"
  fi
  local dep_slug owner_slug adr_path nnnn basename_adr
  dep_slug="$(dwl_cross_repo_dependent_slug "$profile_id")"
  owner_slug="$(dwl_cross_repo_owner_github_repo "$profile_id")"
  [ -n "$owner_slug" ] || owner_slug="$(basename "$owner_repo")"
  adr_path="$(dwl_cross_repo_owner_adr_path_for_slug "$owner_repo" "$slug")"
  if [ -f "$owner_repo/$adr_path" ]; then
    printf 'REFUSED: ADR file already exists: %s\n' "$adr_path" >&2
    return 1
  fi
  basename_adr="$(basename "$adr_path")"
  nnnn="${basename_adr%%-*}"
  printf 'create:%s:from-template:cross-repo-authority-adr.md:SLUG=%s:NNNN=%s:PROFILE_ID=%s:DEPENDENT_REPO=%s:TOPIC_IDS=%s:OWNER_REPO=%s\n' \
    "$adr_path" "$slug" "$nnnn" "$profile_id" "$dep_slug" "$topic_ids" "$owner_slug"
  printf 'index_row:%s/README.md:%s-%s.md:DRAFT\n' "$(dwl_adr_dir "$owner_repo")" "$nnnn" "$slug"
}

# dwl_cross_repo_trigger6_allowed <profile_id> <owner_repo> <dependent_repo>
# Refuses trigger #6 when cross-repo map is CONTRADICTORY or UNRESOLVED (POLICY exit 3).
dwl_cross_repo_trigger6_allowed() {
  local profile_id="$1" owner_repo="$2" dependent_repo="$3" cls
  cls="$(dwl_cross_repo_exit_classification "$profile_id" "$owner_repo" "$dependent_repo")"
  if [ -z "$cls" ]; then
    printf 'NEEDS_OPERATOR: trigger #6 blocked — cross-repo classification unavailable.\n' >&2
    return 1
  fi
  case "$cls" in
    CONTRADICTORY|UNRESOLVED)
      printf 'NEEDS_OPERATOR: trigger #6 blocked — cross-repo exit %s must be resolved first.\n' "$cls" >&2
      return 1
      ;;
  esac
  return 0
}

# dwl_plan_trigger_cross_repo_dependent — trigger #6 dependent-repo pointer blocks at governed paths
# Called via: dwl_plan_trigger_cross_repo_dependent <dependent_repo> <slug> <profile_id> <owner_adr_path> [topic_ids_csv]
dwl_plan_trigger_cross_repo_dependent() {
  local dependent_repo="$1" slug="$2" profile_id="$3" owner_adr_path="$4" topic_ids="${5:-}"
  if ! dwl_validate_slug "$slug"; then
    printf 'REFUSED: invalid slug: %s\n' "$slug" >&2
    return 1
  fi
  if [ -z "$topic_ids" ]; then
    topic_ids="$(dwl_cross_repo_topic_ids_csv "$profile_id")"
  fi
  local owner_github dep_path
  owner_github="$(dwl_cross_repo_owner_github_repo "$profile_id")"
  [ -n "$owner_github" ] || owner_github="unknown/owner"
  while IFS= read -r dep_path; do
    [ -n "$dep_path" ] || continue
    case "$dep_path" in
      *.md|*.mdc) ;;
      *) continue ;;
    esac
    printf 'append_block:%s:from-template:cross-repo-pointer-block.md:TOPIC=%s:OWNER_REPO=%s:OWNER_PATH=%s:PROFILE_ID=%s:TOPIC_ID=%s\n' \
      "$dep_path" "$slug" "$owner_github" "$owner_adr_path" "$profile_id" "$topic_ids"
  done <<< "$(dwl_cross_repo_dependent_paths_csv "$profile_id")"
}

# Back-compat alias: full cross-repo plan = owner actions only (dependent ships via separate repo PR)
dwl_plan_trigger_cross_repo() {
  dwl_plan_trigger_cross_repo_owner "$1" "$3" "$4" "$5"
}

# dwl_plan_reconstruct_repair <repo_root>
# Structural plan: greenfield baseline + reconstructed AGENTS.md + ADR-0001 skeleton.
dwl_plan_reconstruct_repair() {
  local repo="$1"
  local profile
  profile="$(dwl_reconstruct_profile_for_repo "$repo")"
  if [ -z "$profile" ]; then
    printf 'NEEDS_OPERATOR: no reconstruction profile for this repo — operator co-design required.\n' >&2
    return 1
  fi

  local actions
  actions="$(dwl_plan_greenfield "$repo")"
  # Replace append_block with full reconstructed AGENTS.md entrypoint
  actions="$(printf '%s' "$actions" | grep -v '^append_block:AGENTS.md:' || true)"
  [ -n "$actions" ] && actions="${actions}"$'\n'
  actions="${actions}create:AGENTS.md:from-template:agents-md-reconstructed-entry.md"$'\n'

  # ADR-0001 skeleton via trigger #1 (single sanctioned cpp edge writer)
  local adr_actions adr_rc=0
  adr_actions="$(dwl_plan_trigger "$repo" 1 'single-sanctioned-cpp-edge-writer' 2>&1)" || adr_rc=$?
  if [ "$adr_rc" -ne 0 ]; then
    printf '%s\n' "$adr_actions" >&2
    return "$adr_rc"
  fi
  actions="${actions}${adr_actions}"
  printf '%s' "$actions"
}

# ---------------------------------------------------------------------------
# Template rendering
# Substitutes {{PLANS_DIR}}, {{ADR_DIR}}, {{REPO_SLUG}}, {{DATE}}, {{TITLE}}, etc.
# ---------------------------------------------------------------------------

# dwl_render_template <template_name> <output_file> [key=val ...]
dwl_render_template() {
  local tmpl_name="$1" out_file="$2"
  shift 2
  local tmpl_file="$DWL_TEMPLATES_DIR/$tmpl_name"
  [ -f "$tmpl_file" ] || { printf 'ERROR: template not found: %s\n' "$tmpl_file" >&2; return 1; }
  local content
  content="$(cat "$tmpl_file")"
  local today
  today="$(date +%Y-%m-%d)"
  content="${content//\{\{DATE\}\}/$today}"
  # Apply any key=val substitutions
  for kv in "$@"; do
    local key="${kv%%=*}" val="${kv#*=}"
    content="${content//\{\{${key}\}\}/$val}"
  done
  # Derived substitutions (post key=val so SLUG can be set explicitly first)
  if grep -q '{{TITLE}}' <<<"$content" 2>/dev/null; then
    # Default TITLE = slug with hyphens→spaces, title-cased
    local slug_val=""
    for kv in "$@"; do
      [ "${kv%%=*}" = "SLUG" ] && { slug_val="${kv#*=}"; break; }
    done
    if [ -n "$slug_val" ]; then
      local title_val
      title_val="$(printf '%s' "$slug_val" | tr '-' ' ')"
      content="${content//\{\{TITLE\}\}/$title_val}"
    fi
  fi
  if grep -q '{{TERM}}' <<<"$content" 2>/dev/null; then
    local slug_val=""
    for kv in "$@"; do
      [ "${kv%%=*}" = "SLUG" ] && { slug_val="${kv#*=}"; break; }
    done
    if [ -n "$slug_val" ]; then
      local term_val
      term_val="$(printf '%s' "$slug_val" | tr '-' ' ')"
      content="${content//\{\{TERM\}\}/$term_val}"
    fi
  fi
  # Clear any remaining unreplaced {{SUBTITLE}} placeholders
  content="${content//\{\{SUBTITLE\}\}/}"
  # Default OWNER to repo slug when not supplied explicitly
  if grep -q '{{OWNER}}' <<<"$content" 2>/dev/null; then
    local owner_val=""
    for kv in "$@"; do
      [ "${kv%%=*}" = "OWNER" ] && { owner_val="${kv#*=}"; break; }
    done
    [ -z "$owner_val" ] && for kv in "$@"; do
      [ "${kv%%=*}" = "REPO_SLUG" ] && { owner_val="${kv#*=}"; break; }
    done
    [ -n "$owner_val" ] && content="${content//\{\{OWNER\}\}/$owner_val}"
  fi
  # Substitute NNNN if provided
  local nnnn_val=""
  for kv in "$@"; do
    [ "${kv%%=*}" = "NNNN" ] && { nnnn_val="${kv#*=}"; break; }
  done
  [ -n "$nnnn_val" ] && content="${content//\{\{NNNN\}\}/$nnnn_val}"
  # Clear any remaining unreplaced {{REPO_PATH}} — use REPO_SLUG/slug_val as placeholder
  if grep -q '{{REPO_PATH}}' <<<"$content" 2>/dev/null; then
    local slug_for_path=""
    for kv in "$@"; do
      [ "${kv%%=*}" = "SLUG" ] && { slug_for_path="${kv#*=}"; break; }
    done
    content="${content//\{\{REPO_PATH\}\}/$slug_for_path}"
  fi
  printf '%s\n' "$content" > "$out_file"
}

# ---------------------------------------------------------------------------
# Classifier — one pass per taxonomy item (POLICY.md §3, §4, §12)
# Returns one of the six classification values on stdout.
# ---------------------------------------------------------------------------

# dwl_classify_plans_dir <repo_root> <plans_dir_rel>
dwl_classify_plans_dir() {
  local repo="$1" plans_rel="$2"
  local plans_abs="$repo/$plans_rel"
  if [ ! -d "$plans_abs" ]; then
    printf '%s' "$DWL_MISSING"
    return
  fi
  printf '%s' "$DWL_CONFORMANT"
}

# dwl_classify_plans_readme <repo_root> <plans_dir_rel>
dwl_classify_plans_readme() {
  local repo="$1" plans_rel="$2"
  local readme_abs="$repo/$plans_rel/README.md"
  if [ ! -f "$readme_abs" ]; then
    printf '%s' "$DWL_MISSING"
    return
  fi
  # M2: local convention authority — index table + policy drift only
  if dwl_has_local_convention_authority "$repo" "$plans_rel"; then
    if ! dwl_plans_readme_has_index_table "$readme_abs"; then
      printf '%s' "$DWL_DRIFTED"
      return
    fi
    local drifts
    drifts="$(dwl_policy_drift_ids_for_plans_readme "$readme_abs")"
    if [ -n "$drifts" ]; then
      printf '%s' "$DWL_DRIFTED"
    else
      printf '%s' "$DWL_CONFORMANT"
    fi
    return
  fi
  # Default: canonical table header (POLICY.md §10 rule 4)
  if grep -qE '\|\s*Plan\s*\|' "$readme_abs" 2>/dev/null; then
    printf '%s' "$DWL_CONFORMANT"
  else
    printf '%s' "$DWL_DRIFTED"
  fi
}

# dwl_classify_adr_dir <repo_root> <adr_dir_rel>
dwl_classify_adr_dir() {
  local repo="$1" adr_rel="$2"
  local adr_abs="$repo/$adr_rel"
  if [ ! -d "$adr_abs" ]; then
    printf '%s' "$DWL_MISSING"
    return
  fi
  printf '%s' "$DWL_CONFORMANT"
}

# dwl_classify_adr_readme <repo_root> <adr_dir_rel>
dwl_classify_adr_readme() {
  local repo="$1" adr_rel="$2"
  local readme_abs="$repo/$adr_rel/README.md"
  if [ ! -f "$readme_abs" ]; then
    printf '%s' "$DWL_MISSING"
    return
  fi
  # Check for required table header (POLICY.md §10 rule 5)
  if grep -qE '\|\s*ADR\s*\|' "$readme_abs" 2>/dev/null; then
    printf '%s' "$DWL_CONFORMANT"
  else
    printf '%s' "$DWL_DRIFTED"
  fi
}

# dwl_classify_agents_md_block <repo_root>
# CONTRADICTORY: block markers appear more than once, or END precedes BEGIN —
# two authoritative signals conflict (the file both asserts and denies governance).
dwl_classify_agents_md_block() {
  local repo="$1"
  local agents_abs="$repo/AGENTS.md"
  local plans_rel
  plans_rel="$(dwl_plans_dir "$repo")"
  if [ ! -f "$agents_abs" ]; then
    printf '%s' "$DWL_MISSING"
    return
  fi
  # M2: hand-authored AGENTS.md with local convention pointer (POC 3b)
  if dwl_has_local_convention_authority "$repo" "$plans_rel" \
     && dwl_hand_authored_agents_md_ok "$repo" "$plans_rel"; then
    printf '%s' "$DWL_CONFORMANT"
    return
  fi
  local begin_count end_count
  begin_count="$(grep -cF "$DWL_BLOCK_BEGIN" "$agents_abs" 2>/dev/null || true)"
  end_count="$(grep -cF "$DWL_BLOCK_END" "$agents_abs" 2>/dev/null || true)"
  # Duplicate markers → CONTRADICTORY (e.g. two separate doc-warden blocks merged)
  if [ "${begin_count:-0}" -gt 1 ] || [ "${end_count:-0}" -gt 1 ]; then
    printf '%s' "$DWL_CONTRADICTORY"
    return
  fi
  # END before BEGIN → CONTRADICTORY (markers in wrong order)
  if [ "${begin_count:-0}" -eq 1 ] && [ "${end_count:-0}" -eq 1 ]; then
    local begin_line end_line
    begin_line="$(grep -nF "$DWL_BLOCK_BEGIN" "$agents_abs" 2>/dev/null | head -1 | cut -d: -f1)"
    end_line="$(grep -nF "$DWL_BLOCK_END" "$agents_abs" 2>/dev/null | head -1 | cut -d: -f1)"
    if [ -n "$begin_line" ] && [ -n "$end_line" ] && [ "$end_line" -le "$begin_line" ]; then
      printf '%s' "$DWL_CONTRADICTORY"
      return
    fi
    printf '%s' "$DWL_CONFORMANT"
    return
  fi
  printf '%s' "$DWL_DRIFTED"
}

# dwl_plan_has_unfilled_author_todos <fpath>
# True when template placeholder slots remain unfilled — not when an ACCEPTED (frozen) plan
# documents the placeholder syntax in prose (e.g. backtick-wrapped `<!-- TODO: author -->`).
dwl_plan_has_unfilled_author_todos() {
  local fpath="$1"
  if grep -qE '^\*\*Status:\*\*[[:space:]]*ACCEPTED([[:space:]]|$|-)' "$fpath" 2>/dev/null; then
    return 1
  fi
  grep -qE '(^|[[:space:]])<!-- TODO: author|^\*\*[^*]+\*\*:[[:space:]]*<!-- TODO: author|^# TODO: author' "$fpath" 2>/dev/null
}

# dwl_plan_header_area <fpath>
# Emits the header/preamble area only: everything before the first `## ...` section heading.
dwl_plan_header_area() {
  local fpath="$1"
  awk '
    /^## / { exit }
    { print }
  ' "$fpath"
}

# dwl_adr_has_unfilled_author_todos <fpath>
dwl_adr_has_unfilled_author_todos() {
  local fpath="$1"
  if grep -qiE '^Status:[[:space:]]*accepted([[:space:]]|$|-)' "$fpath" 2>/dev/null; then
    return 1
  fi
  grep -qE '(^|[[:space:]])<!-- TODO: author|^\*\*[^*]+\*\*:[[:space:]]*<!-- TODO: author|^# TODO: author' "$fpath" 2>/dev/null
}

# dwl_classify_plan_file <repo_root> <plans_dir_rel> <filename>
# Checks: naming convention, header shape, NEEDS_AUTHORING (TODO markers)
dwl_classify_plan_file() {
  local repo="$1" plans_rel="$2" fname="$3"
  local fpath="$repo/$plans_rel/$fname"
  [ -f "$fpath" ] || { printf '%s' "$DWL_MISSING"; return; }
  # Naming: <slug>-vN.md (POLICY.md §10 rule 1)
  if ! grep -qE '^[a-z0-9-]+-v[0-9]+\.md$' <<<"$fname"; then
    printf '%s' "$DWL_DRIFTED"; return
  fi
  # NEEDS_AUTHORING: unfilled template placeholder slots (not prose citations in ACCEPTED plans)
  if dwl_plan_has_unfilled_author_todos "$fpath"; then
    printf '%s' "$DWL_NEEDS_AUTHORING"; return
  fi
  local header_area
  header_area="$(dwl_plan_header_area "$fpath")"
  # Check for plan-header metadata (POLICY.md §10 rule 1). Header markers must be declared in the
  # header/preamble area only; later body lines that happen to start with the same token do not count.
  #
  # Marker probes below use here-strings (grep -qE 'PAT' <<<"$VAR"), never `printf … | grep -q`.
  # Under `set -o pipefail` (this lib enables it) a `printf "%s\n" "$VAR" | grep -q PAT` pipe is
  # SIGPIPE-susceptible: grep -q exits on first match, closes the read end, and if $VAR is larger
  # than the OS pipe buffer printf is killed by SIGPIPE (141); pipefail then propagates 141 as the
  # pipeline status, so `if ! …` falsely reads the marker as ABSENT → false DRIFTED on large plans.
  # A here-string feeds grep from a regular fd (no early-closing reader), so grep's own exit status
  # is authoritative. Matching semantics are identical (both append a trailing newline to $VAR).
  if ! grep -qE '^\*\*Status:\*\*|^\*\*Date:\*\*|^\*\*Owning repository:\*\*' <<<"$header_area"; then
    printf '%s' "$DWL_DRIFTED"; return
  fi
  # Every non-ACCEPTED plan must declare an explicit closed-vocabulary Plan-type. Accepted legacy
  # plans may remain markerless to preserve byte-identical immutability. If the marker is present,
  # only `standard` and `agentic-execution` are valid values.
  local is_accepted_plan=0 is_agentic_plan=0
  if grep -qE '^\*\*Status:\*\*[[:space:]]*ACCEPTED([[:space:]]|$|-)' <<<"$header_area"; then
    is_accepted_plan=1
  fi
  if grep -qE '^\*\*Plan-type:\*\*[[:space:]]*standard([[:space:]]|$)' <<<"$header_area"; then
    :
  elif grep -qE '^\*\*Plan-type:\*\*[[:space:]]*agentic-execution([[:space:]]|$)' <<<"$header_area"; then
    is_agentic_plan=1
  elif grep -qE '^\*\*Plan-type:\*\*' <<<"$header_area"; then
    printf '%s' "$DWL_DRIFTED"; return
  elif [ "$is_accepted_plan" -ne 1 ]; then
    printf '%s' "$DWL_DRIFTED"; return
  fi
  # Agentic-execution plans must additionally carry the writing-plans task-block shape WITHIN
  # their "## 5. Work items" section (POLICY.md §10 rule 10 / §12): a **Files:** block, an
  # **Interfaces:** block, and at least one checkbox step. Structural / presence-only; a marked-
  # but-unfilled skeleton is caught by the TODO→NEEDS_AUTHORING check above and never reaches here,
  # so a marker with a missing shape means a filled-but-malformed plan → DRIFTED. The shape must be
  # INSIDE the Work items section only — tokens in another section (an appendix, a work-item ledger,
  # background prose) do not satisfy the rule.
  if [ "$is_agentic_plan" -eq 1 ]; then
    local workitems
    workitems="$(awk '
      $0 ~ /^## +([0-9]+\.? *)?[Ww]ork [Ii]tems/ { in_wi=1; next }
      in_wi && $0 ~ /^## / { in_wi=0 }
      in_wi { print }
    ' "$fpath")"
    # Here-strings (not `printf … | grep -q`): $workitems can far exceed the OS pipe buffer, which
    # is exactly where the SIGPIPE-under-pipefail false-DRIFTED bug bit (see the header note above).
    if ! grep -qE '^[[:space:]]*\*\*Files:\*\*' <<<"$workitems" \
       || ! grep -qE '^[[:space:]]*\*\*Interfaces:\*\*' <<<"$workitems" \
       || ! grep -qE '^[[:space:]]*- \[[ xX]\]([[:space:]]|$)' <<<"$workitems"; then
      printf '%s' "$DWL_DRIFTED"; return
    fi
  fi
  # Byte-stability: receipt-bound content must match (POLICY.md §12 step 5)
  local rel_path="${plans_rel}/${fname}" receipt_digest current_digest
  receipt_digest="$(dwl_receipt_content_digest_for_path "$repo" "$rel_path")"
  if [ -n "$receipt_digest" ]; then
    current_digest="$(dwl_content_digest "$fpath")"
    if [ "$current_digest" != "$receipt_digest" ]; then
      printf '%s' "$DWL_DRIFTED"; return
    fi
  fi
  printf '%s' "$DWL_CONFORMANT"
}

# dwl_classify_adr_file <repo_root> <adr_dir_rel> <filename>
dwl_classify_adr_file() {
  local repo="$1" adr_rel="$2" fname="$3"
  local fpath="$repo/$adr_rel/$fname"
  [ -f "$fpath" ] || { printf '%s' "$DWL_MISSING"; return; }
  # Naming: NNNN-slug.md (POLICY.md §10 rule 2)
  if ! grep -qE '^[0-9]{4}-[a-z0-9-]+\.md$' <<<"$fname"; then
    printf '%s' "$DWL_DRIFTED"; return
  fi
  # NEEDS_AUTHORING: unfilled template placeholder slots (not prose citations in accepted ADRs)
  if dwl_adr_has_unfilled_author_todos "$fpath"; then
    printf '%s' "$DWL_NEEDS_AUTHORING"; return
  fi
  # Canonical v2 records use the active schema and accepted-freeze evidence.
  # Plain legacy prose retains the retired Nygard/receipt checks below.
  if [ -d "$repo/_ops/doc-warden/state/v2/receipts" ] \
      || head -n 1 "$fpath" | grep -q '^---' \
      || grep -q 'doc-warden/artifact/' "$fpath"; then
    local v2_rc
    if PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$DWL_DOC_WARDEN_DIR/v2${PYTHONPATH:+:$PYTHONPATH}" \
      dwl_run_python - "$repo" "$fpath" <<'PY' 2>/dev/null
import sys
from pathlib import Path
repo = Path(sys.argv[1]).resolve(strict=True)
path = Path(sys.argv[2]).absolute()
from doc_warden.adrs import validate_adr_record
try:
    if not validate_adr_record(repo, path):
        raise SystemExit(2)
except (ValueError, OSError, KeyError, TypeError):
    raise SystemExit(1)
PY
    then
      printf '%s' "$DWL_CONFORMANT"; return
    else
      v2_rc=$?
    fi
    if [ "$v2_rc" -ne 2 ]; then
      printf '%s' "$DWL_DRIFTED"; return
    fi
  fi
  # Nygard sections: ## Decision, ## Why, ## Consequences (POLICY.md §10 rule 3)
  if ! grep -qE '^## Decision' "$fpath" 2>/dev/null \
     || ! grep -qE '^## Why' "$fpath" 2>/dev/null \
     || ! grep -qE '^## Consequences' "$fpath" 2>/dev/null; then
    printf '%s' "$DWL_DRIFTED"; return
  fi
  # Byte-stability: receipt-bound content must match (POLICY.md §12 step 5)
  local rel_path="${adr_rel}/${fname}" receipt_digest current_digest
  receipt_digest="$(dwl_receipt_content_digest_for_path "$repo" "$rel_path")"
  if [ -n "$receipt_digest" ]; then
    current_digest="$(dwl_content_digest "$fpath")"
    if [ "$current_digest" != "$receipt_digest" ]; then
      printf '%s' "$DWL_DRIFTED"; return
    fi
  fi
  printf '%s' "$DWL_CONFORMANT"
}

# ---------------------------------------------------------------------------
# Trigger catalog lookup helpers
# ---------------------------------------------------------------------------

# dwl_trigger_ids_in_catalog — prints one trigger id per line from triggers.yml
# Returns non-zero if triggers.yml is missing or invalid YAML.
dwl_trigger_ids_in_catalog() {
  local py triggers_py
  if py="$(dwl_python 2>/dev/null)"; then
    "$py" -c "
import yaml, sys
d = yaml.safe_load(open('$DWL_TRIGGERS_FILE'))
for t in d.get('triggers', []):
    print(t['id'])
" 2>/dev/null && return 0
  fi
  triggers_py="$(dwl_trigger_ids_grep)"
  [ -n "$triggers_py" ] || return 1
  printf '%s\n' "$triggers_py"
}

# dwl_triggers_catalog_ok — true when triggers.yml loads successfully
dwl_triggers_catalog_ok() {
  [ -f "$DWL_TRIGGERS_FILE" ] && dwl_trigger_ids_in_catalog >/dev/null 2>&1
}

# dwl_trigger_in_catalog <id> → exits 0 if present, 1 if absent or catalog unreadable
dwl_trigger_in_catalog() {
  local tid="$1"
  dwl_triggers_catalog_ok || return 1
  dwl_trigger_ids_in_catalog | grep -qxF "$tid"
}

# ---------------------------------------------------------------------------
# Unknown-condition detector (B1 fix — POLICY.md §5, §6, §10)
#
# After baseline classification, scan for conditions that LOOK like a known
# trigger-worthy event but have no matching catalog entry. This is the source
# of NEEDS_OPERATOR classifications:
#
#   - ADR-format files found in adr_dir, but trigger #1 (ADR creation) is NOT
#     in triggers.yml → the files exist but we have no rule for how they got there.
#   - Runbook files found in docs/runbooks/, but trigger #3 (runbook) is NOT
#     in triggers.yml → same pattern.
#   - Glossary file found, but trigger #7 (glossary) is NOT in triggers.yml.
#
# CONFORMANT case (no NEEDS_OPERATOR): if the trigger IS in the catalog, the
# engine knows how the artifact got there — it was created by an approved repair.
# ---------------------------------------------------------------------------

# dwl_classify_unknown_conditions <repo_root> <adr_dir_rel>
# Prints "unknown:<key>:<description>:NEEDS_OPERATOR" lines for each unknown condition
dwl_classify_unknown_conditions() {
  local repo="$1" adr_rel="$2"
  local incidents_rel
  incidents_rel="$(dwl_incidents_dir "$repo")"

  if ! dwl_triggers_catalog_ok; then
    printf 'WARN: triggers.yml unreadable — treating trigger-worthy artifacts as NEEDS_OPERATOR\n' >&2
    if [ -d "$repo/$adr_rel" ]; then
      local adr_count=0
      while IFS= read -r fname; do
        [ -n "$fname" ] || continue
        adr_count=$((adr_count+1))
      done < <(dwl_gather_adrs "$repo" "$adr_rel")
      if [ "$adr_count" -gt 0 ]; then
        printf 'unknown:adr_files_catalog_unreadable:ADR file(s) exist but triggers.yml is unreadable:%s\n' "$DWL_NEEDS_OPERATOR"
      fi
    fi
    if [ -d "$repo/docs/runbooks" ]; then
      local runbook_count
      runbook_count="$(find "$repo/docs/runbooks" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l | tr -d ' ')"
      if [ "${runbook_count:-0}" -gt 0 ]; then
        printf 'unknown:runbook_files_catalog_unreadable:Runbook file(s) exist but triggers.yml is unreadable:%s\n' "$DWL_NEEDS_OPERATOR"
      fi
    fi
    if [ -d "$repo/$incidents_rel" ]; then
      local incident_count
      incident_count="$(find "$repo/$incidents_rel" -maxdepth 1 -name "*.md" ! -name "README.md" 2>/dev/null | wc -l | tr -d ' ')"
      if [ "${incident_count:-0}" -gt 0 ]; then
        printf 'unknown:incident_files_catalog_unreadable:Incident record file(s) exist but triggers.yml is unreadable:%s\n' "$DWL_NEEDS_OPERATOR"
      fi
    fi
    if [ -f "$repo/docs/GLOSSARY.md" ]; then
      printf 'unknown:glossary_catalog_unreadable:GLOSSARY.md exists but triggers.yml is unreadable:%s\n' "$DWL_NEEDS_OPERATOR"
    fi
    if [ -d "$repo/docs/decisions" ] && [ "$(find "$repo/docs/decisions" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')" -gt 0 ]; then
      printf 'unknown:decisions_dir_catalog_unreadable:docs/decisions/ contains .md files but triggers.yml is unreadable:%s\n' "$DWL_NEEDS_OPERATOR"
    fi
    return 0
  fi

  # Condition: ADR file exists in adr_dir but trigger #1 is NOT in catalog
  if [ -d "$repo/$adr_rel" ]; then
    local adr_count=0
    while IFS= read -r fname; do
      [ -n "$fname" ] || continue
      adr_count=$((adr_count+1))
    done < <(dwl_gather_adrs "$repo" "$adr_rel")
    if [ "$adr_count" -gt 0 ] && ! dwl_trigger_in_catalog 1; then
      printf 'unknown:adr_files_without_trigger_1:ADR file(s) exist but trigger #1 (first architectural decision) is not in triggers.yml:%s\n' "$DWL_NEEDS_OPERATOR"
    fi
  fi

  # Condition: runbook files exist but trigger #3 is NOT in catalog
  if [ -d "$repo/docs/runbooks" ]; then
    local runbook_count
    runbook_count="$(find "$repo/docs/runbooks" -maxdepth 1 -name "*.md" 2>/dev/null | wc -l | tr -d ' ')"
    if [ "${runbook_count:-0}" -gt 0 ] && ! dwl_trigger_in_catalog 3; then
      printf 'unknown:runbook_files_without_trigger_3:Runbook file(s) exist but trigger #3 (first runbook) is not in triggers.yml:%s\n' "$DWL_NEEDS_OPERATOR"
    fi
  fi

  # Condition: incident records exist but trigger #4 is NOT in catalog
  if [ -d "$repo/$incidents_rel" ]; then
    local incident_count=0
    incident_count="$(find "$repo/$incidents_rel" -maxdepth 1 -name "*.md" ! -name "README.md" 2>/dev/null | wc -l | tr -d ' ')"
    if [ "${incident_count:-0}" -gt 0 ] && ! dwl_trigger_in_catalog 4; then
      printf 'unknown:incident_files_without_trigger_4:Incident record file(s) exist but trigger #4 (first incident/remediation) is not in triggers.yml:%s\n' "$DWL_NEEDS_OPERATOR"
    fi
  fi

  # Condition: glossary file exists but trigger #7 is NOT in catalog
  if [ -f "$repo/docs/GLOSSARY.md" ] && ! dwl_trigger_in_catalog 7; then
    printf 'unknown:glossary_without_trigger_7:GLOSSARY.md exists but trigger #7 (terminology ambiguity) is not in triggers.yml:%s\n' "$DWL_NEEDS_OPERATOR"
  fi

  # Condition: files exist in docs/decisions/ (non-standard location — no trigger covers this)
  # This is a permanent unknown condition used in tests and production: any repo that organises
  # decisions in docs/decisions/ (instead of docs/adr/) needs operator co-design to either
  # add a new trigger or migrate the files to the governed adr_dir location.
  if [ -d "$repo/docs/decisions" ] && [ "$(find "$repo/docs/decisions" -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')" -gt 0 ]; then
    printf 'unknown:decisions_dir_without_trigger:docs/decisions/ contains .md files but no doc-warden trigger covers this non-standard location — operator co-design required:%s\n' "$DWL_NEEDS_OPERATOR"
  fi
}

# ---------------------------------------------------------------------------
# Full repo classification — runs all baseline checks, returns a structured
# newline-separated list of "item:classification" pairs
# ---------------------------------------------------------------------------

# dwl_classify_repo <repo_root>
# Prints: "item_key:CLASSIFICATION" lines (one per item)
# "exit_classification" is the worst classification across all items
dwl_classify_repo() {
  local repo="$1"
  local plans_rel adr_rel
  plans_rel="$(dwl_plans_dir "$repo")"
  adr_rel="$(dwl_adr_dir "$repo")"

  local worst="$DWL_CONFORMANT"

  _dwl_emit() {
    local key="$1" cls="$2"
    printf '%s:%s\n' "$key" "$cls"
    # Track worst classification (order: CONTRADICTORY > NEEDS_OPERATOR > DRIFTED >
    #   NEEDS_AUTHORING > MISSING > CONFORMANT)
    case "$cls" in
      CONTRADICTORY)   worst="$DWL_CONTRADICTORY" ;;
      NEEDS_OPERATOR)
        case "$worst" in CONTRADICTORY) ;; *) worst="$DWL_NEEDS_OPERATOR" ;; esac
        ;;
      DRIFTED)
        case "$worst" in CONFORMANT|MISSING|NEEDS_AUTHORING) worst="$DWL_DRIFTED" ;; esac
        ;;
      NEEDS_AUTHORING)
        case "$worst" in CONFORMANT|MISSING) worst="$DWL_NEEDS_AUTHORING" ;; esac
        ;;
      MISSING)
        case "$worst" in CONFORMANT) worst="$DWL_MISSING" ;; esac
        ;;
    esac
  }

  _dwl_emit "plans_dir" "$(dwl_classify_plans_dir "$repo" "$plans_rel")"
  _dwl_emit "plans_readme" "$(dwl_classify_plans_readme "$repo" "$plans_rel")"
  _dwl_emit "adr_dir" "$(dwl_classify_adr_dir "$repo" "$adr_rel")"
  _dwl_emit "adr_readme" "$(dwl_classify_adr_readme "$repo" "$adr_rel")"
  _dwl_emit "agents_md_block" "$(dwl_classify_agents_md_block "$repo")"

  local skip_file_normalization=0
  if dwl_has_local_convention_authority "$repo" "$plans_rel"; then
    skip_file_normalization=1
    # Emit policy drift detail lines for operator visibility (POC 3b report-only phase)
    local readme_abs="$repo/$plans_rel/README.md"
    while IFS= read -r drift_id; do
      [ -n "$drift_id" ] || continue
      _dwl_emit "policy_drift:${plans_rel}/README.md:${drift_id}" "$DWL_DRIFTED"
    done < <(dwl_policy_drift_ids_for_plans_readme "$readme_abs")
  fi

  # Classify each plan file (shallow scan) — skipped when local convention authority is active
  if [ "$skip_file_normalization" -eq 0 ]; then
    while IFS= read -r fname; do
      [ -n "$fname" ] || continue
      _dwl_emit "plan:$fname" "$(dwl_classify_plan_file "$repo" "$plans_rel" "$fname")"
    done < <(dwl_gather_plans "$repo" "$plans_rel")
    while IFS= read -r fname; do
      [ -n "$fname" ] || continue
      _dwl_emit "superseded_plan:${plans_rel}/${fname}" "$DWL_DRIFTED"
    done < <(dwl_superseded_plans_on_active_surface "$repo" "$plans_rel")
  fi

  # Classify each ADR file (shallow scan) — skipped when local convention authority is active
  if [ "$skip_file_normalization" -eq 0 ]; then
    while IFS= read -r fname; do
      [ -n "$fname" ] || continue
      _dwl_emit "adr:$fname" "$(dwl_classify_adr_file "$repo" "$adr_rel" "$fname")"
    done < <(dwl_gather_adrs "$repo" "$adr_rel")
  fi

  # Detect unknown conditions (NEEDS_OPERATOR / CONTRADICTORY production — B1 fix)
  while IFS=: read -r prefix key desc cls; do
    [ -n "$key" ] || continue
    _dwl_emit "${prefix}:${key}" "$cls"
    # Emit the description as a hint line
    printf 'hint:%s:%s\n' "$key" "$desc"
  done < <(dwl_classify_unknown_conditions "$repo" "$adr_rel")

  printf 'exit_classification:%s\n' "$worst"
}

# ---------------------------------------------------------------------------
# Slug and path safety (POLICY.md §8 — closed vocabulary for trigger slugs)
# ---------------------------------------------------------------------------

# dwl_glossary_term_title <slug> — heading text for a glossary term (hyphens → spaces)
dwl_glossary_term_title() {
  printf '%s' "$1" | sed 's/-/ /g'
}

# dwl_glossary_has_term <repo> <glossary_rel_path> <slug>
dwl_glossary_has_term() {
  local repo="$1" glossary_path="$2" slug="$3"
  local term_title
  term_title="$(dwl_glossary_term_title "$slug")"
  grep -qF "## ${term_title}" "$repo/$glossary_path" 2>/dev/null
}

# dwl_validate_slug <slug> — kebab-case only; rejects path traversal segments
dwl_validate_slug() {
  local slug="$1"
  [ -n "$slug" ] || return 1
  case "$slug" in
    */*|*\\*|*..*) return 1 ;;
  esac
  case "$slug" in
    *[!a-z0-9-]*) return 1 ;;
  esac
  case "$slug" in
    -*) return 1 ;;
  esac
  case "$slug" in
    *-) return 1 ;;
  esac
  return 0
}

# dwl_path_under_repo <repo_root> <relative_path> — refuse writes outside repo root
dwl_path_under_repo() {
  local repo="$1" rel_path="$2"
  case "$rel_path" in
    /*|*..*) return 1 ;;
  esac
  local abs_path="$repo/$rel_path"
  local canon_repo canon_target
  canon_repo="$(cd "$repo" && pwd -P)" || return 1
  if [ -e "$abs_path" ]; then
    if [ -d "$abs_path" ]; then
      canon_target="$(cd "$abs_path" && pwd -P)"
    else
      canon_target="$(cd "$(dirname "$abs_path")" && pwd -P)/$(basename "$abs_path")"
    fi
  else
    local resolved
    resolved="$(DWL_PATH_REPO="$canon_repo" DWL_PATH_REL="$rel_path" python3 <<'PY'
import os, sys
repo = os.environ['DWL_PATH_REPO']
rel = os.environ['DWL_PATH_REL']
target = os.path.normpath(os.path.join(repo, rel))
if target != repo and not target.startswith(repo + os.sep):
    sys.exit(1)
print(target)
PY
)" || return 1
    canon_target="$resolved"
  fi
  case "$canon_target" in
    "$canon_repo"|"$canon_repo"/*) return 0 ;;
    *) return 1 ;;
  esac
}

# dwl_index_row_format <readme_path> <filename> <status> <date>
# Plans index: Plan | Status | Date | Notes
# ADR index:   ADR | Title | Status | Date
# Incident index: Incident | Status | Date | Notes
dwl_index_row_format() {
  local readme_path="$1" fname="$2" status="$3" date="$4"
  if echo "$readme_path" | grep -qE '/adr/README\.md$'; then
    local title
    title="$(printf '%s' "$fname" | sed -E 's/^[0-9]{4}-//;s/-v[0-9]+\.md$//;s/\.md$//;s/-/ /g')"
    printf '| %s | %s | %s | %s |' "$fname" "$title" "$status" "$date"
  elif echo "$readme_path" | grep -qE '/incidents/README\.md$'; then
    printf '| [%s](%s) | %s | %s | |' "$fname" "$fname" "$status" "$date"
  else
    printf '| [%s](%s) | %s | %s | |' "$fname" "$fname" "$status" "$date"
  fi
}

# dwl_index_row_insert <abs_path> <fname> <status> <date> <new_row> <mode>
# mode: replace_placeholder | append_after_header
dwl_index_row_insert() {
  local abs_path="$1" fname_field="$2" status_field="$3" today_field="$4" new_row="$5" mode="$6"
  DWL_INDEX_ABS="$abs_path" \
  DWL_INDEX_FNAME="$fname_field" \
  DWL_INDEX_STATUS="$status_field" \
  DWL_INDEX_DATE="$today_field" \
  DWL_INDEX_ROW="$new_row" \
  DWL_INDEX_MODE="$mode" \
  python3 <<'PY'
import os
abs_path = os.environ['DWL_INDEX_ABS']
fname = os.environ['DWL_INDEX_FNAME']
status = os.environ['DWL_INDEX_STATUS']
today = os.environ['DWL_INDEX_DATE']
new_row = os.environ['DWL_INDEX_ROW']
mode = os.environ['DWL_INDEX_MODE']
txt = open(abs_path).read()
if mode == 'replace_placeholder':
    old = '| <!-- TODO: doc-warden will populate rows here via repair --> | | | |'
    new = new_row + '\n' + old
    if old in txt:
        open(abs_path, 'w').write(txt.replace(old, new, 1))
    else:
        lines = txt.splitlines(keepends=True)
        out = []
        inserted = False
        for line in lines:
            out.append(line)
            if not inserted and line.strip().startswith('|---'):
                out.append(new_row + '\n')
                inserted = True
        open(abs_path, 'w').writelines(out)
else:
    lines = txt.splitlines(keepends=True)
    out = []
    inserted = False
    for i, line in enumerate(lines):
        if not inserted and i > 0 and lines[i-1].strip().startswith('|---'):
            out.append(new_row + '\n')
            inserted = True
        out.append(line)
    if not inserted:
        out.append(new_row + '\n')
    open(abs_path, 'w').writelines(out)
PY
}

# ---------------------------------------------------------------------------
# Action planner (POLICY.md §8)
# Produces structural actions only. Semantic items are flagged, never auto-planned.
# Output: "action_type:path:detail" lines + "plan_digest:SHA" at end
# ---------------------------------------------------------------------------

# dwl_plan_greenfield <repo_root>
# Plans the baseline inheritance structure for a brand-new repo.
# Returns action lines; caller verifies pre-check before writing.
dwl_plan_greenfield() {
  local repo="$1"
  local plans_rel adr_rel
  plans_rel="$(dwl_plans_dir "$repo")"
  adr_rel="$(dwl_adr_dir "$repo")"
  local repo_slug
  repo_slug="$(basename "$repo")"

  # Actions: create dirs + index files + AGENTS.md block
  local actions=""

  # plans_dir
  if [ ! -d "$repo/$plans_rel" ]; then
    actions="${actions}${DWL_ACTION_CREATE}:${plans_rel}/:directory\n"
  fi
  # plans README
  if [ ! -f "$repo/$plans_rel/README.md" ]; then
    actions="${actions}${DWL_ACTION_CREATE}:${plans_rel}/README.md:from-template:docs-plans-README.md\n"
  fi
  # adr_dir
  if [ ! -d "$repo/$adr_rel" ]; then
    actions="${actions}${DWL_ACTION_CREATE}:${adr_rel}/:directory\n"
  fi
  # adr README
  if [ ! -f "$repo/$adr_rel/README.md" ]; then
    actions="${actions}${DWL_ACTION_CREATE}:${adr_rel}/README.md:from-template:docs-adr-README.md\n"
  fi
  # AGENTS.md pointer block
  if ! grep -qF "$DWL_BLOCK_BEGIN" "$repo/AGENTS.md" 2>/dev/null; then
    actions="${actions}${DWL_ACTION_APPEND_BLOCK}:AGENTS.md:from-template:agents-md-pointer-block.md\n"
  fi

  printf '%b' "$actions"
}

# ---------------------------------------------------------------------------
# Trigger-fired action planner (POLICY.md §5 — trigger model, §8 — deterministic split)
# Fires one explicit trigger from the closed catalog with a caller-supplied slug.
# Supports trigger #2 (plan), #3 (runbook), #4 (incident), #7 (glossary).
# Returns action lines for the structural skeleton; semantic prose is always NEEDS_AUTHORING.
# ---------------------------------------------------------------------------

# dwl_plan_trigger <repo_root> <trigger_id> <slug>
dwl_plan_trigger() {
  local repo="$1" trigger_id="$2" slug="$3"
  local plans_rel adr_rel
  plans_rel="$(dwl_plans_dir "$repo")"
  adr_rel="$(dwl_adr_dir "$repo")"

  if ! dwl_validate_slug "$slug"; then
    printf 'REFUSED: invalid slug (use lowercase letters, digits, hyphens only): %s\n' "$slug" >&2
    return 1
  fi

  # Validate trigger is in the catalog
  if ! dwl_trigger_in_catalog "$trigger_id"; then
    printf 'NEEDS_OPERATOR: trigger #%s is not in triggers.yml — update triggers.yml first.\n' "$trigger_id" >&2
    return 1
  fi

  case "$trigger_id" in
    1)  # first-architectural-decision → ADR skeleton + README index row
      # NNNN = next sequential 4-digit number based on existing ADR files
      local next_num=1
      if [ -d "$repo/$adr_rel" ]; then
        local last_num
        last_num="$(find "$repo/$adr_rel" -maxdepth 1 -name '????-*.md' ! -name 'README.md' 2>/dev/null \
          | sed 's|.*/\([0-9][0-9][0-9][0-9]\)-.*|\1|' | sort -n | tail -1)"
        [ -n "$last_num" ] && next_num=$((10#$last_num + 1))
      fi
      local nnnn
      nnnn="$(printf '%04d' "$next_num")"
      local adr_path="${adr_rel}/${nnnn}-${slug}.md"
      if [ -f "$repo/$adr_path" ]; then
        printf 'REFUSED: ADR file already exists: %s\n' "$adr_path" >&2
        return 1
      fi
      printf 'create:%s:from-template:adr-entry.md:SLUG=%s:NNNN=%s\n' "$adr_path" "$slug" "$nnnn"
      printf 'index_row:%s/README.md:%s-%s.md:DRAFT\n' "$adr_rel" "$nnnn" "$slug"
      ;;
    2)  # first-multi-session-plan → plan skeleton + README index row
      local plan_path="${plans_rel}/${slug}-v1.md"
      if [ -f "$repo/$plan_path" ]; then
        printf 'REFUSED: plan file already exists: %s\n' "$plan_path" >&2
        return 1
      fi
      printf 'create:%s:from-template:plan-header.md:SLUG=%s\n' "$plan_path" "$slug"
      printf 'index_row:%s/README.md:%s-v1.md:DRAFT\n' "$plans_rel" "$slug"
      ;;
    3)  # first-operator-runbook → runbook skeleton
      local runbook_path="docs/runbooks/${slug}.md"
      if [ -f "$repo/$runbook_path" ]; then
        printf 'REFUSED: runbook file already exists: %s\n' "$runbook_path" >&2
        return 1
      fi
      printf 'create:%s:from-template:runbook.md:SLUG=%s\n' "$runbook_path" "$slug"
      ;;
    4)  # first-incident-remediation → incident record skeleton + README index row
      local incidents_rel incident_path
      incidents_rel="$(dwl_incidents_dir "$repo")"
      incident_path="${incidents_rel}/${slug}.md"
      if [ -f "$repo/$incident_path" ]; then
        printf 'REFUSED: incident record already exists: %s\n' "$incident_path" >&2
        return 1
      fi
      printf 'create:%s:from-template:incident-record.md:SLUG=%s\n' "$incident_path" "$slug"
      printf 'index_row:%s/README.md:%s.md:DRAFT\n' "$incidents_rel" "$slug"
      ;;
    7)  # first-terminology-ambiguity → glossary skeleton or append term
      local glossary_path="docs/GLOSSARY.md"
      if [ -f "$repo/$glossary_path" ]; then
        if dwl_glossary_has_term "$repo" "$glossary_path" "$slug"; then
          printf 'REFUSED: glossary term already exists: %s\n' "$slug" >&2
          return 1
        fi
        printf 'append_glossary_term:%s:SLUG=%s\n' "$glossary_path" "$slug"
      else
        printf 'create:%s:from-template:glossary.md:SLUG=%s\n' "$glossary_path" "$slug"
      fi
      ;;
    6)  # first-cross-repo-authority-boundary → owner ADR or dependent pointer (separate repo PRs)
      local profile_id6 role6=""
      profile_id6="$(dwl_cross_repo_profile_for_repo "$repo")" && role6=owner
      if [ -z "$profile_id6" ]; then
        profile_id6="$(dwl_cross_repo_profile_for_dependent_repo "$repo")" && role6=dependent
      fi
      if [ -z "$profile_id6" ]; then
        printf 'NEEDS_OPERATOR: trigger #6 on this repo requires a known cross-repo profile (owner or dependent path).\n' >&2
        return 1
      fi
      local xr_owner xr_dep
      if [ "$role6" = owner ]; then
        xr_owner="$repo"
        xr_dep="$(dwl_cross_repo_default_dependent_path "$profile_id6")"
      else
        xr_owner="$(dwl_cross_repo_default_owner_path "$profile_id6")"
        xr_dep="$repo"
      fi
      if [ -z "$xr_owner" ] || [ ! -d "$xr_owner" ] || [ -z "$xr_dep" ] || [ ! -d "$xr_dep" ]; then
        printf 'NEEDS_OPERATOR: cross-repo check paths missing for profile %s (owner/dependent checkout required).\n' "$profile_id6" >&2
        return 1
      fi
      dwl_cross_repo_trigger6_allowed "$profile_id6" "$xr_owner" "$xr_dep" || return 1
      if [ "$role6" = owner ]; then
        dwl_plan_trigger_cross_repo_owner "$repo" "$slug" "$profile_id6"
      else
        local owner_repo6 owner_adr6
        owner_repo6="$(dwl_cross_repo_default_owner_path "$profile_id6")"
        if [ -z "$owner_repo6" ] || [ ! -d "$owner_repo6" ]; then
          printf 'NEEDS_OPERATOR: owner checkout required for dependent trigger #6 (profile %s): %s\n' \
            "$profile_id6" "${owner_repo6:-<unset>}" >&2
          return 1
        fi
        owner_adr6="$(dwl_cross_repo_owner_adr_path_for_slug "$owner_repo6" "$slug")"
        dwl_plan_trigger_cross_repo_dependent "$repo" "$slug" "$profile_id6" "$owner_adr6"
      fi
      ;;
    *)
      printf 'NEEDS_OPERATOR: trigger #%s has no structural action implemented (M2+).\n' "$trigger_id" >&2
      return 1
      ;;
  esac
}

# dwl_plan_repair <repo_root>
# Plans structural repairs for an existing repo.
# Returns action lines; DRIFTED items include diff hints.
dwl_plan_repair() {
  local repo="$1"
  local plans_rel adr_rel
  plans_rel="$(dwl_plans_dir "$repo")"
  adr_rel="$(dwl_adr_dir "$repo")"

  local actions=""
  local classifications
  classifications="$(dwl_classify_repo "$repo")"

  while IFS=: read -r key cls; do
    case "$key" in
      plans_dir)
        [ "$cls" = "$DWL_MISSING" ] && actions="${actions}${DWL_ACTION_CREATE}:${plans_rel}/:directory\n"
        ;;
      plans_readme)
        [ "$cls" = "$DWL_MISSING" ] && actions="${actions}${DWL_ACTION_CREATE}:${plans_rel}/README.md:from-template:docs-plans-README.md\n"
        if [ "$cls" = "$DWL_DRIFTED" ]; then
          if dwl_has_local_convention_authority "$repo" "$plans_rel"; then
            local readme_abs="$repo/$plans_rel/README.md"
            local drift_ids
            drift_ids="$(dwl_policy_drift_ids_for_plans_readme "$readme_abs")"
            if [ -n "$drift_ids" ]; then
              actions="${actions}patch:${plans_rel}/README.md:policy_drift:all\n"
            fi
          else
            actions="${actions}DRIFTED:${plans_rel}/README.md:missing-table-header\n"
          fi
        fi
        ;;
      adr_dir)
        [ "$cls" = "$DWL_MISSING" ] && actions="${actions}${DWL_ACTION_CREATE}:${adr_rel}/:directory\n"
        ;;
      adr_readme)
        [ "$cls" = "$DWL_MISSING" ] && actions="${actions}${DWL_ACTION_CREATE}:${adr_rel}/README.md:from-template:docs-adr-README.md\n"
        [ "$cls" = "$DWL_DRIFTED" ] && actions="${actions}DRIFTED:${adr_rel}/README.md:missing-table-header\n"
        ;;
      agents_md_block)
        [ "$cls" = "$DWL_MISSING" ] && actions="${actions}${DWL_ACTION_APPEND_BLOCK}:AGENTS.md:from-template:agents-md-pointer-block.md\n"
        [ "$cls" = "$DWL_DRIFTED" ] && actions="${actions}DRIFTED:AGENTS.md:incomplete-pointer-block\n"
        ;;
      exit_classification) ;;  # skip summary line
      policy_drift:*) ;;  # detail lines; repair actions emitted via plans_readme branch
      superseded_plan:*) ;;  # detail lines; repair actions emitted below
      plan:*|adr:*) ;;  # file-level classifications are informational in the plan
    esac
  done <<< "$classifications"

  # Superseded plans still on active surface → archive move + index/routing cleanup (§9, acceptance #10)
  while IFS= read -r fname; do
    [ -n "$fname" ] || continue
    actions="${actions}move:${plans_rel}/${fname}:docs/archive/plans/${fname}\n"
    actions="${actions}remove_index_row:${plans_rel}/README.md:${fname}\n"
    if [ -f "$repo/AGENTS.md" ] && grep -qF "$fname" "$repo/AGENTS.md" 2>/dev/null; then
      actions="${actions}patch:AGENTS.md:remove_plan_ref:${fname}\n"
    fi
  done < <(dwl_superseded_plans_on_active_surface "$repo" "$plans_rel")

  printf '%b' "$actions"
}

# dwl_plan_digest <action_lines>
# Computes a SHA256 over the rendered content of planned-write files.
# For directories and appends, hashes the template content that would be written.
dwl_plan_digest() {
  local actions="$1" repo="$2"
  local plans_rel adr_rel
  plans_rel="$(dwl_plans_dir "$repo")"
  adr_rel="$(dwl_adr_dir "$repo")"
  local repo_slug
  repo_slug="$(basename "$repo")"

  local combined=""
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local action path detail
    action="${line%%:*}"
    path="$(echo "$line" | cut -d: -f2)"
    detail="${line#*:*:}"

    case "$action" in
      create|append_block)
        # Hash the post-substitution RENDERED content, not the raw template.
        # This catches date-substitution drift (A1 fix): a {{DATE}} that crosses
        # midnight between --dry-run and --approve would change the written file;
        # hashing rendered content makes the digest invalidate correctly.
        if echo "$detail" | grep -q "from-template:"; then
          local tmpl_raw_d="${detail#from-template:}"
          local tmpl_name="${tmpl_raw_d%%:*}"
          local tmpl_extra_d="${tmpl_raw_d#*:}"
          [ "$tmpl_extra_d" = "$tmpl_raw_d" ] && tmpl_extra_d=""
          local rendered
          local kv_args_d=("PLANS_DIR=$plans_rel" "ADR_DIR=$adr_rel" "REPO_SLUG=$repo_slug")
          if [ -n "$tmpl_extra_d" ]; then
            IFS=: read -ra extra_kvs_d <<< "$tmpl_extra_d"
            for ekv_d in "${extra_kvs_d[@]}"; do
              [ -n "$ekv_d" ] && kv_args_d+=("$ekv_d")
            done
          fi
          local tmpdig
          tmpdig="$(mktemp)"
          dwl_render_template "$tmpl_name" "$tmpdig" "${kv_args_d[@]}" 2>/dev/null
          rendered="$(cat "$tmpdig" 2>/dev/null)"
          rm -f "$tmpdig"
          if [ -n "$rendered" ]; then
            combined="${combined}$(printf '%s' "$rendered" | (sha256sum 2>/dev/null || shasum -a 256 2>/dev/null) | awk '{print $1}'):$path"$'\n'
          fi
        else
          # Directory create: constant token
          combined="${combined}directory:$path"$'\n'
        fi
        ;;
      DRIFTED) ;; # DRIFTED items have no write action; excluded from digest
      patch)
        if echo "$detail" | grep -q '^remove_plan_ref:'; then
          local fname_rp="${detail#remove_plan_ref:}"
          if [ -f "$repo/$path" ]; then
            local tmp_rp patched_rp
            tmp_rp="$(mktemp)"
            cp "$repo/$path" "$tmp_rp"
            if dwl_agents_md_remove_plan_ref "$tmp_rp" "$fname_rp" 2>/dev/null; then
              patched_rp="$(cat "$tmp_rp")"
              combined="${combined}$(printf '%s' "$patched_rp" | (sha256sum 2>/dev/null || shasum -a 256 2>/dev/null) | awk '{print $1}'):$path:remove_plan_ref:$fname_rp"$'\n'
            fi
            rm -f "$tmp_rp"
          fi
        else
          local drift_ids_all patched_content
          drift_ids_all="$(dwl_policy_drift_ids_for_plans_readme "$repo/$path")"
          patched_content="$(dwl_render_patched_plans_readme "$repo" "$plans_rel" "$drift_ids_all")"
          if [ -n "$patched_content" ]; then
            combined="${combined}$(printf '%s' "$patched_content" | (sha256sum 2>/dev/null || shasum -a 256 2>/dev/null) | awk '{print $1}'):$path"$'\n'
          fi
        fi
        ;;
      move)
        local dest_rel="${detail}"
        if [ -f "$repo/$path" ]; then
          combined="${combined}$(dwl_content_digest "$repo/$path"):$path->$dest_rel"$'\n'
        fi
        ;;
      remove_index_row)
        local fname_ri="${detail}"
        if [ -f "$repo/$path" ]; then
          local tmp_ri patched_ri
          tmp_ri="$(mktemp)"
          cp "$repo/$path" "$tmp_ri"
          if dwl_index_row_remove "$tmp_ri" "$fname_ri" 2>/dev/null; then
            patched_ri="$(cat "$tmp_ri")"
            combined="${combined}$(printf '%s' "$patched_ri" | (sha256sum 2>/dev/null || shasum -a 256 2>/dev/null) | awk '{print $1}'):$path:remove:$fname_ri"$'\n'
          fi
          rm -f "$tmp_ri"
        fi
        ;;
      index_row)
        local fname_d status_d today_d row_d
        fname_d="${detail%%:*}"
        status_d="${detail#*:}"
        today_d="$(date +%Y-%m-%d)"
        row_d="$(dwl_index_row_format "$path" "$fname_d" "$status_d" "$today_d")"
        combined="${combined}index_row:$path:$row_d"$'\n'
        ;;
      append_glossary_term)
        local slug_d="${detail#SLUG=}"
        combined="${combined}append_glossary_term:$path:term:$slug_d"$'\n'
        ;;
    esac
  done <<< "$actions"

  if [ -z "$combined" ]; then
    printf 'empty-plan'
  else
    printf '%s' "$combined" \
      | (sha256sum 2>/dev/null || shasum -a 256 2>/dev/null) \
      | awk '{print $1}'
  fi
}

# ---------------------------------------------------------------------------
# Repair executor (POLICY.md §8)
# Executes the action plan. Must be called only after digest verification.
# ---------------------------------------------------------------------------

# Rollback helpers — restore repo on mid-plan refusal (POLICY.md §8: no partial execution).
DWL_EXEC_ROLLBACK_DIR=""

dwl_exec_rollback_init() {
  DWL_EXEC_ROLLBACK_DIR="$(mktemp -d)"
  : > "$DWL_EXEC_ROLLBACK_DIR/.modified"
  : > "$DWL_EXEC_ROLLBACK_DIR/.created"
}

dwl_exec_rollback_cleanup() {
  rm -rf "$DWL_EXEC_ROLLBACK_DIR"
  DWL_EXEC_ROLLBACK_DIR=""
}

dwl_exec_track_path() {
  local abs_path="$1"
  local key bak_file
  [ -n "$DWL_EXEC_ROLLBACK_DIR" ] || return 0
  key="$(printf '%s' "$abs_path" | tr '/ ' '__')"
  if [ -f "$abs_path" ]; then
    bak_file="$DWL_EXEC_ROLLBACK_DIR/${key}.bak"
    cp "$abs_path" "$bak_file"
    grep -qxF "$abs_path" "$DWL_EXEC_ROLLBACK_DIR/.modified" 2>/dev/null \
      || printf '%s\n' "$abs_path" >> "$DWL_EXEC_ROLLBACK_DIR/.modified"
  else
    grep -qxF "$abs_path" "$DWL_EXEC_ROLLBACK_DIR/.created" 2>/dev/null \
      || printf '%s\n' "$abs_path" >> "$DWL_EXEC_ROLLBACK_DIR/.created"
  fi
}

dwl_exec_rollback() {
  local abs_path key bak_file
  [ -n "$DWL_EXEC_ROLLBACK_DIR" ] || return 0
  while IFS= read -r abs_path; do
    [ -n "$abs_path" ] || continue
    key="$(printf '%s' "$abs_path" | tr '/ ' '__')"
    bak_file="$DWL_EXEC_ROLLBACK_DIR/${key}.bak"
    if [ -f "$bak_file" ]; then
      cp "$bak_file" "$abs_path"
    fi
  done < "$DWL_EXEC_ROLLBACK_DIR/.modified"
  while IFS= read -r abs_path; do
    [ -n "$abs_path" ] || continue
    [ -f "$abs_path" ] && rm -f "$abs_path"
  done < "$DWL_EXEC_ROLLBACK_DIR/.created"
  dwl_exec_rollback_cleanup
}

# dwl_plan_has_structural_actions <action_lines> → 0 if any writable action present
dwl_plan_has_structural_actions() {
  local actions="$1"
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local action="${line%%:*}"
    case "$action" in
      create|append_block|move|index_row|append_glossary_term|patch|remove_index_row) return 0 ;;
    esac
  done <<< "$actions"
  return 1
}

# dwl_execute_plan <action_lines> <repo_root>
# Returns: 0 clean, 1 NEEDS_AUTHORING skeletons, 2 refused (unsafe path / execution aborted)
dwl_execute_plan() {
  local actions="$1" repo="$2"
  local plans_rel adr_rel repo_slug
  plans_rel="$(dwl_plans_dir "$repo")"
  adr_rel="$(dwl_adr_dir "$repo")"
  repo_slug="$(basename "$repo")"

  local has_needs_authoring=0

  # Preflight: validate every path before any writes (no partial execution on escape).
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local action path detail
    action="${line%%:*}"
    path="$(echo "$line" | cut -d: -f2)"
    detail="${line#*:*:}"
    case "$action" in
      create|append_block|move|index_row|append_glossary_term|patch|remove_index_row)
        if ! dwl_path_under_repo "$repo" "$path"; then
          printf 'REFUSED: path escapes repo root: %s\n' "$path" >&2
          return 2
        fi
        if [ "$action" = "move" ]; then
          if ! dwl_path_under_repo "$repo" "$detail"; then
            printf 'REFUSED: move destination escapes repo root: %s\n' "$detail" >&2
            return 2
          fi
        fi
        ;;
    esac
  done <<< "$actions"

  # Preflight: dry-render all templates before any writes (no partial execution on render failure).
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local action path detail
    action="${line%%:*}"
    path="$(echo "$line" | cut -d: -f2)"
    detail="${line#*:*:}"
    case "$action" in
      create)
        if echo "$detail" | grep -q "from-template:"; then
          local tmpl_raw_pf="${detail#from-template:}"
          local tmpl_name_pf="${tmpl_raw_pf%%:*}"
          local tmpl_extra_pf="${tmpl_raw_pf#*:}"
          [ "$tmpl_extra_pf" = "$tmpl_raw_pf" ] && tmpl_extra_pf=""
          local kv_args_pf=("PLANS_DIR=$plans_rel" "ADR_DIR=$adr_rel" "REPO_SLUG=$repo_slug")
          if [ -n "$tmpl_extra_pf" ]; then
            IFS=: read -ra extra_kvs_pf <<< "$tmpl_extra_pf"
            for ekv_pf in "${extra_kvs_pf[@]}"; do
              [ -n "$ekv_pf" ] && kv_args_pf+=("$ekv_pf")
            done
          fi
          local tmp_pf
          tmp_pf="$(mktemp)"
          if ! dwl_render_template "$tmpl_name_pf" "$tmp_pf" "${kv_args_pf[@]}"; then
            rm -f "$tmp_pf"
            return 2
          fi
          rm -f "$tmp_pf"
        fi
        ;;
      append_block)
        if echo "$detail" | grep -q "from-template:"; then
          local tmpl_raw="${detail#from-template:}"
          local tmpl_name="${tmpl_raw%%:*}"
          local tmpl_extra="${tmpl_raw#*:}"
          [ "$tmpl_extra" = "$tmpl_raw" ] && tmpl_extra=""
          local kv_args_pf=("PLANS_DIR=$plans_rel" "ADR_DIR=$adr_rel" "REPO_SLUG=$repo_slug")
          if [ -n "$tmpl_extra" ]; then
            IFS=: read -ra extra_kvs_pf <<< "$tmpl_extra"
            for ekv_pf in "${extra_kvs_pf[@]}"; do
              [ -n "$ekv_pf" ] && kv_args_pf+=("$ekv_pf")
            done
          fi
          local tmp_pf
          tmp_pf="$(mktemp)"
          if ! dwl_render_template "$tmpl_name" "$tmp_pf" "${kv_args_pf[@]}"; then
            rm -f "$tmp_pf"
            return 2
          fi
          rm -f "$tmp_pf"
        fi
        ;;
    esac
  done <<< "$actions"

  # Preflight: verify patch actions before any writes (no partial execution on patch refusal).
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local action path detail
    action="${line%%:*}"
    path="$(echo "$line" | cut -d: -f2)"
    detail="${line#*:*:}"
    [ "$action" = "patch" ] || continue
    local abs_path="$repo/$path"
    if ! dwl_path_under_repo "$repo" "$path"; then
      printf 'REFUSED: path escapes repo root: %s\n' "$path" >&2
      return 2
    fi
    if [ ! -f "$abs_path" ]; then
      printf 'REFUSED: patch target missing: %s\n' "$path" >&2
      return 2
    fi
    if echo "$detail" | grep -q '^remove_plan_ref:'; then
      local fname_rp_pf="${detail#remove_plan_ref:}"
      local tmp_rp_pf
      tmp_rp_pf="$(mktemp)"
      cp "$abs_path" "$tmp_rp_pf"
      if ! dwl_agents_md_remove_plan_ref "$tmp_rp_pf" "$fname_rp_pf"; then
        rm -f "$tmp_rp_pf"
        printf 'REFUSED: no AGENTS.md plan reference to remove: %s\n' "$fname_rp_pf" >&2
        return 2
      fi
      rm -f "$tmp_rp_pf"
      continue
    fi
    local drift_id_pf="${detail#policy_drift:}"
    local patch_tmp drift_ids_pf applied_pf=0
    patch_tmp="$(mktemp)"
    cp "$abs_path" "$patch_tmp"
    if [ "$drift_id_pf" = "all" ]; then
      drift_ids_pf="$(dwl_policy_drift_ids_for_plans_readme "$abs_path")"
    else
      drift_ids_pf="$drift_id_pf"
    fi
    while IFS= read -r one_drift; do
      [ -n "$one_drift" ] || continue
      local next_tmp
      next_tmp="$(mktemp)"
      if dwl_apply_policy_patch "$patch_tmp" "$one_drift" "$next_tmp"; then
        mv "$next_tmp" "$patch_tmp"
        applied_pf=1
      else
        rm -f "$next_tmp"
      fi
    done <<< "$drift_ids_pf"
    rm -f "$patch_tmp"
    if [ "$applied_pf" -eq 0 ]; then
      printf 'REFUSED: no policy patches applicable: %s\n' "$path" >&2
      return 2
    fi
  done <<< "$actions"

  dwl_exec_rollback_init

  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local action path detail
    action="${line%%:*}"
    path="$(echo "$line" | cut -d: -f2)"
    detail="${line#*:*:}"

    local abs_path="$repo/$path"

    if ! dwl_path_under_repo "$repo" "$path"; then
      printf 'REFUSED: path escapes repo root: %s\n' "$path" >&2
      dwl_exec_rollback
      return 2
    fi

    case "$action" in
      create)
        if echo "$detail" | grep -q "from-template:"; then
          # detail may be: "from-template:<tmpl_name>" or "from-template:<tmpl_name>:KEY=val:KEY2=val2"
          local tmpl_raw="${detail#from-template:}"
          local tmpl_name="${tmpl_raw%%:*}"
          local tmpl_extra="${tmpl_raw#*:}"
          [ "$tmpl_extra" = "$tmpl_raw" ] && tmpl_extra=""
          # Ensure parent directory exists
          mkdir -p "$(dirname "$abs_path")"
          local kv_args=("PLANS_DIR=$plans_rel" "ADR_DIR=$adr_rel" "REPO_SLUG=$repo_slug")
          # Parse tmpl_extra as colon-separated KEY=val pairs
          if [ -n "$tmpl_extra" ]; then
            IFS=: read -ra extra_kvs <<< "$tmpl_extra"
            for ekv in "${extra_kvs[@]}"; do
              [ -n "$ekv" ] && kv_args+=("$ekv")
            done
          fi
          dwl_exec_track_path "$abs_path"
          dwl_render_template "$tmpl_name" "$abs_path" "${kv_args[@]}" || { dwl_exec_rollback; return 2; }
          # Check if the rendered template has TODO markers (skeleton = NEEDS_AUTHORING)
          grep -q 'TODO: author' "$abs_path" 2>/dev/null && has_needs_authoring=1
        elif echo "$detail" | grep -q "directory"; then
          mkdir -p "$abs_path"
        fi
        ;;
      append_block)
        if echo "$detail" | grep -q "from-template:"; then
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
          local rendered block_marker topic_slug=""
          rendered="$(mktemp)"
          dwl_render_template "$tmpl_name" "$rendered" "${kv_args[@]}" \
            || { rm -f "$rendered"; dwl_exec_rollback; return 2; }
          block_marker="$DWL_BLOCK_BEGIN"
          if [ "$tmpl_name" = "cross-repo-pointer-block.md" ]; then
            for _ekv_xr in "${kv_args[@]}"; do
              case "$_ekv_xr" in
                TOPIC=*) topic_slug="${_ekv_xr#TOPIC=}" ;;
              esac
            done
            [ -n "$topic_slug" ] \
              && block_marker="<!-- doc-warden:cross-repo-authority:${topic_slug}:begin -->" \
              || block_marker='<!-- doc-warden:cross-repo-authority:begin -->'
          fi
          dwl_exec_track_path "$abs_path"
          if [ -f "$abs_path" ]; then
            if ! grep -qF "$block_marker" "$abs_path" 2>/dev/null; then
              printf '\n' >> "$abs_path"
              cat "$rendered" >> "$abs_path"
            fi
          else
            mkdir -p "$(dirname "$abs_path")"
            cat "$rendered" > "$abs_path"
          fi
          rm -f "$rendered"
        fi
        ;;
      DRIFTED)
        printf '  [SKIP] DRIFTED item requires manual review (not written by repair): %s\n' "$path" >&2
        ;;
      patch)
        if echo "$detail" | grep -q '^remove_plan_ref:'; then
          local fname_rp_exec="${detail#remove_plan_ref:}"
          dwl_exec_track_path "$abs_path"
          if ! dwl_agents_md_remove_plan_ref "$abs_path" "$fname_rp_exec"; then
            printf 'REFUSED: no AGENTS.md plan reference to remove: %s\n' "$fname_rp_exec" >&2
            dwl_exec_rollback
            return 2
          fi
        else
        local drift_id_exec="${detail#policy_drift:}"
        local patch_tmp drift_ids_exec
        patch_tmp="$(mktemp)"
        cp "$abs_path" "$patch_tmp"
        if [ "$drift_id_exec" = "all" ]; then
          drift_ids_exec="$(dwl_policy_drift_ids_for_plans_readme "$abs_path")"
        else
          drift_ids_exec="$drift_id_exec"
        fi
        local applied=0
        while IFS= read -r one_drift; do
          [ -n "$one_drift" ] || continue
          local next_tmp
          next_tmp="$(mktemp)"
          if dwl_apply_policy_patch "$patch_tmp" "$one_drift" "$next_tmp"; then
            mv "$next_tmp" "$patch_tmp"
            applied=1
          else
            rm -f "$next_tmp"
          fi
        done <<< "$drift_ids_exec"
        if [ "$applied" -eq 1 ]; then
          dwl_exec_track_path "$abs_path"
          mv "$patch_tmp" "$abs_path"
        else
          rm -f "$patch_tmp"
          printf 'REFUSED: no policy patches applicable: %s\n' "$path" >&2
          dwl_exec_rollback
          return 2
        fi
        fi
        ;;
      move)
        local dest_rel dest_abs
        dest_rel="${detail}"
        dest_abs="$repo/$dest_rel"
        if [ ! -f "$abs_path" ]; then
          printf 'REFUSED: move source missing: %s\n' "$path" >&2
          dwl_exec_rollback
          return 2
        fi
        mkdir -p "$(dirname "$dest_abs")"
        dwl_exec_track_path "$abs_path"
        mv "$abs_path" "$dest_abs"
        ;;
      remove_index_row)
        local fname_ri_exec="${detail}"
        if [ ! -f "$abs_path" ]; then
          printf 'REFUSED: index target missing: %s\n' "$path" >&2
          dwl_exec_rollback
          return 2
        fi
        dwl_exec_track_path "$abs_path"
        if ! dwl_index_row_remove "$abs_path" "$fname_ri_exec"; then
          printf 'REFUSED: no index row to remove: %s\n' "$fname_ri_exec" >&2
          dwl_exec_rollback
          return 2
        fi
        ;;
      index_row)
        local fname_field status_field today_field new_row
        fname_field="${detail%%:*}"
        status_field="${detail#*:}"
        today_field="$(date +%Y-%m-%d)"
        new_row="$(dwl_index_row_format "$path" "$fname_field" "$status_field" "$today_field")"
        if [ ! -f "$abs_path" ]; then
          mkdir -p "$(dirname "$abs_path")"
          dwl_exec_track_path "$abs_path"
          if echo "$path" | grep -qE '/adr/README\.md$'; then
            dwl_render_template "docs-adr-README.md" "$abs_path" \
              "PLANS_DIR=$plans_rel" "ADR_DIR=$adr_rel" "REPO_SLUG=$repo_slug" || { dwl_exec_rollback; return 2; }
          elif echo "$path" | grep -qE '/incidents/README\.md$'; then
            dwl_render_template "docs-incidents-README.md" "$abs_path" \
              "PLANS_DIR=$plans_rel" "ADR_DIR=$adr_rel" "REPO_SLUG=$repo_slug" || { dwl_exec_rollback; return 2; }
          else
            dwl_render_template "docs-plans-README.md" "$abs_path" \
              "PLANS_DIR=$plans_rel" "ADR_DIR=$adr_rel" "REPO_SLUG=$repo_slug" || { dwl_exec_rollback; return 2; }
          fi
        else
          dwl_exec_track_path "$abs_path"
        fi
        if grep -qF '<!-- TODO: doc-warden will populate rows here via repair -->' "$abs_path" 2>/dev/null; then
          dwl_index_row_insert "$abs_path" "$fname_field" "$status_field" "$today_field" "$new_row" replace_placeholder \
            2>/dev/null || printf '\n%s\n' "$new_row" >> "$abs_path"
        else
          dwl_index_row_insert "$abs_path" "$fname_field" "$status_field" "$today_field" "$new_row" append_after_header \
            2>/dev/null || printf '\n%s\n' "$new_row" >> "$abs_path"
        fi
        ;;
      append_glossary_term)
        local slug_val="${detail#SLUG=}"
        local term_title
        term_title="$(dwl_glossary_term_title "$slug_val")"
        mkdir -p "$(dirname "$abs_path")"
        dwl_exec_track_path "$abs_path"
        {
          printf '\n## %s\n\n' "$term_title"
          printf '<!-- TODO: author — definition for %s -->\n\n' "$slug_val"
          printf '*Source: <!-- TODO: author -->\n'
        } >> "$abs_path"
        has_needs_authoring=1
        ;;
    esac
  done <<< "$actions"

  dwl_exec_rollback_cleanup

  return "$has_needs_authoring"
}

# ---------------------------------------------------------------------------
# Receipt writer (POLICY.md §8)
# ---------------------------------------------------------------------------

# dwl_write_receipt <repo_root> <verb> <target_revision> <approved_actions> <outcome>
dwl_write_receipt() {
  local repo="$1" verb="$2" target_rev="$3" approved_actions="$4" outcome="$5"
  local repo_name
  repo_name="$(basename "$repo")"
  local ts
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  local receipt_dir="$DWL_STATE_DIR/$repo_name"
  mkdir -p "$receipt_dir"
  local receipt_file="$receipt_dir/${ts}-${verb}.yml"

  local policy_digest
  policy_digest="$(dwl_policy_digest)"

  # Build approved_actions YAML block
  local actions_yaml=""
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    local action path detail
    action="${line%%:*}"
    path="$(echo "$line" | cut -d: -f2)"
    detail="${line#*:*:}"
    local content_digest="n/a"
    if echo "$detail" | grep -q "from-template:"; then
      local tmpl_name="${detail#from-template:}"
      local rendered_path="$repo/$path"
      [ -f "$rendered_path" ] && content_digest="$(dwl_content_digest "$rendered_path")"
    fi
    case "$action" in
      index_row) content_digest="index_row" ;;
    esac
    actions_yaml="${actions_yaml}  - type: $action"$'\n'
    actions_yaml="${actions_yaml}    path: $path"$'\n'
    actions_yaml="${actions_yaml}    content_digest: $content_digest"$'\n'
  done <<< "$approved_actions"

  cat > "$receipt_file" <<RECEIPT_EOF
schema: doc-warden-receipt/v1
repo: $repo_name
repo_root: $repo
target_revision: $target_rev
policy_version: "1.0.0"
policy_digest: $policy_digest
approved_actions:
${actions_yaml}observed_outcome: $outcome
timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)
notes: ""
RECEIPT_EOF

  printf '%s\n' "$receipt_file"
}

# ---------------------------------------------------------------------------
# Self-test — exercises all 3 fixtures × expected classifications
# Usage: bash _ops/bin/doc-warden-lib.sh --self-test
# ---------------------------------------------------------------------------

if [ "${1:-}" = "--self-test" ]; then
  echo "=== doc-warden-lib.sh self-test ==="
  fail=0
  pass() { printf '  PASS  %s\n' "$1"; }
  bad()  { printf '  FAIL  %s\n' "$1"; fail=1; }

  # Fixtures are relative to the lib dir's _ops/doc-warden/fixtures/
  FIXTURES_DIR="$DWL_DOC_WARDEN_DIR/fixtures"

  # ---- Fixture 1: empty repo → all baseline items MISSING ----
  echo "-- Fixture 1: empty repo --"
  EMPTY_FIXTURE="$FIXTURES_DIR/empty"
  if [ -d "$EMPTY_FIXTURE" ]; then
    classifications="$(dwl_classify_repo "$EMPTY_FIXTURE")"
    for key in plans_dir plans_readme adr_dir adr_readme agents_md_block; do
      cls="$(echo "$classifications" | grep "^${key}:" | cut -d: -f2)"
      if [ "$cls" = "$DWL_MISSING" ]; then
        pass "empty/$key → MISSING"
      else
        bad "empty/$key → expected MISSING, got '$cls'"
      fi
    done
    exit_cls="$(echo "$classifications" | grep "^exit_classification:" | cut -d: -f2)"
    [ "$exit_cls" = "$DWL_MISSING" ] && pass "empty/exit_classification → MISSING" \
      || bad "empty/exit_classification → expected MISSING, got '$exit_cls'"
  else
    bad "Fixture 'empty' not found at $EMPTY_FIXTURE"
  fi

  # ---- Fixture 2: conformant repo → all baseline items CONFORMANT ----
  echo "-- Fixture 2: conformant repo --"
  CONFORMANT_FIXTURE="$FIXTURES_DIR/conformant"
  if [ -d "$CONFORMANT_FIXTURE" ]; then
    classifications="$(dwl_classify_repo "$CONFORMANT_FIXTURE")"
    for key in plans_dir plans_readme adr_dir adr_readme agents_md_block; do
      cls="$(echo "$classifications" | grep "^${key}:" | cut -d: -f2)"
      if [ "$cls" = "$DWL_CONFORMANT" ]; then
        pass "conformant/$key → CONFORMANT"
      else
        bad "conformant/$key → expected CONFORMANT, got '$cls'"
      fi
    done
    exit_cls="$(echo "$classifications" | grep "^exit_classification:" | cut -d: -f2)"
    [ "$exit_cls" = "$DWL_CONFORMANT" ] && pass "conformant/exit_classification → CONFORMANT" \
      || bad "conformant/exit_classification → expected CONFORMANT, got '$exit_cls'"
  else
    bad "Fixture 'conformant' not found at $CONFORMANT_FIXTURE"
  fi

  # ---- Fixture 3: drifted repo → specific DRIFTED items ----
  echo "-- Fixture 3: drifted repo --"
  DRIFTED_FIXTURE="$FIXTURES_DIR/drifted"
  if [ -d "$DRIFTED_FIXTURE" ]; then
    classifications="$(dwl_classify_repo "$DRIFTED_FIXTURE")"
    # plans_readme should be DRIFTED (no table header)
    cls="$(echo "$classifications" | grep "^plans_readme:" | cut -d: -f2)"
    [ "$cls" = "$DWL_DRIFTED" ] && pass "drifted/plans_readme → DRIFTED" \
      || bad "drifted/plans_readme → expected DRIFTED, got '$cls'"
    # adr_readme should be DRIFTED (no table header)
    cls="$(echo "$classifications" | grep "^adr_readme:" | cut -d: -f2)"
    [ "$cls" = "$DWL_DRIFTED" ] && pass "drifted/adr_readme → DRIFTED" \
      || bad "drifted/adr_readme → expected DRIFTED, got '$cls'"
    # exit_classification should be DRIFTED or worse
    exit_cls="$(echo "$classifications" | grep "^exit_classification:" | cut -d: -f2)"
    case "$exit_cls" in
      DRIFTED|NEEDS_OPERATOR|CONTRADICTORY) pass "drifted/exit_classification → DRIFTED (or worse): $exit_cls" ;;
      *) bad "drifted/exit_classification → expected DRIFTED+, got '$exit_cls'" ;;
    esac
  else
    bad "Fixture 'drifted' not found at $DRIFTED_FIXTURE"
  fi

  # ---- Fixture 4: agentic plan marker/header regressions ----
  echo "-- Fixture 4: agentic plan marker/header regressions --"
  AGENTIC_FIXTURE="$FIXTURES_DIR/agentic-plan"
  if [ -d "$AGENTIC_FIXTURE" ]; then
    cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-missing-plan-type-v1.md)"
    [ "$cls" = "$DWL_DRIFTED" ] && pass "agentic/sample-missing-plan-type → DRIFTED" \
      || bad "agentic/sample-missing-plan-type → expected DRIFTED, got '$cls'"

    cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-body-standard-no-header-v1.md)"
    [ "$cls" = "$DWL_DRIFTED" ] && pass "agentic/sample-body-standard-no-header → DRIFTED" \
      || bad "agentic/sample-body-standard-no-header → expected DRIFTED, got '$cls'"

    cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-header-agentic-body-standard-v1.md)"
    [ "$cls" = "$DWL_DRIFTED" ] && pass "agentic/sample-header-agentic-body-standard → DRIFTED" \
      || bad "agentic/sample-header-agentic-body-standard → expected DRIFTED, got '$cls'"
  else
    bad "Fixture 'agentic-plan' not found at $AGENTIC_FIXTURE"
  fi

  # ---- Fixture 5: large agentic plan — SIGPIPE-under-pipefail regression (classifier hot path) ----
  # A CONFORMANT agentic plan whose "## 5. Work items" section far exceeds the OS pipe buffer must
  # classify CONFORMANT. Before the here-string fix, `printf '%s\n' "$workitems" | grep -q` was
  # killed by SIGPIPE (grep -q matches early, then the huge tail can't be written) and pipefail
  # propagated the failure, so a fully-conformant large plan mis-classified DRIFTED — the exact
  # defect that hit _ops/plans/doc-warden-execution-plan-v2.md. The companion (identical but
  # missing **Interfaces:**) must still classify DRIFTED, proving the fix does not mask real drift.
  echo "-- Fixture 5: large agentic plan (SIGPIPE/pipefail regression) --"
  set -o pipefail   # the bug only manifests under pipefail (this lib sets it; assert it explicitly)
  _dwl_gen_large_agentic_plan() {   # <target_file> <include_interfaces:1|0>
    local f="$1" incl_iface="$2"
    {
      printf '# Large agentic plan (self-test regression fixture)\n\n'
      printf '**Status:** DRAFT — self-test regression fixture\n'
      printf '**Owning repository:** KleinPerkins/dev\n'
      printf '**Plan-type:** agentic-execution\n\n'
      printf '## 5. Work items\n\n'
      # Shape markers at the TOP so grep -q matches early; the huge tail below is what triggered
      # SIGPIPE on the pre-fix `printf | grep -q` pipe.
      printf '**Files:**\n\n'
      printf -- '- `_ops/bin/example.sh`\n\n'
      [ "$incl_iface" = "1" ] && { printf '**Interfaces:**\n\n'; printf -- '- `example_fn()`\n\n'; }
      printf -- '- [ ] **Step 1 — do the thing**\n\n'
      # >128 KiB of filler after the markers (no "## ", "**Files/Interfaces:**", "- [ ]", or TODO):
      # ~6000 lines x ~78 chars ~= 468 KiB, comfortably past the 64 KiB pipe buffer.
      awk 'BEGIN{for(i=0;i<6000;i++) printf "filler line %06d padding the work items section beyond the OS pipe buffer size\n", i}'
    } > "$f"
  }
  large_fixture_dir="$(mktemp -d)"
  mkdir -p "$large_fixture_dir/docs/plans"
  _dwl_gen_large_agentic_plan "$large_fixture_dir/docs/plans/sample-large-conformant-agentic-v1.md" 1
  _dwl_gen_large_agentic_plan "$large_fixture_dir/docs/plans/sample-large-drifted-missing-interfaces-v1.md" 0
  cls="$(dwl_classify_plan_file "$large_fixture_dir" docs/plans sample-large-conformant-agentic-v1.md)"
  [ "$cls" = "$DWL_CONFORMANT" ] && pass "large-conformant-agentic (work-items >> pipe buffer) → CONFORMANT" \
    || bad "large-conformant-agentic → expected CONFORMANT, got '$cls' (SIGPIPE/pipefail regression)"
  cls="$(dwl_classify_plan_file "$large_fixture_dir" docs/plans sample-large-drifted-missing-interfaces-v1.md)"
  [ "$cls" = "$DWL_DRIFTED" ] && pass "large-drifted-missing-interfaces (no **Interfaces:**) → DRIFTED (fix masks no drift)" \
    || bad "large-drifted-missing-interfaces → expected DRIFTED, got '$cls'"
  rm -rf "$large_fixture_dir"
  unset -f _dwl_gen_large_agentic_plan

  # ---- Byte-stability test: classify the same fixture twice, assert identical output ----
  echo "-- Byte-stability test --"
  if [ -d "$CONFORMANT_FIXTURE" ]; then
    out1="$(dwl_classify_repo "$CONFORMANT_FIXTURE")"
    out2="$(dwl_classify_repo "$CONFORMANT_FIXTURE")"
    if [ "$out1" = "$out2" ]; then
      pass "byte-stability: conformant fixture classifies identically twice"
    else
      bad "byte-stability: non-deterministic classification output"
    fi
  fi

  echo
  if [ "$fail" -eq 0 ]; then
    echo "doc-warden-lib.sh self-test: OK"
    exit 0
  else
    echo "doc-warden-lib.sh self-test: FAILED (see FAIL lines above)"
    exit 1
  fi
fi
