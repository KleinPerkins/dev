"""Current owner read-only lock/control closure; explicit private I/O bindings.

Pure definitions retain exact owner source. validate_artifact_bytes writes only
recipe/lock inputs inside the caller's fixed private temporary-directory adapter;
the caller supplies a closed qualified compiler process. No network, original
repository, lifecycle writer, gh command or global filesystem root is imported.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
from types import FunctionType
import hashlib
import json
import os
import re

tempfile=None
def _run_checked(*args,**kwargs):
    raise RuntimeError('private qualified compiler binding required')

OWNER_REF='53158e73973d59b111ca1f304b67b995dbba65ea'
OWNER_PROFILE_BLOB='35587bb4afc9b4c75b6bc1c5dbce6f172991363a'
OWNER_FUNCTIONS=('_assert_compiler', '_git_blob_sha', '_json_bytes', '_require_current_recipe_binding', '_sha256_bytes', 'expected_profile_image', 'lock_metadata_errors', 'validate_artifact_bytes', 'validate_live_ruleset_identity', 'validate_managed_ruleset_listing')

MERGE_SAFETY_NAME = "kleinperkins-merge-safety"

LOCK = ".github/pr-automation.lock.json"

LOCK_SCHEMA = "pr-automation-lock/v2"

LOCK_CONTRACT_VERSION = 1

LOCK_CATALOG_ID = "pr-automation-execution-catalog/v1"

LOCK_COVERED_DIGEST_FIELDS = (
    "catalog_digest",
    "profile_digest",
    "image_digest",
    "recipe_digest",
    "assignment_digest",
)

class ControlPlaneError(RuntimeError):
    """A closed control-plane request failed before any mutation."""

def validate_live_ruleset_identity(
    ruleset: Any,
    *,
    expected_ruleset_id: int,
    expected_repo: str,
) -> None:
    if (
        not isinstance(expected_ruleset_id, int)
        or isinstance(expected_ruleset_id, bool)
        or expected_ruleset_id < 1
    ):
        raise ControlPlaneError(f"{expected_repo} has no expected current ruleset id")
    if not isinstance(ruleset, dict):
        raise ControlPlaneError(
            f"{expected_repo} expected ruleset id {expected_ruleset_id} is unreachable"
        )
    identity = {
        "id": expected_ruleset_id,
        "name": MERGE_SAFETY_NAME,
        "target": "branch",
        "enforcement": "active",
        "source_type": "Repository",
        "source": expected_repo,
    }
    observed = {key: ruleset.get(key) for key in identity}
    if observed != identity:
        raise ControlPlaneError(
            f"{expected_repo} ruleset identity changed: expected={identity} observed={observed}"
        )

def validate_managed_ruleset_listing(
    listed: Any,
    *,
    expected_ruleset_id: int,
    expected_repo: str,
) -> None:
    if not isinstance(listed, list):
        raise ControlPlaneError(f"{expected_repo} managed ruleset metadata is unreachable")
    matching = [
        item
        for item in listed
        if isinstance(item, dict) and item.get("name") == MERGE_SAFETY_NAME
    ]
    expected = {
        "id": expected_ruleset_id,
        "name": MERGE_SAFETY_NAME,
        "target": "branch",
        "enforcement": "active",
    }
    if len(matching) != 1 or {key: matching[0].get(key) for key in expected} != expected:
        raise ControlPlaneError(
            f"{expected_repo} must have exactly one active {MERGE_SAFETY_NAME} managed "
            f"ruleset with central id {expected_ruleset_id}; observed={matching}"
        )

def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"

def _git_blob_sha(value: bytes) -> str:
    header = f"blob {len(value)}\0".encode()
    return hashlib.sha1(header + value, usedforsecurity=False).hexdigest()

def _json_bytes(value: bytes, source: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControlPlaneError(f"{source} is not valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ControlPlaneError(f"{source} root must be an object")
    return decoded

def lock_metadata_errors(
    lock: dict[str, Any],
    controller: dict[str, Any],
    *,
    repo: str,
    profile_id: str,
    profile_digest: str,
) -> list[str]:
    """Return deterministic v2/epoch/direct-authority mismatches before Rust recompilation."""
    errors: list[str] = []
    release = controller.get("release", {})
    configured_epoch = release.get("lock_contract_version")
    if configured_epoch != LOCK_CONTRACT_VERSION:
        errors.append(
            "controller lock_contract_version differs from the supported epoch "
            f"{LOCK_CONTRACT_VERSION}: {configured_epoch!r}"
        )
    if lock.get("schema_version") != LOCK_SCHEMA:
        errors.append(
            f"schema_version must be {LOCK_SCHEMA!r}, got {lock.get('schema_version')!r}"
        )
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", str(lock.get("lock_digest", ""))):
        errors.append("lock_digest is malformed")
    payload = lock.get("payload")
    if not isinstance(payload, dict):
        return [*errors, "payload must be an object"]
    if "controller_release" in payload:
        errors.append("payload.controller_release is forbidden by the v2 lock contract")

    expected_image = expected_profile_image(controller, profile_id)
    expected = {
        "repository_id": repo.rsplit("/", 1)[-1],
        "activation_generation": release.get("activation_generation"),
        "lock_contract_version": configured_epoch,
        "catalog_id": LOCK_CATALOG_ID,
        "profile_id": profile_id,
        "profile_digest": profile_digest,
        "image_digest": expected_image,
    }
    for field, expected_value in expected.items():
        if payload.get(field) != expected_value:
            errors.append(
                f"{field} does not match current authority: "
                f"{payload.get(field)!r} != {expected_value!r}"
            )
    for field in ("catalog_digest", "profile_digest", "recipe_digest", "assignment_digest"):
        if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", str(payload.get(field, ""))):
            errors.append(f"{field} is malformed")
    if not re.fullmatch(
        r"[^\s]+@sha256:[0-9a-fA-F]{64}",
        str(payload.get("image_digest", "")),
    ):
        errors.append("image_digest is malformed")
    return errors

def expected_profile_image(controller: dict[str, Any], profile_id: str) -> Any:
    images = controller.get("images", {})
    if not isinstance(images, dict):
        return None
    overrides = images.get("profile_overrides", {})
    if not isinstance(overrides, dict):
        return images.get("execution")
    return overrides.get(profile_id, images.get("execution"))

def _assert_compiler(
    compiler: Path,
    controller: dict[str, Any],
) -> None:
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        raise ControlPlaneError(f"lock-compiler is not an executable file: {compiler}")
    actual = _sha256_bytes(compiler.read_bytes())
    expected = controller.get("release", {}).get("lock_compiler_digest")
    if actual != expected:
        raise ControlPlaneError(
            f"lock-compiler digest mismatch: got {actual}, expected qualified {expected}"
        )

def validate_artifact_bytes(
    recipe_bytes: bytes,
    lock_bytes: bytes,
    compiler: Path,
    controller: dict[str, Any],
    *,
    repo: str,
    profile_id: str,
    profile_digest: str,
) -> dict[str, Any]:
    """Run the release-qualified Rust validator; Python cross-checks direct central authority."""
    _assert_compiler(compiler, controller)
    lock = _json_bytes(lock_bytes, LOCK)
    metadata_errors = lock_metadata_errors(
        lock,
        controller,
        repo=repo,
        profile_id=profile_id,
        profile_digest=profile_digest,
    )
    if metadata_errors:
        raise ControlPlaneError("lock currency metadata mismatch: " + "; ".join(metadata_errors))
    payload = lock.get("payload")
    assert isinstance(payload, dict)
    expected_repository_id = repo.rsplit("/", 1)[-1]
    expected_generation = controller.get("release", {}).get("activation_generation")
    recipe_base_sha = payload.get("recipe_base_sha")
    recipe_blob_sha = payload.get("recipe_blob_sha")
    if not isinstance(recipe_base_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", recipe_base_sha):
        raise ControlPlaneError("lock recipe_base_sha is malformed")
    if not isinstance(recipe_blob_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", recipe_blob_sha):
        raise ControlPlaneError("lock recipe_blob_sha is malformed")
    if _git_blob_sha(recipe_bytes) != recipe_blob_sha:
        raise ControlPlaneError("recipe bytes do not match the lock's pinned recipe_blob_sha")

    with tempfile.TemporaryDirectory(prefix="pr-automation-lock-validate-") as temporary:
        root = Path(temporary)
        recipe = root / "recipe.json"
        lock_path = root / "lock.json"
        recipe.write_bytes(recipe_bytes)
        lock_path.write_bytes(lock_bytes)
        result = _run_checked(
            [
                str(compiler),
                "validate",
                "--recipe",
                str(recipe),
                "--repository-id",
                expected_repository_id,
                "--activation-generation",
                str(expected_generation),
                "--profile-id",
                profile_id,
                "--recipe-base-sha",
                recipe_base_sha,
                "--recipe-blob-sha",
                recipe_blob_sha,
                "--lock",
                str(lock_path),
            ]
        )
    return {
        "validated": True,
        "schema_version": lock["schema_version"],
        "lock_contract_version": payload["lock_contract_version"],
        "lock_digest": lock.get("lock_digest"),
        "covered_digests": {
            field: payload[field] for field in LOCK_COVERED_DIGEST_FIELDS
        },
        "compiler_digest": controller["release"]["lock_compiler_digest"],
        "validator": result.stdout.decode("utf-8", errors="replace").strip(),
    }

def _require_current_recipe_binding(
    recipe_bytes: bytes,
    recipe_blob_sha: str,
    payload: dict[str, Any],
    *,
    source: str,
) -> None:
    pinned_blob = payload.get("recipe_blob_sha")
    observed_blob = _git_blob_sha(recipe_bytes)
    if (
        not isinstance(pinned_blob, str)
        or recipe_blob_sha != pinned_blob
        or observed_blob != pinned_blob
    ):
        raise ControlPlaneError(
            f"{source} current recipe does not match the lock's pinned recipe_blob_sha"
        )

def observation_contract(private_directories,qualified_process):
    if not hasattr(private_directories,'TemporaryDirectory') or not callable(qualified_process):
        raise ValueError('explicit private directory and qualified process bindings required')
    namespace=dict(globals());namespace['tempfile']=private_directories;namespace['_run_checked']=qualified_process
    for name in OWNER_FUNCTIONS:
        source=globals()[name]
        bound=FunctionType(source.__code__,namespace,name,source.__defaults__,source.__closure__)
        bound.__kwdefaults__=source.__kwdefaults__;bound.__annotations__=source.__annotations__;namespace[name]=bound
    return namespace
