#!/usr/bin/env bash
# _ops/checks/verify-operating-model.sh — read-only assertions for the home operating model.
# Makes NO changes. Exit 0 if every assertion holds, else 1.
#
# Modes:
#   (default / --local)  full check: repo invariants + the agent rules installed on THIS machine.
#   --ci                 repo-only invariants (skips ~/.cursor, ~/.codex, ~/.claude checks);
#                        used by CI and the pre-commit hook, which run without user config.
set -uo pipefail

# Worktree-hook GIT_DIR leak guard: when this script runs from a pre-commit hook invoked in a
# LINKED WORKTREE, git exports GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE pointing at that worktree's
# private gitdir (.git/worktrees/<name>) for the hook's whole process tree — correct for the
# hook's OWN git calls, but a footgun for the nested test suites below (pr-automation's
# RepoFixture, v3/test.sh, snow-kit-host-bootstrap.sh), which each `git init`/`git remote add` a
# THROWAWAY repo in its own temp dir. GIT_DIR takes precedence over cwd-based discovery, so those
# child `git init` calls silently no-op against the REAL worktree gitdir instead of creating a
# fresh temp repo, then `git remote add origin` fails with "remote origin already exists" (it's
# adding to the real repo's already-populated config) — confirmed by direct reproduction. Unset
# here, before any nested suite runs, so they fall back to correct cwd-based discovery; safe
# because ROOT below is resolved from this script's own path (lib.sh), not from git, and this
# script's own two direct git calls further down use `git -C "$ROOT"` (an explicit path, not
# reliant on ambient GIT_DIR). Do NOT hoist this into the pre-commit hook itself: session-lock and
# data-guard (the two steps that run before this script) both need the real, git-provided
# GIT_DIR/GIT_INDEX_FILE to find the worktree's own lock file and diff the ACTUAL staged commit.
#
# EXTEND the unset to the full set of git env vars the AWA guard treats as "risky" for primary
# maintenance (engine/guard.py `_PRIMARY_MAINTENANCE_RISKY_GIT_ENV`) — most importantly
# GIT_EXEC_PATH, which `git commit` unconditionally exports to every hook. The nested AWA
# `engine.tests.test_guard` suite (run below via worktree-verify -> kernel-guarantee-verify, and
# again via copy-honesty's verifier_cmd) exercises the guard's "safe to maintain" decision, which
# FAILS CLOSED when ANY risky var is present. Unsetting only GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE
# left GIT_EXEC_PATH leaking, so 36 maintenance "allow" assertions flipped to deny under the
# pre-commit hook (but NOT in a plain-shell `--ci` run, which has no GIT_EXEC_PATH) —
# false-blocking every commit to this repo. Sanitizing the full set here, once, before any nested
# suite, fixes it for the whole process tree; safe because this script's own git calls use
# `git -C "$ROOT"` and git falls back to its built-in exec path when GIT_EXEC_PATH is unset.
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
  GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_CONFIG GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM GIT_EXEC_PATH \
  GIT_NAMESPACE GIT_SHALLOW_FILE GIT_REPLACE_REF_BASE GIT_NO_REPLACE_OBJECTS \
  GIT_CEILING_DIRECTORIES GIT_DISCOVERY_ACROSS_FILESYSTEM

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # _ops/checks
# shellcheck source=../bin/lib.sh
source "$SELF_DIR/../bin/lib.sh"

ROOT="$(om_repo_root)"
MODE="local"
case "${1:-}" in
  --ci) exec python3 -I -B "$ROOT/scripts/verify.py" local ;;
  --ci-group)
    [ "$#" -eq 2 ] || exit 2
    exec python3 -I -B "$ROOT/scripts/verify.py" local --shard "$2" ;;
  --source-contracts) MODE="ci" ;;
  --local|"") MODE="local" ;;
  *) printf 'usage: %s [--ci|--ci-group GROUP|--local]\n' "$0" >&2; exit 2 ;;
