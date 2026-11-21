"""Recheck the exact Dev originating-account admission at App approval time."""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .canonical import digest_ref


def _dev_reviewer():
    source = Path(__file__).resolve().parents[4] / "scripts/reviewer_app.py"
    spec = importlib.util.spec_from_file_location("doc_warden_dev_reviewer", source)
    if spec is None or spec.loader is None:
        raise ValueError("release_delivery_review_unverified")
    reviewer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reviewer)
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
        merge_base = reviewer.bounded_merge_base(command, base, head)
        diff = command("-c", "color.ui=false", "diff", "--no-ext-diff", "--no-textconv", "--binary",
                       f"{base}...{head}", "--")
        return merge_base, reviewer.digest(diff)


def verify_dev_review(
    read: Callable[[str], object], pull: dict[str, Any], approval: dict[str, Any], *,
    commit: str, head: str, base: str,
) -> str:
    try:
        reviewer = _dev_reviewer()
    except (ImportError, OSError) as exc:
        raise ValueError("release_delivery_review_unverified") from exc

    try:
        approved_at = reviewer.timestamp(approval["submitted_at"])
        if approved_at > reviewer.timestamp(pull["merged_at"]):
            raise ValueError("release_delivery_review_unverified")
        merged = read(f"/git/commits/{commit}")
        if [parent["sha"] for parent in merged["parents"]] != [base]:
            raise ValueError("release_delivery_review_unverified")

        document = read(f"/contents/.github/review-enrollments.json?ref={base}")
        if document["encoding"] != "base64":
            raise ValueError("release_delivery_review_unverified")
        policy_bytes = base64.b64decode("".join(document["content"].split()), validate=True)
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
        return digest_ref(reviewer.canonical({"origin": origin, "review": receipt}))
    except (reviewer.Rejected, ValueError, TypeError, AttributeError, KeyError, OSError,
            subprocess.SubprocessError) as exc:
        raise ValueError("release_delivery_review_unverified") from exc
