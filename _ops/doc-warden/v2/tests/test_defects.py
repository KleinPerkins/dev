from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from doc_warden.artifacts import draft_artifact
from doc_warden.canonical import canonical_json, digest_ref, parse_artifact
from doc_warden.defects import (
    append_evidence,
    create_defect,
    defect_ready_check,
    eliminate_hypothesis,
    read_defect,
    reevaluate_exemption,
    transition_defect,
)
from doc_warden.roadmap import parse_roadmap
from doc_warden.transactions import (
    apply_transaction,
    confirmation_for,
)
from doc_warden.validators import (
    defect_event_digest,
    defect_symptoms_digest,
    validate_defect_record,
)
from fixture_factory import FixtureFactory, ROOT


CREATED = "2026-08-31T09:30:00+00:00"
TRIAGED = "2026-08-31T09:31:00+00:00"
INVESTIGATING = "2026-08-31T09:32:00+00:00"
EVIDENCE_AT = "2026-08-31T09:33:00+00:00"
ELIMINATED_AT = "2026-08-31T09:34:00+00:00"
REEVALUATED_AT = "2026-08-31T09:34:30+00:00"
READY_AT = "2026-08-31T09:35:00+00:00"
FIXING_AT = "2026-08-31T09:36:00+00:00"
VERIFYING_AT = "2026-08-31T09:37:00+00:00"
RESOLVED_AT = "2026-08-31T09:38:00+00:00"
RECURRED_AT = "2026-08-31T09:39:00+00:00"
REOPENED_AT = "2026-08-31T09:40:00+00:00"


def complete_input(repository_key: str) -> dict[str, object]:
    return {
        "title": "Fixture cache returns stale values",
        "created_at": CREATED,
        "severity": "high",
        "priority": "P1",
        "owner": "fixture-owner",
        "report_provenance": {
            "source": "synthetic-fixture-report",
            "reported_at": CREATED,
            "author_class": "test",
        },
        "environment": "isolated synthetic fixture",
        "preconditions": ["fixture cache contains one prior value"],
        "test_data": "synthetic key/value pair only",
        "reproduction": [
            "write fixture value v1",
            "replace it with fixture value v2",
            "read the fixture key",
        ],
        "expected": "the reader returns fixture value v2",
        "actual": "the reader returns stale fixture value v1",
        "error_reference": "AssertionError: expected v2, observed v1",
        "frequency": "every synthetic reproduction",
        "known_good_revision": "a" * 40,
        "known_bad_revision": "b" * 40,
        "impact": "the synthetic fixture cannot verify cache freshness",
        "immutable_symptoms": [
            "the second read returns the first synthetic value",
            "the stale read is deterministic in the fixture",
        ],
        "current_focus": {
            "hypothesis": "the cache key omits the fixture revision",
            "test": "compare cache keys before and after the fixture update",
            "expecting": "identical keys would confirm stale-key reuse",
            "next_action": "record both cache keys in the synthetic reproducer",
            "bug_class": "heisenbug-mandelbug",
            "reasoning_checkpoint": None,
            "tdd_checkpoint": None,
        },
        "hypotheses": [
            {
                "id": "HYP-001",
                "statement": "the cache key omits the fixture revision",
                "status": "active",
            },
            {
                "id": "HYP-002",
                "statement": "the fixture update is not persisted",
                "status": "active",
            },
        ],
        "anchors": [
            {
                "repository_key": repository_key,
                "github_repository_id": None,
                "revision": "b" * 40,
                "path": "src/cache.py",
                "kind": "symbol",
                "symbol": "cache.read",
                "line_hint": "10-20",
            },
            {
                "repository_key": repository_key,
                "github_repository_id": None,
                "revision": "b" * 40,
                "path": "tests/test_cache.py",
                "kind": "test",
                "symbol": "test_refreshes_cached_value",
                "line_hint": "30-50",
            },
        ],
        "dependencies": [],
        "workaround": "clear the synthetic fixture cache before the second read",
        "resolution": {
            "root_cause": None,
            "fix": None,
            "verification": {"automated": [], "human": []},
            "oracle_type": None,
            "files_changed": [],
        },
        "fix_refs": {"commit": None, "pull_request": None, "plan": None},
        "acceptance": [
            "the reproducer returns fixture value v2 without manual cache clearing",
            "the cache regression suite remains green",
        ],
        "verification_plan": {
            "automated": [
                "run the focused synthetic reproducer",
                "run the cache regression suite",
            ],
            "human": ["confirm the fixture report is understandable without chat context"],
        },
        "related_artifacts": [],
        "relations": [],
        "affected_users": ["fixture maintainers"],
        "requirement_candidates": [
            "REQ-CAND-001: cache reads return the latest committed fixture value"
        ],
        "risks": ["cache-key changes could reduce the fixture hit rate"],
        "open_decisions": ["whether revision or content digest belongs in the cache key"],
        "scope": {
            "repositories": 1,
            "components": ["cache", "reader"],
            "sessions": 1,
            "new_behavior": False,
            "ui_visual": False,
            "sensitive": False,
            "new_dependency": False,
            "schema_or_state_change": False,
            "reversible": True,
        },
        "exemption": {
            "decision": "exempt",
            "conditions": [True, True, True, True, True],
        },
    }


def exemption_assessment(
    conditions: list[bool] | None = None,
) -> dict[str, object]:
    return {
        "timestamp": REEVALUATED_AT,
        "source": "synthetic-exemption-review",
        "author_class": "test",
        "conditions": (
            [True, True, True, True, True]
            if conditions is None
            else conditions
        ),
    }


