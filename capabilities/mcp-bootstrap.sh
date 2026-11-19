#!/usr/bin/env bash
# capabilities/mcp-bootstrap.sh — kp-mcp bootstrap plus LD-host snow-kit lifecycle.
#
# No arguments preserves the historical full, noninteractive bootstrap. Snow-kit
# additionally supports:
#   install|repin snow-kit [--activate]  status snow-kit
#   doctor snow-kit [--live]            repair snow-kit
#   rollback snow-kit                   uninstall snow-kit
set -euo pipefail

CAP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
MCP_DIR="${KP_MCP_DIR_OVERRIDE:-$CAP_ROOT/mcp}"
PIN_FILE="${SNOW_KIT_PIN_FILE:-$CAP_ROOT/mcp-pins.env}"
MCP_REPO_URL="${KP_MCP_REPO_URL:-}"
SOURCE_IDENTITY="$CAP_ROOT/../_ops/interoperability/original_sources.py"

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
RUNTIME_ROOT="${SNOW_KIT_RUNTIME_ROOT:-$DATA_HOME/kp-mcp/snow-kit}"
STATE_ROOT="${SNOW_KIT_STATE_ROOT:-$STATE_HOME/snow-kit}"
CONFIG_PATH="${SNOW_KIT_CONFIG_PATH:-$CONFIG_HOME/snow-kit/config.env}"
BIN_DIR="${SNOW_KIT_BIN_DIR:-$HOME/.local/bin}"
STABLE_BIN="$BIN_DIR/snow-kit"
CURSOR_CONFIG="${SNOW_KIT_CURSOR_CONFIG:-$HOME/.cursor/mcp.json}"
CODEX_CONFIG="${SNOW_KIT_CODEX_CONFIG:-$HOME/.codex/config.toml}"
CLAUDE_CONFIG="${SNOW_KIT_CLAUDE_CONFIG:-$HOME/.claude.json}"
UV_BIN="${SNOW_KIT_UV_BIN:-uv}"
GIT_BIN="${SNOW_KIT_GIT_BIN:-git}"

LOCK_DIR="$STATE_ROOT/install.lock"
RELEASES_DIR="$RUNTIME_ROOT/releases"
CURRENT_LINK="$RUNTIME_ROOT/current"
CURRENT_SHA_FILE="$STATE_ROOT/current-sha"
PREVIOUS_SHA_FILE="$STATE_ROOT/previous-sha"
LKG_SHA_FILE="$STATE_ROOT/last-known-good-sha"
PRE_MANAGED_BIN="$STATE_ROOT/backups/snow-kit.pre-managed"

log() { printf '[mcp-bootstrap] %s\n' "$*"; }
die() { log "ERROR: $*"; exit 1; }

validate_managed_layout() {
  local path
  for path in "$RUNTIME_ROOT" "$STATE_ROOT" "$CONFIG_PATH" "$BIN_DIR"; do
    case "$path" in
      /*) ;;
      *) die "managed paths must be absolute" ;;
    esac
    case "/$path/" in *"/../"*) die "managed paths must not contain '..'" ;; esac
  done
  case "$RUNTIME_ROOT" in */kp-mcp/snow-kit) ;; *) die "runtime root must end in /kp-mcp/snow-kit" ;; esac
  case "$STATE_ROOT" in */snow-kit) ;; *) die "state root must end in /snow-kit" ;; esac
  case "$CONFIG_PATH" in */snow-kit/config.env) ;; *) die "config path must end in /snow-kit/config.env" ;; esac
  case "$BIN_DIR" in */.local/bin) ;; *) die "binary directory must end in /.local/bin" ;; esac
  [ "$RUNTIME_ROOT" != "/" ] && [ "$STATE_ROOT" != "/" ] && [ "$BIN_DIR" != "/" ] ||
    die "managed roots cannot be filesystem root"
}

secure_dir() {
  mkdir -p "$1"
  chmod 700 "$1"
}

pin_value() {
  local key="$1"
  awk -F= -v wanted="$key" '
    $1 == wanted { value=substr($0, length($1) + 2); count++ }
    END { if (count != 1) exit 3; print value }
  ' "$PIN_FILE"
}

