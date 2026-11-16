#!/usr/bin/env bash
# install-dev-awa-overlay.sh — the ~/dev HOST OVERLAY installer for AWA (thin).
#
# AWA is a Standalone System Package (SSP) that lives in KleinPerkins/awa and installs itself into
# your XDG dirs (~/.local/share/awa/current) from a pinned clone, bound by the global
# `tools/awa` Global Capability Binding (GCB) shelf. `~/dev` is a THIN HOST OVERLAY: it supplies
# only the org/host POLICY LITERALS and a set of thin delegators at the historical `_ops/` paths
# (the always-applied worktree rules reference `_ops/bin/dev-worktree.sh`). It carries NO kernel or
# engine bytes.
#
# This installer:
#   (a) selects AWA's external hook-owner mode and installs through the merged Skills GCB. In that
#       mode the SSP never accesses the selected hook file; this overlay owns its complete matrix.
#   (b) ensures the ~/dev HOST POLICY OVERLAY exists at _ops/policy/worktree-policy.yml (the org/host
#       literals: governed-root globs, include/exclude, cpp exclusion) — the ONLY place the installed
#       generic kernel reads host specifics from, resolved by role via AWA_POLICY.
#   (c) wires ~/.cursor/hooks.json to the ~/dev delegators (idempotent, backup-before-write, dedups
#       any stale installed-path AWA hook entries) so the guard/session hooks run the installed
#       kernel with the ~/dev host policy.
#   (d) points the ~/dev dashboard at the installed AWA emitter (awa-dashboard-data.py delegates).
#
# Verbs:
#   install (default)   install exact AWA v1.8.2, stage local job disabled, wire v2 hooks
#   --repair            force shelf repair, then repair the disabled job and hook projection
#   --preview           source-only read/dry-run plan; never mutates host state
#   --doctor            full runtime, hook, local-jobs, and optional Slack configuration health
#   --check             CI-safe STATIC preflight (policy valid + delegators present + shelf --check);
#                       does NOT require the runtime to be installed (green on a fresh/CI checkout)
#   --deactivate        rollback host triggers first; restore captured hooks; remove owned job
#   --rollback-preview  print the ordered rollback without changing host state
#
# Idempotent. Honors HOME / XDG_* overrides (clean-room runs it in an isolated HOME). Offline-safe:
# ECO_BOOTSTRAP_OFFLINE=1 defers when no runtime exists, but may reconcile a complete local external
# runtime without network. It never wires hooks without validated runtime and owner state.
set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # _ops/bin
ROOT="$(cd "$SELF_DIR/../.." && pwd)"                           # repo root (~/dev)
SKILLS_ROOT="${DEV_AWA_SKILLS_ROOT:-$ROOT/capabilities/skills}"
SHELF_DIR="$SKILLS_ROOT/global/tools/awa"
SHELF="$SHELF_DIR/install.sh"
POLICY="$ROOT/_ops/policy/worktree-policy.yml"
MODES="$ROOT/_ops/policy/worktree-modes.yml"
HOOK_INSTALLER="$ROOT/_ops/bin/install-worktree-hooks.sh"
JOB_INSTALLER="${DEV_AWA_JOB_INSTALLER:-$ROOT/_ops/bin/install-awa-integrity-job.sh}"
BINDING_CHECKER="${DEV_AWA_BINDING_CHECKER:-$ROOT/_ops/bin/check-awa-release-binding.py}"
DASHBOARD_INSTALLER="$ROOT/_ops/bin/install-awa-dashboard.sh"
RUNTIME="${AWA_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/awa/current}"

log()  { printf '[dev-awa-overlay] %s\n' "$*"; }
warn() { printf '[dev-awa-overlay] WARN %s\n' "$*" >&2; }
die()  { printf '[dev-awa-overlay] ERROR %s\n' "$*" >&2; exit 1; }

# Host policy is canonical tracked data, never reconstructed by the installer.
# Missing protection must fail closed rather than seed an obsolete weaker template.
write_policy() {
  [ -f "$POLICY" ] || die "canonical host policy missing; restore the reviewed tracked policy before installation"
}

