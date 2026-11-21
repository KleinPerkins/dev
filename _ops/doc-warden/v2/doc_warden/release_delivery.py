"""Bind approved release records to GitHub's observed delivery evidence."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .canonical import canonical_json, digest_ref
from .review_admission import verify_dev_review
from .scm import _fixture_github_cli, _github_slug, _origin_url, github_bytes, github_json
from .validators import read_repository_config


REVISION = re.compile(r"[0-9a-f]{40}")
PULL_REQUEST = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/([1-9][0-9]*)")
DEV_REPOSITORY_ID = 1459458379
REVIEWER_BOT_ID = 299927791
REVIEWER_APP = "chaos-scheduler-automerge"
ACTIONS_APP_ID = 15368
UNAVAILABLE = "release_delivery_unavailable"
MERGE_TIMELINE = """query ($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    databaseId
    pullRequest(number: $number) {
      id merged mergeCommit { oid }
      autoMergeRequest { enabledBy { __typename login ... on Bot { databaseId } } }
      timelineItems(first: 100, itemTypes: [AUTO_MERGE_ENABLED_EVENT, MERGED_EVENT]) {
        pageInfo { hasNextPage }
        nodes {
          __typename
          ... on AutoMergeEnabledEvent { actor { __typename login ... on Bot { databaseId } } }
          ... on MergedEvent { commit { oid } actor { __typename login ... on Bot { databaseId } } }
        }
      }
    }
  }
}"""


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(UNAVAILABLE)
    return value


def _app_timeline(cli: str, name: str, repository_id: int, pull: dict[str, Any], commit: str) -> tuple[str, bool]:
    def is_app(actor: object) -> bool:
        return _object(actor) == {"__typename": "Bot", "login": REVIEWER_APP, "databaseId": REVIEWER_BOT_ID}

    auto_merge = pull.get("auto_merge")
    enabled_by = _object(_object(auto_merge).get("enabled_by"))
    if "auto_merge" not in pull or (auto_merge is not None and (
        _object(auto_merge).get("merge_method") != "squash"
        or enabled_by.get("id") != REVIEWER_BOT_ID or enabled_by.get("type") != "Bot"
        or enabled_by.get("login") != REVIEWER_APP + "[bot]"
    )):
        raise ValueError("release_delivery_automation_unverified")
    owner, repository_name = name.split("/", 1)
    response = _object(github_json("graphql", github_cli=cli, unavailable=UNAVAILABLE, parameters=(
        "-f", f"query={MERGE_TIMELINE}", "-F", f"owner={owner}", "-F", f"name={repository_name}",
        "-F", f"number={pull['number']}",
    )))
    repository = _object(_object(response.get("data")).get("repository"))
    candidate = _object(repository.get("pullRequest"))
    if (response.get("errors") or repository.get("databaseId") != repository_id
            or not pull.get("node_id") or candidate.get("id") != pull["node_id"]
            or candidate.get("merged") is not True or _object(candidate.get("mergeCommit")).get("oid") != commit
            or "autoMergeRequest" not in candidate):
        raise ValueError("release_delivery_automation_unverified")
    current = candidate["autoMergeRequest"]
    if current is not None and not is_app(_object(current).get("enabledBy")):
        raise ValueError("release_delivery_automation_unverified")
    timeline = _object(candidate.get("timelineItems"))
    events = _rows(timeline.get("nodes"))
    if (_object(timeline.get("pageInfo")).get("hasNextPage") is not False
            or any(event.get("__typename") not in {"AutoMergeEnabledEvent", "MergedEvent"}
                   or not is_app(event.get("actor")) for event in events)):
        raise ValueError("release_delivery_automation_unverified")
    merges = [event for event in events if event["__typename"] == "MergedEvent"]
    if len(merges) != 1 or _object(merges[0].get("commit")).get("oid") != commit:
        raise ValueError("release_delivery_automation_unverified")
    enabled_event = any(event["__typename"] == "AutoMergeEnabledEvent" for event in events)
    return digest_ref(canonical_json({"events": events, "active_request": current})), enabled_event


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

    def read_log(suffix: str) -> bytes:
        return github_bytes(prefix + suffix, github_cli=cli, unavailable=UNAVAILABLE,
                            parameters=("--allow-escape-sequences",))

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
    automation = None
    admitted_review = None
    if require_app:
        if repository_id != DEV_REPOSITORY_ID:
            raise ValueError("release_delivery_review_provider_unavailable")
        reviews = _rows(read(f"/pulls/{number}/reviews?per_page=100"))
        approval = [review for review in reviews if _object(review.get("user")).get("id") == REVIEWER_BOT_ID
                    and review.get("commit_id") == head]
        if (_object(pull.get("merged_by")).get("id") != REVIEWER_BOT_ID or len(reviews) >= 100
                or len(approval) != 1 or approval[0].get("state") != "APPROVED"):
            raise ValueError("release_delivery_app_unverified")
        reviewer = REVIEWER_BOT_ID
        automation, armed = _app_timeline(cli, name, repository_id, pull, commit)
        checks = _rows(_object(read(f"/commits/{head}/check-runs?check_name=ci-required&filter=latest"))
                       .get("check_runs"))
        required = [row for row in checks if row.get("name") == "ci-required" and row.get("head_sha") == head
                    and _object(row.get("app")).get("id") == ACTIONS_APP_ID]
        if (len(required) != 1 or required[0].get("status") != "completed"
                or required[0].get("conclusion") != "success" or type(required[0].get("id")) is not int):
            raise ValueError("release_delivery_ci_unverified")
        check_id = required[0]["id"]
        base_revision = base.get("sha")
        if not isinstance(base_revision, str) or REVISION.fullmatch(base_revision) is None:
            raise ValueError("release_delivery_review_unverified")
        admitted_review = verify_dev_review(read, read_log, pull, approval[0], commit=commit, head=head,
                                            base=base_revision, armed=armed)
    return {
        "repository_id": repository_id, "canonical_url": f"https://github.com/{name}/pull/{number}",
        "branch": branch, "merge_commit": commit, "reviewed_commit": head,
        "reviewer_bot_id": reviewer, "ci_check_id": check_id,
        "automation_digest": automation, "review_receipt_digest": admitted_review,
    }
