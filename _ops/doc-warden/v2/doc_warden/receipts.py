"""Receipt creation, delivery observation, and legacy v1 reading."""

from __future__ import annotations

import re
import subprocess
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from .artifacts import _bindings
from .canonical import atomic_write, canonical_json, contained_path, digest_ref, parse_json_object
from .scm import RepositoryIdentity, _github_slug, _origin_url
from .transactions import (
    MutationAction,
    MutationRequest,
    ObservedInput,
    TransactionPreview,
    _event_for,
    _event_path,
    preview_transaction,
)
from .validators import read_repository_config, require_valid, validate_egress


@dataclass(frozen=True)
class LegacyReceipt:
    path: Path
    schema: str
    repository: str
    policy_version: str
    observed_outcome: str
    content_digest: str


def _scalar(value: str) -> object:
    value = value.strip()
    if value in {"null", "~"}:
        return None
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def read_v1_receipt(path: Path) -> LegacyReceipt:
    fields: dict[str, object] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([a-z_]+):\s*(.*)", line)
        if match:
            fields[match.group(1)] = _scalar(match.group(2))
    if fields.get("schema") != "doc-warden-receipt/v1":
        raise ValueError("unsupported legacy receipt")
    required = ("repo", "policy_version", "observed_outcome")
    if any(not isinstance(fields.get(key), str) or not fields[key] for key in required):
        raise ValueError("malformed legacy receipt")
    return LegacyReceipt(
        path=path,
        schema="doc-warden-receipt/v1",
        repository=str(fields["repo"]),
        policy_version=str(fields["policy_version"]),
        observed_outcome=str(fields["observed_outcome"]),
        content_digest=digest_ref(path.read_bytes()),
    )


def write_receipt_v2(record: dict[str, Any], destination: Path, repo: Path) -> dict[str, Any]:
    """Persist an already-complete receipt record after closed-schema validation."""
    receipt = dict(record)
    validate_egress("receipt", receipt)
    relative = str(destination.relative_to(repo))
    atomic_write(repo, relative, canonical_json(receipt))
    return receipt


def observe_delivery(
    receipt: dict[str, Any],
    *,
    repo: Path,
    delivery_commit: str,
    pull_request: str | None = None,
    default_branch: str = "main",
) -> dict[str, Any]:
    if receipt.get("delivery_commit") is not None:
        raise ValueError("delivery already observed")
    if not re.fullmatch(r"[0-9a-f]{40}", delivery_commit):
        raise ValueError("delivery commit must be a full SHA")
    event = {
        "schema": "doc-warden/operation-event/v2",
        "event_id": str(
            uuid.uuid5(uuid.UUID(receipt["event_id"]), f"delivery:{delivery_commit}")
        ),
        "operation_id": receipt["operation_id"],
        "transition": "delivery_observed",
        "action_digest": receipt["action_digest"],
        "source_revision": delivery_commit,
        "prior_event_digest": digest_ref(canonical_json(receipt)),
        "outcome": "applied",
        "details": {
            "delivery_commit": delivery_commit,
            "pull_request": pull_request,
            "default_branch": default_branch,
        },
    }
    require_valid("operation-event", event)
    event_root = repo / "_ops/doc-warden/state/v2/events"
    if event_root.exists():
        for path in event_root.glob("*.json"):
            existing = parse_json_object(path.read_bytes())
            if (
                existing.get("transition") == "delivery_observed"
                and existing.get("operation_id") == receipt["operation_id"]
            ):
                if existing == event:
                    return existing
                raise ValueError("delivery already observed")
    relative = f"_ops/doc-warden/state/v2/events/{event['event_id']}.json"
    destination = repo / relative
    rendered = canonical_json(event)
    if destination.exists():
        if not destination.is_file() or destination.read_bytes() != rendered:
            raise ValueError("delivery event collision")
    else:
        atomic_write(repo, relative, rendered)
    return event


