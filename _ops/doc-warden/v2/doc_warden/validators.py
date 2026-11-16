"""Small standard-library validator for doc-warden's closed schemas."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from .canonical import (
    CanonicalError,
    canonical_json,
    contained_path,
    digest_ref,
    parse_artifact,
    parse_json_object,
    sha256_bytes,
)


SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "schemas" / "v2"


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True)
class ProvenanceVerdict:
    status: str
    code: str
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApprovedDesignArtifact:
    path: Path
    metadata: dict[str, Any]
    contract: dict[str, Any]
    digest: str


@dataclass(frozen=True)
class ValidatedDefectArtifact:
    path: Path
    metadata: dict[str, Any]
    record: dict[str, Any]
    digest: str


class _RepositoryProfileAction(Protocol):
    path: str
    content: bytes
    kind: str


_EXTERNAL_ASSET_SCHEMA = "doc-warden/external-asset/v2"
_EXTERNAL_ASSET_OBSERVATION_SCHEMA = "doc-warden/external-asset-observation/v1"
_EXTERNAL_ASSET_EGRESS = "external_asset_pointer/v1"
_EXTERNAL_ASSET_PROVIDERS = frozenset({"figma", "quickhost", "local"})
_EXTERNAL_ASSET_POINTER_FIELDS = frozenset(
    {"canonical_url", "source_path", "immutable_revision", "export_sha256"}
)
_EXTERNAL_ASSET_IMMUTABILITY_FIELDS = frozenset(
    {"immutable_revision", "export_sha256"}
)
_PROTOTYPE_REFERENCE = re.compile(
    r"PROTO-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*"
)
_DESIGN_ID = re.compile(
    r"DESIGN-(?P<repository_key>[0-9a-f]{8}-[0-9a-f]{4}-[45][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})-"
    r"(?P<artifact_uuid>[0-9a-f]{8}-[0-9a-f]{4}-[45][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})"
)
_DEFECT_ID = re.compile(
    r"DEF-(?P<repository_key>[0-9a-f]{8}-[0-9a-f]{4}-[45][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})-"
    r"(?P<artifact_uuid>[0-9a-f]{8}-[0-9a-f]{4}-[45][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})"
)
_DEFECT_SYMPTOM_FIELDS = (
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


def parse_defect_id(defect_id: object) -> tuple[str, str]:
    """Return the canonical repository and artifact UUIDs for one defect ID."""

    match = _DEFECT_ID.fullmatch(defect_id) if isinstance(defect_id, str) else None
    if match is None:
        raise ValueError("defect_id_invalid")
    return match.group("repository_key"), match.group("artifact_uuid")


_DEFECT_TRANSITIONS = {
    "reported": frozenset(
        {"triaged", "duplicate", "waived", "wont_fix", "superseded"}
    ),
    "triaged": frozenset(
        {"investigating", "duplicate", "waived", "wont_fix", "superseded"}
    ),
    "investigating": frozenset(
        {"ready", "duplicate", "waived", "wont_fix", "superseded"}
    ),
    "ready": frozenset({"fixing", "investigating", "superseded"}),
    "fixing": frozenset({"verifying", "investigating", "superseded"}),
    "verifying": frozenset({"resolved", "investigating", "superseded"}),
    "resolved": frozenset({"recurred"}),
    "recurred": frozenset({"investigating", "superseded"}),
    "duplicate": frozenset(),
    "waived": frozenset(),
    "wont_fix": frozenset(),
    "superseded": frozenset(),
}
_DEFECT_RELATION_FOR_TARGET = {
    "duplicate": "duplicates",
    "waived": "waives",
    "wont_fix": "waives",
    "recurred": "recurs_as",
    "superseded": "supersedes",
}
_DEFECT_TERMINAL_LIFECYCLES = frozenset(
    {"duplicate", "waived", "wont_fix", "superseded"}
)
_PRD_SEED_ID = re.compile(
    r"PRD-SEED-[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
_PRD_SEED_FIELDS = frozenset(
    {
        "schema",
        "id",
        "status",
        "source_defect_id",
        "problem",
        "current_behavior",
        "target_behavior",
        "evidence",
        "affected_users",
        "requirement_candidates",
        "dependencies",
        "risk",
        "open_decisions",
        "related_artifacts",
    }
)
_GENERIC_DEFECT_ACTION = re.compile(
    r"^(?:continue |keep |start )?(?:investigat(?:e|ing|ion)|debug(?:ging)?)"
    r"(?: (?:the )?(?:issue|defect|bug))?[.!]?$",
    re.IGNORECASE,
)


def is_external_asset_record(record: dict[str, Any]) -> bool:
    """Recognize external-asset provenance without classifying generic provenance."""

    keys = set(record)
    schema = record.get("schema")
    if schema == _EXTERNAL_ASSET_SCHEMA or (
        isinstance(schema, str) and schema.startswith("doc-warden/external-asset/")
    ):
        return True
    egress = record.get("egress_projection")
    if egress == _EXTERNAL_ASSET_EGRESS or (
        isinstance(egress, str) and egress.startswith("external_asset_pointer/")
    ):
        return True
    if {"provider", "canonical_url"} <= keys:
        return True
    if (
        record.get("provider") in _EXTERNAL_ASSET_PROVIDERS
        and bool(keys & _EXTERNAL_ASSET_POINTER_FIELDS)
    ):
        return True
    if "canonical_url" in keys and bool(keys & _EXTERNAL_ASSET_IMMUTABILITY_FIELDS):
        return True
    return _EXTERNAL_ASSET_IMMUTABILITY_FIELDS <= keys


def is_external_asset_observation(record: dict[str, Any]) -> bool:
    """Recognize the one closed read-only observation record."""

    schema = record.get("schema")
    return schema == _EXTERNAL_ASSET_OBSERVATION_SCHEMA or (
        isinstance(schema, str)
        and schema.startswith("doc-warden/external-asset-observation/")
    )


def external_asset_digest(record: dict[str, Any]) -> str:
    """Bind observation evidence to exact canonical external-asset assertions."""

    require_valid("external-asset", record)
    return digest_ref(canonical_json(record))


def _type_matches(expected: str, value: object) -> bool:
    return {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "integer": lambda: isinstance(value, int) and not isinstance(value, bool),
        "boolean": lambda: isinstance(value, bool),
        "null": lambda: value is None,
    }[expected]()


def _walk(schema: dict[str, Any], value: object, path: str, issues: list[ValidationIssue]) -> None:
    if "const" in schema and value != schema["const"]:
        issues.append(ValidationIssue(path, "const", f"must equal {schema['const']!r}"))
        return
    if "enum" in schema and value not in schema["enum"]:
        issues.append(ValidationIssue(path, "enum", "value is outside the closed enum"))
    alternatives = schema.get("anyOf")
    if alternatives:
        if not any(not _validate(sub, value, path) for sub in alternatives):
            issues.append(ValidationIssue(path, "anyOf", "no allowed shape matched"))
        return
    expected = schema.get("type")
    if isinstance(expected, list):
        if not any(_type_matches(item, value) for item in expected):
            issues.append(ValidationIssue(path, "type", f"expected one of {expected}"))
            return
    elif isinstance(expected, str) and not _type_matches(expected, value):
        issues.append(ValidationIssue(path, "type", f"expected {expected}"))
        return
    if isinstance(value, str):
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None:
            issues.append(ValidationIssue(path, "pattern", "value does not match required form"))
        if len(value) < schema.get("minLength", 0):
            issues.append(ValidationIssue(path, "minLength", "value is too short"))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            issues.append(ValidationIssue(path, "minItems", "array has too few items"))
        max_items = schema.get("maxItems")
        if max_items is not None and len(value) > max_items:
            issues.append(ValidationIssue(path, "maxItems", "array has too many items"))
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            issues.append(ValidationIssue(path, "uniqueItems", "array items must be unique"))
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                _walk(item_schema, item, f"{path}/{index}", issues)
    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                issues.append(ValidationIssue(f"{path}/{key}", "required", "field is required"))
        properties = schema.get("properties", {})
        allowed_extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            child_path = f"{path}/{key}"
            if key in properties:
                _walk(properties[key], item, child_path, issues)
            elif allowed_extra is False:
                issues.append(ValidationIssue(child_path, "unknown_field", "field is not allowed"))
            elif isinstance(allowed_extra, dict):
                _walk(allowed_extra, item, child_path, issues)


def _validate(schema: dict[str, Any], value: object, path: str = "$") -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _walk(schema, value, path, issues)
    return issues


def load_schema(schema_name: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z][a-z0-9-]*", schema_name):
        raise ValueError("invalid schema name")
    path = SCHEMA_ROOT / f"{schema_name}.schema.json"
    try:
        return parse_json_object(path.read_bytes())
    except FileNotFoundError as exc:
        raise ValueError(f"unknown schema: {schema_name}") from exc


def validate_record(schema_name: str, value: object) -> list[ValidationIssue]:
    return _validate(load_schema(schema_name), value)


def require_valid(schema_name: str, value: object) -> None:
    issues = validate_record(schema_name, value)
    if issues:
        rendered = "; ".join(f"{issue.path}: {issue.code}" for issue in issues)
        raise ValueError(f"{schema_name} validation failed: {rendered}")


def validate_relation_record(value: dict[str, Any]) -> dict[str, Any]:
    """Validate typed relation semantics beyond the closed JSON shape."""

    require_valid("relation", value)
    target = value["target"]
    relation = value["relation"]
    authority = value["authority"]
    authority_relations = {
        "depends_on_planned": "planned",
        "depends_on_observed": "observed",
        "implements_planned": "planned",
        "implements_observed": "observed",
    }
    if relation in authority_relations and authority != authority_relations[relation]:
        raise ValueError("relation_authority_mismatch")
    anchor = target.get("anchor")
    if target["kind"] in {"file", "symbol", "schema", "test"}:
        if not isinstance(anchor, dict) or anchor.get("kind") != target["kind"]:
            raise ValueError("relation_code_anchor_required")
        anchor_path = Path(anchor["path"])
        if (
            anchor_path.is_absolute()
            or ".." in anchor_path.parts
            or anchor_path.as_posix() != anchor["path"]
            or (
                target["kind"] == "symbol"
                and not anchor.get("symbol")
            )
        ):
            raise ValueError("relation_code_anchor_invalid")
    elif anchor is not None:
        raise ValueError("relation_anchor_kind_mismatch")
    if target["kind"] == "external_asset" and not value.get("provider_revision"):
        raise ValueError("relation_provider_revision_required")
    evidence = value.get("match_evidence")
    if evidence is not None:
        candidates = evidence.get("candidate_target_ids")
        if (
            not isinstance(evidence.get("method"), str)
            or not isinstance(evidence.get("prior_target_id"), str)
            or not isinstance(candidates, list)
            or not candidates
            or not all(isinstance(item, str) and item for item in candidates)
            or candidates != sorted(set(candidates))
        ):
            raise ValueError("relation_match_evidence_invalid")
    return value


def read_repository_config(repo: Path) -> dict[str, Any] | None:
    path = repo / ".planning" / "doc-warden.json"
    if not path.exists():
        return None
    try:
        value = parse_json_object(path.read_bytes())
        require_valid("doc-warden-config", value)
    except (CanonicalError, OSError, ValueError) as exc:
        raise ValueError("repository_key_unreadable") from exc
    return value


def parse_validated_artifact(path: Path, *, repo: Path | None = None) -> dict[str, Any]:
    parsed = parse_artifact(path)
    require_valid("artifact", parsed.metadata)
    for relation in parsed.metadata["relations"]:
        validate_relation_record(relation)
        if relation["source_id"] != parsed.metadata["id"]:
            raise ValueError("artifact_relation_source_mismatch")
    if any(
        is_external_asset_record(record)
        or is_external_asset_observation(record)
        for record in parsed.metadata["provenance"]
    ):
        inferred_repo = repo or next(
            (parent for parent in path.parents if (parent / ".planning/doc-warden.json").is_file()),
            path.parent.parent.parent
            if path.parent.name == "artifacts"
            and path.parent.parent.name == ".planning"
            else path.parent,
        )
        validate_external_asset_provenance(
            parsed.metadata["provenance"],
            lifecycle=parsed.metadata["lifecycle"],
            repo=inferred_repo.resolve(strict=True),
        )
    if (
        parsed.metadata["type"] == "design"
        and parsed.metadata["lifecycle"] == "approved"
    ):
        validated_design_contract(parsed.metadata, parsed.body)
    if parsed.metadata["type"] == "defect":
        validated_defect_record(parsed.metadata, parsed.body)
    return parsed.metadata


def active_approved_artifacts(
    repo: Path,
    artifact_type: str,
) -> list[tuple[Path, dict[str, Any], str]]:
    """Load valid approved artifacts and apply the shared supersession rule."""

    rows: list[tuple[Path, dict[str, Any], str]] = []
    try:
        canonical_repo = repo.resolve(strict=True)
        from .artifact_discovery import artifact_paths
        for path in artifact_paths(canonical_repo):
            parsed = parse_artifact(path)
            require_valid("artifact", parsed.metadata)
            for relation in parsed.metadata["relations"]:
                validate_relation_record(relation)
                if relation["source_id"] != parsed.metadata["id"]:
                    raise ValueError("artifact_relation_source_mismatch")
            validate_external_asset_provenance(
                parsed.metadata["provenance"],
                lifecycle=parsed.metadata["lifecycle"],
                repo=canonical_repo,
            )
            if (
                parsed.metadata["type"] == "design"
                and parsed.metadata["lifecycle"] == "approved"
            ):
                validated_design_contract(parsed.metadata, parsed.body)
            if (
                parsed.metadata["type"] != "adr"
                and path.name != f"{parsed.metadata['id']}-v{parsed.metadata['version']}.md"
            ):
                raise ValueError("artifact_state_invalid")
            if (
                parsed.metadata["type"] == artifact_type
                and parsed.metadata["lifecycle"] == "approved"
            ):
                rows.append((path, parsed.metadata, parsed.body))
    except (CanonicalError, OSError, ValueError) as exc:
        raise ValueError("artifact_state_invalid") from exc
    superseded = {
        str(metadata["supersedes"])
        for _path, metadata, _body in rows
        if metadata["supersedes"] is not None
    }
    return [row for row in rows if row[1]["id"] not in superseded]


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def defect_symptoms_digest(record: dict[str, Any]) -> str:
    """Hash the exact symptom fields that freeze at triage."""

    return digest_ref(
        canonical_json(
            {
                field: record.get(field)
                for field in _DEFECT_SYMPTOM_FIELDS
            }
        )
    )


def defect_event_digest(event: dict[str, Any]) -> str:
    """Hash one conventional defect event without its self-digest."""

    return digest_ref(
        canonical_json(
            {
                key: value
                for key, value in event.items()
                if key != "event_digest"
            }
        )
    )


def _event_tampered(event_id: object) -> ValueError:
    return ValueError(f"defect_event_tampered:{event_id}")


def _event_entry(
    event: dict[str, Any],
    payload: dict[str, Any],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    entry = {
        "event_id": event["event_id"],
        "timestamp": event["timestamp"],
        "source": event["source"],
        "author_class": event["author_class"],
        "prior_event_id": event["prior_event_id"],
        "prior_event_digest": event["prior_event_digest"],
    }
    try:
        entry.update({field: payload[field] for field in fields})
    except KeyError as exc:
        raise _event_tampered(event["event_id"]) from exc
    return entry


def _has_meaningful_string_entries(value: object) -> bool:
    return bool(
        isinstance(value, list)
        and value
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _complete_defect_known_good_revision(value: object) -> bool:
    """A revision or explicit unavailable baseline with closed history evidence."""
    schema = load_schema("defect")["properties"]["known_good_revision"]
    if _validate(schema, value) or value == "":
        return False
    if isinstance(value, dict):
        revisions = [entry["revision"] for entry in value["history"]]
        return len(revisions) == len(set(revisions))
    return True


def _complete_defect_symptoms(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != set(_DEFECT_SYMPTOM_FIELDS):
        return False
    list_fields = {"preconditions", "reproduction", "immutable_symptoms"}
    return all(
        _complete_defect_known_good_revision(value[field])
        if field == "known_good_revision"
        else _has_meaningful_string_entries(value[field])
        if field in list_fields
        else isinstance(value[field], str) and bool(value[field].strip())
        for field in _DEFECT_SYMPTOM_FIELDS
    )


def _complete_defect_resolution(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    verification = value.get("verification")
    return bool(
        value.get("root_cause")
        and value.get("fix")
        and isinstance(verification, dict)
        and _has_meaningful_string_entries(verification.get("automated"))
        and _has_meaningful_string_entries(verification.get("human"))
    )


def _complete_defect_exemption_record(
    record: dict[str, Any],
    state: dict[str, Any],
) -> bool:
    return bool(
        all(
            isinstance(record[field], str) and record[field].strip()
            for field in ("problem", "expected", "actual")
        )
        and _has_meaningful_string_entries(record["acceptance"])
        and state["evidence"]
        and _has_meaningful_string_entries(
            record["verification_plan"]["automated"]
        )
        and _has_meaningful_string_entries(
            record["verification_plan"]["human"]
        )
    )


def _valid_prd_seed(value: object, defect_id: str) -> bool:
    if not isinstance(value, dict) or set(value) != _PRD_SEED_FIELDS:
        return False
    list_fields = (
        "evidence",
        "affected_users",
        "requirement_candidates",
        "dependencies",
        "risk",
        "open_decisions",
        "related_artifacts",
    )
    return bool(
        value["schema"] == "doc-warden/prd-seed/v1"
        and isinstance(value["id"], str)
        and _PRD_SEED_ID.fullmatch(value["id"])
        and value["status"] == "draft"
        and value["source_defect_id"] == defect_id
        and all(
            isinstance(value[field], str)
            for field in ("problem", "current_behavior", "target_behavior")
        )
        and all(isinstance(value[field], list) for field in list_fields)
        and value["related_artifacts"] == [{"kind": "defect", "id": defect_id}]
    )


def _replay_defect_events(record: dict[str, Any]) -> dict[str, Any]:
    events = record["events"]
    state: dict[str, Any] | None = None
    prior_id: str | None = None
    prior_digest: str | None = None
    prior_timestamp: datetime | None = None
    seen_ids: set[str] = set()
    for index, event in enumerate(events):
        event_id = event["event_id"]
        timestamp = _timestamp(event["timestamp"])
        if (
            event_id in seen_ids
            or timestamp is None
            or (prior_timestamp is not None and timestamp < prior_timestamp)
            or event["prior_event_id"] != prior_id
            or event["prior_event_digest"] != prior_digest
            or defect_event_digest(event) != event["event_digest"]
        ):
            raise _event_tampered(event_id)
        seen_ids.add(event_id)
        payload = event["payload"]
        kind = event["kind"]
        if index == 0:
            if kind != "created":
                raise _event_tampered(event_id)
            required = {
                "lifecycle",
                "symptoms",
                "symptoms_digest",
                "symptoms_frozen_event_id",
                "current_focus",
                "hypotheses",
                "resolution",
                "relations",
                "related_artifacts",
                "scope",
                "exemption",
                "fix_paused",
                "promotion",
            }
            if (
                set(payload) != required
                or payload["lifecycle"] != "reported"
                or payload["symptoms_digest"] is not None
                or payload["symptoms_frozen_event_id"] is not None
                or payload["fix_paused"] is not False
                or payload["promotion"] is not None
                or not isinstance(payload["hypotheses"], list)
                or any(
                    hypothesis.get("status") == "eliminated"
                    for hypothesis in payload["hypotheses"]
                    if isinstance(hypothesis, dict)
                )
            ):
                raise _event_tampered(event_id)
            state = {
                "lifecycle": payload["lifecycle"],
                "symptoms_digest": payload["symptoms_digest"],
                "symptoms_frozen_event_id": payload["symptoms_frozen_event_id"],
                "evidence": [],
                "current_focus": payload["current_focus"],
                "next_action": payload["current_focus"]["next_action"],
                "hypotheses": payload["hypotheses"],
                "eliminated_hypotheses": [],
                "resolution": payload["resolution"],
                "relations": payload["relations"],
                "related_artifacts": payload["related_artifacts"],
                "scope": payload["scope"],
                "exemption": payload["exemption"],
                "fix_paused": payload["fix_paused"],
                "promotion": payload["promotion"],
            }
            if set(payload["symptoms"]) != set(_DEFECT_SYMPTOM_FIELDS):
                raise _event_tampered(event_id)
            baseline = payload["symptoms"]["known_good_revision"]
            if baseline != "" and not _complete_defect_known_good_revision(baseline):
                raise _event_tampered(event_id)
            state.update(payload["symptoms"])
        else:
            assert state is not None
            if state["lifecycle"] in _DEFECT_TERMINAL_LIFECYCLES:
                raise _event_tampered(event_id)
            if kind == "symptoms_frozen":
                if (
                    set(payload) != {"symptoms", "symptoms_digest", "lifecycle"}
                    or state["lifecycle"] != "reported"
                    or payload["lifecycle"] != "triaged"
                    or not _complete_defect_symptoms(payload["symptoms"])
                ):
                    raise _event_tampered(event_id)
                state.update(payload["symptoms"])
                state["symptoms_digest"] = payload["symptoms_digest"]
                state["symptoms_frozen_event_id"] = event_id
                state["lifecycle"] = payload["lifecycle"]
            elif kind == "evidence_appended":
                if set(payload) != {"checked", "found", "implication"}:
                    raise _event_tampered(event_id)
                state["evidence"] = [
                    *state["evidence"],
                    _event_entry(
                        event,
                        payload,
                        ("checked", "found", "implication"),
                    ),
                ]
            elif kind == "hypothesis_eliminated":
                if set(payload) != {"hypothesis_id", "evidence"}:
                    raise _event_tampered(event_id)
                hypothesis_id = payload["hypothesis_id"]
                matches = [
                    hypothesis
                    for hypothesis in state["hypotheses"]
                    if hypothesis["id"] == hypothesis_id
                ]
                if len(matches) != 1 or matches[0]["status"] != "active":
                    raise _event_tampered(event_id)
                hypotheses = [dict(hypothesis) for hypothesis in state["hypotheses"]]
                next(
                    hypothesis
                    for hypothesis in hypotheses
                    if hypothesis["id"] == hypothesis_id
                )["status"] = "eliminated"
                state["hypotheses"] = hypotheses
                state["eliminated_hypotheses"] = [
                    *state["eliminated_hypotheses"],
                    _event_entry(
                        event,
                        payload,
                        ("hypothesis_id", "evidence"),
                    ),
                ]
            elif kind == "focus_updated":
                if set(payload) != {"current_focus"}:
                    raise _event_tampered(event_id)
                state["current_focus"] = payload["current_focus"]
                state["next_action"] = payload["current_focus"]["next_action"]
            elif kind == "resolution_updated":
                if set(payload) != {"resolution"}:
                    raise _event_tampered(event_id)
                state["resolution"] = payload["resolution"]
            elif kind == "lifecycle_transition":
                allowed = {
                    "from",
                    "to",
                    "current_focus",
                    "resolution",
                    "relation",
                }
                target = payload.get("to")
                if (
                    not {"from", "to"} <= set(payload)
                    or set(payload) - allowed
                    or payload["from"] != state["lifecycle"]
                    or not isinstance(target, str)
                    or target not in _DEFECT_TRANSITIONS[state["lifecycle"]]
                ):
                    raise _event_tampered(event_id)
                relation_name = _DEFECT_RELATION_FOR_TARGET.get(target)
                relation = payload.get("relation")
                if relation_name is None:
                    if relation is not None:
                        raise _event_tampered(event_id)
                else:
                    if not isinstance(relation, dict):
                        raise _event_tampered(event_id)
                    try:
                        validate_relation_record(relation)
                    except ValueError as exc:
                        raise _event_tampered(event_id) from exc
                    if (
                        relation["source_id"] != record["id"]
                        or relation["relation"] != relation_name
                    ):
                        raise _event_tampered(event_id)
                final_resolution = payload.get("resolution", state["resolution"])
                if target == "resolved" and not _complete_defect_resolution(
                    final_resolution
                ):
                    raise _event_tampered(event_id)
                state["lifecycle"] = target
                if "current_focus" in payload:
                    state["current_focus"] = payload["current_focus"]
                    state["next_action"] = payload["current_focus"]["next_action"]
                if "resolution" in payload:
                    state["resolution"] = payload["resolution"]
                if "relation" in payload:
                    state["relations"] = [*state["relations"], payload["relation"]]
            elif kind == "exemption_reevaluated":
                exemption = payload.get("exemption")
                conditions = (
                    exemption.get("conditions")
                    if isinstance(exemption, dict)
                    else None
                )
                if (
                    set(payload) != {"exemption"}
                    or state["lifecycle"] != "investigating"
                    or state["fix_paused"]
                    or state["promotion"] is not None
                    or state["exemption"].get("decision") != "exempt"
                    or all(state["exemption"].get("conditions", []))
                    or not isinstance(exemption, dict)
                    or set(exemption) != {"decision", "conditions"}
                    or exemption["decision"] != "exempt"
                    or not isinstance(conditions, list)
                    or len(conditions) != 5
                    or any(not isinstance(item, bool) for item in conditions)
                    or not all(conditions)
                    or _defect_scope_requires_promotion(state["scope"])
                    or not _complete_defect_exemption_record(record, state)
                ):
                    raise _event_tampered(event_id)
                state["exemption"] = exemption
            elif kind == "promoted":
                required = {
                    "lifecycle",
                    "scope",
                    "exemption",
                    "current_focus",
                    "fix_paused",
                    "promotion",
                    "related_artifact",
                }
                promotion = payload.get("promotion")
                exemption = payload.get("exemption")
                if (
                    set(payload) != required
                    or state["lifecycle"] == "resolved"
                    or payload["lifecycle"] != "investigating"
                    or payload["fix_paused"] is not True
                    or not isinstance(exemption, dict)
                    or exemption.get("decision") != "promote"
                    or not isinstance(promotion, dict)
                    or promotion.get("source_defect_id") != record["id"]
                    or not _valid_prd_seed(
                        promotion.get("prd_seed"),
                        record["id"],
                    )
                    or payload["related_artifact"]
                    != promotion["prd_seed"].get("id")
                ):
                    raise _event_tampered(event_id)
                state["lifecycle"] = payload["lifecycle"]
                state["scope"] = payload["scope"]
                state["exemption"] = payload["exemption"]
                state["current_focus"] = payload["current_focus"]
                state["next_action"] = payload["current_focus"]["next_action"]
                state["fix_paused"] = payload["fix_paused"]
                state["promotion"] = payload["promotion"]
                state["related_artifacts"] = [
                    *state["related_artifacts"],
                    payload["related_artifact"],
                ]
            else:
                raise _event_tampered(event_id)
        prior_id = event_id
        prior_digest = event["event_digest"]
        prior_timestamp = timestamp
    assert state is not None
    state["record_version"] = len(events)
    state["updated_at"] = events[-1]["timestamp"]
    state["history_head"] = {
        "event_id": events[-1]["event_id"],
        "digest": events[-1]["event_digest"],
    }
    return state


def regenerate_defect_current_view(
    record: dict[str, Any],
) -> dict[str, Any]:
    """Return a copy whose mutable fields are regenerated from defect events."""

    regenerated = dict(record)
    regenerated.update(_replay_defect_events(record))
    return regenerated


def validate_defect_record(record: dict[str, Any]) -> dict[str, Any]:
    """Validate schema, hash links, frozen symptoms, and the event-derived view."""

    require_valid("defect", record)
    if record["known_good_revision"] != "" and not _complete_defect_known_good_revision(record["known_good_revision"]):
        raise ValueError("defect_known_good_revision_invalid")
    defect_match = _DEFECT_ID.fullmatch(record["id"])
    if (
        defect_match is None
        or defect_match.group("repository_key") != record["repository_key"]
        or record["record_version"] < 1
        or _timestamp(record["created_at"]) is None
        or _timestamp(record["updated_at"]) is None
    ):
        raise ValueError("defect_record_invalid")
    if (
        not isinstance(record["scope"]["repositories"], int)
        or isinstance(record["scope"]["repositories"], bool)
        or record["scope"]["repositories"] < 1
        or not isinstance(record["scope"]["sessions"], int)
        or isinstance(record["scope"]["sessions"], bool)
        or record["scope"]["sessions"] < 1
        or len(set(record["scope"]["components"]))
        != len(record["scope"]["components"])
        or len(record["exemption"]["conditions"]) != 5
    ):
        raise ValueError("defect_record_invalid")
    hypothesis_ids = [hypothesis["id"] for hypothesis in record["hypotheses"]]
    if len(set(hypothesis_ids)) != len(hypothesis_ids):
        raise ValueError("defect_hypothesis_duplicate")
    for anchor in record["anchors"]:
        anchor_path = Path(anchor["path"])
        if (
            anchor["repository_key"] != record["repository_key"]
            or not anchor["path"]
            or anchor_path.is_absolute()
            or ".." in anchor_path.parts
            or anchor_path.as_posix() != anchor["path"]
        ):
            raise ValueError("defect_anchor_invalid")
    for relation in record["relations"]:
        validate_relation_record(relation)
        if relation["source_id"] != record["id"]:
            raise ValueError("defect_relation_source_mismatch")

    replayed = _replay_defect_events(record)
    freeze_event_id = record["symptoms_frozen_event_id"]
    if freeze_event_id is not None:
        freeze_events = [
            event
            for event in record["events"]
            if event["event_id"] == freeze_event_id
            and event["kind"] == "symptoms_frozen"
        ]
        if (
            len(freeze_events) != 1
            or record["symptoms_digest"] != defect_symptoms_digest(record)
            or freeze_events[0]["payload"]["symptoms_digest"]
            != record["symptoms_digest"]
        ):
            raise ValueError(f"defect_symptoms_tampered:{freeze_event_id}")
    elif record["symptoms_digest"] is not None:
        raise ValueError("defect_symptoms_freeze_invalid")

    view_keys = {
        *_DEFECT_SYMPTOM_FIELDS,
        "lifecycle",
        "symptoms_digest",
        "symptoms_frozen_event_id",
        "evidence",
        "current_focus",
        "next_action",
        "hypotheses",
        "eliminated_hypotheses",
        "resolution",
        "relations",
        "related_artifacts",
        "scope",
        "exemption",
        "fix_paused",
        "promotion",
        "record_version",
        "updated_at",
        "history_head",
    }
    if any(record[key] != replayed[key] for key in view_keys):
        raise ValueError(
            "defect_current_view_tampered:"
            f"{record['events'][-1]['event_id']}"
        )
    return record


def validated_defect_record(
    metadata: dict[str, Any],
    body: str,
) -> dict[str, Any]:
    """Load one canonical defect body and bind it to artifact metadata."""

    try:
        record = parse_json_object(body)
    except CanonicalError as exc:
        raise ValueError("defect_artifact_state_invalid") from exc
    if body.encode("utf-8") != canonical_json(record):
        raise ValueError("defect_artifact_state_invalid")
    if (
        metadata.get("type") != "defect"
        or metadata.get("id") != record.get("id")
        or metadata.get("repository_key") != record.get("repository_key")
        or metadata.get("mutability") != "append_only"
    ):
        raise ValueError("defect_artifact_state_invalid")
    return validate_defect_record(record)


def load_defect_artifact(
    repo: Path,
    defect_id: str,
) -> ValidatedDefectArtifact:
    """Resolve exactly one canonical defect path without glob retargeting."""

    root = repo.resolve(strict=True)
    repository_key, _ = parse_defect_id(defect_id)
    config = read_repository_config(root)
    if (
        config is None
        or repository_key != config["repository_key"]
    ):
        raise ValueError("defect_repository_mismatch")
    path = contained_path(
        root,
        f".planning/artifacts/{defect_id}-v1.md",
    )
    if not path.is_file() or path.is_symlink():
        raise ValueError("defect_not_found")
    try:
        parsed = parse_artifact(path)
        require_valid("artifact", parsed.metadata)
        record = validated_defect_record(parsed.metadata, parsed.body)
    except (CanonicalError, OSError) as exc:
        raise ValueError("defect_artifact_state_invalid") from exc
    return ValidatedDefectArtifact(
        path=path,
        metadata=parsed.metadata,
        record=record,
        digest=digest_ref(path.read_bytes()),
    )


def _defect_scope_requires_promotion(scope: dict[str, Any]) -> bool:
    return bool(
        scope["repositories"] != 1
        or len(scope["components"]) > 2
        or scope["sessions"] != 1
        or scope["new_behavior"]
        or scope["ui_visual"]
        or scope["sensitive"]
        or scope["new_dependency"]
        or scope["schema_or_state_change"]
        or not scope["reversible"]
    )


def defect_ready_issues(
    record: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Enumerate every zero-context READY gap in deterministic field order."""

    validate_defect_record(record)
    missing: list[str] = []
    invalid: list[str] = []
    provenance = record["report_provenance"]
    for field in ("source", "reported_at", "author_class"):
        if not provenance[field]:
            missing.append(f"report_provenance.{field}")
    if provenance["reported_at"] and _timestamp(provenance["reported_at"]) is None:
        invalid.append("report_provenance.reported_at:invalid")
    if not record["environment"]:
        missing.append("environment")
    if not _has_meaningful_string_entries(record["preconditions"]):
        missing.append("preconditions")
    if not record["test_data"]:
        missing.append("test_data")
    if not _has_meaningful_string_entries(record["reproduction"]):
        missing.append("reproduction")
    for field in (
        "expected",
        "actual",
        "error_reference",
        "frequency",
        "known_good_revision",
        "known_bad_revision",
        "impact",
    ):
        if (not _complete_defect_known_good_revision(record[field])
                if field == "known_good_revision" else not record[field]):
            missing.append(field)
    if not _has_meaningful_string_entries(record["immutable_symptoms"]):
        missing.append("immutable_symptoms")
    for field in (
        "symptoms_digest",
        "evidence",
    ):
        if not record[field]:
            missing.append(field)
    focus = record["current_focus"]
    for field in ("hypothesis", "test", "expecting"):
        if not focus[field]:
            missing.append(f"current_focus.{field}")
    if not focus["next_action"]:
        missing.append("current_focus.next_action")
    elif _GENERIC_DEFECT_ACTION.fullmatch(focus["next_action"].strip()):
        invalid.append("current_focus.next_action:generic")
    active_hypotheses = [
        hypothesis
        for hypothesis in record["hypotheses"]
        if hypothesis["status"] in {"active", "confirmed"}
    ]
    if not active_hypotheses:
        missing.append("hypotheses")
    elif len(active_hypotheses) > 5:
        invalid.append("hypotheses:unbounded")
    code_kinds = {"file", "symbol", "schema"}
    if not any(anchor["kind"] in code_kinds for anchor in record["anchors"]):
        missing.append("anchors.code")
    if not any(anchor["kind"] == "test" for anchor in record["anchors"]):
        missing.append("anchors.test")
    if not _has_meaningful_string_entries(record["acceptance"]):
        missing.append("acceptance")
    for field in ("automated", "human"):
        if not _has_meaningful_string_entries(
            record["verification_plan"][field]
        ):
            missing.append(f"verification_plan.{field}")
    if (
        len(record["exemption"]["conditions"]) != 5
        or not all(record["exemption"]["conditions"])
    ):
        missing.append("exemption.conditions")
    if record["exemption"]["decision"] != "exempt":
        invalid.append("exemption.decision:promote")
    if _defect_scope_requires_promotion(record["scope"]):
        invalid.append("exemption.scope:promotion_required")
    if record["lifecycle"] not in {"investigating", "ready"}:
        invalid.append("lifecycle:not_investigating")
    if record["fix_paused"]:
        invalid.append("fix_paused")
    return tuple(missing), tuple(invalid)


