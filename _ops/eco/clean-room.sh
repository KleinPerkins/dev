#!/usr/bin/env bash
# _ops/eco/clean-room.sh — clean-room fresh-clone + REAL-install regression gate (reorg-v2 WS-4 / D-14).
#
# Proves a FRESH checkout installs to GREEN by running the ACTUAL bootstrap chain a new machine runs
# (bootstrap.sh), without touching the real environment or the network:
#   * local --no-hardlinks clones of dev + skills into a tmpdir (hermetic; no network)
#   * an ISOLATED $HOME so the install never touches the real ~/.cursor /.claude /.codex
#   * runs `ECO_BOOTSTRAP_OFFLINE=1 bash bootstrap.sh` (the real orchestrator, minus the 2 network
#     steps: MCP mirror + kp-mcp clone) and asserts the REAL installed artifacts actually appear:
#       - ~/.cursor/rules/dev-operating-model.mdc symlink resolves into the fresh repo
#       - ~/.codex/AGENTS.md + ~/.claude/CLAUDE.md carry the managed block
#       - Flavor-1 global skill (prompt-architect) + repo /dev-* skill (dev-doctor) are exposed
#   * runs the chain a SECOND time and asserts idempotence (still green; managed block NOT duplicated)
#   * runs the repo-only gates (operating-model --ci, manifests, zero-link) on the fresh tree
#
# This is the anti-false-green gate: the old version only ran one install.sh + repo gates, so a broken
# bootstrap chain could still report "green". Exit 0 = reproducible green. Cleans up unless ECO_KEEP_TMP=1.
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
. "$SELF_DIR/lib.sh"
SRC_DEV="$ECO_REPO_ROOT"
SRC_SKILLS="$ECO_REPO_ROOT/capabilities/skills"

TMP="$(mktemp -d)"; CRHOME="$TMP/home"
CRDATA="$TMP/xdg-data"; CRCONFIG="$TMP/xdg-config"; CRSTATE="$TMP/xdg-state"
AWA_OFFLINE_CLONE="$TMP/offline/awa-unavailable"
GIT_REAL="$(command -v git)"
GIT_CALL_LOG="$TMP/git-calls.log"; GIT_NETWORK_LOG="$TMP/git-network-blocked.log"
mkdir -p "$CRHOME/.cursor/skills" "$CRHOME/.codex" "$CRHOME/.claude" \
  "$CRDATA" "$CRCONFIG" "$CRSTATE" "$TMP/bin"
[ ! -e "$AWA_OFFLINE_CLONE" ] || { eco_err "offline AWA clone sentinel unexpectedly exists"; exit 1; }
cat > "$TMP/bin/git" <<EOF
#!/usr/bin/env bash
set -u
printf '%s\n' "\$*" >> "$GIT_CALL_LOG"
network_op=0
for arg in "\$@"; do [ "\$arg" = clone ] || [ "\$arg" = fetch ] || continue; network_op=1; done
if [ "\$network_op" = 1 ]; then
  for arg in "\$@"; do
    case "\$arg" in
      *://*|*@*:*)
        printf '%s\n' "\$*" >> "$GIT_NETWORK_LOG"
        echo "clean-room git sentry: network clone/fetch URL refused" >&2
        exit 97
        ;;
    esac
  done
