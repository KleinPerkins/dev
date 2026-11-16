"""Canonical repository roadmap views and preview-bound mutations."""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import _bindings
from .canonical import canonical_json, parse_json_object
from .transactions import MutationAction, MutationRequest, TransactionPreview, preview_transaction
from .validators import require_valid


BEGIN = "<!-- doc-warden:roadmap-json:begin -->\n"
END = "<!-- doc-warden:roadmap-json:end -->\n"

_DEFECT_ROADMAP_STATUS = {
    "reported": "backlog",
    "triaged": "backlog",
    "investigating": "backlog",
    "ready": "ready",
    "fixing": "active",
    "verifying": "verifying",
    "resolved": "complete",
    "duplicate": "cancelled",
    "waived": "cancelled",
    "wont_fix": "cancelled",
    "recurred": "backlog",
    "superseded": "superseded",
}


@dataclass(frozen=True)
class RoadmapView:
    repository_key: str
    source_revision: str
    items: tuple[dict[str, Any], ...]
    projection: bool = False


def _head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()


def _observed_at(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), "show", "-s", "--format=%cI", "HEAD"], text=True
    ).strip()


def new_roadmap_item(
    *,
    repository_key: str,
    outcome: str,
    kind: str = "product",
    priority: str = "P2",
    sequence: int = 1,
    item_id: str | None = None,
    source_revision: str = "no-head",
    observed_at: str = "1970-01-01T00:00:00+00:00",
) -> dict[str, Any]:
    item = {
        "schema": "doc-warden/roadmap-item/v2",
        "id": item_id or f"ROAD-{repository_key}-{uuid.uuid4()}",
        "kind": kind,
        "outcome": outcome,
        "priority": priority,
        "sequence": sequence,
        "wave": None,
        "status": "backlog",
        "dependencies": {"planned": [], "observed": []},
        "required_artifacts": [],
        "active_versions": {},
        "active_plan": None,
        "blockers": [],
        "next_action": "classify_rigor",
        "completion_evidence": [],
        "freshness": {"source_revision": source_revision, "observed_at": observed_at},
    }
    require_valid("roadmap", item)
    return item


def new_defect_roadmap_item(
    *,
    repository_key: str,
    defect_id: str,
    outcome: str,
    priority: str,
    source_revision: str,
    observed_at: str,
) -> dict[str, Any]:
    """Create the canonical backlog row linked to one defect record."""

    item = new_roadmap_item(
        repository_key=repository_key,
        item_id=f"ROAD-{defect_id}",
        outcome=outcome,
        kind="defect",
        priority=priority,
        source_revision=source_revision,
        observed_at=observed_at,
    )
    item["required_artifacts"] = [defect_id]
    item["active_versions"] = {defect_id: 1}
    item["next_action"] = f"triage:{defect_id}"
    require_valid("roadmap", item)
    return item


def update_defect_roadmap_item(
    items: list[dict[str, Any]],
    *,
    defect_id: str,
    record_version: int,
    lifecycle: str,
    next_action: str,
    source_revision: str,
    observed_at: str,
    completion_evidence: list[str] | None = None,
    prd_seed_id: str | None = None,
) -> list[dict[str, Any]]:
    """Regenerate one defect row without changing unrelated roadmap ordering."""

    matches = [
        item
        for item in items
        if item.get("id") == f"ROAD-{defect_id}"
        or defect_id in item.get("active_versions", {})
    ]
    if len(matches) != 1:
        raise ValueError("defect_roadmap_item_not_found")
    item = matches[0]
    if lifecycle not in _DEFECT_ROADMAP_STATUS:
        raise ValueError("defect_lifecycle_invalid")
    item["active_versions"][defect_id] = record_version
    item["status"] = _DEFECT_ROADMAP_STATUS[lifecycle]
    item["next_action"] = next_action
    item["freshness"] = {
        "source_revision": source_revision,
        "observed_at": observed_at,
    }
    if completion_evidence is not None:
        item["completion_evidence"] = list(completion_evidence)
    if prd_seed_id is not None:
        item["kind"] = "product"
        item["status"] = "backlog"
        item["required_artifacts"] = [defect_id, "prd"]
        item["next_action"] = f"draft_prd:{prd_seed_id}"
        item["blockers"] = [f"approval_required:{prd_seed_id}"]
    require_valid("roadmap", item)
    return items