esac
fail=0
pass() { printf '  PASS  %s\n' "$1"; }
warn() { printf '  WARN  %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; fail=1; }

echo "== Repo structure (mirrors cpp _ops/ conventions) =="
for rel in \
  OPERATING-MANUAL.md README.md AGENTS.md Makefile bootstrap.sh \
  _ops/POLICY.md _ops/README.md \
  _ops/rules/agent-context.md _ops/rules/dev-operating-model.mdc \
  _ops/bin/lib.sh _ops/bin/install-agent-rules.sh _ops/bin/install-hooks.sh \
  _ops/bin/install-skills.sh _ops/bin/install-identity-guard.sh _ops/bin/dev-new-repo.sh \
  _ops/bin/install-mcp.sh _ops/bin/session-lock.sh _ops/bin/dev-worktree.sh \
  _ops/bin/check-awa-release-binding.py _ops/bin/install-awa-integrity-job.sh \
  _ops/bin/awa-integrity-host-sweep.sh _ops/bin/install-worktree-hooks.sh \
  _ops/bin/baseline-lib.sh _ops/bin/repo-baseline.sh \
  _ops/baseline/README.md _ops/baseline/template/SECURITY.md _ops/baseline/template/CODEOWNERS \
  _ops/baseline/template/gitignore-block.txt _ops/baseline/template/README.md.tmpl \
  _ops/baseline/profiles/pr-automation/README.md _ops/baseline/profiles/pr-automation/LIFECYCLE.md \
  _ops/baseline/profiles/pr-automation/config.schema.json _ops/baseline/profiles/pr-automation/canary-proof.schema.json \
  _ops/baseline/profiles/pr-automation/config.json \
  _ops/baseline/profiles/pr-automation/ruleset.json.tmpl _ops/baseline/profiles/pr-automation/required.yml \
  _ops/baseline/profiles/pr-automation/CODEOWNERS.block _ops/baseline/profiles/pr-automation/profile.py \
  _ops/baseline/profiles/pr-automation/test_profile.py _ops/baseline/profiles/pr-automation/test.sh \
  _ops/baseline/profiles/pr-automation/controller.yml.tmpl _ops/baseline/profiles/pr-automation/APP-CONTROLLER.md \
  _ops/baseline/profiles/pr-automation/phase-b.config.json _ops/baseline/profiles/pr-automation/phase-b.config.schema.json \
  _ops/baseline/profiles/pr-automation/fleet.json _ops/baseline/profiles/pr-automation/fleet.schema.json \
  _ops/baseline/profiles/pr-automation/phase-b.evidence.schema.json _ops/baseline/profiles/pr-automation/phase-b.state.schema.json \
  _ops/baseline/profiles/pr-automation/review-gate.ruleset.json.tmpl _ops/baseline/profiles/pr-automation/merge-safety.ruleset.json.tmpl \
  _ops/baseline/profiles/pr-automation/fleet.py _ops/baseline/profiles/pr-automation/test_fleet.py \
  _ops/baseline/profiles/pr-automation/v3/README.md _ops/baseline/profiles/pr-automation/v3/controller.json \
  _ops/baseline/profiles/pr-automation/v3/controller.schema.json _ops/baseline/profiles/pr-automation/v3/fleet.json \
  _ops/baseline/profiles/pr-automation/v3/fleet.schema.json _ops/baseline/profiles/pr-automation/v3/repository-policy.schema.json \
  _ops/baseline/profiles/pr-automation/v3/verification-manifest.schema.json \
  \
  _ops/baseline/profiles/pr-automation/v3/coverage-assignments.schema.json \
  _ops/baseline/profiles/pr-automation/v3/merge-safety.ruleset.json.tmpl \
  _ops/baseline/profiles/pr-automation/v3/profile.py _ops/baseline/profiles/pr-automation/v3/test.sh \
  _ops/baseline/profiles/pr-automation/v3/bypass-drift-test.sh \
  _ops/hooks/pre-commit _ops/hooks/identity-guard _ops/hooks/session-lock _ops/hooks/data-guard _ops/hooks/registration-guard \
  _ops/cursor-hooks/worktree-session.sh _ops/cursor-hooks/worktree-guard.sh \
  _ops/cursor-hooks/worktree-guard-with-integrity.sh \
  _ops/cursor-hooks/awa-integrity-observer.sh _ops/cursor-hooks/awa-session-handoff.sh \
  _ops/local-jobs/awa-integrity.sh _ops/tests/awa-integrity-host.sh \
  _ops/tests/fixtures/awa-v1.8.1/awa-hook-owner.v2.json \
  _ops/tests/fixtures/awa-v1.8.1/awa-integrity-schedule.v1.json \
  _ops/policy/worktree-policy.yml _ops/rules/global/worktree-default.mdc \
  _ops/bin/awa-dashboard-data.py _ops/bin/install-awa-dashboard.sh _ops/dashboards/awa-dashboard.canvas.tsx \
  _ops/checks/verify-operating-model.sh _ops/checks/dev-doctor.sh _ops/checks/worktree-verify.sh \
  _ops/portability/engine.py _ops/portability/test_engine.py _ops/portability/package.py \
  _ops/portability/test_package.py _ops/portability/manifest.json _ops/portability/README.md \
  _ops/portability/START-HERE.md _ops/portability/DESTINATION-PROMPT.txt _ops/portability/MANUAL-ACTIONS.md \
  \
  _ops/verification/README.md _ops/verification/contracts.py \
  _ops/verification/test_contracts.py _ops/verification/fixtures/wire-goldens-v1.json \
  _ops/verification/verification-manifest.schema.json \
  _ops/verification/verification-receipt.schema.json \
  _ops/verification/verification-rollout-ledger.schema.json \
  _ops/verification/verification-rollout-ledger.json \
  _ops/verification/path-checks.json _ops/verification/path_gate.py \
  _ops/verification/test_path_gate.py \
  _ops/tests/snow-kit-host-bootstrap.sh capabilities/mcp-bootstrap.sh capabilities/mcp-pins.env \
  _ops/bin/dev-remove-repo.sh _ops/tests/dev-remove-repo.sh \
  _ops/tests/fixtures/dev-remove-repo/m1-replay.sanitized.jsonl \
  _ops/skills/dev-doctor/SKILL.md _ops/skills/dev-new-repo/SKILL.md _ops/skills/dev-remove-repo/SKILL.md \
  _ops/doc-warden/POLICY.md _ops/doc-warden/triggers.yml \
  _ops/bin/doc-warden-lib.sh _ops/bin/doc-warden.sh _ops/checks/doc-warden-verify.sh \
  _ops/skills/doc-warden/SKILL.md docs/runbooks/awa-integrity-host-wiring.md \
  docs/runbooks/gsd-core-lock-requalification.md docs/runbooks/dev-repo-removal.md \
  _ops/context-measurement/kp_context_measure.py _ops/context-measurement/test_kp_context_measure.py \
  _ops/context-measurement/validate_static_context_manifest.py _ops/context-measurement/test_validate_static_context_manifest.py \
  _ops/context-measurement/release2_closure.py _ops/context-measurement/test_release2_closure.py \
  _ops/context-measurement/README.md \
  .gitignore ; do
  if [ -e "$ROOT/$rel" ]; then pass "$rel present"; else bad "$rel MISSING"; fi
done

echo "== Frozen manifest-verification v1 contracts (inert) =="
verification_schema_paths=(
  "$ROOT/_ops/verification/verification-manifest.schema.json"
  "$ROOT/_ops/verification/verification-receipt.schema.json"
  "$ROOT/_ops/verification/verification-rollout-ledger.schema.json"
)
verification_ledger="$ROOT/_ops/verification/verification-rollout-ledger.json"
verification_contracts="$ROOT/_ops/verification/contracts.py"
verification_contract_out="$(mktemp)"
trap 'rm -f "$verification_contract_out"' EXIT
verification_json_ok=1
for verification_json in "${verification_schema_paths[@]}" "$verification_ledger"; do
  if python3 -m json.tool "$verification_json" >/dev/null 2>"$verification_contract_out"; then
    pass "${verification_json#$ROOT/} JSON parses"
  else
    bad "${verification_json#$ROOT/} JSON parse failed"
    sed 's/^/        /' "$verification_contract_out"
    verification_json_ok=0
  fi
done
if [ "$verification_json_ok" -eq 1 ] \
   && PYTHONDONTWRITEBYTECODE=1 python3 "$verification_contracts" \
     check-schemas "${verification_schema_paths[@]}" >"$verification_contract_out" 2>&1; then
  pass "manifest-verification schemas self-validate"
else
  bad "manifest-verification schema self-validation failed"
  sed 's/^/        /' "$verification_contract_out"
fi
if [ "$verification_json_ok" -eq 1 ] \
   && PYTHONDONTWRITEBYTECODE=1 python3 "$verification_contracts" \
     check-ledger "$verification_ledger" "${verification_schema_paths[@]}" \
     >"$verification_contract_out" 2>&1; then
  pass "authority genesis validates against frozen contracts"
else
  bad "authority genesis contract validation failed"
  sed 's/^/        /' "$verification_contract_out"
fi
rm -f "$verification_contract_out"
trap - EXIT

# Source suite execution lives in the one closed shard manifest, shared with CI.
if [ "$MODE" = "local" ]; then
  python3 -I -B "$ROOT/scripts/verify.py" local || fail=1
fi

echo "== Cursor .mdc is in sync with the SOT (agent-context.md) =="
if [ -f "$(om_mdc_path)" ] && diff -q <(om_gen_mdc) "$(om_mdc_path)" >/dev/null 2>&1; then
  pass "dev-operating-model.mdc matches agent-context.md"
else
  bad "dev-operating-model.mdc is STALE — run: bash _ops/bin/install-agent-rules.sh --gen-only"
fi

# Decision A: INV-single-master is RETIRED. The SOT (and therefore every mirrored block in
# Cursor/Codex/Claude) must not assert it as a live invariant. A mention is allowed only on a
# line that ALSO carries the word "retired" (e.g. "INV-single-master is retired") — the history
# is fine, the assertion is not.
echo "== agent-context.md does not assert the retired INV-single-master =="
ctx="$ROOT/_ops/rules/agent-context.md"
if [ -f "$ctx" ]; then
  if grep -nE 'INV-single-master' "$ctx" | grep -viE 'retired' >/dev/null 2>&1; then
    bad "agent-context.md mentions INV-single-master without 'retired' on the same line (Decision A)"
    grep -nE 'INV-single-master' "$ctx" | grep -viE 'retired' | sed 's/^/        /'
  else
    pass "agent-context.md: no live INV-single-master assertion"
  fi
else
  bad "agent-context.md missing"
fi

echo "== .gitignore allow-list integrity (no work/personal/nested repos tracked) =="
if command -v git >/dev/null 2>&1 && git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if grep -q '^/\*' "$ROOT/.gitignore"; then pass ".gitignore starts from an ignore-all allow-list"; else bad ".gitignore is not an allow-list (missing '/*')"; fi
  leaked="$(git -C "$ROOT" ls-files -- affirm personal capabilities/skills capabilities/mcp 2>/dev/null)"
  if [ -z "$leaked" ]; then
    pass "no tracked files under affirm/ personal/ capabilities/{skills,mcp}"
  else
    bad "allow-list LEAK — these should never be tracked:"; printf '        %s\n' $leaked
  fi
else
  warn "not a git work tree (or git missing) — skipped tracked-file audit"
fi

echo "== ~/dev AGENTS.md is continual-learning-memory-free (machine ## Learned blocks live in git-ignored agent-learnings.md) =="
agents_md="$ROOT/AGENTS.md"
if [ -f "$agents_md" ]; then
  if grep -qE '^## Learned (User Preferences|Workspace Facts)\b' "$agents_md"; then
    bad "AGENTS.md still contains machine '## Learned *' block(s) — they must live in git-ignored agent-learnings.md"
    grep -nE '^## Learned (User Preferences|Workspace Facts)\b' "$agents_md" | sed 's/^/        /'
  elif ! grep -qF 'agent-learnings.md' "$agents_md"; then
    bad "AGENTS.md is missing the agent-learnings.md pointer (continual-learning memory relocation)"
  else
    pass "AGENTS.md carries no machine '## Learned *' blocks and points to agent-learnings.md"
  fi
else
  bad "AGENTS.md missing"
fi

echo "== Global Cursor-rule SOTs (home + reusable capability sources) =="
gcount="$(om_list_global_rules | wc -l | tr -d ' ')"
if [ "${gcount:-0}" -gt 0 ]; then
  pass "global rule SOT present ($gcount managed rule(s))"
else
  warn "no managed global rule SOT found — the cross-tool mirror has no versioned source"
fi

if [ "$MODE" = "local" ]; then
  subagent_rule_dir="$OM_CAPABILITY_RULES_DIR/subagent-orchestration"
  if [ -f "$subagent_rule_dir/subagent-orchestration.mdc" ] \
     && [ -f "$subagent_rule_dir/model-tiers.json" ] \
     && [ -f "$subagent_rule_dir/verify_model_tiers.py" ]; then
    pass "replacement subagent policy rule + shared catalog present"
    if python3 "$subagent_rule_dir/verify_model_tiers.py" >/dev/null 2>&1; then
      pass "shared subagent model-tier catalog valid"
    else
      bad "shared subagent model-tier catalog invalid"
    fi
  else
    bad "replacement subagent policy incomplete — refresh capabilities/skills"
  fi
fi

if [ "$MODE" = "ci" ]; then
  echo
  if [ "$fail" -eq 0 ]; then echo "verify-operating-model (--ci): OK"; else echo "verify-operating-model (--ci): FAILED"; fi
  exit "$fail"
fi

echo "== Agent rules installed & current on THIS machine =="

# Cursor: symlink resolves to the repo .mdc.
cursor_link="$HOME/.cursor/rules/dev-operating-model.mdc"
if [ -L "$cursor_link" ] && [ -e "$cursor_link" ] && [ "$(readlink "$cursor_link")" = "$(om_mdc_path)" ]; then
  pass "cursor: $cursor_link -> repo .mdc (resolves)"
elif [ -L "$cursor_link" ]; then
  bad "cursor: $cursor_link is a symlink but not pointing at the repo .mdc (run install-agent-rules.sh)"
else
  bad "cursor: $cursor_link missing/not a symlink (run install-agent-rules.sh)"
fi

# Global rules: every present versioned SOT must resolve from ~/.cursor/rules.
if [ -n "$(om_list_global_rules)" ]; then
  gmiss=0
  while IFS= read -r sot; do
    [ -n "$sot" ] || continue
    link="$HOME/.cursor/rules/$(basename "$sot")"
    if [ -L "$link" ] && [ -e "$link" ] && [ "$(readlink "$link")" = "$sot" ]; then :; else
      bad "cursor: global rule $(basename "$sot" .mdc) not linked to SOT (run install-agent-rules.sh)"; gmiss=1
    fi
  done <<EOF
$(om_list_global_rules)
EOF
  [ "$gmiss" -eq 0 ] && pass "cursor: all $(om_list_global_rules | wc -l | tr -d ' ') managed global rule(s) resolve"
fi

# Codex / Claude: managed block present AND byte-current with what we'd generate now.
check_block() {
  local target="$1" label="$2"
  if [ ! -f "$target" ]; then bad "$label: $target missing (run install-agent-rules.sh)"; return; fi
  if ! grep -qF "$OM_BEGIN_MARK" "$target"; then bad "$label: managed block ABSENT (run install-agent-rules.sh)"; return; fi
  if diff -q <(om_build_block) <(om_extract_block "$target") >/dev/null 2>&1; then
    pass "$label: managed block present & hash-current"
  else
    bad "$label: managed block STALE/edited (run install-agent-rules.sh)"
  fi
}
NATIVE_CODEX=0
if [ -f "$HOME/.codex/AGENTS.md" ] && grep -qF 'native-entry-routing/v1' "$HOME/.codex/AGENTS.md"; then
  NATIVE_CODEX=1
  if PYTHONDONTWRITEBYTECODE=1 python3 "$ROOT/_ops/interoperability/native_rules.py" verify; then
    pass "codex: native owner-source managed blocks current (behavior qualification is separate)"
  else
    bad "codex: native owner-source projection stale; preview explicit reconciliation"
  fi
else
  check_block "$HOME/.codex/AGENTS.md" "codex"
fi
check_block "$HOME/.claude/CLAUDE.md" "claude"

# Cross-tool behavioral-rule mirror: assert the cursor-rules-mirror block is current in
# Codex/Claude — but only when there are alwaysApply Cursor rules on THIS machine to mirror
# (a fresh machine before the Cursor rules land has nothing to mirror; that's not a failure).
check_rules_block() {
  local target="$1" label="$2"
  if [ ! -f "$target" ]; then bad "$label: $target missing (run install-agent-rules.sh)"; return; fi
  if ! grep -qF "$OM_RULES_BLOCK_BEGIN" "$target"; then bad "$label: cursor-rules mirror ABSENT (run install-agent-rules.sh)"; return; fi
  if diff -q <(om_build_rules_block) <(om_extract_rules_block "$target") >/dev/null 2>&1; then
    pass "$label: cursor-rules mirror present & current"
  else
    bad "$label: cursor-rules mirror STALE/edited (run install-agent-rules.sh)"
  fi
}
if [ -n "$(om_build_rules_block)" ]; then
  echo "== Cross-tool behavioral-rule mirror (alwaysApply Cursor rules -> Codex/Claude) =="
  [ "$NATIVE_CODEX" -eq 1 ] || check_rules_block "$HOME/.codex/AGENTS.md" "codex"
  check_rules_block "$HOME/.claude/CLAUDE.md" "claude"
else
  warn "cursor-rules mirror: no alwaysApply Cursor rules found on this machine (nothing to mirror)"
fi

# Conditional MCP-safety mirror (same shape; only assert when there are *-mcp-safety rules here).
check_mcp_rules_block() {
  local target="$1" label="$2"
  if [ ! -f "$target" ]; then bad "$label: $target missing (run install-agent-rules.sh)"; return; fi
  if ! grep -qF "$OM_MCP_RULES_BLOCK_BEGIN" "$target"; then bad "$label: mcp-safety mirror ABSENT (run install-agent-rules.sh)"; return; fi
  if diff -q <(om_build_mcp_rules_block) <(om_extract_mcp_rules_block "$target") >/dev/null 2>&1; then
    pass "$label: mcp-safety mirror present & current"
  else
    bad "$label: mcp-safety mirror STALE/edited (run install-agent-rules.sh)"
  fi
}
if [ -n "$(om_build_mcp_rules_block)" ]; then
  echo "== Cross-tool MCP-safety mirror (*-mcp-safety Cursor rules -> Codex/Claude) =="
  [ "$NATIVE_CODEX" -eq 1 ] || check_mcp_rules_block "$HOME/.codex/AGENTS.md" "codex"
  check_mcp_rules_block "$HOME/.claude/CLAUDE.md" "claude"
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "verify-operating-model: OK (repo invariants + all three tool rules installed & current)"
else
  echo "verify-operating-model: FAILED (see FAIL lines above)"
fi
exit "$fail"
