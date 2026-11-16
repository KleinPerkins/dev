#!/usr/bin/env bash
# Reconcile the complete AWA external-owner role matrix into the Cursor user hook file.
#
# The Skills GCB installs and validates the standalone AWA runtime. This Dev host overlay owns the
# selected hooks.json transaction: it composes installed awa-hook-owner/v1 with the exact released
# awa-hook-owner/v2 successor, substitutes only policy-injecting Dev delegator paths, preserves
# unrelated rows, and atomically writes the effective seven-role projection.
#
# Usage:
#   install-worktree-hooks.sh            validate binding + atomically reconcile all seven roles
#   install-worktree-hooks.sh --check    read-only exact inventory check; an entirely absent runtime
#                                        is an honest static/fresh-machine deferral
#   install-worktree-hooks.sh --restore-preimage
#                                        atomically restore the exact captured install preimage
#   install-worktree-hooks.sh --remove   atomically remove only proven AWA role variants
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
RUNTIME="${AWA_HOME:-$DATA_HOME/awa/current}"
HOOKS_JSON="${AWA_HOOKS_JSON:-$HOME/.cursor/hooks.json}"
ROLLBACK_DIR="${DEV_AWA_HOOK_ROLLBACK_DIR:-$STATE_HOME/awa/dev-host-overlay}"
RELEASE_POINTER="${DEV_AWA_RELEASE_POINTER:-${AWA_RELEASE_POINTER:-$DATA_HOME/awa/release-pointer.json}}"
GCB_POINTER="${DEV_AWA_GCB_POINTER:-${AWA_GCB_POINTER:-$DATA_HOME/awa/gcb-pointer.json}}"
OWNER_SELECTION="${DEV_AWA_OWNER_SELECTION:-${AWA_HOOK_OWNER_SELECTION:-$CONFIG_HOME/awa/hook-owner.json}}"
GCB_META="${AWA_GCB_META:-$ROOT/capabilities/skills/global/tools/awa/meta.yml}"
CONTRACT="$RUNTIME/contracts/awa-contract.v1.json"
V2_CONTRACT="$RUNTIME/contracts/awa-hook-owner.v2.json"
V2_FIXTURE="$ROOT/_ops/tests/fixtures/awa-v1.8.1/awa-hook-owner.v2.json"
SESSION_HOOK="$ROOT/_ops/cursor-hooks/worktree-session.sh"
GUARD_HOOK="$ROOT/_ops/cursor-hooks/worktree-guard.sh"
COMPOSITE_HOOK="$ROOT/_ops/cursor-hooks/worktree-guard-with-integrity.sh"
STOP_HOOK="$ROOT/_ops/cursor-hooks/awa-integrity-observer.sh"
HANDOFF_HOOK="$ROOT/_ops/cursor-hooks/awa-session-handoff.sh"
BINDING_CHECKER="${DEV_AWA_BINDING_CHECKER:-$ROOT/_ops/bin/check-awa-release-binding.py}"

MODE="install"
case "${1:-}" in
  --check) MODE="check" ;;
  --source-check) MODE="source-check" ;;
  --restore-preimage) MODE="restore-preimage" ;;
  --remove) MODE="remove" ;;
  "") MODE="install" ;;
  *) printf 'usage: %s [--check|--source-check|--restore-preimage|--remove]\n' "$0" >&2; exit 2 ;;
esac

[ -x "$BINDING_CHECKER" ] || {
  printf 'install-worktree-hooks: release binding checker unavailable\n' >&2
  exit 1
}
"$BINDING_CHECKER" --static >/dev/null || exit 1
if [ "$MODE" = "source-check" ]; then
  for target in \
    "$SESSION_HOOK" "$GUARD_HOOK" "$COMPOSITE_HOOK" "$STOP_HOOK" "$HANDOFF_HOOK"
  do
    [ -f "$target" ] && [ ! -L "$target" ] && [ -x "$target" ] || {
      printf 'install-worktree-hooks --source-check: delegator missing/unsafe\n' >&2
      exit 1
    }
  done
  printf 'install-worktree-hooks --source-check: exact v1.8.2 source contract OK\n'
  exit 0
fi
if [ -d "$RUNTIME" ]; then
  DEV_AWA_RELEASE_POINTER="$RELEASE_POINTER" \
  DEV_AWA_GCB_POINTER="$GCB_POINTER" \
  DEV_AWA_OWNER_SELECTION="$OWNER_SELECTION" \
  DEV_AWA_GCB_DIR="$(dirname "$GCB_META")" \
    "$BINDING_CHECKER" --runtime >/dev/null || exit 1
fi

