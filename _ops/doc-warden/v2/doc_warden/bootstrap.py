"""Restricted one-time adoption of the accepted section-zero authorities."""

from __future__ import annotations

import argparse
import re
import subprocess
import uuid
from pathlib import Path

from .artifacts import _bindings
from .canonical import canonical_json, digest_ref, parse_json_object
from .transactions import (
    MutationAction,
    MutationRequest,
    apply_transaction,
    confirmation_for,
    preview_transaction,
)


ACCEPTED_COMMIT = "3e6e096c0bdcae0d37666a5d8a7f1ce35c53a045"
ACCEPTED_PATHS = (
    "_ops/adr/0009-doc-warden-v2-gsd-aligned-governance.md",
    "_ops/plans/doc-warden-execution-plan-v2.md",
)
DEV_REPOSITORY_KEY = "18c71d9a-d928-4d45-b048-4b063f14957f"
DEV_REMOTES = {
    "git@github.com:KleinPerkins/dev",
    "git@github.com:KleinPerkins/dev.git",
    "https://github.com/KleinPerkins/dev",
    "https://github.com/KleinPerkins/dev.git",
}
def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _authority_binding(repo: Path, commit: str, path: str) -> dict[str, str]:
    content = subprocess.check_output(["git", "-C", str(repo), "show", f"{commit}:{path}"])
    return {
        "path": path,
        "commit": commit,
        "git_blob": _git(repo, "rev-parse", f"{commit}:{path}"),
        "content_digest": digest_ref(content),
        "transition": "accepted_freeze",
    }


def adopt_accepted_authorities(
    repo: Path,
    commit: str,
    paths: tuple[str, ...] = ACCEPTED_PATHS,
    operation_id: str | None = None,
):
    repo = repo.resolve(strict=True)
    if commit != ACCEPTED_COMMIT:
        raise ValueError("section0_commit_refused")
    if tuple(paths) != ACCEPTED_PATHS:
        raise ValueError("section0_path_refused")
    if _git(repo, "remote", "get-url", "origin") not in DEV_REMOTES:
        raise ValueError("section0_repository_refused")
    if subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", commit, "HEAD"], check=False
    ).returncode:
        raise ValueError("section0_commit_not_in_history")
    for path in paths:
        if _git(repo, "rev-parse", f"HEAD:{path}") != _git(repo, "rev-parse", f"{commit}:{path}"):
            raise ValueError("section0_authority_drift")
    bindings = [_authority_binding(repo, commit, path) for path in paths]
    operation_id = operation_id or str(uuid.uuid4())
    adoption = {
        "schema": "doc-warden/section0-adoption/v1",
        "operation_id": operation_id,
        "decision": "operator-approved-section0",
        "accepted_commit": commit,
        "bindings": bindings,
    }
    relative = f"_ops/doc-warden/state/v2/adoption/{operation_id}.json"
    adoption_root = repo / "_ops/doc-warden/state/v2/adoption"
    existing_adoptions = sorted(adoption_root.glob("*.json")) if adoption_root.exists() else []
    recovering = False
    if existing_adoptions:
        if len(existing_adoptions) != 1:
            raise ValueError("section0_adoption_state_ambiguous")
        existing_path = existing_adoptions[0]
        existing = parse_json_object(existing_path.read_bytes())
        if (
            existing.get("schema") != "doc-warden/section0-adoption/v1"
            or existing.get("accepted_commit") != commit
        ):
            raise ValueError("section0_adoption_state_ambiguous")
        if existing.get("operation_id") != operation_id:
            raise ValueError("section0_already_adopted")
        if existing_path != repo / relative or existing != adoption:
            raise ValueError("section0_adoption_state_ambiguous")
        recovering = True
    dirty_paths = {
        line[3:]
        for line in _git(repo, "status", "--porcelain", "--untracked-files=all").splitlines()
        if line
    }
    event_id = str(uuid.uuid5(uuid.UUID(operation_id), "terminal-event"))
    allowed_recovery_paths = {
        relative,
        f"_ops/doc-warden/state/v2/events/{event_id}.json",
        f"_ops/doc-warden/state/v2/receipts/{operation_id}.json",
    }
    allowed_temp_prefixes = {
        str(Path(path).parent / f".{Path(path).name}.") for path in allowed_recovery_paths
    }
    only_recovery_paths = all(
        path in allowed_recovery_paths
        or any(
            path.startswith(prefix)
            and re.fullmatch(r"[a-z0-9_]{8}", path[len(prefix) :]) is not None
            for prefix in allowed_temp_prefixes
        )
        for path in dirty_paths
    )
    if dirty_paths and (not recovering or not only_recovery_paths):
        raise ValueError("section0_requires_clean_tree")
    binding_digests = _bindings(repo)
    return preview_transaction(
        MutationRequest(
            repo=repo,
            repository_key=DEV_REPOSITORY_KEY,
            transition="accepted_freeze",
            actions=(MutationAction(relative, canonical_json(adoption), "create"),),
            bindings=binding_digests,
            operation_id=operation_id,
        ),
        recovery_preimages={relative: None} if recovering else None,
    )


def _preview_dict(preview) -> dict[str, object]:
    return {
        "schema": "doc-warden/transaction-preview/v2",
        "operation_id": preview.operation_id,
        "event_id": preview.event_id,
        "source_revision": preview.source_revision,
        "action_digest": preview.action_digest,
        "canonical_root": preview.canonical_root,
        "transition": preview.transition,
        "paths": [action.path for action in preview.actions],
        "postimages": preview.postimages,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    adopt = sub.add_parser("adopt-section0")
    adopt.add_argument("--repo", type=Path, default=Path.cwd())
    adopt.add_argument("--commit", required=True)
    mode = adopt.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--apply", action="store_true")
    adopt.add_argument("--operation-id")
    adopt.add_argument("--action-digest")
    adopt.add_argument("--confirm")
    args = parser.parse_args(argv)
    preview = adopt_accepted_authorities(args.repo, args.commit, operation_id=args.operation_id)
    if args.preview:
        print(canonical_json(_preview_dict(preview)).decode(), end="")
        return 0
    if (
        args.operation_id != preview.operation_id
        or args.action_digest != preview.action_digest
        or args.confirm != "Apply"
    ):
        raise SystemExit("exact operation, action digest, and confirmation 'Apply' required")
    receipt = apply_transaction(preview, confirmation_for(preview))
    print(canonical_json(receipt).decode(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
