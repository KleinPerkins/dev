#!/usr/bin/env python3
"""Stage and verify the runnerless v3 repository contracts.

Staging and control-plane verification are deliberately local-only. Remote rulesets and controller
enrollment remain explicit, post-canary operations so new repositories cannot accidentally make an
unavailable Check required.

The single exception is `verify-fleet-remote`: a read-only live gate (requires `gh` auth and the
qualified lock compiler) that asserts every fleet target's REMOTE committed policy digest plus
v2/epoch lock recompilation matches central authority. Its absence is what let a controller bump be
recorded "complete" while most repositories were never re-staged and were silently stranded
(fail-closed) behind the required Check.
"""

from __future__ import annotations

import argparse
import sys
import importlib.util
import base64
import copy
import difflib
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, NamedTuple
from urllib.parse import quote


HERE = Path(__file__).resolve().parent
POLICY = ".github/pr-automation.json"
MANIFEST = ".github/pr-verification.json"
CODEOWNERS = ".github/CODEOWNERS"
BEGIN = "# BEGIN kleinperkins runnerless PR automation v3"
END = "# END kleinperkins runnerless PR automation v3"
CHECK = "pr-automation / verify"
NODE_CHECK_PREFIX = "pr-automation / job:"
MAX_NODE_CHECK_NAME_BYTES = 100
MAX_NODE_JOB_ID_BYTES = MAX_NODE_CHECK_NAME_BYTES - len(NODE_CHECK_PREFIX.encode("ascii"))
MAX_DEFAULT_BRANCH_BYTES = 100
# Qualified artifact pins only. Generated-lock currency is the v2 schema/epoch below, and
# `lock_metadata_errors` explicitly forbids the retired `payload.controller_release`.
RELEASE_DIGEST = "sha256:3d0b6b34d29b6d0c9ae94daa8dd4cd1182ae3bb9375944322c58febc52fec07c"
LOCK_COMPILER_DIGEST = (
    "sha256:41eae41a36bed2945be2cd3f3c380a9e1d5d89ef73f61e0669f010468dae90a6"
)
EXECUTION_IMAGE = "buildpack-deps"
EXECUTION_DIGEST = "sha256:877e9e4d949edfbcbedabc3a2d7ab593955fee5d6d0777adf3a991eb30c750d8"
EXECUTION_IMAGE_REF = f"{EXECUTION_IMAGE}@{EXECUTION_DIGEST}"
PROFILE_IMAGE_OVERRIDES = {
    "awa-authoritative-verify.v1": (
        "ghcr.io/kleinperkins/awa-authoritative-verify@"
        "sha256:b703c579ac68cfedf72f76f9272bae5f6fd7379a9afec40b79ff40b9fc9d90ce"
    )
}
AWA_RUNTIME_ENVELOPE = {
    "poll_timeout_seconds": 8100,
    "systemd": {
        "timeout_start_seconds": 8400,
        "timeout_stop_seconds": 180,
        "kill_mode": "control-group",
    },
}
AWA_AUTHORITATIVE_ASSIGNMENT = {
    "catalog_repository_id": "awa",
    "coverage_mode": "local",
    "profile_ref": {
        "digest": "sha256:85b7430a0b7974b007448e4f8d9449b140b39aefe2a234c265395372193626e5",
        "id": "awa-authoritative-verify.v1",
    },
    "required_checks": {
        "job_id": "repo.awa.engine-tests",
        "schema": "pr-automation-required-checks/v1",
    },
    "repo": "KleinPerkins/awa",
}
MERGE_SAFETY_NAME = "kleinperkins-merge-safety"
PROTECTED_PATHS = [".github", "CODEOWNERS", "_ops"]
HARD_EXCLUSION = "chaos-scheduler"
PERMANENT_HARD_EXCLUSION = "KleinPerkins/chaos-scheduler"
CONTROLLER_REPO = "KleinPerkins/pr-automation-controller"
ACTIONS_PAUSED_SCRIPT = "scripts/check-fleet-actions-paused.sh"
# `RepositoryCoverageMode` (src/model.rs) — deliberately excludes `structural_legacy`, which exists
# only on the fleet-wide `CoverageMode` and can never be a per-repository assignment (gen3 M1 plan
# §4.3/§7).
COVERAGE_MODES = {"manual_only", "shadow", "local"}
COVERAGE_MODE_RANK = {"manual_only": 0, "shadow": 1, "local": 2}
POLICY_SCHEMA_DIGEST = "sha256:8d73affc448f145808f8cde408477ec89c621b6bc86ddae104e837969e7e3cea"
MANIFEST_SCHEMA_DIGEST = "sha256:8b184da9ebea8ed9b8d9ded345cc206c6b7fd153ff30b33aedaff929c6eb50e2"
# Sandbox execution memory ceiling. Issue #111 diagnosed chaos-labs' index-pack ENOMEM as a
# gVisor pids-cgroup exhaustion (fixed below by pids 32->64), not a memory ceiling problem; a
# per-repository memory override is therefore unneeded and every repository uses this default.
MEMORY_MIB = 512
REMOTE_HOST = "hetzner-pr-controller"
REMOTE_USER = "pr-automation"
REMOTE_HOME = "/var/lib/pr-automation"
REMOTE_BINARY = "/usr/local/bin/pr-automation-controller"
REMOTE_CONFIG = f"{REMOTE_HOME}/.config/pr-automation-controller/config.json"
RECIPE = ".github/pr-recipe.json"
LOCK = ".github/pr-automation.lock.json"
LOCK_SCHEMA = "pr-automation-lock/v2"
LOCK_CONTRACT_VERSION = 1
LOCK_CATALOG_ID = "pr-automation-execution-catalog/v1"
LOCK_COVERED_DIGEST_FIELDS = (
    "catalog_digest",
    "profile_digest",
    "image_digest",
    "recipe_digest",
    "assignment_digest",
)
QUALIFICATION_LEDGER = "qualification-ledger.json"
CANNED_REPOSITORY_CONTRACT_DIGEST = (
    "sha256:43d4d6238bad4513a58135cc28b0810aff03921053f3d0a282261c756e8d5189"
)
OPERATION_ROOT = Path.home() / ".local/state/pr-automation-controller/coverage-operations"
M3_CUSTOM_COMMANDS = {
    "KleinPerkins/intent-router": ["bash", "tests/run-tests.sh"],
    "KleinPerkins/ecosystem-orchestrator": ["bash", "tests/test_lockkit.sh"],
    "KleinPerkins/skills": ["bash", ".github/scripts/verify-skills.sh"],
    "KleinPerkins/ai-analytics-context": [
        "python3",
        "-B",
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-p",
        "test_*.py",
    ],
    "KleinPerkins/dev": ["bash", "_ops/baseline/profiles/pr-automation/v3/test.sh"],
}
STDLIB_LIMITS = {
    "timeout_seconds": 300,
    "cpus_millis": 1000,
    "memory_mib": 512,
    "pids": 64,
    "disk_mib": 1024,
    "inodes": 8192,
    "output_bytes": 65536,
}


class ControlPlaneError(RuntimeError):
    """A closed control-plane request failed before any mutation."""


class CoverageDrift(ControlPlaneError):
    """The dev assignment SOT does not reproduce the observed live config."""


class LiveProjection(NamedTuple):
    candidate: bytes
    changed: bool
    diff: str


class ActivationPackage(NamedTuple):
    candidate: bytes
    rollback: bytes
    activation_generation: int


class RepositoryProjection(NamedTuple):
    repository_id: int
    repo: str
    assignment: dict[str, Any] | None
    ruleset: dict[str, Any]
    required_status_checks: list[dict[str, Any]]
    runtime_app_visible_fingerprints: list[str]
    operator_full_fingerprints: list[str]


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"{path}: {exc}")
    if not isinstance(value, dict):
        fail(f"{path}: root must be an object")
    return value


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def atomic_write_bytes(path: Path, value: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def encoded(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def validate_json_schema_instance(
    schema: dict[str, Any] | bool,
    instance: Any,
    *,
    source: str,
) -> None:
    """Validate the closed Draft-2020-12 subset used by the central authority schemas.

    The repository intentionally has no undeclared third-party JSON Schema dependency. This
    fail-closed subset covers every assertion keyword present in controller.schema.json,
    coverage-assignments.schema.json, and fleet.schema.json; unsupported keywords and local
    references are rejected rather than silently ignored.
    """
    schema_keywords = {
        "$anchor",
        "$comment",
        "$defs",
        "$id",
        "$ref",
        "$schema",
        "additionalProperties",
        "allOf",
        "const",
        "contains",
        "default",
        "definitions",
        "deprecated",
        "description",
        "else",
        "enum",
        "examples",
        "if",
        "items",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "pattern",
        "properties",
        "propertyNames",
        "readOnly",
        "required",
        "then",
        "title",
        "type",
        "uniqueItems",
        "writeOnly",
    }
    schema_map_keywords = {"$defs", "definitions", "properties"}
    schema_value_keywords = {
        "additionalProperties",
        "contains",
        "else",
        "if",
        "items",
        "propertyNames",
        "then",
    }
    schema_types = {"array", "boolean", "integer", "null", "number", "object", "string"}
    string_keywords = {
        "$anchor",
        "$comment",
        "$id",
        "$ref",
        "$schema",
        "description",
        "pattern",
        "title",
    }
    boolean_keywords = {"deprecated", "readOnly", "uniqueItems", "writeOnly"}
    nonnegative_integer_keywords = {"maxItems", "maxLength", "minItems", "minLength"}
    numeric_keywords = {"maximum", "minimum"}
    inspected_schema_nodes: set[int] = set()

    def inspect_schema_node(node: Any, path: str) -> None:
        if isinstance(node, bool):
            return
        if not isinstance(node, dict):
            raise ControlPlaneError(
                f"{source}: {path} schema node must be an object or boolean"
            )
        node_identity = id(node)
        if node_identity in inspected_schema_nodes:
            return
        inspected_schema_nodes.add(node_identity)
        unsupported = sorted(set(node) - schema_keywords)
        if unsupported:
            raise ControlPlaneError(
                f"{source}: {path} has unsupported schema keyword(s) {unsupported}"
            )
        for keyword in string_keywords:
            if keyword in node and not isinstance(node[keyword], str):
                raise ControlPlaneError(f"{source}: {path}.{keyword} must be a string")
        if "$anchor" in node and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9._-]*", node["$anchor"]
        ) is None:
            raise ControlPlaneError(f"{source}: {path}.$anchor is malformed")
        if "pattern" in node:
            try:
                re.compile(node["pattern"])
            except re.error as exc:
                raise ControlPlaneError(
                    f"{source}: {path}.pattern is not a valid regular expression"
                ) from exc
        for keyword in boolean_keywords:
            if keyword in node and not isinstance(node[keyword], bool):
                raise ControlPlaneError(f"{source}: {path}.{keyword} must be boolean")
        for keyword in nonnegative_integer_keywords:
            bound = node.get(keyword)
            if keyword in node and (
                not isinstance(bound, int) or isinstance(bound, bool) or bound < 0
            ):
                raise ControlPlaneError(
                    f"{source}: {path}.{keyword} must be a non-negative integer"
                )
        for keyword in numeric_keywords:
            bound = node.get(keyword)
            if keyword in node and (
                not isinstance(bound, (int, float)) or isinstance(bound, bool)
            ):
                raise ControlPlaneError(f"{source}: {path}.{keyword} must be numeric")
        if "type" in node:
            expected_types = node["type"]
            candidates = (
                [expected_types] if isinstance(expected_types, str) else expected_types
            )
            if (
                not isinstance(candidates, list)
                or not candidates
                or not all(isinstance(item, str) and item in schema_types for item in candidates)
                or len(candidates) != len(set(candidates))
            ):
                raise ControlPlaneError(f"{source}: {path}.type is malformed")
        enum = node.get("enum")
        if "enum" in node and (
            not isinstance(enum, list)
            or not enum
            or len({canonical(item) for item in enum}) != len(enum)
        ):
            raise ControlPlaneError(
                f"{source}: {path}.enum must be a non-empty unique array"
            )
        examples = node.get("examples")
        if "examples" in node and not isinstance(examples, list):
            raise ControlPlaneError(f"{source}: {path}.examples must be an array")
        required = node.get("required")
        if "required" in node and (
            not isinstance(required, list)
            or not all(isinstance(item, str) for item in required)
            or len(required) != len(set(required))
        ):
            raise ControlPlaneError(
                f"{source}: {path}.required must be a unique string array"
            )
        additional = node.get("additionalProperties")
        if "additionalProperties" in node and not isinstance(additional, (bool, dict)):
            raise ControlPlaneError(
                f"{source}: {path}.additionalProperties must be boolean or a schema object"
            )
        if "$ref" in node:
            inspect_schema_node(
                resolve_ref(node["$ref"]),
                f"{path}.$ref",
            )
        for keyword in schema_map_keywords:
            if keyword not in node:
                continue
            child_map = node[keyword]
            if not isinstance(child_map, dict):
                raise ControlPlaneError(f"{source}: {path}.{keyword} must be an object")
            for name, child in child_map.items():
                inspect_schema_node(child, f"{path}.{keyword}.{name}")
        for keyword in schema_value_keywords:
            if keyword not in node:
                continue
            child = node[keyword]
            if not isinstance(child, (dict, bool)):
                raise ControlPlaneError(
                    f"{source}: {path}.{keyword} must be a schema object or boolean"
                )
            inspect_schema_node(child, f"{path}.{keyword}")
        if "allOf" in node:
            all_of = node["allOf"]
            if not isinstance(all_of, list) or not all_of:
                raise ControlPlaneError(
                    f"{source}: {path}.allOf must be a non-empty array"
                )
            for index, child in enumerate(all_of):
                inspect_schema_node(child, f"{path}.allOf[{index}]")

    def schema_type_matches(expected: str, value: Any) -> bool:
        if expected == "object":
            return isinstance(value, dict)
        if expected == "array":
            return isinstance(value, list)
        if expected == "string":
            return isinstance(value, str)
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "null":
            return value is None
        raise ControlPlaneError(f"{source}: unsupported schema type {expected!r}")

    def resolve_ref(reference: str) -> dict[str, Any] | bool:
        if reference == "#":
            value: Any = schema
        elif reference.startswith("#/"):
            value = schema
            for token in reference[2:].split("/"):
                token = token.replace("~1", "/").replace("~0", "~")
                if not isinstance(value, dict) or token not in value:
                    raise ControlPlaneError(f"{source}: unresolved schema reference {reference}")
                value = value[token]
        else:
            raise ControlPlaneError(f"{source}: unsupported non-local schema reference {reference}")
        if not isinstance(value, (dict, bool)):
            raise ControlPlaneError(
                f"{source}: schema reference {reference} is not an object or boolean"
            )
        return value

    def validate(node: dict[str, Any] | bool, value: Any, path: str) -> None:
        if node is True:
            return
        if node is False:
            raise ControlPlaneError(f"{source}: {path} is forbidden by a false schema")
        reference = node.get("$ref")
        if reference is not None:
            if not isinstance(reference, str):
                raise ControlPlaneError(f"{source}: {path} has a malformed schema reference")
            validate(resolve_ref(reference), value, path)

        expected_types = node.get("type")
        if expected_types is not None:
            candidates = (
                [expected_types] if isinstance(expected_types, str) else expected_types
            )
            if (
                not isinstance(candidates, list)
                or not candidates
                or not all(isinstance(item, str) for item in candidates)
                or not any(schema_type_matches(item, value) for item in candidates)
            ):
                raise ControlPlaneError(
                    f"{source}: {path} must have schema type {expected_types!r}"
                )

        if "const" in node and value != node["const"]:
            raise ControlPlaneError(f"{source}: {path} differs from its schema const")
        if "enum" in node and value not in node["enum"]:
            raise ControlPlaneError(f"{source}: {path} is outside its schema enum")

        if isinstance(value, str):
            pattern = node.get("pattern")
            if pattern is not None and (
                not isinstance(pattern, str) or re.search(pattern, value) is None
            ):
                raise ControlPlaneError(f"{source}: {path} does not match its schema pattern")
            minimum_length = node.get("minLength")
            maximum_length = node.get("maxLength")
            if isinstance(minimum_length, int) and len(value) < minimum_length:
                raise ControlPlaneError(f"{source}: {path} is shorter than its schema minimum")
            if isinstance(maximum_length, int) and len(value) > maximum_length:
                raise ControlPlaneError(f"{source}: {path} exceeds its schema maximum")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            minimum = node.get("minimum")
            maximum = node.get("maximum")
            if minimum is not None and (
                not isinstance(minimum, (int, float)) or isinstance(minimum, bool)
            ):
                raise ControlPlaneError(f"{source}: {path} schema minimum is malformed")
            if maximum is not None and (
                not isinstance(maximum, (int, float)) or isinstance(maximum, bool)
            ):
                raise ControlPlaneError(f"{source}: {path} schema maximum is malformed")
            if isinstance(minimum, (int, float)) and value < minimum:
                raise ControlPlaneError(f"{source}: {path} is below its schema minimum")
            if isinstance(maximum, (int, float)) and value > maximum:
                raise ControlPlaneError(f"{source}: {path} exceeds its schema maximum")

        if isinstance(value, list):
            minimum_items = node.get("minItems")
            maximum_items = node.get("maxItems")
            if isinstance(minimum_items, int) and len(value) < minimum_items:
                raise ControlPlaneError(f"{source}: {path} has too few items")
            if isinstance(maximum_items, int) and len(value) > maximum_items:
                raise ControlPlaneError(f"{source}: {path} has too many items")
            if node.get("uniqueItems") is True:
                rendered = [canonical(item) for item in value]
                if len(rendered) != len(set(rendered)):
                    raise ControlPlaneError(f"{source}: {path} items are not unique")
            items = node.get("items")
            if "items" in node:
                for index, item in enumerate(value):
                    validate(items, item, f"{path}[{index}]")
            if "contains" in node:
                contains = node["contains"]
                if not any(
                    schema_matches(contains, item, f"{path}[{index}]")
                    for index, item in enumerate(value)
                ):
                    raise ControlPlaneError(f"{source}: {path} has no item matching contains")

        if isinstance(value, dict):
            required = node.get("required", [])
            if isinstance(required, list):
                missing = [key for key in required if key not in value]
                if missing:
                    raise ControlPlaneError(f"{source}: {path} is missing {missing}")
            properties = node.get("properties", {})
            if not isinstance(properties, dict):
                properties = {}
            for key, child in properties.items():
                if key in value:
                    validate(child, value[key], f"{path}.{key}")
            if "propertyNames" in node:
                property_names = node["propertyNames"]
                for key in value:
                    validate(property_names, key, f"{path}.<propertyName>")
            additional = node.get("additionalProperties", True)
            extras = set(value) - set(properties)
            if additional is False and extras:
                raise ControlPlaneError(f"{source}: {path} has extra keys {sorted(extras)}")
            if isinstance(additional, (dict, bool)):
                for key in extras:
                    validate(additional, value[key], f"{path}.{key}")

        all_of = node.get("allOf", [])
        if isinstance(all_of, list):
            for child in all_of:
                validate(child, value, path)
        if "if" in node:
            matched = schema_matches(node["if"], value, path)
            consequence_keyword = "then" if matched else "else"
            if consequence_keyword in node:
                validate(node[consequence_keyword], value, path)

    def schema_matches(node: dict[str, Any] | bool, value: Any, path: str) -> bool:
        try:
            validate(node, value, path)
        except ControlPlaneError:
            return False
        return True

    if not isinstance(schema, (dict, bool)):
        raise ControlPlaneError(f"{source}: schema root must be an object or boolean")
    inspect_schema_node(schema, "$schema")
    validate(schema, instance, "$")


def normalize_ruleset(value: dict[str, Any]) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    for raw in value.get("rules", []):
        rule: dict[str, Any] = {"type": raw.get("type"), "parameters": None}
        params = raw.get("parameters") or {}
        if raw.get("type") == "pull_request":
            rule["parameters"] = {
                "allowed_merge_methods": sorted(params.get("allowed_merge_methods", [])),
                "dismiss_stale_reviews_on_push": params.get("dismiss_stale_reviews_on_push"),
                "require_code_owner_review": params.get("require_code_owner_review"),
                "require_last_push_approval": params.get("require_last_push_approval"),
                "required_approving_review_count": params.get("required_approving_review_count"),
                "required_review_thread_resolution": params.get("required_review_thread_resolution"),
                "required_reviewers": params.get("required_reviewers", []),
            }
        elif raw.get("type") == "required_status_checks":
            rule["parameters"] = {
                "do_not_enforce_on_create": params.get("do_not_enforce_on_create"),
                "required_status_checks": sorted(
                    params.get("required_status_checks", []), key=canonical
                ),
                "strict_required_status_checks_policy": params.get(
                    "strict_required_status_checks_policy"
                ),
            }
        rules.append(rule)
    ref_name = value.get("conditions", {}).get("ref_name", {})
    return {
        "name": value.get("name"),
        "target": value.get("target"),
        "enforcement": value.get("enforcement"),
        "bypass_actors": sorted(value.get("bypass_actors", []), key=canonical),
        "conditions": {
            "ref_name": {
                "include": sorted(ref_name.get("include", [])),
                "exclude": sorted(ref_name.get("exclude", [])),
            }
        },
        "rules": sorted(rules, key=lambda item: (str(item.get("type")), canonical(item))),
    }


