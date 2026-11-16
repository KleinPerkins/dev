"""Exact staged-source normalization and inert v1 manifest selection.

This module is deliberately local, dependency-free, sequential, and side-effect
bounded.  It predicts a deterministic plan only; it does not execute proof,
write receipts, activate focus, or alter hooks.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from _ops.verification import contracts


SELECTOR_VERSION = "1"
MANIFEST_RELATIVE_PATH = b"_ops/verification/verification-manifest.json"
MANIFEST_SCHEMA_RELATIVE_PATH = (
    b"_ops/verification/verification-manifest.schema.json"
)
TEMP_PREFIX = "dev-verification-selector-"
ZERO_OID_RE = re.compile(br"^0+$")
RAW_DIFF_HEADER_RE = re.compile(
    br"^:([0-9]{6}) ([0-9]{6}) ([0-9a-f]{40}) ([0-9a-f]{40}) ([AMDT])$"
)
LS_FILES_HEADER_RE = re.compile(br"^([0-9]{6}) ([0-9a-f]{40}) ([0-3])$")
LS_TREE_HEADER_RE = re.compile(br"^([0-9]{6}) (blob|commit) ([0-9a-f]{40})$")
SAFE_GIT_CONFIG = (
    ("core.attributesFile", "/dev/null"),
    ("core.fsmonitor", "false"),
    ("core.hooksPath", "/dev/null"),
    ("core.preloadIndex", "false"),
    ("diff.external", ""),
    ("diff.renames", "false"),
)
ALLOWED_GIT_ENVIRONMENT = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_SYSTEM",
        "GIT_INDEX_FILE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_OBJECT_DIRECTORY",
        "GIT_TERMINAL_PROMPT",
    }
)


class SelectorError(contracts.ContractError):
    """A selector input cannot support a narrow-completeness claim."""


class SourceRefusal(SelectorError):
    """Exact source capture refused and must not be treated as focused proof."""

    def __init__(
        self,
        diagnostic_code: str,
        message: str,
        *,
        source: SourceBinding | None = None,
        candidate_tree_sha256: str | None = None,
        index_tree_sha: str | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = diagnostic_code
        self.fallback_required = True
        self.effective_mode = "full"
        self.source = source
        self.candidate_tree_sha256 = (
            candidate_tree_sha256
            if candidate_tree_sha256 is not None
            else (
                source.candidate_tree_sha256 if source is not None else None
            )
        )
        self.index_tree_sha = (
            index_tree_sha
            if index_tree_sha is not None
            else (source.index_tree_sha if source is not None else None)
        )
        self.source_bound = source is not None


@dataclass(frozen=True)
class PathIdentity:
    path_b64: str
    path_utf8: str | None = None

    @classmethod
    def from_bytes(
        cls, raw: bytes, *, include_utf8: bool = True
    ) -> "PathIdentity":
        value = contracts.PathValue.from_bytes(raw, include_utf8=include_utf8)
        return cls(value.path_b64, value.path_utf8)

    @classmethod
    def from_object(
        cls, value: Mapping[str, Any], where: str = "path"
    ) -> "PathIdentity":
        parsed = contracts.PathValue.from_object(dict(value), where)
        return cls(parsed.path_b64, parsed.path_utf8)

    @property
    def raw(self) -> bytes:
        return contracts.PathValue(
            self.path_b64, self.path_utf8
        ).raw

    def to_object(self, *, include_utf8: bool = False) -> dict[str, str]:
        value = {"path_b64": self.path_b64}
        if include_utf8 and self.path_utf8 is not None:
            value["path_utf8"] = self.path_utf8
        return value


@dataclass(frozen=True)
class CandidateEntry:
    path: PathIdentity
    mode: str
    blob_sha256: str
    _oid: str | None = field(default=None, repr=False, compare=False)

    def to_digest_object(self) -> dict[str, str]:
        return {
            "path_b64": self.path.path_b64,
            "mode": self.mode,
            "blob_sha256": self.blob_sha256,
        }


@dataclass(frozen=True)
class Change:
    status: str
    old_path: PathIdentity | None
    new_path: PathIdentity | None
    old_mode: str | None
    new_mode: str | None
    old_blob_sha256: str | None
    new_blob_sha256: str | None
    _old_blob: bytes | None = field(default=None, repr=False, compare=False)
    _new_blob: bytes | None = field(default=None, repr=False, compare=False)

    def to_object(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "old_path": (
                self.old_path.to_object()
                if self.old_path is not None
                else None
            ),
            "new_path": (
                self.new_path.to_object()
                if self.new_path is not None
                else None
            ),
            "old_mode": self.old_mode,
            "new_mode": self.new_mode,
            "old_blob_sha256": self.old_blob_sha256,
            "new_blob_sha256": self.new_blob_sha256,
        }

    @property
    def sort_key(self) -> tuple[bytes, bytes, str]:
        return (
            self.new_path.raw if self.new_path is not None else b"",
            self.old_path.raw if self.old_path is not None else b"",
            self.status,
        )


@dataclass(frozen=True)
class SourceBinding:
    repository_id: str
    source_kind: str
    candidate_tree_sha256: str
    manifest_id: str
    selector_version: str
    base_commit_sha: str | None
    head_commit_sha: str | None
    merge_base_sha: str | None
    index_tree_sha: str | None
    commit_sha: str | None
    _candidate_entries: tuple[CandidateEntry, ...] | None = field(
        default=None, repr=False, compare=False
    )
    _base_entries: tuple[CandidateEntry, ...] | None = field(
        default=None, repr=False, compare=False
    )
    _candidate_blobs: Mapping[bytes, bytes] = field(
        default_factory=dict, repr=False, compare=False
    )
    _base_blobs: Mapping[bytes, bytes] = field(
        default_factory=dict, repr=False, compare=False
    )
    _manifest_bytes: bytes | None = field(
        default=None, repr=False, compare=False
    )
    _manifest_schema_bytes: bytes | None = field(
        default=None, repr=False, compare=False
    )
    _base_manifest_bytes: bytes | None = field(
        default=None, repr=False, compare=False
    )
    _base_manifest_schema_bytes: bytes | None = field(
        default=None, repr=False, compare=False
    )
    _platform: str | None = field(default=None, repr=False, compare=False)
    _capabilities: frozenset[str] = field(
        default_factory=frozenset, repr=False, compare=False
    )

    def to_object(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "source_kind": self.source_kind,
            "candidate_tree_sha256": self.candidate_tree_sha256,
            "manifest_id": self.manifest_id,
            "selector_version": self.selector_version,
            "base_commit_sha": self.base_commit_sha,
            "head_commit_sha": self.head_commit_sha,
            "merge_base_sha": self.merge_base_sha,
            "index_tree_sha": self.index_tree_sha,
            "commit_sha": self.commit_sha,
        }


@dataclass(frozen=True)
class Manifest:
    value: Mapping[str, Any]
    canonical_bytes: bytes

    @property
    def manifest_id(self) -> str:
        return str(self.value["manifest_id"])


@dataclass(frozen=True)
class ObligationDecision:
    obligation_id: str
    focused_disposition: str
    selection_causes: tuple[str, ...]

    def to_object(self) -> dict[str, Any]:
        return {
            "obligation_id": self.obligation_id,
            "focused_disposition": self.focused_disposition,
            "selection_causes": list(self.selection_causes),
        }


@dataclass(frozen=True)
class Selection:
    source: SourceBinding
    lane: str
    requested_mode: str
    effective_mode: str
    focus_eligible: bool
    selector_control_ok: bool
    change_tags: tuple[str, ...]
    focused_obligation_ids: tuple[str, ...]
    effective_obligation_ids: tuple[str, ...]
    decisions: tuple[ObligationDecision, ...]
    diagnostic_codes: tuple[str, ...]
    fallback_executor: str | None

    def to_plan(self) -> dict[str, Any]:
        """Return a deterministic in-memory plan; this is not a wire contract."""

        return {
            "source": self.source.to_object(),
            "lane": self.lane,
            "requested_mode": self.requested_mode,
            "effective_mode": self.effective_mode,
            "focus_eligible": self.focus_eligible,
            "selector_control_ok": self.selector_control_ok,
            "change_tags": list(self.change_tags),
            "focused_obligation_ids": list(
                self.focused_obligation_ids
            ),
            "effective_obligation_ids": list(
                self.effective_obligation_ids
            ),
            "decisions": [
                decision.to_object() for decision in self.decisions
            ],
            "diagnostic_codes": list(self.diagnostic_codes),
            "fallback_executor": self.fallback_executor,
        }


@dataclass(frozen=True)
class HarnessSpec:
    cwd: bytes
    argv: tuple[str, ...]
    entrypoints: tuple[bytes, ...]


# This is the bounded v1 command inventory required by the accepted design.
# It validates literal command references only; it is intentionally not a shell,
# Python, or Make parser.
HARNESS_INVENTORY_V1: Mapping[str, HarnessSpec] = {
    "awa.host": HarnessSpec(
        b"_ops",
        ("bash", "checks/worktree-verify.sh"),
        (b"_ops/checks/worktree-verify.sh",),
    ),
    "context.measurement": HarnessSpec(
        b"_ops/context-measurement",
        (
            "python3",
            "-m",
            "unittest",
            "test_kp_context_measure.py",
            "test_correction_dogfood.py",
            "test_validate_static_context_manifest.py",
            "test_release2_closure.py",
        ),
        (
            b"_ops/context-measurement/test_kp_context_measure.py",
            b"_ops/context-measurement/test_correction_dogfood.py",
            b"_ops/context-measurement/test_validate_static_context_manifest.py",
            b"_ops/context-measurement/test_release2_closure.py",
        ),
    ),
    "dev.installed-rules": HarnessSpec(
        b"_ops",
        ("bash", "checks/verify-operating-model.sh", "--local"),
        (b"_ops/checks/verify-operating-model.sh",),
    ),
    "dev.structure": HarnessSpec(
        b"_ops",
        ("bash", "checks/verify-operating-model.sh", "--ci"),
        (b"_ops/checks/verify-operating-model.sh",),
    ),
    "doc.full-compat": HarnessSpec(
        b"_ops",
        ("bash", "checks/doc-warden-verify.sh"),
        (b"_ops/checks/doc-warden-verify.sh",),
    ),
    "gate.session-lock": HarnessSpec(
        b"_ops",
        ("bash", "hooks/session-lock", "check"),
        (b"_ops/hooks/session-lock",),
    ),
    "gate.staged-data": HarnessSpec(
        b"_ops",
        ("bash", "hooks/data-guard"),
        (b"_ops/hooks/data-guard",),
    ),
    "pr.legacy": HarnessSpec(
        b"_ops",
        ("bash", "baseline/profiles/pr-automation/test.sh"),
        (b"_ops/baseline/profiles/pr-automation/test.sh",),
    ),
    "pr.v3": HarnessSpec(
        b"_ops",
        ("bash", "baseline/profiles/pr-automation/v3/test.sh"),
        (b"_ops/baseline/profiles/pr-automation/v3/test.sh",),
    ),
    "snowkit.host-lifecycle": HarnessSpec(
        b"_ops",
        ("bash", "tests/snow-kit-host-bootstrap.sh"),
        (b"_ops/tests/snow-kit-host-bootstrap.sh",),
    ),
    "verify.selector": HarnessSpec(
        b"_ops",
        (
            "python3",
            "-m",
            "unittest",
            "-v",
            "verification.test_contracts",
            "verification.test_selector",
        ),
        (
            b"_ops/verification/contracts.py",
            b"_ops/verification/selector.py",
            b"_ops/verification/test_contracts.py",
            b"_ops/verification/test_selector.py",
        ),
    ),
}

CONTROL_MATCHERS_V1: Mapping[str, tuple[str, bytes]] = {
    "control.accepted.adr": (
        "exact",
        b"_ops/adr/0011-manifest-driven-verification-selector.md",
    ),
    "control.accepted.execution-plan": (
        "exact",
        b"_ops/plans/manifest-driven-verification-execution-v1.md",
    ),
    "control.accepted.target-design": (
        "exact",
        b"_ops/plans/manifest-driven-verification-target-design-v1.md",
    ),
    "control.github": ("prefix", b".github/"),
    "control.harness.checks": ("prefix", b"_ops/checks/"),
    "control.harness.context": (
        "prefix",
        b"_ops/context-measurement/",
    ),
    "control.harness.hooks": ("prefix", b"_ops/hooks/"),
    "control.harness.pr": (
        "prefix",
        b"_ops/baseline/profiles/pr-automation/",
    ),
    "control.harness.snowkit": (
        "exact",
        b"_ops/tests/snow-kit-host-bootstrap.sh",
    ),
    "control.manifest-verification": (
        "prefix",
        b"_ops/verification/",
    ),
    "control.ops.policy": ("exact", b"_ops/POLICY.md"),
    "control.root.agents": ("exact", b"AGENTS.md"),
    "control.root.gitignore": ("exact", b".gitignore"),
    "control.root.makefile": ("exact", b"Makefile"),
    "control.root.manual": ("exact", b"OPERATING-MANUAL.md"),
}


def _raw_b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _manifest_value(
    manifest: Manifest | Mapping[str, Any],
) -> Mapping[str, Any]:
    return manifest.value if isinstance(manifest, Manifest) else manifest


def load_manifest_bytes(
    data: bytes, *, schema_bytes: bytes | None = None
) -> Manifest:
    value = contracts.validate_canonical_input(data)
    if not isinstance(value, dict):
        raise SelectorError("manifest root must be an object")
    contracts.validate_manifest(value)
    if schema_bytes is not None:
        schema = contracts.parse_json_document(schema_bytes)
        contracts.validate_schema_document(schema)
        contracts.validate_against_schema(value, schema)
    return Manifest(copy.deepcopy(value), contracts.canonical_json(value))


def load_manifest(
    path: Path,
    *,
    schema_path: Path | None = None,
) -> Manifest:
    path = Path(path)
    if not path.is_absolute():
        raise SelectorError("manifest path must be absolute")
    if schema_path is None:
        schema_path = path.with_name(
            "verification-manifest.schema.json"
        )
    return load_manifest_bytes(
        path.read_bytes(), schema_bytes=Path(schema_path).read_bytes()
    )


def _matcher_matches(rule: Mapping[str, Any], raw: bytes) -> bool:
    return contracts.matcher_matches(rule["matcher"], raw)


def _matching_rules(
    value: Mapping[str, Any], raw: bytes
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    inputs = [
        rule
        for rule in value.get("input_rules", [])
        if _matcher_matches(rule, raw)
    ]
    inert = [
        rule
        for rule in value.get("inert_rules", [])
        if _matcher_matches(rule, raw)
    ]
    return inputs, inert


def _validate_rule_coverage(
    value: Mapping[str, Any], paths: Iterable[bytes]
) -> None:
    for raw in sorted(set(paths)):
        contracts.PathValue.from_bytes(raw, include_utf8=False)
        inputs, inert = _matching_rules(value, raw)
        if inputs and inert:
            raise SelectorError(
                f"input/inert overlap for {_raw_b64(raw)}"
            )
        if not inputs and len(inert) != 1:
            raise SelectorError(
                f"path must have owners or exactly one inert rule: "
                f"{_raw_b64(raw)}"
            )
        if len(inert) > 1:
            raise SelectorError(
                f"multiple inert rules for {_raw_b64(raw)}"
            )


def _validate_harness_inventory(
    value: Mapping[str, Any],
    candidate_entries: Sequence[CandidateEntry],
) -> None:
    obligations = {
        item["id"]: item for item in value.get("obligations", [])
    }
    if set(obligations) != set(HARNESS_INVENTORY_V1):
        raise SelectorError(
            "obligation inventory differs from bounded v1 harness inventory"
        )
    candidate_paths = {entry.path.raw for entry in candidate_entries}
    control_ids = set(value.get("control_rule_ids", []))
    input_rules = {
        item["id"]: item for item in value.get("input_rules", [])
    }
    if control_ids != set(CONTROL_MATCHERS_V1):
        raise SelectorError(
            "control input inventory differs from bounded v1 controls"
        )
    for rule_id, (kind, raw) in CONTROL_MATCHERS_V1.items():
        matcher = input_rules[rule_id]["matcher"]
        if (
            matcher["kind"] != kind
            or contracts._validate_matcher(
                matcher, f"{rule_id}.matcher"
            )
            != raw
        ):
            raise SelectorError(f"{rule_id}: stale control matcher")
    for obligation_id, spec in HARNESS_INVENTORY_V1.items():
        obligation = obligations[obligation_id]
        if tuple(obligation["argv"]) != spec.argv:
            raise SelectorError(
                f"{obligation_id}: stale or ambiguous literal argv"
            )
        cwd = contracts.PathValue.from_object(
            {"path_b64": obligation["cwd_b64"]}, "cwd"
        ).raw
        if cwd != spec.cwd:
            raise SelectorError(f"{obligation_id}: stale cwd")
        for entrypoint in spec.entrypoints:
            if entrypoint not in candidate_paths:
                raise SelectorError(
                    f"{obligation_id}: candidate entrypoint missing: "
                    f"{_raw_b64(entrypoint)}"
                )
            owning_controls = [
                rule_id
                for rule_id in control_ids
                if _matcher_matches(input_rules[rule_id], entrypoint)
            ]
            if not owning_controls:
                raise SelectorError(
                    f"{obligation_id}: entrypoint lacks control ownership"
                )


def validate_manifest_for_candidate(
    manifest: Manifest | Mapping[str, Any],
    candidate_entries: Sequence[CandidateEntry],
    *,
    schema_bytes: bytes | None = None,
) -> None:
    value = _manifest_value(manifest)
    contracts.validate_manifest(dict(value))
    if schema_bytes is not None:
        schema = contracts.parse_json_document(schema_bytes)
        contracts.validate_schema_document(schema)
        contracts.validate_against_schema(value, schema)
    digest_rows = [
        entry.to_digest_object()
        for entry in sorted(candidate_entries, key=lambda item: item.path.raw)
    ]
    if len(digest_rows) != len(candidate_entries):
        raise SelectorError("candidate entry ambiguity")
    contracts.candidate_tree_digest(digest_rows)
    _validate_rule_coverage(
        value, (entry.path.raw for entry in candidate_entries)
    )
    _validate_harness_inventory(value, candidate_entries)


def focus_eligible(
    change_tags: Iterable[str],
    graduated_tags: Iterable[str],
    *,
    ambiguous: bool = False,
    control_change: bool = False,
) -> bool:
    tags = frozenset(change_tags)
    graduated = frozenset(graduated_tags)
    return bool(tags) and not ambiguous and not control_change and tags <= graduated


def _normalized_platform(source: SourceBinding) -> str:
    platform = source._platform or sys.platform
    if platform.startswith("darwin"):
        return "darwin"
    if platform.startswith("linux"):
        return "linux"
    return platform


def _applicability(
    obligation: Mapping[str, Any],
    source: SourceBinding,
    lane: str,
    mode: str,
) -> tuple[bool, bool]:
    if mode not in obligation.get("eligible_in", []):
        return False, False
    applicability = obligation["applicability"]
    if applicability["lanes"] and lane not in applicability["lanes"]:
        return False, False
    platform = _normalized_platform(source)
    if (
        applicability["platforms"]
        and platform not in applicability["platforms"]
    ):
        return False, False
    if (
        applicability["source_kinds"]
        and source.source_kind not in applicability["source_kinds"]
    ):
        return False, False
    missing = set(applicability["required_capabilities"]) - set(
        source._capabilities
    )
    return not missing, bool(missing)


def _topological_order(
    obligations: Mapping[str, Mapping[str, Any]],
    obligation_ids: Iterable[str],
) -> tuple[str, ...]:
    selected = set(obligation_ids)
    levels: dict[str, int] = {}
    visiting: set[str] = set()

    def level(obligation_id: str) -> int:
        if obligation_id in levels:
            return levels[obligation_id]
        if obligation_id in visiting:
            raise SelectorError("dependency cycle")
        visiting.add(obligation_id)
        dependencies = [
            dep
            for dep in obligations[obligation_id]["depends_on"]
            if dep in selected
        ]
        result = (
            0
            if not dependencies
            else max(level(dep) for dep in dependencies) + 1
        )
        visiting.remove(obligation_id)
        levels[obligation_id] = result
        return result

    return tuple(
        sorted(selected, key=lambda item: (level(item), item.encode("utf-8")))
    )


def _best_effort_obligations(
    value: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    obligations = value.get("obligations", [])
    if not isinstance(obligations, list):
        return result
    for item in obligations:
        if (
            isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item["id"] not in result
        ):
            result[item["id"]] = item
    return result


def _fallback_selection(
    manifest: Manifest | Mapping[str, Any],
    source: SourceBinding,
    lane: str,
    requested_mode: str,
    diagnostics: Iterable[str],
    *,
    source_bound: bool = True,
) -> Selection:
    value = _manifest_value(manifest)
    obligations = _best_effort_obligations(value)
    applicable: list[str] = []
    decisions: list[ObligationDecision] = []
    for obligation_id in sorted(obligations):
        obligation = obligations[obligation_id]
        try:
            is_applicable, blocked = _applicability(
                obligation, source, lane, "full"
            )
        except (KeyError, TypeError, SelectorError):
            is_applicable = False
            blocked = False
        causes = (
            ("fallback",)
            if is_applicable or blocked
            else ("not_applicable",)
        )
        disposition = (
            "blocked"
            if blocked
            else ("run" if is_applicable else "not_applicable")
        )
        if is_applicable:
            applicable.append(obligation_id)
        decisions.append(
            ObligationDecision(obligation_id, disposition, causes)
        )
    try:
        ordered = _topological_order(obligations, applicable)
    except (KeyError, TypeError, SelectorError):
        ordered = tuple(sorted(applicable))
    full_profile = (
        value.get("activation", {}).get("full_profile")
        if isinstance(value.get("activation"), dict)
        else None
    )
    return Selection(
        source=source,
        lane=lane,
        requested_mode=requested_mode,
        effective_mode="full",
        focus_eligible=False,
        selector_control_ok=False,
        change_tags=(),
        focused_obligation_ids=(),
        effective_obligation_ids=ordered,
        decisions=tuple(decisions),
        diagnostic_codes=tuple(sorted(set(diagnostics))),
        fallback_executor=(
            "preserved.full"
            if source_bound and full_profile == "preserved_aggregate"
            else None
        ),
    )


def _validate_source_binding(source: SourceBinding) -> None:
    contracts._validate_source(source.to_object(), "source")
    if source._candidate_entries is None:
        raise SelectorError("source candidate entries unavailable")
    if source._base_entries is None:
        raise SelectorError("source base entries unavailable")
    for entry in (*source._base_entries, *source._candidate_entries):
        if entry.mode not in ("100644", "100755", "120000"):
            raise SelectorError("unsupported tracked Git mode")
    rows = [
        entry.to_digest_object()
        for entry in sorted(
            source._candidate_entries, key=lambda item: item.path.raw
        )
    ]
    digest = str(contracts.candidate_tree_digest(rows))
    if digest != source.candidate_tree_sha256:
        raise SelectorError("candidate-tree digest mismatch")


def _validate_bound_blob(
    entries: Sequence[CandidateEntry],
    raw_path: bytes,
    data: bytes | None,
    where: str,
) -> None:
    if data is None:
        raise SelectorError(f"{where} bytes are unavailable")
    entry = next(
        (item for item in entries if item.path.raw == raw_path),
        None,
    )
    if (
        entry is None
        or entry.blob_sha256 != str(contracts.sha256_id(data))
    ):
        raise SelectorError(f"{where} bytes are not source-bound")


def _validate_changes(
    source: SourceBinding, changes: Sequence[Change]
) -> None:
    if tuple(changes) != tuple(sorted(changes, key=lambda item: item.sort_key)):
        raise SelectorError("changes are not deterministically sorted")
    candidate = {
        item.path.raw: item for item in source._candidate_entries or ()
    }
    base = {item.path.raw: item for item in source._base_entries or ()}
    seen: set[tuple[bytes, bytes, str]] = set()
    for index, change in enumerate(changes):
        key = contracts._validate_change(
            change.to_object(), f"changes[{index}]"
        )
        if key in seen:
            raise SelectorError("duplicate change")
        seen.add(key)
        old_raw = change.old_path.raw if change.old_path else None
        new_raw = change.new_path.raw if change.new_path else None
        if old_raw is not None:
            entry = base.get(old_raw)
            if (
                entry is None
                or entry.mode != change.old_mode
                or entry.blob_sha256 != change.old_blob_sha256
            ):
                raise SelectorError("old change side is not base-bound")
            if (
                change._old_blob is None
                or str(contracts.sha256_id(change._old_blob))
                != change.old_blob_sha256
            ):
                raise SelectorError("old blob bytes are unavailable or stale")
        if new_raw is not None:
            entry = candidate.get(new_raw)
            if (
                entry is None
                or entry.mode != change.new_mode
                or entry.blob_sha256 != change.new_blob_sha256
            ):
                raise SelectorError(
                    "new change side is not candidate-bound"
                )
            if (
                change._new_blob is None
                or str(contracts.sha256_id(change._new_blob))
                != change.new_blob_sha256
            ):
                raise SelectorError("new blob bytes are unavailable or stale")

    expected: list[
        tuple[
            str,
            bytes,
            str | None,
            str | None,
            str | None,
            str | None,
        ]
    ] = []
    for raw in sorted(set(base) | set(candidate)):
        old = base.get(raw)
        new = candidate.get(raw)
        if old is None:
            expected.append(
                (
                    "add",
                    raw,
                    None,
                    new.mode,
                    None,
                    new.blob_sha256,
                )
            )
        elif new is None:
            expected.append(
                (
                    "delete",
                    raw,
                    old.mode,
                    None,
                    old.blob_sha256,
                    None,
                )
            )
        elif (
            old.mode != new.mode
            or old.blob_sha256 != new.blob_sha256
        ):
            status = (
                "type_change"
                if old.mode[:3] != new.mode[:3]
                else "modify"
            )
            expected.append(
                (
                    status,
                    raw,
                    old.mode,
                    new.mode,
                    old.blob_sha256,
                    new.blob_sha256,
                )
            )
    expected.sort(
        key=lambda item: (
            item[1] if item[0] != "delete" else b"",
            item[1] if item[0] != "add" else b"",
            item[0],
        )
    )
    observed = [
        (
            change.status,
            (
                change.new_path.raw
                if change.new_path is not None
                else change.old_path.raw
            ),
            change.old_mode,
            change.new_mode,
            change.old_blob_sha256,
            change.new_blob_sha256,
        )
        for change in changes
    ]
    if observed != expected:
        raise SelectorError("change set is not the complete source delta")


def _semantic_additions(
    value: Mapping[str, Any],
    changes: Sequence[Change],
) -> set[str]:
    additions: set[str] = set()
    input_by_id = {
        item["id"]: item for item in value["input_rules"]
    }
    for semantic in value["semantic_selectors"]:
        baseline_ids = semantic["baseline_input_rule_ids"]
        for change in changes:
            paths = [
                path.raw
                for path in (change.old_path, change.new_path)
                if path is not None
            ]
            matching_baselines = [
                input_by_id[rule_id]
                for rule_id in baseline_ids
                if any(
                    _matcher_matches(input_by_id[rule_id], path)
                    for path in paths
                )
            ]
            if not matching_baselines:
                continue
            try:
                pointers = contracts.classify_json_pointer_changes(
                    change._old_blob,
                    change._new_blob,
                    semantic["limits"],
                )
            except RecursionError as exc:
                raise SelectorError(
                    "JSON nesting exceeds the bounded parser"
                ) from exc
            for pointer_rule in semantic["pointer_rules"]:
                if any(
                    contracts.pointer_rule_matches(
                        pointer_rule["pointer"],
                        pointer_rule["match"],
                        changed_pointer,
                    )
                    for changed_pointer in pointers
                ):
                    additions.update(
                        pointer_rule["add_obligation_ids"]
                    )
    return additions


def _load_base_manifest(
    source: SourceBinding,
) -> Manifest:
    data = source._base_manifest_bytes or source._base_blobs.get(
        MANIFEST_RELATIVE_PATH
    )
    schema_bytes = (
        source._base_manifest_schema_bytes
        or source._base_blobs.get(MANIFEST_SCHEMA_RELATIVE_PATH)
    )
    if data is None or schema_bytes is None:
        raise SelectorError("base manifest or schema is unavailable")
    entries = source._base_entries or ()
    _validate_bound_blob(
        entries, MANIFEST_RELATIVE_PATH, data, "base manifest"
    )
    _validate_bound_blob(
        entries,
        MANIFEST_SCHEMA_RELATIVE_PATH,
        schema_bytes,
        "base manifest schema",
    )
    manifest = load_manifest_bytes(data, schema_bytes=schema_bytes)
    validate_manifest_for_candidate(
        manifest,
        entries,
        schema_bytes=schema_bytes,
    )
    return manifest


def select(
    manifest: Manifest | Mapping[str, Any],
    source: SourceBinding,
    changes: tuple[Change, ...],
    lane: str,
    requested_mode: str,
) -> Selection:
    """Predict a deterministic plan; M1 authority always remains full/shadow."""

    value = _manifest_value(manifest)
    base_value = value
    source_bound = False
    try:
        _validate_source_binding(source)
        source_bound = True
        contracts.validate_manifest(dict(value))
        if source.manifest_id != value["manifest_id"]:
            raise SelectorError("source/manifest identity mismatch")
        candidate_entries = source._candidate_entries or ()
        _validate_bound_blob(
            candidate_entries,
            MANIFEST_RELATIVE_PATH,
            source._manifest_bytes,
            "candidate manifest",
        )
        _validate_bound_blob(
            candidate_entries,
            MANIFEST_SCHEMA_RELATIVE_PATH,
            source._manifest_schema_bytes,
            "candidate manifest schema",
        )
        loaded = load_manifest_bytes(
            source._manifest_bytes or b"",
            schema_bytes=source._manifest_schema_bytes,
        )
        if loaded.manifest_id != value["manifest_id"]:
            raise SelectorError(
                "candidate manifest differs from selected manifest"
            )
        if requested_mode not in contracts.MANIFEST_MODES:
            raise SelectorError("unknown requested mode")
        if lane not in ("local", "runnerless_pr"):
            raise SelectorError("unknown lane")
        validate_manifest_for_candidate(
            manifest,
            candidate_entries,
            schema_bytes=source._manifest_schema_bytes,
        )
        _validate_changes(source, changes)
        if any(change.old_path is not None for change in changes):
            base_value = _load_base_manifest(source).value
        activation = value["activation"]
        if (
            activation["generation"] != 1
            or activation["full_profile"] != "preserved_aggregate"
            or any(
                lane_record["policy"] != "shadow"
                or lane_record["graduated_tags"]
                for lane_record in activation["lanes"]
            )
        ):
            raise SelectorError(
                "M1 selector has no focused activation authority"
            )
    except (contracts.ContractError, KeyError, TypeError, ValueError) as exc:
        return _fallback_selection(
            manifest,
            source,
            lane,
            requested_mode,
            ("selector.control-failed",),
            source_bound=source_bound,
        )

    obligations = {
        item["id"]: item for item in value["obligations"]
    }
    direct: set[str] = set()
    reverse_seeds: set[str] = set()
    tags: set[str] = set()
    inert_only = False
    control_change = False
    ambiguous = False

    try:
        for change in changes:
            change_owners: set[str] = set()
            unique_inputs: dict[
                tuple[str, str], Mapping[str, Any]
            ] = {}
            sides: list[tuple[Mapping[str, Any], PathIdentity]] = []
            if change.old_path is not None:
                sides.append((base_value, change.old_path))
            if change.new_path is not None:
                sides.append((value, change.new_path))
            for rule_manifest, path in sides:
                inputs, inert = _matching_rules(
                    rule_manifest, path.raw
                )
                if inputs and inert:
                    raise SelectorError(
                        "changed path has input/inert overlap"
                    )
                if not inputs and len(inert) != 1:
                    raise SelectorError(
                        "changed path is unmatched or inert-ambiguous"
                    )
                if inputs:
                    for rule in inputs:
                        unique_inputs[
                            (
                                str(rule_manifest["manifest_id"]),
                                str(rule["id"]),
                            )
                        ] = rule
                        if (
                            rule["id"]
                            in rule_manifest["control_rule_ids"]
                        ):
                            control_change = True
                else:
                    inert_only = True
                    tags.add("inert")
            if unique_inputs:
                for rule in unique_inputs.values():
                    change_owners.update(rule["owner_obligation_ids"])
                    tags.update(rule["classification_tags"])
                direct.update(change_owners)
                if (
                    change.status == "delete"
                    or len(unique_inputs) > 1
                    or len(change_owners) > 1
                ):
                    reverse_seeds.update(change_owners)

        direct.update(_semantic_additions(value, changes))
        if base_value["manifest_id"] != value["manifest_id"]:
            direct.update(_semantic_additions(base_value, changes))
        if not direct <= set(obligations):
            raise SelectorError(
                "base and candidate obligation relationship is ambiguous"
            )
    except (contracts.ContractError, KeyError, TypeError) as exc:
        return _fallback_selection(
            manifest,
            source,
            lane,
            requested_mode,
            ("selector.classification-failed",),
        )

    selected: set[str] = set(direct)
    causes: dict[str, set[str]] = {
        obligation_id: {"direct"} for obligation_id in direct
    }

    consumers: dict[str, set[str]] = {
        obligation_id: set() for obligation_id in obligations
    }
    for obligation_id, obligation in obligations.items():
        for dependency in obligation["depends_on"]:
            consumers[dependency].add(obligation_id)
    pending = list(sorted(reverse_seeds))
    seen_reverse = set(pending)
    while pending:
        owner = pending.pop(0)
        for consumer in sorted(consumers[owner]):
            if consumer not in seen_reverse:
                seen_reverse.add(consumer)
                pending.append(consumer)
            selected.add(consumer)
            causes.setdefault(consumer, set()).add("reverse_impact")

    pending = list(sorted(selected))
    while pending:
        obligation_id = pending.pop(0)
        for dependency in obligations[obligation_id]["depends_on"]:
            causes.setdefault(dependency, set()).add("dependency")
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)

    for obligation_id, obligation in obligations.items():
        if requested_mode in obligation["universal_in"]:
            selected.add(obligation_id)
            causes.setdefault(obligation_id, set()).add("universal")

    missing_capability = False
    inapplicable_selected = False
    for obligation_id in tuple(selected):
        is_applicable, blocked = _applicability(
            obligations[obligation_id],
            source,
            lane,
            requested_mode,
        )
        if blocked:
            missing_capability = True
        elif not is_applicable:
            inapplicable_selected = True
    if missing_capability or inapplicable_selected:
        return _fallback_selection(
            manifest,
            source,
            lane,
            requested_mode,
            (
                "selector.capability-blocked"
                if missing_capability
                else "selector.relationship-ineligible"
            ,),
        )

    empty_change_set = not changes
    empty_tag_set = bool(changes) and not tags
    if empty_change_set or empty_tag_set:
        ambiguous = True

    lane_record = next(
        item
        for item in value["activation"]["lanes"]
        if item["lane"] == lane
    )
    eligible = focus_eligible(
        tags,
        lane_record["graduated_tags"],
        ambiguous=ambiguous,
        control_change=control_change,
    )

    diagnostics: set[str] = set()
    selector_control_ok = True
    if ambiguous:
        diagnostics.add(
            "selector.empty-change-set"
            if empty_change_set
            else "selector.empty-change-tags"
        )
        selector_control_ok = False
    if control_change:
        diagnostics.add("selector.self-protection")
    if not eligible and not control_change and not ambiguous:
        diagnostics.add("selector.tags-ungraduated")
    if lane_record["policy"] == "shadow":
        diagnostics.add("selector.lane-shadow")

    effective_mode = requested_mode
    if (
        requested_mode in ("pre_commit", "focused_local", "focused_pr")
        and (
            not eligible
            or lane_record["policy"] != "enforce"
            or control_change
            or ambiguous
        )
    ):
        effective_mode = "full"
    elif requested_mode in ("full", "full_release", "deep_periodic"):
        effective_mode = requested_mode

    if control_change:
        for obligation_id, obligation in obligations.items():
            applicable, _ = _applicability(
                obligation, source, lane, "full"
            )
            if applicable and not obligation["deep_only"]:
                selected.add(obligation_id)
                causes.setdefault(obligation_id, set()).add(
                    "self_protection"
                )

    inventory_mode: str | None = None
    inventory_cause: str | None = None
    include_deep = False
    if requested_mode == "full":
        inventory_mode = "full"
        inventory_cause = "full_mode"
    elif requested_mode == "full_release":
        inventory_mode = "full_release"
        inventory_cause = "full_mode"
    elif requested_mode == "deep_periodic":
        inventory_mode = "deep_periodic"
        inventory_cause = "deep_mode"
        include_deep = True
    if inventory_mode is not None:
        selected = {
            obligation_id
            for obligation_id, obligation in obligations.items()
            if (
                _applicability(
                    obligation, source, lane, inventory_mode
                )[0]
                and (include_deep or not obligation["deep_only"])
            )
        }
        for obligation_id in selected:
            causes.setdefault(obligation_id, set()).add(
                str(inventory_cause)
            )

    focused_ids = _topological_order(obligations, selected)
    if effective_mode == "full":
        effective_set = {
            obligation_id
            for obligation_id, obligation in obligations.items()
            if (
                _applicability(obligation, source, lane, "full")[0]
                and not obligation["deep_only"]
            )
        }
        effective_ids = _topological_order(obligations, effective_set)
    else:
        effective_ids = focused_ids

    decisions: list[ObligationDecision] = []
    for obligation_id in _topological_order(
        obligations, obligations.keys()
    ):
        obligation = obligations[obligation_id]
        applicable, blocked = _applicability(
            obligation, source, lane, requested_mode
        )
        obligation_causes = (
            set(causes.get(obligation_id, set()))
            if obligation_id in focused_ids
            else set()
        )
        if control_change and obligation_id in effective_ids:
            obligation_causes.add("self_protection")
        if not applicable:
            obligation_causes = {"not_applicable"}
            disposition = "blocked" if blocked else "not_applicable"
        elif obligation_causes:
            run_causes = {
                "deep_mode",
                "dependency",
                "direct",
                "fallback",
                "full_mode",
                "reverse_impact",
                "self_protection",
                "universal",
            }
            disposition = (
                "run"
                if obligation_causes & run_causes
                else "skip"
            )
        else:
            if inert_only:
                obligation_causes.add("inert")
            disposition = "skip"
        decisions.append(
            ObligationDecision(
                obligation_id,
                disposition,
                tuple(sorted(obligation_causes)),
            )
        )

    return Selection(
        source=source,
        lane=lane,
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        focus_eligible=eligible,
        selector_control_ok=selector_control_ok,
        change_tags=tuple(sorted(tags)),
        focused_obligation_ids=focused_ids,
        effective_obligation_ids=effective_ids,
        decisions=tuple(decisions),
        diagnostic_codes=tuple(sorted(diagnostics)),
        fallback_executor=(
            "preserved.full"
            if effective_mode == "full"
            and value["activation"]["full_profile"]
            == "preserved_aggregate"
            else None
        ),
    )


def _object_store_path(repo: Path, env: Mapping[str, str]) -> Path:
    result = _run_git(
        repo,
        ("rev-parse", "--path-format=absolute", "--git-path", "objects"),
        env=env,
    )
    raw = result.stdout.rstrip(b"\n")
    try:
        path = Path(raw.decode("utf-8", errors="strict"))
    except UnicodeDecodeError as exc:
        raise SourceRefusal(
            "source.object-path-invalid",
            "Git object path is not strict UTF-8",
        ) from exc
    if not path.is_absolute() or not path.is_dir():
        raise SourceRefusal(
            "source.object-path-invalid",
            "Git object directory is unavailable",
        )
    return path.resolve()


def object_store_digest(objects: Path) -> str:
    """Hash real object-store names, types, symlink targets, and bytes."""

    root = Path(objects)
    digest = hashlib.sha256()
    if not root.is_dir():
        raise SelectorError("object store is not a directory")
    paths = sorted(
        root.rglob("*"),
        key=lambda item: os.fsencode(str(item.relative_to(root))),
    )
    for path in paths:
        relative = os.fsencode(str(path.relative_to(root)))
        metadata = path.lstat()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(stat.S_IFMT(metadata.st_mode).to_bytes(8, "big"))
        if stat.S_ISREG(metadata.st_mode):
            content = path.read_bytes()
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        elif stat.S_ISLNK(metadata.st_mode):
            target = os.fsencode(os.readlink(path))
            digest.update(len(target).to_bytes(8, "big"))
            digest.update(target)
    return str(contracts.sha256_id(digest.digest()))


def _base_environment(home: Path) -> dict[str, str]:
    env = {
        "HOME": str(home),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.defpath,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    return env


def _git_environment(
    home: Path,
    *,
    index_file: Path | None = None,
    object_directory: Path | None = None,
    alternate_object_directory: Path | None = None,
) -> dict[str, str]:
    env = _base_environment(home)
    if index_file is not None:
        env["GIT_INDEX_FILE"] = str(index_file)
    if object_directory is not None:
        env["GIT_OBJECT_DIRECTORY"] = str(object_directory)
    if alternate_object_directory is not None:
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = str(
            alternate_object_directory
        )
    git_keys = {key for key in env if key.startswith("GIT_")}
    if not git_keys <= ALLOWED_GIT_ENVIRONMENT:
        raise SelectorError("unsafe Git environment construction")
    return env


def _run_git(
    repo: Path,
    arguments: Sequence[str],
    *,
    env: Mapping[str, str],
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    git = shutil.which("git", path=env.get("PATH"))
    if git is None:
        raise SourceRefusal("source.git-missing", "git is unavailable")
    argv = [git, "-C", str(repo)]
    for key, value in SAFE_GIT_CONFIG:
        argv.extend(("-c", f"{key}={value}"))
    argv.extend(arguments)
    completed = subprocess.run(
        argv,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(env),
        check=False,
    )
    if check and completed.returncode != 0:
        raise SourceRefusal(
            "source.git-refused",
            f"Git plumbing failed for {arguments[0]}",
        )
    return completed


def _parse_index_entries(
    data: bytes,
) -> tuple[tuple[bytes, ...], frozenset[bytes]]:
    records = data.split(b"\0")
    if records and records[-1] == b"":
        records.pop()
    seen: set[bytes] = set()
    zero_oid_paths: set[bytes] = set()
    for record in records:
        try:
            header, path = record.split(b"\t", 1)
        except ValueError as exc:
            raise SourceRefusal(
                "source.index-malformed", "malformed ls-files output"
            ) from exc
        match = LS_FILES_HEADER_RE.fullmatch(header)
        if match is None:
            raise SourceRefusal(
                "source.index-malformed", "malformed ls-files header"
            )
        mode, oid, stage = match.groups()
        contracts.PathValue.from_bytes(path, include_utf8=False)
        if path in seen:
            raise SourceRefusal(
                "source.index-ambiguous", "duplicate index path"
            )
        seen.add(path)
        if stage != b"0":
            raise SourceRefusal(
                "source.index-unmerged", "unmerged index is unsupported"
            )
        if ZERO_OID_RE.fullmatch(oid):
            zero_oid_paths.add(path)
        if mode == b"160000":
            raise SourceRefusal(
                "source.gitlink-unsupported",
                "gitlink candidate bytes are unsupported",
            )
    return tuple(sorted(seen)), frozenset(zero_oid_paths)


def _parse_index_debug(
    data: bytes, paths: Sequence[bytes]
) -> frozenset[bytes]:
    cursor = 0
    intent_to_add_paths: set[bytes] = set()
    debug_pattern = re.compile(
        br"  ctime: [0-9]+:[0-9]+\n"
        br"  mtime: [0-9]+:[0-9]+\n"
        br"  dev: [0-9]+\tino: [0-9]+\n"
        br"  uid: [0-9]+\tgid: [0-9]+\n"
        br"  size: [0-9]+\tflags: ([0-9a-fA-F]+)\n"
    )
    for path in paths:
        prefix = path + b"\0"
        if not data.startswith(prefix, cursor):
            raise SourceRefusal(
                "source.index-malformed",
                "debug index paths do not match staged entries",
            )
        cursor += len(prefix)
        match = debug_pattern.match(data, cursor)
        if match is None:
            raise SourceRefusal(
                "source.index-malformed",
                "malformed debug index metadata",
            )
        flags = int(match.group(1), 16)
        if flags & 0x20000000:
            intent_to_add_paths.add(path)
        cursor = match.end()
    if cursor != len(data):
        raise SourceRefusal(
            "source.index-malformed",
            "debug index contains trailing bytes",
        )
    return frozenset(intent_to_add_paths)


def _parse_tree(
    repo: Path,
    tree_sha: str,
    env: Mapping[str, str],
) -> tuple[tuple[CandidateEntry, ...], dict[bytes, bytes]]:
    result = _run_git(
        repo,
        ("ls-tree", "-r", "-z", "--full-tree", tree_sha),
        env=env,
    )
    records = result.stdout.split(b"\0")
    if records and records[-1] == b"":
        records.pop()
    entries: list[CandidateEntry] = []
    blobs: dict[bytes, bytes] = {}
    for record in records:
        try:
            header, raw_path = record.split(b"\t", 1)
        except ValueError as exc:
            raise SourceRefusal(
                "source.tree-malformed", "malformed ls-tree output"
            ) from exc
        match = LS_TREE_HEADER_RE.fullmatch(header)
        if match is None:
            raise SourceRefusal(
                "source.tree-malformed", "malformed ls-tree header"
            )
        mode_raw, object_type, oid_raw = match.groups()
        if object_type != b"blob":
            raise SourceRefusal(
                "source.gitlink-unsupported",
                "candidate contains a non-blob tracked entry",
            )
        path = PathIdentity.from_bytes(raw_path)
        oid = oid_raw.decode("ascii")
        blob = _run_git(
            repo, ("cat-file", "blob", oid), env=env
        ).stdout
        blob_digest = str(contracts.sha256_id(blob))
        entries.append(
            CandidateEntry(
                path=path,
                mode=mode_raw.decode("ascii"),
                blob_sha256=blob_digest,
                _oid=oid,
            )
        )
        blobs[raw_path] = blob
    if [entry.path.raw for entry in entries] != sorted(
        entry.path.raw for entry in entries
    ):
        raise SourceRefusal(
            "source.tree-malformed", "ls-tree paths are not byte sorted"
        )
    return tuple(entries), blobs


def _candidate_digest(entries: Sequence[CandidateEntry]) -> str:
    return str(
        contracts.candidate_tree_digest(
            [entry.to_digest_object() for entry in entries]
        )
    )


def _parse_raw_diff(
    data: bytes,
    base_entries: Sequence[CandidateEntry],
    candidate_entries: Sequence[CandidateEntry],
    base_blobs: Mapping[bytes, bytes],
    candidate_blobs: Mapping[bytes, bytes],
) -> tuple[Change, ...]:
    fields = data.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        raise SourceRefusal(
            "source.diff-malformed", "raw diff has an incomplete record"
        )
    base = {entry.path.raw: entry for entry in base_entries}
    candidate = {
        entry.path.raw: entry for entry in candidate_entries
    }
    changes: list[Change] = []
    for offset in range(0, len(fields), 2):
        header = fields[offset]
        raw_path = fields[offset + 1]
        match = RAW_DIFF_HEADER_RE.fullmatch(header)
        if match is None:
            raise SourceRefusal(
                "source.diff-malformed",
                "raw diff status is malformed or rename/copy-like",
            )
        old_mode, new_mode, old_oid, new_oid, raw_status = (
            match.groups()
        )
        status = {
            b"A": "add",
            b"M": "modify",
            b"D": "delete",
            b"T": "type_change",
        }[raw_status]
        contracts.PathValue.from_bytes(raw_path, include_utf8=False)
        old_entry = base.get(raw_path)
        new_entry = candidate.get(raw_path)
        if status == "add" and (
            old_entry is not None or new_entry is None
        ):
            raise SourceRefusal(
                "source.diff-ambiguous", "add does not bind candidate"
            )
        if status == "delete" and (
            old_entry is None or new_entry is not None
        ):
            raise SourceRefusal(
                "source.diff-ambiguous", "delete does not bind base"
            )
        if status in ("modify", "type_change") and (
            old_entry is None or new_entry is None
        ):
            raise SourceRefusal(
                "source.diff-ambiguous", "change side is missing"
            )
        if old_entry is not None and old_entry.mode != old_mode.decode(
            "ascii"
        ):
            raise SourceRefusal(
                "source.diff-ambiguous", "old mode mismatch"
            )
        if new_entry is not None and new_entry.mode != new_mode.decode(
            "ascii"
        ):
            raise SourceRefusal(
                "source.diff-ambiguous", "new mode mismatch"
            )
        expected_old_oid = (
            old_entry._oid.encode("ascii")
            if old_entry is not None and old_entry._oid is not None
            else b"0" * 40
        )
        expected_new_oid = (
            new_entry._oid.encode("ascii")
            if new_entry is not None and new_entry._oid is not None
            else b"0" * 40
        )
        if old_oid != expected_old_oid or new_oid != expected_new_oid:
            raise SourceRefusal(
                "source.diff-ambiguous", "raw diff object mismatch"
            )
        changes.append(
            Change(
                status=status,
                old_path=old_entry.path if old_entry else None,
                new_path=new_entry.path if new_entry else None,
                old_mode=old_entry.mode if old_entry else None,
                new_mode=new_entry.mode if new_entry else None,
                old_blob_sha256=(
                    old_entry.blob_sha256 if old_entry else None
                ),
                new_blob_sha256=(
                    new_entry.blob_sha256 if new_entry else None
                ),
                _old_blob=(
                    base_blobs[raw_path] if old_entry else None
                ),
                _new_blob=(
                    candidate_blobs[raw_path] if new_entry else None
                ),
            )
        )
    result = tuple(sorted(changes, key=lambda item: item.sort_key))
    if len({change.sort_key for change in result}) != len(result):
        raise SourceRefusal(
            "source.diff-ambiguous", "duplicate raw diff record"
        )
    return result


def _resolve_head(
    repo: Path, env: Mapping[str, str]
) -> tuple[str | None, str | None]:
    result = _run_git(
        repo,
        ("rev-parse", "--verify", "HEAD^{commit}"),
        env=env,
        check=False,
    )
    if result.returncode != 0:
        symbolic = _run_git(
            repo, ("symbolic-ref", "-q", "HEAD"), env=env, check=False
        )
        if symbolic.returncode == 0:
            return None, None
        raise SourceRefusal(
            "source.head-ambiguous", "HEAD cannot be resolved"
        )
    commit = result.stdout.rstrip(b"\n")
    if not re.fullmatch(br"[0-9a-f]{40}", commit):
        raise SourceRefusal(
            "source.head-malformed", "HEAD output is malformed"
        )
    commit_sha = commit.decode("ascii")
    tree = _run_git(
        repo, ("rev-parse", f"{commit_sha}^{{tree}}"), env=env
    ).stdout.rstrip(b"\n")
    if not re.fullmatch(br"[0-9a-f]{40}", tree):
        raise SourceRefusal(
            "source.head-malformed", "HEAD tree output is malformed"
        )
    return commit_sha, tree.decode("ascii")


def _copy_private_index(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    destination.write_bytes(data)
    destination.chmod(0o600)


def _capture_staged_source(
    repo: Path,
    index_file: Path,
    root: Path,
    real_objects: Path,
) -> tuple[SourceBinding, tuple[Change, ...]]:
    home = root / "home"
    objects = root / "objects"
    home.mkdir(mode=0o700)
    objects.mkdir(mode=0o700)
    private_index = root / "index"
    verify_index = root / "index.verify"
    original_index_bytes = index_file.read_bytes()
    original_index_stat = index_file.stat()
    _copy_private_index(index_file, private_index)
    env = _git_environment(
        home,
        index_file=private_index,
        object_directory=objects,
        alternate_object_directory=real_objects,
    )
    base_commit, base_tree = _resolve_head(repo, env)
    index_listing = _run_git(
        repo, ("ls-files", "--stage", "-z"), env=env
    ).stdout
    index_paths, zero_oid_paths = _parse_index_entries(index_listing)
    index_debug = _run_git(
        repo, ("ls-files", "--debug", "-z"), env=env
    ).stdout
    intent_to_add_paths = _parse_index_debug(
        index_debug, index_paths
    )
    if not zero_oid_paths <= intent_to_add_paths:
        raise SourceRefusal(
            "source.index-malformed",
            "zero object ID lacks intent-to-add metadata",
        )
    intent_to_add = bool(intent_to_add_paths)
    tree_raw = _run_git(repo, ("write-tree",), env=env).stdout.rstrip(
        b"\n"
    )
    if not re.fullmatch(br"[0-9a-f]{40}", tree_raw):
        raise SourceRefusal(
            "source.tree-malformed", "write-tree output is malformed"
        )
    tree_sha = tree_raw.decode("ascii")
    candidate_entries, candidate_blobs = _parse_tree(
        repo, tree_sha, env
    )
    candidate_digest = _candidate_digest(candidate_entries)
    if base_tree is None:
        empty_raw = _run_git(
            repo, ("mktree",), env=env, input_bytes=b""
        ).stdout.rstrip(b"\n")
        if not re.fullmatch(br"[0-9a-f]{40}", empty_raw):
            raise SourceRefusal(
                "source.tree-malformed",
                "empty tree output is malformed",
                candidate_tree_sha256=candidate_digest,
                index_tree_sha=tree_sha,
            )
        base_tree = empty_raw.decode("ascii")
    base_entries, base_blobs = _parse_tree(repo, base_tree, env)

    manifest_bytes = candidate_blobs.get(MANIFEST_RELATIVE_PATH)
    schema_bytes = candidate_blobs.get(
        MANIFEST_SCHEMA_RELATIVE_PATH
    )
    if manifest_bytes is None or schema_bytes is None:
        raise SourceRefusal(
            "source.manifest-missing",
            "candidate manifest or schema is missing",
            candidate_tree_sha256=candidate_digest,
            index_tree_sha=tree_sha,
        )
    try:
        manifest = load_manifest_bytes(
            manifest_bytes, schema_bytes=schema_bytes
        )
    except contracts.ContractError as exc:
        raise SourceRefusal(
            "source.manifest-invalid",
            "candidate manifest is invalid",
            candidate_tree_sha256=candidate_digest,
            index_tree_sha=tree_sha,
        ) from exc

    source = SourceBinding(
        repository_id=contracts.REPOSITORY_ID,
        source_kind="staged_index",
        candidate_tree_sha256=candidate_digest,
        manifest_id=manifest.manifest_id,
        selector_version=SELECTOR_VERSION,
        base_commit_sha=base_commit,
        head_commit_sha=None,
        merge_base_sha=None,
        index_tree_sha=tree_sha,
        commit_sha=None,
        _candidate_entries=candidate_entries,
        _base_entries=base_entries,
        _candidate_blobs=candidate_blobs,
        _base_blobs=base_blobs,
        _manifest_bytes=manifest_bytes,
        _manifest_schema_bytes=schema_bytes,
        _base_manifest_bytes=base_blobs.get(MANIFEST_RELATIVE_PATH),
        _base_manifest_schema_bytes=base_blobs.get(
            MANIFEST_SCHEMA_RELATIVE_PATH
        ),
    )
    try:
        diff = _run_git(
            repo,
            (
                "diff-tree",
                "--raw",
                "-z",
                "--no-commit-id",
                "--no-abbrev",
                "-r",
                "--no-renames",
                "--no-ext-diff",
                "--no-textconv",
                base_tree,
                tree_sha,
                "--",
            ),
            env=env,
        ).stdout
        changes = _parse_raw_diff(
            diff,
            base_entries,
            candidate_entries,
            base_blobs,
            candidate_blobs,
        )
    except SourceRefusal as exc:
        raise SourceRefusal(
            exc.diagnostic_code,
            str(exc),
            source=source,
        ) from exc
    try:
        validate_manifest_for_candidate(
            manifest,
            candidate_entries,
            schema_bytes=schema_bytes,
        )
    except SourceRefusal as exc:
        raise SourceRefusal(
            exc.diagnostic_code,
            str(exc),
            source=source,
        ) from exc
    except contracts.ContractError as exc:
        raise SourceRefusal(
            "source.manifest-invalid",
            str(exc),
            source=source,
        ) from exc

    current_stat = index_file.stat()
    if (
        index_file.read_bytes() != original_index_bytes
        or current_stat.st_ino != original_index_stat.st_ino
        or current_stat.st_size != original_index_stat.st_size
        or current_stat.st_mtime_ns != original_index_stat.st_mtime_ns
    ):
        raise SourceRefusal(
            "source.index-drift",
            "index changed during capture",
            source=source,
        )
    _copy_private_index(index_file, verify_index)
    verify_env = _git_environment(
        home,
        index_file=verify_index,
        object_directory=objects,
        alternate_object_directory=real_objects,
    )
    verify_tree = _run_git(
        repo, ("write-tree",), env=verify_env
    ).stdout.rstrip(b"\n")
    if verify_tree != tree_raw:
        raise SourceRefusal(
            "source.index-drift",
            "rederived index tree differs",
            source=source,
        )
    verify_entries, _ = _parse_tree(
        repo, tree_sha, verify_env
    )
    if _candidate_digest(verify_entries) != candidate_digest:
        raise SourceRefusal(
            "source.index-drift",
            "rederived candidate digest differs",
            source=source,
        )
    verify_head, _ = _resolve_head(repo, verify_env)
    if verify_head != base_commit:
        raise SourceRefusal(
            "source.head-drift",
            "HEAD changed during capture",
            source=source,
        )
    if intent_to_add:
        raise SourceRefusal(
            "source.intent-to-add",
            "intent-to-add index is ambiguous",
            source=source,
        )
    return source, changes


def staged_source(
    repo: Path, index_file: Path
) -> tuple[SourceBinding, tuple[Change, ...]]:
    """Bind one exact staged index without consulting candidate worktree bytes."""

    repo = Path(repo)
    index_file = Path(index_file)
    if not repo.is_absolute() or not index_file.is_absolute():
        raise SourceRefusal(
            "source.path-invalid",
            "repo and index paths must be absolute",
        )
    try:
        repo = repo.resolve(strict=True)
        index_lstat = index_file.lstat()
    except (FileNotFoundError, OSError) as exc:
        raise SourceRefusal(
            "source.path-invalid", "repo or index path is unavailable"
        ) from exc
    if not repo.is_dir():
        raise SourceRefusal(
            "source.path-invalid", "repo path is not a directory"
        )
    if stat.S_ISLNK(index_lstat.st_mode) or not stat.S_ISREG(
        index_lstat.st_mode
    ):
        raise SourceRefusal(
            "source.index-invalid",
            "index must be a regular non-symlink file",
        )

    probe_root = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    probe_root.chmod(0o700)
    base_env = _git_environment(probe_root)
    try:
        top = _run_git(
            repo,
            ("rev-parse", "--show-toplevel"),
            env=base_env,
        ).stdout.rstrip(b"\n")
        try:
            top_path = Path(top.decode("utf-8", errors="strict")).resolve()
        except UnicodeDecodeError as exc:
            raise SourceRefusal(
                "source.repo-invalid",
                "repository root is not strict UTF-8",
            ) from exc
        if top_path != repo:
            raise SourceRefusal(
                "source.repo-invalid",
                "repo is not the exact Git top level",
            )
        real_objects = _object_store_path(repo, base_env)
        before = object_store_digest(real_objects)
        result: tuple[SourceBinding, tuple[Change, ...]] | None = None
        pending: BaseException | None = None
        capture_root = probe_root / "capture"
        capture_root.mkdir(mode=0o700)
        try:
            result = _capture_staged_source(
                repo, index_file, capture_root, real_objects
            )
        except BaseException as exc:
            pending = exc
        after = object_store_digest(real_objects)
        if after != before:
            raise SourceRefusal(
                "source.object-store-drift",
                "real repository object-store bytes changed",
                source=(
                    result[0]
                    if result is not None
                    else (
                        pending.source
                        if isinstance(pending, SourceRefusal)
                        else None
                    )
                ),
            )
        if pending is not None:
            raise pending
        if result is None:
            raise SourceRefusal(
                "source.capture-failed", "source capture produced no result"
            )
        return result
    finally:
        shutil.rmtree(probe_root, ignore_errors=False)