# (b2) Host per-repo MODE file overlay. Source-tracked, tool-owned (schema awa-modes/v1). Seed it
# with the host default (default_mode: on) ONLY if a fresh/CI checkout is missing it. NEVER rewrite
# a present tracked file (non-destructive: preserves operator entries + a changed default_mode).
# Values are on|off only (ASK_ON removed 2026-07-07); ON = an included-primary mutation denies.
write_modes() {
  if [ -f "$MODES" ]; then return 0; fi
  warn "host modes file missing — seeding the tool-owned default (default_mode: on) at $MODES"
  mkdir -p "$(dirname "$MODES")"
  # This heredoc MUST match the canonical form the engine's `_serialize` emits byte-for-byte,
  # so the subsequent `sync_modes` (and any later install) is a byte-stable no-op and the
  # source-tracked file never goes dirty. Keep it in sync with engine/modes.py `_HEADER`.
  cat > "$MODES" <<'YAML'
# AWA per-repo MODE file — TOOL-OWNED, source-tracked (schema awa-modes/v1).
# DO NOT HAND-EDIT: materialized/reconciled by install/bootstrap and edited only via
# `dev-worktree.sh mode ...` (or the AWA MCP mode tools).
# default_mode governs eligible repos with no explicit entry; modes is a tool-managed map.
schema: awa-modes/v1
default_mode: on
modes: {}
YAML
}

# (b3) Reconcile the modes file via the INSTALLED engine using `mode repair` — the MIGRATION verb.
# repair is idempotent + non-destructive (a canonical file is a byte-stable no-op; operator entries
# are preserved) and, crucially, UNCONDITIONALLY normalizes a legacy/invalid default_mode (e.g. a
# pre-refactor `ask_on`) forward to `on` and coerces any non-`off` per-repo value to `on`. `mode sync
# --default-mode <x>` is NOT usable for migration post-ASK_ON-removal: a legacy `--default-mode ask_on`
# now RAISES (2-value set) and would be swallowed, so a stale default would never migrate. Degrades to
# allow when AWA is not installed (kernel guarantee holds engine-off) — write_modes already guaranteed
# the file exists, so repair has a target.
sync_modes() {
  local engine_sh="$RUNTIME/bin/awa-engine.sh"
  [ -x "$engine_sh" ] || { log "AWA engine absent — skipping modes repair (seeded modes file stands)"; return 0; }
  if "$engine_sh" mode repair --policy "$POLICY" >/dev/null 2>&1; then
    log "modes file reconciled/migrated via installed engine (mode repair; legacy default -> on)"
  else
    warn "engine mode repair reported an issue (non-fatal; seeded modes file stands)"
  fi
}

# Read-only summary of the host modes file: "default_mode=<v> entries=<n>". Prefers the installed
# engine for an authoritative read; falls back to a dependency-free scan so it works engine-off.
modes_summary() {
  [ -f "$MODES" ] || { echo "absent"; return 1; }
  local engine_sh="$RUNTIME/bin/awa-engine.sh"
  if [ -x "$engine_sh" ] && "$engine_sh" mode list --modes-file "$MODES" 2>/dev/null \
       | python3 -c 'import json,sys; d=json.load(sys.stdin); print("default_mode=%s entries=%d" % (d.get("default_mode") or "?", len(d.get("modes") or {})))' 2>/dev/null; then
    return 0
  fi
  python3 - "$MODES" <<'PY'
import sys
dm, n, in_modes = "?", 0, False
for raw in open(sys.argv[1], encoding="utf-8"):
    line = raw.rstrip("\n"); s = line.strip()
    if not s or s.startswith("#"):
        continue
    if s.startswith("default_mode:"):
        dm = s.split(":", 1)[1].strip() or "?"; continue
    if s.startswith("modes:"):
        rest = s.split(":", 1)[1].strip(); in_modes = True
        if rest and rest != "{}":
            n += rest.strip("{}").count(":")
        continue
    if in_modes and (line.startswith("  ") or line.startswith("\t")) and ":" in s:
        n += 1
print("default_mode=%s entries=%d" % (dm, n))
PY
}

# Validate the host modes file is present + parses as awa-modes/v1 (engine parse when available).
check_modes() {
  [ -f "$MODES" ] || { warn "host modes file absent: $MODES"; return 1; }
  if [ -x "$RUNTIME/kernel/bin/dev-worktree.sh" ] && [ -x "$RUNTIME/bin/awa-engine.sh" ]; then
    "$RUNTIME/bin/awa-engine.sh" mode list --modes-file "$MODES" >/dev/null 2>&1 \
      || { warn "installed engine could not parse modes file $MODES"; return 1; }
  fi
  return 0
}

