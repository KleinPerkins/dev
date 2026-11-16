#!/usr/bin/env bash
# Preview, install, uninstall, or exactly restore doc-warden's advisory user hooks.
set -euo pipefail
umask 077

usage() {
  printf 'Usage: %s --dry-run|--install|--uninstall|--restore\n' "$0" >&2
}

if [ "$#" -ne 1 ]; then
  usage
  exit 64
fi

case "$1" in
  --dry-run) mode="dry-run" ;;
  --install) mode="install" ;;
  --uninstall) mode="uninstall" ;;
  --restore) mode="restore" ;;
  *)
    usage
    exit 64
    ;;
esac

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd -P)"
export DOC_WARDEN_HOOK_INSTALL_ROOT
DOC_WARDEN_HOOK_INSTALL_ROOT="$(
  CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd -P
)"
export DOC_WARDEN_HOOK_INSTALL_MODE="$mode"
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import shlex
import tempfile
from pathlib import Path
from typing import Any


MODE = os.environ["DOC_WARDEN_HOOK_INSTALL_MODE"]
HOME = Path(os.environ["HOME"])
HOOKS_PATH = Path(
    os.environ.get("DOC_WARDEN_HOOKS_FILE", str(HOME / ".cursor/hooks.json"))
)
STATE_ROOT = Path(
    os.environ.get(
        "XDG_STATE_HOME",
        str(HOME / ".local/state"),
    )
) / "doc-warden/hooks"
BACKUP_PATH = STATE_ROOT / "preimage.json"
MANIFEST_PATH = STATE_ROOT / "preimage-manifest.json"
FAIL_STAGE = os.environ.get("DOC_WARDEN_HOOK_TEST_FAIL_STAGE", "")
ABSENT_HOOKS = b'{"version":1,"hooks":{}}\n'
ABSENT_PREIMAGE_MARKER = b"doc-warden/hook-preimage-absent/v1\n"

INSTALL_ROOT = Path(os.environ["DOC_WARDEN_HOOK_INSTALL_ROOT"])


def hook_command(name: str, *arguments: str) -> str:
    script = INSTALL_ROOT / "_ops/cursor-hooks" / name
    return " ".join(
        shlex.quote(value)
        for value in ("/bin/bash", str(script), *arguments)
    )


OWNED_ROWS: tuple[dict[str, Any], ...] = (
    {
        "event": "sessionStart",
        "semantics": "advisory_context",
        "can_block": False,
        "entry": {
            "type": "command",
            "command": hook_command("doc-warden-session.sh"),
            "description": "doc-warden-session-context",
            "failClosed": False,
        },
    },
    {
        "event": "afterFileEdit",
        "semantics": "observation_only",
        "can_block": False,
        "entry": {
            "type": "command",
            "command": hook_command(
                "doc-warden-observe.sh",
                "after-file-edit",
            ),
            "description": "doc-warden-observe-file-edit",
            "failClosed": False,
        },
    },
    {
        "event": "stop",
        "semantics": "observation_only",
        "can_block": False,
        "entry": {
            "type": "command",
            "command": hook_command("doc-warden-observe.sh", "stop"),
            "description": "doc-warden-observe-stop",
            "failClosed": False,
        },
    },
)
OWNED_DESCRIPTIONS = {
    row["entry"]["description"]
    for row in OWNED_ROWS
}

CLOUD = {
    "user_hooks_run_in_cloud": False,
    "project_command_hooks_only": True,
    "supported_cloud_events": [
        "beforeShellExecution",
        "afterFileEdit",
    ],
    "message": (
        "User hooks do not run in Cursor Cloud. Only committed project command "
        "hooks and their documented project events are available there."
    ),
}


