#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
BINDING_DIR="$(CDPATH= cd -- "$TEST_DIR/.." && pwd -P)"
INSTALLER="$BINDING_DIR/install.sh"
PIN="$BINDING_DIR/gsd-core-pin.json"
LOCK="$BINDING_DIR/package-lock.json"
INTERFACE="$BINDING_DIR/runtime-interface.v1.json"

fail() {
  printf 'verify-binding: FAIL: %s\n' "$*" >&2
  exit 1
}

digest_or_absent() {
  if test -f "$1"; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    printf 'absent\n'
  fi
}

expect_check_failure() {
  label="$1"
  expression="$2"
  replacement="$3"
  fixture="$WORK_ROOT/$label"
  mkdir -p "$fixture"
  cp "$BINDING_DIR/package.json" "$LOCK" "$PIN" "$INTERFACE" "$INSTALLER" "$fixture/"
  python3 - "$fixture" "$expression" "$replacement" <<'PY'
import json, os, sys
root, expression, replacement = sys.argv[1:]
filename, dotted = expression.split(":", 1)
path = os.path.join(root, filename)
value = json.load(open(path, encoding="utf-8"))
target = value
parts = dotted.split("/")
for part in parts[:-1]:
    target = target[part]
try:
    parsed = json.loads(replacement)
except json.JSONDecodeError:
    parsed = replacement
target[parts[-1]] = parsed
with open(path, "w", encoding="utf-8") as handle:
    json.dump(value, handle, indent=2)
    handle.write("\n")
PY
  if HOME="$ISOLATED_HOME" XDG_DATA_HOME="$ISOLATED_HOME/.local/share" \
    XDG_CONFIG_HOME="$ISOLATED_HOME/.config" bash "$fixture/install.sh" --check \
    >"$fixture/output" 2>&1; then
    fail "$label mutation was accepted"
  fi
}

expect_script_failure() {
  label="$1"
  needle="$2"
  replacement="$3"
  fixture="$WORK_ROOT/$label"
  mkdir -p "$fixture"
  cp "$BINDING_DIR/package.json" "$LOCK" "$PIN" "$INTERFACE" "$INSTALLER" "$fixture/"
  python3 - "$fixture/install.sh" "$needle" "$replacement" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1])
value = path.read_text(encoding="utf-8")
if sys.argv[2] not in value:
    raise SystemExit("mutation needle missing")
path.write_text(value.replace(sys.argv[2], sys.argv[3], 1), encoding="utf-8")
PY
  if HOME="$ISOLATED_HOME" XDG_DATA_HOME="$ISOLATED_HOME/.local/share" \
    XDG_CONFIG_HOME="$ISOLATED_HOME/.config" bash "$fixture/install.sh" --check \
    >"$fixture/output" 2>&1; then
    fail "$label mutation was accepted"
  fi
}

test -f "$PIN" || fail "gsd-core-pin.json missing"
test -f "$INSTALLER" || fail "install.sh missing"
test -f "$LOCK" || fail "package-lock.json missing"
test -f "$INTERFACE" || fail "runtime-interface.v1.json missing"

bash "$INSTALLER" --check

python3 - "$PIN" "$LOCK" "$INTERFACE" "$INSTALLER" <<'PY'
import json, pathlib, sys
pin = json.load(open(sys.argv[1], encoding="utf-8"))
lock = json.load(open(sys.argv[2], encoding="utf-8"))
interface = json.load(open(sys.argv[3], encoding="utf-8"))
installer = pathlib.Path(sys.argv[4]).read_text(encoding="utf-8")

assert pin["package"] == "@opengsd/gsd-core"
assert pin["version"] == "1.11.0"
assert pin["git_commit"] == "182f60b4c170785d96f1deb87fea8b108e9b985f"
assert pin["npm_integrity"] == "sha512-z1RLWsQshYViJIk94SB0x9/AYPykj5LIuLxwjS0s+WgaCBgVtTknCsVR3x4itrBeqmiUEvGiN6cO/bOay0zOiQ=="
assert pin["license"]["spdx"] == "MIT"
assert pin["license"]["copyright"] == "Copyright (c) 2026 Open GSD"
assert pin["runtime_defaults"] == {
    "workflow.use_worktrees": False,
    "git.branching_strategy": "none",
    "git.create_tag": False,
}
assert interface["supported_scope"] == "authoring_context_only"
assert "gsd-ship" in interface["excluded_workflows"]
assert "gsd_run" in interface["excluded_commands"]
assert "npm ci --ignore-scripts" in installer
assert "--cursor --global --config-dir" in installer
assert "DOC_WARDEN_ALLOW_LIVE_HOME" in installer

