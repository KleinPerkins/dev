"""Dormant v2 command surface behind the explicit ``v2-preview`` wrapper."""

from __future__ import annotations

import argparse
import fcntl
import os
import pwd
import re
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from .artifacts import apply_preview, draft_artifact, preview_json
from .canonical import canonical_json, contained_path, digest_ref, parse_json_object
from .gsd_adapter import (
    ALLOWED_OUTPUTS,
    AuthoringImportPreview,
    AuthoringScope,
    authoring_result_from_envelope,
    prepare_authoring_import,
    validate_authoring_result,
    validate_authoring_result_envelope,
    validate_runtime_binding,
    verify_frozen_authorities,
)
from .dashboard import (
    current_timestamp,
    generate_canvas,
    render_fleet_snapshot,
    render_repo_snapshot,
)
from .dependencies import PlanRefinementRequired
from .inventory import inventory_fleet
from .intents import map_intent
from .migrate import migration_preview
from .reconcile import reconcile
from .live_install import (
    apply_prepared_install,
    doctor as doctor_live_install,
    load_install_operation,
    prepare_install,
    preview_doctor_receipt,
    read_doctor_observation_file,
    uninstall as uninstall_live_install,
    validate_doctor_observation,
)
from .roadmap import roadmap_prioritize, roadmap_sequence, roadmap_view
from .operation_store import load_preview, operation_schema, store_preview
from .receipts import (
    prepare_remote_identity_observation,
    runnerless_delivery_preview,
)
from .scaffold import greenfield_v2, verify_born_v2
from .transactions import apply_transaction
from .save_game_adapter import (
    SaveGameAdapter,
    event_from_envelope,
    prepare_authoring_resume,
    prepare_checkpoint,
)
from .triggers import (
    dispatch_trigger,
    hook_capability_report,
    inspect_projection_freshness,
    job_egress,
    maintenance_job_contract,
    projection_freshness_preimage,
    reconcile_projection_freshness,
)
from .validators import read_repository_config


def _repo_status(repo: Path) -> dict[str, Any]:
    repo = repo.resolve(strict=True)
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    try:
        config = read_repository_config(repo)
    except ValueError as exc:
        return {
            "schema": "doc-warden/repo-view/v2",
            "repository": str(repo),
            "source_revision": head,
            "central_activation": "active",
            "profile": "invalid",
            "migration_status": "blocked",
            "write_enabled": False,
            "repository_key": None,
            "read_only": True,
            "repository_writes": [],
            "reason": str(exc),
        }
    return {
        "schema": "doc-warden/repo-view/v2",
        "repository": str(repo),
        "source_revision": head,
        "central_activation": "active",
        "profile": "v2" if config else "v1",
        "migration_status": (
            "active"
            if config and config["enabled"]
            else ("write_disabled" if config else "migration_required")
        ),
        "write_enabled": bool(config and config["enabled"]),
        "repository_key": config["repository_key"] if config else None,
        "read_only": True,
        "repository_writes": [],
    }


def _transaction_json(preview) -> dict[str, Any]:
    return {
        "schema": "doc-warden/transaction-preview/v2",
        "operation_id": preview.operation_id,
        "event_id": preview.event_id,
        "repository_key": preview.repository_key,
        "github_repository_id": preview.github_repository_id,
        "action_digest": preview.action_digest,
        "source_revision": preview.source_revision,
        "canonical_root": preview.canonical_root,
        "paths": [action.path for action in preview.actions],
        "writes": [
            {
                "path": action.path,
                "kind": action.kind,
                "preimage": preview.preimages[action.path] or "absent",
                "postimage": preview.postimages[action.path],
                "content": action.content.decode("utf-8"),
            }
            for action in preview.actions
        ],
        "bindings": preview.bindings,
        "observed_inputs": [
            {"path": item.path, "digest": item.digest}
            for item in preview.observed_inputs
        ],
        "record_paths": {
            "event": (
                "_ops/doc-warden/state/v2/events/"
                f"{preview.event_id}.json"
            ),
            "receipt": (
                "_ops/doc-warden/state/v2/receipts/"
                f"{preview.operation_id}.json"
            ),
        },
        "record_preimages": {
            "event": "absent_or_exact_replay",
            "receipt": "absent_or_exact_replay",
        },
    }


def _authoring_preview_json(preview: AuthoringImportPreview) -> dict[str, Any]:
    payload = {
        "schema": "doc-warden/authoring-import-preview/v1",
        "canonical_root": preview.canonical_root,
        "operation_id": preview.operation_id,
        "source_revision": preview.source_revision,
        "pin_digest": preview.pin_digest,
        "interface_digest": preview.interface_digest,
        "input_digests": preview.input_digests,
        "frozen_digests": preview.frozen_digests,
        "allowed_outputs": list(preview.allowed_outputs),
        "post_validator": preview.post_validator,
        "disposition": preview.disposition,
        "active_plan_id": preview.active_plan_id,
    }
    if preview.binding_root is not None:
        payload.update(schema="doc-warden/authoring-import-preview/v2",
                       binding_root=preview.binding_root,
                       authority_bindings=preview.authority_bindings,
                       profile_digest=preview.profile_digest)
    payload["preview_digest"] = digest_ref(canonical_json(payload))
    return payload


