#!/usr/bin/env python3
"""Phase A PR-automation profile lifecycle.

Stdlib-only by design. Local verbs never need GitHub; remote verbs shell out to authenticated `gh`.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlsplit


HERE = Path(__file__).resolve().parent
DEV_ROOT = HERE.parents[3]
BASELINE_ROOT = HERE.parents[1]
CONFIG_SOURCE = HERE / "config.json"
SCHEMA_SOURCE = HERE / "config.schema.json"
CANARY_PROOF_SCHEMA_SOURCE = HERE / "canary-proof.schema.json"
RULESET_TEMPLATE = HERE / "ruleset.json.tmpl"
WORKFLOW_SOURCE = HERE / "required.yml"
CODEOWNERS_BLOCK_SOURCE = HERE / "CODEOWNERS.block"
BASELINE_CODEOWNERS = BASELINE_ROOT / "template" / "CODEOWNERS"
STATE_DIR = HERE / "state"

PROFILE_NAME = "pr-automation"
RULESET_NAME = "kleinperkins-pr-automation"
HISTORY_RULESET_NAME = "kleinperkins-dev-baseline"
CONFIG_REL = Path(".github/pr-automation.json")
WORKFLOW_REL = Path(".github/workflows/required.yml")
CODEOWNERS_REL = Path(".github/CODEOWNERS")
MANAGED_SETTINGS = (
    "allow_auto_merge",
    "delete_branch_on_merge",
    "allow_update_branch",
)
CODEOWNERS_BEGIN = "# BEGIN KleinPerkins/dev pr-automation protected paths (managed; do not hand-edit)"
CODEOWNERS_END = "# END KleinPerkins/dev pr-automation protected paths"
WORKFLOW_MARKER = "# BEGIN KleinPerkins/dev pr-automation (managed; do not hand-edit)"
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
FULL_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
CANARY_PROOF_MAX_AGE = dt.timedelta(hours=24)
CANARY_SCENARIOS = (
    "direct_push",
    "red",
    "cancelled",
    "missing",
    "stale",
    "conflict",
    "draft",
    "non_15368_spoof",
    "skipped_neutral_managed_path",
    "green_native_auto_merge",
    "manual_update",
    "protected_path_self_authorization",
    "history_ruleset_unchanged",
    "pause",
    "rollback",
)
MANDATORY_LIVE_CANARY_SCENARIOS = frozenset(
    {
        "direct_push",
        "red",
        "cancelled",
        "missing",
        "stale",
        "non_15368_spoof",
        "skipped_neutral_managed_path",
        "green_native_auto_merge",
        "manual_update",
        "protected_path_self_authorization",
        "history_ruleset_unchanged",
        "pause",
    }
)


class ProfileError(RuntimeError):
    pass


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def run(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        input=input_text,
        text=True,
        capture_output=True,
    )
    if check and proc.returncode:
        detail = (proc.stderr or proc.stdout).strip()
        raise ProfileError(f"command failed ({' '.join(args)}): {detail}")
    return proc


def git(repo: Path, *args: str, check: bool = True) -> str:
    return run(["git", "-C", str(repo), *args], check=check).stdout.strip()


def resolve_repo(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise ProfileError(f"no such directory: {path}")
    top = git(path, "rev-parse", "--show-toplevel")
    return Path(top).resolve()


def owner_repo(repo: Path) -> str:
    url = git(repo, "config", "--get", "remote.origin.url", check=False)
    match = re.search(r"github\.com(?::|/)([^/]+)/([^/]+?)(?:\.git)?$", url)
    if not match:
        raise ProfileError("origin must be a GitHub repository")
    return f"{match.group(1)}/{match.group(2)}"


def validate_target(repo: Path, *, require_clean: bool) -> str:
    ownerrepo = owner_repo(repo)
    if ownerrepo.lower().split("/", 1)[0] != "kleinperkins":
        raise ProfileError(f"refusing non-KleinPerkins origin: {ownerrepo}")
    if repo == DEV_ROOT:
        raise ProfileError("refusing ~/dev umbrella repo")
    lowered = str(repo).lower()
    if "/affirm/" in lowered or ownerrepo.lower() == "affirm/card-platform-product":
        raise ProfileError("refusing Affirm/governed repository")
    if ownerrepo.lower() == "kleinperkins/chaos-scheduler":
        raise ProfileError("refusing hard-excluded chaos-scheduler")
    branch = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if not branch:
        raise ProfileError("refusing detached HEAD")
    has_head = bool(git(repo, "rev-parse", "--verify", "HEAD", check=False))
    if require_clean and has_head and git(repo, "status", "--porcelain"):
        raise ProfileError("refusing dirty working tree")
    return ownerrepo


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"invalid JSON at {path}: {exc}") from exc


def load_config(path: Path = CONFIG_SOURCE) -> dict[str, Any]:
    data = load_json(path)
    validate_config(data)
    return data


def validate_config(data: Any) -> None:
    if not isinstance(data, dict):
        raise ProfileError("profile config must be an object")
    expected_keys = {
        "schema",
        "profile",
        "ruleset_name",
        "required_check",
        "settings",
        "merge_method",
        "protected_paths",
    }
    if set(data) != expected_keys:
        raise ProfileError(f"profile config keys must be exactly {sorted(expected_keys)}")
    literals = {
        "schema": "pr-automation/v1",
        "profile": PROFILE_NAME,
        "ruleset_name": RULESET_NAME,
        "merge_method": "squash",
    }
    for key, value in literals.items():
        if data.get(key) != value:
            raise ProfileError(f"{key} must equal {value!r}")
    if data.get("required_check") != {
        "context": "required / ci",
        "integration_id": 15368,
    }:
        raise ProfileError("required_check must be required / ci bound to integration 15368")
    if data.get("settings") != {key: True for key in MANAGED_SETTINGS}:
        raise ProfileError(f"settings must set exactly {', '.join(MANAGED_SETTINGS)} to true")
    paths = data.get("protected_paths")
    required_paths = {
        ".github/workflows/**",
        ".github/actions/**",
        ".github/scripts/**",
        ".github/CODEOWNERS",
        ".github/dependabot.yml",
        ".github/pr-automation.json",
    }
    if not isinstance(paths, list) or set(paths) != required_paths or len(paths) != len(required_paths):
        raise ProfileError("protected_paths must equal the approved six-path set")


def desired_ruleset(default_branch: str, *, enforcement: str = "active") -> dict[str, Any]:
    rendered = RULESET_TEMPLATE.read_text().replace("{{DEFAULT_BRANCH}}", default_branch)
    data = json.loads(rendered)
    data["enforcement"] = enforcement
    if data["name"] == HISTORY_RULESET_NAME:
        raise ProfileError("internal safety failure: profile ruleset collides with history ruleset")
    return data


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sort_dict_list(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=canonical)


def normalize_ruleset(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    keep = {
        "name": value.get("name"),
        "target": value.get("target"),
        "enforcement": value.get("enforcement"),
        "bypass_actors": copy.deepcopy(value.get("bypass_actors", [])),
        "conditions": copy.deepcopy(value.get("conditions", {})),
        "rules": copy.deepcopy(value.get("rules", [])),
    }
    keep["bypass_actors"] = _sort_dict_list(keep["bypass_actors"])
    ref = keep["conditions"].get("ref_name", {})
    for key in ("include", "exclude"):
        if isinstance(ref.get(key), list):
            ref[key] = sorted(ref[key])
    for rule in keep["rules"]:
        params = rule.get("parameters", {})
        if isinstance(params.get("allowed_merge_methods"), list):
            params["allowed_merge_methods"] = sorted(params["allowed_merge_methods"])
        if isinstance(params.get("required_status_checks"), list):
            params["required_status_checks"] = _sort_dict_list(params["required_status_checks"])
    keep["rules"] = sorted(keep["rules"], key=lambda item: (item.get("type", ""), canonical(item)))
    return keep


def normalize_settings(value: dict[str, Any]) -> dict[str, bool]:
    return {key: bool(value.get(key)) for key in MANAGED_SETTINGS}


def paused_settings() -> dict[str, bool]:
    desired = normalize_settings(load_config()["settings"])
    desired["allow_auto_merge"] = False
    return desired


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def parse_utc_timestamp(value: Any, *, field: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ProfileError(f"{field} must be an ISO-8601 UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProfileError(f"{field} must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise ProfileError(f"{field} must include the UTC timezone")
    return parsed.astimezone(dt.timezone.utc)


def validate_canary_proof(
    path: Path,
    *,
    ownerrepo: str,
    generation: int,
    ruleset_id: int,
    canary_branch: str,
    canary_sha: str,
    destination_branch: str,
    ruleset_fingerprint: str,
    settings_fingerprint: str,
) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > 1_000_000:
        raise ProfileError("canary proof must be one regular JSON file no larger than 1 MB")
    proof = load_json(path)
    expected_keys = {
        "schema",
        "owner_repo",
        "generation",
        "owned_ruleset_id",
        "canary_branch",
        "canary_sha",
        "destination_branch",
        "ruleset_fingerprint",
        "settings_fingerprint",
        "required_context",
        "integration_id",
        "observed_at",
        "scenarios",
    }
    if not isinstance(proof, dict) or set(proof) != expected_keys:
        raise ProfileError("canary proof must match the closed v1 schema")
    bindings = {
        "schema": "pr-automation-canary-proof/v1",
        "owner_repo": ownerrepo,
        "generation": generation,
        "owned_ruleset_id": ruleset_id,
        "canary_branch": canary_branch,
        "canary_sha": canary_sha,
        "destination_branch": destination_branch,
        "ruleset_fingerprint": ruleset_fingerprint,
        "settings_fingerprint": settings_fingerprint,
        "required_context": "required / ci",
        "integration_id": 15368,
    }
    for key, expected in bindings.items():
        if proof.get(key) != expected or type(proof.get(key)) is not type(expected):
            raise ProfileError(
                f"canary proof binding mismatch for {key}: "
                f"expected {expected!r}, found {proof.get(key)!r}"
            )
    observed_at = parse_utc_timestamp(proof.get("observed_at"), field="observed_at")
    now = dt.datetime.now(dt.timezone.utc)
    if observed_at > now + dt.timedelta(minutes=5):
        raise ProfileError("canary proof observed_at is unacceptably in the future")
    if now - observed_at > CANARY_PROOF_MAX_AGE:
        raise ProfileError("canary proof is stale (maximum age is 24 hours)")
    scenarios = proof.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != len(CANARY_SCENARIOS):
        raise ProfileError("canary proof must contain the exact mandatory scenario set")
    by_id: dict[str, dict[str, Any]] = {}
    for entry in scenarios:
        if not isinstance(entry, dict):
            raise ProfileError("each canary scenario must be an object")
        base_keys = {"id", "mode", "outcome"}
        evidence_keys = {"evidence_url", "api_observation"} & set(entry)
        if set(entry) != base_keys | evidence_keys or len(evidence_keys) != 1:
            raise ProfileError(
                "each canary scenario needs exactly one evidence_url or api_observation"
            )
        scenario_id = entry.get("id")
        if scenario_id not in CANARY_SCENARIOS or scenario_id in by_id:
            raise ProfileError(f"unknown or duplicate canary scenario: {scenario_id!r}")
        if entry.get("mode") not in {"live", "mocked"}:
            raise ProfileError(f"scenario {scenario_id} must be labelled live or mocked")
        if scenario_id in MANDATORY_LIVE_CANARY_SCENARIOS and entry.get("mode") != "live":
            raise ProfileError(f"mandatory-live scenario {scenario_id} cannot be mocked")
        if entry.get("outcome") != "pass":
            raise ProfileError(f"scenario {scenario_id} must have outcome pass")
        if "evidence_url" in entry:
            evidence = entry["evidence_url"]
            parsed_url = urlsplit(evidence) if isinstance(evidence, str) else None
            if (
                not isinstance(evidence, str)
                or parsed_url is None
                or parsed_url.scheme != "https"
                or not parsed_url.hostname
                or parsed_url.username is not None
                or parsed_url.password is not None
                or len(evidence) > 1000
                or bool(parsed_url.query)
                or bool(parsed_url.fragment)
            ):
                raise ProfileError(
                    f"scenario {scenario_id} evidence_url must be secret-free HTTPS without query/fragment"
                )
        else:
            observation = entry["api_observation"]
            if (
                not isinstance(observation, str)
                or not observation.strip()
                or len(observation) > 500
                or "\n" in observation
                or re.search(
                    r"(?i)(authorization\s*[:=]|bearer\s|token\s*=|secret\s*=|private[_-]?key)",
                    observation,
                )
            ):
                raise ProfileError(
                    f"scenario {scenario_id} api_observation is invalid or secret-bearing"
                )
        by_id[str(scenario_id)] = entry
    if set(by_id) != set(CANARY_SCENARIOS):
        missing = sorted(set(CANARY_SCENARIOS) - set(by_id))
        raise ProfileError(f"canary proof is missing mandatory scenarios: {', '.join(missing)}")
    digest = fingerprint(proof)
    return {
        "schema": "pr-automation-canary-proof-summary/v1",
        "digest": digest,
        "validated_at": now.replace(microsecond=0).isoformat(),
        "observed_at": proof["observed_at"],
        "owner_repo": ownerrepo,
        "generation": generation,
        "owned_ruleset_id": ruleset_id,
        "canary_branch": canary_branch,
        "canary_sha": canary_sha,
        "destination_branch": destination_branch,
        "ruleset_fingerprint": ruleset_fingerprint,
        "settings_fingerprint": settings_fingerprint,
        "required_context": "required / ci",
        "integration_id": 15368,
        "scenario_modes": {
            scenario_id: str(by_id[scenario_id]["mode"])
            for scenario_id in CANARY_SCENARIOS
        },
    }


def state_path(ownerrepo: str) -> Path:
    return STATE_DIR / (ownerrepo.lower().replace("/", "__") + ".json")


def read_state(ownerrepo: str) -> dict[str, Any] | None:
    path = state_path(ownerrepo)
    if not path.exists():
        return None
    state = load_json(path)
    if state.get("schema") == "pr-automation-state/v1":
        if state.get("rolled_back"):
            inferred_lifecycle = "rolled_back"
        elif str(state.get("last_operation", "")).startswith("pause"):
            inferred_lifecycle = "paused"
        elif str(state.get("last_operation", "")).startswith("rollback"):
            inferred_lifecycle = "rolling_back"
        else:
            inferred_lifecycle = "active"
        state.setdefault("lifecycle", inferred_lifecycle)
        if state.get("rolled_back"):
            inferred_phase = "complete"
        elif state.get("last_operation") == "rollback-ruleset":
            inferred_phase = "settings_pending"
        else:
            inferred_phase = "not_started"
        state.setdefault("rollback_phase", inferred_phase)
        state.setdefault(
            "task_created_ruleset",
            state.get("rollback_preimage", {}).get("ruleset") is None,
        )
    if state.get("schema") in {"pr-automation-state/v1", "pr-automation-state/v2"}:
        lifecycle = state.get("lifecycle")
        state.setdefault(
            "enforce_phase",
            "settings_pending" if lifecycle == "enforcing" else "complete",
        )
        state.setdefault(
            "pause_phase",
            "complete" if lifecycle == "paused" else "not_started",
        )
    if state.get("schema") in {
        "pr-automation-state/v1",
        "pr-automation-state/v2",
        "pr-automation-state/v3",
    }:
        state["schema"] = "pr-automation-state/v4"
        state.setdefault("repair_phase", "complete")
        state.setdefault(
            "owned_ruleset_id",
            state.get("ruleset_id") if state.get("task_created_ruleset") else None,
        )
    if state.get("schema") == "pr-automation-state/v4":
        state["schema"] = "pr-automation-state/v5"
        target = state.get("default_branch")
        state.setdefault("target_branch", target)
        state.setdefault("target_stage", "default")
        state.setdefault(
            "ruleset_generation",
            1 if state.get("owned_ruleset_id") is not None else 0,
        )
        state.setdefault("last_deleted_ruleset_id", None)
    if state.get("schema") == "pr-automation-state/v5":
        state["schema"] = "pr-automation-state/v6"
        target = state.get("target_branch")
        default = state.get("default_branch")
        generation = int(state.get("ruleset_generation", 0))
        owned_id = state.get("owned_ruleset_id")
        state.setdefault("canary_gate_required", target != default)
        state.setdefault("canary_origin_branch", target if target != default else None)
        state.setdefault(
            "initial_target_mode",
            "explicit_canary" if target != default else "default",
        )
        state.setdefault("target_sha", None)
        state.setdefault("rollback_proofs", [])
        state.setdefault("canary_proof", None)
        state.setdefault(
            "owned_ruleset_history",
            (
                [{"generation": generation, "ruleset_id": owned_id}]
                if generation > 0 and owned_id is not None
                else []
            ),
        )
    return state


def write_state(ownerrepo: str, record: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = state_path(ownerrepo)
    record["updated_at"] = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=STATE_DIR)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(record, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def strip_managed_block(text: str) -> str:
    pattern = re.compile(
        rf"(?ms)^{re.escape(CODEOWNERS_BEGIN)}\n.*?^{re.escape(CODEOWNERS_END)}\n?"
    )
    return pattern.sub("", text).rstrip()


def desired_codeowners(existing: str | None) -> str:
    block = CODEOWNERS_BLOCK_SOURCE.read_text().rstrip()
    if existing is None or existing == BASELINE_CODEOWNERS.read_text():
        return block + "\n"
    base = strip_managed_block(existing)
    return (base + "\n\n" if base else "") + block + "\n"


def workflow_candidates(repo: Path) -> list[Path]:
    root = repo / ".github/workflows"
    if not root.is_dir():
        return []
    return sorted([*root.glob("*.yml"), *root.glob("*.yaml")])


def unquote_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def workflow_job_blocks(text: str) -> tuple[dict[str, str], list[str]]:
    """Parse the intentionally-supported workflow shape and refuse ambiguity.

    This is not a permissive YAML parser. It accepts plain two-space-indented job mappings and
    fails closed on tabs, anchors, aliases, duplicate job ids, or dynamic job keys.
    """
    errors: list[str] = []
    if "\t" in text:
        errors.append("tabs are not allowed in workflow indentation")
    if re.search(r"(?m)(?:^|\s)[&*][A-Za-z0-9_-]+", text):
        errors.append("YAML anchors/aliases are not allowed in the required workflow")
    lines = text.splitlines()
    jobs_indexes = [i for i, line in enumerate(lines) if re.fullmatch(r"jobs:\s*", line)]
    if not jobs_indexes:
        return {}, errors + ["top-level jobs mapping missing"]
    if len(jobs_indexes) != 1:
        errors.append(f"expected exactly one top-level jobs mapping; found {len(jobs_indexes)}")
    jobs_index = jobs_indexes[0]
    blocks: dict[str, str] = {}
    starts: list[tuple[int, str]] = []
    for index in range(jobs_index + 1, len(lines)):
        line = lines[index]
        if line and not line.startswith(" ") and not line.lstrip().startswith("#"):
            break
        match = re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*", line)
        if not match:
            continue
        job_id = match.group(1)
        if job_id in {item[1] for item in starts}:
            errors.append(f"duplicate job id: {job_id}")
        starts.append((index, job_id))
    for position, (start, job_id) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        for index in range(start + 1, end):
            if lines[index] and not lines[index].startswith(" ") and not lines[index].lstrip().startswith("#"):
                end = index
                break
        blocks[job_id] = "\n".join(lines[start:end]) + "\n"
    return blocks, errors


def job_scalar(block: str, key: str) -> str | None:
    matches = re.findall(rf"(?m)^    {re.escape(key)}:\s*(.*?)\s*$", block)
    if len(matches) != 1:
        return None
    return unquote_scalar(matches[0])


def static_needs(job_block: str) -> list[str]:
    lines = job_block.splitlines()
    matches = [index for index, line in enumerate(lines) if re.match(r"^    needs:", line)]
    if len(matches) != 1:
        return []
    index = matches[0]
    value = lines[index].split(":", 1)[1].strip()
    if value:
        if value.startswith("[") and value.endswith("]"):
            items = [item.strip() for item in value[1:-1].split(",") if item.strip()]
        else:
            items = [value]
        return items if items and all(re.fullmatch(r"[A-Za-z0-9_-]+", item) for item in items) else []
    items: list[str] = []
    for nested in lines[index + 1 :]:
        if not nested.strip():
            continue
        indent = len(nested) - len(nested.lstrip())
        if indent <= 4:
            break
        item = re.fullmatch(r"\s{6}-\s*([A-Za-z0-9_-]+)\s*", nested)
        if not item:
            return []
        items.append(item.group(1))
    return items


def decode_double_quoted_scalars(value: str) -> str:
    def decode(match: re.Match[str]) -> str:
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return match.group(0)
        return parsed if isinstance(parsed, str) else match.group(0)

    return re.sub(r'"(?:\\.|[^"\\])*"', decode, value)


def workflow_mentions_required_job(path: Path) -> bool:
    for line in path.read_text(errors="replace").splitlines():
        code = yaml_code(line)
        if not code or code.lstrip().startswith("#"):
            continue
        for variant in (code, decode_double_quoted_scalars(code)):
            if "required / ci" in variant and re.search(
                r"""(?:^|[\s{,])(?:name|"name"|'name')\s*:""",
                variant,
            ):
                return True
    return False


def validate_pull_request_trigger(text: str) -> list[str]:
    errors: list[str] = []
    lines = text.splitlines()
    on_indexes = [
        i for i, line in enumerate(lines) if re.fullmatch(r"(?:on|'on'|\"on\"):\s*", line)
    ]
    if not on_indexes:
        return ["top-level on mapping missing"]
    if len(on_indexes) != 1:
        errors.append(f"expected exactly one top-level on mapping; found {len(on_indexes)}")
    on_index = on_indexes[0]
    pull_indexes: list[int] = []
    for index in range(on_index + 1, len(lines)):
        line = lines[index]
        if line and not line.startswith(" "):
            break
        if re.fullmatch(r"  pull_request:\s*(?:\{\s*\})?\s*", line):
            pull_indexes.append(index)
    if not pull_indexes:
        return ["unconditional pull_request trigger missing"]
    if len(pull_indexes) != 1:
        errors.append(f"expected exactly one pull_request trigger; found {len(pull_indexes)}")
    pull_index = pull_indexes[0]
    for line in lines[pull_index + 1 :]:
        if line and len(line) - len(line.lstrip()) <= 2:
            break
        if re.match(r"^\s{4}(paths|paths-ignore|branches|branches-ignore):", line):
            errors.append("pull_request trigger must have no paths/branches filters")
    return errors


def yaml_code(line: str) -> str:
    return re.sub(r"\s+#.*$", "", line).rstrip()


def contains_flow_syntax(value: str) -> bool:
    without_expressions = re.sub(r"\$\{\{.*?\}\}", "EXPRESSION", value)
    return any(token in without_expressions for token in ("{", "}", "[", "]"))


def validate_supported_yaml_subset(text: str) -> tuple[list[str], list[str]]:
    """Validate the narrow block-style workflow subset this security check understands."""
    errors: list[str] = []
    uses_targets: list[str] = []
    lines = text.splitlines()
    jobs_indexes = [i for i, line in enumerate(lines) if yaml_code(line) == "jobs:"]
    if len(jobs_indexes) != 1:
        return uses_targets, [f"expected exactly one top-level jobs mapping; found {len(jobs_indexes)}"]
    jobs_index = jobs_indexes[0]
    section: str | None = None
    subsection: str | None = None
    in_run_block = False
    parsed_uses_lines: set[int] = set()
    saw_job = False

    for index in range(jobs_index + 1, len(lines)):
        raw = lines[index]
        code = yaml_code(raw)
        if not code or code.lstrip().startswith("#"):
            continue
        indent = len(code) - len(code.lstrip())
        if indent == 0:
            break
        if in_run_block and indent > 8:
            continue
        in_run_block = False
        if contains_flow_syntax(code):
            errors.append(f"line {index + 1}: flow-style/inline YAML is unsupported")

        if indent == 2:
            if not re.fullmatch(r"  [A-Za-z0-9_-]+:\s*", code):
                errors.append(f"line {index + 1}: unsupported or inline job mapping")
            saw_job = True
            section = None
            subsection = None
            continue
        if not saw_job:
            errors.append(f"line {index + 1}: jobs content appears before a plain job id")
            continue

        if indent == 4:
            match = re.fullmatch(r"    ([A-Za-z0-9_-]+):\s*(.*?)\s*", code)
            if not match:
                errors.append(f"line {index + 1}: unsupported job syntax")
                continue
            key, value = match.groups()
            allowed = {
                "name", "runs-on", "outputs", "steps", "if", "needs", "uses",
                "permissions", "timeout-minutes",
            }
            if key not in allowed:
                errors.append(f"line {index + 1}: unsupported job key {key!r}")
            if key == "shell":
                errors.append(f"line {index + 1}: custom shell is forbidden")
            if key in {"outputs", "steps", "needs", "permissions"}:
                if value:
                    errors.append(f"line {index + 1}: {key} must use a block mapping/list")
                section = key
            else:
                if not value:
                    errors.append(f"line {index + 1}: job key {key!r} requires a scalar")
                section = None
            subsection = None
            if key == "uses" and value:
                parsed_uses_lines.add(index)
                uses_targets.append(unquote_scalar(value))
            continue

        if indent == 6:
            if section == "needs":
                if not re.fullmatch(r"      -\s+[A-Za-z0-9_-]+\s*", code):
                    errors.append(f"line {index + 1}: needs must be a plain block sequence of job ids")
            elif section == "outputs":
                if not re.fullmatch(r"      [A-Za-z0-9_-]+:\s+\S.*", code):
                    errors.append(f"line {index + 1}: outputs must be plain scalar mappings")
            elif section == "permissions":
                if not re.fullmatch(r"      [A-Za-z0-9_-]+:\s+\S.*", code):
                    errors.append(f"line {index + 1}: permissions must be plain scalar mappings")
            elif section == "steps":
                match = re.fullmatch(r"      -\s+(name|id|uses):\s*(\S.*)", code)
                if not match:
                    errors.append(f"line {index + 1}: unsupported or inline step entry")
                elif match.group(1) == "uses":
                    parsed_uses_lines.add(index)
                    uses_targets.append(unquote_scalar(match.group(2)))
                subsection = None
            else:
                errors.append(f"line {index + 1}: unexpected nested job syntax")
            continue

        if indent == 8 and section == "steps":
            match = re.fullmatch(
                r"        (name|id|uses|run|env|with|shell|working-directory|if):\s*(.*?)\s*",
                code,
            )
            if not match:
                errors.append(f"line {index + 1}: unsupported step syntax")
                continue
            key, value = match.groups()
            if key == "shell":
                errors.append(f"line {index + 1}: custom shell is forbidden")
            if key in {"env", "with"}:
                if value:
                    errors.append(f"line {index + 1}: step {key} must use a block mapping")
                subsection = key
            else:
                if not value:
                    errors.append(f"line {index + 1}: step key {key!r} requires a scalar")
                subsection = None
            if key == "uses" and value:
                parsed_uses_lines.add(index)
                uses_targets.append(unquote_scalar(value))
            if key == "run" and value in {"|", "|-", "|+"}:
                in_run_block = True
            continue

        if indent == 10 and section == "steps" and subsection in {"env", "with"}:
            if not re.fullmatch(r"          [A-Za-z_][A-Za-z0-9_-]*:\s+\S.*", code):
                errors.append(f"line {index + 1}: {subsection} must contain plain scalar mappings")
            continue

        errors.append(f"line {index + 1}: unsupported indentation or ambiguous YAML syntax")

    for index, line in enumerate(lines[jobs_index + 1 :], start=jobs_index + 1):
        code = yaml_code(line)
        if re.search(r"(?:^|[\s{,])['\"]?uses['\"]?\s*:", code) and index not in parsed_uses_lines:
            errors.append(f"line {index + 1}: unsupported uses occurrence")
    return uses_targets, errors


def validate_uses_pins(targets: list[str]) -> list[str]:
    errors: list[str] = []
    for target in targets:
        if "@" not in target:
            errors.append(f"uses target lacks immutable full-SHA ref: {target}")
            continue
        ref = target.rsplit("@", 1)[1]
        if not FULL_SHA.fullmatch(ref):
            errors.append(f"uses target is not pinned to a full SHA: {target}")
    return errors


def validate_required_job(job_id: str, block: str, blocks: dict[str, str]) -> list[str]:
    errors: list[str] = []
    needs = static_needs(block)
    if not needs:
        errors.append("aggregator must have one non-empty static needs list")
        return errors
    missing = sorted(set(needs) - set(blocks))
    if missing:
        errors.append(f"aggregator references missing static dependencies: {', '.join(missing)}")
    reachable: set[str] = set()
    pending = list(needs)
    while pending:
        dependency = pending.pop()
        if dependency in reachable or dependency not in blocks:
            continue
        reachable.add(dependency)
        pending.extend(static_needs(blocks[dependency]))
    uncovered = sorted(set(blocks) - {job_id} - reachable)
    if uncovered:
        errors.append(
            "aggregator dependency closure omits jobs: " + ", ".join(uncovered)
        )
    if job_scalar(block, "if") != "${{ always() }}":
        errors.append("aggregator must use exact if: ${{ always() }}")
    if re.search(r"(?m)^\s+continue-on-error:", block):
        errors.append("aggregator must not use continue-on-error")
    if re.search(r"(?m)^\s{8}if:", block):
        errors.append("aggregator assertion step must not have a step-level if")
    if len(re.findall(r"(?m)^\s{6}-\s+name:", block)) != 1:
        errors.append("aggregator must contain exactly one named assertion step")
    steps_match = re.search(r"(?ms)^\s{4}steps:\s*\n(.*)$", block)
    steps_block = steps_match.group(1) if steps_match else ""
    if len(re.findall(r"(?m)^\s{6}-\s+", steps_block)) != 1:
        errors.append("aggregator must contain exactly one total step")
    if re.search(r"(?m)^\s{8}uses:", block):
        errors.append("aggregator assertion step must be an inline run, not an action")

    expressions = [item.strip() for item in re.findall(r"\$\{\{(.*?)\}\}", block)]
    allowed = {"always()"}
    allowed.update(f"needs.{need}.result" for need in needs)
    result_env: dict[str, str] = {}
    for match in re.finditer(
        r"(?m)^\s{10}([A-Z][A-Z0-9_]*):\s*\$\{\{\s*needs\.([A-Za-z0-9_-]+)\.result\s*\}\}\s*$",
        block,
    ):
        result_env[match.group(2)] = match.group(1)
    count_env = list(re.finditer(
        r"(?m)^\s{10}([A-Z][A-Z0-9_]*):\s*\$\{\{\s*needs\.([A-Za-z0-9_-]+)\.outputs\.count\s*\}\}\s*$",
        block,
    ))
    if len(count_env) != 1 or count_env[0].group(2) not in needs:
        errors.append("aggregator must map exactly one static dependency outputs.count")
        count_variable = None
    else:
        count_variable = count_env[0].group(1)
        allowed.add(f"needs.{count_env[0].group(2)}.outputs.count")
        discovery_block = blocks.get(count_env[0].group(2), "")
        if not re.search(r"(?m)^\s{6}count:\s*\$\{\{\s*steps\.[A-Za-z0-9_-]+\.outputs\.count\s*\}\}\s*$", discovery_block):
            errors.append("discovery dependency must expose a static count output")
    unsafe = sorted(set(expressions) - allowed)
    if unsafe:
        errors.append(f"unsafe/dynamic expressions in aggregator: {', '.join(unsafe)}")
    if set(result_env) != set(needs):
        errors.append("every static dependency must map its exact needs.<job>.result")
    expected_run_lines: list[str] = []
    for need in needs:
        variable = result_env.get(need)
        if variable:
            expected_run_lines.append(f'test "${variable}" = "success"')
        if not variable or not re.search(
            rf'(?m)^\s{{10}}test "\${re.escape(variable)}" = "success"\s*$', block
        ):
            errors.append(f"dependency {need} is not tested for exact literal success")
    if count_variable:
        expected_run_lines.append(f'test "${count_variable}" -gt 0')
    if count_variable and not re.search(
        rf'(?m)^\s{{10}}test "\${re.escape(count_variable)}" -gt 0\s*$', block
    ):
        errors.append("discovery count is not explicitly tested as positive")
    lines = block.splitlines()
    run_indexes = [
        index for index, line in enumerate(lines) if re.fullmatch(r"\s{8}run:\s*\|\s*", line)
    ]
    actual_run_lines: list[str] = []
    if len(run_indexes) == 1:
        for line in lines[run_indexes[0] + 1 :]:
            if not line.strip():
                continue
            if len(line) - len(line.lstrip()) <= 8:
                break
            if not line.startswith(" " * 10):
                actual_run_lines = []
                break
            actual_run_lines.append(line[10:])
    if sorted(actual_run_lines) != sorted(expected_run_lines):
        errors.append("aggregator run script must contain only exact success and positive-count tests")
    return errors


def validate_aggregator(path: Path) -> list[str]:
    text = path.read_text(errors="replace")
    blocks, errors = workflow_job_blocks(text)
    uses_targets, subset_errors = validate_supported_yaml_subset(text)
    errors.extend(subset_errors)
    errors.extend(validate_pull_request_trigger(text))
    errors.extend(validate_uses_pins(uses_targets))
    defaults_count = len(re.findall(r"(?m)^defaults:\s*$", text))
    exact_bash_defaults = len(
        re.findall(r"(?m)^defaults:\s*\n  run:\s*\n    shell:\s*bash\s*$", text)
    )
    shell_lines = re.findall(r"(?m)^\s*shell\s*:\s*.*$", text)
    if (
        defaults_count != exact_bash_defaults
        or len(shell_lines) != exact_bash_defaults
    ):
        errors.append("only exact top-level defaults.run.shell: bash is permitted")
    if re.search(
        r"""(?m)^\s+["'](?:name|needs|if|uses|shell|continue-on-error|paths|paths-ignore|branches|branches-ignore)["']\s*:""",
        text,
    ):
        errors.append("quoted critical workflow keys are not allowed")
    if re.search(r"""(?m)^\s+(?:continue-on-error|"continue-on-error"|'continue-on-error')\s*:""", text):
        errors.append("continue-on-error is forbidden anywhere in the required workflow")
    named = [(job_id, block) for job_id, block in blocks.items() if job_scalar(block, "name") == "required / ci"]
    if len(named) != 1:
        errors.append(f"expected exactly one unambiguous 'required / ci' job; found {len(named)}")
    else:
        errors.extend(validate_required_job(named[0][0], named[0][1], blocks))
    return sorted(set(errors))


def local_status(repo: Path) -> tuple[list[str], Path | None]:
    errors: list[str] = []
    config_path = repo / CONFIG_REL
    if not config_path.exists():
        errors.append(f"{CONFIG_REL} missing")
    else:
        try:
            config = load_config(config_path)
            if config != load_config():
                errors.append(f"{CONFIG_REL} differs from canonical config")
        except ProfileError as exc:
            errors.append(str(exc))
    codeowners_path = repo / CODEOWNERS_REL
    if not codeowners_path.exists():
        errors.append(f"{CODEOWNERS_REL} missing")
    else:
        content = codeowners_path.read_text()
        if CODEOWNERS_BLOCK_SOURCE.read_text().rstrip() not in content:
            errors.append(f"{CODEOWNERS_REL} missing/current protected-path block")
    candidates = [path for path in workflow_candidates(repo) if workflow_mentions_required_job(path)]
    aggregator = candidates[0] if len(candidates) == 1 else None
    if not candidates:
        errors.append("no workflow produces stable context 'required / ci'")
    else:
        if len(candidates) > 1:
            errors.append("multiple workflows can produce 'required / ci' (ambiguous required source)")
        for candidate in candidates:
            errors.extend(
                f"{candidate.relative_to(repo)}: {item}"
                for item in validate_aggregator(candidate)
            )
    return errors, aggregator


def plan_apply(repo: Path) -> tuple[list[tuple[str, Path, str]], list[str]]:
    conflicts: list[str] = []
    actions: list[tuple[str, Path, str]] = []
    config_dest = repo / CONFIG_REL
    canonical_config = json.dumps(load_config(), indent=2) + "\n"
    if not config_dest.exists():
        actions.append(("create", config_dest, canonical_config))
    elif config_dest.read_text() != canonical_config:
        conflicts.append(str(CONFIG_REL))

    candidates = [path for path in workflow_candidates(repo) if workflow_mentions_required_job(path)]
    if not candidates:
        workflow_dest = repo / WORKFLOW_REL
        desired = WORKFLOW_SOURCE.read_text()
        if not workflow_dest.exists():
            actions.append(("create", workflow_dest, desired))
        elif WORKFLOW_MARKER in workflow_dest.read_text():
            if workflow_dest.read_text() != desired:
                actions.append(("refresh", workflow_dest, desired))
        else:
            conflicts.append(str(WORKFLOW_REL))
    else:
        if len(candidates) > 1:
            conflicts.append("multiple workflows already can produce required / ci")
        for candidate in candidates:
            issues = validate_aggregator(candidate)
            if issues:
                conflicts.extend(
                    f"{candidate.relative_to(repo)}: {issue}" for issue in issues
                )

    codeowners_dest = repo / CODEOWNERS_REL
    existing = codeowners_dest.read_text() if codeowners_dest.exists() else None
    desired = desired_codeowners(existing)
    if existing != desired:
        actions.append(("create" if existing is None else "merge", codeowners_dest, desired))
    return actions, conflicts


def cmd_verify(repo: Path) -> int:
    validate_target(repo, require_clean=False)
    errors, aggregator = local_status(repo)
    print(f"pr-automation verify — {repo}")
    print(f"  config:      {'OK' if not any(str(CONFIG_REL) in e for e in errors) else 'FAIL'}")
    print(f"  CODEOWNERS:  {'OK' if not any(str(CODEOWNERS_REL) in e for e in errors) else 'FAIL'}")
    print(f"  aggregator:  {aggregator.relative_to(repo) if aggregator else 'FAIL'}")
    for error in errors:
        eprint(f"  FAIL: {error}")
    print(f"Overall: {'COMPLIANT' if not errors else 'NONCOMPLIANT'}")
    return 0 if not errors else 1


def cmd_apply(repo: Path, *, dry_run: bool) -> int:
    validate_target(repo, require_clean=False)
    actions, conflicts = plan_apply(repo)
    has_head = bool(git(repo, "rev-parse", "--verify", "HEAD", check=False))
    if actions and has_head and git(repo, "status", "--porcelain"):
        raise ProfileError("refusing to mutate a dirty working tree")
    print(f"pr-automation apply — {repo}")
    if dry_run:
        print("(dry-run — local reads only; no files will be written)")
    for action, path, _ in actions:
        print(f"  {action:8} {path.relative_to(repo)}")
    if not actions and not conflicts:
        print("  no-op     profile files already current")
    if conflicts:
        for conflict in conflicts:
            eprint(f"  CONFLICT: {conflict}")
        if not dry_run:
            raise ProfileError("refusing to overwrite conflicting automation files")
        return 3
    if dry_run:
        return 0
    for _, path, content in actions:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    print("pr-automation apply: local files rendered; GitHub was not contacted")
    return 0


def require_gh() -> None:
    if not shutil.which("gh"):
        raise ProfileError("gh CLI not found")
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
            raise ProfileError("pagination is read-only")
        args += ["--paginate", "--slurp"]
    args.append(endpoint)
    temp: Path | None = None
    try:
        if payload is not None:
            fd, name = tempfile.mkstemp(prefix="pr-automation-", suffix=".json")
            os.close(fd)
            temp = Path(name)
            temp.write_text(json.dumps(payload))
            args += ["--input", str(temp)]
        proc = run(args)
        if not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)
    finally:
        if temp:
            temp.unlink(missing_ok=True)


