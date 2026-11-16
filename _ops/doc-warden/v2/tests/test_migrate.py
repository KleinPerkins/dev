import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from doc_warden.artifacts import apply_preview, consent_for
from doc_warden.canonical import canonical_json, digest_ref
from doc_warden.migrate import migration_preview
from doc_warden.scm import RepositoryIdentity
from fixture_factory import ROOT, FixtureFactory


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.machine = tempfile.TemporaryDirectory(
            prefix="doc-warden-v2-migration-state-"
        )
        self.fixture = FixtureFactory.create("unconfigured")
        subprocess.run(
            [
                "git",
                "-C",
                str(self.fixture.repo),
                "remote",
                "add",
                "origin",
                "git@github.com:KleinPerkins/migration-fixture.git",
            ],
            check=True,
        )
        self.legacy_state = Path(self.machine.name) / "legacy-state"
        self.receipt = self.legacy_state / "20260805T131255Z-repair-greenfield.yml"
        self.receipt.parent.mkdir(parents=True)
        self.receipt.write_text(
            "\n".join(
                (
                    "schema: doc-warden-receipt/v1",
                    "repo: migration-fixture",
                    'policy_version: "1.3.0"',
                    "observed_outcome: CREATED",
                    "",
                )
            ),
            encoding="utf-8",
        )
        self.identity = RepositoryIdentity(
            repository="KleinPerkins/migration-fixture",
            github_repository_id=123456789,
        )

    def tearDown(self):
        self.fixture.cleanup()
        self.machine.cleanup()

    def preview(self):
        with mock.patch(
            "doc_warden.migrate.observe_repository_identity",
            return_value=self.identity,
        ):
            return migration_preview(
                self.fixture.repo,
                authority_root=ROOT,
                legacy_state=self.legacy_state,
            )

    def test_migration_preview_is_closed_applicable_and_read_only(self):
        before = self.receipt.read_bytes()
        status = subprocess.check_output(
            ["git", "-C", str(self.fixture.repo), "status", "--porcelain"],
            text=True,
        )
        plan = self.preview()
        transaction = plan.transaction
        self.assertIsNotNone(transaction)
        assert transaction is not None
        self.assertEqual(plan.status, "ready")
        self.assertEqual(transaction.transition, "migration_adoption")
        self.assertTrue(transaction.consequential)
        self.assertTrue(transaction.require_write_enabled)
        self.assertEqual(transaction.github_repository_id, 123456789)
        self.assertRegex(transaction.operation_id, r"^[0-9a-f-]{36}$")
        self.assertRegex(transaction.action_digest, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            transaction.bindings["repository_identity"],
            {
                "github_repository": "KleinPerkins/migration-fixture",
                "github_repository_id": 123456789,
            },
        )
        self.assertRegex(
            transaction.bindings["gsd_pin_digest"], r"^sha256:[0-9a-f]{64}$"
        )
        self.assertRegex(plan.gsd_interface_digest, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            [action.path for action in transaction.actions],
            [".planning/doc-warden.json"],
        )
        self.assertEqual(transaction.preimages, {".planning/doc-warden.json": None})
        profile = json.loads(transaction.actions[0].content)
        self.assertEqual(profile["repository_key"], plan.repository_key)
        self.assertEqual(profile["github_repository_id"], 123456789)
        self.assertEqual(
            profile["gsd_pin_digest"], transaction.bindings["gsd_pin_digest"]
        )
        self.assertEqual(profile["gsd_interface_digest"], plan.gsd_interface_digest)
        self.assertEqual(len(plan.legacy_evidence), 1)
        self.assertEqual(plan.legacy_evidence[0].classification, "creation_skeleton")
        self.assertEqual(plan.legacy_evidence[0].resolution, "adopted")
        self.assertEqual(self.receipt.read_bytes(), before)
        self.assertEqual(
            subprocess.check_output(
                ["git", "-C", str(self.fixture.repo), "status", "--porcelain"],
                text=True,
            ),
            status,
        )

    def test_migration_applies_only_exact_operation_and_preserves_v1_bytes(self):
        before = self.receipt.read_bytes()
        plan = self.preview()
        transaction = plan.transaction
        assert transaction is not None
        with mock.patch(
            "doc_warden.transactions.observe_repository_identity",
            return_value=self.identity,
        ):
            receipt = apply_preview(
                transaction, consent_for(transaction, consequence_class="migration")
            )
            replay = apply_preview(
                transaction, consent_for(transaction, consequence_class="migration")
            )
        self.assertEqual(receipt, replay)
        self.assertEqual(receipt["transition"], "migration_adoption")
        self.assertEqual(receipt["operation_id"], transaction.operation_id)
        self.assertEqual(receipt["action_digest"], transaction.action_digest)
        self.assertEqual(receipt["github_repository_id"], 123456789)
        self.assertEqual(self.receipt.read_bytes(), before)
        self.assertTrue((self.fixture.repo / ".planning/doc-warden.json").is_file())

    def test_repository_key_is_deterministic_and_operation_bound(self):
        operation_id = "8716de90-97ce-4fa9-9760-897889d34466"
        with mock.patch(
            "doc_warden.migrate.observe_repository_identity",
            return_value=self.identity,
        ):
            first = migration_preview(
                self.fixture.repo,
                authority_root=ROOT,
                legacy_state=self.legacy_state,
                operation_id=operation_id,
            )
            second = migration_preview(
                self.fixture.repo,
                authority_root=ROOT,
                legacy_state=self.legacy_state,
                operation_id=operation_id,
            )
            other = migration_preview(
                self.fixture.repo,
                authority_root=ROOT,
                legacy_state=self.legacy_state,
                operation_id="01fe9455-fc63-4ebf-9d9c-d70b13a16b93",
            )
        assert first.transaction is not None
        assert second.transaction is not None
        assert other.transaction is not None
        self.assertEqual(first.repository_key, second.repository_key)
        self.assertEqual(
            first.transaction.action_digest,
            second.transaction.action_digest,
        )
        self.assertNotEqual(first.repository_key, other.repository_key)

    def test_migration_adoption_enables_a_disabled_profile(self):
        initial = self.preview()
        assert initial.transaction is not None
        profile = json.loads(initial.transaction.actions[0].content)
        profile["enabled"] = False
        config = self.fixture.repo / ".planning/doc-warden.json"
        config.parent.mkdir()
        config.write_bytes(canonical_json(profile))
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "add", ".planning"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "commit", "-qm", "disabled"],
            check=True,
        )
        plan = self.preview()
        assert plan.transaction is not None
        with mock.patch(
            "doc_warden.transactions.observe_repository_identity",
            return_value=self.identity,
        ):
            apply_preview(
                plan.transaction,
                consent_for(plan.transaction, consequence_class="migration"),
            )
        self.assertTrue(json.loads(config.read_bytes())["enabled"])

    def test_already_enabled_profile_ignores_irrelevant_legacy_state(self):
        initial = self.preview()
        assert initial.transaction is not None
        config = self.fixture.repo / ".planning/doc-warden.json"
        config.parent.mkdir()
        config.write_bytes(initial.transaction.actions[0].content)
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "add", ".planning"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "commit", "-qm", "enabled"],
            check=True,
        )
        self.receipt.write_text("not a v1 receipt\n", encoding="utf-8")
        plan = self.preview()
        self.assertEqual(plan.status, "already_v2")
        self.assertIsNone(plan.transaction)
        self.assertEqual(plan.legacy_evidence, ())
        self.assertEqual(
            plan.gsd_interface_digest,
            json.loads(config.read_bytes())["gsd_interface_digest"],
        )
        changed_identity = RepositoryIdentity(
            repository="KleinPerkins/migration-fixture",
            github_repository_id=987654321,
        )
        with mock.patch(
            "doc_warden.migrate.observe_repository_identity",
            return_value=changed_identity,
        ):
            with self.assertRaisesRegex(
                ValueError, "github_repository_id_mismatch"
            ):
                migration_preview(
                    self.fixture.repo,
                    authority_root=ROOT,
                    legacy_state=self.legacy_state,
                )

    def test_migration_refuses_legacy_evidence_or_remote_identity_drift(self):
        plan = self.preview()
        transaction = plan.transaction
        assert transaction is not None
        self.receipt.write_text(
            self.receipt.read_text(encoding="utf-8") + "notes: changed\n",
            encoding="utf-8",
        )
        with mock.patch(
            "doc_warden.transactions.observe_repository_identity",
            return_value=self.identity,
        ):
            with self.assertRaisesRegex(ValueError, "observed_input_drift"):
                apply_preview(
                    transaction,
                    consent_for(transaction, consequence_class="migration"),
                )
        self.assertFalse((self.fixture.repo / ".planning/doc-warden.json").exists())

        self.receipt.write_bytes(
            b"schema: doc-warden-receipt/v1\n"
            b"repo: migration-fixture\n"
            b'policy_version: "1.3.0"\n'
            b"observed_outcome: CREATED\n"
        )
        changed_identity = RepositoryIdentity(
            repository="KleinPerkins/other",
            github_repository_id=987654321,
        )
        with mock.patch(
            "doc_warden.transactions.observe_repository_identity",
            return_value=changed_identity,
        ):
            with self.assertRaisesRegex(ValueError, "repository_identity_mismatch"):
                apply_preview(
                    transaction,
                    consent_for(transaction, consequence_class="migration"),
                )
        self.assertFalse((self.fixture.repo / ".planning/doc-warden.json").exists())

    def add_historical_poc(self, *, matching_owner=True):
        raw = b"schema: doc-warden-poc-evidence/v1\ntarget_repo: ecosystem-orchestrator\nnotes: synthetic historical protocol fixture\n"
        poc = self.legacy_state / "synthetic-poc.yml"
        poc.write_bytes(raw)
        # A fixture digest exercises the exact-byte recognition contract without
        # copying private host evidence or relaxing production's historical pin.
        pin = mock.patch.dict("doc_warden.migrate._HISTORICAL_POC_REPORTS", {digest_ref(raw): "KleinPerkins/ecosystem-orchestrator"}, clear=True)
        pin.start()
        self.addCleanup(pin.stop)
        if matching_owner:
            self.identity = RepositoryIdentity(
                repository="KleinPerkins/ecosystem-orchestrator",
                github_repository_id=1281300995,
            )
            self.receipt.write_text(
                self.receipt.read_text().replace(
                    "repo: migration-fixture", "repo: ecosystem-orchestrator"
                )
            )
        return poc

    def test_historical_poc_is_unresolved_digest_bound_preview_evidence(self):
        poc = self.add_historical_poc()
        before = {path: path.read_bytes() for path in self.legacy_state.iterdir()}
        plan = self.preview()
        assert plan.transaction is not None
        self.assertEqual(plan.status, "ready")
        self.assertTrue(plan.transaction.consequential)
        self.assertEqual(len(plan.legacy_evidence), 2)
        row = next(row for row in plan.legacy_evidence if row.source_path == poc.resolve())
        self.assertEqual(row.classification, "unresolved_legacy_binding")
        self.assertEqual(row.resolution, "operator_decision_required")
        self.assertEqual(row.digest, digest_ref(before[poc]))
        self.assertTrue(any(
            item.path == str(poc.resolve()) and item.digest == row.digest
            for item in plan.transaction.observed_inputs
        ))
        receipt = next(row for row in plan.legacy_evidence if row.source_path == self.receipt.resolve())
        self.assertEqual((receipt.classification, receipt.resolution), ("creation_skeleton", "adopted"))
        self.assertEqual({path: path.read_bytes() for path in before}, before)
        self.assertFalse((self.fixture.repo / ".planning/doc-warden.json").exists())

    def test_historical_poc_refuses_wrong_owner(self):
        self.add_historical_poc(matching_owner=False)
        with self.assertRaisesRegex(ValueError, "legacy_repository_identity_mismatch"):
            self.preview()

    def test_historical_poc_refuses_same_name_under_different_owner(self):
        self.add_historical_poc()
        self.identity = RepositoryIdentity(
            repository="OtherOwner/ecosystem-orchestrator",
            github_repository_id=987654321,
        )
        with self.assertRaisesRegex(ValueError, "legacy_repository_identity_mismatch"):
            self.preview()

    def test_changed_or_unknown_poc_is_not_silently_recognized(self):
        poc = self.add_historical_poc()
        original = poc.read_bytes()
        for changed in (
            original + b"notes: changed\n",
            original.replace(b"target_repo: ecosystem-orchestrator\n", b""),
            original + b"target_repo: other\n",
            original.replace(b"target_repo: ecosystem-orchestrator", b"target_repo: other"),
            original.replace(b"doc-warden-poc-evidence/v1", b"unknown/v1"),
        ):
            with self.subTest(digest=digest_ref(changed)):
                poc.write_bytes(changed)
                with self.assertRaisesRegex(ValueError, "unsupported legacy receipt"):
                    self.preview()
        self.assertFalse((self.fixture.repo / ".planning/doc-warden.json").exists())

    def test_historical_poc_does_not_supply_migration_consent(self):
        poc = self.add_historical_poc()
        original = poc.read_bytes()
        transaction = self.preview().transaction
        assert transaction is not None
        wrong = consent_for(transaction, consequence_class="migration")
        wrong["action_digest"] = "sha256:" + "0" * 64
        for consent in (None, wrong):
            with self.subTest(consent_missing=consent is None):
                with self.assertRaises(ValueError):
                    apply_preview(transaction, consent)
                self.assertFalse((self.fixture.repo / ".planning/doc-warden.json").exists())
        with mock.patch("doc_warden.transactions.observe_repository_identity", return_value=self.identity):
            receipt = apply_preview(transaction, consent_for(transaction, consequence_class="migration"))
            replay = apply_preview(transaction, consent_for(transaction, consequence_class="migration"))
        self.assertEqual(receipt, replay)
        self.assertEqual(poc.read_bytes(), original)

    def test_historical_poc_drift_refuses_before_apply(self):
        poc = self.add_historical_poc()
        transaction = self.preview().transaction
        assert transaction is not None
        poc.write_bytes(poc.read_bytes() + b"notes: changed after preview\n")
        with mock.patch("doc_warden.transactions.observe_repository_identity", return_value=self.identity):
            with self.assertRaisesRegex(ValueError, "observed_input_drift"):
                apply_preview(transaction, consent_for(transaction, consequence_class="migration"))
        self.assertFalse((self.fixture.repo / ".planning/doc-warden.json").exists())

    def test_legacy_evidence_symlink_and_special_file_still_refuse(self):
        poc = self.add_historical_poc()
        poc.unlink()
        poc.symlink_to(self.receipt)
        with self.assertRaisesRegex(ValueError, "legacy_receipt_invalid"):
            self.preview()
        poc.unlink()
        os.mkfifo(poc)
        with self.assertRaisesRegex(ValueError, "legacy_receipt_invalid"):
            self.preview()




if __name__ == "__main__":
    unittest.main()
