import unittest

from doc_warden.canonical import digest_ref
from doc_warden.reconcile import reconcile
from fixture_factory import FixtureFactory


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create()

    def tearDown(self):
        self.fixture.cleanup()

    def test_safe_projection_update_never_changes_frozen_body(self):
        frozen = self.fixture.repo / "README.md"
        before = frozen.read_bytes()
        plan = reconcile(
            self.fixture.repo,
            expected_frozen={"README.md": digest_ref(before)},
            projection_updates={
                ".planning/generated/repo-view.json": b'{"generated":true}\n'
            },
        )
        self.assertEqual(plan.status, "ready")
        self.assertEqual(
            [action.path for action in plan.transaction.actions],
            [".planning/generated/repo-view.json"],
        )
        self.assertEqual(frozen.read_bytes(), before)

    def test_conflicting_authority_writes_nothing(self):
        before = sorted(str(path.relative_to(self.fixture.repo)) for path in self.fixture.repo.rglob("*"))
        plan = reconcile(
            self.fixture.repo,
            expected_frozen={"README.md": "sha256:" + "0" * 64},
            projection_updates={
                ".planning/generated/repo-view.json": b'{"generated":true}\n'
            },
        )
        after = sorted(str(path.relative_to(self.fixture.repo)) for path in self.fixture.repo.rglob("*"))
        self.assertEqual(plan.status, "blocked")
        self.assertIsNone(plan.transaction)
        self.assertEqual(before, after)

    def test_semantic_target_is_never_a_safe_projection(self):
        with self.assertRaisesRegex(ValueError, "unsafe_reconciliation_target"):
            reconcile(
                self.fixture.repo,
                projection_updates={".planning/artifacts/PRD.md": b"changed\n"},
            )

    def test_malformed_roadmap_is_classified_without_writing(self):
        path = self.fixture.repo / ".planning/ROADMAP.md"
        path.write_text("not a roadmap")
        before = path.read_bytes()
        plan = reconcile(self.fixture.repo)
        self.assertEqual(plan.status, "blocked")
        self.assertEqual(
            plan.classifications,
            ((".planning/ROADMAP.md", "contradictory_authority"),),
        )
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
