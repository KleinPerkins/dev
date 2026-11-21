"""Exact consent, current state and durable receipts for authoring continuity."""

from __future__ import annotations

import fcntl
import os
import stat
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .artifacts import validate_consent
from .canonical import atomic_write, canonical_json, contained_path, digest_ref, parse_json_object
from .operation_store import operation_path
from .save_game_adapter import (
    SaveGameAdapter, event_from_envelope, live_binding, prepare_authoring_resume, prepare_checkpoint, validate_pointer,
)
from .validators import require_valid

OPERATION_SCHEMA = "doc-warden/continuity-operation/v1"
RECORD_SCHEMA = "doc-warden/continuity-record/v1"
SESSION_SCHEMA = "doc-warden/continuity-session/v2"
INTENTS = frozenset({"checkpoint", "handoff", "pause-with-continuity", "resume-authoring"})
NEXT_ACTION = {
    "continuity_preview_required": "prepare_continuity_preview",
    "continuity_state_changed": "reload_current_authoring_state",
    "continuity_operation_busy": "retry_same_operation_after_writer_finishes",
    "save_game_unavailable": "install_qualified_save_game",
    "save_game_unqualified": "verify_save_game_source_pin",
    "save_game_observation_unavailable": "install_qualified_save_game_observation",
    "save_game_unadopted": "enable_save_game_adoption",
    "save_game_adoption_disabled": "enable_save_game_adoption",
    "save_game_saved_private_unadopted": "verify_private_save_and_enable_adoption",
    "save_game_checkpoint_unadopted": "choose_a_new_adopted_checkpoint_scope",
    "save_game_workstream_busy": "retry_same_operation_after_writer_finishes",
    "save_game_owner_recovery_required": "request_save_game_owner_recovery",
    "save_game_owner_recovery_blocked": "inspect_save_game_with_owner",
    "save_game_owner_recovery_conflict": "inspect_save_game_with_owner",
    "save_game_invalid_evidence": "inspect_save_game_with_owner",
    "save_game_checkpoint_ambiguous": "inspect_save_game_with_owner",
    "save_game_privacy_blocked": "inspect_save_game_with_owner",
    "save_game_checkpoint_unavailable": "select_current_qualified_checkpoint",
    "save_game_workstream_unavailable": "select_current_qualified_checkpoint",
    "save_game_checkpoint_required": "prepare_checkpoint_preview",
    "save_game_checkpoint_stale": "select_current_qualified_checkpoint",
    "save_game_pointer_identity_mismatch": "reload_current_authoring_state",
    "save_game_live_conflict": "resolve_git_conflict_before_retry",
    "authoring_git_conflict": "resolve_git_conflict_before_retry",
    "authoring_live_state_changed": "review_live_authority_and_prepare_new_preview",
    "save_game_live_state_changed": "review_live_authority_and_prepare_new_preview",
    "authoring_source_revision_changed": "review_live_authority_and_prepare_new_preview",
    "authoring_repository_mismatch": "select_current_governed_checkout",
    "save_game_identity_mismatch": "verify_save_game_workstream_identity",
    "save_game_timeout": "read_current_owner_state_before_retry",
    "save_game_invocation_failed": "read_current_owner_state_before_retry",
}


def _state_root(path: Path) -> Path:
    # The operation store has already created the private doc-warden state root.
    return path.parent.parent


def _record_path(root: Path, state: dict[str, Any]) -> Path:
    return contained_path(root, f"continuity/{state['repository_key']}/{state['operation_id']}.json")


def _validate_record(record: dict[str, Any], operation: str, scope: dict[str, Any]) -> None:
    if (not isinstance(record, dict) or set(record) != {"schema", "operation_id", "action_digest", "state"}
            or record["schema"] != RECORD_SCHEMA or record["operation_id"] != operation):
        raise ValueError("continuity_state_invalid")
    state = record["state"]
    require_valid("authoring-state", state)
    if state["repository_key"] != scope["repository_key"] or state["operation_id"] != scope["operation_id"]:
        raise ValueError("continuity_state_invalid")
    validate_pointer(state["save_game_pointer"])


def _read_session(path: Path, scope: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any], str | None]:
    if not path.is_file():
        return None, {}, None
    if path.stat().st_mode & 0o077:
        raise ValueError("continuity_state_permissions_invalid")
    content = path.read_bytes()
    session = parse_json_object(content)
    if content != canonical_json(session):
        raise ValueError("continuity_state_invalid")
    if session.get("schema") == RECORD_SCHEMA and isinstance(session.get("operation_id"), str):
        current = session["operation_id"]
        receipts = {current: session}
    elif (session.get("schema") == SESSION_SCHEMA and set(session) == {"schema", "current_operation_id", "receipts"}
            and isinstance(session["current_operation_id"], str) and isinstance(session["receipts"], dict)):
        current, receipts = session["current_operation_id"], session["receipts"]
    else:
        raise ValueError("continuity_state_invalid")
    if current not in receipts:
        raise ValueError("continuity_state_invalid")
    for operation, record in receipts.items():
        _validate_record(record, operation, scope)
    return receipts[current], receipts, digest_ref(content)


def _summary(payload: dict[str, Any], *, status: str) -> dict[str, Any]:
    return {"status": status, "intent": payload["intent"], "operation_id": payload["operation_id"],
            "action_digest": payload["action_digest"], "source_revision": payload["authoring_state"]["source_revision"]}


