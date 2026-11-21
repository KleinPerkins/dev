import json
import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from doc_warden.artifacts import (
    _missing_requirement_coverage,
    apply_preview,
    consent_for,
    draft_artifact,
    validate_plan_design_bindings,
)
from doc_warden.canonical import canonical_json, digest_ref, parse_artifact
from doc_warden.gsd_adapter import (
    BEGIN_REQUIREMENTS,
    END_REQUIREMENTS,
    project_current_view,
    requirements_current_view,
)
from doc_warden.operation_store import load_preview, store_preview
from doc_warden.review_admission import _dev_reviewer, _job_proves_delivery, _public_dev_git_tuple, verify_dev_review
from fixture_factory import FixtureFactory


ROOT = Path(__file__).resolve().parents[4]
WRAPPER = ROOT / "_ops/bin/doc-warden.sh"


class ProductLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create("product")

    def tearDown(self):
        repo_path = self.fixture.repo
        self.fixture.cleanup()
        self.assertFalse(repo_path.exists())

    def approval(self):
        return {"approved_by": "operator", "approved_at": "2026-08-30T00:00:00Z"}

    def external_asset(self):
        return {
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

    def external_asset_observation(self, record):
        return {
            "schema": "doc-warden/external-asset-observation/v1",
            "external_asset_digest": digest_ref(canonical_json(record)),
            "observed_revision": record["immutable_revision"],
            "observed_export_sha256": record["export_sha256"],
            "observed_at": "2026-08-30T00:01:00Z",
            "observed_by": "design-reviewer",
            "observation_method": "read_only_provider_observation",
        }

    def design_contract(self):
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
            "approval": self.approval(),
            "verification_rubric": {
                "state_matrix": "complete",
                "accessibility": "complete",
                "responsive": "complete",
            },
        }

    def active_design(self, design_id, version):
        return {
            "id": design_id,
            "version": version,
            "lifecycle": "approved",
            "approval": self.approval(),
        }

    def persist_visual_asset(self):
        record = self.external_asset()
        asset = draft_artifact("asset", {
            "title": "Fixture visual", "lifecycle": "approved", "approval": self.approval(),
            "external_asset": record,
            "external_asset_observations": [self.external_asset_observation(record)],
        }, repo=self.fixture.repo)
        apply_preview(asset, consent_for(asset.transaction))
        return asset.artifact_id

    def persist_design(self, *, lifecycle="approved", version=1, supersedes=None, visual_asset=None):
        inputs = {
            "title": "Design",
            "lifecycle": lifecycle,
            "version": version,
            "supersedes": supersedes,
        }
        if lifecycle == "approved":
            inputs["approval"] = self.approval()
            inputs["design"] = self.design_contract()
            if visual_asset:
                inputs["design"]["visual_assets"] = [visual_asset]
        preview = draft_artifact("design", inputs, repo=self.fixture.repo)
        apply_preview(preview, consent_for(preview.transaction))
        return preview

    def persist_prd(self, requirements, *, supersedes=None):
        preview = draft_artifact(
            "prd",
            {
                "title": "Approved PRD",
                "lifecycle": "approved",
                "approval": self.approval(),
                "requirements": requirements,
                "supersedes": supersedes,
            },
            repo=self.fixture.repo,
            operation_id=str(uuid.uuid4()),
        )
        apply_preview(preview, consent_for(preview.transaction))
        return preview

    def requirements_payload(self):
        rendered = requirements_current_view(self.fixture.repo).decode("utf-8")
        start = rendered.index(BEGIN_REQUIREMENTS) + len(BEGIN_REQUIREMENTS)
        end = rendered.index(END_REQUIREMENTS)
        return json.loads(rendered[start:end])

    def run_cli(self, *arguments):
        with tempfile.TemporaryDirectory(prefix="doc-warden-m2-cli-") as state:
            return subprocess.run(
                ["bash", str(WRAPPER), *arguments],
                text=True,
                capture_output=True,
                check=True,
                env={**os.environ, "XDG_STATE_HOME": str(Path(state) / "xdg-state")},
            )

    def test_project_and_requirements_views_derive_from_approved_versions(self):
        project = draft_artifact(
            "project",
            {
                "title": "Approved project",
                "lifecycle": "approved",
                "approval": self.approval(),
                "body": "# Approved project\n\nPurpose.",
            },
            repo=self.fixture.repo,
            operation_id=str(uuid.uuid4()),
        )
        prd = draft_artifact(
            "prd",
            {
                "title": "Approved PRD",
                "lifecycle": "approved",
                "approval": self.approval(),
                "requirements": [
                    {"id": "REQ-001", "statement": "Show the saved dashboard."}
                ],
                "body": "# Approved PRD\n\nRequirements.",
            },
            repo=self.fixture.repo,
            operation_id=str(uuid.uuid4()),
        )
        apply_preview(project, consent_for(project.transaction))
        apply_preview(prd, consent_for(prd.transaction))
        project_view = project_current_view(self.fixture.repo)
        requirements_view = requirements_current_view(self.fixture.repo)
        self.assertIn(project.artifact_id, project_view.decode("utf-8"))
        self.assertIn(digest_ref((self.fixture.repo / project.artifact_path).read_bytes()), project_view.decode("utf-8"))
        self.assertIn("REQ-001", requirements_view.decode("utf-8"))
        self.assertIn(prd.artifact_id, requirements_view.decode("utf-8"))

    def test_requirements_view_deduplicates_exact_semantic_duplicates(self):
        requirement = {
            "id": "REQ-001",
            "statement": "Show the saved dashboard.",
        }
        previews = [
            self.persist_prd([requirement]),
            self.persist_prd([dict(requirement)]),
        ]

        payload = self.requirements_payload()

        self.assertEqual(
            [
                {
                    key: value
                    for key, value in item.items()
                    if key != "source"
                }
                for item in payload["requirements"]
            ],
            [requirement],
        )
        canonical_source = min(previews, key=lambda preview: preview.artifact_path)
        self.assertEqual(
            payload["requirements"][0]["source"]["artifact_id"],
            canonical_source.artifact_id,
        )

    def test_requirements_view_rejects_conflicting_duplicate_ids_stably(self):
        self.persist_prd(
            [{"id": "REQ-001", "statement": "Show the saved dashboard."}]
        )
        self.persist_prd(
            [{"id": "REQ-001", "statement": "Hide the saved dashboard."}]
        )

        for _attempt in range(2):
            with self.assertRaisesRegex(
                ValueError,
                "^requirement_projection_conflict$",
            ):
                requirements_current_view(self.fixture.repo)

    def test_requirements_view_preserves_canonical_artifact_and_record_order(self):
        records = (
            [
                {"id": "REQ-020", "statement": "Second label."},
                {"id": "REQ-010", "statement": "First label."},
            ],
            [{"id": "REQ-030", "statement": "Third label."}],
        )
        previews = [
            self.persist_prd(records[0]),
            self.persist_prd(records[1]),
        ]
        expected_ids = [
            requirement["id"]
            for preview, requirements in sorted(
                zip(previews, records),
                key=lambda item: item[0].artifact_path,
            )
            for requirement in requirements
        ]

        first = self.requirements_payload()
        second = self.requirements_payload()

        self.assertEqual(
            [item["id"] for item in first["requirements"]],
            expected_ids,
        )
        self.assertEqual(first, second)

    def test_requirements_view_excludes_superseded_prd_before_conflict_check(self):
        original = self.persist_prd(
            [{"id": "REQ-001", "statement": "Stale statement."}]
        )
        successor = self.persist_prd(
            [{"id": "REQ-001", "statement": "Current statement."}],
            supersedes=original.artifact_id,
        )

        payload = self.requirements_payload()

        self.assertEqual(
            [
                (item["id"], item["statement"], item["source"]["artifact_id"])
                for item in payload["requirements"]
            ],
            [("REQ-001", "Current statement.", successor.artifact_id)],
        )

    def test_spec_requires_every_prd_requirement_or_explicit_nonimplementation(self):
        self.fixture.approve_prd("REQ-001", "REQ-002")
        with self.assertRaisesRegex(ValueError, "requirement_coverage_incomplete"):
            draft_artifact(
                "spec",
                {
                    "title": "Spec",
                    "approved_prd": True,
                    "prd_requirements": ["REQ-001", "REQ-002"],
                    "implemented_requirements": ["REQ-001"],
                    "nonimplemented_requirements": {},
                },
                repo=self.fixture.repo,
            )
        preview = draft_artifact(
            "spec",
            {
                "title": "Spec",
                "approved_prd": True,
                "prd_requirements": ["REQ-001", "REQ-002"],
                "implemented_requirements": ["REQ-001"],
                "nonimplemented_requirements": {"REQ-002": "Out of current milestone."},
            },
            repo=self.fixture.repo,
        )
        self.assertTrue(preview.artifact_id.startswith("SPEC-"))

    def test_requirement_coverage_inputs_must_be_json_arrays(self):
        invalid_values = (None, "REQ-001", {"REQ-001": True}, True, False, 1)
        for field in ("prd_requirements", "implemented_requirements"):
            for value in invalid_values:
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaisesRegex(
                        ValueError,
                        f"^{field}_must_be_array$",
                    ),
                ):
                    draft_artifact(
                        "spec",
                        {
                            "title": "Spec",
                            "approved_prd": True,
                            "prd_requirements": ["REQ-001"],
                            "implemented_requirements": [],
                            field: value,
                        },
                        repo=self.fixture.repo,
                    )
        with self.assertRaisesRegex(
            ValueError,
            "^implemented_requirements_must_be_array$",
        ):
            draft_artifact(
                "spec",
                {
                    "title": "Spec",
                    "approved_prd": True,
                    "prd_requirements": [],
                    "implemented_requirements": None,
                },
                repo=self.fixture.repo,
            )

    def test_requirement_coverage_rejects_mixed_empty_and_malformed_arrays(self):
        invalid_items = (
            None,
            True,
            False,
            1,
            1.5,
            {},
            [],
            "",
            " ",
            "req-001",
            "REQ-",
            "REQ--001",
            "REQ-001-",
            "REQ 001",
        )
        for field in ("prd_requirements", "implemented_requirements"):
            for item in invalid_items:
                with (
                    self.subTest(field=field, item=item),
                    self.assertRaisesRegex(
                        ValueError,
                        f"^{field}_item_invalid$",
                    ),
                ):
                    draft_artifact(
                        "spec",
                        {
                            "title": "Spec",
                            "approved_prd": True,
                            "prd_requirements": ["REQ-001"],
                            "implemented_requirements": [],
                            field: ["REQ-001", item],
                        },
                        repo=self.fixture.repo,
                    )

    def test_nonimplemented_requirements_reject_malformed_shapes_and_items(self):
        base = {
            "title": "Spec",
            "approved_prd": True,
            "prd_requirements": ["REQ-001"],
            "implemented_requirements": [],
        }
        for value in (None, True, False, 1, 1.5, "REQ-001"):
            with (
                self.subTest(shape=value),
                self.assertRaisesRegex(
                    ValueError,
                    "^nonimplemented_requirements_must_be_array_or_object$",
                ),
            ):
                draft_artifact(
                    "spec",
                    {**base, "nonimplemented_requirements": value},
                    repo=self.fixture.repo,
                )
        malformed = (
            [None],
            [True],
            [1],
            [{}],
            [""],
            ["req-001"],
            ["REQ--001"],
            {None: "missing key"},
            {"req-001": "wrong case"},
            {"REQ--001": "malformed"},
        )
        for value in malformed:
            with (
                self.subTest(item=value),
                self.assertRaisesRegex(
                    ValueError,
                    "^nonimplemented_requirements_item_invalid$",
                ),
            ):
                draft_artifact(
                    "spec",
                    {**base, "nonimplemented_requirements": value},
                    repo=self.fixture.repo,
                )

    def test_nonimplemented_requirements_support_canonical_lists_and_reason_maps(self):
        self.fixture.approve_prd("REQ-001", "REQ-002")
        for value in (
            ["REQ-002"],
            ["REQ-002", "REQ-002"],
            {"REQ-002": "Out of current milestone."},
        ):
            with self.subTest(value=value):
                inputs = {
                    "title": "Spec",
                    "approved_prd": True,
                    "prd_requirements": ["REQ-001", "REQ-002"],
                    "implemented_requirements": ["REQ-001"],
                    "nonimplemented_requirements": value,
                }
                self.assertEqual(_missing_requirement_coverage(inputs), [])
                preview = draft_artifact(
                    "spec",
                    inputs,
                    repo=self.fixture.repo,
                )
                self.assertTrue(preview.artifact_id.startswith("SPEC-"))

    def test_requirement_coverage_deduplicates_and_preserves_sorted_missing_order(self):
        self.fixture.approve_prd("REQ-001", "REQ-002")
        self.assertEqual(
            _missing_requirement_coverage(
                {
                    "prd_requirements": [
                        "REQ-003",
                        "REQ-001",
                        "REQ-002",
                        "REQ-003",
                    ],
                    "implemented_requirements": ["REQ-002", "REQ-002"],
                    "nonimplemented_requirements": {},
                }
            ),
            ["REQ-001", "REQ-003"],
        )
        preview = draft_artifact(
            "spec",
            {
                "title": "Spec",
                "approved_prd": True,
                "prd_requirements": ["REQ-002", "REQ-001", "REQ-002"],
                "implemented_requirements": ["REQ-001", "REQ-002", "REQ-001"],
                "nonimplemented_requirements": {},
            },
            repo=self.fixture.repo,
        )
        self.assertTrue(preview.artifact_id.startswith("SPEC-"))

    def test_handlers_exist_for_m2_artifact_kinds(self):
        for kind, prefix in (
            ("uxr", "UXR-"),
            ("design", "DESIGN-"),
            ("asset", "ASSET-"),
            ("prototype", "PROTO-"),
            ("sketch", "SKETCH-"),
            ("spike", "SPIKE-"),
            ("verification", "VER-"),
            ("uat", "UAT-"),
            ("release", "REL-"),
        ):
            inputs = {
                "title": kind,
                "lifecycle": "approved",
                "approval": self.approval(),
            }
            if kind == "asset":
                record = self.external_asset()
                inputs["external_asset"] = record
                inputs["external_asset_observations"] = [
                    self.external_asset_observation(record)
                ]
            if kind == "design":
                inputs["design"] = self.design_contract()
            if kind in {"verification", "uat", "release"}:
                inputs["lifecycle"] = "draft"
            preview = draft_artifact(
                kind,
                inputs,
                repo=self.fixture.repo,
            )
            self.assertTrue(preview.artifact_id.startswith(prefix), kind)

    def test_cli_drafts_m2_handlers_without_repository_writes(self):
        before = subprocess.check_output(
            ["git", "-C", str(self.fixture.repo), "status", "--porcelain"],
            text=True,
        )
        result = self.run_cli(
            "draft",
            "uxr",
            "--repo",
            str(self.fixture.repo),
            "--title",
            "UX requirements",
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["artifact_id"].startswith("UXR-"))
        self.assertFalse((self.fixture.repo / payload["artifact_path"]).exists())
        self.assertEqual(
            subprocess.check_output(
                ["git", "-C", str(self.fixture.repo), "status", "--porcelain"],
                text=True,
            ),
            before,
        )

    def test_design_successor_invalidates_bound_plan_until_refined(self):
        plan_id = f"PLAN-{self.fixture.repository_key}-{self.fixture.id_for('plan')}"
        design_id = f"DESIGN-{self.fixture.repository_key}-{self.fixture.id_for('design')}"
        self.assertEqual(
            validate_plan_design_bindings(
                {
                    "id": plan_id,
                    "design_ids": [design_id],
                    "design_versions": {design_id: 1},
                },
                {design_id: self.active_design(design_id, 2)},
            ),
            [design_id],
        )
        self.assertEqual(
            validate_plan_design_bindings(
                {
                    "id": plan_id,
                    "design_ids": [design_id],
                    "design_versions": {design_id: 2},
                },
                {design_id: self.active_design(design_id, 2)},
            ),
            [],
        )

    def test_design_version_semantic_equality_is_canonicalized(self):
        self.fixture.approve_prd("REQ-001")
        uxr_id = self.fixture.approve_uxr()
        design_id = f"DESIGN-{self.fixture.repository_key}-{self.fixture.id_for('design')}"
        self.assertEqual(
            validate_plan_design_bindings(
                {
                    "design_ids": [design_id],
                    "design_versions": {design_id: "2"},
                },
                {design_id: self.active_design(design_id, 2)},
            ),
            [],
        )
        self.assertEqual(
            validate_plan_design_bindings(
                {
                    "design_ids": [design_id],
                    "design_versions": {design_id: 2},
                },
                {design_id: self.active_design(design_id, "2")},
            ),
            [],
        )
        persisted = self.persist_design(version=2, visual_asset=self.persist_visual_asset())
        preview = draft_artifact(
            "plan",
            {
                "title": "Plan",
                "approved_prd": True,
                "uxr_id": uxr_id,
                "design_ids": [persisted.artifact_id],
                "design_versions": {persisted.artifact_id: "2"},
            },
            repo=self.fixture.repo,
        )
        sidecar = json.loads(preview.transaction.actions[-1].content)
        self.assertEqual(
            sidecar["design_versions"],
            {persisted.artifact_id: 2},
        )

    def test_design_version_normalization_rejects_malformed_values(self):
        self.fixture.approve_prd("REQ-001")
        design_id = f"DESIGN-{self.fixture.repository_key}-{self.fixture.id_for('design')}"
        malformed = (True, False, 2.0, "2.0", " 2", "02", 0, -1, None, [], {})
        for value in malformed:
            with self.subTest(value=value), self.assertRaisesRegex(
                ValueError, "design_version_invalid"
            ):
                draft_artifact(
                    "plan",
                    {
                        "title": "Plan",
                        "approved_prd": True,
                        "design_ids": [design_id],
                        "design_versions": {design_id: value},
                    },
                    repo=self.fixture.repo,
                )
        with self.assertRaisesRegex(ValueError, "design_versions_must_be_object"):
            draft_artifact(
                "plan",
                {
                    "title": "Plan",
                    "approved_prd": True,
                    "design_ids": [design_id],
                    "design_versions": [2],
                },
                repo=self.fixture.repo,
            )
        with self.assertRaisesRegex(ValueError, "design_version_invalid"):
            validate_plan_design_bindings(
                {
                    "design_ids": [design_id],
                    "design_versions": {design_id: 2},
                },
                {design_id: {"version": True, "lifecycle": "approved"}},
            )

    def test_canonical_design_versions_preserve_true_stale_detection(self):
        design_id = f"DESIGN-{self.fixture.repository_key}-{self.fixture.id_for('design')}"
        self.assertEqual(
            validate_plan_design_bindings(
                {
                    "design_ids": [design_id],
                    "design_versions": {design_id: "2"},
                },
                {design_id: self.active_design(design_id, 3)},
            ),
            [design_id],
        )

    def test_null_design_versions_are_empty_only_without_design_ids(self):
        self.fixture.approve_prd("REQ-001")
        plan_id = f"PLAN-{self.fixture.repository_key}-{self.fixture.id_for('plan')}"
        design_id = f"DESIGN-{self.fixture.repository_key}-{self.fixture.id_for('design')}"
        with self.assertRaisesRegex(ValueError, "^plan_design_binding_incomplete$"):
            validate_plan_design_bindings(
                {
                    "id": plan_id,
                    "design_ids": [design_id],
                    "design_versions": None,
                },
                {design_id: self.active_design(design_id, 1)},
            )
        with self.assertRaisesRegex(ValueError, "^plan_design_binding_incomplete$"):
            draft_artifact(
                "plan",
                {
                    "title": "Plan",
                    "approved_prd": True,
                    "design_ids": [design_id],
                    "design_versions": None,
                },
                repo=self.fixture.repo,
            )
        preview = draft_artifact(
            "plan",
            {
                "title": "Plan",
                "approved_prd": True,
                "design_versions": None,
            },
            repo=self.fixture.repo,
        )
        sidecar = json.loads(preview.transaction.actions[-1].content)
        self.assertEqual(sidecar["design_versions"], {})

    def test_missing_bound_design_marks_plan_stale(self):
        plan_id = f"PLAN-{self.fixture.repository_key}-{self.fixture.id_for('plan')}"
        design_id = f"DESIGN-{self.fixture.repository_key}-{self.fixture.id_for('design')}"
        plan = {
            "id": plan_id,
            "design_ids": [design_id],
            "design_versions": {design_id: 1},
        }
        self.assertEqual(validate_plan_design_bindings(plan, {}), [design_id])
        self.assertEqual(
            validate_plan_design_bindings(
                plan,
                {design_id: self.active_design(design_id, 1)},
            ),
            [],
        )

    def test_plan_draft_refuses_incomplete_or_malformed_design_bindings(self):
        self.fixture.approve_prd("REQ-001")
        design_id = f"DESIGN-{self.fixture.repository_key}-{self.fixture.id_for('design')}"
        other_id = f"DESIGN-{self.fixture.repository_key}-{self.fixture.id_for('other-design')}"
        incomplete = (
            {"design_ids": [design_id], "design_versions": None},
            {"design_ids": [design_id], "design_versions": {}},
            {"design_ids": [], "design_versions": {design_id: 1}},
            {
                "design_ids": [design_id],
                "design_versions": {other_id: 1},
            },
        )
        for bindings in incomplete:
            with (
                self.subTest(bindings=bindings),
                self.assertRaisesRegex(
                    ValueError,
                    "^plan_design_binding_incomplete$",
                ),
            ):
                draft_artifact(
                    "plan",
                    {
                        "title": "Plan",
                        "approved_prd": True,
                        **bindings,
                    },
                    repo=self.fixture.repo,
                )
        malformed_ids = (None, design_id, True, 1, {}, [None], [True], ["DESIGN-"])
        for value in malformed_ids:
            expected = (
                "design_ids_item_invalid"
                if isinstance(value, list)
                else "design_ids_must_be_array"
            )
            with (
                self.subTest(design_ids=value),
                self.assertRaisesRegex(ValueError, f"^{expected}$"),
            ):
                draft_artifact(
                    "plan",
                    {
                        "title": "Plan",
                        "approved_prd": True,
                        "design_ids": value,
                    },
                    repo=self.fixture.repo,
                )

    def test_plan_draft_requires_active_approved_on_disk_design(self):
        self.fixture.approve_prd("REQ-001")
        uxr_id = self.fixture.approve_uxr()
        missing_id = (
            f"DESIGN-{self.fixture.repository_key}-{self.fixture.id_for('missing-design')}"
        )
        before = list((self.fixture.repo / ".planning/artifacts").glob("PLAN-*.md"))
        with patch("doc_warden.artifacts.preview_transaction") as emit_preview:
            with self.assertRaisesRegex(ValueError, "^plan_design_binding_stale$"):
                draft_artifact(
                    "plan",
                    {
                        "title": "Missing design",
                        "uxr_id": uxr_id,
                        "approved_prd": True,
                        "design_ids": [missing_id],
                        "design_versions": {missing_id: 1},
                    },
                    repo=self.fixture.repo,
                )
            emit_preview.assert_not_called()
        unapproved = self.persist_design(lifecycle="draft")
        with self.assertRaisesRegex(ValueError, "^plan_design_binding_stale$"):
            draft_artifact(
                "plan",
                {
                    "title": "Unapproved design",
                    "uxr_id": uxr_id,
                    "approved_prd": True,
                    "design_ids": [unapproved.artifact_id],
                    "design_versions": {unapproved.artifact_id: 1},
                },
                repo=self.fixture.repo,
            )
        approved = self.persist_design()
        with self.assertRaisesRegex(ValueError, "^plan_design_binding_stale$"):
            draft_artifact(
                "plan",
                {
                    "title": "Mismatched design version",
                    "uxr_id": uxr_id,
                    "approved_prd": True,
                    "design_ids": [approved.artifact_id],
                    "design_versions": {approved.artifact_id: 2},
                },
                repo=self.fixture.repo,
            )
        successor = self.persist_design(
            version=2,
            supersedes=approved.artifact_id,
            visual_asset=self.persist_visual_asset(),
        )
        with self.assertRaisesRegex(ValueError, "^plan_design_binding_stale$"):
            draft_artifact(
                "plan",
                {
                    "title": "Superseded design",
                    "uxr_id": uxr_id,
                    "approved_prd": True,
                    "design_ids": [approved.artifact_id],
                    "design_versions": {approved.artifact_id: 1},
                },
                repo=self.fixture.repo,
            )
        self.assertEqual(
            list((self.fixture.repo / ".planning/artifacts").glob("PLAN-*.md")),
            before,
        )
        valid = draft_artifact(
            "plan",
            {
                "title": "Active design",
                "uxr_id": uxr_id,
                "approved_prd": True,
                "design_ids": [successor.artifact_id, successor.artifact_id],
                "design_versions": {successor.artifact_id: 2},
            },
            repo=self.fixture.repo,
        )
        sidecar = json.loads(valid.transaction.actions[-1].content)
        self.assertEqual(sidecar["design_ids"], [successor.artifact_id])
        self.assertEqual(
            sidecar["design_versions"],
            {successor.artifact_id: 2},
        )

    def test_plan_draft_refuses_malformed_design_artifact_state(self):
        self.fixture.approve_prd("REQ-001")
        uxr_id = self.fixture.approve_uxr()
        design_id = f"DESIGN-{self.fixture.repository_key}-{self.fixture.id_for('design')}"
        artifact_root = self.fixture.repo / ".planning/artifacts"
        artifact_root.mkdir(parents=True, exist_ok=True)
        (artifact_root / "malformed.md").write_text("not canonical\n")
        with self.assertRaisesRegex(ValueError, "^design_artifact_state_invalid$"):
            draft_artifact(
                "plan",
                {
                    "title": "Plan",
                    "uxr_id": uxr_id,
                    "approved_prd": True,
                    "design_ids": [design_id],
                    "design_versions": {design_id: 1},
                },
                repo=self.fixture.repo,
            )
        self.assertEqual(
            list(artifact_root.glob("PLAN-*.md")),
            [],
        )

    def test_dev_review_reads_public_git_objects_before_using_them(self):
        head, base = "a" * 40, "b" * 40
        reviewer = _dev_reviewer((ROOT / "scripts/reviewer_app.py").read_bytes(), base)
        # Simulate the subprocess replies while using the real App helper for
        # the case where the first shallow fetch cannot establish the merge base.
        with patch("doc_warden.review_admission.subprocess.run") as git:
            first_search = subprocess.CompletedProcess([], 1)
            success = subprocess.CompletedProcess([], 0)

            def write(command, *, stdout, **options):
                previous = len(git.call_args_list)
                expected = ("init", "fetch", "merge-base", "fetch", "merge-base", "diff")
                self.assertIn(expected[previous - 1], command)
                if "fetch" in command:
                    self.assertEqual(command[-3:], ["https://github.com/KleinPerkins/dev.git", base, head])
                elif "merge-base" in command:
                    if previous == 3:
                        return first_search
                    stdout.write((base + "\n").encode("ascii"))
                elif "diff" in command:
                    stdout.write(b"exact fixture diff\n")
                return success

            git.side_effect = write
            self.assertEqual(_public_dev_git_tuple(reviewer, head, base),
                             (base, reviewer.digest(b"exact fixture diff\n")))
            self.assertEqual(git.call_count, 6)

    def test_dev_review_refuses_modified_helper_before_execution(self):
        with self.assertRaisesRegex(ValueError, "^release_delivery_review_unverified$"):
            _dev_reviewer(b"raise AssertionError('unverified code ran')\n", "a" * 40)

    def test_dev_review_checks_squash_parent_before_reading_any_helper(self):
        head, base, commit = "a" * 40, "b" * 40, "c" * 40
        read = unittest.mock.Mock(return_value={"sha": commit, "parents": [{"sha": base}, {"sha": head}]})
        read_log = unittest.mock.Mock()
        with self.assertRaisesRegex(ValueError, "^release_delivery_review_unverified$"):
            verify_dev_review(read, read_log, {}, {}, commit=commit, head=head, armed=False)
        read.assert_called_once_with(f"/git/commits/{commit}")
        read_log.assert_not_called()

    def test_dev_review_reads_helper_at_immutable_parent_after_default_branch_advances(self):
        head, original_base, commit, tip = (letter * 40 for letter in "abcd")
        pull = {"base": {"sha": tip}}
        read = unittest.mock.Mock(side_effect=[
            {"sha": commit, "parents": [{"sha": original_base}]}, {"encoding": "base64", "content": "eA=="},
        ])
        with patch("doc_warden.review_admission._dev_reviewer", side_effect=ValueError) as load:
            with self.assertRaisesRegex(ValueError, "^release_delivery_review_unverified$"):
                verify_dev_review(read, unittest.mock.Mock(), pull, {}, commit=commit, head=head, armed=False)
        self.assertEqual(read.call_args_list, [
            unittest.mock.call(f"/git/commits/{commit}"),
            unittest.mock.call(f"/contents/scripts/reviewer_app.py?ref={original_base}"),
        ])
        load.assert_called_once_with(b"x", original_base)

    def test_dev_review_requires_protected_witness_for_direct_squash_or_armed_delivery(self):
        current = {"repository_id": 1459458379, "head_sha": "a" * 40, "base_sha": "b" * 40}
        commit = "c" * 40
        admission = {"status": "qualified-read-only", "tuple": current, "mutated": False}
        direct = {"status": "merged", "merged": True, "head_sha": current["head_sha"],
                  "base_sha": current["base_sha"], "merge_sha": commit}
        requested = {"status": "armed", "merged": False, "head_sha": current["head_sha"]}

        def witness(*records, second_target=10):
            messages = ["TARGET_PR: 10", f"TARGET_PR: {second_target}", *(json.dumps(row) for row in records)]
            return b"".join(f"2026-11-21T00:00:00.000Z {message}\n".encode() for message in messages)

        self.assertTrue(_job_proves_delivery(witness(admission, direct), current, number=10, commit=commit, armed=False))
        self.assertTrue(_job_proves_delivery(witness(admission, requested), current, number=10, commit=commit, armed=True))
        for log, armed in (
            (witness(direct), False),
            (witness(admission, direct, second_target=11), False),
            (witness(admission, direct | {"merge_sha": "d" * 40}), False),
            (witness(admission, direct, direct), False),
            (witness(admission, requested), False),
        ):
            with self.subTest(log=log, armed=armed):
                self.assertFalse(_job_proves_delivery(log, current, number=10, commit=commit, armed=armed))

    def test_release_artifact_binds_plan_verification_uat_commit_and_pr(self):
        repo = self.fixture.repo
        profile_path = repo / ".planning/doc-warden.json"
        profile = json.loads(profile_path.read_bytes())
        profile_path.write_bytes(canonical_json(profile | {"github_repository_id": 1459458379}))
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                        "git@github.com:KleinPerkins/dev.git"], check=True)
        self.fixture.approve_prd("REQ-001")
        lifecycle = {"lifecycle": "approved", "approval": self.approval()}
        plan = draft_artifact("plan", {"title": "Plan", **lifecycle}, repo=repo)
        apply_preview(plan, consent_for(plan.transaction))
        head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        proof = {"path": "README.md", "digest": digest_ref((repo / "README.md").read_bytes())}
        outcomes = {}
        for kind, result in (("verification", "passed"), ("uat", "accepted")):
            record = draft_artifact(kind, {"title": kind, **lifecycle, "outcome_evidence": {
                "plan": plan.artifact_id, "source_revision": head,
                "requirements": {"REQ-001": proof | {"result": result}}, "visual_checks": {},
            }}, repo=repo)
            apply_preview(record, consent_for(record.transaction))
            outcomes[kind] = record.artifact_id
        evidence = {"plan": plan.artifact_id, "commit": head,
                    "pull_request": "https://github.com/KleinPerkins/dev/pull/1", **outcomes}
        reviewed_head, tip, admitted_base = "a" * 40, "b" * 40, "c" * 40
        prefix = "repos/KleinPerkins/dev"
        delivery_rows = {
            prefix: {"id": 1459458379, "full_name": "KleinPerkins/dev", "default_branch": "main"},
            prefix + "/pulls/1": {
                "number": 1, "node_id": "fixture-pull-node", "auto_merge": None,
                "base": {"ref": "main", "sha": admitted_base, "repo": {"id": 1459458379}},
                "head": {"sha": reviewed_head}, "merge_commit_sha": head,
                "merged": True, "state": "closed", "merged_at": "2026-08-30T00:00:00Z",
                "merged_by": {"id": 299927791},
            },
            prefix + "/branches/main": {"commit": {"sha": tip}},
            prefix + f"/compare/{head}...{tip}": {"status": "ahead", "merge_base_commit": {"sha": head}},
            prefix + "/pulls/1/reviews?per_page=100": [
                {"user": {"id": 299927791}, "commit_id": reviewed_head, "state": "APPROVED"},
            ],
            prefix + f"/commits/{reviewed_head}/check-runs?check_name=ci-required&filter=latest": {"check_runs": [
                {"id": 123, "app": {"id": 15368}, "head_sha": reviewed_head, "name": "ci-required",
                 "status": "completed", "conclusion": "success"},
            ]},
        }
        app_actor = {"__typename": "Bot", "login": "chaos-scheduler-automerge", "databaseId": 299927791}
        timeline = {"pageInfo": {"hasNextPage": False}, "nodes": [
            {"__typename": "MergedEvent", "actor": app_actor, "commit": {"oid": head}},
        ]}
        delivery_rows["graphql"] = {"data": {"repository": {"databaseId": 1459458379, "pullRequest": {
            "id": "fixture-pull-node", "merged": True, "mergeCommit": {"oid": head},
            "autoMergeRequest": None, "timelineItems": timeline,
        }}}}

        def draft(**changes):
            return draft_artifact("release", {"title": "Release", **lifecycle,
                                  "release_evidence": evidence | changes}, repo=repo)

        def github(endpoint, **options):
            return delivery_rows[endpoint]

        review_digest = digest_ref(b"fixture originating-account review evidence")
        with patch("doc_warden.release_delivery.github_json", side_effect=github) as remote, patch(
            "doc_warden.release_delivery.verify_dev_review", return_value=review_digest,
        ) as originating_review:
            with self.assertRaisesRegex(ValueError, "release_delivery_repository_mismatch"):
                draft(pull_request="https://github.com/another/repo/pull/1")
            remote.assert_not_called()
            for endpoint, updates, code in (
                ("/pulls/1", {"merged": False}, "release_delivery_merge_unverified"),
                ("/pulls/1", {"merge_commit_sha": reviewed_head}, "release_delivery_merge_unverified"),
                ("/pulls/1", {"merged_by": {"id": 1234}}, "release_delivery_app_unverified"),
                (f"/compare/{head}...{tip}", {"status": "diverged"}, "release_delivery_merge_unverified"),
                (f"/commits/{reviewed_head}/check-runs?check_name=ci-required&filter=latest",
                 {"check_runs": []}, "release_delivery_ci_unverified"),
            ):
                with self.subTest(endpoint=endpoint, updates=updates), patch.dict(
                    delivery_rows[prefix + endpoint], updates,
                ), self.assertRaisesRegex(ValueError, code):
                    draft()
            for actor in (None, {"__typename": "User", "login": "another-actor"}):
                armed = {"__typename": "AutoMergeEnabledEvent", "actor": actor}
                with self.subTest(actor=actor), patch.dict(timeline, {"nodes": [armed, *timeline["nodes"]]}):
                    with self.assertRaisesRegex(ValueError, "release_delivery_automation_unverified"):
                        draft()
            with patch("doc_warden.release_delivery.verify_dev_review",
                       side_effect=ValueError("release_delivery_review_unverified")):
                with self.assertRaisesRegex(ValueError, "release_delivery_review_unverified"):
                    draft()

            preview = draft()
            consent = consent_for(preview.transaction)
            with tempfile.TemporaryDirectory() as state, patch.dict(os.environ, {"XDG_STATE_HOME": state}):
                store_preview(preview.transaction)
                resumed = load_preview(preview.transaction.operation_id, preview.transaction.action_digest)
                with patch.dict(delivery_rows[prefix + "/pulls/1"], {"merged": False}):
                    with self.assertRaisesRegex(ValueError, "release_delivery_merge_unverified"):
                        apply_preview(resumed, consent)
                self.assertFalse((repo / preview.artifact_path).exists())
                receipt = apply_preview(resumed, consent)
                self.assertEqual(receipt["bindings"]["release_delivery"]["reviewed_commit"], reviewed_head)
                self.assertEqual(receipt["bindings"]["release_delivery"]["review_receipt_digest"], review_digest)
                originating_review.assert_called_with(
                    unittest.mock.ANY, unittest.mock.ANY, delivery_rows[prefix + "/pulls/1"],
                    delivery_rows[prefix + "/pulls/1/reviews?per_page=100"][0],
                    commit=head, head=reviewed_head, armed=False,
                )
                remote.side_effect = ValueError("release_delivery_unavailable")
                self.assertEqual(apply_preview(resumed, consent), receipt)
        metadata = parse_artifact(self.fixture.repo / preview.artifact_path).metadata
        self.assertEqual(metadata["type"], "release")
        (repo / "README.md").write_text("Modified evidence.\n")
        with self.assertRaisesRegex(ValueError, "outcome_evidence_changed"):
            draft_artifact("release", {"title": "Stale proof", **lifecycle, "release_evidence": evidence}, repo=repo)

    def test_visual_acceptance_requires_complete_scope_and_exact_design_revision(self):
        repo = self.fixture.repo
        self.fixture.approve_prd("REQ-001")
        uxr = self.fixture.approve_uxr()
        asset = self.persist_visual_asset()
        design = self.persist_design(visual_asset=asset)
        lifecycle = {"lifecycle": "approved", "approval": self.approval()}
        plan = draft_artifact("plan", {"title": "Visual plan", **lifecycle, "uxr_id": uxr,
                                       "design_ids": [design.artifact_id], "design_versions": {design.artifact_id: 1}},
                              repo=repo)
        apply_preview(plan, consent_for(plan.transaction))
        head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        row = {"path": "README.md", "digest": digest_ref((repo / "README.md").read_bytes()), "result": "accepted"}
        fields = {"plan": plan.artifact_id, "source_revision": head,
                  "requirements": {"REQ-001": row}, "visual_checks": {}}
        with self.assertRaisesRegex(ValueError, "outcome_coverage_incomplete"):
            draft_artifact("uat", {"title": "Incomplete visual UAT", **lifecycle, "outcome_evidence": fields}, repo=repo)
        fields["visual_checks"] = {item: row for item in (
            "comparison", "states", "accessibility", "responsive", "copy", "recovery", "assets",
        )}
        approved = draft_artifact("uat", {"title": "Visual UAT", **lifecycle, "outcome_evidence": fields}, repo=repo)
        apply_preview(approved, consent_for(approved.transaction))
        self.persist_design(version=2, supersedes=design.artifact_id, visual_asset=asset)
        with self.assertRaisesRegex(ValueError, "authority_artifact_required"):
            draft_artifact("uat", {"title": "Stale visual UAT", **lifecycle, "outcome_evidence": fields}, repo=repo)


if __name__ == "__main__":
    unittest.main()