def render_roadmap(items: list[dict[str, Any]]) -> bytes:
    for item in items:
        require_valid("roadmap", item)
    return (
        "# Roadmap\n\n"
        + BEGIN
        + canonical_json({"schema": "doc-warden/roadmap/v2", "items": items}).decode("utf-8")
        + END
    ).encode("utf-8")


def parse_roadmap(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    text = path.read_text()
    if text.count(BEGIN) != 1 or text.count(END) != 1:
        raise ValueError("roadmap markers invalid")
    payload = text.split(BEGIN, 1)[1].split(END, 1)[0]
    parsed = parse_json_object(payload.encode("utf-8"))
    if parsed.get("schema") != "doc-warden/roadmap/v2" or not isinstance(
        parsed.get("items"), list
    ):
        raise ValueError("roadmap payload invalid")
    for item in parsed["items"]:
        require_valid("roadmap", item)
    return parsed["items"]


def roadmap_dependency_edges(
    items: list[dict[str, Any]],
    authority: str,
) -> tuple[tuple[str, str], ...]:
    """Return one authority's edges without merging planned and observed state."""

    if authority not in {"planned", "observed"}:
        raise ValueError("roadmap_dependency_authority_invalid")
    return tuple(
        sorted(
            (item["id"], target)
            for item in items
            for target in item["dependencies"][authority]
        )
    )


def roadmap_view(repo: Path, repository_key: str, *, projection: bool = False) -> RoadmapView:
    repo = repo.resolve(strict=True)
    relative = ".planning/generated/fleet-roadmap.md" if projection else ".planning/ROADMAP.md"
    return RoadmapView(
        repository_key=repository_key,
        source_revision=_head(repo),
        items=tuple(parse_roadmap(repo / relative)),
        projection=projection,
    )


def _ensure_acyclic(items: list[dict[str, Any]]) -> None:
    graph = {item["id"]: set(item["dependencies"]["planned"]) for item in items}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            raise ValueError("roadmap dependency cycle")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph.get(node, set()):
            if dependency in graph:
                visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)


def _preview_items(
    repo: Path,
    repository_key: str,
    items: list[dict[str, Any]],
    operation_id: str | None,
) -> TransactionPreview:
    _ensure_acyclic(items)
    return preview_transaction(
        MutationRequest(
            repo=repo,
            repository_key=repository_key,
            transition="roadmap_update",
            actions=(MutationAction(".planning/ROADMAP.md", render_roadmap(items)),),
            bindings=_bindings(repo),
            operation_id=operation_id,
            require_write_enabled=True,
        )
    )


def roadmap_prioritize(
    repo: Path,
    repository_key: str,
    item_id: str,
    priority: str,
    *,
    operation_id: str | None = None,
    projection: bool = False,
) -> TransactionPreview:
    if projection:
        raise ValueError("fleet_projection_read_only")
    if priority not in {"P0", "P1", "P2", "P3"}:
        raise ValueError("invalid priority")
    items = parse_roadmap(repo / ".planning/ROADMAP.md")
    matches = [item for item in items if item["id"] == item_id]
    if len(matches) != 1:
        raise ValueError("roadmap item not found")
    matches[0]["priority"] = priority
    matches[0]["freshness"] = {"source_revision": _head(repo), "observed_at": _observed_at(repo)}
    return _preview_items(repo, repository_key, items, operation_id)


def roadmap_sequence(
    repo: Path,
    repository_key: str,
    item_id: str,
    *,
    before: str | None = None,
    after: str | None = None,
    operation_id: str | None = None,
    projection: bool = False,
) -> TransactionPreview:
    if projection:
        raise ValueError("fleet_projection_read_only")
    if (before is None) == (after is None):
        raise ValueError("exactly one sequence relation required")
    target = before or after
    if target == item_id:
        raise ValueError("roadmap sequence cycle")
    items = parse_roadmap(repo / ".planning/ROADMAP.md")
    by_id = {item["id"]: item for item in items}
    if item_id not in by_id or target not in by_id:
        raise ValueError("roadmap item not found")
    ordered = sorted(items, key=lambda item: (item["sequence"], item["id"]))
    moving = by_id[item_id]
    ordered.remove(moving)
    target_index = ordered.index(by_id[target])
    ordered.insert(target_index if before else target_index + 1, moving)
    for index, item in enumerate(ordered, 1):
        item["sequence"] = index
        item["freshness"] = {"source_revision": _head(repo), "observed_at": _observed_at(repo)}
    return _preview_items(repo, repository_key, ordered, operation_id)
