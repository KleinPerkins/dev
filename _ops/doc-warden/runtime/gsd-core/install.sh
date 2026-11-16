#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
PIN_FILE="$SCRIPT_DIR/gsd-core-pin.json"
LOCK_FILE="$SCRIPT_DIR/package-lock.json"
PACKAGE_FILE="$SCRIPT_DIR/package.json"
INTERFACE_FILE="$SCRIPT_DIR/runtime-interface.v1.json"
COMMIT="182f60b4c170785d96f1deb87fea8b108e9b985f"
VERSION="1.11.0"
INTEGRITY="sha512-z1RLWsQshYViJIk94SB0x9/AYPykj5LIuLxwjS0s+WgaCBgVtTknCsVR3x4itrBeqmiUEvGiN6cO/bOay0zOiQ=="
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
DATA_ROOT="$DATA_HOME/gsd-core"
RELEASE_ROOT="$DATA_ROOT/releases/$COMMIT"
MANIFEST="$DATA_ROOT/doc-warden-manifest.json"
BIN_DIR="$HOME/.local/bin"
CURSOR_DIR="$HOME/.cursor"
PREIMAGE_DIR="$DATA_ROOT/preimages"
DEFAULTS_PREIMAGE="$PREIMAGE_DIR/gsd-defaults.json"
DEFAULTS_ABSENT="$PREIMAGE_DIR/gsd-defaults.absent"

die() {
  printf 'gsd-core binding: ERROR: %s\n' "$*" >&2
  exit 1
}

sha256_file() {
  shasum -a 256 "$1" | awk '{print $1}'
}

require_files() {
  for file in "$PIN_FILE" "$LOCK_FILE" "$PACKAGE_FILE" "$INTERFACE_FILE"; do
    test -f "$file" || die "missing $(basename "$file")"
  done
}

check_contract() {
  require_files
  python3 - "$PIN_FILE" "$LOCK_FILE" "$INTERFACE_FILE" "$0" <<'PY'
import json, sys

pin = json.load(open(sys.argv[1], encoding="utf-8"))
lock = json.load(open(sys.argv[2], encoding="utf-8"))
interface = json.load(open(sys.argv[3], encoding="utf-8"))
installer = open(sys.argv[4], encoding="utf-8").read()
expected = {
    "package": "@opengsd/gsd-core",
    "version": "1.11.0",
    "git_commit": "182f60b4c170785d96f1deb87fea8b108e9b985f",
    "npm_integrity": "sha512-z1RLWsQshYViJIk94SB0x9/AYPykj5LIuLxwjS0s+WgaCBgVtTknCsVR3x4itrBeqmiUEvGiN6cO/bOay0zOiQ==",
}
for key, value in expected.items():
    if pin.get(key) != value:
        raise SystemExit(f"pin mismatch: {key}")
defaults = pin.get("runtime_defaults", {})
if defaults != {
    "workflow.use_worktrees": False,
    "git.branching_strategy": "none",
    "git.create_tag": False,
}:
    raise SystemExit("unsafe runtime defaults")
package = lock.get("packages", {}).get("node_modules/@opengsd/gsd-core", {})
if package.get("version") != expected["version"]:
    raise SystemExit("lock version mismatch")
if package.get("integrity") != expected["npm_integrity"]:
    raise SystemExit("lock integrity mismatch")
if interface.get("supported_scope") != "authoring_context_only":
    raise SystemExit("runtime interface is not authoring-only")
ids = {entry.get("id") for entry in interface.get("host_skills", [])}
required = {"gsd-new-project", "gsd-discuss-phase", "gsd-plan-phase", "gsd-validate-phase"}
if ids != required:
    raise SystemExit("native authoring interface mismatch")
if "gsd-ship" not in interface.get("excluded_workflows", []):
    raise SystemExit("shipping workflow must remain excluded")
if installer.count("npm ci --ignore-scripts --omit=dev") < 2:
    raise SystemExit("lifecycle-script policy missing")
if installer.count("DOC_WARDEN_ALLOW_LIVE_HOME") < 2:
    raise SystemExit("live-HOME isolation gate missing")
if installer.count("--cursor --global --config-dir") < 2:
    raise SystemExit("native Cursor installation interface missing")
PY
}

