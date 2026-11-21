"""Explicit central authority for typed defects; never discovers or grants access."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import canonical_json, contained_path, digest_ref
from .gsd_adapter import (
    _central_authority,
    _central_profile,
    _runtime_paths,
)
from .transactions import ObservedInput


@dataclass(frozen=True)
class DefectAuthority:
    bindings: dict[str, Any]
    observed_inputs: tuple[ObservedInput, ...]


def prepare_authority(repo: Path, binding_root: Path | None) -> DefectAuthority | None:
    if binding_root is None:
        return None
    # An explicit canonical source is required, including non-symlinked ancestors.
    supplied = binding_root.absolute()
    if ".." in supplied.parts or any(p.is_symlink() for p in (supplied, *supplied.parents)):
        raise ValueError("defect_authority_root_invalid")
    authority = supplied.resolve(strict=True)
    repo = repo.resolve(strict=True)
    central = _central_authority(authority)
    pin, interface = _runtime_paths(authority)
    pin_digest = digest_ref(pin.read_bytes())
    interface_digest = digest_ref(interface.read_bytes())
    profile = contained_path(repo, ".planning/doc-warden.json")
    if not profile.is_file():
        raise ValueError("v2_repository_profile_required")
    profile_digest = _central_profile(repo, pin_digest, interface_digest)
    template = contained_path(authority, "_ops/doc-warden/v2/templates/defect.md")
    template_digest = digest_ref(template.read_bytes())
    observed = tuple(dict.fromkeys((*central.inputs, ObservedInput(str(template), template_digest),
                                   ObservedInput(str(profile), profile_digest))))
    # Bindings and observations must describe the same visible source snapshot.
    if (_central_authority(authority) != central
            or digest_ref(pin.read_bytes()) != pin_digest
            or digest_ref(interface.read_bytes()) != interface_digest
            or _central_profile(repo, pin_digest, interface_digest) != profile_digest
            or digest_ref(template.read_bytes()) != template_digest):
        raise ValueError("defect_authority_changed")
    bindings = central.bindings | {"template_digests": {"defect.md": template_digest}}
    return DefectAuthority(bindings, observed)


def validate_replay_authority(receipt: dict[str, Any], repo: Path,
                              authority: DefectAuthority | None) -> None:
    """Rebind portable historical evidence to the caller's exact current context.

    Typed local history remains unchanged. Central history cannot be replayed
    through the local route or silently adopted from an older zero-bound record.
    The action-set digest also binds paths, which receipt digest lists omit.
    """
    if authority is None:
        if receipt.get("observed_input_digests"):
            raise ValueError("defect_operation_replay_mismatch")
        return
    if ({key: value for key, value in receipt["bindings"].items()
         if key != "defect_authority"} != authority.bindings
            or receipt.get("observed_input_digests") != [i.digest for i in authority.observed_inputs]):
        raise ValueError("defect_operation_replay_mismatch")
    digest_input = {
        "schema": "doc-warden/action-set/v2",
        "operation_id": receipt["operation_id"],
        "repository_key": receipt["repository_key"],
        "github_repository_id": receipt["github_repository_id"],
        "canonical_root": str(repo.resolve(strict=True)),
        "source_revision": receipt["source_revision"],
        "transition": receipt["transition"],
        "actions": receipt["actions"],
        "preimages": receipt["preimages"],
        "postimages": receipt["postimages"],
        "bindings": receipt["bindings"],
        "observed_inputs": [{"path": i.path, "digest": i.digest} for i in authority.observed_inputs],
        "consequential": receipt["confirmation_digest"] is not None,
        "require_write_enabled": True,
    }
    if digest_ref(canonical_json(digest_input)) != receipt["action_digest"]:
        raise ValueError("defect_operation_replay_mismatch")
