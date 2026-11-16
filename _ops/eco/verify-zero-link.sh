#!/usr/bin/env bash
# _ops/eco/verify-zero-link.sh — INV-zero-link forensic assertion (WS-5; Decision C all-roots).
#
# A forensic review of global-stuff OR cpp-stuff IN ISOLATION must surface ZERO ld<->cpp
# relationship. This linter scans a tree for the FORBIDDEN tokens of the OTHER side:
#   --mode global <path>   scan an ld/global artifact for CPP tokens (card-platform-product, …)
#   --mode cpp    <path>   scan a cpp artifact/payload for LD tokens (~/dev, KleinPerkins/…, …)
#   --all-roots            scan EVERY managed root (Decision C) present in this checkout in
#                          --mode global (each managed root is an ld/global-side tree); roots that
#                          live in their own repo and are absent here are skipped. Aggregates:
#                          exit 1 if ANY present root violates.
# Read-only. Exit 0 if clean, else 1 (+ the offending file:line), 2 on bad args. Excludes VCS +
# generated fixture/state trees (machine-local routing config legitimately names the other side).
set -uo pipefail
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"

MODE=""; SCAN=""; ALL_ROOTS=0
while [ $# -gt 0 ]; do case "$1" in
  --mode) shift; MODE="${1:-}" ;;
  --all-roots) ALL_ROOTS=1 ;;
  -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
  *) SCAN="$1" ;;
esac; shift; done

# Exclusions: VCS, caches, generated fixture/discovery trees, machine-local routing state.
# Also excluded by FILE (not a capability payload → not subject to INV-zero-link):
#   *.generated.*  machine-generated, git-ignored artifacts (e.g. local-jobs dashboards) that
#                  legitimately embed real machine paths + local-job ids like `cpp-archive`.
#   agent-learnings.md  post-migration untracked machine-mined cross-repo memory; it can name the
#                       other side and would otherwise create a false INV-zero-link violation.
#   AGENTS.md           hand-authored operating-model prose legitimately references cpp; it is not
#                       a capability payload and is never vendored into cpp.
ZL_EXCLUDES=( --exclude-dir=.git --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=.pytest_cache
              --exclude-dir=node_modules --exclude-dir=.state --exclude-dir=home --exclude-dir=discoveries
              --exclude='*.generated.*'
              --exclude=agent-learnings.md
              --exclude=AGENTS.md )

# zl_tokens <mode> — forbidden token regex (extended) for the OTHER side. Returns 2 on a bad mode.
zl_tokens() {
  case "$1" in
    global) printf '%s' 'card-platform-product|cpp-stuff|affirm/(src|vendor)|(^|[^A-Za-z.])cpp([^A-Za-z]|$)' ;;
    cpp)    printf '%s' 'KleinPerkins/[A-Za-z0-9_.-]+|kp-mcp|ecosystem-orchestrator|/Users/laurence\.duggan|/dev/capabilities|(^|[^A-Za-z])~/dev|49759187\+KleinPerkins|ld-stuff' ;;
    *) return 2 ;;
  esac
}

# zl_scan <mode> <path> — 0 clean / 1 violation / 2 bad-args. Prints a per-scan verdict.
zl_scan() {
  local mode="$1" scan="$2" tokens other hits
  tokens="$(zl_tokens "$mode")" || { echo "verify-zero-link: mode must be global|cpp" >&2; return 2; }
  case "$mode" in global) other="cpp" ;; cpp) other="ld" ;; esac
  [ -e "$scan" ] || { echo "verify-zero-link: path not found: $scan" >&2; return 2; }
  echo "== zero-link scan (mode=$mode; forbidding $other tokens) =="
  echo "   path: $scan"
  # -r (NOT -R): do not follow symlinks. -i: case-insensitive (catches CPP / Affirm / KleinPerkins variants).
  hits="$(grep -rEniI "${ZL_EXCLUDES[@]}" "$tokens" "$scan" 2>/dev/null || true)"
  if [ -n "$hits" ]; then
    echo "  FAIL — $other references found in a $mode artifact (INV-zero-link violation):"
    printf '%s\n' "$hits" | sed 's/^/    /'
    return 1
  fi
  echo "  PASS — no $other tokens found."
  return 0
}

# --- all-roots mode (Decision C): scan every present managed root in --mode global ----------------
if [ "$ALL_ROOTS" = 1 ]; then
  # shellcheck source=lib.sh
  . "$SELF_DIR/lib.sh"
  rc=0; any=0
  echo "== zero-link: scanning ALL managed roots (Decision C) =="
  for r in $(eco_managed_roots); do
    p="$ECO_REPO_ROOT/$r"
    if [ -d "$p" ]; then any=1; zl_scan global "$p" || rc=1
    else echo "   (skip) $r — root absent (lives in its own repo; not in this checkout)"; fi
  done
  [ "$any" = 1 ] || echo "   (note) no managed roots present in this checkout — nothing to scan"
  echo
  if [ "$rc" -eq 0 ]; then echo "verify-zero-link: OK (all present managed roots clean)"; else echo "verify-zero-link: FAILED"; fi
  exit "$rc"
fi

# --- single-path mode (back-compat: --mode global|cpp <path>) ------------------------------------
[ -n "$MODE" ] && [ -n "$SCAN" ] || { echo "usage: verify-zero-link.sh --mode global|cpp <path> | --all-roots" >&2; exit 2; }
zl_scan "$MODE" "$SCAN"; rc=$?
echo
if [ "$rc" -eq 0 ]; then echo "verify-zero-link: OK"; elif [ "$rc" -eq 1 ]; then echo "verify-zero-link: FAILED"; fi
exit "$rc"
