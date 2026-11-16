import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import doc_warden.bootstrap as bootstrap
from pathlib import Path

from doc_warden.bootstrap import (
    ACCEPTED_COMMIT,
    ACCEPTED_PATHS,
    adopt_accepted_authorities,
)
from doc_warden.canonical import digest_ref
from doc_warden.transactions import apply_transaction, confirmation_for
from fixture_factory import FixtureFactory


ROOT = Path(__file__).resolve().parents[4]


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="doc-warden-section0-")
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "remote", "add", "origin", "git@github.com:KleinPerkins/dev.git"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Fixture"], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config", "user.email", "fixture@example.invalid"],
            check=True,
        )
        for relative in (
            "_ops/doc-warden/POLICY.md",
            "_ops/doc-warden/schemas/v2",
            "_ops/doc-warden/triggers.v2.json",
            "_ops/doc-warden/runtime/gsd-core/runtime-interface.v1.json",
            "_ops/doc-warden/runtime/gsd-core/gsd-core-pin.json",
        ):
            source = ROOT / relative
            destination = self.repo / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(source, destination)
        for relative in ACCEPTED_PATHS:
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Synthetic historical authority fixture: " + relative + "\n")
        (self.repo / "_ops/doc-warden/drafts/POLICY-v2.md").unlink(missing_ok=True)
        for name in ("adoption", "events", "receipts"):
            shutil.rmtree(self.repo / "_ops/doc-warden/state/v2" / name, ignore_errors=True)
        # Section-zero fixtures represent the state before repository adoption.
        # A later profile in the source checkout must not leak into that state.
        staged_paths = ["_ops"]
        profile = self.repo / ".planning/doc-warden.json"
        if profile.exists():
            profile.unlink()
            staged_paths.append(".planning/doc-warden.json")
        subprocess.run(["git", "-C", str(self.repo), "add", *staged_paths], check=True)
        if subprocess.run(
            ["git", "-C", str(self.repo), "diff", "--cached", "--quiet"], check=False
        ).returncode:
            subprocess.run(
                ["git", "-C", str(self.repo), "commit", "-qm", "fixture inputs"], check=True
            )

        self.accepted_commit = subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", "HEAD"], text=True).strip()
        patcher = patch.object(bootstrap, "ACCEPTED_COMMIT", self.accepted_commit)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.temporary.cleanup()

    def test_section0_adoption_records_both_accepted_freeze_bindings(self):
        preview = adopt_accepted_authorities(self.repo, self.accepted_commit)
        adoption = json.loads(preview.actions[0].content)
        self.assertEqual([item["path"] for item in adoption["bindings"]], list(ACCEPTED_PATHS))
        self.assertEqual(
            [item["git_blob"] for item in adoption["bindings"]],
            [subprocess.check_output(["git", "-C", str(self.repo), "rev-parse", f"{self.accepted_commit}:{path}"], text=True).strip() for path in ACCEPTED_PATHS],
        )
        self.assertTrue(all(item["transition"] == "accepted_freeze" for item in adoption["bindings"]))

    def test_section0_preview_mints_unique_operation_identity(self):
        first = adopt_accepted_authorities(self.repo, self.accepted_commit)
        second = adopt_accepted_authorities(self.repo, self.accepted_commit)
        self.assertNotEqual(first.operation_id, second.operation_id)

    def test_section0_refuses_a_different_adopted_repository_identity(self):
        other = FixtureFactory.create("section0-other-identity")
        try:
            profile = self.repo / ".planning/doc-warden.json"
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_bytes((other.repo / ".planning/doc-warden.json").read_bytes())
        finally:
            other.cleanup()
        subprocess.run(["git", "-C", str(self.repo), "add", "-f", ".planning/doc-warden.json"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "different adopted identity"], check=True)
        with self.assertRaisesRegex(ValueError, "repository_key_mismatch"):
            adopt_accepted_authorities(self.repo, self.accepted_commit)

    def test_section0_bootstrap_refuses_any_path_or_blob_outside_acceptance_commit(self):
        with self.assertRaisesRegex(ValueError, "section0_commit_refused"):
            adopt_accepted_authorities(self.repo, "a" * 40)
        with self.assertRaisesRegex(ValueError, "section0_path_refused"):
            adopt_accepted_authorities(self.repo, self.accepted_commit, (ACCEPTED_PATHS[0],))

    def test_section0_accepts_standard_ssh_remote_without_dot_git_suffix(self):
        subprocess.run(
            [
                "git", "-C", str(self.repo), "remote", "set-url", "origin",
                "git@github.com:KleinPerkins/dev",
            ],
            check=True,
        )
        self.assertEqual(
            adopt_accepted_authorities(self.repo, self.accepted_commit).transition,
            "accepted_freeze",
        )

    def test_section0_bootstrap_refuses_changed_accepted_authority_at_head(self):
        path = self.repo / ACCEPTED_PATHS[0]
        path.write_text(path.read_text() + "\nchanged\n")
        subprocess.run(["git", "-C", str(self.repo), "add", ACCEPTED_PATHS[0]], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "change authority"], check=True)
        with self.assertRaisesRegex(ValueError, "section0_authority_drift"):
            adopt_accepted_authorities(self.repo, self.accepted_commit)

    def test_section0_adoption_applies_and_replays_idempotently(self):
        preview = adopt_accepted_authorities(self.repo, self.accepted_commit)
        receipt = apply_transaction(preview, confirmation_for(preview))
        self.assertEqual(receipt["transition"], "accepted_freeze")
        self.assertEqual(apply_transaction(preview, confirmation_for(preview)), receipt)
        self.assertTrue((self.repo / preview.actions[0].path).is_file())
        with self.assertRaisesRegex(ValueError, "section0_already_adopted"):
            adopt_accepted_authorities(self.repo, self.accepted_commit)

    def test_section0_cli_preview_can_be_rebuilt_after_postimage_only_partial_apply(self):
        preview = adopt_accepted_authorities(self.repo, self.accepted_commit)
        destination = self.repo / preview.actions[0].path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(preview.actions[0].content)
        staged = destination.parent / f".{destination.name}.deadbeef"
        staged.write_bytes(b"interrupted partial output")

        recovered = adopt_accepted_authorities(
            self.repo, self.accepted_commit, operation_id=preview.operation_id
        )
        self.assertEqual(recovered.action_digest, preview.action_digest)
        receipt = apply_transaction(recovered, confirmation_for(recovered))
        self.assertEqual(receipt["operation_id"], preview.operation_id)
        self.assertTrue(
            (self.repo / f"_ops/doc-warden/state/v2/events/{preview.event_id}.json").is_file()
        )
        self.assertFalse(staged.exists())

    def test_section0_replay_does_not_change_active_policy(self):
        canonical = self.repo / "_ops/doc-warden/POLICY.md"
        before = canonical.read_bytes()
        preview = adopt_accepted_authorities(self.repo, self.accepted_commit)
        apply_transaction(preview, confirmation_for(preview))
        self.assertEqual(canonical.read_bytes(), before)
        self.assertIn("**Status:** ACTIVE", canonical.read_text())

    def test_section0_binding_ignores_restored_draft_and_legacy_trigger(self):
        draft = self.repo / "_ops/doc-warden/drafts/POLICY-v2.md"
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text("stale draft\n")
        subprocess.run(
            ["git", "-C", str(self.repo), "add", str(draft.relative_to(self.repo))],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repo), "commit", "-qm", "restore stale draft"],
            check=True,
        )
        preview = adopt_accepted_authorities(self.repo, self.accepted_commit)
        self.assertEqual(preview.bindings["policy_version"], "2.0.0")
        self.assertEqual(
            preview.bindings["policy_digest"],
            digest_ref((self.repo / "_ops/doc-warden/POLICY.md").read_bytes()),
        )
        self.assertEqual(
            preview.bindings["trigger_catalog_digest"],
            digest_ref(
                (self.repo / "_ops/doc-warden/triggers.v2.json").read_bytes()
            ),
        )


if __name__ == "__main__":
    unittest.main()