def emit(value: dict[str, Any]) -> None:
    print(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def read_preimage() -> tuple[bool, bytes, dict[str, Any]]:
    if HOOKS_PATH.is_symlink():
        raise SystemExit("hook_path_unsafe")
    existed = HOOKS_PATH.exists()
    raw = (
        HOOKS_PATH.read_bytes()
        if existed
        else ABSENT_HOOKS
    )
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"hooks_json_invalid:{exc}") from exc
    if not isinstance(document, dict):
        raise SystemExit("hooks_json_not_object")
    hooks = document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit("hooks_member_not_object")
    return existed, raw, document


def stable_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def payload_digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def read_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file() or MANIFEST_PATH.is_symlink():
        raise SystemExit("hook_preimage_manifest_invalid")
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("hook_preimage_manifest_invalid") from exc
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "schema",
            "existed",
            "preimage_sha256",
            "installed_sha256",
        }
        or manifest.get("schema") != "doc-warden/hook-preimage/v2"
        or type(manifest.get("existed")) is not bool
        or not valid_digest(manifest.get("installed_sha256"))
        or (
            manifest["existed"]
            and not valid_digest(manifest.get("preimage_sha256"))
        )
        or (
            not manifest["existed"]
            and manifest.get("preimage_sha256") is not None
        )
        or BACKUP_PATH.is_symlink()
        or (
            manifest["existed"]
            and not BACKUP_PATH.is_file()
        )
        or (
            not manifest["existed"]
            and BACKUP_PATH.exists()
            and (
                not BACKUP_PATH.is_file()
                or BACKUP_PATH.read_bytes() != ABSENT_PREIMAGE_MARKER
            )
        )
    ):
        raise SystemExit("hook_preimage_manifest_invalid")
    if (
        manifest["existed"]
        and payload_digest(BACKUP_PATH.read_bytes())
        != manifest["preimage_sha256"]
    ):
        raise SystemExit("hook_preimage_bytes_invalid")
    return manifest


