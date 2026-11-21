import hashlib
import json
import subprocess
import unittest
import uuid

from doc_warden.artifacts import (
    KINDS,
    apply_preview,
    consent_for,
    draft_artifact,
)
from doc_warden.canonical import canonical_json, digest_ref, parse_artifact
from doc_warden.validators import (
    is_external_asset_record,
    validate_egress,
    verify_external_asset,
)
from fixture_factory import FixtureFactory


class ExternalAssetTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create("asset")

    def tearDown(self):
        repo_path = self.fixture.repo
        self.fixture.cleanup()
        self.assertFalse(repo_path.exists())

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

    def record(self, **overrides):
        value = {
            "schema": "doc-warden/external-asset/v2",
            "provider": "figma",
            "canonical_url": "https://www.figma.com/design/file/Fixture?node-id=1-2",
            "immutable_revision": "figma-revision-123",
            "source_repository_key": self.fixture.repository_key,
            "source_github_repository_id": None,
            "source_commit": None,
            "export_sha256": "a" * 64,
            "captured_at": "2026-08-30T00:00:00Z",
            "owner": "design-owner",
            "license": "internal-use",
            "egress_projection": "external_asset_pointer/v1",
        }
        value.update(overrides)
        return value

    def observation(self, record, **overrides):
        value = {
            "schema": "doc-warden/external-asset-observation/v1",
            "external_asset_digest": digest_ref(canonical_json(record)),
            "observed_revision": record["immutable_revision"],
            "observed_export_sha256": record["export_sha256"],
            "observed_at": "2026-08-30T00:01:00Z",
            "observed_by": "design-reviewer",
            "observation_method": "read_only_provider_observation",
        }
        value.update(overrides)
        return value

    def complete_design(self):
        approval = {
            "approved_by": "operator",
            "approved_at": "2026-08-30T00:00:00Z",
        }
        return {
            "schema": "doc-warden/design-contract/v1",
            "lifecycle": "approved",
            "requirements": ["REQ-001"],
            "journeys": ["open dashboard"],
            "information_hierarchy": ["primary content first"],
            "interaction_copy": ["save button"],
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
            "visual_assets": ["ASSET-001"],
            "unresolved_interactions": [],
            "prototypes": [],
            "approval": approval,
            "verification_rubric": {
                "state_matrix": "complete",
                "accessibility": "complete",
                "responsive": "complete",
            },
        }

    def local_record(self, **overrides):
        source_path = ".planning/assets/ui-fixture.png"
        content = b"\x89PNG\r\n\x1a\nfixture-local-export\n"
        destination = self.fixture.repo / source_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "add", "--", source_path],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "commit", "-qm", "fixture local asset"],
            check=True,
        )
        source_commit = subprocess.check_output(
            ["git", "-C", str(self.fixture.repo), "rev-parse", "HEAD"],
            text=True,
        ).strip()
        value = self.record(
            provider="local",
            canonical_url=f"local:{source_path}",
            immutable_revision=f"git:{source_commit}",
            source_commit=source_commit,
            source_path=source_path,
            export_sha256=hashlib.sha256(content).hexdigest(),
        )
        value.update(overrides)
        return value

    def inputs_for(self, kind, **overrides):
        value = {"title": kind}
        if kind in {"spec", "plan"}:
            value["approved_prd"] = True
        value.update(overrides)
        return value

    def use_unconfigured_fixture(self):
        self.fixture.cleanup()
        self.fixture = FixtureFactory.create("unconfigured")

    def candidate_repository_key(self, operation_id):
        return draft_artifact(
            "project",
            {"title": "Repository bootstrap"},
            repo=self.fixture.repo,
            operation_id=operation_id,
        ).repository_key

    def test_moving_external_url_without_revision_and_export_digest_is_unverifiable(self):
        verdict = verify_external_asset(
            {
                "schema": "doc-warden/external-asset/v2",
                "provider": "figma",
                "canonical_url": "https://www.figma.com/design/file/Moving",
                "source_repository_key": self.fixture.repository_key,
                "source_github_repository_id": None,
                "source_commit": None,
                "captured_at": "2026-08-30T00:00:00Z",
                "owner": "design-owner",
                "license": "internal-use",
                "egress_projection": "external_asset_pointer/v1",
            }
        )
        self.assertEqual(verdict.status, "unverifiable")
        self.assertIn("immutable_revision", verdict.missing_fields)
        self.assertIn("export_sha256", verdict.missing_fields)

    def test_immutable_figma_revision_and_export_digest_are_recorded_without_observation(self):
        verdict = verify_external_asset(self.record())
        self.assertEqual(verdict.status, "recorded")
        self.assertEqual(verdict.code, "format_valid")
        validate_egress("external_asset", self.record())

    def test_quickhost_immutable_version_and_export_digest_are_recorded_without_observation(self):
        verdict = verify_external_asset(
            self.record(
                provider="quickhost",
                canonical_url="https://quickhost.local/p/doc-warden-fixture/v/7",
                immutable_revision="quickhost-version-7",
                export_sha256="b" * 64,
            )
        )
        self.assertEqual(verdict.status, "recorded")
        self.assertEqual(verdict.code, "format_valid")

    def test_local_asset_verifies_exact_tracked_blob_at_source_commit(self):
        record = self.local_record()
        verdict = verify_external_asset(record, repo=self.fixture.repo)
        self.assertEqual(verdict.status, "verified")
        self.assertEqual(verdict.code, "immutable_provenance_verified")
        (self.fixture.repo / record["source_path"]).write_bytes(b"changed worktree bytes\n")
        self.assertEqual(
            verify_external_asset(record, repo=self.fixture.repo).status,
            "verified",
        )

    def test_first_local_asset_draft_bootstraps_matching_profile_atomically(self):
        self.use_unconfigured_fixture()
        operation_id = str(uuid.uuid4())
        repository_key = self.candidate_repository_key(operation_id)
        record = self.local_record(source_repository_key=repository_key)

        preview = draft_artifact(
            "asset",
            {"title": "First local asset", "external_asset": record},
            repo=self.fixture.repo,
            operation_id=operation_id,
        )

        self.assertEqual(preview.repository_key, repository_key)
        self.assertEqual(
            [action.path for action in preview.transaction.actions],
            [".planning/doc-warden.json", preview.artifact_path],
        )
        profile = json.loads(preview.transaction.actions[0].content)
        self.assertEqual(profile["repository_key"], repository_key)
        self.assertEqual(
            self.metadata_for(preview)["provenance"][0]["source_repository_key"],
            profile["repository_key"],
        )
        apply_preview(preview, consent_for(preview.transaction))
        self.assertEqual(
            json.loads(
                (self.fixture.repo / ".planning/doc-warden.json").read_text()
            )["repository_key"],
            repository_key,
        )
        self.assertTrue((self.fixture.repo / preview.artifact_path).is_file())

    def test_first_local_asset_rejects_mismatched_or_other_generated_key(self):
        self.use_unconfigured_fixture()
        operation_id = str(uuid.uuid4())
        repository_key = self.candidate_repository_key(operation_id)
        other_generated_key = self.candidate_repository_key(str(uuid.uuid4()))
        self.assertNotEqual(repository_key, other_generated_key)
        record = self.local_record(source_repository_key=repository_key)

        for mismatched_key in (str(uuid.uuid4()), other_generated_key):
            with (
                self.subTest(source_repository_key=mismatched_key),
                self.assertRaisesRegex(ValueError, "^external_asset_unverifiable$"),
            ):
                draft_artifact(
                    "asset",
                    {
                        "title": "Mismatched local asset",
                        "external_asset": {
                            **record,
                            "source_repository_key": mismatched_key,
                        },
                    },
                    repo=self.fixture.repo,
                    operation_id=operation_id,
                )
        self.assertFalse(
            (self.fixture.repo / ".planning/doc-warden.json").exists()
        )

    def test_direct_local_verification_without_persisted_config_fails_closed(self):
        self.use_unconfigured_fixture()
        operation_id = str(uuid.uuid4())
        record = self.local_record(
            source_repository_key=self.candidate_repository_key(operation_id)
        )

        verdict = verify_external_asset(record, repo=self.fixture.repo)

        self.assertEqual(verdict.status, "unverifiable")
        self.assertEqual(verdict.code, "local_repository_config_required")

    def test_first_local_asset_preview_and_apply_replay_are_deterministic(self):
        self.use_unconfigured_fixture()
        operation_id = str(uuid.uuid4())
        record = self.local_record(
            source_repository_key=self.candidate_repository_key(operation_id)
        )

        first = draft_artifact(
            "asset",
            {"title": "Replayable local asset", "external_asset": record},
            repo=self.fixture.repo,
            operation_id=operation_id,
        )
        second = draft_artifact(
            "asset",
            {"title": "Replayable local asset", "external_asset": record},
            repo=self.fixture.repo,
            operation_id=operation_id,
        )

        self.assertEqual(first.transaction.actions, second.transaction.actions)
        self.assertEqual(
            first.transaction.action_digest,
            second.transaction.action_digest,
        )
        receipt = apply_preview(first, consent_for(first.transaction))
        self.assertEqual(
            apply_preview(second, consent_for(second.transaction)),
            receipt,
        )

    def test_configured_local_asset_keeps_persisted_profile_behavior(self):
        record = self.local_record()
        preview = draft_artifact(
            "asset",
            {"title": "Configured local asset", "external_asset": record},
            repo=self.fixture.repo,
        )

        self.assertEqual(preview.repository_key, self.fixture.repository_key)
        self.assertEqual(
            [action.path for action in preview.transaction.actions],
            [preview.artifact_path],
        )
        self.assertEqual(
            verify_external_asset(record, repo=self.fixture.repo).status,
            "verified",
        )

    def test_local_asset_requires_source_commit_relative_path_and_repository_context(self):
        missing_path = verify_external_asset(
            self.record(
                provider="local",
                canonical_url="local:.planning/assets/ui-fixture.png",
                immutable_revision="local-export-1",
                source_commit="c" * 40,
                export_sha256="c" * 64,
            ),
            repo=self.fixture.repo,
        )
        self.assertEqual(missing_path.status, "unverifiable")
        self.assertIn("source_path", missing_path.missing_fields)
        without_context = verify_external_asset(self.local_record())
        self.assertEqual(without_context.status, "unverifiable")
        self.assertEqual(without_context.code, "local_repository_context_required")

    def test_local_asset_rejects_canonical_url_source_path_mismatch(self):
        record = self.local_record(
            canonical_url="local:.planning/assets/other.png",
        )
        verdict = verify_external_asset(record, repo=self.fixture.repo)
        self.assertEqual(verdict.status, "unverifiable")
        self.assertEqual(verdict.code, "local_canonical_url_mismatch")
        record["canonical_url"] = f"local:{record['source_path']}"
        self.assertEqual(
            verify_external_asset(record, repo=self.fixture.repo).status,
            "verified",
        )

    def test_fabricated_local_repository_commit_blob_or_digest_cannot_pass(self):
        valid = self.local_record()
        cases = (
            (
                "repository",
                {**valid, "source_repository_key": str(uuid.uuid4())},
                "local_repository_key_mismatch",
            ),
            (
                "commit",
                {**valid, "source_commit": "f" * 40},
                "local_source_commit_missing",
            ),
            (
                "blob",
                {
                    **valid,
                    "canonical_url": "local:.planning/assets/missing.png",
                    "source_path": ".planning/assets/missing.png",
                },
                "local_source_blob_missing",
            ),
            (
                "digest",
                {**valid, "export_sha256": "0" * 64},
                "local_export_digest_mismatch",
            ),
        )
        for label, record, expected_code in cases:
            with self.subTest(label=label):
                verdict = verify_external_asset(record, repo=self.fixture.repo)
                self.assertEqual(verdict.status, "unverifiable")
                self.assertEqual(verdict.code, expected_code)
                with self.assertRaisesRegex(ValueError, "external_asset_unverifiable"):
                    draft_artifact(
                        "asset",
                        {"title": "Asset", "external_asset": record},
                        repo=self.fixture.repo,
                    )

    def test_asset_drafting_accepts_bound_local_blob(self):
        record = self.local_record()
        preview = draft_artifact(
            "asset",
            {"title": "Local asset", "external_asset": record},
            repo=self.fixture.repo,
        )
        self.assertEqual(self.metadata_for(preview)["provenance"], [record])

    def test_successor_revision_marks_bound_asset_stale_without_rewriting_record(self):
        record = self.record()
        before = dict(record)
        verdict = verify_external_asset(record, observed_revision="figma-revision-456")
        self.assertEqual(verdict.status, "stale")
        self.assertEqual(record, before)

    def test_remote_complete_matching_observation_verifies(self):
        record = self.record()
        verdict = verify_external_asset(
            record,
            observed_revision=record["immutable_revision"],
            observed_export_sha256=record["export_sha256"],
        )
        self.assertEqual(verdict.status, "verified")
        self.assertEqual(verdict.code, "immutable_provenance_verified")

    def test_remote_incomplete_observation_is_not_verified(self):
        record = self.record()
        verdict = verify_external_asset(
            record,
            observed_revision=record["immutable_revision"],
        )
        self.assertEqual(verdict.status, "recorded")
        self.assertEqual(verdict.code, "observation_incomplete")

    def test_remote_complete_mismatching_observation_marks_stale(self):
        record = self.record()
        cases = (
            ("revision", "figma-revision-456", record["export_sha256"], "immutable_revision_changed"),
            ("digest", record["immutable_revision"], "b" * 64, "export_digest_changed"),
        )
        for label, revision, digest, expected_code in cases:
            with self.subTest(label=label):
                verdict = verify_external_asset(
                    record,
                    observed_revision=revision,
                    observed_export_sha256=digest,
                )
                self.assertEqual(verdict.status, "stale")
                self.assertEqual(verdict.code, expected_code)

    def test_non_asset_artifact_rejects_invalid_generated_external_asset(self):
        invalid = self.record()
        invalid.pop("export_sha256")
        with self.assertRaisesRegex(ValueError, "external_asset_unverifiable"):
            draft_artifact(
                "release",
                {"title": "Release", "external_asset": invalid},
                repo=self.fixture.repo,
            )

    def test_explicit_empty_provenance_matches_omitted_external_asset(self):
        record = self.record()
        operation_id = str(uuid.uuid4())
        omitted = draft_artifact(
            "asset",
            {"title": "Asset", "external_asset": record},
            repo=self.fixture.repo,
            operation_id=operation_id,
        )
        explicit = draft_artifact(
            "asset",
            {"title": "Asset", "external_asset": record, "provenance": []},
            repo=self.fixture.repo,
            operation_id=operation_id,
        )
        self.assertEqual(omitted.transaction.actions, explicit.transaction.actions)
        self.assertEqual(self.metadata_for(omitted), self.metadata_for(explicit))
        self.assertEqual(self.metadata_for(explicit)["provenance"], [record])
        apply_preview(explicit, consent_for(explicit.transaction))
        persisted = parse_artifact(self.fixture.repo / explicit.artifact_path).metadata
        self.assertEqual(persisted["provenance"], [record])

    def test_explicit_copy_of_generated_external_asset_is_not_duplicated(self):
        record = self.record()
        preview = draft_artifact(
            "asset",
            {
                "title": "Asset",
                "external_asset": record,
                "provenance": [dict(record)],
            },
            repo=self.fixture.repo,
        )
        self.assertEqual(self.metadata_for(preview)["provenance"], [record])

    def test_invalid_external_asset_input_is_checked_for_every_artifact_kind(self):
        self.fixture.approve_prd("REQ-001")
        invalid = self.record()
        invalid.pop("export_sha256")
        for kind in sorted(KINDS - {"defect"}):
            with self.subTest(kind=kind), self.assertRaisesRegex(
                ValueError, "external_asset_unverifiable"
            ):
                draft_artifact(
                    kind,
                    self.inputs_for(
                        kind,
                        external_asset=invalid,
                        provenance=[self.record()],
                    ),
                    repo=self.fixture.repo,
                )

    def test_external_asset_input_requires_an_object(self):
        for invalid in (None, [], "moving-url"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(
                ValueError, "external_asset_must_be_object"
            ):
                draft_artifact(
                    "release",
                    {"title": "Release", "external_asset": invalid},
                    repo=self.fixture.repo,
                )

    def test_asset_rejects_provenance_only_fake_external_asset(self):
        fake = {"provider": "figma", "canonical_url": "https://example.invalid/moving"}
        with self.assertRaisesRegex(ValueError, "external_asset_unverifiable"):
            draft_artifact(
                "asset",
                {"title": "Asset", "provenance": [fake]},
                repo=self.fixture.repo,
            )

    def test_asset_requires_accepted_external_asset_provenance_in_every_lifecycle(self):
        cases = (
            ("omitted", {}),
            ("empty", {"provenance": []}),
            ("unrelated", {"provenance": [{"source": "approved-brief"}]}),
        )
        for lifecycle in ("draft", "approved"):
            for label, overrides in cases:
                inputs = {"title": "Asset", "lifecycle": lifecycle, **overrides}
                if lifecycle == "approved":
                    inputs["approval"] = {
                        "approved_by": "operator",
                        "approved_at": "2026-08-30T00:00:00Z",
                    }
                with self.subTest(lifecycle=lifecycle, case=label), self.assertRaisesRegex(
                    ValueError, "asset_external_asset_required"
                ):
                    draft_artifact("asset", inputs, repo=self.fixture.repo)

    def test_draft_asset_persists_recorded_remote_asset(self):
        record = self.record()
        preview = draft_artifact(
            "asset",
            {
                "title": "Draft asset",
                "provenance": [{"source": "approved-brief"}, record],
            },
            repo=self.fixture.repo,
        )
        apply_preview(preview, consent_for(preview.transaction))
        metadata = parse_artifact(self.fixture.repo / preview.artifact_path).metadata
        self.assertEqual(metadata["provenance"], [{"source": "approved-brief"}, record])
        self.assertEqual(
            [item for item in metadata["provenance"] if is_external_asset_record(item)],
            [record],
        )

    def test_approved_remote_asset_rejects_recorded_only_provenance(self):
        record = self.record()
        with self.assertRaisesRegex(ValueError, "^external_asset_recorded$"):
            draft_artifact(
                "asset",
                {
                    "title": "Approved asset",
                    "lifecycle": "approved",
                    "approval": {
                        "approved_by": "operator",
                        "approved_at": "2026-08-30T00:00:00Z",
                    },
                    "external_asset": record,
                },
                repo=self.fixture.repo,
            )

    def test_approved_remote_asset_persists_matching_read_only_observation(self):
        record = self.record()
        observation = self.observation(record)
        preview = draft_artifact(
            "asset",
            {
                "title": "Approved asset",
                "lifecycle": "approved",
                "approval": {
                    "approved_by": "operator",
                    "approved_at": "2026-08-30T00:00:00Z",
                },
                "external_asset": record,
                "external_asset_observations": [observation],
            },
            repo=self.fixture.repo,
        )
        apply_preview(preview, consent_for(preview.transaction))
        metadata = parse_artifact(
            self.fixture.repo / preview.artifact_path
        ).metadata
        self.assertEqual(metadata["provenance"], [record, observation])

    def test_approved_remote_asset_rejects_observation_revision_or_digest_mismatch(self):
        record = self.record()
        cases = (
            {
                "observed_revision": "figma-revision-456",
            },
            {
                "observed_export_sha256": "b" * 64,
            },
        )
        for overrides in cases:
            with (
                self.subTest(overrides=overrides),
                self.assertRaisesRegex(ValueError, "^external_asset_stale$"),
            ):
                draft_artifact(
                    "asset",
                    {
                        "title": "Approved asset",
                        "lifecycle": "approved",
                        "approval": {
                            "approved_by": "operator",
                            "approved_at": "2026-08-30T00:00:00Z",
                        },
                        "provenance": [record],
                        "external_asset_observations": [
                            self.observation(record, **overrides)
                        ],
                    },
                    repo=self.fixture.repo,
                )

    def test_observation_input_is_explicit_closed_and_bound_to_exact_asset(self):
        record = self.record()
        observation = self.observation(record)
        invalid_cases = (
            (
                "not-list",
                {"external_asset_observations": observation},
                "external_asset_observations_must_be_list",
            ),
            (
                "unknown-field",
                {
                    "external_asset_observations": [
                        {**observation, "asserted_verified": True}
                    ]
                },
                "external_asset_observation_invalid",
            ),
            (
                "smuggled-in-provenance",
                {"provenance": [record, observation]},
                "external_asset_observation_requires_explicit_input",
            ),
            (
                "wrong-asset-digest",
                {
                    "external_asset_observations": [
                        {
                            **observation,
                            "external_asset_digest": "sha256:" + "0" * 64,
                        }
                    ]
                },
                "external_asset_recorded",
            ),
        )
        for label, overrides, expected in invalid_cases:
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(ValueError, f"^{expected}$"),
            ):
                draft_artifact(
                    "asset",
                    {
                        "title": "Approved asset",
                        "lifecycle": "approved",
                        "approval": {
                            "approved_by": "operator",
                            "approved_at": "2026-08-30T00:00:00Z",
                        },
                        "external_asset": record,
                        **overrides,
                    },
                    repo=self.fixture.repo,
                )

    def test_approved_provenance_only_remote_asset_cannot_bypass_observation(self):
        record = self.record()
        with self.assertRaisesRegex(ValueError, "^external_asset_recorded$"):
            draft_artifact(
                "asset",
                {
                    "title": "Approved asset",
                    "lifecycle": "approved",
                    "approval": {
                        "approved_by": "operator",
                        "approved_at": "2026-08-30T00:00:00Z",
                    },
                    "provenance": [record],
                },
                repo=self.fixture.repo,
            )

    def test_approved_design_provenance_cannot_bypass_observation(self):
        design = self.complete_design()
        with self.assertRaisesRegex(ValueError, "^external_asset_recorded$"):
            draft_artifact(
                "design",
                {
                    "title": "Approved design",
                    "lifecycle": "approved",
                    "approval": design["approval"],
                    "design": design,
                    "provenance": [self.record()],
                },
                repo=self.fixture.repo,
            )

    def test_approved_local_provider_keeps_git_backed_verification(self):
        record = self.local_record()
        preview = draft_artifact(
            "asset",
            {
                "title": "Approved local asset",
                "lifecycle": "approved",
                "approval": {
                    "approved_by": "operator",
                    "approved_at": "2026-08-30T00:00:00Z",
                },
                "external_asset": record,
            },
            repo=self.fixture.repo,
        )
        self.assertEqual(self.metadata_for(preview)["provenance"], [record])

    def test_asset_like_provenance_without_schema_is_rejected_for_every_artifact_kind(self):
        self.fixture.approve_prd("REQ-001")
        fake = {
            "provider": "figma",
            "canonical_url": "https://example.invalid/moving",
        }
        self.assertTrue(is_external_asset_record(fake))
        for kind in sorted(KINDS - {"defect"}):
            with self.subTest(kind=kind), self.assertRaisesRegex(
                ValueError, "external_asset_unverifiable"
            ):
                draft_artifact(
                    kind,
                    self.inputs_for(kind, provenance=[fake]),
                    repo=self.fixture.repo,
                )

    def test_external_asset_classifier_catches_narrow_partial_signatures(self):
        external_like = (
            {"schema": "doc-warden/external-asset/v2"},
            {"schema": "doc-warden/external-asset/v1"},
            {"egress_projection": "external_asset_pointer/v1"},
            {"egress_projection": "external_asset_pointer/v0"},
            {
                "provider": "local",
                "source_path": ".planning/assets/moving.png",
            },
            {
                "provider": "invented",
                "canonical_url": "https://example.invalid/moving",
            },
            {
                "canonical_url": "https://example.invalid/moving",
                "immutable_revision": "moving-revision",
                "export_sha256": "a" * 64,
            },
            {
                "immutable_revision": "moving-revision",
                "export_sha256": "a" * 64,
            },
        )
        for record in external_like:
            with self.subTest(record=record):
                self.assertTrue(is_external_asset_record(record))
                with self.assertRaisesRegex(ValueError, "external_asset_unverifiable"):
                    draft_artifact(
                        "release",
                        {"title": "Release", "provenance": [record]},
                        repo=self.fixture.repo,
                    )
        ordinary = (
            {"requirements": [{"id": "REQ-001"}]},
            {"source": "approved-prd", "revision": "2", "owner": "product"},
            {"canonical_url": "https://example.invalid/decision"},
        )
        for record in ordinary:
            with self.subTest(record=record):
                self.assertFalse(is_external_asset_record(record))
                preview = draft_artifact(
                    "release",
                    {"title": "Release", "provenance": [record]},
                    repo=self.fixture.repo,
                )
                self.assertTrue(preview.artifact_id.startswith("REL-"))

    def test_asset_rejects_invalid_final_provenance_despite_valid_decoy(self):
        invalid = self.record()
        invalid.pop("immutable_revision")
        with self.assertRaisesRegex(ValueError, "external_asset_unverifiable"):
            draft_artifact(
                "asset",
                {
                    "title": "Asset",
                    "external_asset": self.record(),
                    "provenance": [invalid],
                },
                repo=self.fixture.repo,
            )

    def test_explicit_provenance_cannot_diverge_from_external_asset_input(self):
        with self.assertRaisesRegex(ValueError, "external_asset_provenance_mismatch"):
            draft_artifact(
                "release",
                {
                    "title": "Release",
                    "external_asset": self.record(),
                    "provenance": [
                        self.record(
                            immutable_revision="figma-revision-456",
                            export_sha256="b" * 64,
                        )
                    ],
                },
                repo=self.fixture.repo,
            )
        record = self.record()
        ordinary = {"review_context": "fixture"}
        preview = draft_artifact(
            "release",
            {
                "title": "Release",
                "external_asset": record,
                "provenance": [ordinary, dict(record)],
            },
            repo=self.fixture.repo,
        )
        self.assertEqual(
            self.metadata_for(preview)["provenance"],
            [record, ordinary],
        )

    def test_outcome_authority_cannot_be_supplied_as_external_asset_provenance(self):
        for kind, field in (("release", "release_evidence"), ("uat", "outcome_evidence")):
            with self.subTest(kind=kind), self.assertRaisesRegex(
                ValueError, "outcome_authority_provenance_is_derived"
            ):
                draft_artifact(kind, {
                    "title": kind, "external_asset": self.record(), "provenance": [{field: "verified"}],
                }, repo=self.fixture.repo)

    def test_valid_final_external_asset_provenance_allows_artifacts(self):
        asset = draft_artifact(
            "asset",
            {"title": "Asset", "provenance": [self.record()]},
            repo=self.fixture.repo,
        )
        release = draft_artifact(
            "release",
            {"title": "Release", "external_asset": self.record()},
            repo=self.fixture.repo,
        )
        self.assertTrue(asset.artifact_id.startswith("ASSET-"))
        self.assertTrue(release.artifact_id.startswith("REL-"))


if __name__ == "__main__":
    unittest.main()
