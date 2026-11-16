#!/usr/bin/env bash
# Verify the worktree-by-default automation surface.  Read-only.
set -uo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "$SELF_DIR/../.." && pwd)"
fail=0
pass() { printf '  PASS  %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; fail=1; }
skip() { printf '  SKIP  %s\n' "$1"; }

# Source CI is explicit: never resolve an installed runtime or a sibling checkout.
# Default invocation retains release-bound host verification and fails on bad bindings.
source_only=0
case "${1:-}" in
  --source-only) [ "$#" -eq 1 ] || exit 2; source_only=1 ;;
  "") [ "$#" -eq 0 ] || exit 2 ;;
  *) printf 'usage: worktree-verify.sh [--source-only]\n' >&2; exit 2 ;;
esac

awa_verify_owner="$(mktemp -d)" || exit 1
tmp_paths=("$awa_verify_owner")
cleanup_awa_uats() {
  unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES 2>/dev/null || true
  for path in "${tmp_paths[@]:-}"; do
    [ -n "$path" ] || continue
    rm -rf "$path" 2>/dev/null || true
  done
}
trap cleanup_awa_uats EXIT

if [ "$source_only" = 1 ]; then
  export DEV_AWA_SOURCE_ONLY=1
  export AWA_HOME="$awa_verify_owner/absent-runtime"
  export AWA_ENGINE_HOME="$awa_verify_owner/absent-runtime"
  export AWA_ENGINE_ROOT=""
  export XDG_DATA_HOME="$awa_verify_owner/xdg/data"
  export XDG_CONFIG_HOME="$awa_verify_owner/xdg/config"
  export XDG_STATE_HOME="$awa_verify_owner/xdg/state"
  AWA_RUNTIME="$AWA_HOME"
  INSTALLED_KERNEL_CLI="$AWA_RUNTIME/kernel/bin/dev-worktree.sh"
  AWA_INSTALLED=0
  echo "worktree-verify: SOURCE ONLY; installed runtime and sibling qualification withheld"
else
  # An inherited CI flag cannot weaken the default host verification mode.
  unset DEV_AWA_SOURCE_ONLY
  AWA_RUNTIME="${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}"
  INSTALLED_KERNEL_CLI="$AWA_RUNTIME/kernel/bin/dev-worktree.sh"
  if [ -x "$INSTALLED_KERNEL_CLI" ]; then AWA_INSTALLED=1; else AWA_INSTALLED=0; fi
  if [ "$AWA_INSTALLED" = 1 ]; then
    AWA_RUNTIME="$(cd "$AWA_RUNTIME" && pwd -P)"
    # Resolve development-only evidence before isolating XDG; runtime packages omit it.
    # This validates the installed binding and the exact clean, pinned source checkout.
    AWA_VERIFY_SOURCE="$(python3 "$ROOT/_ops/bin/check-awa-release-binding.py" --source-root)" || exit 1
  fi
fi

# Re-entrancy guard (fork-bomb prevention). The disposable UATs below run `git commit` inside
# throwaway repos. If one of those commits ever executes against a governed tree, that tree's
# pre-commit hook chains into verify-operating-model.sh -> this script, which would recurse and
# fork-bomb the machine. Refuse a nested invocation rather than recurse. (The primary fix is the
# fatal scratch-repo guard in new_included_repo; this is defense-in-depth.)
if [ "${AWA_WORKTREE_VERIFY_ACTIVE:-0}" = "1" ]; then
  echo "worktree-verify: refusing re-entrant invocation (AWA_WORKTREE_VERIFY_ACTIVE already set)" >&2
  exit 0
fi
export AWA_WORKTREE_VERIFY_ACTIVE=1

# Pre-commit runs with GIT_INDEX_FILE and friends set for the parent repo. The
# disposable UAT repos below must use their own git metadata, not the parent index.
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES 2>/dev/null || true

echo "== Worktree automation policy/tooling =="

if python3 -B "$ROOT/_ops/tests/test_awa_evidence_binding.py"; then
  pass "release-bound source evidence identity and refusal cases"
else
  bad "release-bound source evidence checks failed"
fi

if python3 -B "$ROOT/_ops/tests/test_shadow_sync_host_policy.py"; then
  pass "ShadowSync host-policy publication and failure-path fixtures"
else
  bad "ShadowSync host-policy publication checks failed"
fi

if python3 -B "$ROOT/_ops/tests/test_identity_dispatcher.py"; then
  pass "canonical dispatcher installation and prior-hook preservation"
else
  bad "canonical dispatcher installation checks failed"
fi

for rel in \
  _ops/policy/worktree-policy.yml \
  _ops/bin/dev-worktree.sh \
  _ops/bin/check-awa-release-binding.py \
  _ops/bin/install-awa-integrity-job.sh \
  _ops/bin/install-worktree-hooks.sh \
  _ops/local-jobs/awa-integrity.sh \
  _ops/cursor-hooks/worktree-session.sh \
  _ops/cursor-hooks/worktree-guard.sh \
  _ops/cursor-hooks/worktree-guard-with-integrity.sh \
  _ops/cursor-hooks/awa-integrity-observer.sh \
  _ops/cursor-hooks/awa-session-handoff.sh \
  _ops/tests/awa-host-overlay.sh \
  _ops/tests/awa-integrity-host.sh \
  _ops/rules/global/worktree-default.mdc ; do
  if [ -e "$ROOT/$rel" ]; then pass "$rel present"; else bad "$rel MISSING"; fi
done

for rel in \
  _ops/bin/dev-worktree.sh \
  _ops/bin/check-awa-release-binding.py \
  _ops/bin/install-awa-integrity-job.sh \
  _ops/bin/install-worktree-hooks.sh \
  _ops/local-jobs/awa-integrity.sh \
  _ops/cursor-hooks/worktree-session.sh \
  _ops/cursor-hooks/worktree-guard.sh \
  _ops/cursor-hooks/worktree-guard-with-integrity.sh \
  _ops/cursor-hooks/awa-integrity-observer.sh \
  _ops/cursor-hooks/awa-session-handoff.sh \
  _ops/tests/awa-host-overlay.sh \
  _ops/tests/awa-integrity-host.sh
