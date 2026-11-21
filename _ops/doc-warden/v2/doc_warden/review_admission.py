"""Recheck the exact Dev originating-account admission at App approval time."""

from __future__ import annotations

import base64
import json
import re
import subprocess
import tempfile
from datetime import datetime
from typing import Any, Callable

from .canonical import canonical_json, digest_ref, parse_json_object


APP_SCRIPT_DIGEST = "sha256:73ec3d0ebe18e61bfa04bb1ecbdcc76792ecd043d914d25843241b17d5cde0ad"
APP_WORKFLOW_DIGEST = "sha256:5846f782da247434d452633762bb7bbb3faa59ca6c807521fda6a565063c2398"
APP_WORKFLOW_ID = 420920692
APP_WORKFLOW_PATH = ".github/workflows/reviewer-app.yml"
APP_SCRIPT_PATH = "scripts/reviewer_app.py"
REPOSITORY = "KleinPerkins/dev"
REPOSITORY_ID = 1459458379
OWNER_ID = 49759187
MAX_DIFF = 5_000_000
ORIGIN_MARKER = "<!-- g1-pr-origin:v1 -->\n"
REVIEW_MARKER = "<!-- g1-review-receipt:v1 -->\n"


def _timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("release_delivery_review_unverified")
    return result


def _public_dev_git_tuple(head: str, base: str) -> tuple[str, str]:
    # Work only with public Git objects and the same tuple rules as the App.
    with tempfile.TemporaryDirectory(prefix="doc-warden-delivery-") as work:
        environment = {
            "PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C", "HOME": work,
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_ATTR_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
        }

        def command(*arguments, no_common_base_ok=False):
            with tempfile.TemporaryFile() as output:
                result = subprocess.run(
                    ["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=",
                     "-c", "protocol.file.allow=never", "-c", "core.attributesFile=/dev/null", *arguments],
                    cwd=work, env=environment, stdout=output, stderr=subprocess.DEVNULL,
                    timeout=60, check=False,
                )
                if no_common_base_ok and result.returncode == 1:
                    return None
                if result.returncode != 0:
                    raise ValueError("release_delivery_review_unverified")
                output.seek(0)
                data = output.read(MAX_DIFF + 1)
                if len(data) > MAX_DIFF:
                    raise ValueError("release_delivery_review_unverified")
                return data

        command("init", "--bare", ".")
        for depth in (256, 512, 1024, 2048, 4096):
            command("fetch", "--no-tags", "--no-recurse-submodules", f"--depth={depth}",
                    f"https://github.com/{REPOSITORY}.git", base, head)
            common_history = command("merge-base", base, head, no_common_base_ok=True)
            if common_history is not None:
                break
        else:
            raise ValueError("release_delivery_review_unverified")
        merge_base = common_history.decode("ascii").strip()
        if len(merge_base) != 40 or any(character not in "0123456789abcdef" for character in merge_base):
            raise ValueError("release_delivery_review_unverified")
        diff = command("-c", "color.ui=false", "diff", "--no-ext-diff", "--no-textconv", "--binary",
                       f"{base}...{head}", "--")
        return merge_base, digest_ref(diff).removeprefix("sha256:")


def _historical_source(read: Callable[[str], Any], name: str, base: str) -> bytes:
    document = read(f"/contents/{name}?ref={base}")
    if document["encoding"] != "base64":
        raise ValueError("release_delivery_review_unverified")
    return base64.b64decode("".join(document["content"].split()), validate=True)


