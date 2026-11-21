"""Typed dependency graphs, reconciliation findings, and plan assumptions."""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from .canonical import canonical_json, contained_path, digest_ref, parse_json_object
from .roadmap import parse_roadmap, roadmap_dependency_edges
from .artifact_discovery import artifact_paths
from .validators import (
    active_approved_artifacts,
    parse_validated_artifact,
    read_repository_config,
    require_valid,
    validate_egress,
    validate_relation_record,
)


ARTIFACT_NODE_KINDS = frozenset(
    {
        "project",
        "prd",
        "requirement",
        "spec",
        "uxr",
        "design",
        "asset",
        "prototype",
        "sketch",
        "spike",
        "adr",
        "plan",
        "summary",
        "verification",
        "uat",
        "release",
        "defect",
    }
)
CODE_NODE_KINDS = frozenset({"file", "symbol", "schema", "test"})
REPOSITORY_NODE_KINDS = frozenset({"repository"})
EXTERNAL_ASSET_NODE_KINDS = frozenset({"external_asset"})
RELEASE_NODE_KINDS = frozenset({"release"})
EXECUTION_NODE_KINDS = frozenset({"roadmap", "milestone", "task"})
GOVERNANCE_NODE_KINDS = frozenset({"decision"})
NODE_KINDS = frozenset(
    ARTIFACT_NODE_KINDS
    | CODE_NODE_KINDS
    | REPOSITORY_NODE_KINDS
    | EXTERNAL_ASSET_NODE_KINDS
    | EXECUTION_NODE_KINDS
    | GOVERNANCE_NODE_KINDS
)
RELATION_VOCABULARY = frozenset(
    {
        "contains",
        "derives_from",
        "satisfies",
        "implements",
        "verifies",
        "depends_on_planned",
        "depends_on_observed",
        "blocks",
        "supersedes",
        "invalidates",
        "references_asset",
        "affects_code",
        "released_by",
        "duplicates",
        "recurs_as",
        "waives",
    }
)
ASSUMPTION_KINDS = frozenset(
    {"requirement", "design", "adr", "dependency", "code", "schema"}
)
DETERMINISTIC_MATCH_METHODS = frozenset(
    {"exact_symbol_digest", "exact_content_digest", "exact_provider_revision"}
)
DEPENDENCY_OBSERVATION_PATH = (
    ".planning/generated/dependency-observations.json"
)
OPTIONAL_ASSUMPTION_SELECTOR_FIELDS = frozenset({"source_id", "relation"})


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: str
    repository_key: str | None
    version: int | None
    lifecycle: str
    revision: str | None
    provider_revision: str | None
    available: bool

    def __post_init__(self) -> None:
        if self.kind not in NODE_KINDS:
            raise ValueError("dependency_node_kind_invalid")
        if not self.id or not isinstance(self.available, bool):
            raise ValueError("dependency_node_invalid")

    @classmethod
    def from_record(cls, value: dict[str, Any]) -> "GraphNode":
        return cls(
            id=value["id"],
            kind=value["kind"],
            repository_key=value.get("repository_key"),
            version=value.get("version"),
            lifecycle=value["lifecycle"],
            revision=value.get("revision"),
            provider_revision=value.get("provider_revision"),
            available=value["available"],
        )

    def record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "repository_key": self.repository_key,
            "version": self.version,
            "lifecycle": self.lifecycle,
            "revision": self.revision,
            "provider_revision": self.provider_revision,
            "available": self.available,
        }


@dataclass(frozen=True)
class DependencyEdge:
    source_id: str
    source_kind: str
    source_version: int | None
    relation: str
    target_id: str
    target_kind: str
    target_version: int | None
    authority: str
    lifecycle: str
    observed_revision: str | None
    provider_revision: str | None
    target_anchor: dict[str, Any] | None
    match_evidence: dict[str, Any] | None
    assumption_id: str | None
    affected_plan_ids: tuple[str, ...]
    affected_task_ids: tuple[str, ...]
    affected_requirement_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            self.source_kind not in NODE_KINDS
            or self.target_kind not in NODE_KINDS
            or self.relation not in RELATION_VOCABULARY
            or self.authority not in {"planned", "observed"}
            or not self.source_id
            or not self.target_id
        ):
            raise ValueError("dependency_edge_invalid")
        object.__setattr__(
            self, "affected_plan_ids", tuple(sorted(set(self.affected_plan_ids)))
        )
        object.__setattr__(
            self, "affected_task_ids", tuple(sorted(set(self.affected_task_ids)))
        )
        object.__setattr__(
            self,
            "affected_requirement_ids",
            tuple(sorted(set(self.affected_requirement_ids))),
        )

    @classmethod
    def from_record(cls, value: dict[str, Any]) -> "DependencyEdge":
        if "target" in value:
            target = value["target"]
            assumption = value.get("assumption") or {}
            return cls(
                source_id=value["source_id"],
                source_kind=value.get("source_kind", "plan"),
                source_version=value.get("source_version"),
                relation=value["relation"],
                target_id=target["id"],
                target_kind=target["kind"],
                target_version=target.get("version"),
                authority=value["authority"],
                lifecycle=value.get("lifecycle", "active"),
                observed_revision=value.get("observed_revision"),
                provider_revision=value.get("provider_revision"),
                target_anchor=target.get("anchor"),
                match_evidence=value.get("match_evidence"),
                assumption_id=assumption.get("id"),
                affected_plan_ids=tuple(assumption.get("affected_plan_ids", ())),
                affected_task_ids=tuple(assumption.get("affected_task_ids", ())),
                affected_requirement_ids=tuple(
                    assumption.get("affected_requirement_ids", ())
                ),
            )
        return cls(
            source_id=value["source_id"],
            source_kind=value["source_kind"],
            source_version=value.get("source_version"),
            relation=value["relation"],
            target_id=value["target_id"],
            target_kind=value["target_kind"],
            target_version=value.get("target_version"),
            authority=value["authority"],
            lifecycle=value["lifecycle"],
            observed_revision=value.get("observed_revision"),
            provider_revision=value.get("provider_revision"),
            target_anchor=value.get("target_anchor"),
            match_evidence=value.get("match_evidence"),
            assumption_id=value.get("assumption_id"),
            affected_plan_ids=tuple(value.get("affected_plan_ids", ())),
            affected_task_ids=tuple(value.get("affected_task_ids", ())),
            affected_requirement_ids=tuple(
                value.get("affected_requirement_ids", ())
            ),
        )

    @property
    def semantic_relation(self) -> str:
        return (
            "depends_on_planned"
            if self.relation == "depends_on_observed"
            else self.relation
        )

    @property
    def group_key(self) -> tuple[str, str, str]:
        return self.source_id, self.semantic_relation, self.target_kind

    @property
    def exact_key(self) -> tuple[str, str, str, str]:
        return (*self.group_key, self.target_id)

    def record(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "source_version": self.source_version,
            "relation": self.relation,
            "target_id": self.target_id,
            "target_kind": self.target_kind,
            "target_version": self.target_version,
            "authority": self.authority,
            "lifecycle": self.lifecycle,
            "observed_revision": self.observed_revision,
            "provider_revision": self.provider_revision,
            "target_anchor": self.target_anchor,
            "match_evidence": self.match_evidence,
            "assumption_id": self.assumption_id,
            "affected_plan_ids": list(self.affected_plan_ids),
            "affected_task_ids": list(self.affected_task_ids),
            "affected_requirement_ids": list(self.affected_requirement_ids),
        }

    def to_record(self) -> dict[str, Any]:
        return self.record()

    def relation_record(self, observed_at: str) -> dict[str, Any]:
        assumption = (
            {
                "id": self.assumption_id,
                "affected_plan_ids": list(self.affected_plan_ids),
                "affected_task_ids": list(self.affected_task_ids),
                "affected_requirement_ids": list(
                    self.affected_requirement_ids
                ),
            }
            if self.assumption_id is not None
            else None
        )
        target = {
            "kind": self.target_kind,
            "id": self.target_id,
            "version": self.target_version,
        }
        if self.target_anchor is not None:
            target["anchor"] = self.target_anchor
        return {
            "schema": "doc-warden/relation/v2",
            "relation": self.relation,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "source_version": self.source_version,
            "target": target,
            "authority": self.authority,
            "provenance": [{"observer": "dependency_snapshot"}],
            "observed_revision": self.observed_revision,
            "provider_revision": self.provider_revision,
            "observed_at": observed_at,
            "lifecycle": self.lifecycle,
            "match_evidence": self.match_evidence,
            "assumption": assumption,
        }