# Validate the host policy overlay parses + carries the cpp exclusion (a canary for the org literals).
check_policy() {
  [ -f "$POLICY" ] || { warn "host policy overlay absent: $POLICY"; return 1; }
  grep -q 'card-platform-product' "$POLICY" || { warn "host policy overlay missing the cpp exclusion"; return 1; }
  if [ -x "$RUNTIME/kernel/lib/awa_policy.py" ]; then
    python3 "$RUNTIME/kernel/lib/awa_policy.py" dump --policy "$POLICY" >/dev/null 2>&1 \
      || { warn "installed policy resolver could not parse $POLICY"; return 1; }
  fi
  return 0
}

# (a) Ensure AWA is installed via the GCB shelf with the contract's explicit external owner. The
# standalone installer exits before resolving the selected hook destination in this mode, so no
# throwaway hook path or parallel ownership mechanism is needed.
ensure_awa() {
  local verb="$1"   # "" (install) | --repair
  [ -f "$SHELF" ] || { warn "GCB shelf absent: $SHELF (Skills source not checked out)"; return 1; }
  DEV_AWA_GCB_DIR="$SHELF_DIR" DEV_AWA_REQUIRE_GCB=1 \
    "$BINDING_CHECKER" --static >/dev/null 2>&1 || {
      warn "GCB shelf is not the exact merged AWA v1.8.2 descriptor"
      return 1
    }
  if ! bash "$SHELF" --check >/dev/null 2>&1; then
    warn "GCB static preflight failed"
    return 1
  fi
  if [ "${ECO_BOOTSTRAP_OFFLINE:-0}" = "1" ]; then
    if [ ! -x "$RUNTIME/kernel/bin/dev-worktree.sh" ]; then
      log "(offline) GCB is install-ready; deferring runtime and hook reconciliation without mutation"
      return 3
    fi
    if [ "$verb" = "--repair" ]; then
      log "(offline) repairing AWA from the existing local GCB checkout"
      if ! AWA_HOOK_OWNER=external AWA_POLICY="$POLICY" AWA_GOVERNED_ROOT="$ROOT" \
          bash "$SHELF" --repair; then
        warn "offline GCB/SSP repair failed before hook wiring"
        return 1
      fi
    fi
    # A normal offline install is validation-only: doctor requires persisted external selection
    # and pointer identity. Direct/ambiguous owner state fails without touching hooks; the explicit
    # --repair verb above is the only offline owner-migration authority.
    log "(offline) validating the existing local AWA runtime in external-owner mode"
    if ! AWA_HOOK_OWNER=external bash "$SHELF" --doctor >/dev/null 2>&1; then
      warn "existing local AWA runtime failed external-owner doctor"
      return 1
    fi
    return 0
  fi
  log "installing/repairing AWA via the GCB shelf (hook owner: external)"
  if ! AWA_HOOK_OWNER=external AWA_POLICY="$POLICY" AWA_GOVERNED_ROOT="$ROOT" \
      bash "$SHELF" "$verb"; then
    warn "GCB/SSP install failed; host hook transaction was not started"
    return 1
  fi
  # The standalone contract UAT intentionally runs under AWA's generic default policy. Passing the
  # host policy into doctor would classify its scratch repos as standalone/advisory and create a
  # false contract failure; persisted owner/pointer state still proves external selection.
  if ! AWA_HOOK_OWNER=external bash "$SHELF" --doctor >/dev/null 2>&1; then
    warn "GCB/SSP external-owner doctor failed; host hook transaction was not started"
    return 1
  fi
  return 0
}

check_release_binding() {
  [ -x "$BINDING_CHECKER" ] || {
    warn "AWA release binding checker is missing"
    return 1
  }
  DEV_AWA_GCB_DIR="$SHELF_DIR" "$BINDING_CHECKER" --runtime >/dev/null
}

# (c) Wire ~/.cursor/hooks.json to the ~/dev delegators (install-worktree-hooks.sh is idempotent,
# backs up before write, and dedups stale installed-path AWA entries).
wire_hooks() {
  [ -x "$HOOK_INSTALLER" ] || { warn "hook installer absent: $HOOK_INSTALLER"; return 1; }
  AWA_GCB_META="$SHELF_DIR/meta.yml" bash "$HOOK_INSTALLER"
}

