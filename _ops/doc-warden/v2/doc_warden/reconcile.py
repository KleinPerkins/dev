"""Preview-bound reconciliation of typed observations and projections."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import _bindings
from .canonical import canonical_json, contained_path, digest_ref
from .dependencies import (
    DETERMINISTIC_MATCH_METHODS,
    DependencyEdge,
    DependencyFinding,
    DependencySnapshot,
    GeneratedGraph,
    GraphComparison,
    GraphNode,
    build_graph,
    compare_dependency_graphs,
    dependency_snapshot_bytes,
    load_dependency_snapshot,
)
from .transactions import (
    ExplicitConfirmation,
    MutationAction,
    MutationRequest,
    ObservedInput,
    TransactionPreview,
    apply_transaction,
    preview_transaction,
)
from .validators import read_repository_config, validate_relation_record


@dataclass(frozen=True)
class ReconciliationPlan:
    status: str
    classifications: tuple[tuple[str, str], ...]
    graph: GeneratedGraph
    transaction: TransactionPreview | None
    safe_updates: tuple[dict[str, Any], ...] = ()
    unsafe_findings: tuple[dict[str, Any], ...] = ()


def _semantic_edge_bytes(edge: DependencyEdge) -> bytes:
    record = edge.to_record()
    record["relation"] = edge.semantic_relation
    record.pop("authority")
    record.pop("observed_revision")
    anchor = record.get("target_anchor")
    if isinstance(anchor, dict):
        record["target_anchor"] = {
            key: value
            for key, value in anchor.items()
            if key != "revision"
        }
    return canonical_json(record)


def _semantic_node_bytes(node: GraphNode) -> bytes:
    record = node.record()
    record.pop("revision")
    return canonical_json(record)


def _edge_observation_trusted(edge: DependencyEdge) -> bool:
    if edge.lifecycle != "active":
        return False
    evidence = edge.match_evidence
    if evidence is None:
        return True
    return bool(
        isinstance(evidence, dict)
        and evidence.get("method") in DETERMINISTIC_MATCH_METHODS
        and evidence.get("candidate_target_ids") == [edge.target_id]
        and (
            evidence.get("content_digest") is not None
            or evidence.get("symbol") is not None
            or edge.provider_revision is not None
        )
    )


def _revision_only_finding(finding: DependencyFinding) -> bool:
    return bool(
        finding.classification == "stale"
        and finding.planned is not None
        and finding.observed is not None
        and _semantic_edge_bytes(finding.planned)
        == _semantic_edge_bytes(finding.observed)
    )


def _same_trusted_observation_state(
    persisted: DependencySnapshot,
    candidate: DependencySnapshot,
    comparison: GraphComparison,
    *,
    has_cycles: bool,
) -> bool:
    if (
        has_cycles
        or not persisted.edges
        or not candidate.edges
        or comparison.safe_updates
        or any(
            not _revision_only_finding(finding)
            for finding in comparison.findings
        )
    ):
        return False
    persisted_keys = [edge.exact_key for edge in persisted.edges]
    candidate_keys = [edge.exact_key for edge in candidate.edges]
    if (
        len(persisted_keys) != len(set(persisted_keys))
        or len(candidate_keys) != len(set(candidate_keys))
        or any(
            not _edge_observation_trusted(edge)
            for edge in candidate.edges
        )
        or sorted(_semantic_edge_bytes(edge) for edge in persisted.edges)
        != sorted(_semantic_edge_bytes(edge) for edge in candidate.edges)
    ):
        return False
    node_ids = {
        identifier
        for edge in candidate.edges
        for identifier in (edge.source_id, edge.target_id)
    }
    persisted_nodes = {
        node.id: node
        for node in persisted.nodes
        if node.id in node_ids
    }
    candidate_nodes = {
        node.id: node
        for node in candidate.nodes
        if node.id in node_ids
    }
    unavailable = {
        "stale",
        "unmapped",
        "superseded",
        "removed",
        "unavailable",
    }
    return bool(
        set(persisted_nodes) == node_ids
        and set(candidate_nodes) == node_ids
        and all(
            node.available and node.lifecycle not in unavailable
            for node in candidate_nodes.values()
        )
        and sorted(
            _semantic_node_bytes(node)
            for node in persisted_nodes.values()
        )
        == sorted(
            _semantic_node_bytes(node)
            for node in candidate_nodes.values()
        )
    )


def _typed_reconciliation(
    repo: Path,
    graph: GeneratedGraph,
    observations: Path,
    operation_id: str | None,
) -> ReconciliationPlan:
    config = read_repository_config(repo)
    if config is None:
        raise ValueError("v2_repository_profile_required")
    candidate_path = observations.resolve(strict=True)
    candidate = load_dependency_snapshot(candidate_path)
    if (
        candidate.repository_key != config["repository_key"]
        or candidate.source_revision
        != subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
    ):
        raise ValueError("dependency_observation_binding_mismatch")
    for edge in candidate.edges:
        validate_relation_record(
            edge.relation_record(candidate.observed_at)
        )
        if edge.observed_revision != candidate.source_revision:
            raise ValueError("dependency_observation_revision_mismatch")
        if edge.target_kind == "external_asset" and not edge.provider_revision:
            raise ValueError("dependency_observation_provider_revision_missing")
    planned = DependencySnapshot(
        schema="doc-warden/dependency-snapshot/v1",
        repository_key=config["repository_key"],
        source_revision=candidate.source_revision,
        observed_at=candidate.observed_at,
        authority="planned",
        nodes=graph.node_records,
        edges=graph.planned_relations,
    )
    comparison = compare_dependency_graphs(planned, candidate)
    projection_path = repo / ".planning/generated/dependency-observations.json"
    if projection_path.exists():
        persisted = load_dependency_snapshot(projection_path)
        if (
            persisted.repository_key != candidate.repository_key
            or persisted.authority != "observed"
        ):
            raise ValueError("dependency_observation_projection_invalid")
    else:
        persisted = DependencySnapshot(
            schema="doc-warden/dependency-snapshot/v1",
            repository_key=candidate.repository_key,
            source_revision=candidate.source_revision,
            observed_at=candidate.observed_at,
            authority="observed",
            nodes=(),
            edges=(),
        )
    persisted_records = {
        canonical_json(edge.to_record()) for edge in persisted.edges
    }
    has_cycles = bool(graph.cycles or comparison.cycles)
    safe_edges = tuple(
        edge
        for edge in comparison.safe_updates
        if canonical_json(edge.to_record()) not in persisted_records
    ) if not has_cycles else ()
    same_trusted_state = _same_trusted_observation_state(
        persisted,
        candidate,
        comparison,
        has_cycles=has_cycles,
    )
    revision_refresh = bool(
        same_trusted_state
        and persisted.source_revision != candidate.source_revision
    )
    unsafe_findings = (
        ()
        if same_trusted_state
        else comparison.findings
    )
    unsafe = tuple(finding.to_record() for finding in unsafe_findings)
    refresh_classifications = (
        (
            ".planning/generated/dependency-observations.json",
            "safe_observation_revision_refresh",
        ),
    ) if revision_refresh else ()
    classifications = tuple(
        [
            *refresh_classifications,
            *(
                (edge.target_id, "safe_observation_update")
                for edge in safe_edges
            ),
            *(
                (
                    finding.subject,
                    finding.classification,
                )
                for finding in unsafe_findings
            ),
        ]
    )
    transaction = None
    if safe_edges or revision_refresh:
        edge_by_record = {
            canonical_json(edge.to_record()): edge
            for edge in (
                persisted.edges
                if revision_refresh
                else (*persisted.edges, *safe_edges)
            )
        }
        node_ids = {
            identifier
            for edge in edge_by_record.values()
            for identifier in (edge.source_id, edge.target_id)
        }
        candidate_nodes = {
            node.id: node
            for node in (*persisted.nodes, *candidate.nodes)
            if node.id in node_ids
        }
        projection = DependencySnapshot(
            schema="doc-warden/dependency-snapshot/v1",
            repository_key=candidate.repository_key,
            source_revision=candidate.source_revision,
            observed_at=candidate.observed_at,
            authority="observed",
            nodes=tuple(candidate_nodes.values()),
            edges=tuple(edge_by_record.values()),
        )
        transaction = preview_transaction(
            MutationRequest(
                repo=repo,
                repository_key=config["repository_key"],
                github_repository_id=config["github_repository_id"],
                transition="projection_update",
                actions=(
                    MutationAction(
                        ".planning/generated/dependency-observations.json",
                        dependency_snapshot_bytes(projection),
                    ),
                ),
                bindings=_bindings(repo),
                operation_id=operation_id,
                observed_inputs=(
                    ObservedInput(
                        path=str(candidate_path),
                        digest=digest_ref(candidate_path.read_bytes()),
                    ),
                ),
                consequential=True,
                require_write_enabled=True,
            )
        )
    status = (
        "blocked"
        if has_cycles
        else (
            "ready"
            if safe_edges or revision_refresh
            else ("review_required" if unsafe else "conformant")
        )
    )
    return ReconciliationPlan(
        status=status,
        classifications=classifications,
        graph=graph,
        transaction=transaction,
        safe_updates=tuple(edge.to_record() for edge in safe_edges),
        unsafe_findings=unsafe,
    )


def reconcile(
    repo: Path,
    mode: str = "preview",
    *,
    expected_frozen: dict[str, str] | None = None,
    projection_updates: dict[str, bytes] | None = None,
    operation_id: str | None = None,
    observations: Path | None = None,
) -> ReconciliationPlan:
    if mode != "preview":
        raise ValueError("reconciliation_preview_only")
    repo = repo.resolve(strict=True)
    frozen = expected_frozen or {}
    projections = projection_updates or {}
    classifications: list[tuple[str, str]] = []
    try:
        graph = build_graph(repo)
    except ValueError as exc:
        graph = GeneratedGraph((), (), ())
        location = (
            ".planning/ROADMAP.md"
            if str(exc).startswith("roadmap")
            else ".planning/artifacts"
        )
        classifications.append((location, "contradictory_authority"))
        return ReconciliationPlan("blocked", tuple(classifications), graph, None)
    if observations is not None:
        return _typed_reconciliation(repo, graph, observations, operation_id)
    if graph.cycles:
        for cycle in graph.cycles:
            classifications.append((" -> ".join(cycle), "dependency_cycle"))
        return ReconciliationPlan("blocked", tuple(classifications), graph, None)
    for relative, expected in sorted(frozen.items()):
        path = contained_path(repo, relative)
        observed = digest_ref(path.read_bytes()) if path.is_file() else None
        if observed != expected:
            classifications.append((relative, "contradictory_authority"))
    if classifications:
        return ReconciliationPlan("blocked", tuple(classifications), graph, None)
    actions = []
    for relative, content in sorted(projections.items()):
        if not relative.startswith(".planning/generated/") or relative in frozen:
            raise ValueError("unsafe_reconciliation_target")
        actions.append(MutationAction(relative, content))
        classifications.append((relative, "safe_projection_update"))
    transaction = None
    if actions:
        config = read_repository_config(repo)
        if config is None:
            raise ValueError("v2_repository_profile_required")
        transaction = preview_transaction(
            MutationRequest(
                repo=repo,
                repository_key=config["repository_key"],
                github_repository_id=config["github_repository_id"],
                transition="projection_update",
                actions=tuple(actions),
                bindings=_bindings(repo),
                operation_id=operation_id,
                require_write_enabled=True,
            )
        )
    return ReconciliationPlan(
        "ready" if actions else "conformant",
        tuple(classifications),
        graph,
        transaction,
    )


def apply_reconciliation(
    preview: ReconciliationPlan, explicit_confirmation: ExplicitConfirmation
) -> dict[str, Any]:
    if preview.transaction is None or preview.status != "ready":
        raise ValueError("reconciliation_not_applicable")
    return apply_transaction(preview.transaction, explicit_confirmation)
