import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from doc_warden.artifacts import apply_preview, consent_for, draft_artifact
from doc_warden.canonical import canonical_json, digest_ref, parse_artifact
from doc_warden.cli import main
from doc_warden.validators import validate_design_coverage
from fixture_factory import FixtureFactory


class UiContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create("ui")
        self.fixture.approve_prd("REQ-001")
        self.uxr_id = self.fixture.approve_uxr()
        asset_record = {
            "schema": "doc-warden/external-asset/v2", "provider": "figma",
            "canonical_url": "https://www.figma.com/design/file/Fixture?node-id=1-2",
            "immutable_revision": "figma-revision-123", "source_repository_key": self.fixture.repository_key,
            "source_github_repository_id": None, "source_commit": None, "export_sha256": "a" * 64,
            "captured_at": "2026-08-30T00:00:00Z", "owner": "design-owner", "license": "internal-use",
            "egress_projection": "external_asset_pointer/v1",
        }
        asset_observation = {
            "schema": "doc-warden/external-asset-observation/v1",
            "external_asset_digest": digest_ref(canonical_json(asset_record)),
            "observed_revision": asset_record["immutable_revision"],
            "observed_export_sha256": asset_record["export_sha256"],
            "observed_at": "2026-08-30T00:01:00Z", "observed_by": "design-reviewer",
            "observation_method": "read_only_provider_observation",
        }
        asset = draft_artifact("asset", {"title": "Fixture visual", "lifecycle": "approved",
                                         "approval": {"actor": "fixture", "date": "2026-08-30"},
                                         "external_asset": asset_record,
                                         "external_asset_observations": [asset_observation]},
                               repo=self.fixture.repo)
        apply_preview(asset, consent_for(asset.transaction))
        self.asset_id = asset.artifact_id

    def tearDown(self):
        repo_path = self.fixture.repo
        self.fixture.cleanup()
        self.assertFalse(repo_path.exists())

    def complete_design(self):
        return {
            "schema": "doc-warden/design-contract/v1",
            "lifecycle": "approved",
            "requirements": ["REQ-001"],
            "journeys": ["open dashboard"],
            "information_hierarchy": ["primary balance before secondary copy"],
            "interaction_copy": ["save button has explicit label"],
            "states": {
                "loading": "skeleton",
                "empty": "empty copy",
                "error": "retry copy",
                "success": "content",
                "disabled": "disabled save",
                "recovery": "retry succeeds",
            },
            "accessibility": {
                "keyboard": "tab order",
                "screen_reader": "announced labels",
                "contrast": "WCAG AA",
                "motion": "reduced motion",
                "focus": "visible focus",
            },
            "responsive": {
                "web_responsive": True,
                "phone": "single column",
                "tablet": "two columns",
                "desktop": "full layout",
            },
            "design_system": {
                "tokens": ["color.text.primary"],
                "components": ["Button"],
            },
            "visual_assets": [self.asset_id],
            "unresolved_interactions": [],
            "prototypes": [],
            "approval": {"approved_by": "operator", "approved_at": "2026-08-30T00:00:00Z"},
            "verification_rubric": {
                "state_matrix": "complete",
                "accessibility": "complete",
                "responsive": "complete",
            },
        }

    def issue_codes(self, design):
        return {issue.code for issue in validate_design_coverage(design)}

    def persist_approved_design(self, **overrides):
        inputs = {
            "title": "Approved design",
            "lifecycle": "approved",
            "approval": self.complete_design()["approval"],
            "design": self.complete_design(),
        }
        inputs.update(overrides)
        preview = draft_artifact(
            "design",
            inputs,
            repo=self.fixture.repo,
        )
        apply_preview(preview, consent_for(preview.transaction))
        return preview

    def test_ui_plan_refused_without_uxr_and_approved_design(self):
        with self.assertRaisesRegex(ValueError, "ui_plan_requires_uxr_and_approved_design"):
            draft_artifact(
                "plan",
                {"title": "UI plan", "approved_prd": True, "ui_visual": True},
                repo=self.fixture.repo,
            )

    def test_ui_plan_requires_actual_uxr_and_verifiable_visual_assets(self):
        design = self.persist_approved_design(design=self.complete_design() | {"visual_assets": ["ASSET-missing"]})
        inputs = {"title": "Visual plan", "ui_visual": True, "uxr_id": "UXR-missing",
                  "design_ids": [design.artifact_id], "design_versions": {design.artifact_id: 1}}
        with self.assertRaisesRegex(ValueError, "ui_plan_requires_approved_uxr"):
            draft_artifact("plan", inputs, repo=self.fixture.repo)
        with self.assertRaisesRegex(ValueError, "ui_visual_asset_unavailable"):
            draft_artifact("plan", inputs | {"uxr_id": self.uxr_id}, repo=self.fixture.repo)

    def test_design_binding_alone_requires_uxr_and_visual_asset_on_both_authoring_paths(self):
        design = self.persist_approved_design(design=self.complete_design() | {"visual_assets": ["ASSET-missing"]})
        repo = self.fixture.repo
        fields = {"title": "Visual plan", "design_ids": [design.artifact_id],
                  "design_versions": {design.artifact_id: 1}}
        base_cli = ["draft", "plan", "--repo", str(repo), "--title", "Visual plan",
                    "--design-binding", f"{design.artifact_id}@1", "--preview"]
        for cli_args, inputs, code in (
            ([], {}, "ui_plan_requires_uxr_and_approved_design"),
            (["--uxr-id", self.uxr_id], {"uxr_id": self.uxr_id}, "ui_visual_asset_unavailable"),
        ):
            for explicit in ({}, {"ui_visual": False}):
                with self.subTest(inputs=inputs, explicit=explicit), self.assertRaisesRegex(ValueError, f"^{code}$"):
                    draft_artifact("plan", fields | inputs | explicit, repo=repo)
            with redirect_stdout(io.StringIO()) as result:
                self.assertEqual(main(base_cli + cli_args), 1)
            self.assertEqual(json.loads(result.getvalue())["code"], code)

    def test_design_binding_refuses_changed_frozen_bytes_on_both_authoring_paths(self):
        design = self.persist_approved_design()
        repo = self.fixture.repo
        fields = {"title": "Visual plan", "design_ids": [design.artifact_id],
                  "design_versions": {design.artifact_id: 1}, "uxr_id": self.uxr_id}
        path = repo / design.artifact_path
        original = path.read_bytes()
        updated = original.replace(b'"open dashboard"', b'"open visual overview"')
        self.assertNotEqual(updated, original)
        path.write_bytes(updated)
        with self.assertRaisesRegex(ValueError, "^authority_freeze_mismatch$"):
            draft_artifact("plan", fields, repo=repo)
        with redirect_stdout(io.StringIO()) as result:
            self.assertEqual(main(["draft", "plan", "--repo", str(repo), "--title", "Visual plan",
                                   "--design-binding", f"{design.artifact_id}@1",
                                   "--uxr-id", self.uxr_id, "--preview"]), 1)
        self.assertEqual(json.loads(result.getvalue())["code"], "authority_freeze_mismatch")

    def test_cli_rejects_conflicting_versions_for_the_same_design(self):
        design = self.persist_approved_design()
        with redirect_stdout(io.StringIO()) as result:
            self.assertEqual(main(["draft", "plan", "--repo", str(self.fixture.repo), "--title", "Visual plan",
                                   "--design-binding", f"{design.artifact_id}@1",
                                   "--design-binding", f"{design.artifact_id}@2",
                                   "--uxr-id", self.uxr_id, "--preview"]), 1)
        self.assertEqual(json.loads(result.getvalue())["code"], "design_binding_version_conflict")

    def test_design_requires_loading_empty_error_success_disabled_and_recovery_states(self):
        design = self.complete_design()
        design["states"].pop("recovery")
        self.assertIn("missing_state_recovery", self.issue_codes(design))

    def test_design_requires_keyboard_screen_reader_contrast_motion_and_focus_coverage(self):
        design = self.complete_design()
        design["accessibility"].pop("screen_reader")
        self.assertIn("missing_accessibility_screen_reader", self.issue_codes(design))

    def test_design_requires_phone_tablet_desktop_breakpoints_when_web_responsive(self):
        design = self.complete_design()
        design["responsive"].pop("tablet")
        self.assertIn("missing_responsive_tablet", self.issue_codes(design))

    def test_unresolved_interaction_requires_prototype(self):
        design = self.complete_design()
        design["unresolved_interactions"] = ["drag to reorder"]
        self.assertIn("prototype_required", self.issue_codes(design))

    def test_unresolved_interaction_requires_canonical_prototype_references(self):
        malformed = (
            ({}, "prototype_references_must_be_array"),
            ({"items": []}, "prototype_references_must_be_array"),
            ({"items": ["PROTO-001"]}, "prototype_references_must_be_array"),
            ("PROTO-001", "prototype_references_must_be_array"),
            (True, "prototype_references_must_be_array"),
            (1, "prototype_references_must_be_array"),
            ([None], "prototype_reference_invalid"),
            ([True], "prototype_reference_invalid"),
            ([1], "prototype_reference_invalid"),
            ([{}], "prototype_reference_invalid"),
            ([""], "prototype_reference_invalid"),
            (["PROTO-"], "prototype_reference_invalid"),
            (["PROTO-001", "PROTO-001"], "prototype_reference_duplicate"),
        )
        for prototypes, expected in malformed:
            design = self.complete_design()
            design["unresolved_interactions"] = ["drag to reorder"]
            design["prototypes"] = prototypes
            with self.subTest(prototypes=prototypes):
                self.assertIn(expected, self.issue_codes(design))
        design = self.complete_design()
        design["unresolved_interactions"] = ["drag to reorder"]
        design["prototypes"] = ["PROTO-001", "PROTO-external-revision-123"]
        self.assertTrue(
            self.issue_codes(design).isdisjoint(
                {
                    "prototype_required",
                    "prototype_references_must_be_array",
                    "prototype_reference_invalid",
                    "prototype_reference_duplicate",
                }
            )
        )

    def test_inline_design_assertion_is_not_repository_state_proof(self):
        with self.assertRaisesRegex(
            ValueError,
            "^ui_plan_requires_active_design_binding$",
        ):
            draft_artifact(
                "plan",
                {
                    "title": "UI plan",
                    "approved_prd": True,
                    "ui_visual": True,
                    "uxr_id": self.uxr_id,
                    "design": self.complete_design(),
                },
                repo=self.fixture.repo,
            )

    def test_complete_approved_design_allows_ui_plan_preview(self):
        design = self.persist_approved_design()
        preview = draft_artifact(
            "plan",
            {
                "title": "UI plan",
                "approved_prd": True,
                "ui_visual": True,
                "uxr_id": self.uxr_id,
                "design_ids": [design.artifact_id],
                "design_versions": {design.artifact_id: 1},
            },
            repo=self.fixture.repo,
        )
        self.assertTrue(preview.artifact_id.startswith("PLAN-"))
        receipt = apply_preview(preview, consent_for(preview.transaction))
        self.assertEqual(receipt["outcome"], "applied")
        self.assertTrue((self.fixture.repo / preview.artifact_path).is_file())

    def test_incomplete_approved_design_is_rejected_before_preview(self):
        incomplete = self.complete_design()
        incomplete["states"].pop("error")
        with patch("doc_warden.artifacts.preview_transaction") as emit_preview:
            with self.assertRaisesRegex(
                ValueError,
                "design_coverage_blocked:.*missing_state_error",
            ):
                draft_artifact(
                    "design",
                    {
                        "title": "Incomplete design",
                        "lifecycle": "approved",
                        "approval": incomplete["approval"],
                        "design": incomplete,
                    },
                    repo=self.fixture.repo,
                )
            emit_preview.assert_not_called()
        self.assertEqual(list((self.fixture.repo / ".planning/artifacts").glob("DESIGN-*.md")), [])

    def test_complete_design_contract_is_canonical_persisted_authority(self):
        preview = self.persist_approved_design()
        path = self.fixture.repo / preview.artifact_path
        parsed = parse_artifact(path)
        expected = {
            key: value
            for key, value in self.complete_design().items()
            if key not in {"lifecycle", "approval"}
        }
        self.assertEqual(json.loads(parsed.body), expected)
        self.assertEqual(parsed.body.encode("utf-8"), canonical_json(expected))

    def test_complete_inline_design_cannot_rescue_stub_bound_artifact(self):
        stub = draft_artifact(
            "design",
            {"title": "Legacy stub"},
            repo=self.fixture.repo,
        )
        apply_preview(stub, consent_for(stub.transaction))
        path = self.fixture.repo / stub.artifact_path
        parsed = parse_artifact(path)
        metadata = {
            **parsed.metadata,
            "lifecycle": "approved",
            "approval": self.complete_design()["approval"],
        }
        path.write_bytes(
            b"---\n"
            + canonical_json(metadata)
            + b"---\n"
            + parsed.body.encode("utf-8")
        )

        with patch("doc_warden.artifacts.preview_transaction") as emit_preview:
            with self.assertRaisesRegex(
                ValueError,
                "^design_artifact_state_invalid$",
            ):
                draft_artifact(
                    "plan",
                    {
                        "title": "UI plan",
                        "approved_prd": True,
                        "ui_visual": True,
                        "uxr_id": self.uxr_id,
                        "design": self.complete_design(),
                        "design_ids": [stub.artifact_id],
                        "design_versions": {stub.artifact_id: 1},
                    },
                    repo=self.fixture.repo,
                )
            emit_preview.assert_not_called()

    def test_inline_design_mismatch_fails_closed_before_preview(self):
        persisted = self.persist_approved_design()
        mismatched = self.complete_design()
        mismatched["interaction_copy"] = ["different approved copy"]
        with patch("doc_warden.artifacts.preview_transaction") as emit_preview:
            with self.assertRaisesRegex(ValueError, "^inline_design_mismatch$"):
                draft_artifact(
                    "plan",
                    {
                        "title": "UI plan",
                        "approved_prd": True,
                        "ui_visual": True,
                        "uxr_id": self.uxr_id,
                        "design": mismatched,
                        "design_ids": [persisted.artifact_id],
                        "design_versions": {persisted.artifact_id: 1},
                    },
                    repo=self.fixture.repo,
                )
            emit_preview.assert_not_called()

    def test_plan_sidecar_and_apply_bind_exact_design_bytes(self):
        persisted = self.persist_approved_design()
        design_path = self.fixture.repo / persisted.artifact_path
        plan = draft_artifact(
            "plan",
            {
                "title": "UI plan",
                "approved_prd": True,
                "ui_visual": True,
                "uxr_id": self.uxr_id,
                "design_ids": [persisted.artifact_id],
                "design_versions": {persisted.artifact_id: 1},
            },
            repo=self.fixture.repo,
        )
        sidecar = json.loads(plan.transaction.actions[-1].content)
        expected_digest = digest_ref(design_path.read_bytes())
        self.assertEqual(
            sidecar["design_digests"],
            {persisted.artifact_id: expected_digest},
        )
        self.assertEqual(
            plan.transaction.bindings["design_authority"]["design_digests"],
            sidecar["design_digests"],
        )
        design_path.write_bytes(design_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(
            ValueError,
            "design_artifact_state_invalid|design_authority_binding_stale",
        ):
            apply_preview(plan, consent_for(plan.transaction))
        self.assertFalse((self.fixture.repo / plan.artifact_path).exists())

    def test_successor_after_preview_invalidates_plan_apply(self):
        original = self.persist_approved_design()
        plan = draft_artifact(
            "plan",
            {
                "title": "UI plan",
                "approved_prd": True,
                "ui_visual": True,
                "uxr_id": self.uxr_id,
                "design_ids": [original.artifact_id],
                "design_versions": {original.artifact_id: 1},
            },
            repo=self.fixture.repo,
        )
        self.persist_approved_design(
            version=2,
            supersedes=original.artifact_id,
        )
        with self.assertRaisesRegex(
            ValueError,
            "^design_authority_binding_stale$",
        ):
            apply_preview(plan, consent_for(plan.transaction))
        self.assertFalse((self.fixture.repo / plan.artifact_path).exists())

    def test_ui_visual_omitted_or_false_preserves_non_ui_plan(self):
        for label, inputs in (
            ("omitted", {"title": "Plan", "approved_prd": True}),
            ("false", {"title": "Plan", "approved_prd": True, "ui_visual": False}),
        ):
            with self.subTest(ui_visual=label):
                preview = draft_artifact("plan", inputs, repo=self.fixture.repo)
                self.assertTrue(preview.artifact_id.startswith("PLAN-"))
                sidecar = json.loads(preview.transaction.actions[-1].content)
                self.assertEqual(sidecar["design_ids"], [])
                self.assertEqual(sidecar["design_versions"], {})
                receipt = apply_preview(preview, consent_for(preview.transaction))
                self.assertEqual(receipt["outcome"], "applied")
                self.assertTrue((self.fixture.repo / preview.artifact_path).is_file())

    def test_ui_visual_true_requires_full_persisted_design_and_uxr_gates(self):
        with self.assertRaisesRegex(
            ValueError, "^ui_plan_requires_uxr_and_approved_design$"
        ):
            draft_artifact(
                "plan",
                {"title": "UI plan", "approved_prd": True, "ui_visual": True},
                repo=self.fixture.repo,
            )
        with self.assertRaisesRegex(
            ValueError, "^ui_plan_requires_active_design_binding$"
        ):
            draft_artifact(
                "plan",
                {
                    "title": "UI plan",
                    "approved_prd": True,
                    "ui_visual": True,
                    "uxr_id": self.uxr_id,
                },
                repo=self.fixture.repo,
            )
        design = self.persist_approved_design()
        preview = draft_artifact(
            "plan",
            {
                "title": "UI plan",
                "approved_prd": True,
                "ui_visual": True,
                "uxr_id": self.uxr_id,
                "design_ids": [design.artifact_id],
                "design_versions": {design.artifact_id: 1},
            },
            repo=self.fixture.repo,
        )
        self.assertTrue(preview.artifact_id.startswith("PLAN-"))
        receipt = apply_preview(preview, consent_for(preview.transaction))
        self.assertEqual(receipt["outcome"], "applied")

    def test_ui_visual_rejects_non_boolean_before_any_preview(self):
        malformed = (
            "false",
            "0",
            "true",
            "1",
            0,
            1,
            1.5,
            None,
            [],
            ["UXR-001"],
            {},
            {"enabled": True},
        )
        for value in malformed:
            with self.subTest(ui_visual=value):
                with patch(
                    "doc_warden.artifacts.preview_transaction"
                ) as emit_preview:
                    with self.assertRaisesRegex(
                        ValueError, "^ui_visual_must_be_boolean$"
                    ):
                        draft_artifact(
                            "plan",
                            {
                                "title": "UI plan",
                                "approved_prd": True,
                                "ui_visual": value,
                            },
                            repo=self.fixture.repo,
                        )
                    emit_preview.assert_not_called()


if __name__ == "__main__":
    unittest.main()
