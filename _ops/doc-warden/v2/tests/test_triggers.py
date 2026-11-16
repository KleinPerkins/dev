import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from doc_warden.canonical import canonical_json
from doc_warden.triggers import (
    ACTION_HANDLERS,
    DETECTOR_HANDLERS,
    LEGACY_V1_MIGRATION,
    REGISTRY,
    TEMPLATE_HANDLERS,
    VERIFIER_HANDLERS,
    dispatch_trigger,
    projection_freshness_preimage,
    read_projection_freshness,
    reconcile_projection_freshness,
    validate_trigger_parity,
)
from fixture_factory import FixtureFactory, ROOT


class TriggerTests(unittest.TestCase):
    def test_trigger_catalog_fields_have_exact_runtime_handlers(self):
        result = validate_trigger_parity(
            ROOT / "_ops/doc-warden/triggers.v2.json"
        )
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["version"], "2.1.0")
        self.assertEqual(result["trigger_count"], len(REGISTRY))
        self.assertEqual(
            result["handler_counts"],
            {
                "actions": len(ACTION_HANDLERS),
                "detectors": len(DETECTOR_HANDLERS),
                "templates": len(TEMPLATE_HANDLERS),
                "verifiers": len(VERIFIER_HANDLERS),
            },
        )
        self.assertEqual(
            set(REGISTRY),
            {
                "artifact-transition",
                "pre-import",
                "authoring-result-import",
                "completion",
                "defect-transition",
                "reconciliation-preview",
                "session-start",
                "significant-file-edit",
                "external-design-refresh",
                "repository-dependency-observation",
                "routine-maintenance",
            },
        )

    def test_catalog_is_closed_and_disallows_arbitrary_shell(self):
        source = json.loads(
            (ROOT / "_ops/doc-warden/triggers.v2.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "triggers.json"

            with_extra = json.loads(json.dumps(source))
            with_extra["triggers"][0]["shell"] = "rm -rf /"
            path.write_bytes(canonical_json(with_extra))
            with self.assertRaisesRegex(ValueError, "trigger_catalog_field_invalid"):
                validate_trigger_parity(path)

            with_shell_action = json.loads(json.dumps(source))
            with_shell_action["triggers"][0]["action"] = "bash -c whoami"
            path.write_bytes(canonical_json(with_shell_action))
            with self.assertRaisesRegex(ValueError, "trigger_vocabulary_invalid"):
                validate_trigger_parity(path)

    def test_legacy_v1_ids_are_mapped_with_recorded_incompatibilities(self):
        self.assertEqual(set(LEGACY_V1_MIGRATION), {1, 2, 3, 4, 6, 7})
        for legacy_id, migration in LEGACY_V1_MIGRATION.items():
            with self.subTest(legacy_id=legacy_id):
                self.assertIn(migration.v2_trigger_id, REGISTRY)
                self.assertTrue(migration.incompatibilities)
                self.assertNotIn("shell", " ".join(migration.incompatibilities))
        result = validate_trigger_parity(
            ROOT / "_ops/doc-warden/triggers.v2.json"
        )
        self.assertEqual(result["legacy_v1_ids"], [1, 2, 3, 4, 6, 7])

    def test_unknown_trigger_writes_nothing_and_escalates(self):
        fixture = FixtureFactory.create()
        try:
            before = subprocess.check_output(
                ["git", "-C", str(fixture.repo), "status", "--porcelain"],
                text=True,
            )
            result = dispatch_trigger(
                "not-in-the-catalog",
                {"repository": str(fixture.repo)},
            )
            self.assertEqual(result["status"], "escalated")
            self.assertEqual(result["code"], "unknown_trigger")
            self.assertEqual(result["repository_writes"], [])
            self.assertIn("checked", result["message"].lower())
            self.assertIn("uncertain", result["message"].lower())
            self.assertIn("next action", result["message"].lower())
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(fixture.repo), "status", "--porcelain"],
                    text=True,
                ),
                before,
            )
        finally:
            fixture.cleanup()

    def test_forced_handler_failure_proves_no_write_rollback(self):
        fixture = FixtureFactory.create()
        try:
            before = subprocess.check_output(
                ["git", "-C", str(fixture.repo), "status", "--porcelain"],
                text=True,
            )

            def fail(_context):
                raise RuntimeError("forced failure")

            with mock.patch.dict(
                ACTION_HANDLERS,
                {"report_session_context": fail},
            ):
                result = dispatch_trigger(
                    "session-start",
                    {
                        "event": "session_start",
                        "repository": str(fixture.repo),
                    },
                )
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["rollback_verified"])
            self.assertEqual(result["repository_writes"], [])
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(fixture.repo), "status", "--porcelain"],
                    text=True,
                ),
                before,
            )
        finally:
            fixture.cleanup()

    def test_stateful_handler_failure_reports_unrestored_marker(self):
        fixture = FixtureFactory.create()
        try:
            with tempfile.TemporaryDirectory() as directory:
                state_home = Path(directory)
                with mock.patch.dict(
                    VERIFIER_HANDLERS,
                    {"verify_freshness_marker": lambda _payload: False},
                ):
                    result = dispatch_trigger(
                        "significant-file-edit",
                        {
                            "event": "significant_file_edit",
                            "repository": str(fixture.repo),
                            "repository_key": fixture.repository_key,
                            "state_home": str(state_home),
                            "file_path": str(fixture.repo / "README.md"),
                        },
                    )

                markers = list(
                    (state_home / "doc-warden/freshness").glob("*.json")
                )
                self.assertEqual(len(markers), 1)
                self.assertEqual(result["status"], "failed")
                self.assertFalse(result["rollback_verified"])
                self.assertEqual(result["repository_writes"], [])
        finally:
            fixture.cleanup()

    def test_refresh_acknowledgement_cannot_clear_a_newer_marker(self):
        fixture = FixtureFactory.create("freshness-preimage")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state_home = Path(directory)
                context = {
                    "event": "significant_file_edit",
                    "repository": str(fixture.repo),
                    "repository_key": fixture.repository_key,
                    "state_home": str(state_home),
                    "file_path": str(fixture.repo / "README.md"),
                }
                self.assertEqual(
                    dispatch_trigger(
                        "significant-file-edit",
                        context,
                    )["status"],
                    "potentially_stale",
                )
                preimage = projection_freshness_preimage(
                    fixture.repo,
                    state_home,
                )
                self.assertIsNotNone(preimage)

                self.assertEqual(
                    dispatch_trigger(
                        "significant-file-edit",
                        {**context, "repository_key": None},
                    )["status"],
                    "potentially_stale",
                )
                revision = subprocess.check_output(
                    ["git", "-C", str(fixture.repo), "rev-parse", "HEAD"],
                    text=True,
                ).strip()
                self.assertIsNotNone(
                    reconcile_projection_freshness(
                        fixture.repo,
                        state_home,
                        revision,
                        refresh_preimage=preimage,
                    )
                )
                current = read_projection_freshness(
                    fixture.repo,
                    state_home,
                )
                self.assertIsNotNone(current)
                self.assertIsNone(current["repository_key"])
        finally:
            fixture.cleanup()

    def test_refresh_acknowledgement_preserves_out_of_repository_revision(self):
        fixture = FixtureFactory.create("freshness-revision")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state_home = Path(directory)
                unrelated_revision = "f" * 40
                result = dispatch_trigger(
                    "significant-file-edit",
                    {
                        "event": "significant_file_edit",
                        "repository": str(fixture.repo),
                        "repository_key": fixture.repository_key,
                        "source_revision": unrelated_revision,
                        "state_home": str(state_home),
                        "file_path": str(fixture.repo / "README.md"),
                    },
                )
                self.assertEqual(result["status"], "potentially_stale")
                self.assertNotEqual(
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(fixture.repo),
                            "cat-file",
                            "-e",
                            f"{unrelated_revision}^{{commit}}",
                        ],
                        check=False,
                        capture_output=True,
                    ).returncode,
                    0,
                )
                preimage = projection_freshness_preimage(
                    fixture.repo,
                    state_home,
                )
                revision = subprocess.check_output(
                    ["git", "-C", str(fixture.repo), "rev-parse", "HEAD"],
                    text=True,
                ).strip()
                self.assertIsNotNone(
                    reconcile_projection_freshness(
                        fixture.repo,
                        state_home,
                        revision,
                        refresh_preimage=preimage,
                    )
                )
                current = read_projection_freshness(
                    fixture.repo,
                    state_home,
                )
                self.assertIsNotNone(current)
                self.assertEqual(
                    current["source_revision"],
                    unrelated_revision,
                )
        finally:
            fixture.cleanup()

    def test_refresh_without_preimage_distinguishes_absent_and_new_marker(self):
        fixture = FixtureFactory.create("freshness-absent-preimage")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state_home = Path(directory)
                revision = subprocess.check_output(
                    ["git", "-C", str(fixture.repo), "rev-parse", "HEAD"],
                    text=True,
                ).strip()
                preimage = projection_freshness_preimage(
                    fixture.repo,
                    state_home,
                )
                self.assertIsNone(preimage)
                self.assertIsNone(
                    reconcile_projection_freshness(
                        fixture.repo,
                        state_home,
                        revision,
                        refresh_preimage=preimage,
                    )
                )

                self.assertEqual(
                    dispatch_trigger(
                        "significant-file-edit",
                        {
                            "event": "significant_file_edit",
                            "repository": str(fixture.repo),
                            "repository_key": fixture.repository_key,
                            "state_home": str(state_home),
                            "file_path": str(fixture.repo / "README.md"),
                        },
                    )["status"],
                    "potentially_stale",
                )
                self.assertIsNotNone(
                    reconcile_projection_freshness(
                        fixture.repo,
                        state_home,
                        revision,
                    )
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "projection_freshness_changed_during_refresh",
                ):
                    reconcile_projection_freshness(
                        fixture.repo,
                        state_home,
                        revision,
                        refresh_preimage=preimage,
                    )
                self.assertIsNotNone(
                    read_projection_freshness(fixture.repo, state_home)
                )
        finally:
            fixture.cleanup()

    def test_refresh_preimage_refuses_unreadable_marker(self):
        fixture = FixtureFactory.create("freshness-unreadable-preimage")
        try:
            with tempfile.TemporaryDirectory() as directory:
                state_home = Path(directory)
                dispatch_trigger(
                    "significant-file-edit",
                    {
                        "event": "significant_file_edit",
                        "repository": str(fixture.repo),
                        "repository_key": fixture.repository_key,
                        "state_home": str(state_home),
                        "file_path": str(fixture.repo / "README.md"),
                    },
                )
                with mock.patch(
                    "doc_warden.triggers._read_projection_marker",
                    return_value=None,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "projection_freshness_marker_unavailable",
                    ):
                        projection_freshness_preimage(
                            fixture.repo,
                            state_home,
                        )
        finally:
            fixture.cleanup()


if __name__ == "__main__":
    unittest.main()
