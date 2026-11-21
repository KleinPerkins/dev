"""Bounded wrapper for the exact-pin GSD global Cursor installation."""

from __future__ import annotations

import json
import os
import subprocess
import base64
import fcntl
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .canonical import (
    atomic_write,
    canonical_json,
    contained_path,
    digest_ref,
    parse_json_object,
)
from .operation_store import operation_path, private_state_root
from .gsd_adapter import CENTRAL_REPOSITORY_ID, CENTRAL_REPOSITORY_KEY as CURRENT_REPOSITORY_KEY
from .runtime_host import read_destination_qualification
from .scm import observe_repository_identity
from .transactions import (
    MutationAction,
    MutationRequest,
    ObservedInput,
    TransactionPreview,
    preview_transaction,
)
from .validators import read_repository_config, require_valid

BLOCKING_EVENTS = {
    "beforeShellExecution",
    "beforeMCPExecution",
    "beforeReadFile",
}
UPSTREAM_RESIDUE_PATHS = (
    ".cursor/gsd-install-state.json",
    ".cursor/hooks/lib/isolation-deny-reason.js",
    ".cursor/hooks/lib/isolation-sentinel.js",
)
CENTRAL_REPOSITORY_KEY = "18c71d9a-d928-4d45-b048-4b063f14957f"
GSD_PACKAGE = "@opengsd/gsd-core"
GSD_VERSION = "1.11.0"
GSD_COMMIT = "182f60b4c170785d96f1deb87fea8b108e9b985f"
GSD_NPM_INTEGRITY = (
    "sha512-z1RLWsQshYViJIk94SB0x9/AYPykj5LIuLxwjS0s+WgaCBgVtTknCsVR3x4itrBeqmiUEvGiN6cO/bOay0zOiQ=="
)
GSD_UPSTREAM_REPOSITORY = "https://github.com/open-gsd/gsd-core"
GSD_UPSTREAM_TARBALL = (
    "https://registry.npmjs.org/@opengsd/gsd-core/-/gsd-core-1.11.0.tgz"
)
INSTALL_CONSEQUENCE = "live_runtime_install"
UNINSTALL_CONSEQUENCE = "live_runtime_uninstall"
QUALIFICATION_FIELDS = {
    "dependency_licenses",
    "digests",
    "git_commit",
    "license_review",
    "lifecycle_scripts",
    "npm_integrity",
    "package",
    "qualification",
    "qualified_at",
    "schema",
    "toolchain",
    "upstream",
    "version",
}
QUALIFICATION_DIGEST_PATHS = {
    "installer_sha256": "install.sh",
    "package_json_sha256": "package.json",
    "package_lock_sha256": "package-lock.json",
    "pin_sha256": "gsd-core-pin.json",
    "runtime_interface_sha256": "runtime-interface.v1.json",
}
QUALIFICATION_DIGEST_FIELDS = {
    *QUALIFICATION_DIGEST_PATHS,
    "verifier_sha256",
}
M1_QUALIFICATION = {
    "authoring_skill_allowlist_enforced": True,
    "bounded_shim_digest_doctor": "passed",
    "bounded_shims_enforced": True,
    "corrupted_release_repair": "passed",
    "corrupted_uninstaller_recovery": "passed",
    "cursor_command_allowlist_enforced": True,
    "cursor_home_discovery_path": "passed",
    "doctor": "passed",
    "excluded_agents_pruned": True,
    "installed_version_doctor": "passed",
    "isolated_home_apply": "passed",
    "leaf_command_allowlist": "passed",
    "manifest_identity_refusal": "passed",
    "network_required_for_apply": True,
    "preexisting_defaults_byte_restoration": "passed",
    "prior_release_upgrade_path": (
        "implemented; full next-pin fixture deferred to M6 upgrade qualification"
    ),
    "real_home_sentinels_unchanged": True,
    "repair_idempotence": "passed",
    "runtime_defaults_applied_and_rolled_back": True,
    "uninstall_rollback": "passed",
    "vendor_clone_touched": False,
}


@dataclass(frozen=True)
class LiveInstallOperation:
    repo: Path
    canonical_root: str
    repository_key: str
    github_repository_id: int | None
    operation_id: str
    action_digest: str
    source_revision: str
    home: Path
    data_home: Path
    runtime_pin_digest: str
    runtime_digests: dict[str, str]
    qualification_digest: str
    before_sentinels: dict[str, str]
    expires_at: str
    consequence: str = INSTALL_CONSEQUENCE


@dataclass(frozen=True)
class RuntimeQualification:
    qualification_digest: str
    runtime_digests: dict[str, str]
    path: Path
    basis: str


@dataclass(frozen=True)
class CanonicalStateRecord:
    path: Path
    raw: bytes
    value: dict[str, Any]
    digest: str


def validate_global_hooks(hooks: list[dict[str, Any]]) -> None:
    for hook in hooks:
        if hook.get("owner") != "doc-warden":
            continue
        if hook.get("event") in BLOCKING_EVENTS and hook.get("failClosed") is not False:
            raise ValueError("global_blocking_hook_must_fail_open")


def _runtime(repo: Path) -> Path:
    return repo.resolve(strict=True) / "_ops/doc-warden/runtime/gsd-core"


def _environment(home: Path, data_home: Path, *, allow_live_home: bool = False) -> dict[str, str]:
    environment = {**os.environ, "HOME": str(home), "XDG_DATA_HOME": str(data_home)}
    environment.pop("DOC_WARDEN_ALLOW_LIVE_HOME", None)
    if allow_live_home:
        environment["DOC_WARDEN_ALLOW_LIVE_HOME"] = "1"
    return environment


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        return int(value, 16) >= 0 and value == value.lower()
    except ValueError:
        return False


def _valid_dependency_licenses(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(item, dict)
            and set(item) == {"integrity", "license", "name", "optional", "version"}
            and all(
                isinstance(item[key], str)
                for key in ("integrity", "license", "name", "version")
            )
            and type(item["optional"]) is bool
            for item in value
        )
    )


def _read_regular_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("runtime_qualification_invalid")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError("runtime_qualification_invalid") from exc


def _read_canonical_state_record(
    path: Path,
    schema_name: str,
    *,
    missing_code: str,
    invalid_code: str,
    mismatch_code: str,
) -> CanonicalStateRecord:
    if path.is_symlink() or not path.is_file():
        raise ValueError(missing_code)
    try:
        raw = path.read_bytes()
        value = parse_json_object(raw)
        require_valid(schema_name, value)
        canonical = canonical_json(value)
    except (OSError, ValueError) as exc:
        raise ValueError(invalid_code) from exc
    if raw != canonical:
        raise ValueError(mismatch_code)
    return CanonicalStateRecord(
        path=path,
        raw=raw,
        value=value,
        digest=digest_ref(raw),
    )


