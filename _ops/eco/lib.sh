#!/usr/bin/env bash
# _ops/eco/lib.sh — shared helpers for the reorg-v2 ecosystem operating model.
#
# Source it; do not execute it. Exposes: managed-root list, manifest (meta.yml) readers,
# scope inference, out-of-tree backup, and structured logging. Reuses _ops/bin/lib.sh for
# sha256 + the canonical identity. Dependency-free (no PyYAML); meta.yml is FLAT by contract.

ECO_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"   # .../_ops/eco
ECO_OPS_DIR="$(cd "$ECO_LIB_DIR/.." && pwd)"                      # .../_ops
ECO_REPO_ROOT="$(cd "$ECO_OPS_DIR/.." && pwd)"                    # repo root (~/dev)

# Reuse the home-OM lib for om_sha256 + OM_NOREPLY/OM_GH_USER (best-effort).
# shellcheck source=../bin/lib.sh
[ -f "$ECO_OPS_DIR/bin/lib.sh" ] && . "$ECO_OPS_DIR/bin/lib.sh"

# Backups for destructive ops live OUTSIDE the managed tree (D-12 / safety rail).
ECO_ARCHIVE_DIR="${ECO_ARCHIVE_DIR:-$HOME/.reorg-archives}"

# Bootstrap-managed roots (D-12 scope). Each holds per-artifact dirs with a meta.yml.
# Skills use kind shelves under global|local; mcp remains an independently-governed flat root.
eco_managed_roots() {
  local scope shelf
  for scope in global local; do
    for shelf in skills rules sub-agents tools; do
      printf 'capabilities/skills/%s/%s\n' "$scope" "$shelf"
    done
  done
  printf 'capabilities/mcp\n'
}

eco_log()  { printf '[eco] %s\n' "$*"; }
eco_warn() { printf '[eco] WARN %s\n' "$*" >&2; }
eco_err()  { printf '[eco] ERROR %s\n' "$*" >&2; }

# eco_sha256 <file> — prefer the home-OM helper, fall back to shasum/openssl.
eco_sha256() {
  if command -v om_sha256 >/dev/null 2>&1; then om_sha256 "$1"; return; fi
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}';
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}';
  else openssl dgst -sha256 "$1" | awk '{print $NF}'; fi
}

# eco_meta_get <meta.yml> <key> — read a FLAT "key: value" (strips surrounding quotes).
# Returns empty string if the key is absent. Ignores commented (#) lines.
eco_meta_get() {
  [ -f "$1" ] || { printf ''; return; }
  awk -v k="$2" '
    /^[[:space:]]*#/ { next }
    {
      line=$0
      sub(/[[:space:]]+#.*$/, "", line)            # strip trailing comments (require space before #; keep '#' inside values)
      if (match(line, /^[A-Za-z0-9_]+:[[:space:]]*/)) {
        key=line; sub(/:.*$/, "", key)
        if (key==k) {
          val=line; sub(/^[A-Za-z0-9_]+:[[:space:]]*/, "", val)
          gsub(/^"|"$/, "", val); gsub(/^'\''|'\''$/, "", val)
          print val; exit
        }
      }
    }' "$1"
}

eco_kind_shelf() {
  case "$1" in
    skill)     printf 'skills\n' ;;
    rule)      printf 'rules\n' ;;
    sub-agent) printf 'sub-agents\n' ;;
    tool)      printf 'tools\n' ;;
    *) printf '' ;;
  esac
}

eco_shelf_of_dir() {
  local p="$1" seg parent prev=""
  while [ -n "$p" ] && [ "$p" != "/" ] && [ "$p" != "." ]; do
    seg="${p##*/}"
    case "$seg" in
      global|local) printf '%s\n' "$prev"; return ;;
    esac
    prev="$seg"
    parent="${p%/*}"
    [ "$parent" = "$p" ] && break
    p="$parent"
  done
  printf 'unknown\n'
}

# eco_scope_of_dir <artifact-dir> — infer scope from the containing path (the directory paradigm).
# Walks segments from the artifact dir UPWARD and returns the NEAREST global|local segment, so an
# ANCESTOR dir that happens to be named global/local can never mis-classify a deeper artifact
# (e.g. .../global/x/local/<id> ⇒ local, not global). "unknown" if neither is found.
eco_scope_of_dir() {
  local p="$1" seg parent
  while [ -n "$p" ] && [ "$p" != "/" ] && [ "$p" != "." ]; do
    seg="${p##*/}"
    case "$seg" in
      global) printf 'global\n'; return ;;
      local)  printf 'local\n';  return ;;
    esac
    parent="${p%/*}"
    [ "$parent" = "$p" ] && break    # no more slashes
    p="$parent"
  done
  printf 'unknown\n'
}

# eco_backup_outoftree <src-dir> <label> — tar.gz <src> into a timestamped archive OUTSIDE the
# managed tree. Prints the archive path ON SUCCESS ONLY; returns non-zero (and prints nothing to
# stdout) if the tar fails or the archive can't be verified. Callers MUST check the exit status
# before any destructive mutation — it is a hard precondition for replace/rebuild + the dedup swap.
eco_backup_outoftree() {
  local src="$1" label="${2:-backup}" ts out rc
  [ -e "$src" ] || { eco_err "backup: source missing: $src"; return 2; }
  ts="$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$ECO_ARCHIVE_DIR" || { eco_err "backup: cannot create archive dir $ECO_ARCHIVE_DIR"; return 2; }
  out="$ECO_ARCHIVE_DIR/${label}-${ts}.tar.gz"
  ( cd "$(dirname "$src")" && tar -czf "$out" "$(basename "$src")" ); rc=$?
  if [ "$rc" -ne 0 ]; then eco_err "backup: tar failed (rc=$rc) for $src"; rm -f "$out"; return 1; fi
  # smoke-test the archive: must be listable AND non-empty before any caller trusts it.
  if ! tar -tzf "$out" >/dev/null 2>&1 || [ ! -s "$out" ]; then
    eco_err "backup: archive unverifiable (corrupt/empty): $out"; rm -f "$out"; return 1
  fi
  printf '%s\n' "$out"
}

# eco_is_in_managed_tree <abs-path> — guard so a backup target can never live inside the tree.
eco_is_in_managed_tree() {
  case "$1" in "$ECO_REPO_ROOT"/*) return 0 ;; *) return 1 ;; esac
}

# eco_under_managed_root <abs-path> — 0 iff the path is AT or UNDER a configured managed root.
# Used by destructive sync modes so they can never mutate/delete outside a bootstrap-managed root.
eco_under_managed_root() {
  local p="$1" r abs
  for r in $(eco_managed_roots); do
    abs="$ECO_REPO_ROOT/$r"
    [ "$p" = "$abs" ] && return 0
    case "$p/" in "$abs/"*) return 0 ;; esac
  done
  return 1
}