def require_ready_defect(
    repo: Path,
    defect_id: str,
) -> ValidatedDefectArtifact:
    """Load a defect that has explicitly reached READY and bind its exact bytes."""

    artifact = load_defect_artifact(repo, defect_id)
    missing, invalid = defect_ready_issues(artifact.record)
    if artifact.record["lifecycle"] != "ready":
        invalid = (*invalid, "lifecycle:not_ready")
    if missing or invalid:
        raise ValueError(
            "defect_not_ready:" + ",".join((*missing, *invalid))
        )
    return artifact


def validate_egress(sink: str, value: object) -> dict[str, Any]:
    if sink not in {"receipt", "event", "save_game", "canvas", "hook", "job", "external_asset"}:
        raise ValueError("unknown egress sink")
    if sink in {"save_game", "canvas", "hook", "job"}:
        raise ValueError(f"{sink}_egress_not_activated")
    if not isinstance(value, dict):
        raise ValueError("egress payload must be an object")
    forbidden = {
        "credential",
        "credentials",
        "customer_data",
        "diff",
        "environment",
        "prompt",
        "raw_log",
        "secret",
        "source_body",
        "transcript",
    }
    sensitive_markers = ("begin private key", "token=", "password=", "secret=", "sk-", "xox")
    token_pattern = re.compile(
        r"(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
    )
    nested_keys = {
        "active_plan", "active_versions", "artifact_id", "artifact_ids", "authority_pointers",
        "blocker_ids", "blockers", "checkpoint_digest", "checkpoint_id", "classification", "code",
        "completion_evidence", "dependencies", "event", "findings", "freshness", "id", "job_id",
        "kind", "lifecycle", "next_action", "next_action_code", "observed", "observed_at", "outcome",
        "planned", "priority", "repository_key", "required_artifacts", "roadmap", "schema",
        "sequence", "source_revision", "state", "status", "transition", "wave",
    }

    close_nested = False

    digest_map_fields = {
        "design_digests",
        "postimages",
        "preimages",
        "template_digests",
    }

    def inspect(
        item: object,
        *,
        top: bool = False,
        field: str = "",
        parent: str = "",
    ) -> None:
        if isinstance(item, dict):
            if forbidden.intersection(item):
                raise ValueError("sensitive or free-form egress field refused")
            if close_nested and not top:
                unknown_nested = set(item) - nested_keys
                if unknown_nested:
                    raise ValueError(f"unknown nested egress fields: {sorted(unknown_nested)}")
            for key, child in item.items():
                inspect(child, field=key, parent=field)
        elif isinstance(item, list):
            for child in item:
                inspect(child, field=field, parent=parent)
        elif isinstance(item, str):
            counts = {character: item.count(character) for character in set(item)}
            entropy = (
                -sum((count / len(item)) * math.log2(count / len(item)) for count in counts.values())
                if item
                else 0.0
            )
            identifier_exempt = bool(re.fullmatch(r"[a-z]+(?:[-_][a-z]+)+", item))
            digest_shaped = re.fullmatch(r"sha256:[0-9a-f]{64}", item) is not None
            structured_field = (
                field.endswith(("_digest", "_digests", "_id", "_ids", "_key", "_revision", "_commit", "_sha256"))
                or field in {"canonical_root", "canonical_url", "digest", "path", "authority_pointers"}
                or (parent in digest_map_fields and digest_shaped)
            )
            high_entropy = (
                len(item) >= 32 and entropy >= 4.0 and not identifier_exempt and not structured_field
            )
            if (
                len(item) > 512
                or (digest_shaped and not structured_field)
                or any(marker in item.lower() for marker in sensitive_markers)
                or token_pattern.search(item)
                or high_entropy
            ):
                raise ValueError("unbounded or sensitive egress string refused")

    inspect(value, top=True)
    if sink == "receipt":
        require_valid("receipt", value)
        if value.get("canonical_root") != "$REPOSITORY_ROOT":
            raise ValueError("receipt_canonical_root_must_be_projected")
    elif sink == "event":
        require_valid("operation-event", value)
    elif sink == "external_asset":
        require_valid("external-asset", value)
    require_valid("egress", {"schema": "doc-warden/egress/v1", "sink": sink, "payload": value})
    return {"schema": "doc-warden/egress/v1", "sink": sink, "payload": value}