def prepare_remote_identity_observation(
    repo: Path,
    *,
    repository: str,
    github_repository_id: int,
    authority_root: Path,
    operation_id: str,
) -> TransactionPreview:
    """Bind GitHub's immutable ID without changing the local repository key."""

    repo = repo.resolve(strict=True)
    authority = authority_root.resolve(strict=True)
    uuid.UUID(operation_id)
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
        or type(github_repository_id) is not int
        or github_repository_id <= 0
    ):
        raise ValueError("github_repository_identity_invalid")
    requested = _github_slug(_origin_url(repo))
    if requested.casefold() != repository.casefold():
        raise ValueError("github_repository_identity_mismatch")
    config = read_repository_config(repo)
    if config is None or not config["enabled"]:
        raise ValueError("v2_repository_profile_required")
    if config["github_repository_id"] not in {None, github_repository_id}:
        raise ValueError("github_repository_id_mismatch")

    updated = dict(config)
    updated["github_repository_id"] = github_repository_id
    require_valid("doc-warden-config", updated)
    relative = ".planning/doc-warden.json"
    identity = RepositoryIdentity(repository, github_repository_id)
    bindings = _bindings(authority)
    runtime = authority / "_ops/doc-warden/runtime/gsd-core"
    pin = (runtime / "gsd-core-pin.json").resolve(strict=True)
    interface = (runtime / "runtime-interface.v1.json").resolve(strict=True)
    bindings["gsd_interface_digest"] = digest_ref(interface.read_bytes())
    bindings["repository_identity"] = identity.receipt_binding()

    receipt_path = repo / "_ops/doc-warden/state/v2/receipts" / f"{operation_id}.json"
    recovery_preimages = None
    if config["github_repository_id"] == github_repository_id:
        prior = dict(config)
        prior["github_repository_id"] = None
        recovery_preimages = {relative: digest_ref(canonical_json(prior))}
        if receipt_path.is_file():
            existing = parse_json_object(receipt_path.read_bytes())
            require_valid("receipt", existing)
            if (
                existing["repository_key"] != config["repository_key"]
                or existing["github_repository_id"] != github_repository_id
                or not identity.matches_binding(existing["bindings"].get("repository_identity"))
            ):
                raise ValueError("remote_identity_receipt_mismatch")
            bindings["repository_identity"] = existing["bindings"]["repository_identity"]
            recovery_preimages = {
                relative: existing["preimages"].get(relative)
            }
    request = MutationRequest(
        repo=repo,
        repository_key=config["repository_key"],
        github_repository_id=github_repository_id,
        transition="projection_update",
        actions=(MutationAction(relative, canonical_json(updated), "replace"),),
        bindings=bindings,
        operation_id=operation_id,
        observed_inputs=(
            ObservedInput(str(pin), digest_ref(pin.read_bytes())),
            ObservedInput(str(interface), digest_ref(interface.read_bytes())),
        ),
        require_write_enabled=True,
    )
    preview = preview_transaction(request, recovery_preimages=recovery_preimages)
    event_path = contained_path(repo, _event_path(preview))
    if receipt_path.is_file() or not event_path.exists():
        return preview

    if recovery_preimages is None:
        raise ValueError("partial_operation_event_mismatch")
    persisted_event = event_path.read_bytes()
    if persisted_event == canonical_json(_event_for(preview)):
        return preview

    # Replay the raw-name receipt only when the existing event binds
    # every original action, preimage, input and authority exactly.
    legacy_request = replace(
        request, bindings={**bindings, "repository_identity": identity.binding()}
    )
    legacy = preview_transaction(legacy_request, recovery_preimages=recovery_preimages)
    if persisted_event != canonical_json(_event_for(legacy)):
        raise ValueError("partial_operation_event_mismatch")
    return legacy


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *arguments],
        text=True,
    ).strip()


def _authority_binding(
    root: Path,
    relative: str,
    source_revision: str,
) -> tuple[dict[str, Any], bytes]:
    path = root / relative
    committed = subprocess.check_output(
        ["git", "-C", str(root), "show", f"{source_revision}:{relative}"]
    )
    committed_digest = digest_ref(committed)
    worktree_digest = (
        digest_ref(path.read_bytes())
        if path.is_file() and not path.is_symlink()
        else None
    )
    return (
        {
            "path": relative,
            "digest": committed_digest,
            "source_revision": source_revision,
            "last_changed_revision": _git(
                root,
                "log",
                "-1",
                "--format=%H",
                "--",
                relative,
            ),
            "worktree_matches_committed": worktree_digest == committed_digest,
        },
        committed,
    )