class DefectTests(unittest.TestCase):
    @staticmethod
    def unavailable_baseline():
        return {
            "status": "unavailable",
            "reason": "No working baseline exists in the available fixture history",
            "history": [{"revision": "b" * 40, "finding": "Initial implementation reproduces the defect"}],
        }

    def test_unavailable_baseline_lifecycle_and_verification_gate(self):
        inputs = complete_input(self.fixture.repository_key)
        inputs["known_good_revision"] = self.unavailable_baseline()
        preview = self.create(inputs)
        self.advance_to_ready(preview.defect_id)
        self.assertTrue(defect_ready_check(preview.defect_id, repo=self.fixture.repo).ready)
        for target, timestamp in (("fixing", FIXING_AT), ("verifying", VERIFYING_AT)):
            self.apply(transition_defect(preview.defect_id, target, repo=self.fixture.repo,
                                        timestamp=timestamp, source="fixture-fix", author_class="test"))
        current = read_defect(self.fixture.repo, preview.defect_id)
        self.assertEqual(current.record["known_good_revision"], inputs["known_good_revision"])
        with self.assertRaisesRegex(ValueError, "resolution_verification_incomplete"):
            transition_defect(preview.defect_id, "resolved", repo=self.fixture.repo,
                              timestamp=RESOLVED_AT, source="fixture-fix", author_class="test",
                              resolution={"root_cause": "fixture cause", "fix": "fixture correction",
                                          "verification": {"automated": [], "human": []},
                                          "oracle_type": "specified", "files_changed": ["src/cache.py"]})

    def test_unavailable_baseline_triage_replay_and_freeze(self):
        inputs = complete_input(self.fixture.repository_key)
        inputs["known_good_revision"] = ""
        preview = self.create(inputs)
        args = dict(repo=self.fixture.repo, timestamp=TRIAGED, source="fixture-history",
                    author_class="test", operation_id=self.fixture.id_for("baseline-triage"),
                    symptoms={"known_good_revision": self.unavailable_baseline()})
        with self.assertRaisesRegex(ValueError, "defect_symptoms_incomplete:known_good_revision"):
            transition_defect(preview.defect_id, "triaged", **{**args, "symptoms": None})
        receipt = self.apply(transition_defect(preview.defect_id, "triaged", **args))
        before = read_defect(self.fixture.repo, preview.defect_id)
        self.assertEqual(transition_defect(preview.defect_id, "triaged", **args), receipt)
        self.assertEqual(read_defect(self.fixture.repo, preview.defect_id).digest, before.digest)
        changed = self.unavailable_baseline()
        changed["reason"] = "Different investigation"
        with self.assertRaisesRegex(ValueError, "replay_mismatch"):
            transition_defect(preview.defect_id, "triaged",
                              **{**args, "symptoms": {"known_good_revision": changed}})
        with self.assertRaisesRegex(ValueError, "defect_symptoms_frozen"):
            transition_defect(preview.defect_id, "investigating", repo=self.fixture.repo,
                              timestamp=INVESTIGATING, source="fixture-history", author_class="test",
                              symptoms={"known_good_revision": changed})
        tampered = json.loads(json.dumps(before.record))
        tampered["known_good_revision"]["history"][0]["finding"] = "Rewritten history"
        with self.assertRaisesRegex(ValueError, "defect_symptoms_tampered"):
            validate_defect_record(tampered)

    def test_unavailable_baseline_rejects_malformed_evidence_at_create_and_triage(self):
        good = self.unavailable_baseline()
        invalid = [None, [], {}, "unavailable", {**good, "status": "unknown"},
                   {**good, "reason": " \t"}, {**good, "reason": 1},
                   {**good, "history": []}, {**good, "history": "not a list"},
                   {"status": "unavailable", "reason": "no history"},
                   {**good, "extra": True}, {**good, "history": good["history"] * 2}]
        for item in ({"finding": "missing revision"}, {"revision": "b" * 40},
                     {"revision": "no-head", "finding": "no revision"},
                     {"revision": "B" * 40, "finding": "uppercase"},
                     {"revision": "b" * 39, "finding": "short"},
                     {"revision": "b" * 40, "finding": "\n"},
                     {"revision": "b" * 40, "finding": "found", "extra": True}):
            invalid.append({**good, "history": [item]})
        inputs = complete_input(self.fixture.repository_key)
        preview = self.create({**inputs, "known_good_revision": ""})
        before = read_defect(self.fixture.repo, preview.defect_id).digest
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    create_defect({**inputs, "known_good_revision": value}, repo=self.fixture.repo)
                with self.assertRaises(ValueError):
                    transition_defect(preview.defect_id, "triaged", repo=self.fixture.repo,
                                      timestamp=TRIAGED, source="fixture-history", author_class="test",
                                      symptoms={"known_good_revision": value})
                self.assertEqual(read_defect(self.fixture.repo, preview.defect_id).digest, before)

    def test_unavailable_baseline_does_not_replace_other_ready_requirements(self):
        inputs = complete_input(self.fixture.repository_key)
        inputs.update(known_good_revision=self.unavailable_baseline(), known_bad_revision="",
                      reproduction=[], acceptance=[], verification_plan={"automated": [], "human": []})
        preview = self.create(inputs)
        with self.assertRaisesRegex(ValueError, "defect_symptoms_incomplete:reproduction,known_bad_revision"):
            self.advance_to_investigating(preview.defect_id)
        self.apply(transition_defect(preview.defect_id, "triaged", repo=self.fixture.repo,
                                    timestamp=TRIAGED, source="fixture-history", author_class="test",
                                    symptoms={"known_bad_revision": "b" * 40, "reproduction": ["reproduce"]}))
        self.apply(transition_defect(preview.defect_id, "investigating", repo=self.fixture.repo,
                                    timestamp=INVESTIGATING, source="fixture-history", author_class="test"))
        self.append_required_evidence(preview.defect_id)
        verdict = defect_ready_check(preview.defect_id, repo=self.fixture.repo)
        self.assertFalse(verdict.ready)
        for field in ("acceptance", "verification_plan.automated", "verification_plan.human"):
            self.assertIn(field, verdict.missing_fields)

    def test_legacy_baseline_record_bytes_and_digests_remain_exact(self):
        # Captured using the pre-extension implementation, with fixed operation IDs.
        preview = create_defect(complete_input(self.fixture.repository_key), repo=self.fixture.repo,
                                operation_id=self.fixture.id_for("legacy-baseline-golden"))
        self.apply(preview)
        self.apply(transition_defect(preview.defect_id, "triaged", repo=self.fixture.repo,
                                    timestamp=TRIAGED, source="legacy-baseline-golden", author_class="test",
                                    operation_id=self.fixture.id_for("legacy-baseline-triage")))
        record = read_defect(self.fixture.repo, preview.defect_id).record
        self.assertEqual(digest_ref(canonical_json(record)),
                         "sha256:773d4f22a7b3933c1bea099cc8daad83a27ae03a441538aca85cee652ba535f6")
        self.assertEqual(record["symptoms_digest"],
                         "sha256:529d76f7f15efa7219a656d0d5afc152c943d4e127794c3ae5d6ef3406cc14c7")

    def setUp(self):
        self.fixture = FixtureFactory.create("defect")

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

    def assert_receipt_binds_current_defect(
        self,
        receipt,
        defect_id: str,
        previous,
    ):
        current = read_defect(self.fixture.repo, defect_id)
        relative_path = str(current.path.relative_to(self.fixture.repo.resolve()))
        parsed = parse_artifact(current.path)
        self.assertEqual(parsed.body.encode("utf-8"), canonical_json(current.record))
        current_digest = digest_ref(current.path.read_bytes())
        self.assertEqual(
            receipt["bindings"]["defect_authority"],
            {
                "defect_id": current.record["id"],
                "record_version": current.record["record_version"],
                "event_id": current.record["history_head"]["event_id"],
                "defect_digest": current_digest,
            },
        )
        self.assertEqual(receipt["postimages"][relative_path], current_digest)
        defect_action = next(
            action for action in receipt["actions"] if action["path"] == relative_path
        )
        self.assertEqual(defect_action["content_digest"], current_digest)
        self.assertNotEqual(
            receipt["bindings"]["defect_authority"]["record_version"],
            previous.record["record_version"],
        )
        self.assertNotEqual(
            receipt["bindings"]["defect_authority"]["event_id"],
            previous.record["history_head"]["event_id"],
        )
        self.assertNotEqual(
            receipt["bindings"]["defect_authority"]["defect_digest"],
            previous.digest,
        )
        return current

    def create(self, inputs: dict[str, object] | None = None):
        preview = create_defect(
            inputs or complete_input(self.fixture.repository_key),
            repo=self.fixture.repo,
        )
        self.apply(preview)
        return preview

    def advance_to_investigating(self, defect_id: str) -> None:
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

    def append_required_evidence(
        self,
        defect_id: str,
        *,
        operation_id: str | None = None,
    ):
        return append_evidence(
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
            operation_id=operation_id,
        )

    def advance_to_ready(self, defect_id: str) -> None:
        self.advance_to_investigating(defect_id)
        self.append_required_evidence(defect_id)
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

    def test_default_exemption_can_be_reevaluated_to_ready_and_bind_a_plan(self):
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

        self.advance_to_investigating(preview.defect_id)
        self.append_required_evidence(preview.defect_id)
        blocked = defect_ready_check(preview.defect_id, repo=self.fixture.repo)
        self.assertFalse(blocked.ready)
        self.assertEqual(blocked.missing_fields, ("exemption.conditions",))
        self.assertEqual(blocked.invalid_fields, ())
        with self.assertRaisesRegex(
            ValueError,
            "^defect_not_ready:exemption.conditions$",
        ):
            transition_defect(
                preview.defect_id,
                "ready",
                repo=self.fixture.repo,
                timestamp=READY_AT,
                source="synthetic-ready-check",
                author_class="test",
            )

        previous = read_defect(self.fixture.repo, preview.defect_id)
        operation_id = self.fixture.id_for("reevaluate-default-exemption")
        assessment = exemption_assessment()
        receipt = reevaluate_exemption(
            preview.defect_id,
            assessment,
            repo=self.fixture.repo,
            operation_id=operation_id,
        )
        replayed = reevaluate_exemption(
            preview.defect_id,
            assessment,
            repo=self.fixture.repo,
            operation_id=operation_id,
        )
        self.assertEqual(replayed, receipt)
        with self.assertRaisesRegex(
            ValueError,
            "^defect_operation_replay_mismatch$",
        ):
            reevaluate_exemption(
                preview.defect_id,
                {**assessment, "source": "changed-review-source"},
                repo=self.fixture.repo,
                operation_id=operation_id,
            )
        current = self.assert_receipt_binds_current_defect(
            receipt,
            preview.defect_id,
            previous,
        )
        self.assertEqual(
            current.record["events"][-1]["kind"],
            "exemption_reevaluated",
        )
        self.assertEqual(
            current.record["exemption"]["conditions"],
            [True, True, True, True, True],
        )
        self.assertTrue(
            defect_ready_check(preview.defect_id, repo=self.fixture.repo).ready
        )

        self.apply(
            transition_defect(
                preview.defect_id,
                "ready",
                repo=self.fixture.repo,
                timestamp=READY_AT,
                source="synthetic-ready-check",
                author_class="test",
            )
        )
        ready = read_defect(self.fixture.repo, preview.defect_id)
        plan = draft_artifact(
            "plan",
            {
                "title": "Default-created defect fix",
                "defect_id": preview.defect_id,
                "approved_prd": False,
            },
            repo=self.fixture.repo,
        )
        self.assertEqual(
            plan.transaction.bindings["defect_authority"],
            {
                "defect_id": preview.defect_id,
                "record_version": ready.record["record_version"],
                "event_id": ready.record["history_head"]["event_id"],
                "defect_digest": ready.digest,
            },
        )

    def test_exemption_reevaluation_refuses_malformed_partial_and_unsafe_updates(self):
        inputs = complete_input(self.fixture.repository_key)
        inputs.pop("exemption")
        preview = self.create(inputs)
        self.advance_to_investigating(preview.defect_id)
        self.append_required_evidence(preview.defect_id)
        before = read_defect(self.fixture.repo, preview.defect_id)

        malformed = (
            None,
            [],
            {},
            {
                "timestamp": REEVALUATED_AT,
                "source": "synthetic-exemption-review",
                "author_class": "test",
            },
            {**exemption_assessment(), "unexpected": True},
            exemption_assessment([]),
            exemption_assessment([True, True, True, True]),
            exemption_assessment([True, True, True, True, 1]),
            {
                **exemption_assessment(),
                "conditions": (True, True, True, True, True),
            },
        )
        for index, assessment in enumerate(malformed):
            with (
                self.subTest(case=index),
                self.assertRaisesRegex(
                    ValueError,
                    "^defect_exemption_assessment_invalid$",
                ),
            ):
                reevaluate_exemption(
                    preview.defect_id,
                    assessment,
                    repo=self.fixture.repo,
                    operation_id=self.fixture.id_for(
                        f"malformed-exemption-{index}"
                    ),
                )
            unchanged = read_defect(self.fixture.repo, preview.defect_id)
            self.assertEqual(unchanged.digest, before.digest)
            self.assertEqual(unchanged.record, before.record)

        with self.assertRaisesRegex(
            ValueError,
            "^defect_exemption_promotion_required$",
        ):
            reevaluate_exemption(
                preview.defect_id,
                exemption_assessment([True, True, True, False, True]),
                repo=self.fixture.repo,
                operation_id=self.fixture.id_for("invalid-exemption"),
            )
        self.assertEqual(
            read_defect(self.fixture.repo, preview.defect_id).digest,
            before.digest,
        )

        no_evidence_inputs = complete_input(self.fixture.repository_key)
        no_evidence_inputs.pop("exemption")
        no_evidence = self.create(no_evidence_inputs)
        self.advance_to_investigating(no_evidence.defect_id)
        with self.assertRaisesRegex(
            ValueError,
            "^defect_exemption_reevaluation_blocked:evidence$",
        ):
            reevaluate_exemption(
                no_evidence.defect_id,
                exemption_assessment(),
                repo=self.fixture.repo,
            )

        unsafe_inputs = complete_input(self.fixture.repository_key)
        unsafe_inputs.pop("exemption")
        unsafe_inputs["scope"]["new_behavior"] = True
        unsafe = self.create(unsafe_inputs)
        self.advance_to_investigating(unsafe.defect_id)
        self.append_required_evidence(unsafe.defect_id)
        with self.assertRaisesRegex(
            ValueError,
            "^defect_exemption_reevaluation_blocked:"
            "exemption.scope:promotion_required$",
        ):
            reevaluate_exemption(
                unsafe.defect_id,
                exemption_assessment(),
                repo=self.fixture.repo,
            )

    def test_reevaluated_exemption_event_rejects_semantic_digest_forgery(self):
        inputs = complete_input(self.fixture.repository_key)
        inputs.pop("exemption")
        preview = self.create(inputs)
        self.advance_to_investigating(preview.defect_id)
        self.append_required_evidence(preview.defect_id)
        reevaluate_exemption(
            preview.defect_id,
            exemption_assessment(),
            repo=self.fixture.repo,
        )

        artifact = self.fixture.repo / preview.defect_path
        parsed = parse_artifact(artifact)
        record = json.loads(parsed.body)
        event = record["events"][-1]
        self.assertEqual(event["kind"], "exemption_reevaluated")
        event["payload"]["exemption"]["conditions"][4] = False
        event["event_digest"] = defect_event_digest(event)
        record["exemption"] = event["payload"]["exemption"]
        record["history_head"]["digest"] = event["event_digest"]
        artifact.write_bytes(
            b"---\n"
            + canonical_json(parsed.metadata)
            + b"---\n"
            + canonical_json(record)
        )
        with self.assertRaisesRegex(
            ValueError,
            f"^defect_event_tampered:{event['event_id']}$",
        ):
            read_defect(self.fixture.repo, preview.defect_id)

    def test_ready_requires_every_zero_context_field_and_specific_next_action(self):
        incomplete = {
            "title": "Incomplete fixture report",
            "created_at": CREATED,
            "owner": "fixture-owner",
            "severity": "medium",
            "priority": "P2",
            "current_focus": {
                "hypothesis": "",
                "test": "",
                "expecting": "",
                "next_action": "investigate",
                "bug_class": None,
                "reasoning_checkpoint": None,
                "tdd_checkpoint": None,
            },
        }
        preview = self.create(incomplete)
        verdict = defect_ready_check(preview.defect_id, repo=self.fixture.repo)
        self.assertFalse(verdict.ready)
        self.assertEqual(
            verdict.missing_fields,
            (
                "report_provenance.source",
                "report_provenance.reported_at",
                "report_provenance.author_class",
                "environment",
                "preconditions",
                "test_data",
                "reproduction",
                "expected",
                "actual",
                "error_reference",
                "frequency",
                "known_good_revision",
                "known_bad_revision",
                "impact",
                "immutable_symptoms",
                "symptoms_digest",
                "evidence",
                "current_focus.hypothesis",
                "current_focus.test",
                "current_focus.expecting",
                "hypotheses",
                "anchors.code",
                "anchors.test",
                "acceptance",
                "verification_plan.automated",
                "verification_plan.human",
                "exemption.conditions",
            ),
        )
        self.assertIn("current_focus.next_action:generic", verdict.invalid_fields)
        with self.assertRaisesRegex(
            ValueError,
            "defect_not_ready:.*current_focus.next_action:generic",
        ):
            self.apply(
                transition_defect(
                    preview.defect_id,
                    "ready",
                    repo=self.fixture.repo,
                    timestamp=READY_AT,
                    source="synthetic-ready-check",
                    author_class="test",
                )
            )

    def test_ready_rejects_blank_entries_in_every_required_string_list(self):
        cases = (
            ("preconditions", None, [""], "preconditions"),
            ("reproduction", None, [" \t "], "reproduction"),
            (
                "immutable_symptoms",
                None,
                ["the stale value is observed", "\n"],
                "immutable_symptoms",
            ),
            (
                "acceptance",
                None,
                ["the latest value is returned", "  "],
                "acceptance",
            ),
            (
                "verification_plan",
                "automated",
                [""],
                "verification_plan.automated",
            ),
            (
                "verification_plan",
                "human",
                ["confirm the report is resolved", "\t"],
                "verification_plan.human",
            ),
        )
        for field, nested, value, expected in cases:
            with self.subTest(field=expected):
                inputs = complete_input(self.fixture.repository_key)
                if nested is None:
                    inputs[field] = value
                else:
                    inputs[field][nested] = value
                preview = self.create(inputs)
                if field in {
                    "preconditions",
                    "reproduction",
                    "immutable_symptoms",
                }:
                    with self.assertRaises(ValueError) as raised:
                        transition_defect(
                            preview.defect_id,
                            "triaged",
                            repo=self.fixture.repo,
                            timestamp=TRIAGED,
                            source="synthetic-lifecycle",
                            author_class="test",
                        )
                    self.assertEqual(
                        str(raised.exception),
                        f"defect_symptoms_incomplete:{expected}",
                    )
                    self.assertEqual(
                        read_defect(
                            self.fixture.repo,
                            preview.defect_id,
                        ).record["lifecycle"],
                        "reported",
                    )
                    continue
                self.advance_to_investigating(preview.defect_id)
                self.append_required_evidence(preview.defect_id)

                verdict = defect_ready_check(
                    preview.defect_id,
                    repo=self.fixture.repo,
                )
                self.assertEqual(verdict.missing_fields, (expected,))
                self.assertEqual(verdict.invalid_fields, ())
                with self.assertRaises(ValueError) as raised:
                    transition_defect(
                        preview.defect_id,
                        "ready",
                        repo=self.fixture.repo,
                        timestamp=READY_AT,
                        source="synthetic-ready-check",
                        author_class="test",
                    )
                self.assertEqual(
                    str(raised.exception),
                    f"defect_not_ready:{expected}",
                )
                self.assertEqual(
                    read_defect(
                        self.fixture.repo,
                        preview.defect_id,
                    ).record["lifecycle"],
                    "investigating",
                )

    def test_symptoms_cannot_change_after_triage_and_tamper_names_freeze_event(self):
        preview = self.create()
        triage = transition_defect(
            preview.defect_id,
            "triaged",
            repo=self.fixture.repo,
            timestamp=TRIAGED,
            source="synthetic-triage",
            author_class="test",
        )
        freeze_event_id = triage.defect_event_id
        self.apply(triage)
        with self.assertRaisesRegex(ValueError, "defect_symptoms_frozen"):
            transition_defect(
                preview.defect_id,
                "investigating",
                repo=self.fixture.repo,
                timestamp=INVESTIGATING,
                source="synthetic-lifecycle",
                author_class="test",
                symptoms={"actual": "rewritten symptom"},
            )

        artifact = self.fixture.repo / preview.defect_path
        parsed = parse_artifact(artifact)
        record = json.loads(parsed.body)
        record["actual"] = "manually rewritten symptom"
        artifact.write_bytes(
            b"---\n"
            + canonical_json(parsed.metadata)
            + b"---\n"
            + canonical_json(record)
        )
        with self.assertRaisesRegex(
            ValueError,
            f"defect_symptoms_tampered:{freeze_event_id}",
        ):
            defect_ready_check(preview.defect_id, repo=self.fixture.repo)

    def test_triage_requires_complete_symptoms_and_can_complete_partial_report(self):
        complete = complete_input(self.fixture.repository_key)
        inputs = dict(complete)
        inputs["environment"] = " \t "
        inputs["reproduction"] = ["first valid step", "\n"]
        inputs["actual"] = ""
        preview = self.create(inputs)
        before = read_defect(self.fixture.repo, preview.defect_id)

        for symptoms, missing in (
            (
                None,
                "environment,reproduction,actual",
            ),
            (
                {"environment": complete["environment"]},
                "reproduction,actual",
            ),
            (
                {
                    "environment": complete["environment"],
                    "reproduction": complete["reproduction"],
                    "actual": " \n ",
                },
                "actual",
            ),
        ):
            with self.subTest(missing=missing):
                with self.assertRaisesRegex(
                    ValueError,
                    f"^defect_symptoms_incomplete:{missing}$",
                ):
                    transition_defect(
                        preview.defect_id,
                        "triaged",
                        repo=self.fixture.repo,
                        timestamp=TRIAGED,
                        source="synthetic-triage",
                        author_class="test",
                        symptoms=symptoms,
                    )
                unchanged = read_defect(self.fixture.repo, preview.defect_id)
                self.assertEqual(unchanged.digest, before.digest)
                self.assertEqual(unchanged.record, before.record)

        corrections = {
            field: complete[field]
            for field in (
                "environment",
                "preconditions",
                "test_data",
                "reproduction",
                "expected",
                "actual",
                "error_reference",
                "frequency",
                "known_good_revision",
                "known_bad_revision",
                "immutable_symptoms",
            )
        }
        triage = transition_defect(
            preview.defect_id,
            "triaged",
            repo=self.fixture.repo,
            timestamp=TRIAGED,
            source="synthetic-triage",
            author_class="test",
            symptoms=corrections,
        )
        self.apply(triage)
        frozen = read_defect(self.fixture.repo, preview.defect_id)
        self.assertEqual(frozen.record["lifecycle"], "triaged")
        self.assertEqual(frozen.record["symptoms_frozen_event_id"], triage.defect_event_id)
        self.assertEqual(frozen.record["events"][-1]["payload"]["symptoms"], corrections)
        with self.assertRaisesRegex(ValueError, "^defect_symptoms_frozen$"):
            transition_defect(
                preview.defect_id,
                "investigating",
                repo=self.fixture.repo,
                timestamp=INVESTIGATING,
                source="synthetic-lifecycle",
                author_class="test",
                symptoms={"actual": "rewritten after freeze"},
            )

        parsed = parse_artifact(frozen.path)
        tampered = json.loads(parsed.body)
        freeze_event = tampered["events"][-1]
        freeze_event["payload"]["symptoms"]["actual"] = " \t "
        tampered["actual"] = " \t "
        tampered["symptoms_digest"] = defect_symptoms_digest(tampered)
        freeze_event["payload"]["symptoms_digest"] = tampered["symptoms_digest"]
        freeze_event["event_digest"] = defect_event_digest(freeze_event)
        tampered["history_head"]["digest"] = freeze_event["event_digest"]
        frozen.path.write_bytes(
            b"---\n"
            + canonical_json(parsed.metadata)
            + b"---\n"
            + canonical_json(tampered)
        )
        with self.assertRaisesRegex(
            ValueError,
            f"^defect_event_tampered:{freeze_event['event_id']}$",
        ):
            read_defect(self.fixture.repo, preview.defect_id)

    def test_transition_replay_returns_original_receipt_without_duplicate_event(self):
        preview = self.create()
        operation_id = self.fixture.id_for("idempotent-triage")
        transition = transition_defect(
            preview.defect_id,
            "triaged",
            repo=self.fixture.repo,
            timestamp=TRIAGED,
            source="synthetic-triage",
            author_class="test",
            operation_id=operation_id,
        )
        receipt = self.apply(transition)
        receipt_path = (
            self.fixture.repo
            / "_ops/doc-warden/state/v2/receipts"
            / f"{operation_id}.json"
        )
        after = read_defect(self.fixture.repo, preview.defect_id)
        replayed = transition_defect(
            preview.defect_id,
            "triaged",
            repo=self.fixture.repo,
            timestamp=TRIAGED,
            source="synthetic-triage",
            author_class="test",
            operation_id=operation_id,
        )
        self.assertEqual(replayed, receipt)
        self.assertEqual(canonical_json(replayed), receipt_path.read_bytes())
        unchanged = read_defect(self.fixture.repo, preview.defect_id)
        self.assertEqual(unchanged.digest, after.digest)
        self.assertEqual(unchanged.record, after.record)

        for conflict in (
            {"timestamp": INVESTIGATING},
            {"source": "changed-source"},
            {"target": "investigating"},
        ):
            with self.subTest(conflict=conflict):
                arguments = {
                    "defect_id": preview.defect_id,
                    "target": "triaged",
                    "repo": self.fixture.repo,
                    "timestamp": TRIAGED,
                    "source": "synthetic-triage",
                    "author_class": "test",
                    "operation_id": operation_id,
                    **conflict,
                }
                with self.assertRaisesRegex(
                    ValueError,
                    "^defect_operation_replay_mismatch$",
                ):
                    transition_defect(**arguments)
        self.assertEqual(
            read_defect(self.fixture.repo, preview.defect_id).record,
            after.record,
        )

        ordinary_operation = self.fixture.id_for("idempotent-investigating")
        ordinary = transition_defect(
            preview.defect_id,
            "investigating",
            repo=self.fixture.repo,
            timestamp=INVESTIGATING,
            source="synthetic-lifecycle",
            author_class="test",
            operation_id=ordinary_operation,
        )
        ordinary_receipt = self.apply(ordinary)
        ordinary_after = read_defect(self.fixture.repo, preview.defect_id)
        self.assertEqual(
            transition_defect(
                preview.defect_id,
                "investigating",
                repo=self.fixture.repo,
                timestamp=INVESTIGATING,
                source="synthetic-lifecycle",
                author_class="test",
                operation_id=ordinary_operation,
            ),
            ordinary_receipt,
        )
        self.assertEqual(
            read_defect(self.fixture.repo, preview.defect_id).record,
            ordinary_after.record,
        )

    def test_transition_replay_recovers_missing_receipt_without_reapplying_history(self):
        preview = self.create()
        self.apply(
            transition_defect(
                preview.defect_id,
                "triaged",
                repo=self.fixture.repo,
                timestamp=TRIAGED,
                source="synthetic-triage",
                author_class="test",
            )
        )
        operation_id = self.fixture.id_for("interrupted-investigating-receipt")
        transition = transition_defect(
            preview.defect_id,
            "investigating",
            repo=self.fixture.repo,
            timestamp=INVESTIGATING,
            source="synthetic-lifecycle",
            author_class="test",
            operation_id=operation_id,
        )
        receipt = self.apply(transition)
        receipt_path = (
            self.fixture.repo
            / "_ops/doc-warden/state/v2/receipts"
            / f"{operation_id}.json"
        )
        receipt_bytes = receipt_path.read_bytes()
        after = read_defect(self.fixture.repo, preview.defect_id)
        roadmap_path = self.fixture.repo / ".planning/ROADMAP.md"
        authority_state = {
            path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
            for path in (after.path, roadmap_path)
        }
        event_root = self.fixture.repo / "_ops/doc-warden/state/v2/events"
        operation_events = {
            path.name: path.read_bytes()
            for path in sorted(event_root.glob("*.json"))
        }
        operation_event_path = (
            event_root / f"{transition.transaction.event_id}.json"
        )
        operation_event_bytes = operation_event_path.read_bytes()
        receipt_path.unlink()

        with self.assertRaisesRegex(
            ValueError,
            "^defect_operation_replay_mismatch$",
        ):
            transition_defect(
                preview.defect_id,
                "investigating",
                repo=self.fixture.repo,
                timestamp=INVESTIGATING,
                source="changed-source",
                author_class="test",
                operation_id=operation_id,
            )
        with self.assertRaisesRegex(
            ValueError,
            "^defect_operation_replay_mismatch$",
        ):
            transition_defect(
                preview.defect_id,
                "duplicate",
                repo=self.fixture.repo,
                timestamp=EVIDENCE_AT,
                source="synthetic-duplicate",
                author_class="test",
                operation_id=operation_id,
                relation={
                    "schema": "doc-warden/relation/v2",
                    "relation": "duplicates",
                    "source_id": preview.defect_id,
                    "source_version": None,
                    "target": {
                        "kind": "defect",
                        "id": "DEF-other",
                        "version": None,
                    },
                    "authority": "observed",
                    "provenance": [{"source": "synthetic-duplicate"}],
                    "observed_revision": "c" * 40,
                    "observed_at": EVIDENCE_AT,
                    "lifecycle": "active",
                },
            )
        with self.assertRaisesRegex(
            ValueError,
            "^defect_operation_replay_mismatch$",
        ):
            self.append_required_evidence(
                preview.defect_id,
                operation_id=operation_id,
            )
        with self.assertRaisesRegex(
            ValueError,
            "^defect_operation_replay_mismatch$",
        ):
            create_defect(
                complete_input(self.fixture.repository_key),
                repo=self.fixture.repo,
                operation_id=operation_id,
            )
        operation_event_path.unlink()
        with self.assertRaisesRegex(
            ValueError,
            "^defect_operation_replay_mismatch$",
        ):
            self.append_required_evidence(
                preview.defect_id,
                operation_id=operation_id,
            )
        operation_event_path.write_bytes(operation_event_bytes)
        self.assertFalse(receipt_path.exists())
        refused = read_defect(self.fixture.repo, preview.defect_id)
        self.assertEqual(refused.record, after.record)
        self.assertEqual(
            {
                path.name: path.read_bytes()
                for path in sorted(event_root.glob("*.json"))
            },
            operation_events,
        )

        recovered = transition_defect(
            preview.defect_id,
            "investigating",
            repo=self.fixture.repo,
            timestamp=INVESTIGATING,
            source="synthetic-lifecycle",
            author_class="test",
            operation_id=operation_id,
        )
        self.assertEqual(recovered, receipt)
        self.assertEqual(receipt_path.read_bytes(), receipt_bytes)
        self.assertEqual(receipt_path.read_bytes(), canonical_json(recovered))
        current = read_defect(self.fixture.repo, preview.defect_id)
        self.assertEqual(current.record, after.record)
        self.assertEqual(
            [event["event_id"] for event in current.record["events"]],
            [event["event_id"] for event in after.record["events"]],
        )
        self.assertEqual(
            {
                path.name: path.read_bytes()
                for path in sorted(event_root.glob("*.json"))
            },
            operation_events,
        )
        for path, (content, inode, modified) in authority_state.items():
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_create_replay_precedes_collision_and_recovers_missing_receipt(self):
        prior = self.create()
        inputs = complete_input(self.fixture.repository_key)
        operation_id = self.fixture.id_for("idempotent-create")
        preview = create_defect(
            inputs,
            repo=self.fixture.repo,
            operation_id=operation_id,
        )
        receipt = self.apply(preview)
        receipt_path = (
            self.fixture.repo
            / "_ops/doc-warden/state/v2/receipts"
            / f"{operation_id}.json"
        )
        receipt_bytes = receipt_path.read_bytes()
        created = read_defect(self.fixture.repo, preview.defect_id)
        roadmap_path = self.fixture.repo / ".planning/ROADMAP.md"
        authority_state = {
            path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
            for path in (created.path, roadmap_path)
        }
        event_root = self.fixture.repo / "_ops/doc-warden/state/v2/events"
        operation_events = {
            path.name: path.read_bytes()
            for path in sorted(event_root.glob("*.json"))
        }

        replayed = create_defect(
            inputs,
            repo=self.fixture.repo,
            operation_id=operation_id,
        )
        self.assertEqual(replayed, receipt)
        self.assertEqual(canonical_json(replayed), receipt_bytes)
        conflicting = json.loads(json.dumps(inputs))
        conflicting["title"] = "Changed title under the same operation"
        with self.assertRaisesRegex(
            ValueError,
            "^defect_operation_replay_mismatch$",
        ):
            create_defect(
                conflicting,
                repo=self.fixture.repo,
                operation_id=operation_id,
            )

        receipt_path.unlink()
        with self.assertRaisesRegex(
            ValueError,
            "^defect_operation_replay_mismatch$",
        ):
            create_defect(
                conflicting,
                repo=self.fixture.repo,
                operation_id=operation_id,
            )
        self.assertFalse(receipt_path.exists())
        recovered = create_defect(
            inputs,
            repo=self.fixture.repo,
            operation_id=operation_id,
        )
        self.assertEqual(recovered, receipt)
        self.assertEqual(receipt_path.read_bytes(), receipt_bytes)
        self.assertEqual(receipt_path.read_bytes(), canonical_json(recovered))
        current = read_defect(self.fixture.repo, preview.defect_id)
        self.assertEqual(current.record, created.record)
        self.assertEqual(len(current.record["events"]), 1)
        rows = [
            item
            for item in parse_roadmap(roadmap_path)
            if item.get("id") == f"ROAD-{preview.defect_id}"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            len(
                [
                    item
                    for item in parse_roadmap(roadmap_path)
                    if item.get("id") == f"ROAD-{prior.defect_id}"
                ]
            ),
            1,
        )
        self.assertEqual(
            {
                path.name: path.read_bytes()
                for path in sorted(event_root.glob("*.json"))
            },
            operation_events,
        )
        for path, (content, inode, modified) in authority_state.items():
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual(path.stat().st_mtime_ns, modified)

    def test_consequential_transition_replay_preserves_confirmation_and_history(self):
        preview = self.create()
        relation = {
            "schema": "doc-warden/relation/v2",
            "relation": "waives",
            "source_id": preview.defect_id,
            "source_version": None,
            "target": {
                "kind": "decision",
                "id": "WAIVER-IDEMPOTENT-001",
                "version": None,
            },
            "authority": "observed",
            "provenance": [{"source": "synthetic-waiver"}],
            "observed_revision": "c" * 40,
            "observed_at": TRIAGED,
            "lifecycle": "active",
        }
        operation_id = self.fixture.id_for("idempotent-waiver")
        transition = transition_defect(
            preview.defect_id,
            "waived",
            repo=self.fixture.repo,
            timestamp=TRIAGED,
            source="synthetic-waiver",
            author_class="test",
            relation=relation,
            operation_id=operation_id,
        )
        self.assertTrue(transition.transaction.consequential)
        receipt = apply_transaction(
            transition.transaction,
            confirmation_for(transition.transaction),
        )
        after = read_defect(self.fixture.repo, preview.defect_id)
        replayed = transition_defect(
            preview.defect_id,
            "waived",
            repo=self.fixture.repo,
            timestamp=TRIAGED,
            source="synthetic-waiver",
            author_class="test",
            relation=relation,
            operation_id=operation_id,
        )
        self.assertEqual(replayed, receipt)
        self.assertEqual(
            read_defect(self.fixture.repo, preview.defect_id).record,
            after.record,
        )
        conflicting_relation = json.loads(json.dumps(relation))
        conflicting_relation["target"]["id"] = "WAIVER-IDEMPOTENT-002"
        with self.assertRaisesRegex(
            ValueError,
            "^defect_operation_replay_mismatch$",
        ):
            transition_defect(
                preview.defect_id,
                "waived",
                repo=self.fixture.repo,
                timestamp=TRIAGED,
                source="synthetic-waiver",
                author_class="test",
                relation=conflicting_relation,
                operation_id=operation_id,
            )
        self.assertEqual(
            read_defect(self.fixture.repo, preview.defect_id).record,
            after.record,
        )

    def test_evidence_and_eliminated_hypotheses_are_append_only_and_hash_bound(self):
        preview = self.create()
        self.advance_to_investigating(preview.defect_id)
        evidence_operation = self.fixture.id_for("append-evidence")
        receipt = self.append_required_evidence(
            preview.defect_id,
            operation_id=evidence_operation,
        )
        replayed_receipt = self.append_required_evidence(
            preview.defect_id,
            operation_id=evidence_operation,
        )
        self.assertEqual(receipt["transition"], "draft_update")
        self.assertEqual(receipt, replayed_receipt)
        elimination_input = {
            "hypothesis_id": "HYP-002",
            "timestamp": ELIMINATED_AT,
            "source": "synthetic-persistence-check",
            "author_class": "test",
            "evidence": "the fixture update is present before the stale read",
        }
        elimination_operation = self.fixture.id_for("eliminate-hypothesis")
        elimination = eliminate_hypothesis(
            preview.defect_id,
            elimination_input,
            repo=self.fixture.repo,
            operation_id=elimination_operation,
        )
        replayed_elimination = eliminate_hypothesis(
            preview.defect_id,
            elimination_input,
            repo=self.fixture.repo,
            operation_id=elimination_operation,
        )
        self.assertEqual(elimination["transition"], "draft_update")
        self.assertEqual(elimination, replayed_elimination)
        loaded = read_defect(self.fixture.repo, preview.defect_id)
        evidence = loaded.record["evidence"]
        eliminated = loaded.record["eliminated_hypotheses"]
        self.assertEqual(len(evidence), 1)
        self.assertEqual(len(eliminated), 1)
        self.assertEqual(evidence[0]["prior_event_id"], loaded.record["events"][2]["event_id"])
        self.assertEqual(
            eliminated[0]["prior_event_id"],
            evidence[0]["event_id"],
        )
        self.assertEqual(
            next(
                item for item in loaded.record["hypotheses"] if item["id"] == "HYP-002"
            )["status"],
            "eliminated",
        )

        artifact = loaded.path
        parsed = parse_artifact(artifact)
        record = json.loads(parsed.body)
        evidence_event = next(
            event for event in record["events"] if event["kind"] == "evidence_appended"
        )
        evidence_event["payload"]["found"] = "tampered finding"
        artifact.write_bytes(
            b"---\n"
            + canonical_json(parsed.metadata)
            + b"---\n"
            + canonical_json(record)
        )
        with self.assertRaisesRegex(
            ValueError,
            f"defect_event_tampered:{evidence_event['event_id']}",
        ):
            read_defect(self.fixture.repo, preview.defect_id)

    def test_append_evidence_receipt_binds_exact_postmutation_authority(self):
        preview = self.create()
        self.advance_to_investigating(preview.defect_id)
        previous = read_defect(self.fixture.repo, preview.defect_id)
        receipt = self.append_required_evidence(
            preview.defect_id,
            operation_id=self.fixture.id_for("postmutation-evidence-binding"),
        )
        current = self.assert_receipt_binds_current_defect(
            receipt,
            preview.defect_id,
            previous,
        )
        self.assertEqual(
            current.record["evidence"][-1]["checked"],
            "cache keys before and after the fixture update",
        )

    def test_lifecycle_receipt_binds_exact_postmutation_authority(self):
        preview = self.create()
        self.apply(
            transition_defect(
                preview.defect_id,
                "triaged",
                repo=self.fixture.repo,
                timestamp=TRIAGED,
                source="synthetic-triage",
                author_class="test",
            )
        )
        previous = read_defect(self.fixture.repo, preview.defect_id)
        lifecycle = transition_defect(
            preview.defect_id,
            "investigating",
            repo=self.fixture.repo,
            timestamp=INVESTIGATING,
            source="synthetic-lifecycle",
            author_class="test",
            operation_id=self.fixture.id_for("postmutation-lifecycle-binding"),
        )
        receipt = self.apply(lifecycle)
        current = self.assert_receipt_binds_current_defect(
            receipt,
            preview.defect_id,
            previous,
        )
        self.assertEqual(current.record["lifecycle"], "investigating")
        defect_action = next(
            action
            for action in lifecycle.transaction.actions
            if action.path == preview.defect_path
        )
        self.assertEqual(defect_action.content, current.path.read_bytes())

    def test_current_focus_and_resolution_are_mutable_only_with_history(self):
        preview = self.create()
        self.advance_to_investigating(preview.defect_id)
        changed_focus = {
            "hypothesis": "the serializer reuses the prior cache key",
            "test": "trace the serializer input in the fixture",
            "expecting": "a stale input identifies the serializer boundary",
            "next_action": "trace serializer input for both fixture reads",
            "bug_class": "bohrbug",
            "reasoning_checkpoint": {
                "hypothesis": "serializer input is stale",
                "confirming_evidence": "both cache keys match",
                "falsification_test": "compare serializer inputs",
                "fix_rationale": "defer until root cause is confirmed",
                "blind_spots": "fixture clock",
                "candidate_causes": ["serializer", "cache key"],
                "and_gate": "one cause must reproduce independently",
            },
            "tdd_checkpoint": None,
        }
        self.apply(
            transition_defect(
                preview.defect_id,
                "investigating",
                repo=self.fixture.repo,
                timestamp=EVIDENCE_AT,
                source="synthetic-focus-update",
                author_class="test",
                current_focus=changed_focus,
            )
        )
        resolution = {
            "root_cause": "the serializer omitted the fixture revision",
            "fix": "include the fixture revision in the synthetic cache key",
            "verification": {"automated": [], "human": []},
            "oracle_type": "specified",
            "files_changed": ["src/cache.py", "tests/test_cache.py"],
        }
        self.apply(
            transition_defect(
                preview.defect_id,
                "investigating",
                repo=self.fixture.repo,
                timestamp=ELIMINATED_AT,
                source="synthetic-resolution-update",
                author_class="test",
                resolution=resolution,
            )
        )
        loaded = read_defect(self.fixture.repo, preview.defect_id).record
        self.assertEqual(loaded["current_focus"], changed_focus)
        self.assertEqual(loaded["resolution"], resolution)
        self.assertEqual(
            [event["kind"] for event in loaded["events"][-2:]],
            ["focus_updated", "resolution_updated"],
        )

        parsed = parse_artifact(self.fixture.repo / preview.defect_path)
        tampered = json.loads(parsed.body)
        tampered["current_focus"]["next_action"] = "skip the recorded history"
        (self.fixture.repo / preview.defect_path).write_bytes(
            b"---\n"
            + canonical_json(parsed.metadata)
            + b"---\n"
            + canonical_json(tampered)
        )
        with self.assertRaisesRegex(
            ValueError,
            f"defect_current_view_tampered:{tampered['events'][-1]['event_id']}",
        ):
            read_defect(self.fixture.repo, preview.defect_id)

    def test_focus_updates_remain_available_in_triaged_and_ready_states(self):
        preview = self.create()
        self.apply(
            transition_defect(
                preview.defect_id,
                "triaged",
                repo=self.fixture.repo,
                timestamp=TRIAGED,
                source="synthetic-triage",
                author_class="test",
            )
        )
        triaged_focus = {
            **complete_input(self.fixture.repository_key)["current_focus"],
            "next_action": "capture both fixture cache keys before investigation",
        }
        self.apply(
            transition_defect(
                preview.defect_id,
                "triaged",
                repo=self.fixture.repo,
                timestamp=INVESTIGATING,
                source="synthetic-triaged-focus",
                author_class="test",
                current_focus=triaged_focus,
            )
        )
        self.apply(
            transition_defect(
                preview.defect_id,
                "investigating",
                repo=self.fixture.repo,
                timestamp=EVIDENCE_AT,
                source="synthetic-lifecycle",
                author_class="test",
            )
        )
        append_evidence(
            preview.defect_id,
            {
                "timestamp": ELIMINATED_AT,
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
                preview.defect_id,
                "ready",
                repo=self.fixture.repo,
                timestamp=READY_AT,
                source="synthetic-ready-check",
                author_class="test",
            )
        )
        ready_focus = {
            **triaged_focus,
            "next_action": "implement revision-aware cache keys in src/cache.py",
        }
        self.apply(
            transition_defect(
                preview.defect_id,
                "ready",
                repo=self.fixture.repo,
                timestamp=FIXING_AT,
                source="synthetic-ready-focus",
                author_class="test",
                current_focus=ready_focus,
            )
        )
        record = read_defect(self.fixture.repo, preview.defect_id).record
        self.assertEqual(record["lifecycle"], "ready")
        self.assertEqual(record["current_focus"], ready_focus)
        self.assertEqual(
            [event["kind"] for event in record["events"] if event["kind"] == "focus_updated"],
            ["focus_updated", "focus_updated"],
        )

    def test_resolution_requires_meaningful_verification_and_rejects_forgery(self):
        preview = self.create()
        self.advance_to_ready(preview.defect_id)
        for target, timestamp in (
            ("fixing", FIXING_AT),
            ("verifying", VERIFYING_AT),
        ):
            self.apply(
                transition_defect(
                    preview.defect_id,
                    target,
                    repo=self.fixture.repo,
                    timestamp=timestamp,
                    source="synthetic-fix",
                    author_class="test",
                )
            )
        resolution = {
            "root_cause": "the serializer omitted the fixture revision",
            "fix": "include the revision in the cache key",
            "verification": {
                "automated": ["focused reproducer and cache suite passed"],
                "human": ["fixture maintainer confirmed the report is resolved"],
            },
            "oracle_type": "specified",
            "files_changed": ["src/cache.py", "tests/test_cache.py"],
        }
        cases = (
            (
                "automated",
                {
                    "automated": [""],
                    "human": resolution["verification"]["human"],
                },
            ),
            (
                "automated",
                {
                    "automated": [
                        "focused reproducer passed",
                        " \t ",
                    ],
                    "human": resolution["verification"]["human"],
                },
            ),
            (
                "human",
                {
                    "automated": resolution["verification"]["automated"],
                    "human": [""],
                },
            ),
            (
                "human",
                {
                    "automated": resolution["verification"]["automated"],
                    "human": [
                        "fixture maintainer confirmed resolution",
                        "\n",
                    ],
                },
            ),
        )
        for field, verification in cases:
            with self.subTest(field=field, verification=verification):
                candidate = {**resolution, "verification": verification}
                with self.assertRaises(ValueError) as raised:
                    transition_defect(
                        preview.defect_id,
                        "resolved",
                        repo=self.fixture.repo,
                        timestamp=RESOLVED_AT,
                        source="synthetic-resolution",
                        author_class="test",
                        resolution=candidate,
                    )
                self.assertEqual(
                    str(raised.exception),
                    f"resolution_verification_incomplete:{field}",
                )
                self.assertEqual(
                    read_defect(
                        self.fixture.repo,
                        preview.defect_id,
                    ).record["lifecycle"],
                    "verifying",
                )

        self.apply(
            transition_defect(
                preview.defect_id,
                "resolved",
                repo=self.fixture.repo,
                timestamp=RESOLVED_AT,
                source="synthetic-resolution",
                author_class="test",
                resolution=resolution,
            )
        )
        tampered = json.loads(
            json.dumps(read_defect(self.fixture.repo, preview.defect_id).record)
        )
        final_event = tampered["events"][-1]
        forged_resolution = final_event["payload"]["resolution"]
        forged_resolution["verification"]["automated"] = [" \t "]
        final_event["event_digest"] = defect_event_digest(final_event)
        tampered["resolution"] = forged_resolution
        tampered["history_head"]["digest"] = final_event["event_digest"]
        with self.assertRaises(ValueError) as raised:
            validate_defect_record(tampered)
        self.assertEqual(
            str(raised.exception),
            f"defect_event_tampered:{final_event['event_id']}",
        )

    def test_duplicate_waived_wontfix_recurrence_and_supersession_relations_validate(self):
        transitions = (
            ("duplicate", "duplicates", "DEF-other"),
            ("waived", "waives", "WAIVER-001"),
            ("wont_fix", "waives", "DECISION-WONT-FIX-001"),
            ("superseded", "supersedes", "DEF-successor"),
        )
        for index, (target, relation_name, related_id) in enumerate(transitions):
            with self.subTest(target=target):
                fixture = FixtureFactory.create(f"defect-relation-{index}")
                try:
                    preview = create_defect(
                        complete_input(fixture.repository_key),
                        repo=fixture.repo,
                    )
                    self.apply(preview)
                    relation = {
                        "schema": "doc-warden/relation/v2",
                        "relation": relation_name,
                        "source_id": preview.defect_id,
                        "source_version": None,
                        "target": {
                            "kind": "defect" if target != "waived" else "decision",
                            "id": related_id,
                            "version": None,
                        },
                        "authority": "observed",
                        "provenance": [{"source": "synthetic-relation"}],
                        "observed_revision": "c" * 40,
                        "observed_at": TRIAGED,
                        "lifecycle": "active",
                    }
                    with self.assertRaisesRegex(
                        ValueError,
                        f"defect_relation_required:{relation_name}",
                    ):
                        transition_defect(
                            preview.defect_id,
                            target,
                            repo=fixture.repo,
                            timestamp=TRIAGED,
                            source="synthetic-relation",
                            author_class="test",
                        )
                    transition = transition_defect(
                        preview.defect_id,
                        target,
                        repo=fixture.repo,
                        timestamp=TRIAGED,
                        source="synthetic-relation",
                        author_class="test",
                        relation=relation,
                    )
                    confirmation = (
                        confirmation_for(transition.transaction)
                        if transition.transaction.consequential
                        else None
                    )
                    apply_transaction(transition.transaction, confirmation)
                    record = read_defect(fixture.repo, preview.defect_id).record
                    self.assertEqual(record["lifecycle"], target)
                    self.assertEqual(record["relations"][-1], relation)
                    with self.assertRaisesRegex(ValueError, "defect_terminal"):
                        transition_defect(
                            preview.defect_id,
                            target,
                            repo=fixture.repo,
                            timestamp=INVESTIGATING,
                            source="synthetic-terminal-update",
                            author_class="test",
                            current_focus=record["current_focus"],
                        )
                finally:
                    fixture.cleanup()

    def test_reproducer_resolution_and_recurrence_preserve_prior_history(self):
        preview = self.create()
        self.advance_to_ready(preview.defect_id)
        for target, timestamp in (
            ("fixing", FIXING_AT),
            ("verifying", VERIFYING_AT),
        ):
            self.apply(
                transition_defect(
                    preview.defect_id,
                    target,
                    repo=self.fixture.repo,
                    timestamp=timestamp,
                    source="synthetic-fix",
                    author_class="test",
                )
            )
        with self.assertRaisesRegex(
            ValueError,
            "resolution_verification_incomplete:automated,human",
        ):
            transition_defect(
                preview.defect_id,
                "resolved",
                repo=self.fixture.repo,
                timestamp=RESOLVED_AT,
                source="synthetic-resolution",
                author_class="test",
                resolution={
                    "root_cause": "the serializer omitted the fixture revision",
                    "fix": "include the revision in the cache key",
                    "verification": {"automated": [], "human": []},
                    "oracle_type": "specified",
                    "files_changed": ["src/cache.py", "tests/test_cache.py"],
                },
            )
        resolved = {
            "root_cause": "the serializer omitted the fixture revision",
            "fix": "include the revision in the cache key",
            "verification": {
                "automated": ["focused reproducer and cache suite passed"],
                "human": ["fixture maintainer confirmed the report is resolved"],
            },
            "oracle_type": "specified",
            "files_changed": ["src/cache.py", "tests/test_cache.py"],
        }
        self.apply(
            transition_defect(
                preview.defect_id,
                "resolved",
                repo=self.fixture.repo,
                timestamp=RESOLVED_AT,
                source="synthetic-resolution",
                author_class="test",
                resolution=resolved,
            )
        )
        before = read_defect(self.fixture.repo, preview.defect_id).record
        symptoms = list(before["immutable_symptoms"])
        event_ids = [event["event_id"] for event in before["events"]]
        recurrence = {
            "schema": "doc-warden/relation/v2",
            "relation": "recurs_as",
            "source_id": preview.defect_id,
            "source_version": None,
            "target": {"kind": "defect", "id": preview.defect_id, "version": None},
            "authority": "observed",
            "provenance": [{"source": "synthetic-reproducer"}],
            "observed_revision": "d" * 40,
            "observed_at": RECURRED_AT,
            "lifecycle": "active",
        }
        self.apply(
            transition_defect(
                preview.defect_id,
                "recurred",
                repo=self.fixture.repo,
                timestamp=RECURRED_AT,
                source="synthetic-reproducer",
                author_class="test",
                relation=recurrence,
                current_focus={
                    "hypothesis": "a second serializer path still omits the revision",
                    "test": "run the reproducer through the fallback serializer",
                    "expecting": "failure isolates the fallback path",
                    "next_action": "run the fallback serializer reproducer",
                    "bug_class": "bohrbug",
                    "reasoning_checkpoint": None,
                    "tdd_checkpoint": None,
                },
            )
        )
        self.apply(
            transition_defect(
                preview.defect_id,
                "investigating",
                repo=self.fixture.repo,
                timestamp=REOPENED_AT,
                source="synthetic-reproducer",
                author_class="test",
            )
        )
        reopened = read_defect(self.fixture.repo, preview.defect_id).record
        self.assertEqual(reopened["lifecycle"], "investigating")
        self.assertEqual(reopened["immutable_symptoms"], symptoms)
        self.assertEqual(
            [event["event_id"] for event in reopened["events"][: len(event_ids)]],
            event_ids,
        )
        self.assertEqual(reopened["resolution"], resolved)
        self.assertEqual(reopened["relations"][-1], recurrence)

    def test_real_wrapper_reads_fixture_backlog_created_by_defect_gateway(self):
        preview = self.create()
        machine = tempfile.TemporaryDirectory(prefix="doc-warden-defect-wrapper-")
        try:
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "_ops/bin/doc-warden.sh"),
                    "view",
                    "repo",
                    "--repo",
                    str(self.fixture.repo),
                    "--json",
                ],
                check=True,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "XDG_STATE_HOME": str(Path(machine.name) / "state"),
                },
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["items"][0]["kind"], "defect")
            self.assertEqual(
                payload["items"][0]["active_versions"],
                {preview.defect_id: 1},
            )
            self.assertEqual(payload["items"][0]["required_artifacts"], [preview.defect_id])
        finally:
            machine.cleanup()


if __name__ == "__main__":
    unittest.main()
