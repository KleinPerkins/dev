#!/usr/bin/env python3
"""Assemble and validate the Context Efficiency Release 2 closure record.

Closes ``context-efficiency-program-v2.md`` Release 2 task **C-02**: one
canonical, content-safe ``context-efficiency-release2-closure/v1`` artifact that
binds the exact owner refs, the Release 0/1/1.1 evidence digests, the C-01
client-projection matrix result, verified residuals, rollback refs, and the
per-task built-versus-planned map. It is assembled once from live state, then
protected-merged after the operator closure review (Gate 2); after acceptance it
is never edited in place — a successor version supersedes it.

Content-safety invariant: only IDs, path/exposure/eligibility CLASSES, digests,
and normalized COUNTS ever enter the record. No raw skill/rule description text,
no source bytes, and no private session content.

No third-party dependency, no network, no tracked write outside ``--out``. The
canonical-JSON convention and digest primitives are reused from the accepted
measurement tool (``kp_context_measure``), the same convention the D-01
capability-discovery inventory emits.
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import kp_context_measure as kpcm

SCHEMA = "context-efficiency-release2-closure/v1"
REPOSITORY = "KleinPerkins/dev"
STATUS_PASS = "PASS"
C01_SCHEMA = "capability-discovery-inventory/v1"
C01_PROJECTION_RESULT = "C-01 PROJECTION PASS"

HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
MAX_STRING = 600  # defensive content-safety bound; real fields are short

BLOCKING_SEVERITIES = frozenset({"P0", "P1"})
ALL_SEVERITIES = frozenset({"P0", "P1", "P2", "P3"})

OWNER_REPOS = (
    "KleinPerkins/dev",
    "KleinPerkins/skills",
    "KleinPerkins/ecosystem-orchestrator",
    "Affirm/card-platform-product",
    "KleinPerkins/awa",
)

# Root argument -> owner repository, in the fixed order used above.
OWNER_ROOT_ARGS = (
    ("dev_root", "KleinPerkins/dev"),
    ("skills_root", "KleinPerkins/skills"),
    ("orch_root", "KleinPerkins/ecosystem-orchestrator"),
    ("cpp_root", "Affirm/card-platform-product"),
    ("awa_root", "KleinPerkins/awa"),
)

# 13 D-04 description-reconciliation target IDs -> post-D-02 normalized char
# target (program-v2 Release 1.1 / D-04 plan §2.3). This is the C-01 pass rule
# and the C-02 catalog-result input.
REDUCED_TARGETS = {
    "agent-route": 292,
    "algorithmic-art": 227,
    "capability": 285,
    "claude-api": 268,
    "doc-coauthoring": 250,
    "internal-comms": 209,
    "pdf": 233,
    "plan-refine": 290,
    "pr-steward": 299,
    "prompt-architect": 256,
    "skill-creator": 245,
    "swarm": 295,
    "xlsx": 300,
}
REDUCED_TARGET_TOTAL = 3449

# The three Release 0/1/1.1 evidence artifacts (relative to the Dev evidence dir).
EVIDENCE_DIR = "_ops/evidence/context-efficiency"
RELEASE_EVIDENCE_FILES = {
    "release0_static_context_manifest": (
        "static-context-manifest-v1.json",
        "static-context-manifest/v1",
        "FROZEN",
    ),
    "release1_static_reduction": (
        "release1-static-reduction-v1.json",
        "context-efficiency-release1-static-evidence/v1",
        "PASS",
    ),
    "release1_1_capability_discovery_inventory": (
        "capability-discovery-inventory-v1.json",
        "capability-discovery-inventory/v1",
        "PASS",
    ),
}

# D-04 landing anchors (fixed program facts; program-v2 Release 1.1 / D-04 plan).
D04_CPP_MAIN_COMMIT = "5d5d584e6db11871313de72bbf58a680700e6d32"
D04_ORCH_APPROVE_COMMIT = "15a9c1366685248d12108ee34deef5e245baf190"  # #83 re-pin
D04_ORCH_PREREQ_COMMIT = "d36c10c17671e36b708be820dcabc8d190d34071"  # #82 tests/ excl
D04_PAYLOADS_MERGED = 15  # 13 description targets + 2 supporting payloads

# C-01 fresh-client projection matrix (program-v2 Release 2 C-01; plan §4.2).
# Gate-1 recorded scope is Cursor-only; Claude/Codex are product-constrained.
CATALOG_SURFACES = (
    {
        "surface": "cursor-desktop@dev-root",
        "eligible": True,
        "discovery_source_class": "cursor-session-catalog/v1",
        "result": "PASS",
        "product_constraint": None,
    },
    {
        "surface": "cursor-cloud@dev-root",
        "eligible": False,
        "discovery_source_class": None,
        "result": "PRODUCT_CONSTRAINED",
        "product_constraint": (
            "not a Cloud agent session; no live same-session context source "
            "(committed-hooks-only catalog)"
        ),
    },
    {
        "surface": "cursor-background@dev-root",
        "eligible": False,
        "discovery_source_class": None,
        "result": "PRODUCT_CONSTRAINED",
        "product_constraint": (
            "foreground Desktop session; no background injection surface to capture"
        ),
    },
    {
        "surface": "cursor-multi-root",
        "eligible": False,
        "discovery_source_class": None,
        "result": "PRODUCT_CONSTRAINED",
        "product_constraint": (
            "single workspace root equals dev-root; no multi-root ambiguity to prove"
        ),
    },
    {
        "surface": "claude",
        "eligible": False,
        "discovery_source_class": None,
        "result": "PRODUCT_CONSTRAINED",
        "product_constraint": (
            "Gate-1 Cursor-only scope; no structured Claude discovery-catalog source"
        ),
    },
    {
        "surface": "codex",
        "eligible": False,
        "discovery_source_class": None,
        "result": "PRODUCT_CONSTRAINED",
        "product_constraint": (
            "Gate-1 Cursor-only scope; no structured Codex discovery-catalog source"
        ),
    },
)

# Verified residual ledger (plan §2.4). Only the still-open, non-P0/P1 residuals
# are recorded here; R2/R3/R4 were verified resolved and R5 is handled by C-03.
# R2 (agent-route expose widening) was resolved during C-02: save-game enrollment
# and the agent-route widening landed atomically on CPP origin/main, so the CPP
# eco-capability manifest now exposes agent-route to cursor/claude/codex (its
# Skills meta.yml end-state) — see owner_refs["Affirm/card-platform-product"].
# R1 correspondingly narrows: save-game is now enrolled, leaving only the
# third-party + MCP capabilities held for a separate enroll-or-exclude decision.
RESIDUALS = (
    {
        "id": "R1",
        "class": "open-decision-enroll-or-exclude",
        "owner_lane": "orchestrator-registry (outside context-efficiency scope)",
        "status": "open",
        "severity": "P3",
        "follow_up_ref": (
            "orchestrator config/registry.yml: verification-before-completion, "
            "snow-kit, widget-kit unenrolled (third-party + MCP; separate decision)"
        ),
    },
)

# Per-release / per-task rollback pointers (plan §4.3 / §9).
ROLLBACK_REFS = {
    "release0_e09": (
        "supersede-only: never edit static-context-manifest-v1.json in place; a new "
        "accepted decision defines a successor schema/baseline"
    ),
    "release1_static": (
        "governed revert of owner reduction PRs (Dev #285, Skills #152, AWA #116) + "
        "standard rule reinstall/regenerate from preserved inputs"
    ),
    "release1_1_discovery": (
        "revert D-02/D-03 owner reduction PRs and reconcile through Skills/CPP owners"
    ),
    "d04_reconcile": (
        "orchestrator rollback <id> per-capability anchors; CPP payload PRs are "
        "individually revertible; orchestrator re-pin revert via Regime A"
    ),
    "c02_evidence": (
        "before merge discard the candidate; after merge supersede-only, never edit "
        "release2-closure-v1.json in place"
    ),
}

# Built-versus-planned map for every program-v2 milestone/task (§7 / §10).
# evidence_ref cites the authoritative artifact/PR/plan; the E-series rows cite
# the E-09 freeze, whose GO (§10) gates on E-01..E-08 being satisfied.
BUILT_VERSUS_PLANNED = (
    {
        "task": "M-00",
        "planned": "Protected-merge the ADR 0005 + program-v2 documentation authority",
        "built": "Merged; program-v2 ACCEPTED 2026-08-16 with v1 artifacts byte-identical",
        "evidence_ref": "program-v2 §2.1 / §6.4 EV-001..EV-003",
    },
    {
        "task": "M-01",
        "planned": "Add exact remote coverage and closed v2 tests (red-first)",
        "built": "Landed in the corrective Dev PR; focused suite wired into the doc-warden-verify --sandbox entry point",
        "evidence_ref": "correction-dogfood-v1.json; program-v2 §6.4 EV-004/EV-011",
    },
    {
        "task": "M-02",
        "planned": "Implement the v2 wire contract (0/2/3/4 exits, closed validators)",
        "built": "Landed; counting primitives unchanged and canonical JSON preserved",
        "evidence_ref": "_ops/context-measurement/kp_context_measure.py; correction-dogfood-v1.json",
    },
    {
        "task": "M-03",
        "planned": "Deliver one corrective Dev PR with exact-head Checks green",
        "built": "Merged via the protected owner path; pr-automation/verify + m3-verify green",
        "evidence_ref": "program-v2 §6.4; correction-dogfood-v1.json",
    },
    {
        "task": "M-04",
        "planned": "Bounded post-merge correction dogfood with one-file evidence",
        "built": "PASS CORRECTION_PROVEN_NOT_E09",
        "evidence_ref": "correction-dogfood-v1.json",
    },
    {
        "task": "E-01",
        "planned": "Make Skills bootstrap a durable projection",
        "built": "Implemented and merged in Skills",
        "evidence_ref": "static-context-manifest-v1.json (E-09 freeze binds the Skills owner ref); capability-discovery-inventory-v1.json",
    },
    {
        "task": "E-02",
        "planned": "Make CPP projections durable (install/doctor)",
        "built": "Implemented and merged in CPP",
        "evidence_ref": "static-context-manifest-v1.json; D-04 CPP origin/main " + D04_CPP_MAIN_COMMIT[:12],
    },
    {
        "task": "E-03",
        "planned": "Establish strict skill-description eligibility (YAML 1.2 Core parser)",
        "built": "Implemented and merged; the D-01 inventory imports the eligibility profile",
        "evidence_ref": "capability-discovery-inventory-v1.json; Skills scripts/skill-description-inventory.py",
    },
    {
        "task": "E-04",
        "planned": "Implement AWA external hook ownership and a qualified v1.5.2 release",
        "built": "Implemented and merged; AWA release qualified",
        "evidence_ref": "static-context-manifest-v1.json (E-09 binds the AWA owner ref); AWA origin/main 01053f69",
    },
    {
        "task": "E-05",
        "planned": "Pin the qualified AWA release in the Skills GCB",
        "built": "Pinned and merged in Skills (GCB moved to the E-04 release commit)",
        "evidence_ref": "static-context-manifest-v1.json (E-09 freeze precondition per program-v2 §10)",
    },
    {
        "task": "E-06",
        "planned": "Consume the AWA pin through Dev's thin host overlay",
        "built": "Overlay authority accepted (host-overlay v3) and installed; thin host boundary preserved",
        "evidence_ref": "context-efficiency-e06-dev-host-overlay-v3.md (ACCEPTED); static-context-manifest-v1.json",
    },
    {
        "task": "E-07",
        "planned": "Project learned data through the private gate",
        "built": "Attested satisfied by the E-09 freeze precondition (§10 requires content-free E-07 completion before freeze); no learned data in any tracked artifact",
        "evidence_ref": "static-context-manifest-v1.json (E-09 freeze precondition per program-v2 §10)",
    },
    {
        "task": "E-08",
        "planned": "Repair a reproduced code defect only (conditional)",
        "built": "Attested satisfied by the E-09 freeze precondition (§10: merged fix or explicit E08_NOT_ACTIVATED before freeze)",
        "evidence_ref": "static-context-manifest-v1.json (E-09 freeze precondition per program-v2 §10)",
    },
    {
        "task": "E-09",
        "planned": "Freeze the seven-payload Release 0 denominator last",
        "built": "FROZEN; operator-approved, independently reproduced v2 seven-payload receipt",
        "evidence_ref": "static-context-manifest-v1.json (FROZEN); e09-input-v2.json; e09-receipt-v2.json",
    },
    {
        "task": "S-01",
        "planned": "Reduce Dev-owned static projections (duplication + precise pointers)",
        "built": "Merged (Dev PR #285)",
        "evidence_ref": "release1-static-reduction-v1.json owner_reductions.dev_s01 (PR 285)",
    },
    {
        "task": "S-02",
        "planned": "Reduce Skills-owned generated/global wording, preserving learned bullets",
        "built": "Merged (Skills PR #152)",
        "evidence_ref": "release1-static-reduction-v1.json owner_reductions.skills_s02 (PR 152)",
    },
    {
        "task": "S-03",
        "planned": "Conditional AWA awa-operator reduction to meet the 30% target",
        "built": "Merged (AWA PR #116)",
        "evidence_ref": "release1-static-reduction-v1.json owner_reductions.awa_s03 (PR 116)",
    },
    {
        "task": "S-04",
        "planned": "Remeasure the E-09 workload; protected-merge Release-1 evidence at <=30%",
        "built": "PASS RELEASE1_STATIC_TARGET_MET (word and character targets met)",
        "evidence_ref": "release1-static-reduction-v1.json",
    },
    {
        "task": "D-01",
        "planned": "Inventory the injected/discovered catalog by client/root",
        "built": "PASS; this is the reused C-01 capture/validate tool",
        "evidence_ref": "capability-discovery-inventory-v1.json",
    },
    {
        "task": "D-02",
        "planned": "Scope-first, then shorten remaining Skills auto-discovery descriptions",
        "built": "Merged (Skills); the 13 target descriptions reduced to the §2.3 counts",
        "evidence_ref": "capability-discovery-inventory-v1.json; D-04 plan §2.3",
    },
    {
        "task": "D-03",
        "planned": "CPP project scoping test, then shorten globally-necessary descriptions",
        "built": "Merged (CPP)",
        "evidence_ref": "D-04 CPP origin/main " + D04_CPP_MAIN_COMMIT[:12] + "; D-04 plan",
    },
    {
        "task": "D-04",
        "planned": "Reconcile global projections via the standard lifecycle (lockkit/consistency/zero-link/client parity)",
        "built": "13 targets reconciled into CPP origin/main with byte + lockkit parity, 26 zero-link OK, 27 consistency OK; orchestrator re-pin merged",
        "evidence_ref": "D-04 plan (ACCEPTED 2026-08-22); orchestrator " + D04_ORCH_APPROVE_COMMIT[:12] + "; CPP " + D04_CPP_MAIN_COMMIT[:12],
    },
    {
        "task": "C-01",
        "planned": "Fresh-client projection matrix; eligible surfaces proven, ineligible cite a constraint",
        "built": "PROVEN: cursor-desktop@dev-root PASS; 13/13 reduced IDs at target with stable identity; other surfaces product-constrained",
        "evidence_ref": "this record catalog_result (C-01 artifact digest recorded there)",
    },
    {
        "task": "C-02",
        "planned": "Protected-merge one versioned final-evidence + built-versus-planned record",
        "built": "This record: assembled at M2; protected-merged after Gate 2",
        "evidence_ref": "self: release2-closure-v1.json",
    },
    {
        "task": "C-03",
        "planned": "Per-owner documentation closure (implementation-stale docs only)",
        "built": "PENDING (M3): orchestrator registry.yml comment; Dev S-01/D-01 labels; Skills S-02 label",
        "evidence_ref": "context-efficiency-release2-closure-v1.md §2.5 / §4.4",
    },
)

EXPECTED_TASKS = tuple(row["task"] for row in BUILT_VERSUS_PLANNED)

CONTENT_SAFETY = {
    "raw_descriptions_present": False,
    "raw_source_present": False,
    "private_session_content_present": False,
    "only_ids_counts_digests_classes": True,
}

# Open items enumerated for the no-P0/P1 attestation (residuals + the C-03 lag).
# R2 dropped: agent-route expose widening resolved on CPP origin/main at C-02.
NO_P0_P1_OPEN_ITEMS = (
    {"id": "R1", "severity": "P3"},
    {"id": "R5-C03-doc-lag", "severity": "P3"},
)


class ValidationError(Exception):
    """Raised for any closed-schema or content-safety violation."""


def _fail(message: str) -> None:
    raise ValidationError(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _is_hex(value: Any, pattern: re.Pattern[str]) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _is_text(value: Any) -> bool:
    return (
        type(value) is str
        and 0 < len(value) <= MAX_STRING
        and "\x00" not in value
    )


def _is_nonneg_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _sha256_file(path: Path) -> str:
    return kpcm.sha256_hex(path.read_bytes())


def _origin_main_bytes(root: Path, relpath: str) -> bytes:
    """Exact bytes of ``relpath`` at ``origin/main`` (binary-safe).

    Used to prove that a hashed evidence file is exactly what the recorded
    owner commit carries, so a dirty or diverged checkout cannot bind a stale
    digest to the wrong commit.
    """
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"origin/main:{relpath}"],
        check=True,
        capture_output=True,
    )
    return result.stdout


def _load_json(path: Path) -> Any:
    return kpcm._parse_json_text(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Assemble
# --------------------------------------------------------------------------- #
def _owner_refs(args: argparse.Namespace) -> dict[str, Any]:
    refs: dict[str, Any] = {}
    for attr, repo in OWNER_ROOT_ARGS:
        root = Path(getattr(args, attr)).resolve(strict=True)
        commit = _git(root, "rev-parse", "origin/main")
        refs[repo] = {"default_branch": "main", "commit": commit}
    return refs


def _release_evidence(dev_root: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    base = dev_root / EVIDENCE_DIR
    for key, (name, schema, status) in RELEASE_EVIDENCE_FILES.items():
        relpath = f"{EVIDENCE_DIR}/{name}"
        on_disk = (base / name).read_bytes()
        _require(
            on_disk == _origin_main_bytes(dev_root, relpath),
            f"{key} on-disk bytes differ from origin/main "
            "(uncommitted or diverged evidence; refusing to bind a stale digest)",
        )
        doc = kpcm._parse_json_text(on_disk.decode("utf-8"))
        _require(doc.get("schema") == schema, f"{key} schema mismatch")
        _require(doc.get("status") == status, f"{key} status mismatch")
        evidence[key] = {
            "path": relpath,
            "schema": schema,
            "status": status,
            "sha256": kpcm.sha256_hex(on_disk),
        }
    evidence["d04_cpp_payload_landing"] = {
        "repository": "Affirm/card-platform-product",
        "main_commit": D04_CPP_MAIN_COMMIT,
        "payloads_merged": D04_PAYLOADS_MERGED,
        "description_targets": len(REDUCED_TARGETS),
    }
    evidence["d04_orchestrator_repin"] = {
        "repository": "KleinPerkins/ecosystem-orchestrator",
        "approve_merge_commit": D04_ORCH_APPROVE_COMMIT,
        "prereq_merge_commit": D04_ORCH_PREREQ_COMMIT,
    }
    return evidence


def _static_result(dev_root: Path) -> dict[str, Any]:
    doc = _load_json(
        dev_root / EVIDENCE_DIR / "release1-static-reduction-v1.json"
    )
    candidate = doc["candidate"]
    return {
        "classification": doc["classification"],
        "status": doc["status"],
        "baseline_totals": doc["baseline"]["totals"],
        "candidate_totals": candidate["totals"],
        "delta": candidate["delta_from_baseline"],
        "target_30pct": candidate["target_30pct"],
    }


def _reduced_rows(c01: dict[str, Any]) -> list[dict[str, Any]]:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for row in c01["rows"]:
        name = row.get("capability_id", "").rsplit("/", 1)[-1]
        if (
            name in REDUCED_TARGETS
            and row.get("exposure_class") == "cursor-skill-description"
            and row.get("eligibility") == "eligible-skills-d02"
        ):
            by_id.setdefault(name, []).append(row)
    out: list[dict[str, Any]] = []
    for name in sorted(REDUCED_TARGETS, key=lambda item: item.encode("ascii")):
        matches = by_id.get(name)
        _require(
            matches is not None and len(matches) == 1,
            f"reduced id {name} missing or ambiguous in the C-01 artifact",
        )
        row = matches[0]
        target = REDUCED_TARGETS[name]
        chars = row["description_chars"]
        _require(
            chars == target,
            f"reduced id {name} count {chars} != target {target}",
        )
        out.append({
            "capability_id": name,
            "owner_source_repo": row["owner_source_repo"],
            "exposure_class": row["exposure_class"],
            "eligibility": row["eligibility"],
            "description_chars": chars,
            "description_words": row["description_words"],
            "installed_sha256": row["installed_sha256"],
            "target_chars": target,
            "result": "PASS",
        })
    return out


def _catalog_result(dev_root: Path, c01_path: Path) -> dict[str, Any]:
    c01 = _load_json(c01_path)
    _require(c01.get("schema") == C01_SCHEMA, "C-01 artifact schema mismatch")
    _require(c01.get("status") == "PASS", "C-01 artifact is not PASS")
    c01_dev = c01["dev_commit"]
    _require(_is_hex(c01_dev, HEX40), "C-01 artifact dev_commit hex40")
    # The recorded capture_provenance claims the C-01 capture commit is the
    # immediate parent of the closure origin/main; verify that git relationship
    # instead of asserting it, so a mismatched capture cannot validate as PASS.
    parent = _git(dev_root, "rev-parse", "origin/main~1")
    _require(
        c01_dev == parent,
        f"C-01 capture dev_commit {c01_dev[:12]} is not the immediate parent "
        f"of the closure origin/main ({parent[:12]}); recapture or reconcile",
    )
    artifact_sha = _sha256_file(c01_path)
    surfaces = []
    for surface in CATALOG_SURFACES:
        entry = dict(surface)
        entry["catalog_sha256"] = artifact_sha if entry["eligible"] else None
        surfaces.append(entry)
    return {
        "c01_artifact_sha256": artifact_sha,
        "dev_commit": c01["dev_commit"],
        "capture_provenance": (
            "capture dev_commit is the immediate docs-only parent of the C-02 "
            "dev_commit (closure-plan merge); the client catalog is identical"
        ),
        "surfaces": surfaces,
        "reduced_ids": _reduced_rows(c01),
        "reduced_target_total": REDUCED_TARGET_TOTAL,
        "projection_result": C01_PROJECTION_RESULT,
    }


def assemble(args: argparse.Namespace) -> dict[str, Any]:
    dev_root = Path(args.dev_root).resolve(strict=True)
    c01_path = Path(args.c01_artifact).resolve(strict=True)
    document = {
        "schema": SCHEMA,
        "status": STATUS_PASS,
        "captured_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "repository": REPOSITORY,
        "dev_commit": _git(dev_root, "rev-parse", "origin/main"),
        "dev_tree": _git(dev_root, "rev-parse", "origin/main^{tree}"),
        "owner_refs": _owner_refs(args),
        "release_evidence": _release_evidence(dev_root),
        "static_result": _static_result(dev_root),
        "catalog_result": _catalog_result(dev_root, c01_path),
        "residuals": [dict(item) for item in RESIDUALS],
        "rollback_refs": dict(ROLLBACK_REFS),
        "built_versus_planned": [dict(item) for item in BUILT_VERSUS_PLANNED],
        "content_safety": dict(CONTENT_SAFETY),
        "no_unresolved_p0_p1": {
            "value": True,
            "open_items": [dict(item) for item in NO_P0_P1_OPEN_ITEMS],
        },
    }
    validate_document(document)
    return document


# --------------------------------------------------------------------------- #
# Validate
# --------------------------------------------------------------------------- #
def _validate_owner_refs(owner_refs: Any) -> None:
    _require(type(owner_refs) is dict, "owner_refs must be an object")
    _require(set(owner_refs) == set(OWNER_REPOS), "owner_refs repo set mismatch")
    for repo in OWNER_REPOS:
        ref = owner_refs[repo]
        _require(type(ref) is dict and set(ref) == {"default_branch", "commit"},
                 f"owner_refs[{repo}] shape")
        _require(ref["default_branch"] == "main", f"owner_refs[{repo}] branch")
        _require(_is_hex(ref["commit"], HEX40), f"owner_refs[{repo}] commit hex40")


def _validate_release_evidence(evidence: Any) -> None:
    _require(type(evidence) is dict, "release_evidence must be an object")
    expected = set(RELEASE_EVIDENCE_FILES) | {
        "d04_cpp_payload_landing",
        "d04_orchestrator_repin",
    }
    _require(set(evidence) == expected, "release_evidence key set mismatch")
    for key, (name, schema, status) in RELEASE_EVIDENCE_FILES.items():
        item = evidence[key]
        _require(type(item) is dict
                 and set(item) == {"path", "schema", "status", "sha256"},
                 f"release_evidence[{key}] shape")
        _require(item["path"] == f"{EVIDENCE_DIR}/{name}", f"{key} path")
        _require(item["schema"] == schema, f"{key} schema")
        _require(item["status"] == status, f"{key} status")
        _require(_is_hex(item["sha256"], HEX64), f"{key} sha256 hex64")
    cpp = evidence["d04_cpp_payload_landing"]
    _require(type(cpp) is dict and set(cpp) == {
        "repository", "main_commit", "payloads_merged", "description_targets"},
        "d04_cpp_payload_landing shape")
    _require(cpp["repository"] == "Affirm/card-platform-product", "d04 cpp repo")
    # D-04 landing anchors are fixed program facts; pin them to the module
    # constants so a hand-edited record cannot claim the wrong landing.
    _require(cpp["main_commit"] == D04_CPP_MAIN_COMMIT, "d04 cpp main_commit pin")
    _require(cpp["payloads_merged"] == D04_PAYLOADS_MERGED, "d04 payloads_merged pin")
    _require(cpp["description_targets"] == len(REDUCED_TARGETS),
             "d04 description_targets pin")
    repin = evidence["d04_orchestrator_repin"]
    _require(type(repin) is dict and set(repin) == {
        "repository", "approve_merge_commit", "prereq_merge_commit"},
        "d04_orchestrator_repin shape")
    _require(repin["repository"] == "KleinPerkins/ecosystem-orchestrator",
             "d04 orch repo")
    _require(repin["approve_merge_commit"] == D04_ORCH_APPROVE_COMMIT,
             "d04 approve_merge_commit pin")
    _require(repin["prereq_merge_commit"] == D04_ORCH_PREREQ_COMMIT,
             "d04 prereq_merge_commit pin")


def _validate_totals(totals: Any, label: str) -> None:
    _require(type(totals) is dict and set(totals) == {"bytes", "characters", "words"},
             f"{label} totals shape")
    for key in ("bytes", "characters", "words"):
        _require(_is_nonneg_int(totals[key]), f"{label} totals[{key}] int")


def _validate_static_result(static: Any) -> None:
    _require(type(static) is dict and set(static) == {
        "classification", "status", "baseline_totals", "candidate_totals",
        "delta", "target_30pct"}, "static_result shape")
    _require(static["classification"] == "RELEASE1_STATIC_TARGET_MET",
             "static_result classification")
    _require(static["status"] == "PASS", "static_result status")
    _validate_totals(static["baseline_totals"], "static baseline")
    _validate_totals(static["candidate_totals"], "static candidate")
    baseline = static["baseline_totals"]
    candidate = static["candidate_totals"]
    delta = static["delta"]
    _require(type(delta) is dict and set(delta) == {"bytes", "characters", "words"},
             "static delta shape")
    _require(all(type(delta[k]) is int for k in delta), "static delta ints")
    # Cross-check the arithmetic instead of trusting the flags: delta is exactly
    # candidate - baseline, the 30% ceilings are floor(baseline * 70 / 100), and
    # meets_* must follow from the counts and be satisfied.
    for k in ("bytes", "characters", "words"):
        _require(delta[k] == candidate[k] - baseline[k], f"static delta[{k}] mismatch")
    target = static["target_30pct"]
    _require(type(target) is dict, "static target_30pct object")
    _require(_is_nonneg_int(target.get("max_characters")), "static max_characters int")
    _require(_is_nonneg_int(target.get("max_words")), "static max_words int")
    _require(target["max_characters"] == baseline["characters"] * 70 // 100,
             "static max_characters derivation")
    _require(target["max_words"] == baseline["words"] * 70 // 100,
             "static max_words derivation")
    _require(target.get("meets_characters")
             == (candidate["characters"] <= target["max_characters"]),
             "static meets_characters consistency")
    _require(target.get("meets_words")
             == (candidate["words"] <= target["max_words"]),
             "static meets_words consistency")
    _require(target["meets_characters"] is True, "static meets_characters")
    _require(target["meets_words"] is True, "static meets_words")


def _validate_catalog_result(catalog: Any) -> None:
    _require(type(catalog) is dict and set(catalog) == {
        "c01_artifact_sha256", "dev_commit", "capture_provenance", "surfaces",
        "reduced_ids", "reduced_target_total", "projection_result"},
        "catalog_result shape")
    _require(_is_hex(catalog["c01_artifact_sha256"], HEX64), "c01 artifact sha256")
    _require(_is_hex(catalog["dev_commit"], HEX40), "catalog dev_commit hex40")
    _require(_is_text(catalog["capture_provenance"]), "capture_provenance text")
    _require(catalog["projection_result"] == C01_PROJECTION_RESULT,
             "projection_result mismatch")
    _require(catalog["reduced_target_total"] == REDUCED_TARGET_TOTAL,
             "reduced_target_total mismatch")

    surfaces = catalog["surfaces"]
    _require(type(surfaces) is list and len(surfaces) == len(CATALOG_SURFACES),
             "surfaces length")
    # The eligibility/constraint matrix is a fixed Gate-1 decision; the only
    # per-run dynamic field is catalog_sha256. Pin every other surface field to
    # the template so a record cannot flip which client is the eligible PASS
    # surface, or rewrite a surface's Gate-1 product-constraint reason.
    template_by_name = {s["surface"]: s for s in CATALOG_SURFACES}
    proven = 0
    seen = set()
    for entry in surfaces:
        _require(type(entry) is dict and set(entry) == {
            "surface", "eligible", "discovery_source_class", "catalog_sha256",
            "result", "product_constraint"}, "surface shape")
        name = entry["surface"]
        _require(_is_text(name), "surface name")
        template = template_by_name.get(name)
        _require(template is not None,
                 f"surface {name} is not in the fixed Gate-1 matrix")
        seen.add(name)
        _require(
            {k: v for k, v in entry.items() if k != "catalog_sha256"} == dict(template),
            f"surface {name} does not match the fixed Gate-1 matrix",
        )
        if entry["eligible"]:
            _require(_is_hex(entry["catalog_sha256"], HEX64), "eligible catalog_sha256")
            _require(
                entry["catalog_sha256"] == catalog["c01_artifact_sha256"],
                "eligible surface catalog_sha256 must equal c01_artifact_sha256",
            )
            proven += 1
        else:
            _require(entry["catalog_sha256"] is None, "ineligible catalog_sha256 null")
    _require(seen == set(template_by_name), "surface set mismatch")
    _require(proven >= 1, "at least one eligible PASS surface required")

    reduced = catalog["reduced_ids"]
    _require(type(reduced) is list and len(reduced) == len(REDUCED_TARGETS),
             "reduced_ids length")
    ids_seen = []
    for row in reduced:
        _require(type(row) is dict and set(row) == {
            "capability_id", "owner_source_repo", "exposure_class", "eligibility",
            "description_chars", "description_words", "installed_sha256",
            "target_chars", "result"}, "reduced_id shape")
        cid = row["capability_id"]
        _require(cid in REDUCED_TARGETS, f"unknown reduced id {cid}")
        ids_seen.append(cid)
        _require(row["exposure_class"] == "cursor-skill-description",
                 f"{cid} exposure_class")
        _require(row["eligibility"] == "eligible-skills-d02", f"{cid} eligibility")
        _require(_is_text(row["owner_source_repo"]), f"{cid} owner")
        _require(_is_nonneg_int(row["description_chars"]), f"{cid} chars int")
        _require(_is_nonneg_int(row["description_words"]), f"{cid} words int")
        _require(_is_hex(row["installed_sha256"], HEX64), f"{cid} installed_sha256")
        _require(row["target_chars"] == REDUCED_TARGETS[cid], f"{cid} target")
        _require(row["description_chars"] == row["target_chars"], f"{cid} count==target")
        _require(row["result"] == "PASS", f"{cid} result PASS")
    _require(ids_seen == sorted(REDUCED_TARGETS, key=lambda i: i.encode("ascii")),
             "reduced_ids order/coverage")


def _validate_residuals(residuals: Any) -> None:
    _require(type(residuals) is list and residuals, "residuals must be a non-empty list")
    for item in residuals:
        _require(type(item) is dict and set(item) == {
            "id", "class", "owner_lane", "status", "severity", "follow_up_ref"},
            "residual shape")
        for key in ("id", "class", "owner_lane", "status", "follow_up_ref"):
            _require(_is_text(item[key]), f"residual {key} text")
        _require(item["severity"] in ALL_SEVERITIES, "residual severity enum")
        _require(item["severity"] not in BLOCKING_SEVERITIES,
                 f"residual {item['id']} is P0/P1")
    # The residual ledger is a fixed program fact; pin it so a record cannot add,
    # drop, or silently reword a residual.
    _require(residuals == [dict(item) for item in RESIDUALS],
             "residuals do not match the fixed residual ledger")


def _validate_rollback_refs(refs: Any) -> None:
    _require(type(refs) is dict and set(refs) == set(ROLLBACK_REFS),
             "rollback_refs key set mismatch")
    for key, value in refs.items():
        _require(_is_text(value), f"rollback_refs[{key}] text")
    _require(refs == dict(ROLLBACK_REFS),
             "rollback_refs do not match the fixed rollback ledger")


def _validate_built_versus_planned(rows: Any) -> None:
    _require(type(rows) is list and len(rows) == len(EXPECTED_TASKS),
             "built_versus_planned length")
    tasks = []
    for row in rows:
        _require(type(row) is dict and set(row) == {
            "task", "planned", "built", "evidence_ref"}, "bvp row shape")
        tasks.append(row["task"])
        for key in ("task", "planned", "built", "evidence_ref"):
            _require(_is_text(row[key]), f"bvp {key} text")
    _require(tuple(tasks) == EXPECTED_TASKS, "bvp task set/order mismatch")
    # The built-versus-planned map is a fixed program fact; pin every row so the
    # planned/built/evidence text cannot be silently rewritten.
    _require(rows == [dict(item) for item in BUILT_VERSUS_PLANNED],
             "built_versus_planned does not match the fixed program map")


def _validate_content_safety(content_safety: Any, no_p0p1: Any) -> None:
    _require(content_safety == CONTENT_SAFETY, "content_safety attestation mismatch")
    _require(type(no_p0p1) is dict and set(no_p0p1) == {"value", "open_items"},
             "no_unresolved_p0_p1 shape")
    _require(no_p0p1["value"] is True, "no_unresolved_p0_p1.value must be True")
    open_items = no_p0p1["open_items"]
    _require(type(open_items) is list, "open_items list")
    for item in open_items:
        _require(type(item) is dict and set(item) == {"id", "severity"},
                 "open_item shape")
        _require(_is_text(item["id"]), "open_item id text")
        _require(item["severity"] in ALL_SEVERITIES, "open_item severity enum")
        _require(item["severity"] not in BLOCKING_SEVERITIES,
                 f"open_item {item['id']} is P0/P1")
    _require(open_items == [dict(item) for item in NO_P0_P1_OPEN_ITEMS],
             "no_unresolved_p0_p1.open_items do not match the fixed ledger")


def validate_document(document: Any) -> None:
    top = {
        "schema", "status", "captured_at_utc", "repository", "dev_commit",
        "dev_tree", "owner_refs", "release_evidence", "static_result",
        "catalog_result", "residuals", "rollback_refs", "built_versus_planned",
        "content_safety", "no_unresolved_p0_p1",
    }
    _require(type(document) is dict and set(document) == top, "top-level key set")
    _require(document["schema"] == SCHEMA, "schema mismatch")
    _require(document["status"] == STATUS_PASS, "status must be PASS")
    _require(document["repository"] == REPOSITORY, "repository mismatch")
    _require(_is_hex(document["dev_commit"], HEX40), "dev_commit hex40")
    _require(_is_hex(document["dev_tree"], HEX40), "dev_tree hex40")
    captured = document["captured_at_utc"]
    _require(_is_text(captured) and UTC.fullmatch(captured) is not None,
             "captured_at_utc format")
    datetime.datetime.strptime(captured, "%Y-%m-%dT%H:%M:%SZ")
    _validate_owner_refs(document["owner_refs"])
    _validate_release_evidence(document["release_evidence"])
    _validate_static_result(document["static_result"])
    _validate_catalog_result(document["catalog_result"])
    _validate_residuals(document["residuals"])
    _validate_rollback_refs(document["rollback_refs"])
    _validate_built_versus_planned(document["built_versus_planned"])
    _validate_content_safety(
        document["content_safety"], document["no_unresolved_p0_p1"]
    )


def validate_path(path: Path) -> None:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValidationError("evidence is not valid UTF-8") from error
    document = kpcm._parse_json_text(text)
    validate_document(document)
    if raw != kpcm.emit(document).encode("ascii"):
        _fail("evidence is not canonical (round-trip byte mismatch)")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _write_atomic(document: dict[str, Any], out: Path) -> None:
    if out.exists():
        _fail(f"refusing to overwrite existing output: {out}")
    payload = kpcm.emit(document).encode("ascii")
    fd = os.open(str(out), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
    except BaseException:
        try:
            out.unlink()
        except OSError:
            pass
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="release2_closure")
    sub = parser.add_subparsers(dest="verb", required=True)

    assemble_parser = sub.add_parser("assemble")
    assemble_parser.add_argument("--dev-root", required=True)
    assemble_parser.add_argument("--skills-root", required=True)
    assemble_parser.add_argument("--orch-root", required=True)
    assemble_parser.add_argument("--cpp-root", required=True)
    assemble_parser.add_argument("--awa-root", required=True)
    assemble_parser.add_argument("--c01-artifact", required=True)
    assemble_parser.add_argument("--out", required=True)

    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("path")
    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.verb == "assemble":
            document = assemble(args)
            _write_atomic(document, Path(args.out))
            sys.stdout.write(f"assembled {args.out}\n")
            return 0
        validate_path(Path(args.path))
        sys.stdout.write("PASS\n")
        return 0
    except ValidationError as error:
        sys.stderr.write(f"release2_closure: INVALID: {error}\n")
        return 3
    except (
        OSError,
        KeyError,
        ValueError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        sys.stderr.write(f"release2_closure: ERROR: {error}\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