def fingerprint(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def normalize_app_visible_ruleset(value: dict[str, Any]) -> dict[str, Any]:
    """Mirror the controller's App-token canonical view: bypass-redacted, null parameters omitted."""
    app_visible = copy.deepcopy(value)
    app_visible["bypass_actors"] = []
    normalized = normalize_ruleset(app_visible)
    for rule in normalized["rules"]:
        if rule.get("parameters") is None:
            rule.pop("parameters")
    return normalized


def ruleset_fingerprint_pair(value: dict[str, Any]) -> dict[str, list[str]]:
    """Derive the two visibility layers independently from their actual rendered bytes."""
    operator_full = fingerprint(normalize_ruleset(value))
    runtime_app_visible = fingerprint(normalize_app_visible_ruleset(value))
    return {
        "runtime_app_visible": [runtime_app_visible],
        "operator_full": [operator_full],
    }


def _render_base_ruleset(default_branch: str) -> dict[str, Any]:
    validate_default_branch(default_branch)
    source = (HERE / "merge-safety.ruleset.json.tmpl").read_text(encoding="utf-8")
    if source.count("{{DEFAULT_BRANCH}}") != 1:
        raise ControlPlaneError("merge-safety template must contain exactly one branch placeholder")
    try:
        branch_fragment = json.dumps(default_branch, ensure_ascii=False)[1:-1]
        value = json.loads(source.replace("{{DEFAULT_BRANCH}}", branch_fragment))
    except json.JSONDecodeError as exc:
        raise ControlPlaneError(f"merge-safety template is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ControlPlaneError("merge-safety template root must be an object")
    return value


def _required_status_checks(value: dict[str, Any]) -> list[dict[str, Any]]:
    rules = [
        rule
        for rule in value.get("rules", [])
        if isinstance(rule, dict) and rule.get("type") == "required_status_checks"
    ]
    if len(rules) != 1:
        raise ControlPlaneError("merge-safety ruleset must contain exactly one required-status rule")
    checks = (rules[0].get("parameters") or {}).get("required_status_checks")
    if not isinstance(checks, list):
        raise ControlPlaneError("merge-safety required_status_checks must be a list")
    return checks


def validate_default_branch(value: Any, source: str = "default_branch") -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9._-]+", value) is None:
        raise ControlPlaneError(
            f"{source} must be a non-empty ASCII [A-Za-z0-9._-] atom"
        )
    if len(value.encode("ascii")) > MAX_DEFAULT_BRANCH_BYTES:
        raise ControlPlaneError(
            f"{source} exceeds the {MAX_DEFAULT_BRANCH_BYTES}-byte controller limit"
        )
    return value


def render_ruleset_transition(
    live_ruleset: dict[str, Any],
    desired_ruleset: dict[str, Any],
    *,
    expected_ruleset_id: int,
    expected_repo: str,
) -> dict[str, Any]:
    """Bind a base-template-derived projection to the immutable live ruleset identity."""
    validate_live_ruleset_identity(
        live_ruleset,
        expected_ruleset_id=expected_ruleset_id,
        expected_repo=expected_repo,
    )
    if (
        desired_ruleset.get("name") != MERGE_SAFETY_NAME
        or desired_ruleset.get("target") != "branch"
        or desired_ruleset.get("enforcement") != "active"
    ):
        raise ControlPlaneError("desired merge-safety ruleset identity is invalid")
    rendered = copy.deepcopy(desired_ruleset)
    rendered["id"] = expected_ruleset_id
    rendered["source_type"] = "Repository"
    rendered["source"] = expected_repo
    return rendered


def validate_live_ruleset_identity(
    ruleset: Any,
    *,
    expected_ruleset_id: int,
    expected_repo: str,
) -> None:
    if (
        not isinstance(expected_ruleset_id, int)
        or isinstance(expected_ruleset_id, bool)
        or expected_ruleset_id < 1
    ):
        raise ControlPlaneError(f"{expected_repo} has no expected current ruleset id")
    if not isinstance(ruleset, dict):
        raise ControlPlaneError(
            f"{expected_repo} expected ruleset id {expected_ruleset_id} is unreachable"
        )
    identity = {
        "id": expected_ruleset_id,
        "name": MERGE_SAFETY_NAME,
        "target": "branch",
        "enforcement": "active",
        "source_type": "Repository",
        "source": expected_repo,
    }
    observed = {key: ruleset.get(key) for key in identity}
    if observed != identity:
        raise ControlPlaneError(
            f"{expected_repo} ruleset identity changed: expected={identity} observed={observed}"
        )


def validate_managed_ruleset_listing(
    listed: Any,
    *,
    expected_ruleset_id: int,
    expected_repo: str,
) -> None:
    if not isinstance(listed, list):
        raise ControlPlaneError(f"{expected_repo} managed ruleset metadata is unreachable")
    matching = [
        item
        for item in listed
        if isinstance(item, dict) and item.get("name") == MERGE_SAFETY_NAME
    ]
    expected = {
        "id": expected_ruleset_id,
        "name": MERGE_SAFETY_NAME,
        "target": "branch",
        "enforcement": "active",
    }
    if len(matching) != 1 or {key: matching[0].get(key) for key in expected} != expected:
        raise ControlPlaneError(
            f"{expected_repo} must have exactly one active {MERGE_SAFETY_NAME} managed "
            f"ruleset with central id {expected_ruleset_id}; observed={matching}"
        )


def validate_applied_ruleset_semantics(
    observed: Any,
    desired: dict[str, Any],
    *,
    expected_ruleset_id: int,
    expected_repo: str,
) -> dict[str, Any]:
    validate_live_ruleset_identity(
        observed,
        expected_ruleset_id=expected_ruleset_id,
        expected_repo=expected_repo,
    )
    assert isinstance(observed, dict)
    observed_normalized = normalize_ruleset(observed)
    desired_normalized = normalize_ruleset(desired)
    if observed_normalized != desired_normalized:
        raise ControlPlaneError(
            f"{expected_repo} applied ruleset semantics differ from the shared resolver: "
            f"observed={observed_normalized} desired={desired_normalized}"
        )
    return {
        "ruleset_id": expected_ruleset_id,
        "operator_full_fingerprint": fingerprint(observed_normalized),
    }


def require_exact_keys(value: dict[str, Any], expected: set[str], source: str) -> None:
    actual = set(value)
    if actual != expected:
        fail(f"{source}: keys differ; missing={sorted(expected - actual)} extra={sorted(actual - expected)}")


def validate_policy(
    value: dict[str, Any],
    source: str,
    *,
    assignments: dict[str, Any] | None = None,
    fleet: dict[str, Any] | None = None,
    controller: dict[str, Any] | None = None,
) -> None:
    require_exact_keys(
        value,
        {
            "version",
            "repository_id",
            "owner",
            "name",
            "default_branch",
            "activation_generation",
            "check_name",
            "verifier_app_id",
            "verifier_integration_id",
            "reviewer_app_id",
            "reviewer_integration_id",
            "protected_paths",
            "ruleset_fingerprints",
            "max_changed_files",
            "max_total_patch_bytes",
            "controller_release_digest",
        },
        source,
    )
    if value["version"] != "pr-automation/v3":
        fail(f"{source}: unsupported version")
    if not isinstance(value["repository_id"], int) or value["repository_id"] < 1:
        fail(f"{source}: repository_id must be positive")
    if value["owner"] != "KleinPerkins":
        fail(f"{source}: owner must be KleinPerkins")
    if not isinstance(value["name"], str) or not value["name"]:
        fail(f"{source}: name must be non-empty")
    if not isinstance(value["default_branch"], str) or not value["default_branch"]:
        fail(f"{source}: default_branch must be non-empty")
    if not isinstance(value["activation_generation"], int) or value["activation_generation"] < 1:
        fail(f"{source}: activation_generation must be a positive integer")
    if value["check_name"] != CHECK:
        fail(f"{source}: Check name differs from the stable contract")
    if (
        value["verifier_app_id"] != 4274739
        or value["verifier_integration_id"] != 4274739
        or value["reviewer_app_id"] != 4269364
        or value["reviewer_integration_id"] != 4269364
    ):
        fail(f"{source}: App bindings differ from the qualified pair")
    if value["protected_paths"] != PROTECTED_PATHS:
        fail(f"{source}: protected_paths must equal {PROTECTED_PATHS}")
    if value["max_changed_files"] != 200 or value["max_total_patch_bytes"] != 5_000_000:
        fail(f"{source}: repository bounds differ from the qualified contract")
    if value["controller_release_digest"] != RELEASE_DIGEST:
        fail(f"{source}: controller release digest differs from the qualified release")
    if assignments is None:
        assignments = load_json(HERE / "coverage-assignments.json")
    if fleet is None:
        fleet = load_json(HERE / "fleet.json")
    if controller is None:
        controller = load_json(HERE / "controller.json")
    try:
        projection = resolve_repository_projection(
            assignments,
            fleet,
            controller,
            repository_id=value["repository_id"],
            repo=f"{value['owner']}/{value['name']}",
            default_branch=value["default_branch"],
        )
    except ControlPlaneError as exc:
        fail(f"{source}: {exc}")
    if value["ruleset_fingerprints"] != projection.runtime_app_visible_fingerprints:
        fail(f"{source}: runtime ruleset fingerprints differ from repository projection")


def validate_manifest(value: dict[str, Any], source: str) -> None:
    require_exact_keys(value, {"version", "jobs", "secondary_sources"}, source)
    if value["version"] != "pr-automation-verification/v1":
        fail(f"{source}: unsupported version")
    if value["secondary_sources"] != []:
        fail(f"{source}: secondary sources are forbidden")
    jobs = value["jobs"]
    if not isinstance(jobs, list) or len(jobs) != 1:
        fail(f"{source}: exactly one closed repository-contract job is required")
    expected = {
        "id": "verify-repository-contract",
        "image": EXECUTION_IMAGE_REF,
        "argv": ["repository-contract"],
        "environment": {"CI": "true"},
        "network": "none",
        "discovery": {"kind": "literal_stdout", "literal": "PR_AUTOMATION_VERIFY_OK"},
        "limits": {
            "timeout_seconds": 120,
            "cpus_millis": 500,
            "memory_mib": MEMORY_MIB,
            "pids": 64,
            "disk_mib": 128,
            "inodes": 4096,
            "output_bytes": 32768,
        },
    }
    if jobs[0] != expected:
        fail(f"{source}: job differs from the qualified closed execution contract")


def validate_coverage_assignments(value: dict[str, Any], fleet_repos: list[str], source: str) -> None:
    """Validate the sole declarative assignment authority before deterministic live projection.

    `coverage-assignments.json` is the only mutable authoring store. M2 projects each entry directly
    into `LiveConfig.repositories[].coverage_assignment`; no parallel assignment file or database is
    permitted.
    """
    require_exact_keys(value, {"schema", "assignments"}, source)
    if value["schema"] != "pr-automation-coverage-assignments/v2":
        fail(f"{source}: unsupported schema")
    assignments = value["assignments"]
    if not isinstance(assignments, list):
        fail(f"{source}: assignments must be a list")
    seen_repos: set[str] = set()
    seen_catalog_ids: set[str] = set()
    for index, entry in enumerate(assignments):
        label = f"{source}: assignments[{index}]"
        if not isinstance(entry, dict):
            fail(f"{label}: must be an object")
        required_keys = {"repo", "coverage_mode", "catalog_repository_id", "profile_ref"}
        actual_keys = set(entry)
        if not required_keys <= actual_keys or not actual_keys <= required_keys | {"required_checks"}:
            fail(
                f"{label}: keys differ; missing={sorted(required_keys - actual_keys)} "
                f"extra={sorted(actual_keys - required_keys - {'required_checks'})}"
            )
        repo = entry["repo"]
        if not isinstance(repo, str) or not re.fullmatch(
            r"KleinPerkins/[A-Za-z0-9._-]+",
            repo,
        ):
            fail(f"{label}: repo must be a full KleinPerkins repository name")
        if repo in seen_repos:
            fail(f"{label}: duplicate assignment for {repo}")
        seen_repos.add(repo)
        if repo not in fleet_repos:
            fail(f"{label}: {repo} is not a fleet.json target")
        if repo.rsplit("/", 1)[-1] == HARD_EXCLUSION:
            fail(f"{label}: chaos-scheduler is a hard no-touch exclusion and cannot be assigned")
        if entry["coverage_mode"] not in COVERAGE_MODES:
            fail(f"{label}: coverage_mode must be one of {sorted(COVERAGE_MODES)}")
        expected_catalog_id = repo.rsplit("/", 1)[-1]
        if (
            not isinstance(entry["catalog_repository_id"], str)
            or entry["catalog_repository_id"] != expected_catalog_id
        ):
            fail(
                f"{label}: catalog_repository_id must equal the repository's own short name "
                f"({expected_catalog_id!r}) — LiveConfig::validate's owner/name cross-binding check"
            )
        if entry["catalog_repository_id"] in seen_catalog_ids:
            fail(f"{label}: duplicate coverage_assignment.catalog_repository_id")
        seen_catalog_ids.add(entry["catalog_repository_id"])
        profile_ref = entry["profile_ref"]
        if not isinstance(profile_ref, dict):
            fail(f"{label}: profile_ref must be an object")
        require_exact_keys(profile_ref, {"id", "digest"}, f"{label}.profile_ref")
        if not isinstance(profile_ref["id"], str) or not profile_ref["id"]:
            fail(f"{label}.profile_ref: id must be non-empty")
        digest = profile_ref["digest"]
        if (
            not isinstance(digest, str)
            or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest)
        ):
            fail(f"{label}.profile_ref: digest must be a complete sha256: digest")
        if "required_checks" not in entry:
            continue
        required_checks = entry["required_checks"]
        if required_checks is None:
            continue
        if not isinstance(required_checks, dict):
            fail(f"{label}.required_checks: must be an object or null")
        require_exact_keys(
            required_checks,
            {"schema", "job_id"},
            f"{label}.required_checks",
        )
        if required_checks["schema"] != "pr-automation-required-checks/v1":
            fail(f"{label}.required_checks: unsupported schema")
        if entry["coverage_mode"] != "local":
            fail(f"{label}.required_checks: required checks require local coverage")
        job_id = required_checks["job_id"]
        prefix = f"repo.{entry['catalog_repository_id']}."
        if (
            not isinstance(job_id, str)
            or not job_id.startswith(prefix)
            or not re.fullmatch(r"[a-z0-9._-]+", job_id)
            or len(job_id.encode("ascii")) > MAX_NODE_JOB_ID_BYTES
        ):
            fail(
                f"{label}.required_checks: job_id must be a lowercase ASCII "
                f"{prefix!r}-namespaced node of at most {MAX_NODE_JOB_ID_BYTES} bytes"
            )


def _validated_fleet_targets(fleet: dict[str, Any]) -> list[dict[str, Any]]:
    targets = fleet.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ControlPlaneError("fleet targets must be a non-empty list")
    seen_repos: set[str] = set()
    seen_ids: set[int] = set()
    seen_ruleset_ids: set[int] = set()
    result: list[dict[str, Any]] = []
    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            raise ControlPlaneError(f"fleet targets[{index}] must be an object")
        repo = target.get("repo")
        repository_id = target.get("repository_id")
        default_branch = target.get("default_branch")
        ruleset_id = target.get("merge_safety_ruleset_id", ...)
        validate_default_branch(
            default_branch,
            f"fleet targets[{index}].default_branch",
        )
        if (
            not isinstance(repo, str)
            or not re.fullmatch(r"KleinPerkins/[A-Za-z0-9._-]+", repo)
            or not isinstance(repository_id, int)
            or isinstance(repository_id, bool)
            or repository_id < 1
            or ruleset_id is ...
            or (
                ruleset_id is not None
                and (
                    not isinstance(ruleset_id, int)
                    or isinstance(ruleset_id, bool)
                    or ruleset_id < 1
                )
            )
        ):
            raise ControlPlaneError(
                f"fleet targets[{index}] must bind repo, positive repository_id, "
                "default_branch, and explicit merge_safety_ruleset_id"
            )
        if repo in seen_repos or repository_id in seen_ids:
            raise ControlPlaneError("fleet target repository names and IDs must be unique")
        if ruleset_id is not None and ruleset_id in seen_ruleset_ids:
            raise ControlPlaneError("fleet current ruleset IDs must be unique")
        seen_repos.add(repo)
        seen_ids.add(repository_id)
        if ruleset_id is not None:
            seen_ruleset_ids.add(ruleset_id)
        result.append(target)
    return result


def _fleet_repos(fleet: dict[str, Any]) -> list[str]:
    return [target["repo"] for target in _validated_fleet_targets(fleet)]


def resolve_fleet_target(
    fleet: dict[str, Any],
    *,
    repository_id: int,
    repo: str,
) -> dict[str, Any]:
    if (
        not isinstance(repository_id, int)
        or isinstance(repository_id, bool)
        or repository_id < 1
        or not isinstance(repo, str)
    ):
        raise ControlPlaneError("repository identity must include a positive ID and full name")
    targets = _validated_fleet_targets(fleet)
    matches = [
        target
        for target in targets
        if target["repository_id"] == repository_id or target["repo"] == repo
    ]
    if (
        len(matches) != 1
        or matches[0]["repository_id"] != repository_id
        or matches[0]["repo"] != repo
    ):
        raise ControlPlaneError(
            f"repository identity must resolve exactly one enrolled fleet target: "
            f"id={repository_id} repo={repo}"
        )
    return matches[0]


def record_created_ruleset_identity(
    fleet_path: Path,
    *,
    repository_id: int,
    repo: str,
    ruleset_id: int,
) -> None:
    """Atomically promote an explicit creation result into central fleet authority."""
    fleet = load_json(fleet_path)
    target = resolve_fleet_target(
        fleet,
        repository_id=repository_id,
        repo=repo,
    )
    if target["merge_safety_ruleset_id"] is not None:
        raise ControlPlaneError(
            f"{repo} already has central ruleset id {target['merge_safety_ruleset_id']}"
        )
    if (
        not isinstance(ruleset_id, int)
        or isinstance(ruleset_id, bool)
        or ruleset_id < 1
    ):
        raise ControlPlaneError("created ruleset identity must be a positive integer")
    candidate = copy.deepcopy(fleet)
    candidate_target = resolve_fleet_target(
        candidate,
        repository_id=repository_id,
        repo=repo,
    )
    candidate_target["merge_safety_ruleset_id"] = ruleset_id
    _validated_fleet_targets(candidate)
    validate_json_schema_instance(
        load_json(HERE / "fleet.schema.json"),
        candidate,
        source="created fleet ruleset identity",
    )
    atomic_write(fleet_path, encoded(candidate))


def _hard_exclusions(controller: dict[str, Any]) -> list[str]:
    exclusions = controller.get("hard_exclusions")
    if not isinstance(exclusions, list) or not all(isinstance(item, str) for item in exclusions):
        raise ControlPlaneError("controller hard_exclusions must be a string list")
    if PERMANENT_HARD_EXCLUSION not in exclusions:
        raise ControlPlaneError(
            f"controller hard_exclusions must preserve {PERMANENT_HARD_EXCLUSION}"
        )
    return exclusions


def _validate_assignments_or_raise(
    assignments: dict[str, Any],
    fleet: dict[str, Any],
) -> None:
    try:
        validate_coverage_assignments(assignments, _fleet_repos(fleet), "coverage-assignments.json")
    except SystemExit as exc:
        raise ControlPlaneError(str(exc)) from exc


def _assignment_map(assignments: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in assignments["assignments"]:
        projected = {
            "coverage_mode": entry["coverage_mode"],
            "catalog_repository_id": entry["catalog_repository_id"],
            "profile_ref": copy.deepcopy(entry["profile_ref"]),
        }
        if entry.get("required_checks") is not None:
            projected["required_checks"] = copy.deepcopy(entry["required_checks"])
        result[entry["repo"]] = projected
    return result


def _validate_fingerprint_list(value: Any, source: str) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) != 1
        or not isinstance(value[0], str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", value[0])
    ):
        raise ControlPlaneError(f"{source} must be a one-item complete sha256 list")
    return value


def _configured_fingerprint_pair(
    controller: dict[str, Any],
    target: dict[str, Any],
) -> dict[str, list[str]]:
    repository_id = target.get("repository_id")
    if (
        not isinstance(repository_id, int)
        or isinstance(repository_id, bool)
        or repository_id < 1
        or not isinstance(target.get("repo"), str)
    ):
        raise ControlPlaneError("fingerprints require a resolved enrolled fleet target")
    fingerprints = controller.get("ruleset_fingerprints")
    if not isinstance(fingerprints, dict):
        raise ControlPlaneError("controller ruleset_fingerprints must be an object")
    base = {
        "runtime_app_visible": _validate_fingerprint_list(
            fingerprints.get("runtime_app_visible"),
            "controller runtime_app_visible",
        ),
        "operator_full": _validate_fingerprint_list(
            fingerprints.get("operator_full"),
            "controller operator_full",
        ),
    }
    overrides = fingerprints.get("repository_overrides")
    if not isinstance(overrides, dict):
        raise ControlPlaneError("controller repository_overrides must be an object")
    for key, pair in overrides.items():
        if not isinstance(key, str) or not re.fullmatch(r"[1-9][0-9]*", key):
            raise ControlPlaneError("controller repository_overrides keys must be repository IDs")
        if not isinstance(pair, dict) or set(pair) != {
            "runtime_app_visible",
            "operator_full",
        }:
            raise ControlPlaneError(
                f"controller repository_overrides[{key}] must be a closed fingerprint pair"
            )
        _validate_fingerprint_list(
            pair["runtime_app_visible"],
            f"controller repository_overrides[{key}].runtime_app_visible",
        )
        _validate_fingerprint_list(
            pair["operator_full"],
            f"controller repository_overrides[{key}].operator_full",
        )
    return copy.deepcopy(overrides.get(str(repository_id), base))


