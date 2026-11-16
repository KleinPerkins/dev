"""Canonical v2 repository profiles and semantic artifact previews."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .canonical import canonical_json, digest_file_manifest, digest_ref
from .transactions import (
    MutationAction,
    MutationRequest,
    ObservedInput,
    TransactionPreview,
    apply_transaction,
    confirmation_for,
    preview_transaction,
)
from .validators import (
    ApprovedDesignArtifact,
    active_approved_design_artifacts,
    canonical_design_contract,
    is_external_asset_record,
    is_external_asset_observation,
    read_repository_config,
    require_ready_defect,
    require_valid,
    validate_design_coverage,
    validate_external_asset_provenance,
    validate_relation_record,
)


KINDS = {
    "project",
    "prd",
    "spec",
    "plan",
    "uxr",
    "design",
    "asset",
    "prototype",
    "sketch",
    "spike",
    "release",
    "defect",
}
TYPE_PREFIX = {
    "project": "PROJECT",
    "prd": "PRD",
    "spec": "SPEC",
    "plan": "PLAN",
    "uxr": "UXR",
    "design": "DESIGN",
    "asset": "ASSET",
    "prototype": "PROTO",
    "sketch": "SKETCH",
    "spike": "SPIKE",
    "release": "REL",
    "defect": "DEF",
}
_REQUIREMENT_ID = re.compile(r"REQ-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
_DESIGN_ID = re.compile(
    r"DESIGN-(?P<repository_key>[0-9a-f]{8}-[0-9a-f]{4}-[45][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})-"
    r"(?P<artifact_uuid>[0-9a-f]{8}-[0-9a-f]{4}-[45][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12})"
)


@dataclass(frozen=True)
class ArtifactPreview:
    transaction: TransactionPreview
    artifact_id: str
    artifact_path: str
    repository_key: str


def _uuid4_from_seed(seed: str) -> str:
    raw = bytearray(hashlib.sha256(seed.encode("utf-8")).digest()[:16])
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(raw)))


def _bindings(repo: Path) -> dict[str, Any]:
    root = repo / "_ops" / "doc-warden"
    schemas = list((root / "schemas" / "v2").glob("*.schema.json"))
    digest = "sha256:" + "0" * 64
    policy = root / "POLICY.md"
    triggers = root / "triggers.v2.json"
    approved_plan = repo / "_ops/plans/doc-warden-execution-plan-v2.md"
    # Fresh-history source adoption does not replay the predecessor plan approval.
    successor_source = (repo / "_ops/policy/dev-successor.json").is_file()
    return {
        "policy_version": "2.0.0",
        "policy_digest": digest_ref(policy.read_bytes())
        if policy.is_file()
        else digest,
        "schema_digest": digest_file_manifest(schemas) if schemas else digest,
        "trigger_catalog_digest": digest_ref(triggers.read_bytes())
        if triggers.is_file()
        else digest,
        "template_digests": {},
        "gsd_pin_digest": digest_ref(
            (root / "runtime" / "gsd-core" / "gsd-core-pin.json").read_bytes()
        )
        if (root / "runtime" / "gsd-core" / "gsd-core-pin.json").is_file()
        else digest,
        "approved_plan_digest": digest_ref(approved_plan.read_bytes())
        if approved_plan.is_file() and not successor_source
        else digest,
    }


def repository_profile(
    repo: Path,
    repository_key: str,
    *,
    github_repository_id: int | None = None,
    binding_root: Path | None = None,
) -> dict[str, Any]:
    source = binding_root if binding_root is not None else repo
    root = source / "_ops" / "doc-warden" / "runtime" / "gsd-core"
    fallback = "sha256:" + "0" * 64
    return {
        "schema": "doc-warden/config/v2",
        "schema_version": 2,
        "repository_key": repository_key,
        "github_repository_id": github_repository_id,
        "enabled": True,
        "dynamic_defaults": {"rigor": "auto"},
        "legacy_roots": ["_ops/plans", "_ops/adr"],
        "gsd_pin_digest": digest_ref((root / "gsd-core-pin.json").read_bytes())
        if (root / "gsd-core-pin.json").is_file()
        else fallback,
        "gsd_interface_digest": digest_ref((root / "runtime-interface.v1.json").read_bytes())
        if (root / "runtime-interface.v1.json").is_file()
        else fallback,
        "maintenance": {"status": "current", "last_checked_revision": None},
    }


def _artifact_bytes(metadata: dict[str, Any], body: str) -> bytes:
    return b"---\n" + canonical_json(metadata) + b"---\n" + body.rstrip().encode("utf-8") + b"\n"


def _canonical_requirement_ids(
    inputs: dict[str, Any],
    field: str,
) -> tuple[str, ...]:
    value = inputs.get(field, [])
    if not isinstance(value, list):
        raise ValueError(f"{field}_must_be_array")
    canonical: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or _REQUIREMENT_ID.fullmatch(item) is None:
            raise ValueError(f"{field}_item_invalid")
        if item not in seen:
            seen.add(item)
            canonical.append(item)
    return tuple(canonical)


def _canonical_nonimplemented_requirement_ids(
    inputs: dict[str, Any],
) -> tuple[str, ...]:
    field = "nonimplemented_requirements"
    if field not in inputs:
        return ()
    value = inputs[field]
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = list(value)
    else:
        raise ValueError(f"{field}_must_be_array_or_object")
    return _canonical_requirement_ids({field: items}, field)


def _canonical_plan_assumptions(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    value = inputs.get("assumptions", [])
    if not isinstance(value, list):
        raise ValueError("plan_assumptions_must_be_array")
    from .dependencies import PlanAssumption

    assumptions = [PlanAssumption.from_record(item) for item in value]
    for item in assumptions:
        if item.path is not None:
            path = Path(item.path)
            if (
                path.is_absolute()
                or ".." in path.parts
                or path.as_posix() != item.path
            ):
                raise ValueError("plan_assumption_path_invalid")
        if (
            item.version is None
            or item.digest is None
            or item.revision is None
            or (
                item.kind in {"code", "schema"}
                and item.path is None
            )
            or (
                item.target_kind == "external_asset"
                and item.provider_revision is None
            )
        ):
            raise ValueError("plan_assumption_binding_incomplete")
    identifiers = [item.id for item in assumptions]
    targets = [(item.kind, item.target_id) for item in assumptions]
    if len(identifiers) != len(set(identifiers)) or len(targets) != len(set(targets)):
        raise ValueError("plan_assumptions_duplicate")
    return [
        item.to_record()
        for item in sorted(
            assumptions,
            key=lambda item: (item.kind, item.target_id, item.id),
        )
    ]


def _missing_requirement_coverage(inputs: dict[str, Any]) -> list[str]:
    required = set(_canonical_requirement_ids(inputs, "prd_requirements"))
    implemented = set(
        _canonical_requirement_ids(inputs, "implemented_requirements")
    )
    nonimplemented = set(_canonical_nonimplemented_requirement_ids(inputs))
    if not required:
        return []
    return sorted(required - implemented - nonimplemented)


def _canonical_design_version(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("design_version_invalid")
    if isinstance(value, int):
        version = value
    elif isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value):
        try:
            version = int(value)
        except ValueError as exc:
            raise ValueError("design_version_invalid") from exc
    else:
        raise ValueError("design_version_invalid")
    if version < 1:
        raise ValueError("design_version_invalid")
    return version


def _canonical_design_id(value: object, error_code: str) -> str:
    if not isinstance(value, str) or _DESIGN_ID.fullmatch(value) is None:
        raise ValueError(error_code)
    return value


def _canonical_design_ids(record: dict[str, Any]) -> tuple[str, ...]:
    value = record.get("design_ids", [])
    if not isinstance(value, list):
        raise ValueError("design_ids_must_be_array")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        design_id = _canonical_design_id(item, "design_ids_item_invalid")
        if design_id not in seen:
            seen.add(design_id)
            normalized.append(design_id)
    return tuple(normalized)


def _design_versions(record: dict[str, Any]) -> dict[str, int]:
    versions = record.get("design_versions")
    if versions is None:
        return {}
    if not isinstance(versions, dict):
        raise ValueError("design_versions_must_be_object")
    normalized: dict[str, int] = {}
    for design_id, version in versions.items():
        canonical_id = _canonical_design_id(
            design_id,
            "design_version_id_invalid",
        )
        normalized[canonical_id] = _canonical_design_version(version)
    return normalized


def _canonical_plan_design_bindings(
    plan: dict[str, Any],
) -> tuple[tuple[str, ...], dict[str, int]]:
    design_ids = _canonical_design_ids(plan)
    design_versions = _design_versions(plan)
    if set(design_ids) != set(design_versions):
        raise ValueError("plan_design_binding_incomplete")
    return design_ids, design_versions


def validate_plan_design_bindings(
    plan: dict[str, Any],
    active_designs: dict[str, dict[str, Any]],
) -> list[str]:
    stale: list[str] = []
    design_ids, expected_versions = _canonical_plan_design_bindings(plan)
    for design_id in design_ids:
        active = active_designs.get(design_id)
        if (
            not isinstance(active, dict)
            or "version" not in active
        ):
            stale.append(design_id)
            continue
        active_version = _canonical_design_version(active["version"])
        if (
            active.get("lifecycle") != "approved"
            or not isinstance(active.get("approval"), dict)
            or not active["approval"]
            or active_version != expected_versions[design_id]
        ):
            stale.append(design_id)
    return stale


def _canonical_ui_visual(inputs: dict[str, Any]) -> bool:
    """Canonical ``ui_visual`` contract for the M2 drafting path.

    Omitted means ``False``. An explicit value must be a genuine JSON/Python
    boolean; strings such as ``"false"``/``"0"``, numbers, ``null``, and
    containers are rejected deterministically rather than coerced through
    ``bool()`` truthiness. ``bool`` is the only accepted type (note ``0``/``1``
    are ``int``, not ``bool``, so they are refused).
    """
    if "ui_visual" not in inputs:
        return False
    value = inputs["ui_visual"]
    if not isinstance(value, bool):
        raise ValueError("ui_visual_must_be_boolean")
    return value


def _validate_m2_inputs(kind: str, inputs: dict[str, Any]) -> None:
    if kind == "spec":
        missing = _missing_requirement_coverage(inputs)
        if missing:
            raise ValueError("requirement_coverage_incomplete")
    if kind == "plan" and _canonical_ui_visual(inputs):
        if not isinstance(inputs.get("uxr_id"), str) or not inputs["uxr_id"]:
            raise ValueError("ui_plan_requires_uxr_and_approved_design")


def _provenance_for(
    kind: str,
    inputs: dict[str, Any],
    *,
    repo: Path,
    lifecycle: str,
    repository_profile_action: MutationAction | None = None,
) -> list[dict[str, Any]]:
    supplied_external_asset = None
    if "external_asset" in inputs:
        candidate = inputs["external_asset"]
        if not isinstance(candidate, dict):
            raise ValueError("external_asset_must_be_object")
        supplied_external_asset = candidate

    supplied: list[dict[str, Any]] = []
    if "provenance" in inputs:
        candidate_provenance = inputs["provenance"]
        if not isinstance(candidate_provenance, list):
            raise ValueError("provenance_must_be_list")
        for record in candidate_provenance:
            if not isinstance(record, dict):
                raise ValueError("provenance_items_must_be_objects")
            if is_external_asset_observation(record):
                raise ValueError(
                    "external_asset_observation_requires_explicit_input"
                )
            supplied.append(record)

    observations: list[dict[str, Any]] = []
    if "external_asset_observations" in inputs:
        candidate_observations = inputs["external_asset_observations"]
        if not isinstance(candidate_observations, list):
            raise ValueError("external_asset_observations_must_be_list")
        for observation in candidate_observations:
            if not isinstance(observation, dict):
                raise ValueError("external_asset_observation_invalid")
            try:
                require_valid("external-asset-observation", observation)
            except ValueError as exc:
                raise ValueError("external_asset_observation_invalid") from exc
            observations.append(observation)

    generated: list[dict[str, Any]] = []
    if kind == "prd" and inputs.get("requirements"):
        generated.append({"requirements": list(inputs["requirements"])})
    if supplied_external_asset is not None:
        generated.append(supplied_external_asset)
    if inputs.get("release_evidence"):
        generated.append({"release_evidence": inputs["release_evidence"]})

    # Generated records keep their historical order; additional caller records follow
    # in caller order. The first exact-equal record wins.
    provenance: list[dict[str, Any]] = []
    for record in [*generated, *supplied]:
        if record not in provenance:
            provenance.append(record)

    provenance.extend(observations)
    accepted_external_assets = validate_external_asset_provenance(
        provenance,
        lifecycle=lifecycle,
        repo=repo,
        repository_profile_action=repository_profile_action,
    )
    if (
        supplied_external_asset is not None
        and supplied_external_asset not in provenance
    ):
        raise ValueError("external_asset_provenance_mismatch")
    if supplied_external_asset is not None and any(
        is_external_asset_record(record) and record != supplied_external_asset
        for record in supplied
    ):
        raise ValueError("external_asset_provenance_mismatch")
    if kind == "asset" and accepted_external_assets == 0:
        raise ValueError("asset_external_asset_required")
    return provenance


def _design_artifact_body(
    kind: str,
    inputs: dict[str, Any],
    *,
    lifecycle: str,
    approval: object,
) -> str:
    if kind != "design" or "design" not in inputs:
        if kind == "design" and lifecycle == "approved":
            coverage = validate_design_coverage(
                {"lifecycle": lifecycle, "approval": approval}
            )
            raise ValueError(
                "design_coverage_blocked:"
                + ",".join(f"{issue.path}:{issue.code}" for issue in coverage)
            )
        return str(inputs.get("body", f"# {inputs.get('title', kind.title())}"))

    candidate = inputs["design"]
    if isinstance(candidate, dict) and (
        ("lifecycle" in candidate and candidate["lifecycle"] != lifecycle)
        or ("approval" in candidate and candidate["approval"] != approval)
    ):
        raise ValueError("design_authority_mismatch")
    if lifecycle == "approved":
        complete = (
            {**candidate, "lifecycle": lifecycle, "approval": approval}
            if isinstance(candidate, dict)
            else candidate
        )
        coverage = validate_design_coverage(complete)
        if coverage:
            raise ValueError(
                "design_coverage_blocked:"
                + ",".join(f"{issue.path}:{issue.code}" for issue in coverage)
            )
    contract = canonical_design_contract(
        candidate,
        lifecycle=lifecycle,
        approval=approval,
    )
    return canonical_json(contract).decode("utf-8")


def draft_artifact(
    kind: str,
    inputs: dict[str, Any],
    *,
    repo: Path,
    operation_id: str | None = None,
    repository_key_override: str | None = None,
    binding_root: Path | None = None,
) -> ArtifactPreview:
    if kind not in KINDS:
        raise ValueError("unsupported artifact kind")
    if kind == "defect":
        raise ValueError("use_create_defect")
    if kind == "spec" and not inputs.get("approved_prd"):
        raise ValueError("approved_prd_required")
    if (
        kind == "plan"
        and not inputs.get("approved_prd")
        and isinstance(inputs.get("defect_id"), str)
        and inputs["defect_id"]
        and _canonical_ui_visual(inputs)
    ):
        raise ValueError("defect_scope_promotion_required:ui_visual")
    _validate_m2_inputs(kind, inputs)
    repo = repo.resolve(strict=True)
    binding_source = (
        binding_root.resolve(strict=True)
        if binding_root is not None
        else repo
    )
    persisted = read_repository_config(repo)
    defect_authority = None
    if kind == "plan" and not inputs.get("approved_prd"):
        defect_id = inputs.get("defect_id")
        if not isinstance(defect_id, str) or not defect_id:
            raise ValueError("approved_prd_required")
        defect_authority = require_ready_defect(repo, defect_id)
    lifecycle = str(inputs.get("lifecycle", "draft"))
    approved = lifecycle == "approved"
    approval = inputs.get("approval") if approved else None
    if approved and not isinstance(approval, dict):
        raise ValueError("approval_record_required")
    design_ids: tuple[str, ...] = ()
    design_versions: dict[str, int] | None = None
    design_digests: dict[str, str] = {}
    design_authorities: dict[str, ApprovedDesignArtifact] = {}
    design_authority: dict[str, Any] | None = None
    if kind == "plan":
        design_ids, design_versions = _canonical_plan_design_bindings(inputs)
        ui_visual = _canonical_ui_visual(inputs)
        if ui_visual and not design_ids:
            raise ValueError("ui_plan_requires_active_design_binding")
        if design_ids:
            if persisted is None:
                raise ValueError("plan_design_binding_stale")
            active_designs = active_approved_design_artifacts(
                repo,
                persisted["repository_key"],
            )
            if validate_plan_design_bindings(
                {
                    "design_ids": list(design_ids),
                    "design_versions": design_versions,
                },
                {
                    design_id: authority.metadata
                    for design_id, authority in active_designs.items()
                },
            ):
                raise ValueError("plan_design_binding_stale")
            design_authorities = {
                design_id: active_designs[design_id]
                for design_id in design_ids
            }
            design_digests = {
                design_id: design_authorities[design_id].digest
                for design_id in design_ids
            }
            design_authority = {
                "design_ids": list(design_ids),
                "design_versions": design_versions,
                "design_digests": design_digests,
            }
        if ui_visual and "design" in inputs:
            if len(design_ids) != 1:
                raise ValueError("inline_design_mismatch")
            authority = design_authorities[design_ids[0]]
            try:
                inline_contract = canonical_design_contract(
                    inputs["design"],
                    lifecycle="approved",
                    approval=authority.metadata["approval"],
                    error_code="inline_design_mismatch",
                )
            except ValueError as exc:
                raise ValueError("inline_design_mismatch") from exc
            if canonical_json(inline_contract) != canonical_json(
                authority.contract
            ):
                raise ValueError("inline_design_mismatch")
    operation = operation_id or str(uuid.uuid4())
    uuid.UUID(operation)
    if repository_key_override is not None:
        uuid.UUID(repository_key_override)
    if (
        persisted is not None
        and repository_key_override is not None
        and persisted["repository_key"] != repository_key_override
    ):
        raise ValueError("repository_key_mismatch")
    repository_key = (
        persisted["repository_key"]
        if persisted
        else (
            repository_key_override
            or _uuid4_from_seed(f"{operation}:repository")
        )
    )
    repository_profile_action = None
    if persisted is None:
        profile = repository_profile(
            repo,
            repository_key,
            binding_root=binding_source,
        )
        require_valid("doc-warden-config", profile)
        if profile["repository_key"] != repository_key:
            raise ValueError("repository_profile_action_invalid")
        repository_profile_action = MutationAction(
            ".planning/doc-warden.json",
            canonical_json(profile),
            "create",
        )
    artifact_uuid = str(uuid.uuid5(uuid.UUID(operation), kind))
    artifact_id = f"{TYPE_PREFIX[kind]}-{repository_key}-{artifact_uuid}"
    version = int(inputs.get("version", 1))
    artifact_body = _design_artifact_body(
        kind,
        inputs,
        lifecycle=lifecycle,
        approval=approval,
    )
    metadata = {
        "schema": "doc-warden/artifact/v2",
        "id": artifact_id,
        "type": kind,
        "version": version,
        "repository_key": repository_key,
        "github_repository_id": persisted["github_repository_id"] if persisted else None,
        "authority": "semantic",
        "mutability": "frozen_after_approval",
        "lifecycle": lifecycle,
        "supersedes": inputs.get("supersedes"),
        "relations": inputs.get("relations", []),
        "provenance": _provenance_for(
            kind,
            inputs,
            repo=repo,
            lifecycle=lifecycle,
            repository_profile_action=repository_profile_action,
        ),
        "approval": approval,
    }
    if defect_authority is not None:
        defect_binding = {
            "defect_id": defect_authority.record["id"],
            "record_version": defect_authority.record["record_version"],
            "event_id": defect_authority.record["history_head"]["event_id"],
            "defect_digest": defect_authority.digest,
        }
        metadata["provenance"].append({"ready_defect": defect_binding})
    require_valid("artifact", metadata)
    for relation in metadata["relations"]:
        validate_relation_record(relation)
        if relation["source_id"] != artifact_id:
            raise ValueError("artifact_relation_source_mismatch")
    filename = f"{artifact_id}-v{version}.md"
    artifact_path = f".planning/artifacts/{filename}"
    artifact_content = _artifact_bytes(
        metadata,
        artifact_body,
    )
    actions: list[MutationAction] = []
    if repository_profile_action is not None:
        actions.append(repository_profile_action)
    actions.append(
        MutationAction(
            artifact_path,
            artifact_content,
            "create",
        )
    )
    if kind == "plan":
        assumptions = _canonical_plan_assumptions(inputs)
        supplied_task_ids = inputs.get("task_ids", [])
        if not isinstance(supplied_task_ids, list) or not all(
            isinstance(item, str) and item
            for item in supplied_task_ids
        ):
            raise ValueError("plan_task_ids_invalid")
        task_ids = sorted(
            set(supplied_task_ids)
            | {
                task_id
                for assumption in assumptions
                for task_id in assumption["task_ids"]
            }
        )
        plan_requirement_ids = sorted(
            set(_canonical_requirement_ids(inputs, "requirement_ids"))
            | {
                requirement_id
                for assumption in assumptions
                for requirement_id in assumption["requirement_ids"]
            }
        )
        sidecar = {
            "schema": "doc-warden/plan-governance-sidecar/v2",
            "artifact_id": artifact_id,
            "artifact_version": version,
            "canonical_plan_digest": digest_ref(artifact_content),
            "requirement_ids": plan_requirement_ids,
            "design_ids": list(design_ids),
            "design_versions": design_versions,
            "design_digests": design_digests,
            "task_ids": task_ids,
            "assumptions": assumptions,
            "accepted": approved,
        }
        require_valid("plan-governance-sidecar", sidecar)
        actions.append(
            MutationAction(
                f".planning/artifacts/{artifact_id}-v{version}.governance.json",
                canonical_json(sidecar),
                "create",
            )
        )
    bindings = _bindings(binding_source)
    observed_input_rows: list[ObservedInput] = []
    if design_authority is not None:
        bindings["design_authority"] = design_authority
        observed_input_rows.extend(
            ObservedInput(
                path=str(design_authorities[design_id].path),
                digest=design_digests[design_id],
            )
            for design_id in design_ids
        )
    if defect_authority is not None:
        bindings["defect_authority"] = {
            "defect_id": defect_authority.record["id"],
            "record_version": defect_authority.record["record_version"],
            "event_id": defect_authority.record["history_head"]["event_id"],
            "defect_digest": defect_authority.digest,
        }
        observed_input_rows.append(
            ObservedInput(
                path=str(defect_authority.path),
                digest=defect_authority.digest,
            )
        )
    transaction = preview_transaction(
        MutationRequest(
            repo=repo,
            repository_key=repository_key,
            github_repository_id=persisted["github_repository_id"] if persisted else None,
            transition="creation_snapshot" if not approved else "accepted_freeze",
            actions=tuple(actions),
            bindings=bindings,
            operation_id=operation,
            observed_inputs=tuple(observed_input_rows),
            require_write_enabled=True,
        )
    )
    return ArtifactPreview(transaction, artifact_id, artifact_path, repository_key)


def consent_for(
    preview: TransactionPreview, consequence_class: str = "semantic"
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    envelope = {
        "schema": "doc-warden/consent-envelope/v1",
        "operation_id": preview.operation_id,
        "repository_key": preview.repository_key,
        "canonical_root": preview.canonical_root,
        "source_revision": preview.source_revision,
        "action_digest": preview.action_digest,
        "consequence_class": consequence_class,
        "nonce": str(uuid.uuid4()),
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=10)).isoformat(),
        "choice": "apply",
    }
    require_valid("consent-envelope", envelope)
    return envelope


def apply_preview(
    preview: ArtifactPreview | TransactionPreview, consent: dict[str, Any] | None
) -> dict[str, Any]:
    transaction = preview.transaction if isinstance(preview, ArtifactPreview) else preview
    validate_consent(
        consent,
        operation_id=transaction.operation_id,
        repository_key=transaction.repository_key,
        canonical_root=transaction.canonical_root,
        source_revision=transaction.source_revision,
        action_digest=transaction.action_digest,
    )
    return apply_transaction(transaction, confirmation_for(transaction))


def validate_consent(
    consent: dict[str, Any] | None,
    *,
    operation_id: str,
    repository_key: str,
    canonical_root: str,
    source_revision: str,
    action_digest: str,
    consequence_class: str | None = None,
) -> None:
    if consent is None:
        raise ValueError("fresh_exact_consent_required")
    require_valid("consent-envelope", consent)
    expected = {
        "operation_id": operation_id,
        "repository_key": repository_key,
        "canonical_root": canonical_root,
        "source_revision": source_revision,
        "action_digest": action_digest,
        "choice": "apply",
    }
    if consequence_class is not None:
        expected["consequence_class"] = consequence_class
    if any(consent.get(key) != value for key, value in expected.items()):
        raise ValueError("fresh_exact_consent_required")
    expires = datetime.fromisoformat(str(consent["expires_at"]))
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError("fresh_exact_consent_required")


def preview_json(preview: ArtifactPreview) -> dict[str, Any]:
    transaction = preview.transaction
    return {
        "schema": "doc-warden/artifact-preview/v2",
        "operation_id": transaction.operation_id,
        "action_digest": transaction.action_digest,
        "source_revision": transaction.source_revision,
        "canonical_root": transaction.canonical_root,
        "repository_key": preview.repository_key,
        "artifact_id": preview.artifact_id,
        "artifact_path": preview.artifact_path,
        "actions": [
            {"kind": action.kind, "path": action.path, "content_digest": transaction.postimages[action.path]}
            for action in transaction.actions
        ],
    }