def preview_continuity(repo: Path, state: dict[str, Any], event: dict[str, Any], *,
                       intent: str, operation_id: str) -> dict[str, Any]:
    if intent not in INTENTS:
        raise ValueError("authoring_continuity_intent_invalid")
    root = repo.resolve(strict=True)
    decoded_event = event_from_envelope(event)
    observed = live_binding(root, state, decoded_event)
    if state["save_game_pointer"] is not None:
        validate_pointer(state["save_game_pointer"])
    path = operation_path(operation_id)
    existing, _, preimage = _read_session(_record_path(_state_root(path), state), state)
    if existing is not None and existing["state"] != state:
        raise ValueError("continuity_state_changed")
    if intent == "resume-authoring" and existing is None:
        raise ValueError("save_game_checkpoint_required")
    body = {"schema": OPERATION_SCHEMA, "operation_id": operation_id, "repo": str(root), "intent": intent,
            "authoring_state": state, "event": asdict(decoded_event), "record_preimage": preimage,
            "observed_live_binding": observed}
    action = digest_ref(canonical_json(body))
    expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    if path.exists():
        if (path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077
                or parse_json_object(path.read_bytes()).get("action_digest") != action):
            raise ValueError("operation_replay_mismatch")
    payload = body | {"action_digest": action, "expires_at": expires}
    atomic_write(path.parent, path.name, canonical_json(payload))
    return _summary(payload, status="consent_required") | {
        "schema": "doc-warden/continuity-preview/v1",
        "repository_key": state["repository_key"], "canonical_root": str(root),
        "authoring_operation_id": state["operation_id"], "expires_at": expires, "consent_required": True,
        "consequence": "lifecycle", "owner_private_save": intent != "resume-authoring",
    }


def apply_continuity(operation_id: str, action_digest: str, consent: dict[str, Any] | None,
                     *, adapter: SaveGameAdapter | None = None) -> dict[str, Any]:
    path = operation_path(operation_id)
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("operation_specification_unavailable")
    payload = parse_json_object(path.read_bytes())
    fields = {"schema", "operation_id", "repo", "intent", "authoring_state", "event", "record_preimage",
              "observed_live_binding", "action_digest", "expires_at"}
    if (set(payload) != fields or payload["schema"] != OPERATION_SCHEMA or payload["operation_id"] != operation_id
            or payload["intent"] not in INTENTS or payload["action_digest"] != action_digest
            or digest_ref(canonical_json({key: value for key, value in payload.items()
                                          if key not in {"action_digest", "expires_at"}})) != action_digest):
        raise ValueError("operation_specification_mismatch")
    expires = datetime.fromisoformat(payload["expires_at"])
    if expires.tzinfo is None:
        raise ValueError("operation_specification_expired")
    state = payload["authoring_state"]
    require_valid("authoring-state", state)
    event = event_from_envelope(payload["event"])
    repo = Path(payload["repo"]).resolve(strict=True)
    consent_scope = {"operation_id": operation_id, "repository_key": state["repository_key"],
                     "canonical_root": str(repo), "source_revision": state["source_revision"],
                     "action_digest": action_digest, "consequence_class": "lifecycle"}
    validate_consent(consent, **consent_scope, allow_expired=True)
    if str(repo) != payload["repo"] or live_binding(repo, state, event) != payload["observed_live_binding"]:
        raise ValueError("authoring_live_state_changed")
    state_root = _state_root(path)
    target = _record_path(state_root, state)
    lock_path = contained_path(state_root, target.relative_to(state_root).as_posix() + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    try:
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid() or opened.st_mode & 0o077):
            raise ValueError("continuity_lock_invalid")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("continuity_operation_busy") from exc
        record, receipts, preimage = _read_session(target, state)
        completed = receipts.get(operation_id)
        if completed is not None:
            if completed["action_digest"] != action_digest:
                raise ValueError("operation_replay_mismatch")
            return _summary(payload, status="applied") | {"state": completed["state"]}
        # Expired authorization can identify a completed receipt. It cannot
        # authorize the first provider call or state write for an operation.
        if expires <= datetime.now(timezone.utc):
            raise ValueError("operation_specification_expired")
        validate_consent(consent, **consent_scope)
        if preimage != payload["record_preimage"] or (record is not None and record["state"] != state):
            raise ValueError("continuity_state_changed")
        if live_binding(repo, state, event) != payload["observed_live_binding"]:
            raise ValueError("authoring_live_state_changed")
        provider = adapter or SaveGameAdapter(root=repo)
        updated = (prepare_authoring_resume(repo, state, event, provider)
                   if payload["intent"] == "resume-authoring"
                   else prepare_checkpoint(repo, state, event, provider, request_digest=action_digest, intent=payload["intent"]))
        if live_binding(repo, state, event) != payload["observed_live_binding"]:
            raise ValueError("authoring_live_state_changed")
        committed = {"schema": RECORD_SCHEMA, "operation_id": operation_id, "action_digest": action_digest,
                     "state": updated}
        # Advance the current pointer and retain prior receipts in one atomic write.
        receipts[operation_id] = committed
        session = {"schema": SESSION_SCHEMA, "current_operation_id": operation_id, "receipts": receipts}
        atomic_write(state_root, target.relative_to(state_root).as_posix(), canonical_json(session))
        observed_record, observed_receipts, _ = _read_session(target, state)
        if observed_record != committed or observed_receipts != receipts:
            raise ValueError("continuity_state_readback_failed")
        return _summary(payload, status="applied") | {"state": updated}
    finally:
        os.close(fd)
