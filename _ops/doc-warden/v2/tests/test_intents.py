import json
import unittest
import uuid
from pathlib import Path

from doc_warden.intents import INTENT_SPECS, map_intent
from fixture_factory import ROOT


class IntentTests(unittest.TestCase):
    def context(self, **overrides):
        value = {
            "repository_key": str(uuid.uuid4()),
            "operation_id": str(uuid.uuid4()),
            "action_digest": "sha256:" + "a" * 64,
        }
        value.update(overrides)
        return value

    def test_every_intent_has_one_cli_equivalent(self):
        expected = {
            "view_repo",
            "view_fleet",
            "draft_prd",
            "draft_spec",
            "draft_plan",
            "log_defect",
            "update_authority",
            "prioritize",
            "sequence",
            "reconcile_preview",
            "apply_reconciliation",
            "doctor_repo",
            "doctor_fleet",
            "run",
            "pause",
            "resume",
            "verify",
        }
        self.assertEqual(set(INTENT_SPECS), expected)
        cli_equivalents = []
        for intent, spec in INTENT_SPECS.items():
            with self.subTest(intent=intent):
                self.assertEqual(spec.intent, intent)
                self.assertTrue(spec.cli_equivalent.startswith("bash _ops/bin/doc-warden.sh "))
                cli_equivalents.append(spec.cli_equivalent)
                proposal = map_intent(spec.example, self.context())
                self.assertEqual(proposal.status, "proposed")
                self.assertEqual(proposal.intent, intent)
                self.assertEqual(proposal.cli_equivalent, spec.cli_equivalent)
        self.assertEqual(len(cli_equivalents), len(set(cli_equivalents)))

    def test_router_proposes_but_never_authorizes(self):
        proposal = map_intent(
            "Draft the PRD.",
            self.context(authorized=True, confirmed=True),
        )
        self.assertTrue(proposal.proposal_only)
        self.assertFalse(proposal.authorized)
        self.assertEqual(proposal.repository_writes, ())
        self.assertNotEqual(proposal.native_dispatch, "execute")

    def test_consequential_intent_requires_operation_bound_explicit_confirmation(self):
        context = self.context()
        proposal = map_intent("Apply the safe repairs.", context)
        self.assertTrue(proposal.consent_required)
        self.assertEqual(
            proposal.confirmation_binding,
            {
                "operation_id": context["operation_id"],
                "action_digest": context["action_digest"],
            },
        )
        self.assertFalse(proposal.authorized)

        preflight = map_intent("Draft the plan.", {"repository_key": context["repository_key"]})
        self.assertTrue(preflight.consent_required)
        self.assertIsNone(preflight.confirmation_binding)
        self.assertEqual(preflight.next_action, "run_preview")

    def test_read_only_intent_does_not_nag(self):
        for utterance in (
            "What are we working on?",
            "Show everything across repos.",
            "What drifted?",
            "Is governance healthy?",
        ):
            with self.subTest(utterance=utterance):
                proposal = map_intent(utterance, self.context())
                self.assertEqual(proposal.consequence, "read_only")
                self.assertFalse(proposal.consent_required)
                self.assertIsNone(proposal.confirmation_binding)
                self.assertNotIn("confirm", proposal.message.lower())

    def test_plain_language_failure_names_checked_uncertain_and_next_action(self):
        proposal = map_intent("Do the surprising thing.", self.context())
        self.assertEqual(proposal.status, "unmatched")
        self.assertIsNone(proposal.intent)
        self.assertIsNone(proposal.cli_equivalent)
        copy = proposal.message.lower()
        self.assertIn("checked", copy)
        self.assertIn("uncertain", copy)
        self.assertIn("next action", copy)

    def test_different_consequences_are_reported_as_ambiguous(self):
        proposal = map_intent(
            "Show everything across repos and apply the safe repairs.",
            self.context(),
        )
        self.assertEqual(proposal.status, "ambiguous")
        self.assertIsNone(proposal.intent)
        self.assertIsNone(proposal.cli_equivalent)
        self.assertEqual(set(proposal.candidates), {"view_fleet", "apply_reconciliation"})
        self.assertIn("different consequences", proposal.message.lower())
        self.assertFalse(proposal.authorized)

    def test_execution_family_is_proposal_only_without_native_execution(self):
        for utterance, expected in (
            ("Start the work.", "run"),
            ("Pause here.", "pause"),
            ("Resume the work.", "resume"),
            ("Verify this.", "verify"),
        ):
            with self.subTest(intent=expected):
                proposal = map_intent(utterance, self.context())
                self.assertEqual(proposal.intent, expected)
                self.assertEqual(proposal.native_dispatch, "operator_invoke_required")
                self.assertTrue(proposal.proposal_only)
                self.assertFalse(proposal.authorized)
                self.assertIsNone(proposal.confirmation_binding)
                self.assertEqual(
                    proposal.next_action,
                    "await_authorized_execution_surface",
                )
                self.assertIn("intentionally unavailable", proposal.message)
                self.assertEqual(proposal.repository_writes, ())

    def test_reconcile_preview_does_not_match_apply_style_phrasing(self):
        # Regression: apply-style utterances using "reconcile" as the verb must
        # not route to read-only reconcile_preview with consent_required=False.
        # "reconcile the safe repairs" mirrors "apply the safe repairs" semantically;
        # the optional target in the prior pattern let it slip through as preview.
        bug = map_intent("reconcile the safe repairs", self.context())
        self.assertEqual(bug.status, "unmatched", "apply-style phrasing must not route to reconcile_preview")
        self.assertIsNone(bug.intent)
        self.assertFalse(bug.consent_required)  # unmatched, not a consent bypass

        # Adjacent boundary: preview phrasing with explicit scope must still route correctly.
        for utterance, note in (
            ("reconcile repo", "bare target"),
            ("reconcile the repo", "the + target"),
            ("reconcile fleet", "fleet bare"),
            ("reconcile the fleet", "the + fleet"),
            ("reconcile the repository", "full word target"),
        ):
            with self.subTest(utterance=utterance, note=note):
                proposal = map_intent(utterance, self.context())
                self.assertEqual(proposal.status, "proposed", f"{utterance!r} should route to reconcile_preview")
                self.assertEqual(proposal.intent, "reconcile_preview")
                self.assertEqual(proposal.consequence, "read_only")
                self.assertFalse(proposal.consent_required)

        # Apply route must still reach apply_reconciliation with correct consent semantics.
        ctx = self.context()
        apply_proposal = map_intent("apply the safe repairs", ctx)
        self.assertEqual(apply_proposal.status, "proposed")
        self.assertEqual(apply_proposal.intent, "apply_reconciliation")
        self.assertTrue(apply_proposal.consent_required)
        self.assertEqual(
            apply_proposal.confirmation_binding,
            {"operation_id": ctx["operation_id"], "action_digest": ctx["action_digest"]},
        )

    def test_closed_intent_schema_covers_the_accepted_operator_verbs(self):
        schema = json.loads(
            (
                ROOT / "_ops/doc-warden/schemas/v2/intent.schema.json"
            ).read_text(encoding="utf-8")
        )
        operations = set(schema["properties"]["operation"]["enum"])
        self.assertTrue(
            {
                "view",
                "draft",
                "log",
                "update",
                "prioritize",
                "sequence",
                "apply",
                "doctor",
                "reconcile",
                "run",
                "pause",
                "resume",
                "verify",
            }.issubset(operations)
        )

    def test_thin_skill_documents_examples_equivalents_and_router_boundary(self):
        skill = (ROOT / "_ops/skills/doc-warden/SKILL.md").read_text(
            encoding="utf-8"
        )
        for text in (
            "What are we working on?",
            "bash _ops/bin/doc-warden.sh view repo",
            "Apply the safe repairs.",
            "operation-bound",
            "proposal",
            "checked",
            "uncertain",
            "next action",
        ):
            with self.subTest(text=text):
                self.assertIn(text, skill)


if __name__ == "__main__":
    unittest.main()