def remote_repo(ownerrepo: str) -> dict[str, Any]:
    data = gh_api(f"repos/{ownerrepo}")
    actual = str(data.get("owner", {}).get("login", ""))
    expected = ownerrepo.split("/", 1)[0]
    if actual.lower() != expected.lower():
        raise ProfileError(f"remote owner mismatch: expected {expected}, got {actual}")
    return data


def paginated_items(endpoint: str) -> list[dict[str, Any]]:
    pages = gh_api(endpoint, paginate=True)
    if not isinstance(pages, list):
        raise ProfileError(f"paginated GitHub response is not a list: {endpoint}")
    if pages and all(isinstance(page, list) for page in pages):
        items = [item for page in pages for item in page]
    else:
        items = pages
    if not all(isinstance(item, dict) for item in items):
        raise ProfileError(f"paginated GitHub response contains non-object entries: {endpoint}")
    return items


def find_profile_ruleset(ownerrepo: str) -> tuple[int | None, dict[str, Any] | None]:
    entries = paginated_items(f"repos/{ownerrepo}/rulesets?per_page=100")
    matches = [item for item in entries if item.get("name") == RULESET_NAME]
    if len(matches) > 1:
        raise ProfileError(f"multiple rulesets named {RULESET_NAME}")
    if not matches:
        return None, None
    ruleset_id = int(matches[0]["id"])
    return ruleset_id, gh_api(f"repos/{ownerrepo}/rulesets/{ruleset_id}")