set +e
HOOK_MODE="$MODE" HOOKS_JSON="$HOOKS_JSON" AWA_RUNTIME="$RUNTIME" \
  AWA_HOOK_ROLLBACK_DIR="$ROLLBACK_DIR" \
  AWA_RELEASE_POINTER="$RELEASE_POINTER" AWA_GCB_POINTER="$GCB_POINTER" \
  AWA_OWNER_SELECTION="$OWNER_SELECTION" AWA_GCB_META="$GCB_META" \
  AWA_CONTRACT="$CONTRACT" AWA_V2_CONTRACT="$V2_CONTRACT" AWA_V2_FIXTURE="$V2_FIXTURE" \
  DEV_SESSION_HOOK="$SESSION_HOOK" DEV_GUARD_HOOK="$GUARD_HOOK" \
  DEV_COMPOSITE_HOOK="$COMPOSITE_HOOK" DEV_STOP_HOOK="$STOP_HOOK" \
  DEV_HANDOFF_HOOK="$HANDOFF_HOOK" \
  python3 - <<'PY'
import copy
import datetime
import fcntl
import hashlib
import json
import os
import re
import secrets
import shlex
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath


MODE = os.environ["HOOK_MODE"]
DEST = Path(os.path.abspath(str(Path(os.environ["HOOKS_JSON"]).expanduser())))
ROLLBACK_DIR = Path(
    os.path.abspath(str(Path(os.environ["AWA_HOOK_ROLLBACK_DIR"]).expanduser()))
)
ROLLBACK_RECORD = ROLLBACK_DIR / "hook-preimage.json"
ROLLBACK_LOCK = ROLLBACK_DIR / ".lock"
RUNTIME = Path(os.environ["AWA_RUNTIME"]).expanduser()
RELEASE_POINTER = Path(os.environ["AWA_RELEASE_POINTER"]).expanduser()
GCB_POINTER = Path(os.environ["AWA_GCB_POINTER"]).expanduser()
OWNER_SELECTION = Path(os.environ["AWA_OWNER_SELECTION"]).expanduser()
GCB_META = Path(os.environ["AWA_GCB_META"]).expanduser()
CONTRACT = Path(os.environ["AWA_CONTRACT"]).expanduser()
V2_CONTRACT = Path(os.environ["AWA_V2_CONTRACT"]).expanduser()
V2_FIXTURE = Path(os.environ["AWA_V2_FIXTURE"]).expanduser()
SESSION_HOOK = Path(os.environ["DEV_SESSION_HOOK"]).resolve()
GUARD_HOOK = Path(os.environ["DEV_GUARD_HOOK"]).resolve()
COMPOSITE_HOOK = Path(os.environ["DEV_COMPOSITE_HOOK"]).resolve()
STOP_HOOK = Path(os.environ["DEV_STOP_HOOK"]).resolve()
HANDOFF_HOOK = Path(os.environ["DEV_HANDOFF_HOOK"]).resolve()
MAX_RECORD_BYTES = 1_048_576
ROLLBACK_SCHEMA = "dev-awa-hook-preimage/v1"
COMPATIBLE_ROLLBACK_PREDECESSORS = {
    # Exact reviewed maintenance chain; hook contracts are byte-identical.
    "cfe9437739d2928014c2156532d1986a8511fd30": frozenset({
        "ff978ade5ff9c7604f58f4b3810b1cd75ea3287f",
        "60ae49b4b118211d4702d9297e3f479222f45cc0",
    }),
    "ff978ade5ff9c7604f58f4b3810b1cd75ea3287f": frozenset(
        {"60ae49b4b118211d4702d9297e3f479222f45cc0"}
    ),
}
V1_ROLE_IDS = [
    "worktree.session-context",
    "worktree.shell-guard",
    "worktree.file-observer",
    "recovery.maintenance",
    "finish.prompt-recall",
]
V2_ROLE_IDS = [
    "worktree.shell-guard-composite",
    "worktree.stop-observer",
    "worktree.session-handoff",
]
DEV_TARGETS = {
    "worktree.session-context": SESSION_HOOK,
    "worktree.shell-guard": GUARD_HOOK,
    "worktree.file-observer": GUARD_HOOK,
    "worktree.shell-guard-composite": COMPOSITE_HOOK,
    "worktree.stop-observer": STOP_HOOK,
    "worktree.session-handoff": HANDOFF_HOOK,
}


class Refusal(Exception):
    pass


def refuse(message):
    raise Refusal(message)


def strict_regular_info(path, label):
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError:
        refuse(f"{label} missing/unreadable")
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            refuse(f"{label} must be a non-symlink regular file")
        if info.st_size > MAX_RECORD_BYTES:
            refuse(f"{label} exceeds the bounded size")
        chunks = []
        remaining = MAX_RECORD_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_RECORD_BYTES:
            refuse(f"{label} exceeds the bounded size")
        return raw, info
    finally:
        os.close(fd)


def strict_regular(path, label):
    raw, _ = strict_regular_info(path, label)
    return raw


