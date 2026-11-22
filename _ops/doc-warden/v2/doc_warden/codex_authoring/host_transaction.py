"""Consent and recovery for the native project discovery projection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import stat
import subprocess
from typing import Callable
from uuid import uuid4

from ..artifacts import validate_consent
from ..canonical import atomic_write, canonical_json, contained_path, digest_ref, parse_json_object
from ..live_install import _runtime_writer
from ..operation_store import operation_path, private_state_root
from .host_projection import (
    PROJECTION_PATHS,
    apply_descriptors,
    descriptor_images,
    observe_descriptors,
    render_descriptors,
)


OPERATION_SCHEMA = "doc-warden/codex-projection-operation/v1"
STATE_SCHEMA = "doc-warden/codex-projection-state/v1"
SOURCE_ENTRY = "_ops/bin/doc-warden.sh"
MAX_RECORD_BYTES = 256 * 1024
VerifyInstallation = Callable[[dict], None]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), *args],
        capture_output=True, check=False, text=True, timeout=10,
    )
    if result.returncode:
        raise ValueError("native_authoring_project_unavailable")
    return result.stdout.strip()


def _project_identity(root: Path) -> dict:
    root = root.resolve(strict=True)
    if _git(root, "rev-parse", "--show-toplevel") != str(root):
        raise ValueError("native_authoring_project_root_required")
    info = root.stat()
    return {"path": str(root), "device": info.st_dev, "inode": info.st_ino}


def _regular_private(path: Path) -> dict | None:
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_size > MAX_RECORD_BYTES):
        raise ValueError("native_authoring_projection_record_invalid")
    raw = path.read_bytes()
    value = parse_json_object(raw)
    if raw != canonical_json(value):
        raise ValueError("native_authoring_projection_record_invalid")
    return value


def _state_relative(project: Path) -> str:
    name = digest_ref(str(project).encode()).removeprefix("sha256:")
    return f"runtime/codex/projections/{name}.json"


def _read_state(root: Path, project: Path) -> dict:
    empty = {"schema": STATE_SCHEMA, "active": None, "pending": None, "last": None}
    if not root.is_dir():
        return empty
    value = _regular_private(contained_path(root, _state_relative(project)))
    if value is None:
        return empty
    if set(value) != set(empty) or value["schema"] != STATE_SCHEMA:
        raise ValueError("native_authoring_projection_record_invalid")
    return value


def _owned_images(state: dict) -> dict:
    active = state["active"]
    if active is None:
        return descriptor_images({})
    images = active.get("images")
    if not isinstance(images, dict) or set(images) != set(PROJECTION_PATHS):
        raise ValueError("native_authoring_projection_record_invalid")
    return images


def _new_projection(binding: dict | None) -> dict[str, bytes]:
    if binding is None:
        return {}
    return render_descriptors(Path(binding["source_root"]) / SOURCE_ENTRY)


def _state_digest(state: dict) -> str:
    return digest_ref(canonical_json(state))


def _operation_digest(operation: dict) -> str:
    return _state_digest({
        key: value for key, value in operation.items()
        if key not in {"schema", "action_digest"}
    })


def prepare_host_change(
    project: Path, *, home: Path, data_home: Path, authority: dict,
    binding: dict | None, verify: VerifyInstallation,
) -> dict:
    """Write private preview metadata. The project and client are observed only."""
    identity = _project_identity(project)
    project = Path(identity["path"])
    state_root = private_state_root()
    state = _read_state(state_root, project)
    if state["pending"] is not None:
        raise ValueError("native_authoring_projection_recovery_required")
    if state["active"] is not None and state["active"]["owner"] != {
        "project_identity": identity, "home": str(home.resolve()), "data_home": str(data_home.resolve())
    }:
        raise ValueError("native_authoring_projection_destination_changed")
    before = observe_descriptors(project)
    if before != _owned_images(state):
        raise ValueError("native_authoring_projection_foreign")
    if binding is None:
        if state["active"] is None:
            raise ValueError("native_authoring_projection_not_installed")
    else:
        verify(binding)
    after = descriptor_images(_new_projection(binding))
    operation = {
        "schema": OPERATION_SCHEMA,
        "operation_id": str(uuid4()),
        "target": "codex",
        "consequence": "install_codex_authoring" if binding is not None else "remove_codex_authoring",
        "project_identity": identity,
        "project_revision": _git(project, "rev-parse", "HEAD"),
        "home": str(home.resolve()),
        "data_home": str(data_home.resolve()),
        "canonical_root": authority["canonical_root"],
        "repository_key": authority["repository_key"],
        "source_revision": authority["source_revision"],
        "binding": binding,
        "before": before,
        "after": after,
        "ownership_preimage": _state_digest(state),
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "global_hooks": [],
    }
    operation["action_digest"] = _operation_digest(operation)
    target = operation_path(operation["operation_id"])
    atomic_write(target.parent, target.name, canonical_json(operation))
    return operation | {"consent_required": True}


def _is_expired(expires_at: str) -> bool:
    deadline = datetime.fromisoformat(expires_at)
    return deadline.tzinfo is None or deadline <= datetime.now(timezone.utc)


def apply_host_change(
    operation_id: str, digest: str, consent: dict | None, *,
    verify: VerifyInstallation, revalidate: VerifyInstallation | None = None,
    verify_projection: VerifyInstallation | None = None,
) -> dict:
    operation = _regular_private(operation_path(operation_id))
    if (operation is None or operation.get("schema") != OPERATION_SCHEMA
            or operation.get("operation_id") != operation_id
            or operation.get("action_digest") != digest or _operation_digest(operation) != digest):
        raise ValueError("native_authoring_projection_operation_mismatch")
    validate_consent(
        consent, operation_id=operation_id, repository_key=operation["repository_key"],
        canonical_root=operation["canonical_root"], source_revision=operation["source_revision"],
        action_digest=digest, consequence_class="external",
        # The preflight below separately checks freshness before a first write.
        allow_expired=True,
    )
    project = Path(operation["project_identity"]["path"])
    home, data_home = Path(operation["home"]), Path(operation["data_home"])
    if _project_identity(project) != operation["project_identity"]:
        raise ValueError("native_authoring_projection_destination_changed")
    state_root = private_state_root()
    relative = _state_relative(project)
    result = {
        "schema": "doc-warden/codex-projection-result/v1",
        "operation_id": operation_id,
        "action_digest": digest,
        "target": "codex",
        "status": "removed" if operation["binding"] is None else "installed",
        "source_revision": operation["source_revision"],
        "postimages": operation["after"],
    }
    if _is_expired(operation["expires_at"]) or _is_expired(consent["expires_at"]):
        snapshot = _read_state(state_root, project)
        if snapshot["last"] != result and snapshot["pending"] != digest:
            raise ValueError("operation_specification_expired")
    with _runtime_writer(home, data_home, project=project):
        state = _read_state(state_root, project)
        if state["last"] == result:
            if observe_descriptors(project) != operation["after"]:
                raise ValueError("native_authoring_projection_changed")
            return result
        recovering = state["pending"] == digest
        if not recovering:
            if state["pending"] is not None:
                raise ValueError("native_authoring_projection_recovery_required")
            if (_is_expired(operation["expires_at"]) or _is_expired(consent["expires_at"])):
                raise ValueError("operation_specification_expired")
            if _state_digest(state) != operation["ownership_preimage"]:
                raise ValueError("native_authoring_projection_ownership_changed")
            if observe_descriptors(project) != operation["before"]:
                raise ValueError("native_authoring_projection_changed")
        if _git(project, "rev-parse", "HEAD") != operation["project_revision"]:
            raise ValueError("native_authoring_projection_project_changed")
        binding = operation["binding"]
        if binding is not None:
            if not recovering and revalidate is not None:
                revalidate(binding)
            else:
                verify(binding)
        descriptors = _new_projection(binding)
        if descriptor_images(descriptors) != operation["after"]:
            raise ValueError("native_authoring_projection_specification_changed")
        if not recovering:
            atomic_write(state_root, relative, canonical_json(state | {"pending": digest}))
        apply_descriptors(project, before=operation["before"], descriptors=descriptors)
        if binding is not None and verify_projection is not None:
            try:
                verify_projection(binding)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                raise ValueError("native_authoring_projection_recovery_required") from error
        active = None if binding is None else {
            "owner": {key: operation[key] for key in ("project_identity", "home", "data_home")},
            "binding": binding,
            "images": operation["after"],
        }
        atomic_write(state_root, relative, canonical_json(state | {"pending": None, "active": active, "last": result}))
    return result


def read_installed_projection(project: Path, *, state_root: Path, home: Path, data_home: Path) -> dict:
    """Read installed inputs without creating or repairing any state."""
    identity = _project_identity(project)
    project = Path(identity["path"])
    state = _read_state(state_root, project)
    if state["pending"] is not None:
        raise ValueError("native_authoring_projection_recovery_required")
    active = state["active"]
    if active is None:
        raise ValueError("native_authoring_projection_not_installed")
    if active["owner"] != {
        "project_identity": identity, "home": str(home.resolve()), "data_home": str(data_home.resolve())
    }:
        raise ValueError("native_authoring_projection_destination_changed")
    if observe_descriptors(project) != active["images"]:
        raise ValueError("native_authoring_projection_changed")
    return active["binding"]
