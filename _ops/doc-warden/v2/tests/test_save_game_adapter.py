import io
import json
import os
import subprocess
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from doc_warden.canonical import canonical_json
from doc_warden.cli import main
from doc_warden.continuity import apply_continuity, preview_continuity
from doc_warden.save_game_adapter import (
    CheckpointEvent,
    SaveGameAdapter,
    owner_checkpoint_digest,
    prepare_authoring_resume,
    prepare_checkpoint,
    validate_pointer,
)
from fixture_factory import FixtureFactory


REQUEST = "sha256:" + "1" * 64


class SaveGameAdapterTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create()
        self.addCleanup(self.fixture.cleanup)
        self.root = self.fixture.repo.resolve()
        work = tempfile.TemporaryDirectory(prefix="dw-continuity-state-")
        self.addCleanup(work.cleanup)
        self.staging = Path(work.name)
        env = patch.dict(os.environ, {"XDG_STATE_HOME": str(self.staging / "state")})
        env.start()
        self.addCleanup(env.stop)
        self.state = {
            "schema": "doc-warden/authoring-state/v2",
            "repository_key": self.fixture.repository_key,
            "operation_id": str(uuid.uuid4()),
            "active_artifact_id": None,
            "active_plan_id": None,
            "lifecycle": "planned",
            "next_action_code": "author",
            "blocker_ids": [],
            "source_revision": subprocess.check_output(
                ["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True
            ).strip(),
            "save_game_pointer": None,
        }
        self.event = CheckpointEvent(self.state["operation_id"], (), "review", authority_pointers=("README.md",))
        self.event_input = {
            "operation_id": self.event.operation_id, "artifact_ids": [], "blocker_ids": [],
            "next_action_code": "review", "authority_pointers": ["README.md"],
        }
        self.calls = []

    def pointer(self, event, status="created", checkpoint="chk-current", digest="sha256:" + "b" * 64):
        return {
            "schema": "doc-warden/save-game-pointer/v1",
            "checkpoint_id": checkpoint, "checkpoint_digest": digest, "status": status,
            "artifact_ids": list(event.artifact_ids), "next_action_code": event.next_action_code,
            "blocker_ids": list(event.blocker_ids), "authority_pointers": list(event.authority_pointers),
        }

    def success(self, verb, event):
        self.calls.append(verb)
        return self.pointer(event, "created" if verb == "checkpoint" else "reconciled")

    def preview(self, intent="checkpoint", state=None, operation=None):
        return preview_continuity(self.root, self.state if state is None else state, self.event_input,
                                  intent=intent, operation_id=operation or str(uuid.uuid4()))

    @staticmethod
    def consent(preview):
        now = datetime.now(timezone.utc)
        return {
            "schema": "doc-warden/consent-envelope/v1", "operation_id": preview["operation_id"],
            "repository_key": preview["repository_key"], "canonical_root": preview["canonical_root"],
            "source_revision": preview["source_revision"], "action_digest": preview["action_digest"],
            "consequence_class": "lifecycle", "choice": "apply", "nonce": str(uuid.uuid4()),
            "issued_at": now.isoformat(), "expires_at": (now + timedelta(minutes=1)).isoformat(),
        }

    def apply(self, preview, runner=None):
        adapter = SaveGameAdapter(root=self.root, runner=runner or self.success)
        return apply_continuity(preview["operation_id"], preview["action_digest"], self.consent(preview),
                                adapter=adapter)

    def test_checkpoint_is_preview_only_until_exact_consent_and_applies_once(self):
        preview = self.preview()
        self.assertEqual(self.calls, [])
        with self.assertRaisesRegex(ValueError, "fresh_exact_consent_required"):
            apply_continuity(preview["operation_id"], preview["action_digest"], None,
                             adapter=SaveGameAdapter(root=self.root, runner=self.success))
        self.assertEqual(self.calls, [])
        first = self.apply(preview)
        again = self.apply(preview)
        self.assertEqual(again, first)
        self.assertEqual(first["state"]["save_game_pointer"], self.pointer(self.event))
        self.assertEqual(self.calls, ["checkpoint"])
        self.assertEqual(first["state"]["next_action_code"], "review")

    def test_same_operation_cannot_be_reused_for_changed_intent(self):
        first = self.preview()
        with self.assertRaisesRegex(ValueError, "operation_replay_mismatch"):
            self.preview("handoff", operation=first["operation_id"])

    def test_handoff_and_continuity_pause_advance_only_on_success(self):
        first = self.apply(self.preview("handoff"))["state"]
        self.assertEqual(first["lifecycle"], "waiting")
        second = self.apply(self.preview("pause-with-continuity", state=first))["state"]
        self.assertEqual(second["lifecycle"], "paused")
        resumed = self.apply(self.preview("resume-authoring", state=second))["state"]
        self.assertEqual(resumed["lifecycle"], "planned")
        self.assertEqual(resumed["save_game_pointer"]["status"], "reconciled")
        self.assertEqual(self.calls, ["checkpoint", "checkpoint", "reconcile"])

    def test_failed_resume_keeps_previous_state_byte_for_byte(self):
        state = self.apply(self.preview("pause-with-continuity"))["state"]
        preview = self.preview("resume-authoring", state=state)
        record, = (self.staging / "state/doc-warden/continuity").rglob("*.json")
        prior = record.read_bytes()
        for runner, code in (
            (lambda _verb, _event: (_ for _ in ()).throw(ValueError("save_game_unavailable")), "save_game_unavailable"),
            (lambda _verb, event: self.pointer(event, "reconciled", checkpoint="chk-advanced"), "save_game_checkpoint_stale"),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, code):
                self.apply(preview, runner=runner)
            self.assertEqual(prior, record.read_bytes())
            self.assertEqual(state["lifecycle"], "paused")

    def test_missing_or_unqualified_provider_cannot_advance_checkpoint(self):
        adapter = SaveGameAdapter(home=self.staging / "empty", root=self.root)
        self.assertFalse(adapter.available())
        with self.assertRaisesRegex(ValueError, "^save_game_unavailable$"):
            prepare_checkpoint(self.root, self.state, self.event, adapter, request_digest=REQUEST)
        self.assertIsNone(self.state["save_game_pointer"])

    def test_resume_without_a_prior_checkpoint_fails_before_owner_call(self):
        with self.assertRaisesRegex(ValueError, "save_game_checkpoint_required"):
            prepare_authoring_resume(self.root, self.state, self.event,
                                     SaveGameAdapter(root=self.root, runner=self.success))
        self.assertEqual(self.calls, [])

    def test_changed_untracked_bytes_after_preview_fail_before_owner_call(self):
        path = self.root / "working.txt"
        path.write_bytes(b"before\n")
        preview = self.preview()
        path.write_bytes(b"after\n")
        with self.assertRaisesRegex(ValueError, "authoring_live_state_changed"):
            self.apply(preview)
        self.assertEqual(self.calls, [])

    def test_authority_edited_during_checkpoint_does_not_commit_doc_warden_state(self):
        def changing_provider(verb, event):
            (self.root / "README.md").write_text("changed input\n")
            return self.success(verb, event)

        preview = self.preview()
        with self.assertRaisesRegex(ValueError, "authoring_live_state_changed"):
            self.apply(preview, runner=changing_provider)
        self.assertEqual(list((self.staging / "state/doc-warden/continuity").rglob("*.json")), [])

    def test_privacy_and_wrong_repository_are_rejected(self):
        pointer = self.pointer(self.event)
        with self.assertRaisesRegex(ValueError, "not_closed"):
            validate_pointer(pointer | {"transcript": "synthetic-private-text"})
        for field, invalid in (("authority_pointers", "/private/journal.md"), ("artifact_ids", "payload"),
                               ("blocker_ids", "token=not-a-reference")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "save_game_pointer_value"):
                validate_pointer(pointer | {field: [invalid]})
        with self.assertRaisesRegex(ValueError, "authoring_repository_mismatch"):
            self.preview(state=self.state | {"repository_key": str(uuid.uuid4())})
        self.assertEqual(self.calls, [])

    def test_cli_preview_without_consent_never_invokes_owner(self):
        state_file = self.staging / "state.json"
        event_file = self.staging / "event.json"
        state_file.write_bytes(canonical_json(self.state))
        event_file.write_bytes(canonical_json(self.event_input))
        base = ["checkpoint", "--repo", str(self.root), "--state", str(state_file), "--event", str(event_file)]
        with redirect_stdout(io.StringIO()) as output, patch.object(SaveGameAdapter, "_command") as run:
            self.assertEqual(main(base), 1)
            run.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["code"], "continuity_preview_required")
        with redirect_stdout(io.StringIO()) as output, patch.object(SaveGameAdapter, "_command") as run:
            self.assertEqual(main(base + ["--operation-id", str(uuid.uuid4()), "--preview"]), 0)
            run.assert_not_called()
        self.assertTrue(json.loads(output.getvalue())["consent_required"])