def _missing_mapping_keys(value: object, key: str, required: tuple[str, ...]) -> list[ValidationIssue]:
    if not isinstance(value, dict):
        return [ValidationIssue(f"/{key}", f"missing_{key}", f"{key} coverage is required")]
    issues: list[ValidationIssue] = []
    for child in required:
        if not value.get(child):
            issues.append(
                ValidationIssue(
                    f"/{key}/{child}",
                    f"missing_{key}_{child}",
                    f"{key} must cover {child}",
                )
            )
    return issues


def canonical_design_contract(
    design: object,
    *,
    lifecycle: str,
    approval: object,
    error_code: str = "design_contract_invalid",
) -> dict[str, Any]:
    """Return the semantic design payload after checking governance agreement."""

    if not isinstance(design, dict):
        raise ValueError(error_code)
    if (
        ("lifecycle" in design and design["lifecycle"] != lifecycle)
        or ("approval" in design and design["approval"] != approval)
    ):
        raise ValueError("design_authority_mismatch")
    contract = {
        key: value
        for key, value in design.items()
        if key not in {"lifecycle", "approval"}
    }
    if validate_record("design-contract", contract):
        raise ValueError(error_code)
    try:
        canonical_json(contract)
    except CanonicalError as exc:
        raise ValueError(error_code) from exc
    return contract


