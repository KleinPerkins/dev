"""Optional, closed-projection Save-Game adapter for authoring continuity."""

from __future__ import annotations

import re
import shutil
import subprocess
import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .canonical import canonical_json, digest_ref, parse_json_object
from .validators import read_repository_config, require_valid


POINTER_FIELDS = {
    "schema",
    "checkpoint_id",
    "checkpoint_digest",
    "status",
    "artifact_ids",
    "next_action_code",
    "blocker_ids",
    "authority_pointers",
}
NEXT_ACTIONS = {
    "author",
    "review",
    "validate",
    "reconcile",
    "wait",
    "complete",
}
EVENT_FIELDS = {
    "operation_id",
    "artifact_ids",
    "next_action_code",
    "blocker_ids",
    "authority_pointers",
}


@dataclass(frozen=True)
class CheckpointEvent:
    operation_id: str
    artifact_ids: tuple[str, ...]
    next_action_code: str
    blocker_ids: tuple[str, ...] = ()
    authority_pointers: tuple[str, ...] = ()


class SaveGameAdapter:
    def __init__(
        self,
        *,
        home: Path | None = None,
        root: Path | None = None,
        runner: Callable[[str, CheckpointEvent], dict[str, Any]] | None = None,
    ):
        self.home = (home or Path.home()).resolve()
        self.root = (root or Path.cwd()).resolve()
        self.runner = runner

    def executable(self) -> Path | None:
        candidates = (
            self.home / ".cursor/skills/save-game/scripts/save-game.sh",
            self.home / ".claude/skills/save-game/scripts/save-game.sh",
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        discovered = shutil.which("save-game")
        return Path(discovered) if discovered else None

    def available(self) -> bool:
        return self.runner is not None or self.executable() is not None

    def _unavailable(self, event: CheckpointEvent) -> dict[str, Any]:
        return {
            "schema": "doc-warden/save-game-pointer/v1",
            "checkpoint_id": "unavailable",
            "checkpoint_digest": "sha256:" + "0" * 64,
            "status": "unavailable",
            "artifact_ids": list(event.artifact_ids),
            "next_action_code": event.next_action_code,
            "blocker_ids": list(event.blocker_ids),
            "authority_pointers": list(event.authority_pointers),
        }

    def _invoke(self, verb: str, event: CheckpointEvent) -> dict[str, Any]:
        executable = self.executable()
        if executable is None:
            return self._unavailable(event)
        task_seed = event.operation_id.encode("utf-8")
        task_id = "doc-warden-" + hashlib.sha256(task_seed).hexdigest()[:16]
        prefix = [str(executable), "--root", str(self.root)]
        if verb == "checkpoint":
            first = prefix + [
                "flush",
                "--task-id",
                task_id,
                "--client-id",
                "unknown",
                "--objective",
                "doc-warden authoring continuity",
                "--next-action",
                event.next_action_code,
            ]
        else:
            first = prefix + [
                "reconcile",
                "--task-id",
                task_id,
                "--trigger",
                "resume",
            ]
        subprocess.run(first, text=True, capture_output=True, timeout=30, check=True)
        resolved = subprocess.run(
            prefix + ["index", "--task-id", task_id],
            text=False,
            capture_output=True,
            timeout=30,
            check=True,
        )
        checkpoint = parse_json_object(resolved.stdout)
        checkpoint_id = checkpoint.get("checkpoint_id")
        if not isinstance(checkpoint_id, str):
            raise ValueError("save_game_checkpoint_invalid")
        return {
            "schema": "doc-warden/save-game-pointer/v1",
            "checkpoint_id": checkpoint_id,
            "checkpoint_digest": digest_ref(canonical_json(checkpoint)),
            "status": "created" if verb == "checkpoint" else "reconciled",
            "artifact_ids": list(event.artifact_ids),
            "next_action_code": event.next_action_code,
            "blocker_ids": list(event.blocker_ids),
            "authority_pointers": list(event.authority_pointers),
        }

    def checkpoint(self, event: CheckpointEvent) -> dict[str, Any]:
        validate_event(event)
        if self.runner is not None:
            try:
                pointer = self.runner("checkpoint", event)
            except Exception:
                pointer = self._unavailable(event)
        else:
            try:
                pointer = self._invoke("checkpoint", event)
            except Exception:
                pointer = self._unavailable(event)
        return validate_pointer(pointer)

    def reconcile(self, event: CheckpointEvent) -> dict[str, Any]:
        validate_event(event)
        if self.runner is not None:
            try:
                pointer = self.runner("reconcile", event)
            except Exception:
                pointer = self._unavailable(event)
        else:
            try:
                pointer = self._invoke("reconcile", event)
            except Exception:
                pointer = self._unavailable(event)
        return validate_pointer(pointer)


def validate_pointer(pointer: object) -> dict[str, Any]:
    if not isinstance(pointer, dict) or set(pointer) != POINTER_FIELDS:
        raise ValueError("save_game_pointer_not_closed")
    if pointer.get("schema") != "doc-warden/save-game-pointer/v1":
        raise ValueError("save_game_pointer_schema")
    if pointer.get("status") not in {"created", "updated", "reconciled", "unavailable"}:
        raise ValueError("save_game_pointer_status")
    if pointer.get("next_action_code") not in NEXT_ACTIONS:
        raise ValueError("save_game_pointer_next_action")
    if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", str(pointer.get("checkpoint_id", ""))) is None:
        raise ValueError("save_game_pointer_id")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", str(pointer.get("checkpoint_digest", ""))) is None:
        raise ValueError("save_game_pointer_digest")
    for field in ("artifact_ids", "blocker_ids", "authority_pointers"):
        values = pointer.get(field)
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError("save_game_pointer_list")
        if any(
            not isinstance(value, str)
            or len(value) > 256
            or re.fullmatch(r"[A-Za-z0-9._:/-]+", value) is None
            for value in values
        ):
            raise ValueError("save_game_pointer_value")
    return pointer


def validate_event(event: CheckpointEvent) -> None:
    try:
        uuid.UUID(event.operation_id)
    except (ValueError, TypeError) as exc:
        raise ValueError("save_game_event_operation") from exc
    if event.next_action_code not in NEXT_ACTIONS:
        raise ValueError("save_game_pointer_next_action")
    for field in (event.artifact_ids, event.blocker_ids, event.authority_pointers):
        if len(field) > 100 or any(
            not isinstance(value, str)
            or len(value) > 256
            or re.fullmatch(r"[A-Za-z0-9._:/-]+", value) is None
            for value in field
        ):
            raise ValueError("save_game_event_value")


def event_from_envelope(raw: dict[str, Any]) -> CheckpointEvent:
    if set(raw) != EVENT_FIELDS or any(
        not isinstance(raw[field], list)
        for field in ("artifact_ids", "blocker_ids", "authority_pointers")
    ):
        raise ValueError("save_game_event_contract_invalid")
    event = CheckpointEvent(
        operation_id=raw["operation_id"],
        artifact_ids=tuple(raw["artifact_ids"]),
        next_action_code=raw["next_action_code"],
        blocker_ids=tuple(raw["blocker_ids"]),
        authority_pointers=tuple(raw["authority_pointers"]),
    )
    validate_event(event)
    return event


def prepare_checkpoint(
    repo: Path,
    authoring_state: dict[str, Any],
    event: CheckpointEvent,
    adapter: SaveGameAdapter,
) -> dict[str, Any]:
    require_valid("authoring-state", authoring_state)
    root = repo.resolve(strict=True)
    config = read_repository_config(root)
    if config is None or config["repository_key"] != authoring_state["repository_key"]:
        raise ValueError("authoring_repository_mismatch")
    validate_event(event)
    if event.operation_id != authoring_state["operation_id"]:
        raise ValueError("save_game_event_operation")
    pointer = adapter.checkpoint(event)
    updated = dict(authoring_state)
    prior = authoring_state.get("save_game_pointer")
    updated["save_game_pointer"] = (
        prior
        if pointer["status"] == "unavailable"
        and isinstance(prior, dict)
        and prior.get("status") != "unavailable"
        else pointer
    )
    updated["next_action_code"] = event.next_action_code
    require_valid("authoring-state", updated)
    return updated


def prepare_authoring_resume(
    repo: Path,
    authoring_state: dict[str, Any],
    event: CheckpointEvent,
    adapter: SaveGameAdapter,
) -> dict[str, Any]:
    require_valid("authoring-state", authoring_state)
    validate_event(event)
    if event.operation_id != authoring_state["operation_id"]:
        raise ValueError("save_game_event_operation")
    root = repo.resolve(strict=True)
    config = read_repository_config(root)
    if config is None or config["repository_key"] != authoring_state["repository_key"]:
        raise ValueError("authoring_repository_mismatch")
    for pointer in event.authority_pointers:
        relative = Path(pointer)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("authoring_authority_path_invalid")
        path = root / relative
        if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
            raise ValueError("authoring_authority_missing")
    reconciled = adapter.reconcile(event)
    updated = dict(authoring_state)
    prior = authoring_state.get("save_game_pointer")
    updated["save_game_pointer"] = (
        prior
        if reconciled["status"] == "unavailable"
        and isinstance(prior, dict)
        and prior.get("status") != "unavailable"
        else reconciled
    )
    updated["lifecycle"] = "planned"
    updated["next_action_code"] = event.next_action_code
    require_valid("authoring-state", updated)
    return updated