check_versions() {
  command -v node >/dev/null 2>&1 || die "node is required"
  command -v npm >/dev/null 2>&1 || die "npm is required"
  node_major="$(node -p 'process.versions.node.split(`.`)[0]')"
  npm_major="$(npm --version | awk -F. '{print $1}')"
  test "$node_major" -ge 24 || die "Node >=24 is required"
  test "$npm_major" -ge 10 || die "npm >=10 is required"
}

refuse_ungated_live_home() {
  case "$HOME" in
    /Users/laurence.duggan|/Users/laurence.duggan/)
      test "${DOC_WARDEN_ALLOW_LIVE_HOME:-0}" = "1" ||
        die "real-HOME apply requires the separately confirmed live-install gate"
      ;;
  esac
}

verify_registry_metadata() {
  metadata="$(npm view "@opengsd/gsd-core@$VERSION" version gitHead dist.integrity --json)"
  python3 - "$metadata" <<'PY'
import json, sys
value = json.loads(sys.argv[1])
if isinstance(value, list):
    if len(value) != 1 or not isinstance(value[0], dict):
        raise SystemExit("registry metadata returned an unexpected result set")
    value = value[0]
if not isinstance(value, dict):
    raise SystemExit("registry metadata must be an object")
expected = {
    "version": "1.11.0",
    "gitHead": "182f60b4c170785d96f1deb87fea8b108e9b985f",
    "dist.integrity": "sha512-z1RLWsQshYViJIk94SB0x9/AYPykj5LIuLxwjS0s+WgaCBgVtTknCsVR3x4itrBeqmiUEvGiN6cO/bOay0zOiQ==",
}
for key, wanted in expected.items():
    if value.get(key) != wanted:
        raise SystemExit(f"registry metadata mismatch: {key}")
PY
}