def validate_design_coverage(design: dict[str, Any]) -> list[ValidationIssue]:
    """Return field-level UI/design coverage gaps that block planning."""

    if not isinstance(design, dict):
        return [
            ValidationIssue(
                "/design",
                "design_contract_invalid",
                "design contract must be an object",
            )
        ]
    issues: list[ValidationIssue] = []
    contract = {
        key: value
        for key, value in design.items()
        if key not in {"lifecycle", "approval"}
    }
    for issue in validate_record("design-contract", contract):
        normalized_path = issue.path[1:] if issue.path.startswith("$") else issue.path
        issues.append(
            ValidationIssue(
                normalized_path or "/",
                issue.code,
                issue.message,
            )
        )
    required_top = (
        "requirements",
        "journeys",
        "information_hierarchy",
        "interaction_copy",
        "design_system",
        "visual_assets",
        "verification_rubric",
    )
    for key in required_top:
        if not design.get(key):
            issues.append(ValidationIssue(f"/{key}", f"missing_{key}", f"{key} is required"))
    issues.extend(
        _missing_mapping_keys(
            design.get("states"),
            "state",
            ("loading", "empty", "error", "success", "disabled", "recovery"),
        )
    )
    issues.extend(
        _missing_mapping_keys(
            design.get("accessibility"),
            "accessibility",
            ("keyboard", "screen_reader", "contrast", "motion", "focus"),
        )
    )
    responsive = design.get("responsive")
    if not isinstance(responsive, dict):
        issues.append(
            ValidationIssue("/responsive", "missing_responsive", "responsive coverage is required")
        )
    elif responsive.get("web_responsive"):
        for breakpoint in ("phone", "tablet", "desktop"):
            if not responsive.get(breakpoint):
                issues.append(
                    ValidationIssue(
                        f"/responsive/{breakpoint}",
                        f"missing_responsive_{breakpoint}",
                        f"responsive design must cover {breakpoint}",
                    )
                )
    unresolved = design.get("unresolved_interactions") or []
    if unresolved:
        prototypes = design.get("prototypes")
        if not isinstance(prototypes, list):
            issues.append(
                ValidationIssue(
                    "/prototypes",
                    "prototype_references_must_be_array",
                    "prototype references must be a canonical array",
                )
            )
        elif not prototypes:
            issues.append(
                ValidationIssue(
                    "/prototypes",
                    "prototype_required",
                    "unresolved interactions require an immutable prototype reference",
                )
            )
        else:
            seen: set[str] = set()
            for index, reference in enumerate(prototypes):
                if (
                    not isinstance(reference, str)
                    or _PROTOTYPE_REFERENCE.fullmatch(reference) is None
                ):
                    issues.append(
                        ValidationIssue(
                            f"/prototypes/{index}",
                            "prototype_reference_invalid",
                            "prototype reference must use the canonical PROTO identifier",
                        )
                    )
                elif reference in seen:
                    issues.append(
                        ValidationIssue(
                            f"/prototypes/{index}",
                            "prototype_reference_duplicate",
                            "prototype references must be unique",
                        )
                    )
                else:
                    seen.add(reference)
    approval = design.get("approval")
    if design.get("lifecycle") != "approved" or not isinstance(approval, dict) or not approval:
        issues.append(
            ValidationIssue("/approval", "design_not_approved", "approved design evidence is required")
        )
    return issues