stage_integrity_job() {
  local verb="${1:-}"
  [ -x "$JOB_INSTALLER" ] || {
    warn "AWA integrity job installer is missing"
    return 1
  }
  if [ "$verb" = "--repair" ]; then
    "$JOB_INSTALLER" --repair
  else
    "$JOB_INSTALLER" --stage
  fi
}

# (d) The ~/dev dashboard reads live data from the installed AWA emitter via awa-dashboard-data.py
# (a thin delegator). Here we only assert the tracked seed stays data-free (a real refresh is an
# explicit `make worktree-dashboard`). Non-fatal.
point_dashboard() {
  [ -x "$DASHBOARD_INSTALLER" ] || return 0
  if bash "$DASHBOARD_INSTALLER" --check >/dev/null 2>&1; then
    log "dashboard seed data-free; awa-dashboard-data.py delegates to the installed AWA emitter"
  else
    warn "dashboard seed check reported an issue (run: $DASHBOARD_INSTALLER --seed)"
  fi
  return 0
}

do_install() {
  local verb="$1"
  local ensure_rc=0
  write_policy  # Refuse before runtime, modes, hook or job mutations.
  if [ "${ECO_BOOTSTRAP_OFFLINE:-0}" = "1" ]; then
    ensure_awa "$verb" || ensure_rc=$?
    if [ "$ensure_rc" -eq 3 ]; then
      check_policy || die "host policy overlay validation failed"
      check_modes || die "host modes file validation failed"
      log "overlay install deferred: offline mode made no runtime or hook-file change"
      return 0
    fi
    [ "$ensure_rc" -eq 0 ] || die "offline external-owner validation failed before hook wiring"
    check_release_binding || die "exact AWA v1.8.2 binding failed before host trigger wiring"
    write_modes
    check_policy || die "host policy overlay validation failed before hook wiring"
    sync_modes
    check_modes || die "host modes file validation failed before hook wiring"
    point_dashboard
    stage_integrity_job "$verb" || die "disabled local-jobs schedule staging failed before hook wiring"
    wire_hooks || die "complete seven-role hook reconciliation failed"
    log "(offline) existing external-owner runtime reconciled locally; no network acquisition ran"
    return 0
  fi
  ensure_awa "$verb" || ensure_rc=$?
  [ "$ensure_rc" -eq 0 ] || die "AWA external-owner install/validation failed before hook wiring"
  check_release_binding || die "exact AWA v1.8.2 binding failed before host trigger wiring"
  write_modes                      # seed the tool-owned modes file if a fresh checkout lacks it
  point_dashboard
  sync_modes                       # reconcile modes via the installed engine (degrade-to-allow)
  check_policy || die "host policy overlay validation failed"
  check_modes || die "host modes file validation failed"
  stage_integrity_job "$verb" || die "disabled local-jobs schedule staging failed before hook wiring"
  wire_hooks || die "complete seven-role hook reconciliation failed"
  log "AWA v1.8.2 installed in external-owner mode; Dev owns the seven-role hook matrix."
  log "Integrity schedule is registered but disabled pending explicit operator GO."
  log "overlay install complete."
}

slack_status() {
  AWA_RUNTIME="$RUNTIME" python3 - <<'PY'
import importlib
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

runtime = Path(os.environ["AWA_RUNTIME"])
try:
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(runtime))
    module = importlib.import_module("engine.integrity_slack")
    config = module.config_path()
    service = module.KEYCHAIN_SERVICE
    account = module.KEYCHAIN_ACCOUNT
    not_found_exit = module.KEYCHAIN_NOT_FOUND_EXIT
except Exception:
    print("  FAIL  Slack alerts: failed to load released adapter")
    raise SystemExit(1)

configured_user = None
if os.path.lexists(config):
    try:
        info = config.lstat()
        if (
            config.is_symlink()
            or not stat.S_ISREG(info.st_mode)
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid()
        ):
            raise ValueError
        configured_user = module.load_configured_user_id()
        if configured_user is None:
            raise ValueError
    except Exception:
        print("  FAIL  Slack alerts: misconfigured private user configuration")
        raise SystemExit(1)

security = os.environ.get("DEV_AWA_SECURITY_BIN") or shutil.which("security")
if not security:
    print("  FAIL  Slack alerts: failed to inspect credential state")
    raise SystemExit(1)
try:
    probe = subprocess.run(
        [security, "find-generic-password", "-a", account, "-s", service],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=3,
        check=False,
    )
except (OSError, subprocess.TimeoutExpired):
    print("  FAIL  Slack alerts: failed to inspect credential state")
    raise SystemExit(1)