fi
exec "$GIT_REAL" "\$@"
EOF
chmod +x "$TMP/bin/git"
cleanup() { [ "${ECO_KEEP_TMP:-0}" = 1 ] || rm -rf "$TMP"; }
trap cleanup EXIT
fails=0
ok()  { printf '  PASS  %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; fails=1; }
# run <name> <cmd...> — every child receives only fixture-local HOME/XDG/AWA clone state.
run() {
  local n="$1"; shift
  if HOME="$CRHOME" XDG_DATA_HOME="$CRDATA" XDG_CONFIG_HOME="$CRCONFIG" \
     XDG_STATE_HOME="$CRSTATE" AWA_CLONE_URL="$AWA_OFFLINE_CLONE" \
     PATH="$TMP/bin:$PATH" "$@" >"$TMP/out" 2>&1; then
    ok "$n"
  else
    bad "$n"
    sed 's/^/        | /' "$TMP/out" | tail -12
  fi
}

awa_state() {
  local p
  for p in \
    "$CRDATA/awa/current" \
    "$CRDATA/awa/release-pointer.json" \
    "$CRDATA/awa/gcb-pointer.json" \
    "$CRCONFIG/awa/hook-owner.json"; do
    if [ -e "$p" ] || [ -L "$p" ]; then printf 'present %s\n' "$p"; else printf 'absent %s\n' "$p"; fi
  done
  if [ -f "$CRHOME/.cursor/hooks.json" ]; then
    python3 - "$CRHOME/.cursor/hooks.json" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    print("awa-hook-json-invalid")
    raise SystemExit(0)
awa = []
for entries in (data.get("hooks") or {}).values():
    for entry in entries if isinstance(entries, list) else []:
        command = entry.get("command", "") if isinstance(entry, dict) else ""
        if "/_ops/cursor-hooks/worktree-" in command or "/awa/current/kernel/hooks/" in command:
            awa.append(command)
print("awa-hook-count %d" % len(awa))
PY
  else
    printf 'awa-hook-count 0\n'
  fi
  for p in "$CRHOME/.cursor"/hooks.json.bak-*; do
    [ -e "$p" ] && printf 'backup %s\n' "$p"
  done
}

MARK='<!-- BEGIN dev-operating-model (managed by KleinPerkins/dev) -->'
mark_count() { grep -cF "$MARK" "$1" 2>/dev/null || printf '0'; }

eco_log "clean-room: fresh local clones into $TMP (hermetic)"
git clone -q --local --no-hardlinks "$SRC_DEV" "$TMP/dev" || { eco_err "clone dev failed"; exit 1; }
if [ -d "$SRC_SKILLS/.git" ]; then
  git clone -q --local --no-hardlinks "$SRC_SKILLS" "$TMP/dev/capabilities/skills" || { eco_err "clone skills failed"; exit 1; }
else
  eco_err "clean-room: skills repo not found at $SRC_SKILLS (cannot exercise the real chain)"; exit 1
fi
cd "$TMP/dev"

# ---- 1) REAL bootstrap chain (offline), run #1 -----------------------------------------------------
run "bootstrap.sh (offline real chain, isolated HOME)" env ECO_BOOTSTRAP_OFFLINE=1 bash bootstrap.sh
AWA_STATE_FIRST="$(awa_state)"
if printf '%s\n' "$AWA_STATE_FIRST" | grep -q '^present \|^backup \|^awa-hook-json-invalid$\|^awa-hook-count [^0]'; then
  bad "offline AWA lane leaves no runtime/pointer/owner/hook residue"
else
  ok "offline AWA lane leaves no runtime/pointer/owner/hook residue"
fi

# ---- 2) REAL artifacts actually installed into the isolated HOME -----------------------------------
mdc_target="$TMP/dev/_ops/rules/dev-operating-model.mdc"
link="$CRHOME/.cursor/rules/dev-operating-model.mdc"
if [ -L "$link" ] && [ "$(readlink "$link")" = "$mdc_target" ] && [ -e "$link" ]; then ok "cursor .mdc symlink resolves into fresh repo"; else bad "cursor .mdc symlink resolves into fresh repo"; fi
[ "$(mark_count "$CRHOME/.codex/AGENTS.md")"  = 1 ] && ok "codex AGENTS.md has exactly one managed block"  || bad "codex AGENTS.md has exactly one managed block"
[ "$(mark_count "$CRHOME/.claude/CLAUDE.md")" = 1 ] && ok "claude CLAUDE.md has exactly one managed block" || bad "claude CLAUDE.md has exactly one managed block"
[ -L "$CRHOME/.cursor/skills/prompt-architect" ] && ok "Flavor-1 global skill exposed (prompt-architect)" || bad "Flavor-1 global skill exposed (prompt-architect)"
[ -L "$CRHOME/.cursor/skills/dev-doctor" ]        && ok "repo /dev-* skill exposed (dev-doctor)"            || bad "repo /dev-* skill exposed (dev-doctor)"

# ---- 3) Idempotence: re-run the whole chain; must stay green AND not duplicate the managed block ----
run "bootstrap.sh re-run (idempotent)" env ECO_BOOTSTRAP_OFFLINE=1 bash bootstrap.sh
[ "$(awa_state)" = "$AWA_STATE_FIRST" ] && ok "idempotent: offline AWA state byte-identical" || bad "idempotent: offline AWA state changed"
[ "$(mark_count "$CRHOME/.codex/AGENTS.md")"  = 1 ] && ok "idempotent: codex managed block still single"  || bad "idempotent: codex managed block duplicated/lost"
[ "$(mark_count "$CRHOME/.claude/CLAUDE.md")" = 1 ] && ok "idempotent: claude managed block still single" || bad "idempotent: claude managed block duplicated/lost"
[ -L "$link" ] && [ -e "$link" ] && ok "idempotent: cursor .mdc symlink still resolves" || bad "idempotent: cursor .mdc symlink broke on re-run"

# ---- 4) Repo-only reproducibility gates on the fresh tree (fast, HOME-independent) -----------------
run "verify-operating-model --ci" bash _ops/checks/verify-operating-model.sh --ci
run "verify-manifests"            bash _ops/eco/verify-manifests.sh
run "verify-zero-link (all roots)" bash _ops/eco/verify-zero-link.sh --all-roots

# ---- 5) AWA Standalone System Package: install-ready from a fresh clone in an isolated HOME --------
# The offline bootstrap above skips the network clone of KleinPerkins/awa; here we assert the
# standalone install.sh STATIC preflight (--check) passes in the isolated HOME — no runtime required,
# no writes to $HOME — proving a fresh machine can install AWA via the global tools/awa GCB shelf,
# and that the ~/dev thin overlay is self-consistent (host policy valid + delegators thin).
AWA_SHELF="capabilities/skills/global/tools/awa/install.sh"
if [ -f "$AWA_SHELF" ]; then
  run "awa GCB shelf --check (standalone install-ready, isolated HOME)" bash "$AWA_SHELF" --check
else
  bad "awa GCB shelf absent in fresh tree ($AWA_SHELF)"
fi
run "dev AWA overlay --check (thin overlay self-consistent, isolated HOME)" bash _ops/bin/install-dev-awa-overlay.sh --check
if grep -F "$AWA_OFFLINE_CLONE" "$GIT_CALL_LOG" >/dev/null 2>&1; then
  ok "offline AWA clone override consumed"
else
  bad "offline AWA clone override was not consumed"
fi
if [ ! -s "$GIT_NETWORK_LOG" ]; then
  ok "git sentry observed no network URL"
else
  bad "git sentry blocked a network URL"
fi

echo
if [ "$fails" -eq 0 ]; then eco_log "clean-room: PASS (fresh clone runs the REAL bootstrap chain to green, idempotently)"; exit 0
else eco_err "clean-room: FAIL"; exit 1; fi