def validated_design_contract(
    metadata: dict[str, Any],
    body: str,
) -> dict[str, Any]:
    """Load one approved design's exact canonical semantic body."""

    try:
        contract = parse_json_object(body)
        if body.encode("utf-8") != canonical_json(contract):
            raise ValueError("design_artifact_state_invalid")
        require_valid("design-contract", contract)
        coverage = validate_design_coverage(
            {
                **contract,
                "lifecycle": metadata.get("lifecycle"),
                "approval": metadata.get("approval"),
            }
        )
        if coverage:
            raise ValueError("design_artifact_state_invalid")
    except (CanonicalError, UnicodeError, ValueError) as exc:
        if str(exc) == "design_artifact_state_invalid":
            raise
        raise ValueError("design_artifact_state_invalid") from exc
    return contract


def active_approved_design_artifacts(
    repo: Path,
    repository_key: str,
) -> dict[str, ApprovedDesignArtifact]:
    """Resolve complete active design authorities from canonical repository state."""

    try:
        rows = active_approved_artifacts(repo, "design")
        active: dict[str, ApprovedDesignArtifact] = {}
        for path, metadata, body in rows:
            design_id = metadata.get("id")
            match = (
                _DESIGN_ID.fullmatch(design_id)
                if isinstance(design_id, str)
                else None
            )
            version = metadata.get("version")
            if (
                match is None
                or match.group("repository_key") != repository_key
                or metadata.get("repository_key") != repository_key
                or not isinstance(version, int)
                or isinstance(version, bool)
                or version < 1
                or not isinstance(metadata.get("approval"), dict)
                or not metadata["approval"]
                or design_id in active
            ):
                raise ValueError("design_artifact_state_invalid")
            contract = validated_design_contract(metadata, body)
            active[design_id] = ApprovedDesignArtifact(
                path=path.resolve(strict=True),
                metadata=dict(metadata),
                contract=contract,
                digest=digest_ref(path.read_bytes()),
            )
        return active
    except (OSError, ValueError) as exc:
        if str(exc) == "design_artifact_state_invalid":
            raise
        raise ValueError("design_artifact_state_invalid") from exc