do
  if [ -x "$ROOT/$rel" ]; then pass "$rel executable"; else bad "$rel not executable"; fi
done

echo "== E-06 host-overlay lifecycle =="
if bash "$ROOT/_ops/tests/awa-host-overlay.sh"; then
  pass "E-06 external-owner host-overlay lifecycle"
else
  bad "E-06 external-owner host-overlay lifecycle failed"
fi

echo "== M1 integrity host wiring =="
if bash "$ROOT/_ops/tests/awa-integrity-host.sh"; then
  pass "M1 local-jobs host adapter and source contract"
else
  bad "M1 local-jobs host adapter or source contract failed"
fi

# E-06 and M1 above own their complete environments. Bind the following installed
# runtime probes only after those self-contained fixture suites have finished.
if [ "$AWA_INSTALLED" = 1 ]; then
  export AWA_HOME="$AWA_RUNTIME" AWA_ENGINE_HOME="$AWA_RUNTIME" AWA_ENGINE_ROOT="$AWA_VERIFY_SOURCE"
fi
export AWA_GOVERNED_ROOT="$awa_verify_owner/governed"
export AWA_VERIFY_BASE="$AWA_GOVERNED_ROOT/personal"
export XDG_STATE_HOME="$awa_verify_owner/xdg/state"
export XDG_DATA_HOME="$awa_verify_owner/xdg/data"
export XDG_CONFIG_HOME="$awa_verify_owner/xdg/config"
mkdir -p "$AWA_VERIFY_BASE" "$XDG_STATE_HOME" "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" || exit 1

# policy-check + status resolve through the delegator into the installed kernel. When AWA is
# installed they must succeed with the ~/dev host policy overlay; when absent, the delegator
# degrades (exit 3) and we skip (the overlay --check covers policy validity statically).
if [ "$AWA_INSTALLED" = 1 ]; then
  if "$ROOT/_ops/bin/dev-worktree.sh" policy-check >/dev/null 2>&1; then
    pass "dev-worktree policy-check (delegates to installed kernel + host policy)"
  else
    bad "dev-worktree policy-check failed"
  fi
  if "$ROOT/_ops/bin/dev-worktree.sh" status >/dev/null 2>&1; then
    pass "dev-worktree status (delegates to installed kernel + host policy)"
  else
    bad "dev-worktree status failed"
  fi
else
  skip "dev-worktree policy-check + status (AWA not installed; overlay --check covers policy validity)"
fi

if grep -q 'worktree list --porcelain' "$ROOT/_ops/checks/dev-doctor.sh"; then
  pass "dev-doctor includes git worktree discovery"
else
  bad "dev-doctor does not include git worktree discovery"
fi

if grep -q -- '--git-common-dir' "$ROOT/_ops/bin/install-identity-guard.sh"; then
  pass "identity guard installer uses git common dir for linked worktrees"
else
  bad "identity guard installer is not linked-worktree safe"
fi

echo "== AWA status dashboard =="

for rel in \
  _ops/bin/awa-dashboard-data.py \
  _ops/bin/install-awa-dashboard.sh \
  _ops/dashboards/awa-dashboard.canvas.tsx ; do
  if [ -e "$ROOT/$rel" ]; then pass "$rel present"; else bad "$rel MISSING"; fi
done

for rel in _ops/bin/awa-dashboard-data.py _ops/bin/install-awa-dashboard.sh; do
  if [ -x "$ROOT/$rel" ]; then pass "$rel executable"; else bad "$rel not executable"; fi
done

# The dashboard-data verb (delegated to the installed kernel) must emit valid awa-worktree/v1 JSON.
# Scan an empty temp root so the check stays fast and READ-ONLY (no ~/dev walk, no side effects).
if [ "$AWA_INSTALLED" = 1 ]; then
  awa_tmp="$(mktemp -d "$awa_verify_owner/dashboard.XXXXXX")" || exit 1
  if "$ROOT/_ops/bin/dev-worktree.sh" dashboard-data --root "$awa_tmp" 2>/dev/null \
     | python3 -c 'import json,sys; d=json.load(sys.stdin); s=d.get("summary",{}); sys.exit(0 if d.get("schema")=="awa-worktree/v1" and isinstance(d.get("repos"),list) and isinstance(s,dict) and "orphan_branches" in s else 1)'; then
    pass "dev-worktree dashboard-data emits valid awa-worktree/v1 JSON"
  else
    bad "dev-worktree dashboard-data did not emit valid awa-worktree/v1 JSON"
  fi
  # Phase 8: the emitter backs the dashboard's engine card with REAL engine state — an
  # additive `environment.engine.{running,mode,reason}` field (contract v1 allows additive
  # keys). READ-ONLY: it only probes the daemon pidfile via awa-engine.sh; engine-off
  # degrades honestly (running=false, mode="off").
  if "$ROOT/_ops/bin/dev-worktree.sh" dashboard-data --root "$awa_tmp" 2>/dev/null \
     | python3 -c 'import json,sys; e=json.load(sys.stdin).get("environment",{}).get("engine",{}); sys.exit(0 if isinstance(e.get("running"),bool) and e.get("mode") in ("running","off") and isinstance(e.get("reason"),str) and e["reason"] else 1)'; then
    pass "dashboard-data emits engine-backed environment.engine (Phase 8, additive)"
  else
    bad "dashboard-data did not emit a valid environment.engine field (Phase 8)"
  fi
  rm -rf "$awa_tmp"
else
  skip "dashboard-data JSON emission (AWA not installed; installed emitter verified in KleinPerkins/awa CI)"
fi

# The tracked canvas seed must stay data-free (no committed machine snapshot).
if "$ROOT/_ops/bin/install-awa-dashboard.sh" --check >/dev/null 2>&1; then
  pass "awa dashboard seed is data-free"
else
  bad "awa dashboard seed is NOT data-free (run: install-awa-dashboard.sh --seed)"
fi

