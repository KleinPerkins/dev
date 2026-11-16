import subprocess
import os
import unittest
import uuid
from pathlib import Path

from doc_warden.canonical import digest_ref
from doc_warden.gsd_adapter import (
    ALLOWED_OUTPUTS,
    AuthoringResult,
    AuthoringScope,
    apply_authoring_result,
    authoring_result_from_envelope,
    prepare_authoring_import,
    validate_authoring_result,
)
from fixture_factory import FixtureFactory


class GsdAdapterTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create()

    def tearDown(self):
        self.fixture.cleanup()

    def scope(self, **overrides):
        values = {
            "repo": self.fixture.repo,
            "operation_id": str(uuid.uuid4()),
        }
        values.update(overrides)
        return AuthoringScope(**values)

    def result(self, preview, outputs, **overrides):
        values = {
            "source_revision": preview.source_revision,
            "pin_digest": preview.pin_digest,
            "outputs": outputs,
            "checker_passed": True,
        }
        values.update(overrides)
        return AuthoringResult(**values)

    def test_adapter_refuses_wrong_gsd_pin(self):
        preview = prepare_authoring_import(self.scope())
        with self.assertRaisesRegex(ValueError, "wrong_gsd_pin"):
            validate_authoring_result(
                preview,
                self.result(
                    preview,
                    {".planning/STATE.md": b"state\n"},
                    pin_digest="sha256:" + "0" * 64,
                ),
            )

    def test_missing_result_file_reports_digest_mismatch(self):
        preview = prepare_authoring_import(self.scope())
        raw = {
            "source_revision": preview.source_revision,
            "pin_digest": preview.pin_digest,
            "changed_file_digests": {
                ".planning/STATE.md": "sha256:" + "0" * 64
            },
            "checker_passed": True,
            "commands": [],
            "assumptions_changed": False,
        }
        with self.assertRaisesRegex(ValueError, "authoring_result_digest_mismatch"):
            authoring_result_from_envelope(self.fixture.repo, raw)

    def test_gsd_run_and_gsd_tools_are_never_used_as_agentic_workflow_apis(self):
        source = (
            Path(__file__).resolve().parents[1] / "doc_warden/gsd_adapter.py"
        ).read_text()
        self.assertNotIn("gsd_run", source)
        self.assertNotIn("gsd-tools", source)
        self.assertNotIn("Popen(", source)

    def test_import_preview_names_exact_root_pin_inputs_and_allowed_outputs(self):
        input_path = self.fixture.repo / ".planning/PROJECT.md"
        input_path.write_text("project\n")
        preview = prepare_authoring_import(
            self.scope(input_paths=(".planning/PROJECT.md",))
        )
        self.assertEqual(preview.canonical_root, str(self.fixture.repo.resolve()))
        self.assertEqual(preview.allowed_outputs, ALLOWED_OUTPUTS)
        self.assertEqual(
            preview.input_digests[".planning/PROJECT.md"], digest_ref(b"project\n")
        )
        self.assertEqual(preview.disposition, "operator_invoke_required")

    def test_prepare_refuses_symlinked_input(self):
        target = self.fixture.repo / "outside.txt"
        target.write_text("outside\n")
        link = self.fixture.repo / ".planning/input.md"
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, link)
        with self.assertRaises(ValueError):
            prepare_authoring_import(self.scope(input_paths=(".planning/input.md",)))

    def test_unexpected_authoring_result_path_is_refused(self):
        preview = prepare_authoring_import(self.scope())
        with self.assertRaisesRegex(ValueError, "unexpected_authoring_delta"):
            validate_authoring_result(
                preview, self.result(preview, {"src/implementation.py": b"pass\n"})
            )

    def test_result_envelope_refuses_traversal_and_command_type_confusion(self):
        preview = prepare_authoring_import(self.scope())
        base = {
            "source_revision": preview.source_revision,
            "pin_digest": preview.pin_digest,
            "changed_file_digests": {"../../outside": "sha256:" + "0" * 64},
            "checker_passed": True,
            "commands": [],
            "assumptions_changed": False,
        }
        with self.assertRaises(ValueError):
            authoring_result_from_envelope(self.fixture.repo, base)
        state = self.fixture.repo / ".planning/STATE.md"
        state.write_text("state\n")
        with self.assertRaisesRegex(ValueError, "contract_invalid"):
            authoring_result_from_envelope(
                self.fixture.repo,
                base
                | {
                    "changed_file_digests": {
                        ".planning/STATE.md": digest_ref(state.read_bytes())
                    },
                    "commands": "git push origin main",
                },
            )

    def test_result_envelope_rejects_prohibited_extra_fields(self):
        preview = prepare_authoring_import(self.scope())
        state = self.fixture.repo / ".planning/STATE.md"
        state.write_text("state\n")
        raw = {
            "source_revision": preview.source_revision,
            "pin_digest": preview.pin_digest,
            "changed_file_digests": {
                ".planning/STATE.md": digest_ref(state.read_bytes())
            },
            "checker_passed": True,
            "commands": [],
            "assumptions_changed": False,
            "transcript": "must not be accepted",
        }
        with self.assertRaisesRegex(ValueError, "contract_invalid"):
            authoring_result_from_envelope(self.fixture.repo, raw)

    def test_project_requirements_roadmap_state_and_plan_projection_matrix_matches_exact_pin(self):
        self.assertEqual(
            ALLOWED_OUTPUTS[:5],
            (
                ".planning/PROJECT.md",
                ".planning/config.json",
                ".planning/REQUIREMENTS.md",
                ".planning/ROADMAP.md",
                ".planning/STATE.md",
            ),
        )
        self.assertTrue(any(pattern.endswith("*-PLAN.md") for pattern in ALLOWED_OUTPUTS))

    def test_accepted_plan_bytes_unchanged_after_task_progress(self):
        plan = self.fixture.repo / ".planning/phases/01/01-PLAN.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("accepted plan\n")
        subprocess.run(["git", "-C", str(self.fixture.repo), "add", ".planning"], check=True)
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "commit", "-qm", "accept plan"], check=True
        )
        before = plan.read_bytes()
        preview = prepare_authoring_import(
            self.scope(frozen_paths=(".planning/phases/01/01-PLAN.md",))
        )
        import_plan = validate_authoring_result(
            preview,
            self.result(preview, {".planning/STATE.md": b"progress\n"}),
        )
        apply_authoring_result(import_plan)
        self.assertEqual(plan.read_bytes(), before)

    def test_checker_failure_prevents_plan_acceptance(self):
        preview = prepare_authoring_import(self.scope())
        with self.assertRaisesRegex(ValueError, "authoring_checker_failed"):
            validate_authoring_result(
                preview,
                self.result(
                    preview,
                    {".planning/phases/01/01-PLAN.md": b"draft\n"},
                    checker_passed=False,
                ),
            )

    def test_plan_assumption_change_pauses_for_refinement(self):
        preview = prepare_authoring_import(self.scope())
        with self.assertRaisesRegex(ValueError, "plan_refinement_required"):
            validate_authoring_result(
                preview,
                self.result(
                    preview,
                    {".planning/STATE.md": b"state\n"},
                    assumptions_changed=True,
                ),
            )

    def test_input_change_after_prepare_refuses_import(self):
        source = self.fixture.repo / ".planning/PROJECT.md"
        source.write_text("before\n")
        preview = prepare_authoring_import(
            self.scope(input_paths=(".planning/PROJECT.md",))
        )
        source.write_text("after\n")
        with self.assertRaisesRegex(ValueError, "authoring_input_changed"):
            validate_authoring_result(
                preview,
                self.result(preview, {".planning/STATE.md": b"state\n"}),
            )

    def test_no_merge_auto_merge_or_tag_command_is_emitted(self):
        preview = prepare_authoring_import(self.scope())
        with self.assertRaisesRegex(ValueError, "prohibited_authoring_command"):
            validate_authoring_result(
                preview,
                self.result(
                    preview,
                    {".planning/STATE.md": b"state\n"},
                    commands=("git tag v1",),
                ),
            )
        with self.assertRaisesRegex(ValueError, "prohibited_authoring_command"):
            validate_authoring_result(
                preview,
                self.result(
                    preview,
                    {".planning/STATE.md": b"state\n"},
                    commands=("git -C /tmp push origin main",),
                ),
            )
        for command in (
            "git -c push.default=simple push",
            "git -c merge.tool=vim merge feature",
            "git remote push origin",
        ):
            with self.assertRaisesRegex(ValueError, "prohibited_authoring_command"):
                validate_authoring_result(
                    preview,
                    self.result(
                        preview,
                        {".planning/STATE.md": b"state\n"},
                        commands=(command,),
                    ),
                )


if __name__ == "__main__":
    unittest.main()
