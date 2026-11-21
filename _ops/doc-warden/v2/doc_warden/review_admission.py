"""Recheck the exact Dev originating-account admission at App approval time."""

from __future__ import annotations

import base64
import json
import re
import subprocess
import tempfile
from types import ModuleType
from typing import Any, Callable

from .canonical import digest_ref


APP_SCRIPT_DIGEST = "sha256:73ec3d0ebe18e61bfa04bb1ecbdcc76792ecd043d914d25843241b17d5cde0ad"
APP_WORKFLOW_DIGEST = "sha256:5846f782da247434d452633762bb7bbb3faa59ca6c807521fda6a565063c2398"
APP_WORKFLOW_ID = 420920692
APP_WORKFLOW_PATH = ".github/workflows/reviewer-app.yml"
APP_SCRIPT_PATH = "scripts/reviewer_app.py"


def _dev_reviewer(content: bytes, workflow_base: str):
    # The caller supplies the protected public workflow's script from the
    # verified squash parent. This pin selects the supported helper version.
    if digest_ref(content) != APP_SCRIPT_DIGEST:
        raise ValueError("release_delivery_review_unverified")
    source = f"github.com/KleinPerkins/dev/{workflow_base}/{APP_SCRIPT_PATH}"
    reviewer = ModuleType("doc_warden_dev_reviewer")
    reviewer.__file__ = source
    exec(compile(content, source, "exec"), reviewer.__dict__)
    reviewer.REPOSITORY = "KleinPerkins/dev"
    return reviewer


def _public_dev_git_tuple(reviewer, head: str, base: str) -> tuple[str, str]:
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
                data = output.read(reviewer.MAX_DIFF + 1)
                if len(data) > reviewer.MAX_DIFF:
                    raise ValueError("release_delivery_review_unverified")
                return data

        command("init", "--bare", ".")
        command("fetch", "--no-tags", "--no-recurse-submodules", "--depth=256",
                "https://github.com/KleinPerkins/dev.git", base, head)
        common_history = command("merge-base", base, head, no_common_base_ok=True)
        # The App helper repeats the public fetch with progressively deeper history
        # when a shallow checkout cannot establish a common ancestor.
        merge_base = (common_history.decode("ascii").strip() if common_history is not None
                      else reviewer.bounded_merge_base(command, base, head))
        if len(merge_base) != 40 or any(character not in "0123456789abcdef" for character in merge_base):
            raise ValueError("release_delivery_review_unverified")
        diff = command("-c", "color.ui=false", "diff", "--no-ext-diff", "--no-textconv", "--binary",
                       f"{base}...{head}", "--")
        return merge_base, reviewer.digest(diff)


def _historical_source(read: Callable[[str], Any], name: str, base: str) -> bytes:
    document = read(f"/contents/{name}?ref={base}")
    if document["encoding"] != "base64":
        raise ValueError("release_delivery_review_unverified")
    return base64.b64decode("".join(document["content"].split()), validate=True)


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


def _dev_workflow_witness(reviewer, read: Callable[[str], Any], read_log: Callable[[str], bytes],
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
                or run.get("repository", {}).get("id") != reviewer.REPOSITORY_ID
                or run.get("head_repository", {}).get("id") != reviewer.REPOSITORY_ID
                or not reviewer.timestamp(run["created_at"]) <= approved_at <= reviewer.timestamp(run["updated_at"])):
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
                    or not reviewer.timestamp(job["started_at"]) <= approved_at <= reviewer.timestamp(job["completed_at"])):
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
    pull: dict[str, Any], approval: dict[str, Any], *, commit: str, head: str, base: str, armed: bool,
) -> str:
    try:
        # observe_merged_delivery has already proved this exact merge reached
        # the live default branch. Its sole parent is the workflow's trusted
        # base. Only read protected helper bytes from that authenticated Git
        # object, never from the PR head or the mutable local checkout.
        merged = read(f"/git/commits/{commit}")
        if merged["sha"] != commit or [parent["sha"] for parent in merged["parents"]] != [base]:
            raise ValueError("release_delivery_review_unverified")
        reviewer = _dev_reviewer(_historical_source(read, APP_SCRIPT_PATH, base), base)
    except (ImportError, SyntaxError, ValueError, TypeError, AttributeError, KeyError, OSError) as exc:
        raise ValueError("release_delivery_review_unverified") from exc

    try:
        approved_at = reviewer.timestamp(approval["submitted_at"])
        if approved_at > reviewer.timestamp(pull["merged_at"]):
            raise ValueError("release_delivery_review_unverified")
        policy_bytes = _historical_source(read, ".github/review-enrollments.json", base)
        policy = json.loads(policy_bytes)
        if (policy["schema"] != "g1-review-enrollments/v1" or policy["enabled"] is not True
                or policy["repository_id"] != reviewer.REPOSITORY_ID
                or reviewer.REPOSITORY not in policy["repository_names"]):
            raise ValueError("release_delivery_review_unverified")
        comments = read(f"/issues/{pull['number']}/comments?per_page=100")
        if not isinstance(comments, list) or len(comments) >= 100:
            raise ValueError("release_delivery_review_unverified")
        comments = [row for row in comments if isinstance(row.get("body"), str)
                    and row["body"].startswith((reviewer.ORIGIN_MARKER, reviewer.MARKER))
                    and reviewer.timestamp(row["created_at"]) <= approved_at]
        policy_hash = reviewer.digest(policy_bytes)
        origin = reviewer.choose_origin(comments, policy, pull, approved_at)
        merge_base, diff_hash = _public_dev_git_tuple(reviewer, head, base)
        current = {"repository": reviewer.REPOSITORY, "repository_id": reviewer.REPOSITORY_ID,
                   "head_sha": head, "base_sha": base, "merge_base_sha": merge_base,
                   "diff_sha256": diff_hash, "policy_sha256": policy_hash}
        receipt = reviewer.choose_receipt(comments, policy, current, policy_hash, approved_at, origin)
        run, job = _dev_workflow_witness(reviewer, read, read_log, current, pull=pull, commit=commit,
                                         approved_at=approved_at, armed=armed)
        return digest_ref(reviewer.canonical({"origin": origin, "review": receipt, "run_id": run, "job_id": job}))
    except (reviewer.Rejected, ValueError, TypeError, AttributeError, KeyError, OSError,
            subprocess.SubprocessError) as exc:
        raise ValueError("release_delivery_review_unverified") from exc