def resolve_repository_projection(
    assignments: dict[str, Any],
    fleet: dict[str, Any],
    controller: dict[str, Any],
    *,
    repository_id: int,
    repo: str,
    default_branch: str,
    enforce_fingerprint_pins: bool = True,
) -> RepositoryProjection:
    """Resolve assignment, ruleset, and both independently-derived fingerprint layers once."""
    _validate_assignments_or_raise(assignments, fleet)
    target = resolve_fleet_target(fleet, repository_id=repository_id, repo=repo)
    if default_branch != target["default_branch"]:
        raise ControlPlaneError(
            f"{repo} default branch {default_branch!r} differs from fleet authority "
            f"{target['default_branch']!r}"
        )
    assignment = copy.deepcopy(_assignment_map(assignments).get(repo))
    ruleset = _render_base_ruleset(default_branch)
    checks = copy.deepcopy(_required_status_checks(ruleset))
    required = assignment.get("required_checks") if assignment else None
    if required is not None:
        verifier_id = (controller.get("verifier") or {}).get("integration_id")
        if verifier_id != 4274739:
            raise ControlPlaneError(
                "required-check projection requires verifier integration_id 4274739"
            )
        checks.append(
            {
                "context": f"pr-automation / job:{required['job_id']}",
                "integration_id": verifier_id,
            }
        )
    _required_status_checks(ruleset)[:] = checks
    pair = ruleset_fingerprint_pair(ruleset)
    configured = _configured_fingerprint_pair(controller, target)
    if enforce_fingerprint_pins and pair != configured:
        override = (controller["ruleset_fingerprints"]["repository_overrides"]).get(
            str(repository_id)
        )
        scope = "repository override" if override is not None else "fleet fingerprint"
        raise ControlPlaneError(
            f"{repo} assignment/ruleset fingerprint disagrees with its {scope}"
        )
    return RepositoryProjection(
        repository_id=repository_id,
        repo=repo,
        assignment=assignment,
        ruleset=ruleset,
        required_status_checks=checks,
        runtime_app_visible_fingerprints=pair["runtime_app_visible"],
        operator_full_fingerprints=pair["operator_full"],
    )