# The canvas seed must carry the data-injection markers and honest agent-refresh copy.
awa_canvas="$ROOT/_ops/dashboards/awa-dashboard.canvas.tsx"
if grep -q 'AWA_DATA_START' "$awa_canvas" &&
   grep -q 'AWA_DATA_END' "$awa_canvas" &&
   grep -q 'const raw = INITIAL_RAW' "$awa_canvas" &&
   grep -q 'Refresh via agent' "$awa_canvas" &&
   grep -q 'Run make worktree-dashboard' "$awa_canvas"; then
  pass "awa dashboard canvas has injection markers + honest refresh state"
else
  bad "awa dashboard canvas missing injection markers, raw-state behavior, or refresh copy"
fi

# `ensure --json` must use a quiet `worktree add` so stdout stays pure JSON. This is an INSTALLED
# KERNEL property now (the ~/dev entry point is a thin delegator); grep the installed kernel.
if [ "$AWA_INSTALLED" = 1 ]; then
  if grep -q 'worktree add -q' "$INSTALLED_KERNEL_CLI"; then
    pass "dev-worktree ensure --json uses quiet worktree add (installed kernel)"
  else
    bad "installed kernel dev-worktree.sh does not use quiet worktree add (stdout pollution)"
  fi
else
  skip "quiet worktree-add property (AWA not installed; installed-kernel property, verified in KleinPerkins/awa CI)"
fi

if grep -q -- '--git-common-dir' "$ROOT/_ops/checks/dev-doctor.sh"; then
  pass "dev-doctor uses git common dir for hook visibility"
else
  bad "dev-doctor does not use git common dir for hook visibility"
fi

echo "== AWA disposable UATs =="

# The source policy still classifies personal/* as included; the base is beneath
# the verifier-owned governed root created above, never the real personal shelf.

new_included_repo() {
  # Fork-bomb guard: a failed mktemp must NEVER leave REPO empty, or the subsequent
  # `git -C "$repo" ...` calls would run against the current worktree (a governed tree),
  # triggering its pre-commit hook -> verify-operating-model.sh -> this script -> recursion.
  REPO="$(mktemp -d "$AWA_VERIFY_BASE/.awa-verify.XXXXXX" 2>/dev/null || true)"
  if [ -z "${REPO:-}" ] || [ ! -d "$REPO" ]; then
    bad "could not create disposable UAT scratch repo under $AWA_VERIFY_BASE"
    echo "worktree-verify: FATAL — disposable UAT scratch unavailable; aborting before any git op to avoid operating on the parent repo" >&2
    echo "worktree-verify: FAILED"
    exit 1
  fi
  local repo="$REPO"
  tmp_paths+=("$repo" "$repo.wt" "$repo.wt2" "$repo.wt3" "$repo.fail")
  (
    unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES 2>/dev/null || true
    git init -q "$repo"
    printf '# uat\n' > "$repo/README.md"
    git -C "$repo" add README.md
    git -C "$repo" -c user.email="49759187+KleinPerkins@users.noreply.github.com" -c user.name="KleinPerkins" commit -qm init
    git -C "$repo" branch -M main
    git -C "$repo" remote add origin "git@github.com:KleinPerkins/awa-verify-temp.git"
  )
}

json_get_action='import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get("action")==sys.argv[2] and d.get("rootPath") and d.get("branch") else 1)'
json_permission='import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("permission")==sys.argv[1] else 1)'

# v1.8 `ensure` publishes one machine-global pending handoff record. Every H3
# ensure below therefore gets its own test-owned XDG state root, removed before
# its disposable worktree. Never let a prior case's now-absent root make the
# next case's handoff record unreadable, and never touch the operator's state.
clear_h3_handoff_state() {
  local owner="$1" state="$2"
  case "$state" in
    "$owner"/handoff-*) ;;
    *) bad "H3 handoff isolation path escaped its disposable owner"; return 1 ;;
  esac
  if rm -rf -- "$state" && [ ! -e "$state" ]; then
    return 0
  fi
  bad "H3 handoff isolation cleanup failed"
  return 1
}

# The following disposable UATs drive `ensure`/`clean`/the guard through the ~/dev delegators into
# the INSTALLED kernel (with the host policy overlay). They require AWA to be installed; on a runner
# without the private release they SKIP (the kernel behavior is verified in KleinPerkins/awa CI).
if [ "$AWA_INSTALLED" = 1 ]; then

# H3 setup-execution tests need `include` classification: run_worktree_setup intentionally
# gates on explicit `include`, independent of the host's `default_mode` (this host defaults
# eligible repos to `on`). Force `on` via a scoped policy override rather than
# mutating the real source-tracked modes file (which is tool-owned and must not be touched
# by a read-only verify script). NOTE: the override content is global (`default_mode: on`
# for EVERY eligible repo the classifier would see) — it is safe here ONLY because it is
# passed via env var solely to the disposable-repo invocations below, never exported and
# never used against a real working tree. Do not reuse this pattern outside a test harness.
awa_h3_policy="$(mktemp)"; tmp_paths+=("$awa_h3_policy")
grep -vE '^[[:space:]]*modes_file:' "$ROOT/_ops/policy/worktree-policy.yml" > "$awa_h3_policy"
printf 'default_mode: on\n' >> "$awa_h3_policy"

# H3: repo-controlled setup config is OFF by default (not executed) and stdout stays pure.
new_included_repo; repo="$REPO"
awa_cfg="$(mktemp -d)"; tmp_paths+=("$awa_cfg")
mkdir -p "$repo/.cursor"
cat > "$repo/.cursor/worktrees.json" <<'JSON'
{"setup-worktree-unix":["python3 -c \"print('setup stdout')\""]}
JSON
git -C "$repo" add .cursor/worktrees.json
git -C "$repo" -c user.email="49759187+KleinPerkins@users.noreply.github.com" -c user.name="KleinPerkins" commit -qm setup-config
out="$(mktemp)"; err="$(mktemp)"; tmp_paths+=("$out" "$err")
awa_h3_state="$awa_cfg/handoff-off"
if (cd "$repo" && AWA_POLICY="$awa_h3_policy" XDG_CONFIG_HOME="$awa_cfg" XDG_STATE_HOME="$awa_h3_state" "$ROOT/_ops/bin/dev-worktree.sh" ensure --json --path "$repo.wt" --branch "cursor/worktree/awa-off-$$" >"$out" 2>"$err") &&
   python3 -c "$json_get_action" "$out" created &&
   ! grep -q 'setup stdout' "$err" &&
   grep -qi 'NOT allow-listed' "$err"; then
  pass "H3: repo-controlled setup config NOT executed by default (default-off)"
