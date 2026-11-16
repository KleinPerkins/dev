"""Deterministic import boundary for exact-pin GSD authoring results.

This module validates caller-supplied authoring bytes. It never invokes a GSD
workflow, implementation phase, cross-phase driver, SCM command, or scheduler.
"""

from __future__ import annotations

import fnmatch
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .artifacts import _bindings
from .canonical import canonical_json, contained_path, digest_ref, parse_json_object
from .dependencies import assert_plan_assumptions_current
from .transactions import (
    MutationAction,
    MutationRequest,
    ObservedInput,
    TransactionPreview,
    apply_transaction,
    confirmation_for,
    preview_transaction,
    directory_input_digest,
)
from .validators import active_approved_artifacts, read_repository_config


ALLOWED_OUTPUTS = (
    ".planning/PROJECT.md",
    ".planning/config.json",
    ".planning/REQUIREMENTS.md",
    ".planning/ROADMAP.md",
    ".planning/STATE.md",
    ".planning/phases/*/*-CONTEXT.md",
    ".planning/phases/*/*-UI-SPEC.md",
    ".planning/phases/*/*-PLAN.md",
    ".planning/phases/*/*-SKETCH.md",
    ".planning/phases/*/*-SPIKE.md",
    ".planning/phases/*/*-VALIDATION.md",
    ".planning/phases/*/*-VERIFICATION.md",
    ".planning/phases/*/*-UAT.md",
)
RESULT_FIELDS = {
    "source_revision",
    "pin_digest",
    "changed_file_digests",
    "checker_passed",
    "commands",
    "assumptions_changed",
}


@dataclass(frozen=True)
class AuthoringScope:
    repo: Path
    operation_id: str
    input_paths: tuple[str, ...] = ()
    frozen_paths: tuple[str, ...] = ()
    active_artifact_id: str | None = None
    active_plan_id: str | None = None
    binding_root: Path | None = None


@dataclass(frozen=True)
class AuthoringImportPreview:
    repo: Path
    canonical_root: str
    operation_id: str
    source_revision: str
    pin_digest: str
    interface_digest: str
    input_digests: dict[str, str]
    frozen_digests: dict[str, str]
    allowed_outputs: tuple[str, ...]
    post_validator: str
    disposition: str
    active_plan_id: str | None = None
    binding_root: str | None = None
    authority_bindings: dict[str, Any] | None = None
    profile_digest: str | None = None


@dataclass(frozen=True)
class AuthoringResult:
    source_revision: str
    pin_digest: str
    outputs: dict[str, bytes]
    checker_passed: bool
    commands: tuple[str, ...] = ()
    assumptions_changed: bool = False


@dataclass(frozen=True)
class ImportPlan:
    transaction: TransactionPreview
    changed_paths: tuple[str, ...]
    checker_passed: bool


BEGIN_PROJECT = "<!-- doc-warden:project-current:begin -->\n"
END_PROJECT = "<!-- doc-warden:project-current:end -->\n"
BEGIN_REQUIREMENTS = "<!-- doc-warden:requirements-current:begin -->\n"
END_REQUIREMENTS = "<!-- doc-warden:requirements-current:end -->\n"