def _validate_runtime_qualification(repo: Path) -> RuntimeQualification:
    runtime = _runtime(repo)
    qualification_path = (
        repo
        / "_ops/doc-warden/state/v2/runtime/gsd-core-v1.11.0-qualification.json"
    )
    try:
        qualification_bytes = _read_regular_file(qualification_path)
        value = parse_json_object(qualification_bytes)
        pin = parse_json_object(_read_regular_file(runtime / "gsd-core-pin.json"))
        digests = value["digests"]
        qualification = value["qualification"]
        lifecycle = value["lifecycle_scripts"]
        toolchain = value["toolchain"]
        upstream = value["upstream"]
        license_review = value["license_review"]
        qualified_at = datetime.fromisoformat(str(value["qualified_at"]))
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise ValueError("runtime_qualification_invalid") from exc
    if (
        set(value) != QUALIFICATION_FIELDS
        or value["schema"] != "doc-warden/gsd-runtime-qualification/v2"
        or value["package"] != GSD_PACKAGE
        or value["version"] != GSD_VERSION
        or value["git_commit"] != GSD_COMMIT
        or value["npm_integrity"] != GSD_NPM_INTEGRITY
        or not _valid_dependency_licenses(value["dependency_licenses"])
        or not any(
            item["name"] == GSD_PACKAGE
            and item["version"] == GSD_VERSION
            and item["integrity"] == GSD_NPM_INTEGRITY
            and item["license"] == "MIT"
            and item["optional"] is False
            for item in value["dependency_licenses"]
        )
        or not isinstance(digests, dict)
        or set(digests) != QUALIFICATION_DIGEST_FIELDS
        or not all(_is_sha256(item) for item in digests.values())
        or qualification != M1_QUALIFICATION
        or lifecycle
        != {
            "executed": False,
            "install_policy": "npm ci --ignore-scripts --omit=dev",
            "package_scripts_present": True,
        }
        or not isinstance(toolchain, dict)
        or set(toolchain) != {"node", "npm", "platform"}
        or not all(isinstance(item, str) and item for item in toolchain.values())
        or upstream
        != {
            "commit": f"{GSD_UPSTREAM_REPOSITORY}/commit/{GSD_COMMIT}",
            "license": f"{GSD_UPSTREAM_REPOSITORY}/blob/{GSD_COMMIT}/LICENSE",
            "repository": GSD_UPSTREAM_REPOSITORY,
            "tarball": GSD_UPSTREAM_TARBALL,
        }
        or not isinstance(license_review, dict)
        or set(license_review) != {"claude_agent_sdk", "gsd_core"}
        or not isinstance(license_review["claude_agent_sdk"], dict)
        or set(license_review["claude_agent_sdk"])
        != {"classification", "disposition", "license_file"}
        or not all(
            isinstance(item, str) and item
            for item in license_review["claude_agent_sdk"].values()
        )
        or not isinstance(license_review["gsd_core"], dict)
        or set(license_review["gsd_core"]) != {"classification", "disposition"}
        or not all(
            isinstance(item, str) and item
            for item in license_review["gsd_core"].values()
        )
        or qualified_at.tzinfo is None
        or qualified_at.utcoffset() != timedelta(0)
        or pin.get("schema") != "doc-warden/gsd-core-pin/v1"
        or pin.get("package") != GSD_PACKAGE
        or pin.get("version") != GSD_VERSION
        or pin.get("git_commit") != GSD_COMMIT
        or pin.get("npm_integrity") != GSD_NPM_INTEGRITY
        or not isinstance(pin.get("license"), dict)
        or pin["license"].get("spdx") != "MIT"
        or pin.get("upstream")
        != {
            "repository": GSD_UPSTREAM_REPOSITORY,
            "tarball": GSD_UPSTREAM_TARBALL,
        }
    ):
        raise ValueError("runtime_qualification_invalid")
    observed = {}
    try:
        observed = {
            name: digest_ref(_read_regular_file(runtime / relative))
            for name, relative in QUALIFICATION_DIGEST_PATHS.items()
        }
    except ValueError as exc:
        raise ValueError("runtime_qualification_digest_mismatch") from exc
    if any(
        observed[name] != f"sha256:{digests[name]}"
        for name in QUALIFICATION_DIGEST_PATHS
    ):
        raise ValueError("runtime_qualification_digest_mismatch")
    return RuntimeQualification(
        qualification_digest=digest_ref(qualification_bytes),
        runtime_digests=observed,
        path=qualification_path,
        basis="m1_t01_qualification",
    )


def _validated_runtime_files(
    repo: Path, expected_digests: dict[str, str]
) -> Path:
    runtime = _runtime(repo)
    try:
        observed = {
            name: digest_ref(_read_regular_file(runtime / relative))
            for name, relative in QUALIFICATION_DIGEST_PATHS.items()
        }
    except ValueError as exc:
        raise ValueError("operation_specification_mismatch") from exc
    if (
        set(expected_digests) != set(QUALIFICATION_DIGEST_PATHS)
        or observed != expected_digests
    ):
        raise ValueError("operation_specification_mismatch")
    return runtime / QUALIFICATION_DIGEST_PATHS["installer_sha256"]