def _load_authoring_preview(repo: Path, path: Path) -> AuthoringImportPreview:
    raw = parse_json_object(path.read_bytes())
    required = set(_authoring_preview_json(
        AuthoringImportPreview(
            repo=repo,
            canonical_root="",
            operation_id="",
            source_revision="",
            pin_digest="",
            interface_digest="",
            input_digests={},
            frozen_digests={},
            allowed_outputs=(),
            post_validator="",
            disposition="",
        )
    ))
    central = raw.get("schema") == "doc-warden/authoring-import-preview/v2"
    if central:
        extra = {"binding_root", "authority_bindings", "profile_digest"}
        if (set(raw) != required | extra
                or not isinstance(raw.get("binding_root"), str)
                or not Path(raw["binding_root"]).is_absolute()
                or str(Path(raw["binding_root"])) != raw["binding_root"]
                or ".." in Path(raw["binding_root"]).parts
                or not isinstance(raw.get("authority_bindings"), dict)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", str(raw.get("profile_digest", ""))) is None):
            raise ValueError("authoring_preview_contract_invalid")
    elif (set(raw) not in (required, required - {"active_plan_id"})
            or raw.get("schema") != "doc-warden/authoring-import-preview/v1"):
        raise ValueError("authoring_preview_contract_invalid")
    bound = dict(raw)
    observed_digest = bound.pop("preview_digest", None)
    if observed_digest != digest_ref(canonical_json(bound)):
        raise ValueError("authoring_preview_digest_mismatch")
    root = repo.resolve(strict=True)
    try:
        uuid.UUID(str(raw.get("operation_id")))
    except (ValueError, TypeError) as exc:
        raise ValueError("authoring_preview_contract_invalid") from exc
    digest_maps = (raw.get("input_digests"), raw.get("frozen_digests"))
    if (
        raw.get("canonical_root") != str(root)
        or raw.get("allowed_outputs") != list(ALLOWED_OUTPUTS)
        or raw.get("post_validator") != "doc-warden validate-authoring"
        or raw.get("disposition") != "operator_invoke_required"
        or (
            raw.get("active_plan_id") is not None
            and (
                not isinstance(raw.get("active_plan_id"), str)
                or not raw["active_plan_id"]
            )
        )
        or re.fullmatch(r"[0-9a-f]{40}", str(raw.get("source_revision", ""))) is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", str(raw.get("pin_digest", ""))) is None
        or re.fullmatch(r"sha256:[0-9a-f]{64}", str(raw.get("interface_digest", ""))) is None
        or any(not isinstance(mapping, dict) for mapping in digest_maps)
    ):
        raise ValueError("authoring_preview_contract_invalid")
    for mapping in digest_maps:
        for relative, expected in mapping.items():
            if (
                not isinstance(relative, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", str(expected)) is None
            ):
                raise ValueError("authoring_preview_contract_invalid")
            contained_path(root, relative)
    preview = AuthoringImportPreview(
        repo=root,
        canonical_root=str(root),
        operation_id=raw["operation_id"],
        source_revision=raw["source_revision"],
        pin_digest=raw["pin_digest"],
        interface_digest=raw["interface_digest"],
        input_digests=raw["input_digests"],
        frozen_digests=raw["frozen_digests"],
        allowed_outputs=ALLOWED_OUTPUTS,
        post_validator=raw["post_validator"],
        disposition=raw["disposition"],
        active_plan_id=raw.get("active_plan_id"),
        binding_root=raw["binding_root"] if central else None,
        authority_bindings=raw["authority_bindings"] if central else None,
        profile_digest=raw["profile_digest"] if central else None,
    )
    validate_runtime_binding(preview)
    return preview


def _read_hook_input() -> dict[str, Any]:
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        return {}
    try:
        return parse_json_object(raw)
    except ValueError:
        return {}


def _after_file_edit_path(payload: dict[str, Any]) -> Path | None:
    value = payload.get("file_path")
    if not isinstance(value, str) or not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        cwd = payload.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            return None
        path = Path(cwd).expanduser() / path
    try:
        path = path.resolve(strict=True)
    except OSError:
        return None
    if not path.is_file():
        return None
    return path


def _hook_repositories(
    payload: dict[str, Any],
    *,
    event: str | None = None,
) -> tuple[Path, ...]:
    candidates: list[str] = []
    edited_file = (
        _after_file_edit_path(payload)
        if event in {"after-file-edit", "stop"}
        else None
    )
    if edited_file is not None:
        candidates.append(str(edited_file.parent))
    for key in ("cwd", "workspace_root", "project_root"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            candidates.append(value)
    for key in ("workspace_roots", "workspaceRoots"):
        value = payload.get(key)
        if isinstance(value, list):
            candidates.extend(
                item
                for item in value
                if isinstance(item, str) and item
            )
    file_path = payload.get("file_path")
    if (
        event not in {"after-file-edit", "stop"}
        and isinstance(file_path, str)
        and file_path
    ):
        candidates.append(str(Path(file_path).expanduser().parent))
    roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        path = Path(candidate).expanduser()
        if not path.exists():
            continue
        if path.is_file():
            path = path.parent
        observed = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
        if observed.returncode == 0:
            root = Path(observed.stdout.strip())
            if root.is_dir():
                resolved = root.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    roots.append(resolved)
    return tuple(roots)


def _hook_repository(
    payload: dict[str, Any],
    *,
    event: str | None = None,
) -> Path | None:
    repositories = _hook_repositories(payload, event=event)
    return repositories[0] if repositories else None


def _hook_repository_key(repo: Path) -> str | None:
    try:
        config = read_repository_config(repo)
    except ValueError:
        return None
    return config["repository_key"] if config is not None else None


def _state_home() -> Path:
    return Path(
        os.environ.get(
            "XDG_STATE_HOME",
            str(Path.home() / ".local/state"),
        )
    ).expanduser()


def _maintenance_lock_descriptor() -> int:
    lock_root = _state_home() / "doc-warden/locks"
    lock_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        directory_flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
    try:
        root_descriptor = os.open(lock_root, directory_flags)
    except OSError as exc:
        raise ValueError("maintenance_lock_root_invalid") from exc
    try:
        lock_flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_CLOEXEC"):
            lock_flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            lock_flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(
                "maintenance.lock",
                lock_flags,
                0o600,
                dir_fd=root_descriptor,
            )
        except OSError as exc:
            raise ValueError("maintenance_lock_invalid") from exc
    finally:
        os.close(root_descriptor)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError("maintenance_lock_invalid")
    os.fchmod(descriptor, 0o600)
    return descriptor


def _session_hook_output(payload: dict[str, Any]) -> dict[str, str]:
    repo = _hook_repository(payload, event="session-start")
    if repo is None:
        return {
            "additional_context": (
                "Doc-warden checked for a governed repository but could not "
                "identify one. The current governance state is uncertain. "
                "Next action: open the repository and run "
                "`bash _ops/bin/doc-warden.sh doctor repo`."
            )
        }
    status = _repo_status(repo)
    snapshot = render_repo_snapshot(repo)
    short_revision = status["source_revision"][:12]
    governance_state = (
        "blocked"
        if snapshot.get("migration_status") == "blocked"
        else status["migration_status"]
    )
    if governance_state != "active":
        state_copy = {
            "migration_required": (
                "this repository requires governance migration"
            ),
            "write_disabled": (
                "governance writes are disabled for this repository"
            ),
            "blocked": "the governance view is blocked or invalid",
        }.get(
            governance_state,
            "the governance state is blocked or uncertain",
        )
        return {
            "additional_context": (
                "Doc-warden checked the read-only repository view and doctor "
                f"status at {short_revision}; {state_copy}. Roadmap rows were "
                "not summarized because governance is not active. Next "
                "action: run `bash _ops/bin/doc-warden.sh doctor repo` in "
                "chat and resolve the reported state before relying on the "
                "roadmap."
            )
        }
    freshness = reconcile_projection_freshness(
        repo,
        _state_home(),
        status["source_revision"],
    )
    if freshness is not None and freshness.get("status") == "potentially_stale":
        freshness_copy = (
            "The generated roadmap may be stale after a significant file edit."
        )
    else:
        freshness_copy = "No local stale-projection marker was found."
    return {
        "additional_context": (
            "Doc-warden checked the read-only repository view and doctor "
            f"status at {short_revision}; {len(snapshot['items'])} roadmap "
            f"rows are visible. {freshness_copy} Next action: use the "
            "read-only roadmap refresh or manage changes through the "
            "validated CLI in chat."
        )
    }


def _hook_event_output(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event == "capabilities":
        return hook_capability_report()
    if event == "session-start":
        return _session_hook_output(payload)
    if event == "after-file-edit":
        edited_file = _after_file_edit_path(payload)
        if edited_file is None:
            return {}
        repo = _hook_repository(payload, event=event)
        if repo is None:
            return {}
        repository_key = _hook_repository_key(repo)
        if repository_key is None:
            return {}
        status = _repo_status(repo)
        dispatch_trigger(
            "significant-file-edit",
            {
                "event": "significant_file_edit",
                "repository": str(repo),
                "repository_key": repository_key,
                "source_revision": status["source_revision"],
                "state_home": str(_state_home()),
                "file_path": str(edited_file),
            },
        )
        return {}
    if event == "stop":
        stale = False
        for repo in _hook_repositories(payload, event=event):
            try:
                status = _repo_status(repo)
                freshness = reconcile_projection_freshness(
                    repo,
                    _state_home(),
                    status["source_revision"],
                )
            except (OSError, subprocess.SubprocessError, ValueError):
                continue
            if freshness is not None:
                stale = True
        if not stale:
            return {}
        return {
            "followup_message": (
                "Doc-warden observed that the generated governance view may "
                "be stale. Refresh the read-only roadmap view; this is an "
                "observation, not a blocking gate."
            )
        }
    raise ValueError("hook_event_invalid")


def _maintenance_egress(repo: Path) -> dict[str, Any]:
    lock_descriptor = _maintenance_lock_descriptor()
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        repository = repo.resolve(strict=True)
        repositories = inventory_fleet(repository)
        source_revision = _repo_status(repository)["source_revision"]
        trigger = dispatch_trigger(
            "routine-maintenance",
            {
                "event": "routine_maintenance",
                "repository": str(repository),
                "source_revision": source_revision,
            },
        )
        if trigger["status"] not in {"observed", "proposed"}:
            raise ValueError("maintenance_trigger_failed")
        contract = maintenance_job_contract()
        freshness = inspect_projection_freshness(_state_home())
        refresh_pending = bool(freshness["pending_count"])
        freshness_invalid = bool(
            freshness["malformed_count"]
            or freshness["unavailable_count"]
            or freshness["scan_limited"]
        )
        uncertain = sorted(
            {
                row.repository
                for row in repositories
                if not row.available
            }
        )
        if refresh_pending:
            uncertain.append("generated_projection_freshness")
        if freshness["malformed_count"]:
            uncertain.append("generated_projection_freshness_malformed")
        if freshness["unavailable_count"]:
            uncertain.append("generated_projection_freshness_unavailable")
        if freshness["scan_limited"]:
            uncertain.append("generated_projection_freshness_scan_limited")
        report = job_egress(
            {
                "schema": "doc-warden/job-report/v1",
                "job_id": contract["id"],
                "status": (
                    "attention_required"
                    if refresh_pending or freshness_invalid
                    else "pass"
                ),
                "source_revision": source_revision,
                "read_only": True,
                "serialized": True,
                "repository_writes": [],
                "repository_count": len(repositories),
                "checked": [
                    "fleet_conformance",
                    "roadmap_freshness",
                    "dependency_drift",
                ],
                "uncertain": uncertain,
                "next_action": (
                    "inspect_projection_freshness_state"
                    if freshness_invalid
                    else (
                        "refresh_governance_view_in_chat"
                        if refresh_pending
                        else "review_generated_projections"
                    )
                ),
            }
        )
        return report
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doc-warden v2-preview")
    sub = parser.add_subparsers(dest="verb", required=True)

    doctor = sub.add_parser(
        "doctor",
        help="Run read-only repository or fleet health inspection.",
        description=(
            "Read-only inspection: reports health and migration status; "
            "never writes repository content."
        ),
    )
    doctor.add_argument("scope", choices=("repo", "fleet"))
    doctor.add_argument("--repo", type=Path, default=Path.cwd())
    doctor.add_argument(
        "--refresh-projections",
        action="store_true",
        help=(
            "Emit the closed serialized read-only maintenance report for the "
            "fleet job; performs no repository writes."
        ),
    )

    view = sub.add_parser("view")
    view.add_argument("scope", choices=("repo", "fleet"))
    view.add_argument("--repo", type=Path, default=Path.cwd())
    view.add_argument("--json", action="store_true")
    view.add_argument("--canvas", type=Path)

    intent = sub.add_parser(
        "intent",
        help="Map ordinary language to a proposal without authorizing it.",
    )
    intent.add_argument("utterance")
    intent.add_argument("--context", type=Path)
    intent.add_argument("--operation-id")
    intent.add_argument("--action-digest")

    hook = sub.add_parser(
        "hook",
        help="Read-only/freshness-only command-hook projection.",
    )
    hook.add_argument(
        "hook_event",
        choices=("capabilities", "session-start", "after-file-edit", "stop"),
    )

    greenfield = sub.add_parser(
        "greenfield",
        help="Scaffold or inspect one born-v2 repository.",
    )
    greenfield_sub = greenfield.add_subparsers(
        dest="greenfield_action",
        required=True,
    )
    scaffold = greenfield_sub.add_parser("scaffold")
    scaffold.add_argument("--repo", type=Path, required=True)
    scaffold.add_argument("--authority-root", type=Path, required=True)
    scaffold.add_argument("--name", required=True)
    scaffold.add_argument("--repository-key", required=True)
    scaffold.add_argument("--operation-id", required=True)
    scaffold.add_argument("--preview", action="store_true")

    observe_remote = greenfield_sub.add_parser("observe-remote")
    observe_remote.add_argument("--repo", type=Path, required=True)
    observe_remote.add_argument("--authority-root", type=Path, required=True)
    observe_remote.add_argument("--repository", required=True)
    observe_remote.add_argument("--repository-id", type=int, required=True)
    observe_remote.add_argument("--operation-id", required=True)
    observe_remote.add_argument("--preview", action="store_true")

    verify_greenfield = greenfield_sub.add_parser("verify")
    verify_greenfield.add_argument("--repo", type=Path, required=True)
    verify_greenfield.add_argument("--authority-root", type=Path, required=True)
    verify_greenfield.add_argument("--repository-key")
    verify_greenfield.add_argument("--repository-id", type=int)

    delivery = greenfield_sub.add_parser("delivery-preview")
    delivery.add_argument("--authority-root", type=Path, required=True)
    delivery.add_argument("--repository", required=True)
    delivery.add_argument("--repository-id", type=int)

    adr = sub.add_parser("adr")
    adr_sub = adr.add_subparsers(dest="adr_action", required=True)
    for action in ("draft", "update", "accept", "successor"):
        command = adr_sub.add_parser(action)
        command.add_argument("--repo", type=Path, default=Path.cwd())
        command.add_argument("--operation-id")
        command.add_argument("--preview", action="store_true", required=True)
        if action != "draft":
            command.add_argument("--artifact-id", required=True)
        if action == "accept":
            command.add_argument("--approval", type=Path, required=True)
        else:
            command.add_argument("--title", required=True)
            command.add_argument("--body-file", type=Path)
            if action == "draft":
                command.add_argument("--approval-file", type=Path)

    draft = sub.add_parser("draft")
    draft.add_argument(
        "kind",
        choices=(
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
        ),
    )
    draft.add_argument("--repo", type=Path, default=Path.cwd())
    draft.add_argument("--title", required=True)
    draft.add_argument("--body")
    draft.add_argument("--approved-prd", action="store_true")
    draft.add_argument("--operation-id")
    draft.add_argument("--preview", action="store_true")

    prioritize = sub.add_parser("prioritize")
    prioritize.add_argument("roadmap_id")
    prioritize.add_argument("priority", choices=("P0", "P1", "P2", "P3"))
    prioritize.add_argument("--repo", type=Path, default=Path.cwd())
    prioritize.add_argument("--operation-id")
    prioritize.add_argument("--preview", action="store_true")

    sequence = sub.add_parser("sequence")
    sequence.add_argument("roadmap_id")
    relation = sequence.add_mutually_exclusive_group(required=True)
    relation.add_argument("--before")
    relation.add_argument("--after")
    sequence.add_argument("--repo", type=Path, default=Path.cwd())
    sequence.add_argument("--operation-id")
    sequence.add_argument("--preview", action="store_true")

    apply = sub.add_parser("apply")
    apply.add_argument("--operation-id", required=True)
    apply.add_argument("--action-digest", required=True)
    apply.add_argument("--consent-envelope", type=Path)

    for verb in ("log", "update"):
        command = sub.add_parser(verb)
        command.add_argument("arguments", nargs=argparse.REMAINDER)
    reconcile_command = sub.add_parser(
        "reconcile",
        help="Build a read-only reconciliation preview.",
        description=(
            "Read-only reconciliation: --preview classifies drift and "
            "proposes no repository writes."
        ),
    )
    reconcile_command.add_argument("--repo", type=Path, default=Path.cwd())
    reconcile_command.add_argument("--fleet", action="store_true")
    reconcile_command.add_argument("--observations", type=Path)
    reconcile_command.add_argument("--operation-id")
    reconcile_command.add_argument("--preview", action="store_true")
    migrate = sub.add_parser("migrate")
    migrate.add_argument("--repo", type=Path, default=Path.cwd())
    migrate.add_argument("--legacy-state", type=Path)
    migrate.add_argument("--operation-id")
    migrate.add_argument("--preview", action="store_true")
    runtime = sub.add_parser("runtime")
    runtime.add_argument(
        "runtime_verb", choices=("install-gsd", "uninstall-gsd", "doctor-gsd")
    )
    runtime.add_argument("--repo", type=Path, default=Path.cwd())
    runtime.add_argument("--home", type=Path, default=Path(os.environ["HOME"]))
    runtime.add_argument(
        "--data-home",
        type=Path,
        default=Path(
            os.environ.get(
                "XDG_DATA_HOME", str(Path(os.environ["HOME"]) / ".local/share")
            )
        ),
    )
    runtime.add_argument("--preview", action="store_true")
    runtime.add_argument(
        "--observation",
        type=Path,
        help="Validate a prior closed doctor observation without writing.",
    )
    runtime.add_argument(
        "--require-current",
        action="store_true",
        help="Refuse --observation unless it is fresh against current HEAD.",
    )
    prepare = sub.add_parser("prepare-authoring")
    prepare.add_argument("--repo", type=Path, default=Path.cwd())
    prepare.add_argument("--operation-id", required=True)
    prepare.add_argument("--input", action="append", default=[])
    prepare.add_argument("--frozen", action="append", default=[])
    prepare.add_argument("--active-plan")
    prepare.add_argument("--binding-root", type=Path)
    validate = sub.add_parser("validate-authoring")
    validate.add_argument("--repo", type=Path, default=Path.cwd())
    validate.add_argument("--preview", type=Path, required=True)
    validate.add_argument("--result", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--repo", type=Path, default=Path.cwd())
    verify.add_argument("--preview", type=Path, required=True)
    for verb in ("checkpoint", "resume-authoring"):
        command = sub.add_parser(verb)
        command.add_argument("--repo", type=Path, default=Path.cwd())
        command.add_argument("--state", type=Path, required=True)
        command.add_argument("--event", type=Path, required=True)
    return parser


def _run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verb == "greenfield":
        if args.greenfield_action == "scaffold":
            if not args.preview:
                raise ValueError("greenfield_preview_required")
            preview = greenfield_v2(
                args.repo,
                args.name,
                args.repository_key,
                authority_root=args.authority_root,
                operation_id=args.operation_id,
            )
            value = _transaction_json(preview)
            value.update(
                {
                    "schema": "doc-warden/greenfield-preview/v1",
                    "status": "ready",
                    "consequence": "new_repository_scaffold",
                    "consent_required": True,
                    "expires_at": store_preview(preview),
                    "rollback": {
                        "before_remote": (
                            "remove_local_only_after_operator_choice"
                        ),
                        "after_remote": (
                            "preserve_receipts_and_require_external_delete_gate"
                        ),
                        "remote_delete_requires_gate": True,
                    },
                }
            )
            print(canonical_json(value).decode("utf-8"), end="")
            return 0
        if args.greenfield_action == "observe-remote":
            if not args.preview:
                raise ValueError("remote_identity_preview_required")
            preview = prepare_remote_identity_observation(
                args.repo,
                repository=args.repository,
                github_repository_id=args.repository_id,
                authority_root=args.authority_root,
                operation_id=args.operation_id,
            )
            value = _transaction_json(preview)
            value.update(
                {
                    "schema": "doc-warden/remote-identity-preview/v1",
                    "status": "ready",
                    "consequence": "remote_identity_observation",
                    "consent_required": True,
                    "expires_at": store_preview(preview),
                    "stable_repository_key": preview.repository_key,
                    "rollback": {
                        "source": "git_revert_second_commit",
                        "remote_delete_requires_gate": True,
                    },
                }
            )
            print(canonical_json(value).decode("utf-8"), end="")
            return 0
        if args.greenfield_action == "verify":
            value = verify_born_v2(
                args.repo,
                authority_root=args.authority_root,
                repository_key=args.repository_key,
                github_repository_id=args.repository_id,
            )
            print(canonical_json(value).decode("utf-8"), end="")
            return 0
        if args.greenfield_action == "delivery-preview":
            value = runnerless_delivery_preview(
                args.authority_root,
                repository=args.repository,
                github_repository_id=args.repository_id,
            )
            print(canonical_json(value).decode("utf-8"), end="")
            return 0
    if args.verb == "intent":
        context: dict[str, Any] = {}
        if args.context is not None:
            context.update(parse_json_object(args.context.read_bytes()))
        if args.operation_id is not None:
            context["operation_id"] = args.operation_id
        if args.action_digest is not None:
            context["action_digest"] = args.action_digest
        print(
            canonical_json(map_intent(args.utterance, context).as_dict()).decode(
                "utf-8"
            ),
            end="",
        )
        return 0
    if args.verb == "hook":
        payload = (
            {}
            if args.hook_event == "capabilities"
            else _read_hook_input()
        )
        print(
            canonical_json(
                _hook_event_output(args.hook_event, payload)
            ).decode("utf-8"),
            end="",
        )
        return 0
    if args.verb == "doctor":
        if args.refresh_projections:
            if args.scope != "fleet":
                raise ValueError("fleet_refresh_required")
            print(
                canonical_json(_maintenance_egress(args.repo)).decode("utf-8"),
                end="",
            )
            return 0
        if args.scope == "fleet":
            repositories = inventory_fleet(args.repo)
            value = {
                "schema": "doc-warden/fleet-preview/v2",
                "status": "preview",
                "repository_count": len(repositories),
                "runnerless_v2": "blocked_external_dependency",
                "read_only": True,
                "repository_writes": [],
            }
        else:
            value = _repo_status(args.repo)
        print(canonical_json(value).decode("utf-8"), end="")
        return 0
    if args.verb == "view":
        marker_preimage = (
            projection_freshness_preimage(
                args.repo,
                _state_home(),
            )
            if args.canvas is not None
            else None
        )
        generated_at = current_timestamp()
        if args.scope == "fleet":
            repositories = inventory_fleet(args.repo)
            status = _repo_status(args.repo)
            source_observed_at = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(args.repo),
                    "show",
                    "-s",
                    "--format=%cI",
                    "HEAD",
                ],
                text=True,
            ).strip()
            snapshot = render_fleet_snapshot(
                repositories,
                source_revision=status["source_revision"],
                generated_at=generated_at,
                source_observed_at=source_observed_at,
            )
            value = snapshot
        else:
            status = _repo_status(args.repo)
            if status["profile"] != "v2":
                value = {
                    "schema": "doc-warden/roadmap-view/v2",
                    "repository_key": None,
                    "source_revision": status["source_revision"],
                    "migration_status": status["migration_status"],
                    "items": [],
                }
                if "reason" in status:
                    value["reason"] = status["reason"]
            else:
                config = read_repository_config(args.repo)
                assert config is not None
                view = roadmap_view(args.repo, config["repository_key"])
                value = {
                    "schema": "doc-warden/roadmap-view/v2",
                    "repository_key": view.repository_key,
                    "source_revision": view.source_revision,
                    "migration_status": "active",
                    "items": list(view.items),
                }
        if args.canvas is not None:
            if args.scope == "repo":
                snapshot = render_repo_snapshot(
                    args.repo,
                    generated_at=generated_at,
                )
            seed = Path(__file__).resolve().parents[4] / "_ops/dashboards/doc-warden-roadmap.canvas.tsx"
            output = generate_canvas(seed, args.canvas, snapshot)
            reconcile_projection_freshness(
                args.repo,
                _state_home(),
                snapshot["source_revision"],
                refresh_preimage=marker_preimage,
            )
            value = {
                "schema": "doc-warden/canvas-render-result/v1",
                "target": str(args.canvas.resolve()),
                "source_revision": snapshot["source_revision"],
                "source_observed_at": snapshot["source_observed_at"],
                "generated_at": snapshot["generated_at"],
                "refresh_mode": "chat_fallback",
                "repository_writes": [],
                "content_digest": digest_ref(output),
            }
        print(canonical_json(value).decode("utf-8"), end="")
        return 0
    if args.verb == "adr":
        from .adrs import (preview_adr_draft, preview_adr_update,
                           preview_adr_accept, preview_adr_successor)
        kwargs = {"repo": args.repo, "operation_id": args.operation_id}
        if args.adr_action == "accept":
            preview = preview_adr_accept(args.artifact_id,
                parse_json_object(args.approval.read_bytes()), **kwargs)
        else:
            inputs = {"title": args.title}
            if args.body_file:
                inputs["body"] = args.body_file.read_bytes().decode("utf-8")
            if args.adr_action == "draft":
                if args.approval_file:
                    inputs["approval"] = parse_json_object(args.approval_file.read_bytes())
                preview = preview_adr_draft(inputs, **kwargs)
            else:
                function = preview_adr_update if args.adr_action == "update" else preview_adr_successor
                preview = function(args.artifact_id, inputs, **kwargs)
        value = preview_json(preview)
        value.update({"consequence": "semantic", "consent_required": True,
                      "expires_at": store_preview(preview.transaction)})
        print(canonical_json(value).decode("utf-8"), end="")
        return 0
    if args.verb == "draft":
        preview = draft_artifact(
            args.kind,
            {
                "title": args.title,
                "body": args.body or f"# {args.title}",
                "approved_prd": args.approved_prd,
            },
            repo=args.repo,
            operation_id=args.operation_id,
        )
        value = preview_json(preview)
        value.update(
            {
                "consequence": "semantic",
                "consent_required": True,
                "expires_at": store_preview(preview.transaction),
            }
        )
        print(canonical_json(value).decode("utf-8"), end="")
        return 0
    if args.verb in {"prioritize", "sequence"}:
        config = read_repository_config(args.repo)
        if config is None:
            raise ValueError("v2_repository_profile_required")
        if args.verb == "prioritize":
            preview = roadmap_prioritize(
                args.repo,
                config["repository_key"],
                args.roadmap_id,
                args.priority,
                operation_id=args.operation_id,
            )
        else:
            preview = roadmap_sequence(
                args.repo,
                config["repository_key"],
                args.roadmap_id,
                before=args.before,
                after=args.after,
                operation_id=args.operation_id,
            )
        value = _transaction_json(preview)
        value.update(
            {
                "consequence": "roadmap",
                "consent_required": True,
                "expires_at": store_preview(preview),
            }
        )
        print(canonical_json(value).decode("utf-8"), end="")
        return 0
    if args.verb == "apply":
        if (
            operation_schema(args.operation_id)
            == "doc-warden/live-install-operation/v1"
        ):
            if args.consent_envelope is None:
                raise ValueError("fresh_exact_consent_required")
            consent = parse_json_object(args.consent_envelope.read_bytes())
            operation = load_install_operation(
                args.operation_id, args.action_digest
            )
            value = apply_prepared_install(
                operation,
                consent,
                real_home=Path(pwd.getpwuid(os.getuid()).pw_dir),
            )
            print(canonical_json(value).decode("utf-8"), end="")
            return 0
        preview = load_preview(args.operation_id, args.action_digest)
        if preview.consequential:
            if args.consent_envelope is None:
                raise ValueError("fresh_exact_consent_required")
            consent = parse_json_object(args.consent_envelope.read_bytes())
            value = apply_preview(preview, consent)
        else:
            value = apply_transaction(preview, None)
        print(canonical_json(value).decode("utf-8"), end="")
        return 0
    if args.verb == "reconcile":
        if not args.preview:
            raise ValueError("reconciliation_preview_required")
        if args.fleet:
            repositories = inventory_fleet(args.repo)
            value = {
                "schema": "doc-warden/fleet-reconciliation-preview/v2",
                "source_revision": _repo_status(args.repo)["source_revision"],
                "runnerless_v2": "blocked_external_dependency",
                "read_only": True,
                "repository_writes": [],
                "repositories": [
                    {
                        "repository": row.repository,
                        "status": "preview_only" if row.mutation_eligible else "observed_only",
                        "reason": row.reason,
                    }
                    for row in repositories
                ],
            }
        else:
            plan = reconcile(
                args.repo,
                observations=args.observations,
                operation_id=args.operation_id,
            )
            value = {
                "schema": "doc-warden/reconciliation-preview/v2",
                "status": plan.status,
                "classifications": [list(row) for row in plan.classifications],
                "cycles": [list(cycle) for cycle in plan.graph.cycles],
                "safe_updates": list(plan.safe_updates),
                "unsafe_findings": list(plan.unsafe_findings),
                "source_revision": _repo_status(args.repo)["source_revision"],
                "read_only": True,
                "repository_writes": [],
            }
            if plan.transaction is not None:
                value.update(_transaction_json(plan.transaction))
                value["schema"] = "doc-warden/reconciliation-preview/v2"
                value.update(
                    {
                        "status": plan.status,
                        "classifications": [
                            list(row) for row in plan.classifications
                        ],
                        "cycles": [list(cycle) for cycle in plan.graph.cycles],
                        "safe_updates": list(plan.safe_updates),
                        "unsafe_findings": list(plan.unsafe_findings),
                        "consequence": "structural",
                        "consent_required": True,
                        "expires_at": store_preview(plan.transaction),
                        "read_only": True,
                        "repository_writes": [],
                    }
                )
        print(canonical_json(value).decode("utf-8"), end="")
        return 0
    if args.verb == "migrate":
        if not args.preview:
            raise ValueError("migration_preview_required")
        plan = migration_preview(
            args.repo,
            legacy_state=args.legacy_state,
            operation_id=args.operation_id,
        )
        value = {
            "schema": "doc-warden/migration-preview/v2",
            "repository_key": plan.repository_key,
            "source_revision": plan.source_revision,
            "status": plan.status,
            "repository_identity": plan.repository_identity.binding(),
            "legacy_evidence": [
                {
                    "path": row.path,
                    "digest": row.digest,
                    "classification": row.classification,
                    "resolution": row.resolution,
                }
                for row in plan.legacy_evidence
            ],
            "repository_writes_applied": False,
        }
        if plan.transaction is not None:
            value.update(_transaction_json(plan.transaction))
            value["schema"] = "doc-warden/migration-preview/v2"
            value.update(
                {
                    "repository_identity": plan.repository_identity.binding(),
                    "bindings": {
                        **plan.transaction.bindings,
                        "gsd_interface_digest": plan.gsd_interface_digest,
                    },
                    "consequence": "migration",
                    "consent_required": True,
                    "expires_at": store_preview(plan.transaction),
                    "rollback": {
                        "strategy": "git_revert",
                        "paths": [
                            *plan.writes,
                            *value["record_paths"].values(),
                        ],
                        "preserves_legacy_evidence": True,
                    },
                    "repository_writes_applied": False,
                }
            )
        print(canonical_json(value).decode("utf-8"), end="")
        return 0
    if args.verb == "runtime":
        if (
            args.observation is not None
            and args.runtime_verb != "doctor-gsd"
        ):
            raise ValueError("doctor_observation_wrong_runtime_verb")
        if args.runtime_verb == "install-gsd" and args.preview:
            value = prepare_install(
                args.repo, home=args.home, data_home=args.data_home
            )
            print(canonical_json(value).decode("utf-8"), end="")
            return 0
        if args.runtime_verb == "install-gsd":
            raise ValueError("runtime_apply_requires_generic_apply")
        if args.runtime_verb == "uninstall-gsd":
            if args.preview:
                value = {
                    "schema": "doc-warden/live-uninstall-preview/v1",
                    "status": "ready",
                    "home": str(args.home),
                    "ownership": "manifest_identity_matching_only",
                }
                print(canonical_json(value).decode("utf-8"), end="")
                return 0
            uninstall_live_install(
                args.repo, home=args.home, data_home=args.data_home
            )
            return 0
        if args.observation is not None:
            if args.preview:
                raise ValueError("doctor_observation_preview_conflict")
            value = validate_doctor_observation(
                args.repo,
                read_doctor_observation_file(args.observation),
                home=args.home,
                data_home=args.data_home,
                require_current=args.require_current,
            )
        elif args.preview:
            observation, preview = preview_doctor_receipt(
                args.repo,
                home=args.home,
                data_home=args.data_home,
            )
            value = _transaction_json(preview)
            value.update(
                {
                    "schema": "doc-warden/live-doctor-receipt-preview/v1",
                    "observation": observation,
                    "receipt_path": observation["receipt_path"],
                    "consequence": "structural",
                    "consent_required": True,
                    "expires_at": store_preview(preview),
                    "repository_writes_applied": False,
                }
            )
        else:
            value = doctor_live_install(
                args.repo, home=args.home, data_home=args.data_home
            )
        print(canonical_json(value).decode("utf-8"), end="")
        return 0
    if args.verb == "prepare-authoring":
        scope = AuthoringScope(
            repo=args.repo,
            operation_id=args.operation_id,
            input_paths=tuple(args.input),
            frozen_paths=tuple(args.frozen),
            active_plan_id=args.active_plan,
            binding_root=args.binding_root,
        )
        preview = prepare_authoring_import(scope)
        value = _authoring_preview_json(preview)
        print(canonical_json(value).decode("utf-8"), end="")
        return 0
    if args.verb in {"validate-authoring", "verify"}:
        preview = _load_authoring_preview(args.repo, args.preview)
        if args.verb == "verify":
            value = verify_frozen_authorities(preview)
        else:
            raw = parse_json_object(args.result.read_bytes())
            validate_authoring_result_envelope(raw)
            if raw.get("source_revision") != preview.source_revision:
                raise ValueError("authoring_source_revision_changed")
            if raw.get("pin_digest") != preview.pin_digest:
                raise ValueError("wrong_gsd_pin")
            result = authoring_result_from_envelope(args.repo, raw)
            import_plan = validate_authoring_result(preview, result)
            value = _transaction_json(import_plan.transaction)
            value["expires_at"] = store_preview(import_plan.transaction)
            value["consent_required"] = True
        print(canonical_json(value).decode("utf-8"), end="")
        return 0
    if args.verb in {"checkpoint", "resume-authoring"}:
        state = parse_json_object(args.state.read_bytes())
        raw_event = parse_json_object(args.event.read_bytes())
        event = event_from_envelope(raw_event)
        adapter = SaveGameAdapter(root=args.repo)
        value = (
            prepare_checkpoint(args.repo, state, event, adapter)
            if args.verb == "checkpoint"
            else prepare_authoring_resume(args.repo, state, event, adapter)
        )
        print(canonical_json(value).decode("utf-8"), end="")
        return 0
    raise SystemExit(f"{args.verb} is reserved until its owning milestone")


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except PlanRefinementRequired as exc:
        print(
            canonical_json(
                {
                    "schema": "doc-warden/error/v2",
                    "status": "blocked",
                    "code": "plan_refinement_required",
                    "checked": ["accepted_authority_bindings"],
                    "uncertain": ["current_plan_semantics"],
                    "next_action": "refine_plan_before_retry",
                    "repository_writes": [],
                    "message": (
                        "I checked the accepted authority bindings. The current "
                        "plan semantics are uncertain. Next action: refine the "
                        "plan before retrying."
                    ),
                    "plan_refinements": [
                        refinement.record()
                        for refinement in exc.refinements
                    ],
                }
            ).decode("utf-8"),
            end="",
        )
        return 1
    except ValueError as exc:
        observed = str(exc)
        code = (
            observed
            if re.fullmatch(r"[a-z][a-z0-9_]*", observed)
            else "invalid_input"
        )
    except (OSError, subprocess.SubprocessError):
        code = "input_unavailable"
    print(
        canonical_json(
            {
                "schema": "doc-warden/error/v2",
                "status": "blocked",
                "code": code,
                "checked": ["closed_cli_contract"],
                "uncertain": [code],
                "next_action": "correct_input_and_retry",
                "repository_writes": [],
                "message": (
                    "I checked the closed doc-warden CLI contract. The requested "
                    f"operation is uncertain because {code}. Next action: "
                    "correct the named input or precondition and retry."
                ),
            }
        ).decode("utf-8"),
        end="",
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