_QUALIFICATION_REPOSITORY = "KleinPerkins/dev"
_QUALIFICATION_RECEIPT_SCHEMA = "pr-automation-controller-qualification/v1"
_QUALIFICATION_AUTHORITY = "validated_protected_recipe"
_QUALIFICATION_CHECK_NAME = "pr-automation / qualify"
_QUALIFICATION_CHECK_TITLE = "Protected recipe qualification passed"
_QUALIFICATION_ID_DOMAIN = b"pr-automation-qualification/v1\0"
_QUALIFICATION_RELEASE = {
    "version": "v0.13.0",
    "commit": "9be8235a76ae241a925b1273c9688ccdadfc8548",
    "digest": "sha256:3d0b6b34d29b6d0c9ae94daa8dd4cd1182ae3bb9375944322c58febc52fec07c",
}
_QUALIFICATION_VERIFIER_APP_ID = 4274739
_QUALIFICATION_RELEVANT_AUTHORITIES = (
    "coverage_assignments",
    "controller",
    "recipe",
    "lock",
)
_QUALIFICATION_RECEIPT_FIELDS = {
    "schema",
    "qualification_id",
    "authority",
    "repository",
    "revision",
    "job_id",
    "argv",
    "recipe_digest",
    "lock_digest",
    "profile_id",
    "profile_digest",
    "image_digest",
    "controller_release_digest",
    "check_name",
    "check_run_id",
    "conclusion",
    "exit_code",
    "supersedes_legacy_m3_candidate",
}
QualificationCheckObserver = Callable[[str, int], dict[str, Any]]


def _qualification_blocked(
    reason: str,
    *,
    receipt_count: int,
    receipt: dict[str, Any] | None = None,
    check_observed: bool = False,
) -> dict[str, Any]:
    return {
        "status": "blocked_external_dependency",
        "qualified": False,
        "reason": reason,
        "receipt_count": receipt_count,
        "qualification_id": (
            receipt.get("qualification_id") if receipt is not None else None
        ),
        "revision": receipt.get("revision") if receipt is not None else None,
        "check_run_id": (
            receipt.get("check_run_id") if receipt is not None else None
        ),
        "check_observed": check_observed,
    }


def _qualification_receipt_is_closed(receipt: dict[str, Any]) -> bool:
    string_fields = (
        "schema",
        "qualification_id",
        "authority",
        "repository",
        "revision",
        "job_id",
        "recipe_digest",
        "lock_digest",
        "profile_id",
        "profile_digest",
        "image_digest",
        "controller_release_digest",
        "check_name",
        "conclusion",
    )
    return bool(
        set(receipt) == _QUALIFICATION_RECEIPT_FIELDS
        and all(
            isinstance(receipt.get(field), str) and receipt[field]
            for field in string_fields
        )
        and isinstance(receipt.get("argv"), list)
        and receipt["argv"]
        and len(receipt["argv"]) <= 64
        and all(
            isinstance(argument, str)
            and argument
            and len(argument) <= 4096
            and "\0" not in argument
            for argument in receipt["argv"]
        )
        and type(receipt.get("check_run_id")) is int
        and receipt["check_run_id"] > 0
        and type(receipt.get("exit_code")) is int
        and type(receipt.get("supersedes_legacy_m3_candidate")) is bool
        and re.fullmatch(r"[0-9a-f]{40}", receipt["revision"])
        and re.fullmatch(r"sha256:[0-9a-f]{64}", receipt["qualification_id"])
        and all(
            re.fullmatch(r"sha256:[0-9a-f]{64}", receipt[field])
            for field in (
                "recipe_digest",
                "lock_digest",
                "profile_digest",
                "controller_release_digest",
            )
        )
        and re.fullmatch(
            r"[^@\s]+@sha256:[0-9a-f]{64}",
            receipt["image_digest"],
        )
    )