def preview_install(
    repo: Path,
    *,
    home: Path,
    data_home: Path,
    proposed_hooks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    validate_global_hooks(proposed_hooks or [])
    runtime = _runtime(repo)
    before = _sentinels(home, data_home)
    subprocess.run(
        [str(runtime / "install.sh"), "--check"],
        check=True,
        capture_output=True,
        env=_environment(home, data_home),
    )
    if _sentinels(home, data_home) != before:
        raise ValueError("live_install_preview_wrote_state")
    interface = json.loads((runtime / "runtime-interface.v1.json").read_text())
    paths = [
        f".cursor/skills/{entry['id']}"
        for entry in interface["host_skills"]
    ]
    return {
        "schema": "doc-warden/live-install-preview/v1",
        "status": "ready",
        "home": str(home),
        "paths": paths,
        "global_hooks": proposed_hooks or [],
        "rollback": "runtime uninstall-gsd --preview",
        "runtime_pin_digest": digest_ref(
            (runtime / "gsd-core-pin.json").read_bytes()
        ),
    }


def prepare_install(
    repo: Path,
    *,
    home: Path,
    data_home: Path,
    operation_id: str | None = None,
) -> dict[str, Any]:
    return _prepare_runtime_change(repo, home, data_home, operation_id, INSTALL_CONSEQUENCE)


def prepare_uninstall(repo: Path, *, home: Path, data_home: Path) -> dict[str, Any]:
    return _prepare_runtime_change(repo, home, data_home, None, UNINSTALL_CONSEQUENCE)


def _prepare_runtime_change(
    repo: Path, home: Path, data_home: Path, operation_id: str | None, consequence: str,
) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    home = home.expanduser().resolve()
    data_home = data_home.expanduser().resolve()
    operation = operation_id or str(uuid.uuid4())
    if str(uuid.UUID(operation)) != operation:
        raise ValueError("operation_id_invalid")
    repository_key, github_repository_id, qualification = _destination_installation(repo, home, data_home)
    preview = preview_install(repo, home=home, data_home=data_home)
    if consequence == UNINSTALL_CONSEQUENCE:
        _validate_uninstall_destinations(home, data_home)
        wrapper = _wrapper_path(data_home)
        if wrapper.exists() or wrapper.is_symlink():
            _check_wrapper_postimages(home, _read_wrapper_record(wrapper))
        preview = {
            "schema": "doc-warden/live-uninstall-preview/v1", "status": "ready", "home": str(home),
            "paths": preview["paths"], "ownership": "manifest_identity_matching_only",
            "runtime_pin_digest": preview["runtime_pin_digest"],
        }
    if qualification.runtime_digests["pin_sha256"] != preview["runtime_pin_digest"]:
        raise ValueError("runtime_qualification_digest_mismatch")
    source_revision = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    fields = {
        "schema": "doc-warden/live-install-action/v1",
        "operation_id": operation,
        "repository_key": repository_key,
        "github_repository_id": github_repository_id,
        "canonical_root": str(repo),
        "source_revision": source_revision,
        "home": str(home.resolve()),
        "data_home": str(data_home.resolve()),
        "runtime_pin_digest": preview["runtime_pin_digest"],
        "runtime_digests": qualification.runtime_digests,
        "qualification_digest": qualification.qualification_digest,
        "before_sentinels": _sentinels(home, data_home),
        "consequence": consequence,
    }
    action_digest = digest_ref(canonical_json(fields))
    specification = {
        **fields,
        "schema": "doc-warden/live-install-operation/v1",
        "action_digest": action_digest,
        "expires_at": expires_at,
    }
    path = operation_path(operation)
    written = atomic_write(path.parent, path.name, canonical_json(specification))
    written.chmod(0o600)
    return {
        **preview,
        "operation_id": operation,
        "action_digest": action_digest,
        "source_revision": source_revision,
        "canonical_root": str(repo),
        "repository_key": repository_key,
        "github_repository_id": github_repository_id,
        "data_home": str(data_home),
        "before_sentinels_digest": digest_ref(canonical_json(fields["before_sentinels"])),
        "consequence": consequence,
        "consent_required": True,
        "expires_at": expires_at,
    }


def load_install_operation(
    operation_id: str, action_digest: str
) -> LiveInstallOperation:
    path = operation_path(operation_id)
    if path.is_symlink() or not path.is_file():
        raise ValueError("operation_specification_unavailable")
    if path.stat().st_mode & 0o077:
        raise ValueError("operation_specification_permissions_invalid")
    payload = parse_json_object(path.read_bytes())
    required = {
        "schema",
        "operation_id",
        "repository_key",
        "github_repository_id",
        "canonical_root",
        "source_revision",
        "home",
        "data_home",
        "runtime_pin_digest",
        "runtime_digests",
        "qualification_digest",
        "before_sentinels",
        "consequence",
        "action_digest",
        "expires_at",
    }
    if (
        set(payload) != required
        or payload["schema"] != "doc-warden/live-install-operation/v1"
        or payload["operation_id"] != operation_id
        or payload["action_digest"] != action_digest
        or payload["consequence"] not in (INSTALL_CONSEQUENCE, UNINSTALL_CONSEQUENCE)
        or not isinstance(payload["runtime_digests"], dict)
        or set(payload["runtime_digests"]) != set(QUALIFICATION_DIGEST_PATHS)
        or not isinstance(payload["before_sentinels"], dict)
    ):
        raise ValueError("operation_specification_mismatch")
    expires = datetime.fromisoformat(str(payload["expires_at"]))
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError("operation_specification_expired")
    repo = Path(payload["canonical_root"]).resolve(strict=True)
    home = Path(payload["home"])
    data_home = Path(payload["data_home"])
    operation = LiveInstallOperation(
        repo=repo,
        canonical_root=str(repo),
        repository_key=payload["repository_key"],
        github_repository_id=payload["github_repository_id"],
        operation_id=operation_id,
        action_digest=action_digest,
        source_revision=payload["source_revision"],
        home=home,
        data_home=data_home,
        runtime_pin_digest=payload["runtime_pin_digest"],
        runtime_digests=payload["runtime_digests"],
        qualification_digest=payload["qualification_digest"],
        before_sentinels=payload["before_sentinels"],
        expires_at=payload["expires_at"],
        consequence=payload["consequence"],
    )
    _validate_install_operation(operation, require_preimages=False)
    return operation


def _destination_installation(repo: Path, home: Path, data_home: Path):
    if read_repository_config(repo) is None:
        # Historical records support isolated compatibility checks only.
        return CENTRAL_REPOSITORY_KEY, None, _validate_runtime_qualification(repo)
    context, digest, runtime_digests, path = read_destination_qualification(repo, home=home, data_home=data_home)
    return (context["repository_key"], context["github_repository_id"],
            RuntimeQualification(digest, runtime_digests, path, "host_destination_qualification"))


def _validate_install_operation(operation: LiveInstallOperation, *, require_preimages: bool = True) -> None:
    try:
        repo = operation.repo.resolve(strict=True)
        home = operation.home.expanduser().resolve()
        data_home = operation.data_home.expanduser().resolve()
        expires = datetime.fromisoformat(str(operation.expires_at))
        source_revision = subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
        repository_key, github_repository_id, qualification = _destination_installation(repo, home, data_home)
        runtime_pin_digest = qualification.runtime_digests["pin_sha256"]
        fields = {
            "schema": "doc-warden/live-install-action/v1",
            "operation_id": operation.operation_id,
            "repository_key": operation.repository_key,
            "github_repository_id": operation.github_repository_id,
            "canonical_root": operation.canonical_root,
            "source_revision": operation.source_revision,
            "home": str(operation.home),
            "data_home": str(operation.data_home),
            "runtime_pin_digest": operation.runtime_pin_digest,
            "runtime_digests": operation.runtime_digests,
            "qualification_digest": operation.qualification_digest,
            "before_sentinels": operation.before_sentinels,
            "consequence": operation.consequence,
        }
        action_digest = digest_ref(canonical_json(fields))
        operation_id = str(uuid.UUID(operation.operation_id))
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError("operation_specification_mismatch") from exc
    if (
        operation_id != operation.operation_id
        or operation.consequence not in (INSTALL_CONSEQUENCE, UNINSTALL_CONSEQUENCE)
        or operation.repository_key != repository_key
        or operation.github_repository_id != github_repository_id
        or str(repo) != operation.canonical_root
        or home != operation.home
        or data_home != operation.data_home
        or expires.tzinfo is None
        or expires <= datetime.now(timezone.utc)
        or source_revision != operation.source_revision
        or runtime_pin_digest != operation.runtime_pin_digest
        or qualification.runtime_digests != operation.runtime_digests
        or qualification.qualification_digest != operation.qualification_digest
        or (require_preimages and _sentinels(home, data_home) != operation.before_sentinels)
        or action_digest != operation.action_digest
    ):
        raise ValueError("operation_specification_mismatch")


@contextmanager
def _runtime_writer(home: Path, data_home: Path):
    home, data_home = home.resolve(), data_home.resolve()
    for root in {home, data_home}:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    locks = {
        contained_path(home, ".local/state/doc-warden/gsd-install.lock"),
        contained_path(data_home, ".doc-warden-gsd-install.lock"),
    }
    handles = []
    flags = os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        for lock in sorted(locks):
            lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(lock, flags, 0o600)
            handles.append(fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("live_install_lock_invalid")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("live_install_operation_busy") from exc
        yield
    finally:
        for fd in reversed(handles):
            os.close(fd)


def apply_prepared_install(
    operation: LiveInstallOperation,
    consent: dict[str, Any] | None,
    *,
    real_home: Path,
) -> dict[str, Any]:
    from .artifacts import validate_consent

    validate_consent(
        consent,
        operation_id=operation.operation_id,
        repository_key=operation.repository_key,
        canonical_root=operation.canonical_root,
        source_revision=operation.source_revision,
        action_digest=operation.action_digest,
        consequence_class="external",
    )
    _validate_install_operation(operation, require_preimages=False)
    if operation.home == real_home.resolve() and operation.github_repository_id is None:
        raise ValueError("runtime_destination_qualification_required")
    removing = operation.consequence == UNINSTALL_CONSEQUENCE
    verb = "uninstall" if removing else "install"
    result = {
        "schema": f"doc-warden/live-{verb}-result/v1",
        "operation_id": operation.operation_id,
        "action_digest": operation.action_digest,
        "status": "applied",
        "home": str(operation.home),
        "runtime_pin_digest": operation.runtime_pin_digest,
    }
    home, data_home = operation.home, operation.data_home
    operation_binding = {"operation_id": operation.operation_id, "action_digest": operation.action_digest}
    state = private_state_root()
    outcome = contained_path(state, f"runtime/{verb}-{operation.operation_id}.json")
    with _runtime_writer(home, data_home):
        _validate_install_operation(operation, require_preimages=False)
        if removing:
            _apply_uninstall_with_receipt(operation, outcome, result, allow_live_home=home == real_home.resolve())
            return result
        if outcome.is_file():
            saved = parse_json_object(outcome.read_bytes())
            if saved != {"result": result, "postimages": _sentinels(home, data_home)}:
                raise ValueError("live_install_postimage_changed")
            return result
        _apply_install_with_readback(operation, operation_binding, real_home=real_home)
        evidence = canonical_json({"result": result, "postimages": _sentinels(home, data_home)})
        atomic_write(state, outcome.relative_to(state).as_posix(), evidence)
        if outcome.read_bytes() != evidence:
            raise ValueError("live_install_readback_failed")
        return result


def _apply_uninstall_with_receipt(
    operation: LiveInstallOperation, outcome: Path, result: dict[str, Any], *, allow_live_home: bool,
) -> None:
    home, data_home = operation.home, operation.data_home
    wrapper = _wrapper_path(data_home)
    state = outcome.parent.parent
    pending = outcome.with_name(f"uninstall-pending-{operation.operation_id}.json")
    pending_payload = canonical_json({
        "schema": "doc-warden/live-uninstall-pending/v1",
        "operation_id": operation.operation_id,
        "action_digest": operation.action_digest,
    })
    if pending.exists() or pending.is_symlink():
        if pending.is_symlink() or not pending.is_file() or pending.read_bytes() != pending_payload:
            raise ValueError("live_uninstall_recovery_required")

    def verify_completion() -> None:
        if outcome.is_symlink() or not outcome.is_file():
            raise ValueError("live_uninstall_recovery_required")
        saved = parse_json_object(outcome.read_bytes())
        observed = _sentinels(home, data_home)
        wrapper_digest = observed.pop(str(wrapper), None)
        if (set(saved) != {"result", "postimages", "wrapper_digest"} or saved["result"] != result
                or saved["postimages"] != observed
                or (wrapper_digest is not None and wrapper_digest != saved["wrapper_digest"])):
            raise ValueError("live_install_postimage_changed")
        if wrapper_digest is not None:
            wrapper.unlink()
        pending.unlink(missing_ok=True)

    def record_completion() -> None:
        postimages = _sentinels(home, data_home)
        wrapper_digest = postimages.pop(str(wrapper), None)
        evidence = canonical_json({"result": result, "postimages": postimages, "wrapper_digest": wrapper_digest})
        atomic_write(state, outcome.relative_to(state).as_posix(), evidence)
        if outcome.read_bytes() != evidence:
            raise ValueError("live_uninstall_recovery_required")

    try:
        if outcome.exists() or outcome.is_symlink():
            verify_completion()
            return
        if _sentinels(home, data_home) != operation.before_sentinels:
            raise ValueError("live_uninstall_recovery_required" if pending.is_file() else "operation_specification_mismatch")
        _validated_runtime_files(operation.repo, operation.runtime_digests)
        atomic_write(state, pending.relative_to(state).as_posix(), pending_payload)
        _uninstall_locked(operation.repo, home=home, data_home=data_home,
                          record_completion=record_completion, allow_live_home=allow_live_home)
        verify_completion()
    except OSError as exc:
        raise ValueError("live_uninstall_recovery_required") from exc


def _apply_install_with_readback(operation: LiveInstallOperation, binding: dict[str, str], *, real_home: Path) -> None:
    home, data_home = operation.home, operation.data_home
    wrapper = _wrapper_path(data_home)
    if wrapper.is_file():
        previous = _read_wrapper_record(wrapper)
        if previous["operation"] != binding or previous["postimages"] is None:
            raise ValueError("live_install_recovery_evidence_required")
        _check_wrapper_postimages(home, previous)
    else:
        if _sentinels(home, data_home) != operation.before_sentinels:
            raise ValueError("operation_specification_mismatch")
        apply_install(
            operation.repo, home=home, data_home=data_home,
            isolated_home_qualified=True, host_signer_qualified=True, real_home=real_home,
            expected_runtime_digests=operation.runtime_digests, operation_binding=binding,
        )
    if operation.github_repository_id is not None:
        try:
            _live_doctor_state(operation.repo, home=home, data_home=data_home)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            try:
                _uninstall_locked(operation.repo, home=home, data_home=data_home,
                                  allow_live_home=home == real_home.resolve())
            except (OSError, ValueError, subprocess.SubprocessError) as rollback_error:
                raise ValueError("live_install_rollback_incomplete") from rollback_error
            raise ValueError("live_install_readback_failed") from exc


def apply_install(
    repo: Path,
    *,
    home: Path,
    data_home: Path,
    isolated_home_qualified: bool,
    host_signer_qualified: bool,
    real_home: Path,
    expected_runtime_digests: dict[str, str],
    operation_binding: dict[str, str] | None = None,
) -> None:
    if not isolated_home_qualified:
        raise ValueError("isolated_home_not_qualified")
    home, data_home = home.expanduser().resolve(), data_home.expanduser().resolve()
    is_live = home == real_home.resolve()
    if is_live and not host_signer_qualified:
        raise ValueError("host_signer_not_qualified")
    installer = _validated_runtime_files(repo, expected_runtime_digests)
    env = _environment(home, data_home, allow_live_home=is_live)
    wrapper_receipt = _wrapper_path(data_home)
    if wrapper_receipt.exists():
        raise ValueError("live_install_already_applied")
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    wrapper_receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": "doc-warden/live-install-preimage/v2",
        "operation": operation_binding,
        "postimages": None,
        "preimages": {
            relative: (
                {"content": base64.b64encode(path.read_bytes()).decode("ascii"),
                 "mode": stat.S_IMODE(path.stat().st_mode)}
                if path.is_file()
                else None
            )
            for relative in UPSTREAM_RESIDUE_PATHS
            for path in (contained_path(home, relative),)
        },
    }
    written = atomic_write(
        wrapper_receipt.parent,
        wrapper_receipt.name,
        canonical_json(receipt),
    )
    written.chmod(0o600)
    try:
        installer = _validated_runtime_files(repo, expected_runtime_digests)
    except ValueError:
        wrapper_receipt.unlink()
        raise
    try:
        subprocess.run(
            [str(installer), "--apply"], check=True, capture_output=True, env=env
        )
    except (OSError, subprocess.SubprocessError) as install_error:
        try:
            receipt["postimages"] = _wrapper_images(home)
            atomic_write(wrapper_receipt.parent, wrapper_receipt.name, canonical_json(receipt))
            _uninstall_locked(repo, home=home, data_home=data_home, allow_live_home=is_live)
        except (OSError, subprocess.SubprocessError, ValueError) as rollback_error:
            raise ValueError("live_install_rollback_incomplete") from rollback_error
        raise install_error
    receipt["postimages"] = _wrapper_images(home)
    atomic_write(wrapper_receipt.parent, wrapper_receipt.name, canonical_json(receipt))


def _wrapper_path(data_home: Path) -> Path:
    return data_home / "gsd-core/doc-warden-wrapper-preimage.json"


def _wrapper_images(home: Path) -> dict[str, str | None]:
    return {relative: digest_ref(canonical_json({"content": digest_ref(path.read_bytes()),
                                                "mode": stat.S_IMODE(path.stat().st_mode)})) if path.is_file() else None
            for relative in UPSTREAM_RESIDUE_PATHS for path in (contained_path(home, relative),)}


def _check_wrapper_postimages(home: Path, record: dict[str, Any]) -> None:
    if record["postimages"] is None:
        raise ValueError("live_install_recovery_evidence_required")
    if _wrapper_images(home) != record["postimages"]:
        raise ValueError("live_install_postimage_changed")


def _validate_uninstall_destinations(home: Path, data_home: Path) -> tuple[Path, Path]:
    if not data_home.exists():
        return home, data_home
    manifest = contained_path(data_home, "gsd-core/doc-warden-manifest.json")
    if not manifest.exists():
        return home, data_home
    record = parse_json_object(_read_regular_file(manifest))
    if (record.get("schema") != "doc-warden/gsd-install-manifest/v1" or record.get("owner") != "doc-warden"
            or any(not isinstance(record.get(key), str) for key in ("cursor_root", "release_root"))):
        raise ValueError("live_uninstall_destination_mismatch")
    cursor_root = Path(record["cursor_root"])
    release_root = Path(record["release_root"])
    if (not cursor_root.is_absolute() or cursor_root.name != ".cursor"
            or not release_root.is_absolute() or release_root.parts[-3:] != ("gsd-core", "releases", GSD_COMMIT)
            or cursor_root.resolve() != home / ".cursor"
            or release_root.resolve() != data_home / "gsd-core/releases" / GSD_COMMIT):
        raise ValueError("live_uninstall_destination_mismatch")
    # Legacy manifests may record a lexical alias. The retained owner helper
    # compares that spelling; all wrapper preimages use the canonical destination.
    return cursor_root.parent, release_root.parents[2]


def uninstall(repo: Path, *, home: Path, data_home: Path) -> None:
    home, data_home = home.expanduser().resolve(), data_home.expanduser().resolve()
    with _runtime_writer(home, data_home):
        _uninstall_locked(repo, home=home, data_home=data_home)


def _uninstall_locked(
    repo: Path, *, home: Path, data_home: Path, record_completion: Callable[[], None] | None = None,
    allow_live_home: bool = False,
) -> None:
    owner_home, owner_data = _validate_uninstall_destinations(home, data_home)
    wrapper_receipt = _wrapper_path(data_home)
    receipt = _read_wrapper_record(wrapper_receipt) if wrapper_receipt.is_file() else None
    if receipt is not None:
        _check_wrapper_postimages(home, receipt)
    try:
        subprocess.run(
            [str(_runtime(repo) / "install.sh"), "--uninstall"],
            check=True, capture_output=True,
            env=_environment(owner_home, owner_data, allow_live_home=allow_live_home),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("live_install_uninstall_incomplete") from exc
    if receipt is not None:
        _restore_wrapper_preimages(home, receipt)
    if record_completion is not None:
        record_completion()
    if receipt is not None:
        wrapper_receipt.unlink()


def _read_wrapper_record(wrapper_receipt: Path) -> dict[str, Any]:
    if wrapper_receipt.is_symlink() or wrapper_receipt.stat().st_mode & 0o077:
        raise ValueError("live_install_preimage_invalid")
    receipt = parse_json_object(wrapper_receipt.read_bytes())
    if receipt.get("schema") == "doc-warden/live-install-preimage/v1":
        raise ValueError("live_install_recovery_evidence_required")
    if (
        set(receipt) != {"schema", "preimages", "postimages", "operation"}
        or receipt["schema"] != "doc-warden/live-install-preimage/v2"
        or not isinstance(receipt["preimages"], dict)
        or set(receipt["preimages"]) != set(UPSTREAM_RESIDUE_PATHS)
        or (receipt["postimages"] is not None and (not isinstance(receipt["postimages"], dict)
            or set(receipt["postimages"]) != set(UPSTREAM_RESIDUE_PATHS)))
    ):
        raise ValueError("live_install_preimage_invalid")
    return receipt


def _restore_wrapper_preimages(home: Path, receipt: dict[str, Any]) -> None:
    preimages = receipt["preimages"]
    try:
        decoded = {
            relative: (
                None if prior is None else (base64.b64decode(prior["content"], validate=True), prior["mode"])
            )
            for relative, prior in preimages.items()
            if prior is None or (isinstance(prior, dict) and set(prior) == {"content", "mode"}
                                 and type(prior["mode"]) is int and 0 <= prior["mode"] <= 0o777)
        }
    except (ValueError, TypeError) as exc:
        raise ValueError("live_install_preimage_invalid") from exc
    if len(decoded) != len(preimages):
        raise ValueError("live_install_preimage_invalid")
    observed = _wrapper_images(home)
    if any(value is not None and value != receipt["postimages"][relative]
           for relative, value in observed.items()):
        raise ValueError("live_install_postimage_changed")
    for relative, prior in decoded.items():
        path = contained_path(home, relative)
        if prior is None:
            path.unlink(missing_ok=True)
        else:
            data, mode = prior
            atomic_write(home, relative, data).chmod(mode)


def _source_revision(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    revision = result.stdout.strip()
    if len(revision) != 40:
        raise ValueError("live_doctor_source_revision_invalid")
    return revision


def _live_doctor_state(
    repo: Path,
    *,
    home: Path,
    data_home: Path,
) -> tuple[dict[str, Any], tuple[ObservedInput, ...]]:
    root = repo.resolve(strict=True)
    home = home.expanduser().resolve()
    data_home = data_home.expanduser().resolve()
    profile = read_repository_config(root)
    if profile is not None and (profile["repository_key"] == CURRENT_REPOSITORY_KEY
                                or profile["github_repository_id"] == CENTRAL_REPOSITORY_ID):
        _, _, qualification = _destination_installation(root, home, data_home)
    else:
        qualification = _validate_runtime_qualification(root)
    runtime = _runtime(root)
    subprocess.run(
        [str(runtime / "install.sh"), "--doctor"],
        check=True,
        capture_output=True,
        text=True,
        env=_environment(home, data_home),
    )
    manifest_path = data_home / "gsd-core/doc-warden-manifest.json"
    manifest_bytes = _read_regular_file(manifest_path)
    manifest = parse_json_object(manifest_bytes)
    release = data_home / "gsd-core/releases" / GSD_COMMIT
    interface_path = runtime / "runtime-interface.v1.json"
    interface = parse_json_object(_read_regular_file(interface_path))
    host_skills = interface.get("host_skills")
    if (
        set(manifest)
        != {
            "schema",
            "owner",
            "release_root",
            "cursor_root",
            "pin_digest",
            "lock_digest",
            "interface_digest",
            "defaults_preimage",
            "shims",
        }
        or manifest["schema"] != "doc-warden/gsd-install-manifest/v1"
        or manifest["owner"] != "doc-warden"
        or manifest["release_root"] != str(release)
        or manifest["cursor_root"] != str(home / ".cursor")
        or manifest["pin_digest"]
        != qualification.runtime_digests["pin_sha256"].removeprefix("sha256:")
        or manifest["lock_digest"]
        != qualification.runtime_digests["package_lock_sha256"].removeprefix(
            "sha256:"
        )
        or manifest["interface_digest"]
        != qualification.runtime_digests[
            "runtime_interface_sha256"
        ].removeprefix("sha256:")
        or not isinstance(host_skills, list)
        or not host_skills
    ):
        raise ValueError("live_doctor_observation_invalid")
    package = parse_json_object(
        _read_regular_file(
            release / "node_modules/@opengsd/gsd-core/package.json"
        )
    )
    if (
        package.get("name") != GSD_PACKAGE
        or package.get("version") != GSD_VERSION
    ):
        raise ValueError("live_doctor_observation_invalid")
    shims = manifest.get("shims")
    if not isinstance(shims, dict) or set(shims) != {
        "gsd-core",
        "gsd-tools",
        "gsd_run",
    }:
        raise ValueError("live_doctor_observation_invalid")
    observed_inputs = [
        ObservedInput(
            str(manifest_path.resolve(strict=True)),
            digest_ref(manifest_bytes),
        )
    ]
    installed_shims = {}
    for name, record in shims.items():
        shim = release / "doc-warden-bin" / name
        stable = home / ".local/bin" / name
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "sha256"}
            or record["path"] != str(shim)
            or not stable.is_symlink()
            or stable.readlink() != shim
        ):
            raise ValueError("live_doctor_observation_invalid")
        shim_bytes = _read_regular_file(shim)
        if record["sha256"] != digest_ref(shim_bytes).removeprefix("sha256:"):
            raise ValueError("live_doctor_observation_invalid")
        installed_shims[name] = digest_ref(shim_bytes)
        observed_inputs.append(
            ObservedInput(str(shim.resolve(strict=True)), digest_ref(shim_bytes))
        )
    authoring_interfaces = []
    seen: set[str] = set()
    for entry in host_skills:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("id"), str)
            or entry["id"] in seen
        ):
            raise ValueError("live_doctor_observation_invalid")
        skill_id = entry["id"]
        seen.add(skill_id)
        relative = f".cursor/skills/{skill_id}/SKILL.md"
        descriptor = home / relative
        descriptor_bytes = _read_regular_file(descriptor)
        descriptor_digest = digest_ref(descriptor_bytes)
        authoring_interfaces.append(
            {
                "id": skill_id,
                "path": relative,
                "digest": descriptor_digest,
                "digest_basis": "live_descriptor_bytes",
            }
        )
        observed_inputs.append(
            ObservedInput(
                str(descriptor.resolve(strict=True)),
                descriptor_digest,
            )
        )
    utilities = interface.get("deterministic_utilities")
    if not isinstance(utilities, list) or not utilities:
        raise ValueError("live_doctor_observation_invalid")
    deterministic_utilities = []
    seen_utilities: set[str] = set()
    for entry in utilities:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("command"), str)
            or entry["command"] not in {"gsd-core", "gsd-tools"}
            or entry["command"] in seen_utilities
        ):
            raise ValueError("live_doctor_observation_invalid")
        command = entry["command"]
        seen_utilities.add(command)
        deterministic_utilities.append(
            {
                "command": command,
                "path": f".local/bin/{command}",
                "digest": installed_shims[command],
                "digest_basis": "live_bounded_shim_bytes",
            }
        )
    observed_inputs.append(
        ObservedInput(
            str(qualification.path.resolve(strict=True)),
            qualification.qualification_digest,
        )
    )
    for name, relative in QUALIFICATION_DIGEST_PATHS.items():
        path = (runtime / relative).resolve(strict=True)
        observed_inputs.append(
            ObservedInput(str(path), qualification.runtime_digests[name])
        )
    binding = {
        "source_revision": _source_revision(root),
        "runtime": {
            "package": GSD_PACKAGE,
            "version": GSD_VERSION,
            "git_commit": GSD_COMMIT,
            "npm_integrity": GSD_NPM_INTEGRITY,
            "pin_digest": qualification.runtime_digests["pin_sha256"],
            "package_lock_digest": qualification.runtime_digests[
                "package_lock_sha256"
            ],
            "interface_digest": qualification.runtime_digests[
                "runtime_interface_sha256"
            ],
            "interface_digest_basis": qualification.basis,
            "qualification_digest": qualification.qualification_digest,
        },
        "machine_install_receipt": {
            "path": "gsd-core/doc-warden-manifest.json",
            "digest": digest_ref(manifest_bytes),
        },
        "authoring_interfaces": authoring_interfaces,
        "deterministic_utilities": deterministic_utilities,
    }
    return binding, tuple(observed_inputs)