def strict_owned_regular_info(path, label, required_mode=None):
    raw, info = strict_regular_info(path, label)
    if info.st_uid != os.getuid():
        refuse(f"{label} is not owned by the current user")
    if info.st_nlink != 1:
        refuse(f"{label} must have exactly one hard link")
    if required_mode is not None and stat.S_IMODE(info.st_mode) != required_mode:
        refuse(f"{label} mode must be {required_mode:04o}")
    return raw, info


def strict_owned_regular(path, label, required_mode=None):
    raw, _ = strict_owned_regular_info(path, label, required_mode)
    return raw


def load_json(path, label):
    raw = strict_regular(path, label)
    try:
        return json.loads(raw.decode("utf-8")), raw
    except (UnicodeError, ValueError, json.JSONDecodeError):
        refuse(f"{label} is malformed")


def meta_value(path, key):
    raw = strict_regular(path, "Skills AWA metadata")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError:
        refuse("Skills AWA metadata is malformed")
    pattern = re.compile(rf"^[ \t]*{re.escape(key)}:[ \t]*(.*?)[ \t]*$")
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            continue
        value = re.sub(r"[ \t]+#.*$", "", match.group(1)).strip().strip('"')
        return value
    refuse(f"Skills AWA metadata lacks {key}")


def exact_dict(value, expected, label):
    if type(value) is not dict or value != expected:
        refuse(f"{label} drift")


def safe_runtime_role(role):
    if type(role) is not str:
        refuse("contract command role is malformed")
    pure = PurePosixPath(role)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        refuse("contract command role escapes the runtime")
    lexical_target = RUNTIME / Path(*pure.parts)
    target = lexical_target.resolve()
    try:
        target.relative_to(RUNTIME.resolve())
    except ValueError:
        refuse("contract command role escapes the runtime")
    if not target.is_file() or not os.access(target, os.X_OK):
        refuse("installed contract role is missing/not executable")
    return lexical_target


