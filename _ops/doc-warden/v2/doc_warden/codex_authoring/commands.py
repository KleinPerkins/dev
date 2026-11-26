"""Connect the native client target to the existing runtime and apply commands."""

from __future__ import annotations

from pathlib import Path

from ..operation_store import private_state_root
from ..runtime_host import installation_context
from .authoring_command import prepare_native_authoring
from .host_assets import client_environment, qualify_host, read_qualification, verify_assets
from .host_transaction import (
    apply_host_change, prepare_host_change, read_installed_projection, require_authoring_enabled,
)
from .native_client import observe_skills


def apply_codex_install(operation_id: str, action_digest: str, consent: dict | None) -> dict:
    def revalidate(binding):
        _, current = read_qualification(
            Path(binding["authority_root"]), Path(binding["project_identity"]["path"]),
            home=Path(binding["home"]), data=Path(binding["data_home"]),
        )
        if current != binding:
            raise ValueError("native_authoring_qualification_changed")

    return apply_host_change(
        operation_id, action_digest, consent, verify=verify_assets,
        revalidate=revalidate, verify_projection=_native_discovery,
    )


def _native_discovery(binding: dict) -> dict[str, str]:
    home = Path(binding["home"])
    project = Path(binding["project_identity"]["path"])
    return observe_skills(project, client=binding["client"], environment=client_environment(home))


def _state_for(project: Path, home: Path, data: Path) -> dict:
    return read_installed_projection(
        project, state_root=private_state_root(create=False), home=home, data_home=data,
    )


def run_codex_command(args):
    verb = args.runtime_verb
    if args.project is None or args.observation or args.require_current:
        raise ValueError("native_authoring_explicit_project_required")
    if args.client is not None and verb != "qualify-codex":
        raise ValueError("native_authoring_uses_installed_client")
    if verb != "author-codex" and any((args.skill, args.argument, args.operator_input, args.active_plan)):
        raise ValueError("native_authoring_options_require_author_codex")
    project, home, data = (path.expanduser().resolve() for path in (args.project, args.home, args.data_home))
    if verb in {"qualify-codex", "install-codex", "recover-codex", "author-codex"}:
        require_authoring_enabled(project)
    if verb == "qualify-codex":
        if args.preview or args.client is None:
            raise ValueError("native_authoring_qualification_needs_explicit_client")
        return qualify_host(args.repo, project, home=home, data=data, client=args.client)
    if verb in {"install-codex", "recover-codex", "uninstall-codex"}:
        if not args.preview:
            raise ValueError("runtime_apply_requires_generic_apply")
        if verb in {"install-codex", "recover-codex"}:
            authority, binding = read_qualification(args.repo, project, home=home, data=data)
        else:
            authority = installation_context(args.repo.resolve(strict=True), home, data)
            binding = None
        return prepare_host_change(
            project, home=home, data_home=data, authority=authority,
            binding=binding, verify=verify_assets, recover_device=verb == "recover-codex",
        )
    if args.preview:
        raise ValueError("native_authoring_preview_is_default")
    binding = _state_for(project, home, data)
    verify_assets(binding)
    discovered = _native_discovery(binding)
    if verb == "doctor-codex":
        return {
            "schema": "doc-warden/codex-runtime-doctor/v1", "target": "codex",
            "status": "verified", "source_revision": binding["source_revision"],
            "runtime_revision": binding["bundle"]["runtime_revision"],
            "skills": discovered, "global_hooks": [], "read_only": True,
        }
    if args.operator_input is None or args.skill not in discovered:
        raise ValueError("native_authoring_operator_input_required")
    with args.operator_input.open("rb") as brief:
        content = brief.read(32 * 1024 + 1)
    return prepare_native_authoring(
        project, binding=binding, skill=args.skill, arguments=args.argument,
        operator_input=content, active_plan=args.active_plan,
    )
