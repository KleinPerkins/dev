import subprocess
import unittest

from doc_warden.inventory import (
    CheckoutObservation,
    deduplicate_observations,
    inventory_fleet,
)
from fixture_factory import FixtureFactory


class InventoryTests(unittest.TestCase):
    def observation(self, **overrides):
        values = {
            "repository": "KleinPerkins/example",
            "repository_id": 123,
            "path": None,
            "available": False,
            "reason": "checkout unavailable",
            "owner": "KleinPerkins",
            "next_action": "locate checkout",
        }
        values.update(overrides)
        return CheckoutObservation(**values)

    def test_inventory_deduplicates_two_checkouts_by_repository_id(self):
        rows = deduplicate_observations(
            [
                self.observation(path="/one", available=True, reason=None),
                self.observation(path="/two", available=True, reason=None),
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0].observations), 2)

    def test_inventory_keeps_unavailable_repo_with_reason_owner_next_action(self):
        row = deduplicate_observations([self.observation()])[0]
        self.assertFalse(row.available)
        self.assertEqual(row.reason, "checkout unavailable")
        self.assertEqual(row.owner, "KleinPerkins")
        self.assertEqual(row.next_action, "locate checkout")

    def test_inventory_preserves_identity_when_only_one_checkout_has_the_profile(self):
        rows = deduplicate_observations([
            self.observation(path="/one", available=True, reason=None),
            self.observation(path="/two", available=True, reason=None, repository_key="local-key"),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].repository_key, "local-key")
        self.assertEqual(rows[0].repository_id, 123)
        self.assertEqual(len(rows[0].observations), 2)

    def test_inventory_refuses_mutation_when_provider_ids_disagree_on_a_local_key(self):
        rows = deduplicate_observations([
            self.observation(path="/one", available=True, repository_key="local-key"),
            self.observation(path="/two", available=True, repository_key="local-key", repository_id=456),
        ])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.reason == "identity_conflict" for row in rows))
        self.assertTrue(all(row.designated_path is None and not row.mutation_eligible for row in rows))

    def test_chaos_scheduler_is_docs_only_and_never_mutation_eligible(self):
        row = deduplicate_observations(
            [
                self.observation(
                    repository="KleinPerkins/chaos-scheduler",
                    repository_id=None,
                    path="/scheduler",
                    available=True,
                    reason=None,
                    docs_only=True,
                )
            ]
        )[0]
        self.assertTrue(row.docs_only)
        self.assertFalse(row.mutation_eligible)

    def test_fleet_authority_is_available_from_a_consumer_checkout(self):
        fixture = FixtureFactory.create()
        try:
            rows = inventory_fleet(fixture.repo)
            dev = next(row for row in rows if row.repository == "KleinPerkins/dev")
            self.assertFalse(dev.available)
            self.assertIsNone(dev.designated_path)
            self.assertFalse(dev.mutation_eligible)
            self.assertIsNone(dev.source_revision)
            self.assertIsNotNone(dev.observed_at)
            subprocess.run(["git", "-C", str(fixture.repo), "remote", "add", "origin",
                            "https://github.com/KleinPerkins/dev.git"], check=True)
            dev = next(row for row in inventory_fleet(fixture.repo) if row.repository == "KleinPerkins/dev")
            self.assertTrue(dev.available)
            self.assertEqual(dev.source_revision, subprocess.check_output(
                ["git", "-C", str(fixture.repo), "rev-parse", "HEAD"], text=True,
            ).strip())
            self.assertIsNotNone(dev.observed_at)
        finally:
            fixture.cleanup()


if __name__ == "__main__":
    unittest.main()
