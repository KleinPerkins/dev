"""Shared born-v2 scaffold and verifier for ``dev-new-repo``."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .artifacts import _bindings, draft_artifact, repository_profile
from .canonical import canonical_json, digest_ref, parse_artifact, parse_json_object
from .roadmap import new_roadmap_item, parse_roadmap, render_roadmap
from .transactions import (
    MutationAction,
    MutationRequest,
    ObservedInput,
    TransactionPreview,
    preview_transaction,
)
from .validators import read_repository_config, require_valid


REQUIRED_BASELINE = (
    "README.md",
    "SECURITY.md",
    ".github/CODEOWNERS",
    ".github/dependabot.yml",
    ".gitignore",
)
GUARDS = (
    "identity-guard",
    "session-lock",
    "data-guard",
    "registration-guard",
)
HEAVY_ARTIFACTS = (
    ".planning/PRD.md",
    ".planning/SPEC.md",
    ".planning/UI-SPEC.md",
)


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise ValueError("greenfield_git_state_invalid")
    return result.stdout.strip()


def _guard_manifest(repo: Path) -> bytes:
    hook_root = Path(
        _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    ) / "hooks"
    for name in (*GUARDS, "pre-commit"):
        path = hook_root / name
        if not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError("greenfield_guard_missing")
    if "managed-by: KleinPerkins/dev identity-guard" not in (
        hook_root / "pre-commit"
    ).read_text(encoding="utf-8"):
        raise ValueError("greenfield_guard_unmanaged")
    return canonical_json(
        {
            "schema": "doc-warden/guard-state/v1",
            "commit_hook": "identity-session-data-registration",
            "identity_guard": "installed",
            "session_lock": "installed",
            "data_guard": "installed",
            "registration_guard": "installed",
            "worktree_policy": "host-governed",
        }
    )


def _agents_pointer(name: str) -> bytes:
    return (
        f"# {name} agent entrypoint\n\n"
        "This repository is born under doc-warden v2 governance.\n\n"
        "<!-- doc-warden:begin -->\n"
        "## Documentation governance\n\n"
        "| Artifact type | Location |\n"
        "|---|---|\n"
        "| Project, roadmap, and state | `.planning/` |\n"
        "| Phase plans | `.planning/phases/` |\n"
        "| ADRs | `docs/adr/` |\n"
        "| Runbooks | `docs/runbooks/` |\n\n"
        "**Policy:** `~/dev/_ops/doc-warden/POLICY.md`\n"
        "**Engine:** `~/dev/_ops/bin/doc-warden.sh doctor repo --repo .`\n"
        "<!-- doc-warden:end -->\n"
    ).encode("utf-8")


def _recovery_preimages(
    repo: Path,
    actions: tuple[MutationAction, ...],
) -> dict[str, str | None] | None:
    recovered: dict[str, str | None] = {}
    for action in actions:
        destination = repo / action.path
        if not destination.exists():
            continue
        if (
            destination.is_symlink()
            or not destination.is_file()
            or destination.read_bytes() != action.content
        ):
            raise ValueError("greenfield_existing_path_conflict")
        recovered[action.path] = None
    return recovered or None


def greenfield_v2(
    repo: Path,
    name: str,
    repository_key: str,
    *,
    authority_root: Path,
    operation_id: str,
) -> TransactionPreview:
    """Build one replayable transaction for the first guarded commit."""

    repo = repo.resolve(strict=True)
    authority = authority_root.resolve(strict=True)
    uuid.UUID(repository_key)
    uuid.UUID(operation_id)
    if _git(repo, "rev-parse", "--show-toplevel") != str(repo):
        raise ValueError("greenfield_root_mismatch")
    if _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD") != "main":
        raise ValueError("greenfield_main_required")
    if any(not (repo / path).is_file() for path in REQUIRED_BASELINE):
        raise ValueError("greenfield_baseline_required")
    if list((repo / ".github").glob("workflows/*")):
        raise ValueError("greenfield_workflow_refused")
    persisted = read_repository_config(repo)
    if persisted is not None and (
        persisted["repository_key"] != repository_key
        or persisted["github_repository_id"] is not None
    ):
        raise ValueError("greenfield_repository_identity_conflict")

    runtime = authority / "_ops/doc-warden/runtime/gsd-core"
    pin = (runtime / "gsd-core-pin.json").resolve(strict=True)
    interface = (runtime / "runtime-interface.v1.json").resolve(strict=True)
    profile = repository_profile(
        repo,
        repository_key,
        binding_root=authority,
    )
    profile["legacy_roots"] = []
    require_valid("doc-warden-config", profile)
    artifact_preview = draft_artifact(
        "project",
        {
            "title": name,
            "body": f"# {name}\n\nBorn-v2 project authority.",
        },
        repo=repo,
        operation_id=operation_id,
        repository_key_override=repository_key,
        binding_root=authority,
    )
    artifact_id = artifact_preview.artifact_id
    artifact_actions = tuple(
        action
        for action in artifact_preview.transaction.actions
        if action.path != ".planning/doc-warden.json"
    )
    if len(artifact_actions) != 1:
        raise ValueError("greenfield_project_action_invalid")
    source_revision = _git(repo, "rev-parse", "--verify", "HEAD") if (
        subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    ) else "no-head"
    roadmap = new_roadmap_item(
        repository_key=repository_key,
        item_id=(
            f"ROAD-{repository_key}-"
            f"{uuid.uuid5(uuid.UUID(operation_id), 'roadmap')}"
        ),
        outcome="Define the first product outcome",
        source_revision=source_revision,
    )
    bindings = dict(artifact_preview.transaction.bindings)
    bindings["gsd_interface_digest"] = digest_ref(interface.read_bytes())
    actions = (
        MutationAction(
            ".planning/doc-warden.json",
            canonical_json(profile),
            "create",
        ),
        *artifact_actions,
        MutationAction(
            ".planning/PROJECT.md",
            f"# {name}\n\nCanonical project: `{artifact_id}`\n".encode("utf-8"),
            "create",
        ),
        MutationAction(
            ".planning/ROADMAP.md",
            render_roadmap([roadmap]),
            "create",
        ),
        MutationAction(
            ".planning/STATE.md",
            (
                "# Authoring state\n\n"
                f"- Repository key: `{repository_key}`\n"
                "- Lifecycle: planned\n"
                "- Next action: classify rigor\n"
            ).encode("utf-8"),
            "create",
        ),
        MutationAction(
            ".planning/SKILL.md",
            (
                "# Doc-warden\n\n"
                "Use the global `doc-warden` skill and this repository-local "
                "v2 profile.\n"
            ).encode("utf-8"),
            "create",
        ),
        MutationAction(
            ".planning/guards.json",
            _guard_manifest(repo),
            "create",
        ),
        MutationAction("AGENTS.md", _agents_pointer(name), "create"),
        MutationAction(
            "docs/adr/README.md",
            (
                "# Architecture decision records\n\n"
                "Accepted decisions are immutable; semantic changes use successors.\n"
            ).encode("utf-8"),
            "create",
        ),
    )
    return preview_transaction(
        MutationRequest(
            repo=repo,
            repository_key=repository_key,
            transition="creation_snapshot",
            actions=actions,
            bindings=bindings,
            operation_id=operation_id,
            observed_inputs=(
                ObservedInput(str(pin), digest_ref(pin.read_bytes())),
                ObservedInput(str(interface), digest_ref(interface.read_bytes())),
            ),
            require_write_enabled=True,
        ),
        recovery_preimages=_recovery_preimages(repo, actions),
    )


def verify_born_v2(
    repo: Path,
    *,
    authority_root: Path,
    repository_key: str | None = None,
    github_repository_id: int | None = None,
) -> dict[str, Any]:
    """Verify the proportional scaffold without creating or mutating a remote."""

    repo = repo.resolve(strict=True)
    authority = authority_root.resolve(strict=True)
    config = read_repository_config(repo)
    if config is None or not config["enabled"]:
        raise ValueError("greenfield_profile_missing")
    if repository_key is not None and config["repository_key"] != repository_key:
        raise ValueError("repository_key_mismatch")
    if config["github_repository_id"] != github_repository_id:
        raise ValueError("github_repository_id_mismatch")
    runtime = authority / "_ops/doc-warden/runtime/gsd-core"
    if config["gsd_pin_digest"] != digest_ref(
        (runtime / "gsd-core-pin.json").read_bytes()
    ):
        raise ValueError("greenfield_gsd_pin_mismatch")
    if config["gsd_interface_digest"] != digest_ref(
        (runtime / "runtime-interface.v1.json").read_bytes()
    ):
        raise ValueError("greenfield_gsd_interface_mismatch")

    missing = [
        path
        for path in (
            *REQUIRED_BASELINE,
            "AGENTS.md",
            "docs/adr/README.md",
            ".planning/doc-warden.json",
            ".planning/PROJECT.md",
            ".planning/ROADMAP.md",
            ".planning/STATE.md",
            ".planning/SKILL.md",
            ".planning/guards.json",
        )
        if not (repo / path).is_file()
    ]
    if missing:
        raise ValueError("greenfield_required_path_missing")
    _guard_manifest(repo)
    guard_state = parse_json_object((repo / ".planning/guards.json").read_bytes())
    if set(guard_state) != {
        "schema",
        "commit_hook",
        "identity_guard",
        "session_lock",
        "data_guard",
        "registration_guard",
        "worktree_policy",
    } or guard_state["schema"] != "doc-warden/guard-state/v1":
        raise ValueError("greenfield_guard_state_invalid")

    projects = []
    for path in sorted((repo / ".planning/artifacts").glob("*.md")):
        parsed = parse_artifact(path)
        require_valid("artifact", parsed.metadata)
        if parsed.metadata["repository_key"] != config["repository_key"]:
            raise ValueError("greenfield_artifact_repository_mismatch")
        if parsed.metadata["type"] != "project":
            raise ValueError("greenfield_heavy_artifact_refused")
        projects.append(parsed.metadata)
    if len(projects) != 1:
        raise ValueError("greenfield_project_authority_missing")
    roadmap = parse_roadmap(repo / ".planning/ROADMAP.md")
    if (
        len(roadmap) != 1
        or not roadmap[0]["id"].startswith(f"ROAD-{config['repository_key']}-")
    ):
        raise ValueError("greenfield_roadmap_invalid")

    workflow_files = [
        str(path.relative_to(repo))
        for path in sorted((repo / ".github").glob("workflows/**/*"))
        if path.is_file() or path.is_symlink()
    ]
    if workflow_files:
        raise ValueError("greenfield_workflow_refused")
    heavy = [path for path in HEAVY_ARTIFACTS if (repo / path).exists()]
    if heavy:
        raise ValueError("greenfield_heavy_artifact_refused")
    receipt_root = repo / "_ops/doc-warden/state/v2/receipts"
    receipts = []
    for path in sorted(receipt_root.glob("*.json")):
        receipt = parse_json_object(path.read_bytes())
        require_valid("receipt", receipt)
        if receipt["repository_key"] != config["repository_key"]:
            raise ValueError("greenfield_receipt_repository_mismatch")
        receipts.append(receipt)
    if not any(
        receipt["transition"] == "creation_snapshot"
        and receipt["bindings"] == {
            **_bindings(authority),
            "gsd_interface_digest": config["gsd_interface_digest"],
        }
        for receipt in receipts
    ):
        raise ValueError("greenfield_authority_receipt_missing")
    return {
        "schema": "doc-warden/born-v2-verification/v1",
        "status": "verified",
        "repository_key": config["repository_key"],
        "github_repository_id": config["github_repository_id"],
        "enabled": True,
        "project_artifact_id": projects[0]["id"],
        "heavy_artifacts": [],
        "workflow_files": [],
        "guard_state": guard_state,
        "receipt_count": len(receipts),
        "authority_revision": _git(authority, "rev-parse", "HEAD"),
    }
