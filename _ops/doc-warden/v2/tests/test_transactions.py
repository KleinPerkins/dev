import subprocess
import json
import unittest
import uuid
from unittest import mock

from doc_warden.canonical import canonical_json
from doc_warden.transactions import (
    ExplicitConfirmation,
    MutationAction,
    MutationRequest,
    SOURCE_TRACKED_CANONICAL_ROOT,
    apply_transaction,
    confirmation_for,
    preview_transaction,
)
from fixture_factory import FixtureFactory


def bindings():
    digest = "sha256:" + "a" * 64
    return {
        "policy_version": "2.0.0-draft",
        "policy_digest": digest,
        "schema_digest": digest,
        "trigger_catalog_digest": digest,
        "template_digests": {},
        "gsd_pin_digest": digest,
        "approved_plan_digest": digest,
    }


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create()

    def tearDown(self):
        self.fixture.cleanup()

    def preview(self, transition="draft_update", operation_id=None):
        return preview_transaction(
            MutationRequest(
                repo=self.fixture.repo,
                repository_key=self.fixture.repository_key,
                transition=transition,
                actions=(MutationAction(".planning/artifacts/example.json", canonical_json({"v": 1})),),
                bindings=bindings(),
                operation_id=operation_id,
            )
        )

    def receipt_path(self, preview):
        return (
            self.fixture.repo
            / "_ops/doc-warden/state/v2/receipts"
            / f"{preview.operation_id}.json"
        )

    def test_retry_reuses_preview_id_and_receipt(self):
        operation = str(uuid.uuid4())
        preview = self.preview(operation_id=operation)
        first = apply_transaction(preview, confirmation_for(preview))
        second = apply_transaction(preview, confirmation_for(preview))
        self.assertEqual(first, second)
        self.assertEqual(first["operation_id"], operation)
        self.assertEqual(first["canonical_root"], SOURCE_TRACKED_CANONICAL_ROOT)

    def test_legacy_absolute_root_receipt_replay_normalizes_once(self):
        preview = self.preview()
        receipt = apply_transaction(preview, confirmation_for(preview))
        receipt_path = self.receipt_path(preview)
        legacy = {**receipt, "canonical_root": preview.canonical_root}
        receipt_path.write_bytes(canonical_json(legacy))

        replay = apply_transaction(preview, confirmation_for(preview))

        self.assertEqual(replay["canonical_root"], SOURCE_TRACKED_CANONICAL_ROOT)
        self.assertEqual(receipt_path.read_bytes(), canonical_json(receipt))

    def test_legacy_absolute_root_replay_rejects_wrong_root_without_rewrite(self):
        preview = self.preview()
        receipt = apply_transaction(preview, confirmation_for(preview))
        receipt_path = self.receipt_path(preview)
        wrong_root = str(self.fixture.repo.parent / "different")
        legacy = {**receipt, "canonical_root": wrong_root}
        prior = canonical_json(legacy)
        receipt_path.write_bytes(prior)

        with self.assertRaisesRegex(ValueError, "receipt validation failed"):
            apply_transaction(preview, confirmation_for(preview))

        self.assertEqual(receipt_path.read_bytes(), prior)

    def test_legacy_absolute_root_replay_rejects_malformed_without_rewrite(self):
        preview = self.preview()
        receipt = apply_transaction(preview, confirmation_for(preview))
        receipt_path = self.receipt_path(preview)
        malformed = {**receipt, "canonical_root": preview.canonical_root}
        malformed.pop("outcome")
        prior = canonical_json(malformed)
        receipt_path.write_bytes(prior)

        with self.assertRaisesRegex(ValueError, "receipt validation failed"):
            apply_transaction(preview, confirmation_for(preview))

        self.assertEqual(receipt_path.read_bytes(), prior)

    def test_source_tracked_receipt_uses_privacy_safe_root_projection(self):
        preview = self.preview()
        receipt = apply_transaction(preview, confirmation_for(preview))
        self.assertEqual(preview.canonical_root, str(self.fixture.repo.resolve()))
        self.assertEqual(receipt["canonical_root"], SOURCE_TRACKED_CANONICAL_ROOT)
        self.assertNotIn(
            str(self.fixture.repo.resolve()),
            canonical_json(receipt).decode("utf-8"),
        )

    def test_stale_or_mismatched_explicit_confirmation_is_refused(self):
        preview = self.preview()
        valid = confirmation_for(preview)
        stale = ExplicitConfirmation(
            operation_id=str(uuid.uuid4()),
            action_digest=valid.action_digest,
            source_revision=valid.source_revision,
            canonical_root=valid.canonical_root,
            choice=valid.choice,
            confirmation_digest=valid.confirmation_digest,
        )
        with self.assertRaisesRegex(ValueError, "explicit_confirmation_mismatch"):
            apply_transaction(preview, stale)
        self.assertFalse((self.fixture.repo / ".planning/artifacts/example.json").exists())

    def test_action_digest_binds_preimage_and_action_kind(self):
        operation = str(uuid.uuid4())
        first = self.preview(operation_id=operation)
        target = self.fixture.repo / ".planning/artifacts/example.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"before\n")
        second = self.preview(operation_id=operation)
        self.assertNotEqual(first.action_digest, second.action_digest)
        self.assertEqual(first.actions[0].kind, "create")
        self.assertEqual(second.actions[0].kind, "replace")

    def test_action_digest_binds_consequence_and_write_gate(self):
        operation = str(uuid.uuid4())
        baseline = self.preview(operation_id=operation)
        request = MutationRequest(
            repo=self.fixture.repo,
            repository_key=self.fixture.repository_key,
            transition="draft_update",
            actions=(
                MutationAction(
                    ".planning/artifacts/example.json", canonical_json({"v": 1})
                ),
            ),
            bindings=bindings(),
            operation_id=operation,
            consequential=False,
            require_write_enabled=True,
        )
        changed = preview_transaction(request)
        self.assertNotEqual(baseline.action_digest, changed.action_digest)

    def test_unimplemented_action_kinds_are_refused(self):
        with self.assertRaisesRegex(ValueError, "unsupported action kind"):
            preview_transaction(
                MutationRequest(
                    repo=self.fixture.repo,
                    repository_key=self.fixture.repository_key,
                    transition="draft_update",
                    actions=(MutationAction(".planning/value", b"value", "append"),),
                    bindings=bindings(),
                )
            )

    def test_invalid_receipt_is_refused_before_any_transaction_write(self):
        preview = preview_transaction(
            MutationRequest(
                repo=self.fixture.repo,
                repository_key=self.fixture.repository_key,
                transition="draft_update",
                actions=(MutationAction(".planning/artifacts/example.json", b"value"),),
                bindings={},
            )
        )
        with self.assertRaises(ValueError):
            apply_transaction(preview, confirmation_for(preview))
        self.assertFalse((self.fixture.repo / ".planning/artifacts/example.json").exists())
        self.assertFalse((self.fixture.repo / "_ops/doc-warden/state/v2/events").exists())
        self.assertFalse((self.fixture.repo / "_ops/doc-warden/state/v2/receipts").exists())

    def test_receipt_egress_failure_leaves_no_partial_transaction_state(self):
        preview = self.preview()

        def fail_receipt(sink, value):
            if sink == "receipt":
                raise ValueError("receipt_canonical_root_must_be_projected")
            return {"schema": "doc-warden/egress/v1", "sink": sink, "payload": value}

        with mock.patch("doc_warden.transactions.validate_egress", side_effect=fail_receipt):
            with self.assertRaisesRegex(
                ValueError, "receipt_canonical_root_must_be_projected"
            ):
                apply_transaction(preview, confirmation_for(preview))
        self.assertFalse((self.fixture.repo / ".planning/artifacts/example.json").exists())
        self.assertFalse((self.fixture.repo / "_ops/doc-warden/state/v2/events").exists())
        self.assertFalse((self.fixture.repo / "_ops/doc-warden/state/v2/receipts").exists())

    def test_configured_github_repository_id_is_bound_to_receipt(self):
        path = self.fixture.repo / ".planning/doc-warden.json"
        value = json.loads(path.read_text())
        value["github_repository_id"] = 123456789
        path.write_text(json.dumps(value))
        preview = self.preview()
        self.assertEqual(preview.github_repository_id, 123456789)

    def test_accepted_freeze_detects_one_byte_change(self):
        preview = self.preview(transition="accepted_freeze")
        apply_transaction(preview, confirmation_for(preview))
        (self.fixture.repo / ".planning/artifacts/example.json").write_bytes(b'{"v":2}\n')
        with self.assertRaisesRegex(ValueError, "receipt_postimage_mismatch"):
            apply_transaction(preview, confirmation_for(preview))

    def test_creation_snapshot_does_not_freeze_authored_semantics(self):
        preview = self.preview(transition="creation_snapshot")
        receipt = apply_transaction(preview, confirmation_for(preview))
        (self.fixture.repo / ".planning/artifacts/example.json").write_bytes(b'{"v":2}\n')
        self.assertEqual(receipt["transition"], "creation_snapshot")
        with self.assertRaisesRegex(ValueError, "receipt_postimage_mismatch"):
            apply_transaction(preview, confirmation_for(preview))

    def test_partial_apply_with_event_completes_receipt_on_retry(self):
        preview = self.preview()
        receipt = apply_transaction(preview, confirmation_for(preview))
        receipt_path = (
            self.fixture.repo
            / "_ops/doc-warden/state/v2/receipts"
            / f"{preview.operation_id}.json"
        )
        event_path = (
            self.fixture.repo
            / "_ops/doc-warden/state/v2/events"
            / f"{preview.event_id}.json"
        )
        receipt_path.unlink()
        event_path.unlink()
        self.assertEqual(apply_transaction(preview, confirmation_for(preview)), receipt)

    def test_receipt_replay_refuses_missing_event(self):
        preview = self.preview()
        apply_transaction(preview, confirmation_for(preview))
        event_path = (
            self.fixture.repo
            / "_ops/doc-warden/state/v2/events"
            / f"{preview.event_id}.json"
        )
        event_path.unlink()
        with self.assertRaisesRegex(ValueError, "receipt_event_missing"):
            apply_transaction(preview, confirmation_for(preview))

    def test_source_revision_change_refuses_without_writing(self):
        preview = self.preview()
        (self.fixture.repo / "other").write_text("changed\n")
        subprocess.run(["git", "-C", str(self.fixture.repo), "add", "other"], check=True)
        subprocess.run(["git", "-C", str(self.fixture.repo), "commit", "-qm", "change"], check=True)
        with self.assertRaisesRegex(ValueError, "source_revision_changed"):
            apply_transaction(preview, confirmation_for(preview))


if __name__ == "__main__":
    unittest.main()
