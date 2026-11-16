"""Durable defect records adapted from the pinned GSD DEBUG contract."""

from __future__ import annotations

import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import _artifact_bytes, _bindings
from .canonical import canonical_json, digest_ref, parse_json_object
from .defect_authority import DefectAuthority, prepare_authority, validate_replay_authority
from .roadmap import (
    new_defect_roadmap_item,
    parse_roadmap,
    render_roadmap,
    update_defect_roadmap_item,
)
from .transactions import (
    MutationAction,
    MutationRequest,
    TransactionPreview,
    apply_transaction,
    confirmation_for,
    preview_transaction,
)
from .validators import (
    _DEFECT_RELATION_FOR_TARGET,
    _DEFECT_TERMINAL_LIFECYCLES,
    _DEFECT_TRANSITIONS,
    _complete_defect_known_good_revision,
    _has_meaningful_string_entries,
    ValidatedDefectArtifact,
    defect_event_digest,
    defect_ready_issues,
    defect_symptoms_digest,
    load_defect_artifact,
    parse_defect_id,
    read_repository_config,
    regenerate_defect_current_view,
    require_valid,
    validate_defect_record,
    validate_egress,
)


_AUTHOR_CLASSES = {"operator", "agent", "system", "test"}
_LIFECYCLE = {
    "reported",
    "triaged",
    "investigating",
    "ready",
    "fixing",
    "verifying",
    "resolved",
    "duplicate",
    "waived",
    "wont_fix",
    "recurred",
    "superseded",
}
_DEFECT_EVENT_LABELS = frozenset(
    {
        "created",
        "evidence",
        "exemption-reevaluated",
        "elimination",
        "symptoms-frozen",
        "focus",
        "resolution",
        "promoted",
    }
    | {f"transition-{target}" for target in _LIFECYCLE}
)
_CONSEQUENTIAL_TARGETS = {"waived", "wont_fix", "superseded"}
_SYMPTOM_FIELDS = (
    "environment",
    "preconditions",
    "test_data",
    "reproduction",
    "expected",
    "actual",
    "error_reference",
    "frequency",
    "known_good_revision",
    "known_bad_revision",
    "immutable_symptoms",
)
_TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "defect.md"


@dataclass(frozen=True)
class DefectPreview:
    transaction: TransactionPreview
    defect_id: str
    defect_path: str
    repository_key: str
    defect_event_id: str


@dataclass(frozen=True)
class ReadyVerdict:
    defect_id: str
    lifecycle: str
    ready: bool
    missing_fields: tuple[str, ...]
    invalid_fields: tuple[str, ...]


@dataclass(frozen=True)
class PrdSeed:
    record: dict[str, Any]
    receipt: dict[str, Any]


def _head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "no-head"


def _head_time(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", "-s", "--format=%cI", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return (
        result.stdout.strip()
        if result.returncode == 0 and result.stdout.strip()
        else "1970-01-01T00:00:00+00:00"
    )


def _operation(value: str | None) -> str:
    operation_id = value or str(uuid.uuid4())
    uuid.UUID(operation_id)
    return operation_id


def _strings(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field}_must_be_string_array")
    return list(value)


def _mapping(value: object, field: str, default: dict[str, Any]) -> dict[str, Any]:
    if value is None:
        return dict(default)
    if not isinstance(value, dict):
        raise ValueError(f"{field}_must_be_object")
    return dict(value)


def _scope(value: object) -> dict[str, Any]:
    default = {
        "repositories": 1,
        "components": [],
        "sessions": 1,
        "new_behavior": False,
        "ui_visual": False,
        "sensitive": False,
        "new_dependency": False,
        "schema_or_state_change": False,
        "reversible": True,
    }
    candidate = _mapping(value, "scope", default)
    if set(candidate) != set(default):
        raise ValueError("scope_contract_invalid")
    if (
        not isinstance(candidate["repositories"], int)
        or isinstance(candidate["repositories"], bool)
        or candidate["repositories"] < 1
        or not isinstance(candidate["sessions"], int)
        or isinstance(candidate["sessions"], bool)
        or candidate["sessions"] < 1
        or not isinstance(candidate["components"], list)
        or any(not isinstance(item, str) or not item for item in candidate["components"])
        or len(set(candidate["components"])) != len(candidate["components"])
        or any(
            not isinstance(candidate[field], bool)
            for field in (
                "new_behavior",
                "ui_visual",
                "sensitive",
                "new_dependency",
                "schema_or_state_change",
                "reversible",
            )
        )
    ):
        raise ValueError("scope_contract_invalid")
    return candidate


def _focus(value: object) -> dict[str, Any]:
    default = {
        "hypothesis": "",
        "test": "",
        "expecting": "",
        "next_action": "gather exact symptoms",
        "bug_class": None,
        "reasoning_checkpoint": None,
        "tdd_checkpoint": None,
    }
    candidate = _mapping(value, "current_focus", default)
    if set(candidate) != set(default):
        raise ValueError("current_focus_contract_invalid")
    for field in ("hypothesis", "test", "expecting", "next_action"):
        if not isinstance(candidate[field], str):
            raise ValueError("current_focus_contract_invalid")
    return candidate


def _resolution(value: object) -> dict[str, Any]:
    default = {
        "root_cause": None,
        "fix": None,
        "verification": {"automated": [], "human": []},
        "oracle_type": None,
        "files_changed": [],
    }
    candidate = _mapping(value, "resolution", default)
    if set(candidate) != set(default):
        raise ValueError("resolution_contract_invalid")
    verification = candidate.get("verification")
    if not isinstance(verification, dict) or set(verification) != {"automated", "human"}:
        raise ValueError("resolution_contract_invalid")
    candidate["verification"] = {
        "automated": _strings(verification["automated"], "automated_verification"),
        "human": _strings(verification["human"], "human_verification"),
    }
    candidate["files_changed"] = _strings(
        candidate["files_changed"], "resolution_files_changed"
    )
    return candidate


def _verification_plan(value: object) -> dict[str, list[str]]:
    candidate = _mapping(
        value,
        "verification_plan",
        {"automated": [], "human": []},
    )
    if set(candidate) != {"automated", "human"}:
        raise ValueError("verification_plan_contract_invalid")
    return {
        "automated": _strings(candidate["automated"], "automated_verification_plan"),
        "human": _strings(candidate["human"], "human_verification_plan"),
    }


def _exemption(value: object) -> dict[str, Any]:
    candidate = _mapping(
        value,
        "exemption",
        {
            "decision": "exempt",
            "conditions": [True, True, True, False, True],
        },
    )
    if (
        set(candidate) != {"decision", "conditions"}
        or candidate["decision"] not in {"exempt", "promote"}
        or not isinstance(candidate["conditions"], list)
        or len(candidate["conditions"]) != 5
        or any(not isinstance(item, bool) for item in candidate["conditions"])
    ):
        raise ValueError("defect_exemption_contract_invalid")
    return {
        "decision": candidate["decision"],
        "conditions": list(candidate["conditions"]),
    }