load_pin() {
  [ -f "$PIN_FILE" ] || die "pin file missing: $PIN_FILE"
  SNOW_REPO="$(pin_value SNOW_KIT_REPO)" || die "SNOW_KIT_REPO must appear exactly once"
  SNOW_TAG="$(pin_value SNOW_KIT_TAG)" || die "SNOW_KIT_TAG must appear exactly once"
  SNOW_SHA="$(pin_value SNOW_KIT_SHA)" || die "SNOW_KIT_SHA must appear exactly once"
  [[ "$SNOW_TAG" =~ ^snow-kit-v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "invalid snow-kit tag"
  [ "${#SNOW_SHA}" -eq 40 ] || die "snow-kit SHA must be 40 lowercase hex characters"
  case "$SNOW_SHA" in *[!0-9a-f]*) die "snow-kit SHA must be 40 lowercase hex characters" ;; esac
}

verify_remote_pin() {
  local resolved
  command -v "$GIT_BIN" >/dev/null 2>&1 || die "git is required"
  # Only the original ID can supply the existing tag/SHA, before or after rename.
  SNOW_REPO="$(python3 "$SOURCE_IDENTITY" KleinPerkins/kp-mcp --resolve-url "$SNOW_REPO")" ||
    die "release source is not the retained original"
  resolved="$("$GIT_BIN" ls-remote --tags "$SNOW_REPO" "refs/tags/$SNOW_TAG" | awk 'NR == 1 {print $1}')"
  [ -n "$resolved" ] || die "release tag did not resolve"
  [ "$resolved" = "$SNOW_SHA" ] || die "release tag does not match the pinned SHA"
  log "release pin verified ($SNOW_TAG @ ${SNOW_SHA:0:12})"
}

acquire_lock() {
  secure_dir "$STATE_ROOT"
  if mkdir "$LOCK_DIR" 2>/dev/null; then
    printf '%s\n' "$$" >"$LOCK_DIR/pid"
    return
  fi
  if [ -f "$LOCK_DIR/pid" ]; then
    local owner
    owner="$(awk 'NR == 1 {print $1}' "$LOCK_DIR/pid" 2>/dev/null || true)"
    if [ -n "$owner" ] && ! kill -0 "$owner" 2>/dev/null; then
      rm -f "$LOCK_DIR/pid"
      rmdir "$LOCK_DIR" 2>/dev/null || true
      mkdir "$LOCK_DIR" || die "could not reclaim stale install lock"
      printf '%s\n' "$$" >"$LOCK_DIR/pid"
      return
    fi
  fi
  die "another snow-kit lifecycle operation holds the install lock"
}

release_lock() {
  rm -f "$LOCK_DIR/pid" 2>/dev/null || true
  rmdir "$LOCK_DIR" 2>/dev/null || true
}

write_state() {
  local path="$1" value="$2" tmp
  secure_dir "$STATE_ROOT"
  tmp="$STATE_ROOT/.state.$$.$RANDOM"
  printf '%s\n' "$value" >"$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "$path"
}

read_state() {
  [ -f "$1" ] || return 0
  awk 'NR == 1 {print $1}' "$1"
}

migrate_profile() {
  command -v python3 >/dev/null 2>&1 || die "python3 is required for secure profile migration"
  secure_dir "$(dirname "$CONFIG_PATH")"
  python3 - "$CONFIG_PATH" "$CURSOR_CONFIG" "$CODEX_CONFIG" "$CLAUDE_CONFIG" <<'PY'
import json
import os
import shutil
import stat
import sys
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path

profile, cursor, codex, claude = map(Path, sys.argv[1:])
allowed = {
    "SNOW_KIT_USER", "SNOW_KIT_ACCOUNT", "SNOW_KIT_AUTHENTICATOR",
    "SNOW_KIT_WAREHOUSE", "SNOW_KIT_DATABASE", "SNOW_KIT_SCHEMA",
    "SNOW_KIT_ROLE", "SNOW_KIT_LOGIN_TIMEOUT", "SNOW_KIT_NETWORK_TIMEOUT",
    "SNOW_KIT_QUERY_TIMEOUT", "SNOW_KIT_TOOL_TIMEOUT",
    "SNOW_KIT_AUTH_LOCK_TIMEOUT", "SNOW_KIT_MAX_RESULT_ROWS",
    "SNOW_KIT_MAX_RECONNECT_RETRIES", "SNOW_KIT_PERMISSION_SPEC_PATH",
    "SNOW_KIT_WRITE_SCHEMA_PATTERNS", "SNOW_KIT_STATE_DIR",
    "SNOW_KIT_AUTH_LOCK_DIR",
}
forbidden = "SNOW_KIT_ENABLE_WRITE"

def fail(message: str) -> None:
    raise SystemExit(f"profile migration refused: {message}")

def parse_lines(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail(f"line {number} is not KEY=VALUE")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if key == forbidden:
            fail("write enablement is forbidden")
        if key.startswith("SNOWFLAKE_"):
            key = "SNOW_KIT_" + key[len("SNOWFLAKE_"):]
        if key not in allowed:
            fail(f"unsupported key {key!r}")
        if key in result:
            fail(f"duplicate key {key!r}")
        result[key] = value
    return result

def json_entries(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    servers = data.get("mcpServers", {})
    return [servers.get(name, {}) for name in ("snow-kit", "snowflake")]

def toml_entries(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcp_servers", {})
    return [servers.get(name, {}) for name in ("snow-kit", "snowflake")]

values: dict[str, str] = {}
if profile.exists() or profile.is_symlink():
    info = profile.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail("canonical profile must be a regular non-symlink file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        fail("canonical profile must be owned by the current user")
    values.update(parse_lines(profile.read_text(encoding="utf-8")))

for entry in json_entries(cursor) + toml_entries(codex) + json_entries(claude):
    env = entry.get("env", {}) if isinstance(entry, dict) else {}
    if not isinstance(env, dict):
        continue
    for raw_key, raw_value in env.items():
        key = str(raw_key)
        if key == forbidden:
            continue
        if key.startswith("SNOWFLAKE_"):
            key = "SNOW_KIT_" + key[len("SNOWFLAKE_"):]
        if key in allowed and key not in values and isinstance(raw_value, (str, int)):
            value = str(raw_value)
            if any(char in value for char in "\x00\r\n"):
                fail(f"unsafe value for {key!r}")
            values[key] = value

profile.parent.mkdir(parents=True, exist_ok=True)
os.chmod(profile.parent, 0o700)
payload = "# Operator-local snow-kit configuration. Never commit this file.\n"
payload += "".join(f"{key}={values[key]}\n" for key in sorted(values))
if profile.exists() and profile.read_text(encoding="utf-8") == payload:
    os.chmod(profile, 0o600)
    print(f"profile ready ({len(values)} allowlisted setting(s)); values redacted")
    raise SystemExit(0)
if profile.exists():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = profile.with_name(f"{profile.name}.bak.{stamp}")
    shutil.copy2(profile, backup)
    os.chmod(backup, 0o600)
fd, tmp_name = tempfile.mkstemp(prefix=".config.", suffix=".tmp", dir=profile.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp_name, 0o600)
    os.replace(tmp_name, profile)
finally:
    try:
        os.unlink(tmp_name)
    except FileNotFoundError:
        pass
print(f"profile ready ({len(values)} allowlisted setting(s)); values redacted")
PY
}

cleanup_stages() {
  local stage
  [ -d "$RELEASES_DIR" ] || return 0
  for stage in "$RELEASES_DIR"/.stage.*; do
    [ -e "$stage" ] || continue
    [ ! -L "$stage" ] || die "refusing symlinked staging path"
    rm -rf -- "$stage"
  done
}

stage_release() {
  local final="$RELEASES_DIR/$SNOW_SHA" stage candidate head
  secure_dir "$RUNTIME_ROOT"
  secure_dir "$RELEASES_DIR"
  cleanup_stages

  candidate="$final/repo/.venv/bin/snow-kit"
  if [ -x "$candidate" ]; then
    head="$("$GIT_BIN" -C "$final/repo" rev-parse HEAD 2>/dev/null || true)"
    [ "$head" = "$SNOW_SHA" ] || die "existing release directory has the wrong commit"
    "$GIT_BIN" -C "$final/repo" diff --quiet HEAD -- ||
      die "existing release source has tracked modifications"
    if env -u SNOW_KIT_ENABLE_WRITE "$candidate" --help >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return
    fi
    [ ! -L "$final" ] || die "refusing symlinked damaged release directory"
    rm -rf -- "$final"
    log "repairing damaged release runtime" >&2
  fi
  if [ -f "$final/.installing" ]; then
    [ ! -L "$final" ] || die "refusing symlinked interrupted release directory"
    rm -rf -- "$final"
    log "recovered interrupted release staging" >&2
  fi
  if [ -e "$final" ]; then
    head="$("$GIT_BIN" -C "$final/repo" rev-parse HEAD 2>/dev/null || true)"
    [ "$head" = "$SNOW_SHA" ] || die "incomplete release directory has the wrong commit"
    [ ! -L "$final" ] || die "refusing symlinked incomplete release directory"
    rm -rf -- "$final"
    log "repairing incomplete release runtime" >&2
  fi
  [ ! -e "$final" ] || die "incomplete release directory exists; inspect before retrying"

  stage="$RELEASES_DIR/.stage.$SNOW_SHA.$$"
  mkdir -m 700 "$stage"
  "$GIT_BIN" -C "$stage" init -q repo
  "$GIT_BIN" -C "$stage/repo" remote add origin "$SNOW_REPO"
  "$GIT_BIN" -C "$stage/repo" fetch -q --depth=1 origin "refs/tags/$SNOW_TAG"
  "$GIT_BIN" -C "$stage/repo" checkout -q --detach "$SNOW_SHA"
  head="$("$GIT_BIN" -C "$stage/repo" rev-parse HEAD)"
  [ "$head" = "$SNOW_SHA" ] || die "staged checkout does not match pin"

  mv "$stage" "$final"
  : >"$final/.installing"
  command -v "$UV_BIN" >/dev/null 2>&1 || die "uv is required"
  if ! (
    cd "$final/repo"
    "$UV_BIN" sync --locked --package snow-kit --no-dev --no-editable
  ); then
    rm -rf -- "$final"
    die "snow-kit dependency installation failed"
  fi
  [ -x "$candidate" ] || { rm -rf -- "$final"; die "staged snow-kit executable missing"; }
  rm -f "$final/.installing"
  printf '%s\n' "$candidate"
}

run_candidate() {
  local candidate="$1"
  shift
  env -u SNOW_KIT_ENABLE_WRITE SNOW_KIT_CONFIG_PATH="$CONFIG_PATH" \
    "$candidate" "$@"
}

offline_candidate_check() {
  local candidate="$1"
  run_candidate "$candidate" --help >/dev/null
  run_candidate "$candidate" doctor --skip-registrations \
    --binary "$candidate" --config "$CONFIG_PATH" >/dev/null
  log "candidate offline doctor: ready"
}

prepare_stable_path() {
  secure_dir "$BIN_DIR"
  secure_dir "$STATE_ROOT/backups"
  if [ -e "$STABLE_BIN" ] || [ -L "$STABLE_BIN" ]; then
    if [ -L "$STABLE_BIN" ] && [ "$(readlink "$STABLE_BIN")" = "$CURRENT_LINK/.venv/bin/snow-kit" ]; then
      return
    fi
    [ ! -e "$PRE_MANAGED_BIN" ] && [ ! -L "$PRE_MANAGED_BIN" ] ||
      die "pre-managed snow-kit binary backup already exists"
    mv "$STABLE_BIN" "$PRE_MANAGED_BIN"
    log "backed up pre-managed stable command"
  fi
}

activate_links() {
  local sha="$1" tmp_current tmp_bin
  [ -x "$RELEASES_DIR/$sha/repo/.venv/bin/snow-kit" ] || die "release $sha is not runnable"
  prepare_stable_path
  rm -f "$CURRENT_LINK"
  ln -s "releases/$sha/repo" "$CURRENT_LINK"
  tmp_bin="$BIN_DIR/.snow-kit.$$.$RANDOM"
  ln -s "$CURRENT_LINK/.venv/bin/snow-kit" "$tmp_bin"
  mv -f "$tmp_bin" "$STABLE_BIN"
}

promote_release() {
  local sha="$1" old
  old="$(read_state "$CURRENT_SHA_FILE")"
  activate_links "$sha"
  if [ -n "$old" ] && [ "$old" != "$sha" ]; then
    write_state "$PREVIOUS_SHA_FILE" "$old"
  fi
  write_state "$CURRENT_SHA_FILE" "$sha"
}

restore_release() {
  local sha="$1"
  if [ -n "$sha" ] && [ -x "$RELEASES_DIR/$sha/repo/.venv/bin/snow-kit" ]; then
    activate_links "$sha"
    write_state "$CURRENT_SHA_FILE" "$sha"
  else
    rm -f "$CURRENT_LINK"
    if [ -L "$STABLE_BIN" ] && [ "$(readlink "$STABLE_BIN")" = "$CURRENT_LINK/.venv/bin/snow-kit" ]; then
      rm -f "$STABLE_BIN"
    fi
    rm -f "$CURRENT_SHA_FILE"
  fi
}

preflight_clients() {
  local candidate="$1"
  run_candidate "$candidate" bootstrap --dry-run \
    --binary "$STABLE_BIN" --config "$CONFIG_PATH" >/dev/null
}

reconcile_clients() {
  local candidate="$1"
  run_candidate "$candidate" bootstrap \
    --binary "$STABLE_BIN" --config "$CONFIG_PATH" >/dev/null
  log "snow-kit registrations reconciled (Cursor, Codex, Claude)"
}

remove_legacy_registrations() {
  local python_bin="$1"
  "$python_bin" - "$CURSOR_CONFIG" "$CODEX_CONFIG" "$CLAUDE_CONFIG" <<'PY'
import json
import os
import shutil
import sys
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import tomli_w

cursor, codex, claude = map(Path, sys.argv[1:])
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
changed = 0

def atomic(path: Path, payload: bytes) -> None:
    target = Path(os.path.realpath(path))
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass

for path in (cursor, claude):
    if not path.exists():
        continue
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    servers = data.setdefault("mcpServers", {})
    if "snowflake" not in servers:
        continue
    shutil.copy2(path, path.with_name(f"{path.name}.bak.{stamp}"))
    del servers["snowflake"]
    atomic(path, (json.dumps(data, indent=2) + "\n").encode())
    changed += 1

if codex.exists():
    data = tomllib.loads(codex.read_text(encoding="utf-8"))
    servers = data.setdefault("mcp_servers", {})
    if "snowflake" in servers:
        shutil.copy2(codex, codex.with_name(f"{codex.name}.bak.{stamp}"))
        del servers["snowflake"]
        atomic(codex, tomli_w.dumps(data).encode())
        changed += 1

print(f"legacy snowflake registration removed from {changed} client(s); values redacted")
PY
}

install_snow_kit() {
  local activate="${1:-0}" candidate old
  load_pin
  verify_remote_pin
  acquire_lock
  trap release_lock EXIT
  migrate_profile
  candidate="$(stage_release)"
  offline_candidate_check "$candidate"

  if [ "$activate" = 1 ]; then
    log "starting external-browser SSO outside MCP"
    run_candidate "$candidate" auth login >/dev/null
    run_candidate "$candidate" doctor --live --skip-registrations \
      --binary "$candidate" --config "$CONFIG_PATH" >/dev/null
    log "candidate live doctor: ready"
  fi

  old="$(read_state "$CURRENT_SHA_FILE")"
  promote_release "$SNOW_SHA"
  if ! preflight_clients "$candidate" || ! reconcile_clients "$candidate"; then
    restore_release "$old"
    die "client reconciliation failed; previous stable command restored"
  fi

  if [ "$activate" = 1 ]; then
    remove_legacy_registrations "$RELEASES_DIR/$SNOW_SHA/repo/.venv/bin/python"
    write_state "$LKG_SHA_FILE" "$SNOW_SHA"
  fi
  trap - EXIT
  release_lock
  if [ "$activate" = 1 ]; then
    log "snow-kit ${SNOW_SHA:0:12} activated"
  else
    log "snow-kit ${SNOW_SHA:0:12} installed"
  fi
}

status_snow_kit() {
  load_pin
  local current previous lkg
  current="$(read_state "$CURRENT_SHA_FILE")"
  previous="$(read_state "$PREVIOUS_SHA_FILE")"
  lkg="$(read_state "$LKG_SHA_FILE")"
  printf 'snow-kit pin: %s @ %s\n' "$SNOW_TAG" "${SNOW_SHA:0:12}"
  printf 'snow-kit active: %s\n' "${current:-none}"
  printf 'snow-kit previous: %s\n' "${previous:-none}"
  printf 'snow-kit last-known-good: %s\n' "${lkg:-none}"
  if [ -x "$STABLE_BIN" ]; then
    env -u SNOW_KIT_ENABLE_WRITE SNOW_KIT_CONFIG_PATH="$CONFIG_PATH" "$STABLE_BIN" status
  else
    printf 'snow-kit stable command: missing\n'
    return 1
  fi
}

doctor_snow_kit() {
  local live="${1:-0}"
  local current head
  load_pin
  current="$(read_state "$CURRENT_SHA_FILE")"
  [ "$current" = "$SNOW_SHA" ] || die "active release does not match the tracked pin"
  head="$("$GIT_BIN" -C "$RELEASES_DIR/$current/repo" rev-parse HEAD 2>/dev/null || true)"
  [ "$head" = "$SNOW_SHA" ] || die "active release checkout does not match the tracked pin"
  "$GIT_BIN" -C "$RELEASES_DIR/$current/repo" diff --quiet HEAD -- ||
    die "active release source has tracked modifications"
  [ -x "$STABLE_BIN" ] || die "snow-kit stable command is missing"
  if [ "$live" = 1 ]; then
    env -u SNOW_KIT_ENABLE_WRITE SNOW_KIT_CONFIG_PATH="$CONFIG_PATH" \
      "$STABLE_BIN" doctor --live --binary "$STABLE_BIN" --config "$CONFIG_PATH"
  else
    env -u SNOW_KIT_ENABLE_WRITE SNOW_KIT_CONFIG_PATH="$CONFIG_PATH" \
      "$STABLE_BIN" doctor --binary "$STABLE_BIN" --config "$CONFIG_PATH"
  fi
}

rollback_snow_kit() {
  local current target candidate
  acquire_lock
  trap release_lock EXIT
  current="$(read_state "$CURRENT_SHA_FILE")"
  target="$(read_state "$PREVIOUS_SHA_FILE")"
  [ -n "$target" ] || die "no previous snow-kit release is recorded"
  candidate="$RELEASES_DIR/$target/repo/.venv/bin/snow-kit"
  [ -x "$candidate" ] || die "previous snow-kit release is unavailable"
  offline_candidate_check "$candidate"
  activate_links "$target"
  write_state "$CURRENT_SHA_FILE" "$target"
  [ -n "$current" ] && write_state "$PREVIOUS_SHA_FILE" "$current"
  reconcile_clients "$candidate"
  trap - EXIT
  release_lock
  log "rolled back snow-kit to ${target:0:12}"
}

uninstall_snow_kit() {
  local command_path=""
  acquire_lock
  trap release_lock EXIT
  if [ -x "$STABLE_BIN" ]; then
    command_path="$STABLE_BIN"
  elif [ -n "$(read_state "$CURRENT_SHA_FILE")" ]; then
    command_path="$RELEASES_DIR/$(read_state "$CURRENT_SHA_FILE")/repo/.venv/bin/snow-kit"
  fi
  if [ -x "$command_path" ]; then
    env -u SNOW_KIT_ENABLE_WRITE SNOW_KIT_CONFIG_PATH="$CONFIG_PATH" \
      "$command_path" unregister >/dev/null
  fi
  if [ -L "$STABLE_BIN" ] && [ "$(readlink "$STABLE_BIN")" = "$CURRENT_LINK/.venv/bin/snow-kit" ]; then
    rm -f "$STABLE_BIN"
  fi
  rm -f "$CURRENT_LINK"
  [ ! -L "$RUNTIME_ROOT" ] || die "refusing symlinked runtime root"
  [ ! -L "$STATE_ROOT" ] || die "refusing symlinked state root"
  rm -rf -- "$RUNTIME_ROOT"
  if [ -e "$PRE_MANAGED_BIN" ] || [ -L "$PRE_MANAGED_BIN" ]; then
    mv "$PRE_MANAGED_BIN" "$STABLE_BIN"
  fi
  trap - EXIT
  release_lock
  rm -rf -- "$STATE_ROOT"
  log "snow-kit uninstalled; profile and Snowflake secure authentication cache preserved"
}

full_bootstrap() {
  load_pin
  if [ -e "$MCP_DIR/.git" ]; then
    python3 "$SOURCE_IDENTITY" KleinPerkins/kp-mcp --repository "$MCP_DIR" --revision "$SNOW_SHA" >/dev/null
    log "kp-mcp present at $MCP_DIR (leaving checkout as-is)"
  elif [ -e "$MCP_DIR" ]; then
    die "$MCP_DIR exists but is not a git repo"
  else
    if [ -z "$MCP_REPO_URL" ]; then
      MCP_REPO_URL="$(python3 "$SOURCE_IDENTITY" KleinPerkins/kp-mcp)"
    else
      python3 "$SOURCE_IDENTITY" KleinPerkins/kp-mcp --url "$MCP_REPO_URL" >/dev/null
    fi
    log "cloning kp-mcp capability source"
    "$GIT_BIN" clone "$MCP_REPO_URL" "$MCP_DIR"
    python3 "$SOURCE_IDENTITY" KleinPerkins/kp-mcp --repository "$MCP_DIR" --revision "$SNOW_SHA" >/dev/null
  fi

  if command -v "$UV_BIN" >/dev/null 2>&1; then
    (cd "$MCP_DIR" && "$UV_BIN" sync)
  else
    log "WARN: uv not found; development workspace sync skipped"
  fi

  shopt -s nullglob
  local d kit
  for d in "$MCP_DIR"/*/; do
    [ -f "${d}meta.yml" ] || continue
    [ -x "${d}install.sh" ] || continue
    kit="$(basename "${d%/}")"
    [ "$kit" = "snow-kit" ] && continue
    log "install: $kit"
    bash "${d}install.sh" || log "WARN: $kit install returned non-zero"
  done
  shopt -u nullglob

  install_snow_kit 0
  log "done (noninteractive; no browser opened)"
}

usage() {
  cat <<'EOF'
usage:
  capabilities/mcp-bootstrap.sh
  capabilities/mcp-bootstrap.sh install|repin snow-kit [--activate]
  capabilities/mcp-bootstrap.sh status snow-kit
  capabilities/mcp-bootstrap.sh doctor snow-kit [--live]
  capabilities/mcp-bootstrap.sh repair|rollback|uninstall snow-kit
EOF
}

validate_managed_layout

# Hold the same cooperative barrier for the entire mutating lifecycle, before
# profile, package, links, registration or legacy-deletion work. No force bypass.
# Read-only status/doctor retain their existing behavior.
case "${1:-}" in
  status|doctor) ;;
  *)
    MAINTENANCE="$CAP_ROOT/../_ops/interoperability/mcp_maintenance.py"
    if ! command -v python3 >/dev/null 2>&1 || [ ! -r "$MAINTENANCE" ]; then
      log "maintenance guard unavailable; refusing legacy writer"
      exit 73
    fi
    if [ -z "${DEV_MCP_MAINTENANCE_LOCK_FD+x}" ]; then
      exec python3 "$MAINTENANCE" legacy-enter snow "$0" "$@"
    fi
    python3 "$MAINTENANCE" legacy-enter snow "$0" "$@" || exit 73
    ;;
esac

if [ "$#" -eq 0 ]; then
  full_bootstrap
  exit 0
fi

verb="$1"
kit="${2:-}"
[ "$kit" = "snow-kit" ] || { usage >&2; exit 2; }
case "$verb" in
  install|repin)
    case "${3:-}" in
      "") install_snow_kit 0 ;;
      --activate) install_snow_kit 1 ;;
      *) usage >&2; exit 2 ;;
    esac
    ;;
  repair) [ "$#" -eq 2 ] || { usage >&2; exit 2; }; install_snow_kit 0 ;;
  status) [ "$#" -eq 2 ] || { usage >&2; exit 2; }; status_snow_kit ;;
  doctor)
    case "${3:-}" in
      "") doctor_snow_kit 0 ;;
      --live) doctor_snow_kit 1 ;;
      *) usage >&2; exit 2 ;;
    esac
    ;;
  rollback) [ "$#" -eq 2 ] || { usage >&2; exit 2; }; rollback_snow_kit ;;
  uninstall) [ "$#" -eq 2 ] || { usage >&2; exit 2; }; uninstall_snow_kit ;;
  *) usage >&2; exit 2 ;;
esac