write_manifest() {
  python3 - "$MANIFEST" "$RELEASE_ROOT" "$PIN_FILE" "$LOCK_FILE" "$INTERFACE_FILE" \
    "$CURSOR_DIR" "$DEFAULTS_PREIMAGE" "$DEFAULTS_ABSENT" <<'PY'
import hashlib, json, os, sys, tempfile

destination, release, pin, lock, interface, cursor, defaults_preimage, defaults_absent = sys.argv[1:]
def digest(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()
value = {
    "schema": "doc-warden/gsd-install-manifest/v1",
    "owner": "doc-warden",
    "release_root": release,
    "cursor_root": cursor,
    "pin_digest": digest(pin),
    "lock_digest": digest(lock),
    "interface_digest": digest(interface),
    "defaults_preimage": (
        {"state": "present", "sha256": digest(defaults_preimage)}
        if os.path.isfile(defaults_preimage)
        else {"state": "absent"}
    ),
    "shims": {
        name: {
            "path": os.path.join(release, "doc-warden-bin", name),
            "sha256": digest(os.path.join(release, "doc-warden-bin", name)),
        }
        for name in ("gsd-core", "gsd-tools", "gsd_run")
    },
}
if value["defaults_preimage"]["state"] == "absent" and not os.path.isfile(defaults_absent):
    raise SystemExit("defaults preimage marker missing")
os.makedirs(os.path.dirname(destination), exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix=".manifest.", dir=os.path.dirname(destination))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    os.replace(temporary, destination)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
}

validate_manifest_identity() {
  test -f "$MANIFEST" || die "install manifest is missing"
  python3 - "$MANIFEST" "$RELEASE_ROOT" "$PIN_FILE" "$LOCK_FILE" "$INTERFACE_FILE" <<'PY'
import hashlib, json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
def digest(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()
expected = {
    "owner": "doc-warden",
    "release_root": sys.argv[2],
    "pin_digest": digest(sys.argv[3]),
    "lock_digest": digest(sys.argv[4]),
    "interface_digest": digest(sys.argv[5]),
}
for key, value in expected.items():
    if manifest.get(key) != value:
        raise SystemExit(f"manifest identity mismatch: {key}")
PY
}

remove_prior_release() {
  test -f "$MANIFEST" || return 0
  prior_release="$(python3 - "$MANIFEST" "$DATA_ROOT/releases" "$RELEASE_ROOT" <<'PY'
import hashlib, json, os, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
if manifest.get("schema") != "doc-warden/gsd-install-manifest/v1":
    raise SystemExit("prior manifest schema mismatch")
if manifest.get("owner") != "doc-warden":
    raise SystemExit("prior manifest owner mismatch")
release = os.path.realpath(manifest.get("release_root", ""))
releases = os.path.realpath(sys.argv[2])
current = os.path.realpath(sys.argv[3])
if release != releases and not release.startswith(releases + os.sep):
    raise SystemExit("prior release escapes the owned releases root")
shims = manifest.get("shims")
if not isinstance(shims, dict) or set(shims) != {"gsd-core", "gsd-tools", "gsd_run"}:
    raise SystemExit("prior manifest shim set mismatch")
for name, record in shims.items():
    if not isinstance(record, dict):
        raise SystemExit(f"prior manifest shim record invalid: {name}")
    path = record.get("path")
    expected_path = os.path.join(release, "doc-warden-bin", name)
    if os.path.realpath(path or "") != os.path.realpath(expected_path):
        raise SystemExit(f"prior manifest shim path mismatch: {name}")
    if not os.path.isfile(path):
        raise SystemExit(f"prior manifest shim missing: {name}")
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    if record.get("sha256") != digest:
        raise SystemExit(f"prior manifest shim digest mismatch: {name}")
if release != current:
    print(release)
PY
)"
  test -n "$prior_release" || return 0
  prior_installer="$prior_release/node_modules/@opengsd/gsd-core/bin/install.js"
  test -f "$prior_installer" ||
    die "prior release is incomplete; restore its installer before upgrade"
  restore_runtime_defaults check
  node "$prior_installer" --cursor --global --config-dir "$CURSOR_DIR" --uninstall
  python3 - "$MANIFEST" <<'PY'
import json, os, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
for record in manifest.get("shims", {}).values():
    path = record.get("path") if isinstance(record, dict) else record
    if not path:
        continue
    destination = os.path.join(os.path.expanduser("~"), ".local", "bin", os.path.basename(path))
    if os.path.islink(destination) and os.readlink(destination) == path:
        os.unlink(destination)
PY
  restore_runtime_defaults
  rm -rf "$prior_release"
  rm "$MANIFEST"
}

install_release() {
  repair="${1:-0}"
  if test -e "$RELEASE_ROOT"; then
    if test "$repair" = "0"; then
      validate_manifest_identity
      return 0
    fi
    if test -f "$MANIFEST"; then
      validate_manifest_identity
    fi
    rm -rf "$RELEASE_ROOT"
  fi
  mkdir -p "$DATA_ROOT/releases"
  staging="$(mktemp -d "$DATA_ROOT/releases/.staging.XXXXXX")"
  cleanup_staging() {
    rm -rf "$staging"
  }
  trap cleanup_staging EXIT HUP INT TERM
  cp "$PACKAGE_FILE" "$LOCK_FILE" "$staging/"
  (
    cd "$staging"
    npm ci --ignore-scripts --omit=dev --no-audit --no-fund
  )
  installed="$staging/node_modules/@opengsd/gsd-core/package.json"
  test -f "$installed" || die "installed package metadata missing"
  installed_version="$(node -p "require('$installed').version")"
  test "$installed_version" = "$VERSION" || die "installed package version mismatch"
  mv "$staging" "$RELEASE_ROOT"
  trap - EXIT HUP INT TERM
}

capture_runtime_defaults_preimage() {
  if test -f "$DEFAULTS_PREIMAGE" || test -f "$DEFAULTS_ABSENT"; then
    return
  fi
  mkdir -p "$PREIMAGE_DIR"
  if test -f "$HOME/.gsd/defaults.json"; then
    cp "$HOME/.gsd/defaults.json" "$DEFAULTS_PREIMAGE"
  else
    : >"$DEFAULTS_ABSENT"
  fi
}

configure_runtime_defaults() {
  defaults="$HOME/.gsd/defaults.json"
  mkdir -p "$(dirname "$defaults")"
  python3 - "$defaults" <<'PY'
import json, os, sys, tempfile
path = sys.argv[1]
try:
    value = json.load(open(path, encoding="utf-8"))
except FileNotFoundError:
    value = {}
if not isinstance(value, dict):
    raise SystemExit("GSD defaults must be a JSON object")
workflow = value.setdefault("workflow", {})
git = value.setdefault("git", {})
if not isinstance(workflow, dict) or not isinstance(git, dict):
    raise SystemExit("GSD workflow/git defaults must be objects")
workflow["use_worktrees"] = False
git["branching_strategy"] = "none"
git["create_tag"] = False
fd, temporary = tempfile.mkstemp(prefix=".defaults.", dir=os.path.dirname(path))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2)
        handle.write("\n")
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
}