def _doctor_observation(
    binding: dict[str, Any],
    *,
    observation_id: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    identifier = observation_id or str(uuid.uuid4())
    if str(uuid.UUID(identifier)) != identifier:
        raise ValueError("live_doctor_observation_invalid")
    timestamp = observed_at or datetime.now(timezone.utc).isoformat()
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise ValueError("live_doctor_observation_invalid") from exc
    if parsed_timestamp.tzinfo is None:
        raise ValueError("live_doctor_observation_invalid")
    observation = {
        "schema": "doc-warden/gsd-live-doctor-observation/v1",
        "observation_id": identifier,
        "observed_at": timestamp,
        **binding,
        "status": "passed",
        "receipt_path": (
            "_ops/doc-warden/state/v2/runtime/live-doctor/"
            f"{identifier}.json"
        ),
        "rollback": {
            "command": "doc-warden runtime uninstall-gsd --preview",
            "ownership": "manifest_identity_matching_only",
        },
    }
    require_valid("live-doctor-observation", observation)
    return observation


def doctor(
    repo: Path,
    *,
    home: Path,
    data_home: Path,
    observation_id: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    binding, _ = _live_doctor_state(repo, home=home, data_home=data_home)
    return _doctor_observation(
        binding,
        observation_id=observation_id,
        observed_at=observed_at,
    )


LIVE_DOCTOR_FRESHNESS_FIELDS = (
    "runtime",
    "machine_install_receipt",
    "authoring_interfaces",
    "deterministic_utilities",
)


def _expected_doctor_receipt_path(observation_id: str) -> str:
    try:
        identifier = str(uuid.UUID(observation_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("live_doctor_observation_invalid") from exc
    if identifier != observation_id:
        raise ValueError("live_doctor_observation_invalid")
    return (
        "_ops/doc-warden/state/v2/runtime/live-doctor/"
        f"{identifier}.json"
    )


def read_doctor_observation_file(path: Path) -> dict[str, Any]:
    return _read_canonical_state_record(
        path,
        "live-doctor-observation",
        missing_code="live_doctor_observation_invalid",
        invalid_code="live_doctor_observation_invalid",
        mismatch_code="live_doctor_observation_mismatch",
    ).value


def _validate_live_doctor_freshness(
    observation: dict[str, Any], binding: dict[str, Any]
) -> str:
    for field in LIVE_DOCTOR_FRESHNESS_FIELDS:
        if observation[field] != binding[field]:
            raise ValueError("live_doctor_observation_mismatch")
    return (
        "current"
        if observation["source_revision"] == binding["source_revision"]
        else "stale_source_revision"
    )


def _matching_doctor_receipts(
    repo: Path, observation: dict[str, Any], observation_digest: str
) -> list[CanonicalStateRecord]:
    receipt_root = repo / "_ops/doc-warden/state/v2/receipts"
    if receipt_root.is_symlink():
        raise ValueError("live_doctor_receipt_mismatch")
    if not receipt_root.exists():
        return []
    if not receipt_root.is_dir():
        raise ValueError("live_doctor_receipt_mismatch")
    matches = []
    for path in sorted(receipt_root.glob("*.json")):
        record = _read_canonical_state_record(
            path,
            "receipt",
            missing_code="live_doctor_receipt_mismatch",
            invalid_code="live_doctor_receipt_mismatch",
            mismatch_code="live_doctor_receipt_mismatch",
        )
        postimages = record.value["postimages"]
        if postimages.get(observation["receipt_path"]) == observation_digest:
            matches.append(record)
    return matches


def _validate_doctor_repository_identity(repo: Path, receipt: dict[str, Any]) -> None:
    bindings = receipt.get("bindings")
    identity = bindings.get("repository_identity") if isinstance(bindings, dict) else None
    if not isinstance(identity, dict):
        raise ValueError("live_doctor_repository_identity_missing")
    observed = observe_repository_identity(repo)
    if (
        observed.binding() != identity
        or receipt["github_repository_id"] != observed.github_repository_id
        or identity["github_repository_id"] != receipt["github_repository_id"]
    ):
        raise ValueError("repository_identity_mismatch")


def _validate_doctor_event(repo: Path, receipt: dict[str, Any]) -> None:
    event_path = contained_path(
        repo,
        f"_ops/doc-warden/state/v2/events/{receipt['event_id']}.json",
    )
    event = _read_canonical_state_record(
        event_path,
        "operation-event",
        missing_code="live_doctor_event_missing",
        invalid_code="live_doctor_event_mismatch",
        mismatch_code="live_doctor_event_mismatch",
    ).value
    if (
        event["event_id"],
        event["operation_id"],
        event["action_digest"],
        event["transition"],
        event["source_revision"],
        event["prior_event_digest"],
        event["outcome"],
        event["details"],
    ) != (
        receipt["event_id"],
        receipt["operation_id"],
        receipt["action_digest"],
        receipt["transition"],
        receipt["source_revision"],
        receipt["prior_event_digest"],
        receipt["outcome"],
        {"postimages": receipt["postimages"]},
    ):
        raise ValueError("live_doctor_event_mismatch")
    if receipt["result_tree_digest"] != digest_ref(
        canonical_json({"event": event, "postimages": receipt["postimages"]})
    ):
        raise ValueError("live_doctor_receipt_mismatch")


def _validate_doctor_observation_evidence(
    repo: Path,
    observation: dict[str, Any],
    *,
    observation_path: Path,
    observation_digest: str,
    receipt_record: CanonicalStateRecord,
) -> None:
    observation_record = _read_canonical_state_record(
        observation_path,
        "live-doctor-observation",
        missing_code="live_doctor_evidence_missing",
        invalid_code="live_doctor_observation_mismatch",
        mismatch_code="live_doctor_observation_mismatch",
    )
    if observation_record.value != observation or observation_record.digest != observation_digest:
        raise ValueError("live_doctor_observation_mismatch")
    receipt = receipt_record.value
    action = {
        "kind": "create",
        "path": observation["receipt_path"],
        "content_digest": observation_digest,
    }
    if (
        receipt["transition"] != "creation_snapshot"
        or receipt["outcome"] != "applied"
        or receipt["delivery_commit"] is not None
        or receipt["source_revision"] != observation["source_revision"]
        or receipt["postimages"] != {observation["receipt_path"]: observation_digest}
        or receipt["preimages"] != {observation["receipt_path"]: None}
        or receipt["actions"] != [action]
        or receipt["bindings"].get("gsd_interface_digest")
        != observation["runtime"]["interface_digest"]
    ):
        raise ValueError("live_doctor_receipt_mismatch")
    _validate_doctor_repository_identity(repo, receipt)
    _validate_doctor_event(repo, receipt)


def doctor_observation_status(
    repo: Path,
    observation: dict[str, Any],
    *,
    home: Path,
    data_home: Path,
    require_current: bool = False,
) -> dict[str, Any]:
    """Validate immutable evidence and report whether live HEAD is fresh.

    historical_valid/evidence_verified are true only for observations whose
    persisted observation, receipt, event, and postimage lineage were verified.
    A current pre-apply observation with no persisted lineage is valid but
    explicitly non-historical and unevidenced.
    """
    require_valid("live-doctor-observation", observation)
    if observation["receipt_path"] != _expected_doctor_receipt_path(
        observation["observation_id"]
    ):
        raise ValueError("live_doctor_observation_path_mismatch")
    root = repo.resolve(strict=True)
    binding, _ = _live_doctor_state(root, home=home, data_home=data_home)
    live_freshness = _validate_live_doctor_freshness(observation, binding)
    if require_current and live_freshness != "current":
        raise ValueError("live_doctor_observation_stale")
    observation_digest = digest_ref(canonical_json(observation))
    observation_path = contained_path(root, observation["receipt_path"])
    receipt_matches = _matching_doctor_receipts(root, observation, observation_digest)
    evidence_expected = (
        bool(receipt_matches)
        or observation_path.exists()
        or observation_path.is_symlink()
        or live_freshness != "current"
    )
    evidence_verified = False
    if evidence_expected:
        if len(receipt_matches) != 1:
            raise ValueError(
                "live_doctor_evidence_missing"
                if not receipt_matches
                else "live_doctor_evidence_ambiguous"
            )
        _validate_doctor_observation_evidence(
            root,
            observation,
            observation_path=observation_path,
            observation_digest=observation_digest,
            receipt_record=receipt_matches[0],
        )
        evidence_verified = True
    return {
        "schema": "doc-warden/live-doctor-observation-status/v1",
        "status": "valid",
        "historical_valid": evidence_verified,
        "historical_status": "verified" if evidence_verified else "not_historical",
        "evidence_verified": evidence_verified,
        "evidence_status": "verified" if evidence_verified else "not_persisted",
        "live_freshness": live_freshness,
        "source_revision": observation["source_revision"],
        "current_source_revision": binding["source_revision"],
        "observation_id": observation["observation_id"],
        "receipt_path": observation["receipt_path"],
    }


def validate_doctor_observation(
    repo: Path,
    observation: dict[str, Any],
    *,
    home: Path,
    data_home: Path,
    require_current: bool = False,
) -> dict[str, Any]:
    return doctor_observation_status(
        repo,
        observation,
        home=home,
        data_home=data_home,
        require_current=require_current,
    )


def preview_doctor_receipt(
    repo: Path,
    *,
    home: Path,
    data_home: Path,
    operation_id: str | None = None,
) -> tuple[dict[str, Any], TransactionPreview]:
    root = repo.resolve(strict=True)
    binding, observed_inputs = _live_doctor_state(
        root, home=home, data_home=data_home
    )
    observation = _doctor_observation(binding)
    identity = observe_repository_identity(root)
    from .artifacts import _bindings

    bindings = _bindings(root)
    bindings["gsd_interface_digest"] = observation["runtime"][
        "interface_digest"
    ]
    bindings["repository_identity"] = identity.binding()
    profile = read_repository_config(root)
    repository_key = (
        profile["repository_key"]
        if profile is not None
        else CENTRAL_REPOSITORY_KEY
    )
    preview = preview_transaction(
        MutationRequest(
            repo=root,
            repository_key=repository_key,
            github_repository_id=identity.github_repository_id,
            transition="creation_snapshot",
            actions=(
                MutationAction(
                    observation["receipt_path"],
                    canonical_json(observation),
                ),
            ),
            bindings=bindings,
            operation_id=operation_id,
            observed_inputs=observed_inputs,
            consequential=True,
            require_write_enabled=False,
        )
    )
    return observation, preview


def _sentinels(home: Path, data_home: Path) -> dict[str, str]:
    roots = (
        home / ".cursor/skills",
        home / ".cursor/agents",
        home / ".cursor/commands",
        home / ".cursor/hooks",
        home / ".gsd",
        data_home / "gsd-core",
    )
    result: dict[str, str] = {}

    def observe(path: Path) -> None:
        if path.is_symlink():
            result[str(path)] = digest_ref(canonical_json({"symlink": str(path.readlink())}))
        elif path.is_file():
            result[str(path)] = digest_ref(canonical_json({"content": digest_ref(path.read_bytes()),
                                                         "mode": stat.S_IMODE(path.stat().st_mode)}))

    for path in (
        home / ".cursor/hooks.json",
        home / ".local/bin/gsd-core",
        home / ".local/bin/gsd-tools",
        home / ".local/bin/gsd_run",
        *(home / relative for relative in UPSTREAM_RESIDUE_PATHS),
    ):
        observe(path)
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            observe(path)
    return result
