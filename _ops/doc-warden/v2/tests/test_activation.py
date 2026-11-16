import unittest
from subprocess import CalledProcessError
from unittest.mock import patch

from doc_warden.activation import restore_policy_dispatch_pair, validate_activation
from doc_warden.triggers import REGISTRY
from fixture_factory import FixtureFactory, ROOT


class ActivationTests(unittest.TestCase):
    def setUp(self):
        original = __import__('pathlib').Path.is_file
        patcher = patch('pathlib.Path.is_file', lambda p: False if str(p).endswith('/_ops/policy/dev-successor.json') else original(p))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_policy_runtime_schema_catalog_and_dispatch_activate_atomically(self):
        evidence = validate_activation(ROOT)
        self.assertEqual(evidence["status"], "active")
        self.assertEqual(evidence["trigger_count"], len(REGISTRY))

    def test_activation_rollback_restores_v1_policy_and_dispatch_pair(self):
        fixture = FixtureFactory.create()
        try:
            policy = fixture.repo / "_ops/doc-warden/POLICY.md"
            dispatcher = fixture.repo / "_ops/bin/doc-warden.sh"
            policy.parent.mkdir(parents=True, exist_ok=True)
            dispatcher.parent.mkdir(parents=True, exist_ok=True)
            policy.write_bytes(b"v1 policy\n")
            dispatcher.write_bytes(b"v1 dispatch\n")
            prior_policy = policy.read_bytes()
            prior_dispatcher = dispatcher.read_bytes()
            policy.write_bytes(b"v2 policy\n")
            dispatcher.write_bytes(b"v2 dispatch\n")
            restore_policy_dispatch_pair(
                fixture.repo,
                policy_bytes=prior_policy,
                dispatcher_bytes=prior_dispatcher,
            )
            self.assertEqual(policy.read_bytes(), b"v1 policy\n")
            self.assertEqual(dispatcher.read_bytes(), b"v1 dispatch\n")
        finally:
            fixture.cleanup()

    @patch("doc_warden.activation.runnerless_delivery_preview", side_effect=ValueError("historical_input_absent"))
    def test_runnerless_v2_claim_is_blocked_while_dev_is_canned_only(self, preview):
        evidence = validate_activation(ROOT)
        self.assertEqual(
            evidence["runnerless_v2"], "blocked_external_dependency"
        )
        self.assertEqual(
            evidence["runnerless_v2_evidence"]["reason"],
            "runnerless_authority_invalid",
        )

    @patch("doc_warden.activation.runnerless_delivery_preview")
    def test_activation_reports_valid_additive_controller_receipt(self, preview):
        qualification = {
            "status": "qualified",
            "qualified": True,
            "reason": None,
            "qualification_id": f"sha256:{'a' * 64}",
            "check_run_id": 987654321,
            "check_app_id": 4274739,
        }
        preview.return_value = {
            "source_lane": {
                "qualified": True,
                "controller_qualification": qualification,
            }
        }

        evidence = validate_activation(ROOT)

        self.assertEqual(evidence["runnerless_v2"], "qualified")
        self.assertEqual(evidence["runnerless_v2_evidence"], qualification)
        preview.assert_called_once_with(
            ROOT.resolve(strict=True),
            repository="KleinPerkins/dev",
            github_repository_id=None,
            observe_qualification_check=True,
            qualification_check_observer=None,
        )

    @patch(
        "doc_warden.activation.runnerless_delivery_preview",
        side_effect=ValueError("runnerless_qualification_authority_mismatch"),
    )
    def test_activation_reports_invalid_runnerless_authority_as_blocked(
        self,
        preview,
    ):
        evidence = validate_activation(ROOT)

        self.assertEqual(
            evidence["runnerless_v2"],
            "blocked_external_dependency",
        )
        self.assertEqual(
            evidence["runnerless_v2_evidence"]["reason"],
            "runnerless_authority_invalid",
        )
        preview.assert_called_once()

    @patch(
        "doc_warden.activation.runnerless_delivery_preview",
        side_effect=CalledProcessError(128, ["git", "show"]),
    )
    def test_activation_reports_runnerless_git_failure_as_blocked(
        self,
        preview,
    ):
        evidence = validate_activation(ROOT)

        self.assertEqual(
            evidence["runnerless_v2_evidence"]["reason"],
            "runnerless_authority_invalid",
        )
        preview.assert_called_once()


if __name__ == "__main__":
    unittest.main()
