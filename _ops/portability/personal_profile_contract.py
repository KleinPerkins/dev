"""Bounded pure projection from current runnerless v3 owner definitions.

Source: KleinPerkins/dev at 9ac8369944f45b9e3f5e8d455ee03fad191cfd74,
profile.py blob 35587bb4afc9b4c75b6bc1c5dbce6f172991363a.
Only _render_base_ruleset, resolve_repository_projection and validate_policy
adapt I/O to explicit template/authority inputs. No filesystem, network or
lifecycle authority is present. Other definitions retain exact owner bodies.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
from typing import Any, NamedTuple
MAX_DEFAULT_BRANCH_BYTES=100
MAX_NODE_JOB_ID_BYTES=100-len("pr-automation / job:")
HARD_EXCLUSION="chaos-scheduler"
COVERAGE_MODES={"manual_only","shadow","local"}
CHECK="pr-automation / verify"
PROTECTED_PATHS=[".github","CODEOWNERS","_ops"]
RELEASE_DIGEST="sha256:3d0b6b34d29b6d0c9ae94daa8dd4cd1182ae3bb9375944322c58febc52fec07c"
EXECUTION_IMAGE_REF="buildpack-deps@sha256:877e9e4d949edfbcbedabc3a2d7ab593955fee5d6d0777adf3a991eb30c750d8"
MEMORY_MIB=512

class ControlPlaneError(RuntimeError):
    """A closed control-plane request failed before any mutation."""


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


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


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


def _render_base_ruleset(default_branch: str, source: str) -> dict[str, Any]:
    validate_default_branch(default_branch)
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


def require_exact_keys(value: dict[str, Any], expected: set[str], source: str) -> None:
    actual = set(value)
    if actual != expected:
        fail(f"{source}: keys differ; missing={sorted(expected - actual)} extra={sorted(actual - expected)}")


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
    template_source: str,
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
    ruleset = _render_base_ruleset(default_branch, template_source)
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


def validate_policy(
    value: dict[str, Any],
    source: str,
    *,
    assignments: dict[str, Any],
    fleet: dict[str, Any],
    controller: dict[str, Any],
    template_source: str,
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
    try:
        projection = resolve_repository_projection(
            assignments,
            fleet,
            controller,
            repository_id=value["repository_id"],
            repo=f"{value['owner']}/{value['name']}",
            default_branch=value["default_branch"],
            template_source=template_source,
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
