"""Closed typed trigger registry and safe hook/job projections."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .canonical import canonical_json, parse_json_object
from .validators import require_valid


CATALOG_FIELDS = {
    "schema",
    "version",
    "triggers",
    "legacy_v1_migration",
}
TRIGGER_FIELDS = {
    "schema",
    "id",
    "event",
    "detector",
    "action",
    "template",
    "verifier",
    "capability",
    "semantic_mutation",
}
LEGACY_FIELDS = {"legacy_id", "v2_trigger_id", "incompatibilities"}


@dataclass(frozen=True)
class TriggerSpec:
    id: str
    event: str
    detector: str
    action: str
    template: str
    verifier: str
    capability: str
    semantic_mutation: bool = False
    schema: str = "doc-warden/trigger/v2"

    def catalog_record(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "id": self.id,
            "event": self.event,
            "detector": self.detector,
            "action": self.action,
            "template": self.template,
            "verifier": self.verifier,
            "capability": self.capability,
            "semantic_mutation": self.semantic_mutation,
        }


@dataclass(frozen=True)
class LegacyTriggerMigration:
    legacy_id: int
    v2_trigger_id: str
    incompatibilities: tuple[str, ...]

    def catalog_record(self) -> dict[str, Any]:
        return {
            "legacy_id": self.legacy_id,
            "v2_trigger_id": self.v2_trigger_id,
            "incompatibilities": list(self.incompatibilities),
        }


def _detector(expected: str) -> Callable[[Mapping[str, Any]], bool]:
    def detect(context: Mapping[str, Any]) -> bool:
        return context.get("event") == expected

    return detect


def _detect_significant_file_edit(context: Mapping[str, Any]) -> bool:
    if context.get("event") != "significant_file_edit":
        return False
    repository_value = context.get("repository")
    file_path_value = context.get("file_path")
    if (
        not isinstance(repository_value, str)
        or not repository_value
        or not isinstance(file_path_value, str)
        or not file_path_value
    ):
        return False
    try:
        repository = Path(repository_value).expanduser().resolve(strict=True)
        file_path = Path(file_path_value).expanduser().resolve(strict=True)
        relative = file_path.relative_to(repository)
    except (OSError, ValueError):
        return False
    if not repository.is_dir() or not file_path.is_file():
        return False
    if relative.parts[:2] == (".planning", "generated"):
        return False
    if relative.name.endswith(".canvas.tsx"):
        return False
    return True


def _report(
    status: str,
    code: str,
    *,
    checked: tuple[str, ...],
    uncertain: tuple[str, ...],
    next_action: str,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    def action(_context: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "status": status,
            "code": code,
            "checked": list(checked),
            "uncertain": list(uncertain),
            "next_action": next_action,
            "repository_writes": [],
        }

    return action


def _verify_no_repository_writes(payload: Mapping[str, Any]) -> bool:
    return payload.get("repository_writes") == []


def _template(name: str) -> Callable[[], str]:
    return lambda: name


DETECTOR_HANDLERS: dict[str, Callable[[Mapping[str, Any]], bool]] = {
    "detect_artifact_transition": _detector("artifact_transition"),
    "detect_authoring_pre_import": _detector("authoring_pre_import"),
    "detect_authoring_result_import": _detector("authoring_result_import"),
    "detect_artifact_completion": _detector("artifact_completion"),
    "detect_defect_transition": _detector("defect_transition"),
    "detect_reconciliation_preview": _detector("reconciliation_preview"),
    "detect_session_start": _detector("session_start"),
    "detect_significant_file_edit": _detect_significant_file_edit,
    "detect_external_design_refresh": _detector("external_design_refresh"),
    "detect_repository_dependency_change": _detector(
        "repository_dependency_change"
    ),
    "detect_routine_maintenance": _detector("routine_maintenance"),
}


def _projection_marker_path(
    repository: Path,
    state_home: Path,
) -> Path:
    identity = hashlib.sha256(str(repository.resolve()).encode("utf-8")).hexdigest()
    return state_home / "doc-warden" / "freshness" / f"{identity}.json"


def _projection_state_home(value: object = None) -> Path:
    return Path(
        str(
            value
            or os.environ.get(
                "XDG_STATE_HOME",
                str(Path.home() / ".local/state"),
            )
        )
    ).expanduser()


def _projection_marker_target(
    context: Mapping[str, Any],
) -> tuple[Path, Path]:
    repository_value = context.get("repository")
    if not isinstance(repository_value, str) or not repository_value:
        raise ValueError("hook_repository_unavailable")
    repository = Path(repository_value).resolve(strict=True)
    if not repository.is_dir():
        raise ValueError("hook_repository_unavailable")
    state_home = _projection_state_home(context.get("state_home"))
    return repository, _projection_marker_path(repository, state_home)


def _read_projection_marker(destination: Path) -> bytes | None:
    if not destination.is_file() or destination.is_symlink():
        return None
    try:
        return destination.read_bytes()
    except OSError:
        return None


@contextmanager
def _projection_marker_lock(destination: Path) -> Iterator[None]:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(destination.with_suffix(".lock"), flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("projection_freshness_lock_invalid")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _replace_projection_marker(destination: Path, content: bytes) -> None:
    descriptor, staged_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    staged = Path(staged_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, destination)
    finally:
        if staged.exists():
            staged.unlink()


def _parse_projection_marker(content: bytes) -> dict[str, Any]:
    payload = json.loads(content.decode("utf-8"))
    hook_egress(payload)
    return payload


def _revision_contains(
    repository: Path,
    earlier: str,
    later: str,
) -> bool:
    if earlier == later:
        return True
    if any(
        re.fullmatch(r"[0-9a-f]{40}", revision) is None
        for revision in (earlier, later)
    ):
        return False
    return (
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "merge-base",
                "--is-ancestor",
                earlier,
                later,
            ],
            check=False,
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )


def _revision_is_repository_commit(
    repository: Path,
    revision: str,
) -> bool:
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        return False
    return (
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "cat-file",
                "-e",
                f"{revision}^{{commit}}",
            ],
            check=False,
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )


def projection_freshness_preimage(
    repository: Path,
    state_home: Path,
) -> bytes | None:
    destination = _projection_marker_path(
        repository.resolve(strict=True),
        state_home,
    )
    if destination.is_symlink():
        raise ValueError("projection_freshness_marker_unavailable")
    if not destination.exists():
        return None
    content = _read_projection_marker(destination)
    if content is None:
        raise ValueError("projection_freshness_marker_unavailable")
    return content


_PROJECTION_MARKER_LIMIT = 256
_PROJECTION_DIRECTORY_ENTRY_LIMIT = 1024
_PROJECTION_MARKER_BYTE_LIMIT = 64 * 1024
_PROJECTION_MARKER_NAME = re.compile(r"[0-9a-f]{64}\.json")


def _read_bounded_projection_marker(
    destination: Path,
) -> tuple[str, bytes | None]:
    if destination.is_symlink():
        return "unavailable", None
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(destination, flags)
    except OSError:
        return "unavailable", None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return "unavailable", None
        chunks: list[bytes] = []
        remaining = _PROJECTION_MARKER_BYTE_LIMIT + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    except OSError:
        return "unavailable", None
    finally:
        os.close(descriptor)
    content = b"".join(chunks)
    if len(content) > _PROJECTION_MARKER_BYTE_LIMIT:
        return "malformed", None
    return "read", content


def inspect_projection_freshness(
    state_home: Path,
) -> dict[str, int | bool]:
    """Inspect the bounded machine-local marker set without changing it."""

    freshness_root = (
        Path(state_home).expanduser() / "doc-warden" / "freshness"
    )
    if freshness_root.is_symlink():
        return {
            "pending_count": 0,
            "malformed_count": 0,
            "unavailable_count": 1,
            "scan_limited": False,
        }
    names: list[str] = []
    try:
        with os.scandir(freshness_root) as entries:
            for entry in entries:
                if len(names) == _PROJECTION_DIRECTORY_ENTRY_LIMIT:
                    return {
                        "pending_count": 0,
                        "malformed_count": 0,
                        "unavailable_count": 0,
                        "scan_limited": True,
                    }
                names.append(entry.name)
    except FileNotFoundError:
        return {
            "pending_count": 0,
            "malformed_count": 0,
            "unavailable_count": 0,
            "scan_limited": False,
        }
    except OSError:
        return {
            "pending_count": 0,
            "malformed_count": 0,
            "unavailable_count": 1,
            "scan_limited": False,
        }

    marker_names = sorted(
        name for name in names if name.endswith(".json")
    )
    if len(marker_names) > _PROJECTION_MARKER_LIMIT:
        return {
            "pending_count": 0,
            "malformed_count": 0,
            "unavailable_count": 0,
            "scan_limited": True,
        }

    pending = 0
    malformed = 0
    unavailable = 0
    for name in marker_names:
        if _PROJECTION_MARKER_NAME.fullmatch(name) is None:
            malformed += 1
            continue
        read_status, content = _read_bounded_projection_marker(
            freshness_root / name
        )
        if read_status == "unavailable":
            unavailable += 1
            continue
        if read_status == "malformed" or content is None:
            malformed += 1
            continue
        try:
            _parse_projection_marker(content)
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            malformed += 1
            continue
        pending += 1

    return {
        "pending_count": pending,
        "malformed_count": malformed,
        "unavailable_count": unavailable,
        "scan_limited": False,
    }


_NO_REFRESH = object()


def reconcile_projection_freshness(
    repository: Path,
    state_home: Path,
    source_revision: str,
    *,
    refresh_preimage: bytes | None | object = _NO_REFRESH,
) -> dict[str, Any] | None:
    repository = repository.resolve(strict=True)
    destination = _projection_marker_path(repository, state_home)
    if refresh_preimage is None:
        if destination.is_symlink() or destination.exists():
            raise ValueError(
                "projection_freshness_changed_during_refresh"
            )
        return None
    if _read_projection_marker(destination) is None:
        return None
    with _projection_marker_lock(destination):
        content = _read_projection_marker(destination)
        if content is None:
            return None
        try:
            payload = _parse_projection_marker(content)
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return None
        if refresh_preimage is not _NO_REFRESH and content != refresh_preimage:
            return payload
        marker_revision = str(payload["source_revision"])
        if (
            subprocess.check_output(
                ["git", "-C", str(repository), "rev-parse", "HEAD"],
                text=True,
            ).strip()
            != source_revision
        ):
            return payload
        if not _revision_contains(
            repository,
            marker_revision,
            source_revision,
        ) and (
            refresh_preimage is _NO_REFRESH
            or not _revision_is_repository_commit(
                repository,
                marker_revision,
            )
        ):
            return payload
        if refresh_preimage is not _NO_REFRESH:
            destination.unlink()
            return None
        if marker_revision != source_revision:
            payload = {**payload, "source_revision": source_revision}
            hook_egress(payload)
            _replace_projection_marker(destination, canonical_json(payload))
        return payload


def _write_projection_stale(
    context: Mapping[str, Any],
) -> dict[str, Any]:
    repository, destination = _projection_marker_target(context)
    source_revision = context.get("source_revision")
    if not isinstance(source_revision, str) or not source_revision:
        source_revision = subprocess.check_output(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    payload = {
        "schema": "doc-warden/hook-report/v1",
        "event": "significant_file_edit",
        "status": "potentially_stale",
        "code": "projection_freshness_unknown",
        "repository_key": context.get("repository_key"),
        "source_revision": source_revision,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "checked": ["repository_identity", "source_revision"],
        "uncertain": ["generated_projection_freshness"],
        "next_action": "refresh_governance_view",
        "repository_writes": [],
    }
    hook_egress(payload)
    with _projection_marker_lock(destination):
        _replace_projection_marker(destination, canonical_json(payload))
    return payload


ACTION_HANDLERS: dict[
    str, Callable[[Mapping[str, Any]], dict[str, Any]]
] = {
    "preview_artifact_transition": _report(
        "proposed",
        "artifact_transition_preview",
        checked=("artifact_state", "transition_contract"),
        uncertain=("operator_confirmation",),
        next_action="review_preview",
    ),
    "prepare_authoring_import": _report(
        "proposed",
        "authoring_import_preflight",
        checked=("runtime_binding", "authority_inputs"),
        uncertain=("authoring_result",),
        next_action="invoke_authoring_workflow",
    ),
    "validate_authoring_result": _report(
        "proposed",
        "authoring_result_validation",
        checked=("result_contract", "authority_bindings"),
        uncertain=("operator_acceptance",),
        next_action="review_import_preview",
    ),
    "preview_completion": _report(
        "proposed",
        "completion_preview",
        checked=("completion_evidence",),
        uncertain=("operator_acceptance",),
        next_action="review_completion_preview",
    ),
    "preview_defect_transition": _report(
        "proposed",
        "defect_transition_preview",
        checked=("defect_lifecycle",),
        uncertain=("operator_confirmation",),
        next_action="review_preview",
    ),
    "reconcile": _report(
        "observed",
        "reconciliation_preview",
        checked=("authorities", "projections", "observations"),
        uncertain=("semantic_conflicts",),
        next_action="review_findings",
    ),
    "report_session_context": _report(
        "observed",
        "session_context",
        checked=("repository_status", "projection_freshness"),
        uncertain=("unavailable_external_sources",),
        next_action="open_governance_view",
    ),
    "mark_projection_stale": _write_projection_stale,
    "compare_external_revision": _report(
        "observed",
        "external_revision_comparison",
        checked=("recorded_revision", "recorded_export_digest"),
        uncertain=("live_external_revision",),
        next_action="refresh_external_observation",
    ),
    "observe_repository_dependency": _report(
        "observed",
        "repository_dependency_observation",
        checked=("recorded_dependency", "source_revision"),
        uncertain=("unavailable_repository",),
        next_action="refresh_dependency_projection",
    ),
    "doctor_refresh_projections": _report(
        "observed",
        "maintenance_report",
        checked=("fleet_conformance", "projection_freshness"),
        uncertain=("unavailable_repositories",),
        next_action="review_maintenance_report",
    ),
}

TEMPLATE_HANDLERS: dict[str, Callable[[], str]] = {
    name: _template(name)
    for name in (
        "artifact",
        "authoring_import",
        "authoring_result",
        "canvas",
        "completion",
        "defect",
        "none",
        "reconciliation",
    )
}

VERIFIER_HANDLERS: dict[str, Callable[[Mapping[str, Any]], bool]] = {
    "verify_artifact": _verify_no_repository_writes,
    "verify_runtime_binding": _verify_no_repository_writes,
    "verify_authoring_result": _verify_no_repository_writes,
    "verify_completion_evidence": _verify_no_repository_writes,
    "verify_defect": _verify_no_repository_writes,
    "verify_reconciliation": _verify_no_repository_writes,
    "verify_hook_report": _verify_no_repository_writes,
    "verify_freshness_marker": _verify_no_repository_writes,
    "verify_external_revision": _verify_no_repository_writes,
    "verify_repository_dependency": _verify_no_repository_writes,
    "verify_job_report": _verify_no_repository_writes,
}


REGISTRY: dict[str, TriggerSpec] = {
    spec.id: spec
    for spec in (
        TriggerSpec(
            "artifact-transition",
            "artifact_transition",
            "detect_artifact_transition",
            "preview_artifact_transition",
            "artifact",
            "verify_artifact",
            "preview",
        ),
        TriggerSpec(
            "pre-import",
            "authoring_pre_import",
            "detect_authoring_pre_import",
            "prepare_authoring_import",
            "authoring_import",
            "verify_runtime_binding",
            "preview",
        ),
        TriggerSpec(
            "authoring-result-import",
            "authoring_result_import",
            "detect_authoring_result_import",
            "validate_authoring_result",
            "authoring_result",
            "verify_authoring_result",
            "preview",
        ),
        TriggerSpec(
            "completion",
            "artifact_completion",
            "detect_artifact_completion",
            "preview_completion",
            "completion",
            "verify_completion_evidence",
            "preview",
        ),
        TriggerSpec(
            "defect-transition",
            "defect_transition",
            "detect_defect_transition",
            "preview_defect_transition",
            "defect",
            "verify_defect",
            "preview",
        ),
        TriggerSpec(
            "reconciliation-preview",
            "reconciliation_preview",
            "detect_reconciliation_preview",
            "reconcile",
            "reconciliation",
            "verify_reconciliation",
            "read_only",
        ),
        TriggerSpec(
            "session-start",
            "session_start",
            "detect_session_start",
            "report_session_context",
            "none",
            "verify_hook_report",
            "read_only",
        ),
        TriggerSpec(
            "significant-file-edit",
            "significant_file_edit",
            "detect_significant_file_edit",
            "mark_projection_stale",
            "none",
            "verify_freshness_marker",
            "preview",
        ),
        TriggerSpec(
            "external-design-refresh",
            "external_design_refresh",
            "detect_external_design_refresh",
            "compare_external_revision",
            "none",
            "verify_external_revision",
            "read_only",
        ),
        TriggerSpec(
            "repository-dependency-observation",
            "repository_dependency_change",
            "detect_repository_dependency_change",
            "observe_repository_dependency",
            "none",
            "verify_repository_dependency",
            "read_only",
        ),
        TriggerSpec(
            "routine-maintenance",
            "routine_maintenance",
            "detect_routine_maintenance",
            "doctor_refresh_projections",
            "canvas",
            "verify_job_report",
            "read_only",
        ),
    )
}


_COMMON_V1_INCOMPATIBILITIES = (
    "creation_snapshot_is_not_freeze",
    "heuristic_detection_requires_operator",
    "legacy_verifier_not_imported",
)
LEGACY_V1_MIGRATION: dict[int, LegacyTriggerMigration] = {
    legacy_id: LegacyTriggerMigration(
        legacy_id,
        "reconciliation-preview" if legacy_id == 6 else "artifact-transition",
        (
            *_COMMON_V1_INCOMPATIBILITIES,
            *(
                ("cross_repository_writes_require_separate_operations",)
                if legacy_id == 6
                else ()
            ),
        ),
    )
    for legacy_id in (1, 2, 3, 4, 6, 7)
}


def _parse_trigger(row: object) -> TriggerSpec:
    if not isinstance(row, dict) or set(row) != TRIGGER_FIELDS:
        raise ValueError("trigger_catalog_field_invalid")
    closed_handlers = {
        "detector": DETECTOR_HANDLERS,
        "action": ACTION_HANDLERS,
        "template": TEMPLATE_HANDLERS,
        "verifier": VERIFIER_HANDLERS,
    }
    if any(
        not isinstance(row[field], str) or row[field] not in handlers
        for field, handlers in closed_handlers.items()
    ):
        raise ValueError("trigger_vocabulary_invalid")
    require_valid("trigger", row)
    try:
        return TriggerSpec(
            id=row["id"],
            event=row["event"],
            detector=row["detector"],
            action=row["action"],
            template=row["template"],
            verifier=row["verifier"],
            capability=row["capability"],
            semantic_mutation=row["semantic_mutation"],
            schema=row["schema"],
        )
    except TypeError as exc:
        raise ValueError("trigger_catalog_invalid") from exc


def _parse_legacy(row: object) -> LegacyTriggerMigration:
    if not isinstance(row, dict) or set(row) != LEGACY_FIELDS:
        raise ValueError("trigger_legacy_mapping_invalid")
    if (
        type(row["legacy_id"]) is not int
        or not isinstance(row["v2_trigger_id"], str)
        or not isinstance(row["incompatibilities"], list)
        or not all(
            isinstance(value, str) and value
            for value in row["incompatibilities"]
        )
    ):
        raise ValueError("trigger_legacy_mapping_invalid")
    return LegacyTriggerMigration(
        row["legacy_id"],
        row["v2_trigger_id"],
        tuple(row["incompatibilities"]),
    )


def validate_trigger_parity(catalog_path: Path) -> dict[str, Any]:
    catalog = parse_json_object(catalog_path.read_bytes())
    if set(catalog) != CATALOG_FIELDS:
        raise ValueError("trigger_catalog_field_invalid")
    if (
        catalog.get("schema") != "doc-warden/triggers/v2"
        or catalog.get("version") != "2.1.0"
        or not isinstance(catalog.get("triggers"), list)
        or not isinstance(catalog.get("legacy_v1_migration"), list)
    ):
        raise ValueError("trigger_catalog_invalid")

    observed: dict[str, TriggerSpec] = {}
    for raw in catalog["triggers"]:
        spec = _parse_trigger(raw)
        if spec.id in observed:
            raise ValueError("trigger_registry_mismatch")
        if (
            spec.detector not in DETECTOR_HANDLERS
            or spec.action not in ACTION_HANDLERS
            or spec.template not in TEMPLATE_HANDLERS
            or spec.verifier not in VERIFIER_HANDLERS
            or spec.semantic_mutation
        ):
            raise ValueError("trigger_vocabulary_invalid")
        observed[spec.id] = spec
    if observed != REGISTRY:
        raise ValueError("trigger_registry_mismatch")

    used_vocabulary = {
        "detectors": {spec.detector for spec in observed.values()},
        "actions": {spec.action for spec in observed.values()},
        "templates": {spec.template for spec in observed.values()},
        "verifiers": {spec.verifier for spec in observed.values()},
    }
    expected_vocabulary = {
        "detectors": set(DETECTOR_HANDLERS),
        "actions": set(ACTION_HANDLERS),
        "templates": set(TEMPLATE_HANDLERS),
        "verifiers": set(VERIFIER_HANDLERS),
    }
    if used_vocabulary != expected_vocabulary:
        raise ValueError("trigger_vocabulary_invalid")

    migrations: dict[int, LegacyTriggerMigration] = {}
    for raw in catalog["legacy_v1_migration"]:
        migration = _parse_legacy(raw)
        if migration.legacy_id in migrations:
            raise ValueError("trigger_legacy_mapping_invalid")
        migrations[migration.legacy_id] = migration
    if migrations != LEGACY_V1_MIGRATION:
        raise ValueError("trigger_legacy_mapping_invalid")

    return {
        "schema": "doc-warden/trigger-parity/v2",
        "version": catalog["version"],
        "status": "pass",
        "trigger_count": len(observed),
        "handler_counts": {
            "actions": len(ACTION_HANDLERS),
            "detectors": len(DETECTOR_HANDLERS),
            "templates": len(TEMPLATE_HANDLERS),
            "verifiers": len(VERIFIER_HANDLERS),
        },
        "legacy_v1_ids": sorted(migrations),
    }


def _failure_copy(code: str) -> str:
    return (
        "I checked the closed doc-warden trigger catalog and runtime registry. "
        f"I am uncertain how to continue because {code}. Next action: review "
        "the catalog/runtime parity result and choose a supported trigger."
    )


def dispatch_trigger(
    trigger_id: str,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Dispatch one closed handler without granting mutation authority."""

    spec = REGISTRY.get(trigger_id)
    if spec is None:
        return {
            "schema": "doc-warden/trigger-result/v2",
            "status": "escalated",
            "code": "unknown_trigger",
            "trigger_id": trigger_id,
            "repository_writes": [],
            "rollback_verified": True,
            "message": _failure_copy("the trigger is not in the closed catalog"),
        }
    safe_context: Mapping[str, Any] = (
        context if isinstance(context, Mapping) else {}
    )
    stateful_action_started = False
    try:
        if not DETECTOR_HANDLERS[spec.detector](safe_context):
            return {
                "schema": "doc-warden/trigger-result/v2",
                "status": "not_detected",
                "code": "trigger_context_mismatch",
                "trigger_id": trigger_id,
                "repository_writes": [],
                "rollback_verified": True,
                "message": _failure_copy(
                    "the supplied event does not match the trigger detector"
                ),
            }
        if spec.action == "mark_projection_stale":
            stateful_action_started = True
        payload = ACTION_HANDLERS[spec.action](safe_context)
        if not VERIFIER_HANDLERS[spec.verifier](payload):
            raise ValueError("trigger_verification_failed")
        TEMPLATE_HANDLERS[spec.template]()
    except Exception:
        rollback_verified = not stateful_action_started
        return {
            "schema": "doc-warden/trigger-result/v2",
            "status": "failed",
            "code": "trigger_handler_failed",
            "trigger_id": trigger_id,
            "repository_writes": [],
            "rollback_verified": rollback_verified,
            "message": _failure_copy(
                "the selected handler failed"
                + (
                    " and machine-local freshness state could not be "
                    "verified as restored"
                    if not rollback_verified
                    else ""
                )
            ),
        }
    return {
        "schema": "doc-warden/trigger-result/v2",
        "status": payload["status"],
        "code": payload["code"],
        "trigger_id": trigger_id,
        "capability": spec.capability,
        "semantic_mutation": False,
        "repository_writes": [],
        "rollback_verified": True,
        "result": payload,
    }


