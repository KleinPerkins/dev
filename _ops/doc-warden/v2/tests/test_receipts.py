import tempfile
import unittest
from pathlib import Path

from doc_warden.canonical import digest_file_manifest, digest_ref
from doc_warden.receipts import observe_delivery, read_v1_receipt, write_receipt_v2
from doc_warden.transactions import (
    MutationAction,
    MutationRequest,
    SOURCE_TRACKED_CANONICAL_ROOT,
    apply_transaction,
    confirmation_for,
    preview_transaction,
)
from doc_warden.validators import require_valid, validate_egress
from fixture_factory import FixtureFactory


ROOT = Path(__file__).resolve().parents[4]


def live_bindings():
    schema_root = ROOT / "_ops/doc-warden/schemas/v2"
    return {
        "policy_version": "2.0.0",
        "policy_digest": digest_ref((ROOT / "_ops/doc-warden/POLICY.md").read_bytes()),
        "schema_digest": digest_file_manifest(list(schema_root.glob("*.schema.json"))),
        "trigger_catalog_digest": digest_ref(
            (ROOT / "_ops/doc-warden/triggers.v2.json").read_bytes()
        ),
        "template_digests": {},
        "gsd_pin_digest": digest_ref(
            (ROOT / "_ops/doc-warden/runtime/gsd-core/gsd-core-pin.json").read_bytes()
        ),
        # Retained predecessor plan is not successor approval authority.
        "approved_plan_digest": "sha256:" + "0" * 64,
    }


class ReceiptTests(unittest.TestCase):
    def test_receipt_uses_live_policy_schema_catalog_template_and_gsd_versions(self):
        fixture = FixtureFactory.create()
        try:
            request = MutationRequest(
                repo=fixture.repo,
                repository_key=fixture.repository_key,
                transition="draft_update",
                actions=(MutationAction(".planning/value", b"value\n"),),
                bindings=live_bindings(),
            )
            preview = preview_transaction(request)
            receipt = apply_transaction(preview, confirmation_for(preview))
            self.assertEqual(receipt["bindings"], live_bindings())
        finally:
            fixture.cleanup()

    def test_receipt_egress_requires_projected_canonical_root(self):
        fixture = FixtureFactory.create()
        try:
            request = MutationRequest(
                repo=fixture.repo,
                repository_key=fixture.repository_key,
                transition="draft_update",
                actions=(MutationAction(".planning/value", b"value\n"),),
                bindings=live_bindings(),
            )
            preview = preview_transaction(request)
            receipt = apply_transaction(preview, confirmation_for(preview))
            validate_egress("receipt", receipt)
            self.assertEqual(receipt["canonical_root"], SOURCE_TRACKED_CANONICAL_ROOT)
            leaked = {**receipt, "canonical_root": str(fixture.repo.resolve())}
            with self.assertRaisesRegex(ValueError, "receipt validation failed"):
                require_valid("receipt", leaked)
            with self.assertRaisesRegex(
                ValueError,
                "receipt validation failed|receipt_canonical_root_must_be_projected",
            ):
                validate_egress("receipt", leaked)
            copy = fixture.repo / "_ops/doc-warden/state/v2/receipts/copy.json"
            with self.assertRaisesRegex(ValueError, "receipt validation failed"):
                write_receipt_v2(leaked, copy, fixture.repo)
            self.assertFalse(copy.exists())
        finally:
            fixture.cleanup()

    def test_v1_receipt_adopts_without_rewriting_source(self):
        with tempfile.TemporaryDirectory(prefix="legacy-receipt-fixture-") as directory:
            path = Path(directory) / "receipt.yml"
            path.write_text("schema: doc-warden-receipt/v1\nrepo: synthetic-fixture\npolicy_version: 1.0.0\nobserved_outcome: conformant\n")
            before = path.read_bytes()
            legacy = read_v1_receipt(path)
            self.assertEqual(legacy.schema, "doc-warden-receipt/v1")
            self.assertEqual(path.read_bytes(), before)

    def test_receipt_allows_null_delivery_commit_then_delivery_event(self):
        fixture = FixtureFactory.create()
        try:
            preview = preview_transaction(
                MutationRequest(
                    repo=fixture.repo,
                    repository_key=fixture.repository_key,
                    transition="creation_snapshot",
                    actions=(MutationAction(".planning/value", b"value\n"),),
                    bindings=live_bindings(),
                )
            )
            receipt = apply_transaction(preview, confirmation_for(preview))
            self.assertIsNone(receipt["delivery_commit"])
            delivery = observe_delivery(
                receipt, repo=fixture.repo, delivery_commit="a" * 40, pull_request="PR-1"
            )
            self.assertEqual(delivery["transition"], "delivery_observed")
            self.assertNotEqual(delivery["event_id"], receipt["event_id"])
            self.assertEqual(delivery["details"]["delivery_commit"], "a" * 40)
            self.assertTrue(
                (
                    fixture.repo
                    / "_ops/doc-warden/state/v2/events"
                    / f"{delivery['event_id']}.json"
                ).is_file()
            )
            self.assertEqual(
                observe_delivery(
                    receipt, repo=fixture.repo, delivery_commit="a" * 40, pull_request="PR-1"
                ),
                delivery,
            )
            with self.assertRaisesRegex(ValueError, "delivery already observed"):
                observe_delivery(receipt, repo=fixture.repo, delivery_commit="b" * 40)
            copy = fixture.repo / "_ops/doc-warden/state/v2/receipts/copy.json"
            self.assertEqual(write_receipt_v2(receipt, copy, fixture.repo), receipt)
        finally:
            fixture.cleanup()


if __name__ == "__main__":
    unittest.main()