def _head(repo: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("repository_head_unavailable") from exc


def _runtime_paths(repo: Path) -> tuple[Path, Path]:
    prefix = "_ops/doc-warden/runtime/gsd-core/"
    return (contained_path(repo, prefix + "gsd-core-pin.json"),
            contained_path(repo, prefix + "runtime-interface.v1.json"))


def _central_schema_directory(root: Path) -> Path:
    path = root
    for part in ("_ops", "doc-warden", "schemas", "v2"):
        path = path / part
        if path.is_symlink() or not path.is_dir():
            raise ValueError("authoring_authority_unavailable")
    return path


def _central_authority_bindings(root: Path) -> dict[str, Any]:
    required = ("_ops/doc-warden/POLICY.md", "_ops/doc-warden/triggers.v2.json",
                "_ops/plans/doc-warden-execution-plan-v2.md")
    for relative in required:
        if not contained_path(root, relative).is_file():
            raise ValueError("authoring_authority_unavailable")
    schemas = _central_schema_directory(root)
    paths = list(schemas.glob("*.schema.json"))
    if not paths:
        raise ValueError("authoring_authority_unavailable")
    for path in paths:
        if not contained_path(root, str(path.relative_to(root))).is_file():
            raise ValueError("authoring_authority_unavailable")
    bindings = _bindings(root)
    for name in ("policy_digest", "schema_digest", "trigger_catalog_digest",
                 "gsd_pin_digest", "approved_plan_digest"):
        if bindings[name] == "sha256:" + "0" * 64:
            raise ValueError("authoring_authority_unavailable")
    return bindings


def _central_profile(repo: Path, pin_digest: str, interface_digest: str) -> str:
    config = read_repository_config(repo)
    if config is None or not config["enabled"]:
        raise ValueError("v2_repository_profile_required")
    if (config["gsd_pin_digest"] != pin_digest
            or config["gsd_interface_digest"] != interface_digest):
        raise ValueError("authoring_profile_binding_mismatch")
    return digest_ref(contained_path(repo, ".planning/doc-warden.json").read_bytes())


def validate_runtime_binding(preview: AuthoringImportPreview) -> Path:
    """Recheck the prepared bytes; this is not authority to invoke or apply work."""
    authority = Path(preview.binding_root).resolve(strict=True) if preview.binding_root else preview.repo
    pin, interface = _runtime_paths(authority)
    try:
        if (digest_ref(pin.read_bytes()) != preview.pin_digest
                or digest_ref(interface.read_bytes()) != preview.interface_digest):
            raise ValueError("wrong_gsd_pin")
    except OSError as exc:
        raise ValueError("runtime_binding_unavailable") from exc
    if preview.binding_root is not None:
        if str(authority) != preview.binding_root:
            raise ValueError("authoring_authority_root_changed")
        if _central_authority_bindings(authority) != preview.authority_bindings:
            raise ValueError("authoring_authority_changed")
        if _central_profile(preview.repo, preview.pin_digest, preview.interface_digest) != preview.profile_digest:
            raise ValueError("authoring_profile_changed")
    return authority


def project_current_view(repo: Path) -> bytes:
    repo = repo.resolve(strict=True)
    rows = active_approved_artifacts(repo, "project")
    payload = {
        "schema": "doc-warden/project-current-view/v1",
        "source_revision": _head(repo),
        "projects": [
            {
                "artifact_id": metadata["id"],
                "version": metadata["version"],
                "digest": digest_ref(path.read_bytes()),
                "path": str(path.relative_to(repo)),
            }
            for path, metadata, _body in rows
        ],
    }
    body = "\n\n".join(body.strip() for _path, _metadata, body in rows)
    return (
        "# Project\n\n"
        + BEGIN_PROJECT
        + canonical_json(payload).decode("utf-8")
        + END_PROJECT
        + (body + "\n" if body else "")
    ).encode("utf-8")


def _requirement_rows(metadata: dict[str, Any], body: str) -> list[dict[str, Any]]:
    provenance = {"artifact_id": metadata["id"], "version": metadata["version"]}
    rows = []
    for item in metadata.get("provenance", []):
        if isinstance(item, dict) and isinstance(item.get("requirements"), list):
            for requirement in item["requirements"]:
                if isinstance(requirement, dict) and requirement.get("id"):
                    rows.append({**requirement, "source": provenance})
    if rows:
        return rows
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("REQ-"):
            rid, _, statement = stripped.partition(":")
            rows.append({"id": rid.strip(), "statement": statement.strip(), "source": provenance})
    return rows


def requirements_current_view(repo: Path) -> bytes:
    repo = repo.resolve(strict=True)
    rows = active_approved_artifacts(repo, "prd")
    requirements = []
    semantic_by_id: dict[bytes, bytes] = {}
    for path, metadata, body in rows:
        digest = digest_ref(path.read_bytes())
        for requirement in _requirement_rows(metadata, body):
            semantic = {
                key: value
                for key, value in requirement.items()
                if key != "source"
            }
            requirement_id = canonical_json(semantic["id"])
            canonical_semantic = canonical_json(semantic)
            previous = semantic_by_id.get(requirement_id)
            if previous is not None:
                if previous != canonical_semantic:
                    raise ValueError("requirement_projection_conflict")
                continue
            semantic_by_id[requirement_id] = canonical_semantic
            requirements.append(
                {
                    **semantic,
                    "source": {
                        **requirement["source"],
                        "digest": digest,
                        "path": str(path.relative_to(repo)),
                    },
                }
            )
    payload = {
        "schema": "doc-warden/requirements-current-view/v1",
        "source_revision": _head(repo),
        "requirements": requirements,
    }
    rendered = "\n".join(
        f"- {item['id']}: {item.get('statement', '')} "
        f"(source: {item['source']['artifact_id']} v{item['source']['version']})"
        for item in requirements
    )
    return (
        "# Requirements\n\n"
        + BEGIN_REQUIREMENTS
        + canonical_json(payload).decode("utf-8")
        + END_REQUIREMENTS
        + (rendered + "\n" if rendered else "")
    ).encode("utf-8")


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("unexpected_authoring_delta")
    return str(path)


def _matches_allowed(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def validate_authoring_result_envelope(raw: dict[str, Any]) -> None:
    if set(raw) != RESULT_FIELDS:
        raise ValueError("authoring_result_contract_invalid")
    source_revision = raw["source_revision"]
    pin_digest = raw["pin_digest"]
    changed = raw["changed_file_digests"]
    commands = raw["commands"]
    if (
        not isinstance(source_revision, str)
        or len(source_revision) != 40
        or any(character not in "0123456789abcdef" for character in source_revision)
        or not isinstance(pin_digest, str)
        or not pin_digest.startswith("sha256:")
        or len(pin_digest) != 71
        or not isinstance(changed, dict)
        or not changed
        or not isinstance(commands, list)
        or any(not isinstance(command, str) for command in commands)
        or commands
        or type(raw["checker_passed"]) is not bool
        or type(raw["assumptions_changed"]) is not bool
    ):
        raise ValueError("authoring_result_contract_invalid")
    for relative, expected_digest in changed.items():
        safe = _safe_relative(relative)
        if not _matches_allowed(safe, ALLOWED_OUTPUTS):
            raise ValueError("unexpected_authoring_delta")
        if (
            not isinstance(expected_digest, str)
            or not expected_digest.startswith("sha256:")
            or len(expected_digest) != 71
        ):
            raise ValueError("authoring_result_contract_invalid")


def authoring_result_from_envelope(repo: Path, raw: dict[str, Any]) -> AuthoringResult:
    validate_authoring_result_envelope(raw)
    outputs: dict[str, bytes] = {}
    root = repo.resolve(strict=True)
    for relative, expected_digest in raw["changed_file_digests"].items():
        safe = _safe_relative(relative)
        path = contained_path(root, safe)
        if not path.is_file():
            raise ValueError("authoring_result_digest_mismatch")
        content = path.read_bytes()
        if digest_ref(content) != expected_digest:
            raise ValueError("authoring_result_digest_mismatch")
        outputs[safe] = content
    return AuthoringResult(
        source_revision=raw["source_revision"],
        pin_digest=raw["pin_digest"],
        outputs=outputs,
        checker_passed=raw["checker_passed"],
        commands=tuple(raw["commands"]),
        assumptions_changed=raw["assumptions_changed"],
    )


def prepare_authoring_import(scope: AuthoringScope) -> AuthoringImportPreview:
    repo = scope.repo.resolve(strict=True)
    try:
        uuid.UUID(scope.operation_id)
    except (ValueError, TypeError) as exc:
        raise ValueError("authoring_operation_id_invalid") from exc
    if scope.binding_root is not None:
        config = read_repository_config(repo)
        if config is None or not config["enabled"]:
            raise ValueError("v2_repository_profile_required")
    authority = scope.binding_root.resolve(strict=True) if scope.binding_root is not None else repo
    pin_path, interface_path = _runtime_paths(authority)
    try:
        pin_bytes = pin_path.read_bytes()
        interface_bytes = interface_path.read_bytes()
    except OSError as exc:
        raise ValueError("runtime_binding_unavailable") from exc
    pin = parse_json_object(pin_bytes)
    interface = parse_json_object(interface_bytes)
    if (
        pin.get("version") != "1.11.0"
        or pin.get("git_commit") != "182f60b4c170785d96f1deb87fea8b108e9b985f"
        or interface.get("version") != pin.get("version")
        or interface.get("git_commit") != pin.get("git_commit")
        or interface.get("supported_scope") != "authoring_context_only"
    ):
        raise ValueError("wrong_gsd_pin")
    input_digests: dict[str, str] = {}
    for relative in scope.input_paths:
        safe = _safe_relative(relative)
        path = contained_path(repo, safe)
        if not path.is_file():
            raise ValueError("authoring_input_missing")
        input_digests[safe] = digest_ref(path.read_bytes())
    frozen_digests: dict[str, str] = {}
    for relative in scope.frozen_paths:
        safe = _safe_relative(relative)
        path = contained_path(repo, safe)
        if not path.is_file():
            raise ValueError("frozen_authority_missing")
        frozen_digests[safe] = digest_ref(path.read_bytes())
    return AuthoringImportPreview(
        repo=repo,
        canonical_root=str(repo),
        operation_id=scope.operation_id,
        source_revision=_head(repo),
        pin_digest=digest_ref(pin_bytes),
        interface_digest=digest_ref(interface_bytes),
        input_digests=input_digests,
        frozen_digests=frozen_digests,
        allowed_outputs=ALLOWED_OUTPUTS,
        post_validator="doc-warden validate-authoring",
        disposition="operator_invoke_required",
        active_plan_id=scope.active_plan_id,
        binding_root=str(authority) if scope.binding_root is not None else None,
        authority_bindings=_central_authority_bindings(authority) if scope.binding_root is not None else None,
        profile_digest=_central_profile(repo, digest_ref(pin_bytes), digest_ref(interface_bytes))
        if scope.binding_root is not None else None,
    )


def validate_authoring_result(
    preview: AuthoringImportPreview, result: AuthoringResult
) -> ImportPlan:
    if result.source_revision != preview.source_revision or _head(preview.repo) != preview.source_revision:
        raise ValueError("authoring_source_revision_changed")
    if result.pin_digest != preview.pin_digest:
        raise ValueError("wrong_gsd_pin")
    authority = validate_runtime_binding(preview)
    assert_plan_assumptions_current(preview.repo, preview.active_plan_id)
    if result.assumptions_changed:
        raise ValueError("plan_refinement_required")
    if result.commands:
        raise ValueError("prohibited_authoring_command")
    for relative, expected in preview.input_digests.items():
        path = contained_path(preview.repo, relative)
        if not path.is_file() or digest_ref(path.read_bytes()) != expected:
            raise ValueError("authoring_input_changed")
    actions: list[MutationAction] = []
    for relative, content in sorted(result.outputs.items()):
        safe = _safe_relative(relative)
        if not _matches_allowed(safe, preview.allowed_outputs):
            raise ValueError("unexpected_authoring_delta")
        if safe in preview.frozen_digests and digest_ref(content) != preview.frozen_digests[safe]:
            raise ValueError("contradictory_authority")
        actions.append(MutationAction(safe, content))
    for relative, expected in preview.frozen_digests.items():
        path = contained_path(preview.repo, relative)
        if not path.is_file() or digest_ref(path.read_bytes()) != expected:
            raise ValueError("contradictory_authority")
    if any(path.endswith("-PLAN.md") for path in result.outputs) and not result.checker_passed:
        raise ValueError("authoring_checker_failed")
    if not actions:
        raise ValueError("authoring_result_empty")
    config = read_repository_config(preview.repo)
    if config is None:
        raise ValueError("v2_repository_profile_required")
    observed: dict[str, ObservedInput] = {}
    def observe(path: Path, expected: str) -> None:
        value = ObservedInput(str(path), expected)
        if value.path in observed and observed[value.path] != value:
            raise ValueError("authoring_input_changed")
        observed[value.path] = value
    pin_path, interface_path = _runtime_paths(authority)
    observe(pin_path, preview.pin_digest)
    observe(interface_path, preview.interface_digest)
    for mapping in (preview.input_digests, preview.frozen_digests):
        for relative, expected in mapping.items():
            # Co-written inputs use transaction preimages/postimages so an exact
            # receipt replay remains valid after this operation changes them.
            if relative not in result.outputs:
                observe(contained_path(preview.repo, relative), expected)
    if preview.binding_root is not None:
        profile = contained_path(preview.repo, ".planning/doc-warden.json")
        observe(profile, preview.profile_digest)
        schema_dir = _central_schema_directory(authority)
        observe(schema_dir, directory_input_digest(schema_dir))
        relatives = ["_ops/doc-warden/POLICY.md", "_ops/doc-warden/triggers.v2.json",
                     "_ops/plans/doc-warden-execution-plan-v2.md"]
        relatives += [str(path.relative_to(authority)) for path in schema_dir.glob("*.schema.json")]
        for relative in relatives:
            path = contained_path(authority, relative)
            observe(path, digest_ref(path.read_bytes()))
        # Refuse visible drift during observed-input collection as well.
        validate_runtime_binding(preview)
    transaction = preview_transaction(
        MutationRequest(
            repo=preview.repo,
            repository_key=config["repository_key"],
            github_repository_id=config["github_repository_id"],
            transition="draft_update",
            actions=tuple(actions),
            bindings=preview.authority_bindings if preview.binding_root is not None else _bindings(preview.repo),
            operation_id=preview.operation_id,
            require_write_enabled=True,
            observed_inputs=tuple(observed.values()),
        )
    )
    return ImportPlan(
        transaction=transaction,
        changed_paths=tuple(action.path for action in transaction.actions),
        checker_passed=result.checker_passed,
    )


def apply_authoring_result(import_plan: ImportPlan) -> dict[str, Any]:
    return apply_transaction(
        import_plan.transaction, confirmation_for(import_plan.transaction)
    )


def verify_frozen_authorities(preview: AuthoringImportPreview) -> dict[str, Any]:
    mismatches = []
    for relative, expected in preview.frozen_digests.items():
        path = contained_path(preview.repo, relative)
        if not path.is_file() or digest_ref(path.read_bytes()) != expected:
            mismatches.append(relative)
    return {
        "schema": "doc-warden/authoring-verification/v1",
        "source_revision": _head(preview.repo),
        "status": "pass" if not mismatches else "blocked",
        "mismatches": mismatches,
    }
