"""Atomic v2 policy/dispatcher activation and rollback evidence."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from subprocess import SubprocessError
from typing import Any

from .canonical import atomic_write, digest_file_manifest, digest_ref
from .receipts import QualificationCheckObserver, runnerless_delivery_preview
from .triggers import validate_trigger_parity


def validate_activation(
    root: Path,
    *,
    observe_runnerless: bool = True,
    qualification_check_observer: QualificationCheckObserver | None = None,
) -> dict[str, Any]:
    root = root.resolve(strict=True)
    policy = root / "_ops/doc-warden/POLICY.md"
    dispatcher = root / "_ops/bin/doc-warden.sh"
    draft = root / "_ops/doc-warden/drafts/POLICY-v2.md"
    policy_bytes = policy.read_bytes()
    dispatcher_bytes = dispatcher.read_bytes()
    if b"**Status:** ACTIVE" not in policy_bytes or b"**Version:** 2.0.0" not in policy_bytes:
        raise ValueError("v2_policy_inactive")
    if draft.exists():
        raise ValueError("inactive_policy_draft_present")
    if b"legacy-v1" not in dispatcher_bytes or b"v2-preview" not in dispatcher_bytes:
        raise ValueError("dispatcher_activation_mismatch")
    trigger = validate_trigger_parity(root / "_ops/doc-warden/triggers.v2.json")
    schemas = sorted((root / "_ops/doc-warden/schemas/v2").glob("*.schema.json"))
    templates = sorted((root / "_ops/doc-warden/v2/templates").glob("*"))
    runtime = root / "_ops/doc-warden/runtime/gsd-core"
    successor = None
    if (root / "_ops/policy/dev-successor.json").is_file():
        spec = importlib.util.spec_from_file_location("dev_successor", root / "_ops/checks/dev-successor.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        config = json.loads((root / ".planning/doc-warden.json").read_bytes())
        successor = module.validate(root, repository_id=config["github_repository_id"], repository=None)
    try:
        if successor is not None:
            raise ValueError("retired_runnerless_delivery")
        delivery = runnerless_delivery_preview(
            root,
            repository="KleinPerkins/dev",
            github_repository_id=None,
            observe_qualification_check=observe_runnerless,
            qualification_check_observer=qualification_check_observer,
        )
        source_lane = delivery["source_lane"]
    except (KeyError, OSError, SubprocessError, TypeError, ValueError):
        source_lane = {
            "qualified": False,
            "controller_qualification": {
                "status": "blocked_external_dependency",
                "qualified": False,
                "reason": "runnerless_authority_invalid",
                "receipt_count": 0,
                "qualification_id": None,
                "revision": None,
                "check_run_id": None,
                "check_observed": False,
            },
        }
    result = {
        "schema": "doc-warden/activation-evidence/v2",
        "status": "active",
        "policy_digest": digest_ref(policy_bytes),
        "dispatcher_digest": digest_ref(dispatcher_bytes),
        "schema_digest": digest_file_manifest(schemas),
        "template_digest": digest_file_manifest(templates),
        "trigger_digest": digest_ref(
            (root / "_ops/doc-warden/triggers.v2.json").read_bytes()
        ),
        "trigger_count": trigger["trigger_count"],
        "gsd_pin_digest": digest_ref((runtime / "gsd-core-pin.json").read_bytes()),
        "gsd_interface_digest": digest_ref(
            (runtime / "runtime-interface.v1.json").read_bytes()
        ),
        "runnerless_v2": (
            "qualified"
            if source_lane["qualified"]
            else "blocked_external_dependency"
        ),
        "runnerless_v2_evidence": source_lane["controller_qualification"],
    }
    if successor is not None:
        result["runnerless_v2"] = "retired"
        result["runnerless_v2_evidence"]["reason"] = "successor_delivery_pending"
        result["successor_source"] = successor
    return result


def restore_policy_dispatch_pair(
    root: Path, *, policy_bytes: bytes, dispatcher_bytes: bytes
) -> None:
    root = root.resolve(strict=True)
    atomic_write(root, "_ops/doc-warden/POLICY.md", policy_bytes)
    atomic_write(root, "_ops/bin/doc-warden.sh", dispatcher_bytes)
