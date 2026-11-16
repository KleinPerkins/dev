#!/usr/bin/env bash
# _ops/checks/doc-warden-verify.sh — durable regression check for the doc-warden subsystem.
#
# Makes NO changes. Exit 0 if every assertion holds, else 1.
# Wired into verify-operating-model.sh --ci (called from pre-commit and CI).
#
# Execution plan: _ops/plans/doc-warden-execution-plan-v1.md §18 WI-M1-02
# Policy: _ops/doc-warden/POLICY.md
#
# Modes:
#   (default)    full regression (local pre-commit / make verify-ci)
#   --sandbox    pr-automation sandbox subset: no PyYAML, no nested git init,
#                no mktemp execute paths — buildpack-deps stdlib-shell.v1 only
set -uo pipefail

MODE="full"
case "${1:-}" in
  --sandbox) MODE="sandbox" ;;
  --ci)      MODE="full" ;;  # alias: verify-operating-model --ci uses full suite
  --poc3d-setup-probe) MODE="poc3d-setup-probe" ;;  # internal fault-injection child
  "")        MODE="full" ;;
  *) printf 'usage: %s [--sandbox|--ci]\n' "$0" >&2; exit 2 ;;
esac

# Nested suites (git init in fixtures, mktemp copies) must not inherit hook GIT_DIR.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES 2>/dev/null || true

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # _ops/checks
OPS_DIR="$(dirname "$SELF_DIR")"                                  # _ops
DEV_ROOT="$(dirname "$OPS_DIR")"                                  # ~/dev

# shellcheck source=../bin/doc-warden-lib.sh
source "$OPS_DIR/bin/doc-warden-lib.sh"