restore_runtime_defaults() {
  mode="${1:-apply}"
  defaults="$HOME/.gsd/defaults.json"
  python3 - "$defaults" "$DEFAULTS_PREIMAGE" "$DEFAULTS_ABSENT" "$mode" <<'PY'
import copy, json, os, shutil, sys
current, preimage, absent, mode = sys.argv[1:]
if mode not in {"apply", "check"}:
    raise SystemExit("invalid runtime-default restore mode")
value = json.load(open(current, encoding="utf-8")) if os.path.exists(current) else {}
if not isinstance(value, dict):
    raise SystemExit("refusing to overwrite malformed GSD runtime defaults")
if os.path.isfile(preimage):
    original = json.load(open(preimage, encoding="utf-8"))
elif os.path.isfile(absent):
    original = {}
else:
    raise SystemExit("GSD defaults preimage is missing")

owned = (
    (("workflow", "use_worktrees"), False),
    (("git", "branching_strategy"), "none"),
    (("git", "create_tag"), False),
    (("resolve_model_ids",), "omit"),
)
expected = copy.deepcopy(original)
expected.setdefault("workflow", {})["use_worktrees"] = False
expected.setdefault("git", {})["branching_strategy"] = "none"
expected.setdefault("git", {})["create_tag"] = False
expected.setdefault("runtime", "cursor")
expected["resolve_model_ids"] = "omit"
if value == expected:
    if mode == "check":
        raise SystemExit(0)
    if os.path.isfile(preimage):
        shutil.copyfile(preimage, current)
    elif os.path.exists(current):
        os.unlink(current)
    raise SystemExit(0)

def read(root, parts):
    cursor = root
    for part in parts:
        if not isinstance(cursor, dict) or part not in cursor:
            return False, None
        cursor = cursor[part]
    return True, cursor
def write(root, parts, present, replacement):
    cursor = root
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    if present:
        cursor[parts[-1]] = replacement
    else:
        cursor.pop(parts[-1], None)
    for part in ("workflow", "git"):
        if value.get(part) == {}:
            value.pop(part)

runtime_present, runtime_value = read(original, ("runtime",))
dynamic_owned = owned + (
    (("runtime",), runtime_value if runtime_present else "cursor"),
)
for parts, installed in dynamic_owned:
    present, observed = read(value, parts)
    original_present, original_value = read(original, parts)
    restored_already = (
        (present and original_present and observed == original_value)
        or (not present and not original_present)
    )
    if not restored_already and (not present or observed != installed):
        raise SystemExit(f"refusing to overwrite changed GSD runtime default: {'.'.join(parts)}")
    write(value, parts, original_present, original_value)

if mode == "check":
    raise SystemExit(0)
if value == original and os.path.isfile(preimage):
    shutil.copyfile(preimage, current)
elif value:
    os.makedirs(os.path.dirname(current), exist_ok=True)
    with open(current, "w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2)
        handle.write("\n")
elif os.path.exists(current):
    os.unlink(current)
PY
  if test "$mode" = "apply"; then
    rm -rf "$PREIMAGE_DIR"
    rmdir "$HOME/.gsd" 2>/dev/null || true
  fi
}

prune_cursor_surface() {
  for path in "$CURSOR_DIR"/skills/gsd-*; do
    test -e "$path" || continue
    name="$(basename "$path")"
    case "$name" in
      gsd-new-project|gsd-discuss-phase|gsd-plan-phase|gsd-validate-phase) ;;
      *) rm -rf "$path" ;;
    esac
  done
  for path in "$CURSOR_DIR"/agents/gsd-*; do
    test -e "$path" || continue
    name="$(basename "$path" .md)"
    case "$name" in
      gsd-advisor-researcher|gsd-nyquist-auditor|gsd-pattern-mapper|\
      gsd-phase-researcher|gsd-plan-checker|gsd-planner|\
      gsd-project-researcher|gsd-research-synthesizer|gsd-roadmapper) ;;
      *) rm -f "$path" ;;
    esac
  done
  for path in "$CURSOR_DIR"/commands/gsd-*.md; do
    test -e "$path" || continue
    name="$(basename "$path" .md)"
    case "$name" in
      gsd-new-project|gsd-discuss-phase|gsd-plan-phase|gsd-validate-phase) ;;
      *) rm -f "$path" ;;
    esac
  done
}