def open_armed_auto_merges(ownerrepo: str) -> list[dict[str, Any]]:
    pulls = paginated_items(f"repos/{ownerrepo}/pulls?state=open&per_page=100")
    armed: list[dict[str, Any]] = []
    for pull in pulls:
        if "auto_merge" not in pull:
            raise ProfileError("open PR response omitted auto_merge state; refusing to infer zero")
        request = pull.get("auto_merge")
        if request:
            enabled_by = request.get("enabled_by") or {}
            head = pull.get("head") or {}
            if not pull.get("number") or not pull.get("node_id") or not head.get("sha"):
                raise ProfileError("armed auto-merge PR lacks number, node id, or exact head SHA")
            armed.append(
                {
                    "number": pull.get("number"),
                    "url": pull.get("html_url"),
                    "enabled_by": enabled_by.get("login"),
                    "node_id": pull.get("node_id"),
                    "head_sha": head.get("sha"),
                }
            )
    return armed


DISABLE_AUTO_MERGE_MUTATION = """
mutation DisablePullRequestAutoMerge($pullRequestId: ID!) {
  disablePullRequestAutoMerge(input: {pullRequestId: $pullRequestId}) {
    pullRequest {
      id
      autoMergeRequest {
        enabledAt
      }
    }
  }
}
""".strip()


