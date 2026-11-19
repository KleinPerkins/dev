#!/usr/bin/env bash
# Hermetic LD-host snow-kit lifecycle regression. Uses temp HOME, local git, and fake uv.
set -euo pipefail

# Pre-commit runs with GIT_DIR/GIT_INDEX_FILE and friends set for the parent repo. The
# disposable $SOURCE fixture repo below must use its own git metadata, not the parent's --
# otherwise `git init` here silently re-initializes the parent repo instead (see
# worktree-verify.sh for the same guard).
unset BASH_ENV
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES 2>/dev/null || true

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
SUT="$ROOT/capabilities/mcp-bootstrap.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { printf 'snow-kit-host-test: FAIL: %s\n' "$*" >&2; exit 1; }
assert_file() { [ -f "$1" ] || fail "missing file: $1"; }
assert_absent() { [ ! -e "$1" ] && [ ! -L "$1" ] || fail "unexpected path: $1"; }

SOURCE="$TMP/source repo"
mkdir -p "$SOURCE"
git -C "$SOURCE" init -q -b main
printf 'fixture\n' >"$SOURCE/README.md"
printf 'version = 1\n' >"$SOURCE/uv.lock"
printf '[tool.uv]\npackage = false\n[tool.uv.workspace]\nmembers = []\n' >"$SOURCE/pyproject.toml"
git -C "$SOURCE" add README.md uv.lock pyproject.toml
git -C "$SOURCE" -c user.name=Fixture -c user.email=fixture@example.invalid \
  commit -q -m "fixture v1"
SHA1="$(git -C "$SOURCE" rev-parse HEAD)"
git -C "$SOURCE" tag snow-kit-v0.1.0
git -C "$SOURCE" remote add origin git@github.com:KleinPerkins/kp-mcp.git

# Exercise production source verification against a real synthetic original
# history. Only the disposable helper's identity anchor is replaced; runtime
# release pins remain separate inputs and cannot replace this source anchor.
FIXTURE_DEV="$TMP/dev"
mkdir -p "$FIXTURE_DEV/capabilities" "$FIXTURE_DEV/_ops/interoperability"
cp "$ROOT/capabilities/mcp-bootstrap.sh" "$FIXTURE_DEV/capabilities/"
cp "$ROOT/capabilities/mcp-pins.env" "$FIXTURE_DEV/capabilities/"
for helper in original_sources.py inventory.py mcp_maintenance.py; do
  cp "$ROOT/_ops/interoperability/$helper" "$FIXTURE_DEV/_ops/interoperability/"
done
python3 - "$FIXTURE_DEV/_ops/interoperability/original_sources.py" "$SHA1" <<'PY_SOURCE'
from pathlib import Path
import sys
path = Path(sys.argv[1])
path.write_text(path.read_text().replace('7594346fbb09161749d21624b35cf5a173c84958', sys.argv[2]))
PY_SOURCE
SUT="$FIXTURE_DEV/capabilities/mcp-bootstrap.sh"

FAKE="$TMP/fake"
mkdir -p "$FAKE"
cat >"$FAKE/tomli_w.py" <<'PY'
def _value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'

def dumps(data):
    lines = []
    def visit(prefix, table):
        scalars = {key: value for key, value in table.items() if not isinstance(value, dict)}
        children = {key: value for key, value in table.items() if isinstance(value, dict)}
        if prefix and scalars:
            lines.append(f"[{prefix}]")
            for key, value in scalars.items():
                lines.append(f"{key} = {_value(value)}")
            lines.append("")
        for key, child in children.items():
            visit(f"{prefix}.{key}" if prefix else key, child)
    visit("", data)
    return "\n".join(lines).rstrip() + "\n"
PY

cat >"$FAKE/fake_snow.py" <<'PY'
import json
import os
import sys
import tempfile
import tomllib
from pathlib import Path

import tomli_w

args = sys.argv[1:]
log_path = os.environ.get("SNOW_KIT_TEST_LOG")
if log_path:
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(" ".join(args) + "\n")
if os.environ.get("SNOW_KIT_ENABLE_WRITE"):
    raise SystemExit(91)