def _edge_sort_key(edge: DependencyEdge) -> tuple[Any, ...]:
    return (
        edge.source_id,
        edge.semantic_relation,
        edge.target_kind,
        edge.target_id,
        edge.relation,
        edge.target_version or -1,
        canonical_json(edge.record()),
    )


@dataclass(frozen=True)
class DependencySnapshot:
    schema: str
    repository_key: str
    source_revision: str
    observed_at: str
    authority: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[DependencyEdge, ...]

    def __post_init__(self) -> None:
        if (
            self.schema != "doc-warden/dependency-snapshot/v1"
            or self.authority not in {"planned", "observed", "mixed"}
        ):
            raise ValueError("dependency_snapshot_invalid")
        identifiers = [node.id for node in self.nodes]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("dependency_snapshot_duplicate_node")
        if self.authority != "mixed" and any(
            edge.authority != self.authority for edge in self.edges
        ):
            raise ValueError("dependency_snapshot_authority_mismatch")
        object.__setattr__(
            self, "nodes", tuple(sorted(self.nodes, key=lambda item: (item.kind, item.id)))
        )
        object.__setattr__(self, "edges", tuple(sorted(self.edges, key=_edge_sort_key)))

    @classmethod
    def from_record(cls, value: dict[str, Any]) -> "DependencySnapshot":
        if (
            set(value)
            != {
                "schema",
                "repository_key",
                "source_revision",
                "observed_at",
                "authority",
                "nodes",
                "edges",
            }
            or not isinstance(value["nodes"], list)
            or not isinstance(value["edges"], list)
        ):
            raise ValueError("dependency_snapshot_invalid")
        return cls(
            schema=value["schema"],
            repository_key=value["repository_key"],
            source_revision=value["source_revision"],
            observed_at=value["observed_at"],
            authority=value["authority"],
            nodes=tuple(GraphNode.from_record(item) for item in value["nodes"]),
            edges=tuple(DependencyEdge.from_record(item) for item in value["edges"]),
        )

    def record(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repository_key": self.repository_key,
            "source_revision": self.source_revision,
            "observed_at": self.observed_at,
            "authority": self.authority,
            "nodes": [node.record() for node in self.nodes],
            "edges": [edge.record() for edge in self.edges],
        }

    def to_record(self) -> dict[str, Any]:
        return self.record()


@dataclass(frozen=True)
class GeneratedGraph:
    nodes: tuple[str, ...]
    edges: tuple[tuple[str, str], ...]
    cycles: tuple[tuple[str, ...], ...]
    node_records: tuple[GraphNode, ...] = ()
    planned_relations: tuple[DependencyEdge, ...] = ()
    observed_relations: tuple[DependencyEdge, ...] = ()


@dataclass(frozen=True)
class DependencyFinding:
    classification: str
    subject: str
    node_kind: str
    planned: DependencyEdge | None
    observed: DependencyEdge | None
    evidence: dict[str, Any]
    safe_observation_update: bool = False
    path: tuple[str, ...] = ()

    def record(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "subject": self.subject,
            "node_kind": self.node_kind,
            "planned": self.planned.record() if self.planned else None,
            "observed": self.observed.record() if self.observed else None,
            "evidence": self.evidence,
            "safe_observation_update": self.safe_observation_update,
            "path": list(self.path),
        }

    def to_record(self) -> dict[str, Any]:
        return self.record()


@dataclass(frozen=True)
class GraphComparison:
    safe_updates: tuple[DependencyEdge, ...]
    findings: tuple[DependencyFinding, ...]
    cycles: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class PlanAssumption:
    schema: str
    id: str
    kind: str
    source_id: str | None
    target_id: str
    target_kind: str
    version: int | None
    digest: str | None
    repository_key: str
    revision: str | None
    provider_revision: str | None
    path: str | None
    symbol: str | None
    relation: str | None
    task_ids: tuple[str, ...]
    requirement_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            self.schema != "doc-warden/plan-assumption/v1"
            or self.kind not in ASSUMPTION_KINDS
            or self.target_kind not in NODE_KINDS | ASSUMPTION_KINDS
            or not self.id
            or not self.target_id
        ):
            raise ValueError("plan_assumption_invalid")
        object.__setattr__(self, "task_ids", tuple(sorted(set(self.task_ids))))
        object.__setattr__(
            self, "requirement_ids", tuple(sorted(set(self.requirement_ids)))
        )

    @classmethod
    def from_record(cls, value: dict[str, Any]) -> "PlanAssumption":
        required = {
            "schema",
            "id",
            "kind",
            "source_id",
            "target_id",
            "target_kind",
            "version",
            "digest",
            "repository_key",
            "revision",
            "provider_revision",
            "path",
            "symbol",
            "relation",
            "task_ids",
            "requirement_ids",
        }
        if set(value) != required:
            raise ValueError("plan_assumption_invalid")
        return cls(
            schema=value["schema"],
            id=value["id"],
            kind=value["kind"],
            source_id=value["source_id"],
            target_id=value["target_id"],
            target_kind=value["target_kind"],
            version=value["version"],
            digest=value["digest"],
            repository_key=value["repository_key"],
            revision=value["revision"],
            provider_revision=value["provider_revision"],
            path=value["path"],
            symbol=value["symbol"],
            relation=value["relation"],
            task_ids=tuple(value["task_ids"]),
            requirement_ids=tuple(value["requirement_ids"]),
        )

    def binding(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "target_kind": self.target_kind,
            "version": self.version,
            "digest": self.digest,
            "repository_key": self.repository_key,
            "revision": self.revision,
            "provider_revision": self.provider_revision,
            "path": self.path,
            "symbol": self.symbol,
            "relation": self.relation,
        }

    def record(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "id": self.id,
            "kind": self.kind,
            **self.binding(),
            "task_ids": list(self.task_ids),
            "requirement_ids": list(self.requirement_ids),
        }

    def to_record(self) -> dict[str, Any]:
        return self.record()