else
  bad "H3 default-off failed (setup ran without opt-in, or no default-off notice)"
fi
clear_h3_handoff_state "$awa_cfg" "$awa_h3_state"
git -C "$repo" worktree remove --force "$repo.wt" 2>/dev/null || true
git -C "$repo" branch -D "cursor/worktree/awa-off-$$" >/dev/null 2>&1 || true

# H3 opt-in: with DEV_WORKTREE_SETUP_OPT_IN=1 the setup runs; stdout stays pure on stderr.
awa_h3_state="$awa_cfg/handoff-optin"
if (cd "$repo" && AWA_POLICY="$awa_h3_policy" DEV_WORKTREE_SETUP_OPT_IN=1 XDG_CONFIG_HOME="$awa_cfg" XDG_STATE_HOME="$awa_h3_state" "$ROOT/_ops/bin/dev-worktree.sh" ensure --json --path "$repo.wt2" --branch "cursor/worktree/awa-optin-$$" >"$out" 2>"$err") &&
   python3 -c "$json_get_action" "$out" created &&
   grep -q 'setup stdout' "$err"; then
  pass "H3 opt-in: allow-listed setup executes; ensure --json stdout stays pure"
else
  bad "H3 opt-in setup execution failed"
fi
clear_h3_handoff_state "$awa_cfg" "$awa_h3_state"
git -C "$repo" worktree remove --force "$repo.wt2" 2>/dev/null || true
git -C "$repo" branch -D "cursor/worktree/awa-optin-$$" >/dev/null 2>&1 || true

# H3 ON deny (post-ASK_ON, 2026-07-07): the live source-tracked host default is `on` (ASK_ON removed;
# only `off` disables). Under the REAL host policy (no override) an included PRIMARY must therefore
# DENY a mutating command — the enforced-deny ON posture — while `ensure` stays eligible (only the
# safe linked worktree is where work lands). This is the host-overlay regression for the live
# default_mode VALUE: a stale `ask_on`/`off` in the tracked modes file would fail the first assert.
if grep -Eq '^[[:space:]]*default_mode:[[:space:]]*on[[:space:]]*$' "$ROOT/_ops/policy/worktree-modes.yml"; then
  pass "H3 live default: source-tracked default_mode is 'on' (ASK_ON removed; only off disables)"
else
  bad "H3 live default: host modes file default_mode is not 'on' (stale ask_on/off?)"
fi
awa_h3_state="$awa_cfg/handoff-on"
if printf '{"cwd":"%s","command":"git commit -am x"}' "$repo" | "$ROOT/_ops/cursor-hooks/worktree-guard.sh" | python3 -c "$json_permission" deny &&
   (cd "$repo" && DEV_WORKTREE_SETUP_OPT_IN=1 XDG_CONFIG_HOME="$awa_cfg" XDG_STATE_HOME="$awa_h3_state" "$ROOT/_ops/bin/dev-worktree.sh" ensure --json --path "$repo.wt3" --branch "cursor/worktree/awa-on-$$" >"$out" 2>"$err") &&
   python3 -c "$json_get_action" "$out" created; then
  pass "H3 ON deny: live host default (on) denies a mutating primary; ensure stays eligible"
else
  bad "H3 ON deny failed (mutating primary not denied under live host default, or ensure blocked)"
fi
clear_h3_handoff_state "$awa_cfg" "$awa_h3_state"
git -C "$repo" worktree remove --force "$repo.wt3" 2>/dev/null || true
git -C "$repo" branch -D "cursor/worktree/awa-on-$$" >/dev/null 2>&1 || true

# Setup failure is structured (under opt-in, since default-off would never execute).
new_included_repo; repo="$REPO"
awa_cfg="$(mktemp -d)"; tmp_paths+=("$awa_cfg")
mkdir -p "$repo/.cursor"
cat > "$repo/.cursor/worktrees.json" <<'JSON'
{"setup-worktree-unix":"python3 -c \"import sys; print('setup failed'); sys.exit(7)\""}
JSON
git -C "$repo" add .cursor/worktrees.json
git -C "$repo" -c user.email="49759187+KleinPerkins@users.noreply.github.com" -c user.name="KleinPerkins" commit -qm setup-config
out="$(mktemp)"; err="$(mktemp)"; tmp_paths+=("$out" "$err")
awa_h3_state="$awa_cfg/handoff-fail"
if ! (cd "$repo" && AWA_POLICY="$awa_h3_policy" DEV_WORKTREE_SETUP_OPT_IN=1 XDG_CONFIG_HOME="$awa_cfg" XDG_STATE_HOME="$awa_h3_state" "$ROOT/_ops/bin/dev-worktree.sh" ensure --json --path "$repo.fail" --branch "cursor/worktree/awa-fail-$$" >"$out" 2>"$err") &&
   python3 -c "$json_get_action" "$out" setup_failed &&
   grep -q 'setup failed' "$err"; then
  pass "ensure --json setup failure is structured (opt-in)"
else
  bad "ensure --json setup failure was not structured"
fi
clear_h3_handoff_state "$awa_cfg" "$awa_h3_state"
git -C "$repo" worktree remove --force "$repo.fail" 2>/dev/null || true
git -C "$repo" branch -D "cursor/worktree/awa-fail-$$" >/dev/null 2>&1 || true

new_included_repo; repo="$REPO"
git -C "$repo" worktree add -q -b "cursor/worktree/awa-unsafe-$$" "$repo.wt" main
printf 'unsafe\n' >> "$repo.wt/README.md"
git -C "$repo.wt" add README.md
git -C "$repo.wt" -c user.email="49759187+KleinPerkins@users.noreply.github.com" -c user.name="KleinPerkins" commit -qm unsafe
if ! "$ROOT/_ops/bin/dev-worktree.sh" clean --path "$repo.wt" >"$out" 2>"$err" &&
   grep -q 'local-only commits' "$err"; then
  pass "clean refuses unsafe local-only branch"