def _published_review(read: Callable[[str], Any], pull: dict[str, Any], current: dict[str, Any],
                      approved_at: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind the public receipts to the tuple accepted by the protected workflow."""
    comments = read(f"/issues/{pull['number']}/comments?per_page=100")
    if not isinstance(comments, list) or len(comments) >= 100:
        raise ValueError("release_delivery_review_unverified")
    records: dict[str, list[tuple[int, dict[str, Any]]]] = {ORIGIN_MARKER: [], REVIEW_MARKER: []}
    for comment in comments:
        body, sender = comment.get("body"), comment.get("user", {})
        if not isinstance(body, str) or sender.get("id") != OWNER_ID or sender.get("type") != "User":
            continue
        marker = next((value for value in records if body.startswith(value)), None)
        if marker is None or _timestamp(comment["created_at"]) > approved_at:
            continue
        if (comment["created_at"] != comment["updated_at"] or type(comment["id"]) is not int
                or len(body.encode("utf-8")) > 60_000):
            raise ValueError("release_delivery_review_unverified")
        records[marker].append((comment["id"], parse_json_object(body.removeprefix(marker))))
    if len(records[ORIGIN_MARKER]) != 1 or not records[REVIEW_MARKER]:
        raise ValueError("release_delivery_review_unverified")
    origin = records[ORIGIN_MARKER][0][1]
    _, receipt = max(records[REVIEW_MARKER], key=lambda row: row[0])
    origin_id = origin["origin_account"]
    if (origin["schema"] != "g1-pr-origin/v1" or origin["repository"] != REPOSITORY
            or origin["repository_id"] != REPOSITORY_ID or origin["pull_request"] != pull["number"]
            or origin["pull_request_node_id"] != pull["node_id"] or origin["github_user_id"] != OWNER_ID
            or receipt["schema"] != "g1-local-review/v1" or receipt["tuple"] != (current | {"origin_account": origin_id})
            or receipt["reviewer_origin_account"] != origin_id
            or receipt["reviewer_enrollment_id"] != origin["creator_enrollment_id"]
            or receipt["review"]["verdict"] != "pass" or receipt["review"]["coverage"] != "complete"
            or receipt["review"]["findings"] != [] or receipt["review"]["unresolved_findings"] != []):
        raise ValueError("release_delivery_review_unverified")
    return origin, receipt


def _job_proves_delivery(log: bytes, current: dict[str, Any], *, number: int, commit: str, armed: bool) -> bool:
    targets = []
    qualified = []
    outcomes = []
    for line in log.splitlines():
        _, _, message = re.sub(rb"\x1b\[[0-9;]*m", b"", line).partition(b" ")
        message = message.strip()
        if message.startswith(b"TARGET_PR: "):
            targets.append(message.removeprefix(b"TARGET_PR: "))
        elif message.startswith(b"{"):
            try:
                payload = json.loads(message)
            except (UnicodeError, json.JSONDecodeError):
                continue
            if payload.get("status") == "qualified-read-only":
                qualified.append(payload)
            elif payload.get("status") in {"merged", "armed"}:
                outcomes.append(payload)
    if (targets != [str(number).encode("ascii")] * 2 or len(qualified) != 1 or len(outcomes) != 1
            or qualified[0].get("mutated") is not False or qualified[0].get("tuple") != current):
        return False
    result = outcomes[0]
    if result.get("head_sha") != current["head_sha"]:
        return False
    # The protected workflow can merge directly. An enable event is required
    # only when its write step reports that it armed GitHub native auto-merge.
    if result["status"] == "armed":
        return armed and result.get("merged") is False
    return (result.get("merged") is True and result.get("base_sha") == current["base_sha"]
            and result.get("merge_sha") == commit)


def _dev_workflow_witness(read: Callable[[str], Any], read_log: Callable[[str], bytes],
                          current: dict[str, Any], *, pull: dict[str, Any], commit: str,
                          approved_at, armed: bool) -> tuple[int, int]:
    base = current["base_sha"]
    workflow = read(f"/actions/workflows/{APP_WORKFLOW_ID}")
    if (workflow.get("id") != APP_WORKFLOW_ID or workflow.get("path") != APP_WORKFLOW_PATH
            or digest_ref(_historical_source(read, APP_WORKFLOW_PATH, base)) != APP_WORKFLOW_DIGEST):
        raise ValueError("release_delivery_review_unverified")
    listing = read(f"/actions/workflows/{APP_WORKFLOW_ID}/runs?head_sha={base}&branch=main&per_page=100")
    rows = listing["workflow_runs"]
    if not isinstance(rows, list) or listing["total_count"] != len(rows):
        raise ValueError("release_delivery_review_unverified")
    matches = []
    for run in rows:
        if (run.get("workflow_id") != APP_WORKFLOW_ID or run.get("path") != APP_WORKFLOW_PATH
                or run.get("head_sha") != base or run.get("head_branch") != "main"
                or run.get("event") not in {"issue_comment", "workflow_run"}
                or run.get("repository", {}).get("id") != REPOSITORY_ID
                or run.get("head_repository", {}).get("id") != REPOSITORY_ID
                or not _timestamp(run["created_at"]) <= approved_at <= _timestamp(run["updated_at"])):
            continue
        run_id = run["id"]
        if type(run_id) is not int or run_id <= 0:
            raise ValueError("release_delivery_review_unverified")
        jobs = read(f"/actions/runs/{run_id}/jobs?filter=all&per_page=100")
        if not isinstance(jobs["jobs"], list) or jobs["total_count"] != len(jobs["jobs"]):
            raise ValueError("release_delivery_review_unverified")
        for job in jobs["jobs"]:
            if (job.get("run_id") != run_id or job.get("head_sha") != base
                    or job.get("name") != "admit" or job.get("workflow_name") != "Reviewer App"
                    or job.get("status") != "completed" or job.get("conclusion") != "success"
                    or not _timestamp(job["started_at"]) <= approved_at <= _timestamp(job["completed_at"])):
                continue
            successful = {step["name"] for step in job["steps"] if step.get("conclusion") == "success"}
            if not {"Qualify current receipt, CI, controls and trusted source without writes",
                    "Approve exact head and request native squash through existing App"} <= successful:
                continue
            job_id = job["id"]
            if type(job_id) is not int or job_id <= 0:
                raise ValueError("release_delivery_review_unverified")
            if _job_proves_delivery(read_log(f"/actions/jobs/{job_id}/logs"), current,
                                    number=pull["number"], commit=commit, armed=armed):
                matches.append((run_id, job_id))
    if len(matches) != 1:
        raise ValueError("release_delivery_review_unverified")
    return matches[0]


def verify_dev_review(
    read: Callable[[str], Any], read_log: Callable[[str], bytes],
    pull: dict[str, Any], approval: dict[str, Any], *, commit: str, head: str, armed: bool,
) -> str:
    try:
        # observe_merged_delivery has already proved this exact merge reached
        # the live default branch. Its sole parent is the workflow's trusted
        # base. Verify the protected script as data. Its authenticated job
        # already evaluated the full enrollment and independent receipt rules.
        merged = read(f"/git/commits/{commit}")
        parents = [parent["sha"] for parent in merged["parents"]]
        if merged["sha"] != commit or len(parents) != 1 or re.fullmatch(r"[0-9a-f]{40}", parents[0]) is None:
            raise ValueError("release_delivery_review_unverified")
        base = parents[0]
        if digest_ref(_historical_source(read, APP_SCRIPT_PATH, base)) != APP_SCRIPT_DIGEST:
            raise ValueError("release_delivery_review_unverified")
        approved_at = _timestamp(approval["submitted_at"])
        if approved_at > _timestamp(pull["merged_at"]):
            raise ValueError("release_delivery_review_unverified")
        policy_bytes = _historical_source(read, ".github/review-enrollments.json", base)
        policy = parse_json_object(policy_bytes)
        if (policy["schema"] != "g1-review-enrollments/v1" or policy["enabled"] is not True
                or policy["repository_id"] != REPOSITORY_ID or REPOSITORY not in policy["repository_names"]):
            raise ValueError("release_delivery_review_unverified")
        merge_base, diff_hash = _public_dev_git_tuple(head, base)
        current = {"repository": REPOSITORY, "repository_id": REPOSITORY_ID,
                   "head_sha": head, "base_sha": base, "merge_base_sha": merge_base,
                   "diff_sha256": diff_hash, "policy_sha256": digest_ref(policy_bytes).removeprefix("sha256:")}
        origin, receipt = _published_review(read, pull, current, approved_at)
        run, job = _dev_workflow_witness(read, read_log, current, pull=pull, commit=commit,
                                         approved_at=approved_at, armed=armed)
        return digest_ref(canonical_json({"origin": origin, "review": receipt, "run_id": run, "job_id": job}))
    except (ValueError, TypeError, AttributeError, KeyError, OSError, subprocess.SubprocessError) as exc:
        raise ValueError("release_delivery_review_unverified") from exc
