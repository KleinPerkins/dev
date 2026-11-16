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

    def persist_design(self, *, lifecycle="approved", version=1, supersedes=None):
        inputs = {
            "title": "Design",
            "lifecycle": lifecycle,
            "version": version,
            "supersedes": supersedes,
        }
        if lifecycle == "approved":
            inputs["approval"] = self.approval()
            inputs["design"] = self.design_contract()
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
        persisted = self.persist_design(version=2)
        preview = draft_artifact(
            "plan",
            {
                "title": "Plan",
                "approved_prd": True,
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
                    "approved_prd": True,
                    "design_ids": [approved.artifact_id],
                    "design_versions": {approved.artifact_id: 2},
                },
                repo=self.fixture.repo,
            )
        successor = self.persist_design(
            version=2,
            supersedes=approved.artifact_id,
        )
        with self.assertRaisesRegex(ValueError, "^plan_design_binding_stale$"):
            draft_artifact(
                "plan",
                {
                    "title": "Superseded design",
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
        design_id = f"DESIGN-{self.fixture.repository_key}-{self.fixture.id_for('design')}"
        artifact_root = self.fixture.repo / ".planning/artifacts"
        artifact_root.mkdir(parents=True, exist_ok=True)
        (artifact_root / "malformed.md").write_text("not canonical\n")
        with self.assertRaisesRegex(ValueError, "^design_artifact_state_invalid$"):
            draft_artifact(
                "plan",
                {
                    "title": "Plan",
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

    def test_release_artifact_binds_plan_verification_uat_commit_and_pr(self):
        preview = draft_artifact(
            "release",
            {
                "title": "Release",
                "lifecycle": "approved",
                "approval": self.approval(),
                "release_evidence": {
                    "plan": "PLAN-001",
                    "verification": "VER-001",
                    "uat": "UAT-001",
                    "commit": "a" * 40,
                    "pull_request": "https://github.com/KleinPerkins/dev/pull/1",
                },
            },
            repo=self.fixture.repo,
        )
        apply_preview(preview, consent_for(preview.transaction))
        metadata = parse_artifact(self.fixture.repo / preview.artifact_path).metadata
        self.assertEqual(metadata["type"], "release")


if __name__ == "__main__":
    unittest.main()
