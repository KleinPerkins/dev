"""Closed JSON renderers for repository and fleet governance views."""

from __future__ import annotations

from typing import Any

from .inventory import LogicalRepository


def render_logical_repository(repository: LogicalRepository) -> dict[str, Any]:
    return {
        "repository": repository.repository,
        "repository_key": repository.repository_key,
        "repository_id": repository.repository_id,
        "designated_path": repository.designated_path,
        "available": repository.available,
        "reason": repository.reason,
        "owner": repository.owner,
        "next_action": repository.next_action,
        "mutation_eligible": repository.mutation_eligible,
        "docs_only": repository.docs_only,
        "checkout_count": len(repository.observations),
        "source_revision": repository.source_revision,
        "observed_at": repository.observed_at,
    }