def option(name, default=None):
    try:
        return args[args.index(name) + 1]
    except (ValueError, IndexError):
        return default

def atomic(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass

cursor = Path(os.environ["SNOW_KIT_CURSOR_CONFIG"])
codex = Path(os.environ["SNOW_KIT_CODEX_CONFIG"])
claude = Path(os.environ["SNOW_KIT_CLAUDE_CONFIG"])
config = option("--config", os.environ["SNOW_KIT_CONFIG_PATH"])
binary = option("--binary", sys.argv[0])

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

def read_toml(path):
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

def register():
    entry = {
        "command": binary,
        "args": ["mcp", "--read-only"],
        "env": {"SNOW_KIT_CONFIG_PATH": config},
    }
    for path, claude_mode in ((cursor, False), (claude, True)):
        data = read_json(path)
        servers = data.setdefault("mcpServers", {})
        servers["snow-kit"] = {"type": "stdio", **entry} if claude_mode else entry
        atomic(path, (json.dumps(data, indent=2) + "\n").encode())
    data = read_toml(codex)
    data.setdefault("mcp_servers", {})["snow-kit"] = entry
    atomic(codex, tomli_w.dumps(data).encode())

def unregister():
    for path in (cursor, claude):
        if not path.exists():
            continue
        data = read_json(path)
        data.setdefault("mcpServers", {}).pop("snow-kit", None)
        atomic(path, (json.dumps(data, indent=2) + "\n").encode())
    if codex.exists():
        data = read_toml(codex)
        data.setdefault("mcp_servers", {}).pop("snow-kit", None)
        atomic(codex, tomli_w.dumps(data).encode())

command = args[0] if args else "--help"
if command in ("--help", "status"):
    print('{"ready":true,"write_posture":"fail-closed-read-only"}')
elif command == "doctor":
    if "--live" in args and os.environ.get("SNOW_KIT_TEST_FAIL_LIVE"):
        raise SystemExit(42)
    for path, kind in ((cursor, "json"), (codex, "toml"), (claude, "json")):
        if path.exists():
            read_json(path) if kind == "json" else read_toml(path)
    print('{"ready":true}')
elif command == "auth":
    if len(args) < 2 or args[1] != "login":
        raise SystemExit(2)
    print('{"status":"connected"}')
elif command == "bootstrap":
    for path, kind in ((cursor, "json"), (codex, "toml"), (claude, "json")):
        if path.exists():
            read_json(path) if kind == "json" else read_toml(path)
    if os.environ.get("SNOW_KIT_TEST_FAIL_BOOTSTRAP"):
        raise SystemExit(43)
    if "--dry-run" not in args:
        register()
    print('{"ready":true}')
elif command == "unregister":
    unregister()
    print('{"ready":true}')
else:
    raise SystemExit(2)
PY

cat >"$FAKE/uv" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" != sync ]; then exit 0; fi
mkdir -p .venv/bin .venv/libfake
cp "$SNOW_KIT_TEST_FAKE_SNOW" .venv/fake_snow.py
cp "$SNOW_KIT_TEST_FAKE_TOMLI" .venv/libfake/tomli_w.py
cat >.venv/bin/snow-kit <<'EOF'
#!/usr/bin/env bash
SCRIPT="$0"
while [ -L "$SCRIPT" ]; do
  TARGET="$(readlink "$SCRIPT")"
  case "$TARGET" in /*) SCRIPT="$TARGET" ;; *) SCRIPT="$(dirname "$SCRIPT")/$TARGET" ;; esac
done
HERE="$(cd "$(dirname "$SCRIPT")/.." && pwd)"
PYTHONPATH="$HERE/libfake${PYTHONPATH:+:$PYTHONPATH}" exec python3 "$HERE/fake_snow.py" "$@"
EOF
cat >.venv/bin/python <<'EOF'
#!/usr/bin/env bash
SCRIPT="$0"
while [ -L "$SCRIPT" ]; do
  TARGET="$(readlink "$SCRIPT")"
  case "$TARGET" in /*) SCRIPT="$TARGET" ;; *) SCRIPT="$(dirname "$SCRIPT")/$TARGET" ;; esac
done
HERE="$(cd "$(dirname "$SCRIPT")/.." && pwd)"
PYTHONPATH="$HERE/libfake${PYTHONPATH:+:$PYTHONPATH}" exec python3 "$@"
EOF
chmod +x .venv/bin/snow-kit .venv/bin/python
SH
chmod +x "$FAKE/uv"

HOME_DIR="$TMP/home"
PIN="$TMP/pins.env"
LOG="$TMP/commands.log"
mkdir -p "$HOME_DIR/.cursor" "$HOME_DIR/.codex"
cat >"$HOME_DIR/.cursor/mcp.json" <<'JSON'
{
  "mcpServers": {
    "sibling": {"command": "/sibling"},
    "snow-kit": {
      "command": "/old/snow-kit",
      "args": ["mcp"],
      "env": {
        "SNOW_KIT_ACCOUNT": "example-account",
        "SNOW_KIT_USER": "operator@example.invalid",
        "SNOW_KIT_ENABLE_WRITE": "1"
      }
    },
    "snowflake": {"command": "/legacy"}
  }
}
JSON
cat >"$HOME_DIR/.claude.json" <<'JSON'
{"mcpServers":{"sibling":{"command":"/sibling"},"snowflake":{"command":"/legacy"}}}
JSON
cat >"$HOME_DIR/.codex/config.toml" <<'TOML'
[mcp_servers.sibling]
command = "/sibling"

[mcp_servers.snowflake]
command = "/legacy"
TOML

write_pin() {
  local tag="$1" sha="$2"
  cat >"$PIN" <<EOF
SNOW_KIT_REPO=git@github.com:KleinPerkins/kp-mcp.git
SNOW_KIT_TAG=$tag
SNOW_KIT_SHA=$sha
EOF
}
write_pin snow-kit-v0.1.0 "$SHA1"

export HOME="$HOME_DIR"
# All Git/API traffic stays in this disposable fixture. The production resolver
# still receives the original immutable ID and exact allowed GitHub endpoint.
cat >"$FAKE/gh" <<'SH'
#!/usr/bin/env bash
[ "$*" = "api /repositories/1271164179" ] || exit 91
printf '%s\n' '{"id":1271164179,"full_name":"KleinPerkins/kp-mcp","private":true}'
SH
chmod +x "$FAKE/gh"
export PATH="$FAKE:$PATH"
export SNOW_KIT_TEST_SOURCE="$SOURCE"
export SNOW_KIT_TEST_REAL_GIT="$(command -v git)"
cat >"$FAKE/source-git" <<'SH'
#!/bin/bash
exec "$SNOW_KIT_TEST_REAL_GIT" -c "url.$SNOW_KIT_TEST_SOURCE.insteadOf=git@github.com:KleinPerkins/kp-mcp.git" "$@"
SH
chmod +x "$FAKE/source-git"
export SNOW_KIT_GIT_BIN="$FAKE/source-git"

export SNOW_KIT_PIN_FILE="$PIN"
export SNOW_KIT_UV_BIN="$FAKE/uv"
export SNOW_KIT_TEST_FAKE_SNOW="$FAKE/fake_snow.py"
export SNOW_KIT_TEST_FAKE_TOMLI="$FAKE/tomli_w.py"
export SNOW_KIT_TEST_LOG="$LOG"
export SNOW_KIT_CURSOR_CONFIG="$HOME/.cursor/mcp.json"
export SNOW_KIT_CODEX_CONFIG="$HOME/.codex/config.toml"
export SNOW_KIT_CLAUDE_CONFIG="$HOME/.claude.json"
export SNOW_KIT_RUNTIME_ROOT="$HOME/.local/share/kp-mcp/snow-kit"
export SNOW_KIT_STATE_ROOT="$HOME/.local/state/snow-kit"
export SNOW_KIT_BIN_DIR="$HOME/.local/bin"
export SNOW_KIT_CONFIG_PATH="$HOME/.config/snow-kit/config.env"
export KP_MCP_DIR_OVERRIDE="$SOURCE"

# Install is idempotent, migrates only allowlisted values, and strips poisoned write env.
SNOW_KIT_ENABLE_WRITE=1 bash "$SUT" install snow-kit >/dev/null
[ "$(cat "$HOME/.local/state/snow-kit/current-sha")" = "$SHA1" ] || fail "wrong active SHA"
bash "$SUT" doctor snow-kit >/dev/null || fail "offline doctor failed"
assert_file "$HOME/.config/snow-kit/config.env"
if stat -f '%Lp' "$HOME/.config/snow-kit/config.env" >/dev/null 2>&1; then
  mode="$(stat -f '%Lp' "$HOME/.config/snow-kit/config.env")"
else
  mode="$(stat -c '%a' "$HOME/.config/snow-kit/config.env")"
fi
[ "$mode" = 600 ] || fail "profile mode is $mode"
if grep -q 'SNOW_KIT_ENABLE_WRITE' "$HOME/.config/snow-kit/config.env"; then
  fail "write flag migrated into profile"
fi

# A live install lock blocks a concurrent writer.
mkdir "$HOME/.local/state/snow-kit/install.lock"
printf '%s\n' "$$" >"$HOME/.local/state/snow-kit/install.lock/pid"
if bash "$SUT" repin snow-kit >/dev/null 2>&1; then fail "live install lock was ignored"; fi
rm -f "$HOME/.local/state/snow-kit/install.lock/pid"
rmdir "$HOME/.local/state/snow-kit/install.lock"

bash "$SUT" repin snow-kit >/dev/null
[ "$(cat "$HOME/.local/state/snow-kit/current-sha")" = "$SHA1" ] || fail "repin drifted"

# Repair reconstructs a damaged managed runtime at the same immutable pin.
printf '#!/usr/bin/env bash\nexit 99\n' \
  >"$HOME/.local/share/kp-mcp/snow-kit/releases/$SHA1/repo/.venv/bin/snow-kit"
chmod +x "$HOME/.local/share/kp-mcp/snow-kit/releases/$SHA1/repo/.venv/bin/snow-kit"
bash "$SUT" repair snow-kit >/dev/null
"$HOME/.local/bin/snow-kit" --help >/dev/null || fail "repair did not rebuild runtime"

python3 - "$HOME/.cursor/mcp.json" "$HOME/.codex/config.toml" "$HOME/.claude.json" <<'PY'
import json, sys, tomllib
from pathlib import Path
cursor, codex, claude = map(Path, sys.argv[1:])
for data in (json.loads(cursor.read_text()), json.loads(claude.read_text())):
    assert "sibling" in data["mcpServers"]
    entry = data["mcpServers"]["snow-kit"]
    assert entry["args"] == ["mcp", "--read-only"]
    assert set(entry["env"]) == {"SNOW_KIT_CONFIG_PATH"}
codex_data = tomllib.loads(codex.read_text())
assert "sibling" in codex_data["mcp_servers"]
entry = codex_data["mcp_servers"]["snow-kit"]
assert entry["args"] == ["mcp", "--read-only"]
assert set(entry["env"]) == {"SNOW_KIT_CONFIG_PATH"}
PY

# Pin mismatch fails before changing the active release.
write_pin snow-kit-v0.1.0 0000000000000000000000000000000000000000
if bash "$SUT" install snow-kit >/dev/null 2>&1; then fail "bad pin unexpectedly installed"; fi
[ "$(cat "$HOME/.local/state/snow-kit/current-sha")" = "$SHA1" ] || fail "bad pin changed active release"
write_pin snow-kit-v0.1.0 "$SHA1"

# Install a second immutable release, then rollback.
printf 'v2\n' >>"$SOURCE/README.md"
git -C "$SOURCE" add README.md
git -C "$SOURCE" -c user.name=Fixture -c user.email=fixture@example.invalid \
  commit -q -m "fixture v2"
SHA2="$(git -C "$SOURCE" rev-parse HEAD)"
git -C "$SOURCE" tag snow-kit-v0.1.1
write_pin snow-kit-v0.1.1 "$SHA2"
bash "$SUT" install snow-kit >/dev/null
[ "$(cat "$HOME/.local/state/snow-kit/current-sha")" = "$SHA2" ] || fail "v2 not active"
bash "$SUT" rollback snow-kit >/dev/null
[ "$(cat "$HOME/.local/state/snow-kit/current-sha")" = "$SHA1" ] || fail "rollback failed"

# A post-promotion client failure restores the prior active release.
bash "$SUT" install snow-kit >/dev/null
[ "$(cat "$HOME/.local/state/snow-kit/current-sha")" = "$SHA2" ] || fail "v2 reactivation failed"
printf 'v3\n' >>"$SOURCE/README.md"
git -C "$SOURCE" add README.md
git -C "$SOURCE" -c user.name=Fixture -c user.email=fixture@example.invalid \
  commit -q -m "fixture v3"
SHA3="$(git -C "$SOURCE" rev-parse HEAD)"
git -C "$SOURCE" tag snow-kit-v0.1.2
write_pin snow-kit-v0.1.2 "$SHA3"
if SNOW_KIT_TEST_FAIL_BOOTSTRAP=1 bash "$SUT" install snow-kit >/dev/null 2>&1; then
  fail "client failure unexpectedly succeeded"
fi
[ "$(cat "$HOME/.local/state/snow-kit/current-sha")" = "$SHA2" ] ||
  fail "client failure did not restore prior release"

# Live activation succeeds before legacy removal and records last-known-good.
write_pin snow-kit-v0.1.1 "$SHA2"
ACTIVATION_OUT="$TMP/activation.out"
bash "$SUT" install snow-kit --activate >"$ACTIVATION_OUT"
grep -q 'candidate live doctor: ready' "$ACTIVATION_OUT" ||
  fail "live doctor did not precede activation"
grep -q 'legacy snowflake registration removed' "$ACTIVATION_OUT" ||
  fail "legacy removal missing"
[ "$(cat "$HOME/.local/state/snow-kit/last-known-good-sha")" = "$SHA2" ] ||
  fail "last-known-good missing"
python3 - "$HOME/.cursor/mcp.json" "$HOME/.codex/config.toml" "$HOME/.claude.json" <<'PY'
import json, sys, tomllib
from pathlib import Path
cursor, codex, claude = map(Path, sys.argv[1:])
assert "snowflake" not in json.loads(cursor.read_text())["mcpServers"]
assert "snowflake" not in tomllib.loads(codex.read_text())["mcp_servers"]
assert "snowflake" not in json.loads(claude.read_text())["mcpServers"]
PY

# A failed live candidate never promotes or removes/restores legacy state.
before="$(cat "$HOME/.local/state/snow-kit/current-sha")"
if SNOW_KIT_TEST_FAIL_LIVE=1 bash "$SUT" install snow-kit --activate >/dev/null 2>&1; then
  fail "failed live candidate unexpectedly succeeded"
fi
[ "$(cat "$HOME/.local/state/snow-kit/current-sha")" = "$before" ] ||
  fail "failed live candidate changed active release"

# Historical no-argument bootstrap stays noninteractive.
: >"$LOG"
bash "$SUT" >/dev/null
# Reuse the existing root uv environment on a second no-argument bootstrap.
bash "$SUT" >/dev/null
if grep -q '^auth login' "$LOG"; then fail "no-arg bootstrap opened auth"; fi

# Uninstall removes only managed runtime/registrations and preserves config.
bash "$SUT" uninstall snow-kit >/dev/null
assert_absent "$HOME/.local/share/kp-mcp/snow-kit"
assert_absent "$HOME/.local/state/snow-kit"
assert_absent "$HOME/.local/bin/snow-kit"
assert_file "$HOME/.config/snow-kit/config.env"
python3 - "$HOME/.cursor/mcp.json" "$HOME/.codex/config.toml" "$HOME/.claude.json" <<'PY'
import json, sys, tomllib
from pathlib import Path
cursor, codex, claude = map(Path, sys.argv[1:])
for data in (json.loads(cursor.read_text()), json.loads(claude.read_text())):
    assert "snow-kit" not in data["mcpServers"]
    assert "sibling" in data["mcpServers"]
codex_data = tomllib.loads(codex.read_text())
assert "snow-kit" not in codex_data["mcp_servers"]
assert "sibling" in codex_data["mcp_servers"]
PY

printf 'snow-kit-host-test: OK\n'