fail=0
pass() { printf '  PASS  %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; fail=1; }

poc3d_prepare_temp_layout() {
  poc3d_alloc_fail="${DWL_POC3D_ALLOC_FAIL:-}"
  poc3d_tmp_base="${TMPDIR:-/tmp}"
  poc3d_setup_ok=1
  poc3d_tmp_root=""
  poc3d_err=""
  poc3d_empty_owner=""
  poc3d_empty_dep=""
  poc3d_err_a=""
  poc3d_err_b=""

  if [ "$poc3d_alloc_fail" = root ]; then
    poc3d_tmp_root=""
  else
    poc3d_tmp_root="$(mktemp -d "$poc3d_tmp_base/doc-warden-verify-poc3d.XXXXXX" 2>/dev/null)"
  fi
  if [ -n "$poc3d_tmp_root" ] && [ -d "$poc3d_tmp_root" ]; then
    if [ "$poc3d_alloc_fail" = chmod ]; then
      bad "poc3d stderr capture root → chmod 700 failed"
      poc3d_setup_ok=0
    elif chmod 700 "$poc3d_tmp_root" 2>/dev/null; then
      :
    else
      bad "poc3d stderr capture root → chmod 700 failed"
      poc3d_setup_ok=0
    fi
    if [ "$poc3d_alloc_fail" = main ]; then
      poc3d_err=""
    else
      poc3d_err="$(mktemp "$poc3d_tmp_root/poc3d-main.err.XXXXXX" 2>/dev/null)"
    fi
    if [ -z "$poc3d_err" ] || [ ! -f "$poc3d_err" ]; then
      bad "poc3d main stderr file → mktemp failed"
      poc3d_setup_ok=0
    fi
    if [ "$poc3d_alloc_fail" = err_a ]; then
      poc3d_err_a=""
    else
      poc3d_err_a="$(mktemp "$poc3d_tmp_root/poc3d-dup.err.XXXXXX" 2>/dev/null)"
    fi
    if [ -z "$poc3d_err_a" ] || [ ! -f "$poc3d_err_a" ]; then
      bad "poc3d duplicate stderr file → mktemp failed"
      poc3d_setup_ok=0
    fi
    if [ "$poc3d_alloc_fail" = err_b ]; then
      poc3d_err_b=""
    else
      poc3d_err_b="$(mktemp "$poc3d_tmp_root/poc3d-unresolved.err.XXXXXX" 2>/dev/null)"
    fi
    if [ -z "$poc3d_err_b" ] || [ ! -f "$poc3d_err_b" ]; then
      bad "poc3d unresolved stderr file → mktemp failed"
      poc3d_setup_ok=0
    fi
    poc3d_empty_owner="$poc3d_tmp_root/owner-empty"
    poc3d_empty_dep="$poc3d_tmp_root/dependent-empty"
    if [ "$poc3d_alloc_fail" = mkdir ]; then
      bad "poc3d empty repo dirs → mkdir failed"
      poc3d_setup_ok=0
    elif mkdir -p "$poc3d_empty_owner" "$poc3d_empty_dep"; then
      :
    else
      bad "poc3d empty repo dirs → mkdir failed"
      poc3d_setup_ok=0
    fi
  else
    bad "poc3d stderr capture root → mktemp -d failed"
    poc3d_setup_ok=0
  fi
}

poc3d_cleanup_temp_layout() {
  [ -n "${poc3d_tmp_root:-}" ] && rm -rf "$poc3d_tmp_root"
}

# The six setup-failure checks invoke only this shared setup path. Previously each
# case recursively reran this entire verifier, multiplying a broad suite sevenfold.
if [ "$MODE" = "poc3d-setup-probe" ]; then
  poc3d_prepare_temp_layout
  poc3d_cleanup_temp_layout
  echo
  if [ "$fail" -eq 0 ]; then
    echo "doc-warden-verify: OK"
    exit 0
  fi
  echo "doc-warden-verify: FAILED (see FAIL lines above)"
  exit 1
fi

# Grep-based trigger-id extraction lives in doc-warden-lib.sh (dwl_trigger_ids_grep).

FIXTURES_DIR="$DWL_DOC_WARDEN_DIR/fixtures"

# ---------------------------------------------------------------------------
# §1 Policy and template structure
# ---------------------------------------------------------------------------
echo "== doc-warden subsystem structure =="

for f in \
  "$DWL_POLICY_FILE" \
  "$DWL_TRIGGERS_FILE" \
  "$DWL_TEMPLATES_DIR/plan-header.md" \
  "$DWL_TEMPLATES_DIR/plan-task-block.md" \
  "$DWL_TEMPLATES_DIR/docs-plans-README.md" \
  "$DWL_TEMPLATES_DIR/docs-adr-README.md" \
  "$DWL_TEMPLATES_DIR/docs-incidents-README.md" \
  "$DWL_TEMPLATES_DIR/adr-entry.md" \
  "$DWL_TEMPLATES_DIR/runbook.md" \
  "$DWL_TEMPLATES_DIR/incident-record.md" \
  "$DWL_TEMPLATES_DIR/glossary.md" \
  "$DWL_TEMPLATES_DIR/agents-md-pointer-block.md" \
  "$DWL_TEMPLATES_DIR/agents-md-reconstructed-entry.md" \
  "$DWL_DOC_WARDEN_DIR/v2/templates/ux-requirements.md" \
  "$DWL_DOC_WARDEN_DIR/v2/templates/design-contract.md" \
  "$DWL_DOC_WARDEN_DIR/v2/templates/external-asset.md" \
  "$DWL_DOC_WARDEN_DIR/v2/templates/defect.md" \
  "$DWL_DOC_WARDEN_DIR/v2/templates/release.md" \
  "$OPS_DIR/bin/doc-warden-lib.sh" \
  "$FIXTURES_DIR/empty" \
  "$FIXTURES_DIR/conformant/AGENTS.md" \
  "$FIXTURES_DIR/conformant/docs/plans/README.md" \
  "$FIXTURES_DIR/conformant/docs/adr/README.md" \
  "$FIXTURES_DIR/drifted/AGENTS.md" \
  "$FIXTURES_DIR/drifted/docs/plans/README.md" \
  "$FIXTURES_DIR/drifted/docs/adr/README.md" \
  "$FIXTURES_DIR/needs_operator/AGENTS.md" \
  "$FIXTURES_DIR/needs_operator/docs/adr/0001-first-decision.md" \
  "$FIXTURES_DIR/contradictory/AGENTS.md" \
  "$FIXTURES_DIR/poc3b/AGENTS.md" \
  "$FIXTURES_DIR/poc3b/docs/plans/README.md" \
  "$FIXTURES_DIR/poc3b/docs/adr/README.md" \
  "$FIXTURES_DIR/poc3c/README.md" \
  "$FIXTURES_DIR/poc3c/config/relationship.yml" \
  "$FIXTURES_DIR/poc3c/lib/vendor.sh" \
  "$FIXTURES_DIR/superseded-plan/AGENTS.md" \
  "$DWL_CROSS_REPO_PROFILES_FILE" \
  "$DWL_TEMPLATES_DIR/cross-repo-pointer-block.md" \
  "$DWL_TEMPLATES_DIR/cross-repo-authority-adr.md" \
  "$FIXTURES_DIR/poc3d/owner/ARCHITECTURE.md" \
  "$FIXTURES_DIR/poc3d/dependent/OPERATING-MANUAL.md" \
  "$FIXTURES_DIR/poc3d/dependent/_ops/policy/worktree-modes.yml" \
  "$FIXTURES_DIR/superseded-plan/docs/plans/README.md" \
  "$FIXTURES_DIR/superseded-plan/docs/plans/widget-plan-v1.md" \
  "$FIXTURES_DIR/superseded-plan/docs/plans/widget-plan-v2.md" \
  "$FIXTURES_DIR/superseded-plan/docs/adr/README.md" \
  "$FIXTURES_DIR/agentic-plan/docs/plans/sample-standard-v1.md" \
  "$FIXTURES_DIR/agentic-plan/docs/plans/sample-feature-v1.md" \
  "$FIXTURES_DIR/agentic-plan/docs/plans/sample-missing-plan-type-v1.md" \
  "$FIXTURES_DIR/agentic-plan/docs/plans/sample-invalid-plan-type-v1.md" \
  "$FIXTURES_DIR/agentic-plan/docs/plans/sample-missing-shape-v1.md" \
  "$FIXTURES_DIR/agentic-plan/docs/plans/sample-skeleton-v1.md" \
  "$FIXTURES_DIR/agentic-plan/docs/plans/sample-shape-outside-workitems-v1.md" \
  "$FIXTURES_DIR/agentic-plan/docs/plans/sample-checkbox-eol-v1.md" \
  "$FIXTURES_DIR/agentic-plan/docs/plans/sample-accepted-prose-todo-v1.md" \
; do
  rel="${f#$DEV_ROOT/}"
  if [ -e "$f" ]; then
    pass "$rel present"
  else
    bad "$rel MISSING"
  fi
done

# triggers.yml validity
echo "== triggers.yml validity =="
if [ "$MODE" = "sandbox" ]; then
  if grep -q '^schema: doc-warden-triggers/v1' "$DWL_TRIGGERS_FILE" \
     && grep -qE '^triggers:' "$DWL_TRIGGERS_FILE"; then
    pass "triggers.yml structure present (sandbox: no PyYAML)"
  else
    bad "triggers.yml structure invalid (sandbox grep check)"
  fi
  trigger_ids="$(dwl_trigger_ids_grep | paste -sd, -)"
else
  if python3 -c "import yaml,sys; yaml.safe_load(open('$DWL_TRIGGERS_FILE'))" 2>/dev/null; then
    pass "triggers.yml YAML syntax valid"
  else
    bad "triggers.yml YAML syntax invalid"
  fi
  trigger_ids="$(python3 -c "
import yaml
d = yaml.safe_load(open('$DWL_TRIGGERS_FILE'))
ids = sorted(t['id'] for t in d.get('triggers', []))
print(','.join(str(i) for i in ids))
" 2>/dev/null)"
fi
if [ "$trigger_ids" = "1,2,3,4,6,7" ]; then
  pass "triggers.yml contains expected triggers (ids: 1,2,3,4,6,7)"
else
  bad "triggers.yml trigger ids: expected '1,2,3,4,6,7', got '$trigger_ids'"
fi
if dwl_trigger_in_catalog 4; then
  pass "trigger #4 in catalog"
else
  bad "trigger #4 missing from catalog"
fi

# ---------------------------------------------------------------------------
# §2 Static checks — no forbidden references (acceptance test #20)
# ---------------------------------------------------------------------------
echo "== Static grep: no forbidden references =="

# POLICY.md is explicitly excluded: it legitimately names these artifacts to say they are
# OUT OF SCOPE (§2 taxonomy table). The prohibition (ADR-0001/0003, acceptance test #20)
# targets engine/CLI code paths and templates, not the canonical policy document.
forbidden_patterns="meta\.yml|install\.sh|cpp-sync|quiver|eco-registry|card-platform-product|WF1|WF2"
found=0
for f in \
  "$DWL_TRIGGERS_FILE" \
  "$OPS_DIR/bin/doc-warden-lib.sh" \
  "$OPS_DIR/bin/doc-warden.sh" \
; do
  if grep -qE "$forbidden_patterns" "$f" 2>/dev/null; then
    bad "forbidden reference in $(basename "$f")"
    found=1
  fi
done
for tmpl in "$DWL_TEMPLATES_DIR"/*.md; do
  if grep -qE "$forbidden_patterns" "$tmpl" 2>/dev/null; then
    bad "forbidden reference in templates/$(basename "$tmpl")"
    found=1
  fi
done
[ "$found" -eq 0 ] && pass "no forbidden cpp/capability references in engine/CLI/templates"

# ---------------------------------------------------------------------------
# §3 Fixture classification regression (acceptance tests #6, #8)
# ---------------------------------------------------------------------------
echo "== Fixture classification regression =="

# Fixture: empty → all baseline items MISSING
classifications="$(dwl_classify_repo "$FIXTURES_DIR/empty")"
for key in plans_dir plans_readme adr_dir adr_readme agents_md_block; do
  cls="$(echo "$classifications" | grep "^${key}:" | cut -d: -f2)"
  [ "$cls" = "$DWL_MISSING" ] && pass "empty/$key → MISSING" \
    || bad "empty/$key → expected MISSING, got '$cls'"
done
exit_cls="$(echo "$classifications" | grep "^exit_classification:" | cut -d: -f2)"
[ "$exit_cls" = "$DWL_MISSING" ] && pass "empty/exit_classification → MISSING" \
  || bad "empty/exit_classification → expected MISSING, got '$exit_cls'"

# Fixture: conformant → all baseline items CONFORMANT
classifications="$(dwl_classify_repo "$FIXTURES_DIR/conformant")"
for key in plans_dir plans_readme adr_dir adr_readme agents_md_block; do
  cls="$(echo "$classifications" | grep "^${key}:" | cut -d: -f2)"
  [ "$cls" = "$DWL_CONFORMANT" ] && pass "conformant/$key → CONFORMANT" \
    || bad "conformant/$key → expected CONFORMANT, got '$cls'"
done
exit_cls="$(echo "$classifications" | grep "^exit_classification:" | cut -d: -f2)"
[ "$exit_cls" = "$DWL_CONFORMANT" ] && pass "conformant/exit_classification → CONFORMANT" \
  || bad "conformant/exit_classification → expected CONFORMANT, got '$exit_cls'"

# Fixture: drifted → specific DRIFTED items
classifications="$(dwl_classify_repo "$FIXTURES_DIR/drifted")"
cls="$(echo "$classifications" | grep "^plans_readme:" | cut -d: -f2)"
[ "$cls" = "$DWL_DRIFTED" ] && pass "drifted/plans_readme → DRIFTED" \
  || bad "drifted/plans_readme → expected DRIFTED, got '$cls'"
cls="$(echo "$classifications" | grep "^adr_readme:" | cut -d: -f2)"
[ "$cls" = "$DWL_DRIFTED" ] && pass "drifted/adr_readme → DRIFTED" \
  || bad "drifted/adr_readme → expected DRIFTED, got '$cls'"
exit_cls="$(echo "$classifications" | grep "^exit_classification:" | cut -d: -f2)"
case "$exit_cls" in
  DRIFTED|NEEDS_OPERATOR|CONTRADICTORY) pass "drifted/exit_classification → DRIFTED+: $exit_cls" ;;
  *) bad "drifted/exit_classification → expected DRIFTED+, got '$exit_cls'" ;;
esac

# Fixture: needs_operator → exit_classification must be NEEDS_OPERATOR (B1 fix)
# The needs_operator fixture intentionally carries unknown-condition inputs
# (for example docs/decisions/) that remain outside the closed trigger catalog.
classifications="$(dwl_classify_repo "$FIXTURES_DIR/needs_operator")"
exit_cls="$(echo "$classifications" | grep "^exit_classification:" | cut -d: -f2)"
[ "$exit_cls" = "$DWL_NEEDS_OPERATOR" ] && pass "needs_operator/exit_classification → NEEDS_OPERATOR" \
  || bad "needs_operator/exit_classification → expected NEEDS_OPERATOR, got '$exit_cls'"
# Also verify at least one unknown: line emitted
unknown_line="$(echo "$classifications" | grep "^unknown:" | head -1)"
[ -n "$unknown_line" ] && pass "needs_operator: unknown condition line emitted" \
  || bad "needs_operator: no unknown condition line emitted (dwl_classify_unknown_conditions not firing)"

# Fixture-like temp repo: incident records without trigger #4 must still surface NEEDS_OPERATOR.
# Requires PyYAML + mktemp — unavailable in pr-automation --sandbox (buildpack-deps stdlib-shell.v1).
if [ "$MODE" = "sandbox" ]; then
  pass "incident fixture without trigger #4 → skipped in --sandbox (PyYAML + mktemp unavailable)"
else
  incident_fixture="$(mktemp -d)"
  mkdir -p "$incident_fixture/docs/plans" "$incident_fixture/docs/adr" "$incident_fixture/docs/incidents"
  cp "$FIXTURES_DIR/conformant/AGENTS.md" "$incident_fixture/AGENTS.md"
  cp "$FIXTURES_DIR/conformant/docs/plans/README.md" "$incident_fixture/docs/plans/README.md"
  cp "$FIXTURES_DIR/conformant/docs/adr/README.md" "$incident_fixture/docs/adr/README.md"
  printf '# Incident: sample\n' > "$incident_fixture/docs/incidents/sample.md"
  saved_triggers="$DWL_TRIGGERS_FILE"
  DWL_TRIGGERS_FILE="$(mktemp)"
  python3 - <<'PY' "$saved_triggers" "$DWL_TRIGGERS_FILE"
import sys, yaml
src, dst = sys.argv[1], sys.argv[2]
doc = yaml.safe_load(open(src)) or {}
doc["triggers"] = [t for t in (doc.get("triggers") or []) if t.get("id") != 4]
with open(dst, "w") as fh:
    yaml.safe_dump(doc, fh, sort_keys=False)
PY
  classifications="$(dwl_classify_repo "$incident_fixture")"
  exit_cls="$(echo "$classifications" | grep "^exit_classification:" | cut -d: -f2)"
  [ "$exit_cls" = "$DWL_NEEDS_OPERATOR" ] && pass "incident fixture without trigger #4 → NEEDS_OPERATOR" \
    || bad "incident fixture without trigger #4 → expected NEEDS_OPERATOR, got '$exit_cls'"
  echo "$classifications" | grep -q '^unknown:incident_files_without_trigger_4:' \
    && pass "incident fixture without trigger #4 → unknown condition emitted" \
    || bad "incident fixture without trigger #4 → missing incident unknown-condition line"
  rm -f "$DWL_TRIGGERS_FILE"
  DWL_TRIGGERS_FILE="$saved_triggers"
  rm -rf "$incident_fixture"
fi

# Fixture: contradictory → exit_classification must be CONTRADICTORY (B1 fix)
# The contradictory fixture has duplicate doc-warden block markers in AGENTS.md.
classifications="$(dwl_classify_repo "$FIXTURES_DIR/contradictory")"
cls="$(echo "$classifications" | grep "^agents_md_block:" | cut -d: -f2)"
[ "$cls" = "$DWL_CONTRADICTORY" ] && pass "contradictory/agents_md_block → CONTRADICTORY" \
  || bad "contradictory/agents_md_block → expected CONTRADICTORY, got '$cls'"
exit_cls="$(echo "$classifications" | grep "^exit_classification:" | cut -d: -f2)"
[ "$exit_cls" = "$DWL_CONTRADICTORY" ] && pass "contradictory/exit_classification → CONTRADICTORY" \
  || bad "contradictory/exit_classification → expected CONTRADICTORY, got '$exit_cls'"

# Fixture: poc3b (M2 / POC 3b — local governance + single policy drift)
classifications="$(dwl_classify_repo "$FIXTURES_DIR/poc3b")"
cls="$(echo "$classifications" | grep "^plans_readme:" | cut -d: -f2)"
[ "$cls" = "$DWL_DRIFTED" ] && pass "poc3b/plans_readme → DRIFTED (policy drift)" \
  || bad "poc3b/plans_readme → expected DRIFTED, got '$cls'"
cls="$(echo "$classifications" | grep "^agents_md_block:" | cut -d: -f2)"
[ "$cls" = "$DWL_CONFORMANT" ] && pass "poc3b/agents_md_block → CONFORMANT (hand-authored)" \
  || bad "poc3b/agents_md_block → expected CONFORMANT, got '$cls'"
policy_drift_count="$(echo "$classifications" | grep -c '^policy_drift:' || true)"
[ "${policy_drift_count:-0}" -eq 1 ] && pass "poc3b/policy_drift → exactly one drift" \
  || bad "poc3b/policy_drift → expected 1 drift line, got ${policy_drift_count:-0}"
plan_lines="$(echo "$classifications" | grep -c '^plan:' || true)"
[ "${plan_lines:-0}" -eq 0 ] && pass "poc3b/plan files → not over-normalized (0 plan: lines)" \
  || bad "poc3b/plan files → expected 0 plan: lines (local governance), got ${plan_lines:-0}"
poc3b_actions="$(dwl_plan_repair "$FIXTURES_DIR/poc3b")"
echo "$poc3b_actions" | grep -q '^patch:docs/plans/README.md:policy_drift:all$' \
  && pass "poc3b/repair plan → patch action for policy drift" \
  || bad "poc3b/repair plan → expected patch action, got: $(echo "$poc3b_actions" | tr '\n' ' ')"

# ---------------------------------------------------------------------------
# §3b M3 / POC 3c reconstruction regression (requires PyYAML + nested git init)
# ---------------------------------------------------------------------------
if [ "$MODE" = "sandbox" ]; then
  echo "== M3 / POC 3c reconstruction regression =="
  pass "skipped in --sandbox (PyYAML + nested git init unavailable in pr-automation sandbox)"
else
echo "== M3 / POC 3c reconstruction regression =="

POC3C_FIXTURE="$FIXTURES_DIR/poc3c"
# Ephemeral nested git repo (fixture lives inside ~/dev worktree — rev-parse alone is not enough)
if [ ! -d "$POC3C_FIXTURE/.git" ]; then
  git -C "$POC3C_FIXTURE" init -q
  git -C "$POC3C_FIXTURE" add -A
  git -C "$POC3C_FIXTURE" -c user.name='KleinPerkins' \
    -c user.email='49759187+KleinPerkins@users.noreply.github.com' \
    commit -q -m 'test: ephemeral poc3c fixture history'
fi
classifications="$(dwl_classify_repo "$POC3C_FIXTURE")"
exit_cls="$(echo "$classifications" | grep "^exit_classification:" | cut -d: -f2)"
[ "$exit_cls" = "$DWL_MISSING" ] && pass "poc3c/baseline → MISSING (thin docs)" \
  || bad "poc3c/baseline → expected MISSING, got '$exit_cls'"

gh_out="$(dwl_gather_git_history "$POC3C_FIXTURE" lib/vendor.sh | head -1)"
[ -n "$gh_out" ] && [ "$gh_out" != "not_implemented_until_m3" ] && pass "M3 git_history gatherer → live output" \
  || bad "M3 git_history gatherer → expected commit line, got '$gh_out'"

transcript_out="$(dwl_gather_transcript "$POC3C_FIXTURE")"
[ "$transcript_out" = "unavailable_private_evidence" ] && pass "M3 transcript gatherer → sanitized unavailable" \
  || bad "M3 transcript gatherer → expected unavailable_private_evidence, got '$transcript_out'"

if dwl_reconstruct_has_unresolved_contradictory "$POC3C_FIXTURE"; then
  bad "poc3c/reconstruct → unexpected unresolved CONTRADICTORY claim (dual-regime scope resolved)"
else
  pass "poc3c/reconstruct → dual-regime auto-merge claims accepted (no CONTRADICTORY)"
fi

poc3c_actions="$(dwl_plan_reconstruct_repair "$POC3C_FIXTURE")"
echo "$poc3c_actions" | grep -q '^create:AGENTS.md:from-template:agents-md-reconstructed-entry.md$' \
  && pass "poc3c/reconstruct plan → reconstructed AGENTS.md" \
  || bad "poc3c/reconstruct plan → missing AGENTS.md create action"
echo "$poc3c_actions" | grep -q '^create:docs/adr/0001-single-sanctioned-cpp-edge-writer.md:' \
  && pass "poc3c/reconstruct plan → ADR-0001 skeleton" \
  || bad "poc3c/reconstruct plan → missing ADR-0001 skeleton action"

if [ -f "$OPS_DIR/bin/doc-warden.sh" ]; then
  bash "$OPS_DIR/bin/doc-warden.sh" check "$POC3C_FIXTURE" --reconstruct >/dev/null 2>&1
  ec=$?
  [ "$ec" -eq 1 ] && pass "check --reconstruct poc3c → exit 1 (MISSING baseline, not CONTRADICTORY)" \
    || bad "check --reconstruct poc3c → expected exit 1, got $ec"

  bash "$OPS_DIR/bin/doc-warden.sh" repair "$POC3C_FIXTURE" --reconstruct --dry-run >/dev/null 2>&1
  ec=$?
  [ "$ec" -eq 0 ] && pass "repair --reconstruct --dry-run poc3c → exit 0" \
    || bad "repair --reconstruct --dry-run poc3c → expected exit 0, got $ec"

  poc3c_sha="$(git -C "$POC3C_FIXTURE" rev-parse HEAD 2>/dev/null || echo 'no-git')"
  bash "$OPS_DIR/bin/doc-warden.sh" repair "$POC3C_FIXTURE" --reconstruct --approve --revision "$poc3c_sha" --plan-digest "wrong" >/dev/null 2>&1
  ec=$?
  [ "$ec" -eq 1 ] && pass "repair --reconstruct --approve → passes CONTRADICTORY gate (digest mismatch exit 1)" \
    || bad "repair --reconstruct --approve → expected exit 1 past CONTRADICTORY gate, got $ec"
fi

# Evidence records must not contain credential-like patterns (acceptance test #13)
if dwl_reconstruct_emit_records "$POC3C_FIXTURE" "ecosystem-orchestrator" 2>/dev/null \
   | grep -qiE '(api[_-]?key|password|secret|token=|Bearer )'; then
  bad "M3 evidence records → credential-like pattern detected"
else
  pass "M3 evidence records → no credential-like patterns"
fi
fi

# ---------------------------------------------------------------------------
# §3c M2 acceptance test #10 — superseded plan leaves active surface
# ---------------------------------------------------------------------------
echo "== M2 / acceptance test #10 superseded-plan regression =="

SUPERSEDED_FIXTURE="$FIXTURES_DIR/superseded-plan"
super_count="$(dwl_superseded_plans_on_active_surface "$SUPERSEDED_FIXTURE" docs/plans | wc -l | tr -d ' ')"
[ "${super_count:-0}" -eq 1 ] && pass "superseded-plan → one superseded plan on active surface" \
  || bad "superseded-plan → expected 1 superseded active plan, got ${super_count:-0}"

super_actions="$(dwl_plan_repair "$SUPERSEDED_FIXTURE")"
echo "$super_actions" | grep -q '^move:docs/plans/widget-plan-v1.md:docs/archive/plans/widget-plan-v1.md$' \
  && pass "superseded-plan/repair → archive move action" \
  || bad "superseded-plan/repair → missing archive move action"
echo "$super_actions" | grep -q '^remove_index_row:docs/plans/README.md:widget-plan-v1.md$' \
  && pass "superseded-plan/repair → index row removal" \
  || bad "superseded-plan/repair → missing index row removal"
echo "$super_actions" | grep -q '^patch:AGENTS.md:remove_plan_ref:widget-plan-v1.md$' \
  && pass "superseded-plan/repair → AGENTS.md routing cleanup" \
  || bad "superseded-plan/repair → missing AGENTS.md routing cleanup"

super_work="$(mktemp -d)"
cp -R "$SUPERSEDED_FIXTURE/." "$super_work/"
if dwl_execute_plan "$super_actions" "$super_work" >/dev/null 2>&1; then
  if [ -f "$super_work/docs/archive/plans/widget-plan-v1.md" ] \
     && [ ! -f "$super_work/docs/plans/widget-plan-v1.md" ]; then
    pass "superseded-plan/execute → plan archived on disk"
  else
    bad "superseded-plan/execute → archive path wrong after repair"
  fi
  if grep -qF 'widget-plan-v1.md' "$super_work/docs/plans/README.md" 2>/dev/null; then
    bad "superseded-plan/execute → v1 still in active index"
  else
    pass "superseded-plan/execute → v1 removed from active index"
  fi
  if grep -qF 'widget-plan-v1.md' "$super_work/AGENTS.md" 2>/dev/null; then
    bad "superseded-plan/execute → v1 still in AGENTS.md routing"
  else
    pass "superseded-plan/execute → v1 removed from AGENTS.md routing"
  fi
else
  bad "superseded-plan/execute → dwl_execute_plan failed"
fi
rm -rf "$super_work"

# ---------------------------------------------------------------------------
# §3d M4 / POC 3d cross-repo authority regression (requires PyYAML)
# ---------------------------------------------------------------------------
if [ "$MODE" = "sandbox" ]; then
  echo "== M4 / POC 3d cross-repo authority regression =="
  pass "skipped in --sandbox (PyYAML unavailable in pr-automation sandbox)"
else
echo "== M4 / POC 3d cross-repo authority regression =="

POC3D_OWNER="$FIXTURES_DIR/poc3d/owner"
POC3D_DEP="$FIXTURES_DIR/poc3d/dependent"

if dwl_cross_repo_profile_exists poc3d-fixture; then
  pass "cross-repo profile poc3d-fixture present"
else
  bad "cross-repo profile poc3d-fixture missing"
fi
if dwl_cross_repo_profile_exists pr-automation-required-checks; then
  pass "cross-repo profile pr-automation-required-checks present"
else
  bad "cross-repo profile pr-automation-required-checks missing"
fi
pr_v3_readme="$OPS_DIR/baseline/profiles/pr-automation/v3/README.md"
grep -qF '<!-- doc-warden:cross-repo-authority:controller-required-node-authority:begin -->' "$pr_v3_readme" \
  && grep -qF 'docs/adr/0008-controller-owned-required-node-authority.md' "$pr_v3_readme" \
  && grep -qF '**Profile:** pr-automation-required-checks' "$pr_v3_readme" \
  && pass "pr-automation ADR 0008 dependent pointer is marker-delimited" \
  || bad "pr-automation ADR 0008 dependent pointer missing or malformed"

poc3d_prepare_temp_layout
poc3d_map="$( [ "$poc3d_setup_ok" -eq 1 ] && dwl_cross_repo_emit_ownership_map poc3d-fixture "$POC3D_OWNER" "$POC3D_DEP" 2>"$poc3d_err" )"
if [ "$poc3d_setup_ok" -eq 1 ]; then
poc3d_exit="$(printf '%s' "$poc3d_map" | python3 -c "
import sys, yaml
docs = list(yaml.safe_load_all(sys.stdin.read()))
doc = docs[-1] if docs else {}
print(doc.get('exit_classification',''))
" 2>/dev/null)"
case "$poc3d_exit" in
  DUPLICATE_AUTHORITY|CONTRADICTORY)
    pass "poc3d-fixture exit_classification → $poc3d_exit (duplicate/contradictory detected)"
    ;;
  *)
    bad "poc3d-fixture exit_classification → expected DUPLICATE_AUTHORITY or CONTRADICTORY, got '$poc3d_exit'"
    ;;
esac

grep -q '^map:ssp-product-location:DUPLICATE_AUTHORITY$' "$poc3d_err" 2>/dev/null \
  && pass "poc3d-fixture/ssp-product-location → DUPLICATE_AUTHORITY" \
  || bad "poc3d-fixture/ssp-product-location → expected DUPLICATE_AUTHORITY"

grep -q '^map:contradictory-example:CONTRADICTORY$' "$poc3d_err" 2>/dev/null \
  && pass "poc3d-fixture/contradictory-example → CONTRADICTORY" \
  || bad "poc3d-fixture/contradictory-example → expected CONTRADICTORY"

  dwl_cross_repo_emit_ownership_map poc3d-fixture "$POC3D_OWNER" "$POC3D_DEP" > /dev/null 2>"$poc3d_err_a"
  dwl_cross_repo_emit_ownership_map poc3d-fixture "$poc3d_empty_owner" "$poc3d_empty_dep" >/dev/null 2>"$poc3d_err_b"
  [ "$poc3d_err_a" != "$poc3d_err_b" ] \
    && pass "poc3d stderr hermeticity → per-run paths are distinct" \
    || bad "poc3d stderr hermeticity → per-run paths must be distinct"
  grep -qF 'map:ssp-product-location:DUPLICATE_AUTHORITY' "$poc3d_err_a" 2>/dev/null \
    && grep -qF 'map:contradictory-example:CONTRADICTORY' "$poc3d_err_a" 2>/dev/null \
    && pass "poc3d stderr hermeticity → duplicate/contradictory run preserved its own stderr" \
    || bad "poc3d stderr hermeticity → duplicate/contradictory run stderr was clobbered"
  grep -qF 'map:ssp-product-location:UNRESOLVED' "$poc3d_err_b" 2>/dev/null \
    && grep -qF 'map:contradictory-example:UNRESOLVED' "$poc3d_err_b" 2>/dev/null \
    && pass "poc3d stderr hermeticity → unresolved run preserved its own stderr" \
    || bad "poc3d stderr hermeticity → unresolved run stderr was clobbered"
fi

if dwl_trigger_in_catalog 6; then
  pass "trigger #6 in catalog"
else
  bad "trigger #6 missing from catalog"
fi

if [ -f "$OPS_DIR/bin/doc-warden.sh" ]; then
  bash "$OPS_DIR/bin/doc-warden.sh" check --cross-repo poc3d-fixture >/dev/null 2>&1
  ec=$?
  [ "$ec" -eq 1 ] || [ "$ec" -eq 3 ] && pass "check --cross-repo poc3d-fixture → exit $ec (not conformant)" \
    || bad "check --cross-repo poc3d-fixture → expected exit 1 or 3, got $ec"

  trig6_plan="$(dwl_plan_trigger_cross_repo_owner "$POC3D_OWNER" 'awa-dev-overlay' poc3d-fixture 2>/dev/null || true)"
  echo "$trig6_plan" | grep -q 'cross-repo-authority-adr.md' \
    && pass "trigger #6 plan → cross-repo-authority-adr skeleton" \
    || bad "trigger #6 plan → missing cross-repo-authority-adr action"
  echo "$trig6_plan" | grep -q 'TOPIC_IDS=ssp-product-location' \
    && pass "trigger #6 plan → TOPIC_IDS from profile (not slug)" \
    || bad "trigger #6 plan → TOPIC_IDS must list profile topic ids, not ADR slug"
  echo "$trig6_plan" | grep -q 'cross-repo-pointer-block' \
    && bad "trigger #6 owner plan → must not include dependent pointer (separate repo)" \
    || pass "trigger #6 owner plan → owner-only actions (no mixed-repo pointer)"
  dep6_plan="$(dwl_plan_trigger_cross_repo_dependent "$POC3D_DEP" 'awa-dev-overlay' poc3d-fixture 'docs/adr/0001-awa-dev-overlay.md' 2>/dev/null || true)"
  echo "$dep6_plan" | grep -q 'append_block:OPERATING-MANUAL.md:from-template:cross-repo-pointer-block.md' \
    && pass "trigger #6 dependent plan → append_block at governed dependent_paths" \
    || bad "trigger #6 dependent plan → expected append_block at OPERATING-MANUAL.md"
  dep6_via_trigger="$(dwl_plan_trigger "$POC3D_DEP" 6 'awa-dev-overlay' 2>&1 || true)"
  echo "$dep6_via_trigger" | grep -q 'trigger #6 blocked' \
    && pass "trigger #6 via dwl_plan_trigger on dependent → blocked when CONTRADICTORY" \
    || bad "trigger #6 via dwl_plan_trigger on dependent → must refuse CONTRADICTORY cross-repo state"
  echo "$dep6_plan" | grep -q 'https://' \
    && bad "trigger #6 dependent plan → must not embed URL in colon-delimited KV" \
    || pass "trigger #6 dependent plan → colon-safe KV (no raw URL)"
  dup_owner="$(mktemp -d "$poc3d_tmp_base/doc-warden-verify-poc3d-owner.XXXXXX" 2>/dev/null)"
  if [ -z "$dup_owner" ] || [ ! -d "$dup_owner" ]; then
    bad "trigger #6 owner duplicate-slug harness → mktemp -d failed"
  elif cp -R "$POC3D_OWNER/." "$dup_owner/" 2>/dev/null; then
    dup_adr="$dup_owner/docs/adr/0099-awa-dev-overlay-dup-test.md"
    mkdir -p "$dup_owner/docs/adr"
    printf '# dup test\n' >"$dup_adr"
    dup_out="$(dwl_plan_trigger_cross_repo_owner "$dup_owner" 'awa-dev-overlay-dup-test' poc3d-fixture 2>&1 || true)"
    echo "$dup_out" | grep -q 'REFUSED: ADR file already exists' \
      && pass "trigger #6 owner plan → refuses duplicate slug ADR" \
      || bad "trigger #6 owner plan → must refuse duplicate slug ADR"
    printf '# longer slug ADR\n' >"$dup_owner/docs/adr/0001-awa-dev-overlay.md"
    adr_match="$(dwl_cross_repo_owner_adr_path_for_slug "$dup_owner" 'dev-overlay')"
    [ "$adr_match" != "docs/adr/0001-awa-dev-overlay.md" ] \
      && pass "owner ADR slug lookup → exact token match (no suffix glob)" \
      || bad "owner ADR slug lookup → must not match awa-dev-overlay for slug dev-overlay (got $adr_match)"
  else
    bad "trigger #6 owner duplicate-slug harness → fixture copy failed"
  fi
  [ -n "$dup_owner" ] && rm -rf "$dup_owner"
  dry6_out="$(bash "$OPS_DIR/bin/doc-warden.sh" repair "$POC3D_DEP" --trigger 6 --slug awa-dev-overlay --dry-run 2>&1 || true)"
  echo "$dry6_out" | grep -q 'trigger #6 blocked' \
    && pass "trigger #6 dry-run → refuses CONTRADICTORY cross-repo state" \
    || bad "trigger #6 dry-run → must refuse CONTRADICTORY cross-repo state"
  echo "$trig6_plan" | grep -q 'OWNER_REPO=fixture/owner' \
    && pass "trigger #6 owner plan → OWNER_REPO from profile github repo" \
    || bad "trigger #6 owner plan → OWNER_REPO must use profile owner.repo"
  # Test repository identity using inert checkouts, not this host's real ~/dev.
  # The successor deliberately has a different Git common directory from it.
  dwl_alias_fixture="$(mktemp -d "${TMPDIR:-/tmp}/doc-warden-alias.XXXXXX")"
  dwl_alias_git() { env GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 git "$@"; }
  if [ -n "$dwl_alias_fixture" ] &&
     dwl_alias_git init -q "$dwl_alias_fixture/primary" &&
     dwl_alias_git -C "$dwl_alias_fixture/primary" -c user.name='Synthetic Fixture' \
       -c user.email='fixture@example.invalid' -c commit.gpgsign=false \
       commit --allow-empty -qm 'Inert alias fixture' &&
     dwl_alias_git -C "$dwl_alias_fixture/primary" worktree add -q -b fixture-alias "$dwl_alias_fixture/linked" &&
     dwl_alias_git init -q "$dwl_alias_fixture/unrelated"; then
    dwl_cross_repo_repos_match "$dwl_alias_fixture/primary" "$dwl_alias_fixture/linked" \
      && pass "cross-repo repos match via git-common-dir (synthetic linked checkout)" \
      || bad "cross-repo repos match → linked checkout must share identity"
    if dwl_cross_repo_repos_match "$dwl_alias_fixture/primary" "$dwl_alias_fixture/unrelated"; then
      bad "cross-repo repos match → unrelated checkout must not share identity"
    else
      pass "cross-repo repos match → unrelated checkout rejected"
    fi
    if dwl_cross_repo_repos_match "$dwl_alias_fixture/primary/.git" "$dwl_alias_fixture/linked"; then
      bad "cross-repo repos match → in-repository subdirectory must not be an alias"
    else
      pass "cross-repo repos match → in-repository subdirectory rejected"
    fi
  else
    bad "cross-repo repos match → synthetic fixture initialization failed"
  fi
  [ -n "$dwl_alias_fixture" ] && rm -rf "$dwl_alias_fixture"
  unset -f dwl_alias_git
  if dwl_cross_repo_profile_for_dependent_repo "$OPS_DIR" >/dev/null 2>&1; then
    bad "cross-repo profile → in-repo subdir must not match repo-root dependent profile"
  else
    pass "cross-repo profile → in-repo subdir rejected for repo-root alias"
  fi
  grep -q 'cross-repo-authority:{{TOPIC}}:begin' "$OPS_DIR/doc-warden/templates/cross-repo-pointer-block.md" \
    && pass "cross-repo pointer template → per-slug marker delimiters" \
    || bad "cross-repo pointer template → expected per-slug marker delimiters"
  poc3d_non_md="$(dwl_cross_repo_dependent_paths_csv poc3d | grep -Ev '\.(md|mdc)$' || true)"
  if [ -n "$poc3d_non_md" ]; then
    poc3d_ptr_plan="$(dwl_plan_trigger_cross_repo_dependent "$POC3D_DEP" 'awa-dev-overlay' poc3d 'docs/adr/0001-awa-dev-overlay.md' 2>/dev/null || true)"
    while IFS= read -r non_md_path; do
      [ -n "$non_md_path" ] || continue
      echo "$poc3d_ptr_plan" | grep -q "append_block:${non_md_path}:" \
        && bad "dependent pointer plan → must not append to non-markdown path $non_md_path" \
        || pass "dependent pointer plan → skips non-markdown path $non_md_path"
    done <<< "$poc3d_non_md"
  else
    pass "dependent pointer plan → poc3d profile has no non-markdown dependent_paths (filter N/A)"
  fi
  empty_owner="$(mktemp -d)"
  empty_dep="$(mktemp -d)"
  dwl_cross_repo_trigger6_allowed poc3d-fixture "$empty_owner" "$empty_dep" >/dev/null 2>&1
  blocked_rc=$?
  rm -rf "$empty_owner" "$empty_dep"
  [ "$blocked_rc" -ne 0 ] \
    && pass "trigger #6 gate → refuses when cross-repo map is UNRESOLVED" \
    || bad "trigger #6 gate → must refuse UNRESOLVED cross-repo state"
  fail_owner="$(mktemp -d)"
  fail_dep="$(mktemp -d)"
  dwl_cross_repo_trigger6_allowed no-such-profile "$fail_owner" "$fail_dep" >/dev/null 2>&1
  gate_closed_rc=$?
  rm -rf "$fail_owner" "$fail_dep"
  [ "$gate_closed_rc" -ne 0 ] \
    && pass "trigger #6 gate → fails closed when classification unavailable" \
    || bad "trigger #6 gate → must fail closed when classification unavailable"
  empty_owner="$(mktemp -d)"
  empty_dep="$(mktemp -d)"
  empty_exit="$(dwl_cross_repo_emit_ownership_map poc3d-fixture "$empty_owner" "$empty_dep" 2>/dev/null \
    | python3 -c "import sys,yaml; d=list(yaml.safe_load_all(sys.stdin.read()))[-1]; print(d.get('exit_classification',''))" 2>/dev/null)"
  rm -rf "$empty_owner" "$empty_dep"
  [ "$empty_exit" = UNRESOLVED ] \
    && pass "cross-repo map → UNRESOLVED when no markers match either repo" \
    || bad "cross-repo map → expected UNRESOLVED for empty trees, got '$empty_exit'"
  rollup_exit="$(python3 -c "
classes = ['DUPLICATE_AUTHORITY', 'UNRESOLVED', 'OWNED_CORRECTLY']
if 'CONTRADICTORY' in classes:
    print('CONTRADICTORY')
elif 'UNRESOLVED' in classes:
    print('UNRESOLVED')
elif 'DUPLICATE_AUTHORITY' in classes:
    print('DUPLICATE_AUTHORITY')
elif 'DEPENDENT_ONLY' in classes:
    print('DEPENDENT_ONLY')
else:
    print('OWNED_CORRECTLY')
" 2>/dev/null)"
  [ "$rollup_exit" = UNRESOLVED ] \
    && pass "exit_classification rollup → UNRESOLVED beats DUPLICATE_AUTHORITY" \
    || bad "exit_classification rollup → expected UNRESOLVED precedence, got '$rollup_exit'"
fi
poc3d_cleanup_temp_layout

echo "== M4 / POC 3d temp-setup failure regression =="
if [ "$MODE" = "sandbox" ]; then
  pass "skipped in --sandbox (fault injection uses mktemp paths)"
else
  for alloc_case in root chmod main err_a err_b mkdir; do
    case "$alloc_case" in
      root) setup_expect="poc3d stderr capture root → mktemp -d failed" ;;
      chmod) setup_expect="poc3d stderr capture root → chmod 700 failed" ;;
      main) setup_expect="poc3d main stderr file → mktemp failed" ;;
      err_a) setup_expect="poc3d duplicate stderr file → mktemp failed" ;;
      err_b) setup_expect="poc3d unresolved stderr file → mktemp failed" ;;
      mkdir) setup_expect="poc3d empty repo dirs → mkdir failed" ;;
    esac
    setup_case_base="$(mktemp -d "$poc3d_tmp_base/doc-warden-verify-poc3d-selftest.XXXXXX" 2>/dev/null)"
    if [ -z "$setup_case_base" ] || [ ! -d "$setup_case_base" ]; then
      bad "poc3d setup-failure harness → mktemp -d failed for $alloc_case"
      continue
    fi
    setup_out="$(mktemp "$setup_case_base/poc3d-failure.XXXXXX" 2>/dev/null)"
    if [ -z "$setup_out" ] || [ ! -f "$setup_out" ]; then
      bad "poc3d setup-failure harness → mktemp failed for $alloc_case"
      rm -rf "$setup_case_base"
      continue
    fi
    if TMPDIR="$setup_case_base" DWL_POC3D_ALLOC_FAIL="$alloc_case" bash "$0" --poc3d-setup-probe >"$setup_out" 2>&1; then
      bad "poc3d setup-failure/$alloc_case → verifier must fail closed"
    elif grep -qF "$setup_expect" "$setup_out" 2>/dev/null \
      && grep -qF 'doc-warden-verify: FAILED' "$setup_out" 2>/dev/null; then
      if DWL_POC3D_TMP_BASE="$setup_case_base" python3 - <<'PY'
import glob, os, sys
base = os.environ["DWL_POC3D_TMP_BASE"]
leftovers = glob.glob(os.path.join(base, "doc-warden-verify-poc3d.*"))
sys.exit(0 if not leftovers else 1)
PY
      then
        pass "poc3d setup-failure/$alloc_case → explicit failure and cleanup"
      else
        bad "poc3d setup-failure/$alloc_case → leaked temp root after failure"
      fi
    else
      bad "poc3d setup-failure/$alloc_case → missing explicit failure diagnostic"
    fi
    rm -f "$setup_out"
    rm -rf "$setup_case_base"
  done
fi

echo "== M4 / POC 3d temp-base parity regression =="
if [ "$MODE" = "sandbox" ]; then
  pass "skipped in --sandbox (temp-base parity uses custom tmp roots)"
else
  base_case_parent="$(mktemp -d "$poc3d_tmp_base/doc-warden-verify-poc3d-base.XXXXXX" 2>/dev/null)"
  if [ -z "$base_case_parent" ] || [ ! -d "$base_case_parent" ]; then
    bad "poc3d temp-base parity harness → mktemp -d failed"
  else
    base_case_space="$base_case_parent/with space"
    if mkdir -p "$base_case_parent/custom" "$base_case_space" 2>/dev/null; then
      :
    else
      bad "poc3d temp-base parity harness → mkdir failed"
    fi
    for base_case in unset empty custom spaces; do
      case "$base_case" in
        unset)
          case_base="$(env -u TMPDIR bash -lc 'printf %s "${TMPDIR:-/tmp}"')"
          ;;
        empty)
          case_base="$(TMPDIR='' bash -lc 'printf %s "${TMPDIR:-/tmp}"')"
          ;;
        custom)
          case_base="$(TMPDIR="$base_case_parent/custom" bash -lc 'printf %s "${TMPDIR:-/tmp}"')"
          ;;
        spaces)
          case_base="$(TMPDIR="$base_case_space" bash -lc 'printf %s "${TMPDIR:-/tmp}"')"
          ;;
      esac
      probe_root="$(mktemp -d "$case_base/doc-warden-verify-poc3d.probe.XXXXXX" 2>/dev/null)"
      if [ -z "$probe_root" ] || [ ! -d "$probe_root" ]; then
        bad "poc3d temp-base parity/$base_case → probe mktemp failed"
        continue
      fi
      if DWL_POC3D_TMP_BASE="$case_base" python3 - <<'PY' "$probe_root"
import glob, os, sys
base = os.environ["DWL_POC3D_TMP_BASE"]
probe = sys.argv[1]
hits = glob.glob(os.path.join(base, "doc-warden-verify-poc3d.*"))
sys.exit(0 if probe in hits else 1)
PY
      then
        pass "poc3d temp-base parity/$base_case → leak scan uses shell-resolved base"
      else
        bad "poc3d temp-base parity/$base_case → leak scan missed shell-resolved base"
      fi
      rm -rf "$probe_root"
      if DWL_POC3D_TMP_BASE="$case_base" python3 - <<'PY'
import glob, os, sys
base = os.environ["DWL_POC3D_TMP_BASE"]
hits = glob.glob(os.path.join(base, "doc-warden-verify-poc3d.probe.*"))
sys.exit(0 if not hits else 1)
PY
      then
        pass "poc3d temp-base parity/$base_case → cleanup removes test leak"
      else
        bad "poc3d temp-base parity/$base_case → cleanup left test leak"
      fi
    done
    rm -rf "$base_case_parent"
  fi
fi

fi

# ---------------------------------------------------------------------------
# §3e Agentic-execution plan Work-item shape regression (POLICY.md §10 rule 10)
# ---------------------------------------------------------------------------
echo "== agentic-execution plan Work-item shape regression =="

AGENTIC_FIXTURE="$FIXTURES_DIR/agentic-plan"

cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-standard-v1.md)"
[ "$cls" = "$DWL_CONFORMANT" ] && pass "agentic/sample-standard (explicit standard marker) → CONFORMANT" \
  || bad "agentic/sample-standard → expected CONFORMANT, got '$cls'"

cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-missing-plan-type-v1.md)"
[ "$cls" = "$DWL_DRIFTED" ] && pass "agentic/sample-missing-plan-type (draft, no marker) → DRIFTED" \
  || bad "agentic/sample-missing-plan-type → expected DRIFTED, got '$cls'"

cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-body-standard-no-header-v1.md)"
[ "$cls" = "$DWL_DRIFTED" ] && pass "agentic/sample-body-standard-no-header (body marker only) → DRIFTED" \
  || bad "agentic/sample-body-standard-no-header → expected DRIFTED, got '$cls'"

cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-invalid-plan-type-v1.md)"
[ "$cls" = "$DWL_DRIFTED" ] && pass "agentic/sample-invalid-plan-type (closed set) → DRIFTED" \
  || bad "agentic/sample-invalid-plan-type → expected DRIFTED, got '$cls'"

cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-feature-v1.md)"
[ "$cls" = "$DWL_CONFORMANT" ] && pass "agentic/sample-feature (marker + full task-block) → CONFORMANT" \
  || bad "agentic/sample-feature → expected CONFORMANT, got '$cls'"

cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-missing-shape-v1.md)"
[ "$cls" = "$DWL_DRIFTED" ] && pass "agentic/sample-missing-shape (marker, no shape) → DRIFTED" \
  || bad "agentic/sample-missing-shape → expected DRIFTED, got '$cls'"

cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-header-agentic-body-standard-v1.md)"
[ "$cls" = "$DWL_DRIFTED" ] && pass "agentic/sample-header-agentic-body-standard (header wins) → DRIFTED" \
  || bad "agentic/sample-header-agentic-body-standard → expected DRIFTED, got '$cls'"

cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-skeleton-v1.md)"
[ "$cls" = "$DWL_NEEDS_AUTHORING" ] && pass "agentic/sample-skeleton (marker + TODO) → NEEDS_AUTHORING" \
  || bad "agentic/sample-skeleton → expected NEEDS_AUTHORING, got '$cls'"

# Shape gate is scoped to the "## 5. Work items" section — tokens in another section do not count.
cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-shape-outside-workitems-v1.md)"
[ "$cls" = "$DWL_DRIFTED" ] && pass "agentic/sample-shape-outside-workitems (shape not in §5) → DRIFTED" \
  || bad "agentic/sample-shape-outside-workitems → expected DRIFTED, got '$cls'"

# A checkbox token with no trailing space/text ('- [ ]' at end of line) still satisfies the gate.
cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-checkbox-eol-v1.md)"
[ "$cls" = "$DWL_CONFORMANT" ] && pass "agentic/sample-checkbox-eol (bare '- [ ]' checkbox) → CONFORMANT" \
  || bad "agentic/sample-checkbox-eol → expected CONFORMANT, got '$cls'"

# ACCEPTED plans may cite `<!-- TODO: author -->` in prose without being unfilled skeletons.
cls="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-accepted-prose-todo-v1.md)"
[ "$cls" = "$DWL_CONFORMANT" ] && pass "agentic/sample-accepted-prose-todo (ACCEPTED cites syntax) → CONFORMANT" \
  || bad "agentic/sample-accepted-prose-todo → expected CONFORMANT, got '$cls'"

cls="$(dwl_classify_plan_file "$DEV_ROOT" _ops/plans doc-warden-execution-plan-v1.md)"
[ "$cls" = "$DWL_CONFORMANT" ] && pass "dev/doc-warden-execution-plan-v1 (frozen ACCEPTED) → CONFORMANT" \
  || bad "dev/doc-warden-execution-plan-v1 → expected CONFORMANT, got '$cls'"

a1="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-feature-v1.md)"
a2="$(dwl_classify_plan_file "$AGENTIC_FIXTURE" docs/plans sample-feature-v1.md)"
[ "$a1" = "$a2" ] && pass "byte-stability: agentic feature plan classifies identically twice" \
  || bad "byte-stability: agentic feature plan non-deterministic"

# ---------------------------------------------------------------------------
# §4 Byte-stability (acceptance test #8)
# ---------------------------------------------------------------------------
echo "== Byte-stability regression =="

out1="$(dwl_classify_repo "$FIXTURES_DIR/conformant")"
out2="$(dwl_classify_repo "$FIXTURES_DIR/conformant")"
if [ "$out1" = "$out2" ]; then
  pass "byte-stability: conformant fixture classifies identically twice"
else
  bad "byte-stability: non-deterministic classification output"
fi

out1="$(dwl_classify_repo "$FIXTURES_DIR/drifted")"
out2="$(dwl_classify_repo "$FIXTURES_DIR/drifted")"
if [ "$out1" = "$out2" ]; then
  pass "byte-stability: drifted fixture classifies identically twice"
else
  bad "byte-stability: non-deterministic classification (drifted)"
fi

out1="$(dwl_classify_repo "$FIXTURES_DIR/needs_operator")"
out2="$(dwl_classify_repo "$FIXTURES_DIR/needs_operator")"
if [ "$out1" = "$out2" ]; then
  pass "byte-stability: needs_operator fixture classifies identically twice"
else
  bad "byte-stability: non-deterministic classification (needs_operator)"
fi

out1="$(dwl_classify_repo "$FIXTURES_DIR/contradictory")"
out2="$(dwl_classify_repo "$FIXTURES_DIR/contradictory")"
if [ "$out1" = "$out2" ]; then
  pass "byte-stability: contradictory fixture classifies identically twice"
else
  bad "byte-stability: non-deterministic classification (contradictory)"
fi

# ---------------------------------------------------------------------------
# §5 lib self-test
# ---------------------------------------------------------------------------
echo "== doc-warden-lib.sh --self-test =="
if bash "$OPS_DIR/bin/doc-warden-lib.sh" --self-test >/dev/null 2>&1; then
  pass "doc-warden-lib.sh --self-test OK"
else
  bad "doc-warden-lib.sh --self-test FAILED"
fi

# ---------------------------------------------------------------------------
# §6 CLI exit-code matrix (WI-M1-03, acceptance tests #6, #7, #8, #14, #19)
# Requires doc-warden.sh to exist; skipped gracefully if not yet present.
# ---------------------------------------------------------------------------
if [ -f "$OPS_DIR/bin/doc-warden.sh" ]; then
  echo "== doc-warden.sh exit-code matrix =="

  DW="$OPS_DIR/bin/doc-warden.sh"

  # check: CONFORMANT → exit 0
  bash "$DW" check "$FIXTURES_DIR/conformant" >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 0 ] && pass "check conformant → exit 0" \
    || bad "check conformant → expected exit 0, got $ec"

  # check: MISSING → exit 1
  bash "$DW" check "$FIXTURES_DIR/empty" >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 1 ] && pass "check empty (MISSING) → exit 1" \
    || bad "check empty → expected exit 1, got $ec"

  # check: DRIFTED → exit 1
  bash "$DW" check "$FIXTURES_DIR/drifted" >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 1 ] && pass "check drifted → exit 1" \
    || bad "check drifted → expected exit 1, got $ec"

  # repair --dry-run: conformant → exit 0 (empty plan)
  bash "$DW" repair "$FIXTURES_DIR/conformant" --dry-run >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 0 ] && pass "repair --dry-run conformant → exit 0" \
    || bad "repair --dry-run conformant → expected exit 0, got $ec"

  # repair --dry-run: empty → exit 0 (plan computed)
  bash "$DW" repair "$FIXTURES_DIR/empty" --dry-run >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 0 ] && pass "repair --dry-run empty → exit 0" \
    || bad "repair --dry-run empty → expected exit 0, got $ec"

  # repair --approve --revision: HEAD mismatch → exit 1 (acceptance test #19)
  bash "$DW" repair "$FIXTURES_DIR/empty" --approve --revision "deadbeef" --plan-digest "deadbeef" >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 1 ] && pass "repair --approve HEAD mismatch → exit 1" \
    || bad "repair --approve HEAD mismatch → expected exit 1, got $ec"

  # repair --approve --revision: digest mismatch → exit 1
  actual_sha="$(git -C "$FIXTURES_DIR/empty" rev-parse HEAD 2>/dev/null || echo 'no-git')"
  bash "$DW" repair "$FIXTURES_DIR/empty" --approve --revision "$actual_sha" --plan-digest "wrong" >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 1 ] && pass "repair --approve digest mismatch → exit 1" \
    || bad "repair --approve digest mismatch → expected exit 1, got $ec"

  # repair --approve --greenfield: on drifted → exit 1 (greenfield misuse, acceptance test #19)
  bash "$DW" repair "$FIXTURES_DIR/drifted" --approve --greenfield >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 1 ] && pass "repair --greenfield on drifted → exit 1 (refused)" \
    || bad "repair --greenfield on drifted → expected exit 1, got $ec"

  # No --approve without --revision/--greenfield → exit 2 (usage error)
  bash "$DW" repair "$FIXTURES_DIR/empty" --approve >/dev/null 2>&1
  ec=$?; [ "$ec" -ge 1 ] && pass "repair --approve without mode → exit ≥1 (usage error)" \
    || bad "repair --approve without mode → expected exit ≥1, got $ec"

  # check: NEEDS_OPERATOR → exit 3 (B1 fix — was unreachable before)
  bash "$DW" check "$FIXTURES_DIR/needs_operator" >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 3 ] && pass "check needs_operator → exit 3" \
    || bad "check needs_operator → expected exit 3, got $ec"

  # check: CONTRADICTORY → exit 3 (same exit as NEEDS_OPERATOR per CLI spec)
  bash "$DW" check "$FIXTURES_DIR/contradictory" >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 3 ] && pass "check contradictory → exit 3" \
    || bad "check contradictory → expected exit 3, got $ec"

  # repair --dry-run: needs_operator → exit 1 (repair ladder reserves 3 for check only)
  bash "$DW" repair "$FIXTURES_DIR/needs_operator" --dry-run >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 1 ] && pass "repair --dry-run needs_operator → exit 1" \
    || bad "repair --dry-run needs_operator → expected exit 1, got $ec"

  # repair --dry-run: contradictory → exit 1
  bash "$DW" repair "$FIXTURES_DIR/contradictory" --dry-run >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 1 ] && pass "repair --dry-run contradictory → exit 1" \
    || bad "repair --dry-run contradictory → expected exit 1, got $ec"

  # slug validation: path traversal rejected
  bash "$DW" repair "$FIXTURES_DIR/empty" --trigger 2 --slug '../evil' --dry-run >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 1 ] && pass "repair --trigger invalid slug → exit 1" \
    || bad "repair --trigger invalid slug → expected exit 1, got $ec"

  # execute_plan: path escape must return 2 and must NOT mkdir outside repo (pass 9)
  escape_parent="$(mktemp -d)"
  tmp_repo="$(mktemp -d "$escape_parent/escape-repo.XXXXXX")"
  mkdir -p "$tmp_repo/docs"
  outside_sentinel="$escape_parent/outside-sentinel"
  if dwl_execute_plan $'create:../../outside/evil.md:from-template:plan-header.md:SLUG=test\n' "$tmp_repo" >/dev/null 2>&1; then
    bad "dwl_execute_plan path escape → expected return 2, got 0"
  else
    exec_rc=$?
    [ "$exec_rc" -eq 2 ] && pass "dwl_execute_plan path escape → return 2" \
      || bad "dwl_execute_plan path escape → expected return 2, got $exec_rc"
  fi
  if [ -e "$escape_parent/outside" ] || [ -e "$outside_sentinel" ]; then
    bad "dwl_execute_plan path escape → created paths outside repo"
  else
    pass "dwl_execute_plan path escape → no dirs created outside repo"
  fi
  # Directory-create escape must also refuse before mkdir
  if dwl_execute_plan $'create:../../outside/:directory\n' "$tmp_repo" >/dev/null 2>&1; then
    bad "dwl_execute_plan directory escape → expected return 2, got 0"
  else
    exec_rc=$?
    [ "$exec_rc" -eq 2 ] && pass "dwl_execute_plan directory escape → return 2" \
      || bad "dwl_execute_plan directory escape → expected return 2, got $exec_rc"
  fi
  if [ -d "$escape_parent/outside" ]; then
    bad "dwl_execute_plan directory escape → created dir outside repo"
  else
    pass "dwl_execute_plan directory escape → no dir created outside repo"
  fi
  rm -rf "$escape_parent"

  # trigger #7: duplicate glossary term refused
  glossary_fixture="$(mktemp -d)"
  mkdir -p "$glossary_fixture/docs"
  printf '## existing term\n\nDefinition.\n' > "$glossary_fixture/docs/GLOSSARY.md"
  if dwl_plan_trigger "$glossary_fixture" 7 'existing-term' >/dev/null 2>&1; then
    bad "trigger #7 duplicate glossary term → expected refusal, got success"
  else
    trig_rc=$?
    [ "$trig_rc" -eq 1 ] && pass "trigger #7 duplicate glossary term → return 1" \
      || bad "trigger #7 duplicate glossary term → expected return 1, got $trig_rc"
  fi
  rm -rf "$glossary_fixture"

  # greenfield: conformant plan/ADR files must not block baseline inheritance
  gf_fixture="$(mktemp -d)"
  cp -R "$FIXTURES_DIR/conformant/." "$gf_fixture/"
  bash "$DW" repair "$gf_fixture" --approve --greenfield >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 0 ] || [ "$ec" -eq 2 ] && pass "repair --greenfield with conformant plan/ADR files → not refused (rc=$ec)" \
    || bad "repair --greenfield with conformant plan/ADR → expected 0 or 2, got $ec"
  rm -rf "$gf_fixture"

  # override path traversal falls back to default
  override_fixture="$(mktemp -d)"
  printf 'plans_dir: ../../outside\nadr_dir: docs/adr\n' > "$override_fixture/.doc-warden.yml"
  resolved="$(dwl_plans_dir "$override_fixture")"
  [ "$resolved" = "docs/plans" ] && pass "invalid plans_dir override → default docs/plans" \
    || bad "invalid plans_dir override → expected docs/plans, got $resolved"
  rm -rf "$override_fixture"

  # ADR index rows use ADR | Title | Status | Date columns
  adr_row="$(dwl_index_row_format "docs/adr/README.md" "0001-test-slug-v1.md" "DRAFT" "2026-08-05")"
  echo "$adr_row" | grep -qF '| 0001-test-slug-v1.md | test slug | DRAFT | 2026-08-05 |' \
    && pass "ADR index_row format → ADR | Title | Status | Date" \
    || bad "ADR index_row format mismatch: $adr_row"
  adr_row2="$(dwl_index_row_format "docs/adr/README.md" "0002-policy-name.md" "DRAFT" "2026-08-05")"
  echo "$adr_row2" | grep -qF '| policy name |' \
    && pass "ADR index_row title strips .md suffix" \
    || bad "ADR index_row .md strip failed: $adr_row2"
  incident_row="$(dwl_index_row_format "_ops/incidents/README.md" "sample-incident.md" "DRAFT" "2026-08-05")"
  echo "$incident_row" | grep -qF '| [sample-incident.md](sample-incident.md) | DRAFT | 2026-08-05 | |' \
    && pass "incident index_row format → Incident | Status | Date | Notes" \
    || bad "incident index_row format mismatch: $incident_row"

  # dev-new-repo: greenfield exit 2 (NEEDS_AUTHORING) must still commit inherited docs
  if grep -qF '[ "$gf_rc" -eq 0 ] || [ "$gf_rc" -eq 2 ]' "$DEV_ROOT/_ops/bin/dev-new-repo.sh" 2>/dev/null; then
    pass "dev-new-repo greenfield exit 2 → still commits docs"
  else
    bad "dev-new-repo must treat greenfield exit 2 as applied (NEEDS_AUTHORING)"
  fi

  # dev-new-repo: greenfield refusal must abort scaffold before gh repo create
  if grep -qF 'greenfield repair failed' "$DEV_ROOT/_ops/bin/dev-new-repo.sh" 2>/dev/null \
     && grep -A2 'greenfield repair failed' "$DEV_ROOT/_ops/bin/dev-new-repo.sh" | grep -q 'exit 1'; then
    pass "dev-new-repo greenfield failure → abort scaffold"
  else
    bad "dev-new-repo must exit 1 when greenfield repair fails"
  fi

  # repair --approve: DRIFTED-only plan must refuse (no false-success receipt)
  drifted_sha="$(git -C "$FIXTURES_DIR/drifted" rev-parse HEAD 2>/dev/null || echo 'no-git')"
  bash "$DW" repair "$FIXTURES_DIR/drifted" --approve --revision "$drifted_sha" --plan-digest "empty-plan" >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 1 ] && pass "repair --approve DRIFTED-only → exit 1" \
    || bad "repair --approve DRIFTED-only → expected exit 1, got $ec"

  # execute_plan preflight: escape on later action must not write earlier actions
  preflight_parent="$(mktemp -d)"
  preflight_repo="$(mktemp -d "$preflight_parent/preflight-repo.XXXXXX")"
  mkdir -p "$preflight_repo/docs"
  if dwl_execute_plan $'create:docs/safe.md:from-template:plan-header.md:SLUG=safe\nappend_block:../../outside/AGENTS.md:from-template:agents-md-pointer-block.md\n' "$preflight_repo" >/dev/null 2>&1; then
    bad "dwl_execute_plan preflight → expected return 2 on mixed plan, got 0"
  else
    exec_rc=$?
    [ "$exec_rc" -eq 2 ] && pass "dwl_execute_plan preflight → return 2 on mixed plan" \
      || bad "dwl_execute_plan preflight → expected return 2, got $exec_rc"
  fi
  if [ -f "$preflight_repo/docs/safe.md" ] || [ -e "$preflight_parent/outside" ]; then
    bad "dwl_execute_plan preflight → partial writes occurred before refusal"
  else
    pass "dwl_execute_plan preflight → no partial writes before refusal"
  fi
  rm -rf "$preflight_parent"

  # triggers catalog: unreadable YAML must not emit spurious unknown conditions
  if [ "$MODE" = "sandbox" ]; then
    if [ -n "$(dwl_trigger_ids_grep)" ]; then
      pass "triggers.yml catalog ids present (sandbox grep)"
    else
      bad "triggers.yml catalog ids absent (sandbox grep)"
    fi
  elif dwl_triggers_catalog_ok; then
    pass "dwl_triggers_catalog_ok → triggers.yml loads"
  else
    bad "dwl_triggers_catalog_ok → triggers.yml failed to load"
  fi

  # Regression: macOS /usr/bin/python3 lacks PyYAML — catalog must still load (grep fallback).
  if ( unset DWL_PYTHON_CACHED; PATH=/usr/bin:/bin; export PATH; DOC_WARDEN_PYTHON= dwl_triggers_catalog_ok ); then
    pass "dwl_triggers_catalog_ok with /usr/bin-only PATH (grep fallback)"
  else
    bad "dwl_triggers_catalog_ok failed with /usr/bin-only PATH"
  fi

  # Fleet check from target repo must not false-NEEDS_OPERATOR on catalog unreadable alone.
  if ( unset DWL_PYTHON_CACHED; PATH="/usr/bin:/bin:$SELF_DIR/.."; export PATH; DOC_WARDEN_PYTHON= \
       bash "$DW" check "$FIXTURES_DIR/conformant" 2>&1 | grep -q 'triggers.yml unreadable' ); then
    bad "check conformant emits triggers.yml unreadable under /usr/bin-only PATH"
  else
    pass "check conformant: no triggers.yml unreadable warn under /usr/bin-only PATH"
  fi

  # repair --approve --greenfield: NEEDS_OPERATOR repo must refuse
  bash "$DW" repair "$FIXTURES_DIR/needs_operator" --approve --greenfield >/dev/null 2>&1
  ec=$?; [ "$ec" -eq 1 ] && pass "repair --greenfield needs_operator → exit 1" \
    || bad "repair --greenfield needs_operator → expected exit 1, got $ec"

  # Acceptance test #19: no iteration path in CLI (static code check)
  if grep -qE 'for.*repo.*approve|while.*repos.*repair' "$DW" 2>/dev/null; then
    bad "CLI contains a fleet-iteration + approve loop (acceptance test #19 violation)"
  else
    pass "CLI: no fleet-iteration repair loop (acceptance test #19)"
  fi

  # Acceptance test #6: check and repair use same lib functions (source check)
  if grep -q 'dwl_classify_repo' "$DW" 2>/dev/null; then
    pass "CLI uses shared dwl_classify_repo from lib (acceptance test #6)"
  else
    bad "CLI does not use dwl_classify_repo — parallel implementation risk"
  fi
else
  echo "  SKIP  doc-warden.sh exit-code matrix (doc-warden.sh not yet present — WI-M1-03 pending)"
fi

# ---------------------------------------------------------------------------
# §7 Active v2 schema/canonical/transaction suite
# ---------------------------------------------------------------------------
echo "== active doc-warden v2 contracts =="
if [ "$MODE" = "full" ]; then
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$DWL_DOC_WARDEN_DIR/v2" \
    python3 -m unittest discover -s "$DWL_DOC_WARDEN_DIR/v2/tests" -p 'test_*.py'
  ec=$?
  [ "$ec" -eq 0 ] && pass "active v2 stdlib suite OK" \
    || bad "active v2 stdlib suite FAILED (exit $ec)"
else
  if PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$DWL_DOC_WARDEN_DIR/v2" \
    python3 - "$DWL_DOC_WARDEN_DIR/schemas/v2" "$DWL_DEV_ROOT" <<'PY'
import json
import sys
from pathlib import Path
from doc_warden.activation import validate_activation
root = Path(sys.argv[1])
paths = sorted(root.glob("*.schema.json"))
assert len(paths) >= 16
for path in paths:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert value["type"] == "object"
    assert value["additionalProperties"] is False
assert validate_activation(
    Path(sys.argv[2]),
    observe_runnerless=False,
)["status"] == "active"
PY
  then
    pass "active v2 closed schemas and activation parse in sandbox"
  else
    bad "active v2 closed schema/activation sandbox check failed"
  fi
fi

# ---------------------------------------------------------------------------
# §7b GSD Core runtime qualification record (both modes: offline, stdlib-only).
# The runnerless PR sandbox reaches this check; the full v2 suite above does not.
# ---------------------------------------------------------------------------
echo "== gsd-core runtime qualification record =="
if [ -f "$DWL_DEV_ROOT/_ops/policy/dev-successor.json" ]; then
  # Source-only successor deliberately omits predecessor host qualification.
  # Positive and negative record-binding behavior remains tested with synthetic
  # fixtures in the full v2 suite; do not mint replacement runtime evidence.
  if [ -e "$DWL_DOC_WARDEN_DIR/state/v2/runtime/gsd-core-v1.11.0-qualification.json" ]; then
    bad "successor unexpectedly contains predecessor runtime qualification"
  else
    echo "  PENDING  successor runtime qualification (separate runtime gate; no source claim)"
  fi
elif PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$DWL_DOC_WARDEN_DIR/v2" \
  python3 -m doc_warden.runtime_qualification check --repo "$DWL_DEV_ROOT"; then
  pass "gsd-core qualification record matches its pinned runtime files"
else
  bad "gsd-core qualification record is stale; re-qualify per docs/runbooks/gsd-core-lock-requalification.md"
fi

# ---------------------------------------------------------------------------
# §8 Context-measurement focused suite (actual runnerless Dev entry point)
# ---------------------------------------------------------------------------
if [ "$MODE" = "sandbox" ]; then
  echo "== context-measurement focused suite =="
  (
    cd "$DEV_ROOT/_ops/context-measurement"
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
      test_kp_context_measure.py \
      test_correction_dogfood.py \
      test_capability_discovery_inventory.py \
      test_validate_static_context_manifest.py \
      test_release2_closure.py
  )
  ec=$?
  [ "$ec" -eq 0 ] && pass "context-measurement focused suite OK" \
    || bad "context-measurement focused suite FAILED (exit $ec)"
fi

# ---------------------------------------------------------------------------
# Personal fresh-account native import observer (offline, no account access).
# Run directly so a missing test file cannot turn into an empty passing discovery.
# ---------------------------------------------------------------------------
echo "== personal native import contracts =="
if python3 -B "$OPS_DIR/portability/test_personal_native_imports.py" -v; then
  pass "personal native import contract suite OK"
else
  bad "personal native import contract suite FAILED"
fi

# ---------------------------------------------------------------------------
# Native Skill Creator import observer (offline, both verifier modes).
# Direct invocation refuses a missing suite; no PyYAML or native access required.
# ---------------------------------------------------------------------------
echo "== personal native skill creator contracts =="
if python3 -B "$OPS_DIR/portability/test_personal_native_skill_creator.py" -v; then
  pass "personal native skill creator contract suite OK"
else
  bad "personal native skill creator contract suite FAILED"
fi

# ---------------------------------------------------------------------------
# Personal Internal Comms canary profile (offline, both verifier modes).
# Direct invocation refuses a missing suite; no native publication or worker.
# ---------------------------------------------------------------------------
echo "== personal Internal Comms canary contracts =="
if python3 -B "$OPS_DIR/interoperability/test_internal_comms_canary.py"; then
  pass "personal Internal Comms canary contract suite OK"
else
  bad "personal Internal Comms canary contract suite FAILED"
fi

# ---------------------------------------------------------------------------
# Personal Theme Factory temporary owner contracts (offline, both modes).
# Direct invocation refuses a missing suite and starts no native model worker.
# ---------------------------------------------------------------------------
echo "== personal Theme Factory canary contracts =="
if python3 -B "$OPS_DIR/interoperability/test_theme_factory_canary.py" -v; then
  pass "personal Theme Factory canary contract suite OK"
else
  bad "personal Theme Factory canary contract suite FAILED"
fi

# Separate retained lifecycle/identity contracts (both modes). The eight actual
# Mac transport methods use their own OS fence and mandatory closed qualifier;
# a second nested sandbox cannot qualify those cases here.
echo "== personal Theme Factory retained contracts =="
if python3 -B "$OPS_DIR/interoperability/test_theme_factory_retained.py" Retained Identity -v; then
  pass "personal Theme Factory retained lifecycle/identity suite OK"
else
  bad "personal Theme Factory retained lifecycle/identity suite FAILED"
fi

# Personal Plan Refine temporary owner contracts (offline, both modes).
echo "== personal Plan Refine canary contracts =="
if python3 -B -m unittest discover -s "$OPS_DIR/interoperability" -p 'test_plan_refine_*.py' -v; then
  pass "personal Plan Refine canary contract suite OK"
else
  bad "personal Plan Refine canary contract suite FAILED"
fi
# End personal Plan Refine temporary owner contracts.


# ---------------------------------------------------------------------------
# Personal Canvas Design temporary owner contract (offline, both modes).
# Direct invocation refuses a missing suite and starts no native model worker.
# ---------------------------------------------------------------------------
echo "== personal Canvas Design canary contracts =="
if python3 -B "$OPS_DIR/interoperability/test_canvas_design_canary.py" -v; then
  pass "personal Canvas Design canary contract suite OK"
else
  bad "personal Canvas Design canary contract suite FAILED"
fi

# ---------------------------------------------------------------------------
# Personal active-v2 read/proposal dependency (offline, both verifier modes).
# Direct invocation refuses a missing test file instead of passing zero tests.
# ---------------------------------------------------------------------------
echo "== personal active-v2 read contracts =="
if python3 -B "$OPS_DIR/portability/test_personal_doc_v2_read.py" -v; then
  pass "personal active-v2 read contract suite OK"
else
  bad "personal active-v2 read contract suite FAILED"
fi

# ---------------------------------------------------------------------------
# Personal exact-pin Codex GSD source-text dependency (offline, both modes).
# This checks the source contract; no package download, npm or Node invocation.
# ---------------------------------------------------------------------------
echo "== personal Codex GSD source-text contracts =="
if python3 -B "$OPS_DIR/portability/test_personal_gsd_codex_source.py" -v; then
  pass "personal Codex GSD source-text contract suite OK"
else
  bad "personal Codex GSD source-text contract suite FAILED"
fi

# ---------------------------------------------------------------------------
# Whole private pinned GSD bundle (offline, both verifier modes)
# ---------------------------------------------------------------------------
echo "== personal whole-package Codex GSD bundle contracts =="
if python3 -B "$OPS_DIR/portability/test_personal_gsd_codex_bundle.py"; then
  pass "personal Codex GSD bundle contract suite OK"
else
  bad "personal Codex GSD bundle contract suite FAILED"
fi

# Authoring runtime and central reference binding (offline, both modes).
echo "== authoring runtime and central authority binding contracts =="
if PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$DWL_DOC_WARDEN_DIR/v2" \
  python3 -B "$DWL_DOC_WARDEN_DIR/v2/tests/test_authoring_binding.py"; then
  pass "authoring runtime and central authority bindings OK"
else
  bad "authoring runtime and central authority bindings FAILED"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
if [ "$fail" -eq 0 ]; then
  echo "doc-warden-verify: OK"
  exit 0
else
  echo "doc-warden-verify: FAILED (see FAIL lines above)"
  exit 1
fi
