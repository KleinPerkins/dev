"""Bind declared verification and acceptance to current planned scope and observed evidence."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .artifact_authority import ApprovedArtifact, resolve_approved_artifact
from .canonical import contained_path, digest_ref, parse_json_object
from .release_delivery import PULL_REQUEST, REVISION, observe_merged_delivery
from .transactions import ObservedInput

KINDS = {"verification", "uat"}
VISUAL_CHECKS = {"comparison", "states", "accessibility", "responsive", "copy", "recovery", "assets"}


def _plan_scope(repo: Path, plan_id: object) -> tuple[ApprovedArtifact, set[str], list[ApprovedArtifact]]:
    from .dependencies import assert_plan_assumptions_current

    if not isinstance(plan_id, str) or not plan_id:
        raise ValueError("outcome_plan_required")
    plan = resolve_approved_artifact(repo, "plan", plan_id)
    assert_plan_assumptions_current(repo, plan_id)
    sidecar = parse_json_object(plan.path.with_suffix(".governance.json").read_bytes())
    designs = [
        resolve_approved_artifact(repo, "design", identifier,
                                  version=sidecar["design_versions"][identifier],
                                  digest=sidecar["design_digests"][identifier])
        for identifier in sidecar["design_ids"]
    ]
    return plan, set(sidecar["requirement_ids"]), designs


def _check_evidence_files(repo: Path, checks: object, expected: set[str], outcome: str) -> list[ObservedInput]:
    if not isinstance(checks, dict) or set(checks) != expected:
        raise ValueError("outcome_coverage_incomplete")
    observed = []
    for row in checks.values():
        if (not isinstance(row, dict) or set(row) != {"result", "path", "digest"} or row["result"] != outcome
                or not isinstance(row["path"], str) or not re.fullmatch(r"[A-Za-z0-9._/ -]{1,256}", row["path"])
                or Path(row["path"]).as_posix() != row["path"]):
            raise ValueError("outcome_evidence_invalid")
        path = contained_path(repo, row["path"])
        if not path.is_file() or row["digest"] != digest_ref(path.read_bytes()):
            raise ValueError("outcome_evidence_changed")
        observed.append(ObservedInput(str(path), row["digest"]))
    return observed


def _observe_outcome(repo: Path, kind: str, value: object):
    if not isinstance(value, dict) or set(value) != {"plan", "source_revision", "requirements", "visual_checks"}:
        raise ValueError("outcome_evidence_required")
    revision = value["source_revision"]
    if not isinstance(revision, str) or REVISION.fullmatch(revision) is None:
        raise ValueError("outcome_source_revision_invalid")
    plan, requirements, designs = _plan_scope(repo, value["plan"])
    expected = "passed" if kind == "verification" else "accepted"
    observed = _check_evidence_files(repo, value["requirements"], requirements, expected)
    observed.extend(_check_evidence_files(repo, value["visual_checks"], VISUAL_CHECKS if designs else set(), expected))
    for authority in (plan, *designs):
        observed.extend(authority.observed_inputs)
    return value | {"plan_digest": plan.digest}, observed


def outcome_binding(kind: str, inputs: dict[str, Any], repo: Path, *, approved: bool):
    if kind not in KINDS | {"release"}:
        return None, ()
    field = "release_evidence" if kind == "release" else "outcome_evidence"
    value = inputs.get(field)
    if value is None and not approved:
        return None, ()
    if kind in KINDS:
        bound, observed = _observe_outcome(repo, kind, value)
        revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        if bound["source_revision"] != revision:
            raise ValueError("outcome_source_revision_changed")
        return {field: bound}, observed
    fields = {"plan", "verification", "uat", "commit", "pull_request"}
    if (not approved and isinstance(value, dict) and set(value) < fields
            and all(isinstance(item, str) for item in value.values())):
        return {field: value}, ()
    if (not isinstance(value, dict) or set(value) != fields or any(not isinstance(item, str) for item in value.values())
            or REVISION.fullmatch(value["commit"]) is None or PULL_REQUEST.fullmatch(value["pull_request"]) is None):
        raise ValueError("release_evidence_required")
    plan, _, _ = _plan_scope(repo, value["plan"])
    observed = list(plan.observed_inputs)
    for proof_kind in ("verification", "uat"):
        proof = resolve_approved_artifact(repo, proof_kind, value[proof_kind])
        records = [item["outcome_evidence"] for item in proof.metadata["provenance"] if "outcome_evidence" in item]
        if len(records) != 1 or not isinstance(records[0], dict):
            raise ValueError("release_outcome_evidence_required")
        bound, proof_inputs = _observe_outcome(
            repo, proof_kind, {key: item for key, item in records[0].items() if key != "plan_digest"},
        )
        if (bound != records[0] or bound["plan_digest"] != plan.digest
                or bound["plan"] != value["plan"] or bound["source_revision"] != value["commit"]):
            raise ValueError("release_outcome_evidence_stale")
        observed.extend(proof.observed_inputs)
        observed.extend(proof_inputs)
    bound = value | {"plan_digest": plan.digest}
    if approved:
        bound["delivery"] = observe_merged_delivery(repo, value["pull_request"], value["commit"])
    return {field: bound}, observed
