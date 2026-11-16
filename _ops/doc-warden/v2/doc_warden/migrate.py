"""Read-only construction of an applicable, identity-bound migration operation."""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from .artifacts import _bindings, repository_profile
from .canonical import canonical_json, digest_ref
from .receipts import read_v1_receipt
from .scm import RepositoryIdentity, observe_repository_identity
from .transactions import (
    MutationAction,
    MutationRequest,
    ObservedInput,
    TransactionPreview,
    preview_transaction,
)
from .validators import read_repository_config, require_valid


# This immutable report is not a receipt or approval. Recognize only its exact
# historical bytes; future/modified reports require separate review. Its original
# target_repo_root is historical context, never the authority for a live target.
_HISTORICAL_POC_REPORTS = {
    "sha256:a722a4b22b98cd62e14bd862472615498dcfd2b0007576fe52f7a1ab796b6eff":
        "KleinPerkins/ecosystem-orchestrator",
}


@dataclass(frozen=True)
class LegacyEvidence:
    path: str
    digest: str
    classification: str
    resolution: str
    source_path: Path


@dataclass(frozen=True)
class MigrationPlan:
    repository_key: str
    repository_identity: RepositoryIdentity
    source_revision: str
    gsd_interface_digest: str
    legacy_evidence: tuple[LegacyEvidence, ...]
    transaction: TransactionPreview | None
    status: str

    @property
    def writes(self) -> tuple[str, ...]:
        if self.transaction is None:
            return ()
        return tuple(action.path for action in self.transaction.actions)


def _logical_evidence_path(
    path: Path,
    *,
    repo: Path,
    authority_root: Path,
    legacy_state: Path,
) -> str:
    for root in (repo, authority_root):
        try:
            return str(path.relative_to(root))
        except ValueError:
            pass
    return f"legacy-state/{path.relative_to(legacy_state)}"


def _legacy_evidence(
    state: Path,
    *,
    repo: Path,
    authority_root: Path,
    repository: str,
) -> tuple[LegacyEvidence, ...]:
    evidence = []
    if not state.exists():
        return ()
    if state.is_symlink() or not state.is_dir():
        raise ValueError("legacy_state_invalid")
    for path in sorted(state.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("legacy_receipt_invalid")
        if path.suffix not in {".yml", ".yaml"}:
            raise ValueError("legacy_receipt_invalid")
        digest = digest_ref(path.read_bytes())
        historical_owner = _HISTORICAL_POC_REPORTS.get(digest)
        if historical_owner is not None:
            if historical_owner != repository:
                raise ValueError("legacy_repository_identity_mismatch")
            classification = "unresolved_legacy_binding"
            resolution = "operator_decision_required"
        else:
            receipt = read_v1_receipt(path)
            if receipt.repository != repository.split("/", 1)[1]:
                raise ValueError("legacy_repository_identity_mismatch")
            digest = receipt.content_digest
            classification = "creation_skeleton"
            resolution = "adopted"
        evidence.append(
            LegacyEvidence(
                path=_logical_evidence_path(
                    path,
                    repo=repo,
                    authority_root=authority_root,
                    legacy_state=state,
                ),
                digest=digest,
                classification=classification,
                resolution=resolution,
                source_path=path.resolve(strict=True),
            )
        )
    return tuple(evidence)


def migration_preview(
    repo: Path,
    *,
    authority_root: Path | None = None,
    legacy_state: Path | None = None,
    operation_id: str | None = None,
) -> MigrationPlan:
    repo = repo.resolve(strict=True)
    authority = (
        authority_root.resolve(strict=True)
        if authority_root is not None
        else Path(__file__).resolve().parents[4]
    )
    identity = observe_repository_identity(repo)
    config = read_repository_config(repo)
    if (
        config is not None
        and config["github_repository_id"] not in {
            None,
            identity.github_repository_id,
        }
    ):
        raise ValueError("github_repository_id_mismatch")
    if config is not None and config["enabled"]:
        return MigrationPlan(
            repository_key=config["repository_key"],
            repository_identity=identity,
            source_revision=_head(repo),
            gsd_interface_digest=config["gsd_interface_digest"],
            legacy_evidence=(),
            transaction=None,
            status="already_v2",
        )
    dirty = subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain"],
        text=True,
    ).strip()
    if dirty:
        raise ValueError("migration_repository_dirty")
    effective_operation_id = operation_id or str(uuid.uuid4())
    operation_uuid = uuid.UUID(effective_operation_id)
    repository_key = (
        config["repository_key"]
        if config is not None
        else str(
            uuid.uuid5(
                operation_uuid,
                f"repository-key:{identity.github_repository_id}",
            )
        )
    )
    state = (
        legacy_state.resolve(strict=True)
        if legacy_state is not None
        else authority
        / "_ops/doc-warden/state"
        / identity.repository.split("/", 1)[1]
    )
    evidence = _legacy_evidence(
        state,
        repo=repo,
        authority_root=authority,
        repository=identity.repository,
    )
    profile = repository_profile(
        repo,
        repository_key,
        github_repository_id=identity.github_repository_id,
        binding_root=authority,
    )
    profile["legacy_roots"] = [
        relative
        for relative in ("_ops/plans", "_ops/adr", "docs/plans", "docs/adr")
        if (repo / relative).is_dir()
    ]
    require_valid("doc-warden-config", profile)
    runtime = authority / "_ops/doc-warden/runtime/gsd-core"
    pin_path = (runtime / "gsd-core-pin.json").resolve(strict=True)
    interface_path = (runtime / "runtime-interface.v1.json").resolve(strict=True)
    gsd_interface_digest = digest_ref(interface_path.read_bytes())
    bindings = _bindings(authority)
    bindings["gsd_interface_digest"] = gsd_interface_digest
    bindings["repository_identity"] = identity.binding()
    observed_inputs = [
        ObservedInput(str(pin_path), digest_ref(pin_path.read_bytes())),
        ObservedInput(str(interface_path), gsd_interface_digest),
    ]
    observed_inputs.extend(
        ObservedInput(str(row.source_path), row.digest) for row in evidence
    )
    transaction = preview_transaction(
        MutationRequest(
            repo=repo,
            repository_key=repository_key,
            github_repository_id=identity.github_repository_id,
            transition="migration_adoption",
            actions=(
                MutationAction(
                    ".planning/doc-warden.json",
                    canonical_json(profile),
                ),
            ),
            bindings=bindings,
            operation_id=effective_operation_id,
            observed_inputs=tuple(observed_inputs),
            consequential=True,
            require_write_enabled=True,
        )
    )
    return MigrationPlan(
        repository_key=repository_key,
        repository_identity=identity,
        source_revision=transaction.source_revision,
        gsd_interface_digest=gsd_interface_digest,
        legacy_evidence=evidence,
        transaction=transaction,
        status="ready",
    )


def _head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