def validate_binding():
    runtime_present = RUNTIME.is_dir()
    state_paths = (
        RELEASE_POINTER,
        GCB_POINTER,
        OWNER_SELECTION,
        CONTRACT,
        V2_CONTRACT,
    )
    if not runtime_present:
        if MODE == "check" and not any(os.path.lexists(path) for path in state_paths):
            refuse_static_awa_hooks_without_runtime()
            raise SystemExit(3)
        refuse("installed AWA runtime is absent")

    pin = meta_value(GCB_META, "provenance_ref")
    source = meta_value(GCB_META, "provenance_source")
    if pin != "cfe9437739d2928014c2156532d1986a8511fd30":
        refuse("Skills AWA pin is not the accepted v1.8.2 commit")
    if source != "github.com/KleinPerkins/awa":
        refuse("Skills AWA source drift")

    gcb, _ = load_json(GCB_POINTER, "AWA GCB pointer")
    required_gcb = {
        "schema",
        "id",
        "kind",
        "source",
        "ref",
        "clone_url",
        "checkout",
        "shelf",
        "release_pointer",
    }
    if (
        type(gcb) is not dict
        or set(gcb) != required_gcb
        or gcb.get("schema") != "awa-gcb-pointer/v1"
        or gcb.get("id") != "awa"
        or gcb.get("kind") != "global-capability-binding"
        or gcb.get("source") != source
        or gcb.get("ref") != pin
        or gcb.get("shelf") != str(GCB_META.parent.resolve())
        or gcb.get("release_pointer") != str(RELEASE_POINTER)
    ):
        refuse("AWA GCB pointer drift")

    pointer, _ = load_json(RELEASE_POINTER, "AWA release pointer")
    required_pointer = {
        "schema",
        "version",
        "source",
        "commit",
        "runtime",
        "policy",
        "hook_owner_contract",
        "hook_owner_mode",
        "hook_owner_contract_sha256",
        "installed_at",
    }
    if (
        type(pointer) is not dict
        or set(pointer) != required_pointer
        or pointer.get("schema") != "awa-release-pointer/v1"
        or pointer.get("version") != "1.8.2"
        or pointer.get("commit") != pin
        or pointer.get("source") != gcb.get("checkout")
        or pointer.get("runtime") != str(RUNTIME)
        or pointer.get("hook_owner_contract") != "awa-hook-owner/v1"
        or pointer.get("hook_owner_mode") != "external"
        or re.fullmatch(r"[0-9a-f]{64}", str(pointer.get("hook_owner_contract_sha256")))
        is None
    ):
        refuse("AWA release pointer drift")

    selection, _ = load_json(OWNER_SELECTION, "AWA hook-owner selection")
    exact_dict(
        selection,
        {
            "schema": "awa-hook-owner-selection/v1",
            "contract": "awa-hook-owner/v1",
            "mode": "external",
        },
        "AWA hook-owner selection",
    )

    contract, contract_bytes = load_json(CONTRACT, "installed AWA contract")
    digest = hashlib.sha256(contract_bytes).hexdigest()
    if pointer["hook_owner_contract_sha256"] != digest:
        refuse("installed AWA contract digest mismatch")
    owner = contract.get("hook_ownership") if type(contract) is dict else None
    if (
        type(owner) is not dict
        or owner.get("schema") != "awa-hook-owner/v1"
        or owner.get("modes") != ["direct", "external"]
        or owner.get("default_mode") != "direct"
        or owner.get("selection_env") != "AWA_HOOK_OWNER"
        or owner.get("selection_schema") != "awa-hook-owner-selection/v1"
        or owner.get("external_real_hook_file_writes") is not False
    ):
        refuse("installed AWA hook-owner contract drift")
    contract_roles = owner.get("roles")
    if (
        type(contract_roles) is not list
        or [role.get("id") if type(role) is dict else None for role in contract_roles]
        != V1_ROLE_IDS
    ):
        refuse("installed AWA v1 role inventory drift")

    v2, v2_bytes = load_json(V2_CONTRACT, "installed AWA hook-owner v2 contract")
    fixture_bytes = strict_regular(V2_FIXTURE, "source AWA hook-owner v2 fixture")
    if v2_bytes != fixture_bytes:
        refuse("installed AWA hook-owner v2 contract bytes drift")
    v2_roles = v2.get("roles") if type(v2) is dict else None
    if (
        v2.get("schema") != "awa-hook-owner/v2"
        or v2.get("version") != 2
        or v2.get("successor_of") != "awa-hook-owner/v1"
        or v2.get("supersedes_roles") != ["worktree.shell-guard"]
        or v2.get("external_real_hook_file_writes") is not False
        or type(v2_roles) is not list
        or [role.get("id") if type(role) is dict else None for role in v2_roles]
        != V2_ROLE_IDS
    ):
        refuse("installed AWA v2 role inventory drift")

    def project(role):
        role_id = role["id"]
        event = role.get("event")
        command_role = role.get("direct_command_role")
        path_class = role.get("external_command_path_class")
        entry = role.get("entry")
        if (
            type(event) is not str
            or not event
            or type(entry) is not dict
            or entry.get("type") != "command"
            or "command" in entry
        ):
            refuse("installed AWA role definition drift")
        runtime_target = safe_runtime_role(command_role)
        if role_id in DEV_TARGETS:
            if path_class != "host-policy-delegator":
                refuse("installed AWA delegator class drift")
            target = DEV_TARGETS[role_id]
            if not target.is_file() or not os.access(target, os.X_OK):
                refuse("Dev host-policy delegator is missing/not executable")
        else:
            if path_class != "installed-awa":
                refuse("installed AWA product-hook class drift")
            target = runtime_target
        wanted = {"command": str(target)}
        wanted.update(entry)
        return {
            "id": role_id,
            "event": event,
            "basename": Path(command_role).name,
            "wanted": wanted,
            "runtime_target": str(runtime_target),
        }

    variants = [project(role) for role in contract_roles]
    variants.extend(project(role) for role in v2_roles)
    superseded = set(v2["supersedes_roles"])
    roles = [role for role in variants if role["id"] not in superseded]
    expected_effective = [
        "worktree.session-context",
        "worktree.file-observer",
        "recovery.maintenance",
        "finish.prompt-recall",
        *V2_ROLE_IDS,
    ]
    if [role["id"] for role in roles] != expected_effective:
        refuse("effective AWA v2 role composition drift")
    return roles, variants, {
        "source": source,
        "release_commit": pin,
        "v1_contract_sha256": digest,
        "v2_contract_sha256": hashlib.sha256(v2_bytes).hexdigest(),
        "v2_fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
    }


def validate_hook_document(data):
    if (
        type(data) is not dict
        or type(data.get("version")) is not int
        or data.get("version") != 1
        or type(data.get("hooks")) is not dict
    ):
        refuse("hook file object/version/hooks shape is malformed")
    for event, entries in data["hooks"].items():
        if type(event) is not str or type(entries) is not list:
            refuse("hook event shape is malformed")
        if any(type(entry) is not dict for entry in entries):
            refuse("hook entry shape is malformed")


def command_path(entry):
    command = entry.get("command")
    if type(command) is not str or not command:
        return None
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv:
        return None
    if Path(argv[0]).name in ("bash", "sh"):
        if len(argv) < 2 or argv[1].startswith("-"):
            return None
        candidate = argv[1]
    else:
        candidate = argv[0]
    return Path(candidate).expanduser()


def path_has_suffix(path, suffix):
    parts = path.parts
    return len(parts) >= len(suffix) and tuple(parts[-len(suffix) :]) == tuple(suffix)


def path_has_sequence(path, sequence):
    parts = path.parts
    width = len(sequence)
    return any(
        tuple(parts[index : index + width]) == tuple(sequence)
        for index in range(len(parts) - width + 1)
    )


