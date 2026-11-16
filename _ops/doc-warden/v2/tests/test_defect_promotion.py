from __future__ import annotations

import unittest
import uuid

from doc_warden.artifacts import (
    apply_preview,
    consent_for,
    draft_artifact,
)
from doc_warden.defects import (
    append_evidence,
    create_defect,
    defect_ready_check,
    promote_defect,
    read_defect,
    transition_defect,
)
from doc_warden.transactions import apply_transaction, confirmation_for
from fixture_factory import FixtureFactory
from test_defects import (
    CREATED,
    EVIDENCE_AT,
    INVESTIGATING,
    READY_AT,
    TRIAGED,
    complete_input,
)


PROMOTED_AT = "2026-08-31T09:41:00+00:00"


class DefectPromotionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create("defect-promotion")

    def tearDown(self):
        self.fixture.cleanup()

    @staticmethod
    def apply(preview):
        confirmation = (
            confirmation_for(preview.transaction)
            if preview.transaction.consequential
            else None
        )
        return apply_transaction(preview.transaction, confirmation)

    def create(self, inputs: dict[str, object] | None = None):
        preview = create_defect(
            inputs or complete_input(self.fixture.repository_key),
            repo=self.fixture.repo,
        )
        self.apply(preview)
        return preview

    def ready(self, defect_id: str) -> None:
        for target, timestamp in (
            ("triaged", TRIAGED),
            ("investigating", INVESTIGATING),
        ):
            self.apply(
                transition_defect(
                    defect_id,
                    target,
                    repo=self.fixture.repo,
                    timestamp=timestamp,
                    source="synthetic-lifecycle",
                    author_class="test",
                )
            )
        append_evidence(
            defect_id,
            {
                "timestamp": EVIDENCE_AT,
                "source": "synthetic-reproducer",
                "author_class": "test",
                "checked": "cache keys before and after the fixture update",
                "found": "both reads used the same key",
                "implication": "the fixture revision is absent from the key",
            },
            repo=self.fixture.repo,
        )
        self.apply(
            transition_defect(
                defect_id,
                "ready",
                repo=self.fixture.repo,
                timestamp=READY_AT,
                source="synthetic-ready-check",
                author_class="test",
            )
        )

    def test_plan_validation_refuses_non_ready_defect_and_binds_ready_record(self):
        inputs = complete_input(self.fixture.repository_key)
        inputs["reproduction"] = []
        preview = self.create(inputs)
        with self.assertRaisesRegex(
            ValueError,
            "defect_not_ready:.*reproduction.*symptoms_digest.*evidence",
        ):
            draft_artifact(
                "plan",
                {
                    "title": "Premature defect plan",
                    "defect_id": preview.defect_id,
                    "approved_prd": False,
                },
                repo=self.fixture.repo,
            )

        second = self.create()
        self.ready(second.defect_id)
        verdict = defect_ready_check(second.defect_id, repo=self.fixture.repo)
        self.assertTrue(verdict.ready)
        plan = draft_artifact(
            "plan",
            {
                "title": "Ready defect plan",
                "defect_id": second.defect_id,
                "approved_prd": False,
            },
            repo=self.fixture.repo,
        )
        binding = plan.transaction.bindings["defect_authority"]
        self.assertEqual(binding["defect_id"], second.defect_id)
        self.assertEqual(
            binding["event_id"],
            read_defect(self.fixture.repo, second.defect_id).record["history_head"][
                "event_id"
            ],
        )

        append_evidence(
            second.defect_id,
            {
                "timestamp": "2026-08-31T09:35:30+00:00",
                "source": "synthetic-late-evidence",
                "author_class": "test",
                "checked": "the ready record after plan preview",
                "found": "new evidence arrived",
                "implication": "the plan must be re-previewed",
            },
            repo=self.fixture.repo,
        )
        with self.assertRaisesRegex(ValueError, "observed_input_drift"):
            apply_preview(plan, consent_for(plan.transaction))

    def test_default_created_defect_can_promote_instead_of_dead_ending(self):
        inputs = complete_input(self.fixture.repository_key)
        inputs.pop("exemption")
        preview = self.create(inputs)
        created = read_defect(self.fixture.repo, preview.defect_id)
        self.assertEqual(
            created.record["exemption"],
            {
                "decision": "exempt",
                "conditions": [True, True, True, False, True],
            },
        )
        with self.assertRaisesRegex(
            ValueError,
            "defect_not_ready:.*symptoms_digest.*evidence.*exemption.conditions",
        ):
            draft_artifact(
                "plan",
                {
                    "title": "Unreviewed default defect plan",
                    "defect_id": preview.defect_id,
                    "approved_prd": False,
                },
                repo=self.fixture.repo,
            )

        operation_id = self.fixture.id_for("default-exemption-promotion")
        promoted = promote_defect(
            preview.defect_id,
            repo=self.fixture.repo,
            timestamp=PROMOTED_AT,
            source="synthetic-default-promotion",
            author_class="test",
            operation_id=operation_id,
        )
        replayed = promote_defect(
            preview.defect_id,
            repo=self.fixture.repo,
            timestamp=PROMOTED_AT,
            source="synthetic-default-promotion",
            author_class="test",
            operation_id=operation_id,
        )
        self.assertEqual(replayed, promoted)
        defect = read_defect(self.fixture.repo, preview.defect_id)
        relative_path = str(defect.path.relative_to(self.fixture.repo.resolve()))
        self.assertEqual(
            promoted.receipt["bindings"]["defect_authority"],
            {
                "defect_id": preview.defect_id,
                "record_version": defect.record["record_version"],
                "event_id": defect.record["history_head"]["event_id"],
                "defect_digest": defect.digest,
            },
        )
        self.assertEqual(
            promoted.receipt["postimages"][relative_path],
            defect.digest,
        )
        self.assertEqual(defect.record["exemption"]["decision"], "promote")
        self.assertEqual(
            defect.record["exemption"]["conditions"],
            [True, True, True, False, True],
        )
        self.assertTrue(defect.record["fix_paused"])
        self.assertEqual(
            defect.record["promotion"]["prd_seed"],
            promoted.record,
        )
        with self.assertRaisesRegex(ValueError, "defect_not_ready:.*fix_paused"):
            draft_artifact(
                "plan",
                {
                    "title": "Promoted default defect plan",
                    "defect_id": preview.defect_id,
                    "approved_prd": False,
                },
                repo=self.fixture.repo,
            )

    def test_ui_plan_cannot_use_the_defect_prd_exemption(self):
        preview = self.create()
        self.ready(preview.defect_id)
        with self.assertRaisesRegex(
            ValueError,
            "^defect_scope_promotion_required:ui_visual$",
        ):
            draft_artifact(
                "plan",
                {
                    "title": "UI defect plan",
                    "defect_id": preview.defect_id,
                    "approved_prd": False,
                    "ui_visual": True,
                },
                repo=self.fixture.repo,
            )

    def test_scope_growth_produces_deterministic_prd_seed_and_pauses_fix(self):
        preview = self.create()
        self.ready(preview.defect_id)
        operation_id = self.fixture.id_for("scope-growth-promotion")
        promoted = promote_defect(
            preview.defect_id,
            repo=self.fixture.repo,
            timestamp=PROMOTED_AT,
            source="synthetic-scope-review",
            author_class="test",
            scope={
                "repositories": 1,
                "components": ["cache", "reader", "serializer"],
                "sessions": 2,
                "new_behavior": True,
                "ui_visual": False,
                "sensitive": False,
                "new_dependency": True,
                "schema_or_state_change": False,
                "reversible": True,
            },
            operation_id=operation_id,
        )
        replayed = promote_defect(
            preview.defect_id,
            repo=self.fixture.repo,
            timestamp=PROMOTED_AT,
            source="synthetic-scope-review",
            author_class="test",
            scope={
                "repositories": 1,
                "components": ["cache", "reader", "serializer"],
                "sessions": 2,
                "new_behavior": True,
                "ui_visual": False,
                "sensitive": False,
                "new_dependency": True,
                "schema_or_state_change": False,
                "reversible": True,
            },
            operation_id=operation_id,
        )
        self.assertEqual(promoted.record, replayed.record)
        self.assertEqual(promoted.receipt, replayed.receipt)
        append_evidence(
            preview.defect_id,
            {
                "timestamp": "2026-08-31T09:42:00+00:00",
                "source": "synthetic-post-promotion-check",
                "author_class": "test",
                "checked": "the promoted defect history",
                "found": "the original promotion event remains linked",
                "implication": "operation replay must return the original seed",
            },
            repo=self.fixture.repo,
        )
        replayed_after_history = promote_defect(
            preview.defect_id,
            repo=self.fixture.repo,
            timestamp=PROMOTED_AT,
            source="synthetic-scope-review",
            author_class="test",
            operation_id=operation_id,
        )
        self.assertEqual(promoted, replayed_after_history)
        with self.assertRaisesRegex(ValueError, "defect_already_promoted"):
            promote_defect(
                preview.defect_id,
                repo=self.fixture.repo,
                timestamp="2026-08-31T09:43:00+00:00",
                source="synthetic-second-promotion",
                author_class="test",
                operation_id=self.fixture.id_for("second-promotion"),
            )
        self.assertEqual(
            set(promoted.record),
            {
                "schema",
                "id",
                "status",
                "source_defect_id",
                "problem",
                "current_behavior",
                "target_behavior",
                "evidence",
                "affected_users",
                "requirement_candidates",
                "dependencies",
                "risk",
                "open_decisions",
                "related_artifacts",
            },
        )
        self.assertEqual(promoted.record["source_defect_id"], preview.defect_id)
        self.assertEqual(
            promoted.record["current_behavior"],
            "the reader returns stale fixture value v1",
        )
        self.assertEqual(
            promoted.record["target_behavior"],
            "the reader returns fixture value v2",
        )
        self.assertEqual(
            promoted.record["related_artifacts"],
            [{"kind": "defect", "id": preview.defect_id}],
        )
        self.assertTrue(promoted.record["evidence"])

        defect = read_defect(self.fixture.repo, preview.defect_id).record
        self.assertTrue(defect["fix_paused"])
        self.assertEqual(defect["exemption"]["decision"], "promote")
        self.assertEqual(defect["promotion"]["prd_seed"], promoted.record)
        self.assertEqual(defect["lifecycle"], "investigating")
        self.assertIn(promoted.record["id"], defect["related_artifacts"])
        self.assertIn("approve PRD seed", defect["current_focus"]["next_action"])

        roadmap = (
            self.fixture.repo / ".planning/ROADMAP.md"
        ).read_text(encoding="utf-8")
        self.assertIn('"kind":"product"', roadmap)
        self.assertIn(promoted.record["id"], roadmap)
        with self.assertRaisesRegex(ValueError, "defect_not_ready:.*fix_paused"):
            draft_artifact(
                "plan",
                {
                    "title": "Paused promoted defect plan",
                    "defect_id": preview.defect_id,
                    "approved_prd": False,
                },
                repo=self.fixture.repo,
            )

    def test_canonical_hyphenated_defect_id_produces_stable_seed(self):
        creation_operation = self.fixture.id_for("hyphenated-defect-identity")
        inputs = complete_input(self.fixture.repository_key)
        preview = create_defect(
            inputs,
            repo=self.fixture.repo,
            operation_id=creation_operation,
        )
        self.apply(preview)
        self.ready(preview.defect_id)
        defect_uuid = uuid.uuid5(uuid.UUID(creation_operation), "defect")
        self.assertEqual(
            preview.defect_id,
            f"DEF-{self.fixture.repository_key}-{defect_uuid}",
        )
        self.assertIn("-", self.fixture.repository_key)
        self.assertEqual(
            str(uuid.UUID(self.fixture.repository_key)),
            self.fixture.repository_key,
        )

        source = read_defect(self.fixture.repo, preview.defect_id).record
        operation_id = self.fixture.id_for("stable-seed-promotion")
        scope = {
            **inputs["scope"],
            "components": ["cache", "reader", "serializer"],
        }
        promoted = promote_defect(
            preview.defect_id,
            repo=self.fixture.repo,
            timestamp=PROMOTED_AT,
            source="synthetic-canonical-id-review",
            author_class="test",
            scope=scope,
            operation_id=operation_id,
        )
        expected_seed_id = (
            "PRD-SEED-"
            + str(uuid.uuid5(defect_uuid, "feature-promotion-prd-seed"))
        )
        self.assertEqual(
            promoted.record,
            {
                "schema": "doc-warden/prd-seed/v1",
                "id": expected_seed_id,
                "status": "draft",
                "source_defect_id": preview.defect_id,
                "problem": source["problem"],
                "current_behavior": source["actual"],
                "target_behavior": source["expected"],
                "evidence": source["evidence"],
                "affected_users": source["affected_users"],
                "requirement_candidates": source["requirement_candidates"],
                "dependencies": source["dependencies"],
                "risk": source["risks"],
                "open_decisions": source["open_decisions"],
                "related_artifacts": [
                    {"kind": "defect", "id": preview.defect_id}
                ],
            },
        )
        replayed = promote_defect(
            preview.defect_id,
            repo=self.fixture.repo,
            timestamp=PROMOTED_AT,
            source="synthetic-canonical-id-review",
            author_class="test",
            scope=scope,
            operation_id=operation_id,
        )
        self.assertEqual(replayed, promoted)

    def test_promotion_refuses_malformed_and_cross_repository_ids(self):
        inputs = complete_input(self.fixture.repository_key)
        preview = self.create(inputs)
        malformed_ids = (
            f"DEF-{self.fixture.repository_key}-not-a-uuid",
            f"{preview.defect_id}-suffix",
        )
        for defect_id in malformed_ids:
            with (
                self.subTest(defect_id=defect_id),
                self.assertRaisesRegex(ValueError, "^defect_id_invalid$"),
            ):
                promote_defect(
                    defect_id,
                    repo=self.fixture.repo,
                    timestamp=PROMOTED_AT,
                    source="synthetic-malformed-id-review",
                    author_class="test",
                )

        other = FixtureFactory.create("defect-promotion-cross-repository")
        try:
            foreign = create_defect(
                complete_input(other.repository_key),
                repo=other.repo,
            )
            self.apply(foreign)
            with self.assertRaisesRegex(
                ValueError,
                "^defect_repository_mismatch$",
            ):
                promote_defect(
                    foreign.defect_id,
                    repo=self.fixture.repo,
                    timestamp=PROMOTED_AT,
                    source="synthetic-cross-repository-review",
                    author_class="test",
                )
        finally:
            other.cleanup()

    def test_promotion_refuses_while_all_five_exemption_conditions_hold(self):
        preview = self.create()
        self.ready(preview.defect_id)
        with self.assertRaisesRegex(ValueError, "defect_exemption_still_valid"):
            promote_defect(
                preview.defect_id,
                repo=self.fixture.repo,
                timestamp=PROMOTED_AT,
                source="synthetic-scope-review",
                author_class="test",
            )
        self.assertFalse(read_defect(self.fixture.repo, preview.defect_id).record["fix_paused"])

    def test_recorded_scope_growth_blocks_ready_and_promotes_without_scope_reentry(self):
        inputs = complete_input(self.fixture.repository_key)
        inputs["scope"]["new_behavior"] = True
        preview = self.create(inputs)
        for target, timestamp in (
            ("triaged", TRIAGED),
            ("investigating", INVESTIGATING),
        ):
            self.apply(
                transition_defect(
                    preview.defect_id,
                    target,
                    repo=self.fixture.repo,
                    timestamp=timestamp,
                    source="synthetic-scope-review",
                    author_class="test",
                )
            )
        append_evidence(
            preview.defect_id,
            {
                "timestamp": EVIDENCE_AT,
                "source": "synthetic-scope-review",
                "author_class": "test",
                "checked": "the recorded defect scope",
                "found": "the fix defines new behavior",
                "implication": "the defect exemption no longer applies",
            },
            repo=self.fixture.repo,
        )

        verdict = defect_ready_check(preview.defect_id, repo=self.fixture.repo)
        self.assertFalse(verdict.ready)
        self.assertIn(
            "exemption.scope:promotion_required",
            verdict.invalid_fields,
        )
        with self.assertRaisesRegex(
            ValueError,
            "defect_not_ready:.*exemption.scope:promotion_required",
        ):
            transition_defect(
                preview.defect_id,
                "ready",
                repo=self.fixture.repo,
                timestamp=READY_AT,
                source="synthetic-ready-check",
                author_class="test",
            )

        promoted = promote_defect(
            preview.defect_id,
            repo=self.fixture.repo,
            timestamp=PROMOTED_AT,
            source="synthetic-scope-review",
            author_class="test",
        )
        defect = read_defect(self.fixture.repo, preview.defect_id).record
        self.assertEqual(promoted.record["source_defect_id"], preview.defect_id)
        self.assertEqual(
            defect["exemption"]["conditions"],
            [False, True, False, True, True],
        )
        self.assertTrue(defect["fix_paused"])

    def test_each_failed_exemption_condition_allows_promotion(self):
        for index in range(5):
            with self.subTest(condition=index):
                fixture = FixtureFactory.create(f"defect-promotion-condition-{index}")
                try:
                    inputs = complete_input(fixture.repository_key)
                    conditions = [True, True, True, True, True]
                    conditions[index] = False
                    inputs["exemption"] = {
                        "decision": "promote",
                        "conditions": conditions,
                    }
                    preview = create_defect(inputs, repo=fixture.repo)
                    self.apply(preview)
                    promoted = promote_defect(
                        preview.defect_id,
                        repo=fixture.repo,
                        timestamp=PROMOTED_AT,
                        source="synthetic-condition-review",
                        author_class="test",
                    )
                    self.assertEqual(
                        promoted.record["source_defect_id"],
                        preview.defect_id,
                    )
                finally:
                    fixture.cleanup()

    def test_each_scope_growth_signal_promotes_to_feature_path(self):
        cases = (
            ("repository", {"repositories": 2}),
            ("components", {"components": ["cache", "reader", "serializer"]}),
            ("sessions", {"sessions": 2}),
            ("behavior", {"new_behavior": True}),
            ("ui", {"ui_visual": True}),
            ("sensitive", {"sensitive": True}),
            ("dependency", {"new_dependency": True}),
            ("schema_state", {"schema_or_state_change": True}),
            ("irreversible", {"reversible": False}),
        )
        for label, growth in cases:
            with self.subTest(signal=label):
                fixture = FixtureFactory.create(f"defect-scope-growth-{label}")
                try:
                    inputs = complete_input(fixture.repository_key)
                    preview = create_defect(inputs, repo=fixture.repo)
                    self.apply(preview)
                    scope = dict(inputs["scope"])
                    scope.update(growth)
                    promoted = promote_defect(
                        preview.defect_id,
                        repo=fixture.repo,
                        timestamp=PROMOTED_AT,
                        source="synthetic-scope-review",
                        author_class="test",
                        scope=scope,
                    )
                    defect = read_defect(fixture.repo, preview.defect_id).record
                    self.assertEqual(
                        promoted.record["source_defect_id"],
                        preview.defect_id,
                    )
                    self.assertEqual(defect["exemption"]["decision"], "promote")
                    self.assertTrue(defect["fix_paused"])
                finally:
                    fixture.cleanup()

    def test_promotion_seed_uses_explicit_closed_fields_without_chat_context(self):
        inputs = complete_input(self.fixture.repository_key)
        inputs.update(
            {
                "problem": "fixture readers can observe a value older than the committed value",
                "affected_users": ["fixture readers", "fixture maintainers"],
                "requirement_candidates": [
                    "REQ-CAND-001: return the latest committed value",
                    "REQ-CAND-002: invalidate stale serializer cache entries",
                ],
                "risks": [
                    "cache invalidation may increase synthetic fixture latency",
                    "serializer changes may affect a second component",
                ],
                "open_decisions": [
                    "select revision-based or digest-based invalidation"
                ],
                "dependencies": ["DEP-synthetic-serializer"],
                "exemption": {
                    "decision": "promote",
                    "conditions": [True, False, True, True, True],
                },
            }
        )
        preview = self.create(inputs)
        seed = promote_defect(
            preview.defect_id,
            repo=self.fixture.repo,
            timestamp=PROMOTED_AT,
            source="synthetic-scope-review",
            author_class="test",
        ).record
        self.assertEqual(seed["problem"], inputs["problem"])
        self.assertEqual(seed["affected_users"], inputs["affected_users"])
        self.assertEqual(
            seed["requirement_candidates"],
            inputs["requirement_candidates"],
        )
        self.assertEqual(seed["dependencies"], inputs["dependencies"])
        self.assertEqual(seed["risk"], inputs["risks"])
        self.assertEqual(seed["open_decisions"], inputs["open_decisions"])
        self.assertEqual(seed["status"], "draft")
        self.assertNotIn(CREATED, seed)


if __name__ == "__main__":
    unittest.main()