credential_present = probe.returncode == 0
credential_absent = probe.returncode == not_found_exit
if not credential_present and not credential_absent:
    print("  FAIL  Slack alerts: failed to inspect credential state")
    raise SystemExit(1)
if configured_user is None and not credential_present:
    print("  PASS  Slack alerts: opted out (default)")
    raise SystemExit(0)
if configured_user is not None and credential_present:
    print("  PASS  Slack alerts: configured")
    raise SystemExit(0)
print("  FAIL  Slack alerts: misconfigured (private user configuration and credential disagree)")
raise SystemExit(1)
PY
}

do_doctor() {
  local rc=0
  echo "== dev AWA overlay doctor =="
  echo "   runtime=$RUNTIME  policy=$POLICY"
  if check_policy; then echo "  PASS  host policy overlay present + valid (cpp excluded)"; else echo "  FAIL  host policy overlay invalid/missing"; rc=1; fi
  if check_modes; then echo "  PASS  host modes file present + valid ($(modes_summary))"; else echo "  FAIL  host modes file invalid/missing"; rc=1; fi
  if [ -x "$ROOT/_ops/bin/dev-worktree.sh" ]; then
    echo "  PASS  delegator _ops/bin/dev-worktree.sh present"
  else
    echo "  FAIL  delegator _ops/bin/dev-worktree.sh missing"
    rc=1
  fi
  for d in worktree-guard.sh worktree-session.sh worktree-guard-with-integrity.sh awa-integrity-observer.sh awa-session-handoff.sh; do
    if [ -x "$ROOT/_ops/cursor-hooks/$d" ]; then
      echo "  PASS  delegator _ops/cursor-hooks/$d present"
    else
      echo "  FAIL  delegator _ops/cursor-hooks/$d missing"
      rc=1
    fi
  done
  if [ -x "$RUNTIME/kernel/bin/dev-worktree.sh" ]; then
    echo "  PASS  installed AWA runtime present"
    if [ -f "$SHELF" ] && AWA_HOOK_OWNER=external \
         bash "$SHELF" --doctor >/dev/null 2>&1; then
      echo "  PASS  awa external-owner doctor all-PASS (via the GCB shelf)"
    else
      echo "  FAIL  awa external-owner doctor reported problems"; rc=1
    fi
    if check_release_binding; then
      echo "  PASS  exact AWA v1.8.2 GCB/runtime binding"
    else
      echo "  FAIL  AWA GCB/runtime binding is stale or mismatched"; rc=1
    fi
    if AWA_GCB_META="$SHELF_DIR/meta.yml" bash "$HOOK_INSTALLER" --check >/dev/null 2>&1; then
      echo "  PASS  host hook file has the exact seven-role matrix + rollback preimage"
    else
      echo "  FAIL  host hook matrix or rollback preimage is missing/stale/unsafe"; rc=1
    fi
    # The dev CLI delegator must classify with the host policy: cpp stays excluded.
    if AWA_POLICY="$POLICY" AWA_GOVERNED_ROOT="$ROOT" python3 "$RUNTIME/kernel/lib/awa_policy.py" \
         classify --policy "$POLICY" --governed-root "$ROOT" \
         --toplevel "$ROOT/affirm/src/card-platform-product" 2>/dev/null | grep -q '^exclude'; then
      echo "  PASS  host policy excludes cpp (card-platform-product)"
    else
      echo "  FAIL  host policy did not exclude cpp"; rc=1
    fi
  else
    echo "  FAIL  installed AWA runtime absent ($RUNTIME) — run in an isolated HOME or request machine GO before repair"
    rc=1
  fi
  if [ -x "$JOB_INSTALLER" ] && "$JOB_INSTALLER" --doctor >/dev/null 2>&1; then
    echo "  PASS  AWA integrity schedule is owned by local-jobs"
  else
    echo "  FAIL  AWA integrity local-jobs registration is absent or drifted"; rc=1
  fi
  slack_status || rc=1
  if [ "$rc" -eq 0 ]; then echo "dev-awa-overlay doctor: OK"; else echo "dev-awa-overlay doctor: FAILED"; fi
  return "$rc"
}