@dataclass(frozen=True)
class AssumptionFinding:
    classification: str
    assumption: PlanAssumption
    observed_binding: dict[str, Any]
    evidence: dict[str, Any]
    source_revision: str
    plan_id: str
    plan_version: int


@dataclass(frozen=True)
class PlanRefinement:
    changed_assumption: PlanAssumption
    observed_binding: dict[str, Any]
    evidence: dict[str, Any]
    source_revision: str
    affected_plans: tuple[str, ...]
    affected_tasks: tuple[str, ...]
    affected_requirements: tuple[str, ...]
    smallest_successor_action: str

    def record(self) -> dict[str, Any]:
        changed = {
            **self.changed_assumption.record(),
            "observed_binding": self.observed_binding,
            "changed_fields": sorted(self.evidence),
        }
        payload = {
            "schema": "doc-warden/plan-refinement-record/v1",
            "classification": "changed-assumption",
            "source_revision": self.source_revision,
            "changed_assumption": changed,
            "affected_plans": list(self.affected_plans),
            "affected_tasks": list(self.affected_tasks),
            "affected_requirements": list(self.affected_requirements),
            "smallest_successor_action": self.smallest_successor_action,
        }
        return {
            **payload,
            "record_id": "PLAN-REFINEMENT-"
            + hashlib.sha256(canonical_json(payload)).hexdigest(),
        }


class PlanRefinementRequired(ValueError):
    def __init__(self, refinements: Iterable[PlanRefinement]):
        self.refinements = tuple(refinements)
        super().__init__("plan_refinement_required")


def dependency_snapshot_bytes(snapshot: DependencySnapshot) -> bytes:
    return canonical_json(snapshot.record())


def load_dependency_snapshot(path: Path) -> DependencySnapshot:
    if path.is_symlink() or not path.is_file():
        raise ValueError("dependency_snapshot_unavailable")
    content = path.read_bytes()
    try:
        snapshot = DependencySnapshot.from_record(parse_json_object(content))
    except (KeyError, TypeError) as exc:
        raise ValueError("dependency_snapshot_invalid") from exc
    if content != dependency_snapshot_bytes(snapshot):
        raise ValueError("dependency_snapshot_not_canonical")
    return snapshot


def _canonical_cycle(path: tuple[str, ...]) -> tuple[str, ...]:
    body = path[:-1]
    return min(
        body[index:] + body[:index] + (body[index],)
        for index in range(len(body))
    )


def _find_cycles(graph: dict[str, tuple[str, ...]]) -> tuple[tuple[str, ...], ...]:
    found: set[tuple[str, ...]] = set()
    for start in sorted(graph):
        path = [start]
        visited = {start}

        def walk(node: str) -> None:
            for target in graph.get(node, ()):
                if target == start:
                    found.add(_canonical_cycle(tuple(path + [start])))
                elif target >= start and target not in visited:
                    visited.add(target)
                    path.append(target)
                    walk(target)
                    path.pop()
                    visited.remove(target)

        walk(start)
    return tuple(sorted(found))


def detect_cycles(
    snapshot: DependencySnapshot | GeneratedGraph,
) -> tuple[tuple[str, ...], ...]:
    if isinstance(snapshot, GeneratedGraph):
        return snapshot.cycles
    graph: dict[str, set[str]] = {node.id: set() for node in snapshot.nodes}
    for edge in snapshot.edges:
        graph.setdefault(edge.source_id, set()).add(edge.target_id)
        graph.setdefault(edge.target_id, set())
    return _find_cycles(
        {node: tuple(sorted(targets)) for node, targets in graph.items()}
    )


def _deterministic_retarget(
    planned: DependencyEdge,
    observed: DependencyEdge,
) -> bool:
    evidence = observed.match_evidence
    return bool(
        isinstance(evidence, dict)
        and evidence.get("method") in DETERMINISTIC_MATCH_METHODS
        and evidence.get("prior_target_id") == planned.target_id
        and evidence.get("candidate_target_ids") == [observed.target_id]
        and (
            evidence.get("content_digest") is not None
            or evidence.get("symbol") is not None
            or observed.provider_revision is not None
        )
    )


def _finding(
    classification: str,
    *,
    planned: DependencyEdge | None = None,
    observed: DependencyEdge | None = None,
    evidence: dict[str, Any] | None = None,
    safe: bool = False,
    path: tuple[str, ...] = (),
) -> DependencyFinding:
    edge = observed or planned
    assert edge is not None
    subject = " -> ".join(path) if path else edge.target_id
    return DependencyFinding(
        classification=classification,
        subject=subject,
        node_kind=edge.target_kind,
        planned=planned,
        observed=observed,
        evidence=evidence or {},
        safe_observation_update=safe,
        path=path,
    )


def _edge_change(
    planned: DependencyEdge,
    observed: DependencyEdge,
    observed_nodes: dict[str, GraphNode],
) -> str | None:
    node = observed_nodes.get(observed.target_id)
    if node is None or not node.available:
        return "dangling"
    if planned.assumption_id and (
        planned.target_version != observed.target_version
        or planned.observed_revision != observed.observed_revision
        or planned.provider_revision != observed.provider_revision
        or planned.lifecycle != observed.lifecycle
    ):
        return "changed-assumption"
    if observed.lifecycle == "removed":
        return "removed"
    if observed.lifecycle == "superseded" or node.lifecycle == "superseded":
        return "superseded"
    if observed.lifecycle == "stale":
        return "stale"
    if (
        planned.target_version is not None
        and observed.target_version is not None
        and planned.target_version != observed.target_version
    ):
        return "inconsistent"
    if (
        planned.observed_revision not in {None, "no-head"}
        and observed.observed_revision not in {None, "no-head"}
        and planned.observed_revision != observed.observed_revision
    ):
        return "stale"
    if (
        planned.provider_revision is not None
        and observed.provider_revision is not None
        and planned.provider_revision != observed.provider_revision
    ):
        return "stale"
    return None


def _edge_assumption_evidence(
    planned: DependencyEdge,
    observed: DependencyEdge,
) -> dict[str, Any]:
    fields = {
        "target_version": (
            planned.target_version,
            observed.target_version,
        ),
        "observed_revision": (
            planned.observed_revision,
            observed.observed_revision,
        ),
        "provider_revision": (
            planned.provider_revision,
            observed.provider_revision,
        ),
        "lifecycle": (planned.lifecycle, observed.lifecycle),
    }
    return {
        field: {"accepted": values[0], "observed": values[1]}
        for field, values in fields.items()
        if values[0] != values[1]
    }