def _decode_live_config(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControlPlaneError(f"live config is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ControlPlaneError("live config root must be an object")
    return value


def _render_like_source(value: dict[str, Any], source: bytes) -> bytes:
    trailing_newline = b"\n" if source.endswith(b"\n") else b""
    return json.dumps(value, indent=2, ensure_ascii=False).encode() + trailing_newline


def project_live_config(
    live_raw: bytes,
    assignments: dict[str, Any],
    fleet: dict[str, Any],
    controller: dict[str, Any],
) -> LiveProjection:
    """Project the sole assignment SOT into LiveRepositoryConfig without mutating either source."""
    _validate_assignments_or_raise(assignments, fleet)
    live = _decode_live_config(live_raw)
    generation = controller.get("release", {}).get("activation_generation")
    if not isinstance(generation, int) or generation < 1:
        raise ControlPlaneError("controller release activation_generation must be positive")
    if live.get("activation_generation") != generation:
        raise ControlPlaneError("live config activation_generation differs from controller.json")

    repositories = live.get("repositories")
    if not isinstance(repositories, list):
        raise ControlPlaneError("live config repositories must be a list")
    by_repo = _assignment_map(assignments)
    fleet_repos = set(_fleet_repos(fleet))
    seen_live: set[str] = set()
    seen_live_ids: set[int] = set()
    changed = False
    for repository in repositories:
        if not isinstance(repository, dict):
            raise ControlPlaneError("live repository entry must be an object")
        owner = repository.get("owner")
        name = repository.get("name")
        if not isinstance(owner, str) or not isinstance(name, str):
            raise ControlPlaneError("live repository owner/name must be strings")
        repo = f"{owner}/{name}"
        repository_id = repository.get("id")
        if not isinstance(repository_id, int) or repository_id < 1:
            raise ControlPlaneError(f"live repository {repo} has no positive immutable id")
        default_branch = repository.get("default_branch")
        if not isinstance(default_branch, str) or not default_branch:
            raise ControlPlaneError(f"live repository {repo} has no default branch")
        if repo in seen_live:
            raise ControlPlaneError(f"live config has duplicate repository {repo}")
        if repository_id in seen_live_ids:
            raise ControlPlaneError(f"live config has duplicate repository id {repository_id}")
        seen_live.add(repo)
        seen_live_ids.add(repository_id)
        desired_projection = resolve_repository_projection(
            assignments,
            fleet,
            controller,
            repository_id=repository_id,
            repo=repo,
            default_branch=default_branch,
        )
        desired_assignment = desired_projection.assignment
        desired_fingerprints = desired_projection.runtime_app_visible_fingerprints
        current_assignment = repository.get("coverage_assignment")
        current_fingerprints = repository.get("expected_ruleset_fingerprints")
        if (
            current_assignment != desired_assignment
            or current_fingerprints != desired_fingerprints
        ):
            repository["coverage_assignment"] = copy.deepcopy(desired_assignment)
            repository["expected_ruleset_fingerprints"] = copy.deepcopy(
                desired_fingerprints
            )
            changed = True

    missing = sorted(fleet_repos - seen_live)
    extra = sorted(seen_live - fleet_repos)
    if missing:
        raise ControlPlaneError(f"enrolled fleet repositories missing from live config: {missing}")
    if extra:
        raise ControlPlaneError(f"unenrolled repositories present in live config: {extra}")
    hard = set(_hard_exclusions(controller))
    if hard & set(by_repo):
        raise ControlPlaneError(f"hard exclusion cannot be assigned: {sorted(hard & set(by_repo))}")

    if not changed:
        return LiveProjection(live_raw, False, "")
    candidate = _render_like_source(live, live_raw)
    before = live_raw.decode("utf-8", errors="replace").splitlines(keepends=True)
    after = candidate.decode("utf-8", errors="replace").splitlines(keepends=True)
    diff = "".join(
        difflib.unified_diff(
            before,
            after,
            fromfile="live-config.observed.json",
            tofile="live-config.projected.json",
        )
    )
    return LiveProjection(candidate, True, diff)


def rehearse_live_projection(
    live_path: Path,
    assignments: dict[str, Any],
    fleet: dict[str, Any],
    controller: dict[str, Any],
) -> LiveProjection:
    """A1/A2 rehearsal: exact match passes; any mismatch stops with a diff and writes nothing."""
    raw = live_path.read_bytes()
    projection = project_live_config(raw, assignments, fleet, controller)
    if projection.changed:
        raise CoverageDrift(f"coverage projection differs from live state:\n{projection.diff}")
    return projection


def view_coverage(
    live_raw: bytes,
    assignments: dict[str, Any],
    fleet: dict[str, Any],
    controller: dict[str, Any],
) -> dict[str, Any]:
    projection = project_live_config(live_raw, assignments, fleet, controller)
    live = _decode_live_config(live_raw)
    return {
        "schema": "pr-automation-coverage-view/v1",
        "parity": not projection.changed,
        "assignments": copy.deepcopy(assignments["assignments"]),
        "live_assignments": [
            {
                "repo": f"{repository['owner']}/{repository['name']}",
                "coverage_assignment": copy.deepcopy(repository.get("coverage_assignment")),
            }
            for repository in live["repositories"]
            if repository.get("coverage_assignment") is not None
        ],
        "hard_exclusions": [
            {"repo": repo, "promotable": False} for repo in _hard_exclusions(controller)
        ],
        "diff": projection.diff,
    }


def _validate_mode_transition(current_mode: str | None, desired_mode: str) -> None:
    """Promotions advance one observed stage; safer demotions may move directly downward."""
    if desired_mode not in COVERAGE_MODE_RANK:
        raise ControlPlaneError(f"unknown desired coverage mode {desired_mode!r}")
    if current_mode is not None and current_mode not in COVERAGE_MODE_RANK:
        raise ControlPlaneError(f"unknown current coverage mode {current_mode!r}")
    current_rank = -1 if current_mode is None else COVERAGE_MODE_RANK[current_mode]
    desired_rank = COVERAGE_MODE_RANK[desired_mode]
    if desired_rank > current_rank + 1:
        current_label = current_mode or "unassigned"
        raise ControlPlaneError(
            f"coverage promotion cannot skip observation stages: {current_label} -> {desired_mode}"
        )


def propose_assignment(
    assignments: dict[str, Any],
    fleet: dict[str, Any],
    controller: dict[str, Any],
    *,
    repo: str,
    coverage_mode: str,
    profile_id: str,
    profile_digest: str,
    artifacts_validated: bool,
) -> dict[str, Any]:
    """Return a proposed new SOT value; never write it."""
    if repo in _hard_exclusions(controller):
        raise ControlPlaneError(f"{repo} is a hard exclusion and cannot be assigned or activated")
    if repo not in _fleet_repos(fleet):
        raise ControlPlaneError(f"{repo} is not a fleet target")
    if coverage_mode not in COVERAGE_MODES:
        raise ControlPlaneError(f"coverage_mode must be one of {sorted(COVERAGE_MODES)}")
    if not artifacts_validated:
        raise ControlPlaneError(
            "a validated recipe/lock is required before an assignment can be produced"
        )
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", profile_id):
        raise ControlPlaneError("profile_id is not a valid catalog atom")
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", profile_digest):
        raise ControlPlaneError("profile_digest is malformed")

    current = next(
        (entry for entry in assignments.get("assignments", []) if entry.get("repo") == repo),
        None,
    )
    _validate_mode_transition(
        current.get("coverage_mode") if isinstance(current, dict) else None,
        coverage_mode,
    )
    proposed = copy.deepcopy(assignments)
    proposed_entries = [
        entry for entry in proposed.get("assignments", []) if entry.get("repo") != repo
    ]
    proposed_entry = {
        "repo": repo,
        "coverage_mode": coverage_mode,
        "catalog_repository_id": repo.rsplit("/", 1)[-1],
        "profile_ref": {"id": profile_id, "digest": profile_digest},
    }
    if isinstance(current, dict) and current.get("required_checks") is not None:
        proposed_entry["required_checks"] = copy.deepcopy(current["required_checks"])
    proposed_entries.append(proposed_entry)
    proposed["assignments"] = sorted(proposed_entries, key=lambda item: item["repo"])
    _validate_assignments_or_raise(proposed, fleet)
    return proposed


def rollout_phase(
    recipe_merged: bool,
    lock_merged: bool,
    assigned_mode: str | None,
    desired_mode: str,
    *,
    lock_current: bool,
) -> str:
    if not recipe_merged:
        return "recipe"
    if not lock_merged:
        return "lock"
    if assigned_mode is None:
        return "assignment"
    if not lock_current:
        return "relock"
    if assigned_mode != desired_mode:
        _validate_mode_transition(assigned_mode, desired_mode)
        return "mode"
    return "current"


def build_repository_recipe(
    repo: str,
    *,
    custom_argv: list[str] | None,
) -> dict[str, Any]:
    short = repo.rsplit("/", 1)[-1]
    canned_id = "canned.repository-contract.v1"
    custom_id = f"repo.{short}.m3-verify"
    jobs = [{"id": canned_id, "depends_on": []}]
    custom_jobs: list[dict[str, Any]] = []
    if custom_argv:
        custom_jobs.append(
            {
                "id": custom_id,
                "argv": ["run-literal", *custom_argv],
                "environment": {},
                "depends_on": [canned_id],
            }
        )
        jobs.append({"id": custom_id, "depends_on": [canned_id]})
    return {
        "schema": "pr-automation-recipe/v1",
        "repository_id": short,
        "canned_refs": [{"id": canned_id, "digest": CANNED_REPOSITORY_CONTRACT_DIGEST}],
        "custom_jobs": custom_jobs,
        "pipeline": {
            "version": "pr-automation-pipeline/v1",
            "pipeline_id": f"{short}-m3-pipeline",
            "jobs": jobs,
            "aggregate": "all_required",
        },
    }


def render_phase_diff(phase: str, before: bytes | None, after: bytes) -> str:
    path = {
        "recipe": RECIPE,
        "lock": LOCK,
        "relock": LOCK,
        "assignment": "coverage-assignments.json",
        "mode": "coverage-assignments.json",
    }.get(phase)
    if path is None:
        raise ControlPlaneError(f"unsupported rollout phase: {phase}")
    return "".join(
        difflib.unified_diff(
            (before or b"").decode("utf-8").splitlines(keepends=True),
            after.decode("utf-8").splitlines(keepends=True),
            fromfile=f"a/{path}" if before is not None else "/dev/null",
            tofile=f"b/{path}",
        )
    )


def build_sync_plan(repo: str, *, phase: str, operation_id: str) -> dict[str, Any]:
    """One owner-gated operation stages exactly one durable authority change."""
    short = repo.rsplit("/", 1)[-1]
    if phase in {"recipe", "lock", "relock"}:
        repository = repo
        files = [RECIPE if phase == "recipe" else LOCK]
    elif phase == "assignment":
        repository = "KleinPerkins/dev"
        files = ["_ops/baseline/profiles/pr-automation/v3/coverage-assignments.json"]
    else:
        raise ControlPlaneError(f"sync phase must be recipe, lock, relock, or assignment: {phase}")
    return {
        "schema": "pr-automation-coverage-sync-plan/v1",
        "operation_id": operation_id,
        "phase": phase,
        "pull_requests": [
            {
                "repository": repository,
                "operation_id": operation_id,
                "title": f"chore(checks): sync {phase} for {short} [{operation_id}]",
                "files": files,
            },
        ],
    }


def build_activation_plan(repo: str, *, phase: str, operation_id: str) -> dict[str, Any]:
    if phase not in {"stage", "transcribe", "stage-requiredness", "finalize-requiredness"}:
        raise ControlPlaneError(
            "activate phase must be stage, transcribe, stage-requiredness, or finalize-requiredness"
        )
    return {
        "schema": "pr-automation-coverage-activation-plan/v1",
        "repo": repo,
        "phase": phase,
        "operation_id": operation_id,
        "files": (
            ["_ops/baseline/profiles/pr-automation/v3/coverage-assignments.json"]
            if phase in {"stage", "stage-requiredness"}
            else []
        ),
    }


def assert_phase_change_set(phase: str, changed: set[str]) -> None:
    expected = {
        "recipe": {RECIPE},
        "lock": {LOCK},
        "relock": {LOCK},
        "assignment": {
            "_ops/baseline/profiles/pr-automation/v3/coverage-assignments.json"
        },
        "stage": {
            "_ops/baseline/profiles/pr-automation/v3/coverage-assignments.json"
        },
    }.get(phase)
    if changed != expected:
        raise ControlPlaneError(
            f"{phase} phase must change exactly {sorted(expected or [])}; got {sorted(changed)}"
        )


def claim_operation(root: Path, operation_id: str, kind: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", operation_id):
        raise ControlPlaneError("operation_id must be a safe 1..80-character token")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    path = root / f"{operation_id}.json"
    receipt = {
        "schema": "pr-automation-coverage-operation/v1",
        "operation_id": operation_id,
        "kind": kind,
        "status": "claimed",
    }
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ControlPlaneError(f"operation_id already used: {operation_id}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(encoded(receipt))
        handle.flush()
        os.fsync(handle.fileno())
    return receipt


def _read_operation_receipt(root: Path, operation_id: str) -> dict[str, Any]:
    path = root / f"{operation_id}.json"
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlPlaneError(f"operation receipt is missing or invalid: {operation_id}") from exc
    if not isinstance(receipt, dict):
        raise ControlPlaneError(f"operation receipt is invalid: {operation_id}")
    return receipt


def _write_operation_receipt(root: Path, operation_id: str, receipt: dict[str, Any]) -> None:
    atomic_write_bytes(root / f"{operation_id}.json", encoded(receipt).encode(), 0o600)


def complete_operation(root: Path, operation_id: str) -> None:
    receipt = _read_operation_receipt(root, operation_id)
    receipt["status"] = "completed"
    _write_operation_receipt(root, operation_id, receipt)


def mark_operation_staged(
    root: Path,
    operation_id: str,
    *,
    candidate_digest: str,
    rollback_config: str,
    recovery_operation_id: str,
    status_snapshot: dict[str, Any],
) -> None:
    receipt = _read_operation_receipt(root, operation_id)
    if receipt.get("status") not in {"claimed", "stage_written", "staged"}:
        raise ControlPlaneError(
            f"operation {operation_id} cannot be marked staged from {receipt.get('status')!r}"
        )
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", candidate_digest):
        raise ControlPlaneError("candidate_digest must be a complete sha256 digest")
    receipt.update(
        {
            "status": "staged",
            "candidate_digest": candidate_digest,
            "rollback_config": rollback_config,
            "recovery_operation_id": recovery_operation_id,
            "staged_status": copy.deepcopy(status_snapshot),
        }
    )
    _write_operation_receipt(root, operation_id, receipt)


def mark_operation_stage_written(
    root: Path,
    operation_id: str,
    *,
    candidate_digest: str,
    rollback_config: str,
    recovery_operation_id: str,
    status_snapshot: dict[str, Any],
) -> None:
    receipt = _read_operation_receipt(root, operation_id)
    if receipt.get("status") != "claimed":
        raise ControlPlaneError(
            f"operation {operation_id} cannot be marked stage_written from {receipt.get('status')!r}"
        )
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", candidate_digest):
        raise ControlPlaneError("candidate_digest must be a complete sha256 digest")
    receipt.update(
        {
            "status": "stage_written",
            "candidate_digest": candidate_digest,
            "rollback_config": rollback_config,
            "recovery_operation_id": recovery_operation_id,
            "stage_written_status": copy.deepcopy(status_snapshot),
        }
    )
    _write_operation_receipt(root, operation_id, receipt)


def mark_operation_restored(
    root: Path,
    operation_id: str,
    *,
    reason: str,
    status_snapshot: dict[str, Any],
) -> None:
    receipt = _read_operation_receipt(root, operation_id)
    if receipt.get("status") not in {"claimed", "stage_written", "staged"}:
        raise ControlPlaneError(
            f"operation {operation_id} cannot be marked restored from {receipt.get('status')!r}"
        )
    receipt.update(
        {
            "status": "restored",
            "restore_reason": reason,
            "restore_status": copy.deepcopy(status_snapshot),
        }
    )
    _write_operation_receipt(root, operation_id, receipt)


def mark_operation_restore_failed(
    root: Path,
    operation_id: str,
    *,
    reason: str,
    restore_error: str,
) -> None:
    receipt = _read_operation_receipt(root, operation_id)
    if receipt.get("status") not in {"claimed", "stage_written", "staged"}:
        raise ControlPlaneError(
            f"operation {operation_id} cannot be marked restore_failed from {receipt.get('status')!r}"
        )
    receipt.update(
        {
            "status": "restore_failed",
            "restore_reason": reason,
            "restore_error": restore_error,
        }
    )
    _write_operation_receipt(root, operation_id, receipt)


def _assert_requiredness_staged_status(status: dict[str, Any]) -> None:
    if status.get("paused") is not True or status.get("drain") is not True:
        raise ControlPlaneError("requiredness staging must leave controller paused and drained")
    floor = status.get("operator_floor") or {}
    queue = floor.get("queue_depth") or {}
    if (
        queue.get("in_flight_attempts", 0) != 0
        or queue.get("owed_runs", 0) != 0
        or status.get("recovery_candidates", 0) != 0
    ):
        raise ControlPlaneError("requiredness staging must leave controller idle and debt-free")


def _assert_requiredness_completed_status(status: dict[str, Any]) -> None:
    if status.get("paused") is not False:
        raise ControlPlaneError("requiredness completion requires an unpaused healthy controller")
    if status.get("drain") is not False:
        raise ControlPlaneError("requiredness completion requires an undrained healthy controller")
    floor = status.get("operator_floor") or {}
    driver = floor.get("driver") or {}
    if driver.get("healthy") is not True or driver.get("state") != "running":
        raise ControlPlaneError("requiredness completion requires a healthy running driver")
    queue = floor.get("queue_depth") or {}
    if (
        queue.get("in_flight_attempts", 0) != 0
        or queue.get("owed_runs", 0) != 0
        or status.get("recovery_candidates", 0) != 0
    ):
        raise ControlPlaneError("requiredness completion requires an idle debt-free controller")


def complete_requiredness_operation(
    root: Path,
    operation_id: str,
    status: dict[str, Any],
) -> None:
    receipt = _read_operation_receipt(root, operation_id)
    if receipt.get("status") not in {"claimed", "staged"}:
        raise ControlPlaneError("requiredness operation must be claimed or staged before completion")
    _assert_requiredness_completed_status(status)
    complete_operation(root, operation_id)


def validate_qualified_release(
    manifest_path: Path,
    controller: dict[str, Any],
) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ControlPlaneError(f"qualified release manifest missing or unreadable: {manifest_path}") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != "pr-automation-qualified-release/v1"
        or manifest.get("lifecycle_state") != "qualified"
    ):
        raise ControlPlaneError("qualified release manifest is not in qualified lifecycle state")
    release = controller.get("release", {})
    if manifest.get("version") != str(release.get("version", "")).removeprefix("v"):
        raise ControlPlaneError("qualified release version does not match controller.json")
    records = {
        item.get("name"): item
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict)
    }
    expected = {
        "pr-automation-controller": release.get("digest"),
        "lock-compiler": release.get("lock_compiler_digest"),
    }
    if set(records) != set(expected):
        raise ControlPlaneError("qualified release must contain exactly controller and lock-compiler")
    for name, expected_digest in expected.items():
        artifact = manifest_path.parent / name
        record = records[name]
        if not artifact.is_file():
            raise ControlPlaneError(f"qualified release artifact missing: {artifact}")
        value = artifact.read_bytes()
        if len(value) != record.get("size"):
            raise ControlPlaneError(f"qualified release artifact size mismatch: {name}")
        actual = _sha256_bytes(value)
        if actual != record.get("sha256") or actual != expected_digest:
            raise ControlPlaneError(f"qualified release artifact digest mismatch: {name}")
    return {
        "lifecycle_state": "qualified",
        "manifest": str(manifest_path),
        "version": manifest["version"],
    }


def plan_assignment(
    live_raw: bytes,
    assignments: dict[str, Any],
    fleet: dict[str, Any],
    controller: dict[str, Any],
    **proposal: Any,
) -> dict[str, Any]:
    proposed = propose_assignment(assignments, fleet, controller, **proposal)
    projection = project_live_config(live_raw, proposed, fleet, controller)
    before = encoded(assignments).splitlines(keepends=True)
    after = encoded(proposed).splitlines(keepends=True)
    assignment_diff = "".join(
        difflib.unified_diff(
            before,
            after,
            fromfile="coverage-assignments.json",
            tofile="coverage-assignments.proposed.json",
        )
    )
    return {
        "schema": "pr-automation-coverage-plan/v1",
        "assignment_diff": assignment_diff,
        "live_config_diff": projection.diff,
        "proposed_assignments": proposed,
    }


def doctor_coverage(
    live_raw: bytes,
    assignments: dict[str, Any],
    fleet: dict[str, Any],
    controller: dict[str, Any],
    *,
    remote_controls: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    projection = project_live_config(live_raw, assignments, fleet, controller)
    if projection.changed:
        raise CoverageDrift(f"coverage projection differs from live state:\n{projection.diff}")
    result = {
        "schema": "pr-automation-coverage-doctor/v1",
        "control_plane": "valid",
        "live_parity": "exact",
        "activation_generation": controller["release"]["activation_generation"],
        "assigned": len(assignments["assignments"]),
        "fleet": len(_fleet_repos(fleet)),
    }
    if remote_controls is not None:
        result["repository_controls"] = verify_repository_controls(
            assignments,
            fleet,
            controller,
            remote_controls,
        )
    return result


def build_activation_package(
    live_raw: bytes,
    assignments: dict[str, Any],
    fleet: dict[str, Any],
    controller: dict[str, Any],
    *,
    repo: str,
) -> ActivationPackage:
    projection = project_live_config(live_raw, assignments, fleet, controller)
    generation = controller["release"]["activation_generation"]
    live = _decode_live_config(live_raw)
    candidate_config = _decode_live_config(projection.candidate)
    current_by_repo = {
        f"{repository['owner']}/{repository['name']}": {
            "coverage_assignment": repository.get("coverage_assignment"),
            "expected_ruleset_fingerprints": repository.get(
                "expected_ruleset_fingerprints"
            ),
        }
        for repository in live["repositories"]
    }
    desired_by_repo = {
        f"{repository['owner']}/{repository['name']}": {
            "coverage_assignment": repository.get("coverage_assignment"),
            "expected_ruleset_fingerprints": repository.get(
                "expected_ruleset_fingerprints"
            ),
        }
        for repository in candidate_config["repositories"]
    }
    changed = sorted(
        candidate
        for candidate in set(current_by_repo) | set(desired_by_repo)
        if current_by_repo.get(candidate) != desired_by_repo.get(candidate)
    )
    if changed and changed != [repo]:
        raise ControlPlaneError(
            f"activate may transcribe exactly one requested repository; changed={changed}"
        )
    desired_state = desired_by_repo.get(repo)
    if desired_state is None or desired_state["coverage_assignment"] is None:
        raise ControlPlaneError(f"{repo} has no desired coverage assignment")
    desired = desired_state["coverage_assignment"]
    current_state = current_by_repo.get(repo)
    current = (
        current_state.get("coverage_assignment")
        if isinstance(current_state, dict)
        else None
    )
    _validate_mode_transition(
        current.get("coverage_mode") if isinstance(current, dict) else None,
        desired["coverage_mode"],
    )
    if candidate_config.get("activation_generation") != generation:
        raise ControlPlaneError("activation candidate changed activation_generation")
    return ActivationPackage(projection.candidate, live_raw, generation)


def rollback_command(controller_binary: str) -> list[str]:
    """Bind only to Commands::RollBack, never DirectOperation::RollBackController."""
    return [controller_binary, "roll-back", "--json"]


def validate_rollback_receipt(
    before_status: dict[str, Any],
    receipt: dict[str, Any],
    after_status: dict[str, Any],
) -> None:
    generation = before_status.get("activation_generation")
    if (
        receipt.get("activation_generation") != generation
        or after_status.get("activation_generation") != generation
    ):
        raise ControlPlaneError("rollback activation generation changed")
    if not (
        isinstance(receipt.get("prior_supersede_generation"), int)
        and isinstance(receipt.get("new_supersede_generation"), int)
        and receipt["new_supersede_generation"] > receipt["prior_supersede_generation"]
    ):
        raise ControlPlaneError("rollback supersede generation did not advance monotonically")
    if receipt.get("coverage_mode") != "manual_only" or not receipt.get("resumed"):
        raise ControlPlaneError("rollback did not land resumed at manual_only")
    if after_status.get("coverage_mode") != "manual_only":
        raise ControlPlaneError("post-rollback status is not manual_only")


def _run_checked(
    command: list[str],
    *,
    cwd: Path | None = None,
    input_bytes: bytes | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            input=input_bytes,
            capture_output=True,
            env=env,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ControlPlaneError(f"command could not run: {command[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ControlPlaneError(f"{command[0]} failed: {detail or 'no diagnostic'}")
    return result


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _git_blob_sha(value: bytes) -> str:
    header = f"blob {len(value)}\0".encode()
    return hashlib.sha1(header + value, usedforsecurity=False).hexdigest()


def _json_bytes(value: bytes, source: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControlPlaneError(f"{source} is not valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ControlPlaneError(f"{source} root must be an object")
    return decoded


def lock_metadata_errors(
    lock: dict[str, Any],
    controller: dict[str, Any],
    *,
    repo: str,
    profile_id: str,
    profile_digest: str,
) -> list[str]:
    """Return deterministic v2/epoch/direct-authority mismatches before Rust recompilation."""
    errors: list[str] = []
    release = controller.get("release", {})
    configured_epoch = release.get("lock_contract_version")
    if configured_epoch != LOCK_CONTRACT_VERSION:
        errors.append(
            "controller lock_contract_version differs from the supported epoch "
            f"{LOCK_CONTRACT_VERSION}: {configured_epoch!r}"
        )
    if lock.get("schema_version") != LOCK_SCHEMA:
        errors.append(
            f"schema_version must be {LOCK_SCHEMA!r}, got {lock.get('schema_version')!r}"
        )
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", str(lock.get("lock_digest", ""))):
        errors.append("lock_digest is malformed")
    payload = lock.get("payload")
    if not isinstance(payload, dict):
        return [*errors, "payload must be an object"]
    if "controller_release" in payload:
        errors.append("payload.controller_release is forbidden by the v2 lock contract")

    expected_image = expected_profile_image(controller, profile_id)
    expected = {
        "repository_id": repo.rsplit("/", 1)[-1],
        "activation_generation": release.get("activation_generation"),
        "lock_contract_version": configured_epoch,
        "catalog_id": LOCK_CATALOG_ID,
        "profile_id": profile_id,
        "profile_digest": profile_digest,
        "image_digest": expected_image,
    }
    for field, expected_value in expected.items():
        if payload.get(field) != expected_value:
            errors.append(
                f"{field} does not match current authority: "
                f"{payload.get(field)!r} != {expected_value!r}"
            )
    for field in ("catalog_digest", "profile_digest", "recipe_digest", "assignment_digest"):
        if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", str(payload.get(field, ""))):
            errors.append(f"{field} is malformed")
    if not re.fullmatch(
        r"[^\s]+@sha256:[0-9a-fA-F]{64}",
        str(payload.get("image_digest", "")),
    ):
        errors.append("image_digest is malformed")
    return errors


def expected_profile_image(controller: dict[str, Any], profile_id: str) -> Any:
    images = controller.get("images", {})
    if not isinstance(images, dict):
        return None
    overrides = images.get("profile_overrides", {})
    if not isinstance(overrides, dict):
        return images.get("execution")
    return overrides.get(profile_id, images.get("execution"))


def lock_is_current(
    lock_bytes: bytes,
    controller: dict[str, Any],
    *,
    repo: str,
    profile_id: str,
    profile_digest: str,
    artifact_validation: Callable[[], dict[str, Any]] | None,
) -> bool:
    """Require v2 metadata plus lock-bound Rust validation evidence; legacy/stale metadata is false."""
    lock = _json_bytes(lock_bytes, LOCK)
    if lock_metadata_errors(
        lock,
        controller,
        repo=repo,
        profile_id=profile_id,
        profile_digest=profile_digest,
    ):
        return False
    if artifact_validation is None:
        raise ControlPlaneError(
            "current lock classification requires exact Rust validator/recompile evidence"
        )
    proof = artifact_validation()
    payload = lock["payload"]
    expected_covered = {
        field: payload.get(field) for field in LOCK_COVERED_DIGEST_FIELDS
    }
    if (
        not isinstance(proof, dict)
        or proof.get("validated") is not True
        or proof.get("schema_version") != LOCK_SCHEMA
        or proof.get("lock_contract_version") != LOCK_CONTRACT_VERSION
        or proof.get("covered_digests") != expected_covered
    ):
        raise ControlPlaneError(
            "Rust validator/recompile evidence does not bind the exact v2 lock covered inputs"
        )
    return True


def _assert_compiler(
    compiler: Path,
    controller: dict[str, Any],
) -> None:
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        raise ControlPlaneError(f"lock-compiler is not an executable file: {compiler}")
    actual = _sha256_bytes(compiler.read_bytes())
    expected = controller.get("release", {}).get("lock_compiler_digest")
    if actual != expected:
        raise ControlPlaneError(
            f"lock-compiler digest mismatch: got {actual}, expected qualified {expected}"
        )


def validate_artifact_bytes(
    recipe_bytes: bytes,
    lock_bytes: bytes,
    compiler: Path,
    controller: dict[str, Any],
    *,
    repo: str,
    profile_id: str,
    profile_digest: str,
) -> dict[str, Any]:
    """Run the release-qualified Rust validator; Python cross-checks direct central authority."""
    _assert_compiler(compiler, controller)
    lock = _json_bytes(lock_bytes, LOCK)
    metadata_errors = lock_metadata_errors(
        lock,
        controller,
        repo=repo,
        profile_id=profile_id,
        profile_digest=profile_digest,
    )
    if metadata_errors:
        raise ControlPlaneError("lock currency metadata mismatch: " + "; ".join(metadata_errors))
    payload = lock.get("payload")
    assert isinstance(payload, dict)
    expected_repository_id = repo.rsplit("/", 1)[-1]
    expected_generation = controller.get("release", {}).get("activation_generation")
    recipe_base_sha = payload.get("recipe_base_sha")
    recipe_blob_sha = payload.get("recipe_blob_sha")
    if not isinstance(recipe_base_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", recipe_base_sha):
        raise ControlPlaneError("lock recipe_base_sha is malformed")
    if not isinstance(recipe_blob_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", recipe_blob_sha):
        raise ControlPlaneError("lock recipe_blob_sha is malformed")
    if _git_blob_sha(recipe_bytes) != recipe_blob_sha:
        raise ControlPlaneError("recipe bytes do not match the lock's pinned recipe_blob_sha")

    with tempfile.TemporaryDirectory(prefix="pr-automation-lock-validate-") as temporary:
        root = Path(temporary)
        recipe = root / "recipe.json"
        lock_path = root / "lock.json"
        recipe.write_bytes(recipe_bytes)
        lock_path.write_bytes(lock_bytes)
        result = _run_checked(
            [
                str(compiler),
                "validate",
                "--recipe",
                str(recipe),
                "--repository-id",
                expected_repository_id,
                "--activation-generation",
                str(expected_generation),
                "--profile-id",
                profile_id,
                "--recipe-base-sha",
                recipe_base_sha,
                "--recipe-blob-sha",
                recipe_blob_sha,
                "--lock",
                str(lock_path),
            ]
        )
    return {
        "validated": True,
        "schema_version": lock["schema_version"],
        "lock_contract_version": payload["lock_contract_version"],
        "lock_digest": lock.get("lock_digest"),
        "covered_digests": {
            field: payload[field] for field in LOCK_COVERED_DIGEST_FIELDS
        },
        "compiler_digest": controller["release"]["lock_compiler_digest"],
        "validator": result.stdout.decode("utf-8", errors="replace").strip(),
    }


def _git(root: Path, *arguments: str) -> str:
    return (
        _run_checked(["git", "-C", str(root), *arguments])
        .stdout.decode("utf-8", errors="strict")
        .strip()
    )


def _parse_porcelain_paths(output: bytes) -> set[str]:
    paths: set[str] = set()
    for entry in output.split(b"\0"):
        if not entry:
            continue
        if len(entry) < 4 or entry[2:3] != b" ":
            raise ControlPlaneError("git status returned malformed porcelain-v1 output")
        status = entry[:2].decode("ascii", errors="strict")
        if "R" in status or "C" in status:
            raise ControlPlaneError("git status rename/copy entries are not valid phase changes")
        paths.add(entry[3:].decode("utf-8", errors="strict"))
    return paths


def _git_changed_paths(root: Path) -> set[str]:
    result = _run_checked(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z"]
    )
    return _parse_porcelain_paths(result.stdout)


def _git_file_at(root: Path, ref: str, path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{path}"],
        capture_output=True,
    )
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 128:
        return None
    detail = result.stderr.decode("utf-8", errors="replace").strip()
    raise ControlPlaneError(f"git could not read {ref}:{path}: {detail}")


def _assert_staging_worktree(root: Path, repo: str, default_branch: str) -> None:
    _ensure_linked_worktree(root, default_branch)
    _assert_origin(root, repo)
    if _git(root, "status", "--porcelain"):
        raise ControlPlaneError(f"{repo} staging worktree must start clean")
    origin_ref = f"origin/{default_branch}"
    changes = set(
        filter(None, _git(root, "diff", "--name-only", f"{origin_ref}...HEAD").splitlines())
    )
    if changes:
        raise ControlPlaneError(
            f"{repo} staging branch must start at {origin_ref}; got {sorted(changes)}"
        )


def _require_current_recipe_binding(
    recipe_bytes: bytes,
    recipe_blob_sha: str,
    payload: dict[str, Any],
    *,
    source: str,
) -> None:
    pinned_blob = payload.get("recipe_blob_sha")
    observed_blob = _git_blob_sha(recipe_bytes)
    if (
        not isinstance(pinned_blob, str)
        or recipe_blob_sha != pinned_blob
        or observed_blob != pinned_blob
    ):
        raise ControlPlaneError(
            f"{source} current recipe does not match the lock's pinned recipe_blob_sha"
        )


def validate_repository_artifacts(
    root: Path,
    compiler: Path,
    controller: dict[str, Any],
    *,
    repo: str,
    profile_id: str,
    profile_digest: str,
) -> dict[str, Any]:
    lock_bytes = (root / LOCK).read_bytes()
    lock = _json_bytes(lock_bytes, str(root / LOCK))
    payload = lock.get("payload", {})
    base = payload.get("recipe_base_sha")
    if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}", base):
        raise ControlPlaneError("lock recipe_base_sha is malformed")
    current_recipe_bytes = _run_checked(
        ["git", "-C", str(root), "show", f"HEAD:{RECIPE}"]
    ).stdout
    current_recipe_blob = _git(root, "rev-parse", f"HEAD:{RECIPE}")
    _require_current_recipe_binding(
        current_recipe_bytes,
        current_recipe_blob,
        payload,
        source=str(root),
    )
    recipe_bytes = _run_checked(
        ["git", "-C", str(root), "show", f"{base}:{RECIPE}"]
    ).stdout
    observed_blob = _git(root, "rev-parse", f"{base}:{RECIPE}")
    if observed_blob != payload.get("recipe_blob_sha"):
        raise ControlPlaneError("git recipe blob differs from the lock's pinned recipe_blob_sha")
    return validate_artifact_bytes(
        recipe_bytes,
        lock_bytes,
        compiler,
        controller,
        repo=repo,
        profile_id=profile_id,
        profile_digest=profile_digest,
    )


def validate_repository_artifacts_at_ref(
    root: Path,
    ref: str,
    compiler: Path,
    controller: dict[str, Any],
    *,
    repo: str,
    profile_id: str,
    profile_digest: str,
) -> dict[str, Any]:
    lock_bytes = _git_file_at(root, ref, LOCK)
    if lock_bytes is None:
        raise ControlPlaneError(f"{repo}@{ref} has no merged {LOCK}")
    lock = _json_bytes(lock_bytes, f"{repo}@{ref}:{LOCK}")
    base = lock.get("payload", {}).get("recipe_base_sha")
    if not isinstance(base, str) or not re.fullmatch(r"[0-9a-f]{40}", base):
        raise ControlPlaneError("lock recipe_base_sha is malformed")
    current_recipe_bytes = _git_file_at(root, ref, RECIPE)
    if current_recipe_bytes is None:
        raise ControlPlaneError(f"{repo}@{ref} has no current {RECIPE}")
    current_recipe_blob = _git(root, "rev-parse", f"{ref}:{RECIPE}")
    _require_current_recipe_binding(
        current_recipe_bytes,
        current_recipe_blob,
        lock.get("payload", {}),
        source=f"{repo}@{ref}",
    )
    recipe_bytes = _git_file_at(root, base, RECIPE)
    if recipe_bytes is None:
        raise ControlPlaneError("lock recipe_base_sha does not contain the pinned recipe")
    observed_blob = _git(root, "rev-parse", f"{base}:{RECIPE}")
    if observed_blob != lock.get("payload", {}).get("recipe_blob_sha"):
        raise ControlPlaneError("git recipe blob differs from the lock's pinned recipe_blob_sha")
    return validate_artifact_bytes(
        recipe_bytes,
        lock_bytes,
        compiler,
        controller,
        repo=repo,
        profile_id=profile_id,
        profile_digest=profile_digest,
    )


def repository_lock_currency_at_ref(
    root: Path,
    ref: str,
    lock_bytes: bytes | None,
    compiler: Path,
    controller: dict[str, Any],
    *,
    repo: str,
    profile_id: str,
    profile_digest: str,
) -> dict[str, Any]:
    """Classify merged lock currency; only exact Rust validation can produce `current: true`."""
    if lock_bytes is None:
        return {"current": False, "reason": f"{repo}@{ref} has no merged {LOCK}"}
    proof: dict[str, Any] | None = None

    def validate() -> dict[str, Any]:
        nonlocal proof
        proof = validate_repository_artifacts_at_ref(
            root,
            ref,
            compiler,
            controller,
            repo=repo,
            profile_id=profile_id,
            profile_digest=profile_digest,
        )
        return proof

    try:
        current = lock_is_current(
            lock_bytes,
            controller,
            repo=repo,
            profile_id=profile_id,
            profile_digest=profile_digest,
            artifact_validation=validate,
        )
    except ControlPlaneError as exc:
        return {"current": False, "reason": str(exc)}
    if not current:
        lock = _json_bytes(lock_bytes, f"{repo}@{ref}:{LOCK}")
        errors = lock_metadata_errors(
            lock,
            controller,
            repo=repo,
            profile_id=profile_id,
            profile_digest=profile_digest,
        )
        return {
            "current": False,
            "reason": "; ".join(errors) or "lock did not produce current evidence",
        }
    return {"current": True, "artifact_validation": proof}


def compile_repository_lock(
    root: Path,
    compiler: Path,
    controller: dict[str, Any],
    *,
    repo: str,
    profile_id: str,
) -> tuple[bytes, str]:
    _assert_compiler(compiler, controller)
    base = _git(root, "rev-parse", "HEAD")
    recipe_blob = _git(root, "rev-parse", f"HEAD:{RECIPE}")
    recipe_bytes = _run_checked(["git", "-C", str(root), "show", f"HEAD:{RECIPE}"]).stdout
    if (root / RECIPE).read_bytes() != recipe_bytes:
        raise ControlPlaneError("recipe must be committed at target HEAD before sync")
    with tempfile.TemporaryDirectory(prefix="pr-automation-lock-compile-") as temporary:
        lock_path = Path(temporary) / "lock.json"
        _run_checked(
            [
                str(compiler),
                "compile",
                "--recipe",
                str(root / RECIPE),
                "--repository-id",
                repo.rsplit("/", 1)[-1],
                "--activation-generation",
                str(controller["release"]["activation_generation"]),
                "--profile-id",
                profile_id,
                "--recipe-base-sha",
                base,
                "--recipe-blob-sha",
                recipe_blob,
                "--out-lock",
                str(lock_path),
            ],
            cwd=root,
        )
        lock_bytes = lock_path.read_bytes()
    lock = _json_bytes(lock_bytes, "compiled lock")
    profile_digest = lock.get("payload", {}).get("profile_digest")
    if not isinstance(profile_digest, str):
        raise ControlPlaneError("compiled lock did not contain a profile digest")
    validate_artifact_bytes(
        recipe_bytes,
        lock_bytes,
        compiler,
        controller,
        repo=repo,
        profile_id=profile_id,
        profile_digest=profile_digest,
    )
    return lock_bytes, profile_digest


def compile_repository_lock_at_ref(
    root: Path,
    ref: str,
    compiler: Path,
    controller: dict[str, Any],
    *,
    repo: str,
    profile_id: str,
) -> tuple[bytes, str]:
    _assert_compiler(compiler, controller)
    base = _git(root, "rev-parse", ref)
    recipe_bytes = _git_file_at(root, ref, RECIPE)
    if recipe_bytes is None:
        raise ControlPlaneError(f"{repo}@{ref} has no merged {RECIPE}")
    recipe_blob = _git(root, "rev-parse", f"{ref}:{RECIPE}")
    with tempfile.TemporaryDirectory(prefix="pr-automation-lock-compile-") as temporary:
        directory = Path(temporary)
        recipe_path = directory / "recipe.json"
        lock_path = directory / "lock.json"
        recipe_path.write_bytes(recipe_bytes)
        _run_checked(
            [
                str(compiler),
                "compile",
                "--recipe",
                str(recipe_path),
                "--repository-id",
                repo.rsplit("/", 1)[-1],
                "--activation-generation",
                str(controller["release"]["activation_generation"]),
                "--profile-id",
                profile_id,
                "--recipe-base-sha",
                base,
                "--recipe-blob-sha",
                recipe_blob,
                "--out-lock",
                str(lock_path),
            ],
            cwd=root,
        )
        lock_bytes = lock_path.read_bytes()
    lock = _json_bytes(lock_bytes, "compiled lock")
    profile_digest = lock.get("payload", {}).get("profile_digest")
    if not isinstance(profile_digest, str):
        raise ControlPlaneError("compiled lock did not contain a profile digest")
    validate_artifact_bytes(
        recipe_bytes,
        lock_bytes,
        compiler,
        controller,
        repo=repo,
        profile_id=profile_id,
        profile_digest=profile_digest,
    )
    return lock_bytes, profile_digest


def _fetch_github_file(repo: str, path: str, ref: str) -> bytes:
    if not isinstance(ref, str) or not ref:
        raise ControlPlaneError(f"{repo}:{path} requires an explicit verified ref")
    result = _run_checked(
        ["gh", "api", f"repos/{repo}/contents/{path}?ref={quote(ref, safe='')}"]
    )
    value = _json_bytes(result.stdout, f"{repo}@{ref}:{path}")
    content = value.get("content")
    if not isinstance(content, str):
        raise ControlPlaneError(f"{repo}@{ref}:{path} did not return file content")
    try:
        return base64.b64decode(content, validate=False)
    except ValueError as exc:
        raise ControlPlaneError(f"{repo}@{ref}:{path} content is not base64") from exc


def check_fleet_actions_paused(
    fleet_repos: list[str],
    *,
    controller_default_branch: str,
) -> dict[str, Any]:
    """A4 (docs/plans/gen3-m4-actions-retirement-steady-state-v3.md §4 D2 step 5): fetch the
    controller repo's read-only scripts/check-fleet-actions-paused.sh live from its verified
    default branch and run it against `fleet_repos`. Fetching live (rather than trusting any local
    clone) means this always exercises the exact bytes merged to that branch --
    the same live-GitHub-truth philosophy `verify_fleet_remote` already uses.

    The script itself is the single source of truth for the enabled/workflows drift check (and
    carries its own offline self-test in the controller repo); this wrapper only fetches, executes,
    and reports -- it never re-implements the gh api parsing.
    """
    script_bytes = _fetch_github_file(
        CONTROLLER_REPO,
        ACTIONS_PAUSED_SCRIPT,
        controller_default_branch,
    )
    with tempfile.TemporaryDirectory(prefix="pr-automation-fleet-actions-paused-") as temporary:
        script_path = Path(temporary) / "check-fleet-actions-paused.sh"
        script_path.write_bytes(script_bytes)
        script_path.chmod(0o600)
        environment = dict(os.environ)
        environment["PR_AUTOMATION_FLEET_REPOS"] = " ".join(fleet_repos)
        environment.pop("PR_AUTOMATION_FLEET_FIXTURE", None)
        try:
            result = subprocess.run(
                ["bash", str(script_path)],
                capture_output=True,
                env=environment,
                timeout=180,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ControlPlaneError(f"{ACTIONS_PAUSED_SCRIPT} could not run: {exc}") from exc
    return {
        "schema": "pr-automation-fleet-actions-paused/v1",
        "ok": result.returncode == 0,
        "source": (
            f"{CONTROLLER_REPO}@{controller_default_branch}:{ACTIONS_PAUSED_SCRIPT}"
        ),
        "fleet_repos": list(fleet_repos),
        "stdout": result.stdout.decode("utf-8", errors="replace").strip(),
        "stderr": result.stderr.decode("utf-8", errors="replace").strip(),
    }


def validate_remote_repository_artifacts(
    assignment: dict[str, Any],
    compiler: Path,
    controller: dict[str, Any],
    *,
    default_branch: str,
) -> dict[str, Any]:
    repo = assignment["repo"]
    lock_bytes = _fetch_github_file(repo, LOCK, default_branch)
    lock = _json_bytes(lock_bytes, f"{repo}:{LOCK}")
    base = lock.get("payload", {}).get("recipe_base_sha")
    if not isinstance(base, str):
        raise ControlPlaneError(f"{repo}: lock has no recipe_base_sha")
    current_recipe_bytes = _fetch_github_file(repo, RECIPE, default_branch)
    _require_current_recipe_binding(
        current_recipe_bytes,
        _git_blob_sha(current_recipe_bytes),
        lock.get("payload", {}),
        source=f"{repo}@{default_branch}",
    )
    recipe_bytes = _fetch_github_file(repo, RECIPE, base)
    return validate_artifact_bytes(
        recipe_bytes,
        lock_bytes,
        compiler,
        controller,
        repo=repo,
        profile_id=assignment["profile_ref"]["id"],
        profile_digest=assignment["profile_ref"]["digest"],
    )


def _validate_host(host: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", host):
        raise ControlPlaneError("SSH host contains unsafe characters")


def _ssh(
    host: str,
    remote_command: str,
    *,
    input_bytes: bytes | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[bytes]:
    _validate_host(host)
    return _run_checked(
        ["ssh", "-o", "BatchMode=yes", host, remote_command],
        input_bytes=input_bytes,
        timeout=timeout,
    )


def _box_command(*arguments: str) -> str:
    if any(not re.fullmatch(r"[A-Za-z0-9._/-]+", argument) for argument in arguments):
        raise ControlPlaneError("box controller argument contains unsafe characters")
    return " ".join(["sudo", "-u", REMOTE_USER, "-H", REMOTE_BINARY, *arguments])


def read_box_live_config(host: str) -> bytes:
    encoded_config = _ssh(host, f'base64 < "{REMOTE_CONFIG}"').stdout
    try:
        return base64.b64decode(encoded_config, validate=False)
    except ValueError as exc:
        raise ControlPlaneError("box live config was not valid base64") from exc


def read_box_json(host: str, command: str) -> dict[str, Any]:
    result = _ssh(host, command)
    return _json_bytes(result.stdout, f"{host} command output")


def _read_live(args: argparse.Namespace) -> bytes:
    if getattr(args, "live_config", None):
        return Path(args.live_config).read_bytes()
    return read_box_live_config(args.host)


def _ensure_linked_worktree(root: Path, default_branch: str) -> None:
    branch = _git(root, "branch", "--show-current")
    if not branch or branch == default_branch:
        raise ControlPlaneError(f"{root} must be a non-default feature branch")
    git_dir = Path(_git(root, "rev-parse", "--git-dir"))
    common_dir = Path(_git(root, "rev-parse", "--git-common-dir"))
    if not git_dir.is_absolute():
        git_dir = (root / git_dir).resolve()
    if not common_dir.is_absolute():
        common_dir = (root / common_dir).resolve()
    if git_dir == common_dir:
        raise ControlPlaneError(f"{root} is the primary checkout, not a linked worktree")


def _assert_origin(root: Path, repo: str) -> None:
    origin = _git(root, "remote", "get-url", "origin")
    normalized = origin.removesuffix(".git").replace("git@github.com:", "https://github.com/")
    if normalized != f"https://github.com/{repo}":
        raise ControlPlaneError(f"{root} origin {origin!r} does not match {repo}")


def _assert_origin_default_fresh(root: Path, repo: str, default_branch: str) -> None:
    remote = (
        _run_checked(
            [
                "gh",
                "api",
                f"repos/{repo}/commits/{quote(default_branch, safe='')}",
                "--jq",
                ".sha",
            ]
        )
        .stdout.decode("utf-8", errors="strict")
        .strip()
    )
    origin_ref = f"origin/{default_branch}"
    local = _git(root, "rev-parse", origin_ref)
    if not re.fullmatch(r"[0-9a-f]{40}", remote) or local != remote:
        raise ControlPlaneError(
            f"{repo} {origin_ref} is stale or ambiguous; fetch it before planning/staging"
        )


def _run_bind_guard(controller_root: Path, repos: list[str]) -> str:
    environment = dict(os.environ)
    environment["PR_AUTOMATION_BIND_REQUIRE_CLEAR"] = "1"
    environment["PR_AUTOMATION_BIND_REPOS"] = " ".join(dict.fromkeys(repos))
    return (
        _run_checked(
            ["make", "bind-guard"],
            cwd=controller_root,
            env=environment,
            timeout=120,
        )
        .stdout.decode("utf-8", errors="replace")
        .strip()
    )


def _assert_owner_go(operation_id: str, owner_go: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", operation_id):
        raise ControlPlaneError("operation_id must be a safe 1..80-character token")
    if owner_go != operation_id:
        raise ControlPlaneError(
            "live/bind operation refused: --owner-go must exactly repeat --operation-id"
        )


def _assert_control_plane_merged(dev_root: Path, default_branch: str, *, include_sharding=False) -> None:
    control_plane = _control_plane(dev_root)
    names = ("coverage-assignments.json", "fleet.json", "controller.json")
    if include_sharding: names += ("test-sharding-coverage.json",)
    for name in names:
        local = (control_plane / name).read_bytes()
        merged = _fetch_github_file(
            "KleinPerkins/dev",
            f"_ops/baseline/profiles/pr-automation/v3/{name}",
            default_branch,
        )
        if local != merged:
            raise ControlPlaneError(
                f"local {name} is not byte-identical to "
                f"KleinPerkins/dev {default_branch}"
            )


def transcribe_box_config(
    host: str,
    candidate: bytes,
    *,
    operation_id: str,
) -> dict[str, Any]:
    _validate_host(host)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", operation_id):
        raise ControlPlaneError("operation_id is unsafe")
    backup = (
        f"{REMOTE_HOME}/.local/state/pr-automation-controller/activation-backups/"
        f"{operation_id}.prior.json"
    )
    script = f"""
set -eu
umask 077
bin={REMOTE_BINARY}
config="{REMOTE_CONFIG}"
backup="{backup}"
mkdir -p "$(dirname "$backup")"
chown {REMOTE_USER}:{REMOTE_USER} "$(dirname "$backup")"
chmod 700 "$(dirname "$backup")"
test ! -e "$backup"
install -o {REMOTE_USER} -g {REMOTE_USER} -m 600 "$config" "$backup"
candidate="$(sudo -u {REMOTE_USER} -H mktemp "{REMOTE_HOME}/.config/pr-automation-controller/.coverage-candidate.XXXXXX")"
armed=0
cleanup() {{
  rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ] && [ "$armed" -eq 1 ]; then
    sudo -u {REMOTE_USER} -H "$bin" install --source "$backup" >/dev/null 2>&1 || true
    sudo -u {REMOTE_USER} -H "$bin" doctor --live --json >/dev/null 2>&1 || true
    sudo -u {REMOTE_USER} -H "$bin" resume >/dev/null 2>&1 || true
  fi
  rm -f "$candidate"
  exit "$rc"
}}
trap cleanup EXIT
cat > "$candidate"
sudo -u {REMOTE_USER} -H "$bin" --config "$config" pause --drain >/dev/null
armed=1
sudo -u {REMOTE_USER} -H "$bin" install --source "$candidate" >/dev/null
sudo -u {REMOTE_USER} -H "$bin" doctor --live --json >/dev/null
sudo -u {REMOTE_USER} -H "$bin" resume >/dev/null
armed=0
sudo -u {REMOTE_USER} -H "$bin" status --json
"""
    status = _json_bytes(
        _ssh(host, script, input_bytes=candidate, timeout=180).stdout,
        "post-activation box status",
    )
    return {"status": status, "rollback_config": backup}


def restore_box_config_paused(host: str, backup: str) -> dict[str, Any]:
    _validate_host(host)
    if not backup.startswith(f"{REMOTE_HOME}/.local/state/pr-automation-controller/"):
        raise ControlPlaneError("backup path is outside controller operation state")
    script = f"""
set -eu
bin={REMOTE_BINARY}
backup="{backup}"
sudo -u {REMOTE_USER} -H "$bin" install --source "$backup" >/dev/null
sudo -u {REMOTE_USER} -H "$bin" pause --drain >/dev/null
sudo -u {REMOTE_USER} -H "$bin" status --json
"""
    status = _json_bytes(
        _ssh(host, script, timeout=90).stdout,
        "post-requiredness-restore box status",
    )
    _assert_requiredness_staged_status(status)
    return status


def pause_box_controller(host: str) -> dict[str, Any]:
    _validate_host(host)
    script = f"""
set -eu
sudo systemctl stop pr-automation-controller.timer >/dev/null || true
sudo -u {REMOTE_USER} -H {REMOTE_BINARY} pause --drain >/dev/null
sudo -u {REMOTE_USER} -H {REMOTE_BINARY} status --json
"""
    status = _json_bytes(
        _ssh(host, script, timeout=60).stdout,
        "post-requiredness-repause box status",
    )
    _assert_requiredness_staged_status(status)
    return status


def read_box_status(host: str) -> dict[str, Any]:
    _validate_host(host)
    script = f"""
set -eu
sudo -u {REMOTE_USER} -H {REMOTE_BINARY} status --json
"""
    return _json_bytes(
        _ssh(host, script, timeout=60).stdout,
        "requiredness box status",
    )


def stage_requiredness_box_config(
    host: str,
    candidate: bytes,
    *,
    operation_id: str,
    operation_root: Path = OPERATION_ROOT,
    recovery_operation_id: str,
) -> dict[str, Any]:
    _validate_host(host)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", operation_id):
        raise ControlPlaneError("operation_id is unsafe")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", recovery_operation_id):
        raise ControlPlaneError("recovery_operation_id is unsafe")
    backup = (
        f"{REMOTE_HOME}/.local/state/pr-automation-controller/activation-backups/"
        f"{operation_id}.prior.json"
    )
    script = f"""
set -eu
umask 077
bin={REMOTE_BINARY}
config="{REMOTE_CONFIG}"
backup="{backup}"
mkdir -p "$(dirname "$backup")"
chown {REMOTE_USER}:{REMOTE_USER} "$(dirname "$backup")"
chmod 700 "$(dirname "$backup")"
test ! -e "$backup"
install -o {REMOTE_USER} -g {REMOTE_USER} -m 600 "$config" "$backup"
candidate="$(sudo -u {REMOTE_USER} -H mktemp "{REMOTE_HOME}/.config/pr-automation-controller/.requiredness-candidate.XXXXXX")"
armed=0
cleanup() {{
  rc=$?
  trap - EXIT
  if [ "$rc" -ne 0 ] && [ "$armed" -eq 1 ]; then
    sudo -u {REMOTE_USER} -H "$bin" install --source "$backup" >/dev/null 2>&1 || true
    sudo -u {REMOTE_USER} -H "$bin" pause --drain >/dev/null 2>&1 || true
    sudo -u {REMOTE_USER} -H "$bin" doctor --live --json >/dev/null 2>&1 || true
  fi
  rm -f "$candidate"
  exit "$rc"
}}
trap cleanup EXIT
cat > "$candidate"
sudo -u {REMOTE_USER} -H "$bin" --config "$config" pause --drain >/dev/null
armed=1
sudo -u {REMOTE_USER} -H "$bin" install --source "$candidate" >/dev/null
sudo -u {REMOTE_USER} -H "$bin" pause --drain >/dev/null
sudo -u {REMOTE_USER} -H "$bin" doctor --live --json >/dev/null
armed=0
sudo -u {REMOTE_USER} -H "$bin" status --json
"""
    status = _json_bytes(
        _ssh(host, script, input_bytes=candidate, timeout=180).stdout,
        "post-requiredness-stage box status",
    )
    mark_operation_stage_written(
        operation_root,
        operation_id,
        candidate_digest=_sha256_bytes(candidate),
        rollback_config=backup,
        recovery_operation_id=recovery_operation_id,
        status_snapshot=status,
    )
    try:
        _assert_requiredness_staged_status(status)
    except ControlPlaneError as exc:
        try:
            restore_status = restore_box_config_paused(host, backup)
        except ControlPlaneError as restore_exc:
            mark_operation_restore_failed(
                operation_root,
                operation_id,
                reason=str(exc),
                restore_error=str(restore_exc),
            )
            raise ControlPlaneError(
                f"{exc}; aggregate-only restore failed: {restore_exc}"
            ) from restore_exc
        else:
            mark_operation_restored(
                operation_root,
                operation_id,
                reason=str(exc),
                status_snapshot=restore_status,
            )
        raise
    mark_operation_staged(
        operation_root,
        operation_id,
        candidate_digest=_sha256_bytes(candidate),
        rollback_config=backup,
        recovery_operation_id=recovery_operation_id,
        status_snapshot=status,
    )
    return {"status": status, "rollback_config": backup}


def resume_box_controller(host: str) -> dict[str, Any]:
    _validate_host(host)
    resume_script = f"""
set -eu
sudo -u {REMOTE_USER} -H {REMOTE_BINARY} resume >/dev/null
sudo -u {REMOTE_USER} -H {REMOTE_BINARY} status --json
"""
    status = _json_bytes(
        _ssh(host, resume_script, timeout=60).stdout,
        "post-requiredness-finalize box status",
    )
    try:
        _assert_requiredness_completed_status(status)
    except ControlPlaneError:
        pause_box_controller(host)
        raise
    timer_script = f"""
set -eu
sudo systemctl start pr-automation-controller.timer >/dev/null
sudo -u {REMOTE_USER} -H {REMOTE_BINARY} status --json
"""
    try:
        final_status = _json_bytes(
            _ssh(host, timer_script, timeout=60).stdout,
            "post-requiredness-timer-start box status",
        )
        _assert_requiredness_completed_status(final_status)
    except ControlPlaneError:
        pause_box_controller(host)
        raise
    return final_status


def repository_name(root: Path) -> str:
    return root.resolve().name


def refuse_excluded(root: Path) -> None:
    if repository_name(root).lower() == HARD_EXCLUSION:
        fail("chaos-scheduler is a hard no-touch exclusion")


def managed_codeowners(existing: str) -> str:
    block = "\n".join(
        [
            BEGIN,
            "/.github/ @KleinPerkins",
            "/CODEOWNERS @KleinPerkins",
            "/_ops/ @KleinPerkins",
            END,
        ]
    )
    pattern = re.compile(
        rf"(?:\n)?{re.escape(BEGIN)}\n.*?\n{re.escape(END)}(?:\n)?",
        re.DOTALL,
    )
    stripped = pattern.sub("\n", existing).rstrip()
    return f"{stripped}\n\n{block}\n" if stripped else f"{block}\n"


def refuse_native_delivery(root: Path) -> None:
    library = Path(__file__).resolve().parents[4] / "bin/baseline-lib.sh"
    environment = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"}
    try:
        result = subprocess.run(
            ["/bin/bash", "-c", '. "$1"; bl_repo_delivery_class "$2"',
             "delivery-policy", str(library), str(root)],
            capture_output=True, text=True, timeout=10, env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        fail(f"delivery identity unavailable: {exc}")
    if result.returncode != 0 or result.stdout.strip() != "runnerless-default":
        fail("native delivery identity refuses runnerless profile staging")


def stage(args: argparse.Namespace) -> None:
    root = Path(args.repo_root).resolve()
    refuse_excluded(root)
    if not (root / ".git").exists():
        fail(f"{root}: not a git working tree root")
    refuse_native_delivery(root)
    name = args.name or repository_name(root)
    assignments = load_json(HERE / "coverage-assignments.json")
    fleet = load_json(HERE / "fleet.json")
    controller = load_json(HERE / "controller.json")
    try:
        projection = resolve_repository_projection(
            assignments,
            fleet,
            controller,
            repository_id=args.repository_id,
            repo=f"{args.owner}/{name}",
            default_branch=args.default_branch,
        )
    except ControlPlaneError as exc:
        fail(f"generated policy: {exc}")
    policy = {
        "version": "pr-automation/v3",
        "repository_id": args.repository_id,
        "owner": args.owner,
        "name": name,
        "default_branch": args.default_branch,
        "activation_generation": args.activation_generation,
        "check_name": CHECK,
        "verifier_app_id": 4274739,
        "verifier_integration_id": 4274739,
        "reviewer_app_id": 4269364,
        "reviewer_integration_id": 4269364,
        "protected_paths": PROTECTED_PATHS,
        "ruleset_fingerprints": projection.runtime_app_visible_fingerprints,
        "max_changed_files": 200,
        "max_total_patch_bytes": 5_000_000,
        "controller_release_digest": RELEASE_DIGEST,
    }
    manifest = {
        "version": "pr-automation-verification/v1",
        "jobs": [
            {
                "id": "verify-repository-contract",
                "image": EXECUTION_IMAGE_REF,
                "argv": ["repository-contract"],
                "environment": {"CI": "true"},
                "network": "none",
                "discovery": {
                    "kind": "literal_stdout",
                    "literal": "PR_AUTOMATION_VERIFY_OK",
                },
                "limits": {
                    "timeout_seconds": 120,
                    "cpus_millis": 500,
                    "memory_mib": MEMORY_MIB,
                    "pids": 64,
                    "disk_mib": 128,
                    "inodes": 4096,
                    "output_bytes": 32768,
                },
            }
        ],
        "secondary_sources": [],
    }
    validate_policy(
        policy,
        "generated policy",
        assignments=assignments,
        fleet=fleet,
        controller=controller,
    )
    validate_manifest(manifest, "generated manifest")
    atomic_write(root / POLICY, encoded(policy))
    atomic_write(root / MANIFEST, encoded(manifest))
    codeowners_path = root / CODEOWNERS
    existing = codeowners_path.read_text(encoding="utf-8") if codeowners_path.exists() else ""
    atomic_write(codeowners_path, managed_codeowners(existing))
    verify_repository(root)
    print(f"STAGED: runnerless v3 contracts for {repository_name(root)} (remote activation unchanged)")


def verify_repository(root: Path) -> None:
    refuse_excluded(root)
    validate_policy(
        load_json(root / POLICY),
        POLICY,
        assignments=load_json(HERE / "coverage-assignments.json"),
        fleet=load_json(HERE / "fleet.json"),
        controller=load_json(HERE / "controller.json"),
    )
    validate_manifest(load_json(root / MANIFEST), MANIFEST)
    codeowners = (root / CODEOWNERS).read_text(encoding="utf-8")
    if codeowners.count(BEGIN) != 1 or codeowners.count(END) != 1:
        fail(f"{CODEOWNERS}: managed block must occur exactly once")
    for required in ("/.github/ @KleinPerkins", "/CODEOWNERS @KleinPerkins", "/_ops/ @KleinPerkins"):
        if required not in codeowners:
            fail(f"{CODEOWNERS}: missing {required}")
    workflows = root / ".github/workflows"
    if workflows.exists():
        for path in workflows.glob("*.y*ml"):
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            if "pr-automation" in text or "kleinperkins-review-bot" in text:
                fail(f"{path}: legacy Actions PR automation must be removed before v3 verification")
    print(f"OK: runnerless v3 repository contracts verified for {repository_name(root)}")


def validate_awa_authoritative_verify_authority(
    controller: dict[str, Any], coverage: dict[str, Any]
) -> None:
    if controller.get("runtime") != AWA_RUNTIME_ENVELOPE:
        raise ControlPlaneError(
            "controller.json AWA runtime envelope must remain exactly 8100/8400/180/control-group"
        )
    if controller.get("images", {}).get("profile_overrides") != PROFILE_IMAGE_OVERRIDES:
        raise ControlPlaneError(
            "controller.json AWA profile image override must remain qualified and exact"
        )
    assignments = coverage.get("assignments")
    if not isinstance(assignments, list):
        raise ControlPlaneError("coverage-assignments.json assignments must be a list")
    awa_assignments = [
        assignment
        for assignment in assignments
        if isinstance(assignment, dict) and assignment.get("repo") == "KleinPerkins/awa"
    ]
    if awa_assignments != [AWA_AUTHORITATIVE_ASSIGNMENT]:
        raise ControlPlaneError(
            "coverage-assignments.json AWA authoritative profile, digest, and required Check "
            "must remain exact"
        )


def verify_control_plane() -> None:
    controller = load_json(HERE / "controller.json")
    fleet = load_json(HERE / "fleet.json")
    controller_schema = load_json(HERE / "controller.schema.json")
    fleet_schema = load_json(HERE / "fleet.schema.json")
    coverage_schema = load_json(HERE / "coverage-assignments.schema.json")
    try:
        validate_json_schema_instance(
            controller_schema,
            controller,
            source="controller.json",
        )
        validate_json_schema_instance(
            fleet_schema,
            fleet,
            source="fleet.json",
        )
    except ControlPlaneError as exc:
        fail(str(exc))
    evidence = load_json(HERE / "canary-evidence.json")
    rollout = load_json(HERE / "rollout-evidence.json")
    if controller.get("schema") != "pr-automation-controller-binding/v3":
        fail("controller.json schema mismatch")
    if controller.get("check_name") != CHECK:
        fail("controller.json Check name mismatch")
    if controller.get("verifier") != {
        "app_id": 4274739,
        "integration_id": 4274739,
        "slug": "kleinperkins-verify-bot",
        "installation_id": 145944952,
    }:
        fail("controller.json verifier App binding mismatch")
    if controller.get("reviewer") != {
        "app_id": 4269364,
        "integration_id": 4269364,
        "slug": "kleinperkins-review-bot",
        "installation_id": 145790860,
    }:
        fail("controller.json reviewer App binding mismatch")
    if controller.get("hard_exclusions") != ["KleinPerkins/chaos-scheduler"]:
        fail("controller.json must preserve the hard exclusion")
    if controller.get("release", {}).get("digest") != RELEASE_DIGEST:
        fail("controller.json release digest mismatch")
    if controller.get("release", {}).get("lock_compiler_digest") != LOCK_COMPILER_DIGEST:
        fail("controller.json qualified lock-compiler digest mismatch")
    if controller.get("release", {}).get("lock_contract_version") != LOCK_CONTRACT_VERSION:
        fail(
            "controller.json lock_contract_version must equal the supported "
            f"epoch {LOCK_CONTRACT_VERSION}"
        )
    if controller.get("images", {}).get("profile_overrides", {}) != PROFILE_IMAGE_OVERRIDES:
        fail("controller.json profile image overrides are not freshly derived")
    configured_fingerprints = controller.get("ruleset_fingerprints", {})
    overrides = configured_fingerprints.get("repository_overrides", {})
    if not isinstance(overrides, dict):
        fail("controller.json repository_overrides must be an object")
    try:
        targets = _validated_fleet_targets(fleet)
    except ControlPlaneError as exc:
        fail(str(exc))
    base_branches = {
        target["default_branch"]
        for target in targets
        if str(target["repository_id"]) not in overrides
    }
    if len(base_branches) != 1:
        fail(
            "controller.json base fingerprints require exactly one default branch "
            "across non-overridden fleet targets"
        )
    base_pair = ruleset_fingerprint_pair(
        _render_base_ruleset(next(iter(base_branches)))
    )
    if configured_fingerprints.get("runtime_app_visible") != base_pair["runtime_app_visible"]:
        fail("controller.json base app-visible fingerprint is not freshly derived")
    if configured_fingerprints.get("operator_full") != base_pair["operator_full"]:
        fail("controller.json base owner-visible fingerprint is not freshly derived")
    try:
        _configured_fingerprint_pair(controller, targets[0])
    except ControlPlaneError as exc:
        fail(str(exc))
    if fleet.get("schema") != "pr-automation-fleet/v3":
        fail("fleet.json schema mismatch")
    repos = [item["repo"] for item in targets]
    if len(repos) < 14 or len(repos) != len(set(repos)):
        fail("fleet.json must contain at least fourteen unique targets")
    excluded = {item.get("repo") for item in fleet.get("excluded", []) if isinstance(item, dict)}
    if "KleinPerkins/chaos-scheduler" not in excluded:
        fail("fleet.json must preserve the chaos-scheduler exclusion")
    if "KleinPerkins/chaos-scheduler" in repos:
        fail("chaos-scheduler cannot be a target")
    if evidence.get("schema") != "pr-automation-canary-evidence/v3":
        fail("canary-evidence.json schema mismatch")
    if evidence.get("generation_1", {}).get("rollback_observed_empty") is not True:
        fail("generation-1 rollback proof is incomplete")
    if evidence.get("generation_2", {}).get("active") is not True:
        fail("generation-2 activation proof is incomplete")
    if evidence.get("invariants", {}).get("actions_repository_enabled") is not False:
        fail("canary Actions-off proof is incomplete")
    if rollout.get("schema") != "pr-automation-rollout-evidence/v3":
        fail("rollout-evidence.json schema mismatch")
    qualified = rollout.get("qualified", [])
    if not isinstance(qualified, list) or len(qualified) < 14:
        fail("rollout evidence must contain at least fourteen qualified repositories")
    expected_rulesets = {"kleinperkins-merge-safety"}
    target_by_repo = {target["repo"]: target for target in targets}
    for row in qualified:
        if row.get("check_conclusion") != "success":
            fail("every qualified repository must have a successful verifier Check")
        if row.get("head_sha") != row.get("approval_commit_sha"):
            fail("every qualified approval must bind the exact head")
        names = {item.get("name") for item in row.get("rulesets", [])}
        if names != expected_rulesets:
            fail("every qualified repository must have exactly the v3 ruleset pair")
        target = target_by_repo.get(row.get("repository"))
        if target is not None:
            ids = [
                item.get("id")
                for item in row.get("rulesets", [])
                if isinstance(item, dict) and item.get("name") == MERGE_SAFETY_NAME
            ]
            if ids != [target["merge_safety_ruleset_id"]]:
                fail(
                    f"{target['repo']} fleet current ruleset id differs from rollout evidence"
                )
    if rollout.get("blocked") != []:
        fail("qualified fleet must not retain rollout blockers")
    if fingerprint(load_json(HERE / "repository-policy.schema.json")) != POLICY_SCHEMA_DIGEST:
        fail("repository policy schema differs from the released controller")
    if fingerprint(load_json(HERE / "verification-manifest.schema.json")) != MANIFEST_SCHEMA_DIGEST:
        fail("verification manifest schema differs from the released controller")
    coverage = load_json(HERE / "coverage-assignments.json")
    validate_coverage_assignments(coverage, repos, "coverage-assignments.json")
    try:
        validate_json_schema_instance(
            coverage_schema,
            coverage,
            source="coverage-assignments.json",
        )
        validate_awa_authoritative_verify_authority(controller, coverage)
    except ControlPlaneError as exc:
        fail(str(exc))
    target_ids = {
        str(item.get("repository_id"))
        for item in targets
        if isinstance(item, dict) and isinstance(item.get("repository_id"), int)
    }
    override_ids = set(configured_fingerprints.get("repository_overrides", {}))
    if not override_ids <= target_ids:
        fail(
            "controller.json repository fingerprint overrides must reference fleet repository IDs"
        )
    for target in targets:
        if not isinstance(target, dict):
            fail("fleet target must be an object")
        try:
            resolve_repository_projection(
                coverage,
                fleet,
                controller,
                repository_id=target.get("repository_id"),
                repo=target.get("repo"),
                default_branch=target.get("default_branch"),
            )
        except ControlPlaneError as exc:
            fail(f"repository projection: {exc}")
    if (
        coverage_schema.get("properties", {}).get("schema", {}).get("const")
        != "pr-automation-coverage-assignments/v2"
    ):
        fail("coverage assignment schema does not declare v2")
    qualification = load_json(HERE / QUALIFICATION_LEDGER)
    if qualification.get("schema") != "pr-automation-m3-qualification-ledger/v1":
        fail(f"{QUALIFICATION_LEDGER}: schema mismatch")
    candidates = qualification.get("candidates")
    if not isinstance(candidates, list) or {
        item.get("repo") for item in candidates if isinstance(item, dict)
    } != set(M3_CUSTOM_COMMANDS):
        fail(f"{QUALIFICATION_LEDGER}: must disposition exactly the five reviewed candidates")
    for item in candidates:
        repo = item.get("repo")
        if (
            item.get("status") not in {"qualified", "canned_only"}
            or item.get("argv") != M3_CUSTOM_COMMANDS[repo]
            or item.get("image") != EXECUTION_IMAGE_REF
            or item.get("limits") != STDLIB_LIMITS
            or not isinstance(item.get("evidence"), dict)
        ):
            fail(f"{QUALIFICATION_LEDGER}: invalid disposition for {repo}")
    assigned = coverage["assignments"]
    assigned_repos = sorted(item["repo"] for item in assigned)
    unassigned_repos = sorted(repo for repo in repos if repo not in assigned_repos)
    print(f"OK: coverage assignments — {len(assigned_repos)} assigned, {len(unassigned_repos)} unassigned")
    for repo in assigned_repos:
        mode = next(item["coverage_mode"] for item in assigned if item["repo"] == repo)
        print(f"  ASSIGNED    {repo}  {mode}")
    print("OK: runnerless v3 central control plane verified")
    print(
        "NOTE: this is a local/evidence check only. Run `verify-fleet-remote --lock-compiler "
        "<qualified-path>` (needs gh) to confirm every repository's REMOTE policy and exact v2/epoch "
        "lock recompilation before declaring a bind complete."
    )


def _gh_json(path: str) -> Any:
    """Read-only GitHub API GET via gh; returns parsed JSON or None on any failure."""
    import subprocess

    try:
        result = subprocess.run(
            ["gh", "api", path], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _gh_json_paginated_list(path: str) -> list[Any] | None:
    """Read every page from one list endpoint; malformed or repeated pages fail closed."""
    result: list[Any] = []
    seen_pages: set[str] = set()
    page = 1
    while page <= 1000:
        values = _gh_json(f"{path}?per_page=100&page={page}")
        if not isinstance(values, list):
            return None
        rendered = canonical(values)
        if len(values) == 100 and rendered in seen_pages:
            return None
        seen_pages.add(rendered)
        result.extend(values)
        if len(values) < 100:
            return result
        page += 1
    return None


def _decode_remote_content(value: Any, source: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("content"), str):
        raise ControlPlaneError(f"{source} is unreachable")
    try:
        decoded = json.loads(base64.b64decode(value["content"]))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ControlPlaneError(f"{source} is not valid encoded JSON") from exc
    if not isinstance(decoded, dict):
        raise ControlPlaneError(f"{source} root must be an object")
    return decoded


def fetch_live_repository_metadata(
    fleet: dict[str, Any],
    repo: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch one live repository record, then resolve it by immutable ID plus full name."""
    raw = _gh_json(f"repos/{repo}")
    if not isinstance(raw, dict):
        raise ControlPlaneError(f"{repo} live repository metadata is unreachable")
    repository_id = raw.get("id")
    full_name = raw.get("full_name")
    default_branch = raw.get("default_branch")
    if (
        not isinstance(repository_id, int)
        or isinstance(repository_id, bool)
        or repository_id < 1
        or not isinstance(full_name, str)
        or full_name != repo
    ):
        raise ControlPlaneError(
            f"{repo} live repository identity/default branch is incomplete or changed"
        )
    validate_default_branch(default_branch, f"{repo} live default branch")
    target = resolve_fleet_target(
        fleet,
        repository_id=repository_id,
        repo=full_name,
    )
    if default_branch != target["default_branch"]:
        raise ControlPlaneError(
            f"{repo} live default branch {default_branch!r} differs from fleet authority "
            f"{target['default_branch']!r}"
        )
    return (
        {
            "repository_id": repository_id,
            "full_name": full_name,
            "default_branch": default_branch,
        },
        target,
    )


def fetch_remote_repository_controls(
    fleet: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Read metadata, policies, and exact owner-visible rulesets; never mutate GitHub."""
    controls: dict[str, dict[str, Any]] = {}
    for enrolled in _validated_fleet_targets(fleet):
        repo = enrolled["repo"]
        metadata, target = fetch_live_repository_metadata(fleet, repo)
        default_branch = metadata["default_branch"]
        policy = _decode_remote_content(
            _gh_json(
                f"repos/{repo}/contents/{POLICY}?ref={quote(default_branch, safe='')}"
            ),
            f"{repo}@{default_branch} policy",
        )
        ruleset_id = target["merge_safety_ruleset_id"]
        if ruleset_id is None:
            raise ControlPlaneError(
                f"{repo} has no expected current {MERGE_SAFETY_NAME} ruleset id"
            )
        listed = _gh_json_paginated_list(f"repos/{repo}/rulesets")
        validate_managed_ruleset_listing(
            listed,
            expected_ruleset_id=ruleset_id,
            expected_repo=repo,
        )
        ruleset = _gh_json(f"repos/{repo}/rulesets/{ruleset_id}")
        validate_live_ruleset_identity(
            ruleset,
            expected_ruleset_id=ruleset_id,
            expected_repo=repo,
        )
        controls[repo] = {
            "metadata": metadata,
            "policy": policy,
            "ruleset_metadata": listed,
            "ruleset": ruleset,
        }
    return controls


def verify_repository_control_parity(
    assignments: dict[str, Any],
    fleet: dict[str, Any],
    controller: dict[str, Any],
    *,
    target: dict[str, Any],
    metadata: dict[str, Any],
    policy: dict[str, Any],
    ruleset: dict[str, Any],
) -> dict[str, Any]:
    repo = target.get("repo")
    repository_id = target.get("repository_id")
    if not isinstance(repo, str) or not isinstance(repository_id, int):
        raise ControlPlaneError("fleet target identity is invalid")
    if (
        not isinstance(metadata, dict)
        or not isinstance(policy, dict)
        or not isinstance(ruleset, dict)
    ):
        raise ControlPlaneError(f"{repo} metadata/policy/live-ruleset control record is invalid")
    resolved = resolve_fleet_target(
        fleet,
        repository_id=metadata.get("repository_id"),
        repo=metadata.get("full_name"),
    )
    if resolved is not target and resolved != target:
        raise ControlPlaneError(f"{repo} fleet target authority changed during verification")
    if metadata.get("default_branch") != target.get("default_branch"):
        raise ControlPlaneError(f"{repo} live metadata default branch disagrees with fleet")
    expected_ruleset_id = target.get("merge_safety_ruleset_id")
    validate_live_ruleset_identity(
        ruleset,
        expected_ruleset_id=expected_ruleset_id,
        expected_repo=repo,
    )
    try:
        validate_policy(
            policy,
            f"{repo} remote policy",
            assignments=assignments,
            fleet=fleet,
            controller=controller,
        )
    except SystemExit as exc:
        raise ControlPlaneError(str(exc)) from exc
    projection = resolve_repository_projection(
        assignments,
        fleet,
        controller,
        repository_id=repository_id,
        repo=repo,
        default_branch=metadata["default_branch"],
    )
    if (
        policy.get("repository_id") != repository_id
        or f"{policy.get('owner')}/{policy.get('name')}" != repo
        or policy.get("default_branch") != metadata["default_branch"]
    ):
        raise ControlPlaneError(
            f"{repo} assignment/metadata/policy repository identity disagreement"
        )
    live_pair = ruleset_fingerprint_pair(ruleset)
    expected_pair = {
        "runtime_app_visible": projection.runtime_app_visible_fingerprints,
        "operator_full": projection.operator_full_fingerprints,
    }
    if live_pair != expected_pair:
        raise ControlPlaneError(
            f"{repo} assignment/policy/live-ruleset fingerprint disagreement: "
            f"live={live_pair} expected={expected_pair}"
        )
    return {
        "repository_id": repository_id,
        "full_name": metadata["full_name"],
        "default_branch": metadata["default_branch"],
        "ruleset_id": expected_ruleset_id,
        "required_status_checks": copy.deepcopy(projection.required_status_checks),
        "runtime_app_visible": projection.runtime_app_visible_fingerprints,
        "operator_full": projection.operator_full_fingerprints,
    }


def verify_repository_controls(
    assignments: dict[str, Any],
    fleet: dict[str, Any],
    controller: dict[str, Any],
    controls: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    targets = [target for target in fleet.get("targets", []) if isinstance(target, dict)]
    expected_repos = {target.get("repo") for target in targets}
    if set(controls) != expected_repos:
        raise ControlPlaneError(
            "assignment/policy/live-ruleset controls are incomplete: "
            f"missing={sorted(expected_repos - set(controls))} "
            f"extra={sorted(set(controls) - expected_repos)}"
        )
    verified = {}
    for target in targets:
        repo = target["repo"]
        control = controls[repo]
        if not isinstance(control, dict):
            raise ControlPlaneError(f"{repo} remote control record is invalid")
        verified[repo] = verify_repository_control_parity(
            assignments,
            fleet,
            controller,
            target=target,
            metadata=control.get("metadata"),
            policy=control.get("policy"),
            ruleset=control.get("ruleset"),
        )
    return {"status": "exact", "repositories": verified}


def verify_fleet_remote(compiler: Path) -> None:
    """Read-only live gate for policy parity plus exact v2/epoch Rust lock validation.

    Requires `gh` auth, network, and the controller-bound qualified lock compiler (operator use,
    never headless CI).

    This is the objective completeness check that `verify-control-plane` cannot make: the latter
    trusts rollout-evidence.json, so a controller bump can be recorded "complete" while repositories
    are never re-staged. A stranded repo fails closed (its required Check can never post), so drift
    stays invisible until someone opens a PR. This verb makes the drift loud and PR-independent.

    It asserts three independent dimensions per repository and fails closed on any:
      1. Control parity — assignment, committed policy fingerprints, and the owner-visible live
         merge-safety ruleset all equal the shared repository projection.
      2. Policy digest parity — the committed `.github/pr-automation.json` `controller_release_digest`
         (and pinned `activation_generation`) equals the bound release. This is the ORIGINAL check.
      3. Lock-recompile currency — for every lock-governed repo (fleet StructuralLegacy x per-repo
         Shadow|Local), the committed lock is schema v2/epoch 1 and the exact qualified Rust
         validator byte-recompiles it from current catalog/profile/image/recipe/assignment inputs.
         Policy `controller_release_digest` remains an independent binary-integrity binding."""

    controller = load_json(HERE / "controller.json")
    release = controller.get("release", {})
    expected = release.get("digest")
    expected_generation = release.get("activation_generation")
    if expected != RELEASE_DIGEST:
        fail("controller.json release digest disagrees with the profile constant")
    expected_epoch = release.get("lock_contract_version")
    if expected_epoch != LOCK_CONTRACT_VERSION:
        fail(
            "controller.json lock_contract_version disagrees with the supported "
            f"epoch {LOCK_CONTRACT_VERSION}"
        )
    _assert_compiler(compiler, controller)
    fleet = load_json(HERE / "fleet.json")
    try:
        target_rows = _validated_fleet_targets(fleet)
    except ControlPlaneError as exc:
        fail(str(exc))
    targets = [item["repo"] for item in target_rows]
    if not targets:
        fail("fleet.json has no targets")
    # Lock-governed cohort: mirror the box's `observe_lock` enforcement gate
    # (`effective_repository_coverage`, controller repo src/model.rs) -- fleet gate StructuralLegacy
    # (the generation-3 fleet gate this whole v3 profile operates under) x per-repo Shadow|Local.
    # A manual_only / unassigned repo carries no ENFORCED lock, so its lock is never read and it is
    # never flagged for lock staleness. chaos-scheduler is a hard exclusion and can never appear in
    # coverage-assignments.json (validate_coverage_assignments forbids it).
    assignments = load_json(HERE / "coverage-assignments.json")
    try:
        controls = fetch_remote_repository_controls(fleet)
        control_proof = verify_repository_controls(
            assignments,
            fleet,
            controller,
            controls,
        )
    except ControlPlaneError as exc:
        fail(f"fleet assignment/policy/live-ruleset verification FAILED: {exc}")
    assignment_by_repo = {
        entry["repo"]: entry
        for entry in assignments["assignments"]
        if isinstance(entry, dict) and isinstance(entry.get("repo"), str)
    }
    lock_governed = {
        repo
        for repo, entry in assignment_by_repo.items()
        if entry["coverage_mode"] in {"shadow", "local"}
    }
    current: list[str] = []
    stale: list[tuple[str, str]] = []
    unreachable: list[str] = []
    lock_current: list[str] = []
    lock_stale: list[tuple[str, str]] = []
    lock_cell: dict[str, str] = {}
    for repo in targets:
        policy = controls[repo]["policy"]
        digest = policy.get("controller_release_digest")
        generation = policy.get("activation_generation")
        if digest == expected and (
            expected_generation is None or generation == expected_generation
        ):
            current.append(repo)
        else:
            stale.append((repo, f"digest={digest} generation={generation}"))
        # Only lock-governed repos carry an enforced lock. Their currency proof must traverse the
        # qualified Rust validator against the exact remote recipe and central assignment.
        if repo not in lock_governed:
            lock_cell[repo] = "lock n/a"
            continue
        try:
            proof = validate_remote_repository_artifacts(
                assignment_by_repo[repo],
                compiler,
                controller,
                default_branch=controls[repo]["metadata"]["default_branch"],
            )
            if (
                proof.get("validated") is not True
                or proof.get("schema_version") != LOCK_SCHEMA
                or proof.get("lock_contract_version") != expected_epoch
                or not isinstance(proof.get("covered_digests"), dict)
                or set(proof["covered_digests"]) != set(LOCK_COVERED_DIGEST_FIELDS)
            ):
                raise ControlPlaneError(
                    "validator evidence omitted v2/epoch/current covered-digest proof"
                )
            lock_current.append(repo)
            lock_cell[repo] = f"lock=v2/epoch={expected_epoch}"
        except ControlPlaneError as exc:
            lock_stale.append((repo, str(exc)))
            lock_cell[repo] = "lock STALE"
    # Per-repo report: BOTH dimensions on one line so a stranded/stale repo is obvious at a glance.
    stale_repos = {repo for repo, _ in stale}
    for repo in targets:
        if repo in stale_repos:
            digest_cell = "STALE"
        elif repo in unreachable:
            digest_cell = "UNREACH"
        else:
            digest_cell = "OK"
        evidence = control_proof["repositories"][repo]
        print(
            f"{digest_cell:<8}{lock_cell.get(repo, 'lock n/a'):<20}{repo} "
            f"id={evidence['repository_id']} branch={evidence['default_branch']} "
            f"ruleset={evidence['ruleset_id']}"
        )
    for repo, detail in stale:
        print(f"  digest STALE       {repo}  {detail}")
    for repo in unreachable:
        print(f"  digest UNREACHABLE {repo}")
    for repo, detail in lock_stale:
        print(f"  lock STALE         {repo}  {detail} (required {LOCK_SCHEMA} epoch {expected_epoch})")
    problems: list[str] = []
    if stale or unreachable:
        problems.append(
            f"digest parity {len(current)}/{len(targets)} current, "
            f"{len(stale)} stale, {len(unreachable)} unreachable"
        )
    if lock_stale:
        problems.append(
            f"lock currency {len(lock_current)}/{len(lock_governed)} current, "
            f"{len(lock_stale)} stale"
        )
    if problems:
        fail(
            "fleet remote verification FAILED: "
            + "; ".join(problems)
            + " — rollout is NOT complete"
        )
    parity = f"digest {expected}"
    if expected_generation is not None:
        parity += f" + generation {expected_generation}"
    print(f"OK: fleet remote parity — {len(current)}/{len(targets)} match {parity}")
    print(
        f"OK: fleet lock currency — {len(lock_current)}/{len(lock_governed)} "
        f"lock-governed repos at {LOCK_SCHEMA} epoch {expected_epoch} with exact Rust validation"
    )

    # A4 (gen3-m4-actions-retirement-steady-state-v3.md §5): the fleet-wide Actions-pause
    # invariant is now a standing declared state alongside policy-digest parity above, so this
    # live gate exercises both -- matching the precedent that verify-fleet-remote accumulates new
    # standing fleet-wide invariants over time (see the plan's D3 reversibility-table row).
    controller_metadata = controls.get(CONTROLLER_REPO, {}).get("metadata", {})
    controller_default_branch = controller_metadata.get("default_branch")
    if not isinstance(controller_default_branch, str) or not controller_default_branch:
        fail("controller repository live default branch evidence is missing")
    actions_paused = check_fleet_actions_paused(
        targets,
        controller_default_branch=controller_default_branch,
    )
    if actions_paused["stdout"]:
        print(actions_paused["stdout"])
    if not actions_paused["ok"]:
        fail(
            "fleet Actions-pause drift detected (A4, check-fleet-actions-paused.sh):\n"
            + (actions_paused["stderr"] or "no diagnostic")
        )
    print(f"OK: fleet Actions-pause parity — {len(targets)}/{len(targets)} confirmed paused")


def _control_plane(dev_root: Path) -> Path:
    return dev_root / "_ops/baseline/profiles/pr-automation/v3"


def _authorities(dev_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = _control_plane(dev_root)
    return (
        load_json(root / "coverage-assignments.json"),
        load_json(root / "fleet.json"),
        load_json(root / "controller.json"),
    )


def _qualified_custom_argv(dev_root: Path, repo: str) -> list[str] | None:
    ledger = load_json(_control_plane(dev_root) / QUALIFICATION_LEDGER)
    matches = [
        item
        for item in ledger.get("candidates", [])
        if isinstance(item, dict) and item.get("repo") == repo
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ControlPlaneError(f"{repo} has duplicate qualification dispositions")
    entry = matches[0]
    status = entry.get("status")
    if status == "canned_only":
        return None
    if status != "qualified":
        raise ControlPlaneError(f"{repo} custom command is not qualified: {status}")
    argv = entry.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise ControlPlaneError(f"{repo} qualified custom argv is invalid")
    if entry.get("image") != EXECUTION_IMAGE_REF or entry.get("limits") != STDLIB_LIMITS:
        raise ControlPlaneError(f"{repo} qualification does not match stdlib-shell.v1")
    if argv != M3_CUSTOM_COMMANDS.get(repo):
        raise ControlPlaneError(f"{repo} qualification argv differs from the reviewed M3 command")
    return argv


def _assignment_for(assignments: dict[str, Any], repo: str) -> dict[str, Any]:
    matches = [entry for entry in assignments["assignments"] if entry["repo"] == repo]
    if len(matches) != 1:
        raise ControlPlaneError(f"{repo} does not have exactly one coverage assignment")
    return matches[0]


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def command_view(args: argparse.Namespace) -> None:
    dev_root = Path(args.dev_root).resolve()
    assignments, fleet, controller = _authorities(dev_root)
    live = _read_live(args)
    view = view_coverage(live, assignments, fleet, controller)
    controls = fetch_remote_repository_controls(fleet)
    view["repository_controls"] = verify_repository_controls(
        assignments,
        fleet,
        controller,
        controls,
    )
    view["source"] = str(args.live_config) if args.live_config else args.host
    if args.live_config:
        view["controller_status"] = "not_requested_for_local_snapshot"
    else:
        view["controller_status"] = read_box_json(
            args.host, _box_command("status", "--json")
        )
    if args.lock_compiler:
        compiler = Path(args.lock_compiler).resolve()
        view["repository_parity"] = [
            {
                "repo": assignment["repo"],
                **validate_remote_repository_artifacts(
                    assignment,
                    compiler,
                    controller,
                    default_branch=controls[assignment["repo"]]["metadata"][
                        "default_branch"
                    ],
                ),
            }
            for assignment in assignments["assignments"]
        ]
    else:
        view["repository_parity"] = "not_requested; pass --lock-compiler for full proof"
    _emit(view)


def command_plan(args: argparse.Namespace) -> None:
    dev_root = Path(args.dev_root).resolve()
    target_root = Path(args.target_root).resolve()
    assignments, fleet, controller = _authorities(dev_root)
    metadata, _ = fetch_live_repository_metadata(fleet, args.repo)
    default_branch = metadata["default_branch"]
    origin_ref = f"origin/{default_branch}"
    _assert_origin(target_root, args.repo)
    _assert_origin_default_fresh(target_root, args.repo, default_branch)
    if args.repo in _hard_exclusions(controller):
        raise ControlPlaneError(f"{args.repo} is a hard exclusion")
    recipe_bytes = _git_file_at(target_root, origin_ref, RECIPE)
    lock_bytes = _git_file_at(target_root, origin_ref, LOCK)
    assignment = next(
        (item for item in assignments["assignments"] if item["repo"] == args.repo),
        None,
    )
    lock_payload = _json_bytes(lock_bytes, LOCK).get("payload", {}) if lock_bytes else {}
    if not isinstance(lock_payload, dict):
        raise ControlPlaneError("merged lock payload must be an object")
    qualified_release: dict[str, Any] | None = None
    lock_currency: dict[str, Any] = {"current": False, "reason": "no merged lock"}
    if lock_bytes is not None:
        if not args.lock_compiler or not args.release_manifest:
            raise ControlPlaneError(
                "merged lock currency planning requires --lock-compiler and --release-manifest"
            )
        qualified_release = validate_qualified_release(
            Path(args.release_manifest).resolve(), controller
        )
        profile_ref = assignment.get("profile_ref", {}) if assignment else {}
        expected_profile_digest = profile_ref.get("digest", lock_payload.get("profile_digest"))
        if not isinstance(expected_profile_digest, str):
            raise ControlPlaneError("merged lock has no current profile_digest authority")
        lock_currency = repository_lock_currency_at_ref(
            target_root,
            origin_ref,
            lock_bytes,
            Path(args.lock_compiler).resolve(),
            controller,
            repo=args.repo,
            profile_id=args.profile_id,
            profile_digest=expected_profile_digest,
        )
    phase = rollout_phase(
        recipe_bytes is not None,
        lock_bytes is not None,
        assignment.get("coverage_mode") if assignment else None,
        args.coverage_mode,
        lock_current=bool(lock_currency["current"]),
    )
    value: dict[str, Any] = {
        "schema": "pr-automation-coverage-plan/v2",
        "repo": args.repo,
        "phase": phase,
        "mutated": False,
    }
    if lock_bytes is not None:
        value["lock_currency"] = lock_currency
    if phase == "recipe":
        proposed = encoded(
            build_repository_recipe(
                args.repo, custom_argv=_qualified_custom_argv(dev_root, args.repo)
            )
        ).encode()
        value["diff"] = render_phase_diff("recipe", None, proposed)
    elif phase in {"lock", "relock"}:
        if not args.lock_compiler or not args.release_manifest:
            raise ControlPlaneError(f"{phase} planning requires --lock-compiler and --release-manifest")
        value["qualified_release"] = qualified_release or validate_qualified_release(
            Path(args.release_manifest).resolve(), controller
        )
        proposed, profile_digest = compile_repository_lock_at_ref(
            target_root,
            origin_ref,
            Path(args.lock_compiler).resolve(),
            controller,
            repo=args.repo,
            profile_id=args.profile_id,
        )
        value["profile_digest"] = profile_digest
        value["diff"] = render_phase_diff(phase, lock_bytes, proposed)
    elif phase == "assignment":
        if not args.lock_compiler or not args.release_manifest:
            raise ControlPlaneError(
                "assignment planning requires --lock-compiler and --release-manifest"
            )
        value["qualified_release"] = qualified_release or validate_qualified_release(
            Path(args.release_manifest).resolve(), controller
        )
        profile_digest = lock_payload.get("profile_digest")
        if not isinstance(profile_digest, str):
            raise ControlPlaneError("merged lock has no profile_digest")
        value["artifact_validation"] = lock_currency.get("artifact_validation")
        if not value["artifact_validation"]:
            raise ControlPlaneError("assignment planning requires a current v2 lock validation")
        proposed = propose_assignment(
            assignments,
            fleet,
            controller,
            repo=args.repo,
            coverage_mode="manual_only",
            profile_id=args.profile_id,
            profile_digest=profile_digest,
            artifacts_validated=True,
        )
        value["diff"] = render_phase_diff(
            "assignment", encoded(assignments).encode(), encoded(proposed).encode()
        )
    elif phase == "mode":
        profile_ref = assignment.get("profile_ref", {})
        proposed = propose_assignment(
            assignments,
            fleet,
            controller,
            repo=args.repo,
            coverage_mode=args.coverage_mode,
            profile_id=profile_ref.get("id", ""),
            profile_digest=profile_ref.get("digest", ""),
            artifacts_validated=True,
        )
        value["diff"] = render_phase_diff(
            "mode", encoded(assignments).encode(), encoded(proposed).encode()
        )
    else:
        value["diff"] = ""
        value["reason"] = (
            "merged recipe, v2/epoch lock, assignment, and requested mode are current; "
            "controller release policy/deploy binding is independent"
        )
    _emit(value)


def command_sync(args: argparse.Namespace) -> None:
    _assert_owner_go(args.operation_id, args.owner_go)
    dev_root = Path(args.dev_root).resolve()
    target_root = Path(args.target_root).resolve()
    controller_root = Path(args.controller_root).resolve()
    assignments, fleet, controller = _authorities(dev_root)
    target_metadata, _ = fetch_live_repository_metadata(fleet, args.repo)
    target_default_branch = target_metadata["default_branch"]
    target_origin_ref = f"origin/{target_default_branch}"
    _assert_origin(dev_root, "KleinPerkins/dev")
    _assert_origin(target_root, args.repo)
    _assert_origin_default_fresh(target_root, args.repo, target_default_branch)
    if args.phase in {"recipe", "lock", "relock"}:
        _assert_staging_worktree(target_root, args.repo, target_default_branch)
    else:
        dev_metadata, _ = fetch_live_repository_metadata(fleet, "KleinPerkins/dev")
        _assert_origin_default_fresh(
            dev_root,
            "KleinPerkins/dev",
            dev_metadata["default_branch"],
        )
        _assert_staging_worktree(
            dev_root,
            "KleinPerkins/dev",
            dev_metadata["default_branch"],
        )
    guard = _run_bind_guard(
        controller_root,
        [args.repo, "KleinPerkins/dev", "KleinPerkins/pr-automation-controller"],
    )
    if args.repo in _hard_exclusions(controller):
        raise ControlPlaneError(f"{args.repo} is a hard exclusion")
    qualified_release = validate_qualified_release(
        Path(args.release_manifest).resolve(), controller
    )

    recipe_bytes = _git_file_at(target_root, target_origin_ref, RECIPE)
    lock_bytes = _git_file_at(target_root, target_origin_ref, LOCK)
    assignment = next(
        (item for item in assignments["assignments"] if item["repo"] == args.repo),
        None,
    )
    lock_payload = _json_bytes(lock_bytes, LOCK).get("payload", {}) if lock_bytes else {}
    if not isinstance(lock_payload, dict):
        raise ControlPlaneError("merged lock payload must be an object")
    profile_ref = assignment.get("profile_ref", {}) if assignment else {}
    expected_profile_digest = profile_ref.get("digest", lock_payload.get("profile_digest"))
    lock_currency: dict[str, Any] = {"current": False, "reason": "no merged lock"}
    if lock_bytes is not None:
        if not isinstance(expected_profile_digest, str):
            raise ControlPlaneError("merged lock has no current profile_digest authority")
        lock_currency = repository_lock_currency_at_ref(
            target_root,
            target_origin_ref,
            lock_bytes,
            Path(args.lock_compiler).resolve(),
            controller,
            repo=args.repo,
            profile_id=args.profile_id,
            profile_digest=expected_profile_digest,
        )
    expected_phase = rollout_phase(
        recipe_bytes is not None,
        lock_bytes is not None,
        assignment.get("coverage_mode") if assignment else None,
        assignment.get("coverage_mode") if assignment else "manual_only",
        lock_current=bool(lock_currency["current"]),
    )
    if args.phase != expected_phase:
        raise ControlPlaneError(
            f"sync phase {args.phase} does not match merged state; expected {expected_phase}"
        )

    if args.phase == "recipe":
        path = target_root / RECIPE
        candidate = encoded(
            build_repository_recipe(
                args.repo, custom_argv=_qualified_custom_argv(dev_root, args.repo)
            )
        ).encode()
        profile_digest = None
    elif args.phase in {"lock", "relock"}:
        path = target_root / LOCK
        candidate, profile_digest = compile_repository_lock_at_ref(
            target_root,
            target_origin_ref,
            Path(args.lock_compiler).resolve(),
            controller,
            repo=args.repo,
            profile_id=args.profile_id,
        )
    else:
        profile_digest = lock_payload.get("profile_digest")
        if not isinstance(profile_digest, str):
            raise ControlPlaneError("merged lock has no profile_digest")
        validate_repository_artifacts_at_ref(
            target_root,
            target_origin_ref,
            Path(args.lock_compiler).resolve(),
            controller,
            repo=args.repo,
            profile_id=args.profile_id,
            profile_digest=profile_digest,
        )
        proposed = propose_assignment(
            assignments,
            fleet,
            controller,
            repo=args.repo,
            coverage_mode="manual_only",
            profile_id=args.profile_id,
            profile_digest=profile_digest,
            artifacts_validated=True,
        )
        path = _control_plane(dev_root) / "coverage-assignments.json"
        candidate = encoded(proposed).encode()

    claim_operation(OPERATION_ROOT, args.operation_id, f"sync:{args.phase}")
    atomic_write_bytes(path, candidate)
    changed_root = target_root if args.phase in {"recipe", "lock", "relock"} else dev_root
    assert_phase_change_set(args.phase, _git_changed_paths(changed_root))
    complete_operation(OPERATION_ROOT, args.operation_id)
    plan = build_sync_plan(args.repo, phase=args.phase, operation_id=args.operation_id)
    plan.update(
        {
            "bind_guard": guard,
            "profile_digest": profile_digest,
            "qualified_release": qualified_release,
            "staged": True,
            "note": "One phase is staged only; commit, push, and open its governed PR separately.",
        }
    )
    _emit(plan)


def verify_test_sharding_activation(dev_root, repository, repository_id, ref, assignment, proof, *, authority_branch):
    """Read-only owner preflight; no repository command enters controller execution."""
    path = dev_root / '_ops/bin/test-sharding.py'
    spec = importlib.util.spec_from_file_location('dev_test_sharding_activation', path)
    if spec is None or spec.loader is None:
        raise ControlPlaneError('test sharding authority unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        contract = module.validate_remote(repository, ref)
        if contract['required']:
            _assert_control_plane_merged(dev_root, authority_branch, include_sharding=True)
            authority = load_json(dev_root / '_ops/baseline/profiles/pr-automation/v3/test-sharding-coverage.json')
            module.controller_coverage(contract, authority, repository=repository, repository_id=repository_id,
                                       assignment=assignment, proof=proof)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        raise ControlPlaneError('test sharding activation refused: ' + str(error)) from error


def command_activate(args: argparse.Namespace) -> None:
    _assert_owner_go(args.operation_id, args.owner_go)
    dev_root = Path(args.dev_root).resolve()
    controller_root = Path(args.controller_root).resolve()
    _assert_origin(dev_root, "KleinPerkins/dev")
    guard = _run_bind_guard(
        controller_root,
        [args.repo, "KleinPerkins/dev", "KleinPerkins/pr-automation-controller"],
    )
    assignments, fleet, controller = _authorities(dev_root)
    controls = fetch_remote_repository_controls(fleet)
    if args.repo not in controls:
        raise ControlPlaneError(f"{args.repo} is not an enrolled fleet target")
    dev_default_branch = controls["KleinPerkins/dev"]["metadata"]["default_branch"]
    _assert_control_plane_merged(dev_root, dev_default_branch)
    qualified_release = validate_qualified_release(
        Path(args.release_manifest).resolve(), controller
    )
    if args.repo in _hard_exclusions(controller):
        raise ControlPlaneError(f"{args.repo} is a hard exclusion")
    assignment = _assignment_for(assignments, args.repo)
    artifact_validation = validate_remote_repository_artifacts(
        assignment,
        Path(args.lock_compiler).resolve(),
        controller,
        default_branch=controls[args.repo]["metadata"]["default_branch"],
    )
    verify_test_sharding_activation(
        dev_root, args.repo, controls[args.repo]['metadata']['repository_id'],
        controls[args.repo]['metadata']['default_branch'], assignment, artifact_validation,
        authority_branch=dev_default_branch,
    )
    has_required_checks = assignment.get("required_checks") is not None

    if args.phase == "stage":
        if has_required_checks:
            raise ControlPlaneError(
                "required-check activation must use the stage-requiredness/finalize-requiredness phases"
            )
        _assert_origin_default_fresh(
            dev_root,
            "KleinPerkins/dev",
            dev_default_branch,
        )
        _assert_staging_worktree(
            dev_root,
            "KleinPerkins/dev",
            dev_default_branch,
        )
        if assignment["coverage_mode"] == args.coverage_mode:
            raise ControlPlaneError("requested mode is already the merged assignment")
        profile_ref = assignment["profile_ref"]
        proposed = propose_assignment(
            assignments,
            fleet,
            controller,
            repo=args.repo,
            coverage_mode=args.coverage_mode,
            profile_id=profile_ref["id"],
            profile_digest=profile_ref["digest"],
            artifacts_validated=True,
        )
        claim_operation(OPERATION_ROOT, args.operation_id, "activate:stage")
        assignment_path = _control_plane(dev_root) / "coverage-assignments.json"
        atomic_write(assignment_path, encoded(proposed))
        assert_phase_change_set("stage", _git_changed_paths(dev_root))
        complete_operation(OPERATION_ROOT, args.operation_id)
        result = build_activation_plan(
            args.repo, phase="stage", operation_id=args.operation_id
        )
        result.update(
            {
                "coverage_mode": args.coverage_mode,
                "bind_guard": guard,
                "qualified_release": qualified_release,
                "artifact_validation": artifact_validation,
                "staged": True,
                "note": "Mode-only assignment change staged; commit, push, and owner-merge before transcription.",
            }
        )
        _emit(result)
        return

    if args.phase == "stage-requiredness":
        if not has_required_checks:
            raise ControlPlaneError("stage-requiredness requires a merged required-check assignment")
        if not args.recovery_operation_id:
            raise ControlPlaneError("stage-requiredness requires --recovery-operation-id")
        before = read_box_live_config(args.host)
        package = build_activation_package(
            before, assignments, fleet, controller, repo=args.repo
        )
        claim_operation(OPERATION_ROOT, args.operation_id, "activate:requiredness-stage")
        receipt = stage_requiredness_box_config(
            args.host,
            package.candidate,
            operation_id=args.operation_id,
            operation_root=OPERATION_ROOT,
            recovery_operation_id=args.recovery_operation_id,
        )
        _emit(
            {
                "schema": "pr-automation-requiredness-stage/v1",
                "changed": package.candidate != before,
                "repo": args.repo,
                "activation_generation": package.activation_generation,
                "prior_config_digest": _sha256_bytes(package.rollback),
                "candidate_digest": _sha256_bytes(package.candidate),
                "bind_guard": guard,
                "qualified_release": qualified_release,
                "artifact_validation": artifact_validation,
                **receipt,
            }
        )
        return

    if args.phase == "finalize-requiredness":
        if not has_required_checks:
            raise ControlPlaneError("finalize-requiredness requires a merged required-check assignment")
        if not args.recovery_operation_id:
            raise ControlPlaneError("finalize-requiredness requires --recovery-operation-id")
        before = read_box_live_config(args.host)
        package = build_activation_package(
            before, assignments, fleet, controller, repo=args.repo
        )
        if package.candidate != before:
            raise ControlPlaneError("requiredness finalization requires the box config to be staged first")
        claim_operation(OPERATION_ROOT, args.operation_id, "activate:requiredness-finalize")
        pre_resume_status = read_box_status(args.host)
        _assert_requiredness_staged_status(pre_resume_status)
        proof = doctor_coverage(
            before,
            assignments,
            fleet,
            controller,
            remote_controls=controls,
        )
        status = resume_box_controller(args.host)
        complete_requiredness_operation(OPERATION_ROOT, args.operation_id, status)
        _emit(
            {
                "schema": "pr-automation-requiredness-finalize/v1",
                "changed": False,
                "repo": args.repo,
                "activation_generation": package.activation_generation,
                "candidate_digest": _sha256_bytes(package.candidate),
                "bind_guard": guard,
                "qualified_release": qualified_release,
                "artifact_validation": artifact_validation,
                "doctor": proof,
                "status": status,
            }
        )
        return

    if assignment["coverage_mode"] != args.coverage_mode:
        raise ControlPlaneError(
            "requested mode does not match the merged coverage-assignments.json authority"
        )
    before = read_box_live_config(args.host)
    package = build_activation_package(
        before, assignments, fleet, controller, repo=args.repo
    )
    claim_operation(OPERATION_ROOT, args.operation_id, "activate:transcribe")
    if has_required_checks:
        raise ControlPlaneError(
            "required-check activation final parity requires stage-requiredness/finalize-requiredness"
        )
    if package.candidate == before:
        complete_operation(OPERATION_ROOT, args.operation_id)
        _emit(
            {
                "schema": "pr-automation-coverage-activation/v1",
                "changed": False,
                "reason": "box config already matches the merged dev assignment authority",
                "bind_guard": guard,
                "qualified_release": qualified_release,
                "artifact_validation": artifact_validation,
            }
        )
        return
    receipt = transcribe_box_config(
        args.host, package.candidate, operation_id=args.operation_id
    )
    after = read_box_live_config(args.host)
    proof = doctor_coverage(
        after,
        assignments,
        fleet,
        controller,
        remote_controls=controls,
    )
    if _decode_live_config(after).get("activation_generation") != package.activation_generation:
        raise ControlPlaneError("post-activation generation changed")
    complete_operation(OPERATION_ROOT, args.operation_id)
    _emit(
        {
            "schema": "pr-automation-coverage-activation/v1",
            "changed": True,
            "repo": args.repo,
            "coverage_mode": args.coverage_mode,
            "activation_generation": package.activation_generation,
            "prior_config_digest": _sha256_bytes(package.rollback),
            "new_config_digest": _sha256_bytes(after),
            "bind_guard": guard,
            "qualified_release": qualified_release,
            "artifact_validation": artifact_validation,
            "doctor": proof,
            **receipt,
        }
    )


def command_doctor(args: argparse.Namespace) -> None:
    dev_root = Path(args.dev_root).resolve()
    assignments, fleet, controller = _authorities(dev_root)
    live = _read_live(args)
    controls = fetch_remote_repository_controls(fleet)
    proof = doctor_coverage(
        live,
        assignments,
        fleet,
        controller,
        remote_controls=controls,
    )
    compiler = Path(args.lock_compiler).resolve()
    proof["qualified_release"] = validate_qualified_release(
        Path(args.release_manifest).resolve(), controller
    )
    proof["repository_parity"] = [
        {
            "repo": assignment["repo"],
            **validate_remote_repository_artifacts(
                assignment,
                compiler,
                controller,
                default_branch=controls[assignment["repo"]]["metadata"][
                    "default_branch"
                ],
            ),
        }
        for assignment in assignments["assignments"]
    ]
    if args.live_config:
        proof["box"] = "not_requested_for_local_snapshot"
    else:
        proof["box"] = {
            "status": read_box_json(args.host, _box_command("status", "--json")),
            "doctor": read_box_json(args.host, _box_command("doctor", "--live", "--json")),
        }
    # A4 (gen3-m4-actions-retirement-steady-state-v3.md §5): prove the fleet-wide Actions-pause
    # invariant alongside coverage/repository parity -- doctor fails closed on drift just like it
    # already does for coverage-projection and repository-artifact drift above.
    controller_default_branch = controls[CONTROLLER_REPO]["metadata"]["default_branch"]
    actions_paused = check_fleet_actions_paused(
        _fleet_repos(fleet),
        controller_default_branch=controller_default_branch,
    )
    proof["actions_paused"] = actions_paused
    if not actions_paused["ok"]:
        fail(
            "fleet Actions-pause drift detected (A4, check-fleet-actions-paused.sh):\n"
            + (actions_paused["stderr"] or "no diagnostic")
        )
    _emit(proof)


def command_rollback(args: argparse.Namespace) -> None:
    if args.execute != "ROLLBACK":
        raise ControlPlaneError("rollback refused: pass --execute ROLLBACK exactly")
    before = read_box_json(args.host, _box_command("status", "--json"))
    receipt = read_box_json(
        args.host,
        " ".join(["sudo", "-u", REMOTE_USER, "-H", *rollback_command(REMOTE_BINARY)]),
    )
    after = read_box_json(args.host, _box_command("status", "--json"))
    validate_rollback_receipt(before, receipt, after)
    _emit(
        {
            "schema": "pr-automation-coverage-rollback/v1",
            "path": "Commands::RollBack",
            "receipt": receipt,
            "after": after,
        }
    )


def command_resolve_merge_safety(args: argparse.Namespace) -> None:
    assignments = load_json(HERE / "coverage-assignments.json")
    fleet = load_json(HERE / "fleet.json")
    controller = load_json(HERE / "controller.json")
    projection = resolve_repository_projection(
        assignments,
        fleet,
        controller,
        repository_id=args.repository_id,
        repo=args.repo,
        default_branch=args.default_branch,
    )
    if args.output == "ruleset":
        print(encoded(projection.ruleset), end="")
    elif args.output == "runtime-app-visible":
        print(json.dumps(projection.runtime_app_visible_fingerprints, sort_keys=True))
    elif args.output == "operator-full":
        print(json.dumps(projection.operator_full_fingerprints, sort_keys=True))
    else:
        raise AssertionError(f"unhandled projection output: {args.output}")


def command_resolve_fleet_target(args: argparse.Namespace) -> None:
    fleet = load_json(HERE / "fleet.json")
    target = resolve_fleet_target(
        fleet,
        repository_id=args.repository_id,
        repo=args.repo,
    )
    if args.default_branch != target["default_branch"]:
        raise ControlPlaneError(
            f"{args.repo} live default branch {args.default_branch!r} differs from "
            f"fleet authority {target['default_branch']!r}"
        )
    _emit(
        {
            "repo": target["repo"],
            "repository_id": target["repository_id"],
            "default_branch": target["default_branch"],
            "merge_safety_ruleset_id": target["merge_safety_ruleset_id"],
        }
    )


def command_record_created_ruleset(args: argparse.Namespace) -> None:
    record_created_ruleset_identity(
        HERE / "fleet.json",
        repository_id=args.repository_id,
        repo=args.repo,
        ruleset_id=args.ruleset_id,
    )
    _emit(
        {
            "repo": args.repo,
            "repository_id": args.repository_id,
            "merge_safety_ruleset_id": args.ruleset_id,
            "fleet_path": str(HERE / "fleet.json"),
        }
    )


def command_verify_applied_ruleset(args: argparse.Namespace) -> None:
    assignments = load_json(HERE / "coverage-assignments.json")
    fleet = load_json(HERE / "fleet.json")
    controller = load_json(HERE / "controller.json")
    projection = resolve_repository_projection(
        assignments,
        fleet,
        controller,
        repository_id=args.repository_id,
        repo=args.repo,
        default_branch=args.default_branch,
    )
    observed = load_json(Path(args.observed_ruleset).resolve())
    proof = validate_applied_ruleset_semantics(
        observed,
        projection.ruleset,
        expected_ruleset_id=args.ruleset_id,
        expected_repo=args.repo,
    )
    _emit(proof)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="repo-baseline.sh profile pr-automation v3",
        description="Runnerless v3 contracts and owner-gated coverage control plane.",
    )
    commands = result.add_subparsers(dest="command", required=True)
    stage_command = commands.add_parser("stage")
    stage_command.add_argument("--repo-root", required=True)
    stage_command.add_argument("--repository-id", type=int, required=True)
    stage_command.add_argument("--owner", default="KleinPerkins")
    stage_command.add_argument("--name")
    stage_command.add_argument("--default-branch", required=True)
    stage_command.add_argument("--activation-generation", type=int, required=True)
    verify_command = commands.add_parser("verify")
    verify_command.add_argument("--repo-root", required=True)
    commands.add_parser("verify-control-plane")
    verify_remote = commands.add_parser(
        "verify-fleet-remote",
        help="Read-only policy parity plus exact v2/epoch Rust lock validation",
    )
    verify_remote.add_argument("--lock-compiler", required=True)
    resolve = commands.add_parser(
        "resolve-merge-safety",
        help="Resolve one repository's template-derived ruleset or fingerprint layer",
    )
    resolve.add_argument("--repository-id", type=int, required=True)
    resolve.add_argument("--repo", required=True)
    resolve.add_argument("--default-branch", required=True)
    resolve.add_argument(
        "--output",
        choices=["ruleset", "runtime-app-visible", "operator-full"],
        default="ruleset",
    )
    resolve_target = commands.add_parser(
        "resolve-fleet-target",
        help="Resolve one live ID/full-name/default-branch tuple against fleet authority",
    )
    resolve_target.add_argument("--repository-id", type=int, required=True)
    resolve_target.add_argument("--repo", required=True)
    resolve_target.add_argument("--default-branch", required=True)
    record_ruleset = commands.add_parser(
        "record-created-ruleset",
        help="Atomically bind an explicit creation result into fleet authority",
    )
    record_ruleset.add_argument("--repository-id", type=int, required=True)
    record_ruleset.add_argument("--repo", required=True)
    record_ruleset.add_argument("--ruleset-id", type=int, required=True)
    verify_applied = commands.add_parser(
        "verify-applied-ruleset",
        help="Compare one exact owner-visible reread with the shared ruleset resolver",
    )
    verify_applied.add_argument("--repository-id", type=int, required=True)
    verify_applied.add_argument("--repo", required=True)
    verify_applied.add_argument("--default-branch", required=True)
    verify_applied.add_argument("--ruleset-id", type=int, required=True)
    verify_applied.add_argument("--observed-ruleset", required=True)

    def dev_root(command: argparse.ArgumentParser) -> None:
        command.add_argument("--dev-root", default=str(HERE.parents[4]))

    def live_source(command: argparse.ArgumentParser) -> None:
        command.add_argument("--live-config")
        command.add_argument("--host", default=REMOTE_HOST)

    view = commands.add_parser("view", help="Read box/dev/repository coverage parity")
    dev_root(view)
    live_source(view)
    view.add_argument("--lock-compiler")

    plan = commands.add_parser("plan", help="Show exact non-mutating assignment/config diffs")
    dev_root(plan)
    live_source(plan)
    plan.add_argument("--repo", required=True)
    plan.add_argument("--coverage-mode", choices=sorted(COVERAGE_MODES), required=True)
    plan.add_argument("--profile-id", required=True)
    plan.add_argument("--target-root", required=True)
    plan.add_argument("--lock-compiler")
    plan.add_argument("--release-manifest")

    sync = commands.add_parser("sync", help="Stage one serial recipe, lock, relock, or assignment phase")
    dev_root(sync)
    sync.add_argument("--controller-root", default=str(Path.home() / "dev/personal/pr-automation-controller"))
    sync.add_argument("--repo", required=True)
    sync.add_argument("--phase", choices=["recipe", "lock", "relock", "assignment"], required=True)
    sync.add_argument("--profile-id", required=True)
    sync.add_argument("--target-root", required=True)
    sync.add_argument("--lock-compiler", required=True)
    sync.add_argument("--release-manifest", required=True)
    sync.add_argument("--operation-id", required=True)
    sync.add_argument("--owner-go", required=True)

    activate = commands.add_parser(
        "activate",
        help=(
            "Stage a mode-only PR, transcribe an ordinary merged assignment, "
            "or stage/finalize a required-check activation"
        ),
    )
    dev_root(activate)
    activate.add_argument(
        "--controller-root", default=str(Path.home() / "dev/personal/pr-automation-controller")
    )
    activate.add_argument("--host", default=REMOTE_HOST)
    activate.add_argument("--repo", required=True)
    activate.add_argument(
        "--phase",
        choices=["stage", "transcribe", "stage-requiredness", "finalize-requiredness"],
        required=True,
    )
    activate.add_argument("--coverage-mode", choices=sorted(COVERAGE_MODES), required=True)
    activate.add_argument("--lock-compiler", required=True)
    activate.add_argument("--release-manifest", required=True)
    activate.add_argument("--operation-id", required=True)
    activate.add_argument(
        "--recovery-operation-id",
        default="",
        help="Required for stage-requiredness/finalize-requiredness recovery receipts",
    )
    activate.add_argument("--owner-go", required=True)

    doctor = commands.add_parser("doctor", help="Prove control-plane and coverage parity")
    dev_root(doctor)
    live_source(doctor)
    doctor.add_argument("--lock-compiler", required=True)
    doctor.add_argument("--release-manifest", required=True)

    rollback = commands.add_parser(
        "rollback", help="Run the local S30 Commands::RollBack box path"
    )
    rollback.add_argument("--host", default=REMOTE_HOST)
    rollback.add_argument("--execute", required=True)
    return result


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {
        "verify", "verify-control-plane", "verify-fleet-remote", "resolve-merge-safety",
        "resolve-fleet-target", "verify-applied-ruleset", "view", "doctor", "--help", "-h"
    }:
        raise SystemExit("REFUSED: retired controller mutation; historical inspection only")

    args = parser().parse_args()
    try:
        if args.command == "stage":
            stage(args)
        elif args.command == "verify":
            verify_repository(Path(args.repo_root).resolve())
        elif args.command == "verify-control-plane":
            verify_control_plane()
        elif args.command == "verify-fleet-remote":
            verify_fleet_remote(Path(args.lock_compiler).resolve())
        elif args.command == "resolve-merge-safety":
            command_resolve_merge_safety(args)
        elif args.command == "resolve-fleet-target":
            command_resolve_fleet_target(args)
        elif args.command == "record-created-ruleset":
            command_record_created_ruleset(args)
        elif args.command == "verify-applied-ruleset":
            command_verify_applied_ruleset(args)
        elif args.command == "view":
            command_view(args)
        elif args.command == "plan":
            command_plan(args)
        elif args.command == "sync":
            command_sync(args)
        elif args.command == "activate":
            command_activate(args)
        elif args.command == "doctor":
            command_doctor(args)
        elif args.command == "rollback":
            command_rollback(args)
        else:
            raise AssertionError(f"unhandled command: {args.command}")
    except ControlPlaneError as exc:
        fail(str(exc))


if __name__ == "__main__":
    main()