packages = lock["packages"]
core = packages["node_modules/@opengsd/gsd-core"]
assert core["version"] == "1.11.0"
assert core["integrity"] == pin["npm_integrity"]
for path, package in packages.items():
    if not path:
        continue
    assert package.get("version"), f"{path}: missing exact version"
    assert package.get("integrity") or package.get("link"), f"{path}: missing integrity"
PY

WORK_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/doc-warden-gsd-binding.XXXXXX")"
ISOLATED_HOME="$WORK_ROOT/home"
mkdir -p "$ISOLATED_HOME"
trap 'rm -rf "$WORK_ROOT"' EXIT HUP INT TERM

expect_check_failure version 'gsd-core-pin.json:version' '"0.0.0"'
expect_check_failure commit 'gsd-core-pin.json:git_commit' '"0000000000000000000000000000000000000000"'
expect_check_failure integrity 'gsd-core-pin.json:npm_integrity' '"sha512-wrong"'
expect_check_failure worktree 'gsd-core-pin.json:runtime_defaults/workflow.use_worktrees' 'true'
expect_check_failure branching 'gsd-core-pin.json:runtime_defaults/git.branching_strategy' '"feature"'
expect_check_failure tag 'gsd-core-pin.json:runtime_defaults/git.create_tag' 'true'
expect_check_failure scope 'runtime-interface.v1.json:supported_scope' '"autonomous"'
expect_script_failure lifecycle-policy 'npm ci --ignore-scripts --omit=dev' 'npm ci --omit=dev'
expect_script_failure isolation-gate 'DOC_WARDEN_ALLOW_LIVE_HOME' 'DOC_WARDEN_LIVE_BYPASS'
expect_script_failure native-installer '--cursor --global --config-dir' '--cursor --local --config-dir'

REAL_HOME="${HOME:?HOME is required}"
REAL_HOOK_SENTINEL="$(digest_or_absent "$REAL_HOME/.cursor/hooks.json")"
REAL_SKILL_SENTINEL="$(digest_or_absent "$REAL_HOME/.cursor/skills/gsd-plan-phase/SKILL.md")"

export HOME="$ISOLATED_HOME"
export XDG_CONFIG_HOME="$ISOLATED_HOME/.config"
export XDG_DATA_HOME="$ISOLATED_HOME/.local/share"
export XDG_STATE_HOME="$ISOLATED_HOME/.local/state"
export XDG_CACHE_HOME="$ISOLATED_HOME/.cache"

bash "$INSTALLER" --apply
bash "$INSTALLER" --doctor
test ! -e "$HOME/.cursor/skills/gsd-autonomous" ||
  fail "autonomous skill was exposed"
test ! -e "$HOME/.cursor/skills/gsd-execute-phase" ||
  fail "execution skill was exposed"
test ! -e "$HOME/.cursor/skills/gsd-ship" ||
  fail "shipping skill was exposed"
test ! -e "$HOME/.cursor/commands/gsd-autonomous.md" ||
  fail "autonomous command was exposed"
test ! -e "$HOME/.cursor/commands/gsd-execute-phase.md" ||
  fail "execution command was exposed"
test ! -e "$HOME/.cursor/commands/gsd-ship.md" ||
  fail "shipping command was exposed"
if "$HOME/.local/bin/gsd_run" >/dev/null 2>&1; then
  fail "gsd_run agentic interface was exposed"
fi
if "$HOME/.local/bin/gsd-tools" git status >/dev/null 2>&1; then
  fail "mutable gsd-tools command was exposed"
fi
if "$HOME/.local/bin/gsd-tools" requirements mark-complete REQ-001 >/dev/null 2>&1; then
  fail "requirements mutation was exposed"
fi
if "$HOME/.local/bin/gsd-tools" phases clear --confirm >/dev/null 2>&1; then
  fail "phase mutation was exposed"
fi
if "$HOME/.local/bin/gsd-tools" validate health --repair >/dev/null 2>&1; then
  fail "validation repair mutation was exposed"
fi

INSTALLED_PACKAGE="$XDG_DATA_HOME/gsd-core/releases/182f60b4c170785d96f1deb87fea8b108e9b985f/node_modules/@opengsd/gsd-core/package.json"
python3 - "$INSTALLED_PACKAGE" <<'PY'
import json, sys
path = sys.argv[1]
value = json.load(open(path, encoding="utf-8"))
value["version"] = "0.0.0"
with open(path, "w", encoding="utf-8") as handle:
    json.dump(value, handle)
