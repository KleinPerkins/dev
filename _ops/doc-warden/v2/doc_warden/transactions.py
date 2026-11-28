"""Preview-bound, idempotent local governance transactions."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import atomic_write, canonical_json, digest_ref
from .scm import observe_repository_identity
from .validators import (
    read_repository_config,
    require_valid,
    validate_design_authority_binding,
    validate_egress,
)


TRANSITIONS = {
    "creation_snapshot",
    "draft_update",
    "accepted_freeze",
    "roadmap_update",
    "projection_update",
    "migration_adoption",
    "supersession",
}
SOURCE_TRACKED_CANONICAL_ROOT = "$REPOSITORY_ROOT"


@dataclass(frozen=True)
class MutationAction:
    path: str
    content: bytes
    kind: str = "auto"


@dataclass(frozen=True)
class ObservedInput:
    path: str
    digest: str


@dataclass(frozen=True)
class MutationRequest:
    repo: Path
    repository_key: str
    transition: str
    actions: tuple[MutationAction, ...]
    bindings: dict[str, Any]
    operation_id: str | None = None
    github_repository_id: int | None = None
    observed_inputs: tuple[ObservedInput, ...] = ()
    consequential: bool = True
    require_write_enabled: bool = False


@dataclass(frozen=True)
class TransactionPreview:
    repo: Path
    canonical_root: str
    root_identity: tuple[int, int]
    repository_key: str
    github_repository_id: int | None
    transition: str
    operation_id: str
    event_id: str
    source_revision: str
    action_digest: str
    actions: tuple[MutationAction, ...]
    preimages: dict[str, str | None]
    postimages: dict[str, str]
    bindings: dict[str, Any]
    observed_inputs: tuple[ObservedInput, ...]
    consequential: bool
    require_write_enabled: bool


@dataclass(frozen=True)
class ExplicitConfirmation:
    operation_id: str
    action_digest: str
    source_revision: str
    canonical_root: str
    choice: str
    confirmation_digest: str


def _head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "no-head"


def _root_identity(repo: Path) -> tuple[int, int]:
    info = repo.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("canonical root is not a directory")
    return info.st_dev, info.st_ino


def _operation_ids(operation_id: str | None) -> tuple[str, str]:
    operation = operation_id or str(uuid.uuid4())
    uuid.UUID(operation)
    return operation, str(uuid.uuid5(uuid.UUID(operation), "terminal-event"))


def directory_input_digest(path: Path, *, omit: set[str] | None = None) -> str:
    """Domain-separated immediate names/types; file bytes have separate bindings."""
    rows = []
    for child in sorted(path.iterdir()):
        if child.name in (omit or set()):
            continue
        mode = child.lstat().st_mode
        kind = ("symlink" if stat.S_ISLNK(mode) else "directory"
                if stat.S_ISDIR(mode) else "file" if stat.S_ISREG(mode) else "special")
        rows.append([child.name, kind])
    return digest_ref(canonical_json({"domain": "doc-warden/directory-input/v1", "entries": rows}))


def _validated_observed_inputs(
    observed_inputs: tuple[ObservedInput, ...],
    *, preview: TransactionPreview | None = None,
) -> tuple[ObservedInput, ...]:
    validated = []
    seen: set[str] = set()
    for item in observed_inputs:
        path = Path(item.path)
        if (not path.is_absolute() or path.is_symlink()
                or not (path.is_file() or path.is_dir())
                or re.fullmatch(r"sha256:[0-9a-f]{64}", item.digest) is None):
            raise ValueError("observed_input_invalid")
        canonical = str(path.resolve(strict=True))
        if canonical != item.path or canonical in seen:
            raise ValueError("observed_input_invalid")
        seen.add(canonical)
        observed = directory_input_digest(path) if path.is_dir() else digest_ref(path.read_bytes())
        if observed != item.digest and path.is_dir() and preview is not None:
            # Reconstruct only this operation's own directory additions for
            # interrupted apply/replay. Unexpected descendants cannot disappear.
            created = {preview.repo / action.path: preview.postimages[action.path]
                       for action in preview.actions if preview.preimages[action.path] is None}
            created[preview.repo / _event_path(preview)] = digest_ref(canonical_json(_event_for(preview)))
            created[preview.repo / _receipt_path(preview)] = digest_ref(canonical_json(
                _receipt_for(preview, confirmation_for(preview).confirmation_digest if preview.consequential else None)))
            omit = set()
            for child in path.iterdir():
                if child.is_symlink():
                    continue
                leaves = list(child.rglob("*")) if child.is_dir() else [child]
                files = [leaf for leaf in leaves if not leaf.is_dir()]
                if ((child in created or any(child in output.parents for output in created))
                        and all(not leaf.is_symlink() and leaf.is_file()
                        and leaf in created and digest_ref(leaf.read_bytes()) == created[leaf]
                        for leaf in files)
                        and all(not leaf.is_symlink() and (
                            not leaf.is_dir() or any(leaf in output.parents for output in created)
                        ) for leaf in leaves)):
                    omit.add(child.name)
            observed = directory_input_digest(path, omit=omit)
        if observed != item.digest:
            raise ValueError("observed_input_drift")
        validated.append(item)
    return tuple(validated)


def _validate_repository_identity(
    repo: Path,
    bindings: dict[str, Any],
    github_repository_id: int | None,
) -> None:
    expected = bindings.get("repository_identity")
    if expected is None:
        return
    if not isinstance(expected, dict):
        raise ValueError("repository_identity_invalid")
    observed = observe_repository_identity(repo)
    if (
        not observed.matches_binding(expected)
        or observed.github_repository_id != github_repository_id
    ):
        raise ValueError("repository_identity_mismatch")


def preview_transaction(
    request: MutationRequest,
    *,
    recovery_preimages: dict[str, str | None] | None = None,
) -> TransactionPreview:
    if request.transition not in TRANSITIONS:
        raise ValueError("unsupported transition")
    repo = request.repo.resolve(strict=True)
    uuid.UUID(request.repository_key)
    persisted = read_repository_config(repo)
    if persisted and persisted["repository_key"] != request.repository_key:
        raise ValueError("repository_key_mismatch")
    key = persisted["repository_key"] if persisted else request.repository_key
    github_repository_id = request.github_repository_id
    if persisted and persisted["github_repository_id"] is not None:
        if github_repository_id not in {None, persisted["github_repository_id"]}:
            raise ValueError("github_repository_id_mismatch")
        github_repository_id = persisted["github_repository_id"]
    design_authority = request.bindings.get("design_authority")
    if design_authority is not None:
        validate_design_authority_binding(repo, design_authority)
    observed_inputs = request.observed_inputs
    operation_id, event_id = _operation_ids(request.operation_id)
    preimages: dict[str, str | None] = {}
    postimages: dict[str, str] = {}
    action_records: list[dict[str, Any]] = []
    normalized_actions: list[MutationAction] = []
    seen: set[str] = set()
    from .canonical import contained_path

    if recovery_preimages is not None and not set(recovery_preimages).issubset({
        action.path for action in request.actions
    }):
        raise ValueError("recovery preimages do not match actions")
    for action in request.actions:
        if action.path in seen:
            raise ValueError("duplicate action path")
        seen.add(action.path)
        destination = contained_path(repo, action.path)
        observed_preimage = digest_ref(destination.read_bytes()) if destination.exists() else None
        if recovery_preimages is not None and action.path in recovery_preimages:
            recovered_preimage = recovery_preimages[action.path]
            if action.kind not in {"create", "replace"} or not destination.is_file():
                raise ValueError("invalid create recovery state")
            if digest_ref(destination.read_bytes()) != digest_ref(action.content):
                raise ValueError("create recovery postimage mismatch")
            preimages[action.path] = recovered_preimage
        else:
            preimages[action.path] = observed_preimage
        postimages[action.path] = digest_ref(action.content)
        effective_kind = (
            "replace" if destination.exists() else "create"
        ) if action.kind == "auto" else action.kind
        if effective_kind not in {"create", "replace"}:
            raise ValueError("unsupported action kind")
        normalized_actions.append(MutationAction(action.path, action.content, effective_kind))
        action_records.append(
            {"kind": effective_kind, "path": action.path, "content_digest": postimages[action.path]}
        )
    source_revision = _head(repo)
    digest_input = {
        "schema": "doc-warden/action-set/v2",
        "operation_id": operation_id,
        "repository_key": key,
        "github_repository_id": github_repository_id,
        "canonical_root": str(repo),
        "source_revision": source_revision,
        "transition": request.transition,
        "actions": action_records,
        "preimages": preimages,
        "postimages": postimages,
        "bindings": request.bindings,
        "observed_inputs": [
            {"path": item.path, "digest": item.digest} for item in observed_inputs
        ],
        "consequential": request.consequential,
        "require_write_enabled": request.require_write_enabled,
    }
    preview = TransactionPreview(
        repo=repo,
        canonical_root=str(repo),
        root_identity=_root_identity(repo),
        repository_key=key,
        github_repository_id=github_repository_id,
        transition=request.transition,
        operation_id=operation_id,
        event_id=event_id,
        source_revision=source_revision,
        action_digest=digest_ref(canonical_json(digest_input)),
        actions=tuple(normalized_actions),
        preimages=preimages,
        postimages=postimages,
        bindings=request.bindings,
        observed_inputs=observed_inputs,
        consequential=request.consequential,
        require_write_enabled=request.require_write_enabled,
    )
    _validated_observed_inputs(observed_inputs, preview=preview if recovery_preimages else None)
    return preview


def confirmation_for(preview: TransactionPreview, choice: str = "apply") -> ExplicitConfirmation:
    payload = {
        "schema": "doc-warden/explicit-confirmation/v1",
        "operation_id": preview.operation_id,
        "action_digest": preview.action_digest,
        "source_revision": preview.source_revision,
        "canonical_root": preview.canonical_root,
        "choice": choice,
    }
    return ExplicitConfirmation(
        operation_id=preview.operation_id,
        action_digest=preview.action_digest,
        source_revision=preview.source_revision,
        canonical_root=preview.canonical_root,
        choice=choice,
        confirmation_digest=digest_ref(canonical_json(payload)),
    )


def _validate_confirmation(
    preview: TransactionPreview, confirmation: ExplicitConfirmation | None
) -> str | None:
    if not preview.consequential:
        return None
    if confirmation is None:
        raise ValueError("explicit_confirmation_required")
    expected = confirmation_for(preview, confirmation.choice)
    if confirmation.choice != "apply" or confirmation != expected:
        raise ValueError("explicit_confirmation_mismatch")
    return confirmation.confirmation_digest


def _receipt_path(preview: TransactionPreview) -> str:
    return f"_ops/doc-warden/state/v2/receipts/{preview.operation_id}.json"


def _event_path(preview: TransactionPreview) -> str:
    return f"_ops/doc-warden/state/v2/events/{preview.event_id}.json"


def _cleanup_staged_duplicates(preview: TransactionPreview) -> None:
    from .canonical import contained_path

    targets = [action.path for action in preview.actions]
    targets.extend((_event_path(preview), _receipt_path(preview)))
    for relative in targets:
        destination = contained_path(preview.repo, relative)
        if not destination.is_file():
            continue
        for staged in destination.parent.glob(f".{destination.name}.*"):
            suffix = staged.name[len(destination.name) + 2 :]
            if re.fullmatch(r"[a-z0-9_]{8}", suffix) is None:
                continue
            staged_relative = str(staged.relative_to(preview.repo))
            staged_path = contained_path(preview.repo, staged_relative)
            staged_path.unlink()


def _event_for(preview: TransactionPreview) -> dict[str, Any]:
    return {
        "schema": "doc-warden/operation-event/v2",
        "event_id": preview.event_id,
        "operation_id": preview.operation_id,
        "transition": preview.transition,
        "action_digest": preview.action_digest,
        "source_revision": preview.source_revision,
        "prior_event_digest": None,
        "outcome": "applied",
        "details": {"postimages": preview.postimages},
    }


def _receipt_for(preview: TransactionPreview, confirmation_digest: str | None) -> dict[str, Any]:
    event = _event_for(preview)
    return {
        "schema": "doc-warden/receipt/v2",
        "repository_key": preview.repository_key,
        "github_repository_id": preview.github_repository_id,
        "canonical_root": SOURCE_TRACKED_CANONICAL_ROOT,
        "operation_id": preview.operation_id,
        "event_id": preview.event_id,
        "prior_event_digest": None,
        "source_revision": preview.source_revision,
        "action_digest": preview.action_digest,
        "preimages": preview.preimages,
        "postimages": preview.postimages,
        "result_tree_digest": digest_ref(
            canonical_json({"event": event, "postimages": preview.postimages})
        ),
        "delivery_commit": None,
        "transition": preview.transition,
        "bindings": preview.bindings,
        "observed_input_digests": [
            item.digest for item in preview.observed_inputs
        ],
        "actions": [
            {
                "kind": action.kind,
                "path": action.path,
                "content_digest": preview.postimages[action.path],
            }
            for action in preview.actions
        ],
        "verification": [],
        "outcome": "applied",
        "confirmation_digest": confirmation_digest,
    }


def _validate_or_normalize_replay_receipt(
    preview: TransactionPreview,
    receipt_file: Path,
    existing: dict[str, Any],
) -> dict[str, Any]:
    try:
        validate_egress("receipt", existing)
        return existing
    except ValueError as current_error:
        prior_root = existing.get("canonical_root")
        if (
            existing.get("schema") != "doc-warden/receipt/v2"
            or prior_root != preview.canonical_root
            or not Path(str(prior_root)).is_absolute()
        ):
            raise current_error
    normalized = {**existing, "canonical_root": SOURCE_TRACKED_CANONICAL_ROOT}
    validate_egress("receipt", normalized)
    atomic_write(
        preview.repo,
        str(receipt_file.relative_to(preview.repo)),
        canonical_json(normalized),
    )
    return normalized


def apply_transaction(
    preview: TransactionPreview, confirmation: ExplicitConfirmation | None
) -> dict[str, Any]:
    if _root_identity(preview.repo) != preview.root_identity or str(preview.repo.resolve()) != preview.canonical_root:
        raise ValueError("canonical_root_changed")
    if _head(preview.repo) != preview.source_revision:
        raise ValueError("source_revision_changed")
    _validate_repository_identity(
        preview.repo, preview.bindings, preview.github_repository_id
    )
    design_authority = preview.bindings.get("design_authority")
    if design_authority is not None:
        validate_design_authority_binding(preview.repo, design_authority)
    _validated_observed_inputs(preview.observed_inputs, preview=preview)
    confirmation_digest = _validate_confirmation(preview, confirmation)
    receipt_file = preview.repo / _receipt_path(preview)
    if receipt_file.exists():
        from .canonical import parse_json_object

        existing = parse_json_object(receipt_file.read_bytes())
        if receipt_file.read_bytes() != canonical_json(existing):
            raise ValueError("receipt_not_canonical")
        if existing.get("action_digest") != preview.action_digest:
            raise ValueError("operation_replay_mismatch")
        from .canonical import contained_path

        for action in preview.actions:
            destination = contained_path(preview.repo, action.path)
            if not destination.is_file() or digest_ref(destination.read_bytes()) != preview.postimages[action.path]:
                raise ValueError("receipt_postimage_mismatch")
        event_file = preview.repo / _event_path(preview)
        if not event_file.is_file():
            raise ValueError("receipt_event_missing")
        event = parse_json_object(event_file.read_bytes())
        validate_egress("event", event)
        if event_file.read_bytes() != canonical_json(event) or (
            event["event_id"],
            event["operation_id"],
            event["action_digest"],
            event["transition"],
            event["source_revision"],
            event["details"],
        ) != (
            preview.event_id,
            preview.operation_id,
            preview.action_digest,
            preview.transition,
            preview.source_revision,
            {"postimages": preview.postimages},
        ):
            raise ValueError("receipt_event_mismatch")
        existing = _validate_or_normalize_replay_receipt(
            preview, receipt_file, existing
        )
        _cleanup_staged_duplicates(preview)
        return existing
    delivery = preview.bindings.get("release_delivery")
    if delivery is not None:
        from .release_delivery import observe_merged_delivery

        if observe_merged_delivery(preview.repo, delivery["canonical_url"], delivery["merge_commit"]) != delivery:
            raise ValueError("release_delivery_changed")
    receipt = _receipt_for(preview, confirmation_digest)
    validate_egress("receipt", receipt)
    from .canonical import contained_path

    event = _event_for(preview)
    validate_egress("event", event)
    observed_postimages = True
    operation_started = False
    for action in preview.actions:
        destination = contained_path(preview.repo, action.path)
        observed = digest_ref(destination.read_bytes()) if destination.exists() else None
        if observed != preview.postimages[action.path]:
            observed_postimages = False
        elif observed != preview.preimages[action.path]:
            operation_started = True
        if observed not in {preview.preimages[action.path], preview.postimages[action.path]}:
            raise ValueError("preimage_changed")
    if preview.require_write_enabled:
        persisted = read_repository_config(preview.repo)
        enabled = bool(persisted and persisted["enabled"])
        for action in preview.actions:
            if action.path != ".planning/doc-warden.json":
                continue
            from .canonical import parse_json_object

            proposed = parse_json_object(action.content)
            require_valid("doc-warden-config", proposed)
            if persisted is None:
                enabled = proposed["enabled"]
            elif preview.transition == "migration_adoption":
                enabled = (
                    proposed["enabled"]
                    and proposed["repository_key"] == preview.repository_key
                    and proposed["github_repository_id"]
                    == preview.github_repository_id
                )
            break
        if not enabled and not operation_started:
            raise ValueError("repository_write_disabled")
    event_file = preview.repo / _event_path(preview)
    if observed_postimages:
        if event_file.exists() and (
            not event_file.is_file() or event_file.read_bytes() != canonical_json(event)
        ):
            raise ValueError("partial_operation_event_mismatch")
        if not event_file.exists():
            atomic_write(preview.repo, _event_path(preview), canonical_json(event))
    else:
        for action in preview.actions:
            atomic_write(preview.repo, action.path, action.content)
        atomic_write(preview.repo, _event_path(preview), canonical_json(event))
    atomic_write(preview.repo, _receipt_path(preview), canonical_json(receipt))
    _cleanup_staged_duplicates(preview)
    return receipt


def replay_operation_events(repo: Path) -> dict[str, Any]:
    from .canonical import parse_json_object

    events = []
    event_root = repo / "_ops" / "doc-warden" / "state" / "v2" / "events"
    for path in sorted(event_root.glob("*.json")) if event_root.exists() else []:
        event = parse_json_object(path.read_bytes())
        require_valid("operation-event", event)
        events.append(event)
    return {"schema": "doc-warden/projection-state/v1", "events": events}