class OwnerWireTests(unittest.TestCase):
    def setUp(self):
        self.adapter = SaveGameAdapter()
        self.event = CheckpointEvent(str(uuid.uuid4()), (), "review")
        self.scope = {"repo_key": "a" * 64, "clone_key": "b" * 64, "workstream_key": "c" * 64}
        repo_identity = {key: self.scope[key] for key in ("repo_key", "clone_key")}
        self.registration = repo_identity | {"adopted": True, "case": "configured", "registration": {
            "schema": "save-game-registration/v1", "enabled": True, **repo_identity,
        }}
        self.unknown = (1, {"schema": "save-game-reconcile-observation/v1", "status": "WORKSTREAM_UNAVAILABLE", **self.scope})
        self.checkpoint = {"schema": "save-game-checkpoint/v1", "active_state_digest": "f" * 64,
                           "active_state_generation": 1, "checkpoint_id": "chk-current",
                           "workstream_key": self.scope["workstream_key"],
                           "objective": "Doc-Warden authoring continuity"}
        self.match = (0, {"schema": "save-game-reconcile-observation/v1", "status": "MATCH", **self.scope,
                          "checkpoint": {"id": "chk-current", "generation": 1,
                                         "digest": owner_checkpoint_digest(self.checkpoint)}})
        self.receipt = {"schema": "save-game-flush-receipt/v1", "status": "SAVED", "reconciliation_required": False,
                        "checkpoint_id": "chk-current", "workstream_key": self.scope["workstream_key"],
                        "receipt_id": "rcpt-fixture", "created_at": "2026-01-01T00:00:00Z",
                        "saved": [], "omitted": [], "refused": [], "stale": [], "negative_claims": []}

    def checkpoint_call(self, replies):
        with patch.object(self.adapter, "executable", return_value=Path("/fixture/save-game")), patch.object(
            self.adapter, "_command", side_effect=replies,
        ) as command:
            value = self.adapter.checkpoint(self.event, request_digest=REQUEST)
        return value, command.call_args_list

    def test_saves_then_requires_matching_index_and_rechecks_observation(self):
        value, calls = self.checkpoint_call([(0, self.registration), self.unknown, (1, {"status": "NO_CHECKPOINT"}),
            (0, self.receipt), self.match, (0, self.checkpoint), self.match, (0, self.registration)])
        self.assertEqual(value["checkpoint_id"], "chk-current")
        self.assertEqual(value["status"], "created")
        self.assertTrue(all("--observe" in call.args for call in calls if call.args[1] == "reconcile"))
        self.assertNotIn("objective", value)

    def test_unadopted_save_cannot_be_converted_into_success_by_index(self):
        receipt = self.receipt | {"status": "SAVED_PRIVATE_UNADOPTED"}
        with self.assertRaisesRegex(ValueError, "save_game_saved_private_unadopted"):
            self.checkpoint_call([(0, self.registration), self.unknown, (1, {"status": "NO_CHECKPOINT"}), (0, receipt)])

    def test_no_delta_requires_the_exact_prior_checkpoint_for_this_request(self):
        receipt = (self.receipt | {"status": "NO_DURABLE_DELTA"}).copy()
        receipt.pop("checkpoint_id")
        replies = [(0, self.registration), self.match, (0, self.checkpoint), (0, receipt),
                   self.match, (0, self.checkpoint), self.match, (0, self.registration)]
        value, _ = self.checkpoint_call(replies)
        self.assertEqual(value["status"], "created")
        stale = self.checkpoint | {"checkpoint_id": "chk-other"}
        evidence = self.match[1] | {"checkpoint": self.match[1]["checkpoint"] |
                                    {"id": "chk-other", "digest": owner_checkpoint_digest(stale)}}
        with self.assertRaisesRegex(ValueError, "save_game_checkpoint_stale"):
            self.checkpoint_call([(0, self.registration), self.match, (0, self.checkpoint), (0, receipt),
                                  (0, evidence), (0, stale)])