install_cursor_descriptor() {
  mkdir -p "$CURSOR_DIR"
  node "$RELEASE_ROOT/node_modules/@opengsd/gsd-core/bin/install.js" \
    --cursor --global --config-dir "$CURSOR_DIR"
  prune_cursor_surface
  configure_runtime_defaults
}

create_bounded_shims() {
  wrapper_dir="$RELEASE_ROOT/doc-warden-bin"
  mkdir -p "$wrapper_dir"
  cat >"$wrapper_dir/gsd-core" <<EOF
#!/usr/bin/env bash
if test "\${1:-}" = "--help"; then
  exec node "$RELEASE_ROOT/node_modules/@opengsd/gsd-core/bin/install.js" --help
fi
printf '%s\n' 'gsd-core: direct installation is disabled; use doc-warden runtime operations' >&2
exit 64
EOF
  cat >"$wrapper_dir/gsd-tools" <<EOF
#!/usr/bin/env bash
case "\${1:-}" in
  check|config-get|current-timestamp|find-phase|inspect-dispatch-isolation|\
  phase-plan-index|progress|verify|\
  verify-path-exists|verify-summary)
    exec "$RELEASE_ROOT/node_modules/.bin/gsd-tools" "\$@"
    ;;
  *)
    printf '%s\n' 'gsd-tools: command is outside the read-only authoring interface' >&2
    exit 64
    ;;
esac
EOF
  cat >"$wrapper_dir/gsd_run" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' 'gsd_run: prohibited as a doc-warden agentic interface' >&2
exit 64
EOF
  chmod +x "$wrapper_dir/gsd-core" "$wrapper_dir/gsd-tools" "$wrapper_dir/gsd_run"
}

install_shims() {
  create_bounded_shims
  mkdir -p "$BIN_DIR"
  for name in gsd-core gsd-tools gsd_run; do
    target="$RELEASE_ROOT/doc-warden-bin/$name"
    destination="$BIN_DIR/$name"
    if test -e "$destination" && test ! -L "$destination"; then
      die "refusing to replace non-symlink: $destination"
    fi
    if test -L "$destination"; then
      current="$(readlink "$destination")"
      test "$current" = "$target" || die "refusing to replace foreign symlink: $destination"
    else
      ln -s "$target" "$destination"
    fi
  done
}