def validate_design_authority_binding(
    repo: Path,
    binding: object,
) -> dict[str, ApprovedDesignArtifact]:
    """Fail closed unless a plan binding still names exact active design bytes."""

    if not isinstance(binding, dict) or set(binding) != {
        "design_ids",
        "design_versions",
        "design_digests",
    }:
        raise ValueError("design_authority_binding_invalid")
    design_ids = binding["design_ids"]
    versions = binding["design_versions"]
    digests = binding["design_digests"]
    if (
        not isinstance(design_ids, list)
        or not isinstance(versions, dict)
        or not isinstance(digests, dict)
    ):
        raise ValueError("design_authority_binding_invalid")
    if any(not isinstance(design_id, str) for design_id in design_ids):
        raise ValueError("design_authority_binding_invalid")
    if (
        len(set(design_ids)) != len(design_ids)
        or set(design_ids) != set(versions)
        or set(design_ids) != set(digests)
    ):
        raise ValueError("design_authority_binding_invalid")
    for design_id in design_ids:
        version = versions.get(design_id)
        digest = digests.get(design_id)
        if (
            _DESIGN_ID.fullmatch(design_id) is None
            or not isinstance(version, int)
            or isinstance(version, bool)
            or version < 1
            or not isinstance(digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
        ):
            raise ValueError("design_authority_binding_invalid")
    config = read_repository_config(repo)
    if config is None:
        raise ValueError("design_authority_binding_stale")
    active = active_approved_design_artifacts(repo, config["repository_key"])
    selected: dict[str, ApprovedDesignArtifact] = {}
    for design_id in design_ids:
        authority = active.get(design_id)
        if (
            authority is None
            or authority.metadata["version"] != versions[design_id]
            or authority.digest != digests[design_id]
        ):
            raise ValueError("design_authority_binding_stale")
        selected[design_id] = authority
    return selected


def _git_read(
    repo: Path,
    *arguments: str,
    literal_pathspecs: bool = False,
) -> subprocess.CompletedProcess[bytes] | None:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
        }
    )
    if literal_pathspecs:
        environment["GIT_LITERAL_PATHSPECS"] = "1"
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=False,
            capture_output=True,
            env=environment,
        )
    except OSError:
        return None


