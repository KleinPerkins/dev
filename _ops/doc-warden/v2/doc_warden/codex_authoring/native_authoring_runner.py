"""Translate a verified Doc-Warden role request into one native Codex turn."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import time
from types import ModuleType

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
    cfg = (
        "-c", f"agents.{name}.config_file=" + json.dumps(role_path.as_posix()),
        "-c", f"agents.{name}.description=" + json.dumps(f"Doc-Warden authoring role {name}"),
        "-c", "model_reasoning_effort=" + json.dumps(owner.EFFORT),
        "-c", "features.plugins=false",
        "-c", "agents.max_depth=1",
        "-c", "agents.max_concurrent_threads_per_session=1",
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
    owner.verify_spawn_offer(spawn_offer, name)
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
            "sandbox": "read-only", "approvalPolicy": "on-request",
        }, deadline)
        sandbox = parent.get("sandbox", {})
        if (sandbox.get("type") != "readOnly" or sandbox.get("networkAccess", False) is not False
                or parent.get("model") != owner.MODEL
                or parent.get("thread", {}).get("cwd") != str(work)):
            raise ValueError("native_authoring_parent_permissions_changed")
        parent_id = parent["thread"]["id"]
        text = (
            f"Spawn exactly one named worker with {owner.TOOL}, agent_type {name}, fork_turns none, "
            f"task_name doc_warden_authoring, model {owner.MODEL}, reasoning_effort {owner.EFFORT}. "
            "Give the worker the task below with the instruction to work alone. Wait for that same worker "
            "to finish. Do not perform the task yourself, spawn again, or resume or replace any worker. "
            "Only the worker performs the task. If it fails, report unavailable and end this turn. "
            "If it completes, end this turn with the single word Settled. Never echo its report.\n\n"
            + request.task
        )
        turn = channel.request("turn/start", {
            "threadId": parent_id, "effort": owner.EFFORT, "input": [{"type": "text", "text": text}],
        }, deadline)["turn"]["id"]
        channel.wait_for_turn(parent_id, turn, deadline)
        child_threads = {
            item["agentThreadId"]
            for event in channel.observed if event.get("method") == "item/completed"
            for item in (event["params"].get("item", {}),)
            if item.get("type") == "subAgentActivity" and isinstance(item.get("agentThreadId"), str)
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
    return PrivateRoleResult(observation.evidence, observation.report, run_id)
