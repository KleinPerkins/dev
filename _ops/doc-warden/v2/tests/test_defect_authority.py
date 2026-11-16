"""Synthetic central-source binding regressions for the typed defect lifecycle."""
import json
import os
from pathlib import Path
import shutil
import unittest
import uuid

from doc_warden.artifacts import _bindings
from doc_warden.canonical import canonical_json, digest_ref
from doc_warden.defects import (
    append_evidence, create_defect, eliminate_hypothesis, promote_defect,
    read_defect, reevaluate_exemption, transition_defect,
)
from doc_warden.operation_store import load_preview, store_preview
from doc_warden.transactions import apply_transaction, confirmation_for
import test_authoring_binding as binding_fixture
from test_defects import complete_input


class DefectAuthorityTests(unittest.TestCase):
    def setUp(self):
        binding_fixture.AuthoringBindingTests.setUp(self)
        self.authority = self.authority.resolve()
        template = self.authority / "_ops/doc-warden/v2/templates/defect.md"
        template.parent.mkdir(parents=True)
        template.write_bytes((binding_fixture.ROOT / "_ops/doc-warden/v2/templates/defect.md").read_bytes())
        shutil.rmtree(self.repo / "_ops/doc-warden")
        self.inputs = complete_input(self.fixture.repository_key)

    def create(self, operation=None, central=True):
        return create_defect(self.inputs, repo=self.repo, operation_id=operation or str(uuid.uuid4()),
                             binding_root=self.authority if central else None)

    def apply(self, preview):
        transaction = preview.transaction
        return apply_transaction(transaction, confirmation_for(transaction) if transaction.consequential else None)

    def snapshot(self):
        return {str(path.relative_to(self.repo)): path.read_bytes()
                for path in self.repo.rglob("*") if path.is_file() and ".git" not in path.parts}

    def assert_receipt(self, receipt):
        for key, value in _bindings(self.authority).items():
            if key != "template_digests":
                self.assertEqual(receipt["bindings"][key], value)
        self.assertGreater(len(receipt["observed_input_digests"]), 5)

    def evidence(self, defect_id, operation):
        return append_evidence(defect_id, {
            "timestamp": "2026-08-31T09:40:00+00:00", "source": "synthetic", "author_class": "test",
            "checked": "central bindings", "found": "exact source digests", "implication": "safe preview"},
            repo=self.repo, operation_id=operation, binding_root=self.authority)

    def transition(self, defect_id, target, operation, **kwargs):
        return transition_defect(defect_id, target, repo=self.repo, timestamp="2026-08-31T09:40:00+00:00",
                                 source="synthetic", author_class="test", operation_id=operation,
                                 binding_root=self.authority, **kwargs)

    def replay_and_recover(self, call):
        result = call()
        receipt = self.apply(result) if hasattr(result, "transaction") else getattr(result, "receipt", result)
        self.assert_receipt(receipt)
        before = self.snapshot()
        repeated = call()
        self.assertEqual(getattr(repeated, "receipt", repeated), receipt)
        self.assertEqual(self.snapshot(), before)
        path = self.repo / "_ops/doc-warden/state/v2/receipts" / (receipt["operation_id"] + ".json")
        path.unlink()
        recovered = call()
        self.assertEqual(getattr(recovered, "receipt", recovered), receipt)
        self.assertEqual(self.snapshot(), before)
        return receipt

    def test_creation_binds_central_source_without_consumer_engine_copy(self):
        index = (self.repo / ".git/index").read_bytes()
        profile = self.profile.read_bytes()
        preview = create_defect(self.inputs, repo=self.repo,
                                binding_root=self.authority, operation_id=str(uuid.uuid4()))
        for name in ("policy_digest", "schema_digest", "trigger_catalog_digest",
                     "gsd_pin_digest", "approved_plan_digest"):
            self.assertEqual(preview.transaction.bindings[name], _bindings(self.authority)[name])
            self.assertNotEqual(preview.transaction.bindings[name], "sha256:" + "0" * 64)
        self.assertEqual(preview.transaction.bindings["template_digests"]["defect.md"],
                         digest_ref((self.authority / "_ops/doc-warden/v2/templates/defect.md").read_bytes()))
        self.assertGreater(len(preview.transaction.observed_inputs), 5)
        self.assertFalse((self.repo / "_ops/doc-warden").exists())
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)
        self.assertEqual(self.profile.read_bytes(), profile)

    def test_every_lifecycle_family_replays_and_recovers_exact_receipt(self):
        self.inputs["exemption"]["conditions"][3] = False
        operation = str(uuid.uuid4())
        initial = self.create(operation)
        defect_id = initial.defect_id
        creation = self.replay_and_recover(lambda: self.create(operation))
        evidence_op = str(uuid.uuid4())
        evidence = self.replay_and_recover(lambda: self.evidence(defect_id, evidence_op))
        for target in ("triaged", "investigating"):
            op = str(uuid.uuid4())
            self.replay_and_recover(lambda: self.transition(defect_id, target, op))
        op = str(uuid.uuid4())
        assessment = {"timestamp": "2026-08-31T09:40:00+00:00", "source": "synthetic",
                      "author_class": "test", "conditions": [True] * 5}
        self.replay_and_recover(lambda: reevaluate_exemption(defect_id, assessment, repo=self.repo,
                                                            operation_id=op, binding_root=self.authority))
        op = str(uuid.uuid4())
        elimination = {"hypothesis_id": "HYP-002", "timestamp": "2026-08-31T09:40:00+00:00",
                       "source": "synthetic", "author_class": "test", "evidence": "alternative ruled out"}
        self.replay_and_recover(lambda: eliminate_hypothesis(defect_id, elimination, repo=self.repo,
                                                            operation_id=op, binding_root=self.authority))
        for target in ("ready", "fixing", "verifying"):
            op = str(uuid.uuid4())
            self.replay_and_recover(lambda: self.transition(defect_id, target, op))
        self.assertEqual(self.create(operation), creation)
        self.assertEqual(self.evidence(defect_id, evidence_op), evidence)

    def test_consequential_transition_recovery_preserves_prior_confirmation(self):
        preview = self.create(); self.apply(preview)
        relation = {"schema": "doc-warden/relation/v2", "relation": "waives",
                    "source_id": preview.defect_id, "source_version": None,
                    "target": {"kind": "decision", "id": "ADR-synthetic", "version": None},
                    "authority": "observed", "provenance": [{"source": "synthetic"}],
                    "observed_revision": "a" * 40, "observed_at": "2026-08-31T09:40:00+00:00",
                    "lifecycle": "active"}
        op = str(uuid.uuid4())
        receipt = self.replay_and_recover(lambda: self.transition(preview.defect_id, "waived", op, relation=relation))
        self.assertIsNotNone(receipt["confirmation_digest"])

    def test_promotion_replays_and_recovers(self):
        preview = self.create(); self.apply(preview)
        scope = dict(self.inputs["scope"], new_behavior=True)
        op = str(uuid.uuid4())
        self.replay_and_recover(lambda: promote_defect(preview.defect_id, repo=self.repo,
            timestamp="2026-08-31T09:40:00+00:00", source="synthetic", author_class="test",
            scope=scope, operation_id=op, binding_root=self.authority))

    def test_each_observed_file_drift_refuses_before_any_write(self):
        preview = self.create()
        for observed in preview.transaction.observed_inputs:
            path = Path(observed.path)
            if not path.is_file():
                continue
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                before = self.snapshot()
                try:
                    with self.assertRaises(ValueError): self.apply(preview)
                    self.assertEqual(self.snapshot(), before)
                finally:
                    path.write_bytes(original)

    def test_schema_membership_add_remove_rename_refuses(self):
        directory = self.authority / "_ops/doc-warden/schemas/v2"
        original_path = next(directory.glob("*.schema.json"))
        original = original_path.read_bytes()
        extra = directory / "synthetic-extra.schema.json"
        for mode in ("add", "remove", "rename"):
            with self.subTest(mode=mode):
                preview = self.create()
                if mode == "add": extra.write_bytes(b"{}\n")
                elif mode == "remove": original_path.unlink()
                else: original_path.rename(extra)
                before = self.snapshot()
                try:
                    with self.assertRaises(ValueError): self.apply(preview)
                    self.assertEqual(self.snapshot(), before)
                finally:
                    if extra.exists(): extra.unlink()
                    original_path.write_bytes(original)

    def test_invalid_profiles_missing_authority_and_special_inputs_refuse(self):
        original = self.profile.read_bytes()
        for field, value in (("enabled", False), ("gsd_pin_digest", "sha256:" + "0" * 64),
                             ("gsd_interface_digest", "sha256:" + "0" * 64)):
            self.profile.write_bytes(canonical_json(dict(json.loads(original), **{field: value})))
            before = self.snapshot()
            with self.assertRaises(ValueError): self.create()
            self.assertEqual(self.snapshot(), before)
        self.profile.write_bytes(original)
        paths = [self.profile, self.pin.resolve(), self.interface.resolve(),
                 self.authority / "_ops/doc-warden/POLICY.md",
                 self.authority / "_ops/doc-warden/triggers.v2.json",
                 self.authority / "_ops/plans/doc-warden-execution-plan-v2.md",
                 self.authority / "_ops/doc-warden/v2/templates/defect.md",
                 next((self.authority / "_ops/doc-warden/schemas/v2").glob("*.schema.json"))]
        for path in paths:
            content = path.read_bytes()
            for mode in ("missing", "symlink", "special"):
                # Selection binds the offered schema set, not a hard-coded version.
                # Removing a member AFTER preview is covered by the drift test.
                if mode == "missing" and path.name.endswith(".schema.json"):
                    continue
                with self.subTest(path=path.name, mode=mode):
                    path.unlink()
                    if mode == "symlink": path.symlink_to(self.state / "missing-synthetic")
                    if mode == "special": os.mkfifo(path)
                    try:
                        with self.assertRaises((ValueError, OSError)): self.create()
                    finally:
                        if path.exists() or path.is_symlink(): path.unlink()
                        path.write_bytes(content)
        directory = self.authority / "_ops/doc-warden/schemas/v2"
        moved = directory.with_name("v2-saved")
        directory.rename(moved)
        try:
            with self.assertRaises(ValueError): self.create()
            directory.mkdir()
            with self.assertRaises(ValueError): self.create()
        finally:
            if directory.exists(): directory.rmdir()
            moved.rename(directory)

    def test_symlinked_authority_root_or_ancestor_refuses(self):
        for path in (self.authority, self.authority / "_ops/doc-warden/schemas",
                     self.authority / "_ops/doc-warden/runtime", self.repo / ".planning"):
            with self.subTest(path=path.name):
                moved = path.with_name(path.name + "-real")
                path.rename(moved); path.symlink_to(moved, target_is_directory=True)
                try:
                    with self.assertRaises(ValueError): self.create()
                finally:
                    path.unlink(); moved.rename(path)

    def test_changed_authority_profile_or_source_root_refuses_receipt_replay(self):
        op = str(uuid.uuid4()); preview = self.create(op); self.apply(preview)
        for path in (self.profile, self.authority / "_ops/doc-warden/POLICY.md",
                     self.authority / "_ops/doc-warden/v2/templates/defect.md"):
            original = path.read_bytes(); path.write_bytes(original + b"\n")
            before = self.snapshot()
            try:
                with self.assertRaises(ValueError): self.create(op)
                self.assertEqual(self.snapshot(), before)
            finally: path.write_bytes(original)
        other = self.authority.with_name("identical-other-authority")
        shutil.copytree(self.authority, other)
        with self.assertRaises(ValueError):
            create_defect(self.inputs, repo=self.repo, operation_id=op, binding_root=other)
        with self.assertRaises(ValueError): self.create(op, central=False)

    def test_local_history_is_unchanged_and_cannot_be_relabelled_central(self):
        op = str(uuid.uuid4()); receipt = self.apply(self.create(op, central=False))
        before = self.snapshot()
        self.assertEqual(self.create(op, central=False), receipt)
        with self.assertRaises(ValueError): self.create(op)
        self.assertEqual(self.snapshot(), before)

    def test_missing_or_conflicting_terminal_event_refuses_recovery(self):
        op = str(uuid.uuid4()); receipt = self.apply(self.create(op))
        receipt_path = self.repo / "_ops/doc-warden/state/v2/receipts" / (op + ".json")
        event_path = self.repo / "_ops/doc-warden/state/v2/events" / (receipt["event_id"] + ".json")
        original = event_path.read_bytes(); receipt_path.unlink(); event_path.unlink()
        before = self.snapshot()
        with self.assertRaises(ValueError): self.create(op)
        self.assertEqual(self.snapshot(), before)
        event = json.loads(original); event["action_digest"] = "sha256:" + "0" * 64
        event_path.write_bytes(canonical_json(event)); before = self.snapshot()
        with self.assertRaises(ValueError): self.create(op)
        self.assertEqual(self.snapshot(), before)

    def test_changed_authority_refuses_missing_receipt_recovery(self):
        op = str(uuid.uuid4()); receipt = self.apply(self.create(op))
        path = self.repo / "_ops/doc-warden/state/v2/receipts" / (op + ".json")
        path.unlink()
        policy = self.authority / "_ops/doc-warden/POLICY.md"
        policy.write_bytes(policy.read_bytes() + b"\n")
        before = self.snapshot()
        with self.assertRaises(ValueError): self.create(op)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(path.exists())

    def test_stored_preview_preserves_observations_and_drift_refusal(self):
        preview = self.create(); store_preview(preview.transaction)
        loaded = load_preview(preview.transaction.operation_id, preview.transaction.action_digest)
        self.assertEqual(loaded.observed_inputs, preview.transaction.observed_inputs)
        template = self.authority / "_ops/doc-warden/v2/templates/defect.md"
        template.write_bytes(template.read_bytes() + b"\n")
        before = self.snapshot()
        with self.assertRaises(ValueError): apply_transaction(loaded, None)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