else
  bad "clean did not refuse unsafe local-only branch"
fi
git -C "$repo" worktree remove --force "$repo.wt" 2>/dev/null || true
git -C "$repo" branch -D "cursor/worktree/awa-unsafe-$$" >/dev/null 2>&1 || true

new_included_repo; repo="$REPO"
git -C "$repo" worktree add -q -b "cursor/worktree/awa-safe-$$" "$repo.wt" main
if "$ROOT/_ops/bin/dev-worktree.sh" clean --path "$repo.wt" >/dev/null 2>"$err" &&
   [ ! -e "$repo.wt" ] &&
   git -C "$repo" show-ref --verify --quiet "refs/heads/cursor/worktree/awa-safe-$$"; then
  pass "clean removes safe worktree and leaves branch"
else
  bad "clean safe worktree removal failed"
fi
git -C "$repo" branch -D "cursor/worktree/awa-safe-$$" >/dev/null 2>&1 || true

new_included_repo; repo="$REPO"
git -C "$repo" worktree add -q -b "cursor/worktree/awa-delete-$$" "$repo.wt" main
if "$ROOT/_ops/bin/dev-worktree.sh" clean --path "$repo.wt" --delete-branch >/dev/null 2>"$err" &&
   [ ! -e "$repo.wt" ] &&
   ! git -C "$repo" show-ref --verify --quiet "refs/heads/cursor/worktree/awa-delete-$$"; then
  pass "clean --delete-branch deletes safe captured branch"
else
  bad "clean --delete-branch failed"
fi

# X3: clean must bundle-or-refuse git-ignored files (never silently delete .env / *.localdb).
new_included_repo; repo="$REPO"
printf '*.env\n*.localdb\n' > "$repo/.gitignore"
git -C "$repo" add .gitignore
git -C "$repo" -c user.email="49759187+KleinPerkins@users.noreply.github.com" -c user.name="KleinPerkins" commit -qm gitignore
git -C "$repo" worktree add -q -b "cursor/worktree/awa-ign-$$" "$repo.wt" main
printf 'k=v\n' > "$repo.wt/config.env"          # secret-pattern -> must be skipped by bundle
printf 'DBDATA\n' > "$repo.wt/data.localdb"      # non-secret -> must be archived
awa_rec="$(mktemp -d)"; tmp_paths+=("$awa_rec")
# default (no --bundle/--force): refuse, listing the ignored files; worktree must survive.
if ! "$ROOT/_ops/bin/dev-worktree.sh" clean --path "$repo.wt" >/dev/null 2>"$err" &&
   grep -q 'git-ignored local files' "$err" &&
   grep -q 'config.env' "$err" &&
   [ -e "$repo.wt" ]; then
  pass "clean refuses to delete git-ignored files by default (X3 bundle-or-refuse)"
else
  bad "clean did not refuse git-ignored files by default"