def _qualification_id(receipt: dict[str, Any]) -> str:
    identity = {
        "repository": receipt["repository"],
        "revision": receipt["revision"],
        "job_id": receipt["job_id"],
        "recipe_digest": receipt["recipe_digest"],
        "lock_digest": receipt["lock_digest"],
        "profile_digest": receipt["profile_digest"],
        "image_digest": receipt["image_digest"],
        "controller_release_digest": receipt["controller_release_digest"],
    }
    canonical = canonical_json(identity)[:-1]
    return digest_ref(_QUALIFICATION_ID_DOMAIN + canonical)


def _qualification_check_summary(receipt: dict[str, Any]) -> str:
    return "\n".join(
        (
            f"authority={_QUALIFICATION_AUTHORITY}",
            f"repository={receipt['repository']}",
            f"revision={receipt['revision']}",
            f"job_id={receipt['job_id']}",
            f"recipe_digest={receipt['recipe_digest']}",
            f"lock_digest={receipt['lock_digest']}",
            f"controller_release_digest={receipt['controller_release_digest']}",
            "conclusion=success",
        )
    )


def _read_qualification_check(
    repository: str,
    check_run_id: int,
) -> dict[str, Any]:
    result = subprocess.run(
        [
            "gh",
            "api",
            (
                f"repos/{quote(repository, safe='/')}/"
                f"check-runs/{check_run_id}"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise ValueError("qualification_check_unavailable")
    return parse_json_object(result.stdout)


def _qualification_check_error(
    check: dict[str, Any],
    receipt: dict[str, Any],
    controller: dict[str, Any],
) -> str | None:
    app = check.get("app")
    if not isinstance(app, dict):
        return "qualification_check_identity_mismatch"
    verifier = controller["verifier"]
    if (
        app.get("id") != verifier["app_id"]
        or app.get("slug") != verifier["slug"]
        or verifier["app_id"] != verifier["integration_id"]
        or verifier["app_id"] != _QUALIFICATION_VERIFIER_APP_ID
    ):
        return "qualification_check_foreign_app"
    output = check.get("output")
    if not isinstance(output, dict):
        return "qualification_check_identity_mismatch"
    expected = {
        "id": receipt["check_run_id"],
        "name": _QUALIFICATION_CHECK_NAME,
        "head_sha": receipt["revision"],
        "status": "completed",
        "conclusion": "success",
        "external_id": receipt["qualification_id"],
    }
    if any(check.get(key) != value for key, value in expected.items()):
        return "qualification_check_identity_mismatch"
    if (
        output.get("title") != _QUALIFICATION_CHECK_TITLE
        or output.get("summary") != _qualification_check_summary(receipt)
    ):
        return "qualification_check_payload_mismatch"
    return None


def _git_revision_bytes(
    root: Path,
    revision: str,
    relative: str,
) -> bytes | None:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{revision}:{relative}"],
        check=False,
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def _controller_qualification_evidence(
    root: Path,
    *,
    source_revision: str,
    observations: dict[str, tuple[dict[str, Any], bytes]],
    records: dict[str, dict[str, Any]],
    observe_check: bool,
    check_observer: QualificationCheckObserver | None,
) -> dict[str, Any]:
    assignments = records["coverage_assignments"].get("assignments")
    candidates = records["qualification_ledger"].get("candidates")
    if not isinstance(assignments, list) or not isinstance(candidates, list):
        raise ValueError("runnerless_qualification_authority_malformed")
    source_assignments = [
        row
        for row in assignments
        if isinstance(row, dict) and row.get("repo") == _QUALIFICATION_REPOSITORY
    ]
    legacy_candidates = [
        row
        for row in candidates
        if isinstance(row, dict) and row.get("repo") == _QUALIFICATION_REPOSITORY
    ]
    if len(source_assignments) != 1 or len(legacy_candidates) != 1:
        raise ValueError("runnerless_source_authority_ambiguous")
    source_assignment = source_assignments[0]
    legacy_candidate = legacy_candidates[0]
    required = source_assignment.get("required_checks")
    required_job_id = required.get("job_id") if isinstance(required, dict) else None
    profile_ref = source_assignment.get("profile_ref")
    if (
        not isinstance(required_job_id, str)
        or not isinstance(profile_ref, dict)
        or legacy_candidate.get("status") != "canned_only"
    ):
        raise ValueError("runnerless_source_authority_malformed")

    recipe = records["recipe"]
    lock = records["lock"]
    controller = records["controller"]
    recipe_jobs = recipe.get("custom_jobs")
    lock_payload = lock.get("payload")
    release = controller.get("release")
    verifier = controller.get("verifier")
    images = controller.get("images")
    if (
        not isinstance(recipe_jobs, list)
        or not isinstance(lock_payload, dict)
        or not isinstance(release, dict)
        or not isinstance(verifier, dict)
        or not isinstance(images, dict)
    ):
        raise ValueError("runnerless_qualification_authority_malformed")
    matching_recipe_jobs = [
        job
        for job in recipe_jobs
        if isinstance(job, dict) and job.get("id") == required_job_id
    ]
    lock_jobs = lock_payload.get("jobs")
    if not isinstance(lock_jobs, list):
        raise ValueError("runnerless_qualification_authority_malformed")
    matching_lock_jobs = [
        job
        for job in lock_jobs
        if isinstance(job, dict)
        and isinstance(job.get("source_ref"), dict)
        and job["source_ref"].get("custom_id") == required_job_id
    ]
    if len(matching_recipe_jobs) != 1 or len(matching_lock_jobs) != 1:
        raise ValueError("runnerless_protected_recipe_binding_missing")
    recipe_job = matching_recipe_jobs[0]
    lock_job = matching_lock_jobs[0]
    recipe_argv = recipe_job.get("argv")
    lock_runtime = lock_job.get("runtime")
    lock_source = lock_job.get("source_ref")
    if (
        not isinstance(recipe_argv, list)
        or len(recipe_argv) < 2
        or recipe_argv[0] != "run-literal"
        or not isinstance(lock_runtime, dict)
        or lock_runtime.get("argv") != recipe_argv
        or lock_job.get("provenance_kind") != "protected_recipe"
        or not isinstance(lock_source, dict)
    ):
        raise ValueError("runnerless_protected_recipe_binding_mismatch")

    expected_release = {
        key: release.get(key) for key in _QUALIFICATION_RELEASE
    }
    profile_id = profile_ref.get("id")
    profile_digest = profile_ref.get("digest")
    image_digest = lock_payload.get("image_digest")
    if (
        expected_release != _QUALIFICATION_RELEASE
        or verifier.get("app_id") != _QUALIFICATION_VERIFIER_APP_ID
        or verifier.get("integration_id") != _QUALIFICATION_VERIFIER_APP_ID
        or lock_payload.get("repository_id") != "dev"
        or lock_payload.get("profile_id") != profile_id
        or lock_payload.get("profile_digest") != profile_digest
        or lock_payload.get("activation_generation")
        != release.get("activation_generation")
        or lock_runtime.get("image") != image_digest
        or images.get("execution") != image_digest
        or lock_source.get("recipe_digest") != lock_payload.get("recipe_digest")
        or lock_source.get("custom_id") != required_job_id
        or recipe.get("repository_id") != "dev"
    ):
        raise ValueError("runnerless_qualification_authority_mismatch")
    recipe_blob_sha = _git(
        root,
        "rev-parse",
        f"{source_revision}:.github/pr-recipe.json",
    )
    if (
        recipe_blob_sha != lock_payload.get("recipe_blob_sha")
        or lock_source.get("blob_sha") != recipe_blob_sha
    ):
        raise ValueError("runnerless_recipe_blob_binding_mismatch")

    receipts = records["qualification_ledger"].get("controller_qualifications")
    if receipts is None:
        return _qualification_blocked(
            "controller_qualification_receipt_missing",
            receipt_count=0,
        )
    if not isinstance(receipts, list) or any(
        not isinstance(receipt, dict) for receipt in receipts
    ):
        return _qualification_blocked(
            "controller_qualification_receipt_malformed",
            receipt_count=0,
        )
    source_receipts = [
        receipt
        for receipt in receipts
        if receipt.get("repository") == _QUALIFICATION_REPOSITORY
    ]
    if not source_receipts:
        return _qualification_blocked(
            "controller_qualification_receipt_missing",
            receipt_count=0,
        )
    if any(not _qualification_receipt_is_closed(receipt) for receipt in source_receipts):
        return _qualification_blocked(
            "controller_qualification_receipt_malformed",
            receipt_count=len(source_receipts),
        )
    qualification_ids = [
        receipt["qualification_id"] for receipt in source_receipts
    ]
    if len(qualification_ids) != len(set(qualification_ids)):
        return _qualification_blocked(
            "controller_qualification_receipt_duplicate",
            receipt_count=len(source_receipts),
        )

    expected_fields = {
        "schema": _QUALIFICATION_RECEIPT_SCHEMA,
        "authority": _QUALIFICATION_AUTHORITY,
        "repository": _QUALIFICATION_REPOSITORY,
        "job_id": required_job_id,
        "argv": recipe_argv[1:],
        "recipe_digest": lock_payload.get("recipe_digest"),
        "lock_digest": lock.get("lock_digest"),
        "profile_id": profile_id,
        "profile_digest": profile_digest,
        "image_digest": image_digest,
        "controller_release_digest": release.get("digest"),
        "check_name": _QUALIFICATION_CHECK_NAME,
        "conclusion": "success",
        "exit_code": 0,
        "supersedes_legacy_m3_candidate": True,
    }
    current_receipts = [
        receipt
        for receipt in source_receipts
        if all(receipt.get(key) == value for key, value in expected_fields.items())
    ]
    if not current_receipts:
        return _qualification_blocked(
            "controller_qualification_receipt_mismatch",
            receipt_count=len(source_receipts),
        )
    relative = {
        "coverage_assignments": (
            "_ops/baseline/profiles/pr-automation/v3/"
            "coverage-assignments.json"
        ),
        "controller": "_ops/baseline/profiles/pr-automation/v3/controller.json",
        "recipe": ".github/pr-recipe.json",
        "lock": ".github/pr-automation.lock.json",
    }
    valid_receipts = []
    for candidate_receipt in current_receipts:
        ancestor = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "merge-base",
                "--is-ancestor",
                candidate_receipt["revision"],
                source_revision,
            ],
            check=False,
            capture_output=True,
        )
        unchanged = all(
            _git_revision_bytes(
                root,
                candidate_receipt["revision"],
                relative[key],
            )
            == observations[key][1]
            for key in _QUALIFICATION_RELEVANT_AUTHORITIES
        )
        if ancestor.returncode == 0 and unchanged:
            valid_receipts.append(candidate_receipt)
    if not valid_receipts:
        return _qualification_blocked(
            "controller_qualification_receipt_stale",
            receipt_count=len(source_receipts),
            receipt=current_receipts[-1],
        )
    receipt = valid_receipts[-1]
    if legacy_candidate.get("argv") == receipt["argv"]:
        return _qualification_blocked(
            "legacy_candidate_not_superseded",
            receipt_count=len(source_receipts),
            receipt=receipt,
        )
    if receipt["qualification_id"] != _qualification_id(receipt):
        return _qualification_blocked(
            "controller_qualification_receipt_untrusted",
            receipt_count=len(source_receipts),
            receipt=receipt,
        )
    if not observe_check:
        return _qualification_blocked(
            "qualification_check_unobserved",
            receipt_count=len(source_receipts),
            receipt=receipt,
        )
    observer = check_observer or _read_qualification_check
    try:
        check = observer(_QUALIFICATION_REPOSITORY, receipt["check_run_id"])
    except (OSError, subprocess.SubprocessError, ValueError):
        return _qualification_blocked(
            "qualification_check_unavailable",
            receipt_count=len(source_receipts),
            receipt=receipt,
        )
    if not isinstance(check, dict):
        return _qualification_blocked(
            "qualification_check_unavailable",
            receipt_count=len(source_receipts),
            receipt=receipt,
        )
    check_error = _qualification_check_error(check, receipt, controller)
    if check_error is not None:
        return _qualification_blocked(
            check_error,
            receipt_count=len(source_receipts),
            receipt=receipt,
            check_observed=True,
        )
    return {
        "status": "qualified",
        "qualified": True,
        "reason": None,
        "receipt_count": len(source_receipts),
        "qualification_id": receipt["qualification_id"],
        "revision": receipt["revision"],
        "check_run_id": receipt["check_run_id"],
        "check_observed": True,
        "check_app_id": controller["verifier"]["app_id"],
        "check_name": _QUALIFICATION_CHECK_NAME,
    }


def runnerless_delivery_preview(
    authority_root: Path,
    *,
    repository: str,
    github_repository_id: int | None,
    observe_qualification_check: bool = True,
    qualification_check_observer: QualificationCheckObserver | None = None,
) -> dict[str, Any]:
    """Read exact runnerless authorities without claiming or changing them."""

    root = authority_root.resolve(strict=True)
    if not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
        repository,
    ):
        raise ValueError("github_repository_identity_invalid")
    if github_repository_id is not None and (
        type(github_repository_id) is not int or github_repository_id <= 0
    ):
        raise ValueError("github_repository_identity_invalid")
    relative = {
        "coverage_assignments": (
            "_ops/baseline/profiles/pr-automation/v3/"
            "coverage-assignments.json"
        ),
        "qualification_ledger": (
            "_ops/baseline/profiles/pr-automation/v3/"
            "qualification-ledger.json"
        ),
        "controller": (
            "_ops/baseline/profiles/pr-automation/v3/controller.json"
        ),
        "fleet": "_ops/baseline/profiles/pr-automation/v3/fleet.json",
        "recipe": ".github/pr-recipe.json",
        "lock": ".github/pr-automation.lock.json",
    }
    source_revision = _git(root, "rev-parse", "HEAD")
    observations = {
        key: _authority_binding(root, path, source_revision)
        for key, path in relative.items()
    }
    bindings = {key: observation[0] for key, observation in observations.items()}
    records = {
        key: parse_json_object(observation[1])
        for key, observation in observations.items()
    }
    authority_worktree_drift = sorted(
        key
        for key, binding in bindings.items()
        if not binding["worktree_matches_committed"]
    )
    assignments = records["coverage_assignments"]["assignments"]
    source_assignment = next(
        (
            row
            for row in assignments
            if row.get("repo") == "KleinPerkins/dev"
        ),
        None,
    )
    if source_assignment is None:
        raise ValueError("runnerless_source_assignment_missing")
    required = source_assignment.get("required_checks")
    required_job_id = required.get("job_id") if isinstance(required, dict) else None
    recipe_jobs = records["recipe"]["custom_jobs"]
    recipe_job = next(
        (job for job in recipe_jobs if job.get("id") == required_job_id),
        None,
    )
    lock_jobs = records["lock"]["payload"]["jobs"]
    lock_job = next(
        (
            job
            for job in lock_jobs
            if job.get("source_ref", {}).get("custom_id")
            == required_job_id
        ),
        None,
    )
    candidate = next(
        (
            row
            for row in records["qualification_ledger"]["candidates"]
            if row.get("repo") == "KleinPerkins/dev"
        ),
        None,
    )
    disposition = (
        candidate.get("status")
        if isinstance(candidate, dict)
        else "unqualified"
    )
    protected_recipe_bound = bool(
        recipe_job
        and lock_job
        and lock_job.get("provenance_kind") == "protected_recipe"
        and lock_job.get("runtime", {}).get("argv") == recipe_job.get("argv")
    )
    controller_qualification = _controller_qualification_evidence(
        root,
        source_revision=source_revision,
        observations=observations,
        records=records,
        observe_check=observe_qualification_check,
        check_observer=qualification_check_observer,
    )
    source_lane_qualified = bool(
        controller_qualification["qualified"]
        and protected_recipe_bound
        and not authority_worktree_drift
    )
    target_assignment = next(
        (row for row in assignments if row.get("repo") == repository),
        None,
    )
    target_fleet = next(
        (
            row
            for row in records["fleet"]["targets"]
            if row.get("repo") == repository
        ),
        None,
    )
    hard_exclusions = records["controller"]["hard_exclusions"]
    documentation_only = repository == "KleinPerkins/chaos-scheduler"
    target_exclusion = next(
        (
            row
            for row in records["fleet"]["excluded"]
            if row.get("repo") == repository
        ),
        None,
    )
    if documentation_only and (
        repository not in hard_exclusions
        or target_exclusion is None
    ):
        raise ValueError("chaos_scheduler_exclusion_missing")
    target_assigned = bool(
        target_assignment is not None
        and target_fleet is not None
        and not documentation_only
    )
    target_identity_bound = bool(
        target_assigned
        and github_repository_id is not None
        and target_fleet["repository_id"] == github_repository_id
    )
    ac_049_closed = bool(
        source_lane_qualified
        and target_identity_bound
        and not authority_worktree_drift
    )
    qualification_state = (
        "documentation_only"
        if documentation_only
        else ("qualified" if ac_049_closed else "waiting_external")
    )
    workflow_root = root / ".github/workflows"
    workflows = (
        [
            str(path.relative_to(root))
            for path in sorted(workflow_root.rglob("*"))
            if path.is_file() or path.is_symlink()
        ]
        if workflow_root.exists()
        else []
    )
    if workflows:
        raise ValueError("committed_actions_workflow_refused")
    release = records["controller"]["release"]
    if documentation_only:
        external_gate_reason = "chaos_scheduler_is_documentation_only"
    elif ac_049_closed:
        external_gate_reason = None
    elif authority_worktree_drift:
        external_gate_reason = "runnerless_authority_worktree_drift"
    elif not controller_qualification["qualified"]:
        external_gate_reason = (
            controller_qualification["reason"]
            or "controller_qualification_not_qualified"
        )
    elif not protected_recipe_bound:
        external_gate_reason = "protected_recipe_binding_missing"
    else:
        external_gate_reason = "target_enrollment_or_identity_binding_required"
    return {
        "schema": "doc-warden/delivery-preview/v1",
        "source_revision": source_revision,
        "source_tree": _git(root, "rev-parse", f"{source_revision}^{{tree}}"),
        "target": {
            "repository": repository,
            "github_repository_id": github_repository_id,
            "exclusion_reason": (
                target_exclusion.get("reason")
                if documentation_only
                else None
            ),
        },
        "qualification_state": qualification_state,
        "ac_049_closed": ac_049_closed,
        "source_lane": {
            "repository": "KleinPerkins/dev",
            "required_job_id": required_job_id,
            "qualification_disposition": disposition,
            "protected_recipe_bound": protected_recipe_bound,
            "qualified": source_lane_qualified,
            "controller_qualification": controller_qualification,
        },
        "target_staging": {
            "assigned": target_assigned,
            "identity_bound": target_identity_bound,
            "allowed": ac_049_closed,
            "state": "documentation_only" if documentation_only else "inert",
            "activation_performed": False,
        },
        "controller_release": {
            "version": release["version"],
            "commit": release["commit"],
            "digest": release["digest"],
            "lock_compiler_digest": release["lock_compiler_digest"],
            "activation_generation": release["activation_generation"],
        },
        "authority_bindings": bindings,
        "authority_observation": {
            "trusted_source": "committed_revision",
            "worktree_drift": authority_worktree_drift,
        },
        "warnings": (
            [
                {
                    "code": "runnerless_authority_worktree_drift",
                    "authorities": authority_worktree_drift,
                    "effect": "runnerless_staging_disallowed",
                }
            ]
            if authority_worktree_drift
            else []
        ),
        "workflow_files": [],
        "auto_merge_armed": False,
        "actions_taken": [],
        "external_gate": {
            "required": not ac_049_closed,
            "owner": "KleinPerkins/pr-automation-controller",
            "reason": external_gate_reason,
            "control_plane_mutation_performed": False,
        },
    }
