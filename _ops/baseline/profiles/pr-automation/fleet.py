#!/usr/bin/env python3
"""PR Automation Phase B fleet lifecycle.

The Phase A engine remains in profile.py. This module owns the paired-ruleset,
App-controller lifecycle and records secret-free source-tracked state in dev.
"""
from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote


HERE = Path(__file__).resolve().parent
DEV_ROOT = HERE.parents[3]
CONFIG_SOURCE = HERE / "phase-b.config.json"
CONFIG_SCHEMA = HERE / "phase-b.config.schema.json"
FLEET_SOURCE = HERE / "fleet.json"
FLEET_SCHEMA = HERE / "fleet.schema.json"
EVIDENCE_SCHEMA = HERE / "phase-b.evidence.schema.json"
STATE_SCHEMA = HERE / "phase-b.state.schema.json"
CONTROLLER_TEMPLATE = HERE / "controller.yml.tmpl"
CODEOWNERS_BLOCK = HERE / "CODEOWNERS.block"
REVIEW_TEMPLATE = HERE / "review-gate.ruleset.json.tmpl"
SAFETY_TEMPLATE = HERE / "merge-safety.ruleset.json.tmpl"
WORKFLOW_SOURCE = HERE / "required.yml"
STATE_DIR = HERE / "state" / "v2"
CONFIG_REL = Path(".github/pr-automation.json")
CONTROLLER_REL = Path(".github/workflows/controller.yml")
CODEOWNERS_REL = Path(".github/CODEOWNERS")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
FULL_DIGEST = re.compile(r"^[0-9a-f]{64}$")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
MUTATING_VERBS = {
    "apply",
    "credential-provision",
    "credential-revoke",
    "enforce-canary",
    "activate-canary",
    "qualify",
    "promote",
    "pause",
    "repair",
    "rollback",
    "activate",
}
REMOTE_MUTATING_VERBS = MUTATING_VERBS - {"apply"}
REMOTE_LOCK_VARIABLE = "PR_AUTOMATION_FLEET_LOCK"
REMOTE_STATE_VARIABLE = "PR_AUTOMATION_FLEET_STATE"
SAFE_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_REMOTE_LOCK_CONTEXT: dict[str, Any] | None = None
SCENARIOS = (
    "disabled_bootstrap",
    "suite_spoof",
    "duplicate_check",
    "missing_check",
    "skipped_check",
    "neutral_check",
    "red_check",
    "exact_bot_identity",
    "protected_add",
    "protected_delete",
    "protected_rename",
    "file_count_refusal",
    "head_race_h1",
    "head_race_h2",
    "base_race",
    "stale_approval",
    "native_arm",
    "idempotent_rerun",
    "direct_fallback",
    "break_glass",
    "workflow_disable_drain",
    "pair_rollback_recreate",
    "draft_conflict_untrusted",
    "final_zero_residual",
)
MOCKABLE_SCENARIOS: frozenset[str] = frozenset()

_spec = importlib.util.spec_from_file_location("phase_a_profile", HERE / "profile.py")
assert _spec and _spec.loader
phase_a = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(phase_a)


class FleetError(RuntimeError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: Any) -> str:
    data = value if isinstance(value, str) else canonical(value)
    return hashlib.sha256(data.encode()).hexdigest()


def validate_branch_name(branch: str) -> str:
    if (
        not SAFE_BRANCH.fullmatch(branch)
        or ".." in branch
        or "//" in branch
        or "@{" in branch
        or branch.endswith(("/", "."))
        or branch.startswith("-")
    ):
        raise FleetError(f"unsafe or unsupported branch name: {branch!r}")
    checked = run(["git", "check-ref-format", f"refs/heads/{branch}"], check=False)
    if checked.returncode != 0:
        raise FleetError(f"invalid branch name: {branch!r}")
    return branch


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise FleetError(f"invalid JSON at {path}: {exc}") from exc


def policy() -> dict[str, Any]:
    value = load_json(CONFIG_SOURCE)
    required = {
        "schema",
        "profile",
        "controller",
        "required_workflow",
        "rulesets",
        "settings",
        "protected_paths",
        "self_enrollment",
        "hard_exclusions",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise FleetError("Phase B policy does not match its closed schema")
    if value["schema"] != "pr-automation/v2":
        raise FleetError("Phase B policy schema must be pr-automation/v2")
    if value["hard_exclusions"] != ["KleinPerkins/chaos-scheduler"]:
        raise FleetError("hard exclusion must be exactly KleinPerkins/chaos-scheduler")
    if "KleinPerkins/dev" not in value["self_enrollment"]:
        raise FleetError("dev self-enrollment must be explicit")
    if value["required_workflow"]["integration_id"] != 15368:
        raise FleetError("required check must bind GitHub Actions integration 15368")
    expected_codeowners = (
        "# BEGIN KleinPerkins/dev pr-automation protected paths (managed; do not hand-edit)\n"
        + "\n".join(f"/{path} @KleinPerkins" for path in value["protected_paths"])
        + "\n# END KleinPerkins/dev pr-automation protected paths\n"
    )
    if CODEOWNERS_BLOCK.read_text() != expected_codeowners:
        raise FleetError("CODEOWNERS block differs from canonical protected-path policy")
    return value


def fleet() -> dict[str, Any]:
    value = load_json(FLEET_SOURCE)
    if value.get("schema") != "pr-automation-fleet/v2":
        raise FleetError("fleet manifest schema mismatch")
    targets = [entry["repo"] for entry in value.get("targets", [])]
    excluded = [entry["repo"] for entry in value.get("excluded", [])]
    if len(targets) != len(set(targets)):
        raise FleetError("fleet manifest contains duplicate targets")
    if set(targets) & set(excluded):
        raise FleetError("fleet target/excluded classes overlap")
    if "KleinPerkins/chaos-scheduler" not in excluded:
        raise FleetError("fleet manifest omits hard exclusion")
    return value


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    stdin=None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        stdin=stdin,
        text=False if stdin is not None else True,
        capture_output=True,
    )
    if check and result.returncode:
        stderr = result.stderr.decode(errors="replace") if isinstance(result.stderr, bytes) else result.stderr
        stdout = result.stdout.decode(errors="replace") if isinstance(result.stdout, bytes) else result.stdout
        raise FleetError(f"command failed ({' '.join(args)}): {(stderr or stdout).strip()}")
    return result


def git(repo: Path, *args: str, check: bool = True) -> str:
    return str(run(["git", "-C", str(repo), *args], check=check).stdout).strip()


