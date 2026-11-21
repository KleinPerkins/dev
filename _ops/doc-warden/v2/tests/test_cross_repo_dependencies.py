import json
import os
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from doc_warden.artifacts import apply_preview, consent_for, draft_artifact
from doc_warden.canonical import canonical_json, digest_ref
from doc_warden.dependencies import (
    DependencyEdge,
    DependencySnapshot,
    GraphNode,
    PlanRefinementRequired,
    assert_plan_assumptions_current,
    dependency_snapshot_bytes,
    load_dependency_snapshot,
    resolve_graph,
)
from doc_warden.receipts import observe_delivery
from doc_warden.reconcile import apply_reconciliation, reconcile
from doc_warden.roadmap import new_roadmap_item, render_roadmap
from doc_warden.transactions import confirmation_for
from fixture_factory import FixtureFactory


ROOT = Path(__file__).resolve().parents[4]
WRAPPER = ROOT / "_ops/bin/doc-warden.sh"


class CrossRepoDependencyTests(unittest.TestCase):
    def setUp(self):
        self.machine = tempfile.TemporaryDirectory(
            prefix="doc-warden-cross-repo-dependencies-"
        )
        self.owner = FixtureFactory.create("dependency-owner")
        self.dependent = FixtureFactory.create("dependency-dependent")

    def tearDown(self):
        owner = self.owner.repo
        dependent = self.dependent.repo
        self.owner.cleanup()
        self.dependent.cleanup()
        self.machine.cleanup()
        self.assertFalse(owner.exists())
        self.assertFalse(dependent.exists())

    @staticmethod
    def head(repo):
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            text=True,
        ).strip()

    def relation(
        self,
        *,
        source_id,
        target_id,
        target_kind,
        authority,
        relation,
        repository_key,
        revision,
        path=None,
        symbol=None,
        lifecycle="active",
        match_evidence=None,
    ):
        anchor = None
        if target_kind in {"file", "symbol", "schema", "test"}:
            anchor = {
                "repository_key": repository_key,
                "github_repository_id": None,
                "revision": revision,
                "path": path,
                "kind": target_kind,
                "symbol": symbol,
                "line_hint": None,
            }
        return {
            "schema": "doc-warden/relation/v2",
            "relation": relation,
            "source_id": source_id,
            "source_kind": "plan",
            "source_version": 1,
            "target": {
                "kind": target_kind,
                "id": target_id,
                "version": None,
                "anchor": anchor,
            },
            "authority": authority,
            "provenance": [{"observer": "fixture"}],
            "observed_revision": revision,
            "provider_revision": None,
            "observed_at": "2026-08-31T20:00:00Z",
            "lifecycle": lifecycle,
            "match_evidence": match_evidence,
            "assumption": None,
        }

    def persist_plan_with_relations(self, relations):
        self.dependent.approve_prd("REQ-001")
        operation_id = self.dependent.id_for("dependency-plan-operation")
        plan_id = (
            f"PLAN-{self.dependent.repository_key}-"
            f"{uuid.uuid5(uuid.UUID(operation_id), 'plan')}"
        )
        normalized = [
            {**relation, "source_id": plan_id}
            for relation in relations
        ]
        preview = draft_artifact(
            "plan",
            {
                "title": "Dependency plan",
                "approved_prd": True,
                "relations": normalized,
            },
            repo=self.dependent.repo,
            operation_id=operation_id,
        )
        self.assertEqual(preview.artifact_id, plan_id)
        apply_preview(preview, consent_for(preview.transaction))
        return preview

    def run_cli(self, *arguments, check=True):
        return subprocess.run(
            ["bash", str(WRAPPER), *arguments],
            text=True,
            capture_output=True,
            check=check,
            env={
                **os.environ,
                "XDG_STATE_HOME": str(Path(self.machine.name) / "xdg-state"),
            },
        )

    def accepted_dependency_state(self, match_evidence=None):
        self.dependent.approve_prd("REQ-001")
        revision = self.head(self.dependent.repo)
        target_id = f"REPO-{self.owner.repository_key}"
        evidence = match_evidence or {
            "method": "exact_content_digest",
            "prior_target_id": target_id,
            "candidate_target_ids": [target_id],
            "content_digest": "sha256:" + "a" * 64,
        }
        operation_id = self.dependent.id_for(
            "accepted-dependency-plan-operation"
        )
        plan_id = (
            f"PLAN-{self.dependent.repository_key}-"
            f"{uuid.uuid5(uuid.UUID(operation_id), 'plan')}"
        )
        relation = self.relation(
            source_id=plan_id,
            target_id=target_id,
            target_kind="repository",
            authority="planned",
            relation="depends_on_planned",
            repository_key=self.owner.repository_key,
            revision=revision,
            match_evidence=evidence,
        )
        relation["target"]["version"] = 1
        assumption = {
            "schema": "doc-warden/plan-assumption/v1",
            "id": f"ASM-{self.dependent.id_for('dependency-assumption')}",
            "kind": "dependency",
            "source_id": plan_id,
            "target_id": target_id,
            "target_kind": "repository",
            "version": 1,
            "digest": evidence["content_digest"],
            "repository_key": self.dependent.repository_key,
            "revision": revision,
            "provider_revision": None,
            "path": None,
            "symbol": None,
            "relation": "depends_on_planned",
            "task_ids": ["M2-T03"],
            "requirement_ids": ["REQ-001"],
        }
        plan = draft_artifact(
            "plan",
            {
                "title": "Accepted dependency plan",
                "approved_prd": True,
                "lifecycle": "approved",
                "approval": {
                    "approved_by": "operator",
                    "approved_at": "2026-09-01T01:00:00Z",
                },
                "relations": [relation],
                "assumptions": [assumption],
                "requirement_ids": ["REQ-001"],
                "task_ids": ["M2-T03"],
            },
            repo=self.dependent.repo,
            operation_id=operation_id,
        )
        apply_preview(plan, consent_for(plan.transaction))
        return (
            plan,
            assumption,
            evidence,
            self.dependency_observation(
                plan,
                assumption,
                revision,
                evidence,
                observed_at="2026-09-01T01:05:00Z",
            ),
        )

    def dependency_observation(
        self,
        plan,
        assumption,
        revision,
        match_evidence,
        *,
        observed_at,
    ):
        source = GraphNode(
            id=plan.artifact_id,
            kind="plan",
            repository_key=self.dependent.repository_key,
            version=1,
            lifecycle="active",
            revision=revision,
            provider_revision=None,
            available=True,
        )
        target = GraphNode(
            id=assumption["target_id"],
            kind="repository",
            repository_key=self.owner.repository_key,
            version=assumption["version"],
            lifecycle="active",
            revision=revision,
            provider_revision=None,
            available=True,
        )
        relation = self.relation(
            source_id=plan.artifact_id,
            target_id=assumption["target_id"],
            target_kind="repository",
            authority="observed",
            relation="depends_on_observed",
            repository_key=self.owner.repository_key,
            revision=revision,
            match_evidence=match_evidence,
        )
        relation["target"]["version"] = assumption["version"]
        return DependencySnapshot(
            schema="doc-warden/dependency-snapshot/v1",
            repository_key=self.dependent.repository_key,
            source_revision=revision,
            observed_at=observed_at,
            authority="observed",
            nodes=(source, target),
            edges=(DependencyEdge.from_record(relation),),
        )

    def persist_dependency_projection(self, snapshot):
        projection = (
            self.dependent.repo
            / ".planning/generated/dependency-observations.json"
        )
        projection.parent.mkdir(parents=True, exist_ok=True)
        projection.write_bytes(dependency_snapshot_bytes(snapshot))
        return projection

    def advance_dependent_head(self, label):
        marker = self.dependent.repo / f"{label}.txt"
        marker.write_text(f"{label}\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.dependent.repo), "add", marker.name],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.dependent.repo),
                "commit",
                "-qm",
                label,
            ],
            check=True,
        )
        return self.head(self.dependent.repo)

    def current_dependency_candidate(
        self,
        plan,
        assumption,
        match_evidence,
        revision,
        label,
    ):
        candidate = self.dependency_observation(
            plan,
            assumption,
            revision,
            match_evidence,
            observed_at="2026-09-01T01:10:00Z",
        )
        path = Path(self.machine.name) / f"{label}.json"
        path.write_bytes(dependency_snapshot_bytes(candidate))
        return candidate, path

    def test_resolve_graph_keeps_cross_repo_nodes_and_exact_revisions(self):
        revision = self.head(self.owner.repo)
        relation = self.relation(
            source_id="placeholder",
            target_id=f"REPO-{self.owner.repository_key}",
            target_kind="repository",
            authority="observed",
            relation="depends_on_observed",
            repository_key=self.owner.repository_key,
            revision=revision,
        )
        plan = self.persist_plan_with_relations([relation])
        graph = resolve_graph((self.dependent.repo, self.owner.repo))
        node_by_id = {node.id: node for node in graph.node_records}
        self.assertIn(plan.artifact_id, node_by_id)
        self.assertIn(f"REPO-{self.owner.repository_key}", node_by_id)
        observed = next(
            edge
            for edge in graph.observed_relations
            if edge.target_id == f"REPO-{self.owner.repository_key}"
        )
        self.assertEqual(observed.observed_revision, revision)
        self.assertEqual(observed.target_kind, "repository")
        self.assertEqual(graph.planned_relations, ())

    def test_cross_repo_artifact_availability_and_version_come_from_owner_records(self):
        target = self.owner.approve_prd("REQ-001")
        missing = f"PRD-{self.owner.repository_key}-{self.owner.id_for('missing-prd')}"
        relations = [
            self.relation(
                source_id="placeholder", target_id=identifier, target_kind="prd",
                authority="planned", relation="depends_on_planned",
                repository_key=self.owner.repository_key, revision=self.head(self.owner.repo),
            )
            for identifier in (target, missing)
        ]
        for relation in relations:
            relation["target"]["version"] = 9
        self.persist_plan_with_relations(relations)
        successor = draft_artifact("prd", {
            "title": "Replacement requirements", "version": 2, "supersedes": target,
            "lifecycle": "approved", "approval": {"actor": "fixture", "date": "2026-01-01"},
            "requirements": [{"id": "REQ-002", "statement": "Current behavior."}],
        }, repo=self.owner.repo)
        apply_preview(successor, consent_for(successor.transaction))

        for roots in ((self.dependent.repo, self.owner.repo), (self.owner.repo, self.dependent.repo)):
            records = {node.id: node for node in resolve_graph(roots).node_records}
            self.assertFalse(records[missing].available)
            self.assertEqual(records[missing].lifecycle, "unavailable")
            self.assertTrue(records[target].available)
            self.assertEqual(records[target].version, 1)
            self.assertEqual(records[target].lifecycle, "superseded")
            self.assertEqual(records[successor.artifact_id].lifecycle, "approved")

    def test_revision_only_refresh_updates_projection_and_unblocks_authoring(self):
        plan, assumption, evidence, old_projection = (
            self.accepted_dependency_state()
        )
        projection_path = self.persist_dependency_projection(old_projection)
        plan_path = self.dependent.repo / plan.artifact_path
        accepted_plan_bytes = plan_path.read_bytes()
        current_revision = self.advance_dependent_head(
            "advance-for-dependency-refresh"
        )
        with self.assertRaises(PlanRefinementRequired):
            assert_plan_assumptions_current(
                self.dependent.repo,
                plan.artifact_id,
            )
        candidate, candidate_path = self.current_dependency_candidate(
            plan,
            assumption,
            evidence,
            current_revision,
            "revision-refresh-observations",
        )
        operation_id = self.dependent.id_for(
            "revision-refresh-reconciliation-operation"
        )
        preview = reconcile(
            self.dependent.repo,
            observations=candidate_path,
            operation_id=operation_id,
        )
        self.assertEqual(preview.status, "ready")
        self.assertEqual(
            preview.classifications,
            (
                (
                    ".planning/generated/dependency-observations.json",
                    "safe_observation_revision_refresh",
                ),
            ),
        )
        self.assertEqual(preview.safe_updates, ())
        self.assertEqual(preview.unsafe_findings, ())
        self.assertIsNotNone(preview.transaction)
        transaction = preview.transaction
        assert transaction is not None
        self.assertEqual(transaction.transition, "projection_update")
        self.assertEqual(
            [(action.path, action.kind) for action in transaction.actions],
            [
                (
                    ".planning/generated/dependency-observations.json",
                    "replace",
                )
            ],
        )
        self.assertEqual(
            transaction.observed_inputs[0].digest,
            digest_ref(candidate_path.read_bytes()),
        )
        self.assertEqual(
            transaction.preimages[
                ".planning/generated/dependency-observations.json"
            ],
            digest_ref(dependency_snapshot_bytes(old_projection)),
        )
        with self.assertRaisesRegex(
            ValueError,
            "explicit_confirmation_required",
        ):
            apply_reconciliation(preview, None)
        candidate_bytes = candidate_path.read_bytes()
        candidate_path.write_bytes(candidate_bytes + b" ")
        with self.assertRaisesRegex(ValueError, "observed_input_drift"):
            apply_reconciliation(
                preview,
                confirmation_for(transaction),
            )
        candidate_path.write_bytes(candidate_bytes)
        receipt = apply_reconciliation(
            preview,
            confirmation_for(transaction),
        )
        refreshed = load_dependency_snapshot(projection_path)
        self.assertEqual(refreshed.source_revision, current_revision)
        self.assertEqual(refreshed.observed_at, candidate.observed_at)
        self.assertEqual(refreshed.edges, old_projection.edges)
        self.assertEqual(refreshed.nodes, candidate.nodes)
        self.assertEqual(plan_path.read_bytes(), accepted_plan_bytes)
        self.assertEqual(
            receipt["postimages"][
                ".planning/generated/dependency-observations.json"
            ],
            digest_ref(projection_path.read_bytes()),
        )
        self.assertEqual(
            receipt["observed_input_digests"],
            [digest_ref(candidate_path.read_bytes())],
        )
        receipt_path = (
            self.dependent.repo
            / "_ops/doc-warden/state/v2/receipts"
            / f"{operation_id}.json"
        )
        self.assertEqual(json.loads(receipt_path.read_bytes()), receipt)
        assert_plan_assumptions_current(
            self.dependent.repo,
            plan.artifact_id,
        )
        replay = apply_reconciliation(
            preview,
            confirmation_for(transaction),
        )
        self.assertEqual(replay, receipt)
        receipts_before_noop = sorted(
            path.name
            for path in receipt_path.parent.glob("*.json")
        )
        second = reconcile(
            self.dependent.repo,
            observations=candidate_path,
            operation_id=self.dependent.id_for(
                "revision-refresh-noop-operation"
            ),
        )
        self.assertEqual(second.status, "conformant")
        self.assertEqual(second.classifications, ())
        self.assertEqual(second.safe_updates, ())
        self.assertEqual(second.unsafe_findings, ())
        self.assertIsNone(second.transaction)
        self.assertEqual(load_dependency_snapshot(projection_path), refreshed)
        self.assertEqual(
            sorted(
                path.name
                for path in receipt_path.parent.glob("*.json")
            ),
            receipts_before_noop,
        )

    def test_revision_only_refresh_refuses_ambiguous_untrusted_evidence(self):
        target_id = f"REPO-{self.owner.repository_key}"
        evidence = {
            "method": "ambiguous_candidates",
            "prior_target_id": target_id,
            "candidate_target_ids": [target_id, f"{target_id}-OTHER"],
            "content_digest": "sha256:" + "a" * 64,
        }
        plan, assumption, evidence, old_projection = (
            self.accepted_dependency_state(evidence)
        )
        projection_path = self.persist_dependency_projection(old_projection)
        current_revision = self.advance_dependent_head(
            "advance-for-ambiguous-refresh"
        )
        _, candidate_path = self.current_dependency_candidate(
            plan,
            assumption,
            evidence,
            current_revision,
            "ambiguous-refresh-observations",
        )
        preview = reconcile(
            self.dependent.repo,
            observations=candidate_path,
            operation_id=self.dependent.id_for(
                "ambiguous-refresh-operation"
            ),
        )
        self.assertEqual(preview.status, "review_required")
        self.assertIsNone(preview.transaction)
        self.assertEqual(
            {row["classification"] for row in preview.unsafe_findings},
            {"stale"},
        )
        self.assertEqual(
            load_dependency_snapshot(projection_path),
            old_projection,
        )

    def test_revision_only_refresh_refuses_missing_unsafe_observation(self):
        plan, _, _, old_projection = self.accepted_dependency_state()
        projection_path = self.persist_dependency_projection(old_projection)
        current_revision = self.advance_dependent_head(
            "advance-for-missing-refresh"
        )
        candidate = DependencySnapshot(
            schema="doc-warden/dependency-snapshot/v1",
            repository_key=self.dependent.repository_key,
            source_revision=current_revision,
            observed_at="2026-09-01T01:10:00Z",
            authority="observed",
            nodes=(),
            edges=(),
        )
        candidate_path = Path(self.machine.name) / "missing-observations.json"
        candidate_path.write_bytes(dependency_snapshot_bytes(candidate))
        preview = reconcile(
            self.dependent.repo,
            observations=candidate_path,
            operation_id=self.dependent.id_for(
                "missing-refresh-operation"
            ),
        )
        self.assertEqual(preview.status, "review_required")
        self.assertIsNone(preview.transaction)
        self.assertEqual(
            {row["classification"] for row in preview.unsafe_findings},
            {"dangling"},
        )
        self.assertEqual(
            load_dependency_snapshot(projection_path),
            old_projection,
        )

    def test_revision_only_refresh_refuses_cyclic_graph(self):
        plan, assumption, evidence, old_projection = (
            self.accepted_dependency_state()
        )
        projection_path = self.persist_dependency_projection(old_projection)
        current_revision = self.advance_dependent_head(
            "advance-for-cyclic-refresh"
        )
        first = new_roadmap_item(
            repository_key=self.dependent.repository_key,
            item_id="ROAD-REFRESH-A",
            outcome="First refresh cycle node",
        )
        second = new_roadmap_item(
            repository_key=self.dependent.repository_key,
            item_id="ROAD-REFRESH-B",
            outcome="Second refresh cycle node",
            sequence=2,
        )
        first["dependencies"]["planned"] = [second["id"]]
        second["dependencies"]["planned"] = [first["id"]]
        (
            self.dependent.repo / ".planning/ROADMAP.md"
        ).write_bytes(render_roadmap([first, second]))
        _, candidate_path = self.current_dependency_candidate(
            plan,
            assumption,
            evidence,
            current_revision,
            "cyclic-refresh-observations",
        )
        preview = reconcile(
            self.dependent.repo,
            observations=candidate_path,
            operation_id=self.dependent.id_for(
                "cyclic-refresh-operation"
            ),
        )
        self.assertEqual(preview.status, "blocked")
        self.assertIsNone(preview.transaction)
        self.assertEqual(
            preview.graph.cycles,
            (("ROAD-REFRESH-A", "ROAD-REFRESH-B", "ROAD-REFRESH-A"),),
        )
        self.assertEqual(
            load_dependency_snapshot(projection_path),
            old_projection,
        )

    def test_roadmap_planned_and_observed_edges_remain_separate(self):
        item = new_roadmap_item(
            repository_key=self.dependent.repository_key,
            item_id="ROAD-DEPENDENT",
            outcome="Keep authorities separate",
        )
        item["dependencies"]["planned"] = ["ROAD-PLANNED"]
        item["dependencies"]["observed"] = ["ROAD-OBSERVED"]
        (
            self.dependent.repo / ".planning/ROADMAP.md"
        ).write_bytes(render_roadmap([item]))
        graph = resolve_graph((self.dependent.repo,))
        self.assertEqual(
            [
                (edge.relation, edge.target_id)
                for edge in graph.planned_relations
                if edge.source_id == "ROAD-DEPENDENT"
            ],
            [("depends_on_planned", "ROAD-PLANNED")],
        )
        self.assertEqual(
            [
                (edge.relation, edge.target_id)
                for edge in graph.observed_relations
                if edge.source_id == "ROAD-DEPENDENT"
            ],
            [("depends_on_observed", "ROAD-OBSERVED")],
        )

    def test_cycle_blocks_typed_safe_projection(self):
        revision = self.head(self.dependent.repo)
        plan = self.persist_plan_with_relations(
            [
                self.relation(
                    source_id="placeholder",
                    target_id="SYMBOL-CYCLE-OLD",
                    target_kind="symbol",
                    authority="planned",
                    relation="affects_code",
                    repository_key=self.dependent.repository_key,
                    revision=revision,
                    path="src/cycle_old.py",
                    symbol="package.cycle",
                )
            ]
        )
        first = new_roadmap_item(
            repository_key=self.dependent.repository_key,
            item_id="ROAD-CYCLE-A",
            outcome="First cycle node",
        )
        second = new_roadmap_item(
            repository_key=self.dependent.repository_key,
            item_id="ROAD-CYCLE-B",
            outcome="Second cycle node",
            sequence=2,
        )
        first["dependencies"]["planned"] = [second["id"]]
        second["dependencies"]["planned"] = [first["id"]]
        (
            self.dependent.repo / ".planning/ROADMAP.md"
        ).write_bytes(render_roadmap([first, second]))
        source = GraphNode(
            id=plan.artifact_id,
            kind="plan",
            repository_key=self.dependent.repository_key,
            version=1,
            lifecycle="active",
            revision=revision,
            provider_revision=None,
            available=True,
        )
        target = GraphNode(
            id="SYMBOL-CYCLE-NEW",
            kind="symbol",
            repository_key=self.dependent.repository_key,
            version=None,
            lifecycle="active",
            revision=revision,
            provider_revision=None,
            available=True,
        )
        edge = DependencyEdge.from_record(
            self.relation(
                source_id=plan.artifact_id,
                target_id=target.id,
                target_kind="symbol",
                authority="observed",
                relation="affects_code",
                repository_key=self.dependent.repository_key,
                revision=revision,
                path="src/cycle_new.py",
                symbol="package.cycle",
                match_evidence={
                    "method": "exact_symbol_digest",
                    "prior_target_id": "SYMBOL-CYCLE-OLD",
                    "candidate_target_ids": [target.id],
                    "symbol": "package.cycle",
                    "content_digest": "sha256:" + "f" * 64,
                },
            )
        )
        candidate = DependencySnapshot(
            schema="doc-warden/dependency-snapshot/v1",
            repository_key=self.dependent.repository_key,
            source_revision=revision,
            observed_at="2026-08-31T20:05:00Z",
            authority="observed",
            nodes=(source, target),
            edges=(edge,),
        )
        path = Path(self.machine.name) / "cycle-observations.json"
        path.write_bytes(dependency_snapshot_bytes(candidate))
        preview = reconcile(
            self.dependent.repo,
            observations=path,
            operation_id=self.dependent.id_for(
                "cycle-reconciliation-operation"
            ),
        )
        self.assertEqual(preview.status, "blocked")
        self.assertIsNone(preview.transaction)
        self.assertEqual(preview.safe_updates, ())
        self.assertEqual(
            preview.graph.cycles,
            (("ROAD-CYCLE-A", "ROAD-CYCLE-B", "ROAD-CYCLE-A"),),
        )

    def test_real_wrapper_reconciles_safe_rows_once_and_preserves_unsafe_rows(self):
        revision = self.head(self.dependent.repo)
        placeholder = "placeholder"
        planned_relations = [
            self.relation(
                source_id=placeholder,
                target_id="SYMBOL-OLD",
                target_kind="symbol",
                authority="planned",
                relation="affects_code",
                repository_key=self.dependent.repository_key,
                revision=revision,
                path="src/old.py",
                symbol="package.function",
            ),
            self.relation(
                source_id=placeholder,
                target_id="SYMBOL-AMBIGUOUS-OLD",
                target_kind="symbol",
                authority="planned",
                relation="affects_code",
                repository_key=self.dependent.repository_key,
                revision=revision,
                path="src/ambiguous_old.py",
                symbol="package.ambiguous",
            ),
            self.relation(
                source_id=placeholder,
                target_id="REPO-UNAVAILABLE",
                target_kind="repository",
                authority="planned",
                relation="depends_on_planned",
                repository_key=self.dependent.id_for(
                    "unavailable-repository-key"
                ),
                revision=revision,
            ),
        ]
        plan = self.persist_plan_with_relations(planned_relations)

        source = GraphNode(
            id=plan.artifact_id,
            kind="plan",
            repository_key=self.dependent.repository_key,
            version=1,
            lifecycle="active",
            revision=revision,
            provider_revision=None,
            available=True,
        )
        exact_target = GraphNode(
            id="SYMBOL-NEW",
            kind="symbol",
            repository_key=self.dependent.repository_key,
            version=None,
            lifecycle="active",
            revision=revision,
            provider_revision=None,
            available=True,
        )
        ambiguous_target = GraphNode(
            id="SYMBOL-AMBIGUOUS-NEW",
            kind="symbol",
            repository_key=self.dependent.repository_key,
            version=None,
            lifecycle="active",
            revision=revision,
            provider_revision=None,
            available=True,
        )
        unavailable_target = GraphNode(
            id="REPO-UNAVAILABLE",
            kind="repository",
            repository_key=self.dependent.id_for(
                "unavailable-repository-key"
            ),
            version=None,
            lifecycle="unavailable",
            revision=None,
            provider_revision=None,
            available=False,
        )
        exact_evidence = {
            "method": "exact_symbol_digest",
            "prior_target_id": "SYMBOL-OLD",
            "candidate_target_ids": ["SYMBOL-NEW"],
            "symbol": "package.function",
            "content_digest": "sha256:" + "c" * 64,
        }
        ambiguous_evidence = {
            "method": "ambiguous_candidates",
            "prior_target_id": "SYMBOL-AMBIGUOUS-OLD",
            "candidate_target_ids": [
                "SYMBOL-AMBIGUOUS-NEW",
                "SYMBOL-AMBIGUOUS-OTHER",
            ],
            "symbol": "package.ambiguous",
            "content_digest": "sha256:" + "d" * 64,
        }
        observed_edges = (
            DependencyEdge.from_record(
                self.relation(
                    source_id=plan.artifact_id,
                    target_id=exact_target.id,
                    target_kind="symbol",
                    authority="observed",
                    relation="affects_code",
                    repository_key=self.dependent.repository_key,
                    revision=revision,
                    path="src/new.py",
                    symbol="package.function",
                    match_evidence=exact_evidence,
                )
            ),
            DependencyEdge.from_record(
                self.relation(
                    source_id=plan.artifact_id,
                    target_id=ambiguous_target.id,
                    target_kind="symbol",
                    authority="observed",
                    relation="affects_code",
                    repository_key=self.dependent.repository_key,
                    revision=revision,
                    path="src/ambiguous_new.py",
                    symbol="package.ambiguous",
                    match_evidence=ambiguous_evidence,
                )
            ),
            DependencyEdge.from_record(
                self.relation(
                    source_id=plan.artifact_id,
                    target_id=unavailable_target.id,
                    target_kind="repository",
                    authority="observed",
                    relation="depends_on_observed",
                    repository_key=unavailable_target.repository_key,
                    revision=revision,
                )
            ),
        )
        candidate = DependencySnapshot(
            schema="doc-warden/dependency-snapshot/v1",
            repository_key=self.dependent.repository_key,
            source_revision=revision,
            observed_at="2026-08-31T20:05:00Z",
            authority="observed",
            nodes=(source, exact_target, ambiguous_target, unavailable_target),
            edges=observed_edges,
        )
        candidate_path = Path(self.machine.name) / "candidate-observations.json"
        candidate_path.write_bytes(dependency_snapshot_bytes(candidate))

        first_operation = self.dependent.id_for(
            "first-reconciliation-operation"
        )
        first = self.run_cli(
            "reconcile",
            "--repo",
            str(self.dependent.repo),
            "--observations",
            str(candidate_path),
            "--operation-id",
            first_operation,
            "--preview",
        )
        first_payload = json.loads(first.stdout)
        self.assertEqual(first_payload["status"], "ready")
        self.assertEqual(first_payload["operation_id"], first_operation)
        self.assertEqual(
            [row["target_id"] for row in first_payload["safe_updates"]],
            ["SYMBOL-NEW"],
        )
        self.assertTrue(
            {"unmapped", "dangling"}
            <= {row["classification"] for row in first_payload["unsafe_findings"]}
        )
        self.assertTrue(first_payload["consent_required"])
        self.assertEqual(first_payload["consequence"], "structural")
        self.assertEqual(
            first_payload["observed_inputs"],
            [
                {
                    "path": str(candidate_path.resolve()),
                    "digest": digest_ref(candidate_path.read_bytes()),
                }
            ],
        )
        projection = self.dependent.repo / ".planning/generated/dependency-observations.json"
        self.assertFalse(projection.exists())

        now = datetime.now(timezone.utc)
        consent_path = Path(self.machine.name) / "consent.json"
        consent_path.write_bytes(
            canonical_json(
                {
                    "schema": "doc-warden/consent-envelope/v1",
                    "operation_id": first_payload["operation_id"],
                    "repository_key": first_payload["repository_key"],
                    "canonical_root": first_payload["canonical_root"],
                    "source_revision": first_payload["source_revision"],
                    "action_digest": first_payload["action_digest"],
                    "consequence_class": "structural",
                    "nonce": self.dependent.id_for(
                        "reconciliation-confirmation"
                    ),
                    "issued_at": now.isoformat(),
                    "expires_at": (now + timedelta(minutes=5)).isoformat(),
                    "choice": "apply",
                }
            )
        )
        applied = self.run_cli(
            "apply",
            "--operation-id",
            first_payload["operation_id"],
            "--action-digest",
            first_payload["action_digest"],
            "--consent-envelope",
            str(consent_path),
            check=False,
        )
        self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
        receipt = json.loads(applied.stdout)
        self.assertEqual(receipt["source_revision"], revision)
        self.assertEqual(receipt["action_digest"], first_payload["action_digest"])
        self.assertEqual(
            receipt["postimages"][".planning/generated/dependency-observations.json"],
            digest_ref(projection.read_bytes()),
        )
        self.assertEqual(
            receipt["observed_input_digests"],
            [digest_ref(candidate_path.read_bytes())],
        )
        self.assertNotIn(
            str(candidate_path.resolve()),
            canonical_json(receipt).decode("utf-8"),
        )
        self.assertEqual(
            json.loads(
                (
                    self.dependent.repo
                    / "_ops/doc-warden/state/v2/events"
                    / f"{receipt['event_id']}.json"
                ).read_text(encoding="utf-8")
            )["action_digest"],
            receipt["action_digest"],
        )
        persisted = load_dependency_snapshot(projection)
        self.assertEqual([edge.target_id for edge in persisted.edges], ["SYMBOL-NEW"])

        replay = self.run_cli(
            "apply",
            "--operation-id",
            first_payload["operation_id"],
            "--action-digest",
            first_payload["action_digest"],
            "--consent-envelope",
            str(consent_path),
        )
        self.assertEqual(json.loads(replay.stdout), receipt)

        second = self.run_cli(
            "reconcile",
            "--repo",
            str(self.dependent.repo),
            "--observations",
            str(candidate_path),
            "--operation-id",
            self.dependent.id_for("second-reconciliation-operation"),
            "--preview",
        )
        second_payload = json.loads(second.stdout)
        self.assertEqual(second_payload["status"], "review_required")
        self.assertEqual(second_payload["safe_updates"], [])
        self.assertNotIn("operation_id", second_payload)
        self.assertEqual(
            {row["classification"] for row in second_payload["unsafe_findings"]},
            {row["classification"] for row in first_payload["unsafe_findings"]},
        )
        persisted_again = load_dependency_snapshot(projection)
        self.assertEqual(persisted_again, persisted)
        self.assertNotIn(
            "SYMBOL-AMBIGUOUS-NEW",
            [edge.target_id for edge in persisted_again.edges],
        )
        self.assertNotIn(
            "REPO-UNAVAILABLE",
            [edge.target_id for edge in persisted_again.edges],
        )

        delivery = observe_delivery(
            receipt,
            repo=self.dependent.repo,
            delivery_commit="e" * 40,
            pull_request="PR-DRAFT",
        )
        self.assertEqual(delivery["transition"], "delivery_observed")
        self.assertEqual(delivery["prior_event_digest"], digest_ref(canonical_json(receipt)))
        self.assertTrue(
            (
                self.dependent.repo
                / "_ops/doc-warden/state/v2/events"
                / f"{delivery['event_id']}.json"
            ).is_file()
        )


if __name__ == "__main__":
    unittest.main()