def compare_dependencies(
    planned: DependencySnapshot,
    observed: DependencySnapshot,
) -> tuple[DependencyFinding, ...]:
    if planned.authority != "planned" or observed.authority != "observed":
        raise ValueError("dependency_snapshot_authority_mismatch")
    planned_nodes = {node.id: node for node in planned.nodes}
    observed_nodes = {node.id: node for node in observed.nodes}
    observed_exact: dict[
        tuple[str, str, str, str], list[DependencyEdge]
    ] = {}
    observed_groups: dict[
        tuple[str, str, str], list[DependencyEdge]
    ] = {}
    for edge in observed.edges:
        observed_exact.setdefault(edge.exact_key, []).append(edge)
        observed_groups.setdefault(edge.group_key, []).append(edge)
    matched: set[int] = set()
    findings: list[DependencyFinding] = []
    for planned_edge in planned.edges:
        exact = observed_exact.get(planned_edge.exact_key, [])
        if exact:
            matched.update(id(edge) for edge in exact)
            distinct = {canonical_json(edge.record()) for edge in exact}
            if len(distinct) > 1:
                findings.append(
                    _finding(
                        "inconsistent",
                        planned=planned_edge,
                        observed=exact[0],
                        evidence={"observed_candidates": [edge.record() for edge in exact]},
                    )
                )
                continue
            observed_edge = exact[0]
            classification = _edge_change(
                planned_edge, observed_edge, observed_nodes
            )
            if classification:
                findings.append(
                    _finding(
                        classification,
                        planned=planned_edge,
                        observed=observed_edge,
                        evidence=(
                            _edge_assumption_evidence(
                                planned_edge, observed_edge
                            )
                            if classification == "changed-assumption"
                            else None
                        ),
                    )
                )
            continue
        candidates = observed_groups.get(planned_edge.group_key, [])
        deterministic = [
            candidate
            for candidate in candidates
            if _deterministic_retarget(planned_edge, candidate)
        ]
        if len(deterministic) == 1:
            candidate = deterministic[0]
            matched.add(id(candidate))
            findings.append(
                _finding(
                    "stale",
                    planned=planned_edge,
                    observed=candidate,
                    evidence={"match_evidence": candidate.match_evidence},
                    safe=True,
                )
            )
        elif candidates:
            findings.append(
                _finding(
                    "unmapped",
                    planned=planned_edge,
                    observed=candidates[0],
                    evidence={"candidate_count": len(candidates)},
                )
            )
        elif (
            planned_edge.target_id not in planned_nodes
            or not planned_nodes[planned_edge.target_id].available
        ):
            findings.append(_finding("dangling", planned=planned_edge))
        else:
            findings.append(_finding("missing", planned=planned_edge))
    planned_groups = {edge.group_key for edge in planned.edges}
    for observed_edge in observed.edges:
        if id(observed_edge) in matched:
            continue
        if observed_edge.group_key in planned_groups:
            continue
        node = observed_nodes.get(observed_edge.target_id)
        findings.append(
            _finding(
                "dangling" if node is None or not node.available else "added",
                observed=observed_edge,
            )
        )
    cycles = tuple(
        sorted(set(detect_cycles(planned)) | set(detect_cycles(observed)))
    )
    for cycle in cycles:
        edge = next(
            item
            for item in (*planned.edges, *observed.edges)
            if item.source_id == cycle[0] and item.target_id == cycle[1]
        )
        findings.append(
            _finding(
                "cyclic",
                planned=edge if edge.authority == "planned" else None,
                observed=edge if edge.authority == "observed" else None,
                path=cycle,
            )
        )
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.classification,
                item.subject,
                canonical_json(item.record()),
            ),
        )
    )


def compare_dependency_graphs(
    planned: DependencySnapshot,
    observed: DependencySnapshot,
) -> GraphComparison:
    findings = compare_dependencies(planned, observed)
    cycles = tuple(
        sorted(set(detect_cycles(planned)) | set(detect_cycles(observed)))
    )
    cycle_edges = {
        (cycle[index], cycle[index + 1])
        for cycle in cycles
        for index in range(len(cycle) - 1)
    }
    return GraphComparison(
        safe_updates=tuple(
            finding.observed
            for finding in findings
            if (
                finding.safe_observation_update
                and finding.observed is not None
                and (
                    finding.observed.source_id,
                    finding.observed.target_id,
                )
                not in cycle_edges
            )
        ),
        findings=tuple(
            finding for finding in findings if not finding.safe_observation_update
        ),
        cycles=cycles,
    )


def classify_finding(finding: DependencyFinding) -> str:
    """Classify whether a finding is safely projectable or report-only."""

    return (
        "safe_observation_update"
        if finding.safe_observation_update
        else "report_only"
    )


def _head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "no-head"


def _merge_node(current: GraphNode | None, candidate: GraphNode) -> GraphNode:
    if current is None:
        return candidate
    return GraphNode(
        id=current.id,
        kind=current.kind,
        repository_key=current.repository_key or candidate.repository_key,
        version=current.version if current.version is not None else candidate.version,
        lifecycle=(
            current.lifecycle
            if current.lifecycle not in {"unmapped", "unavailable"}
            else candidate.lifecycle
        ),
        revision=current.revision or candidate.revision,
        provider_revision=current.provider_revision or candidate.provider_revision,
        available=current.available or candidate.available,
    )


def _target_node(
    edge: DependencyEdge,
    known_repositories: set[str],
) -> GraphNode:
    repository_key = (
        edge.target_anchor.get("repository_key")
        if isinstance(edge.target_anchor, dict)
        else None
    )
    if edge.target_kind == "repository" and edge.target_id.startswith("REPO-"):
        repository_key = edge.target_id.removeprefix("REPO-")
    if repository_key is None and edge.target_kind in ARTIFACT_NODE_KINDS:
        match = re.match(
            r"^[A-Z_]+-([0-9a-f]{8}-[0-9a-f]{4}-[45][0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12})-",
            edge.target_id,
        )
        repository_key = match.group(1) if match else None
    available = edge.target_kind not in ARTIFACT_NODE_KINDS and (
        repository_key in known_repositories
        if (
            repository_key is not None
            and edge.target_kind != "external_asset"
        )
        else edge.target_kind != "repository"
    )
    return GraphNode(
        id=edge.target_id,
        kind=edge.target_kind,
        repository_key=repository_key,
        version=edge.target_version,
        lifecycle=edge.lifecycle if available else "unavailable",
        revision=(
            edge.target_anchor.get("revision")
            if isinstance(edge.target_anchor, dict)
            else edge.observed_revision
        ),
        provider_revision=edge.provider_revision,
        available=available,
    )


