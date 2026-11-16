import subprocess
import unittest
import uuid

from doc_warden.save_game_adapter import (
    CheckpointEvent,
    SaveGameAdapter,
    prepare_authoring_resume,
    prepare_checkpoint,
    validate_pointer,
)
from fixture_factory import FixtureFactory


class SaveGameAdapterTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureFactory.create()
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
                ["git", "-C", str(self.fixture.repo), "rev-parse", "HEAD"], text=True
            ).strip(),
            "save_game_pointer": None,
        }
        self.event = CheckpointEvent(
            operation_id=self.state["operation_id"],
            artifact_ids=("PRD-example",),
            next_action_code="author",
            authority_pointers=("README.md",),
        )

    def tearDown(self):
        self.fixture.cleanup()

    def test_missing_save_game_degrades_without_blocking(self):
        adapter = SaveGameAdapter(home=self.fixture.repo / "missing-home")
        self.assertFalse(adapter.available())
        updated = prepare_checkpoint(self.fixture.repo, self.state, self.event, adapter)
        self.assertEqual(updated["save_game_pointer"]["status"], "unavailable")
        self.assertEqual(updated["next_action_code"], "author")

    def test_save_game_adapter_emits_only_closed_pointer_schema(self):
        pointer = {
            "schema": "doc-warden/save-game-pointer/v1",
            "checkpoint_id": "checkpoint-1",
            "checkpoint_digest": "sha256:" + "a" * 64,
            "status": "created",
            "artifact_ids": ["PRD-example"],
            "next_action_code": "review",
            "blocker_ids": [],
            "authority_pointers": ["README.md"],
        }
        self.assertEqual(validate_pointer(pointer), pointer)
        with self.assertRaisesRegex(ValueError, "not_closed"):
            validate_pointer(pointer | {"transcript": "forbidden"})

    def test_discovered_save_game_cli_is_invoked(self):
        home = self.fixture.repo / "home"
        script = home / ".cursor/skills/save-game/scripts/save-game.sh"
        marker = home / "invoked"
        script.parent.mkdir(parents=True)
        script.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> {marker}\n"
            "case \" $* \" in\n"
            "  *\" index \"*) printf '%s\\n' '{\"checkpoint_id\":\"checkpoint-1\"}' ;;\n"
            "  *) printf '%s\\n' '{\"status\":\"SAVED\"}' ;;\n"
            "esac\n"
        )
        script.chmod(0o755)
        pointer = SaveGameAdapter(home=home, root=self.fixture.repo).checkpoint(self.event)
        self.assertEqual(pointer["status"], "created")
        self.assertIn("flush", marker.read_text())
        self.assertIn("index", marker.read_text())

    def test_event_rejects_unbounded_action_and_escaping_authority(self):
        bad_action = CheckpointEvent(self.state["operation_id"], (), "run-anything")
        with self.assertRaisesRegex(ValueError, "next_action"):
            prepare_checkpoint(
                self.fixture.repo,
                self.state,
                bad_action,
                SaveGameAdapter(home=self.fixture.repo / "missing-home"),
            )
        escaping = CheckpointEvent(
            self.state["operation_id"],
            (),
            "author",
            authority_pointers=("../../outside",),
        )
        with self.assertRaisesRegex(ValueError, "authority_path_invalid"):
            prepare_authoring_resume(
                self.fixture.repo,
                self.state,
                escaping,
                SaveGameAdapter(home=self.fixture.repo / "missing-home"),
            )

    def test_authoring_checkpoint_precedes_optional_save_game(self):
        calls = []

        def runner(_verb, _event):
            calls.append("called")
            return {}

        invalid = dict(self.state)
        invalid["unknown"] = True
        with self.assertRaises(ValueError):
            prepare_checkpoint(
                self.fixture.repo, invalid, self.event, SaveGameAdapter(runner=runner)
            )
        self.assertEqual(calls, [])

    def test_checkpoint_and_resume_bind_repository_key(self):
        state = dict(self.state)
        state["repository_key"] = str(uuid.uuid4())
        adapter = SaveGameAdapter(home=self.fixture.repo / "missing-home")
        with self.assertRaisesRegex(ValueError, "authoring_repository_mismatch"):
            prepare_checkpoint(self.fixture.repo, state, self.event, adapter)
        with self.assertRaisesRegex(ValueError, "authoring_repository_mismatch"):
            prepare_authoring_resume(
                self.fixture.repo, state, self.event, adapter
            )

    def test_authoring_resume_reconciles_live_authorities(self):
        def runner(verb, event):
            self.assertEqual(verb, "reconcile")
            return {
                "schema": "doc-warden/save-game-pointer/v1",
                "checkpoint_id": "checkpoint-1",
                "checkpoint_digest": "sha256:" + "b" * 64,
                "status": "reconciled",
                "artifact_ids": list(event.artifact_ids),
                "next_action_code": event.next_action_code,
                "blocker_ids": list(event.blocker_ids),
                "authority_pointers": list(event.authority_pointers),
            }

        updated = prepare_authoring_resume(
            self.fixture.repo,
            self.state,
            self.event,
            SaveGameAdapter(runner=runner),
        )
        self.assertEqual(updated["save_game_pointer"]["status"], "reconciled")
        self.assertEqual(updated["lifecycle"], "planned")

    def test_unavailable_resume_preserves_existing_checkpoint_pointer(self):
        prior = {
            "schema": "doc-warden/save-game-pointer/v1",
            "checkpoint_id": "checkpoint-prior",
            "checkpoint_digest": "sha256:" + "c" * 64,
            "status": "created",
            "artifact_ids": ["PRD-example"],
            "next_action_code": "author",
            "blocker_ids": [],
            "authority_pointers": ["README.md"],
        }
        state = dict(self.state)
        state["save_game_pointer"] = prior
        updated = prepare_authoring_resume(
            self.fixture.repo,
            state,
            self.event,
            SaveGameAdapter(home=self.fixture.repo / "missing-home"),
        )
        self.assertEqual(updated["save_game_pointer"], prior)

    def test_unavailable_checkpoint_preserves_existing_pointer(self):
        prior = {
            "schema": "doc-warden/save-game-pointer/v1",
            "checkpoint_id": "checkpoint-prior",
            "checkpoint_digest": "sha256:" + "e" * 64,
            "status": "created",
            "artifact_ids": ["PRD-example"],
            "next_action_code": "author",
            "blocker_ids": [],
            "authority_pointers": ["README.md"],
        }
        state = dict(self.state)
        state["save_game_pointer"] = prior
        updated = prepare_checkpoint(
            self.fixture.repo,
            state,
            self.event,
            SaveGameAdapter(home=self.fixture.repo / "missing-home"),
        )
        self.assertEqual(updated["save_game_pointer"], prior)

    def test_save_game_task_id_is_operation_specific(self):
        seen = []

        def runner(_verb, event):
            seen.append(event.operation_id)
            return {
                "schema": "doc-warden/save-game-pointer/v1",
                "checkpoint_id": "checkpoint-" + event.operation_id[:8],
                "checkpoint_digest": "sha256:" + "d" * 64,
                "status": "created",
                "artifact_ids": list(event.artifact_ids),
                "next_action_code": event.next_action_code,
                "blocker_ids": list(event.blocker_ids),
                "authority_pointers": list(event.authority_pointers),
            }

        adapter = SaveGameAdapter(runner=runner)
        adapter.checkpoint(self.event)
        adapter.checkpoint(
            CheckpointEvent(
                str(uuid.uuid4()),
                self.event.artifact_ids,
                self.event.next_action_code,
                authority_pointers=self.event.authority_pointers,
            )
        )
        self.assertNotEqual(seen[0], seen[1])


if __name__ == "__main__":
    unittest.main()
