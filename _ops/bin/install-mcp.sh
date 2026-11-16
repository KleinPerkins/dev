#!/usr/bin/env bash
# _ops/bin/install-mcp.sh — mirror the SHAREABLE MCP servers from Cursor into Codex + Claude,
# so the other tools inherit your tooling, not just the home context.
#
#   Source of truth : ~/.cursor/mcp.json  (whatever you've configured in Cursor)
#   Claude  (~/.claude.json)      : ALL servers — Claude uses the same mcpServers JSON schema
#                                   and supports http/sse/stdio transports.
#   Codex   (~/.codex/config.toml): COMMAND-based (stdio) servers only, as [mcp_servers.<name>]
#                                   TOML tables. Remote `url` servers are SKIPPED — Codex's MCP
#                                   client is stdio-first and won't run them from this config.
#
# Safe by construction: NON-DESTRUCTIVE (only ADDS servers the target is missing; never deletes
# or rewrites a server you already defined — pass MCP_MIRROR_FORCE=1 to overwrite Claude entries),
# BACKED UP (timestamped .bak before any write), and IDEMPOTENT (a re-run with nothing new to add
# writes nothing). These files live under ~ and are never committed, so no secret ever lands in git.
#
# Usage: _ops/bin/install-mcp.sh   (or: make install-mcp)   [--dry-run]
set -euo pipefail

DRY_RUN=0
case "${1:-}" in
  --dry-run) DRY_RUN=1 ;;
  ""|--all)  DRY_RUN=0 ;;
  -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
  *) printf '[install-mcp] unknown argument: %s (use --dry-run or no args)\n' "$1" >&2; exit 2 ;;
esac

# All legacy invocations (including dry-run and force) share the maintenance
# barrier. The supervisor holds it until this process exits; the second entry
# validates the inherited descriptor and current handoff records before reads.
MAINTENANCE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../interoperability" && pwd)/mcp_maintenance.py"
if ! command -v python3 >/dev/null 2>&1 || [ ! -r "$MAINTENANCE" ]; then
  echo "[install-mcp] maintenance guard unavailable; refusing legacy writer" >&2
  exit 73
fi
if [ -z "${DEV_MCP_MAINTENANCE_LOCK_FD+x}" ]; then
  exec python3 "$MAINTENANCE" legacy-enter mirror "$0" "$@"
fi
python3 "$MAINTENANCE" legacy-enter mirror "$0" "$@" || exit 73

CURSOR_MCP="$HOME/.cursor/mcp.json"
if [ ! -f "$CURSOR_MCP" ]; then
  echo "[install-mcp] (skip) no $CURSOR_MCP — nothing to mirror (is Cursor installed?)"
  exit 0
fi
command -v python3 >/dev/null 2>&1 || { echo "[install-mcp] FATAL: python3 required"; exit 1; }

MCP_MIRROR_DRYRUN="$DRY_RUN" python3 - "$CURSOR_MCP" "$HOME/.claude.json" "$HOME/.codex/config.toml" <<'PY'
import json, os, re, sys, time, shutil

cursor_path, claude_path, codex_path = sys.argv[1], sys.argv[2], sys.argv[3]
DRY   = os.environ.get("MCP_MIRROR_DRYRUN") == "1"
FORCE = os.environ.get("MCP_MIRROR_FORCE") == "1"

# Tool-internal servers we must never propagate out of their owning tool.
SKIP = {"node_repl"}

def ts() -> str:
    return time.strftime("%Y%m%d%H%M%S")

with open(cursor_path) as f:
    servers = (json.load(f).get("mcpServers") or {})

changed = False

# ----------------------------------------------------------------------------- Claude (JSON)
claude = {}
if os.path.exists(claude_path):
    with open(claude_path) as f:
        claude = json.load(f)
cms = claude.get("mcpServers")
if not isinstance(cms, dict):
    cms = {}

added, updated, kept = [], [], []
for name, spec in servers.items():
    if name in SKIP:
        continue
    if name not in cms:
        cms[name] = spec; added.append(name)
    elif cms[name] == spec:
        pass
    elif FORCE:
        cms[name] = spec; updated.append(name)
    else:
        kept.append(name)

if (added or updated):
    if DRY:
        print(f"[install-mcp] claude: WOULD add {sorted(added)} update {sorted(updated)}")
    else:
        claude["mcpServers"] = cms
        if os.path.exists(claude_path):
            bak = f"{claude_path}.bak.{ts()}"
            shutil.copy2(claude_path, bak)
            note = f" (backup: {os.path.basename(bak)})"
        else:
            note = ""
        tmp = f"{claude_path}.tmp.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(claude, f, indent=2); f.write("\n")
        os.replace(tmp, claude_path)
        print(f"[install-mcp] claude: +{len(added)} added {sorted(added)}"
              + (f", ~{len(updated)} updated {sorted(updated)}" if updated else "") + note)
    changed = True
else:
    print(f"[install-mcp] claude: up to date ({len(cms)} servers; {len(kept)} kept as-is)")
if kept and not FORCE:
    print(f"[install-mcp] claude: kept {len(kept)} pre-existing differing server(s) {sorted(kept)} "
          f"(set MCP_MIRROR_FORCE=1 to overwrite)")

# ----------------------------------------------------------------------------- Codex (TOML)
def toml_str(s) -> str:
    s = str(s)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

codex_txt = ""
if os.path.exists(codex_path):
    with open(codex_path) as f:
        codex_txt = f.read()

def has_table(txt, name) -> bool:
    return re.search(r'(?m)^\[mcp_servers\.' + re.escape(name) + r'\]', txt) is not None

emit, added_codex, skipped_url, skipped_present = [], [], [], []
for name, spec in servers.items():
    if name in SKIP:
        continue
    cmd = spec.get("command")
    if not cmd:
        if spec.get("url"):
            skipped_url.append(name)
        continue
    if has_table(codex_txt, name):
        skipped_present.append(name); continue   # append-only: never duplicate a TOML table
    lines = [f"[mcp_servers.{name}]", f"command = {toml_str(cmd)}"]
    args = spec.get("args") or []
    lines.append("args = [" + ", ".join(toml_str(a) for a in args) + "]")
    block = "\n".join(lines)
    env = spec.get("env") or {}
    if env:
        block += f"\n\n[mcp_servers.{name}.env]\n" + "\n".join(
            f"{k} = {toml_str(v)}" for k, v in env.items())
    emit.append(block)
    added_codex.append(name)

if added_codex:
    if DRY:
        print(f"[install-mcp] codex: WOULD add stdio server(s) {sorted(added_codex)}")
    else:
        if os.path.exists(codex_path):
            bak = f"{codex_path}.bak.{ts()}"
            shutil.copy2(codex_path, bak)
            note = f" (backup: {os.path.basename(bak)})"
        else:
            os.makedirs(os.path.dirname(codex_path), exist_ok=True)
            note = ""
        sep = "" if codex_txt == "" else ("\n" if codex_txt.endswith("\n") else "\n\n")
        with open(codex_path, "a") as f:
            f.write(sep + "\n\n".join(emit) + "\n")
        print(f"[install-mcp] codex: +{len(added_codex)} stdio server(s) {sorted(added_codex)}" + note)
    changed = True
else:
    print("[install-mcp] codex: no new stdio servers to add")
if skipped_url:
    print(f"[install-mcp] codex: skipped {len(skipped_url)} remote url server(s) "
          f"(Codex MCP is stdio-first) {sorted(skipped_url)}")

print("[install-mcp] OK" + ("" if changed else " — everything already current (no changes)"))
PY