def resolve_graph(repositories: Iterable[Path]) -> GeneratedGraph:
    roots = tuple(Path(repo).resolve(strict=True) for repo in repositories)
    configs = {
        repo: config
        for repo in roots
        if (config := read_repository_config(repo)) is not None
    }
    known_keys = {config["repository_key"] for config in configs.values()}
    nodes: dict[str, GraphNode] = {}
    edges: list[DependencyEdge] = []
    retired: dict[str, tuple[str, str]] = {}
    for repo, config in configs.items():
        revision = _head(repo)
        repository_id = f"REPO-{config['repository_key']}"
        nodes[repository_id] = GraphNode(
            id=repository_id,
            kind="repository",
            repository_key=config["repository_key"],
            version=None,
            lifecycle="active",
            revision=revision,
            provider_revision=None,
            available=True,
        )
        for path in artifact_paths(repo):
            metadata = parse_validated_artifact(path, repo=repo)
            source = GraphNode(
                id=metadata["id"],
                kind=metadata["type"],
                repository_key=metadata["repository_key"],
                version=metadata["version"],
                lifecycle=metadata["lifecycle"],
                revision=revision,
                provider_revision=None,
                available=True,
            )
            if source.id in nodes and nodes[source.id] != source:
                raise ValueError("dependency_artifact_identity_conflict")
            nodes[source.id] = source
            if metadata["lifecycle"] == "approved" and metadata["supersedes"] is not None:
                retired[metadata["supersedes"]] = (source.kind, metadata["repository_key"])
            for record in metadata["relations"]:
                edge = DependencyEdge.from_record(
                    {
                        **record,
                        "source_kind": record.get(
                            "source_kind", metadata["type"]
                        ),
                    }
                )
                edges.append(edge)
        roadmap_items = parse_roadmap(repo / ".planning/ROADMAP.md")
        roadmap_ids = {item["id"] for item in roadmap_items}
        for item in roadmap_items:
            nodes[item["id"]] = GraphNode(
                id=item["id"],
                kind="roadmap",
                repository_key=config["repository_key"],
                version=None,
                lifecycle=item["status"],
                revision=item["freshness"]["source_revision"],
                provider_revision=None,
                available=True,
            )
        for authority in ("planned", "observed"):
            relation = (
                "depends_on_planned"
                if authority == "planned"
                else "depends_on_observed"
            )
            for source_id, target_id in roadmap_dependency_edges(
                roadmap_items, authority
            ):
                source = next(
                    item for item in roadmap_items if item["id"] == source_id
                )
                edge = DependencyEdge(
                    source_id=source_id,
                    source_kind="roadmap",
                    source_version=None,
                    relation=relation,
                    target_id=target_id,
                    target_kind="roadmap",
                    target_version=None,
                    authority=authority,
                    lifecycle=(
                        "active" if target_id in roadmap_ids else "unavailable"
                    ),
                    observed_revision=source["freshness"]["source_revision"],
                    provider_revision=None,
                    target_anchor=None,
                    match_evidence=None,
                    assumption_id=None,
                    affected_plan_ids=(),
                    affected_task_ids=(),
                    affected_requirement_ids=(),
                )
                edges.append(edge)
                if target_id not in nodes:
                    nodes[target_id] = GraphNode(
                        id=target_id,
                        kind="roadmap",
                        repository_key=config["repository_key"],
                        version=None,
                        lifecycle="unavailable",
                        revision=None,
                        provider_revision=None,
                        available=False,
                    )
    for identifier, owner in retired.items():
        predecessor = nodes.get(identifier)
        if predecessor and (predecessor.kind, predecessor.repository_key) == owner:
            nodes[identifier] = replace(predecessor, lifecycle="superseded")
    inspected = set(nodes)
    for edge in edges:
        if edge.target_id not in inspected:
            target = _target_node(edge, known_keys)
            nodes[target.id] = _merge_node(nodes.get(target.id), target)
    planned = tuple(
        sorted(
            (edge for edge in edges if edge.authority == "planned"),
            key=_edge_sort_key,
        )
    )
    observed = tuple(
        sorted(
            (edge for edge in edges if edge.authority == "observed"),
            key=_edge_sort_key,
        )
    )
    mixed = DependencySnapshot(
        schema="doc-warden/dependency-snapshot/v1",
        repository_key=next(iter(known_keys), "00000000-0000-4000-8000-000000000000"),
        source_revision=_head(roots[0]) if roots else "no-head",
        observed_at="1970-01-01T00:00:00Z",
        authority="mixed",
        nodes=tuple(nodes.values()),
        edges=tuple(edges),
    )
    return GeneratedGraph(
        nodes=tuple(sorted(nodes)),
        edges=tuple(
            sorted((edge.source_id, edge.target_id) for edge in mixed.edges)
        ),
        cycles=detect_cycles(mixed),
        node_records=mixed.nodes,
        planned_relations=planned,
        observed_relations=observed,
    )


def build_graph(repo: Path) -> GeneratedGraph:
    parse_roadmap(repo / ".planning/ROADMAP.md")
    return resolve_graph((repo,))


def compare_plan_assumption(
    assumption: PlanAssumption,
    observed_binding: dict[str, Any],
    *,
    source_revision: str,
    plan_id: str,
    plan_version: int,
) -> AssumptionFinding | None:
    accepted = assumption.binding()
    changed = {
        field: {
            "accepted": accepted.get(field),
            "observed": observed_binding.get(field),
        }
        for field in sorted(
            (set(accepted) | set(observed_binding)) - {"revision"}
        )
        if accepted.get(field) != observed_binding.get(field)
        and not (
            field in OPTIONAL_ASSUMPTION_SELECTOR_FIELDS
            and accepted.get(field) is None
        )
    }
    if not changed:
        return None
    return AssumptionFinding(
        classification="changed-assumption",
        assumption=assumption,
        observed_binding=dict(observed_binding),
        evidence=changed,
        source_revision=source_revision,
        plan_id=plan_id,
        plan_version=plan_version,
    )


_SUCCESSOR_ACTION = {
    "requirement": "create_successor_plan_rebinding_requirement",
    "design": "create_successor_plan_rebinding_design",
    "adr": "create_successor_plan_rebinding_adr",
    "dependency": "create_successor_plan_after_dependency_reconciliation",
    "code": "create_successor_plan_revalidating_code_precondition",
    "schema": "create_successor_plan_revalidating_schema_precondition",
}


def plans_invalidated(
    findings: Iterable[AssumptionFinding | DependencyFinding],
) -> tuple[PlanRefinement, ...]:
    refinements = []
    for finding in findings:
        if finding.classification != "changed-assumption":
            continue
        if isinstance(finding, AssumptionFinding):
            assumption = finding.assumption
            observed_binding = finding.observed_binding
            evidence = finding.evidence
            source_revision = finding.source_revision
            affected_plans = (finding.plan_id,)
        else:
            planned = finding.planned
            observed = finding.observed
            if planned is None or planned.assumption_id is None:
                continue
            kind = (
                planned.target_kind
                if planned.target_kind
                in {"requirement", "design", "adr", "schema"}
                else (
                    "code"
                    if planned.target_kind in CODE_NODE_KINDS
                    else "dependency"
                )
            )
            anchor = planned.target_anchor or {}
            assumption = PlanAssumption(
                schema="doc-warden/plan-assumption/v1",
                id=planned.assumption_id,
                kind=kind,
                source_id=planned.source_id,
                target_id=planned.target_id,
                target_kind=planned.target_kind,
                version=planned.target_version,
                digest=(
                    planned.match_evidence or {}
                ).get("content_digest"),
                repository_key=anchor.get(
                    "repository_key",
                    "00000000-0000-4000-8000-000000000000",
                ),
                revision=planned.observed_revision,
                provider_revision=planned.provider_revision,
                path=anchor.get("path"),
                symbol=anchor.get("symbol"),
                relation=planned.semantic_relation,
                task_ids=planned.affected_task_ids,
                requirement_ids=planned.affected_requirement_ids,
            )
            observed_binding = assumption.binding()
            if observed is not None:
                observed_binding.update(
                    {
                        "target_id": observed.target_id,
                        "target_kind": observed.target_kind,
                        "version": observed.target_version,
                        "revision": observed.observed_revision,
                        "provider_revision": observed.provider_revision,
                        "relation": observed.semantic_relation,
                    }
                )
            evidence = finding.evidence
            source_revision = (
                observed.observed_revision
                if observed is not None
                else planned.observed_revision
            ) or "no-head"
            affected_plans = (
                planned.affected_plan_ids or (planned.source_id,)
            )
        refinements.append(
            PlanRefinement(
                changed_assumption=assumption,
                observed_binding=observed_binding,
                evidence=evidence,
                source_revision=source_revision,
                affected_plans=affected_plans,
                affected_tasks=assumption.task_ids,
                affected_requirements=assumption.requirement_ids,
                smallest_successor_action=_SUCCESSOR_ACTION[
                    assumption.kind
                ],
            )
        )
    return tuple(
        sorted(
            refinements,
            key=lambda item: (
                item.affected_plans,
                item.changed_assumption.id,
            ),
        )
    )