fi
# --bundle: archive non-secret ignored files, SKIP secret-pattern files, then remove.
if AWA_RECOVERY_DIR="$awa_rec" "$ROOT/_ops/bin/dev-worktree.sh" clean --path "$repo.wt" --bundle >/dev/null 2>"$err" &&
   [ ! -e "$repo.wt" ] &&
   ls "$awa_rec"/*.tar.gz >/dev/null 2>&1 &&
   python3 -c 'import json,glob,sys; m=json.load(open(glob.glob(sys.argv[1]+"/*.manifest.json")[0])); inc="/".join(m["included"]); sk="/".join(m["skipped_secrets"]); sys.exit(0 if "data.localdb" in inc and "config.env" in sk else 1)' "$awa_rec"; then
  pass "clean --bundle archives non-secret ignored files and skips secret-pattern files (X3/S1)"
else
  bad "clean --bundle did not bundle/skip correctly"
fi
git -C "$repo" branch -D "cursor/worktree/awa-ign-$$" >/dev/null 2>&1 || true

new_included_repo; repo="$REPO"
# Post-ASK_ON (2026-07-07): a mutating command on an included PRIMARY is an enforced hook `deny`
# (Cursor treats `ask` as non-blocking; only `deny` actually stops the command). The override still
# allows; an unparseable payload on an included-looking primary stays `ask` (honest no-op on genuine
# uncertainty — never a false deny).
if printf '{"cwd":"%s","command":"git add README.md"}' "$repo" | "$ROOT/_ops/cursor-hooks/worktree-guard.sh" | python3 -c "$json_permission" deny &&
   printf '{"cwd":"%s","command":"git add README.md"}' "$repo" | DEV_WORKTREE_GUARD_ALLOW_PRIMARY=1 "$ROOT/_ops/cursor-hooks/worktree-guard.sh" | python3 -c "$json_permission" allow &&
   (cd "$repo" && printf '{' | "$ROOT/_ops/cursor-hooks/worktree-guard.sh") | python3 -c "$json_permission" ask; then
  pass "worktree guard: shell mutation DENIES; override allows; bad payload asks (uncertainty)"
else
  bad "worktree guard shell deny/allow behavior failed"
fi

# X2: afterFileEdit is observation-only, so the guard must ALLOW (never emit a no-op `ask`) AND
# write an honest metadata-only detection receipt for a native edit to an included primary.
awa_state="$(mktemp -d)"; tmp_paths+=("$awa_state")
if printf '{"workspaceRoot":"%s","filePath":"README.md"}' "$repo" | XDG_STATE_HOME="$awa_state" "$ROOT/_ops/cursor-hooks/worktree-guard.sh" | python3 -c "$json_permission" allow &&
   [ -f "$awa_state/awa/detections/receipts.jsonl" ] &&
   AWA_REPO="$repo" python3 -c 'import json,os,sys; log=sys.argv[1]; repo=os.environ["AWA_REPO"]; sys.exit(0 if any((lambda d: d.get("kind")=="primary-file-edit-detected" and d.get("path","").startswith(repo))(json.loads(l)) for l in open(log) if l.strip()) else 1)' "$awa_state/awa/detections/receipts.jsonl"; then
  pass "worktree guard: afterFileEdit allows + writes detection receipt (X2, no no-op ask)"
else
  bad "worktree guard afterFileEdit detect-only behavior failed"
fi

else
  skip "AWA disposable kernel UATs — H3 setup gating, clean safe/unsafe/bundle, guard ask/allow, X2 detect (AWA not installed; verified in KleinPerkins/awa CI)"
fi  # AWA_INSTALLED (disposable UATs)

# Exact external-owner projection drift (missing/duplicate/stale/wrong fields/event/path) is covered
# by the E-06 hermetic lifecycle suite above. A bare three-role fixture is no longer valid.

echo "== AWA committed cloud project hooks (Phase 12) =="

# Cloud agents run ONLY committed project hooks (not the operator's user-level ~/.cursor/hooks.json).
# The committed .cursor/hooks.json + its two wrapper scripts give a cloud agent the AWA gate, and
# MUST degrade gracefully (never hard-block) when the AWA kernel guard is not present on the cloud
# VM — and project beforeShellExecution is failClosed:false so timeout cannot machine-brick.
CLOUD_HOOKS="$ROOT/.cursor/hooks.json"
CLOUD_GUARD="$ROOT/.cursor/hooks/awa-cloud-guard.sh"
CLOUD_SESSION="$ROOT/.cursor/hooks/awa-cloud-session.sh"

# (a) manifest present + valid JSON + correct failClosed semantics (beforeShellExecution false,
#     afterFileEdit unset/false, sessionStart false) pointing at the two wrapper basenames.
if [ -f "$CLOUD_HOOKS" ] && CLOUD_HOOKS="$CLOUD_HOOKS" python3 - <<'PY'
import json, os, sys
data = json.load(open(os.environ["CLOUD_HOOKS"]))
hooks = data.get("hooks", {}) if isinstance(data, dict) else {}
EXPECT = [
    ("beforeShellExecution", "awa-cloud-guard.sh", False),  # soft backstop: fail-open on hook failure
    ("afterFileEdit", "awa-cloud-guard.sh", None),          # observation-only: no failClosed
    ("sessionStart", "awa-cloud-session.sh", False),        # fire-and-forget context
]
def base(cmd):
    for tok in str(cmd).split():
        if tok.endswith(".sh"):
            return os.path.basename(tok)
    return ""
for event, want_base, want_fc in EXPECT:
    entries = [e for e in (hooks.get(event) or []) if isinstance(e, dict) and base(e.get("command", "")) == want_base]
    if not entries:
        print(f"missing {event} -> {want_base}", file=sys.stderr); sys.exit(1)
    fc = entries[0].get("failClosed", None)
    if want_fc is None:
        if fc is True:
            print(f"{event}: failClosed must be unset/false (observation-only)", file=sys.stderr); sys.exit(1)
    elif fc != want_fc:
        print(f"{event}: failClosed={fc!r} expected {want_fc!r}", file=sys.stderr); sys.exit(1)
sys.exit(0)
PY
then
  pass "committed .cursor/hooks.json present, valid JSON, correct failClosed (Phase 12)"
else
  bad "committed .cursor/hooks.json missing/invalid or wrong failClosed (Phase 12)"
fi

# (b) wrapper scripts present + executable.
for rel in .cursor/hooks/awa-cloud-guard.sh .cursor/hooks/awa-cloud-session.sh; do
  if [ -x "$ROOT/$rel" ]; then pass "$rel present + executable"; else bad "$rel missing/not executable"; fi
done

# (c) GRACEFUL DEGRADATION: with the AWA kernel guard UNREACHABLE (wrapper copied out of the repo
#     so its ../../_ops/... guard does not resolve), the cloud guard wrapper must ALLOW a mutating
#     command and exit 0 — never hard-block a cloud agent that has no AWA installed.
degrade_tmp="$(mktemp -d)"; tmp_paths+=("$degrade_tmp")
mkdir -p "$degrade_tmp/.cursor/hooks"
cp "$CLOUD_GUARD" "$CLOUD_SESSION" "$degrade_tmp/.cursor/hooks/" 2>/dev/null || true
if printf '{"cwd":"/tmp","command":"rm -rf /"}' | bash "$degrade_tmp/.cursor/hooks/awa-cloud-guard.sh" 2>/dev/null | python3 -c "$json_permission" allow; then
  pass "cloud guard wrapper degrades to ALLOW when the AWA guard is unreachable (no cloud brick)"
else
  bad "cloud guard wrapper did not degrade to allow with the guard unreachable"
fi

# (d) DELEGATION: at its real location the wrapper delegates to the kernel guard and returns a
#     valid permission JSON (allow/ask/deny).
if printf '{"cwd":"%s","command":"git status"}' "$degrade_tmp" | bash "$CLOUD_GUARD" 2>/dev/null \
   | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("permission") in ("allow","ask","deny") else 1)'; then
  pass "cloud guard wrapper delegates to the kernel guard (valid permission JSON)"
else
  bad "cloud guard wrapper did not return a valid permission JSON"
fi

# (e) session wrapper emits valid JSON when the session hook is unreachable (degraded {}).
if printf '{}' | bash "$degrade_tmp/.cursor/hooks/awa-cloud-session.sh" 2>/dev/null \
   | python3 -c 'import json,sys; json.load(sys.stdin); sys.exit(0)'; then
  pass "cloud session wrapper emits valid JSON when degraded"
else
  bad "cloud session wrapper did not emit valid JSON when degraded"
fi

echo "== AWA security UATs (Cluster D) =="

# The engine software + its security/architecture docs + redaction lib + hook-probe + the FROZEN
# kernel CONTRACT now live in the standalone KleinPerkins/awa repo (pinned by the global tools/awa
# shelf) and its INSTALLED runtime (~/.local/share/awa/current/contracts/). Dev keeps ONLY the
# operator-copy table, which the copy-honesty gate verifies against the installed kernel surface
# (genuinely dev-local: it pins what the D3 shims must satisfy). The contract freeze is delegated to
# the installed checker (see below).
for rel in _ops/awa/copy/operator-copy.json; do
  if [ -e "$ROOT/$rel" ]; then pass "$rel present"; else bad "$rel MISSING"; fi
done

# The remaining Cluster-D UATs drive the guard/clean through the delegators into the INSTALLED
# kernel; gate on AWA install (verified in KleinPerkins/awa CI when absent here).
if [ "$AWA_INSTALLED" = 1 ]; then

# Adversarial shell-gate (S6): the mutating classifier must catch the review-flagged bypasses
# (git -C . commit, sed -i, > redirection) on an included primary -> DENY (enforced; ASK_ON removed
# 2026-07-07 — Cursor honors only `deny`); read-only -> allow.
new_included_repo; repo="$REPO"
err="$(mktemp)"; tmp_paths+=("$err")
adv_ok=1
for c in "git -C . commit -m x" "sed -i s/a/b/ README.md" "echo pwned > README.md"; do
  if ! printf '{"cwd":"%s","command":"%s"}' "$repo" "$c" | "$ROOT/_ops/cursor-hooks/worktree-guard.sh" | python3 -c "$json_permission" deny; then
    adv_ok=0
  fi
done
if ! printf '{"cwd":"%s","command":"git status"}' "$repo" | "$ROOT/_ops/cursor-hooks/worktree-guard.sh" | python3 -c "$json_permission" allow; then
  adv_ok=0
fi
if [ "$adv_ok" = "1" ]; then
  pass "shell gate DENIES git -C/sed -i/> bypasses, allows read-only (S6 adversarial)"
else
  bad "shell gate failed an adversarial bypass assertion (S6)"
fi

# S2: a symlinked worktree path must be refused by clean (symlink-traversal guard).
new_included_repo; repo="$REPO"
git -C "$repo" worktree add -q -b "cursor/worktree/awa-s2-$$" "$repo.wt" main
ln -s "$repo.wt" "$repo.wtlink"; tmp_paths+=("$repo.wtlink")
if ! "$ROOT/_ops/bin/dev-worktree.sh" clean --path "$repo.wtlink" >/dev/null 2>"$err" &&
   grep -q 'symlinked worktree path' "$err"; then
  pass "clean refuses a symlinked worktree path (S2)"
else
  bad "clean did not refuse a symlinked worktree path (S2)"
fi
git -C "$repo" worktree remove --force "$repo.wt" 2>/dev/null || true
git -C "$repo" branch -D "cursor/worktree/awa-s2-$$" >/dev/null 2>&1 || true

# S2: an ignored symlink whose target escapes the worktree root must NOT be archived; a regular
# ignored file inside the worktree still is.
new_included_repo; repo="$REPO"
printf '*.dat\n' > "$repo/.gitignore"
git -C "$repo" add .gitignore
git -C "$repo" -c user.email="49759187+KleinPerkins@users.noreply.github.com" -c user.name="KleinPerkins" commit -qm gitignore
git -C "$repo" worktree add -q -b "cursor/worktree/awa-s2b-$$" "$repo.wt" main
outside="$(mktemp -d)"; tmp_paths+=("$outside")
printf 'SECRETOUT\n' > "$outside/leak.dat"
ln -s "$outside/leak.dat" "$repo.wt/escape.dat"
printf 'INSIDE\n' > "$repo.wt/inside.dat"
awa_rec2="$(mktemp -d)"; tmp_paths+=("$awa_rec2")
if AWA_RECOVERY_DIR="$awa_rec2" "$ROOT/_ops/bin/dev-worktree.sh" clean --path "$repo.wt" --bundle >/dev/null 2>"$err" &&
   python3 -c 'import json,glob,sys; m=json.load(open(glob.glob(sys.argv[1]+"/*.manifest.json")[0])); esc="/".join(m.get("skipped_symlink_escape",[])); inc="/".join(m["included"]); sys.exit(0 if "escape.dat" in esc and "inside.dat" in inc else 1)' "$awa_rec2"; then
  pass "bundle drops a symlink escaping the worktree root, keeps inside files (S2)"
else
  bad "bundle did not drop an escaping symlink (S2)"
fi
git -C "$repo" branch -D "cursor/worktree/awa-s2b-$$" >/dev/null 2>&1 || true

# S1: seeded .env / *.key are refused from the archive (recorded as skipped_secrets); a non-secret
# ignored file is archived.
new_included_repo; repo="$REPO"
printf '*.key\n*.env\n*.txt\n' > "$repo/.gitignore"
git -C "$repo" add .gitignore
git -C "$repo" -c user.email="49759187+KleinPerkins@users.noreply.github.com" -c user.name="KleinPerkins" commit -qm gitignore
git -C "$repo" worktree add -q -b "cursor/worktree/awa-s1-$$" "$repo.wt" main
printf 'PRIVATE\n' > "$repo.wt/secret.key"
printf 'A=1\n' > "$repo.wt/app.env"
printf 'notes\n' > "$repo.wt/notes.txt"
awa_rec3="$(mktemp -d)"; tmp_paths+=("$awa_rec3")
if AWA_RECOVERY_DIR="$awa_rec3" "$ROOT/_ops/bin/dev-worktree.sh" clean --path "$repo.wt" --bundle >/dev/null 2>"$err" &&
   python3 -c 'import json,glob,sys; m=json.load(open(glob.glob(sys.argv[1]+"/*.manifest.json")[0])); sk="/".join(m["skipped_secrets"]); inc="/".join(m["included"]); sys.exit(0 if "secret.key" in sk and "app.env" in sk and "notes.txt" in inc else 1)' "$awa_rec3"; then
  pass "clean --bundle refuses seeded .env/*.key from the archive, keeps non-secret (S1)"
else
  bad "clean --bundle did not refuse seeded secrets (S1)"
fi
git -C "$repo" branch -D "cursor/worktree/awa-s1-$$" >/dev/null 2>&1 || true

# S5 (redaction scaffold): the redact pass moved to the standalone KleinPerkins/awa engine
# (engine/redact.py) and is covered by that repo's suite (test_redact + test_state_lock event
# redaction). Dev no longer ships redact.py, so the S5 UAT lives with the engine now.

new_included_repo; repo="$REPO"
git -C "$repo" branch "cursor/worktree/awa-orphan-$$" main
if "$ROOT/_ops/bin/dev-worktree.sh" dashboard-data --root "$repo" 2>/dev/null \
   | AWA_BRANCH="cursor/worktree/awa-orphan-$$" python3 -c 'import json,sys,os; d=json.load(sys.stdin); name=os.environ["AWA_BRANCH"]; sys.exit(0 if any(b.get("branch")==name for r in d.get("repos",[]) for b in r.get("orphan_branches",[])) else 1)'; then
  pass "dashboard-data surfaces orphan AWA branches"
else
  bad "dashboard-data did not surface orphan AWA branches"
fi
git -C "$repo" branch -D "cursor/worktree/awa-orphan-$$" >/dev/null 2>&1 || true

new_included_repo; repo="$REPO"
git -C "$repo" worktree add -q -b "cursor/worktree/awa-common-$$" "$repo.wt" main
mkdir -p "$repo/.git/hooks"
printf '# managed-by: KleinPerkins/dev identity-guard\n' > "$repo/.git/hooks/pre-commit"
common_dir="$(git -C "$repo.wt" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
# Compare by inode (-ef), not string equality: git canonicalizes the common dir (on macOS the
# temp root /var/folders resolves to /private/var/folders), so a raw string compare against the
# constructed "$repo/.git" spuriously differs under a symlinked root (e.g. the clean-room tmp).
if [ -n "$common_dir" ] && [ "$common_dir" -ef "$repo/.git" ] && grep -q 'managed-by: KleinPerkins/dev identity-guard' "$common_dir/hooks/pre-commit"; then
  pass "linked worktree hook visibility uses common dir"
else
  bad "linked worktree hook visibility common-dir check failed"
fi
git -C "$repo" worktree remove --force "$repo.wt" 2>/dev/null || true
git -C "$repo" branch -D "cursor/worktree/awa-common-$$" >/dev/null 2>&1 || true

else
  skip "AWA Cluster-D kernel UATs — S6 adversarial gate, S2 symlink guard, S1 secret-skip, orphan surfacing, common-dir hooks (AWA not installed; verified in KleinPerkins/awa CI)"
fi  # AWA_INSTALLED (security/Cluster-D UATs)

# H5 (hook-probe harness): the empirical hook-probe harness moved to the standalone
# KleinPerkins/awa engine (hook-probe/), where its self-check runs. Dev no longer ships it.

# Phase-0 contract freeze: the kernel surfaces (CLI, awa-worktree/v1 JSON, guard permission
# schema, .awa/lease.json shape) are pinned so the later engine can only BACK them. This
# sub-check FAILS on a breaking drift (removal/rename), which would require a versioned bump.
echo "== AWA kernel contract freeze =="
if [ -x "$ROOT/_ops/checks/awa-contract-freeze.sh" ]; then
  # The checker creates its own governed fixtures; do not override those roots.
  cf_out="$(env -u AWA_GOVERNED_ROOT -u AWA_VERIFY_BASE "$ROOT/_ops/checks/awa-contract-freeze.sh" 2>&1)"; cf_rc=$?
  printf '%s\n' "$cf_out" | grep -E '^  (PASS|FAIL)  ' || true
  if [ "$cf_rc" -ne 0 ]; then
    bad "awa-contract-freeze reported drift (see above)"
  fi
else
  bad "awa-contract-freeze.sh missing or not executable"
fi

# AWA engine smoke: the engine software now lives in the standalone KleinPerkins/awa repo
# (pinned by the global tools/awa shelf); its full suite runs in THAT repo's CI. Here we only
# run a thin dev-side smoke against the INSTALLED release (doctor + daemon-status probe). It
# SKIPS cleanly (exit 0) when no release is installed — dev's gates must not depend on an
# in-tree engine copy, and the kernel guarantee holds engine-off.
echo "== AWA engine smoke (installed release) =="
if [ "$source_only" = 1 ]; then
  skip "installed engine smoke intentionally withheld in source-only mode (host qualification required)"
elif [ -x "$ROOT/_ops/checks/awa-engine-smoke.sh" ]; then
  sm_out="$("$ROOT/_ops/checks/awa-engine-smoke.sh" 2>&1)"; sm_rc=$?
  printf '%s\n' "$sm_out" | grep -E '^  (PASS|FAIL|SKIP)  ' || true
  if [ "$sm_rc" -ne 0 ]; then
    bad "awa-engine-smoke reported a failure (see above)"
  fi
else
  bad "awa-engine-smoke.sh missing or not executable"
fi

# Copy-honesty gate: no operator-facing string may promise a protection verb ahead of the
# capability that backs it (plan §H1). This sub-check FAILS if a gated verb ships without its
# named verifier being green.
echo "== AWA kernel guarantee (Phase 5 env matrix) =="
if [ -x "$ROOT/_ops/checks/kernel-guarantee-verify.sh" ]; then
  kg_out="$("$ROOT/_ops/checks/kernel-guarantee-verify.sh" 2>&1)"; kg_rc=$?
  printf '%s\n' "$kg_out" | grep -E '^  (PASS|FAIL)  ' || true
  if [ "$kg_rc" -ne 0 ]; then
    bad "kernel-guarantee-verify reported a failure (see above)"
  fi
else
  bad "kernel-guarantee-verify.sh missing or not executable"
fi

echo "== AWA copy-honesty gate =="
if [ -x "$ROOT/_ops/checks/copy-honesty-check.sh" ]; then
  ch_out="$("$ROOT/_ops/checks/copy-honesty-check.sh" 2>&1)"; ch_rc=$?
  printf '%s\n' "$ch_out" | grep -E '^  (PASS|FAIL)  ' || true
  if [ "$ch_rc" -ne 0 ]; then
    bad "copy-honesty-check reported a dishonest protection promise (see above)"
  fi
else
  bad "copy-honesty-check.sh missing or not executable"
fi

if [ "$fail" -eq 0 ]; then
  echo "worktree-verify: OK"
else
  echo "worktree-verify: FAILED"
fi
exit "$fail"