def hook_capability_report() -> dict[str, Any]:
    return {
        "schema": "doc-warden/hook-capabilities/v1",
        "desktop_user_events": ("sessionStart", "afterFileEdit", "stop"),
        "user_hooks_run_in_cloud": False,
        "project_command_hooks_only": True,
        "supported_cloud_events": (
            "beforeShellExecution",
            "afterFileEdit",
        ),
        "enforcement": "commit_and_runnerless_checks",
    }


def maintenance_job_contract(
    *,
    source_root: Path | None = None,
) -> dict[str, Any]:
    root = (
        source_root
        if source_root is not None
        else Path(__file__).resolve().parents[4]
    ).expanduser().resolve(strict=True)
    wrapper = root / "_ops/bin/doc-warden.sh"
    if not wrapper.is_file():
        raise ValueError("maintenance_source_root_invalid")
    command = (
        str(wrapper),
        "doctor",
        "fleet",
        "--refresh-projections",
        "--repo",
        str(root),
    )
    program = "/bin/bash"
    return {
        "schema": "doc-warden/local-job-contract/v1",
        "id": "doc-warden-maintenance",
        "type": "command",
        "execution_mode": "scheduled",
        "interval_seconds": 21600,
        "serialization": "per_job_dispatcher_lock",
        "program": program,
        "args": list(command),
        "display_command": shlex.join((program, *command)),
        "read_only": True,
        "egress_sink": "job",
    }