doctor() {
  check_contract
  check_versions
  test -d "$RELEASE_ROOT" || die "release is not installed"
  test -f "$MANIFEST" || die "install manifest is missing"
  validate_manifest_identity
  installed="$RELEASE_ROOT/node_modules/@opengsd/gsd-core/package.json"
  test -f "$installed" || die "installed package metadata missing"
  test "$(node -p "require('$installed').version")" = "$VERSION" ||
    die "installed package version mismatch"
  for name in gsd-core gsd-tools gsd_run; do
    destination="$BIN_DIR/$name"
    test -L "$destination" || die "missing stable shim: $destination"
    test "$(readlink "$destination")" = "$RELEASE_ROOT/doc-warden-bin/$name" ||
      die "stable shim target mismatch: $destination"
  done
  python3 - "$MANIFEST" <<'PY'
import hashlib, json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
for name, record in manifest.get("shims", {}).items():
    observed = hashlib.sha256(open(record["path"], "rb").read()).hexdigest()
    if observed != record["sha256"]:
        raise SystemExit(f"bounded shim digest mismatch: {name}")
PY
  test -f "$CURSOR_DIR/skills/gsd-plan-phase/SKILL.md" ||
    die "Cursor authoring descriptor missing"
  for name in gsd-autonomous gsd-execute-phase gsd-ship gsd-resume-work; do
    test ! -e "$CURSOR_DIR/skills/$name" || die "excluded skill installed: $name"
    test ! -e "$CURSOR_DIR/commands/$name.md" || die "excluded command installed: $name"
  done
  for name in gsd-executor gsd-code-fixer gsd-debugger gsd-verifier; do
    test ! -e "$CURSOR_DIR/agents/$name.md" || die "excluded agent installed: $name"
  done
  "$BIN_DIR/gsd_run" >/dev/null 2>&1 &&
    die "gsd_run must refuse agentic invocation"
  python3 - "$HOME/.gsd/defaults.json" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
assert value["workflow"]["use_worktrees"] is False
assert value["git"]["branching_strategy"] == "none"
assert value["git"]["create_tag"] is False
PY
  printf 'gsd-core binding: OK\n'
  printf '  release: %s\n' "$RELEASE_ROOT"
  printf '  pin_sha256: %s\n' "$(sha256_file "$PIN_FILE")"
  printf '  lock_sha256: %s\n' "$(sha256_file "$LOCK_FILE")"
  printf '  interface_sha256: %s\n' "$(sha256_file "$INTERFACE_FILE")"
}

uninstall() {
  refuse_ungated_live_home
  if test ! -e "$RELEASE_ROOT" && test ! -e "$MANIFEST" &&
    test ! -e "$DEFAULTS_PREIMAGE" && test ! -e "$DEFAULTS_ABSENT"; then
    printf 'gsd-core binding: already uninstalled\n'
    return
  fi
  test ! -f "$MANIFEST" || validate_manifest_identity
  if test ! -f "$RELEASE_ROOT/node_modules/@opengsd/gsd-core/bin/install.js"; then
    install_release 1
  fi
  restore_runtime_defaults check
  node "$RELEASE_ROOT/node_modules/@opengsd/gsd-core/bin/install.js" \
    --cursor --global --config-dir "$CURSOR_DIR" --uninstall
  restore_runtime_defaults
  for name in gsd-core gsd-tools gsd_run; do
    destination="$BIN_DIR/$name"
    if test -L "$destination" &&
      test "$(readlink "$destination")" = "$RELEASE_ROOT/doc-warden-bin/$name"; then
      rm "$destination"
    fi
  done
  test ! -e "$RELEASE_ROOT" || rm -rf "$RELEASE_ROOT"
  test ! -e "$MANIFEST" || rm "$MANIFEST"
  rmdir "$DATA_ROOT/releases" "$DATA_ROOT" "$BIN_DIR" 2>/dev/null || true
  printf 'gsd-core binding: uninstalled owned release\n'
}

print_pin() {
  check_contract
  python3 - "$PIN_FILE" "$LOCK_FILE" "$INTERFACE_FILE" <<'PY'
import hashlib, json, sys
pin = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"package={pin['package']}")
print(f"version={pin['version']}")
print(f"git_commit={pin['git_commit']}")
print(f"npm_integrity={pin['npm_integrity']}")
for label, path in (("lock_sha256", sys.argv[2]), ("interface_sha256", sys.argv[3])):
    print(f"{label}={hashlib.sha256(open(path, 'rb').read()).hexdigest()}")
PY
}

usage() {
  printf 'usage: %s --apply|--repair|--doctor|--check|--uninstall|--print-pin\n' "$0"
}

case "${1:-}" in
  --check)
    check_contract
    check_versions
    printf 'gsd-core binding contract: OK\n'
    ;;
  --apply)
    check_contract
    check_versions
    refuse_ungated_live_home
    verify_registry_metadata
    remove_prior_release
    capture_runtime_defaults_preimage
    install_release 0
    install_cursor_descriptor
    install_shims
    write_manifest
    doctor
    ;;
  --repair)
    check_contract
    check_versions
    refuse_ungated_live_home
    verify_registry_metadata
    remove_prior_release
    capture_runtime_defaults_preimage
    install_release 1
    install_cursor_descriptor
    install_shims
    write_manifest
    doctor
    ;;
  --doctor)
    doctor
    ;;
  --uninstall)
    uninstall
    ;;
  --print-pin)
    print_pin
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
