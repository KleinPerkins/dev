import json
import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from doc_warden.adrs import preview_adr_draft
from doc_warden.artifacts import _bindings, apply_preview, consent_for, draft_artifact
from doc_warden.canonical import canonical_json, digest_ref
from doc_warden.dependencies import (
    DependencyEdge,
    DependencySnapshot,
    GraphNode,
    PlanAssumption,
    PlanRefinementRequired,
    _assert_plan_parent_authority,
    assert_plan_assumptions_current,
    compare_plan_assumption,
    dependency_snapshot_bytes,
    plans_invalidated,
)
from doc_warden.gsd_adapter import (
    AuthoringResult,
    AuthoringScope,
    prepare_authoring_import,
    validate_authoring_result,
)
from doc_warden.transactions import (
    MutationAction,
    MutationRequest,
    ObservedInput,
    apply_transaction,
    confirmation_for,
    preview_transaction,
)
from fixture_factory import FixtureFactory


ROOT = Path(__file__).resolve().parents[4]
WRAPPER = ROOT / "_ops/bin/doc-warden.sh"


class PlanInvalidationTests(unittest.TestCase):
    def setUp(self):
        self.machine = tempfile.TemporaryDirectory(
            prefix="doc-warden-plan-invalidation-state-"
        )
        self.fixture = FixtureFactory.create("plan-invalidation")
        self.revision = subprocess.check_output(
            ["git", "-C", str(self.fixture.repo), "rev-parse", "HEAD"],
            text=True,
        ).strip()
        self.observation_counter = 0

    def tearDown(self):
        repo = self.fixture.repo
        self.fixture.cleanup()
        self.machine.cleanup()
        self.assertFalse(repo.exists())

    def assumption(self, kind, target_id, **overrides):
        values = {
            "schema": "doc-warden/plan-assumption/v1",
            "id": f"ASM-{self.fixture.id_for(kind + ':' + target_id)}",
            "kind": kind,
            "source_id": None,
            "target_id": target_id,
            "target_kind": kind,
            "version": 1,
            "digest": "sha256:" + "a" * 64,
            "repository_key": self.fixture.repository_key,
            "revision": self.revision,
            "provider_revision": None,
            "path": None,
            "symbol": None,
            "relation": None,
            "task_ids": ["M2-T03"],
            "requirement_ids": ["REQ-001"],
        }
        values.update(overrides)
        return values

    def accepted_plan_preview(
        self,
        assumptions,
        *,
        version=1,
        operation_label="accepted-plan-operation",
        relations=(),
        supersedes=None,
    ):
        requirement_ids = [
            assumption["target_id"]
            for assumption in assumptions
            if assumption["kind"] == "requirement"
        ]
        if not list((self.fixture.repo / ".planning/artifacts").glob("PRD-*.md")):
            self.fixture.approve_prd(*requirement_ids)
        return draft_artifact(
            "plan",
            {
                "title": "Accepted plan",
                "body": "# Accepted plan\n\nFrozen.",
                "version": version,
                "approved_prd": True,
                "lifecycle": "approved",
                "approval": {
                    "approved_by": "operator",
                    "approved_at": "2026-08-31T20:00:00Z",
                },
                **({"requirement_ids": requirement_ids} if requirement_ids else {}),
                "task_ids": ["M2-T03"],
                "assumptions": assumptions,
                "relations": list(relations),
                **({"supersedes": supersedes} if supersedes else {}),
            },
            repo=self.fixture.repo,
            operation_id=self.fixture.id_for(operation_label),
        )

    def persist_accepted_plan(self, assumptions):
        preview = self.accepted_plan_preview(assumptions)
        apply_preview(preview, consent_for(preview.transaction))
        return preview

    def persist_accepted_plan_with_sidecar_mutation(
        self,
        assumptions,
        mutate,
        *,
        operation_label="accepted-plan-operation",
    ):
        preview = self.accepted_plan_preview(assumptions, operation_label=operation_label)
        original = preview.transaction
        actions = []
        for action in original.actions:
            content = action.content
            if action.path.endswith(".governance.json"):
                sidecar = json.loads(content)
                mutate(sidecar)
                content = canonical_json(sidecar)
            actions.append(MutationAction(action.path, content, action.kind))
        transaction = preview_transaction(
            MutationRequest(
                repo=original.repo,
                repository_key=original.repository_key,
                github_repository_id=original.github_repository_id,
                transition=original.transition,
                actions=tuple(actions),
                bindings=original.bindings,
                operation_id=original.operation_id,
                observed_inputs=original.observed_inputs,
                consequential=original.consequential,
                require_write_enabled=original.require_write_enabled,
            )
        )
        apply_preview(transaction, consent_for(transaction))
        return preview

    def persist_approved_prd(
        self,
        requirements,
        *,
        label,
        version=1,
        supersedes=None,
    ):
        preview = draft_artifact(
            "prd",
            {
                "title": "Approved PRD",
                "version": version,
                "lifecycle": "approved",
                "approval": {
                    "approved_by": "operator",
                    "approved_at": "2026-08-31T20:00:00Z",
                },
                "requirements": requirements,
                "supersedes": supersedes,
            },
            repo=self.fixture.repo,
            operation_id=self.fixture.id_for(label),
        )
        apply_preview(preview, consent_for(preview.transaction))
        return preview

    def requirement_assumption(self, prd, requirement_id):
        path = self.fixture.repo / prd.artifact_path
        version = int(path.name.rsplit("-v", 1)[1].removesuffix(".md"))
        return self.assumption(
            "requirement",
            requirement_id,
            version=version,
            digest=digest_ref(path.read_bytes()),
        )

    def persist_drifting_code_plan(self):
        path = self.fixture.repo / "src/example.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE = 1\n", encoding="utf-8")
        plan = self.persist_accepted_plan(
            [
                self.assumption(
                    "code",
                    "CODE-example",
                    target_kind="symbol",
                    digest=digest_ref(path.read_bytes()),
                    path="src/example.py",
                    symbol="example.VALUE",
                )
            ]
        )
        path.write_text("VALUE = 2\n", encoding="utf-8")
        return plan

    def write_higher_version_sidecar(
        self,
        plan,
        *,
        filename=None,
        root=".planning/artifacts",
        mutate=None,
        write_plan=True,
    ):
        candidate = self.accepted_plan_preview([], version=2)
        self.assertEqual(candidate.artifact_id, plan.artifact_id)
        plan_action = next(
            action
            for action in candidate.transaction.actions
            if action.path.endswith(".md")
        )
        sidecar_action = next(
            action
            for action in candidate.transaction.actions
            if action.path.endswith(".governance.json")
        )
        if write_plan:
            plan_path = self.fixture.repo / plan_action.path
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_bytes(plan_action.content)
        sidecar = json.loads(sidecar_action.content)
        if mutate is not None:
            mutate(sidecar)
        destination = (
            self.fixture.repo
            / root
            / (filename or Path(sidecar_action.path).name)
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(canonical_json(sidecar))
        return destination

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

    def validate_recomputed_legacy_preview(
        self,
        *,
        label,
        active_plan_id=None,
    ):
        arguments = [
            "prepare-authoring",
            "--repo",
            str(self.fixture.repo),
            "--operation-id",
            self.fixture.id_for(label),
        ]
        if active_plan_id is not None:
            arguments.extend(("--active-plan", active_plan_id))
        prepared = self.run_cli(*arguments)
        payload = json.loads(prepared.stdout)
        payload.pop("preview_digest")
        payload.pop("active_plan_id")
        payload["preview_digest"] = digest_ref(canonical_json(payload))
        preview_path = self.fixture.repo / f"{label}-preview.json"
        preview_path.write_bytes(canonical_json(payload))
        output = self.fixture.repo / ".planning/STATE.md"
        output.write_text("state\n", encoding="utf-8")
        result_path = self.fixture.repo / f"{label}-result.json"
        result_path.write_bytes(
            canonical_json(
                {
                    "source_revision": payload["source_revision"],
                    "pin_digest": payload["pin_digest"],
                    "changed_file_digests": {
                        ".planning/STATE.md": digest_ref(output.read_bytes())
                    },
                    "checker_passed": True,
                    "commands": [],
                    "assumptions_changed": False,
                }
            )
        )
        return self.run_cli(
            "validate-authoring",
            "--repo",
            str(self.fixture.repo),
            "--preview",
            str(preview_path),
            "--result",
            str(result_path),
            check=False,
        )

    def dependency_assumption(self):
        return self.assumption(
            "dependency",
            "REPO-DEPENDENCY",
            source_id="PLAN-SOURCE",
            target_kind="repository",
            relation="depends_on_planned",
        )

    def observed_dependency_edge(self, assumption, **overrides):
        values = {
            "source_id": assumption["source_id"],
            "source_kind": "plan",
            "source_version": 1,
            "relation": "depends_on_observed",
            "target_id": assumption["target_id"],
            "target_kind": assumption["target_kind"],
            "target_version": assumption["version"],
            "authority": "observed",
            "lifecycle": "active",
            "observed_revision": assumption["revision"],
            "provider_revision": assumption["provider_revision"],
            "target_anchor": None,
            "match_evidence": {
                "method": "exact_content_digest",
                "prior_target_id": assumption["target_id"],
                "candidate_target_ids": [assumption["target_id"]],
                "content_digest": assumption["digest"],
            },
            "assumption_id": None,
            "affected_plan_ids": (),
            "affected_task_ids": (),
            "affected_requirement_ids": (),
        }
        values.update(overrides)
        return DependencyEdge(**values)

    def write_dependency_observation(
        self,
        edges,
        *,
        source_revision=None,
        observed_at="2026-08-31T20:05:00Z",
        receipt=True,
    ):
        if receipt:
            self.observation_counter += 1
            return self.apply_dependency_observation(
                edges,
                operation_label=(
                    "dependency-observation-"
                    f"{self.observation_counter}"
                ),
                source_revision=source_revision,
                observed_at=observed_at,
            )
        observation = DependencySnapshot(
            schema="doc-warden/dependency-snapshot/v1",
            repository_key=self.fixture.repository_key,
            source_revision=source_revision or self.revision,
            observed_at=observed_at,
            authority="observed",
            nodes=(),
            edges=tuple(edges),
        )
        projection = (
            self.fixture.repo
            / ".planning/generated/dependency-observations.json"
        )
        projection.parent.mkdir(parents=True, exist_ok=True)
        projection.write_bytes(dependency_snapshot_bytes(observation))
        return projection

    def apply_dependency_observation(
        self,
        edges,
        *,
        operation_label,
        transition="projection_update",
        receipt_target=".planning/generated/dependency-observations.json",
        source_revision=None,
        observed_at="2026-08-31T20:05:00Z",
    ):
        observation = DependencySnapshot(
            schema="doc-warden/dependency-snapshot/v1",
            repository_key=self.fixture.repository_key,
            source_revision=source_revision or self.revision,
            observed_at=observed_at,
            authority="observed",
            nodes=(),
            edges=tuple(edges),
        )
        content = dependency_snapshot_bytes(observation)
        projection_relative = (
            ".planning/generated/dependency-observations.json"
        )
        action_content = (
            content
            if receipt_target == projection_relative
            else canonical_json({"projection": "other"})
        )
        observed_input = Path(self.machine.name) / f"{operation_label}.json"
        observed_input.write_bytes(content)
        transaction = preview_transaction(
            MutationRequest(
                repo=self.fixture.repo,
                repository_key=self.fixture.repository_key,
                github_repository_id=None,
                transition=transition,
                actions=(
                    MutationAction(receipt_target, action_content),
                ),
                bindings=_bindings(self.fixture.repo),
                operation_id=self.fixture.id_for(operation_label),
                observed_inputs=(
                    ObservedInput(
                        path=str(observed_input.resolve(strict=True)),
                        digest=digest_ref(content),
                    ),
                ),
                consequential=True,
                require_write_enabled=True,
            )
        )
        apply_transaction(transaction, confirmation_for(transaction))
        projection = self.fixture.repo / projection_relative
        if receipt_target != projection_relative:
            projection.parent.mkdir(parents=True, exist_ok=True)
            projection.write_bytes(content)
        return projection

    def validate_active_plan(self, plan, label):
        preview = prepare_authoring_import(
            AuthoringScope(
                repo=self.fixture.repo,
                operation_id=self.fixture.id_for(label),
                active_plan_id=plan.artifact_id,
            )
        )
        return validate_authoring_result(
            preview,
            AuthoringResult(
                source_revision=preview.source_revision,
                pin_digest=preview.pin_digest,
                outputs={".planning/STATE.md": b"state\n"},
                checker_passed=True,
            ),
        )

    def assert_plan_refinement(self, plan, label):
        with self.assertRaises(PlanRefinementRequired) as raised:
            self.validate_active_plan(plan, label)
        record = raised.exception.refinements[0].record()
        self.assertEqual(record["classification"], "changed-assumption")
        self.assertIn("digest", record["changed_assumption"]["changed_fields"])
        self.assertIsNone(
            record["changed_assumption"]["observed_binding"]["digest"]
        )
        return record

    def test_accepted_plan_sidecar_binds_every_required_assumption_kind(self):
        prd = self.persist_approved_prd(
            [{"id": "REQ-001", "statement": "Keep a current requirement binding."}], label="matrix-prd",
        )
        assumptions = [
            self.requirement_assumption(prd, "REQ-001"),
            self.assumption("design", "DESIGN-1", target_kind="design"),
            self.assumption("adr", "ADR-1", target_kind="adr"),
            self.assumption(
                "dependency",
                "REPO-DEPENDENCY",
                source_id="PLAN-SOURCE",
                target_kind="repository",
                relation="depends_on_planned",
            ),
            self.assumption(
                "code",
                "CODE-1",
                target_kind="symbol",
                path="src/example.py",
                symbol="package.example",
            ),
            self.assumption(
                "schema",
                "SCHEMA-1",
                target_kind="schema",
                path="schemas/example.json",
            ),
        ]
        preview = self.persist_accepted_plan(assumptions)
        sidecar_action = next(
            action
            for action in preview.transaction.actions
            if action.path.endswith(".governance.json")
        )
        sidecar = json.loads(sidecar_action.content)
        self.assertTrue(sidecar["accepted"])
        self.assertEqual(sidecar["task_ids"], ["M2-T03"])
        self.assertEqual(
            {item["kind"] for item in sidecar["assumptions"]},
            {"requirement", "design", "adr", "dependency", "code", "schema"},
        )

    def test_typed_predecessor_retirement_refuses_current_plan_use(self):
        repo = self.fixture.repo
        original = self.persist_accepted_plan([])
        label = "continuation-of-accepted-plan"
        operation_id = self.fixture.id_for(label)
        plan_suffix = uuid.uuid5(uuid.UUID(operation_id), "plan")
        continuation_id = f"PLAN-{self.fixture.repository_key}-{plan_suffix}"
        plan_parent = {
            "schema": "doc-warden/relation/v2",
            "relation": "derives_from",
            "source_id": continuation_id,
            "source_kind": "plan",
            "source_version": 1,
            "target": {"kind": "plan", "id": original.artifact_id, "version": 1},
            "authority": "planned",
            "lifecycle": "active",
            "observed_at": "2026-08-31T20:00:00Z",
            "observed_revision": self.revision,
            "provenance": [{"digest": digest_ref((repo / original.artifact_path).read_bytes())}],
        }
        continuation = self.accepted_plan_preview([], operation_label=label, relations=(plan_parent,))
        apply_preview(continuation, consent_for(continuation.transaction))
        assert_plan_assumptions_current(repo, continuation.artifact_id)
        frozen = {action.path: (repo / action.path).read_bytes() for action in continuation.transaction.actions}

        successor = self.accepted_plan_preview(
            [], version=2, operation_label="parent-successor", supersedes=original.artifact_id,
        )
        apply_preview(successor, consent_for(successor.transaction))
        with self.assertRaisesRegex(ValueError, "^plan_parent_authority_changed$"):
            assert_plan_assumptions_current(repo, continuation.artifact_id)
        self.assertEqual({path: (repo / path).read_bytes() for path in frozen}, frozen)

    def test_parent_guard_refuses_bytes_outside_the_receipted_digest(self):
        repo = self.fixture.repo
        continuation = self.persist_accepted_plan([])
        body_path = repo / continuation.artifact_path
        sidecar_action = next(action for action in continuation.transaction.actions if action.path.endswith(".governance.json"))
        sidecar = json.loads(sidecar_action.content)
        original = body_path.read_bytes()
        alternate = original + b"\nTransient content."
        # A current parentless plan passes. A read that returns different bytes
        # fails exact binding even though the alternate artifact still parses.
        _assert_plan_parent_authority(repo, sidecar)
        read_bytes = Path.read_bytes
        reads = []

        def transient_read(path):
            if path == body_path:
                reads.append(path)
                return alternate
            return read_bytes(path)

        with patch.object(Path, "read_bytes", transient_read):
            with self.assertRaisesRegex(ValueError, "^plan_assumption_authority_invalid$"):
                _assert_plan_parent_authority(repo, sidecar)
        self.assertEqual(reads, [body_path])
        self.assertEqual(body_path.read_bytes(), original)

    def test_governing_decision_requires_its_plan_parent_at_draft_and_live_use(self):
        repo = self.fixture.repo
        predecessor = self.persist_accepted_plan([])
        digest = digest_ref((repo / predecessor.artifact_path).read_bytes())
        decision_body = "# Continuation decision\n\nThe fixture continues an accepted plan.\n"
        decision = preview_adr_draft({
            "title": "Continuation decision", "body": decision_body,
            "approval": {
                "actor": "fixture", "date": "2026-08-31",
                "review_sha256": digest_ref(decision_body.encode())[7:],
            },
            "parents": {
                "observed_at": "2026-08-31T20:00:00Z",
                "parents": [{"kind": "plan", "id": predecessor.artifact_id, "version": 1, "digest": digest}],
            },
        }, repo=repo)
        apply_preview(decision, consent_for(decision.transaction))
        options = {
            "title": "Continuation lacking a required predecessor",
            "body": "# Governed continuation\n",
            "lifecycle": "approved",
            "approval": {"approved_by": "operator", "approved_at": "2026-08-31T20:00:00Z"},
            "approved_prd": True,
            "rigor_signals": {"sensitive": True},
            "sensitive_adr_id": decision.artifact_id,
        }
        with self.assertRaisesRegex(ValueError, "^plan_parent_binding_missing$"):
            draft_artifact("plan", options, repo=repo)
        # Reproduce legacy receipt-backed input admitted before the draft check existed.
        with patch("doc_warden.artifacts.require_decision_plan_parents"):
            legacy = draft_artifact("plan", options, repo=repo)
        apply_preview(legacy, consent_for(legacy.transaction))
        with self.assertRaisesRegex(ValueError, "^plan_parent_binding_missing$"):
            assert_plan_assumptions_current(repo, legacy.artifact_id)

    def test_receipted_legacy_sidecar_without_m2_fields_remains_valid(self):
        def remove_m2_fields(sidecar):
            sidecar.pop("task_ids")
            sidecar.pop("assumptions")

        plan = self.persist_accepted_plan_with_sidecar_mutation(
            [],
            remove_m2_fields,
        )

        assert_plan_assumptions_current(
            self.fixture.repo,
            plan.artifact_id,
        )

    def test_receipted_sidecar_rejects_malformed_present_m2_fields(self):
        def corrupt_m2_fields(sidecar):
            sidecar["task_ids"] = "M2-T03"
            sidecar["assumptions"] = {}

        plan = self.persist_accepted_plan_with_sidecar_mutation(
            [],
            corrupt_m2_fields,
        )

        with self.assertRaisesRegex(
            ValueError,
            "^plan_assumption_authority_invalid$",
        ):
            assert_plan_assumptions_current(
                self.fixture.repo,
                plan.artifact_id,
            )

    def test_orphaned_unrelated_plan_sidecar_does_not_block_active_plan(self):
        active_plan = self.persist_accepted_plan([])
        unrelated_plan = self.accepted_plan_preview(
            [],
            operation_label="unrelated-accepted-plan-operation",
        )
        apply_preview(
            unrelated_plan,
            consent_for(unrelated_plan.transaction),
        )
        unrelated_sidecar = next(
            action
            for action in unrelated_plan.transaction.actions
            if action.path.endswith(".governance.json")
        )
        self.assertNotEqual(active_plan.artifact_id, unrelated_plan.artifact_id)
        self.assertTrue((self.fixture.repo / unrelated_sidecar.path).is_file())
        (self.fixture.repo / unrelated_plan.artifact_path).unlink()

        assert_plan_assumptions_current(
            self.fixture.repo,
            active_plan.artifact_id,
        )

    def test_noncanonical_requested_plan_sidecar_remains_invalid(self):
        plan = self.persist_accepted_plan([])
        sidecar = next(
            action
            for action in plan.transaction.actions
            if action.path.endswith(".governance.json")
        )
        sidecar_path = self.fixture.repo / sidecar.path
        sidecar_path.write_bytes(sidecar_path.read_bytes() + b" ")

        with self.assertRaisesRegex(
            ValueError,
            "^plan_assumption_authority_invalid$",
        ):
            assert_plan_assumptions_current(
                self.fixture.repo,
                plan.artifact_id,
            )

    def test_changed_binding_matrix_emits_exact_smallest_refinement(self):
        expected_actions = {
            "requirement": "create_successor_plan_rebinding_requirement",
            "design": "create_successor_plan_rebinding_design",
            "adr": "create_successor_plan_rebinding_adr",
            "dependency": "create_successor_plan_after_dependency_reconciliation",
            "code": "create_successor_plan_revalidating_code_precondition",
            "schema": "create_successor_plan_revalidating_schema_precondition",
        }
        findings = []
        for kind, action in expected_actions.items():
            assumption = PlanAssumption.from_record(
                self.assumption(kind, f"{kind.upper()}-1")
            )
            observed = {
                **assumption.binding(),
                "version": 2,
                "digest": "sha256:" + "b" * 64,
            }
            finding = compare_plan_assumption(
                assumption,
                observed,
                source_revision="b" * 40,
                plan_id="PLAN-1",
                plan_version=1,
            )
            self.assertIsNotNone(finding)
            self.assertEqual(finding.classification, "changed-assumption")
            findings.append(finding)
            refinement = plans_invalidated([finding])[0]
            record = refinement.record()
            self.assertEqual(record["changed_assumption"]["id"], assumption.id)
            self.assertEqual(record["affected_plans"], ["PLAN-1"])
            self.assertEqual(record["affected_tasks"], ["M2-T03"])
            self.assertEqual(record["affected_requirements"], ["REQ-001"])
            self.assertEqual(record["smallest_successor_action"], action)

    def test_missing_bound_artifact_requires_plan_refinement(self):
        plan = self.persist_accepted_plan(
            [self.assumption("design", "DESIGN-MISSING", target_kind="design")]
        )
        self.assert_plan_refinement(plan, "missing-artifact-authoring-operation")

    def test_missing_dependency_projection_requires_plan_refinement(self):
        plan = self.persist_accepted_plan([self.dependency_assumption()])
        self.assert_plan_refinement(plan, "missing-projection-authoring-operation")

    def test_missing_active_plan_id_cannot_bypass_accepted_assumptions(self):
        self.persist_drifting_code_plan()
        preview = prepare_authoring_import(
            AuthoringScope(
                repo=self.fixture.repo,
                operation_id=self.fixture.id_for(
                    "missing-active-plan-authoring-operation"
                ),
            )
        )
        with self.assertRaises(PlanRefinementRequired):
            validate_authoring_result(
                preview,
                AuthoringResult(
                    source_revision=preview.source_revision,
                    pin_digest=preview.pin_digest,
                    outputs={".planning/STATE.md": b"state\n"},
                    checker_passed=True,
                ),
            )

    def test_supplied_draft_plan_cannot_bypass_accepted_assumptions(self):
        self.persist_drifting_code_plan()
        draft = draft_artifact(
            "plan",
            {
                "title": "Draft plan",
                "approved_prd": True,
            },
            repo=self.fixture.repo,
            operation_id=self.fixture.id_for("draft-plan-operation"),
        )
        apply_preview(draft, consent_for(draft.transaction))
        preview = prepare_authoring_import(
            AuthoringScope(
                repo=self.fixture.repo,
                operation_id=self.fixture.id_for(
                    "draft-active-plan-authoring-operation"
                ),
                active_plan_id=draft.artifact_id,
            )
        )
        with self.assertRaisesRegex(
            ValueError,
            "^active_plan_binding_not_accepted$",
        ):
            validate_authoring_result(
                preview,
                AuthoringResult(
                    source_revision=preview.source_revision,
                    pin_digest=preview.pin_digest,
                    outputs={".planning/STATE.md": b"state\n"},
                    checker_passed=True,
                ),
            )

    def test_accepted_empty_plan_cannot_mask_assumption_bearing_plan(self):
        self.persist_drifting_code_plan()
        empty = self.persist_accepted_plan_with_sidecar_mutation(
            [],
            lambda sidecar: sidecar.update(assumptions=[]),
            operation_label="accepted-empty-plan-operation",
        )
        preview = prepare_authoring_import(
            AuthoringScope(
                repo=self.fixture.repo,
                operation_id=self.fixture.id_for(
                    "empty-active-plan-authoring-operation"
                ),
                active_plan_id=empty.artifact_id,
            )
        )
        with self.assertRaisesRegex(
            ValueError,
            "^active_plan_binding_mismatch$",
        ):
            validate_authoring_result(
                preview,
                AuthoringResult(
                    source_revision=preview.source_revision,
                    pin_digest=preview.pin_digest,
                    outputs={".planning/STATE.md": b"state\n"},
                    checker_passed=True,
                ),
            )

    def test_missing_active_plan_id_blocks_ambiguous_assumption_authority(self):
        self.persist_drifting_code_plan()
        second = self.accepted_plan_preview(
            [self.dependency_assumption()],
            operation_label="second-assumption-plan-operation",
        )
        apply_preview(second, consent_for(second.transaction))
        preview = prepare_authoring_import(
            AuthoringScope(
                repo=self.fixture.repo,
                operation_id=self.fixture.id_for(
                    "ambiguous-active-plan-authoring-operation"
                ),
            )
        )
        with self.assertRaisesRegex(
            ValueError,
            "^active_plan_binding_ambiguous$",
        ):
            validate_authoring_result(
                preview,
                AuthoringResult(
                    source_revision=preview.source_revision,
                    pin_digest=preview.pin_digest,
                    outputs={".planning/STATE.md": b"state\n"},
                    checker_passed=True,
                ),
            )

    def test_stripped_recomputed_preview_cannot_downgrade_plan_gate(self):
        plan = self.persist_drifting_code_plan()
        result = self.validate_recomputed_legacy_preview(
            label="stripped-plan-preview-operation",
            active_plan_id=plan.artifact_id,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["code"],
            "plan_refinement_required",
        )

    def test_legacy_preview_remains_valid_without_assumption_bearing_plan(self):
        def remove_m2_fields(sidecar):
            sidecar.pop("task_ids")
            sidecar.pop("assumptions")

        self.persist_accepted_plan_with_sidecar_mutation(
            [],
            remove_m2_fields,
        )
        result = self.validate_recomputed_legacy_preview(
            label="legacy-preview-no-assumptions-operation",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dependency_observation_without_receipt_cannot_clear_assumption(self):
        assumption = self.dependency_assumption()
        plan = self.persist_accepted_plan([assumption])
        self.write_dependency_observation(
            (self.observed_dependency_edge(assumption),),
            receipt=False,
        )
        with self.assertRaises(PlanRefinementRequired):
            assert_plan_assumptions_current(
                self.fixture.repo,
                plan.artifact_id,
            )

    def test_external_asset_observation_without_receipt_cannot_clear_assumption(self):
        assumption = self.assumption(
            "dependency",
            "FIGMA-ASSET-NO-RECEIPT",
            source_id="DESIGN-1",
            target_kind="external_asset",
            relation="references_asset",
            provider_revision="figma-revision-1",
        )
        plan = self.persist_accepted_plan([assumption])
        self.write_dependency_observation(
            (
                self.observed_dependency_edge(
                    assumption,
                    relation="references_asset",
                    match_evidence={
                        "method": "exact_provider_revision",
                        "prior_target_id": assumption["target_id"],
                        "candidate_target_ids": [assumption["target_id"]],
                    },
                ),
            ),
            receipt=False,
        )
        with self.assertRaises(PlanRefinementRequired):
            assert_plan_assumptions_current(
                self.fixture.repo,
                plan.artifact_id,
            )

    def test_nonauthoritative_projection_receipts_cannot_clear_assumption(self):
        assumption = self.dependency_assumption()
        plan = self.persist_accepted_plan([assumption])
        edge = self.observed_dependency_edge(assumption)

        with self.subTest(authority="wrong-transition"):
            self.apply_dependency_observation(
                (edge,),
                operation_label="wrong-transition-projection-receipt",
                transition="draft_update",
                observed_at="2026-08-31T20:06:00Z",
            )
            with self.assertRaises(PlanRefinementRequired):
                assert_plan_assumptions_current(
                    self.fixture.repo,
                    plan.artifact_id,
                )

        with self.subTest(authority="wrong-target"):
            self.apply_dependency_observation(
                (edge,),
                operation_label="wrong-target-projection-receipt",
                receipt_target=".planning/generated/other.json",
                observed_at="2026-08-31T20:07:00Z",
            )
            with self.assertRaises(PlanRefinementRequired):
                assert_plan_assumptions_current(
                    self.fixture.repo,
                    plan.artifact_id,
                )

        with self.subTest(authority="forged-confirmation"):
            label = "forged-confirmation-projection-receipt"
            self.apply_dependency_observation(
                (edge,),
                operation_label=label,
                observed_at="2026-08-31T20:07:30Z",
            )
            receipt_path = (
                self.fixture.repo
                / "_ops/doc-warden/state/v2/receipts"
                / f"{self.fixture.id_for(label)}.json"
            )
            receipt = json.loads(receipt_path.read_bytes())
            receipt["confirmation_digest"] = "sha256:" + "f" * 64
            receipt_path.write_bytes(canonical_json(receipt))
            with self.assertRaises(PlanRefinementRequired):
                assert_plan_assumptions_current(
                    self.fixture.repo,
                    plan.artifact_id,
                )

        with self.subTest(authority="stale-postimage"):
            projection = self.apply_dependency_observation(
                (edge,),
                operation_label="stale-postimage-projection-receipt",
                observed_at="2026-08-31T20:08:00Z",
            )
            replacement = DependencySnapshot(
                schema="doc-warden/dependency-snapshot/v1",
                repository_key=self.fixture.repository_key,
                source_revision=self.revision,
                observed_at="2026-08-31T20:09:00Z",
                authority="observed",
                nodes=(),
                edges=(edge,),
            )
            projection.write_bytes(dependency_snapshot_bytes(replacement))
            with self.assertRaises(PlanRefinementRequired):
                assert_plan_assumptions_current(
                    self.fixture.repo,
                    plan.artifact_id,
                )

    def test_applied_projection_update_receipt_clears_assumption(self):
        assumption = self.dependency_assumption()
        plan = self.persist_accepted_plan([assumption])
        self.apply_dependency_observation(
            (self.observed_dependency_edge(assumption),),
            operation_label="valid-projection-update-receipt",
        )
        assert_plan_assumptions_current(
            self.fixture.repo,
            plan.artifact_id,
        )

    def test_receipted_dependency_observation_enriches_unspecified_selectors(self):
        assumption = self.assumption(
            "dependency",
            "REPO-DEPENDENCY",
            source_id=None,
            target_kind="repository",
            relation=None,
        )
        plan = self.persist_accepted_plan([assumption])
        self.write_dependency_observation(
            (
                self.observed_dependency_edge(
                    assumption,
                    source_id="PLAN-SOURCE",
                ),
            )
        )

        assert_plan_assumptions_current(
            self.fixture.repo,
            plan.artifact_id,
        )
        self.assertIsNotNone(
            self.validate_active_plan(
                plan,
                "enriched-dependency-authoring-operation",
            )
        )

    def test_non_null_dependency_selectors_still_detect_mismatch(self):
        assumption = PlanAssumption.from_record(self.dependency_assumption())
        for field, observed_value in (
            ("source_id", "PLAN-OTHER"),
            ("relation", "blocks"),
        ):
            with self.subTest(field=field):
                finding = compare_plan_assumption(
                    assumption,
                    {
                        **assumption.binding(),
                        field: observed_value,
                    },
                    source_revision=self.revision,
                    plan_id="PLAN-1",
                    plan_version=1,
                )
                self.assertIsNotNone(finding)
                self.assertEqual(
                    finding.evidence,
                    {
                        field: {
                            "accepted": assumption.binding()[field],
                            "observed": observed_value,
                        }
                    },
                )

    def test_unreadable_dependency_projection_requires_plan_refinement(self):
        plan = self.persist_accepted_plan([self.dependency_assumption()])
        projection = (
            self.fixture.repo
            / ".planning/generated/dependency-observations.json"
        )
        projection.parent.mkdir(parents=True, exist_ok=True)
        projection.write_bytes(b"not canonical json\n")
        self.assert_plan_refinement(
            plan, "unreadable-projection-authoring-operation"
        )

    def test_zero_matching_dependency_edges_requires_plan_refinement(self):
        plan = self.persist_accepted_plan([self.dependency_assumption()])
        self.write_dependency_observation(())
        self.assert_plan_refinement(plan, "zero-edge-authoring-operation")

    def test_ambiguous_dependency_edges_requires_plan_refinement(self):
        assumption = self.dependency_assumption()
        plan = self.persist_accepted_plan([assumption])
        self.write_dependency_observation(
            (
                self.observed_dependency_edge(assumption),
                self.observed_dependency_edge(
                    assumption,
                    provider_revision="ambiguous-provider-revision",
                ),
            )
        )
        self.assert_plan_refinement(plan, "ambiguous-edge-authoring-operation")

    def test_stale_dependency_projection_requires_plan_refinement(self):
        assumption = self.dependency_assumption()
        plan = self.persist_accepted_plan([assumption])
        self.write_dependency_observation(
            (self.observed_dependency_edge(assumption),),
            source_revision="f" * 40,
        )
        self.assert_plan_refinement(plan, "stale-projection-authoring-operation")

    def test_unique_current_dependency_binding_remains_valid(self):
        assumption = self.dependency_assumption()
        plan = self.persist_accepted_plan([assumption])
        self.write_dependency_observation(
            (self.observed_dependency_edge(assumption),)
        )
        self.assertIsNotNone(
            self.validate_active_plan(
                plan, "current-dependency-authoring-operation"
            )
        )

    def test_unique_current_requirement_binding_remains_valid(self):
        prd = self.persist_approved_prd(
            [{"id": "REQ-001", "statement": "Keep the binding stable."}],
            label="current-requirement-prd",
        )
        plan = self.persist_accepted_plan(
            [self.requirement_assumption(prd, "REQ-001")]
        )

        assert_plan_assumptions_current(
            self.fixture.repo,
            plan.artifact_id,
        )

    def test_requirement_authority_change_requires_plan_refinement(self):
        original = self.persist_approved_prd(
            [{"id": "REQ-001", "statement": "Use the original behavior."}],
            label="original-requirement-prd",
        )
        plan = self.persist_accepted_plan([])
        assert_plan_assumptions_current(self.fixture.repo, plan.artifact_id)
        successor = self.persist_approved_prd(
            [{"id": "REQ-001", "statement": "Use the changed behavior."}],
            label="successor-requirement-prd",
            version=2,
            supersedes=original.artifact_id,
        )

        with self.assertRaises(PlanRefinementRequired) as raised:
            assert_plan_assumptions_current(
                self.fixture.repo,
                plan.artifact_id,
            )
        record = raised.exception.refinements[0].record()
        successor_path = self.fixture.repo / successor.artifact_path
        self.assertEqual(
            record["changed_assumption"]["changed_fields"],
            ["digest", "version"],
        )
        self.assertEqual(
            record["changed_assumption"]["observed_binding"]["version"],
            2,
        )
        self.assertEqual(
            record["changed_assumption"]["observed_binding"]["digest"],
            digest_ref(successor_path.read_bytes()),
        )

    def test_malformed_higher_version_sidecar_cannot_bypass(self):
        plan = self.persist_drifting_code_plan()
        self.write_higher_version_sidecar(
            plan,
            mutate=lambda sidecar: sidecar.pop("canonical_plan_digest"),
            write_plan=False,
        )

        with self.assertRaises(ValueError):
            assert_plan_assumptions_current(
                self.fixture.repo,
                plan.artifact_id,
            )

    def test_wrong_name_higher_version_sidecar_cannot_bypass(self):
        plan = self.persist_drifting_code_plan()
        self.write_higher_version_sidecar(
            plan,
            filename="squatted-plan-authority.json",
        )

        with self.assertRaises(ValueError):
            assert_plan_assumptions_current(
                self.fixture.repo,
                plan.artifact_id,
            )

    def test_wrong_plan_digest_higher_version_sidecar_cannot_bypass(self):
        plan = self.persist_drifting_code_plan()
        self.write_higher_version_sidecar(
            plan,
            mutate=lambda sidecar: sidecar.update(
                {"canonical_plan_digest": "sha256:" + "f" * 64}
            ),
        )

        with self.assertRaises(ValueError):
            assert_plan_assumptions_current(
                self.fixture.repo,
                plan.artifact_id,
            )

    def test_unreceipted_higher_version_sidecar_cannot_bypass(self):
        plan = self.persist_drifting_code_plan()
        self.write_higher_version_sidecar(plan)

        with self.assertRaises(ValueError):
            assert_plan_assumptions_current(
                self.fixture.repo,
                plan.artifact_id,
            )

    def test_state_sidecar_cannot_bypass_canonical_accepted_authority(self):
        plan = self.persist_drifting_code_plan()
        self.write_higher_version_sidecar(
            plan,
            root="_ops/doc-warden/state/v2/plan-governance",
        )

        with self.assertRaises(ValueError):
            assert_plan_assumptions_current(
                self.fixture.repo,
                plan.artifact_id,
            )

    def test_exact_provider_revision_external_asset_remains_current(self):
        assumption = self.assumption(
            "dependency",
            "FIGMA-ASSET-CURRENT",
            source_id="DESIGN-1",
            target_kind="external_asset",
            relation="references_asset",
            provider_revision="figma-revision-1",
        )
        plan = self.persist_accepted_plan([assumption])
        self.write_dependency_observation(
            (
                self.observed_dependency_edge(
                    assumption,
                    relation="references_asset",
                    match_evidence={
                        "method": "exact_provider_revision",
                        "prior_target_id": assumption["target_id"],
                        "candidate_target_ids": [assumption["target_id"]],
                    },
                ),
            )
        )
        assert_plan_assumptions_current(
            self.fixture.repo,
            plan.artifact_id,
        )
        self.assertIsNotNone(
            self.validate_active_plan(
                plan,
                "current-external-asset-authoring-operation",
            )
        )

    def test_design_external_asset_projection_remains_current(self):
        assumption = self.assumption(
            "design",
            "FIGMA-DESIGN-ASSET-CURRENT",
            source_id="DESIGN-1",
            target_kind="external_asset",
            relation="references_asset",
            provider_revision="figma-revision-1",
        )
        plan = self.persist_accepted_plan([assumption])
        self.write_dependency_observation(
            (
                self.observed_dependency_edge(
                    assumption,
                    source_kind="design",
                    relation="references_asset",
                    match_evidence={
                        "method": "exact_provider_revision",
                        "prior_target_id": assumption["target_id"],
                        "candidate_target_ids": [assumption["target_id"]],
                    },
                ),
            )
        )

        assert_plan_assumptions_current(
            self.fixture.repo,
            plan.artifact_id,
        )

    def test_design_external_asset_real_binding_drift_is_precise(self):
        assumption = self.assumption(
            "design",
            "FIGMA-DESIGN-ASSET-DRIFTED",
            source_id="DESIGN-1",
            target_kind="external_asset",
            relation="references_asset",
            provider_revision="figma-revision-1",
        )
        plan = self.persist_accepted_plan([assumption])
        exact_revision = {
            "method": "exact_provider_revision",
            "prior_target_id": assumption["target_id"],
            "candidate_target_ids": [assumption["target_id"]],
        }
        changed_digest = {
            "method": "exact_content_digest",
            "prior_target_id": assumption["target_id"],
            "candidate_target_ids": [assumption["target_id"]],
            "content_digest": "sha256:" + "b" * 64,
        }
        for label, expected_fields, overrides in (
            (
                "provider_revision",
                ["provider_revision"],
                {
                    "provider_revision": "figma-revision-2",
                    "match_evidence": exact_revision,
                },
            ),
            ("version", ["version"], {
                "target_version": 2,
                "match_evidence": exact_revision,
            }),
            ("digest", ["digest"], {"match_evidence": changed_digest}),
        ):
            with self.subTest(label=label):
                self.write_dependency_observation(
                    (
                        self.observed_dependency_edge(
                            assumption,
                            source_kind="design",
                            relation="references_asset",
                            **overrides,
                        ),
                    )
                )
                with self.assertRaises(PlanRefinementRequired) as raised:
                    assert_plan_assumptions_current(
                        self.fixture.repo,
                        plan.artifact_id,
                    )
                record = raised.exception.refinements[0].record()
                self.assertEqual(
                    record["changed_assumption"]["changed_fields"],
                    expected_fields,
                )
                self.assertEqual(
                    record["smallest_successor_action"],
                    "create_successor_plan_rebinding_design",
                )
        self.assertEqual(
            record["changed_assumption"]["observed_binding"]["digest"],
            changed_digest["content_digest"],
        )

    def test_design_external_asset_ambiguous_or_untrusted_evidence_blocks(self):
        assumption = self.assumption(
            "design",
            "FIGMA-DESIGN-ASSET-UNRESOLVED",
            source_id="DESIGN-1",
            target_kind="external_asset",
            relation="references_asset",
            provider_revision="figma-revision-1",
        )
        plan = self.persist_accepted_plan([assumption])
        trusted = self.observed_dependency_edge(
            assumption,
            source_kind="design",
            relation="references_asset",
            match_evidence={
                "method": "exact_provider_revision",
                "prior_target_id": assumption["target_id"],
                "candidate_target_ids": [assumption["target_id"]],
            },
        )
        untrusted = self.observed_dependency_edge(
            assumption,
            source_kind="design",
            relation="references_asset",
            match_evidence={
                "method": "exact_provider_revision",
                "prior_target_id": assumption["target_id"],
                "candidate_target_ids": ["OTHER-ASSET"],
            },
        )
        for label, edges in (
            ("ambiguous", (trusted, trusted)),
            ("untrusted", (untrusted,)),
            (
                "source-mismatch",
                (
                    self.observed_dependency_edge(
                        assumption,
                        source_id="DESIGN-OTHER",
                        source_kind="design",
                        relation="references_asset",
                        match_evidence={
                            "method": "exact_provider_revision",
                            "prior_target_id": assumption["target_id"],
                            "candidate_target_ids": [assumption["target_id"]],
                        },
                    ),
                ),
            ),
            ("missing", ()),
        ):
            with self.subTest(label=label):
                self.write_dependency_observation(edges)
                with self.assertRaises(PlanRefinementRequired):
                    assert_plan_assumptions_current(
                        self.fixture.repo,
                        plan.artifact_id,
                    )

    def test_exact_provider_revision_external_asset_requires_usable_revision(self):
        assumption = self.assumption(
            "dependency",
            "FIGMA-ASSET-INVALID-REVISION",
            source_id="DESIGN-1",
            target_kind="external_asset",
            relation="references_asset",
            provider_revision="figma-revision-1",
        )
        plan = self.persist_accepted_plan([assumption])
        evidence = {
            "method": "exact_provider_revision",
            "prior_target_id": assumption["target_id"],
            "candidate_target_ids": [assumption["target_id"]],
        }
        for label, provider_revision in (
            ("missing", None),
            ("empty", ""),
            ("malformed", 42),
        ):
            with self.subTest(label=label):
                self.write_dependency_observation(
                    (
                        self.observed_dependency_edge(
                            assumption,
                            relation="references_asset",
                            provider_revision=provider_revision,
                            match_evidence=evidence,
                        ),
                    )
                )
                with self.assertRaises(PlanRefinementRequired):
                    assert_plan_assumptions_current(
                        self.fixture.repo,
                        plan.artifact_id,
                    )

    def test_unique_current_artifact_binding_remains_valid(self):
        design = draft_artifact(
            "design",
            {"title": "Current design"},
            repo=self.fixture.repo,
            operation_id=self.fixture.id_for("current-design-operation"),
        )
        apply_preview(design, consent_for(design.transaction))
        design_path = self.fixture.repo / design.artifact_path
        plan = self.persist_accepted_plan(
            [
                self.assumption(
                    "design",
                    design.artifact_id,
                    target_kind="design",
                    digest=digest_ref(design_path.read_bytes()),
                )
            ]
        )
        self.assertIsNotNone(
            self.validate_active_plan(
                plan, "current-artifact-authoring-operation"
            )
        )

    def test_unrelated_head_advance_with_stable_code_binding_remains_current(self):
        code = self.fixture.repo / "src/example.py"
        code.parent.mkdir(parents=True)
        code.write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "add", "src/example.py"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "commit", "-qm", "add code"],
            check=True,
        )
        self.revision = subprocess.check_output(
            ["git", "-C", str(self.fixture.repo), "rev-parse", "HEAD"],
            text=True,
        ).strip()
        plan = self.persist_accepted_plan(
            [
                self.assumption(
                    "code",
                    "CODE-example",
                    target_kind="symbol",
                    digest=digest_ref(code.read_bytes()),
                    path="src/example.py",
                    symbol="example.VALUE",
                )
            ]
        )
        accepted_revision = self.revision
        unrelated = self.fixture.repo / "unrelated.txt"
        unrelated.write_text("unrelated\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "add", "unrelated.txt"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.fixture.repo),
                "commit",
                "-qm",
                "advance unrelated head",
            ],
            check=True,
        )
        current_revision = subprocess.check_output(
            ["git", "-C", str(self.fixture.repo), "rev-parse", "HEAD"],
            text=True,
        ).strip()
        self.assertNotEqual(current_revision, accepted_revision)
        self.assertIsNotNone(
            self.validate_active_plan(
                plan,
                "revision-only-code-binding-authoring-operation",
            )
        )
        code.write_text("VALUE = 2\n", encoding="utf-8")
        with self.assertRaises(PlanRefinementRequired) as raised:
            self.validate_active_plan(
                plan,
                "changed-code-binding-after-head-advance-operation",
            )
        record = raised.exception.refinements[0].record()
        self.assertEqual(
            record["changed_assumption"]["changed_fields"],
            ["digest"],
        )
        self.assertEqual(
            record["changed_assumption"]["observed_binding"]["revision"],
            current_revision,
        )
        self.assertEqual(record["source_revision"], current_revision)

    def test_external_asset_provider_revision_invalidates_design_bound_plan(self):
        assumption = PlanAssumption.from_record(
            self.assumption(
                "dependency",
                "FIGMA-ASSET-1",
                source_id="DESIGN-1",
                target_kind="external_asset",
                relation="references_asset",
                provider_revision="figma-revision-1",
            )
        )
        finding = compare_plan_assumption(
            assumption,
            {
                **assumption.binding(),
                "provider_revision": "figma-revision-2",
            },
            source_revision=self.revision,
            plan_id="PLAN-1",
            plan_version=1,
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.classification, "changed-assumption")
        self.assertIn("provider_revision", finding.evidence)
        self.assertEqual(
            plans_invalidated([finding])[0].smallest_successor_action,
            "create_successor_plan_after_dependency_reconciliation",
        )

    def test_observed_external_asset_revision_blocks_authoring_import(self):
        assumption_record = self.assumption(
            "dependency",
            "FIGMA-ASSET-OBSERVED",
            source_id="DESIGN-1",
            target_kind="external_asset",
            relation="references_asset",
            provider_revision="figma-revision-1",
        )
        plan = self.persist_accepted_plan([assumption_record])
        preview = prepare_authoring_import(
            AuthoringScope(
                repo=self.fixture.repo,
                operation_id=self.fixture.id_for(
                    "external-asset-authoring-operation"
                ),
                active_plan_id=plan.artifact_id,
            )
        )
        observation = DependencySnapshot(
            schema="doc-warden/dependency-snapshot/v1",
            repository_key=self.fixture.repository_key,
            source_revision=self.revision,
            observed_at="2026-08-31T20:05:00Z",
            authority="observed",
            nodes=(
                GraphNode(
                    id="DESIGN-1",
                    kind="design",
                    repository_key=self.fixture.repository_key,
                    version=1,
                    lifecycle="active",
                    revision=self.revision,
                    provider_revision=None,
                    available=True,
                ),
                GraphNode(
                    id="FIGMA-ASSET-OBSERVED",
                    kind="external_asset",
                    repository_key=self.fixture.repository_key,
                    version=1,
                    lifecycle="active",
                    revision=self.revision,
                    provider_revision="figma-revision-2",
                    available=True,
                ),
            ),
            edges=(
                DependencyEdge(
                    source_id="DESIGN-1",
                    source_kind="design",
                    source_version=1,
                    relation="references_asset",
                    target_id="FIGMA-ASSET-OBSERVED",
                    target_kind="external_asset",
                    target_version=1,
                    authority="observed",
                    lifecycle="active",
                    observed_revision=self.revision,
                    provider_revision="figma-revision-2",
                    target_anchor=None,
                    match_evidence={
                        "method": "exact_provider_revision",
                        "prior_target_id": "FIGMA-ASSET-OBSERVED",
                        "candidate_target_ids": ["FIGMA-ASSET-OBSERVED"],
                    },
                    assumption_id=None,
                    affected_plan_ids=(),
                    affected_task_ids=(),
                    affected_requirement_ids=(),
                ),
            ),
        )
        self.apply_dependency_observation(
            observation.edges,
            operation_label="changed-external-asset-projection",
            observed_at=observation.observed_at,
        )
        result = AuthoringResult(
            source_revision=preview.source_revision,
            pin_digest=preview.pin_digest,
            outputs={".planning/STATE.md": b"state\n"},
            checker_passed=True,
        )
        with self.assertRaises(PlanRefinementRequired) as raised:
            validate_authoring_result(preview, result)
        record = raised.exception.refinements[0].record()
        self.assertEqual(
            record["changed_assumption"]["provider_revision"],
            "figma-revision-1",
        )
        self.assertIn(
            "provider_revision",
            record["changed_assumption"]["changed_fields"],
        )
        self.assertEqual(
            record["changed_assumption"]["changed_fields"],
            ["provider_revision"],
        )
        self.assertEqual(
            record["changed_assumption"]["observed_binding"]["provider_revision"],
            "figma-revision-2",
        )
        self.assertEqual(
            record["changed_assumption"]["observed_binding"]["digest"],
            assumption_record["digest"],
        )

    def test_changed_code_precondition_blocks_authoring_import_with_record(self):
        code = self.fixture.repo / "src/example.py"
        code.parent.mkdir(parents=True)
        code.write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "add", "src/example.py"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "commit", "-qm", "add code"],
            check=True,
        )
        self.revision = subprocess.check_output(
            ["git", "-C", str(self.fixture.repo), "rev-parse", "HEAD"],
            text=True,
        ).strip()
        assumption = self.assumption(
            "code",
            "CODE-example",
            target_kind="symbol",
            digest=digest_ref(code.read_bytes()),
            revision=self.revision,
            path="src/example.py",
            symbol="example.VALUE",
        )
        plan = self.persist_accepted_plan([assumption])
        preview = prepare_authoring_import(
            AuthoringScope(
                repo=self.fixture.repo,
                operation_id=self.fixture.id_for(
                    "direct-authoring-operation"
                ),
                active_plan_id=plan.artifact_id,
            )
        )
        code.write_text("VALUE = 2\n", encoding="utf-8")
        result = AuthoringResult(
            source_revision=preview.source_revision,
            pin_digest=preview.pin_digest,
            outputs={".planning/STATE.md": b"state\n"},
            checker_passed=True,
        )
        with self.assertRaises(PlanRefinementRequired) as raised:
            validate_authoring_result(preview, result)
        record = raised.exception.refinements[0].record()
        self.assertEqual(record["changed_assumption"]["path"], "src/example.py")
        self.assertEqual(record["affected_plans"], [plan.artifact_id])
        self.assertEqual(record["affected_tasks"], ["M2-T03"])
        self.assertEqual(
            record["smallest_successor_action"],
            "create_successor_plan_revalidating_code_precondition",
        )
        self.assertFalse((self.fixture.repo / ".planning/STATE.md").exists())

    def test_real_wrapper_returns_plan_refinement_before_import(self):
        code = self.fixture.repo / "schemas/example.json"
        code.parent.mkdir(parents=True)
        code.write_bytes(canonical_json({"version": 1}))
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "add", "schemas/example.json"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "commit", "-qm", "add schema"],
            check=True,
        )
        self.revision = subprocess.check_output(
            ["git", "-C", str(self.fixture.repo), "rev-parse", "HEAD"],
            text=True,
        ).strip()
        plan = self.persist_accepted_plan(
            [
                self.assumption(
                    "schema",
                    "SCHEMA-example",
                    target_kind="schema",
                    digest=digest_ref(code.read_bytes()),
                    revision=self.revision,
                    path="schemas/example.json",
                )
            ]
        )
        operation_id = self.fixture.id_for("cli-authoring-operation")
        prepared = self.run_cli(
            "prepare-authoring",
            "--repo",
            str(self.fixture.repo),
            "--operation-id",
            operation_id,
            "--active-plan",
            plan.artifact_id,
        )
        preview_path = self.fixture.repo / "authoring-preview.json"
        preview_path.write_text(prepared.stdout, encoding="utf-8")
        code.write_bytes(canonical_json({"version": 2}))
        output = self.fixture.repo / ".planning/STATE.md"
        output.write_text("state\n", encoding="utf-8")
        prepared_record = json.loads(prepared.stdout)
        result_path = self.fixture.repo / "authoring-result.json"
        result_path.write_bytes(
            canonical_json(
                {
                    "source_revision": prepared_record["source_revision"],
                    "pin_digest": prepared_record["pin_digest"],
                    "changed_file_digests": {
                        ".planning/STATE.md": digest_ref(output.read_bytes())
                    },
                    "checker_passed": True,
                    "commands": [],
                    "assumptions_changed": False,
                }
            )
        )
        result = self.run_cli(
            "validate-authoring",
            "--repo",
            str(self.fixture.repo),
            "--preview",
            str(preview_path),
            "--result",
            str(result_path),
            check=False,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["code"], "plan_refinement_required")
        self.assertEqual(
            payload["plan_refinements"][0]["changed_assumption"]["path"],
            "schemas/example.json",
        )
        self.assertEqual(
            payload["plan_refinements"][0]["smallest_successor_action"],
            "create_successor_plan_revalidating_schema_precondition",
        )


if __name__ == "__main__":
    unittest.main()