def _receipt_binds_plan_sidecar(
    repo: Path,
    *,
    plan_path: str,
    plan_digest: str,
    sidecar_path: str,
    sidecar_digest: str,
    repository_key: str,
    accepted: bool,
) -> bool:
    root = repo / "_ops/doc-warden/state/v2/receipts"
    if not root.exists():
        return False
    if root.is_symlink() or not root.is_dir():
        raise ValueError("plan_assumption_authority_invalid")
    expected_transition = "accepted_freeze" if accepted else "creation_snapshot"
    required_actions = {
        (plan_path, plan_digest),
        (sidecar_path, sidecar_digest),
    }
    for path in sorted(root.glob("*.json"), key=lambda item: item.name):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            relative = str(path.relative_to(repo))
            if contained_path(repo, relative) != path:
                raise ValueError("receipt_path_mismatch")
        except ValueError as exc:
            raise ValueError("plan_assumption_authority_invalid") from exc
        try:
            raw = path.read_bytes()
            receipt = parse_json_object(raw)
        except (OSError, ValueError):
            continue
        postimages = receipt.get("postimages")
        if (
            not isinstance(postimages, dict)
            or postimages.get(plan_path) != plan_digest
            or postimages.get(sidecar_path) != sidecar_digest
        ):
            continue
        try:
            if raw != canonical_json(receipt):
                raise ValueError("receipt_not_canonical")
            validate_egress("receipt", receipt)
            if path.name != f"{receipt['operation_id']}.json":
                raise ValueError("receipt_name_mismatch")
            actions = {
                (action["path"], action["content_digest"])
                for action in receipt["actions"]
            }
            if (
                receipt["transition"] != expected_transition
                or receipt["outcome"] != "applied"
                or receipt["repository_key"] != repository_key
                or not required_actions.issubset(actions)
            ):
                raise ValueError("receipt_binding_mismatch")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("plan_assumption_authority_invalid") from exc
        return True
    return False


def _receipt_binds_dependency_projection(
    repo: Path,
    *,
    projection_digest: str,
    repository_key: str,
    source_revision: str,
) -> bool:
    receipt_root = repo / "_ops/doc-warden/state/v2/receipts"
    if not receipt_root.exists():
        return False
    if receipt_root.is_symlink() or not receipt_root.is_dir():
        raise ValueError("dependency_observation_authority_invalid")
    for path in sorted(
        receipt_root.glob("*.json"),
        key=lambda item: item.name,
    ):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            relative = str(path.relative_to(repo))
            if contained_path(repo, relative) != path:
                raise ValueError("receipt_path_mismatch")
        except ValueError as exc:
            raise ValueError(
                "dependency_observation_authority_invalid"
            ) from exc
        try:
            raw = path.read_bytes()
            receipt = parse_json_object(raw)
        except (OSError, ValueError):
            continue
        postimages = receipt.get("postimages")
        if (
            not isinstance(postimages, dict)
            or postimages.get(DEPENDENCY_OBSERVATION_PATH)
            != projection_digest
        ):
            continue
        try:
            if raw != canonical_json(receipt):
                raise ValueError("receipt_not_canonical")
            validate_egress("receipt", receipt)
            if path.name != f"{receipt['operation_id']}.json":
                raise ValueError("receipt_name_mismatch")
            actions = receipt["actions"]
            action_paths = [action["path"] for action in actions]
            action_postimages = {
                action["path"]: action["content_digest"]
                for action in actions
            }
            confirmation = {
                "schema": "doc-warden/explicit-confirmation/v1",
                "operation_id": receipt["operation_id"],
                "action_digest": receipt["action_digest"],
                "source_revision": receipt["source_revision"],
                "canonical_root": str(repo),
                "choice": "apply",
            }
            event_relative = (
                "_ops/doc-warden/state/v2/events/"
                f"{receipt['event_id']}.json"
            )
            event_path = contained_path(repo, event_relative)
            if event_path.is_symlink() or not event_path.is_file():
                raise ValueError("receipt_event_missing")
            event_raw = event_path.read_bytes()
            event = parse_json_object(event_raw)
            if event_raw != canonical_json(event):
                raise ValueError("receipt_event_not_canonical")
            validate_egress("event", event)
            if (
                len(action_paths) != len(set(action_paths))
                or set(receipt["preimages"]) != set(postimages)
                or action_postimages != postimages
                or receipt["transition"] != "projection_update"
                or receipt["outcome"] != "applied"
                or receipt["repository_key"] != repository_key
                or receipt["source_revision"] != source_revision
                or receipt["confirmation_digest"]
                != digest_ref(canonical_json(confirmation))
                or not receipt["observed_input_digests"]
                or not any(
                    action["path"] == DEPENDENCY_OBSERVATION_PATH
                    and action["content_digest"] == projection_digest
                    and action["kind"] in {"create", "replace"}
                    for action in actions
                )
                or event["event_id"] != receipt["event_id"]
                or event["operation_id"] != receipt["operation_id"]
                or event["transition"] != receipt["transition"]
                or event["action_digest"] != receipt["action_digest"]
                or event["source_revision"]
                != receipt["source_revision"]
                or event["prior_event_digest"]
                != receipt["prior_event_digest"]
                or event["outcome"] != receipt["outcome"]
                or event["details"] != {"postimages": postimages}
                or receipt["result_tree_digest"]
                != digest_ref(
                    canonical_json(
                        {
                            "event": event,
                            "postimages": postimages,
                        }
                    )
                )
            ):
                raise ValueError("receipt_binding_mismatch")
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise ValueError(
                "dependency_observation_authority_invalid"
            ) from exc
        return True
    return False