def refuse_static_awa_hooks_without_runtime():
    if not os.path.lexists(DEST):
        return
    raw = strict_regular(DEST, "Cursor hook file")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        refuse("Cursor hook file is malformed while AWA runtime is absent")
    validate_hook_document(data)
    for entries in data["hooks"].values():
        for entry in entries:
            path = command_path(entry)
            if path is None:
                continue
            if path_has_sequence(path, ("awa", "current", "kernel", "hooks")):
                refuse("stale installed-path AWA hook exists without runtime state")
            if path_has_sequence(path, ("_ops", "cursor-hooks")) and path.name in {
                "worktree-session.sh",
                "worktree-guard.sh",
                "worktree-guard-with-integrity.sh",
                "awa-integrity-observer.sh",
                "awa-session-handoff.sh",
            }:
                refuse("stale Dev AWA delegator hook exists without runtime state")


def proven_variant(entry, roles):
    path = command_path(entry)
    if path is None:
        return False
    for role in roles:
        basename = role["basename"]
        if path.name != basename:
            continue
        if str(path) in (role["wanted"]["command"], role["runtime_target"]):
            return True
        if path_has_suffix(path, ("_ops", "cursor-hooks", basename)):
            return True
        if path_has_suffix(path, ("awa", "current", "kernel", "hooks", basename)):
            return True
    return False


def is_exact_role(event, entry, roles):
    return any(event == role["event"] and entry == role["wanted"] for role in roles)


def exact_matrix(data, roles, variants):
    validate_hook_document(data)
    hooks = data["hooks"]
    for role in roles:
        matches = [
            entry
            for entry in hooks.get(role["event"], [])
            if entry == role["wanted"]
        ]
        if len(matches) != 1:
            refuse(f"role {role['id']} is missing/duplicate/drifted")
    for event, entries in hooks.items():
        for entry in entries:
            if proven_variant(entry, variants) and not is_exact_role(event, entry, roles):
                refuse("stale, duplicate, or wrong-event AWA hook variant")


def absent_matrix(data, variants):
    validate_hook_document(data)
    for entries in data["hooks"].values():
        if any(proven_variant(entry, variants) for entry in entries):
            refuse("AWA hook variant remains after removal")


def load_hooks_for_mode():
    if not os.path.lexists(DEST):
        if MODE == "check":
            refuse("required external-owner hook file is absent")
        return {"version": 1, "hooks": {}}, None, 0o600
    raw, info = strict_owned_regular_info(DEST, "Cursor hook file")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        refuse("Cursor hook file is malformed")
    validate_hook_document(data)
    mode = stat.S_IMODE(info.st_mode)
    return data, raw, mode


def reconcile(data, roles, variants):
    hooks = data["hooks"]
    for event in list(hooks):
        hooks[event] = [
            entry for entry in hooks[event] if not proven_variant(entry, variants)
        ]
    for role in roles:
        hooks.setdefault(role["event"], []).append(role["wanted"])
    exact_matrix(data, roles, variants)
    return data