def disarm_auto_merge(ownerrepo: str, armed: dict[str, Any]) -> None:
    number = int(armed["number"])
    endpoint = f"repos/{ownerrepo}/pulls/{number}"
    pre = gh_api(endpoint)
    pre_head = (pre.get("head") or {}).get("sha")
    if (
        "auto_merge" not in pre
        or pre.get("state") != "open"
        or pre.get("node_id") != armed.get("node_id")
        or pre_head != armed.get("head_sha")
        or not pre.get("auto_merge")
    ):
        raise ProfileError(
            f"auto-merge disarm refusal for PR #{number}: identity/head/armed state changed"
        )
    response = gh_api(
        "graphql",
        method="POST",
        payload={
            "query": DISABLE_AUTO_MERGE_MUTATION,
            "variables": {"pullRequestId": armed["node_id"]},
        },
    )
    if not isinstance(response, dict):
        raise ProfileError(f"auto-merge disarm mutation returned no object for PR #{number}")
    result = (response.get("data") or {}).get("disablePullRequestAutoMerge") or {}
    returned = result.get("pullRequest") or {}
    if returned.get("id") != armed["node_id"] or returned.get("autoMergeRequest") is not None:
        raise ProfileError(f"auto-merge disarm mutation returned an unexpected PR #{number} postimage")
    post = gh_api(endpoint)
    post_head = (post.get("head") or {}).get("sha")
    if (
        "auto_merge" not in post
        or post.get("state") != "open"
        or post.get("node_id") != armed["node_id"]
        or post_head != armed["head_sha"]
        or post.get("auto_merge") is not None
    ):
        raise ProfileError(
            f"auto-merge disarm postcondition failed for PR #{number}: "
            "exact head/identity changed or request remains armed"
        )


def live_objects(ownerrepo: str) -> tuple[dict[str, bool], int | None, dict[str, Any] | None, str]:
    repo_data = remote_repo(ownerrepo)
    settings = normalize_settings(repo_data)
    ruleset_id, ruleset = find_profile_ruleset(ownerrepo)
    branch = str(repo_data.get("default_branch") or "")
    if not branch:
        raise ProfileError("GitHub default branch is missing or ambiguous")
    return settings, ruleset_id, ruleset, branch


def assert_managed_live(
    state: dict[str, Any],
    settings: dict[str, bool],
    ruleset_id: int | None,
    ruleset: dict[str, Any] | None,
) -> None:
    expected = state.get("managed_post_fingerprints", {})
    expected_id = state.get("ruleset_id")
    if expected_id != ruleset_id:
        raise ProfileError(
            f"optimistic drift refusal: stored ruleset id {expected_id!r} != live id {ruleset_id!r}"
        )
    actual_settings = fingerprint(normalize_settings(settings))
    actual_ruleset = fingerprint(normalize_ruleset(ruleset))
    if expected.get("settings") != actual_settings or expected.get("ruleset") != actual_ruleset:
        raise ProfileError(
            "optimistic drift refusal: live settings/ruleset differ from the stored managed postimage"
        )


def expect_ruleset_now(
    ownerrepo: str,
    *,
    expected_id: int | None,
    expected_fingerprint: str,
) -> dict[str, Any] | None:
    live_id, live_ruleset = find_profile_ruleset(ownerrepo)
    if live_id != expected_id:
        raise ProfileError(
            f"optimistic drift refusal immediately before write: expected ruleset id "
            f"{expected_id!r}, found {live_id!r}"
        )
    if fingerprint(normalize_ruleset(live_ruleset)) != expected_fingerprint:
        raise ProfileError("optimistic drift refusal immediately before write: ruleset changed")
    return live_ruleset


def expect_settings_now(ownerrepo: str, expected_fingerprint: str) -> dict[str, bool]:
    settings = normalize_settings(remote_repo(ownerrepo))
    if fingerprint(settings) != expected_fingerprint:
        raise ProfileError("optimistic drift refusal immediately before write: settings changed")
    return settings


def verify_ruleset_postimage(
    ownerrepo: str,
    *,
    expected_id: int | None,
    desired: dict[str, Any] | None,
) -> dict[str, Any] | None:
    live_id, live_ruleset = find_profile_ruleset(ownerrepo)
    if live_id != expected_id:
        raise ProfileError(
            f"unexpected ruleset resource transition: expected id {expected_id!r}, found {live_id!r}"
        )
    if normalize_ruleset(live_ruleset) != normalize_ruleset(desired):
        raise ProfileError("ruleset postcondition differs from the exact desired postimage")
    return live_ruleset


def verify_settings_postimage(ownerrepo: str, desired: dict[str, bool]) -> dict[str, bool]:
    settings = normalize_settings(remote_repo(ownerrepo))
    if settings != normalize_settings(desired):
        raise ProfileError("settings postcondition differs from the exact desired postimage")
    return settings


def seed_state(
    ownerrepo: str,
    default_branch: str,
    target_branch: str,
    target_stage: str,
    target_sha: str,
    canary_gate_required: bool,
    ruleset_id: int | None,
    settings_pre: dict[str, bool],
    ruleset_pre: dict[str, Any] | None,
) -> dict[str, Any]:
    existing = read_state(ownerrepo)
    if existing:
        return existing
    return {
        "schema": "pr-automation-state/v6",
        "profile": PROFILE_NAME,
        "owner_repo": ownerrepo,
        "default_branch": default_branch,
        "target_branch": target_branch,
        "target_stage": target_stage,
        "target_sha": target_sha,
        "canary_gate_required": canary_gate_required,
        "canary_origin_branch": target_branch if canary_gate_required else None,
        "initial_target_mode": "explicit_canary" if canary_gate_required else "default",
        "ruleset_name": RULESET_NAME,
        "ruleset_id": ruleset_id,
        "lifecycle": "initializing",
        "enforce_phase": "pre_mutation",
        "pause_phase": "not_started",
        "repair_phase": "not_started",
        "rollback_phase": "not_started",
        "task_created_ruleset": ruleset_pre is None,
        "owned_ruleset_id": None,
        "ruleset_generation": 0,
        "last_deleted_ruleset_id": None,
        "owned_ruleset_history": [],
        "rollback_proofs": [],
        "canary_proof": None,
        "rollback_preimage": {
            "settings": normalize_settings(settings_pre),
            "ruleset": normalize_ruleset(ruleset_pre),
        },
        "mutation_preimages": [],
        "managed_postimage": {
            "settings": normalize_settings(settings_pre),
            "ruleset": normalize_ruleset(ruleset_pre),
        },
        "managed_post_fingerprints": {
            "settings": fingerprint(normalize_settings(settings_pre)),
            "ruleset": fingerprint(normalize_ruleset(ruleset_pre)),
        },
    }


def append_preimage(
    state: dict[str, Any],
    *,
    operation: str,
    object_name: str,
    value: Any,
) -> None:
    normalized = normalize_settings(value) if object_name == "settings" else normalize_ruleset(value)
    state.setdefault("mutation_preimages", []).append(
        {
            "operation": operation,
            "object": object_name,
            "captured_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "normalized": normalized,
            "fingerprint": fingerprint(normalized),
        }
    )


def finalize_state(
    state: dict[str, Any],
    *,
    operation: str,
    ruleset_id: int | None,
    settings: dict[str, bool],
    ruleset: dict[str, Any] | None,
) -> None:
    normalized_settings = normalize_settings(settings)
    normalized_ruleset = normalize_ruleset(ruleset)
    state["last_operation"] = operation
    state["ruleset_id"] = ruleset_id
    state["managed_postimage"] = {
        "settings": normalized_settings,
        "ruleset": normalized_ruleset,
    }
    state["managed_post_fingerprints"] = {
        "settings": fingerprint(normalized_settings),
        "ruleset": fingerprint(normalized_ruleset),
    }
    state.pop("pending_settings_transition", None)
    write_state(state["owner_repo"], state)


def begin_settings_transition(
    state: dict[str, Any],
    *,
    operation: str,
    current: dict[str, bool],
    desired: dict[str, bool],
) -> None:
    normalized_current = normalize_settings(current)
    normalized_desired = normalize_settings(desired)
    state["pending_settings_transition"] = {
        "operation": operation,
        "from_fingerprint": fingerprint(normalized_current),
        "desired": normalized_desired,
        "desired_fingerprint": fingerprint(normalized_desired),
    }


def resume_settings_transition(
    state: dict[str, Any],
    *,
    operation: str,
    settings: dict[str, bool],
    ruleset_id: int | None,
    ruleset: dict[str, Any] | None,
    dry_run: bool,
) -> bool:
    transition = state.get("pending_settings_transition")
    if not isinstance(transition, dict) or transition.get("operation") != operation:
        return False
    expected = state.get("managed_post_fingerprints", {})
    if (
        state.get("ruleset_id") != ruleset_id
        or expected.get("ruleset") != fingerprint(normalize_ruleset(ruleset))
    ):
        raise ProfileError(
            f"{operation} settings recovery refusal: ruleset id/fingerprint changed"
        )
    live_fingerprint = fingerprint(normalize_settings(settings))
    if live_fingerprint == transition.get("from_fingerprint"):
        return False
    desired = transition.get("desired")
    if (
        isinstance(desired, dict)
        and live_fingerprint == transition.get("desired_fingerprint")
        and normalize_settings(settings) == normalize_settings(desired)
    ):
        if not dry_run:
            finalize_state(
                state,
                operation=f"{operation}-settings",
                ruleset_id=ruleset_id,
                settings=settings,
                ruleset=ruleset,
            )
        return True
    raise ProfileError(
        f"{operation} settings recovery refusal: live settings match neither stored preimage "
        "nor exact desired postimage"
    )


def ensure_local_compliant(repo: Path) -> None:
    errors, _ = local_status(repo)
    if errors:
        raise ProfileError("local profile is not compliant: " + "; ".join(errors))


def remote_plan(verb: str, ownerrepo: str, branch: str, ruleset_id: int | None) -> None:
    print(f"pr-automation {verb} — {ownerrepo}")
    print(f"  target branch: {branch}")
    print(f"  profile ruleset: {RULESET_NAME} ({ruleset_id or 'not created'})")
    print(f"  history ruleset: {HISTORY_RULESET_NAME} (explicitly out of scope)")


def validate_head_branch(branch: str) -> None:
    if (
        not branch
        or branch in {"HEAD", "-", "@"}
        or branch.startswith(("refs/", "origin/"))
        or FULL_SHA.fullmatch(branch)
        or any(token in branch for token in ("*", "?", "[", "]", "@{", ".."))
    ):
        raise ProfileError(f"target must be one exact branch head name, got {branch!r}")
    if run(["git", "check-ref-format", "--branch", branch], check=False).returncode:
        raise ProfileError(f"target is not a valid branch head name: {branch!r}")


def fetch_remote_branch_sha(repo: Path, branch: str) -> str:
    result = run(
        [
            "git",
            "-C",
            str(repo),
            "fetch",
            "--quiet",
            "origin",
            f"refs/heads/{branch}",
        ],
        check=False,
    )
    if result.returncode:
        raise ProfileError(f"target branch {branch!r} is missing from origin or could not be fetched")
    return git(repo, "rev-parse", "FETCH_HEAD")


def github_branch_sha(ownerrepo: str, branch: str) -> str:
    validate_head_branch(branch)
    branch_data = gh_api(f"repos/{ownerrepo}/branches/{quote(branch, safe='')}")
    sha = str((branch_data.get("commit") or {}).get("sha") or "")
    if not FULL_SHA.fullmatch(sha):
        raise ProfileError(f"target branch {branch!r} is missing or has no full remote SHA")
    return sha


def require_exact_remote_branch_head(
    repo: Path,
    ownerrepo: str,
    branch: str,
) -> str:
    github_sha = github_branch_sha(ownerrepo, branch)
    local_branch = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if local_branch != branch:
        raise ProfileError(
            f"refusing remote mutation from local branch {local_branch!r}; "
            f"checkout exact target branch {branch!r}"
        )
    upstream = git(
        repo,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
        check=False,
    )
    expected_upstream = f"origin/{branch}"
    if upstream != expected_upstream:
        raise ProfileError(
            f"refusing remote mutation: target branch must track {expected_upstream!r}, "
            f"found {upstream!r}"
        )
    local_sha = git(repo, "rev-parse", "HEAD")
    upstream_sha = git(repo, "rev-parse", "@{upstream}")
    fetched_sha = fetch_remote_branch_sha(repo, branch)
    if not all(FULL_SHA.fullmatch(value) for value in (local_sha, upstream_sha, fetched_sha)):
        raise ProfileError(
            "refusing remote mutation: local/upstream/fetched HEAD is not a full commit SHA"
        )
    if not FULL_SHA.fullmatch(github_sha):
        raise ProfileError("refusing remote mutation: GitHub target branch SHA is unavailable")
    if len({local_sha, upstream_sha, fetched_sha, github_sha}) != 1:
        raise ProfileError(
            "refusing remote mutation: local HEAD, upstream, fetched remote, and GitHub target "
            f"branch must match exactly (local={local_sha}, upstream={upstream_sha}, "
            f"fetched={fetched_sha}, github={github_sha})"
        )
    return github_sha