def _validated_plan_sidecar(
    repo: Path,
    path: Path,
) -> dict[str, Any] | None:
    try:
        sidecar_relative = str(path.relative_to(repo))
        if contained_path(repo, sidecar_relative) != path:
            raise ValueError("plan_sidecar_path_mismatch")
        raw = path.read_bytes()
        value = parse_json_object(raw)
        if value.get("schema") != "doc-warden/plan-governance-sidecar/v2":
            return None
        if raw != canonical_json(value):
            raise ValueError("plan_sidecar_not_canonical")
        require_valid("plan-governance-sidecar", value)
        artifact_id = value["artifact_id"]
        artifact_version = value["artifact_version"]
        expected_name = (
            f"{artifact_id}-v{artifact_version}.governance.json"
        )
        if path.name != expected_name:
            raise ValueError("plan_sidecar_name_mismatch")
        plan_relative = (
            f".planning/artifacts/{artifact_id}-v{artifact_version}.md"
        )
        plan_path = contained_path(repo, plan_relative)
        if plan_path.is_symlink() or not plan_path.is_file():
            raise ValueError("plan_artifact_missing")
        metadata = parse_validated_artifact(plan_path)
        plan_digest = digest_ref(plan_path.read_bytes())
        if (
            metadata["id"] != artifact_id
            or metadata["type"] != "plan"
            or metadata["version"] != artifact_version
            or value["accepted"]
            != (metadata["lifecycle"] == "approved")
            or value["canonical_plan_digest"] != plan_digest
        ):
            raise ValueError("plan_sidecar_artifact_mismatch")
        if not _receipt_binds_plan_sidecar(
            repo,
            plan_path=plan_relative,
            plan_digest=plan_digest,
            sidecar_path=sidecar_relative,
            sidecar_digest=digest_ref(raw),
            repository_key=metadata["repository_key"],
            accepted=value["accepted"],
        ):
            raise ValueError("plan_sidecar_receipt_missing")
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise ValueError("plan_assumption_authority_invalid") from exc
    return value


def _plan_sidecar(repo: Path, plan_id: str) -> dict[str, Any] | None:
    roots = (repo / ".planning/artifacts",)
    matches = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_symlink() or not root.is_dir():
            raise ValueError("plan_assumption_authority_invalid")
        for path in sorted(root.glob("*.json"), key=lambda item: item.name):
            if path.is_symlink() or not path.is_file():
                raise ValueError("plan_assumption_authority_invalid")
            try:
                candidate = parse_json_object(path.read_bytes())
            except (OSError, ValueError) as exc:
                raise ValueError("plan_assumption_authority_invalid") from exc
            candidate_id = candidate.get("artifact_id")
            path_claims_plan = path.name.startswith(f"{plan_id}-v")
            if (
                not path_claims_plan
                and isinstance(candidate_id, str)
                and candidate_id != plan_id
            ):
                continue
            value = _validated_plan_sidecar(repo, path)
            if value is None:
                if path_claims_plan or candidate_id == plan_id:
                    raise ValueError("plan_assumption_authority_invalid")
                continue
            if value["artifact_id"] != plan_id:
                raise ValueError("plan_assumption_authority_invalid")
            matches.append(value)
    if not matches:
        return None
    accepted = [value for value in matches if value.get("accepted")]
    candidates = accepted or matches
    highest = max(int(item.get("artifact_version", 0)) for item in candidates)
    current = [
        item
        for item in candidates
        if int(item.get("artifact_version", 0)) == highest
    ]
    if len({canonical_json(item) for item in current}) > 1:
        raise ValueError("contradictory_plan_assumption_authority")
    return current[0]


def _active_accepted_plan_sidecars(
    repo: Path,
) -> dict[str, dict[str, Any]]:
    try:
        active_versions: dict[str, set[int]] = {}
        for _path, metadata, _body in active_approved_artifacts(
            repo,
            "plan",
        ):
            active_versions.setdefault(metadata["id"], set()).add(
                metadata["version"]
            )
        selected = {}
        for plan_id, versions in sorted(active_versions.items()):
            sidecar = _plan_sidecar(repo, plan_id)
            if (
                sidecar is None
                or not sidecar.get("accepted")
                or sidecar.get("artifact_version") not in versions
            ):
                raise ValueError("active_plan_authority_mismatch")
            selected[plan_id] = sidecar
        return selected
    except (KeyError, OSError, TypeError, ValueError) as exc:
        if str(exc) == "plan_assumption_authority_invalid":
            raise
        raise ValueError("plan_assumption_authority_invalid") from exc


def _plan_sidecar_for_assumption_validation(
    repo: Path,
    plan_id: str | None,
) -> dict[str, Any] | None:
    active = _active_accepted_plan_sidecars(repo)
    assumption_bearing = {
        identifier: sidecar
        for identifier, sidecar in active.items()
        if sidecar.get("assumptions")
    }
    if plan_id is None:
        if not assumption_bearing:
            return None
        if len(assumption_bearing) != 1:
            raise ValueError("active_plan_binding_ambiguous")
        return next(iter(assumption_bearing.values()))
    requested = _plan_sidecar(repo, plan_id)
    if requested is None:
        raise ValueError("active_plan_binding_unavailable")
    if not requested.get("accepted"):
        raise ValueError("active_plan_binding_not_accepted")
    authoritative = active.get(plan_id)
    if (
        authoritative is None
        or canonical_json(authoritative) != canonical_json(requested)
    ):
        raise ValueError("active_plan_binding_unavailable")
    if not requested.get("assumptions") and assumption_bearing:
        raise ValueError("active_plan_binding_mismatch")
    return requested


def _unresolved_assumption_binding(
    assumption: PlanAssumption,
    current_revision: str,
) -> dict[str, Any]:
    return {
        **assumption.binding(),
        "version": None,
        "digest": None,
        "revision": current_revision,
        "provider_revision": None,
    }


