"""Mode-0600 machine-local persistence for cross-process apply."""

from __future__ import annotations

import base64
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .canonical import (
    atomic_write,
    canonical_json,
    contained_path,
    digest_ref,
    parse_json_object,
)
from .transactions import (
    MutationAction,
    MutationRequest,
    ObservedInput,
    TransactionPreview,
    preview_transaction,
)


def private_state_root() -> Path:
    state = Path(
        os.environ.get(
            "XDG_STATE_HOME", str(Path.home() / ".local/state")
        )
    ).expanduser()
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    root = state / "doc-warden"
    root.mkdir(mode=0o700, exist_ok=True)
    return root.resolve(strict=True)


def _directory() -> Path:
    operations = private_state_root() / "operations"
    operations.mkdir(mode=0o700, parents=True, exist_ok=True)
    return operations.resolve(strict=True)


def operation_path(operation_id: str) -> Path:
    try:
        if str(uuid.UUID(operation_id)) != operation_id:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("operation_id_invalid") from exc
    return _directory() / f"{operation_id}.json"


def operation_schema(operation_id: str) -> str:
    path = operation_path(operation_id)
    if path.is_symlink() or not path.is_file():
        raise ValueError("operation_specification_unavailable")
    if path.stat().st_mode & 0o077:
        raise ValueError("operation_specification_permissions_invalid")
    schema = parse_json_object(path.read_bytes()).get("schema")
    if not isinstance(schema, str):
        raise ValueError("operation_specification_invalid")
    return schema


def store_preview(preview: TransactionPreview) -> str:
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=10)
    ).isoformat()
    payload = {
        "schema": "doc-warden/operation-specification/v1",
        "operation_id": preview.operation_id,
        "action_digest": preview.action_digest,
        "repo": preview.canonical_root,
        "repository_key": preview.repository_key,
        "github_repository_id": preview.github_repository_id,
        "transition": preview.transition,
        "actions": [
            {
                "path": action.path,
                "kind": action.kind,
                "content_base64": base64.b64encode(action.content).decode("ascii"),
            }
            for action in preview.actions
        ],
        "preimages": preview.preimages,
        "bindings": preview.bindings,
        "observed_inputs": [
            {"path": item.path, "digest": item.digest}
            for item in preview.observed_inputs
        ],
        "consequential": preview.consequential,
        "require_write_enabled": preview.require_write_enabled,
        "expires_at": expires_at,
    }
    root = _directory()
    path = atomic_write(root, f"{preview.operation_id}.json", canonical_json(payload))
    path.chmod(0o600)
    return expires_at


def load_preview(operation_id: str, action_digest: str) -> TransactionPreview:
    try:
        if str(uuid.UUID(operation_id)) != operation_id:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("operation_id_invalid") from exc
    path = operation_path(operation_id)
    if path.is_symlink() or not path.is_file():
        raise ValueError("operation_specification_unavailable")
    if path.stat().st_mode & 0o077:
        raise ValueError("operation_specification_permissions_invalid")
    payload = parse_json_object(path.read_bytes())
    required = {
        "schema",
        "operation_id",
        "action_digest",
        "repo",
        "repository_key",
        "github_repository_id",
        "transition",
        "actions",
        "preimages",
        "bindings",
        "observed_inputs",
        "consequential",
        "require_write_enabled",
        "expires_at",
    }
    if (
        set(payload) != required
        or payload["schema"] != "doc-warden/operation-specification/v1"
        or payload["operation_id"] != operation_id
        or payload["action_digest"] != action_digest
        or not isinstance(payload["consequential"], bool)
        or not isinstance(payload["require_write_enabled"], bool)
        or not isinstance(payload["actions"], list)
        or not isinstance(payload["preimages"], dict)
        or not isinstance(payload["bindings"], dict)
        or not isinstance(payload["observed_inputs"], list)
    ):
        raise ValueError("operation_specification_mismatch")
    expires = datetime.fromisoformat(str(payload["expires_at"]))
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError("operation_specification_expired")
    try:
        actions = tuple(
            MutationAction(
                path=entry["path"],
                kind=entry["kind"],
                content=base64.b64decode(entry["content_base64"], validate=True),
            )
            for entry in payload["actions"]
            if isinstance(entry, dict)
            and set(entry) == {"path", "kind", "content_base64"}
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("operation_specification_invalid") from exc
    if len(actions) != len(payload["actions"]):
        raise ValueError("operation_specification_invalid")
    try:
        observed_inputs = tuple(
            ObservedInput(path=entry["path"], digest=entry["digest"])
            for entry in payload["observed_inputs"]
            if isinstance(entry, dict) and set(entry) == {"path", "digest"}
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("operation_specification_invalid") from exc
    if len(observed_inputs) != len(payload["observed_inputs"]):
        raise ValueError("operation_specification_invalid")
    if set(payload["preimages"]) != {action.path for action in actions} or any(
        value is not None
        and (
            not isinstance(value, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
        )
        for value in payload["preimages"].values()
    ):
        raise ValueError("operation_specification_invalid")
    repo = Path(payload["repo"])
    recovery_preimages = {}
    for action in actions:
        destination = contained_path(repo, action.path)
        observed = digest_ref(destination.read_bytes()) if destination.is_file() else None
        postimage = digest_ref(action.content)
        if observed == postimage and observed != payload["preimages"][action.path]:
            recovery_preimages[action.path] = payload["preimages"][action.path]
    preview = preview_transaction(
        MutationRequest(
            repo=repo,
            repository_key=payload["repository_key"],
            github_repository_id=payload["github_repository_id"],
            transition=payload["transition"],
            actions=actions,
            bindings=payload["bindings"],
            operation_id=operation_id,
            observed_inputs=observed_inputs,
            consequential=payload["consequential"],
            require_write_enabled=payload["require_write_enabled"],
        ),
        recovery_preimages=recovery_preimages or None,
    )
    if preview.action_digest != action_digest:
        raise ValueError("operation_specification_mismatch")
    return preview


def consume_preview(operation_id: str) -> None:
    try:
        if str(uuid.UUID(operation_id)) != operation_id:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("operation_id_invalid") from exc
    (_directory() / f"{operation_id}.json").unlink(missing_ok=True)