def assert_recorded_default_branch(state: dict[str, Any], default_branch: str) -> None:
    recorded = state.get("default_branch")
    if recorded != default_branch:
        raise ProfileError(
            f"GitHub default branch changed or is ambiguous: recorded={recorded!r}, "
            f"live={default_branch!r}"
        )


def recorded_target_branch(state: dict[str, Any], default_branch: str) -> str:
    assert_recorded_default_branch(state, default_branch)
    target = state.get("target_branch")
    if not isinstance(target, str):
        raise ProfileError("managed state is missing its exact target branch")
    validate_head_branch(target)
    return target


def canary_proof_status(
    state: dict[str, Any] | None,
    *,
    ownerrepo: str,
    settings: dict[str, bool],
    ruleset_id: int | None,
    ruleset: dict[str, Any] | None,
) -> str:
    if not state or not state.get("canary_gate_required"):
        return "NOT_REQUIRED"
    try:
        rollback_proof = require_prior_canary_rollback_proof(state)
    except ProfileError as exc:
        return f"NOT_READY ({exc})"
    summary = state.get("canary_proof")
    if not isinstance(summary, dict):
        return f"AWAITING_BUNDLE (rollback proof {rollback_proof['digest']})"
    if state.get("target_stage") == "promoted":
        return f"COMPLETE ({summary.get('digest')})"
    pending = state.get("pending_retarget")
    ruleset_fp = fingerprint(normalize_ruleset(ruleset))
    destination = state.get("default_branch")
    if isinstance(pending, dict):
        ruleset_fp = str(pending.get("preimage_fingerprint"))
        destination = pending.get("to_target")
    target = state.get("target_branch")
    try:
        live_target_sha = github_branch_sha(ownerrepo, str(target))
    except ProfileError as exc:
        return f"NOT_READY ({exc})"
    ready = (
        ruleset_id is not None
        and state.get("owned_ruleset_id") == ruleset_id
        and live_target_sha == state.get("target_sha")
        and canary_summary_matches_live(
            summary,
            ownerrepo=ownerrepo,
            generation=int(state.get("ruleset_generation", 0)),
            ruleset_id=ruleset_id,
            canary_branch=str(target),
            canary_sha=live_target_sha,
            destination_branch=str(destination),
            ruleset_fingerprint=ruleset_fp,
            settings_fingerprint=fingerprint(settings),
        )
    )
    return f"{'READY' if ready else 'NOT_READY'} ({summary.get('digest')})"


def cmd_status(repo: Path) -> int:
    ownerrepo = validate_target(repo, require_clean=False)
    require_gh()
    errors, aggregator = local_status(repo)
    settings, ruleset_id, ruleset, default_branch = live_objects(ownerrepo)
    desired_settings = load_config()["settings"]
    desired_paused_settings = paused_settings()
    state = read_state(ownerrepo)
    status_target = default_branch
    if state and isinstance(state.get("target_branch"), str):
        status_target = str(state["target_branch"])
    desired = normalize_ruleset(desired_ruleset(status_target))
    live_ruleset = normalize_ruleset(ruleset)
    managed = "MISSING"
    id_detail = "unmanaged"
    if state:
        expected = state.get("managed_post_fingerprints", {})
        default_match = state.get("default_branch") == default_branch
        id_match = state.get("ruleset_id") == ruleset_id
        ruleset_match = expected.get("ruleset") == fingerprint(live_ruleset)
        settings_match = expected.get("settings") == fingerprint(settings)
        managed = (
            "CURRENT"
            if default_match and id_match and ruleset_match and settings_match
            else "DRIFT"
        )
        id_detail = "match" if id_match else f"stored={state.get('ruleset_id')!r},live={ruleset_id!r}"
    if live_ruleset == desired and settings == desired_settings:
        desired_state = "ACTIVE_CURRENT"
    elif live_ruleset == desired and settings == desired_paused_settings:
        desired_state = "PAUSED"
    else:
        desired_state = "DRIFT_OR_ROLLBACK"
    lifecycle = "unmanaged"
    if state:
        lifecycle = str(state.get("lifecycle", "unknown"))
        if lifecycle == "rolling_back":
            lifecycle += f":{state.get('rollback_phase', 'unknown')}"
        elif lifecycle == "pausing":
            lifecycle += f":{state.get('pause_phase', 'unknown')}"
        elif lifecycle == "repairing":
            lifecycle += f":{state.get('repair_phase', 'unknown')}"
        elif lifecycle in {"initializing", "enforcing"}:
            lifecycle += f":{state.get('enforce_phase', 'unknown')}"
        elif lifecycle == "ownership_ambiguous":
            lifecycle += f":{state.get('enforce_phase', 'unknown')}"
        elif lifecycle == "retargeting":
            lifecycle += f":{state.get('retarget_phase', 'unknown')}"
    print(f"pr-automation status — {ownerrepo} (READ-ONLY)")
    print(f"  local:       {'COMPLIANT' if not errors else 'NONCOMPLIANT'}")
    print(f"  aggregator:  {aggregator.relative_to(repo) if aggregator else 'missing/ambiguous'}")
    print(f"  lifecycle:   {lifecycle}")
    print(
        f"  target:      {status_target} "
        f"(stage={state.get('target_stage', 'unmanaged') if state else 'unmanaged'}, "
        f"generation={state.get('ruleset_generation', 0) if state else 0})"
    )
    if state:
        print(
            f"  default:     live={default_branch}, "
            f"recorded={state.get('default_branch')}"
        )
    print(
        "  proof gate:  "
        + canary_proof_status(
            state,
            ownerrepo=ownerrepo,
            settings=settings,
            ruleset_id=ruleset_id,
            ruleset=ruleset,
        )
    )
    print(f"  managed:     {managed} (resource-id {id_detail})")
    print(f"  desired:     {desired_state}")
    print(f"  live ruleset: id {ruleset_id or 'none'}; fingerprint {fingerprint(live_ruleset)}")
    print(f"  live settings: fingerprint {fingerprint(settings)}")
    for error in errors:
        print(f"  local issue: {error}")
    return 0


def target_stage(default_branch: str, target_branch: str, generation: int) -> str:
    if target_branch == default_branch:
        return "default"
    return "canary_recreated" if generation > 1 else "canary"


def rollback_proof_digest(record: dict[str, Any]) -> str:
    unsigned = copy.deepcopy(record)
    unsigned.pop("digest", None)
    return fingerprint(unsigned)


def require_prior_canary_rollback_proof(state: dict[str, Any]) -> dict[str, Any]:
    generation = int(state.get("ruleset_generation", 0))
    proofs = state.get("rollback_proofs")
    owned_history = state.get("owned_ruleset_history")
    if generation < 2 or not isinstance(proofs, list):
        raise ProfileError("canary promotion requires a prior exact rollback and newer generation")
    valid: list[dict[str, Any]] = []
    for proof in proofs:
        restored = proof.get("restored_preimage") if isinstance(proof, dict) else None
        restored_fingerprints = (
            {
                "settings": fingerprint(normalize_settings(restored.get("settings"))),
                "ruleset": fingerprint(normalize_ruleset(restored.get("ruleset"))),
            }
            if isinstance(restored, dict)
            and isinstance(restored.get("settings"), dict)
            else None
        )
        managed_pre = (
            proof.get("managed_pre_fingerprints", {})
            if isinstance(proof, dict)
            and isinstance(proof.get("managed_pre_fingerprints", {}), dict)
            else {}
        )
        if isinstance(proof, dict):
            try:
                parse_utc_timestamp(proof.get("completed_at"), field="completed_at")
                completion_valid = True
            except ProfileError:
                completion_valid = False
        else:
            completion_valid = False
        if (
            isinstance(proof, dict)
            and proof.get("schema") == "pr-automation-rollback-proof/v1"
            and type(proof.get("generation")) is int
            and proof["generation"] < generation
            and type(proof.get("ruleset_id")) is int
            and proof.get("ruleset_id") != state.get("owned_ruleset_id")
            and isinstance(owned_history, list)
            and any(
                isinstance(entry, dict)
                and entry.get("generation") == proof.get("generation")
                and entry.get("ruleset_id") == proof.get("ruleset_id")
                for entry in owned_history
            )
            and proof.get("target_branch") == state.get("canary_origin_branch")
            and proof.get("target_sha") is not None
            and FULL_SHA.fullmatch(str(proof.get("target_sha"))) is not None
            and proof.get("digest") == rollback_proof_digest(proof)
            and proof.get("restored_preimage") == state.get("rollback_preimage")
            and proof.get("restored_post_fingerprints") == restored_fingerprints
            and all(
                FULL_FINGERPRINT.fullmatch(str(value)) is not None
                for value in managed_pre.values()
            )
            and set(managed_pre) == {"settings", "ruleset"}
            and completion_valid
        ):
            valid.append(proof)
    if not valid or not any(proof["generation"] == 1 for proof in valid):
        raise ProfileError(
            "canary promotion requires the persisted exact generation-1 rollback proof"
        )
    return max(valid, key=lambda proof: int(proof["generation"]))


def canary_summary_matches_live(
    summary: Any,
    *,
    ownerrepo: str,
    generation: int,
    ruleset_id: int,
    canary_branch: str,
    canary_sha: str,
    destination_branch: str,
    ruleset_fingerprint: str,
    settings_fingerprint: str,
) -> bool:
    if not isinstance(summary, dict):
        return False
    try:
        observed_at = parse_utc_timestamp(summary.get("observed_at"), field="observed_at")
    except ProfileError:
        return False
    now = dt.datetime.now(dt.timezone.utc)
    scenario_modes = summary.get("scenario_modes")
    if (
        observed_at > now + dt.timedelta(minutes=5)
        or now - observed_at > CANARY_PROOF_MAX_AGE
        or not isinstance(scenario_modes, dict)
        or set(scenario_modes) != set(CANARY_SCENARIOS)
        or any(
            scenario_modes.get(scenario_id) != "live"
            for scenario_id in MANDATORY_LIVE_CANARY_SCENARIOS
        )
        or any(mode not in {"live", "mocked"} for mode in scenario_modes.values())
    ):
        return False
    return all(
        summary.get(key) == expected
        for key, expected in {
            "schema": "pr-automation-canary-proof-summary/v1",
            "owner_repo": ownerrepo,
            "generation": generation,
            "owned_ruleset_id": ruleset_id,
            "canary_branch": canary_branch,
            "canary_sha": canary_sha,
            "destination_branch": destination_branch,
            "ruleset_fingerprint": ruleset_fingerprint,
            "settings_fingerprint": settings_fingerprint,
            "required_context": "required / ci",
            "integration_id": 15368,
        }.items()
    ) and FULL_FINGERPRINT.fullmatch(str(summary.get("digest") or "")) is not None