_HOOK_REPORT_FIELDS = {
    "schema",
    "event",
    "status",
    "code",
    "repository_key",
    "source_revision",
    "observed_at",
    "checked",
    "uncertain",
    "next_action",
    "repository_writes",
}
_JOB_REPORT_FIELDS = {
    "schema",
    "job_id",
    "status",
    "source_revision",
    "read_only",
    "serialized",
    "repository_writes",
    "repository_count",
    "checked",
    "uncertain",
    "next_action",
}
_FORBIDDEN_EGRESS_FIELDS = {
    "credential",
    "customer_data",
    "diff",
    "environment",
    "prompt",
    "raw_log",
    "secret",
    "source_body",
    "transcript",
}


def _closed_egress(
    sink: str,
    payload: Mapping[str, Any],
    *,
    allowed: set[str],
    required: set[str],
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise ValueError(f"{sink}_egress_invalid")
    if set(payload) - allowed or _FORBIDDEN_EGRESS_FIELDS.intersection(payload):
        raise ValueError(f"{sink}_egress_invalid")
    if payload.get("repository_writes") != []:
        raise ValueError(f"{sink}_egress_must_be_read_only")
    envelope = {
        "schema": "doc-warden/egress/v1",
        "sink": sink,
        "payload": dict(payload),
    }
    require_valid("egress", envelope)
    return envelope


def hook_egress(payload: Mapping[str, Any]) -> dict[str, Any]:
    if (
        payload.get("schema") != "doc-warden/hook-report/v1"
        or payload.get("event") != "significant_file_edit"
        or re.fullmatch(
            r"[0-9a-f]{40}",
            str(payload.get("source_revision", "")),
        )
        is None
        or not isinstance(payload.get("observed_at"), str)
        or not isinstance(payload.get("next_action"), str)
        or any(
            not isinstance(value, str)
            for field in ("checked", "uncertain")
            for value in (
                payload.get(field)
                if isinstance(payload.get(field), list)
                else [None]
            )
        )
    ):
        raise ValueError("hook_egress_invalid")
    return _closed_egress(
        "hook",
        payload,
        allowed=_HOOK_REPORT_FIELDS,
        required=_HOOK_REPORT_FIELDS,
    )


def job_egress(payload: Mapping[str, Any]) -> dict[str, Any]:
    if (
        payload.get("schema") != "doc-warden/job-report/v1"
        or payload.get("job_id") != "doc-warden-maintenance"
        or payload.get("read_only") is not True
        or payload.get("serialized") is not True
        or re.fullmatch(
            r"[0-9a-f]{40}",
            str(payload.get("source_revision", "")),
        )
        is None
        or (
            "repository_count" in payload
            and (
                type(payload["repository_count"]) is not int
                or payload["repository_count"] < 0
            )
        )
        or any(
            not isinstance(value, str)
            for field in ("checked", "uncertain")
            for value in (
                payload.get(field, [])
                if isinstance(payload.get(field, []), list)
                else [None]
            )
        )
        or (
            "next_action" in payload
            and not isinstance(payload["next_action"], str)
        )
    ):
        raise ValueError("job_egress_invalid")
    return _closed_egress(
        "job",
        payload,
        allowed=_JOB_REPORT_FIELDS,
        required={
            "schema",
            "job_id",
            "status",
            "source_revision",
            "read_only",
            "serialized",
            "repository_writes",
        },
    )


def read_projection_freshness(
    repository: Path,
    state_home: Path,
) -> dict[str, Any] | None:
    marker = _projection_marker_path(repository, state_home)
    content = _read_projection_marker(marker)
    if content is None:
        return None
    try:
        payload = _parse_projection_marker(content)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    return payload