def resolve_repo(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise FleetError(f"repository directory missing: {path}")
    top = git(path, "rev-parse", "--show-toplevel")
    return Path(top).resolve()


def owner_repo(repo: Path) -> str:
    remote = git(repo, "config", "--get", "remote.origin.url", check=False)
    match = re.search(r"github\.com(?::|/)([^/]+)/([^/]+?)(?:\.git)?$", remote)
    if not match:
        raise FleetError("origin must be a GitHub repository")
    return f"{match.group(1)}/{match.group(2)}"


def validate_target(repo: Path, *, clean: bool, allow_unlisted_apply: bool = False) -> str:
    ownerrepo = owner_repo(repo)
    cfg = policy()
    manifest = fleet()
    lowered_ownerrepo = ownerrepo.lower()
    hard_exclusions = {item.lower() for item in cfg["hard_exclusions"]}
    allowed = {
        item["repo"].lower()
        for group in ("targets", "already_compliant")
        for item in manifest[group]
    }
    excluded = {item["repo"].lower() for item in manifest["excluded"]}
    if lowered_ownerrepo in hard_exclusions:
        raise FleetError("refusing hard-excluded KleinPerkins/chaos-scheduler")
    if lowered_ownerrepo in excluded or (
        lowered_ownerrepo not in allowed and not allow_unlisted_apply
    ):
        raise FleetError(f"repository is not an authorized Phase B fleet target: {ownerrepo}")
    if ownerrepo.split("/", 1)[0].lower() != "kleinperkins":
        raise FleetError(f"refusing non-KleinPerkins repository: {ownerrepo}")
    if repo == DEV_ROOT and lowered_ownerrepo not in {
        item.lower() for item in cfg["self_enrollment"]
    }:
        raise FleetError("dev requires explicit self-enrollment policy")
    if "/affirm/" in str(repo).lower():
        raise FleetError("refusing Affirm/governed working tree")
    branch = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if not branch:
        raise FleetError("refusing detached HEAD")
    if clean and git(repo, "status", "--porcelain"):
        raise FleetError("refusing dirty working tree")
    return ownerrepo


def require_gh() -> None:
    if not shutil.which("gh"):
        raise FleetError("gh CLI unavailable")
    run(["gh", "auth", "status"])


def gh_api(
    endpoint: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    paginate: bool = False,
) -> Any:
    method = method.upper()
    args = ["gh", "api"]
    if method != "GET":
        args += ["-X", method]
    if paginate:
        if method != "GET":
            raise FleetError("pagination is read-only")
        args += ["--paginate", "--slurp"]
    args.append(endpoint)
    temporary: Path | None = None
    try:
        if payload is not None:
            fd, name = tempfile.mkstemp(prefix="phase-b-", suffix=".json")
            os.close(fd)
            temporary = Path(name)
            temporary.write_text(json.dumps(payload))
            args += ["--input", str(temporary)]
        result = run(args)
        output = str(result.stdout).strip()
        return json.loads(output) if output else None
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def set_remote_state_value(ownerrepo: str, value: str | None) -> None:
    if value is None:
        result = run(
            [
                "gh",
                "variable",
                "delete",
                REMOTE_STATE_VARIABLE,
                "--repo",
                ownerrepo,
            ],
            check=False,
        )
        if result.returncode != 0:
            check = run(
                [
                    "gh",
                    "api",
                    f"repos/{ownerrepo}/actions/variables/{REMOTE_STATE_VARIABLE}",
                ],
                check=False,
            )
            if check.returncode == 0:
                raise FleetError("failed to remove remote state marker")
        return
    run(
        [
            "gh",
            "variable",
            "set",
            REMOTE_STATE_VARIABLE,
            "--repo",
            ownerrepo,
            "--body",
            value,
        ]
    )
    remote = gh_api(f"repos/{ownerrepo}/actions/variables/{REMOTE_STATE_VARIABLE}")
    if not isinstance(remote, dict) or remote.get("value") != value:
        raise FleetError("remote state marker postcondition failed")


def local_state_marker(ownerrepo: str) -> str | None:
    path = state_path(ownerrepo)
    if not path.exists():
        return None
    value = load_json(path)
    validate_state(value, ownerrepo=ownerrepo)
    return state_marker(value)


def reconcile_remote_state_value(ownerrepo: str, remote_value: str | None) -> str | None:
    if remote_value is None:
        return None
    try:
        parsed = json.loads(remote_value)
    except json.JSONDecodeError as exc:
        raise FleetError("remote state marker is malformed") from exc
    if isinstance(parsed, dict) and set(parsed) == {"transition"}:
        transition = parsed["transition"]
        if not isinstance(transition, dict) or set(transition) != {"from", "to"}:
            raise FleetError("remote state transition marker is malformed")
        local = local_state_marker(ownerrepo)
        if local == transition["to"]:
            resolved = transition["to"]
        elif local == transition["from"]:
            resolved = transition["from"]
        else:
            raise FleetError("remote state transition does not match local pre/postimage")
        set_remote_state_value(ownerrepo, resolved)
        return resolved
    if (
        not isinstance(parsed, dict)
        or set(parsed) != {"revision", "digest"}
        or type(parsed.get("revision")) is not int
        or parsed["revision"] < 1
        or not FULL_DIGEST.fullmatch(str(parsed.get("digest") or ""))
    ):
        raise FleetError("remote state marker is malformed")
    return remote_value


@contextmanager
def remote_repo_lock(ownerrepo: str, operation: str) -> Iterator[None]:
    """Serialize remote mutations across machines using an atomic Actions-variable create."""
    endpoint = f"repos/{ownerrepo}/actions/variables"
    item_endpoint = f"{endpoint}/{REMOTE_LOCK_VARIABLE}"
    token = json.dumps(
        {
            "operation": operation,
            "operation_id": str(uuid.uuid4()),
            "started_at": now(),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    try:
        gh_api(
            endpoint,
            method="POST",
            payload={"name": REMOTE_LOCK_VARIABLE, "value": token},
        )
    except FleetError as exc:
        current = run(["gh", "api", item_endpoint], check=False)
        detail = ""
        if current.returncode == 0:
            try:
                metadata = json.loads(str(current.stdout))
                detail = f"; existing lock={metadata.get('value')}"
            except json.JSONDecodeError:
                detail = "; existing lock metadata is malformed"
        raise FleetError(
            f"remote one-writer lock unavailable for {ownerrepo}{detail}; "
            "inspect and recover it explicitly before retrying"
        ) from exc
    global _REMOTE_LOCK_CONTEXT
    active_error: BaseException | None = None
    try:
        state_endpoint = f"{endpoint}/{REMOTE_STATE_VARIABLE}"
        state_result = run(["gh", "api", state_endpoint], check=False)
        remote_state = None
        if state_result.returncode == 0:
            try:
                remote_state = json.loads(str(state_result.stdout)).get("value")
            except (json.JSONDecodeError, AttributeError) as exc:
                raise FleetError("remote state marker is malformed") from exc
        remote_state = reconcile_remote_state_value(ownerrepo, remote_state)
        _REMOTE_LOCK_CONTEXT = {
            "owner_repo": ownerrepo,
            "state_marker": remote_state,
        }
        yield
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        try:
            current = gh_api(item_endpoint)
            if not isinstance(current, dict) or current.get("value") != token:
                raise FleetError(
                    f"remote one-writer lock ownership drifted for {ownerrepo}; refusing delete"
                )
            gh_api(item_endpoint, method="DELETE")
        except Exception as exc:
            if active_error is not None:
                print(f"warning: remote lock release also failed: {exc}", file=sys.stderr)
            else:
                raise
        finally:
            _REMOTE_LOCK_CONTEXT = None


def paginated(endpoint: str) -> list[dict[str, Any]]:
    pages = gh_api(endpoint, paginate=True)
    if not isinstance(pages, list):
        raise FleetError(f"paginated response is not a list: {endpoint}")
    items = [item for page in pages for item in page] if pages and all(
        isinstance(page, list) for page in pages
    ) else pages
    if not all(isinstance(item, dict) for item in items):
        raise FleetError(f"paginated response contains non-objects: {endpoint}")
    return items


def normalize_ruleset(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    rules = []
    for raw in value.get("rules", []):
        rule: dict[str, Any] = {"type": raw.get("type"), "parameters": None}
        params = raw.get("parameters")
        if raw.get("type") == "pull_request":
            params = params or {}
            rule["parameters"] = {
                "allowed_merge_methods": sorted(params.get("allowed_merge_methods", [])),
                "dismiss_stale_reviews_on_push": params.get("dismiss_stale_reviews_on_push"),
                "require_code_owner_review": params.get("require_code_owner_review"),
                "require_last_push_approval": params.get("require_last_push_approval"),
                "required_approving_review_count": params.get("required_approving_review_count"),
                "required_review_thread_resolution": params.get(
                    "required_review_thread_resolution"
                ),
                "required_reviewers": params.get("required_reviewers", []),
            }
        elif raw.get("type") == "required_status_checks":
            params = params or {}
            rule["parameters"] = {
                "do_not_enforce_on_create": params.get("do_not_enforce_on_create"),
                "required_status_checks": sorted(
                    params.get("required_status_checks", []),
                    key=canonical,
                ),
                "strict_required_status_checks_policy": params.get(
                    "strict_required_status_checks_policy"
                ),
            }
        rules.append(rule)
    conditions = value.get("conditions", {}).get("ref_name", {})
    return {
        "name": value.get("name"),
        "target": value.get("target"),
        "enforcement": value.get("enforcement"),
        "bypass_actors": sorted(value.get("bypass_actors", []), key=canonical),
        "conditions": {
            "ref_name": {
                "include": sorted(conditions.get("include", [])),
                "exclude": sorted(conditions.get("exclude", [])),
            }
        },
        "rules": sorted(rules, key=lambda item: (str(item.get("type")), canonical(item))),
    }


def render_rulesets(branch: str) -> dict[str, dict[str, Any]]:
    branch = validate_branch_name(branch)
    cfg = policy()
    review = json.loads(
        REVIEW_TEMPLATE.read_text().replace("{{TARGET_BRANCH}}", branch)
    )
    safety = json.loads(
        SAFETY_TEMPLATE.read_text()
        .replace("{{TARGET_BRANCH}}", branch)
        .replace("{{REQUIRED_CHECK_CONTEXT}}", cfg["required_workflow"]["context"])
        .replace(
            "{{REQUIRED_INTEGRATION_ID}}",
            str(cfg["required_workflow"]["integration_id"]),
        )
    )
    return {"merge_safety": safety, "review_gate": review}


def template_digests() -> dict[str, str]:
    return {
        "merge_safety": digest(SAFETY_TEMPLATE.read_text()),
        "review_gate": digest(REVIEW_TEMPLATE.read_text()),
    }


def render_policy(
    ownerrepo: str,
    base_branch: str,
    *,
    workflow_name: str | None = None,
    workflow_path: str | None = None,
) -> dict[str, Any]:
    base_branch = validate_branch_name(base_branch)
    if workflow_name is not None and not re.fullmatch(
        r"[A-Za-z0-9 ._-]+", workflow_name
    ):
        raise FleetError("required workflow name contains unsupported characters")
    if workflow_path is not None and not re.fullmatch(
        r"\.github/workflows/[A-Za-z0-9._/-]+\.ya?ml", workflow_path
    ):
        raise FleetError("required workflow path is unsupported")
    cfg = copy.deepcopy(policy())
    cfg.pop("self_enrollment")
    cfg.pop("hard_exclusions")
    cfg["repository"] = {"owner_repo": ownerrepo, "base_branch": base_branch}
    if workflow_name:
        cfg["required_workflow"]["name"] = workflow_name
    if workflow_path:
        cfg["required_workflow"]["path"] = workflow_path
    cfg["template_digests"] = template_digests()
    return cfg


def policy_for_branch(config: dict[str, Any], branch: str) -> dict[str, Any]:
    rendered = copy.deepcopy(config)
    rendered["repository"]["base_branch"] = validate_branch_name(branch)
    return rendered


def protected_path_jq(paths: list[str]) -> str:
    expressions = []
    for path in paths:
        if path.endswith("/**") and path.count("**") == 1:
            expressions.append(f"startswith({json.dumps(path[:-2])})")
        elif "*" not in path:
            expressions.append(f".=={json.dumps(path)}")
        else:
            raise FleetError(f"unsupported protected-path pattern: {path}")
    if not expressions:
        raise FleetError("protected-path policy must not be empty")
    return "\n              or ".join(expressions)


def render_controller(config: dict[str, Any]) -> str:
    base = config["repository"]["base_branch"]
    pairs = render_rulesets(base)
    replacements = {
        "REQUIRED_WORKFLOW_NAME": config["required_workflow"]["name"],
        "REQUIRED_WORKFLOW_PATH": config["required_workflow"]["path"],
        "REQUIRED_CHECK_CONTEXT": config["required_workflow"]["context"],
        "REQUIRED_INTEGRATION_ID": str(config["required_workflow"]["integration_id"]),
        "PR_AUTHOR_ALLOWLIST": " ".join(config["controller"]["author_allowlist"]),
        "BASE_BRANCH": base,
        "REVIEW_GATE_NAME": config["rulesets"]["review_gate"],
        "MERGE_SAFETY_NAME": config["rulesets"]["merge_safety"],
        "BOT_LOGIN": config["controller"]["bot_login"],
        "PROTECTED_PATH_JQ": protected_path_jq(config["protected_paths"]),
        "REVIEW_GATE_FINGERPRINT": digest(
            normalize_ruleset(pairs["review_gate"])
        ),
        "MERGE_SAFETY_FINGERPRINT": digest(
            normalize_ruleset(pairs["merge_safety"])
        ),
    }
    rendered = CONTROLLER_TEMPLATE.read_text()
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", str(value))
    leftovers = sorted(set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", rendered)))
    if leftovers:
        raise FleetError(f"unresolved controller placeholders: {', '.join(leftovers)}")
    return rendered


def render_starter_workflow(name: str) -> str:
    rendered, count = re.subn(
        r"(?m)^name:\s*.*$",
        f"name: {name}",
        WORKFLOW_SOURCE.read_text(),
        count=1,
    )
    if count != 1:
        raise FleetError("central starter workflow has no unambiguous top-level name")
    return rendered


def phase_b_config(repo: Path) -> dict[str, Any]:
    value = load_json(repo / CONFIG_REL)
    expected = {
        "schema",
        "profile",
        "controller",
        "required_workflow",
        "rulesets",
        "settings",
        "protected_paths",
        "repository",
        "template_digests",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise FleetError(f"{CONFIG_REL} does not match the closed Phase B policy shape")
    if value.get("schema") != "pr-automation/v2":
        raise FleetError(f"{CONFIG_REL} is not Phase B")
    repository = value.get("repository")
    required = value.get("required_workflow")
    if not isinstance(repository, dict) or set(repository) != {"owner_repo", "base_branch"}:
        raise FleetError("repository policy is malformed")
    if not re.fullmatch(r"KleinPerkins/[A-Za-z0-9_.-]+", str(repository.get("owner_repo") or "")):
        raise FleetError("repository owner_repo is unsupported")
    base_branch = validate_branch_name(str(repository.get("base_branch") or ""))
    if not isinstance(required, dict):
        raise FleetError("required workflow policy is malformed")
    workflow_name = str(required.get("name") or "")
    workflow_path = str(required.get("path") or "")
    if not re.fullmatch(r"[A-Za-z0-9 ._-]+", workflow_name):
        raise FleetError("required workflow name contains unsupported characters")
    if not re.fullmatch(r"\.github/workflows/[A-Za-z0-9._/-]+\.ya?ml", workflow_path):
        raise FleetError("required workflow path is unsupported")
    expected_value = render_policy(
        repository["owner_repo"],
        base_branch,
        workflow_name=workflow_name,
        workflow_path=workflow_path,
    )
    if value != expected_value:
        raise FleetError(f"{CONFIG_REL} differs from the closed central Phase B policy")
    return value


def workflow_producers(repo: Path) -> list[Path]:
    return [
        path
        for path in phase_a.workflow_candidates(repo)
        if phase_a.workflow_mentions_required_job(path)
    ]


def verify_local(repo: Path) -> list[str]:
    errors: list[str] = []
    try:
        config = phase_b_config(repo)
    except (FleetError, phase_a.ProfileError) as exc:
        return [str(exc)]
    if config["repository"]["owner_repo"] != owner_repo(repo):
        errors.append("policy owner_repo differs from origin")
    branch = config["repository"]["base_branch"]
    if not branch:
        errors.append("policy base_branch is empty")
    controller = repo / CONTROLLER_REL
    expected_controller = render_controller(config)
    if not controller.is_file() or controller.read_text() != expected_controller:
        errors.append(f"{CONTROLLER_REL} differs from rendered central controller")
    producers = workflow_producers(repo)
    if len(producers) != 1:
        errors.append(f"expected exactly one required / ci producer; found {len(producers)}")
    else:
        configured_path = Path(config["required_workflow"]["path"])
        if producers[0].relative_to(repo) != configured_path:
            errors.append("configured required workflow path differs from actual producer")
        text = producers[0].read_text(errors="replace")
        name_matches = re.findall(r"(?m)^name:\s*(.*?)\s*$", text)
        actual_name = phase_a.unquote_scalar(name_matches[0]) if len(name_matches) == 1 else None
        if actual_name != config["required_workflow"]["name"]:
            errors.append(
                "required workflow top-level name differs from configured workflow_run trigger"
            )
        errors.extend(
            f"{producers[0].relative_to(repo)}: {error}"
            for error in phase_a.validate_aggregator(producers[0])
        )
    codeowners = repo / CODEOWNERS_REL
    if not codeowners.is_file():
        errors.append(f"{CODEOWNERS_REL} missing")
    else:
        content = codeowners.read_text()
        if any(line.strip() == "* @KleinPerkins" for line in content.splitlines()):
            errors.append("CODEOWNERS broad owner rule must be narrowed to protected paths")
        for path in config["protected_paths"]:
            rule = "/" + path.replace("**", "**") + " @KleinPerkins"
            if rule not in content:
                errors.append(f"CODEOWNERS missing protected path {path}")
    return errors


def cmd_verify(repo: Path) -> int:
    validate_target(repo, clean=False)
    errors = verify_local(repo)
    print(f"pr-automation Phase B verify — {repo}")
    for error in errors:
        print(f"  FAIL: {error}", file=sys.stderr)
    print(f"Overall: {'COMPLIANT' if not errors else 'NONCOMPLIANT'}")
    return 0 if not errors else 1


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cmd_apply(
    repo: Path,
    *,
    dry_run: bool,
    base_branch: str | None,
    workflow_name: str | None,
    workflow_path: str | None,
) -> int:
    ownerrepo = validate_target(repo, clean=False, allow_unlisted_apply=True)
    has_head = bool(git(repo, "rev-parse", "--verify", "HEAD", check=False))
    if has_head and git(repo, "status", "--porcelain"):
        raise FleetError("refusing dirty working tree")
    default = base_branch or git(repo, "branch", "--show-current")
    rendered_policy = render_policy(
        ownerrepo,
        default,
        workflow_name=workflow_name,
        workflow_path=workflow_path,
    )
    controller = render_controller(rendered_policy)
    actions: list[tuple[Path, str]] = []
    config_path = repo / CONFIG_REL
    config_text = json.dumps(rendered_policy, indent=2, sort_keys=True) + "\n"
    if config_path.exists() and config_path.read_text() != config_text:
        existing = load_json(config_path)
        if existing.get("schema") not in {"pr-automation/v1", "pr-automation/v2"}:
            raise FleetError(f"refusing unmanaged {CONFIG_REL}")
    if not config_path.exists() or config_path.read_text() != config_text:
        actions.append((config_path, config_text))
    controller_path = repo / CONTROLLER_REL
    if controller_path.exists() and controller_path.read_text() != controller:
        if "pr-automation/v2" not in controller_path.read_text():
            raise FleetError(f"refusing unmanaged {CONTROLLER_REL}")
    if not controller_path.exists() or controller_path.read_text() != controller:
        actions.append((controller_path, controller))
    producers = workflow_producers(repo)
    desired_workflow_path = repo / Path(rendered_policy["required_workflow"]["path"])
    starter_workflow = render_starter_workflow(
        rendered_policy["required_workflow"]["name"]
    )
    if not producers:
        if desired_workflow_path.exists() and "KleinPerkins/dev pr-automation" not in desired_workflow_path.read_text():
            raise FleetError(f"required workflow path is occupied: {desired_workflow_path}")
        actions.append((desired_workflow_path, starter_workflow))
    elif len(producers) > 1:
        raise FleetError("multiple required / ci producers; refusing")
    elif producers[0] != desired_workflow_path:
        raise FleetError("required producer exists at a different path than policy")
    if producers:
        producer_errors = phase_a.validate_aggregator(producers[0])
        text = producers[0].read_text(errors="replace")
        names = re.findall(r"(?m)^name:\s*(.*?)\s*$", text)
        actual_name = (
            phase_a.unquote_scalar(names[0]) if len(names) == 1 else None
        )
        if actual_name != rendered_policy["required_workflow"]["name"]:
            producer_errors.append(
                "required workflow top-level name differs from configured trigger"
            )
        if producer_errors:
            raise FleetError(
                "required workflow prevalidation failed: "
                + "; ".join(sorted(set(producer_errors)))
            )
    else:
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "required.yml"
            candidate.write_text(starter_workflow)
            producer_errors = phase_a.validate_aggregator(candidate)
        if producer_errors:
            raise FleetError(
                "central starter workflow prevalidation failed: "
                + "; ".join(producer_errors)
            )
    codeowners_path = repo / CODEOWNERS_REL
    existing_codeowners = codeowners_path.read_text() if codeowners_path.exists() else None
    desired_codeowners = phase_a.desired_codeowners(existing_codeowners)
    desired_codeowners = "\n".join(
        line
        for line in desired_codeowners.splitlines()
        if line.strip() != "* @KleinPerkins"
    ).rstrip() + "\n"
    if existing_codeowners != desired_codeowners:
        actions.append((codeowners_path, desired_codeowners))
    print(f"pr-automation Phase B apply — {ownerrepo}")
    for path, _ in actions:
        print(f"  {'would write' if dry_run else 'write'} {path.relative_to(repo)}")
    if dry_run:
        return 0
    for path, content in actions:
        atomic_write(path, content)
    errors = verify_local(repo)
    if errors:
        raise FleetError("post-apply verification failed: " + "; ".join(errors))
    print("Phase B files rendered inert; GitHub was not mutated")
    return 0


def state_path(ownerrepo: str) -> Path:
    return STATE_DIR / (ownerrepo.lower().replace("/", "__") + ".json")


def read_state(ownerrepo: str) -> dict[str, Any] | None:
    path = state_path(ownerrepo)
    if not path.exists():
        return None
    value = load_json(path)
    validate_state(value, ownerrepo=ownerrepo)
    return value


def validate_state(value: Any, *, ownerrepo: str) -> None:
    required = {
        "schema", "owner_repo", "default_branch", "lifecycle", "generation",
        "target_branch", "target_sha", "controller_digest",
        "production_controller_digest", "policy_digest", "template_digests",
        "pair", "rollback_preimage", "credentials", "qualification",
        "managed_settings", "rollback_proofs", "pending", "history", "revision",
        "updated_at",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise FleetError("Phase B state does not match its closed schema")
    if value.get("schema") != "pr-automation-state/v2":
        raise FleetError("Phase B state schema mismatch")
    if value.get("owner_repo", "").lower() != ownerrepo.lower():
        raise FleetError("Phase B state owner mismatch")
    if type(value.get("generation")) is not int or value["generation"] < 0:
        raise FleetError("Phase B state generation invalid")
    if type(value.get("revision")) is not int or value["revision"] < 1:
        raise FleetError("Phase B state revision invalid")
    if value.get("lifecycle") not in {
        "staged",
        "canary",
        "canary_active",
        "qualified",
        "promoted",
        "active",
        "paused",
        "credentials_revoked",
        "rolling_back",
        "rolled_back",
        "blocked",
        "ownership_ambiguous",
    }:
        raise FleetError("Phase B state lifecycle invalid")
    validate_branch_name(str(value.get("default_branch") or ""))
    if value.get("target_branch") is not None:
        validate_branch_name(str(value["target_branch"]))
    if value.get("target_sha") is not None and not FULL_SHA.fullmatch(
        str(value["target_sha"])
    ):
        raise FleetError("Phase B state target_sha invalid")
    for key in ("controller_digest", "production_controller_digest", "policy_digest"):
        if not FULL_DIGEST.fullmatch(str(value.get(key) or "")):
            raise FleetError(f"Phase B state {key} invalid")
    if set(value.get("pair", {})) != {"merge_safety", "review_gate"}:
        raise FleetError("Phase B state pair invalid")
    for key, item in value["pair"].items():
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "fingerprint", "owned"}
            or not FULL_DIGEST.fullmatch(str(item.get("fingerprint") or ""))
            or type(item.get("owned")) is not bool
            or (item.get("id") is not None and type(item.get("id")) is not int)
        ):
            raise FleetError(f"Phase B state resource invalid: {key}")
    if set(value.get("template_digests", {})) != {"merge_safety", "review_gate"} or any(
        not FULL_DIGEST.fullmatch(str(item or ""))
        for item in value["template_digests"].values()
    ):
        raise FleetError("Phase B state template digests invalid")
    credentials = value.get("credentials")
    expected_names = {
        "variable": "AUTOMERGE_APP_ID",
        "secret": "AUTOMERGE_APP_PRIVATE_KEY",
        "activation": "AUTOMERGE_ENABLED",
    }
    if not isinstance(credentials, dict) or set(credentials) != set(expected_names):
        raise FleetError("Phase B state credentials invalid")
    for key, name in expected_names.items():
        item = credentials[key]
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "owned", "updated_at"}
            or item.get("name") != name
            or type(item.get("owned")) is not bool
            or (
                item.get("updated_at") is not None
                and not isinstance(item.get("updated_at"), str)
            )
        ):
            raise FleetError(f"Phase B state credential invalid: {key}")
    managed_settings = value.get("managed_settings")
    if (
        not isinstance(managed_settings, dict)
        or set(managed_settings) != set(policy()["settings"])
        or any(type(item) is not bool for item in managed_settings.values())
    ):
        raise FleetError("Phase B managed settings postimage invalid")
    pending = value.get("pending")
    allowed_pending_keys = {
        "operation",
        "phase",
        "preexisting",
        "settings",
        "returned_id",
        "original_pair",
        "key",
        "id",
        "preimage",
        "preimage_fingerprint",
        "desired",
        "desired_fingerprint",
        "destination_branch",
        "destination_sha",
        "required_check",
        "updated_at",
    }
    allowed_pending_operations = {
        "credential-provision",
        "credential-revoke",
        "create-pair",
        "activate-canary-settings",
        "activate-canary",
        "pause-controls",
        "pause",
        "rollback-pair",
        "rollback-settings",
        "promote",
        "promote-stage",
        "activate-authorized",
        "activate-settings",
        "activate",
    }
    if pending is not None and (
        not isinstance(pending, dict)
        or not set(pending) <= allowed_pending_keys
        or pending.get("operation") not in allowed_pending_operations
    ):
        raise FleetError("Phase B pending journal is not closed or recognized")
    qualification = value.get("qualification")
    if qualification is not None and (
        not isinstance(qualification, dict)
        or set(qualification)
        != {
            "schema",
            "digest",
            "observed_at",
            "required_check",
            "scenario_modes",
        }
        or qualification.get("schema") != "pr-automation-evidence-summary/v2"
        or not FULL_DIGEST.fullmatch(str(qualification.get("digest") or ""))
    ):
        raise FleetError("Phase B qualification summary is invalid")
    for proof in value.get("rollback_proofs", []):
        if not isinstance(proof, dict) or set(proof) != {
            "generation",
            "pair_ids",
            "pair_fingerprints",
            "target_branch",
            "target_sha",
            "restored_settings_fingerprint",
            "completed_at",
            "digest",
        }:
            raise FleetError("Phase B rollback proof is not closed")
    allowed_history_keys = {
        "operation",
        "at",
        "generation",
        "target_branch",
        "target_sha",
        "evidence_digest",
        "destination_sha",
        "required_check",
        "secret_preserved",
        "original_pair",
    }
    for entry in value.get("history", []):
        if (
            not isinstance(entry, dict)
            or not set(entry) <= allowed_history_keys
            or not isinstance(entry.get("operation"), str)
            or not isinstance(entry.get("at"), str)
        ):
            raise FleetError("Phase B history entry is not closed")


def state_marker(value: dict[str, Any]) -> str:
    return canonical(
        {
            "revision": value["revision"],
            "digest": digest(value),
        }
    )


def write_state(ownerrepo: str, value: dict[str, Any]) -> None:
    path = state_path(ownerrepo)
    previous_marker = local_state_marker(ownerrepo)
    if _REMOTE_LOCK_CONTEXT is not None:
        if _REMOTE_LOCK_CONTEXT.get("owner_repo") != ownerrepo:
            raise FleetError("remote state lock owner differs from local state owner")
        if _REMOTE_LOCK_CONTEXT.get("state_marker") != previous_marker:
            raise FleetError(
                "local lifecycle state differs from the durable remote revision marker"
            )
    value["revision"] = int(value.get("revision", 0)) + 1
    value["updated_at"] = now()
    validate_state(value, ownerrepo=ownerrepo)
    marker = state_marker(value)
    if _REMOTE_LOCK_CONTEXT is not None:
        transition = canonical(
            {
                "transition": {
                    "from": previous_marker,
                    "to": marker,
                }
            }
        )
        set_remote_state_value(ownerrepo, transition)
    atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")
    if _REMOTE_LOCK_CONTEXT is not None:
        set_remote_state_value(ownerrepo, marker)
        _REMOTE_LOCK_CONTEXT["state_marker"] = marker


def acquire_repo_lock(ownerrepo: str):
    root = Path.home() / ".local/state/pr-automation/locks"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    path = root / (ownerrepo.lower().replace("/", "__") + ".lock")
    handle = path.open("a+")
    os.chmod(path, 0o600)
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise FleetError(f"another Phase B writer holds the {ownerrepo} lifecycle lock") from exc
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()} acquired_at={now()}\n")
    handle.flush()
    return handle


def remote_repo(ownerrepo: str) -> dict[str, Any]:
    value = gh_api(f"repos/{ownerrepo}")
    if str(value.get("owner", {}).get("login", "")).lower() != "kleinperkins":
        raise FleetError("remote owner mismatch")
    return value


def branch_sha(ownerrepo: str, branch: str) -> str:
    value = gh_api(f"repos/{ownerrepo}/branches/{quote(branch, safe='')}")
    sha = str((value.get("commit") or {}).get("sha") or "")
    if not FULL_SHA.fullmatch(sha):
        raise FleetError(f"branch {branch!r} has no exact GitHub SHA")
    return sha


def remote_file_bytes(ownerrepo: str, path: str, ref: str) -> bytes:
    value = gh_api(
        f"repos/{ownerrepo}/contents/{quote(path, safe='/')}?ref={quote(ref, safe='')}"
    )
    if not isinstance(value, dict) or value.get("encoding") != "base64":
        raise FleetError(f"remote file response is malformed: {path}@{ref}")
    try:
        return base64.b64decode(str(value.get("content") or ""), validate=False)
    except (ValueError, TypeError) as exc:
        raise FleetError(f"remote file content is invalid: {path}@{ref}") from exc


def assert_remote_managed_files(
    repo: Path,
    ownerrepo: str,
    ref: str,
    *,
    include_required: bool,
    expected_config: dict[str, Any] | None = None,
) -> None:
    config = expected_config or phase_b_config(repo)
    expected = {
        str(CONFIG_REL): (
            json.dumps(config, indent=2, sort_keys=True) + "\n"
        ).encode(),
        str(CONTROLLER_REL): render_controller(config).encode(),
    }
    if include_required:
        relative = config["required_workflow"]["path"]
        local = repo / relative
        if not local.is_file():
            raise FleetError(f"managed local file missing: {relative}")
        expected[relative] = local.read_bytes()
    for relative, content in expected.items():
        if remote_file_bytes(ownerrepo, relative, ref) != content:
            raise FleetError(f"remote {relative}@{ref} differs from verified local bytes")


def require_exact_head(repo: Path, ownerrepo: str, branch: str) -> str:
    local_branch = git(repo, "branch", "--show-current")
    if local_branch != branch:
        raise FleetError(f"checkout exact target branch {branch!r}, found {local_branch!r}")
    upstream = git(repo, "rev-parse", "--abbrev-ref", "@{upstream}", check=False)
    if upstream != f"origin/{branch}":
        raise FleetError(f"target must track origin/{branch}")
    run(["git", "-C", str(repo), "fetch", "--quiet", "origin", f"refs/heads/{branch}"])
    values = {
        git(repo, "rev-parse", "HEAD"),
        git(repo, "rev-parse", "@{upstream}"),
        git(repo, "rev-parse", "FETCH_HEAD"),
        branch_sha(ownerrepo, branch),
    }
    if len(values) != 1:
        raise FleetError("local/upstream/fetched/GitHub target SHAs must match exactly")
    return next(iter(values))


def list_named_rulesets(ownerrepo: str) -> dict[str, tuple[int, dict[str, Any]]]:
    cfg = policy()
    names = set(cfg["rulesets"].values())
    entries = paginated(f"repos/{ownerrepo}/rulesets?per_page=100")
    result: dict[str, tuple[int, dict[str, Any]]] = {}
    for name in names:
        matches = [entry for entry in entries if entry.get("name") == name]
        if len(matches) > 1:
            raise FleetError(f"multiple rulesets named {name}")
        if matches:
            ruleset_id = int(matches[0]["id"])
            result[name] = (
                ruleset_id,
                gh_api(f"repos/{ownerrepo}/rulesets/{ruleset_id}"),
            )
    return result


def pair_live(ownerrepo: str) -> dict[str, dict[str, Any]]:
    cfg = policy()
    named = list_named_rulesets(ownerrepo)
    output = {}
    for key, name in cfg["rulesets"].items():
        if name in named:
            ruleset_id, value = named[name]
            output[key] = {
                "id": ruleset_id,
                "value": value,
                "fingerprint": digest(normalize_ruleset(value)),
            }
    return output


def settings_live(ownerrepo: str) -> dict[str, bool]:
    remote = remote_repo(ownerrepo)
    return {key: bool(remote.get(key)) for key in policy()["settings"]}


def credential_metadata(ownerrepo: str) -> dict[str, dict[str, Any] | None]:
    cfg = policy()["controller"]
    result: dict[str, dict[str, Any] | None] = {}
    for key, endpoint in {
        "variable": f"repos/{ownerrepo}/actions/variables/{cfg['app_id_variable']}",
        "activation": f"repos/{ownerrepo}/actions/variables/{cfg['activation_variable']}",
        "secret": f"repos/{ownerrepo}/actions/secrets/{cfg['private_key_secret']}",
    }.items():
        process = run(["gh", "api", endpoint], check=False)
        if process.returncode == 0:
            try:
                result[key] = json.loads(str(process.stdout))
            except json.JSONDecodeError as exc:
                raise FleetError(f"malformed credential metadata response for {key}") from exc
        else:
            detail = str(process.stderr or process.stdout)
            if "HTTP 404" in detail:
                result[key] = None
            else:
                raise FleetError(f"credential metadata read failed for {key}: {detail.strip()}")
    return result


def controller_runs(ownerrepo: str) -> list[dict[str, Any]]:
    workflow = policy()["controller"]["workflow_path"]
    result = run(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{ownerrepo}/actions/workflows/{quote(workflow, safe='')}/runs?per_page=100",
        ],
        check=False,
    )
    if result.returncode:
        detail = str(result.stderr or result.stdout)
        if "HTTP 404" in detail:
            return []
        raise FleetError(f"controller run discovery failed: {detail.strip()}")
    pages = json.loads(str(result.stdout))
    if not isinstance(pages, list) or not all(isinstance(page, dict) for page in pages):
        raise FleetError("controller run discovery returned malformed pagination")
    runs = [item for page in pages for item in page.get("workflow_runs", [])]
    if not all(isinstance(item, dict) for item in runs):
        raise FleetError("controller run discovery returned malformed runs")
    return runs


def open_pulls(ownerrepo: str) -> list[dict[str, Any]]:
    return paginated(f"repos/{ownerrepo}/pulls?state=open&per_page=100")


def armed_pulls(ownerrepo: str) -> list[dict[str, Any]]:
    pulls = open_pulls(ownerrepo)
    if any("auto_merge" not in pull for pull in pulls):
        raise FleetError("open PR response omitted auto_merge state")
    return [pull for pull in pulls if pull.get("auto_merge")]


def cmd_preflight(repo: Path, *, target_branch: str | None) -> int:
    ownerrepo = validate_target(repo, clean=True)
    require_gh()
    errors = verify_local(repo)
    if errors:
        raise FleetError("local Phase B verification failed: " + "; ".join(errors))
    remote = remote_repo(ownerrepo)
    branch = target_branch or str(remote.get("default_branch") or "")
    sha = require_exact_head(repo, ownerrepo, branch)
    pulls = open_pulls(ownerrepo)
    armed = armed_pulls(ownerrepo)
    running = [
        item for item in controller_runs(ownerrepo)
        if item.get("status") in {"queued", "in_progress", "requested", "waiting", "pending"}
    ]
    existing = pair_live(ownerrepo)
    state = read_state(ownerrepo)
    if pulls:
        raise FleetError(f"preflight requires zero open PRs; found {len(pulls)}")
    if armed or running:
        raise FleetError("preflight requires zero armed merges and zero running controller jobs")
    if existing and not state:
        raise FleetError("same-named ruleset pair is not owned by lifecycle state")
    print(
        json.dumps(
            {
                "owner_repo": ownerrepo,
                "target_branch": branch,
                "target_sha": sha,
                "open_prs": 0,
                "armed_auto_merges": 0,
                "running_controller_runs": 0,
                "pair_resources": {
                    key: {"id": item["id"], "fingerprint": item["fingerprint"]}
                    for key, item in existing.items()
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_credential_status(repo: Path) -> int:
    ownerrepo = validate_target(repo, clean=False)
    require_gh()
    metadata = credential_metadata(ownerrepo)
    safe = {
        key: (
            {
                "name": value.get("name"),
                "created_at": value.get("created_at"),
                "updated_at": value.get("updated_at"),
            }
            if value
            else None
        )
        for key, value in metadata.items()
    }
    print(json.dumps({"owner_repo": ownerrepo, "credentials": safe}, indent=2, sort_keys=True))
    return 0


def cmd_credential_provision(
    repo: Path,
    *,
    key_file: Path | None,
    preserve_existing_secret: bool,
) -> int:
    ownerrepo = validate_target(repo, clean=True)
    require_gh()
    cfg = policy()["controller"]
    state = read_state(ownerrepo)
    if not state:
        raise FleetError("credential provisioning requires an owned canary state")
    if state.get("lifecycle") != "canary" or (
        state.get("pending") is not None
        and state["pending"].get("operation") != "credential-provision"
    ):
        raise FleetError("credential provisioning requires an idle canary lifecycle")
    require_exact_head(repo, ownerrepo, state["target_branch"])
    before = credential_metadata(ownerrepo)
    if (
        before["variable"] is not None
        and str(before["variable"].get("value")) != str(cfg["app_id"])
    ):
        raise FleetError("pre-existing AUTOMERGE_APP_ID differs from closed policy")
    prior_pending = state.get("pending")
    recovering = (
        isinstance(prior_pending, dict)
        and prior_pending.get("operation") == "credential-provision"
        and isinstance(prior_pending.get("preexisting"), dict)
    )
    preexisting = (
        copy.deepcopy(prior_pending["preexisting"])
        if recovering
        else {key: value is not None for key, value in before.items()}
    )
    recovering_created_secret = (
        recovering and preexisting.get("secret") is False
    )
    if (
        before["secret"] is not None
        and not preserve_existing_secret
        and not recovering_created_secret
    ):
        raise FleetError(
            "pre-existing opaque App secret requires --preserve-existing-secret or explicit rotation"
        )
    if (
        before["activation"] is not None
        and str(before["activation"].get("value")) != "false"
        and not state["credentials"]["activation"].get("owned")
    ):
        raise FleetError("refusing to overwrite a pre-existing active activation variable")
    if before["secret"] is None:
        if key_file is None:
            raise FleetError("--key-file is required when the App secret is absent")
        if not key_file.is_file():
            raise FleetError(f"private key file missing: {key_file}")
        if key_file.stat().st_mode & 0o077:
            raise FleetError("private key file must not be group/world accessible")
    state["pending"] = {
        "operation": "credential-provision",
        "phase": "app-id",
        "preexisting": preexisting,
    }
    write_state(ownerrepo, state)
    if before["variable"] is None:
        run(
            [
                "gh", "variable", "set", cfg["app_id_variable"],
                "--repo", ownerrepo, "--body", str(cfg["app_id"]),
            ]
        )
    state["pending"]["phase"] = "activation"
    write_state(ownerrepo, state)
    if before["activation"] is None or str(before["activation"].get("value")) != "false":
        run(
            [
                "gh", "variable", "set", cfg["activation_variable"],
                "--repo", ownerrepo, "--body", "false",
            ]
        )
    state["pending"]["phase"] = "secret"
    write_state(ownerrepo, state)
    secret_owned = (
        state["credentials"]["secret"].get("owned")
        or before["secret"] is None
        or recovering_created_secret
    )
    if before["secret"] is None:
        assert key_file is not None
        with key_file.open("rb") as handle:
            run(
                [
                    "gh", "secret", "set", cfg["private_key_secret"],
                    "--repo", ownerrepo,
                ],
                stdin=handle,
            )
    after = credential_metadata(ownerrepo)
    if not all(after.values()):
        raise FleetError("credential provisioning postcondition failed")
    if (
        str(after["variable"].get("value")) != str(cfg["app_id"])
        or str(after["activation"].get("value")) != "false"
    ):
        raise FleetError("credential provisioning exact variable postcondition failed")
    state["credentials"] = {
        "variable": {
            "name": cfg["app_id_variable"],
            "owned": state["credentials"]["variable"].get("owned")
            or not preexisting["variable"],
            "updated_at": after["variable"].get("updated_at"),
        },
        "activation": {
            "name": cfg["activation_variable"],
            "owned": state["credentials"]["activation"].get("owned")
            or not preexisting["activation"],
            "updated_at": after["activation"].get("updated_at"),
        },
        "secret": {
            "name": cfg["private_key_secret"],
            "owned": secret_owned,
            "updated_at": after["secret"].get("updated_at"),
        },
    }
    state.setdefault("history", []).append(
        {"operation": "credential-provision", "at": now(), "secret_preserved": not secret_owned}
    )
    state["pending"] = None
    write_state(ownerrepo, state)
    print(f"credentials present by name for {ownerrepo}; activation remains false")
    return 0


def set_workflow_enabled(ownerrepo: str, enabled: bool) -> None:
    path = quote(policy()["controller"]["workflow_path"], safe="")
    expected = "active" if enabled else "disabled_manually"
    workflow_endpoint = f"repos/{ownerrepo}/actions/workflows/{path}"
    workflow = gh_api(workflow_endpoint)
    if not isinstance(workflow, dict):
        raise FleetError("controller workflow state response is malformed")
    if workflow.get("state") == expected:
        return
    if workflow.get("state") not in {"active", "disabled_manually"}:
        raise FleetError(
            f"controller workflow has unexpected state: {workflow.get('state')!r}"
        )
    endpoint = f"{workflow_endpoint}/{'enable' if enabled else 'disable'}"
    gh_api(endpoint, method="PUT")
    workflow = gh_api(workflow_endpoint)
    if not isinstance(workflow, dict) or workflow.get("state") != expected:
        raise FleetError(f"controller workflow state did not become {expected}")


def controller_workflow_state(ownerrepo: str, *, required: bool = True) -> str:
    path = quote(policy()["controller"]["workflow_path"], safe="")
    result = run(
        ["gh", "api", f"repos/{ownerrepo}/actions/workflows/{path}"],
        check=False,
    )
    if result.returncode != 0:
        if not required and "HTTP 404" in str(result.stderr or result.stdout):
            return "missing"
        raise FleetError("controller workflow state could not be read")
    workflow = json.loads(str(result.stdout))
    state = str((workflow or {}).get("state") or "")
    if state not in {"active", "disabled_manually"}:
        raise FleetError(f"controller workflow has unexpected state: {state!r}")
    return state


def set_activation(ownerrepo: str, enabled: bool) -> dict[str, Any]:
    cfg = policy()["controller"]
    expected = "true" if enabled else "false"
    run(
        [
            "gh",
            "variable",
            "set",
            cfg["activation_variable"],
            "--repo",
            ownerrepo,
            "--body",
            expected,
        ]
    )
    metadata = credential_metadata(ownerrepo)["activation"]
    if not isinstance(metadata, dict) or str(metadata.get("value")) != expected:
        raise FleetError(f"activation variable did not become {expected}")
    return metadata


def cancel_and_drain(ownerrepo: str) -> None:
    for run_record in controller_runs(ownerrepo):
        if run_record.get("status") in {"queued", "in_progress", "requested", "waiting", "pending"}:
            result = run(
                ["gh", "api", "-X", "POST", f"repos/{ownerrepo}/actions/runs/{run_record['id']}/cancel"],
                check=False,
            )
            if result.returncode not in {0}:
                raise FleetError(f"failed to cancel controller run {run_record['id']}")
    zero_observations = 0
    for attempt in range(15):
        remaining = [
            item for item in controller_runs(ownerrepo)
            if item.get("status") in {"queued", "in_progress", "requested", "waiting", "pending"}
        ]
        if not remaining:
            zero_observations += 1
            if zero_observations >= 2:
                return
            time.sleep(2)
            continue
        zero_observations = 0
        if attempt == 14:
            raise FleetError("controller runs did not drain")
        time.sleep(5)


DISABLE_AUTO_MERGE = """
mutation($id:ID!){disablePullRequestAutoMerge(input:{pullRequestId:$id}){
pullRequest{id autoMergeRequest{enabledAt}}}}
""".strip()


def disarm_all(ownerrepo: str) -> None:
    for pull in armed_pulls(ownerrepo):
        exact = gh_api(f"repos/{ownerrepo}/pulls/{pull['number']}")
        if (
            exact.get("node_id") != pull.get("node_id")
            or (exact.get("head") or {}).get("sha") != (pull.get("head") or {}).get("sha")
            or not exact.get("auto_merge")
        ):
            raise FleetError(f"armed PR #{pull['number']} changed before disarm")
        gh_api(
            "graphql",
            method="POST",
            payload={
                "query": DISABLE_AUTO_MERGE,
                "variables": {"id": pull["node_id"]},
            },
        )
    if armed_pulls(ownerrepo):
        raise FleetError("armed auto-merge requests remain after drain")


def transition_settings(
    ownerrepo: str,
    state: dict[str, Any],
    *,
    operation: str,
    desired: dict[str, bool],
) -> dict[str, bool]:
    current = settings_live(ownerrepo)
    pending = state.get("pending")
    if (
        isinstance(pending, dict)
        and pending.get("operation") == operation
        and isinstance(pending.get("settings"), dict)
    ):
        transition = pending["settings"]
        if digest(current) == transition.get("desired_fingerprint"):
            state["managed_settings"] = copy.deepcopy(current)
            write_state(ownerrepo, state)
            return current
        if digest(current) != transition.get("from_fingerprint"):
            raise FleetError(f"{operation} settings recovery found an unknown third state")
        exact_desired = transition.get("desired")
        if exact_desired != desired:
            raise FleetError(f"{operation} settings recovery desired postimage changed")
    else:
        if current != state.get("managed_settings"):
            raise FleetError(f"{operation} settings drifted from the last managed postimage")
        transition = {
            "from": current,
            "from_fingerprint": digest(current),
            "desired": desired,
            "desired_fingerprint": digest(desired),
        }
        state["pending"] = {"operation": operation, "settings": transition}
        write_state(ownerrepo, state)
    if current == desired:
        state["managed_settings"] = copy.deepcopy(current)
        write_state(ownerrepo, state)
        return current
    if settings_live(ownerrepo) != transition["from"]:
        raise FleetError(f"{operation} settings changed immediately before write")
    gh_api(f"repos/{ownerrepo}", method="PATCH", payload=desired)
    post = settings_live(ownerrepo)
    if post != desired:
        raise FleetError(f"{operation} settings postimage mismatch")
    state["managed_settings"] = copy.deepcopy(post)
    write_state(ownerrepo, state)
    return post


def create_ruleset_owned(
    ownerrepo: str,
    state: dict[str, Any],
    *,
    key: str,
    desired: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    stored = state["pair"][key]
    if stored.get("id") is not None and stored.get("owned"):
        ruleset_id = int(stored["id"])
    else:
        if key in pair_live(ownerrepo):
            raise FleetError(f"{key} appeared immediately before create; refusing ownership")
        try:
            response = gh_api(f"repos/{ownerrepo}/rulesets", method="POST", payload=desired)
            ruleset_id = int(response["id"])
        except (FleetError, KeyError, TypeError, ValueError) as exc:
            state["lifecycle"] = "ownership_ambiguous"
            state["pending"] = {
                "operation": "create-pair",
                "phase": key,
                "returned_id": None,
            }
            write_state(ownerrepo, state)
            raise FleetError(
                f"{key} create returned no durable id; ownership is ambiguous"
            ) from exc
        state["pair"][key] = {
            "id": ruleset_id,
            "fingerprint": digest(None),
            "owned": True,
        }
        state["pending"] = {
            "operation": "create-pair",
            "phase": key + "_verify",
            "returned_id": ruleset_id,
        }
        write_state(ownerrepo, state)
    live = gh_api(f"repos/{ownerrepo}/rulesets/{ruleset_id}")
    if normalize_ruleset(live) != normalize_ruleset(desired):
        raise FleetError(f"ruleset {ruleset_id} postimage mismatch")
    state["pair"][key]["fingerprint"] = digest(normalize_ruleset(live))
    write_state(ownerrepo, state)
    return ruleset_id, live


def state_seed(
    ownerrepo: str,
    default_branch: str,
    target_branch: str,
    target_sha: str,
    settings: dict[str, bool],
) -> dict[str, Any]:
    return {
        "schema": "pr-automation-state/v2",
        "owner_repo": ownerrepo,
        "default_branch": default_branch,
        "lifecycle": "staged",
        "generation": 0,
        "target_branch": target_branch,
        "target_sha": target_sha,
        "controller_digest": digest(CONTROLLER_TEMPLATE.read_text()),
        "production_controller_digest": digest(CONTROLLER_TEMPLATE.read_text()),
        "policy_digest": digest(policy()),
        "template_digests": template_digests(),
        "pair": {
            "merge_safety": {"id": None, "fingerprint": digest(None), "owned": False},
            "review_gate": {"id": None, "fingerprint": digest(None), "owned": False},
        },
        "rollback_preimage": {"settings": settings, "rulesets": {}},
        "managed_settings": copy.deepcopy(settings),
        "credentials": {
            "variable": {"name": "AUTOMERGE_APP_ID", "owned": False, "updated_at": None},
            "secret": {"name": "AUTOMERGE_APP_PRIVATE_KEY", "owned": False, "updated_at": None},
            "activation": {"name": "AUTOMERGE_ENABLED", "owned": False, "updated_at": None},
        },
        "qualification": None,
        "rollback_proofs": [],
        "pending": None,
        "history": [],
        "updated_at": now(),
    }


def cmd_enforce_canary(repo: Path, *, target_branch: str) -> int:
    ownerrepo = validate_target(repo, clean=True)
    require_gh()
    errors = verify_local(repo)
    if errors:
        raise FleetError("local Phase B verification failed: " + "; ".join(errors))
    local_config = phase_b_config(repo)
    if local_config["repository"]["base_branch"] != target_branch:
        raise FleetError("canary policy base branch must equal the exact canary target")
    cmd_preflight(repo, target_branch=target_branch)
    remote = remote_repo(ownerrepo)
    default = str(remote.get("default_branch") or "")
    if target_branch == default:
        raise FleetError("enforce-canary requires a non-default exact branch")
    target_sha = require_exact_head(repo, ownerrepo, target_branch)
    assert_remote_managed_files(
        repo,
        ownerrepo,
        default,
        include_required=False,
        expected_config=policy_for_branch(local_config, default),
    )
    assert_remote_managed_files(repo, ownerrepo, target_branch, include_required=True)
    existing = pair_live(ownerrepo)
    state = read_state(ownerrepo)
    if state and state.get("lifecycle") == "ownership_ambiguous":
        raise FleetError("pair creation ownership is ambiguous; manual investigation required")
    resumable_create = (
        state is not None
        and isinstance(state.get("pending"), dict)
        and state["pending"].get("operation") == "create-pair"
    )
    if state and state.get("default_branch") != default:
        raise FleetError("default branch changed since lifecycle state creation")
    if existing:
        if not state or (
            not resumable_create
            and state.get("lifecycle") not in {"canary", "canary_active", "paused"}
        ):
            raise FleetError("same-named rulesets exist outside a resumable owned canary")
        for key, item in existing.items():
            stored = state["pair"][key]
            if stored.get("id") is None:
                state["lifecycle"] = "ownership_ambiguous"
                state["pending"] = {
                    "operation": "create-pair",
                    "phase": key,
                    "returned_id": None,
                }
                write_state(ownerrepo, state)
                raise FleetError(
                    f"{key} appeared without a durable returned id; ownership is ambiguous"
                )
            if item["id"] != stored.get("id") or not stored.get("owned"):
                raise FleetError(f"live {key} differs from owned canary state")
    elif not resumable_create:
        if state and state.get("lifecycle") != "rolled_back":
            raise FleetError(
                f"pair recreation requires exact rolled_back state, found {state.get('lifecycle')!r}"
            )
        current_settings = settings_live(ownerrepo)
        previous = state
        prior_rollbacks = previous.get("rollback_proofs", []) if previous else []
        generation = int(previous.get("generation", 0)) + 1 if previous else 1
        state = state_seed(ownerrepo, default, target_branch, target_sha, current_settings)
        state["generation"] = generation
        state["rollback_proofs"] = prior_rollbacks
        if previous:
            state["revision"] = previous["revision"]
            state["credentials"] = previous.get("credentials", state["credentials"])
            state["history"] = previous.get("history", [])
        state["controller_digest"] = digest(render_controller(local_config))
        production_config = copy.deepcopy(local_config)
        production_config["repository"]["base_branch"] = default
        state["production_controller_digest"] = digest(
            render_controller(production_config)
        )
        state["pending"] = {"operation": "create-pair", "phase": "prepare-controls"}
        write_state(ownerrepo, state)
    assert state is not None
    state["target_branch"] = target_branch
    state["target_sha"] = target_sha
    activation = credential_metadata(ownerrepo)["activation"]
    if (
        activation is not None
        and str(activation.get("value")) != "false"
        and not state["credentials"]["activation"].get("owned")
    ):
        raise FleetError("refusing to overwrite a pre-existing active activation variable")
    if activation is None:
        state["credentials"]["activation"]["owned"] = True
        state["pending"] = {"operation": "create-pair", "phase": "activation-create"}
        write_state(ownerrepo, state)
    activation_after = set_activation(ownerrepo, False)
    state["credentials"]["activation"]["updated_at"] = activation_after.get("updated_at")
    state["pending"] = {"operation": "create-pair", "phase": "workflow-disable"}
    write_state(ownerrepo, state)
    set_workflow_enabled(ownerrepo, False)
    cancel_and_drain(ownerrepo)
    desired = render_rulesets(target_branch)
    for key in ("merge_safety", "review_gate"):
        live_now = pair_live(ownerrepo)
        if key in live_now:
            stored = state["pair"][key]
            if (
                live_now[key]["id"] != stored.get("id")
                or normalize_ruleset(live_now[key]["value"])
                != normalize_ruleset(desired[key])
                or not stored.get("owned")
            ):
                raise FleetError(f"{key} exists but is not the exact owned canary resource")
            fingerprint = digest(normalize_ruleset(live_now[key]["value"]))
            if stored.get("fingerprint") == digest(None) and resumable_create:
                state["pair"][key]["fingerprint"] = fingerprint
                state["pending"] = {
                    "operation": "create-pair",
                    "phase": key + "_verified",
                    "returned_id": live_now[key]["id"],
                }
                write_state(ownerrepo, state)
            elif stored.get("fingerprint") != fingerprint:
                raise FleetError(f"{key} stored fingerprint differs from exact live resource")
            continue
        state["pending"] = {"operation": "create-pair", "phase": key}
        write_state(ownerrepo, state)
        create_ruleset_owned(
            ownerrepo,
            state,
            key=key,
            desired=desired[key],
        )
    state["pending"] = None
    state["lifecycle"] = "canary"
    state["history"].append(
        {
            "operation": "create-pair",
            "generation": state["generation"],
            "target_branch": target_branch,
            "target_sha": target_sha,
            "at": now(),
        }
    )
    write_state(ownerrepo, state)
    existing = pair_live(ownerrepo)
    desired = render_rulesets(target_branch)
    for key in ("merge_safety", "review_gate"):
        if key not in existing or normalize_ruleset(existing[key]["value"]) != normalize_ruleset(desired[key]):
            raise FleetError(f"{key} canary ruleset is not exact")
    print(
        json.dumps(
            {
                "owner_repo": ownerrepo,
                "generation": state["generation"],
                "target_branch": target_branch,
                "target_sha": target_sha,
                "pair": {
                    key: {
                        "id": existing[key]["id"],
                        "fingerprint": existing[key]["fingerprint"],
                    }
                    for key in ("merge_safety", "review_gate")
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_activate_canary(repo: Path) -> int:
    ownerrepo = validate_target(repo, clean=True)
    require_gh()
    state = read_state(ownerrepo)
    if not state or state.get("lifecycle") not in {"canary", "canary_active"}:
        raise FleetError("canary activation requires an exact canary lifecycle")
    config = phase_b_config(repo)
    target = state["target_branch"]
    if config["repository"]["base_branch"] != target:
        raise FleetError("canary controller base binding changed")
    require_exact_head(repo, ownerrepo, target)
    assert_remote_managed_files(
        repo,
        ownerrepo,
        state["default_branch"],
        include_required=False,
        expected_config=policy_for_branch(config, state["default_branch"]),
    )
    assert_remote_managed_files(repo, ownerrepo, target, include_required=True)
    live = pair_live(ownerrepo)
    desired = render_rulesets(target)
    for key in ("merge_safety", "review_gate"):
        if (
            key not in live
            or live[key]["id"] != state["pair"][key]["id"]
            or normalize_ruleset(live[key]["value"]) != normalize_ruleset(desired[key])
            or not state["pair"][key]["owned"]
        ):
            raise FleetError(f"canary activation pair mismatch: {key}")
    credentials = credential_metadata(ownerrepo)
    if not all(credentials.values()):
        raise FleetError("canary activation credentials missing by name")
    activation_pending = (
        isinstance(state.get("pending"), dict)
        and state["pending"].get("operation") == "activate-canary"
        and state["pending"].get("phase") == "activation-enable"
    )
    if (
        str(credentials["activation"].get("value")) == "true"
        and activation_pending
        and controller_workflow_state(ownerrepo) == "active"
        and settings_live(ownerrepo) == policy()["settings"]
    ):
        state["pending"] = None
        state["lifecycle"] = "canary_active"
        state["history"].append(
            {
                "operation": "activate-canary-recovered",
                "generation": state["generation"],
                "at": now(),
            }
        )
        write_state(ownerrepo, state)
        print(f"{ownerrepo}: canary activation finalized from exact postimage")
        return 0
    if (
        str(credentials["variable"].get("value"))
        != str(policy()["controller"]["app_id"])
        or str(credentials["activation"].get("value")) != "false"
    ):
        raise FleetError("canary activation credential values are not inert and exact")
    transition_settings(
        ownerrepo,
        state,
        operation="activate-canary-settings",
        desired=policy()["settings"],
    )
    state["pending"] = {"operation": "activate-canary", "phase": "workflow-enable"}
    write_state(ownerrepo, state)
    set_workflow_enabled(ownerrepo, True)
    state["pending"] = {"operation": "activate-canary", "phase": "activation-enable"}
    write_state(ownerrepo, state)
    activation = set_activation(ownerrepo, True)
    state["credentials"]["activation"]["updated_at"] = activation.get("updated_at")
    state["pending"] = None
    state["lifecycle"] = "canary_active"
    state["history"].append(
        {"operation": "activate-canary", "generation": state["generation"], "at": now()}
    )
    write_state(ownerrepo, state)
    print(f"{ownerrepo}: canary controller active for {target}")
    return 0


def pause_remote(ownerrepo: str, state: dict[str, Any]) -> None:
    recovering_settings = (
        isinstance(state.get("pending"), dict)
        and state["pending"].get("operation") == "pause"
        and isinstance(state["pending"].get("settings"), dict)
    )
    if not recovering_settings:
        state["pending"] = {
            "operation": "pause-controls",
            "phase": "activation-disable",
        }
        write_state(ownerrepo, state)
    activation = credential_metadata(ownerrepo)["activation"]
    if activation is not None:
        activation = set_activation(ownerrepo, False)
        state["credentials"]["activation"]["updated_at"] = activation.get("updated_at")
    if not recovering_settings:
        state["pending"] = {
            "operation": "pause-controls",
            "phase": "workflow-disable",
        }
        write_state(ownerrepo, state)
    set_workflow_enabled(ownerrepo, False)
    cancel_and_drain(ownerrepo)
    current = settings_live(ownerrepo)
    desired = copy.deepcopy(current)
    desired["allow_auto_merge"] = False
    transition_settings(ownerrepo, state, operation="pause", desired=desired)
    disarm_all(ownerrepo)


def cmd_pause(repo: Path) -> int:
    ownerrepo = validate_target(repo, clean=True)
    require_gh()
    state = read_state(ownerrepo)
    if not state:
        raise FleetError("no Phase B state")
    if state.get("lifecycle") not in {
        "canary",
        "canary_active",
        "qualified",
        "promoted",
        "active",
        "paused",
    }:
        raise FleetError(f"pause is invalid from lifecycle {state.get('lifecycle')!r}")
    pending = state.get("pending")
    if isinstance(pending, dict) and pending.get("operation") not in {
        "pause-controls",
        "pause",
        "activate-canary",
        "activate-canary-settings",
        "activate",
        "activate-settings",
    }:
        raise FleetError(
            f"pause refuses unrelated pending operation {pending.get('operation')!r}"
        )
    if isinstance(pending, dict) and pending.get("operation") in {
        "activate-canary-settings",
        "activate-settings",
    }:
        transition_settings(
            ownerrepo,
            state,
            operation=pending["operation"],
            desired=policy()["settings"],
        )
    if isinstance(pending, dict) and pending.get("operation") in {
        "activate-canary",
        "activate-canary-settings",
        "activate",
        "activate-settings",
    }:
        state["pending"] = None
        state["history"].append(
            {"operation": "activation-aborted-by-pause", "at": now()}
        )
        write_state(ownerrepo, state)
    pause_remote(ownerrepo, state)
    state["pending"] = None
    state["lifecycle"] = "paused"
    state["history"].append({"operation": "pause", "at": now()})
    write_state(ownerrepo, state)
    print(f"{ownerrepo}: controller disabled/drained; zero armed auto-merges")
    return 0


def cmd_rollback(repo: Path) -> int:
    ownerrepo = validate_target(repo, clean=True)
    require_gh()
    state = read_state(ownerrepo)
    if not state:
        raise FleetError("no Phase B state")
    pending_before_rollback = state.get("pending")
    if isinstance(pending_before_rollback, dict) and pending_before_rollback.get(
        "operation"
    ) in {"promote", "promote-stage"}:
        live_promotion = pair_live(ownerrepo)
        desired_default = render_rulesets(state["default_branch"])
        for key in ("merge_safety", "review_gate"):
            allowed = {
                state["pair"][key]["fingerprint"],
                digest(normalize_ruleset(desired_default[key])),
            }
            if (
                key not in live_promotion
                or live_promotion[key]["id"] != state["pair"][key]["id"]
                or live_promotion[key]["fingerprint"] not in allowed
            ):
                raise FleetError(f"rollback cannot classify interrupted promotion {key}")
            state["pair"][key]["fingerprint"] = live_promotion[key]["fingerprint"]
        state["pending"] = None
        state["history"].append(
            {"operation": "promotion-aborted-by-rollback", "at": now()}
        )
        write_state(ownerrepo, state)
    elif isinstance(pending_before_rollback, dict) and pending_before_rollback.get(
        "operation"
    ) not in {"rollback-pair", "rollback-settings", "pause", "pause-controls"}:
        raise FleetError(
            "rollback refuses unrelated pending operation "
            f"{pending_before_rollback.get('operation')!r}"
        )
    if state.get("lifecycle") == "rolled_back":
        if pair_live(ownerrepo):
            raise FleetError("rolled-back state has unexpected live pair")
        print(f"{ownerrepo}: generation {state['generation']} already rolled back")
        return 0
    if state.get("lifecycle") != "rolling_back":
        if state.get("lifecycle") not in {
            "canary",
            "canary_active",
            "qualified",
            "paused",
            "promoted",
        }:
            raise FleetError(f"rollback is invalid from lifecycle {state.get('lifecycle')!r}")
        pause_remote(ownerrepo, state)
        live = pair_live(ownerrepo)
        expected = copy.deepcopy(state.get("pair", {}))
        if set(live) != {"merge_safety", "review_gate"}:
            raise FleetError("initial rollback requires both concrete owned rulesets")
        for key in ("merge_safety", "review_gate"):
            item = live[key]
            expected_item = expected.get(key, {})
            if (
                item["id"] != expected_item.get("id")
                or item["fingerprint"] != expected_item.get("fingerprint")
                or not expected_item.get("owned")
                or type(expected_item.get("id")) is not int
            ):
                raise FleetError(f"rollback drift refusal for {key}")
        state["lifecycle"] = "rolling_back"
        state["pending"] = {
            "operation": "rollback-pair",
            "phase": "review_gate",
            "original_pair": expected,
        }
        write_state(ownerrepo, state)
    else:
        pending = state.get("pending")
        if not isinstance(pending, dict):
            raise FleetError("rollback recovery is missing its exact journal")
        if pending.get("operation") == "rollback-pair":
            expected = pending.get("original_pair")
        elif pending.get("operation") == "rollback-settings":
            snapshots = [
                item.get("original_pair")
                for item in state.get("history", [])
                if isinstance(item, dict) and item.get("operation") == "rollback-pair-deleted"
            ]
            expected = snapshots[-1] if snapshots else None
        else:
            expected = None
        if not isinstance(expected, dict):
            raise FleetError("rollback recovery is missing its original pair")
        cfg = policy()["controller"]
        run(
            [
                "gh", "variable", "set", cfg["activation_variable"],
                "--repo", ownerrepo, "--body", "false",
            ]
        )
        set_workflow_enabled(ownerrepo, False)
        cancel_and_drain(ownerrepo)
        disarm_all(ownerrepo)
    for key in ("review_gate", "merge_safety"):
        live = pair_live(ownerrepo)
        item = live.get(key)
        current_state = state["pair"][key]
        if current_state.get("id") is None:
            if item is not None:
                raise FleetError(f"{key} reappeared after recorded deletion")
            continue
        expected_item = expected[key]
        if (
            item is None
            and (state.get("pending") or {}).get("phase") == key + "_delete"
            and current_state.get("id") == expected_item["id"]
            and current_state.get("owned")
        ):
            state["pair"][key] = {
                "id": None,
                "fingerprint": digest(None),
                "owned": False,
            }
            state["pending"]["phase"] = key + "_done"
            write_state(ownerrepo, state)
            continue
        if (
            item is None
            or item["id"] != expected_item["id"]
            or item["fingerprint"] != expected_item["fingerprint"]
        ):
            raise FleetError(f"{key} changed before rollback deletion")
        state["pending"]["phase"] = key + "_delete"
        write_state(ownerrepo, state)
        gh_api(f"repos/{ownerrepo}/rulesets/{item['id']}", method="DELETE")
        if key in pair_live(ownerrepo):
            raise FleetError(f"{key} remains after rollback deletion")
        state["pair"][key] = {
            "id": None,
            "fingerprint": digest(None),
            "owned": False,
        }
        state["pending"]["phase"] = key + "_done"
        write_state(ownerrepo, state)
    pre_settings = state["rollback_preimage"]["settings"]
    recovering_rollback_settings = (
        isinstance(state.get("pending"), dict)
        and state["pending"].get("operation") == "rollback-settings"
        and isinstance(state["pending"].get("settings"), dict)
    )
    if not recovering_rollback_settings:
        state["history"].append(
            {
                "operation": "rollback-pair-deleted",
                "generation": state["generation"],
                "original_pair": expected,
                "at": now(),
            }
        )
        state["pending"]["phase"] = "settings"
        write_state(ownerrepo, state)
        state["pending"] = None
    restored = transition_settings(
        ownerrepo,
        state,
        operation="rollback-settings",
        desired=pre_settings,
    )
    if restored != pre_settings or pair_live(ownerrepo):
        raise FleetError("rollback did not restore exact preimage")
    proof = {
        "generation": state["generation"],
        "pair_ids": {key: expected[key]["id"] for key in ("merge_safety", "review_gate")},
        "pair_fingerprints": {
            key: expected[key]["fingerprint"] for key in ("merge_safety", "review_gate")
        },
        "target_branch": state["target_branch"],
        "target_sha": state["target_sha"],
        "restored_settings_fingerprint": digest(restored),
        "completed_at": now(),
    }
    proof["digest"] = digest(proof)
    state["rollback_proofs"].append(proof)
    state["lifecycle"] = "rolled_back"
    state["pending"] = None
    state["history"].append({"operation": "rollback", "generation": state["generation"], "at": now()})
    write_state(ownerrepo, state)
    print(f"{ownerrepo}: generation {state['generation']} rolled back exactly")
    return 0


def validate_evidence(
    path: Path,
    state: dict[str, Any],
    repo: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    value = load_json(path)
    required = {
        "schema", "owner_repo", "generation", "canary_branch", "canary_sha",
        "destination_branch", "controller_digests", "policy_digest",
        "ruleset_template_digests", "ruleset_ids", "ruleset_fingerprints",
        "required_check", "observed_at", "scenarios",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise FleetError("qualification evidence does not match closed schema")
    bindings = {
        "schema": "pr-automation-evidence/v2",
        "owner_repo": state["owner_repo"],
        "generation": state["generation"],
        "canary_branch": state["target_branch"],
        "canary_sha": state["target_sha"],
        "destination_branch": state["default_branch"],
        "controller_digests": {
            "canary": state["controller_digest"],
            "production": state["production_controller_digest"],
        },
        "policy_digest": state["policy_digest"],
        "ruleset_template_digests": state["template_digests"],
        "ruleset_ids": {key: state["pair"][key]["id"] for key in ("merge_safety", "review_gate")},
        "ruleset_fingerprints": {
            key: state["pair"][key]["fingerprint"] for key in ("merge_safety", "review_gate")
        },
    }
    for key, expected in bindings.items():
        if value.get(key) != expected:
            raise FleetError(f"qualification evidence binding mismatch: {key}")
    required_check = value["required_check"]
    expected_check_keys = {
        "context",
        "integration_id",
        "workflow_path",
        "workflow_run_id",
        "check_suite_id",
        "check_run_id",
        "head_sha",
    }
    if (
        not isinstance(required_check, dict)
        or set(required_check) != expected_check_keys
        or required_check.get("context") != "required / ci"
        or required_check.get("integration_id") != 15368
        or required_check.get("workflow_path")
        != config["required_workflow"]["path"]
        or any(
            type(required_check.get(key)) is not int
            or required_check[key] < 1
            for key in ("workflow_run_id", "check_suite_id", "check_run_id")
        )
        or not FULL_SHA.fullmatch(str(required_check.get("head_sha") or ""))
    ):
        raise FleetError("qualification required-check binding invalid")
    workflow_run = gh_api(
        f"repos/{state['owner_repo']}/actions/runs/{required_check['workflow_run_id']}"
    )
    if (
        workflow_run.get("path") != required_check["workflow_path"]
        or workflow_run.get("name") != config["required_workflow"]["name"]
        or workflow_run.get("event") != "pull_request"
        or workflow_run.get("status") != "completed"
        or workflow_run.get("conclusion") != "success"
        or workflow_run.get("check_suite_id") != required_check["check_suite_id"]
        or workflow_run.get("head_sha") != required_check["head_sha"]
        or len(workflow_run.get("pull_requests") or []) != 1
    ):
        raise FleetError("qualification workflow-run evidence is not exact and successful")
    try:
        completed_at = dt.datetime.fromisoformat(
            str(workflow_run.get("updated_at") or "").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise FleetError("qualification workflow run completion timestamp is invalid") from exc
    activations = [
        item
        for item in state["history"]
        if isinstance(item, dict)
        and item.get("operation")
        in {"activate-canary", "activate-canary-recovered"}
        and item.get("generation") == state["generation"]
    ]
    if not activations:
        raise FleetError("qualification lacks generation-bound canary activation")
    activated_at = dt.datetime.fromisoformat(
        str(activations[-1]["at"]).replace("Z", "+00:00")
    )
    run_age = dt.datetime.now(dt.timezone.utc) - completed_at
    if (
        completed_at < activated_at
        or run_age < dt.timedelta(0)
        or run_age > dt.timedelta(hours=24)
    ):
        raise FleetError("qualification workflow run is stale or predates activation")
    local_workflow = repo / required_check["workflow_path"]
    if (
        not local_workflow.is_file()
        or remote_file_bytes(
            state["owner_repo"],
            required_check["workflow_path"],
            required_check["head_sha"],
        )
        != local_workflow.read_bytes()
    ):
        raise FleetError("qualification workflow bytes differ from verified canary bytes")
    pull_number = workflow_run["pull_requests"][0].get("number")
    pull = gh_api(f"repos/{state['owner_repo']}/pulls/{pull_number}")
    if (
        (pull.get("base") or {}).get("ref") != state["target_branch"]
        or (pull.get("head") or {}).get("sha") != required_check["head_sha"]
    ):
        raise FleetError("qualification required-check PR tuple is not canary-bound")
    checks = gh_api(
        f"repos/{state['owner_repo']}/check-suites/"
        f"{required_check['check_suite_id']}/check-runs?per_page=100"
    )
    context_checks = [
        item
        for item in checks.get("check_runs", [])
        if item.get("name") == "required / ci"
        and (item.get("app") or {}).get("id") == 15368
    ]
    if (
        len(context_checks) != 1
        or context_checks[0].get("id") != required_check["check_run_id"]
        or context_checks[0].get("conclusion") != "success"
    ):
        raise FleetError("qualification required-check run is not unique literal success")
    scenarios = value.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != len(SCENARIOS):
        raise FleetError("qualification evidence must contain the exact scenario set")
    by_id = {entry.get("id"): entry for entry in scenarios if isinstance(entry, dict)}
    if set(by_id) != set(SCENARIOS):
        raise FleetError("qualification evidence scenario ids are incomplete/duplicated")
    for scenario_id, entry in by_id.items():
        if set(entry) != {"id", "mode", "outcome", "evidence"}:
            raise FleetError(f"scenario {scenario_id} shape invalid")
        if entry["outcome"] != "pass" or entry["mode"] not in {"live", "mocked"}:
            raise FleetError(f"scenario {scenario_id} did not pass")
        if entry["mode"] == "mocked" and scenario_id not in MOCKABLE_SCENARIOS:
            raise FleetError(f"scenario {scenario_id} must be live")
        if (
            not isinstance(entry["evidence"], str)
            or not re.fullmatch(
                r"https://github\.com/KleinPerkins/[A-Za-z0-9._-]+/(?:pull|actions/runs)/[0-9]+(?:#.*)?",
                entry["evidence"].strip(),
            )
        ):
            raise FleetError(f"scenario {scenario_id} lacks evidence")
    observed = dt.datetime.fromisoformat(value["observed_at"].replace("Z", "+00:00"))
    age = dt.datetime.now(dt.timezone.utc) - observed
    if (
        age < dt.timedelta(0)
        or age > dt.timedelta(hours=24)
        or abs(observed - completed_at) > dt.timedelta(minutes=5)
    ):
        raise FleetError("qualification evidence is stale")
    return value


def cmd_qualify(repo: Path, *, evidence: Path) -> int:
    ownerrepo = validate_target(repo, clean=True)
    errors = verify_local(repo)
    if errors:
        raise FleetError("local Phase B verification failed: " + "; ".join(errors))
    state = read_state(ownerrepo)
    if (
        not state
        or state.get("generation") != 2
        or state.get("lifecycle") != "paused"
        or state.get("pending") is not None
    ):
        raise FleetError("qualification requires paused, fully drained generation 2")
    config = phase_b_config(repo)
    if (
        config["repository"]["base_branch"] != state["target_branch"]
        or digest(render_controller(config)) != state["controller_digest"]
    ):
        raise FleetError("qualification canary controller binding changed")
    require_exact_head(repo, ownerrepo, state["target_branch"])
    assert_remote_managed_files(
        repo,
        ownerrepo,
        state["default_branch"],
        include_required=False,
        expected_config=policy_for_branch(config, state["default_branch"]),
    )
    assert_remote_managed_files(
        repo, ownerrepo, state["target_branch"], include_required=True
    )
    desired = render_rulesets(state["target_branch"])
    live = pair_live(ownerrepo)
    for key in ("merge_safety", "review_gate"):
        stored = state["pair"][key]
        if (
            type(stored.get("id")) is not int
            or not stored.get("owned")
            or key not in live
            or live[key]["id"] != stored["id"]
            or live[key]["fingerprint"] != stored["fingerprint"]
            or normalize_ruleset(live[key]["value"]) != normalize_ruleset(desired[key])
        ):
            raise FleetError(f"qualification live canary pair mismatch: {key}")
    activation = credential_metadata(ownerrepo)["activation"]
    if (
        activation is None
        or str(activation.get("value")) != "false"
        or controller_workflow_state(ownerrepo) != "disabled_manually"
        or open_pulls(ownerrepo)
        or armed_pulls(ownerrepo)
        or any(
            item.get("status")
            in {"queued", "in_progress", "requested", "waiting", "pending"}
            for item in controller_runs(ownerrepo)
        )
    ):
        raise FleetError(
            "qualification requires inert controls, zero open PRs, and zero residual activity"
        )
    valid_generation_one = False
    for proof in state.get("rollback_proofs", []):
        unsigned = copy.deepcopy(proof)
        recorded_digest = unsigned.pop("digest", None)
        pair_ids = proof.get("pair_ids") if isinstance(proof, dict) else None
        pair_fingerprints = proof.get("pair_fingerprints") if isinstance(proof, dict) else None
        if (
            proof.get("generation") == 1
            and recorded_digest == digest(unsigned)
            and isinstance(pair_ids, dict)
            and all(type(pair_ids.get(key)) is int for key in ("merge_safety", "review_gate"))
            and isinstance(pair_fingerprints, dict)
            and all(
                FULL_DIGEST.fullmatch(str(pair_fingerprints.get(key) or ""))
                for key in ("merge_safety", "review_gate")
            )
            and all(
                pair_ids[key] != state["pair"][key]["id"]
                for key in ("merge_safety", "review_gate")
            )
        ):
            valid_generation_one = True
    if not valid_generation_one:
        raise FleetError("qualification requires the exact generation-1 pair rollback proof")
    value = validate_evidence(evidence, state, repo, config)
    state["qualification"] = {
        "schema": "pr-automation-evidence-summary/v2",
        "digest": digest(value),
        "observed_at": value["observed_at"],
        "required_check": value["required_check"],
        "scenario_modes": {entry["id"]: entry["mode"] for entry in value["scenarios"]},
    }
    state["lifecycle"] = "qualified"
    state["history"].append({"operation": "qualify", "evidence_digest": digest(value), "at": now()})
    write_state(ownerrepo, state)
    print(f"{ownerrepo}: generation {state['generation']} qualification accepted")
    return 0


def update_ruleset_exact(
    ownerrepo: str,
    state: dict[str, Any],
    key: str,
    current: dict[str, Any],
    desired: dict[str, Any],
    destination_sha: str,
) -> dict[str, Any]:
    desired_fingerprint = digest(normalize_ruleset(desired))
    pending = state.get("pending")
    if (
        isinstance(pending, dict)
        and pending.get("operation") == "promote"
        and pending.get("key") == key
    ):
        if (
            pending.get("id") != current["id"]
            or pending.get("desired_fingerprint") != desired_fingerprint
            or pending.get("destination_sha") != destination_sha
        ):
            raise FleetError(f"{key} promotion recovery binding changed")
        if current["fingerprint"] == desired_fingerprint:
            return {
                "id": current["id"],
                "fingerprint": desired_fingerprint,
                "owned": True,
            }
        if current["fingerprint"] != pending.get("preimage_fingerprint"):
            raise FleetError(f"{key} promotion recovery found a third state")
    else:
        pending = {
            "operation": "promote",
            "key": key,
            "id": current["id"],
            "preimage": normalize_ruleset(current["value"]),
            "preimage_fingerprint": current["fingerprint"],
            "desired": normalize_ruleset(desired),
            "desired_fingerprint": desired_fingerprint,
            "destination_branch": state["default_branch"],
            "destination_sha": destination_sha,
        }
        state["pending"] = pending
        write_state(ownerrepo, state)
    reread = gh_api(f"repos/{ownerrepo}/rulesets/{current['id']}")
    if digest(normalize_ruleset(reread)) != pending["preimage_fingerprint"]:
        raise FleetError(f"{key} changed immediately before retarget")
    gh_api(f"repos/{ownerrepo}/rulesets/{current['id']}", method="PUT", payload=desired)
    post = gh_api(f"repos/{ownerrepo}/rulesets/{current['id']}")
    if normalize_ruleset(post) != normalize_ruleset(desired):
        raise FleetError(f"{key} retarget postimage mismatch")
    return {
        "id": current["id"],
        "fingerprint": digest(normalize_ruleset(post)),
        "owned": True,
    }


def cmd_promote(repo: Path) -> int:
    ownerrepo = validate_target(repo, clean=True)
    require_gh()
    state = read_state(ownerrepo)
    if not state or state.get("lifecycle") != "qualified":
        raise FleetError("promotion requires qualified generation")
    default = state["default_branch"]
    if str(remote_repo(ownerrepo).get("default_branch") or "") != default:
        raise FleetError("default branch changed since canary creation")
    current_config = phase_b_config(repo)
    if (
        digest(render_controller(current_config)) != state["controller_digest"]
        or digest(policy()) != state["policy_digest"]
        or template_digests() != state["template_digests"]
    ):
        raise FleetError("qualified canary artifacts changed; requalification required")
    pending_before = state.get("pending")
    exact_destination_sha = require_exact_head(repo, ownerrepo, default)
    persisted_destination = (
        pending_before.get("destination_sha")
        if isinstance(pending_before, dict)
        and pending_before.get("operation") in {"promote", "promote-stage"}
        else None
    )
    destination_sha = persisted_destination or exact_destination_sha
    live = pair_live(ownerrepo)
    desired = render_rulesets(default)
    pending = state.get("pending")
    for key in ("merge_safety", "review_gate"):
        allowed_fingerprints = {state["pair"][key]["fingerprint"]}
        if (
            isinstance(pending, dict)
            and pending.get("operation") in {"promote", "promote-stage"}
        ):
            allowed_fingerprints.add(digest(normalize_ruleset(desired[key])))
        if (
            key not in live
            or live[key]["id"] != state["pair"][key]["id"]
            or live[key]["fingerprint"] not in allowed_fingerprints
        ):
            raise FleetError(f"promotion drift refusal for {key}")
    outstanding = [
        key
        for key in ("merge_safety", "review_gate")
        if live[key]["fingerprint"] != digest(normalize_ruleset(desired[key]))
    ]
    if not outstanding:
        for key in ("merge_safety", "review_gate"):
            state["pair"][key] = {
                "id": live[key]["id"],
                "fingerprint": live[key]["fingerprint"],
                "owned": True,
            }
        state["target_branch"] = default
        state["target_sha"] = destination_sha
        state["lifecycle"] = "promoted"
        state["pending"] = None
        state["history"].append(
            {
                "operation": "promote-recovered",
                "destination_sha": destination_sha,
                "at": now(),
            }
        )
        write_state(ownerrepo, state)
        print(f"{ownerrepo}: promotion finalized from exact applied postimages")
        return 0
    qualified_at = dt.datetime.fromisoformat(
        str(state["qualification"]["observed_at"]).replace("Z", "+00:00")
    )
    age = dt.datetime.now(dt.timezone.utc) - qualified_at
    if age < dt.timedelta(0) or age > dt.timedelta(hours=24):
        raise FleetError(
            "qualification evidence is stale before an outstanding promotion write; "
            "rollback and requalify"
        )
    if persisted_destination and persisted_destination != exact_destination_sha:
        destination_sha = exact_destination_sha
        if not isinstance(state.get("pending"), dict):
            raise FleetError("promotion destination refresh lacks its exact journal")
        state["pending"]["destination_sha"] = destination_sha
        state["history"].append(
            {
                "operation": "promote-destination-refreshed",
                "destination_sha": destination_sha,
                "at": now(),
            }
        )
        write_state(ownerrepo, state)
    if (
        live["merge_safety"]["fingerprint"]
        == digest(normalize_ruleset(desired["merge_safety"]))
        and state["pair"]["merge_safety"]["fingerprint"]
        == live["merge_safety"]["fingerprint"]
    ):
        state["pair"]["merge_safety"] = {
            "id": live["merge_safety"]["id"],
            "fingerprint": live["merge_safety"]["fingerprint"],
            "owned": True,
        }
    else:
        state["pair"]["merge_safety"] = update_ruleset_exact(
            ownerrepo,
            state,
            "merge_safety",
            live["merge_safety"],
            desired["merge_safety"],
            destination_sha,
        )
    state["pending"] = {
        "operation": "promote-stage",
        "phase": "merge_safety_done",
        "destination_sha": destination_sha,
    }
    write_state(ownerrepo, state)
    refreshed = pair_live(ownerrepo)
    state["pair"]["review_gate"] = update_ruleset_exact(
        ownerrepo,
        state,
        "review_gate",
        refreshed["review_gate"],
        desired["review_gate"],
        destination_sha,
    )
    state["target_branch"] = default
    state["target_sha"] = destination_sha
    state["lifecycle"] = "promoted"
    state["pending"] = None
    state["history"].append({"operation": "promote", "destination_sha": destination_sha, "at": now()})
    write_state(ownerrepo, state)
    print(f"{ownerrepo}: generation {state['generation']} pair promoted in place")
    return 0


def required_check_observation(
    repo: Path,
    ownerrepo: str,
    config: dict[str, Any],
    *,
    not_before: dt.datetime,
) -> dict[str, Any]:
    workflow_path = config["required_workflow"]["path"]
    local_workflow = repo / workflow_path
    if not local_workflow.is_file():
        raise FleetError("required workflow file is missing locally")
    workflow_digest = hashlib.sha256(local_workflow.read_bytes()).hexdigest()
    encoded = quote(workflow_path, safe="")
    pages = gh_api(
        f"repos/{ownerrepo}/actions/workflows/{encoded}/runs"
        "?event=pull_request&status=completed&per_page=100",
        paginate=True,
    )
    if not isinstance(pages, list) or not all(isinstance(page, dict) for page in pages):
        raise FleetError("required workflow run pagination is malformed")
    runs = [item for page in pages for item in page.get("workflow_runs", [])]
    for run_record in runs:
        sha = str(run_record.get("head_sha") or "")
        suite_id = run_record.get("check_suite_id")
        try:
            completed_at = dt.datetime.fromisoformat(
                str(run_record.get("updated_at") or "").replace("Z", "+00:00")
            )
        except ValueError:
            continue
        if (
            not FULL_SHA.fullmatch(sha)
            or type(suite_id) is not int
            or run_record.get("path") != workflow_path
            or run_record.get("name") != config["required_workflow"]["name"]
            or run_record.get("event") != "pull_request"
            or run_record.get("conclusion") != "success"
            or len(run_record.get("pull_requests") or []) != 1
            or completed_at < not_before
            or dt.datetime.now(dt.timezone.utc) - completed_at > dt.timedelta(hours=24)
        ):
            continue
        if hashlib.sha256(
            remote_file_bytes(ownerrepo, workflow_path, sha)
        ).hexdigest() != workflow_digest:
            continue
        checks = gh_api(
            f"repos/{ownerrepo}/check-suites/{suite_id}/check-runs?per_page=100"
        )
        matches = [
            item for item in checks.get("check_runs", [])
            if item.get("name") == "required / ci"
            and (item.get("app") or {}).get("id") == 15368
        ]
        if len(matches) == 1 and matches[0].get("conclusion") == "success":
            return {
                "workflow_run_id": run_record.get("id"),
                "head_sha": sha,
                "check_run_id": matches[0].get("id"),
                "check_suite_id": suite_id,
                "workflow_path": workflow_path,
                "context": "required / ci",
                "integration_id": 15368,
            }
    raise FleetError("no recent unique literal-success required / ci observation")


def cmd_activate(repo: Path) -> int:
    ownerrepo = validate_target(repo, clean=True)
    require_gh()
    state = read_state(ownerrepo)
    if not state or state.get("lifecycle") not in {"promoted", "paused", "active"}:
        raise FleetError("activation requires promoted or paused state")
    default = state["default_branch"]
    if str(remote_repo(ownerrepo).get("default_branch") or "") != default:
        raise FleetError("default branch changed since qualification")
    require_exact_head(repo, ownerrepo, default)
    errors = verify_local(repo)
    if errors:
        raise FleetError("local Phase B verification failed: " + "; ".join(errors))
    current_config = phase_b_config(repo)
    if current_config["repository"]["base_branch"] != default:
        raise FleetError("production policy base branch is not the default branch")
    assert_remote_managed_files(repo, ownerrepo, default, include_required=True)
    if (
        not isinstance(state.get("qualification"), dict)
        or digest(render_controller(current_config))
        != state["production_controller_digest"]
        or digest(policy()) != state["policy_digest"]
        or template_digests() != state["template_digests"]
    ):
        raise FleetError("production artifacts differ from qualified bindings")
    live = pair_live(ownerrepo)
    desired = render_rulesets(default)
    for key in ("merge_safety", "review_gate"):
        if (
            key not in live
            or live[key]["id"] != state["pair"][key]["id"]
            or normalize_ruleset(live[key]["value"]) != normalize_ruleset(desired[key])
        ):
            raise FleetError(f"activation pair postimage mismatch: {key}")
    credentials = credential_metadata(ownerrepo)
    if not all(credentials.values()):
        raise FleetError("activation credentials missing by name")
    if str(credentials["variable"].get("value")) != str(policy()["controller"]["app_id"]):
        raise FleetError("AUTOMERGE_APP_ID differs from closed policy")
    if state.get("lifecycle") == "active":
        if (
            str(credentials["activation"].get("value")) == "true"
            and controller_workflow_state(ownerrepo) == "active"
            and settings_live(ownerrepo) == policy()["settings"]
        ):
            print(f"{ownerrepo}: controller already active and exact")
            return 0
        raise FleetError("active lifecycle live controls drifted; pause before recovery")
    activation_pending = (
        isinstance(state.get("pending"), dict)
        and state["pending"].get("operation") == "activate"
        and state["pending"].get("phase") == "activation-enable"
    )
    if (
        str(credentials["activation"].get("value")) == "true"
        and activation_pending
        and controller_workflow_state(ownerrepo) == "active"
        and settings_live(ownerrepo) == policy()["settings"]
        and isinstance(state["pending"].get("required_check"), dict)
    ):
        check = state["pending"]["required_check"]
        state["pending"] = None
        state["lifecycle"] = "active"
        state["history"].append(
            {"operation": "activate-recovered", "required_check": check, "at": now()}
        )
        write_state(ownerrepo, state)
        print(f"{ownerrepo}: controller activation finalized from exact postimage")
        return 0
    if str(credentials["activation"].get("value")) != "false":
        raise FleetError("activation variable must be false immediately before activation")
    promote_events = [
        item
        for item in state["history"]
        if isinstance(item, dict) and item.get("operation") == "promote"
    ]
    if not promote_events:
        raise FleetError("activation is missing its promotion journal")
    promoted_at = dt.datetime.fromisoformat(
        str(promote_events[-1]["at"]).replace("Z", "+00:00")
    )
    authorizations = [
        item
        for item in state["history"]
        if isinstance(item, dict)
        and item.get("operation") == "activate-authorized"
        and isinstance(item.get("required_check"), dict)
    ]
    if (
        isinstance(state.get("pending"), dict)
        and state["pending"].get("operation")
        in {"activate-authorized", "activate-settings", "activate"}
        and authorizations
    ):
        check = authorizations[-1]["required_check"]
    else:
        check = required_check_observation(
            repo,
            ownerrepo,
            current_config,
            not_before=promoted_at,
        )
        state["history"].append(
            {"operation": "activate-authorized", "required_check": check, "at": now()}
        )
        state["pending"] = {
            "operation": "activate-authorized",
            "required_check": check,
        }
        write_state(ownerrepo, state)
    transition_settings(
        ownerrepo,
        state,
        operation="activate-settings",
        desired=policy()["settings"],
    )
    state["pending"] = {
        "operation": "activate",
        "phase": "workflow-enable",
        "required_check": check,
    }
    write_state(ownerrepo, state)
    set_workflow_enabled(ownerrepo, True)
    state["pending"] = {
        "operation": "activate",
        "phase": "activation-enable",
        "required_check": check,
    }
    write_state(ownerrepo, state)
    activation = set_activation(ownerrepo, True)
    state["credentials"]["activation"]["updated_at"] = activation.get("updated_at")
    state["pending"] = None
    state["lifecycle"] = "active"
    state["history"].append({"operation": "activate", "required_check": check, "at": now()})
    write_state(ownerrepo, state)
    print(f"{ownerrepo}: controller active; required check bound to integration 15368")
    return 0


def cmd_repair(repo: Path) -> int:
    ownerrepo = validate_target(repo, clean=True)
    state = read_state(ownerrepo)
    if not state:
        raise FleetError("no Phase B state")
    pending = state.get("pending")
    if isinstance(pending, dict):
        operation = pending.get("operation")
        if operation == "create-pair":
            return cmd_enforce_canary(repo, target_branch=state["target_branch"])
        if operation in {"activate-canary", "activate-canary-settings"}:
            return cmd_activate_canary(repo)
        if operation in {"promote", "promote-stage"}:
            return cmd_promote(repo)
        if operation in {"activate-authorized", "activate-settings", "activate"}:
            return cmd_activate(repo)
        if operation in {"pause-controls", "pause"}:
            return cmd_pause(repo)
        if operation == "credential-provision":
            return cmd_credential_provision(
                repo, key_file=None, preserve_existing_secret=True
            )
    if state.get("lifecycle") == "rolling_back":
        return cmd_rollback(repo)
    if (
        isinstance(state.get("pending"), dict)
        and state["pending"].get("operation") == "credential-revoke"
    ):
        return cmd_credential_revoke(repo)
    if state.get("lifecycle") == "paused":
        pause_remote(ownerrepo, state)
        state["pending"] = None
        state["history"].append({"operation": "repair-paused", "at": now()})
        write_state(ownerrepo, state)
        print(f"{ownerrepo}: paused controls repaired and drained")
        return 0
    if state.get("lifecycle") == "active":
        try:
            return cmd_activate(repo)
        except FleetError:
            cmd_pause(repo)
            return cmd_activate(repo)
    raise FleetError(
        f"repair has no safe implicit transition from {state.get('lifecycle')!r}; "
        "resume the explicit lifecycle verb"
    )


def cmd_credential_revoke(repo: Path) -> int:
    ownerrepo = validate_target(repo, clean=True)
    require_gh()
    state = read_state(ownerrepo)
    if not state:
        raise FleetError("no Phase B state")
    if state.get("lifecycle") == "credentials_revoked":
        print(f"{ownerrepo}: task-owned credential names already revoked")
        return 0
    if state.get("lifecycle") != "rolled_back" or pair_live(ownerrepo):
        raise FleetError("credential revoke requires rolled_back state with no managed pair")
    if state.get("pending") is not None and state["pending"].get(
        "operation"
    ) != "credential-revoke":
        raise FleetError("credential revoke refuses an unrelated pending operation")
    prior_pending = copy.deepcopy(state.get("pending"))
    activation_before = credential_metadata(ownerrepo)["activation"]
    if activation_before is not None:
        activation_after = set_activation(ownerrepo, False)
        state["credentials"]["activation"]["updated_at"] = activation_after.get(
            "updated_at"
        )
    set_workflow_enabled(ownerrepo, False)
    cancel_and_drain(ownerrepo)
    disarm_all(ownerrepo)
    cfg = policy()["controller"]
    commands = {
        "secret": ["gh", "secret", "delete", cfg["private_key_secret"], "--repo", ownerrepo],
        "variable": ["gh", "variable", "delete", cfg["app_id_variable"], "--repo", ownerrepo],
        "activation": ["gh", "variable", "delete", cfg["activation_variable"], "--repo", ownerrepo],
    }
    state["pending"] = {
        "operation": "credential-revoke",
        "phase": (
            prior_pending.get("phase")
            if isinstance(prior_pending, dict)
            and prior_pending.get("operation") == "credential-revoke"
            else "start"
        ),
    }
    write_state(ownerrepo, state)
    for key, command in commands.items():
        if state["credentials"][key]["owned"]:
            metadata = credential_metadata(ownerrepo)
            if metadata[key] is None:
                if (
                    prior_pending
                    and prior_pending.get("operation") == "credential-revoke"
                    and prior_pending.get("phase") == key + "_delete"
                ):
                    state["credentials"][key]["owned"] = False
                    state["credentials"][key]["updated_at"] = None
                    state["pending"]["phase"] = key + "_done"
                    write_state(ownerrepo, state)
                    continue
                raise FleetError(f"task-owned credential {key} disappeared before revoke")
            recorded_at = state["credentials"][key].get("updated_at")
            if recorded_at and metadata[key].get("updated_at") != recorded_at:
                raise FleetError(f"credential {key} changed since provisioning")
            state["pending"]["phase"] = key + "_delete"
            state["pending"]["updated_at"] = metadata[key].get("updated_at")
            write_state(ownerrepo, state)
            run(command)
            if credential_metadata(ownerrepo)[key] is not None:
                raise FleetError(f"credential {key} remains after revoke")
            state["credentials"][key]["owned"] = False
            state["credentials"][key]["updated_at"] = None
            state["pending"]["phase"] = key + "_done"
            write_state(ownerrepo, state)
    state["pending"] = None
    state["lifecycle"] = "credentials_revoked"
    state["history"].append({"operation": "credential-revoke", "at": now()})
    write_state(ownerrepo, state)
    print(f"{ownerrepo}: task-owned credential names revoked; pre-existing values preserved")
    return 0


def cmd_status(repo: Path) -> int:
    ownerrepo = validate_target(repo, clean=False)
    require_gh()
    errors = verify_local(repo)
    state = read_state(ownerrepo)
    live = pair_live(ownerrepo)
    metadata = credential_metadata(ownerrepo)
    settings = settings_live(ownerrepo)
    marker_result = run(
        [
            "gh",
            "api",
            f"repos/{ownerrepo}/actions/variables/{REMOTE_STATE_VARIABLE}",
        ],
        check=False,
    )
    remote_marker = None
    if marker_result.returncode == 0:
        remote_marker = json.loads(str(marker_result.stdout)).get("value")
    local_marker = local_state_marker(ownerrepo)
    running = [
        item for item in controller_runs(ownerrepo)
        if item.get("status") in {"queued", "in_progress", "requested", "waiting", "pending"}
    ]
    result = {
        "owner_repo": ownerrepo,
        "local": "COMPLIANT" if not errors else "NONCOMPLIANT",
        "local_errors": errors,
        "lifecycle": state.get("lifecycle") if state else "unmanaged",
        "generation": state.get("generation") if state else 0,
        "pending": state.get("pending") if state else None,
        "activation_value": (
            str(metadata["activation"].get("value"))
            if metadata["activation"]
            else None
        ),
        "controller_workflow_state": controller_workflow_state(
            ownerrepo, required=False
        ),
        "state_marker": {
            "local": local_marker,
            "remote": remote_marker,
            "parity": local_marker == remote_marker,
        },
        "settings": {
            "live": settings,
            "managed": state.get("managed_settings") if state else None,
            "exact": bool(state and settings == state.get("managed_settings")),
        },
        "pair": {
            key: {"id": item["id"], "fingerprint": item["fingerprint"]}
            for key, item in live.items()
        },
        "pair_state_exact": bool(
            state
            and all(
                (
                    state["pair"][key]["id"] is None
                    and key not in live
                )
                or (
                    key in live
                    and live[key]["id"] == state["pair"][key]["id"]
                    and live[key]["fingerprint"]
                    == state["pair"][key]["fingerprint"]
                )
                for key in ("merge_safety", "review_gate")
            )
        ),
        "required_context": "required / ci",
        "required_integration": 15368,
        "credential_names": {
            key: value.get("name") if value else None for key, value in metadata.items()
        },
        "credential_ownership": (
            {
                key: {
                    "owned": state["credentials"][key]["owned"],
                    "present": metadata[key] is not None,
                    "updated_at_exact": (
                        metadata[key] is not None
                        and metadata[key].get("updated_at")
                        == state["credentials"][key].get("updated_at")
                    ),
                }
                for key in ("variable", "secret", "activation")
            }
            if state
            else None
        ),
        "open_prs": len(open_pulls(ownerrepo)),
        "armed_auto_merges": len(armed_pulls(ownerrepo)),
        "running_controller_runs": len(running),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_inventory() -> int:
    require_gh()
    manifest = fleet()
    rows = []
    for entry in manifest["targets"]:
        ownerrepo = entry["repo"]
        remote = remote_repo(ownerrepo)
        rows.append(
            {
                **entry,
                "default_branch": remote.get("default_branch"),
                "archived": remote.get("archived"),
                "fork": remote.get("fork"),
                "actions": run(
                    ["gh", "api", f"repos/{ownerrepo}/actions/permissions"],
                    check=False,
                ).returncode
                == 0,
                "pair_present": sorted(pair_live(ownerrepo)),
                "credential_names": {
                    key: value.get("name") if value else None
                    for key, value in credential_metadata(ownerrepo).items()
                },
            }
        )
    print(
        json.dumps(
            {
                "schema": manifest["schema"],
                "targets": rows,
                "already_compliant": manifest["already_compliant"],
                "excluded": manifest["excluded"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def dispatch_repo_command(args: argparse.Namespace, repo: Path) -> int:
    if args.verb == "verify":
        return cmd_verify(repo)
    if args.verb == "apply":
        return cmd_apply(
            repo,
            dry_run=args.dry_run,
            base_branch=args.base_branch,
            workflow_name=args.required_workflow_name,
            workflow_path=args.required_workflow_path,
        )
    if args.verb == "preflight":
        return cmd_preflight(repo, target_branch=args.target_branch)
    if args.verb == "credential-status":
        return cmd_credential_status(repo)
    if args.verb == "credential-provision":
        return cmd_credential_provision(
            repo,
            key_file=(
                args.key_file.expanduser().resolve()
                if args.key_file is not None
                else None
            ),
            preserve_existing_secret=args.preserve_existing_secret,
        )
    if args.verb == "enforce-canary":
        return cmd_enforce_canary(repo, target_branch=args.target_branch)
    if args.verb == "activate-canary":
        return cmd_activate_canary(repo)
    if args.verb == "qualify":
        return cmd_qualify(repo, evidence=args.evidence.expanduser().resolve())
    if args.verb == "promote":
        return cmd_promote(repo)
    if args.verb == "pause":
        return cmd_pause(repo)
    if args.verb == "repair":
        return cmd_repair(repo)
    if args.verb == "rollback":
        return cmd_rollback(repo)
    if args.verb == "activate":
        return cmd_activate(repo)
    if args.verb == "credential-revoke":
        return cmd_credential_revoke(repo)
    if args.verb == "status":
        return cmd_status(repo)
    raise AssertionError(args.verb)


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"inventory", "verify", "status", "credential-status", "--help", "-h"}:
        print("REFUSED: retired controller mutation; historical inspection only", file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("inventory")
    for verb in (
        "verify",
        "status",
        "credential-status",
        "activate-canary",
        "pause",
        "repair",
        "rollback",
        "activate",
        "credential-revoke",
    ):
        command = sub.add_parser(verb)
        command.add_argument("repo")
    apply = sub.add_parser("apply")
    apply.add_argument("repo")
    apply.add_argument("--dry-run", action="store_true")
    apply.add_argument("--base-branch")
    apply.add_argument("--required-workflow-name")
    apply.add_argument("--required-workflow-path")
    preflight = sub.add_parser("preflight")
    preflight.add_argument("repo")
    preflight.add_argument("--target-branch")
    provision = sub.add_parser("credential-provision")
    provision.add_argument("repo")
    provision.add_argument("--key-file", type=Path)
    provision.add_argument("--preserve-existing-secret", action="store_true")
    enforce = sub.add_parser("enforce-canary")
    enforce.add_argument("repo")
    enforce.add_argument("--target-branch", required=True)
    qualify = sub.add_parser("qualify")
    qualify.add_argument("repo")
    qualify.add_argument("--evidence", type=Path, required=True)
    promote = sub.add_parser("promote")
    promote.add_argument("repo")
    args = parser.parse_args(argv)
    try:
        if args.verb == "inventory":
            return cmd_inventory()
        repo = resolve_repo(args.repo)
        lock_handle = (
            acquire_repo_lock(owner_repo(repo))
            if args.verb in MUTATING_VERBS
            else None
        )
        _ = lock_handle
        if args.verb in REMOTE_MUTATING_VERBS:
            target = validate_target(repo, clean=True)
            with remote_repo_lock(target, args.verb):
                return dispatch_repo_command(args, repo)
        return dispatch_repo_command(args, repo)
    except (FleetError, phase_a.ProfileError) as exc:
        print(f"pr-automation Phase B: {exc}", file=sys.stderr)
        return 1
    finally:
        handle = locals().get("lock_handle")
        if handle is not None:
            handle.close()
    raise AssertionError(args.verb)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