PY
if bash "$INSTALLER" --doctor >/dev/null 2>&1; then
  fail "doctor accepted a corrupted installed version"
fi
bash "$INSTALLER" --repair

MANIFEST="$XDG_DATA_HOME/gsd-core/doc-warden-manifest.json"
cp "$MANIFEST" "$WORK_ROOT/manifest.backup"
python3 - "$MANIFEST" <<'PY'
import json, sys
path = sys.argv[1]
value = json.load(open(path, encoding="utf-8"))
value["owner"] = "foreign"
with open(path, "w", encoding="utf-8") as handle:
    json.dump(value, handle)
PY
if bash "$INSTALLER" --uninstall >/dev/null 2>&1; then
  fail "uninstall ignored a manifest identity mismatch"
fi
cp "$WORK_ROOT/manifest.backup" "$MANIFEST"
python3 - "$HOME/.gsd/defaults.json" <<'PY'
import json, sys
path = sys.argv[1]
value = json.load(open(path, encoding="utf-8"))
value["workflow"]["use_worktrees"] = True
with open(path, "w", encoding="utf-8") as handle:
    json.dump(value, handle)
PY
if bash "$INSTALLER" --uninstall >/dev/null 2>&1; then
  fail "uninstall overwrote an operator-changed runtime default"
fi
test -f "$HOME/.cursor/skills/gsd-plan-phase/SKILL.md" ||
  fail "failed uninstall partially removed the Cursor integration"
python3 - "$HOME/.gsd/defaults.json" <<'PY'
import json, sys
path = sys.argv[1]
value = json.load(open(path, encoding="utf-8"))
value["workflow"]["use_worktrees"] = False
with open(path, "w", encoding="utf-8") as handle:
    json.dump(value, handle)
PY
rm "$XDG_DATA_HOME/gsd-core/releases/182f60b4c170785d96f1deb87fea8b108e9b985f/node_modules/@opengsd/gsd-core/bin/install.js"
bash "$INSTALLER" --uninstall
bash "$INSTALLER" --uninstall

test ! -e "$ISOLATED_HOME/.local/share/gsd-core/doc-warden-manifest.json" ||
  fail "manifest remained after uninstall"
test ! -e "$ISOLATED_HOME/.local/share/gsd-core/releases/182f60b4c170785d96f1deb87fea8b108e9b985f" ||
  fail "release remained after uninstall"
test ! -e "$ISOLATED_HOME/.local/bin/gsd-core" || fail "gsd-core shim remained"
test ! -e "$ISOLATED_HOME/.local/bin/gsd-tools" || fail "gsd-tools shim remained"
test ! -e "$ISOLATED_HOME/.local/bin/gsd_run" || fail "gsd_run shim remained"
test ! -e "$ISOLATED_HOME/.gsd/defaults.json" || fail "GSD defaults preimage was not restored"

PREEXISTING_HOME="$WORK_ROOT/preexisting-home"
mkdir -p "$PREEXISTING_HOME/.gsd"
printf '%s\n' '{"resolve_model_ids":"keep","runtime":"custom","unrelated":{"keep":true}}' \
  >"$PREEXISTING_HOME/.gsd/defaults.json"
PREEXISTING_DIGEST="$(digest_or_absent "$PREEXISTING_HOME/.gsd/defaults.json")"
export HOME="$PREEXISTING_HOME"
export XDG_CONFIG_HOME="$PREEXISTING_HOME/.config"
export XDG_DATA_HOME="$PREEXISTING_HOME/.local/share"
export XDG_STATE_HOME="$PREEXISTING_HOME/.local/state"
export XDG_CACHE_HOME="$PREEXISTING_HOME/.cache"
bash "$INSTALLER" --apply >/dev/null
cp "$WORK_ROOT/preexisting-home/.local/share/gsd-core/preimages/gsd-defaults.json" \
  "$PREEXISTING_HOME/.gsd/defaults.json"
bash "$INSTALLER" --uninstall >/dev/null
test "$(digest_or_absent "$PREEXISTING_HOME/.gsd/defaults.json")" = "$PREEXISTING_DIGEST" ||
  fail "pre-existing GSD defaults were not restored byte-for-byte"

test "$(digest_or_absent "$REAL_HOME/.cursor/hooks.json")" = "$REAL_HOOK_SENTINEL" ||
  fail "real HOME hook sentinel changed"
test "$(digest_or_absent "$REAL_HOME/.cursor/skills/gsd-plan-phase/SKILL.md")" = "$REAL_SKILL_SENTINEL" ||
  fail "real HOME skill sentinel changed"

printf 'verify-binding: PASS\n'