def _local_source_blob(
    repo: Path,
    source_commit: str,
    source_path: str,
) -> tuple[bytes | None, str | None]:
    top_level = _git_read(repo, "rev-parse", "--show-toplevel")
    if (
        top_level is None
        or top_level.returncode != 0
        or not top_level.stdout.endswith(b"\n")
        or b"\n" in top_level.stdout[:-1]
    ):
        return None, "local_repository_context_invalid"
    try:
        observed_root = Path(os.fsdecode(top_level.stdout[:-1])).resolve(strict=True)
    except (OSError, UnicodeError):
        return None, "local_repository_context_invalid"
    if observed_root != repo:
        return None, "local_repository_context_invalid"

    object_type = _git_read(repo, "cat-file", "-t", source_commit)
    if (
        object_type is None
        or object_type.returncode != 0
        or object_type.stdout != b"commit\n"
    ):
        return None, "local_source_commit_missing"

    entry = _git_read(
        repo,
        "ls-tree",
        "-z",
        "--full-tree",
        source_commit,
        "--",
        source_path,
        literal_pathspecs=True,
    )
    if entry is None or entry.returncode != 0:
        return None, "local_source_blob_missing"
    rows = [row for row in entry.stdout.split(b"\0") if row]
    if len(rows) != 1:
        return None, "local_source_blob_missing"
    metadata, separator, observed_path = rows[0].partition(b"\t")
    fields = metadata.split(b" ")
    if (
        separator != b"\t"
        or len(fields) != 3
        or fields[0] not in {b"100644", b"100755"}
        or fields[1] != b"blob"
        or observed_path != os.fsencode(source_path)
    ):
        return None, "local_source_blob_missing"
    try:
        object_id = fields[2].decode("ascii")
    except UnicodeDecodeError:
        return None, "local_source_blob_missing"
    blob = _git_read(repo, "cat-file", "blob", object_id)
    if blob is None or blob.returncode != 0:
        return None, "local_source_blob_missing"
    return blob.stdout, None


