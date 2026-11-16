import unittest

from doc_warden.dependencies import (
    ARTIFACT_NODE_KINDS,
    CODE_NODE_KINDS,
    RELATION_VOCABULARY,
    DependencyEdge,
    DependencySnapshot,
    GraphNode,
    compare_dependencies,
    dependency_snapshot_bytes,
    detect_cycles,
    load_dependency_snapshot,
)
from fixture_factory import FixtureFactory


REVISION = "a" * 40


class DependencyPropertyCases(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create("dependency-properties")

    def tearDown(self):
        repo = self.fixture.repo
        self.fixture.cleanup()
        self.assertFalse(repo.exists())

    def node(self, node_id, kind, **overrides):
        values = {
            "id": node_id,
            "kind": kind,
            "repository_key": self.fixture.repository_key,
            "version": 1,
            "lifecycle": "active",
            "revision": REVISION,
            "provider_revision": None,
            "available": True,
        }
        values.update(overrides)
        return GraphNode(**values)

    def edge(self, source_id, target_id, target_kind, **overrides):
        values = {
            "source_id": source_id,
            "source_kind": "plan",
            "source_version": 1,
            "relation": "depends_on_planned",
            "target_id": target_id,
            "target_kind": target_kind,
            "target_version": 1,
            "authority": "planned",
            "lifecycle": "active",
            "observed_revision": REVISION,
            "provider_revision": None,
            "target_anchor": None,
            "match_evidence": None,
            "assumption_id": None,
            "affected_plan_ids": (),
            "affected_task_ids": (),
            "affected_requirement_ids": (),
        }
        values.update(overrides)
        return DependencyEdge(**values)

    def snapshot(self, nodes, edges, *, authority):
        return DependencySnapshot(
            schema="doc-warden/dependency-snapshot/v1",
            repository_key=self.fixture.repository_key,
            source_revision=REVISION,
            observed_at="2026-08-31T20:00:00Z",
            authority=authority,
            nodes=tuple(nodes),
            edges=tuple(edges),
        )

    def test_all_node_kinds_and_relation_vocabulary_round_trip(self):
        required_artifacts = {
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
        self.assertEqual(set(ARTIFACT_NODE_KINDS), required_artifacts)
        self.assertTrue({"file", "symbol", "schema", "test"} <= set(CODE_NODE_KINDS))
        self.assertEqual(
            set(RELATION_VOCABULARY),
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
            },
        )
        kinds = sorted(
            required_artifacts
            | set(CODE_NODE_KINDS)
            | {"repository", "external_asset", "roadmap", "milestone", "task"}
        )
        nodes = [self.node(f"NODE-{index}", kind) for index, kind in enumerate(kinds)]
        source = nodes[0]
        edges = []
        for index, relation in enumerate(RELATION_VOCABULARY):
            observed = relation == "depends_on_observed"
            edges.append(
                self.edge(
                    source.id,
                    nodes[(index + 1) % len(nodes)].id,
                    nodes[(index + 1) % len(nodes)].kind,
                    relation=relation,
                    authority="observed" if observed else "planned",
                )
            )
        snapshot = self.snapshot(nodes, edges, authority="mixed")
        path = self.fixture.repo / "dependency-snapshot.json"
        path.write_bytes(dependency_snapshot_bytes(snapshot))
        self.assertEqual(load_dependency_snapshot(path), snapshot)

    def test_required_finding_class_matrix_across_node_types(self):
        source = self.node("PLAN-1", "plan")
        target_kinds = ("prd", "symbol", "repository", "external_asset", "release")
        for target_kind in target_kinds:
            with self.subTest(classification="missing", target_kind=target_kind):
                target = self.node(f"{target_kind.upper()}-1", target_kind)
                planned = self.snapshot(
                    (source, target),
                    (self.edge(source.id, target.id, target_kind),),
                    authority="planned",
                )
                observed = self.snapshot((source, target), (), authority="observed")
                self.assertEqual(
                    {finding.classification for finding in compare_dependencies(planned, observed)},
                    {"missing"},
                )

        target = self.node("REQ-1", "requirement")
        planned_edge = self.edge(source.id, target.id, target.kind)
        planned = self.snapshot((source, target), (planned_edge,), authority="planned")

        stale = self.snapshot(
            (source, target),
            (
                self.edge(
                    source.id,
                    target.id,
                    target.kind,
                    relation="depends_on_observed",
                    authority="observed",
                    lifecycle="stale",
                ),
            ),
            authority="observed",
        )
        self.assertIn("stale", {item.classification for item in compare_dependencies(planned, stale)})

        removed = self.snapshot(
            (source, target),
            (
                self.edge(
                    source.id,
                    target.id,
                    target.kind,
                    relation="depends_on_observed",
                    authority="observed",
                    lifecycle="removed",
                ),
            ),
            authority="observed",
        )
        self.assertIn("removed", {item.classification for item in compare_dependencies(planned, removed)})

        superseded = self.snapshot(
            (source, self.node(target.id, target.kind, lifecycle="superseded")),
            (
                self.edge(
                    source.id,
                    target.id,
                    target.kind,
                    relation="depends_on_observed",
                    authority="observed",
                    lifecycle="superseded",
                ),
            ),
            authority="observed",
        )
        self.assertIn(
            "superseded",
            {item.classification for item in compare_dependencies(planned, superseded)},
        )

        added_target = self.node("ASSET-ADDED", "external_asset", provider_revision="figma-2")
        added = self.snapshot(
            (source, target, added_target),
            (
                self.edge(
                    source.id,
                    added_target.id,
                    added_target.kind,
                    relation="depends_on_observed",
                    authority="observed",
                    provider_revision="figma-2",
                ),
            ),
            authority="observed",
        )
        self.assertIn("added", {item.classification for item in compare_dependencies(planned, added)})

        dangling_edge = self.edge(source.id, "REPO-MISSING", "repository")
        dangling = compare_dependencies(
            self.snapshot((source,), (dangling_edge,), authority="planned"),
            self.snapshot((source,), (), authority="observed"),
        )
        self.assertIn("dangling", {item.classification for item in dangling})

        ambiguous_target = self.node("SYMBOL-NEW", "symbol")
        ambiguous = self.snapshot(
            (source, self.node("SYMBOL-OLD", "symbol"), ambiguous_target),
            (
                self.edge(
                    source.id,
                    ambiguous_target.id,
                    "symbol",
                    relation="depends_on_observed",
                    authority="observed",
                    match_evidence={
                        "method": "ambiguous_candidates",
                        "prior_target_id": "SYMBOL-OLD",
                        "candidate_target_ids": ["SYMBOL-NEW", "SYMBOL-OTHER"],
                        "symbol": "package.function",
                        "content_digest": "sha256:" + "b" * 64,
                    },
                ),
            ),
            authority="observed",
        )
        ambiguous_planned = self.snapshot(
            (source, self.node("SYMBOL-OLD", "symbol")),
            (self.edge(source.id, "SYMBOL-OLD", "symbol"),),
            authority="planned",
        )
        self.assertIn(
            "unmapped",
            {item.classification for item in compare_dependencies(ambiguous_planned, ambiguous)},
        )

        inconsistent = self.snapshot(
            (source, target),
            (
                self.edge(
                    source.id,
                    target.id,
                    target.kind,
                    relation="depends_on_observed",
                    authority="observed",
                    target_version=2,
                ),
                self.edge(
                    source.id,
                    target.id,
                    target.kind,
                    relation="depends_on_observed",
                    authority="observed",
                    target_version=3,
                ),
            ),
            authority="observed",
        )
        self.assertIn(
            "inconsistent",
            {item.classification for item in compare_dependencies(planned, inconsistent)},
        )

        assumed = self.snapshot(
            (source, target),
            (
                self.edge(
                    source.id,
                    target.id,
                    target.kind,
                    assumption_id="ASM-REQ-1",
                    affected_plan_ids=("PLAN-1",),
                    affected_task_ids=("M2-T03",),
                    affected_requirement_ids=("REQ-1",),
                ),
            ),
            authority="planned",
        )
        changed = self.snapshot(
            (source, self.node(target.id, target.kind, version=2)),
            (
                self.edge(
                    source.id,
                    target.id,
                    target.kind,
                    relation="depends_on_observed",
                    authority="observed",
                    target_version=2,
                ),
            ),
            authority="observed",
        )
        self.assertIn(
            "changed-assumption",
            {item.classification for item in compare_dependencies(assumed, changed)},
        )

    def test_cycles_use_canonical_stable_id_paths_and_are_never_safe(self):
        nodes = tuple(self.node(node_id, "task") for node_id in ("TASK-C", "TASK-A", "TASK-B"))
        by_id = {node.id: node for node in nodes}
        edges = (
            self.edge("TASK-C", "TASK-A", "task", source_kind="task"),
            self.edge("TASK-A", "TASK-B", "task", source_kind="task"),
            self.edge("TASK-B", "TASK-C", "task", source_kind="task"),
        )
        planned = self.snapshot(nodes, edges, authority="planned")
        self.assertEqual(detect_cycles(planned), (("TASK-A", "TASK-B", "TASK-C", "TASK-A"),))
        observed = self.snapshot(tuple(by_id.values()), (), authority="observed")
        findings = compare_dependencies(planned, observed)
        cyclic = [finding for finding in findings if finding.classification == "cyclic"]
        self.assertEqual([finding.subject for finding in cyclic], ["TASK-A -> TASK-B -> TASK-C -> TASK-A"])
        self.assertTrue(all(not finding.safe_observation_update for finding in cyclic))

    def test_symbol_retarget_requires_unique_digest_bound_match_evidence(self):
        source = self.node("PLAN-1", "plan")
        old = self.node("SYMBOL-OLD", "symbol")
        new = self.node("SYMBOL-NEW", "symbol")
        planned = self.snapshot(
            (source, old),
            (self.edge(source.id, old.id, old.kind),),
            authority="planned",
        )
        exact = self.snapshot(
            (source, new),
            (
                self.edge(
                    source.id,
                    new.id,
                    new.kind,
                    relation="depends_on_observed",
                    authority="observed",
                    target_anchor={
                        "repository_key": self.fixture.repository_key,
                        "github_repository_id": None,
                        "revision": REVISION,
                        "path": "src/new.py",
                        "kind": "symbol",
                        "symbol": "package.function",
                        "line_hint": None,
                    },
                    match_evidence={
                        "method": "exact_symbol_digest",
                        "prior_target_id": old.id,
                        "candidate_target_ids": [new.id],
                        "symbol": "package.function",
                        "content_digest": "sha256:" + "c" * 64,
                    },
                ),
            ),
            authority="observed",
        )
        finding = next(
            item for item in compare_dependencies(planned, exact) if item.observed is not None
        )
        self.assertEqual(finding.classification, "stale")
        self.assertTrue(finding.safe_observation_update)

        ambiguous_edge = DependencyEdge(
            **{
                **exact.edges[0].__dict__,
                "match_evidence": {
                    **exact.edges[0].match_evidence,
                    "method": "ambiguous_candidates",
                    "candidate_target_ids": [new.id, "SYMBOL-OTHER"],
                },
            }
        )
        ambiguous = self.snapshot((source, new), (ambiguous_edge,), authority="observed")
        finding = next(
            item for item in compare_dependencies(planned, ambiguous) if item.observed is not None
        )
        self.assertEqual(finding.classification, "unmapped")
        self.assertFalse(finding.safe_observation_update)


if __name__ == "__main__":
    unittest.main()
