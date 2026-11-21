"""Bind approved release records to GitHub's observed delivery evidence."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .scm import _fixture_github_cli, _github_slug, _origin_url, github_json
from .validators import read_repository_config


REVISION = re.compile(r"[0-9a-f]{40}")
PULL_REQUEST = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)")
DEV_REPOSITORY_ID = 1459458379
REVIEWER_BOT_ID = 299927791
ACTIONS_APP_ID = 15368
UNAVAILABLE = "release_delivery_unavailable"


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(UNAVAILABLE)
    return value


def observe_merged_delivery(repo: Path, pull_request: str, commit: str) -> dict[str, Any]:
    match = PULL_REQUEST.fullmatch(pull_request)
    if match is None or REVISION.fullmatch(commit) is None:
        raise ValueError("release_evidence_required")
    profile = read_repository_config(repo)
    if profile is None or profile["github_repository_id"] is None:
        raise ValueError("release_repository_identity_required")
    repository_id = profile["github_repository_id"]
    origin = _github_slug(_origin_url(repo))
    if match[1].casefold() != origin.casefold():
        raise ValueError("release_delivery_repository_mismatch")
    cli = _fixture_github_cli(repo)
    prefix = f"repos/{quote(origin, safe='/')}"

    def read(suffix: str = "") -> object:
        return github_json(prefix + suffix, github_cli=cli, unavailable=UNAVAILABLE)

    identity = _object(read())
    name, branch = identity.get("full_name"), identity.get("default_branch")
    if (identity.get("id") != repository_id or not isinstance(name, str)
            or name.casefold() != origin.casefold() or not isinstance(branch, str) or not branch):
        raise ValueError("release_delivery_repository_mismatch")
    number = int(match[2])
    pull = _object(read(f"/pulls/{number}"))
    base, head = _object(pull.get("base")), _object(pull.get("head")).get("sha")
    if (pull.get("number") != number or _object(base.get("repo")).get("id") != repository_id
            or base.get("ref") != branch):
        raise ValueError("release_delivery_repository_mismatch")
    if (pull.get("merged") is not True or pull.get("state") != "closed" or not pull.get("merged_at")
            or pull.get("merge_commit_sha") != commit or not isinstance(head, str)
            or REVISION.fullmatch(head) is None):
        raise ValueError("release_delivery_merge_unverified")
    branch_path = quote(branch, safe="")
    tip = _object(_object(read(f"/branches/{branch_path}")).get("commit")).get("sha")
    if not isinstance(tip, str) or REVISION.fullmatch(tip) is None:
        raise ValueError(UNAVAILABLE)
    if tip != commit:
        comparison = _object(read(f"/compare/{commit}...{tip}"))
        if comparison.get("status") != "ahead" or _object(comparison.get("merge_base_commit")).get("sha") != commit:
            raise ValueError("release_delivery_merge_unverified")

    require_app = repository_id == DEV_REPOSITORY_ID
    if name.casefold().startswith("kleinperkins/") and not require_app:
        rules = _rows(read(f"/rules/branches/{branch_path}"))
        require_app = any(
            check.get("context") == "ci-required" and check.get("integration_id") == ACTIONS_APP_ID
            for rule in rules if rule.get("type") == "required_status_checks"
            for check in _rows(_object(rule.get("parameters")).get("required_status_checks"))
        )
    reviewer = None
    check_id = None
    if require_app:
        reviews = _rows(read(f"/pulls/{number}/reviews?per_page=100"))
        if (_object(pull.get("merged_by")).get("id") != REVIEWER_BOT_ID
                or not any(_object(review.get("user")).get("id") == REVIEWER_BOT_ID
                           and review.get("commit_id") == head and review.get("state") == "APPROVED"
                           for review in reviews)):
            raise ValueError("release_delivery_app_unverified")
        reviewer = REVIEWER_BOT_ID
        checks = _rows(_object(read(f"/commits/{head}/check-runs?check_name=ci-required&filter=latest"))
                       .get("check_runs"))
        required = [row for row in checks if row.get("name") == "ci-required" and row.get("head_sha") == head
                    and _object(row.get("app")).get("id") == ACTIONS_APP_ID]
        if (len(required) != 1 or required[0].get("status") != "completed"
                or required[0].get("conclusion") != "success" or type(required[0].get("id")) is not int):
            raise ValueError("release_delivery_ci_unverified")
        check_id = required[0]["id"]
    return {
        "repository_id": repository_id, "canonical_url": f"https://github.com/{name}/pull/{number}",
        "branch": branch, "merge_commit": commit, "reviewed_commit": head,
        "reviewer_bot_id": reviewer, "ci_check_id": check_id,
    }