def _observation_verdict(
    record: dict[str, Any],
    observed_revision: str | None,
    observed_export_sha256: str | None,
    *,
    verified_without_observation: bool,
) -> ProvenanceVerdict:
    if (
        observed_revision is not None
        and observed_revision != record["immutable_revision"]
    ):
        return ProvenanceVerdict("stale", "immutable_revision_changed")
    if (
        observed_export_sha256 is not None
        and observed_export_sha256 != record["export_sha256"]
    ):
        return ProvenanceVerdict("stale", "export_digest_changed")
    if verified_without_observation or (
        observed_revision is not None and observed_export_sha256 is not None
    ):
        return ProvenanceVerdict("verified", "immutable_provenance_verified")
    if observed_revision is not None or observed_export_sha256 is not None:
        return ProvenanceVerdict("recorded", "observation_incomplete")
    return ProvenanceVerdict("recorded", "format_valid")


def _repository_config_from_profile_action(
    action: _RepositoryProfileAction,
) -> dict[str, Any]:
    if (
        action.path != ".planning/doc-warden.json"
        or action.kind != "create"
        or not isinstance(action.content, bytes)
    ):
        raise ValueError("repository_profile_action_invalid")
    value = parse_json_object(action.content)
    require_valid("doc-warden-config", value)
    if action.content != canonical_json(value):
        raise ValueError("repository_profile_action_invalid")
    return value


def _verify_external_asset(
    record: dict[str, Any],
    *,
    repo: Path | None = None,
    observed_revision: str | None = None,
    observed_export_sha256: str | None = None,
    repository_profile_action: _RepositoryProfileAction | None = None,
) -> ProvenanceVerdict:
    required = [
        "schema",
        "provider",
        "canonical_url",
        "immutable_revision",
        "source_repository_key",
        "source_github_repository_id",
        "source_commit",
        "export_sha256",
        "captured_at",
        "owner",
        "license",
        "egress_projection",
    ]
    nullable_fields = {"source_commit", "source_github_repository_id"}
    missing = [
        field
        for field in required
        if field not in record
        or (record.get(field) in ("", None) and field not in nullable_fields)
    ]
    provider = record.get("provider")
    if provider == "local":
        if not record.get("source_commit"):
            missing.append("source_commit")
        if not record.get("source_path"):
            missing.append("source_path")
    if missing:
        return ProvenanceVerdict(
            "unverifiable",
            "missing_immutable_provenance",
            tuple(dict.fromkeys(missing)),
        )
    try:
        require_valid("external-asset", record)
    except ValueError:
        return ProvenanceVerdict("unverifiable", "schema_invalid")
    if provider == "local":
        source_path = str(record.get("source_path", ""))
        if (
            source_path != Path(source_path).as_posix()
            or source_path.startswith("/")
            or ".." in Path(source_path).parts
        ):
            return ProvenanceVerdict("unverifiable", "local_source_path_invalid")
        if record["canonical_url"] != f"local:{source_path}":
            return ProvenanceVerdict("unverifiable", "local_canonical_url_mismatch")
        if repo is None:
            return ProvenanceVerdict(
                "unverifiable", "local_repository_context_required"
            )
        try:
            root = repo.resolve(strict=True)
            contained_path(root, source_path)
            config = read_repository_config(root)
        except (CanonicalError, OSError, ValueError):
            return ProvenanceVerdict(
                "unverifiable", "local_repository_context_invalid"
            )
        if config is None and repository_profile_action is not None:
            try:
                config = _repository_config_from_profile_action(
                    repository_profile_action
                )
            except (CanonicalError, OSError, TypeError, ValueError):
                return ProvenanceVerdict(
                    "unverifiable", "local_repository_profile_action_invalid"
                )
        if config is None:
            return ProvenanceVerdict(
                "unverifiable", "local_repository_config_required"
            )
        if record["source_repository_key"] != config["repository_key"]:
            return ProvenanceVerdict(
                "unverifiable", "local_repository_key_mismatch"
            )
        blob, error = _local_source_blob(
            root,
            str(record["source_commit"]),
            source_path,
        )
        if error is not None:
            return ProvenanceVerdict("unverifiable", error)
        assert blob is not None
        if sha256_bytes(blob) != record["export_sha256"]:
            return ProvenanceVerdict(
                "unverifiable", "local_export_digest_mismatch"
            )
        return _observation_verdict(
            record,
            observed_revision,
            observed_export_sha256,
            verified_without_observation=True,
        )
    return _observation_verdict(
        record,
        observed_revision,
        observed_export_sha256,
        verified_without_observation=False,
    )


def verify_external_asset(
    record: dict[str, Any],
    *,
    repo: Path | None = None,
    observed_revision: str | None = None,
    observed_export_sha256: str | None = None,
) -> ProvenanceVerdict:
    """Validate immutable local/Figma/Quickhost provenance from persisted state."""

    return _verify_external_asset(
        record,
        repo=repo,
        observed_revision=observed_revision,
        observed_export_sha256=observed_export_sha256,
    )


def _verify_external_asset_for_profile_action(
    record: dict[str, Any],
    *,
    repo: Path,
    repository_profile_action: _RepositoryProfileAction,
) -> ProvenanceVerdict:
    """Validate local provenance against the exact profile action being previewed."""

    return _verify_external_asset(
        record,
        repo=repo,
        repository_profile_action=repository_profile_action,
    )


def validate_external_asset_provenance(
    provenance: object,
    *,
    lifecycle: str,
    repo: Path,
    repository_profile_action: _RepositoryProfileAction | None = None,
) -> int:
    """Validate every external assertion and its separately recorded observation."""

    if not isinstance(provenance, list):
        raise ValueError("provenance_must_be_list")
    assets: dict[str, dict[str, Any]] = {}
    observations: dict[str, dict[str, Any]] = {}
    for record in provenance:
        if not isinstance(record, dict):
            raise ValueError("provenance_items_must_be_objects")
        if is_external_asset_observation(record):
            try:
                require_valid("external-asset-observation", record)
            except ValueError as exc:
                raise ValueError("external_asset_observation_invalid") from exc
            asset_digest = record["external_asset_digest"]
            if asset_digest in observations:
                raise ValueError("external_asset_observation_invalid")
            observations[asset_digest] = record
            continue
        if not is_external_asset_record(record):
            continue
        try:
            asset_digest = external_asset_digest(record)
        except (CanonicalError, ValueError) as exc:
            raise ValueError("external_asset_unverifiable") from exc
        if asset_digest in assets:
            raise ValueError("external_asset_provenance_duplicate")
        assets[asset_digest] = record

    for asset_digest, record in assets.items():
        observation = observations.pop(asset_digest, None)
        if record.get("provider") == "local":
            if observation is not None:
                raise ValueError("external_asset_observation_unexpected")
            if repository_profile_action is None:
                verdict = verify_external_asset(record, repo=repo)
            else:
                verdict = _verify_external_asset_for_profile_action(
                    record,
                    repo=repo,
                    repository_profile_action=repository_profile_action,
                )
        else:
            verdict = verify_external_asset(
                record,
                repo=repo,
                observed_revision=(
                    observation["observed_revision"]
                    if observation is not None
                    else None
                ),
                observed_export_sha256=(
                    observation["observed_export_sha256"]
                    if observation is not None
                    else None
                ),
            )
        accepted = (
            verdict.status == "verified"
            if record.get("provider") == "local" or lifecycle == "approved"
            else verdict.status in {"recorded", "verified"}
        )
        if not accepted:
            raise ValueError(f"external_asset_{verdict.status}")
    if observations:
        raise ValueError("external_asset_observation_orphan")
    return len(assets)
