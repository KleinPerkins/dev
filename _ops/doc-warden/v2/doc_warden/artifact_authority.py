"""Resolve current, receipt-bound semantic authority for authoring operations."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .artifact_discovery import ADR_NAME, adr_directory, artifact_paths
from .canonical import contained_path, digest_ref, parse_json_object
from .transactions import ObservedInput, directory_input_digest
from .validators import (
    parse_validated_artifact, read_repository_config, record_approved_successor, require_valid, validate_relation_record,
)


AUTHORITY_PREFIXES = {
    "adr": "ADR", "asset": "ASSET", "design": "DESIGN", "plan": "PLAN", "prd": "PRD",
    "project": "PROJECT", "prototype": "PROTO", "release": "REL", "sketch": "SKETCH",
    "spec": "SPEC", "spike": "SPIKE", "uat": "UAT", "uxr": "UXR", "verification": "VER",
}
RECEIPTS = "_ops/doc-warden/state/v2/receipts"
EVENTS = "_ops/doc-warden/state/v2/events"
APPROVED_PARENTS_SCHEMA = "doc-warden/approved-parents/v1"


@dataclass(frozen=True)
class ApprovedArtifact:
    path: Path
    metadata: dict[str, Any]
    digest: str
    source_revision: str
    operation_id: str
    observed_inputs: tuple[ObservedInput, ...]


def _artifact_identity(repo: Path, path: Path, metadata: dict[str, Any], profile: dict[str, Any]) -> None:
    kind = metadata["type"]
    prefix = f"{AUTHORITY_PREFIXES[kind]}-{profile['repository_key']}-"
    identifier = metadata["id"]
    suffix = identifier.removeprefix(prefix)
    try:
        valid_uuid = str(uuid.UUID(suffix)) == suffix
    except ValueError:
        valid_uuid = False
    if (not identifier.startswith(prefix) or not valid_uuid
            or metadata["repository_key"] != profile["repository_key"]
            or metadata["github_repository_id"] != profile["github_repository_id"]):
        raise ValueError("authority_artifact_identity_mismatch")
    if kind == "adr":
        canonical = path.parent == repo / adr_directory(repo) and ADR_NAME.fullmatch(path.name)
    else:
        canonical = path == repo / ".planning/artifacts" / f"{identifier}-v{metadata['version']}.md"
    if not canonical:
        raise ValueError("authority_artifact_path_invalid")


def _in_authority_scope(path: Path, owner: Path, kind: str) -> bool:
    return path.parent == owner and (
        bool(ADR_NAME.fullmatch(path.name)) if kind == "adr"
        else path.suffix == ".md" and path.name.startswith(AUTHORITY_PREFIXES[kind] + "-")
    )


def _freeze_evidence(
    repo: Path, owner: Path, kind: str, repository_id: int | None,
) -> tuple[dict[Path, tuple[str, str, str]], dict[str, ObservedInput]]:
    from .adrs import _validate_freeze_receipt, frozen_semantic_postimages

    directory = contained_path(repo, f"{RECEIPTS}/.receipt-probe").parent
    accepted: dict[Path, tuple[str, str, str]] = {}
    observed: dict[str, ObservedInput] = {}
    if directory.is_dir():
        observed[str(directory)] = ObservedInput(str(directory), directory_input_digest(directory))
    for path in sorted(directory.glob("*.json")):
        contained_path(repo, path.relative_to(repo).as_posix())
        data = path.read_bytes()
        observed[str(path)] = ObservedInput(str(path), digest_ref(data))
        receipt = parse_json_object(data)
        require_valid("receipt", receipt)
        frozen = frozen_semantic_postimages(receipt)
        matches = [(relative, digest) for relative, digest in frozen.items()
                   if _in_authority_scope(repo / relative, owner, kind)]
        if not matches:
            continue
        event = contained_path(repo, f"{EVENTS}/{receipt['event_id']}.json")
        event_digest = digest_ref(event.read_bytes())
        _validate_freeze_receipt(repo, path, receipt)
        if receipt["github_repository_id"] != repository_id:
            raise ValueError("authority_freeze_mismatch")
        observed[str(event)] = ObservedInput(str(event), event_digest)
        for relative, digest in matches:
            artifact = contained_path(repo, relative)
            if artifact in accepted:
                raise ValueError("authority_freeze_ambiguous")
            if not artifact.is_file() or digest_ref(artifact.read_bytes()) != digest:
                raise ValueError("authority_freeze_mismatch")
            if kind == "plan":
                sidecar = artifact.with_suffix(".governance.json")
                sidecar = contained_path(repo, sidecar.relative_to(repo).as_posix())
                if not sidecar.is_file():
                    raise ValueError("authority_plan_sidecar_required")
                pair_digest = digest_ref(sidecar.read_bytes())
                if frozen.get(sidecar.relative_to(repo).as_posix()) != pair_digest:
                    raise ValueError("authority_freeze_mismatch")
                observed[str(sidecar)] = ObservedInput(str(sidecar), pair_digest)
            accepted[artifact] = (digest, receipt["source_revision"], receipt["operation_id"])
    return accepted, observed


def resolve_approved_artifact(
    repo: Path, kind: str, artifact_id: str | None = None,
    *, version: int | None = None, digest: str | None = None,
) -> ApprovedArtifact:
    """Find one active approved artifact and bind the evidence used to select it."""
    if kind not in AUTHORITY_PREFIXES:
        raise ValueError("authority_artifact_kind_invalid")
    if artifact_id is not None and (not isinstance(artifact_id, str) or not artifact_id):
        raise ValueError("authority_artifact_id_invalid")
    if version is not None and (type(version) is not int or version < 1):
        raise ValueError("authority_artifact_version_invalid")
    if digest is not None and (not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None):
        raise ValueError("authority_artifact_digest_invalid")

    root = repo.resolve(strict=True)
    profile_path = contained_path(root, ".planning/doc-warden.json")
    profile = read_repository_config(root)
    if profile is None:
        raise ValueError("v2_repository_profile_required")
    observed = [ObservedInput(str(profile_path), digest_ref(profile_path.read_bytes()))]
    # Observe the candidate inventory as well as its bytes. A new or modified
    # successor can change which record is current without touching the chosen parent.
    adr_root = root / adr_directory(root)
    planning_root = root / ".planning/artifacts"
    inventory_roots = dict.fromkeys((".planning/artifacts", adr_root.relative_to(root).as_posix()))
    for relative in inventory_roots:
        inventory = contained_path(root, f"{relative}/.artifact-probe").parent
        if inventory.is_dir():
            observed.append(ObservedInput(str(inventory), directory_input_digest(inventory)))
    override = contained_path(root, ".doc-warden.yml")
    if override.is_file():
        observed.append(ObservedInput(str(override), digest_ref(override.read_bytes())))
    owner = adr_root if kind == "adr" else planning_root
    frozen, freeze_inputs = _freeze_evidence(root, owner, kind, profile["github_repository_id"])
    approved = {}
    for path in artifact_paths(root):
        if not _in_authority_scope(path, owner, kind):
            continue
        content = path.read_bytes()
        content_digest = digest_ref(content)
        metadata = parse_validated_artifact(path, repo=root, content=content)
        if metadata["type"] != kind:
            raise ValueError("authority_artifact_identity_mismatch")
        _artifact_identity(root, path, metadata, profile)
        observed.append(ObservedInput(str(path), content_digest))
        if path in frozen and (frozen[path][0] != content_digest or metadata["lifecycle"] != "approved"):
            raise ValueError("authority_freeze_mismatch")
        if metadata["lifecycle"] != "approved":
            continue
        if path not in frozen:
            raise ValueError("authority_freeze_required")
        if metadata["id"] in approved:
            raise ValueError("authority_artifact_ambiguous")
        approved[metadata["id"]] = (path, metadata, content_digest)
    if {record[0] for record in approved.values()} != set(frozen):
        raise ValueError("authority_freeze_mismatch")

    retired: dict[str, tuple[str, str, str]] = {}
    for _, metadata, _ in approved.values():
        record_approved_successor(retired, metadata)
    active = [record for identifier, record in approved.items()
              if identifier not in retired and (artifact_id is None or artifact_id == identifier)]
    if len(active) != 1:
        raise ValueError("authority_artifact_required" if not active else "authority_artifact_ambiguous")
    path, metadata, content_digest = active[0]
    if (version is not None and version != metadata["version"]) or (digest is not None and digest != content_digest):
        raise ValueError("authority_artifact_stale")
    if kind == "plan":
        from .dependencies import _validated_plan_sidecar

        sidecar = path.with_suffix(".governance.json")
        if not sidecar.is_file() or sidecar.is_symlink():
            raise ValueError("authority_plan_sidecar_required")
        plan = _validated_plan_sidecar(root, sidecar)
        if plan is None or not plan["accepted"] or plan["canonical_plan_digest"] != content_digest:
            raise ValueError("authority_plan_sidecar_invalid")
    _, source_revision, operation_id = frozen[path]
    return ApprovedArtifact(path, metadata, content_digest, source_revision, operation_id,
                            (*observed, *freeze_inputs.values()))


def approved_parent_relations(repo: Path, source: dict[str, Any], requested: object):
    """Derive typed relations and observed inputs from closed parent selectors."""
    if (not isinstance(requested, dict) or set(requested) != {"parents", "observed_at"}
            or not isinstance(requested["parents"], list) or not requested["parents"]):
        raise ValueError("approved_parents_invalid")
    try:
        timestamp = datetime.fromisoformat(requested["observed_at"])
    except (TypeError, ValueError) as exc:
        raise ValueError("approved_parents_invalid") from exc
    if timestamp.tzinfo is None:
        raise ValueError("approved_parents_invalid")
    relations = []
    observed: dict[str, ObservedInput] = {}
    seen = set()
    for parent in requested["parents"]:
        if (not isinstance(parent, dict) or set(parent) != {"kind", "id", "version", "digest"}
                or not isinstance(parent["kind"], str) or not isinstance(parent["id"], str)
                or type(parent["version"]) is not int or not isinstance(parent["digest"], str)
                or parent["id"] == source["id"] or parent["id"] in seen):
            raise ValueError("approved_parent_invalid")
        seen.add(parent["id"])
        authority = resolve_approved_artifact(repo, parent["kind"], parent["id"],
                                              version=parent["version"], digest=parent["digest"])
        relation = {
            "schema": "doc-warden/relation/v2", "relation": "derives_from",
            "source_id": source["id"], "source_kind": source["type"], "source_version": source["version"],
            "target": {"kind": parent["kind"], "id": parent["id"], "version": parent["version"]},
            "authority": "planned", "lifecycle": "active",
            "observed_at": requested["observed_at"], "observed_revision": authority.source_revision,
            "provenance": [{"digest": authority.digest}],
        }
        relations.append(validate_relation_record(relation))
        for item in authority.observed_inputs:
            if observed.setdefault(item.path, item) != item:
                raise ValueError("observed_input_drift")
    return relations, tuple(observed.values())