# CI-safe static preflight: no runtime required. Green on a fresh/CI checkout.
do_check() {
  local rc=0
  echo "== dev AWA overlay --check (static, no runtime required) =="
  if check_policy; then echo "  PASS  host policy overlay present + valid"; else echo "  FAIL  host policy overlay invalid/missing"; rc=1; fi
  if check_modes; then echo "  PASS  host modes file present + valid ($(modes_summary))"; else echo "  FAIL  host modes file invalid/missing"; rc=1; fi
  for rel in \
    _ops/bin/dev-worktree.sh \
    _ops/bin/check-awa-release-binding.py \
    _ops/bin/install-awa-integrity-job.sh \
    _ops/local-jobs/awa-integrity.sh \
    _ops/cursor-hooks/worktree-guard.sh \
    _ops/cursor-hooks/worktree-session.sh \
    _ops/cursor-hooks/worktree-guard-with-integrity.sh \
    _ops/cursor-hooks/awa-integrity-observer.sh \
    _ops/cursor-hooks/awa-session-handoff.sh \
    _ops/checks/awa-contract-freeze.sh
  do
    if [ -x "$ROOT/$rel" ]; then echo "  PASS  delegator $rel present + executable"; else echo "  FAIL  delegator $rel missing/not executable"; rc=1; fi
  done
  # Each delegator must be THIN (resolve the installed AWA), not a forked kernel copy.
  if grep -q 'DELEGATOR' "$ROOT/_ops/bin/dev-worktree.sh"; then echo "  PASS  dev-worktree.sh is a thin delegator"; else echo "  FAIL  dev-worktree.sh is not a thin delegator"; rc=1; fi
  if [ -f "$SHELF" ]; then
    if DEV_AWA_GCB_DIR="$SHELF_DIR" DEV_AWA_REQUIRE_GCB=1 \
         "$BINDING_CHECKER" --static >/dev/null 2>&1 \
         && bash "$SHELF" --check >/dev/null 2>&1; then
      echo "  PASS  exact GCB shelf install-ready (--check)"
    else
      echo "  SKIP  local Skills checkout is behind the merged exact descriptor"
    fi
  else
    echo "  SKIP  GCB shelf absent (skills sibling not checked out)"
  fi
  if DEV_AWA_GCB_DIR="$SHELF_DIR" "$BINDING_CHECKER" --static >/dev/null 2>&1; then
    echo "  PASS  exact AWA v1.8.2 source contracts and binding expectations"
  else
    echo "  FAIL  AWA v1.8.2 source binding drifted"; rc=1
  fi
  if "$JOB_INSTALLER" --check >/dev/null 2>&1; then
    echo "  PASS  AWA integrity local-jobs source contract"
  else
    echo "  FAIL  AWA integrity local-jobs source contract drifted"; rc=1
  fi
  if AWA_GCB_META="$SHELF_DIR/meta.yml" bash "$HOOK_INSTALLER" --source-check >/dev/null 2>&1; then
    echo "  PASS  seven-role host hook projection source contract"
  else
    echo "  FAIL  seven-role host hook projection source contract drifted"; rc=1
  fi
  if [ "$rc" -eq 0 ]; then echo "dev-awa-overlay --check: OK"; else echo "dev-awa-overlay --check: FAILED"; fi
  return "$rc"
}

do_preview() {
  local rc=0
  echo "== dev AWA M1 source-only preview =="
  check_policy || rc=1
  check_modes || rc=1
  if [ -f "$SHELF" ] \
      && DEV_AWA_GCB_DIR="$SHELF_DIR" DEV_AWA_REQUIRE_GCB=1 \
         "$BINDING_CHECKER" --static >/dev/null 2>&1 \
      && bash "$SHELF" --check >/dev/null 2>&1; then
    echo "  PASS  exact GCB shelf is install-ready"
  elif [ -f "$SHELF" ]; then
    echo "  SKIP  local Skills checkout is behind the merged exact descriptor"
  else
    echo "  SKIP  Skills checkout is absent; merged descriptor is prerequisite"
  fi
  DEV_AWA_PREVIEW_STATIC=1 "$JOB_INSTALLER" --preview || rc=1
  AWA_GCB_META="$SHELF_DIR/meta.yml" "$HOOK_INSTALLER" --source-check || rc=1
  echo "  PLAN  install exact AWA v1.8.2 through the GCB"
  echo "  PLAN  register the local-jobs schedule disabled"
  echo "  PLAN  reconcile the seven-role external hook projection last"
  echo "  HOLD  activation requires explicit operator GO"
  [ "$rc" -eq 0 ] || return "$rc"
  log "source-only preview complete; host state was not changed"
}