def ensure_backup(existed: bool, raw: bytes) -> tuple[bool, bytes]:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    if MANIFEST_PATH.exists() or MANIFEST_PATH.is_symlink():
        manifest = read_manifest()
        return (
            manifest["existed"],
            (
                BACKUP_PATH.read_bytes()
                if manifest["existed"]
                else ABSENT_HOOKS
            ),
        )
    if BACKUP_PATH.exists() or BACKUP_PATH.is_symlink():
        if BACKUP_PATH.is_symlink() or not BACKUP_PATH.is_file():
            raise SystemExit("hook_preimage_bytes_invalid")
        try:
            backup_raw = BACKUP_PATH.read_bytes()
            preimage_existed = backup_raw != ABSENT_PREIMAGE_MARKER
            preimage_raw = backup_raw if preimage_existed else ABSENT_HOOKS
            preimage_document = json.loads(preimage_raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit("hook_preimage_bytes_invalid") from exc
        if not isinstance(preimage_document, dict):
            raise SystemExit("hook_preimage_bytes_invalid")
        hooks = preimage_document.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise SystemExit("hook_preimage_bytes_invalid")
        try:
            _, additions = install(preimage_document)
        except SystemExit as exc:
            raise SystemExit("hook_preimage_bytes_invalid") from exc
        if (
            len(additions) != len(OWNED_ROWS)
            or restore_projection(preimage_raw)
            != restore_projection(raw)
        ):
            raise SystemExit("hook_preimage_bytes_invalid")
        return preimage_existed, preimage_raw
    atomic_write(
        BACKUP_PATH,
        raw if existed else ABSENT_PREIMAGE_MARKER,
    )
    return existed, raw


def save_manifest(existed: bool, raw: bytes, installed: bytes) -> None:
    atomic_write(
        MANIFEST_PATH,
        stable_bytes(
            {
                "schema": "doc-warden/hook-preimage/v2",
                "existed": existed,
                "preimage_sha256": payload_digest(raw) if existed else None,
                "installed_sha256": payload_digest(installed),
            }
        ),
    )


def install(
    document: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    hooks = document["hooks"]
    expected_by_description = {
        row["entry"]["description"]: (row["event"], row["entry"])
        for row in OWNED_ROWS
    }
    seen_owned: set[str] = set()
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            raise SystemExit(f"hook_event_not_list:{event}")
        for entry in entries:
            if not isinstance(entry, dict):
                raise SystemExit(f"hook_entry_not_object:{event}")
            description = entry.get("description")
            if description not in OWNED_DESCRIPTIONS:
                continue
            if description in seen_owned:
                raise SystemExit(f"owned_hook_collision:{description}")
            seen_owned.add(description)
            expected_event, expected_entry = expected_by_description[description]
            if event != expected_event or entry != expected_entry:
                raise SystemExit(f"owned_hook_collision:{description}")
    additions: list[dict[str, Any]] = []
    for row in OWNED_ROWS:
        entries = hooks.setdefault(row["event"], [])
        if row["entry"] not in entries:
            entries.append(row["entry"])
            additions.append(row)
    return document, additions


def uninstall(document: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False
    for event, entries in document["hooks"].items():
        if not isinstance(entries, list):
            raise SystemExit(f"hook_event_not_list:{event}")
        retained = [
            entry
            for entry in entries
            if not (
                isinstance(entry, dict)
                and entry.get("description") in OWNED_DESCRIPTIONS
            )
        ]
        if retained != entries:
            changed = True
            document["hooks"][event] = retained
    return document, changed


def restore_projection(payload: bytes) -> dict[str, Any] | None:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    hooks = document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        return None
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            return None
        retained = []
        for entry in entries:
            if not isinstance(entry, dict):
                return None
            if entry.get("description") not in OWNED_DESCRIPTIONS:
                retained.append(entry)
        hooks[event] = retained
    for row in OWNED_ROWS:
        hooks.setdefault(row["event"], [])
    return document


def reconstruct_owned_free_preimage(
    document: dict[str, Any],
) -> bytes:
    hooks = document["hooks"]
    for row in OWNED_ROWS:
        event = row["event"]
        entry = row["entry"]
        entries = hooks.get(event)
        if not isinstance(entries, list):
            raise SystemExit("hook_preimage_bytes_invalid")
        retained = [
            candidate
            for candidate in entries
            if candidate != entry
        ]
        if len(entries) - len(retained) != 1:
            raise SystemExit("hook_preimage_bytes_invalid")
        hooks[event] = retained
    return stable_bytes(document)


def repair_missing_manifest(
    installed: bytes,
    installed_document: dict[str, Any],
) -> None:
    if MANIFEST_PATH.exists() or MANIFEST_PATH.is_symlink():
        return
    if not BACKUP_PATH.exists() and not BACKUP_PATH.is_symlink():
        canonical_absent, _ = install(json.loads(ABSENT_HOOKS))
        # With both state files lost, an absent file is indistinguishable
        # from an existing file containing ABSENT_HOOKS. Infer absence only
        # for the exact canonical bytes that installing that placeholder
        # creates; every other shape is reconstructed as an existing file.
        preimage_existed = installed != stable_bytes(canonical_absent)
        preimage_raw = (
            reconstruct_owned_free_preimage(installed_document)
            if preimage_existed
            else ABSENT_HOOKS
        )
        ensure_backup(preimage_existed, preimage_raw)
        save_manifest(preimage_existed, preimage_raw, installed)
        return
    if BACKUP_PATH.is_symlink() or not BACKUP_PATH.is_file():
        raise SystemExit("hook_preimage_bytes_invalid")
    try:
        backup_raw = BACKUP_PATH.read_bytes()
        preimage_existed = backup_raw != ABSENT_PREIMAGE_MARKER
        preimage_raw = backup_raw if preimage_existed else ABSENT_HOOKS
        preimage_document = json.loads(preimage_raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("hook_preimage_bytes_invalid") from exc
    if not isinstance(preimage_document, dict):
        raise SystemExit("hook_preimage_bytes_invalid")
    hooks = preimage_document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SystemExit("hook_preimage_bytes_invalid")
    try:
        expected_document, additions = install(preimage_document)
    except SystemExit as exc:
        raise SystemExit("hook_preimage_bytes_invalid") from exc
    expected_projection = restore_projection(
        stable_bytes(expected_document)
    )
    installed_projection = restore_projection(installed)
    if (
        not additions
        or expected_projection is None
        or installed_projection != expected_projection
    ):
        raise SystemExit("hook_preimage_bytes_invalid")
    save_manifest(preimage_existed, preimage_raw, installed)


if MODE == "dry-run":
    _, _, document = read_preimage()
    _, additions = install(document)
    emit(
        {
            "schema": "doc-warden/hook-install-preview/v1",
            "mode": MODE,
            "owned_additions": additions,
            "cloud": CLOUD,
            "writes": [],
        }
    )
    raise SystemExit(0)

if MODE == "restore":
    if not MANIFEST_PATH.exists() and not MANIFEST_PATH.is_symlink():
        raise SystemExit("hook_preimage_missing")
    manifest = read_manifest()
    preimage_raw = (
        BACKUP_PATH.read_bytes()
        if manifest["existed"]
        else ABSENT_HOOKS
    )
    if (
        manifest["existed"]
        and payload_digest(preimage_raw) != manifest["preimage_sha256"]
    ):
        raise SystemExit("hook_preimage_bytes_invalid")
    preimage_projection = restore_projection(preimage_raw)
    if preimage_projection is None:
        raise SystemExit("hook_preimage_bytes_invalid")
    if HOOKS_PATH.is_symlink():
        raise SystemExit("hook_path_unsafe")
    current_exists = HOOKS_PATH.exists()
    current_raw = HOOKS_PATH.read_bytes() if current_exists else None
    current_digest = (
        payload_digest(current_raw)
        if current_raw is not None
        else None
    )
    already_restored = (
        manifest["existed"]
        and current_exists
        and current_digest == manifest["preimage_sha256"]
    ) or (not manifest["existed"] and not current_exists)
    recoverable = (
        not current_exists
        or current_digest == manifest["installed_sha256"]
        or (
            current_raw is not None
            and restore_projection(current_raw) == preimage_projection
        )
    )
    if (
        not already_restored
        and not recoverable
    ):
        raise SystemExit("hook_restore_conflict")
    if manifest.get("existed") is True:
        if not already_restored:
            atomic_write(HOOKS_PATH, preimage_raw)
    elif manifest.get("existed") is False:
        if not already_restored:
            try:
                HOOKS_PATH.unlink()
            except FileNotFoundError:
                pass
    else:
        raise SystemExit("hook_preimage_manifest_invalid")
    emit(
        {
            "schema": "doc-warden/hook-install-result/v1",
            "mode": MODE,
            "status": "restored",
            "cloud": CLOUD,
        }
    )
    raise SystemExit(0)

existed, raw, document = read_preimage()
if MODE == "install":
    candidate, additions = install(document)
    candidate_bytes = stable_bytes(candidate) if additions else raw
    if additions:
        preimage_existed, preimage_raw = ensure_backup(existed, raw)
        if FAIL_STAGE == "before-replace":
            raise SystemExit("forced_failure_before_replace")
        atomic_write(HOOKS_PATH, candidate_bytes)
        save_manifest(
            preimage_existed,
            preimage_raw,
            candidate_bytes,
        )
    else:
        repair_missing_manifest(candidate_bytes, candidate)
    status = "installed"
elif MODE == "uninstall":
    candidate, changed = uninstall(document)
    candidate_bytes = stable_bytes(candidate) if changed else raw
    if changed:
        atomic_write(HOOKS_PATH, candidate_bytes)
    status = "uninstalled"
else:
    raise SystemExit("unsupported_mode")

emit(
    {
        "schema": "doc-warden/hook-install-result/v1",
        "mode": MODE,
        "status": status,
        "cloud": CLOUD,
    }
)
PY