def _exemption_assessment(value: object) -> dict[str, Any]:
    required = {
        "timestamp",
        "source",
        "author_class",
        "conditions",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or any(
            not isinstance(value[field], str) or not value[field]
            for field in ("timestamp", "source", "author_class")
        )
        or value["author_class"] not in _AUTHOR_CLASSES
        or not isinstance(value["conditions"], list)
        or len(value["conditions"]) != 5
        or any(not isinstance(item, bool) for item in value["conditions"])
    ):
        raise ValueError("defect_exemption_assessment_invalid")
    return {
        "timestamp": value["timestamp"],
        "source": value["source"],
        "author_class": value["author_class"],
        "conditions": list(value["conditions"]),
    }


def _event_id(operation_id: str, defect_id: str, label: str) -> str:
    return str(uuid.uuid5(uuid.UUID(operation_id), f"{defect_id}:{label}"))


def _append_event(
    record: dict[str, Any],
    *,
    operation_id: str,
    label: str,
    kind: str,
    timestamp: str,
    source: str,
    author_class: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if not source or author_class not in _AUTHOR_CLASSES:
        raise ValueError("defect_event_actor_invalid")
    event_id = _event_id(operation_id, record["id"], label)
    prior = record["events"][-1] if record["events"] else None
    event = {
        "event_id": event_id,
        "kind": kind,
        "timestamp": timestamp,
        "source": source,
        "author_class": author_class,
        "prior_event_id": prior["event_id"] if prior else None,
        "prior_event_digest": prior["event_digest"] if prior else None,
        "payload": payload,
    }
    event["event_digest"] = defect_event_digest(event)
    updated = dict(record)
    updated["events"] = [*record["events"], event]
    updated = regenerate_defect_current_view(updated)
    validate_defect_record(updated)
    return updated, event_id


def _template_bindings(repo: Path, authority: DefectAuthority | None = None) -> dict[str, Any]:
    if authority is not None:
        return dict(authority.bindings)
    bindings = _bindings(repo)
    bindings["template_digests"] = {
        "defect.md": digest_ref(_TEMPLATE.read_bytes())
    }
    return bindings


def _metadata(
    *,
    defect_id: str,
    repository_key: str,
    github_repository_id: int | None,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    value = {
        "schema": "doc-warden/artifact/v2",
        "id": defect_id,
        "type": "defect",
        "version": 1,
        "repository_key": repository_key,
        "github_repository_id": github_repository_id,
        "authority": "semantic",
        "mutability": "append_only",
        "lifecycle": "draft",
        "supersedes": None,
        "relations": [],
        "provenance": [provenance],
        "approval": None,
    }
    require_valid("artifact", value)
    return value


def _artifact_content(
    metadata: dict[str, Any],
    record: dict[str, Any],
) -> bytes:
    return _artifact_bytes(
        metadata,
        canonical_json(record).decode("utf-8"),
    )


def _roadmap_update(
    loaded: ValidatedDefectArtifact,
    record: dict[str, Any],
    *,
    source_revision: str,
    prd_seed_id: str | None = None,
) -> bytes:
    items = parse_roadmap(loaded.path.parents[1] / "ROADMAP.md")
    verification = record["resolution"]["verification"]
    completion = [
        *verification["automated"],
        *verification["human"],
    ]
    update_defect_roadmap_item(
        items,
        defect_id=record["id"],
        record_version=record["record_version"],
        lifecycle=record["lifecycle"],
        next_action=record["current_focus"]["next_action"],
        source_revision=source_revision,
        observed_at=record["updated_at"],
        completion_evidence=completion if record["lifecycle"] == "resolved" else None,
        prd_seed_id=prd_seed_id,
    )
    return render_roadmap(items)


def _update_preview(
    loaded: ValidatedDefectArtifact,
    record: dict[str, Any],
    *,
    operation_id: str,
    defect_event_id: str,
    consequential: bool,
    transaction_transition: str = "draft_update",
    prd_seed_id: str | None = None,
    recovery_preimages: dict[str, str | None] | None = None,
    authority: DefectAuthority | None = None,
) -> DefectPreview:
    repo = loaded.path.parents[2]
    source_revision = _head(repo)
    defect_content = _artifact_content(loaded.metadata, record)
    bindings = _template_bindings(repo, authority)
    bindings["defect_authority"] = {
        "defect_id": record["id"],
        "record_version": record["record_version"],
        "event_id": record["history_head"]["event_id"],
        "defect_digest": digest_ref(defect_content),
    }
    transaction = preview_transaction(
        MutationRequest(
            repo=repo,
            repository_key=record["repository_key"],
            github_repository_id=loaded.metadata["github_repository_id"],
            transition=transaction_transition,
            actions=(
                MutationAction(
                    str(loaded.path.relative_to(repo)),
                    defect_content,
                    "replace",
                ),
                MutationAction(
                    ".planning/ROADMAP.md",
                    _roadmap_update(
                        loaded,
                        record,
                        source_revision=source_revision,
                        prd_seed_id=prd_seed_id,
                    ),
                    "replace",
                ),
            ),
            bindings=bindings,
            operation_id=operation_id,
            consequential=consequential,
            require_write_enabled=True,
            observed_inputs=authority.observed_inputs if authority else (),
        ),
        recovery_preimages=recovery_preimages,
    )
    return DefectPreview(
        transaction=transaction,
        defect_id=record["id"],
        defect_path=str(loaded.path.relative_to(repo)),
        repository_key=record["repository_key"],
        defect_event_id=defect_event_id,
    )


def _operation_event_path(repo: Path, operation_id: str) -> Path:
    event_id = str(uuid.uuid5(uuid.UUID(operation_id), "terminal-event"))
    return repo / "_ops/doc-warden/state/v2/events" / f"{event_id}.json"


def _operation_event_for_recovery(
    repo: Path,
    operation_id: str,
) -> dict[str, Any]:
    event_id = str(uuid.uuid5(uuid.UUID(operation_id), "terminal-event"))
    path = _operation_event_path(repo, operation_id)
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("operation event missing")
        raw = path.read_bytes()
        event = parse_json_object(raw)
        if raw != canonical_json(event):
            raise ValueError("operation event is not canonical")
        validate_egress("event", event)
    except (OSError, ValueError) as exc:
        raise ValueError("defect_operation_replay_mismatch") from exc
    if (
        event["event_id"] != event_id
        or event["operation_id"] != operation_id
        or event["outcome"] != "applied"
    ):
        raise ValueError("defect_operation_replay_mismatch")
    return event


def _operation_event_matches(
    event: dict[str, Any],
    preview: TransactionPreview,
) -> bool:
    return event == {
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


def _prior_roadmap_digest(
    repo: Path,
    *,
    defect_path: str,
    defect_digest: str,
) -> str:
    matches: list[str] = []
    receipt_root = repo / "_ops/doc-warden/state/v2/receipts"
    for path in sorted(receipt_root.glob("*.json")) if receipt_root.exists() else []:
        if path.is_symlink() or not path.is_file():
            continue
        try:
            raw = path.read_bytes()
            receipt = parse_json_object(raw)
        except (OSError, ValueError):
            continue
        postimages = receipt.get("postimages")
        if (
            not isinstance(postimages, dict)
            or postimages.get(defect_path) != defect_digest
        ):
            continue
        try:
            if raw != canonical_json(receipt):
                raise ValueError("receipt is not canonical")
            validate_egress("receipt", receipt)
            roadmap_digest = postimages[".planning/ROADMAP.md"]
        except (KeyError, ValueError) as exc:
            raise ValueError("defect_operation_replay_mismatch") from exc
        matches.append(roadmap_digest)
    if len(matches) != 1:
        raise ValueError("defect_operation_replay_mismatch")
    return matches[0]


def _recover_creation_receipt(
    loaded: ValidatedDefectArtifact,
    *,
    operation_id: str,
    expected_events: tuple[dict[str, Any], ...],
    operation_event: dict[str, Any],
    authority: DefectAuthority | None = None,
) -> dict[str, Any]:
    if (
        len(expected_events) != 1
        or expected_events[0]["kind"] != "created"
        or len(loaded.record["events"]) != 1
    ):
        raise ValueError("defect_operation_replay_mismatch")
    repo = loaded.path.parents[2]
    defect_path = str(loaded.path.relative_to(repo))
    roadmap_path = repo / ".planning/ROADMAP.md"
    try:
        items = parse_roadmap(roadmap_path)
        roadmap_content = render_roadmap(items)
        if roadmap_path.read_bytes() != roadmap_content:
            raise ValueError("roadmap is not canonical")
    except (OSError, ValueError) as exc:
        raise ValueError("defect_operation_replay_mismatch") from exc
    matching_rows = [
        item
        for item in items
        if item.get("id") == f"ROAD-{loaded.record['id']}"
        or loaded.record["id"] in item.get("active_versions", {})
    ]
    if len(matching_rows) != 1:
        raise ValueError("defect_operation_replay_mismatch")
    prior_items = [item for item in items if item is not matching_rows[0]]
    roadmap_candidates: tuple[tuple[str | None, str], ...] = (
        (None, "create"),
        (digest_ref(render_roadmap(prior_items)), "replace"),
    )
    previews: list[TransactionPreview] = []
    for roadmap_preimage, roadmap_kind in roadmap_candidates:
        try:
            preview = preview_transaction(
                MutationRequest(
                    repo=repo,
                    repository_key=loaded.record["repository_key"],
                    github_repository_id=loaded.metadata["github_repository_id"],
                    transition="creation_snapshot",
                    actions=(
                        MutationAction(
                            defect_path,
                            _artifact_content(loaded.metadata, loaded.record),
                            "create",
                        ),
                        MutationAction(
                            ".planning/ROADMAP.md",
                            roadmap_content,
                            roadmap_kind,
                        ),
                    ),
                    bindings=_template_bindings(repo, authority),
                    operation_id=operation_id,
                    consequential=False,
                    require_write_enabled=True,
                    observed_inputs=authority.observed_inputs if authority else (),
                ),
                recovery_preimages={
                    defect_path: None,
                    ".planning/ROADMAP.md": roadmap_preimage,
                },
            )
        except ValueError:
            continue
        if _operation_event_matches(operation_event, preview):
            previews.append(preview)
    if len(previews) != 1:
        raise ValueError("defect_operation_replay_mismatch")
    try:
        return apply_transaction(previews[0], None)
    except ValueError as exc:
        raise ValueError("defect_operation_replay_mismatch") from exc


def _recover_update_receipt(
    loaded: ValidatedDefectArtifact,
    *,
    operation_id: str,
    expected_events: tuple[dict[str, Any], ...],
    operation_event: dict[str, Any],
    authority: DefectAuthority | None = None,
) -> dict[str, Any]:
    expected_ids = [event["event_id"] for event in expected_events]
    events = loaded.record["events"]
    if (
        not expected_ids
        or len(events) <= len(expected_ids)
        or [event["event_id"] for event in events[-len(expected_ids) :]]
        != expected_ids
    ):
        raise ValueError("defect_operation_replay_mismatch")
    prior_record = dict(loaded.record)
    prior_record["events"] = events[: -len(expected_ids)]
    try:
        prior_record = regenerate_defect_current_view(prior_record)
        validate_defect_record(prior_record)
    except ValueError as exc:
        raise ValueError("defect_operation_replay_mismatch") from exc
    repo = loaded.path.parents[2]
    defect_path = str(loaded.path.relative_to(repo))
    prior_defect_digest = digest_ref(
        _artifact_content(loaded.metadata, prior_record)
    )
    prior_roadmap_digest = _prior_roadmap_digest(
        repo,
        defect_path=defect_path,
        defect_digest=prior_defect_digest,
    )
    transaction_transition = "draft_update"
    consequential = False
    prd_seed_id = None
    for event in expected_events:
        if (
            event["kind"] == "lifecycle_transition"
            and event["payload"].get("to") == "superseded"
        ):
            transaction_transition = "supersession"
        if (
            event["kind"] == "lifecycle_transition"
            and event["payload"].get("to") in _CONSEQUENTIAL_TARGETS
        ):
            consequential = True
        if event["kind"] == "promoted":
            prd_seed_id = event["payload"]["promotion"]["prd_seed"]["id"]
    try:
        recovered = _update_preview(
            loaded,
            loaded.record,
            operation_id=operation_id,
            defect_event_id=expected_ids[0],
            consequential=consequential,
            transaction_transition=transaction_transition,
            prd_seed_id=prd_seed_id,
            recovery_preimages={
                defect_path: prior_defect_digest,
                ".planning/ROADMAP.md": prior_roadmap_digest,
            },
            authority=authority,
        )
    except ValueError as exc:
        raise ValueError("defect_operation_replay_mismatch") from exc
    if not _operation_event_matches(operation_event, recovered.transaction):
        raise ValueError("defect_operation_replay_mismatch")
    confirmation = (
        confirmation_for(recovered.transaction)
        if recovered.transaction.consequential
        else None
    )
    try:
        return apply_transaction(recovered.transaction, confirmation)
    except ValueError as exc:
        raise ValueError("defect_operation_replay_mismatch") from exc


def _recover_missing_receipt(
    loaded: ValidatedDefectArtifact,
    *,
    operation_id: str,
    expected_events: tuple[dict[str, Any], ...],
    authority: DefectAuthority | None = None,
) -> dict[str, Any]:
    operation_event = _operation_event_for_recovery(
        loaded.path.parents[2],
        operation_id,
    )
    if expected_events[0]["kind"] == "created":
        return _recover_creation_receipt(
            loaded,
            operation_id=operation_id,
            expected_events=expected_events,
            operation_event=operation_event,
            authority=authority,
        )
    return _recover_update_receipt(
        loaded,
        operation_id=operation_id,
        expected_events=expected_events,
        operation_event=operation_event,
        authority=authority,
    )


def _existing_receipt(
    loaded: ValidatedDefectArtifact,
    *,
    operation_id: str,
    event_id: str,
    kind: str,
    timestamp: str,
    source: str,
    author_class: str,
    payload: dict[str, Any],
    authority: DefectAuthority | None = None,
) -> dict[str, Any] | None:
    return _existing_receipt_for_events(
        loaded,
        operation_id=operation_id,
        expected_events=(
            {
                "event_id": event_id,
                "kind": kind,
                "timestamp": timestamp,
                "source": source,
                "author_class": author_class,
                "payload": payload,
            },
        ),
        authority=authority,
    )


def _existing_receipt_for_events(
    loaded: ValidatedDefectArtifact,
    *,
    operation_id: str,
    expected_events: tuple[dict[str, Any], ...],
    authority: DefectAuthority | None = None,
) -> dict[str, Any] | None:
    expected_ids = [event["event_id"] for event in expected_events]
    operation_event_ids = {
        _event_id(operation_id, loaded.record["id"], label)
        for label in _DEFECT_EVENT_LABELS
    }
    if any(
        event["event_id"] in operation_event_ids
        and event["event_id"] not in expected_ids
        for event in loaded.record["events"]
    ):
        raise ValueError("defect_operation_replay_mismatch")
    matches = [
        event
        for event in loaded.record["events"]
        if event["event_id"] in expected_ids
    ]
    receipt_path = (
        loaded.path.parents[2]
        / "_ops/doc-warden/state/v2/receipts"
        / f"{operation_id}.json"
    )
    if not matches:
        operation_event_path = _operation_event_path(
            loaded.path.parents[2],
            operation_id,
        )
        if (
            receipt_path.exists()
            or receipt_path.is_symlink()
            or operation_event_path.exists()
            or operation_event_path.is_symlink()
        ):
            raise ValueError("defect_operation_replay_mismatch")
        return None
    if (
        len(matches) != len(expected_events)
        or [event["event_id"] for event in matches] != expected_ids
        or any(
            any(event[field] != expected[field] for field in expected)
            for event, expected in zip(matches, expected_events, strict=True)
        )
    ):
        raise ValueError("defect_operation_replay_mismatch")
    if not receipt_path.is_file():
        if receipt_path.exists() or receipt_path.is_symlink():
            raise ValueError("defect_operation_replay_mismatch")
        return _recover_missing_receipt(
            loaded,
            operation_id=operation_id,
            expected_events=expected_events,
            authority=authority,
        )
    receipt = parse_json_object(receipt_path.read_bytes())
    if receipt_path.read_bytes() != canonical_json(receipt):
        raise ValueError("defect_operation_replay_mismatch")
    validate_egress("receipt", receipt)
    if receipt["operation_id"] != operation_id:
        raise ValueError("defect_operation_replay_mismatch")
    validate_replay_authority(receipt, loaded.path.parents[2], authority)
    return receipt


def _symptom_values(
    record: dict[str, Any],
    symptoms: dict[str, Any] | None,
) -> dict[str, Any]:
    values = {field: record[field] for field in _SYMPTOM_FIELDS}
    if symptoms is not None:
        if not isinstance(symptoms, dict) or set(symptoms) - set(_SYMPTOM_FIELDS):
            raise ValueError("defect_symptoms_contract_invalid")
        values.update(symptoms)
    for field in ("preconditions", "reproduction", "immutable_symptoms"):
        value = values[field]
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise ValueError("defect_symptoms_contract_invalid")
    if any(
        not isinstance(values[field], str)
        for field in set(_SYMPTOM_FIELDS)
        - {"preconditions", "reproduction", "immutable_symptoms", "known_good_revision"}
    ):
        raise ValueError("defect_symptoms_contract_invalid")
    return values


def _incomplete_symptoms(symptoms: dict[str, Any]) -> tuple[str, ...]:
    incomplete = []
    for field in _SYMPTOM_FIELDS:
        value = symptoms[field]
        if field == "known_good_revision":
            complete = _complete_defect_known_good_revision(value)
        elif isinstance(value, str):
            complete = bool(value.strip())
        else:
            complete = _has_meaningful_string_entries(value)
        if not complete:
            incomplete.append(field)
    return tuple(incomplete)


def _transition_replay(
    loaded: ValidatedDefectArtifact,
    *,
    operation_id: str,
    target: str,
    timestamp: str,
    source: str,
    author_class: str,
    symptoms: dict[str, Any] | None,
    current_focus: dict[str, Any] | None,
    resolution: dict[str, Any] | None,
    relation: dict[str, Any] | None,
    authority: DefectAuthority | None = None,
) -> dict[str, Any] | None:
    record = loaded.record
    event_ids = {
        "symptoms-frozen": _event_id(operation_id, record["id"], "symptoms-frozen"),
        "transition": _event_id(operation_id, record["id"], f"transition-{target}"),
        "focus": _event_id(operation_id, record["id"], "focus"),
        "resolution": _event_id(operation_id, record["id"], "resolution"),
    }
    prior = {
        label: next(
            (
                event
                for event in record["events"]
                if event["event_id"] == event_id
            ),
            None,
        )
        for label, event_id in event_ids.items()
    }
    present = {label for label, event in prior.items() if event is not None}
    expected: list[dict[str, Any]] = []
    if "symptoms-frozen" in present:
        if target != "triaged":
            raise ValueError("defect_operation_replay_mismatch")
        symptom_values = _symptom_values(record, symptoms)
        expected.append(
            {
                "event_id": event_ids["symptoms-frozen"],
                "kind": "symptoms_frozen",
                "timestamp": timestamp,
                "source": source,
                "author_class": author_class,
                "payload": {
                    "symptoms": symptom_values,
                    "symptoms_digest": defect_symptoms_digest(
                        {**record, **symptom_values}
                    ),
                    "lifecycle": "triaged",
                },
            }
        )
    elif "transition" in present:
        transition = prior["transition"]
        assert transition is not None
        payload: dict[str, Any] = {
            "from": transition["payload"]["from"],
            "to": target,
        }
        if current_focus is not None:
            payload["current_focus"] = _focus(current_focus)
        if resolution is not None:
            payload["resolution"] = _resolution(resolution)
        bound_relation = _relation_for_transition(record, target, relation)
        if bound_relation is not None:
            payload["relation"] = bound_relation
        expected.append(
            {
                "event_id": event_ids["transition"],
                "kind": "lifecycle_transition",
                "timestamp": timestamp,
                "source": source,
                "author_class": author_class,
                "payload": payload,
            }
        )
    else:
        if current_focus is not None:
            expected.append(
                {
                    "event_id": event_ids["focus"],
                    "kind": "focus_updated",
                    "timestamp": timestamp,
                    "source": source,
                    "author_class": author_class,
                    "payload": {"current_focus": _focus(current_focus)},
                }
            )
        if resolution is not None:
            expected.append(
                {
                    "event_id": event_ids["resolution"],
                    "kind": "resolution_updated",
                    "timestamp": timestamp,
                    "source": source,
                    "author_class": author_class,
                    "payload": {"resolution": _resolution(resolution)},
                }
            )
    if present and present != {
        label
        for label, event_id in event_ids.items()
        if any(item["event_id"] == event_id for item in expected)
    }:
        raise ValueError("defect_operation_replay_mismatch")
    return _existing_receipt_for_events(
        loaded,
        operation_id=operation_id,
        expected_events=tuple(expected),
        authority=authority,
    )


def create_defect(
    inputs: dict[str, Any],
    *,
    repo: Path,
    operation_id: str | None = None,
    binding_root: Path | None = None,
) -> DefectPreview | dict[str, Any]:
    """Preview one defect record and its canonical backlog row.

    ``binding_root`` explicitly selects a previously authorized central source.
    Supply it on subsequent lifecycle and replay calls as well. Omitting it
    preserves repository-local behavior; selection never grants write authority.
    """

    if not isinstance(inputs, dict):
        raise ValueError("defect_input_must_be_object")
    root = repo.resolve(strict=True)
    authority = prepare_authority(repo, binding_root)
    config = read_repository_config(root)
    if config is None:
        raise ValueError("v2_repository_profile_required")
    operation = _operation(operation_id)
    defect_uuid = str(uuid.uuid5(uuid.UUID(operation), "defect"))
    defect_id = f"DEF-{config['repository_key']}-{defect_uuid}"
    timestamp = str(inputs.get("created_at") or _head_time(root))
    provenance = _mapping(
        inputs.get("report_provenance"),
        "report_provenance",
        {"source": "", "reported_at": "", "author_class": ""},
    )
    if set(provenance) != {"source", "reported_at", "author_class"}:
        raise ValueError("report_provenance_contract_invalid")
    focus = _focus(inputs.get("current_focus"))
    resolution = _resolution(inputs.get("resolution"))
    hypotheses = inputs.get("hypotheses", [])
    if not isinstance(hypotheses, list) or any(
        not isinstance(item, dict) for item in hypotheses
    ):
        raise ValueError("hypotheses_must_be_object_array")
    anchors = inputs.get("anchors", [])
    relations = inputs.get("relations", [])
    if not isinstance(anchors, list) or any(not isinstance(item, dict) for item in anchors):
        raise ValueError("anchors_must_be_object_array")
    if not isinstance(relations, list) or any(
        not isinstance(item, dict) for item in relations
    ):
        raise ValueError("relations_must_be_object_array")
    fix_refs = _mapping(
        inputs.get("fix_refs"),
        "fix_refs",
        {"commit": None, "pull_request": None, "plan": None},
    )
    if set(fix_refs) != {"commit", "pull_request", "plan"}:
        raise ValueError("fix_refs_contract_invalid")
    record: dict[str, Any] = {
        "schema": "doc-warden/defect/v2",
        "id": defect_id,
        "kind": "defect",
        "repository_key": config["repository_key"],
        "record_version": 1,
        "title": str(inputs.get("title", "")),
        "lifecycle": "reported",
        "severity": inputs.get("severity", "medium"),
        "priority": inputs.get("priority", "P2"),
        "owner": str(inputs.get("owner", "")),
        "created_at": timestamp,
        "updated_at": timestamp,
        "report_provenance": provenance,
        "environment": str(inputs.get("environment", "")),
        "preconditions": _strings(inputs.get("preconditions"), "preconditions"),
        "test_data": str(inputs.get("test_data", "")),
        "reproduction": _strings(inputs.get("reproduction"), "reproduction"),
        "expected": str(inputs.get("expected", "")),
        "actual": str(inputs.get("actual", "")),
        "error_reference": str(inputs.get("error_reference", "")),
        "frequency": str(inputs.get("frequency", "")),
        "known_good_revision": inputs.get("known_good_revision", ""),
        "known_bad_revision": str(inputs.get("known_bad_revision", "")),
        "impact": str(inputs.get("impact", "")),
        "immutable_symptoms": _strings(
            inputs.get("immutable_symptoms"), "immutable_symptoms"
        ),
        "symptoms_digest": None,
        "symptoms_frozen_event_id": None,
        "evidence": [],
        "current_focus": focus,
        "next_action": focus["next_action"],
        "hypotheses": [dict(item) for item in hypotheses],
        "eliminated_hypotheses": [],
        "anchors": [dict(item) for item in anchors],
        "dependencies": _strings(inputs.get("dependencies"), "dependencies"),
        "workaround": inputs.get("workaround"),
        "resolution": resolution,
        "fix_refs": fix_refs,
        "acceptance": _strings(inputs.get("acceptance"), "acceptance"),
        "verification_plan": _verification_plan(inputs.get("verification_plan")),
        "related_artifacts": _strings(
            inputs.get("related_artifacts"), "related_artifacts"
        ),
        "relations": [dict(item) for item in relations],
        "affected_users": _strings(inputs.get("affected_users"), "affected_users"),
        "requirement_candidates": _strings(
            inputs.get("requirement_candidates"), "requirement_candidates"
        ),
        "risks": _strings(inputs.get("risks"), "risks"),
        "open_decisions": _strings(inputs.get("open_decisions"), "open_decisions"),
        "problem": str(
            inputs.get("problem")
            or inputs.get("impact")
            or inputs.get("title", "")
        ),
        "scope": _scope(inputs.get("scope")),
        "exemption": _exemption(inputs.get("exemption")),
        "fix_paused": False,
        "promotion": None,
        "events": [],
        "history_head": None,
    }
    creation_payload = {
        "lifecycle": "reported",
        "symptoms": {field: record[field] for field in _SYMPTOM_FIELDS},
        "symptoms_digest": None,
        "symptoms_frozen_event_id": None,
        "current_focus": focus,
        "hypotheses": record["hypotheses"],
        "resolution": resolution,
        "relations": record["relations"],
        "related_artifacts": record["related_artifacts"],
        "scope": record["scope"],
        "exemption": record["exemption"],
        "fix_paused": False,
        "promotion": None,
    }
    record, created_event_id = _append_event(
        record,
        operation_id=operation,
        label="created",
        kind="created",
        timestamp=timestamp,
        source=str(provenance.get("source") or "doc-warden"),
        author_class=str(provenance.get("author_class") or "agent"),
        payload=creation_payload,
    )
    metadata = _metadata(
        defect_id=defect_id,
        repository_key=config["repository_key"],
        github_repository_id=config["github_repository_id"],
        provenance=provenance,
    )
    defect_path = f".planning/artifacts/{defect_id}-v1.md"
    artifact_path = root / defect_path
    if artifact_path.exists() or artifact_path.is_symlink():
        if artifact_path.is_symlink() or not artifact_path.is_file():
            raise ValueError("defect_operation_replay_mismatch")
        loaded = load_defect_artifact(root, defect_id)
        actual_created = dict(loaded.record)
        actual_created["events"] = [loaded.record["events"][0]]
        try:
            actual_created = regenerate_defect_current_view(actual_created)
            validate_defect_record(actual_created)
        except ValueError as exc:
            raise ValueError("defect_operation_replay_mismatch") from exc
        if loaded.metadata != metadata or actual_created != record:
            raise ValueError("defect_operation_replay_mismatch")
        created_event = record["events"][0]
        replay = _existing_receipt(
            loaded,
            operation_id=operation,
            event_id=created_event_id,
            kind="created",
            timestamp=timestamp,
            source=str(provenance.get("source") or "doc-warden"),
            author_class=str(provenance.get("author_class") or "agent"),
            payload=created_event["payload"],
            authority=authority,
        )
        if (
            replay is None
            or replay["transition"] != "creation_snapshot"
            or replay["postimages"].get(defect_path)
            != digest_ref(_artifact_content(metadata, record))
        ):
            raise ValueError("defect_operation_replay_mismatch")
        return replay
    receipt_path = (
        root
        / "_ops/doc-warden/state/v2/receipts"
        / f"{operation}.json"
    )
    operation_event_path = _operation_event_path(root, operation)
    if (
        receipt_path.exists()
        or receipt_path.is_symlink()
        or operation_event_path.exists()
        or operation_event_path.is_symlink()
    ):
        raise ValueError("defect_operation_replay_mismatch")
    roadmap_path = root / ".planning/ROADMAP.md"
    items = parse_roadmap(roadmap_path)
    if any(
        item.get("id") == f"ROAD-{defect_id}"
        or defect_id in item.get("active_versions", {})
        for item in items
    ):
        raise ValueError("defect_roadmap_item_exists")
    item = new_defect_roadmap_item(
        repository_key=config["repository_key"],
        defect_id=defect_id,
        outcome=record["impact"] or record["title"],
        priority=record["priority"],
        source_revision=_head(root),
        observed_at=timestamp,
    )
    item["sequence"] = max(
        (existing["sequence"] for existing in items),
        default=0,
    ) + 1
    require_valid("roadmap", item)
    items.append(item)
    transaction = preview_transaction(
        MutationRequest(
            repo=root,
            repository_key=config["repository_key"],
            github_repository_id=config["github_repository_id"],
            transition="creation_snapshot",
            actions=(
                MutationAction(
                    defect_path,
                    _artifact_content(metadata, record),
                    "create",
                ),
                MutationAction(
                    ".planning/ROADMAP.md",
                    render_roadmap(items),
                ),
            ),
            bindings=_template_bindings(root, authority),
            operation_id=operation,
            consequential=False,
            require_write_enabled=True,
            observed_inputs=authority.observed_inputs if authority else (),
        )
    )
    return DefectPreview(
        transaction=transaction,
        defect_id=defect_id,
        defect_path=defect_path,
        repository_key=config["repository_key"],
        defect_event_id=created_event_id,
    )


def read_defect(repo: Path, defect_id: str) -> ValidatedDefectArtifact:
    """Read and fully validate one defect current view."""

    return load_defect_artifact(repo, defect_id)


def append_evidence(
    defect_id: str,
    evidence: dict[str, Any],
    *,
    repo: Path,
    operation_id: str | None = None,
    binding_root: Path | None = None,
) -> dict[str, Any]:
    """Append one evidence fact through the shared transaction gateway."""

    if not isinstance(evidence, dict):
        raise ValueError("defect_evidence_must_be_object")
    required = {
        "timestamp",
        "source",
        "author_class",
        "checked",
        "found",
        "implication",
    }
    if set(evidence) != required or any(
        not isinstance(evidence[field], str) or not evidence[field]
        for field in required
    ):
        raise ValueError("defect_evidence_contract_invalid")
    authority = prepare_authority(repo, binding_root)
    loaded = read_defect(repo, defect_id)
    operation = _operation(operation_id)
    payload = {
        field: evidence[field]
        for field in ("checked", "found", "implication")
    }
    event_id = _event_id(operation, defect_id, "evidence")
    replay = _existing_receipt(
        loaded,
        operation_id=operation,
        event_id=event_id,
        kind="evidence_appended",
        timestamp=evidence["timestamp"],
        source=evidence["source"],
        author_class=evidence["author_class"],
        payload=payload,
        authority=authority,
    )
    if replay is not None:
        return replay
    if loaded.record["lifecycle"] in _DEFECT_TERMINAL_LIFECYCLES:
        raise ValueError("defect_terminal")
    record, event_id = _append_event(
        loaded.record,
        operation_id=operation,
        label="evidence",
        kind="evidence_appended",
        timestamp=evidence["timestamp"],
        source=evidence["source"],
        author_class=evidence["author_class"],
        payload=payload,
    )
    preview = _update_preview(
        loaded,
        record,
        operation_id=operation,
        defect_event_id=event_id,
        consequential=False,
        authority=authority,
    )
    return apply_transaction(preview.transaction, None)


def reevaluate_exemption(
    defect_id: str,
    assessment: dict[str, Any],
    *,
    repo: Path,
    operation_id: str | None = None,
    binding_root: Path | None = None,
) -> dict[str, Any]:
    """Record one complete, evidence-backed defect exemption reevaluation."""

    candidate = _exemption_assessment(assessment)
    authority = prepare_authority(repo, binding_root)
    loaded = read_defect(repo, defect_id)
    operation = _operation(operation_id)
    exemption = {
        "decision": "exempt",
        "conditions": candidate["conditions"],
    }
    payload = {"exemption": exemption}
    event_id = _event_id(operation, defect_id, "exemption-reevaluated")
    replay = _existing_receipt(
        loaded,
        operation_id=operation,
        event_id=event_id,
        kind="exemption_reevaluated",
        timestamp=candidate["timestamp"],
        source=candidate["source"],
        author_class=candidate["author_class"],
        payload=payload,
        authority=authority,
    )
    if replay is not None:
        return replay
    if loaded.record["lifecycle"] in _DEFECT_TERMINAL_LIFECYCLES:
        raise ValueError("defect_terminal")
    if (
        loaded.record["promotion"] is not None
        or loaded.record["fix_paused"]
        or loaded.record["exemption"]["decision"] != "exempt"
    ):
        raise ValueError("defect_exemption_reevaluation_blocked:promotion_required")
    if all(loaded.record["exemption"]["conditions"]):
        raise ValueError("defect_exemption_already_valid")
    if not all(candidate["conditions"]):
        raise ValueError("defect_exemption_promotion_required")
    missing, invalid = defect_ready_issues(loaded.record)
    blockers = (
        *(field for field in missing if field != "exemption.conditions"),
        *invalid,
    )
    if blockers:
        raise ValueError(
            "defect_exemption_reevaluation_blocked:" + ",".join(blockers)
        )
    record, event_id = _append_event(
        loaded.record,
        operation_id=operation,
        label="exemption-reevaluated",
        kind="exemption_reevaluated",
        timestamp=candidate["timestamp"],
        source=candidate["source"],
        author_class=candidate["author_class"],
        payload=payload,
    )
    preview = _update_preview(
        loaded,
        record,
        operation_id=operation,
        defect_event_id=event_id,
        consequential=False,
        authority=authority,
    )
    return apply_transaction(preview.transaction, None)


def eliminate_hypothesis(
    defect_id: str,
    result: dict[str, Any],
    *,
    repo: Path,
    operation_id: str | None = None,
    binding_root: Path | None = None,
) -> dict[str, Any]:
    """Append one eliminated hypothesis and update its derived status."""

    if not isinstance(result, dict):
        raise ValueError("defect_elimination_must_be_object")
    required = {
        "hypothesis_id",
        "timestamp",
        "source",
        "author_class",
        "evidence",
    }
    if set(result) != required or any(
        not isinstance(result[field], str) or not result[field]
        for field in required
    ):
        raise ValueError("defect_elimination_contract_invalid")
    authority = prepare_authority(repo, binding_root)
    loaded = read_defect(repo, defect_id)
    operation = _operation(operation_id)
    payload = {
        "hypothesis_id": result["hypothesis_id"],
        "evidence": result["evidence"],
    }
    event_id = _event_id(operation, defect_id, "elimination")
    replay = _existing_receipt(
        loaded,
        operation_id=operation,
        event_id=event_id,
        kind="hypothesis_eliminated",
        timestamp=result["timestamp"],
        source=result["source"],
        author_class=result["author_class"],
        payload=payload,
        authority=authority,
    )
    if replay is not None:
        return replay
    if loaded.record["lifecycle"] in _DEFECT_TERMINAL_LIFECYCLES:
        raise ValueError("defect_terminal")
    matches = [
        hypothesis
        for hypothesis in loaded.record["hypotheses"]
        if hypothesis["id"] == result["hypothesis_id"]
    ]
    if len(matches) != 1 or matches[0]["status"] != "active":
        raise ValueError("defect_hypothesis_not_active")
    record, event_id = _append_event(
        loaded.record,
        operation_id=operation,
        label="elimination",
        kind="hypothesis_eliminated",
        timestamp=result["timestamp"],
        source=result["source"],
        author_class=result["author_class"],
        payload=payload,
    )
    preview = _update_preview(
        loaded,
        record,
        operation_id=operation,
        defect_event_id=event_id,
        consequential=False,
        authority=authority,
    )
    return apply_transaction(preview.transaction, None)


def _relation_for_transition(
    record: dict[str, Any],
    target: str,
    relation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    required_relation = _DEFECT_RELATION_FOR_TARGET.get(target)
    if required_relation is None:
        if relation is not None:
            raise ValueError("defect_relation_unexpected")
        return None
    if not isinstance(relation, dict):
        raise ValueError(f"defect_relation_required:{required_relation}")
    require_valid("relation", relation)
    if (
        relation["source_id"] != record["id"]
        or relation["relation"] != required_relation
    ):
        raise ValueError(f"defect_relation_required:{required_relation}")
    return dict(relation)


def transition_defect(
    defect_id: str,
    target: str,
    *,
    repo: Path,
    timestamp: str,
    source: str,
    author_class: str,
    operation_id: str | None = None,
    symptoms: dict[str, Any] | None = None,
    current_focus: dict[str, Any] | None = None,
    resolution: dict[str, Any] | None = None,
    relation: dict[str, Any] | None = None,
    binding_root: Path | None = None,
) -> DefectPreview | dict[str, Any]:
    """Preview a lifecycle or mutable-current-view defect event."""

    if target not in _LIFECYCLE:
        raise ValueError("defect_lifecycle_invalid")
    authority = prepare_authority(repo, binding_root)
    loaded = read_defect(repo, defect_id)
    record = loaded.record
    current = record["lifecycle"]
    operation = _operation(operation_id)
    replay = _transition_replay(
        loaded,
        operation_id=operation,
        target=target,
        timestamp=timestamp,
        source=source,
        author_class=author_class,
        symptoms=symptoms,
        current_focus=current_focus,
        resolution=resolution,
        relation=relation,
        authority=authority,
    )
    if replay is not None:
        return replay
    if target == "ready" and current not in {"investigating", "ready"}:
        missing, invalid = defect_ready_issues(record)
        raise ValueError(
            "defect_not_ready:" + ",".join((*missing, *invalid))
        )
    if target != current and target not in _DEFECT_TRANSITIONS[current]:
        raise ValueError(f"defect_transition_invalid:{current}:{target}")
    if symptoms is not None and target != "triaged":
        raise ValueError("defect_symptoms_frozen")
    if current != "reported" and symptoms is not None:
        raise ValueError("defect_symptoms_frozen")
    event_ids: list[str] = []
    updated = record
    if target == "triaged" and current == "reported":
        symptom_values = _symptom_values(record, symptoms)
        incomplete = _incomplete_symptoms(symptom_values)
        if incomplete:
            raise ValueError(
                "defect_symptoms_incomplete:" + ",".join(incomplete)
            )
        candidate = {**record, **symptom_values}
        payload = {
            "symptoms": symptom_values,
            "symptoms_digest": defect_symptoms_digest(candidate),
            "lifecycle": "triaged",
        }
        updated, event_id = _append_event(
            updated,
            operation_id=operation,
            label="symptoms-frozen",
            kind="symptoms_frozen",
            timestamp=timestamp,
            source=source,
            author_class=author_class,
            payload=payload,
        )
        event_ids.append(event_id)
    elif target != current:
        bound_relation = _relation_for_transition(record, target, relation)
        payload: dict[str, Any] = {"from": current, "to": target}
        if current_focus is not None:
            payload["current_focus"] = _focus(current_focus)
        if resolution is not None:
            payload["resolution"] = _resolution(resolution)
        if bound_relation is not None:
            payload["relation"] = bound_relation
        if target == "resolved":
            final_resolution = payload.get("resolution", record["resolution"])
            missing_verification = [
                field
                for field in ("automated", "human")
                if not _has_meaningful_string_entries(
                    final_resolution["verification"][field]
                )
            ]
            if missing_verification:
                raise ValueError(
                    "resolution_verification_incomplete:"
                    + ",".join(missing_verification)
                )
            missing_resolution = [
                field
                for field in ("root_cause", "fix")
                if not final_resolution[field]
            ]
            if missing_resolution:
                raise ValueError(
                    "resolution_incomplete:" + ",".join(missing_resolution)
                )
        updated, event_id = _append_event(
            updated,
            operation_id=operation,
            label=f"transition-{target}",
            kind="lifecycle_transition",
            timestamp=timestamp,
            source=source,
            author_class=author_class,
            payload=payload,
        )
        event_ids.append(event_id)
    else:
        if current in _DEFECT_TERMINAL_LIFECYCLES:
            raise ValueError("defect_terminal")
        if relation is not None or symptoms is not None:
            raise ValueError("defect_transition_update_invalid")
        if current_focus is None and resolution is None:
            raise ValueError("defect_transition_no_change")
        if current_focus is not None:
            updated, event_id = _append_event(
                updated,
                operation_id=operation,
                label="focus",
                kind="focus_updated",
                timestamp=timestamp,
                source=source,
                author_class=author_class,
                payload={"current_focus": _focus(current_focus)},
            )
            event_ids.append(event_id)
        if resolution is not None:
            updated, event_id = _append_event(
                updated,
                operation_id=operation,
                label="resolution",
                kind="resolution_updated",
                timestamp=timestamp,
                source=source,
                author_class=author_class,
                payload={"resolution": _resolution(resolution)},
            )
            event_ids.append(event_id)
    if target == "ready":
        missing, invalid = defect_ready_issues(updated)
        if missing or invalid:
            raise ValueError(
                "defect_not_ready:" + ",".join((*missing, *invalid))
            )
    return _update_preview(
        loaded,
        updated,
        operation_id=operation,
        defect_event_id=event_ids[0],
        consequential=target in _CONSEQUENTIAL_TARGETS,
        transaction_transition=(
            "supersession" if target == "superseded" else "draft_update"
        ),
        authority=authority,
    )


def defect_ready_check(
    defect_id: str,
    *,
    repo: Path,
) -> ReadyVerdict:
    """Return every READY gap rather than stopping at the first field."""

    loaded = read_defect(repo, defect_id)
    missing, invalid = defect_ready_issues(loaded.record)
    return ReadyVerdict(
        defect_id=defect_id,
        lifecycle=loaded.record["lifecycle"],
        ready=not missing
        and not invalid
        and loaded.record["lifecycle"] in {"investigating", "ready"},
        missing_fields=missing,
        invalid_fields=invalid,
    )


def _promotion_conditions(
    record: dict[str, Any],
    scope: dict[str, Any],
) -> list[bool]:
    existing = record["exemption"]["conditions"]
    return [
        existing[0] and not scope["new_behavior"],
        existing[1]
        and scope["repositories"] == 1
        and len(scope["components"]) <= 2
        and scope["sessions"] == 1,
        (
            existing[2]
            and scope["repositories"] == 1
            and not scope["new_behavior"]
            and not scope["ui_visual"]
            and not scope["sensitive"]
            and not scope["new_dependency"]
            and not scope["schema_or_state_change"]
        ),
        existing[3],
        existing[4] and scope["reversible"],
    ]


def _prd_seed(record: dict[str, Any]) -> dict[str, Any]:
    repository_key, defect_uuid = parse_defect_id(record["id"])
    if repository_key != record["repository_key"]:
        raise ValueError("defect_repository_mismatch")
    seed_uuid = str(
        uuid.uuid5(
            uuid.UUID(defect_uuid),
            "feature-promotion-prd-seed",
        )
    )
    return {
        "schema": "doc-warden/prd-seed/v1",
        "id": f"PRD-SEED-{seed_uuid}",
        "status": "draft",
        "source_defect_id": record["id"],
        "problem": record["problem"],
        "current_behavior": record["actual"],
        "target_behavior": record["expected"],
        "evidence": list(record["evidence"]),
        "affected_users": list(record["affected_users"]),
        "requirement_candidates": list(record["requirement_candidates"]),
        "dependencies": list(record["dependencies"]),
        "risk": list(record["risks"]),
        "open_decisions": list(record["open_decisions"]),
        "related_artifacts": [{"kind": "defect", "id": record["id"]}],
    }


def promote_defect(
    defect_id: str,
    *,
    repo: Path,
    timestamp: str,
    source: str,
    author_class: str,
    scope: dict[str, Any] | None = None,
    operation_id: str | None = None,
    binding_root: Path | None = None,
) -> PrdSeed:
    """Auto-promote scope growth, persist the link, and pause defect fixing."""

    authority = prepare_authority(repo, binding_root)
    loaded = read_defect(repo, defect_id)
    operation = _operation(operation_id)
    event_id = _event_id(operation, defect_id, "promoted")
    prior_events = [
        event
        for event in loaded.record["events"]
        if event["event_id"] == event_id
    ]
    if prior_events:
        event = prior_events[0]
        if scope is not None and _scope(scope) != event["payload"].get("scope"):
            raise ValueError("defect_operation_replay_mismatch")
        replay = _existing_receipt(
            loaded,
            operation_id=operation,
            event_id=event_id,
            kind="promoted",
            timestamp=timestamp,
            source=source,
            author_class=author_class,
            payload=event["payload"],
            authority=authority,
        )
        assert replay is not None
        return PrdSeed(
            record=event["payload"]["promotion"]["prd_seed"],
            receipt=replay,
        )
    if loaded.record["lifecycle"] in {*_DEFECT_TERMINAL_LIFECYCLES, "resolved"}:
        raise ValueError("defect_promotion_lifecycle_invalid")
    selected_scope = _scope(scope) if scope is not None else loaded.record["scope"]
    conditions = _promotion_conditions(loaded.record, selected_scope)
    if all(conditions) and loaded.record["exemption"]["decision"] == "exempt":
        raise ValueError("defect_exemption_still_valid")
    seed = _prd_seed(loaded.record)
    focus = {
        "hypothesis": loaded.record["current_focus"]["hypothesis"],
        "test": loaded.record["current_focus"]["test"],
        "expecting": loaded.record["current_focus"]["expecting"],
        "next_action": f"draft and approve PRD seed {seed['id']} before resuming the fix",
        "bug_class": loaded.record["current_focus"]["bug_class"],
        "reasoning_checkpoint": loaded.record["current_focus"][
            "reasoning_checkpoint"
        ],
        "tdd_checkpoint": loaded.record["current_focus"]["tdd_checkpoint"],
    }
    promotion = {
        "status": "paused_for_prd",
        "source_defect_id": defect_id,
        "prd_seed": seed,
    }
    payload = {
        "lifecycle": "investigating",
        "scope": selected_scope,
        "exemption": {"decision": "promote", "conditions": conditions},
        "current_focus": focus,
        "fix_paused": True,
        "promotion": promotion,
        "related_artifact": seed["id"],
    }
    replay = _existing_receipt(
        loaded,
        operation_id=operation,
        event_id=event_id,
        kind="promoted",
        timestamp=timestamp,
        source=source,
        author_class=author_class,
        payload=payload,
        authority=authority,
    )
    if replay is not None:
        raise ValueError("defect_operation_replay_mismatch")
    if loaded.record["promotion"] is not None:
        raise ValueError("defect_already_promoted")
    record, event_id = _append_event(
        loaded.record,
        operation_id=operation,
        label="promoted",
        kind="promoted",
        timestamp=timestamp,
        source=source,
        author_class=author_class,
        payload=payload,
    )
    preview = _update_preview(
        loaded,
        record,
        operation_id=operation,
        defect_event_id=event_id,
        consequential=False,
        prd_seed_id=seed["id"],
        authority=authority,
    )
    receipt = apply_transaction(preview.transaction, None)
    return PrdSeed(record=seed, receipt=receipt)


__all__ = [
    "DefectPreview",
    "PrdSeed",
    "ReadyVerdict",
    "append_evidence",
    "create_defect",
    "defect_ready_check",
    "eliminate_hypothesis",
    "promote_defect",
    "read_defect",
    "reevaluate_exemption",
    "transition_defect",
]