drain_integrity_workers() {
  AWA_RUNTIME="$RUNTIME" python3 - <<'PY'
import os
import shlex
import signal
import subprocess
import time
from pathlib import Path

runtime = Path(os.environ["AWA_RUNTIME"]).resolve()
ps_binary = "/bin/ps"
if (
    os.environ.get("AWA_ENGINE_TEST_ACTIVE") == "1"
    and os.environ.get("DEV_AWA_TEST_PS_BIN")
):
    ps_binary = os.environ["DEV_AWA_TEST_PS_BIN"]
targets = {
    str(runtime / "kernel" / "bin" / "awa-integrity-sweep.sh"),
    str(runtime / "engine" / "integrity_detach.py"),
    str(runtime / "bin" / "awa-engine.sh"),
}
try:
    wait_seconds = min(30.0, max(0.0, float(
        os.environ.get("DEV_AWA_WORKER_WAIT_SECONDS", "5")
    )))
    term_seconds = min(10.0, max(0.0, float(
        os.environ.get("DEV_AWA_WORKER_TERM_SECONDS", "2")
    )))
except ValueError:
    raise SystemExit("invalid integrity worker drain timeout")


def processes():
    result = subprocess.run(
        [ps_binary, "-axo", "pid=,ppid=,command="],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3,
        check=True,
    )
    observed = {}
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) != 3:
            continue
        try:
            pid, ppid = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        observed[pid] = (ppid, fields[2])
    return observed


def roots(observed):
    matched = set()
    for pid, (_, command) in observed.items():
        try:
            argv = shlex.split(command)
        except ValueError:
            continue
        if not any(token in targets for token in argv):
            continue
        if str(runtime / "bin" / "awa-engine.sh") in argv:
            joined = " ".join(argv)
            if "integrity verify" not in joined:
                continue
        matched.add(pid)
    return matched


def tree(observed, root_pids):
    selected = set(root_pids)
    changed = True
    while changed:
        changed = False
        for pid, (ppid, _) in observed.items():
            if ppid in selected and pid not in selected:
                selected.add(pid)
                changed = True
    return selected


def live_targets():
    observed = processes()
    return tree(observed, roots(observed))


deadline = time.monotonic() + wait_seconds
live = live_targets()
while live and time.monotonic() < deadline:
    time.sleep(0.1)
    live = live_targets()
if not live:
    print("[dev-awa-overlay] integrity workers drained without intervention")
    raise SystemExit(0)

for pid in sorted(live, reverse=True):
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
deadline = time.monotonic() + term_seconds
while live and time.monotonic() < deadline:
    time.sleep(0.1)
    live = live_targets()
for pid in sorted(live, reverse=True):
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
time.sleep(0.1)
remaining = live_targets()
if remaining:
    raise SystemExit("integrity worker drain did not converge")
print("[dev-awa-overlay] exact AWA integrity worker tree terminated after bounded wait")
PY
}

do_rollback_preview() {
  echo "== dev AWA M1 rollback preview (no mutation) =="
  echo "  1. Disable the owned local-jobs trigger."
  echo "  2. Atomically restore the captured, validated hook-file preimage."
  echo "  3. Wait a bounded interval, then terminate only exact AWA integrity workers."
  echo "  4. Remove the owned local-jobs instance and type."
  echo "  5. Only afterward may Git/GCB/runtime rollback proceed under its own authority."
}

do_deactivate() {
  check_release_binding || die "exact release binding required for safe trigger rollback"
  "$JOB_INSTALLER" --deactivate \
    || die "local-jobs trigger could not be disabled"
  AWA_GCB_META="$SHELF_DIR/meta.yml" "$HOOK_INSTALLER" --restore-preimage \
    || die "captured AWA hook preimage could not be restored"
  drain_integrity_workers \
    || die "AWA integrity worker drain failed"
  "$JOB_INSTALLER" --remove \
    || die "owned local-jobs registration could not be removed"
  log "host triggers rolled back to the captured hook preimage; Git/GCB/runtime were not changed"
}

case "${1:-install}" in
  install|"") do_install "" ;;
  --repair)   do_install --repair ;;
  --preview)  do_preview ;;
  --doctor)   do_doctor ;;
  --check)    do_check ;;
  --deactivate) do_deactivate ;;
  --rollback-preview) do_rollback_preview ;;
  -h|--help)  sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "unknown argument: $1 (see --help)" ;;
esac