def finalize_retarget(
    state: dict[str, Any],
    *,
    default_branch: str,
    previous_target: str,
    target_branch: str,
    target_sha: str,
    proof_digest: str | None,
    ruleset_id: int,
    settings: dict[str, bool],
    ruleset: dict[str, Any],
) -> None:
    state.setdefault("target_history", []).append(
        {
            "from": previous_target,
            "to": target_branch,
            "ruleset_id": ruleset_id,
            "destination_sha": target_sha,
            "canary_proof_digest": proof_digest,
            "retargeted_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        }
    )
    state["target_branch"] = target_branch
    state["target_sha"] = target_sha
    state["target_stage"] = (
        "promoted" if target_branch == default_branch and previous_target != default_branch
        else target_stage(default_branch, target_branch, int(state.get("ruleset_generation", 0)))
    )
    state["lifecycle"] = "active"
    state["retarget_phase"] = "complete"
    state.pop("pending_target_branch", None)
    state.pop("pending_retarget", None)
    finalize_state(
        state,
        operation="retarget",
        ruleset_id=ruleset_id,
        settings=settings,
        ruleset=ruleset,
    )


def cmd_retarget(
    repo: Path,
    *,
    ownerrepo: str,
    state: dict[str, Any] | None,
    settings: dict[str, bool],
    ruleset_id: int | None,
    ruleset: dict[str, Any] | None,
    default_branch: str,
    target_branch: str,
    canary_proof_path: Path | None,
    dry_run: bool,
) -> int:
    if not state:
        raise ProfileError("cannot retarget: no managed state record")
    if state.get("lifecycle") == "ownership_ambiguous":
        raise ProfileError("cannot retarget an ownership-ambiguous ruleset")
    previous_target = recorded_target_branch(state, default_branch)
    if not ruleset_id or not ruleset:
        raise ProfileError("cannot retarget: managed ruleset is absent")
    if state.get("owned_ruleset_id") != ruleset_id:
        raise ProfileError("cannot retarget: stored ruleset id is not recorded as owned")
    gate_required = bool(state.get("canary_gate_required"))
    generation = int(state.get("ruleset_generation", 0))
    owned_history = state.get("owned_ruleset_history")
    if gate_required:
        if not isinstance(owned_history, list) or not any(
            isinstance(entry, dict)
            and entry.get("generation") == generation
            and entry.get("ruleset_id") == ruleset_id
            and entry.get("target_branch") == previous_target
            for entry in owned_history
        ):
            raise ProfileError("current canary generation/id is missing from owned history")
    live_ruleset_fingerprint = fingerprint(normalize_ruleset(ruleset))
    live_settings_fingerprint = fingerprint(settings)
    canary_sha = str(state.get("target_sha") or "")
    if not gate_required and canary_proof_path is not None:
        raise ProfileError("--canary-proof is only valid for proof-gated canary retargeting")
    desired = desired_ruleset(target_branch)
    desired_fingerprint = fingerprint(normalize_ruleset(desired))

    if state.get("lifecycle") == "retargeting":
        pending = state.get("pending_retarget")
        if not isinstance(pending, dict):
            raise ProfileError("retarget recovery state is missing its exact transition record")
        if set(pending) != {
            "schema",
            "ruleset_id",
            "from_target",
            "to_target",
            "from_target_sha",
            "to_target_sha",
            "preimage",
            "preimage_fingerprint",
            "desired_postimage",
            "desired_fingerprint",
            "settings_fingerprint",
            "canary_proof_digest",
            "rollback_proof_digest",
        }:
            raise ProfileError("retarget recovery transition does not match its closed schema")
        expected_pending = {
            "schema": "pr-automation-retarget-transition/v1",
            "ruleset_id": ruleset_id,
            "from_target": previous_target,
            "to_target": target_branch,
            "from_target_sha": canary_sha,
        }
        for key, expected in expected_pending.items():
            if pending.get(key) != expected:
                raise ProfileError(
                    f"retarget recovery binding mismatch for {key}: "
                    f"expected {expected!r}, found {pending.get(key)!r}"
                )
        preimage = pending.get("preimage")
        desired_postimage = pending.get("desired_postimage")
        if (
            not isinstance(preimage, dict)
            or not isinstance(desired_postimage, dict)
            or pending.get("preimage_fingerprint") != fingerprint(normalize_ruleset(preimage))
            or pending.get("desired_fingerprint")
            != fingerprint(normalize_ruleset(desired_postimage))
            or pending.get("desired_fingerprint") != desired_fingerprint
            or normalize_ruleset(desired_postimage) != normalize_ruleset(desired)
            or not FULL_SHA.fullmatch(str(pending.get("to_target_sha") or ""))
            or (
                gate_required
                and (
                    not FULL_FINGERPRINT.fullmatch(
                        str(pending.get("canary_proof_digest") or "")
                    )
                    or not FULL_FINGERPRINT.fullmatch(
                        str(pending.get("rollback_proof_digest") or "")
                    )
                )
            )
        ):
            raise ProfileError("retarget recovery transition fingerprints are invalid")
        live_normalized = normalize_ruleset(ruleset)
        if live_normalized == normalize_ruleset(desired_postimage):
            persisted_settings = state.get("managed_postimage", {}).get("settings")
            persisted_summary = state.get("canary_proof")
            persisted_rollback = (
                require_prior_canary_rollback_proof(state) if gate_required else None
            )
            if (
                not isinstance(persisted_settings, dict)
                or fingerprint(normalize_settings(persisted_settings))
                != pending.get("settings_fingerprint")
                or (
                    gate_required
                    and (
                        not isinstance(persisted_summary, dict)
                        or persisted_summary.get("digest")
                        != pending.get("canary_proof_digest")
                        or persisted_rollback is None
                        or persisted_rollback.get("digest")
                        != pending.get("rollback_proof_digest")
                    )
                )
            ):
                raise ProfileError(
                    "retarget recovery postimage binding is inconsistent with persisted state"
                )
            if not dry_run:
                finalize_retarget(
                    state,
                    default_branch=default_branch,
                    previous_target=previous_target,
                    target_branch=target_branch,
                    target_sha=str(pending["to_target_sha"]),
                    proof_digest=(
                        str(pending["canary_proof_digest"])
                        if pending.get("canary_proof_digest")
                        else None
                    ),
                    ruleset_id=ruleset_id,
                    settings=normalize_settings(persisted_settings),
                    ruleset=ruleset,
                )
            print(
                f"pr-automation enforce --retarget: recovered exact postimage "
                f"(ruleset id {ruleset_id}, target {target_branch})"
            )
            return 0
        if live_normalized != normalize_ruleset(preimage):
            raise ProfileError(
                "retarget recovery refusal: live ruleset is neither exact preimage nor desired postimage"
            )
        destination_sha = require_exact_remote_branch_head(repo, ownerrepo, target_branch)
        if pending.get("settings_fingerprint") != live_settings_fingerprint:
            raise ProfileError("retarget recovery refusal: managed settings changed")
        proof_summary = None
        rollback_proof = None
        if gate_required:
            rollback_proof = require_prior_canary_rollback_proof(state)
            current_canary_sha = github_branch_sha(ownerrepo, previous_target)
            if not FULL_SHA.fullmatch(canary_sha) or current_canary_sha != canary_sha:
                raise ProfileError(
                    "canary target SHA changed; refresh canary state/evidence before retry"
                )
            if canary_proof_path is not None:
                proof_summary = validate_canary_proof(
                    canary_proof_path,
                    ownerrepo=ownerrepo,
                    generation=generation,
                    ruleset_id=ruleset_id,
                    canary_branch=previous_target,
                    canary_sha=canary_sha,
                    destination_branch=target_branch,
                    ruleset_fingerprint=str(pending["preimage_fingerprint"]),
                    settings_fingerprint=live_settings_fingerprint,
                )
            else:
                persisted_summary = state.get("canary_proof")
                if canary_summary_matches_live(
                    persisted_summary,
                    ownerrepo=ownerrepo,
                    generation=generation,
                    ruleset_id=ruleset_id,
                    canary_branch=previous_target,
                    canary_sha=canary_sha,
                    destination_branch=target_branch,
                    ruleset_fingerprint=str(pending["preimage_fingerprint"]),
                    settings_fingerprint=live_settings_fingerprint,
                ):
                    proof_summary = persisted_summary
                else:
                    raise ProfileError(
                        "retarget retry requires a fresh --canary-proof while live remains "
                        "the exact persisted preimage"
                    )
        replacement_needed = (
            pending.get("to_target_sha") != destination_sha
            or (
                gate_required
                and proof_summary is not None
                and pending.get("canary_proof_digest") != proof_summary.get("digest")
            )
            or (
                gate_required
                and rollback_proof is not None
                and pending.get("rollback_proof_digest") != rollback_proof.get("digest")
            )
        )
        if replacement_needed and not dry_run:
            pending["to_target_sha"] = destination_sha
            if proof_summary is not None:
                state["canary_proof"] = proof_summary
                pending["canary_proof_digest"] = proof_summary.get("digest")
            if rollback_proof is not None:
                pending["rollback_proof_digest"] = rollback_proof.get("digest")
            state["pending_retarget"] = pending
            write_state(ownerrepo, state)
        if dry_run:
            print(
                f"[dry-run] retarget recovery gate READY; would "
                f"{'replace pending binding then ' if replacement_needed else ''}"
                f"retry PUT for ruleset id {ruleset_id} from exact persisted preimage"
            )
            return 0
        pre_ruleset = preimage
    else:
        destination_sha = require_exact_remote_branch_head(repo, ownerrepo, target_branch)
        assert_managed_live(state, settings, ruleset_id, ruleset)
        if state.get("lifecycle") != "active":
            raise ProfileError(
                f"cannot retarget from lifecycle {state.get('lifecycle')!r}; "
                "enforce active canary first"
            )
        remote_plan("enforce --retarget", ownerrepo, target_branch, ruleset_id)
        if previous_target == target_branch and normalize_ruleset(ruleset) == normalize_ruleset(desired):
            print(f"pr-automation enforce --retarget: no-op; target already {target_branch}")
            return 0
        proof_summary = None
        rollback_proof = None
        if gate_required:
            rollback_proof = require_prior_canary_rollback_proof(state)
            current_canary_sha = github_branch_sha(ownerrepo, previous_target)
            if not FULL_SHA.fullmatch(canary_sha) or current_canary_sha != canary_sha:
                raise ProfileError(
                    "canary target SHA changed or was never captured; rerun explicit canary "
                    "enforce from its exact current head before collecting evidence"
                )
            if canary_proof_path is None:
                raise ProfileError(
                    "proof-gated canary retarget requires --canary-proof <json>"
                )
            proof_summary = validate_canary_proof(
                canary_proof_path,
                ownerrepo=ownerrepo,
                generation=generation,
                ruleset_id=ruleset_id,
                canary_branch=previous_target,
                canary_sha=canary_sha,
                destination_branch=target_branch,
                ruleset_fingerprint=live_ruleset_fingerprint,
                settings_fingerprint=live_settings_fingerprint,
            )
        if dry_run:
            gate = (
                f"READY proof={proof_summary['digest']} rollback={rollback_proof['digest']}"
                if gate_required and proof_summary and rollback_proof
                else "NOT_REQUIRED legacy default enforcement"
            )
            print(
                f"[dry-run] canary promotion gate {gate}; would PUT only ruleset id "
                f"{ruleset_id}; retarget {previous_target} -> {target_branch}; settings unchanged"
            )
            return 0
        pre_ruleset = expect_ruleset_now(
            ownerrepo,
            expected_id=ruleset_id,
            expected_fingerprint=live_ruleset_fingerprint,
        )
        expect_settings_now(ownerrepo, live_settings_fingerprint)
        append_preimage(state, operation="retarget", object_name="ruleset", value=pre_ruleset)
        if proof_summary is not None:
            state["canary_proof"] = proof_summary
        state["lifecycle"] = "retargeting"
        state["retarget_phase"] = "ruleset_pending"
        state["pending_target_branch"] = target_branch
        state["pending_retarget"] = {
            "schema": "pr-automation-retarget-transition/v1",
            "ruleset_id": ruleset_id,
            "from_target": previous_target,
            "to_target": target_branch,
            "from_target_sha": canary_sha,
            "to_target_sha": destination_sha,
            "preimage": normalize_ruleset(pre_ruleset),
            "preimage_fingerprint": fingerprint(normalize_ruleset(pre_ruleset)),
            "desired_postimage": normalize_ruleset(desired),
            "desired_fingerprint": desired_fingerprint,
            "settings_fingerprint": live_settings_fingerprint,
            "canary_proof_digest": (
                proof_summary.get("digest") if proof_summary is not None else None
            ),
            "rollback_proof_digest": (
                rollback_proof.get("digest") if rollback_proof is not None else None
            ),
        }
        write_state(ownerrepo, state)
    expect_ruleset_now(
        ownerrepo,
        expected_id=ruleset_id,
        expected_fingerprint=fingerprint(normalize_ruleset(pre_ruleset)),
    )
    expect_settings_now(ownerrepo, fingerprint(settings))
    if gate_required and github_branch_sha(ownerrepo, previous_target) != canary_sha:
        raise ProfileError("canary branch changed immediately before retarget PUT")
    require_exact_remote_branch_head(repo, ownerrepo, target_branch)
    gh_api(f"repos/{ownerrepo}/rulesets/{ruleset_id}", method="PUT", payload=desired)
    require_exact_remote_branch_head(repo, ownerrepo, target_branch)
    post_ruleset = verify_ruleset_postimage(
        ownerrepo,
        expected_id=ruleset_id,
        desired=desired,
    )
    post_settings = verify_settings_postimage(ownerrepo, settings)
    finalize_retarget(
        state,
        default_branch=default_branch,
        previous_target=previous_target,
        target_branch=target_branch,
        target_sha=destination_sha,
        proof_digest=(
            str(state.get("canary_proof", {}).get("digest"))
            if gate_required and isinstance(state.get("canary_proof"), dict)
            else None
        ),
        ruleset_id=ruleset_id,
        settings=post_settings,
        ruleset=post_ruleset,
    )
    print(
        f"pr-automation enforce --retarget: preserved ruleset id {ruleset_id}; "
        f"target {previous_target} -> {target_branch}"
    )
    return 0


def cmd_enforce(
    repo: Path,
    *,
    dry_run: bool,
    target_branch: str | None = None,
    retarget: str | None = None,
    canary_proof: str | None = None,
) -> int:
    ownerrepo = validate_target(repo, require_clean=True)
    ensure_local_compliant(repo)
    require_gh()
    settings, ruleset_id, ruleset, default_branch = live_objects(ownerrepo)
    existing_state = read_state(ownerrepo)
    if retarget is not None:
        validate_head_branch(retarget)
        proof_path = Path(canary_proof).expanduser().resolve() if canary_proof else None
        return cmd_retarget(
            repo,
            ownerrepo=ownerrepo,
            state=existing_state,
            settings=settings,
            ruleset_id=ruleset_id,
            ruleset=ruleset,
            default_branch=default_branch,
            target_branch=retarget,
            canary_proof_path=proof_path,
            dry_run=dry_run,
        )
    if canary_proof is not None:
        raise ProfileError("--canary-proof requires --retarget")
    requested_target = target_branch or default_branch
    validate_head_branch(requested_target)
    if existing_state:
        recorded_target = recorded_target_branch(existing_state, default_branch)
        if target_branch is None and recorded_target != default_branch:
            raise ProfileError(
                "no-flag enforce targets the actual default branch only; "
                f"managed target is {recorded_target!r}. Use --target-branch for canary retry "
                "or --retarget for in-place promotion"
            )
        if requested_target != recorded_target:
            raise ProfileError(
                f"enforce target {requested_target!r} differs from managed target "
                f"{recorded_target!r}; use --retarget for an owned in-place change"
            )
    verified_target_sha = require_exact_remote_branch_head(repo, ownerrepo, requested_target)
    desired = desired_ruleset(requested_target)
    desired_settings = load_config()["settings"]
    if ruleset is not None and existing_state is None:
        raise ProfileError("same-named live ruleset is not owned by a local state record; refusing adoption")
    if existing_state:
        if existing_state.get("lifecycle") == "ownership_ambiguous":
            raise ProfileError(
                "cannot enforce: ruleset creation ownership is ambiguous; refusing adoption"
            )
        recorded_create_postimage = (
            existing_state.get("lifecycle") == "enforcing"
            and existing_state.get("enforce_phase") == "ruleset_pending"
            and existing_state.get("ruleset_id") == ruleset_id
            and existing_state.get("owned_ruleset_id") == ruleset_id
            and bool(existing_state.get("task_created_ruleset"))
            and ruleset_id is not None
            and normalize_ruleset(ruleset) == normalize_ruleset(desired)
            and existing_state.get("managed_post_fingerprints", {}).get("settings")
            == fingerprint(settings)
        )
        if recorded_create_postimage:
            if not dry_run:
                existing_state["enforce_phase"] = "settings_pending"
                finalize_state(
                    existing_state,
                    operation="enforce-ruleset",
                    ruleset_id=ruleset_id,
                    settings=settings,
                    ruleset=ruleset,
                )
        elif resume_settings_transition(
            existing_state,
            operation="enforce",
            settings=settings,
            ruleset_id=ruleset_id,
            ruleset=ruleset,
            dry_run=dry_run,
        ):
            pass
        else:
            assert_managed_live(existing_state, settings, ruleset_id, ruleset)
    remote_plan("enforce", ownerrepo, requested_target, ruleset_id)
    if (
        existing_state
        and normalize_ruleset(ruleset) == normalize_ruleset(desired)
        and settings == desired_settings
    ):
        target_sha_changed = existing_state.get("target_sha") != verified_target_sha
        if not dry_run and (
            existing_state.get("lifecycle") != "active" or target_sha_changed
        ):
            existing_state["lifecycle"] = "active"
            existing_state["enforce_phase"] = "complete"
            existing_state["target_sha"] = verified_target_sha
            if target_sha_changed:
                existing_state["canary_proof"] = None
            finalize_state(
                existing_state,
                operation="enforce",
                ruleset_id=ruleset_id,
                settings=settings,
                ruleset=ruleset,
            )
        print("pr-automation enforce: no-op; live profile already current")
        return 0
    if dry_run:
        print("[dry-run] would drift-check then write the profile ruleset and three managed settings")
        return 0

    state = seed_state(
        ownerrepo,
        default_branch,
        requested_target,
        target_stage(default_branch, requested_target, 0),
        verified_target_sha,
        target_branch is not None and requested_target != default_branch,
        ruleset_id,
        settings,
        ruleset,
    )
    if state.get("target_sha") != verified_target_sha:
        state["target_sha"] = verified_target_sha
        state["canary_proof"] = None
    initializing = (
        state.get("lifecycle") == "initializing"
        and state.get("enforce_phase") == "pre_mutation"
    )
    if not initializing:
        state["lifecycle"] = "enforcing"
        state["enforce_phase"] = (
            "settings_pending"
            if normalize_ruleset(ruleset) == normalize_ruleset(desired)
            else "ruleset_pending"
        )
    state["rollback_phase"] = "not_started"
    state["rolled_back"] = False
    write_state(ownerrepo, state)
    ruleset_post = ruleset
    if normalize_ruleset(ruleset) != normalize_ruleset(desired):
        # Best-effort optimistic refusal: re-read id+semantic fingerprint immediately before write.
        pre_ruleset = expect_ruleset_now(
            ownerrepo,
            expected_id=ruleset_id,
            expected_fingerprint=fingerprint(normalize_ruleset(ruleset)),
        )
        append_preimage(state, operation="enforce", object_name="ruleset", value=pre_ruleset)
        state["lifecycle"] = "enforcing"
        state["enforce_phase"] = "ruleset_pending"
        write_state(ownerrepo, state)
        expect_ruleset_now(
            ownerrepo,
            expected_id=ruleset_id,
            expected_fingerprint=fingerprint(normalize_ruleset(pre_ruleset)),
        )
        expect_settings_now(ownerrepo, fingerprint(settings))
        require_exact_remote_branch_head(repo, ownerrepo, requested_target)
        if ruleset_id:
            gh_api(f"repos/{ownerrepo}/rulesets/{ruleset_id}", method="PUT", payload=desired)
        else:
            try:
                response = gh_api(f"repos/{ownerrepo}/rulesets", method="POST", payload=desired)
                ruleset_id = int(response["id"])
            except (ProfileError, KeyError, TypeError, ValueError) as exc:
                state["lifecycle"] = "ownership_ambiguous"
                state["enforce_phase"] = "ruleset_create_ambiguous"
                state["ownership_ambiguity"] = {
                    "operation": "create-ruleset",
                    "expected_ruleset_fingerprint": fingerprint(normalize_ruleset(desired)),
                    "returned_id": None,
                }
                state["ruleset_id"] = None
                state["owned_ruleset_id"] = None
                write_state(ownerrepo, state)
                raise ProfileError(
                    "ruleset creation ownership is ambiguous: GitHub did not return a recorded "
                    "resource id; refusing adoption, retry, or rollback deletion"
                ) from exc
            prior_owned_ids = {
                entry.get("ruleset_id")
                for entry in state.get("owned_ruleset_history", [])
                if isinstance(entry, dict)
            }
            if ruleset_id in prior_owned_ids or ruleset_id == state.get("last_deleted_ruleset_id"):
                state["lifecycle"] = "ownership_ambiguous"
                state["enforce_phase"] = "ruleset_id_reused"
                state["ruleset_id"] = None
                state["owned_ruleset_id"] = None
                write_state(ownerrepo, state)
                raise ProfileError(
                    "ruleset creation returned a previously owned/deleted id; refusing ownership"
                )
            state["ruleset_id"] = ruleset_id
            state["owned_ruleset_id"] = ruleset_id
            state["ruleset_generation"] = int(state.get("ruleset_generation", 0)) + 1
            state["target_branch"] = requested_target
            state["target_stage"] = target_stage(
                default_branch,
                requested_target,
                int(state["ruleset_generation"]),
            )
            state["target_sha"] = verified_target_sha
            state["canary_proof"] = None
            state.setdefault("owned_ruleset_history", []).append(
                {
                    "generation": int(state["ruleset_generation"]),
                    "ruleset_id": ruleset_id,
                    "target_branch": requested_target,
                    "target_sha": verified_target_sha,
                    "created_at": dt.datetime.now(dt.timezone.utc)
                    .replace(microsecond=0)
                    .isoformat(),
                }
            )
            write_state(ownerrepo, state)
        state["ruleset_id"] = ruleset_id
        require_exact_remote_branch_head(repo, ownerrepo, requested_target)
        ruleset_post = verify_ruleset_postimage(
            ownerrepo,
            expected_id=ruleset_id,
            desired=desired,
        )
        # Advance the managed postimage after the first independent write so a later failure is retryable.
        state["enforce_phase"] = "settings_pending"
        finalize_state(
            state,
            operation="enforce-ruleset",
            ruleset_id=ruleset_id,
            settings=settings,
            ruleset=ruleset_post,
        )

    post_settings = settings
    if settings != desired_settings:
        pre_settings = expect_settings_now(ownerrepo, fingerprint(settings))
        append_preimage(state, operation="enforce", object_name="settings", value=pre_settings)
        begin_settings_transition(
            state,
            operation="enforce",
            current=pre_settings,
            desired=desired_settings,
        )
        write_state(ownerrepo, state)
        verify_ruleset_postimage(ownerrepo, expected_id=ruleset_id, desired=desired)
        expect_settings_now(ownerrepo, fingerprint(pre_settings))
        gh_api(f"repos/{ownerrepo}", method="PATCH", payload=desired_settings)
        post_settings = verify_settings_postimage(ownerrepo, desired_settings)
    post_ruleset = verify_ruleset_postimage(ownerrepo, expected_id=ruleset_id, desired=desired)
    post_id = ruleset_id
    state["lifecycle"] = "active"
    state["enforce_phase"] = "complete"
    state["pause_phase"] = "not_started"
    state["repair_phase"] = "not_started"
    state["rollback_phase"] = "not_started"
    finalize_state(
        state,
        operation="enforce",
        ruleset_id=post_id,
        settings=post_settings,
        ruleset=post_ruleset,
    )
    print(f"pr-automation enforce: active (ruleset id {post_id}); state: {state_path(ownerrepo)}")
    return 0


def cmd_pause(repo: Path, *, dry_run: bool) -> int:
    ownerrepo = validate_target(repo, require_clean=True)
    require_gh()
    state = read_state(ownerrepo)
    if not state:
        raise ProfileError("cannot pause: no managed state record")
    settings, ruleset_id, ruleset, default_branch = live_objects(ownerrepo)
    target_branch = recorded_target_branch(state, default_branch)
    require_exact_remote_branch_head(repo, ownerrepo, target_branch)
    if not ruleset_id or not ruleset:
        raise ProfileError("cannot pause: managed profile ruleset missing")
    active_ruleset = desired_ruleset(target_branch)
    if normalize_ruleset(ruleset) != normalize_ruleset(active_ruleset):
        raise ProfileError("pause refuses unless the full PR/check ruleset is active and exact")
    desired_paused_settings = paused_settings()
    phase = state.get("pause_phase", "not_started")
    resume_settings_transition = False
    if (
        state.get("lifecycle") == "pausing"
        and phase == "settings_pending"
        and settings == desired_paused_settings
    ):
        expected = state.get("managed_post_fingerprints", {})
        if (
            state.get("ruleset_id") != ruleset_id
            or expected.get("ruleset") != fingerprint(normalize_ruleset(ruleset))
        ):
            raise ProfileError("pause resume refusal: ruleset id/fingerprint changed")
        resume_settings_transition = True
        phase = "disarming"
    else:
        assert_managed_live(state, settings, ruleset_id, ruleset)
    remote_plan("pause", ownerrepo, target_branch, ruleset_id)
    if dry_run:
        armed = open_armed_auto_merges(ownerrepo)
        print(
            f"[dry-run] would keep ruleset active, set allow_auto_merge=false, "
            f"then exact-head-check and disarm {len(armed)} armed request(s)"
        )
        return 0

    if resume_settings_transition:
        state["pause_phase"] = "disarming"
        finalize_state(
            state,
            operation="pause-settings",
            ruleset_id=ruleset_id,
            settings=settings,
            ruleset=ruleset,
        )

    if settings != desired_paused_settings:
        state["lifecycle"] = "pausing"
        state["pause_phase"] = "settings_pending"
        write_state(ownerrepo, state)
        pre_settings = expect_settings_now(ownerrepo, fingerprint(settings))
        append_preimage(state, operation="pause", object_name="settings", value=pre_settings)
        write_state(ownerrepo, state)
        verify_ruleset_postimage(ownerrepo, expected_id=ruleset_id, desired=active_ruleset)
        expect_settings_now(ownerrepo, fingerprint(pre_settings))
        gh_api(f"repos/{ownerrepo}", method="PATCH", payload=desired_paused_settings)
        post_settings = verify_settings_postimage(ownerrepo, desired_paused_settings)
        post_ruleset = verify_ruleset_postimage(
            ownerrepo,
            expected_id=ruleset_id,
            desired=active_ruleset,
        )
        state["lifecycle"] = "pausing"
        state["pause_phase"] = "disarming"
        finalize_state(
            state,
            operation="pause-settings",
            ruleset_id=ruleset_id,
            settings=post_settings,
            ruleset=post_ruleset,
        )

    for _ in range(5):
        verify_ruleset_postimage(ownerrepo, expected_id=ruleset_id, desired=active_ruleset)
        expect_settings_now(ownerrepo, fingerprint(desired_paused_settings))
        armed = open_armed_auto_merges(ownerrepo)
        if not armed:
            break
        for request in armed:
            verify_ruleset_postimage(ownerrepo, expected_id=ruleset_id, desired=active_ruleset)
            expect_settings_now(ownerrepo, fingerprint(desired_paused_settings))
            disarm_auto_merge(ownerrepo, request)
            verify_ruleset_postimage(ownerrepo, expected_id=ruleset_id, desired=active_ruleset)
            expect_settings_now(ownerrepo, fingerprint(desired_paused_settings))
    else:
        raise ProfileError("pause failed closed: armed auto-merge requests did not converge to zero")

    if open_armed_auto_merges(ownerrepo):
        raise ProfileError("pause postcondition failed: an auto-merge request remains armed")
    post_settings = verify_settings_postimage(ownerrepo, desired_paused_settings)
    post_ruleset = verify_ruleset_postimage(
        ownerrepo,
        expected_id=ruleset_id,
        desired=active_ruleset,
    )
    state["lifecycle"] = "paused"
    state["pause_phase"] = "complete"
    finalize_state(
        state,
        operation="pause",
        ruleset_id=ruleset_id,
        settings=post_settings,
        ruleset=post_ruleset,
    )
    print(
        "pr-automation pause: auto-merge disabled and requests disarmed; "
        "PR/check ruleset remains active"
    )
    return 0


def cmd_repair(repo: Path, *, dry_run: bool) -> int:
    ownerrepo = validate_target(repo, require_clean=True)
    ensure_local_compliant(repo)
    require_gh()
    state = read_state(ownerrepo)
    if not state:
        raise ProfileError("cannot repair: no managed state record; run enforce")
    settings, ruleset_id, ruleset, default_branch = live_objects(ownerrepo)
    target_branch = recorded_target_branch(state, default_branch)
    require_exact_remote_branch_head(repo, ownerrepo, target_branch)
    desired = desired_ruleset(target_branch)
    desired_settings = load_config()["settings"]
    if not resume_settings_transition(
        state,
        operation="repair",
        settings=settings,
        ruleset_id=ruleset_id,
        ruleset=ruleset,
        dry_run=dry_run,
    ):
        assert_managed_live(state, settings, ruleset_id, ruleset)
    if not ruleset_id:
        raise ProfileError("cannot repair: managed ruleset id missing")
    remote_plan("repair", ownerrepo, target_branch, ruleset_id)
    if normalize_ruleset(ruleset) == normalize_ruleset(desired) and settings == desired_settings:
        if not dry_run and state.get("lifecycle") != "active":
            state["lifecycle"] = "active"
            state["repair_phase"] = "complete"
            finalize_state(
                state,
                operation="repair",
                ruleset_id=ruleset_id,
                settings=settings,
                ruleset=ruleset,
            )
        print("pr-automation repair: no-op; live profile already current")
        return 0
    if dry_run:
        print("[dry-run] would restore active profile ruleset and the three managed settings")
        return 0
    ruleset_post = ruleset
    if normalize_ruleset(ruleset) != normalize_ruleset(desired):
        pre_ruleset = expect_ruleset_now(
            ownerrepo,
            expected_id=ruleset_id,
            expected_fingerprint=fingerprint(normalize_ruleset(ruleset)),
        )
        expect_settings_now(ownerrepo, fingerprint(settings))
        append_preimage(state, operation="repair", object_name="ruleset", value=pre_ruleset)
        write_state(ownerrepo, state)
        expect_ruleset_now(
            ownerrepo,
            expected_id=ruleset_id,
            expected_fingerprint=fingerprint(normalize_ruleset(pre_ruleset)),
        )
        expect_settings_now(ownerrepo, fingerprint(settings))
        gh_api(f"repos/{ownerrepo}/rulesets/{ruleset_id}", method="PUT", payload=desired)
        ruleset_post = verify_ruleset_postimage(ownerrepo, expected_id=ruleset_id, desired=desired)
        state["lifecycle"] = "repairing"
        finalize_state(
            state,
            operation="repair-ruleset",
            ruleset_id=ruleset_id,
            settings=settings,
            ruleset=ruleset_post,
        )
    post_settings = settings
    if settings != desired_settings:
        verify_ruleset_postimage(ownerrepo, expected_id=ruleset_id, desired=desired)
        pre_settings = expect_settings_now(ownerrepo, fingerprint(settings))
        append_preimage(state, operation="repair", object_name="settings", value=pre_settings)
        state["lifecycle"] = "repairing"
        state["repair_phase"] = "settings_pending"
        begin_settings_transition(
            state,
            operation="repair",
            current=pre_settings,
            desired=desired_settings,
        )
        write_state(ownerrepo, state)
        verify_ruleset_postimage(ownerrepo, expected_id=ruleset_id, desired=desired)
        expect_settings_now(ownerrepo, fingerprint(pre_settings))
        gh_api(f"repos/{ownerrepo}", method="PATCH", payload=desired_settings)
        post_settings = verify_settings_postimage(ownerrepo, desired_settings)
    post_ruleset = verify_ruleset_postimage(ownerrepo, expected_id=ruleset_id, desired=desired)
    post_id = ruleset_id
    state["lifecycle"] = "active"
    state["pause_phase"] = "not_started"
    state["enforce_phase"] = "complete"
    state["repair_phase"] = "complete"
    finalize_state(
        state,
        operation="repair",
        ruleset_id=post_id,
        settings=post_settings,
        ruleset=post_ruleset,
    )
    print("pr-automation repair: desired profile restored")
    return 0


def complete_rollback_proof(
    state: dict[str, Any],
    *,
    settings: dict[str, bool],
    ruleset: dict[str, Any] | None,
) -> None:
    pending = state.get("pending_rollback_proof")
    if not isinstance(pending, dict):
        return
    restored_preimage = {
        "settings": normalize_settings(settings),
        "ruleset": normalize_ruleset(ruleset),
    }
    if restored_preimage != state.get("rollback_preimage"):
        raise ProfileError("rollback proof refusal: restored state is not the exact rollback preimage")
    record = {
        **copy.deepcopy(pending),
        "restored_post_fingerprints": {
            "settings": fingerprint(restored_preimage["settings"]),
            "ruleset": fingerprint(restored_preimage["ruleset"]),
        },
        "restored_preimage": restored_preimage,
        "completed_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
    }
    record["digest"] = rollback_proof_digest(record)
    proofs = state.setdefault("rollback_proofs", [])
    matching = [
        proof
        for proof in proofs
        if isinstance(proof, dict)
        and proof.get("generation") == record.get("generation")
        and proof.get("ruleset_id") == record.get("ruleset_id")
    ]
    if matching and matching != [record]:
        raise ProfileError("rollback proof refusal: conflicting proof already exists")
    if not matching:
        proofs.append(record)
    state.pop("pending_rollback_proof", None)


def cmd_rollback(repo: Path, *, dry_run: bool) -> int:
    ownerrepo = validate_target(repo, require_clean=True)
    require_gh()
    state = read_state(ownerrepo)
    if not state:
        raise ProfileError("cannot rollback: no managed state record")
    settings, ruleset_id, ruleset, default_branch = live_objects(ownerrepo)
    target_branch = recorded_target_branch(state, default_branch)
    require_exact_remote_branch_head(repo, ownerrepo, target_branch)
    if state.get("lifecycle") == "ownership_ambiguous":
        raise ProfileError(
            "rollback refused: ruleset creation ownership is ambiguous and no returned id was "
            "recorded; this command will never delete the matching resource"
        )
    rollback = state.get("rollback_preimage", {})
    prior_ruleset = rollback.get("ruleset")
    prior_settings = rollback.get("settings")
    if not isinstance(prior_settings, dict):
        raise ProfileError("rollback state is missing settings preimage")
    remote_plan("rollback", ownerrepo, target_branch, ruleset_id)
    lifecycle = state.get("lifecycle")
    phase = state.get("rollback_phase", "not_started")
    task_created = bool(state.get("task_created_ruleset"))
    if lifecycle == "rolled_back" and phase == "complete":
        assert_managed_live(state, settings, ruleset_id, ruleset)
        print("pr-automation rollback: no-op; original preimage already restored")
        return 0
    if dry_run:
        if lifecycle != "rolling_back":
            assert_managed_live(state, settings, ruleset_id, ruleset)
            remaining = "ruleset, settings"
        elif phase == "ruleset_pending" and task_created and ruleset_id is None:
            expected_settings_fp = state.get("managed_post_fingerprints", {}).get("settings")
            expect_settings_now(ownerrepo, expected_settings_fp)
            remaining = "settings (task-created ruleset already absent)"
        else:
            assert_managed_live(state, settings, ruleset_id, ruleset)
            remaining = "settings" if phase in {"ruleset_done", "settings_pending"} else "ruleset, settings"
        print(
            f"[dry-run] rollback phase={phase}; remaining={remaining}; "
            "would perform reads/drift checks only before each planned write"
        )
        return 0

    if lifecycle != "rolling_back":
        assert_managed_live(state, settings, ruleset_id, ruleset)
        if task_created and state.get("canary_gate_required"):
            generation = int(state.get("ruleset_generation", 0))
            if generation < 1 or not ruleset_id:
                raise ProfileError("rollback proof refusal: missing owned canary generation/id")
            state["pending_rollback_proof"] = {
                "schema": "pr-automation-rollback-proof/v1",
                "generation": generation,
                "ruleset_id": ruleset_id,
                "target_branch": target_branch,
                "target_sha": state.get("target_sha"),
                "managed_pre_fingerprints": copy.deepcopy(
                    state.get("managed_post_fingerprints", {})
                ),
            }
        state["lifecycle"] = "rolling_back"
        state["rollback_phase"] = "ruleset_pending"
        state["rolled_back"] = False
        write_state(ownerrepo, state)
        phase = "ruleset_pending"

    # Resume a DELETE that reached GitHub but failed before the local phase record advanced.
    if phase == "ruleset_pending" and task_created and ruleset_id is None:
        expected_settings_fp = state.get("managed_post_fingerprints", {}).get("settings")
        expect_settings_now(ownerrepo, expected_settings_fp)
        state["rollback_phase"] = "ruleset_done"
        finalize_state(
            state,
            operation="rollback-ruleset",
            ruleset_id=None,
            settings=settings,
            ruleset=None,
        )
        phase = "ruleset_done"

    if phase == "ruleset_pending":
        assert_managed_live(state, settings, ruleset_id, ruleset)
        if ruleset_id is None:
            raise ProfileError("rollback refusal: managed ruleset unexpectedly absent")
        pre_ruleset = expect_ruleset_now(
            ownerrepo,
            expected_id=ruleset_id,
            expected_fingerprint=fingerprint(normalize_ruleset(ruleset)),
        )
        expect_settings_now(ownerrepo, fingerprint(settings))
        append_preimage(state, operation="rollback", object_name="ruleset", value=pre_ruleset)
        if task_created:
            state["last_deleted_ruleset_id"] = ruleset_id
        write_state(ownerrepo, state)
        expect_ruleset_now(
            ownerrepo,
            expected_id=ruleset_id,
            expected_fingerprint=fingerprint(normalize_ruleset(pre_ruleset)),
        )
        expect_settings_now(ownerrepo, fingerprint(settings))
        if task_created:
            if prior_ruleset is not None:
                raise ProfileError("rollback state inconsistent: task-created ruleset has prior payload")
            if state.get("owned_ruleset_id") != ruleset_id:
                raise ProfileError(
                    "rollback refusal: task-created ruleset id is not recorded as owned"
                )
            gh_api(f"repos/{ownerrepo}/rulesets/{ruleset_id}", method="DELETE")
            ruleset_id = None
            ruleset_post = verify_ruleset_postimage(ownerrepo, expected_id=None, desired=None)
        else:
            if prior_ruleset is None:
                raise ProfileError("rollback state inconsistent: adopted ruleset lacks prior payload")
            gh_api(f"repos/{ownerrepo}/rulesets/{ruleset_id}", method="PUT", payload=prior_ruleset)
            ruleset_post = verify_ruleset_postimage(
                ownerrepo,
                expected_id=ruleset_id,
                desired=prior_ruleset,
            )
        state["rollback_phase"] = "ruleset_done"
        finalize_state(
            state,
            operation="rollback-ruleset",
            ruleset_id=ruleset_id,
            settings=settings,
            ruleset=ruleset_post,
        )
        phase = "ruleset_done"

    expected_ruleset_id = None if task_created else state.get("ruleset_id")
    expected_ruleset = None if task_created else prior_ruleset
    verify_ruleset_postimage(
        ownerrepo,
        expected_id=expected_ruleset_id,
        desired=expected_ruleset,
    )
    current_settings = normalize_settings(remote_repo(ownerrepo))
    expected_settings_fp = state.get("managed_post_fingerprints", {}).get("settings")
    current_settings_fp = fingerprint(current_settings)
    already_restored = current_settings == normalize_settings(prior_settings)
    if current_settings_fp != expected_settings_fp and not (
        phase == "settings_pending" and already_restored
    ):
        raise ProfileError(
            "rollback optimistic drift refusal: live settings differ from the stored "
            f"managed postimage for phase {phase}"
        )
    if already_restored:
        state["rollback_phase"] = "complete"
        state["lifecycle"] = "rolled_back"
        state["rolled_back"] = True
        if task_created:
            state["target_stage"] = (
                "canary_rolled_back"
                if target_branch != default_branch
                else "default_rolled_back"
            )
        complete_rollback_proof(
            state,
            settings=current_settings,
            ruleset=expected_ruleset,
        )
        finalize_state(
            state,
            operation="rollback",
            ruleset_id=expected_ruleset_id,
            settings=current_settings,
            ruleset=expected_ruleset,
        )
        print("pr-automation rollback: original preimage already reached; completion recorded")
        return 0

    if phase not in {"ruleset_done", "settings_pending"}:
        raise ProfileError(f"rollback state has unsupported phase: {phase}")
    state["rollback_phase"] = "settings_pending"
    write_state(ownerrepo, state)
    verify_ruleset_postimage(
        ownerrepo,
        expected_id=expected_ruleset_id,
        desired=expected_ruleset,
    )
    pre_settings = expect_settings_now(ownerrepo, expected_settings_fp)
    append_preimage(state, operation="rollback", object_name="settings", value=pre_settings)
    write_state(ownerrepo, state)
    verify_ruleset_postimage(
        ownerrepo,
        expected_id=expected_ruleset_id,
        desired=expected_ruleset,
    )
    expect_settings_now(ownerrepo, fingerprint(pre_settings))
    gh_api(f"repos/{ownerrepo}", method="PATCH", payload=prior_settings)
    post_settings = verify_settings_postimage(ownerrepo, prior_settings)
    post_ruleset = verify_ruleset_postimage(
        ownerrepo,
        expected_id=expected_ruleset_id,
        desired=expected_ruleset,
    )
    post_id = expected_ruleset_id
    state["rollback_phase"] = "complete"
    state["lifecycle"] = "rolled_back"
    state["rolled_back"] = True
    if task_created:
        state["target_stage"] = (
            "canary_rolled_back"
            if target_branch != default_branch
            else "default_rolled_back"
        )
    complete_rollback_proof(
        state,
        settings=post_settings,
        ruleset=post_ruleset,
    )
    finalize_state(
        state,
        operation="rollback",
        ruleset_id=post_id,
        settings=post_settings,
        ruleset=post_ruleset,
    )
    print("pr-automation rollback: original preimage restored; history ruleset untouched")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="repo-baseline.sh profile pr-automation")
    sub = parser.add_subparsers(dest="verb", required=True)
    for name in ("verify", "status"):
        command = sub.add_parser(name)
        command.add_argument("repo")
    for name in ("apply", "pause", "repair", "rollback"):
        command = sub.add_parser(name)
        command.add_argument("repo")
        command.add_argument("--dry-run", action="store_true")
    enforce = sub.add_parser("enforce")
    enforce.add_argument("repo")
    enforce.add_argument("--dry-run", action="store_true")
    target = enforce.add_mutually_exclusive_group()
    target.add_argument("--target-branch")
    target.add_argument("--retarget")
    enforce.add_argument("--canary-proof")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"verify", "status", "--help", "-h"}:
        print("REFUSED: retired controller mutation; historical inspection only", file=sys.stderr)
        return 1

    args = parse_args(argv)
    repo = resolve_repo(args.repo)
    if args.verb == "verify":
        return cmd_verify(repo)
    if args.verb == "apply":
        return cmd_apply(repo, dry_run=args.dry_run)
    if args.verb == "status":
        return cmd_status(repo)
    if args.verb == "enforce":
        return cmd_enforce(
            repo,
            dry_run=args.dry_run,
            target_branch=args.target_branch,
            retarget=args.retarget,
            canary_proof=args.canary_proof,
        )
    if args.verb == "pause":
        return cmd_pause(repo, dry_run=args.dry_run)
    if args.verb == "repair":
        return cmd_repair(repo, dry_run=args.dry_run)
    if args.verb == "rollback":
        return cmd_rollback(repo, dry_run=args.dry_run)
    raise ProfileError(f"unknown verb: {args.verb}")


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except ProfileError as exc:
        eprint(f"pr-automation: {exc}")
        raise SystemExit(1)