def _observe_requirement_assumption(
    repo: Path,
    assumption: PlanAssumption,
    current_revision: str,
) -> dict[str, Any]:
    unresolved = _unresolved_assumption_binding(
        assumption,
        current_revision,
    )
    try:
        from .artifact_authority import resolve_approved_artifact
        from .gsd_adapter import (
            BEGIN_REQUIREMENTS,
            END_REQUIREMENTS,
            requirements_current_view,
        )

        rendered = requirements_current_view(repo).decode("utf-8")
        start = rendered.index(BEGIN_REQUIREMENTS) + len(BEGIN_REQUIREMENTS)
        end = rendered.index(END_REQUIREMENTS, start)
        payload_bytes = rendered[start:end].encode("utf-8")
        payload = parse_json_object(payload_bytes)
        if (
            payload_bytes != canonical_json(payload)
            or set(payload)
            != {"schema", "source_revision", "requirements"}
            or payload["schema"]
            != "doc-warden/requirements-current-view/v1"
            or payload["source_revision"] != current_revision
            or not isinstance(payload["requirements"], list)
        ):
            return unresolved
        candidates = [
            item
            for item in payload["requirements"]
            if isinstance(item, dict)
            and item.get("id") == assumption.target_id
        ]
        if len(candidates) != 1:
            return unresolved
        source = candidates[0].get("source")
        if (
            not isinstance(source, dict)
            or set(source)
            != {"artifact_id", "version", "digest", "path"}
            or not isinstance(source["artifact_id"], str)
            or not isinstance(source["version"], int)
            or isinstance(source["version"], bool)
            or source["version"] < 1
            or not isinstance(source["digest"], str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", source["digest"])
            is None
            or not isinstance(source["path"], str)
        ):
            return unresolved
        authority_path = contained_path(
            repo,
            source["path"],
        )
        if authority_path.is_symlink() or not authority_path.is_file():
            return unresolved
        metadata = parse_validated_artifact(authority_path)
        if (
            metadata["id"] != source["artifact_id"]
            or metadata["type"] != "prd"
            or metadata["version"] != source["version"]
            or metadata["lifecycle"] != "approved"
            or digest_ref(authority_path.read_bytes()) != source["digest"]
        ):
            return unresolved
        resolve_approved_artifact(repo, "prd", metadata["id"], version=source["version"], digest=source["digest"])
    except (KeyError, OSError, TypeError, UnicodeError, ValueError):
        return unresolved
    observed = assumption.binding()
    observed.update(
        {
            "target_id": candidates[0]["id"],
            "target_kind": "requirement",
            "version": source["version"],
            "digest": source["digest"],
            "repository_key": metadata["repository_key"],
            "revision": current_revision,
            "provider_revision": None,
        }
    )
    return observed


def _observe_assumption(repo: Path, assumption: PlanAssumption) -> dict[str, Any]:
    current_revision = _head(repo)
    unresolved = _unresolved_assumption_binding(
        assumption,
        current_revision,
    )
    if (
        assumption.kind == "requirement"
        and assumption.target_kind not in EXTERNAL_ASSET_NODE_KINDS
    ):
        return _observe_requirement_assumption(
            repo,
            assumption,
            current_revision,
        )
    if (
        assumption.kind == "dependency"
        or assumption.target_kind in EXTERNAL_ASSET_NODE_KINDS
    ):
        try:
            projection = contained_path(
                repo,
                DEPENDENCY_OBSERVATION_PATH,
            )
        except (OSError, ValueError):
            return unresolved
        if projection.is_symlink() or not projection.is_file():
            return unresolved
        try:
            snapshot = load_dependency_snapshot(projection)
            projection_bytes = projection.read_bytes()
            if projection_bytes != dependency_snapshot_bytes(snapshot):
                return unresolved
            config = read_repository_config(repo)
            if (
                config is None
                or snapshot.repository_key != config["repository_key"]
                or snapshot.source_revision != current_revision
                or snapshot.authority != "observed"
                or not _receipt_binds_dependency_projection(
                    repo,
                    projection_digest=digest_ref(projection_bytes),
                    repository_key=config["repository_key"],
                    source_revision=current_revision,
                )
            ):
                return unresolved
            for edge in snapshot.edges:
                validate_relation_record(
                    edge.relation_record(snapshot.observed_at)
                )
            candidates = [
                edge
                for edge in snapshot.edges
                if edge.target_id == assumption.target_id
                and edge.target_kind == assumption.target_kind
                and (
                    assumption.source_id is None
                    or edge.source_id == assumption.source_id
                )
                and (
                    assumption.relation is None
                    or edge.semantic_relation == assumption.relation
                )
            ]
            if len(candidates) != 1:
                return unresolved
            edge = candidates[0]
            evidence = edge.match_evidence
            content_digest = (
                evidence.get("content_digest")
                if isinstance(evidence, dict)
                else None
            )
            exact_provider_revision = bool(
                isinstance(evidence, dict)
                and evidence.get("method") == "exact_provider_revision"
                and edge.target_kind == "external_asset"
                and isinstance(edge.provider_revision, str)
                and edge.provider_revision
            )
            if (
                edge.lifecycle != "active"
                or not isinstance(evidence, dict)
                or evidence.get("method") not in DETERMINISTIC_MATCH_METHODS
                or evidence.get("prior_target_id") != assumption.target_id
                or evidence.get("candidate_target_ids") != [edge.target_id]
                or not (
                    isinstance(content_digest, str)
                    or exact_provider_revision
                )
            ):
                return unresolved
        except (OSError, TypeError, ValueError):
            return unresolved
        observed = assumption.binding()
        anchor = edge.target_anchor or {}
        observed.update(
            {
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "target_kind": edge.target_kind,
                "version": edge.target_version,
                "repository_key": anchor.get(
                    "repository_key", assumption.repository_key
                ),
                "revision": edge.observed_revision,
                "provider_revision": edge.provider_revision,
                "path": anchor.get("path", assumption.path),
                "symbol": anchor.get("symbol", assumption.symbol),
                "relation": edge.semantic_relation,
            }
        )
        if isinstance(content_digest, str):
            observed["digest"] = content_digest
        return observed
    if assumption.kind in {"code", "schema"} and assumption.path:
        try:
            path = contained_path(repo, assumption.path)
            if path.is_symlink() or not path.is_file():
                return unresolved
            digest = digest_ref(path.read_bytes())
        except (OSError, ValueError):
            return unresolved
        observed = assumption.binding()
        observed["digest"] = digest
        observed["revision"] = current_revision
        return observed
    if assumption.target_kind in ARTIFACT_NODE_KINDS:
        exact = []
        successors = []
        try:
            for path in artifact_paths(repo):
                metadata = parse_validated_artifact(path, repo=repo)
                if metadata["id"] == assumption.target_id:
                    exact.append((path, metadata))
                elif (
                    metadata.get("supersedes") == assumption.target_id
                    and metadata["lifecycle"]
                    not in {"rejected", "cancelled"}
                    and (metadata["type"] != "adr" or metadata["lifecycle"] == "approved")
                ):
                    successors.append((path, metadata))
        except (OSError, TypeError, ValueError):
            return unresolved
        candidates = successors or exact
        if not candidates:
            return unresolved
        try:
            highest = max(
                int(metadata["version"]) for _, metadata in candidates
            )
            current = [
                (path, metadata)
                for path, metadata in candidates
                if int(metadata["version"]) == highest
            ]
            if len(current) != 1:
                return unresolved
            path, metadata = current[0]
            artifact_digest = digest_ref(path.read_bytes())
        except (OSError, TypeError, ValueError):
            return unresolved
        observed = assumption.binding()
        observed["target_id"] = metadata["id"]
        observed["target_kind"] = metadata["type"]
        observed["version"] = metadata["version"]
        observed["digest"] = artifact_digest
        observed["repository_key"] = metadata["repository_key"]
        observed["revision"] = current_revision
        return observed
    return unresolved


def refinements_for_active_plan(
    repo: Path,
    plan_id: str | None,
) -> tuple[PlanRefinement, ...]:
    root = repo.resolve(strict=True)
    sidecar = _plan_sidecar_for_assumption_validation(root, plan_id)
    if sidecar is None:
        return ()
    findings = []
    for value in sidecar.get("assumptions", []):
        assumption = PlanAssumption.from_record(value)
        finding = compare_plan_assumption(
            assumption,
            _observe_assumption(root, assumption),
            source_revision=_head(root),
            plan_id=sidecar["artifact_id"],
            plan_version=sidecar["artifact_version"],
        )
        if finding is not None:
            findings.append(finding)
    return plans_invalidated(findings)


def assert_plan_assumptions_current(
    repo: Path,
    plan_id: str | None,
) -> None:
    refinements = refinements_for_active_plan(repo, plan_id)
    if refinements:
        raise PlanRefinementRequired(refinements)