def write_all(fd, payload):
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def ensure_rollback_dir():
    existed = os.path.lexists(ROLLBACK_DIR)
    if not existed:
        ROLLBACK_DIR.mkdir(parents=True, mode=0o700)
        os.chmod(ROLLBACK_DIR, 0o700)
    try:
        info = ROLLBACK_DIR.lstat()
    except OSError:
        refuse("rollback state directory is missing/unreadable")
    if (
        not stat.S_ISDIR(info.st_mode)
        or ROLLBACK_DIR.is_symlink()
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        refuse("rollback state directory must be an owned mode-0700 real directory")


def acquire_rollback_lock():
    ensure_rollback_dir()
    flags = os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    created = False
    try:
        fd = os.open(ROLLBACK_LOCK, flags | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
    except FileExistsError:
        try:
            fd = os.open(ROLLBACK_LOCK, flags)
        except OSError:
            refuse("rollback lock is unsafe or unreadable")
    if created:
        os.fchmod(fd, 0o600)
        sync_directory(ROLLBACK_DIR)
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        os.close(fd)
        refuse("rollback lock must be an owned mode-0600 regular file")
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def create_backup(old, generation):
    for _ in range(32):
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y%m%dT%H%M%S%fZ"
        )
        backup = DEST.with_name(f"{DEST.name}.bak-{stamp}-{generation}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(backup, flags, 0o600)
        except FileExistsError:
            generation = secrets.token_hex(16)
            continue
        try:
            write_all(fd, old)
            os.fchmod(fd, 0o600)
            os.fsync(fd)
        finally:
            os.close(fd)
        sync_directory(DEST.parent)
        return backup, generation
    raise OSError("could not allocate collision-safe backup")


def write_private_atomic(path, payload):
    fd, candidate_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    candidate = Path(candidate_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(candidate, path)
        sync_directory(path.parent)
    finally:
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass


def rollback_record_bytes(
    generation, backup, old_bytes, old_exists, prior_mode, new_bytes, provenance
):
    record = {
        "schema": ROLLBACK_SCHEMA,
        "generation": generation,
        "hook_path": str(DEST),
        "preimage": {
            "exists": old_exists,
            "sha256": digest(old_bytes or b""),
            "mode": prior_mode if old_exists else None,
            "backup_name": backup.name,
        },
        "postimage": {
            "sha256": digest(new_bytes),
            "mode": prior_mode,
        },
        "provenance": provenance,
    }
    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")


def capture_rollback_preimage(
    old_bytes, old_exists, prior_mode, new_bytes, provenance
):
    generation = secrets.token_hex(16)
    backup, generation = create_backup(old_bytes or b"", generation)
    if os.path.lexists(ROLLBACK_RECORD):
        strict_owned_regular(
            ROLLBACK_RECORD, "existing rollback preimage record", required_mode=0o600
        )
    payload = rollback_record_bytes(
        generation,
        backup,
        old_bytes,
        old_exists,
        prior_mode,
        new_bytes,
        provenance,
    )
    parsed = json.loads(payload.decode("utf-8"))
    if parsed.get("schema") != ROLLBACK_SCHEMA:
        refuse("rollback record candidate is malformed")
    write_private_atomic(ROLLBACK_RECORD, payload)


def load_rollback_preimage(provenance, *, compatible_predecessors=frozenset()):
    raw = strict_owned_regular(
        ROLLBACK_RECORD, "rollback preimage record", required_mode=0o600
    )
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        refuse("rollback preimage record is malformed")
    if type(record) is not dict or set(record) != {
        "schema",
        "generation",
        "hook_path",
        "preimage",
        "postimage",
        "provenance",
    }:
        refuse("rollback preimage record schema drift")
    generation = record.get("generation")
    preimage = record.get("preimage")
    postimage = record.get("postimage")
    recorded_provenance = record.get("provenance")
    provenance_exact = recorded_provenance == provenance
    provenance_compatible = False
    if (
        not provenance_exact
        and compatible_predecessors
        and type(recorded_provenance) is dict
    ):
        recorded_release = recorded_provenance.get("release_commit")
        compatible = dict(provenance)
        compatible["release_commit"] = recorded_release
        provenance_compatible = (
            recorded_release in compatible_predecessors
            and recorded_provenance == compatible
        )
    if (
        record.get("schema") != ROLLBACK_SCHEMA
        or re.fullmatch(r"[0-9a-f]{32}", str(generation)) is None
        or record.get("hook_path") != str(DEST)
        or not (provenance_exact or provenance_compatible)
        or type(preimage) is not dict
        or set(preimage) != {"exists", "sha256", "mode", "backup_name"}
        or type(postimage) is not dict
        or set(postimage) != {"sha256", "mode"}
    ):
        refuse("rollback preimage record provenance/schema/path drift")
    backup_name = preimage.get("backup_name")
    expected_name = re.compile(
        rf"^{re.escape(DEST.name)}\.bak-\d{{8}}T\d{{12}}Z-{generation}$"
    )
    if (
        type(backup_name) is not str
        or Path(backup_name).name != backup_name
        or expected_name.fullmatch(backup_name) is None
    ):
        refuse("rollback backup generation/path drift")
    if (
        type(preimage.get("exists")) is not bool
        or re.fullmatch(r"[0-9a-f]{64}", str(preimage.get("sha256"))) is None
        or re.fullmatch(r"[0-9a-f]{64}", str(postimage.get("sha256"))) is None
        or type(postimage.get("mode")) is not int
        or not 0 <= postimage["mode"] <= 0o7777
    ):
        refuse("rollback preimage record value drift")
    if preimage["exists"]:
        if (
            type(preimage.get("mode")) is not int
            or not 0 <= preimage["mode"] <= 0o7777
        ):
            refuse("rollback preimage mode drift")
    elif preimage.get("mode") is not None:
        refuse("absent rollback preimage must not carry a mode")
    backup = DEST.parent / backup_name
    backup_bytes = strict_owned_regular(
        backup, "rollback preimage backup", required_mode=0o600
    )
    if digest(backup_bytes) != preimage["sha256"]:
        refuse("rollback preimage backup digest mismatch")
    if preimage["exists"]:
        try:
            backup_data = json.loads(backup_bytes.decode("utf-8"))
        except (UnicodeError, ValueError, json.JSONDecodeError):
            refuse("rollback preimage backup is malformed")
        validate_hook_document(backup_data)
    elif backup_bytes != b"":
        refuse("absent rollback preimage backup must be empty")
    return record, backup_bytes, provenance_exact


def current_snapshot():
    if not os.path.lexists(DEST):
        return False, None, None
    raw, info = strict_owned_regular_info(DEST, "Cursor hook file")
    return True, raw, stat.S_IMODE(info.st_mode)


def assert_snapshot(expected_exists, expected_bytes, expected_mode):
    exists, raw, mode = current_snapshot()
    if (
        exists != expected_exists
        or raw != expected_bytes
        or mode != expected_mode
    ):
        refuse("Cursor hook file changed during the locked transaction")


def validate_active_rollback(provenance, current_bytes, current_mode):
    record, _, _ = load_rollback_preimage(provenance)
    if (
        digest(current_bytes) != record["postimage"]["sha256"]
        or current_mode != record["postimage"]["mode"]
    ):
        refuse("rollback preimage record is stale for the current hook projection")


def migrate_compatible_rollback_provenance(
    provenance, current_bytes, current_mode
):
    """Advance one closed reviewed predecessor without changing rollback evidence."""
    current_release = provenance.get("release_commit")
    predecessors = COMPATIBLE_ROLLBACK_PREDECESSORS.get(
        current_release, frozenset()
    )
    record, backup_bytes, provenance_exact = load_rollback_preimage(
        provenance,
        compatible_predecessors=predecessors,
    )
    if (
        digest(current_bytes) != record["postimage"]["sha256"]
        or current_mode != record["postimage"]["mode"]
    ):
        refuse("rollback preimage record is stale for the current hook projection")
    if provenance_exact:
        return False

    previous_release = record["provenance"]["release_commit"]
    migrated = copy.deepcopy(record)
    migrated["provenance"]["release_commit"] = current_release
    payload = (
        json.dumps(migrated, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    write_private_atomic(ROLLBACK_RECORD, payload)

    verified, verified_backup, verified_exact = load_rollback_preimage(
        provenance
    )
    if (
        not verified_exact
        or verified_backup != backup_bytes
        or verified["generation"] != record["generation"]
        or verified["hook_path"] != record["hook_path"]
        or verified["preimage"] != record["preimage"]
        or verified["postimage"] != record["postimage"]
    ):
        refuse("rollback provenance migration postcondition failed")
    print(
        "install-worktree-hooks: migrated compatible rollback provenance "
        f"{previous_release[:12]} -> {current_release[:12]} "
        "(original preimage preserved)"
    )
    return True


def stage_hook_candidate(payload, mode, roles, variants, validation="install"):
    DEST.parent.mkdir(parents=True, exist_ok=True)
    fd, candidate_name = tempfile.mkstemp(
        dir=DEST.parent, prefix=f".{DEST.name}.e06-", suffix=".tmp"
    )
    candidate = Path(candidate_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            candidate_data = json.loads(candidate.read_text(encoding="utf-8"))
        except (UnicodeError, ValueError, json.JSONDecodeError):
            refuse("hook candidate is malformed")
        if validation == "remove":
            absent_matrix(candidate_data, variants)
        elif validation == "install":
            exact_matrix(candidate_data, roles, variants)
        elif validation == "document":
            validate_hook_document(candidate_data)
        else:
            refuse("unknown hook candidate validation")
        return candidate
    except Exception:
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
        raise


def restore_preimage(roles, variants, provenance):
    record, backup_bytes, _ = load_rollback_preimage(provenance)
    exists, current_bytes, current_mode = current_snapshot()
    preimage = record["preimage"]
    postimage = record["postimage"]
    if preimage["exists"]:
        already_restored = (
            exists
            and digest(current_bytes) == preimage["sha256"]
            and current_mode == preimage["mode"]
        )
    else:
        already_restored = not exists
    if already_restored:
        print("install-worktree-hooks --restore-preimage: already restored")
        return
    if (
        not exists
        or digest(current_bytes) != postimage["sha256"]
        or current_mode != postimage["mode"]
    ):
        refuse("current hook file does not match the captured transaction postimage")
    try:
        current_data = json.loads(current_bytes.decode("utf-8"))
    except (UnicodeError, ValueError, json.JSONDecodeError):
        refuse("current hook transaction postimage is malformed")
    exact_matrix(current_data, roles, variants)

    candidate = None
    if preimage["exists"]:
        candidate = stage_hook_candidate(
            backup_bytes,
            preimage["mode"],
            roles,
            variants,
            validation="document",
        )
        try:
            candidate_data = json.loads(candidate.read_text(encoding="utf-8"))
            validate_hook_document(candidate_data)
            if os.environ.get("DEV_AWA_HOOK_TEST_FAIL_STAGE") == "restore-candidate":
                refuse("injected restore candidate failure")
            create_backup(current_bytes, secrets.token_hex(16))
            assert_snapshot(True, current_bytes, current_mode)
            if os.environ.get("DEV_AWA_HOOK_TEST_FAIL_STAGE") == "restore-replace":
                refuse("injected restore replace failure")
            os.replace(candidate, DEST)
            sync_directory(DEST.parent)
            if os.environ.get("DEV_AWA_HOOK_TEST_FAIL_STAGE") == "restore-post-replace":
                refuse("injected restore post-replace failure")
        finally:
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
    else:
        create_backup(current_bytes, secrets.token_hex(16))
        assert_snapshot(True, current_bytes, current_mode)
        if os.environ.get("DEV_AWA_HOOK_TEST_FAIL_STAGE") == "restore-replace":
            refuse("injected restore replace failure")
        DEST.unlink()
        sync_directory(DEST.parent)
        if os.environ.get("DEV_AWA_HOOK_TEST_FAIL_STAGE") == "restore-post-replace":
            refuse("injected restore post-replace failure")

    restored_exists, restored_bytes, restored_mode = current_snapshot()
    if preimage["exists"]:
        if (
            not restored_exists
            or restored_bytes != backup_bytes
            or digest(restored_bytes) != preimage["sha256"]
            or restored_mode != preimage["mode"]
        ):
            refuse("post-restore Cursor hook file drift")
    elif restored_exists:
        refuse("post-restore Cursor hook file should be absent")
    print("install-worktree-hooks --restore-preimage: exact captured preimage restored")


try:
    roles, variants, provenance = validate_binding()
    if MODE == "remove" and not os.path.lexists(DEST):
        print("install-worktree-hooks --remove: already absent")
        raise SystemExit(0)
    if MODE == "check":
        data, old_bytes, prior_mode = load_hooks_for_mode()
        exact_matrix(data, roles, variants)
        validate_active_rollback(provenance, old_bytes, prior_mode)
        print(
            "install-worktree-hooks --check: exact external-owner seven-role matrix "
            "and rollback preimage OK"
        )
        raise SystemExit(0)

    lock_fd = acquire_rollback_lock()
    try:
        if MODE == "restore-preimage":
            restore_preimage(roles, variants, provenance)
            raise SystemExit(0)

        data, old_bytes, prior_mode = load_hooks_for_mode()
        old_exists = old_bytes is not None

        if MODE == "remove":
            hooks = data["hooks"]
            for event in list(hooks):
                hooks[event] = [
                    entry
                    for entry in hooks[event]
                    if not proven_variant(entry, variants)
                ]
            absent_matrix(data, variants)
        else:
            data = reconcile(data, roles, variants)
        new_bytes = (
            json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        if old_bytes == new_bytes:
            if MODE == "install":
                migrate_compatible_rollback_provenance(
                    provenance, old_bytes, prior_mode
                )
                validate_active_rollback(provenance, old_bytes, prior_mode)
            print(f"install-worktree-hooks: already current {DEST}")
            raise SystemExit(0)

        if MODE == "install" and os.path.lexists(ROLLBACK_RECORD):
            predecessors = COMPATIBLE_ROLLBACK_PREDECESSORS.get(
                provenance.get("release_commit"), frozenset()
            )
            record, _, provenance_exact = load_rollback_preimage(
                provenance,
                compatible_predecessors=predecessors,
            )
            if (
                digest(old_bytes) != record["postimage"]["sha256"]
                or prior_mode != record["postimage"]["mode"]
            ):
                refuse(
                    "rollback preimage record is stale for the current hook projection"
                )
            if not provenance_exact:
                refuse(
                    "compatible rollback provenance migration requires "
                    "an unchanged hook projection"
                )

        candidate = stage_hook_candidate(
            new_bytes,
            prior_mode,
            roles,
            variants,
            validation="remove" if MODE == "remove" else "install",
        )
        try:
            if os.environ.get("DEV_AWA_HOOK_TEST_FAIL_STAGE") == "candidate":
                refuse("injected candidate failure")
            if MODE == "install":
                capture_rollback_preimage(
                    old_bytes,
                    old_exists,
                    prior_mode,
                    new_bytes,
                    provenance,
                )
            elif old_exists:
                create_backup(old_bytes, secrets.token_hex(16))
            assert_snapshot(old_exists, old_bytes, prior_mode if old_exists else None)
            if os.environ.get("DEV_AWA_HOOK_TEST_FAIL_STAGE") == "replace":
                refuse("injected replace failure")
            os.replace(candidate, DEST)
            sync_directory(DEST.parent)
            if os.environ.get("DEV_AWA_HOOK_TEST_FAIL_STAGE") == "post-replace":
                refuse("injected post-replace failure")
            post_bytes, post_info = strict_owned_regular_info(
                DEST, "post-write Cursor hook file"
            )
            try:
                post = json.loads(post_bytes.decode("utf-8"))
            except (UnicodeError, ValueError, json.JSONDecodeError):
                refuse("post-write Cursor hook file is malformed")
            if MODE == "remove":
                absent_matrix(post, variants)
            else:
                exact_matrix(post, roles, variants)
                validate_active_rollback(provenance, post_bytes, prior_mode)
            if stat.S_IMODE(post_info.st_mode) != prior_mode:
                refuse("post-write Cursor hook mode drift")
            print(f"install-worktree-hooks: updated {DEST}")
        finally:
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
except Refusal as exc:
    print(f"install-worktree-hooks: REFUSED: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY
rc=$?
set -e

if [ "$rc" -eq 3 ] && [ "$MODE" = "check" ]; then
  printf 'install-worktree-hooks --check: no installed AWA external-owner state — static deferral\n'
  exit 0
fi
exit "$rc"
