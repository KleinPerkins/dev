"""Logical fleet inventory derived from source-tracked repository authority."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .canonical import parse_json_object


@dataclass(frozen=True)
class CheckoutObservation:
    repository: str
    repository_id: int | None
    path: str | None
    available: bool
    reason: str | None
    owner: str
    next_action: str
    docs_only: bool = False
    repository_key: str | None = None


@dataclass(frozen=True)
class LogicalRepository:
    repository: str
    repository_id: int | None
    designated_path: str | None
    observations: tuple[CheckoutObservation, ...]
    available: bool
    reason: str | None
    owner: str
    next_action: str
    mutation_eligible: bool
    docs_only: bool
    repository_key: str | None = None


def deduplicate_observations(
    observations: Iterable[CheckoutObservation],
) -> list[LogicalRepository]:
    grouped: dict[tuple[str, str], list[CheckoutObservation]] = {}
    for observation in observations:
        key = (
            ("local", observation.repository_key)
            if observation.repository_key is not None
            else (
                ("id", str(observation.repository_id))
                if observation.repository_id is not None
                else ("repo", observation.repository.lower())
            )
        )
        grouped.setdefault(key, []).append(observation)
    logical: list[LogicalRepository] = []
    for rows in grouped.values():
        ordered = tuple(sorted(rows, key=lambda row: (not row.available, row.path or "")))
        current = next((row for row in ordered if row.available), ordered[0])
        docs_only = any(row.docs_only for row in ordered)
        conflict = len({row.repository.lower() for row in ordered}) > 1
        logical.append(
            LogicalRepository(
                repository=current.repository,
                repository_id=current.repository_id,
                designated_path=current.path if current.available else None,
                observations=ordered,
                available=any(row.available for row in ordered),
                reason=(
                    "identity_conflict"
                    if conflict
                    else (None if any(row.available for row in ordered) else current.reason)
                ),
                owner=current.owner,
                next_action=current.next_action,
                mutation_eligible=(
                    any(row.available for row in ordered) and not docs_only and not conflict
                ),
                docs_only=docs_only,
                repository_key=current.repository_key,
            )
        )
    return sorted(logical, key=lambda row: row.repository.lower())


def inventory_fleet(root: Path) -> list[LogicalRepository]:
    """Build the non-mutating fleet view from the committed runnerless catalog.

    Checkout availability is intentionally unknown in a linked worktree; no
    primary-tree or nested-repository path is guessed or traversed.
    """
    fleet_path = root / "_ops/baseline/profiles/pr-automation/v3/fleet.json"
    if not fleet_path.is_file():
        authority_root = Path(
            os.environ.get(
                "DOC_WARDEN_FLEET_ROOT",
                str(Path(__file__).resolve().parents[4]),
            )
        )
        fleet_path = authority_root / "_ops/baseline/profiles/pr-automation/v3/fleet.json"
    if not fleet_path.is_file():
        raise ValueError("fleet_authority_unavailable")
    fleet = parse_json_object(fleet_path.read_bytes())
    observed = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        check=False,
        capture_output=True,
        text=True,
    )
    dev_checkout = (
        observed.returncode == 0
        and observed.stdout.strip()
        in {
            "git@github.com:KleinPerkins/dev.git",
            "git@github.com:KleinPerkins/dev",
            "https://github.com/KleinPerkins/dev.git",
            "https://github.com/KleinPerkins/dev",
        }
    )
    observations = [
        CheckoutObservation(
            repository=target["repo"],
            repository_id=target["repository_id"],
            path=str(root) if target["repo"] == "KleinPerkins/dev" and dev_checkout else None,
            available=target["repo"] == "KleinPerkins/dev" and dev_checkout,
            reason=None
            if target["repo"] == "KleinPerkins/dev" and dev_checkout
            else "checkout_unavailable_from_selected_worktree",
            owner=target["repo"].split("/", 1)[0],
            next_action="inspect_current_checkout"
            if target["repo"] == "KleinPerkins/dev" and dev_checkout
            else "open_or_locate_checkout",
        )
        for target in fleet["targets"]
    ]
    observations.extend(
        CheckoutObservation(
            repository=row["repo"],
            repository_id=None,
            path=None,
            available=False,
            reason=row["reason"],
            owner=row["repo"].split("/", 1)[0],
            next_action="observe_only",
            docs_only=row["repo"] == "KleinPerkins/chaos-scheduler",
        )
        for row in fleet["excluded"]
    )
    return deduplicate_observations(observations)
