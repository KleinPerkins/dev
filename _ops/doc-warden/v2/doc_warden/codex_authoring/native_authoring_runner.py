"""Translate a verified Doc-Warden role request into one native Codex turn."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import time
from types import ModuleType
from uuid import uuid4

from ..canonical import contained_path, digest_ref
from .native_authoring_transport import NativeAuthoringChannel


@dataclass(frozen=True)
class PrivateRoleResult:
    evidence: dict
    report: bytes
    run_id: str


@dataclass(frozen=True)
class RoleRequest:
    fixture_root: Path
    bundle_root: Path
    binary: Path
    role: str
    task: str
    node: Path | None = None


def _spawn_offer(response: dict) -> dict:
    """Find the actual collaboration namespace, avoiding legacy tool aliases."""
    namespaces = []

    def scan(value: object):
        if isinstance(value, list):
            for row in value:
                scan(row)
        elif isinstance(value, dict):
            if value.get("type") == "namespace" and value.get("name") == "collaboration":
                namespaces.append(value)
            else:
                for row in value.values():
                    scan(row)

    scan(response)
    if len(namespaces) != 1:
        raise ValueError("native_authoring_selector_unavailable")
    tools = namespaces[0].get("tools")
    if not isinstance(tools, list):
        raise ValueError("native_authoring_selector_unavailable")
    matches = [row for row in tools if isinstance(row, dict) and row.get("name") == "spawn_agent"]
    if len(matches) != 1:
        raise ValueError("native_authoring_selector_unavailable")
    return matches[0]


def _role_dispatch(offer: dict, request: RoleRequest, owner: ModuleType) -> dict[str, str]:
    # This is the measured selector inside the owned Codex client. The
    # ordinary repository-review worker ABI has no named-role selector.
    owner.verify_spawn_offer(offer, request.role)
    arguments = {
        "agent_type": request.role,
        "task_name": "doc_warden_authoring",
        "fork_turns": "none",
        "model": owner.MODEL,
        "reasoning_effort": owner.EFFORT,
        "message": request.task,
    }
    if arguments.keys() != offer["parameters"]["properties"].keys():
        raise ValueError("native_authoring_selector_unavailable")
    return arguments


def _scoped_worker_permissions(
    profile: str, staged: Path, bundle: Path, binary: Path, node: Path | None,
) -> tuple[tuple[str, ...], str]:
    # The pinned client applies custom filesystem profiles through Seatbelt
    # on macOS. Use a fresh name so no lower config layer contributes paths.
    paths = (staged, bundle, binary) if node is None else (staged, bundle, binary, node)
    reads = {":root": "deny", ":minimal": "read"}
    for path in paths:
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise ValueError("native_authoring_permission_path_changed")
        reads[str(path)] = "read"
    filesystem = ", ".join(json.dumps(path) + "=" + json.dumps(mode) for path, mode in reads.items())
    return (
        "-c", "default_permissions=" + json.dumps(profile),
        "-c", "permissions." + profile + "={filesystem={" + filesystem + "},network={enabled=false}}",
        "-c", "apps._default.enabled=false",
        "-c", 'web_search="disabled"',
    ), digest_ref(json.dumps({"filesystem": reads, "network": False}, sort_keys=True).encode())


def run_role(
    request: RoleRequest,
    owner: ModuleType,
    *,
    environment: dict[str, str],
    package_digest: str,
    timeout: int,
):
    """Run one read-only named worker against an approved disposable project.

    The host installer admits the exact owner module and bundle and the caller
    derives the task from an accepted authoring request. This adapter never
    applies a generated plan.
    """
    binary = request.binary.resolve(strict=True)
    work = request.fixture_root.resolve(strict=True)
    bundle = request.bundle_root.resolve(strict=True)
    if request.role not in owner.ROLE_DIGESTS:
        raise ValueError("native_authoring_role_unqualified")
    role_path = contained_path(bundle, f"agents/{request.role}.toml")
    role_bytes = role_path.read_bytes()
    binary_digest = digest_ref(binary.read_bytes())
    if binary_digest != "sha256:" + owner.CLIENT_SHA256:
        raise ValueError("native_authoring_client_unqualified")
    version_text = subprocess.check_output(
        [str(binary), "--version"], cwd=work, env=environment, stderr=subprocess.DEVNULL, timeout=10,
    ).decode().strip()
    prefix = "codex-cli "
    if not version_text.startswith(prefix):
        raise ValueError("native_authoring_client_unqualified")
    version = version_text.removeprefix(prefix)
    source = {
        "client_version": version, "client_digest": binary_digest.removeprefix("sha256:"),
        "package_digest": package_digest, "role_config": role_bytes, "bundle_root": bundle,
    }
    owner.verify_role_input(request.role, **source)
    name = request.role
    profile = "doc-warden-authoring-" + uuid4().hex
    permission_flags, permission_digest = _scoped_worker_permissions(profile, work, bundle, binary, request.node)
    cfg = (
        "-c", f"agents.{name}.config_file=" + json.dumps(role_path.as_posix()),
        "-c", f"agents.{name}.description=" + json.dumps(f"Doc-Warden authoring role {name}"),
        "-c", "model_reasoning_effort=" + json.dumps(owner.EFFORT),
        "-c", "features.plugins=false",
        "-c", "agents.max_depth=1",
        "-c", "agents.max_concurrent_threads_per_session=1",
        *permission_flags,
    )
    raw = subprocess.check_output(
        [str(binary), *cfg, "debug", "prompt-input", "Synthetic native selector metadata check."],
        cwd=work, env=environment, stderr=subprocess.DEVNULL, timeout=15,
    )
    # The native debug response contains unrelated telemetry floats. Consume
    # only its named function shape, never treat the response as a receipt.
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("native_authoring_selector_response_too_large")
    spawn_offer = _spawn_offer(json.loads(raw))
    dispatch = _role_dispatch(spawn_offer, request, owner)
    channel = NativeAuthoringChannel(binary=binary, binary_digest=binary_digest, cwd=work,
                                     configuration=cfg, environment=environment)
    deadline = time.monotonic() + timeout
    with channel:
        channel.request("initialize", {
            "clientInfo": {"name": "doc_warden_native_authoring", "version": "1"},
            "capabilities": {"experimentalApi": True},
        }, deadline)
        channel.notify("initialized", deadline)
        parent = channel.request("thread/start", {
            "cwd": str(work), "ephemeral": True, "model": owner.MODEL,
            "permissions": profile, "approvalPolicy": "on-request", "approvalsReviewer": "user",
            "developerInstructions": (
                "Make one native collaboration.spawn_agent call for the explicitly requested role. "
                "Wait only for that child. End the turn after its first terminal outcome. "
                "Use no shell, other role, or reroute in this controller."
            ),
        }, deadline)
        sandbox = parent.get("sandbox", {})
        if (sandbox.get("type") != "readOnly" or sandbox.get("networkAccess", False) is not False
                or parent.get("activePermissionProfile") != {"id": profile, "extends": None}
                or parent.get("approvalPolicy") != "on-request" or parent.get("approvalsReviewer") != "user"
                or parent.get("model") != owner.MODEL
                or parent.get("thread", {}).get("cwd") != str(work)):
            raise ValueError("native_authoring_parent_permissions_changed")
        parent_id = parent["thread"]["id"]
        text = (
            f"Call the measured native function {owner.TOOL} exactly once with the following JSON arguments. "
            "Wait for the same worker to finish, then end the turn. Do not perform its task yourself or repeat the call. "
            "Report unavailable if the worker fails. Otherwise end with the single word Settled.\n"
            + json.dumps(dispatch, ensure_ascii=True)
        )
        turn = channel.request("turn/start", {
            "threadId": parent_id, "effort": owner.EFFORT, "input": [{"type": "text", "text": text}],
        }, deadline)["turn"]["id"]
        channel.wait_for_turn(parent_id, turn, deadline)
        child_threads = {
            item["agentThreadId"]
            for event in channel.observed if event.get("method") == "item/completed"
            for item in (event["params"].get("item", {}),)
            if item.get("type") == "subAgentActivity" and item.get("kind") == "started"
            and event["params"].get("threadId") == parent_id and isinstance(item.get("agentThreadId"), str)
        }
        if not child_threads:
            raise ValueError("native_authoring_child_not_observed")
        if len(child_threads) != 1:
            raise ValueError("native_authoring_foreign_child_observed")
        run_id = next(iter(child_threads))
        child = channel.request("thread/read", {
            "threadId": run_id, "includeTurns": False,
        }, deadline)["thread"]
        observation = owner.observe_role(name, **source, parent_result=parent,
                                         spawn_offer=spawn_offer, parent_turn=turn, events=channel.observed, child_result=child)
    if not channel.reaped or role_path.read_bytes() != role_bytes:
        raise ValueError("native_authoring_run_identity_changed")
    return PrivateRoleResult(observation.evidence | {"permission_profile_digest": permission_digest},
                             observation.report, run_id)
