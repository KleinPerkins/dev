#!/usr/bin/env python3
"""INT-014 fixture preview and separate partial maintenance transaction helpers.

The caller supplies an explicit catalog, selection, retained wheel, owner Git
repository, and disposable fixture parent.  This module verifies the exact
unreleased kp-mcp source/package/API binding before importing from the wheel,
then calls only the public ``inspect_registration`` and ``preview`` methods in
owner-created disposable fixture contexts.

The original CLI/API never discovers a live target, installs a package, prepares
or saves an operation, applies/recovers/rolls back/cancels, executes a configured
command, or claims writer retirement/native qualification. Shareable output contains
only identifiers, digests, fixture identifiers, proposed/preserved native
paths, and bounded reason codes/conflicts.

The separate 0.4 helpers near the end exercise actual registrar transactions
under the maintenance barrier. Production control admission remains closed:
native pause/drain, baseline/restoration and target eligibility are unresolved.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence
import zipfile

import original_sources


REQUEST_SCHEMA = "dev/mcp-migration-preview-request/v1"
RESULT_SCHEMA = "dev/mcp-migration-preview/v1"
ERROR_SCHEMA = "dev/mcp-migration-preview-error/v1"

SOURCE_OWNER = "KleinPerkins/kp-mcp"
SOURCE_REVISION = "a34a0f73b93650e4a6abe9c9dff9a2e3eced94cb"
SOURCE_TREE = "eb8b0de067101f8387ea177ac395a2c2997eff28"
PACKAGE_TREE = "b6d2991a8c7f84d3e856d145124ed711e12b39b4"
PACKAGE_VERSION = "0.3.0"
WHEEL_SHA256 = "1c63c3843a2e28d057a4be263cf30c7ac933479a2e514b6d25393c90e4a794df"
ADAPTER_SOURCE_DIGEST = "fd79e12ad903ddf5ca7760622f9afb41f7f7b4828bda3c536643d69c854c85c6"

ADAPTER_BINDINGS = MappingProxyType(
    {
        "cursor": {
            "class": "CursorRegistrar",
            "mapping_version": "cursor-mcp-json/v1",
            "mapping_digest": "6239dc08b7981b63f7e18809e350f43ce9adb99edf902ddb373695838e999206",
        },
        "codex": {
            "class": "CodexRegistrar",
            "mapping_version": "codex-config-toml/v1",
            "mapping_digest": "234a69e2d914ae008301b2e482277c000a7c5552550ef3a490f6ae6be65b00f7",
        },
        "claude": {
            "class": "ClaudeRegistrar",
            "mapping_version": "claude-user-json/v1",
            "mapping_digest": "c574dbd3e44de24cbbf473bd2b73921f96754e6d3f10356a8c0cdec4cb1a6917",
        },
    }
)

INSPECTION_SIGNATURE = "(path: 'Path', *, context: 'RegistrationContext') -> 'Inspection'"
PREVIEW_SIGNATURE = "(path: 'Path', definition: 'RegistrationDefinition', *, context: 'RegistrationContext') -> 'Preview'"
TARGETS = frozenset(ADAPTER_BINDINGS)
MANAGEMENT = frozenset({"registrar-owned", "external-app"})

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}\Z")
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_REASON = re.compile(r"[a-z][a-z0-9_]{0,79}\Z")
_SECRET_KEY_PARTS = ("token", "secret", "password", "credential", "private_key")


class MigrationError(Exception):
    """Bounded failure that never carries source/config values or local paths."""

    def __init__(self, *reason_codes: str) -> None:
        normalized = tuple(dict.fromkeys(reason_codes or ("owner_api_failed",)))
        if any(not _REASON.fullmatch(code) for code in normalized):
            normalized = ("owner_api_failed",)
        self.reason_codes = normalized
        super().__init__("mcp-migration:" + ",".join(normalized))


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    connection_id: str
    native_name: str
    owner: str
    management: str
    targets: tuple[str, ...]
    source_revision: str | None = None
    transport: Mapping[str, Any] | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class Selection:
    connection_id: str
    targets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreviewRequest:
    fixture_id: str
    catalog: tuple[CatalogEntry, ...]
    selection: tuple[Selection, ...]
    request_digest: str


@dataclass(frozen=True, slots=True)
class BoundOwnerAPI:
    """Exact public owner API after source/wheel/signature verification."""

    registrar_classes: Mapping[str, type]
    SourceIdentity: type
    RegistrationDefinition: type
    AuthBinding: type
    RegistrarError: type[BaseException]
    fixture_context: Callable[..., Any]
    package_version: str = PACKAGE_VERSION
    source_owner: str = SOURCE_OWNER
    source_revision: str = SOURCE_REVISION
    source_tree: str = SOURCE_TREE
    package_tree: str = PACKAGE_TREE
    wheel_sha256: str = WHEEL_SHA256
    adapter_source_digest: str = ADAPTER_SOURCE_DIGEST


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _require_identifier(value: Any, reason: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise MigrationError(reason)
    return value


def _require_targets(value: Any, reason: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or item not in TARGETS for item in value)
        or len(value) != len(set(value))
    ):
        raise MigrationError(reason)
    return tuple(sorted(value))


def _validate_transport(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        raise MigrationError("catalog_invalid")
    kind = value["kind"]
    if kind == "stdio":
        if set(value) != {"kind", "command", "args", "env"}:
            raise MigrationError("catalog_invalid")
        command, args, env = value["command"], value["args"], value["env"]
        if (
            not isinstance(command, str)
            or not Path(command).is_absolute()
            or "\x00" in command
            or not isinstance(args, list)
            or any(not isinstance(arg, str) or "\x00" in arg for arg in args)
            or not isinstance(env, dict)
        ):
            raise MigrationError("catalog_invalid")
        for key, item in env.items():
            if (
                not isinstance(key, str)
                or not _ENV_NAME.fullmatch(key)
                or any(part in key.lower() for part in _SECRET_KEY_PARTS)
                or not isinstance(item, str)
                or "\x00" in item
            ):
                raise MigrationError("catalog_invalid")
    elif kind == "streamable-http":
        if set(value) != {"kind", "url"} or not isinstance(value["url"], str):
            raise MigrationError("catalog_invalid")
    else:
        raise MigrationError("catalog_invalid")
    if kind == "stdio":
        return MappingProxyType(
            {
                "kind": kind,
                "command": command,
                "args": tuple(args),
                "env": MappingProxyType(dict(env)),
            }
        )
    return MappingProxyType({"kind": kind, "url": value["url"]})


def validate_request(value: Any) -> PreviewRequest:
    """Validate the closed explicit catalog/selection request."""

    if (
        not isinstance(value, dict)
        or set(value) != {"schema", "fixture_id", "catalog", "selection"}
        or value.get("schema") != REQUEST_SCHEMA
    ):
        raise MigrationError("catalog_invalid")
    fixture_id = _require_identifier(value["fixture_id"], "catalog_invalid")
    if not isinstance(value["catalog"], list) or not value["catalog"]:
        raise MigrationError("catalog_invalid")

    entries: list[CatalogEntry] = []
    connection_ids: set[str] = set()
    for row in value["catalog"]:
        if not isinstance(row, dict):
            raise MigrationError("catalog_invalid")
        management = row.get("management")
        if not isinstance(management, str) or management not in MANAGEMENT:
            raise MigrationError("catalog_invalid")
        common = {"connection_id", "native_name", "owner", "management", "targets"}
        expected = (
            common | {"source_revision", "transport"}
            if management == "registrar-owned"
            else common
        )
        if set(row) != expected:
            raise MigrationError("catalog_invalid")
        connection_id = _require_identifier(row["connection_id"], "catalog_invalid")
        native_name = _require_identifier(row["native_name"], "catalog_invalid")
        owner = _require_identifier(row["owner"], "catalog_invalid")
        targets = _require_targets(row["targets"], "catalog_invalid")
        if connection_id in connection_ids:
            raise MigrationError("catalog_invalid")
        connection_ids.add(connection_id)
        if management == "registrar-owned":
            if owner != SOURCE_OWNER:
                raise MigrationError("source_identity_mismatch")
            revision = row["source_revision"]
            if not isinstance(revision, str) or not _HEX40.fullmatch(revision):
                raise MigrationError("catalog_invalid")
            if revision != SOURCE_REVISION:
                raise MigrationError("source_drift")
            transport = _validate_transport(row["transport"])
        else:
            revision = None
            transport = None
        entries.append(
            CatalogEntry(
                connection_id=connection_id,
                native_name=native_name,
                owner=owner,
                management=management,
                targets=targets,
                source_revision=revision,
                transport=transport,
            )
        )

    if not isinstance(value["selection"], list) or not value["selection"]:
        raise MigrationError("selection_invalid")
    by_id = {entry.connection_id: entry for entry in entries}
    selections: list[Selection] = []
    selected_ids: set[str] = set()
    for row in value["selection"]:
        if not isinstance(row, dict) or set(row) != {"connection_id", "targets"}:
            raise MigrationError("selection_invalid")
        connection_id = _require_identifier(row["connection_id"], "selection_invalid")
        targets = _require_targets(row["targets"], "selection_invalid")
        if connection_id in selected_ids or connection_id not in by_id:
            raise MigrationError("selection_invalid")
        if not set(targets).issubset(by_id[connection_id].targets):
            raise MigrationError("selection_invalid")
        selected_ids.add(connection_id)
        selections.append(Selection(connection_id, targets))

    return PreviewRequest(
        fixture_id=fixture_id,
        catalog=tuple(sorted(entries, key=lambda item: item.connection_id)),
        selection=tuple(sorted(selections, key=lambda item: item.connection_id)),
        request_digest=digest_value(value),
    )


def _json_no_duplicates(path: Path) -> Any:
    def pairs(items: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise MigrationError("catalog_invalid")
            result[key] = value
        return result

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except MigrationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise MigrationError("catalog_invalid") from None


def load_request(path: Path) -> PreviewRequest:
    if not path.is_absolute() or not path.is_file():
        raise MigrationError("catalog_invalid")
    return validate_request(_json_no_duplicates(path))


def _git(repository: Path, *args: str) -> bytes:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
    }
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise MigrationError("source_unavailable") from None
    if result.returncode != 0:
        raise MigrationError("source_unavailable")
    return result.stdout


def _remote_identity(remote: str) -> str | None:
    patterns = (
        r"git@github\.com:(?P<name>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?",
        r"ssh://git@github\.com/(?P<name>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, remote)
        if match:
            return match.group("name")
    return None


def _verify_original_source(repository: Path, revision: str = SOURCE_REVISION) -> None:
    try:
        original_sources.verify_repository(repository, SOURCE_OWNER, revision=revision)
    except ValueError:
        raise MigrationError("source_identity_mismatch") from None


def _verify_source_and_wheel(wheel: Path, repository: Path) -> None:
    if not wheel.is_absolute() or not wheel.is_file() or wheel.is_symlink():
        raise MigrationError("package_unavailable")
    try:
        wheel_info = wheel.stat()
    except OSError:
        raise MigrationError("package_unavailable") from None
    if not stat.S_ISREG(wheel_info.st_mode):
        raise MigrationError("package_unavailable")
    try:
        wheel_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    except OSError:
        raise MigrationError("package_unavailable") from None
    if wheel_digest != WHEEL_SHA256:
        raise MigrationError("package_drift")
    if not repository.is_absolute() or not repository.is_dir() or repository.is_symlink():
        raise MigrationError("source_unavailable")
    try:
        remote = _git(repository, "remote", "get-url", "origin").decode("utf-8").strip()
    except UnicodeError:
        raise MigrationError("source_unavailable") from None
    if _remote_identity(remote) not in (SOURCE_OWNER, "KleinPerkins/kp-mcp-private-original"):
        raise MigrationError("source_identity_mismatch")
    _verify_original_source(repository)
    revision = _git(repository, "rev-parse", SOURCE_REVISION + "^{commit}").decode().strip()
    tree = _git(repository, "rev-parse", SOURCE_REVISION + "^{tree}").decode().strip()
    package_tree = _git(
        repository, "rev-parse", SOURCE_REVISION + ":kp-mcp-bootstrap"
    ).decode().strip()
    if revision != SOURCE_REVISION or tree != SOURCE_TREE or package_tree != PACKAGE_TREE:
        raise MigrationError("source_drift")

    prefix = "kp-mcp-bootstrap/src/"
    paths = (
        _git(repository, "ls-tree", "-r", "--name-only", SOURCE_REVISION, prefix)
        .decode("utf-8")
        .splitlines()
    )
    python_paths = sorted(path for path in paths if path.endswith(".py"))
    source_hashes: dict[str, str] = {}
    try:
        with zipfile.ZipFile(wheel) as archive:
            packaged = {
                name
                for name in archive.namelist()
                if name.startswith("kp_mcp_bootstrap/") and name.endswith(".py")
            }
            expected_packaged = {path.removeprefix(prefix) for path in python_paths}
            if packaged != expected_packaged:
                raise MigrationError("package_drift")
            for path in python_paths:
                source_bytes = _git(repository, "show", SOURCE_REVISION + ":" + path)
                if archive.read(path.removeprefix(prefix)) != source_bytes:
                    raise MigrationError("package_drift")
                source_hashes[path] = hashlib.sha256(source_bytes).hexdigest()
    except MigrationError:
        raise
    except (OSError, KeyError, zipfile.BadZipFile):
        raise MigrationError("package_drift") from None
    adapter_hashes = {
        path: digest
        for path, digest in source_hashes.items()
        if "/registrars/" in path or path.endswith("/errors.py")
    }
    if hashlib.sha256(canonical_json_bytes(adapter_hashes)).hexdigest() != ADAPTER_SOURCE_DIGEST:
        raise MigrationError("source_drift")


def _module_origin_is_wheel(module: Any, wheel: Path) -> bool:
    origin = getattr(module, "__file__", None)
    return isinstance(origin, str) and origin.startswith(str(wheel.resolve()) + "/")


def load_owner_api(wheel: Path, repository: Path) -> BoundOwnerAPI:
    """Verify and load only the exact merged, unreleased owner API."""

    _verify_source_and_wheel(wheel, repository)
    loaded = sys.modules.get("kp_mcp_bootstrap")
    if loaded is not None and not _module_origin_is_wheel(loaded, wheel):
        raise MigrationError("api_drift")
    before_modules = set(sys.modules)
    sys.path.insert(0, str(wheel.resolve()))
    try:
        package = importlib.import_module("kp_mcp_bootstrap")
        registrars = importlib.import_module("kp_mcp_bootstrap.registrars")
    except Exception:
        for name in set(sys.modules) - before_modules:
            if name == "kp_mcp_bootstrap" or name.startswith("kp_mcp_bootstrap."):
                sys.modules.pop(name, None)
        raise MigrationError("api_unavailable") from None
    finally:
        try:
            sys.path.remove(str(wheel.resolve()))
        except ValueError:
            pass
    if (
        getattr(package, "__version__", None) != PACKAGE_VERSION
        or not _module_origin_is_wheel(package, wheel)
        or not _module_origin_is_wheel(registrars, wheel)
    ):
        raise MigrationError("api_drift")

    required = (
        "SourceIdentity",
        "RegistrationDefinition",
        "AuthBinding",
        "RegistrarError",
        "fixture_context",
    )
    if any(not hasattr(registrars, name) for name in required):
        raise MigrationError("api_drift")
    classes: dict[str, type] = {}
    for target, expected in ADAPTER_BINDINGS.items():
        registrar_class = getattr(registrars, expected["class"], None)
        if not isinstance(registrar_class, type):
            raise MigrationError("api_drift")
        try:
            registrar = registrar_class()
            inspection_signature = str(inspect.signature(registrar.inspect_registration))
            preview_signature = str(inspect.signature(registrar.preview))
            mapping_version = registrar.MAPPING_VERSION
            mapping_digest = registrar.mapping_digest
        except Exception:
            raise MigrationError("api_drift") from None
        if (
            mapping_version != expected["mapping_version"]
            or mapping_digest != expected["mapping_digest"]
            or inspection_signature != INSPECTION_SIGNATURE
            or preview_signature != PREVIEW_SIGNATURE
        ):
            raise MigrationError("api_drift")
        classes[target] = registrar_class
    return BoundOwnerAPI(
        registrar_classes=MappingProxyType(classes),
        SourceIdentity=registrars.SourceIdentity,
        RegistrationDefinition=registrars.RegistrationDefinition,
        AuthBinding=registrars.AuthBinding,
        RegistrarError=registrars.RegistrarError,
        fixture_context=registrars.fixture_context,
    )


def _enum_value(value: Any) -> str:
    candidate = getattr(value, "value", value)
    if not isinstance(candidate, str) or not _REASON.fullmatch(candidate):
        raise MigrationError("owner_api_failed")
    return candidate


def _reason_values(values: Sequence[Any]) -> list[str]:
    return sorted({_enum_value(item) for item in values})


def _definition(api: BoundOwnerAPI, entry: CatalogEntry) -> Any:
    try:
        identity = api.SourceIdentity(
            source_owner=entry.owner,
            connection_id=entry.connection_id,
            source_revision=entry.source_revision,
            native_name=entry.native_name,
        )
        assert entry.transport is not None
        if entry.transport["kind"] == "stdio":
            return api.RegistrationDefinition.stdio(
                identity,
                command=entry.transport["command"],
                args=tuple(entry.transport["args"]),
                env=dict(entry.transport["env"]),
            )
        return api.RegistrationDefinition.streamable_http(
            identity, url=entry.transport["url"]
        )
    except (MigrationError, KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        raise MigrationError("definition_invalid") from None


def _tree_snapshot(
    root: Path,
) -> tuple[tuple[str, str, int, int, int, int, str | None], ...]:
    rows: list[tuple[str, str, int, int, int, int, str | None]] = []
    for path in (root, *sorted(root.rglob("*"))):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISDIR(info.st_mode):
            rows.append(
                (
                    relative,
                    "directory",
                    mode,
                    info.st_size,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                    None,
                )
            )
        elif stat.S_ISREG(info.st_mode):
            rows.append(
                (
                    relative,
                    "file",
                    mode,
                    info.st_size,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
        else:
            rows.append(
                (
                    relative,
                    "unsupported",
                    mode,
                    info.st_size,
                    info.st_mtime_ns,
                    info.st_ctime_ns,
                    None,
                )
            )
    return tuple(rows)


def _entry_result(
    *,
    request: PreviewRequest,
    entry: CatalogEntry,
    target: str,
    definition: Any,
    registrar: Any,
    api: BoundOwnerAPI,
    fixture_base: Path,
    seed: bytes | None,
) -> dict[str, Any]:
    mapping = ADAPTER_BINDINGS[target]
    inspection = None
    preview = None
    owner_reasons: list[str] = []
    conflicts: list[str] = []
    proposed: list[str] = []
    preserved: list[str] = []
    try:
        auth_binding = api.AuthBinding.none(
            binding_id=f"int014-fixture-none:{entry.connection_id}:{target}",
            host="fixture",
            surface=registrar.SURFACE,
            scope="user",
            target_origin_digest=definition.target_origin_digest,
        )
        with api.fixture_context(
            registrar,
            definition,
            fixture_root=fixture_base,
            auth_binding=auth_binding,
        ) as fixture:
            if seed is not None:
                if not isinstance(seed, bytes) or len(seed) > 65536:
                    raise MigrationError("catalog_invalid")
                fixture.config_path.write_bytes(seed)
                fixture.config_path.chmod(0o600)
            before = _tree_snapshot(fixture.root)
            try:
                inspection = registrar.inspect_registration(
                    fixture.config_path, context=fixture.context
                )
                preview = registrar.preview(
                    fixture.config_path, definition, context=fixture.context
                )
            except api.RegistrarError as error:
                owner_reasons.extend(
                    _reason_values(
                        getattr(
                            error,
                            "reason_codes",
                            (getattr(error, "code", None),),
                        )
                    )
                )
            after = _tree_snapshot(fixture.root)
            if before != after:
                raise MigrationError("fixture_write_detected")
            seed_digest = hashlib.sha256(seed).hexdigest() if seed is not None else None
    except MigrationError:
        raise
    except (KeyboardInterrupt, SystemExit):
        raise
    except api.RegistrarError as error:
        raise MigrationError(
            *_reason_values(
                getattr(error, "reason_codes", (getattr(error, "code", None),))
            )
        ) from None
    except Exception:
        raise MigrationError("owner_api_failed") from None

    if inspection is not None:
        owner_reasons.extend(_reason_values(inspection.reason_codes))
        owner_reasons.append("ownership_" + _enum_value(inspection.ownership))
    if preview is not None:
        conflicts = _reason_values(preview.conflicts)
        owner_reasons.extend(conflicts)
        proposed = sorted({item.path for item in preview.owned_leaf_actions})
        preserved = sorted(set(preview.preserved_paths))
        owner_reasons.append("preview_conflict" if conflicts else "preview_ready")
    elif not owner_reasons:
        owner_reasons.append("owner_api_failed")
    owner_reasons.extend(
        (
            "fixture_only",
            "fixture_zero_writes",
            "concurrency_unqualified",
            "not_adoption",
            "not_mirror_retirement",
            "not_native_qualification",
        )
    )
    for code in owner_reasons:
        if not _REASON.fullmatch(code):
            raise MigrationError("owner_api_failed")
    return {
        "ids": {
            "fixture_id": request.fixture_id,
            "connection_id": entry.connection_id,
            "native_name": entry.native_name,
            "owner": entry.owner,
            "adapter": target,
        },
        "digests": {
            "definition": definition.digest,
            "mapping": mapping["mapping_digest"],
            "fixture_preimage": seed_digest,
        },
        "proposed_owned_paths": proposed,
        "preserved_paths": preserved,
        "reason_codes": sorted(set(owner_reasons)),
        "conflicts": conflicts,
    }


@contextmanager
def _fixture_directory(parent: Path):
    try:
        if not parent.is_absolute() or not parent.is_dir():
            raise MigrationError("catalog_invalid")
        with tempfile.TemporaryDirectory(prefix="int014-mcp-preview-", dir=parent) as name:
            base = Path(name)
            base.chmod(0o700)
            yield base
    except OSError:
        raise MigrationError("fixture_unavailable") from None


def preview_migration(
    request: PreviewRequest,
    api: BoundOwnerAPI,
    *,
    fixture_parent: Path,
    fixture_preimages: Mapping[tuple[str, str], bytes] | None = None,
) -> dict[str, Any]:
    """Return a deterministic redacted fixture preview for explicit selections."""

    entries = {entry.connection_id: entry for entry in request.catalog}
    selected_pairs = {
        (selection.connection_id, target)
        for selection in request.selection
        for target in selection.targets
    }
    seeds = dict(fixture_preimages or {})
    if any(key not in selected_pairs for key in seeds):
        raise MigrationError("selection_invalid")
    results: list[dict[str, Any]] = []
    native_claims: dict[tuple[str, str], list[CatalogEntry]] = {}
    for entry in request.catalog:
        for target in entry.targets:
            native_claims.setdefault((target, entry.native_name), []).append(entry)
    with _fixture_directory(fixture_parent) as base:
        for selection in request.selection:
            entry = entries[selection.connection_id]
            for target in selection.targets:
                colliders = native_claims[(target, entry.native_name)]
                owner_conflict = len(colliders) > 1
                external_collision = any(
                    item.management == "external-app" for item in colliders
                )
                if entry.management == "external-app":
                    results.append(
                        {
                            "ids": {
                                "fixture_id": request.fixture_id,
                                "connection_id": entry.connection_id,
                                "native_name": entry.native_name,
                                "owner": entry.owner,
                                "adapter": target,
                            },
                            "digests": {
                                "definition": None,
                                "mapping": ADAPTER_BINDINGS[target]["mapping_digest"],
                                "fixture_preimage": None,
                            },
                            "proposed_owned_paths": [],
                            "preserved_paths": [],
                            "reason_codes": [
                                "concurrency_unqualified",
                                "external_owner",
                                "fixture_only",
                                "local_registration_not_proposed",
                                "not_adoption",
                                "not_mirror_retirement",
                                "not_native_qualification",
                                *(["owner_conflict"] if owner_conflict else []),
                            ],
                            "conflicts": ["owner_conflict"] if owner_conflict else [],
                        }
                    )
                    continue
                definition = _definition(api, entry)
                if owner_conflict:
                    results.append(
                        {
                            "ids": {
                                "fixture_id": request.fixture_id,
                                "connection_id": entry.connection_id,
                                "native_name": entry.native_name,
                                "owner": entry.owner,
                                "adapter": target,
                            },
                            "digests": {
                                "definition": definition.digest,
                                "mapping": ADAPTER_BINDINGS[target]["mapping_digest"],
                                "fixture_preimage": None,
                            },
                            "proposed_owned_paths": [],
                            "preserved_paths": [],
                            "reason_codes": sorted(
                                {
                                    "concurrency_unqualified",
                                    "fixture_only",
                                    "local_registration_not_proposed",
                                    "not_adoption",
                                    "not_mirror_retirement",
                                    "not_native_qualification",
                                    "owner_conflict",
                                    *(("external_owner",) if external_collision else ()),
                                }
                            ),
                            "conflicts": ["owner_conflict"],
                        }
                    )
                    continue
                registrar_class = api.registrar_classes.get(target)
                if registrar_class is None:
                    raise MigrationError("unsupported_surface")
                results.append(
                    _entry_result(
                        request=request,
                        entry=entry,
                        target=target,
                        definition=definition,
                        registrar=registrar_class(),
                        api=api,
                        fixture_base=base,
                        seed=seeds.get((entry.connection_id, target)),
                    )
                )
    results.sort(key=lambda row: (row["ids"]["connection_id"], row["ids"]["adapter"]))
    aggregate_conflicts = sorted(
        {code for row in results for code in row["conflicts"]}
    )
    return {
        "schema": RESULT_SCHEMA,
        "ids": {"fixture_id": request.fixture_id},
        "digests": {
            "request": request.request_digest,
            "source_revision": api.source_revision,
            "source_tree": api.source_tree,
            "package_tree": api.package_tree,
            "wheel": api.wheel_sha256,
            "adapter_source": api.adapter_source_digest,
        },
        "reason_codes": [
            "concurrency_unqualified",
            "fixture_only",
            "not_adoption",
            "not_mirror_retirement",
            "not_native_qualification",
        ],
        "conflicts": aggregate_conflicts,
        "entries": results,
    }


def error_result(error: MigrationError) -> dict[str, Any]:
    return {
        "schema": ERROR_SCHEMA,
        "ids": {},
        "digests": {},
        "reason_codes": list(error.reason_codes),
        "conflicts": list(error.reason_codes),
    }


# Separate D1 0.4 operation binding. The historical 0.3 fixture API above keeps
# its pins and behavior. Loading this API grants neither admission nor approval.
MAINTENANCE_SOURCE_REVISION = "3c1f05e596dc3cbd24d99334686193e172edb464"
MAINTENANCE_SOURCE_TREE = "c6bc485a4b9e8019ffca2a2f96c75db364423de4"
MAINTENANCE_PACKAGE_TREE = "f8664d10c243d678f2553cfde73ae7f792bda6b6"
MAINTENANCE_WHEEL_SHA256 = "cb0269938c39bf089b540010cdcb836ced51ea7a208dd05dc134b61bcb681c2e"
MAINTENANCE_ADAPTER_DIGEST = "1c187bb184c0dc7f61a894699e336666601754d67c3c7669966ee759d64ac006"
SUPPORTED_CONTROL_PROFILES: tuple[str, ...] = ()
MAINTENANCE_SIGNATURES = MappingProxyType({
    "prepare": "(preview: 'Preview') -> 'PreparedOperation'",
    "apply": "(prepared: 'PreparedOperation', approval: 'Approval') -> 'Result'",
    "load_prepared": "(record_id: 'str', *, context: 'RegistrationContext', definition: 'RegistrationDefinition | None') -> 'PreparedOperation'",
    "prepare_recovery": "(prepared: 'PreparedOperation', disposition: 'Any', *, context: 'RegistrationContext | None' = None) -> 'PreparedOperation'",
    "prepare_cancel": "(prepared: 'PreparedOperation', *, context: 'RegistrationContext | None' = None) -> 'PreparedOperation'",
    "recover": "(prepared: 'PreparedOperation', disposition: 'Any', approval: 'Approval') -> 'Result'",
    "rollback": "(operation_ref: 'OperationRef', *, context: 'RegistrationContext') -> 'Preview'",
})


@dataclass(frozen=True)
class BoundMaintenanceAPI:
    registrars: Any = field(repr=False)
    wheel: Path = field(repr=False)
    repository: Path = field(repr=False)

    def recheck(self) -> None:
        try:
            if (self.wheel.is_symlink()
                or hashlib.sha256(self.wheel.read_bytes()).hexdigest() != MAINTENANCE_WHEEL_SHA256
                or _remote_identity(_git(self.repository, "remote", "get-url", "origin").decode().strip()) not in (SOURCE_OWNER, "KleinPerkins/kp-mcp-private-original")):
                raise MigrationError("source_drift")
            _verify_original_source(self.repository, MAINTENANCE_SOURCE_REVISION)
        except (OSError, UnicodeError):
            raise MigrationError("source_unavailable") from None
        if any(not _module_origin_is_wheel(module, self.wheel)
               for name, module in sys.modules.items()
               if name == "kp_mcp_bootstrap" or name.startswith("kp_mcp_bootstrap.")):
            raise MigrationError("api_drift")


def load_maintenance_api(wheel: Path, repository: Path) -> BoundMaintenanceAPI:
    try:
        return _load_maintenance_api(wheel, repository)
    except MigrationError:
        raise
    except Exception:
        raise MigrationError("api_unavailable") from None


def _load_maintenance_api(wheel: Path, repository: Path) -> BoundMaintenanceAPI:
    """Byte-verify the separate D1 package before importing; no installation.

    Mixed 0.3/0.4 imports require a fresh process. Every Python wheel member is
    checked against immutable owner Git objects, not the owner's working tree.
    """
    if (not wheel.is_absolute() or not wheel.is_file() or wheel.is_symlink()
        or not repository.is_absolute() or not repository.is_dir() or repository.is_symlink()):
        raise MigrationError("source_unavailable")
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != MAINTENANCE_WHEEL_SHA256:
        raise MigrationError("package_drift")
    if _remote_identity(_git(repository, "remote", "get-url", "origin").decode().strip()) not in (SOURCE_OWNER, "KleinPerkins/kp-mcp-private-original"):
        raise MigrationError("source_identity_mismatch")
    _verify_original_source(repository, MAINTENANCE_SOURCE_REVISION)
    for expression, expected in (("^{commit}", MAINTENANCE_SOURCE_REVISION),
                                  ("^{tree}", MAINTENANCE_SOURCE_TREE),
                                  (":kp-mcp-bootstrap", MAINTENANCE_PACKAGE_TREE)):
        if _git(repository, "rev-parse", MAINTENANCE_SOURCE_REVISION + expression).decode().strip() != expected:
            raise MigrationError("source_drift")
    prefix = "kp-mcp-bootstrap/src/"
    paths = sorted(p for p in _git(repository, "ls-tree", "-r", "--name-only",
                                  MAINTENANCE_SOURCE_REVISION, prefix).decode().splitlines() if p.endswith(".py"))
    hashes = {}
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or {n for n in names if n.endswith(".py")} != {p[len(prefix):] for p in paths}:
            raise MigrationError("package_drift")
        for path in paths:
            data = _git(repository, "show", MAINTENANCE_SOURCE_REVISION + ":" + path)
            if archive.read(path[len(prefix):]) != data:
                raise MigrationError("package_drift")
            if "/registrars/" in path or path.endswith("/errors.py"):
                hashes[path] = hashlib.sha256(data).hexdigest()
    if digest_value(hashes) != MAINTENANCE_ADAPTER_DIGEST:
        raise MigrationError("source_drift")
    if any(not _module_origin_is_wheel(module, wheel) for name, module in sys.modules.items()
           if name == "kp_mcp_bootstrap" or name.startswith("kp_mcp_bootstrap.")):
        raise MigrationError("api_drift")
    before = set(sys.modules)
    sys.path.insert(0, str(wheel.resolve()))
    try:
        package = importlib.import_module("kp_mcp_bootstrap")
        api = importlib.import_module("kp_mcp_bootstrap.registrars")
        if package.__version__ != "0.4.0":
            raise MigrationError("api_drift")
        for binding in ADAPTER_BINDINGS.values():
            registrar = getattr(api, binding["class"])()
            if (registrar.mapping_digest != binding["mapping_digest"]
                or registrar.MAPPING_VERSION != binding["mapping_version"]
                or str(inspect.signature(registrar.preview)) != PREVIEW_SIGNATURE
                or str(inspect.signature(registrar.inspect_registration)) != INSPECTION_SIGNATURE
                or any(str(inspect.signature(getattr(registrar, name))) != expected
                       for name, expected in MAINTENANCE_SIGNATURES.items())):
                raise MigrationError("api_drift")
        if str(inspect.signature(api.operation_ref)) != "(prepared: 'PreparedOperation', *, pending: 'bool' = False, maintenance_validator: 'Any' = None) -> 'OperationRef'":
            raise MigrationError("api_drift")
        bound = BoundMaintenanceAPI(api, wheel.resolve(), repository)
        bound.recheck()
        return bound
    except Exception:
        for name in set(sys.modules) - before:
            if name == "kp_mcp_bootstrap" or name.startswith("kp_mcp_bootstrap."):
                sys.modules.pop(name, None)
        raise MigrationError("api_drift") from None
    finally:
        sys.path.remove(str(wheel.resolve()))


def open_maintenance_operation(*, control_profile: str) -> None:
    """Production entry gate; no supported native pause/drain profile exists.

    Independent transaction helpers below are exercised with disposable test
    observations. They are not a replacement for the missing control resolver.
    """
    raise MigrationError("concurrency_unqualified")


class MaintenanceOperations:
    """Partial D2 transaction plumbing; caller still owns control/handoff proof.

    Every public registrar call holds the existing cooperative barrier. No
    success here releases maintenance or resumes a writer. D1's empty admission
    table and the production entry gate remain closed. Tests inject admission
    in their own process only; this class never enrolls a caller or observer.
    """
    def __init__(self, api: BoundMaintenanceAPI, validator: Any, checks: Any,
                 *, host: str, approvals: Any):
        api.recheck()
        if (host not in ADAPTER_BINDINGS or validator.observations.checks is not checks
            or validator.observations.approvals is not approvals):
            raise MigrationError("concurrency_unqualified")
        self.api, self.validator, self.checks, self.approvals = api, validator, checks, approvals
        self.registrar = getattr(api.registrars, ADAPTER_BINDINGS[host]["class"])(maintenance_validator=validator)

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self.api.recheck()
        with self.validator.operation():
            return getattr(self.registrar, name)(*args, **kwargs)

    def preview(self, context: Any, definition: Any) -> Any:
        self.checks.bind(context, definition)
        return self._call("preview", context.config_path, definition, context=context)

    def prepare(self, preview: Any) -> Any:
        self.checks.bind(preview._private.context, preview._private.definition)
        return self._call("prepare", preview)

    def load(self, record_id: str, *, context: Any, definition: Any) -> Any:
        self.checks.bind(context, definition)
        return self._call("load_prepared", record_id, context=context, definition=definition)

    def apply(self, prepared: Any, approval: Any) -> Any:
        self.checks.bind(prepared._context, prepared._definition)
        return self._call("apply", prepared, approval)

    def prepare_recovery(self, original: Any, disposition: Any, *, context: Any) -> Any:
        self.checks.bind(context, original._definition)
        return self._call("prepare_recovery", original, disposition, context=context)

    def prepare_cancel(self, original: Any, *, context: Any) -> Any:
        self.checks.bind(context, original._definition)
        return self._call("prepare_cancel", original, context=context)

    def recover(self, prepared: Any, disposition: Any, approval: Any) -> Any:
        self.checks.bind(prepared._context, prepared._definition)
        return self._call("recover", prepared, disposition, approval)

    def rollback(self, reference: Any, *, context: Any, definition: Any) -> Any:
        self.checks.bind(context, definition)
        return self._call("rollback", reference, context=context)

    def operation_ref(self, prepared: Any, *, pending: bool = False) -> Any:
        self.api.recheck()
        self.checks.bind(prepared._context, prepared._definition)
        with self.validator.operation():
            return self.api.registrars.operation_ref(prepared, pending=pending,
                                                     maintenance_validator=self.validator)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--source-repository", type=Path, required=True)
    parser.add_argument("--fixture-parent", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request = load_request(args.request)
        api = load_owner_api(args.wheel, args.source_repository)
        result = preview_migration(
            request, api, fixture_parent=args.fixture_parent
        )
    except MigrationError as error:
        print(json.dumps(error_result(error), sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
