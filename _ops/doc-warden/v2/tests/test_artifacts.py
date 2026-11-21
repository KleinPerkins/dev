import json
import unittest
import uuid

from doc_warden.adrs import preview_adr_draft
from doc_warden.artifact_authority import resolve_approved_artifact
from doc_warden.artifacts import (
    apply_preview,
    consent_for,
    draft_artifact,
)
from doc_warden.canonical import canonical_json, digest_ref, parse_artifact
from doc_warden.dependencies import build_graph
from doc_warden.transactions import MutationRequest, preview_transaction
from doc_warden.validators import active_approved_artifacts, parse_validated_artifact
from fixture_factory import FixtureFactory


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create()

    def tearDown(self):
        self.fixture.cleanup()

    @staticmethod
    def metadata_for(preview):
        action = next(
            action
            for action in preview.transaction.actions
            if action.path == preview.artifact_path
        )
        rendered = action.content.decode("utf-8")
        metadata_end = rendered.index("\n---\n", 4)
        return json.loads(rendered[4:metadata_end])

    def relation_for(self, artifact_id, *, authority="planned"):
        return {
            "schema": "doc-warden/relation/v2",
            "relation": "depends_on_planned",
            "source_id": artifact_id,
            "source_kind": "project",
            "source_version": 1,
            "target": {
                "kind": "repository",
                "id": f"REPO-{self.fixture.repository_key}",
                "version": None,
            },
            "authority": authority,
            "provenance": [{"observer": "artifact-test"}],
            "observed_revision": "a" * 40,
            "provider_revision": None,
            "observed_at": "2026-08-31T20:00:00Z",
            "lifecycle": "active",
            "match_evidence": None,
            "assumption": None,
        }

    def test_feature_plan_refused_without_approved_prd(self):
        with self.assertRaisesRegex(ValueError, "approved_prd_required"):
            draft_artifact("plan", {"title": "Plan"}, repo=self.fixture.repo)
        for kind in ("spec", "plan"):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "approved_prd_required"):
                draft_artifact(kind, {"title": "Plan", "approved_prd": True}, repo=self.fixture.repo)

    def test_feature_plan_uses_selected_approved_prd_requirements_and_observed_bytes(self):
        self.fixture.approve_prd("REQ-001")
        selected = self.fixture.approve_prd("REQ-002", "REQ-003")
        with self.assertRaisesRegex(ValueError, "authority_artifact_ambiguous"):
            draft_artifact("plan", {"title": "Ambiguous plan"}, repo=self.fixture.repo)
        with self.assertRaisesRegex(ValueError, "approved_prd_requirement_set_mismatch"):
            draft_artifact("plan", {"title": "Incomplete plan", "prd_id": selected,
                                    "requirement_ids": ["REQ-002"]}, repo=self.fixture.repo)
        plan = draft_artifact("plan", {"title": "Bound plan", "prd_id": selected}, repo=self.fixture.repo)
        sidecar = next(action for action in plan.transaction.actions if action.path.endswith(".governance.json"))
        self.assertEqual(json.loads(sidecar.content)["requirement_ids"], ["REQ-002", "REQ-003"])
        prd = self.fixture.repo / ".planning/artifacts" / f"{selected}-v1.md"
        prd.write_bytes(prd.read_bytes() + b"Unapproved change.\n")
        with self.assertRaisesRegex(ValueError, "observed_input_drift"):
            apply_preview(plan, consent_for(plan.transaction))
        self.assertFalse((self.fixture.repo / plan.artifact_path).exists())

    def test_changed_or_deleted_frozen_prd_successor_cannot_restore_authority_to_its_predecessor(self):
        predecessor = self.fixture.approve_prd("REQ-001")
        successor = draft_artifact("prd", {
            "title": "Current requirements", "version": 2, "supersedes": predecessor,
            "lifecycle": "approved", "approval": {"actor": "fixture", "date": "2026-01-01"},
            "requirements": [{"id": "REQ-002", "statement": "Current behavior."}],
        }, repo=self.fixture.repo)
        apply_preview(successor, consent_for(successor.transaction))
        plan = draft_artifact("plan", {"title": "Current plan"}, repo=self.fixture.repo)
        sidecar = next(action for action in plan.transaction.actions if action.path.endswith(".governance.json"))
        self.assertEqual(json.loads(sidecar.content)["requirement_ids"], ["REQ-002"])

        path = self.fixture.repo / successor.artifact_path
        document = parse_artifact(path)
        metadata = document.metadata | {"lifecycle": "draft", "approval": None}
        path.write_bytes(b"---\n" + canonical_json(metadata) + b"---\n" + document.body.encode("utf-8"))
        for loss in ("edited", "deleted"):
            if loss == "deleted":
                path.unlink()
            for selection in ({}, {"prd_id": predecessor}):
                with self.subTest(loss=loss, selection=selection), self.assertRaisesRegex(
                    ValueError, "^authority_freeze_mismatch$",
                ):
                    draft_artifact("plan", {"title": "Invalid plan"} | selection, repo=self.fixture.repo)

    def test_competing_approved_successors_refuse_stale_apply_and_historical_ambiguity(self):
        repo = self.fixture.repo
        predecessor = self.fixture.approve_prd("REQ-001")
        inputs = {
            "title": "Replacement requirements", "version": 2, "supersedes": predecessor,
            "lifecycle": "approved", "approval": {"actor": "fixture", "date": "2026-01-01"},
            "requirements": [{"id": "REQ-002", "statement": "Current behavior."}],
        }
        first = draft_artifact("prd", inputs, repo=repo)
        competing = draft_artifact("prd", inputs, repo=repo)
        apply_preview(first, consent_for(first.transaction))
        self.assertEqual(resolve_approved_artifact(repo, "prd").metadata["id"], first.artifact_id)
        with self.assertRaisesRegex(ValueError, "^observed_input_drift$"):
            apply_preview(competing, consent_for(competing.transaction))
        self.assertFalse((repo / competing.artifact_path).exists())
        with self.assertRaisesRegex(ValueError, "^authority_artifact_required$"):
            draft_artifact("prd", inputs, repo=repo)

        # Model previously accepted divergent history with an older transaction
        # that did not observe the current predecessor.
        old = competing.transaction
        legacy = preview_transaction(MutationRequest(
            repo=repo, repository_key=old.repository_key, github_repository_id=old.github_repository_id,
            transition=old.transition, actions=old.actions, bindings=old.bindings, operation_id=old.operation_id,
            require_write_enabled=old.require_write_enabled,
        ))
        apply_preview(legacy, consent_for(legacy))
        for read in (lambda: build_graph(repo), lambda: active_approved_artifacts(repo, "prd"),
                     lambda: resolve_approved_artifact(repo, "prd", first.artifact_id),
                     lambda: resolve_approved_artifact(repo, "prd", competing.artifact_id)):
            with self.assertRaisesRegex(ValueError, "^artifact_supersession_conflict$"):
                read()

    def test_authoring_rigor_requires_approved_sensitive_decision_and_rejects_unknown_signals(self):
        self.fixture.approve_prd("REQ-001")
        with self.assertRaisesRegex(ValueError, "rigor_signal_invalid:sensitive"):
            draft_artifact("plan", {"title": "Ambiguous", "rigor_signals": {"sensitive": None}},
                           repo=self.fixture.repo)
        inputs = {"title": "Sensitive plan", "rigor_signals": {"sensitive": True, "sessions": 2}}
        with self.assertRaisesRegex(ValueError, "sensitive_authoring_requires_approved_adr"):
            draft_artifact("plan", inputs, repo=self.fixture.repo)
        body = "# Sensitive decision\n\nApproved fixture data flow.\n"
        decision = preview_adr_draft({"title": "Sensitive decision", "body": body, "approval": {
            "actor": "fixture", "date": "2026-01-01", "review_sha256": digest_ref(body.encode())[7:],
        }}, repo=self.fixture.repo)
        apply_preview(decision, consent_for(decision.transaction))
        plan = draft_artifact("plan", inputs | {"sensitive_adr_id": decision.artifact_id}, repo=self.fixture.repo)
        apply_preview(plan, consent_for(plan.transaction))
        metadata = parse_artifact(self.fixture.repo / plan.artifact_path).metadata
        rigor = next(item["rigor"] for item in metadata["provenance"] if "rigor" in item)
        self.assertEqual(rigor["base_class"], "multi_session_cross_component")
        self.assertEqual(rigor["dimensions"], ["sensitive"])
        self.assertIn("security_verification", rigor["required_artifacts"])

    def test_feature_authoring_cannot_claim_trivial_rigor_from_one_negative_signal(self):
        self.fixture.approve_prd("REQ-001")
        inputs = {"title": "Unclassified scope", "rigor_signals": {"new_user_value": False}}
        with self.assertRaisesRegex(ValueError, "feature_rigor_scope_unresolved"):
            draft_artifact("plan", inputs, repo=self.fixture.repo)
        with self.assertRaisesRegex(ValueError, "defect_and_feature_authoring_conflict"):
            draft_artifact("plan", {"title": "Mixed routes", "defect_id": "DEF-unknown", "approved_prd": True},
                           repo=self.fixture.repo)

    def test_uuid_artifact_id_is_bound_in_preview_and_reused_on_retry(self):
        operation_id = str(uuid.uuid4())
        preview = draft_artifact(
            "prd",
            {"title": "Feature", "body": "# Feature\n\nProblem."},
            repo=self.fixture.repo,
            operation_id=operation_id,
        )
        self.assertIn(operation_id, {preview.transaction.operation_id})
        receipt = apply_preview(preview, consent_for(preview.transaction))
        replay = apply_preview(preview, consent_for(preview.transaction))
        self.assertEqual(receipt, replay)
        metadata = parse_artifact(self.fixture.repo / preview.artifact_path).metadata
        self.assertEqual(metadata["id"], preview.artifact_id)

    def test_invalid_relation_semantics_are_rejected_before_draft_persistence(self):
        operation_id = str(uuid.uuid4())
        artifact_id = (
            f"PROJECT-{self.fixture.repository_key}-"
            f"{uuid.uuid5(uuid.UUID(operation_id), 'project')}"
        )
        with self.assertRaisesRegex(ValueError, "relation_authority_mismatch"):
            draft_artifact(
                "project",
                {
                    "title": "Invalid relation",
                    "relations": [
                        self.relation_for(artifact_id, authority="observed")
                    ],
                },
                repo=self.fixture.repo,
                operation_id=operation_id,
            )
        self.assertFalse((self.fixture.repo / ".planning/artifacts").exists())

    def test_valid_relation_semantics_draft_and_persist_unchanged(self):
        operation_id = str(uuid.uuid4())
        artifact_id = (
            f"PROJECT-{self.fixture.repository_key}-"
            f"{uuid.uuid5(uuid.UUID(operation_id), 'project')}"
        )
        relation = self.relation_for(artifact_id)
        preview = draft_artifact(
            "project",
            {"title": "Valid relation", "relations": [relation]},
            repo=self.fixture.repo,
            operation_id=operation_id,
        )
        self.assertEqual(self.metadata_for(preview)["relations"], [relation])
        apply_preview(preview, consent_for(preview.transaction))
        metadata = parse_validated_artifact(
            self.fixture.repo / preview.artifact_path
        )
        self.assertEqual(metadata["relations"], [relation])

    def test_consequential_apply_requires_fresh_exact_consent_envelope(self):
        preview = draft_artifact("project", {"title": "Project"}, repo=self.fixture.repo)
        with self.assertRaisesRegex(ValueError, "fresh_exact_consent_required"):
            apply_preview(preview, None)
        stale = consent_for(preview.transaction)
        stale["action_digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "fresh_exact_consent_required"):
            apply_preview(preview, stale)
        self.assertFalse((self.fixture.repo / preview.artifact_path).exists())

    def test_unconfigured_profile_and_artifact_share_one_repository_key(self):
        self.fixture.cleanup()
        self.fixture = FixtureFactory.create("unconfigured")
        preview = draft_artifact("project", {"title": "Project"}, repo=self.fixture.repo)
        receipt = apply_preview(preview, consent_for(preview.transaction))
        self.assertEqual(receipt["repository_key"], preview.repository_key)
        self.assertEqual(len(receipt["actions"]), 2)

    def test_disabled_repository_refuses_apply(self):
        preview = draft_artifact("project", {"title": "Project"}, repo=self.fixture.repo)
        config_path = self.fixture.repo / ".planning/doc-warden.json"
        config = json.loads(config_path.read_text())
        config["enabled"] = False
        config_path.write_bytes(canonical_json(config))
        with self.assertRaisesRegex(ValueError, "repository_write_disabled"):
            apply_preview(preview, consent_for(preview.transaction))
        self.assertFalse((self.fixture.repo / preview.artifact_path).exists())

    def test_disabled_repository_allows_verified_receipt_replay(self):
        preview = draft_artifact("project", {"title": "Project"}, repo=self.fixture.repo)
        consent = consent_for(preview.transaction)
        receipt = apply_preview(preview, consent)
        config_path = self.fixture.repo / ".planning/doc-warden.json"
        config = json.loads(config_path.read_text())
        config["enabled"] = False
        config_path.write_bytes(canonical_json(config))
        self.assertEqual(apply_preview(preview, consent), receipt)

    def test_disabled_repository_finishes_started_partial_apply(self):
        preview = draft_artifact("project", {"title": "Project"}, repo=self.fixture.repo)
        action = preview.transaction.actions[0]
        destination = self.fixture.repo / action.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(action.content)
        config_path = self.fixture.repo / ".planning/doc-warden.json"
        config = json.loads(config_path.read_text())
        config["enabled"] = False
        config_path.write_bytes(canonical_json(config))
        receipt = apply_preview(preview, consent_for(preview.transaction))
        self.assertEqual(receipt["outcome"], "applied")
        self.assertTrue(
            (
                self.fixture.repo
                / f"_ops/doc-warden/state/v2/receipts/{preview.transaction.operation_id}.json"
            ).is_file()
        )

    def test_plan_draft_emits_governance_sidecar(self):
        self.fixture.approve_prd("REQ-001")
        preview = draft_artifact(
            "plan",
            {"title": "Plan", "approved_prd": True},
            repo=self.fixture.repo,
        )
        self.assertEqual(len(preview.transaction.actions), 2)
        self.assertTrue(preview.transaction.actions[1].path.endswith(".governance.json"))

    def test_approved_artifact_requires_approval_record(self):
        with self.assertRaisesRegex(ValueError, "approval_record_required"):
            draft_artifact(
                "prd",
                {"title": "Approved", "lifecycle": "approved"},
                repo=self.fixture.repo,
            )

    def test_malformed_provenance_uses_deterministic_validation(self):
        for provenance in (None, {}, "not-a-list"):
            with self.subTest(provenance=provenance), self.assertRaisesRegex(
                ValueError, "provenance_must_be_list"
            ):
                draft_artifact(
                    "project",
                    {"title": "Project", "provenance": provenance},
                    repo=self.fixture.repo,
                )
        with self.assertRaisesRegex(ValueError, "provenance_items_must_be_objects"):
            draft_artifact(
                "project",
                {"title": "Project", "provenance": [None]},
                repo=self.fixture.repo,
            )
        preview = draft_artifact(
            "project",
            {"title": "Project", "provenance": []},
            repo=self.fixture.repo,
        )
        self.assertTrue(preview.artifact_id.startswith("PROJECT-"))

    def test_explicit_empty_provenance_matches_omitted_generated_provenance(self):
        cases = (
            (
                "prd",
                {
                    "title": "Feature",
                    "requirements": [
                        {"id": "REQ-001", "statement": "Compose provenance."}
                    ],
                },
                {
                    "requirements": [
                        {"id": "REQ-001", "statement": "Compose provenance."}
                    ]
                },
            ),
            (
                "release",
                {
                    "title": "Release",
                    "release_evidence": {
                        "commit": "a" * 40,
                        "verification": "VER-001",
                    },
                },
                {
                    "release_evidence": {
                        "commit": "a" * 40,
                        "verification": "VER-001",
                    }
                },
            ),
        )
        for kind, inputs, generated_record in cases:
            with self.subTest(kind=kind):
                operation_id = str(uuid.uuid4())
                omitted = draft_artifact(
                    kind,
                    inputs,
                    repo=self.fixture.repo,
                    operation_id=operation_id,
                )
                explicit = draft_artifact(
                    kind,
                    {**inputs, "provenance": []},
                    repo=self.fixture.repo,
                    operation_id=operation_id,
                )
                self.assertEqual(
                    omitted.transaction.actions, explicit.transaction.actions
                )
                self.assertEqual(
                    self.metadata_for(omitted), self.metadata_for(explicit)
                )
                self.assertEqual(
                    self.metadata_for(explicit)["provenance"], [generated_record]
                )

    def test_generated_provenance_precedes_and_preserves_ordinary_caller_record(self):
        requirements = [{"id": "REQ-001", "statement": "Compose provenance."}]
        ordinary = {"source": "approved-brief", "revision": "2"}
        preview = draft_artifact(
            "prd",
            {
                "title": "Feature",
                "requirements": requirements,
                "provenance": [ordinary],
            },
            repo=self.fixture.repo,
        )
        self.assertEqual(
            self.metadata_for(preview)["provenance"],
            [{"requirements": requirements}, ordinary],
        )

    def test_explicit_copy_of_generated_provenance_is_not_duplicated(self):
        requirements = [{"id": "REQ-001", "statement": "Compose provenance."}]
        generated = {"requirements": requirements}
        preview = draft_artifact(
            "prd",
            {
                "title": "Feature",
                "requirements": requirements,
                "provenance": [dict(generated)],
            },
            repo=self.fixture.repo,
        )
        self.assertEqual(self.metadata_for(preview)["provenance"], [generated])


if __name__ == "__main__":
    unittest.main()
