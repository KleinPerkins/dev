import json
import os
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from doc_warden.canonical import canonical_json, digest_ref
from doc_warden.artifacts import _bindings
from fixture_factory import FixtureFactory


ROOT = Path(__file__).resolve().parents[4]
WRAPPER = ROOT / "_ops/bin/doc-warden.sh"


class CliTests(unittest.TestCase):
    def setUp(self):
        self.machine = tempfile.TemporaryDirectory(prefix="doc-warden-v2-cli-state-")
        self.machine_root = Path(self.machine.name)
        self.fixture = FixtureFactory.create()

    def tearDown(self):
        self.fixture.cleanup()
        self.machine.cleanup()

    def run_cli(self, *arguments, check=True, extra_env=None):
        return subprocess.run(
            ["bash", str(WRAPPER), *arguments],
            text=True,
            capture_output=True,
            check=check,
            env={
                **os.environ,
                "XDG_STATE_HOME": str(self.machine_root / "xdg-state"),
                **(extra_env or {}),
            },
        )

    def test_doctor_reports_v1_repository_migration_without_mutating(self):
        self.fixture.cleanup()
        self.fixture = FixtureFactory.create("unconfigured")
        before = subprocess.check_output(
            ["git", "-C", str(self.fixture.repo), "status", "--porcelain"], text=True
        )
        result = self.run_cli(
            "v2-preview", "doctor", "repo", "--repo", str(self.fixture.repo)
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["profile"], "v1")
        self.assertEqual(payload["migration_status"], "migration_required")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["repository_writes"], [])
        self.assertEqual(
            subprocess.check_output(
                ["git", "-C", str(self.fixture.repo), "status", "--porcelain"], text=True
            ),
            before,
        )

    def test_doctor_and_reconcile_help_are_unambiguously_read_only(self):
        doctor = self.run_cli("doctor", "--help")
        reconcile = self.run_cli("reconcile", "--help")
        self.assertIn("read-only", doctor.stdout.lower())
        self.assertIn("read-only", reconcile.stdout.lower())
        self.assertIn("--preview", reconcile.stdout)

    def test_reconcile_preview_reports_read_only_metadata(self):
        result = self.run_cli(
            "reconcile",
            "--repo",
            str(self.fixture.repo),
            "--preview",
        )
        payload = json.loads(result.stdout)
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["repository_writes"], [])

    def test_migrate_preview_emits_bound_operation_without_repo_writes(self):
        self.fixture.cleanup()
        self.fixture = FixtureFactory.create("unconfigured")
        secret = "credential-that-must-not-persist"
        subprocess.run(
            [
                "git",
                "-C",
                str(self.fixture.repo),
                "remote",
                "add",
                "origin",
                (
                    f"https://oauth2:{secret}@github.com/"
                    "KleinPerkins/migration-fixture.git"
                ),
            ],
            check=True,
        )
        legacy_state = self.machine_root / "legacy-state"
        legacy_state.mkdir()
        receipt = legacy_state / "receipt.yml"
        receipt.write_text(
            "schema: doc-warden-receipt/v1\n"
            "repo: migration-fixture\n"
            'policy_version: "1.3.0"\n'
            "observed_outcome: CREATED\n",
            encoding="utf-8",
        )
        fake_bin = self.machine_root / "fake-bin"
        fake_bin.mkdir()
        gh = fake_bin / "gh"
        gh.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' "
            '\'{"id":123456789,"full_name":"KleinPerkins/migration-fixture"}\'\n',
            encoding="utf-8",
        )
        gh.chmod(0o755)
        before = subprocess.check_output(
            ["git", "-C", str(self.fixture.repo), "status", "--porcelain"],
            text=True,
        )
        operation_id = "8716de90-97ce-4fa9-9760-897889d34466"
        result = self.run_cli(
            "migrate",
            "--repo",
            str(self.fixture.repo),
            "--legacy-state",
            str(legacy_state),
            "--operation-id",
            operation_id,
            "--preview",
            extra_env={
                "BASH_ENV": "/dev/null",
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            },
        )
        payload = json.loads(result.stdout)
        replayed = self.run_cli(
            "migrate",
            "--repo",
            str(self.fixture.repo),
            "--legacy-state",
            str(legacy_state),
            "--operation-id",
            operation_id,
            "--preview",
            extra_env={
                "BASH_ENV": "/dev/null",
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            },
        )
        replayed_payload = json.loads(replayed.stdout)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["operation_id"], operation_id)
        self.assertEqual(
            replayed_payload["repository_key"], payload["repository_key"]
        )
        self.assertEqual(
            replayed_payload["action_digest"], payload["action_digest"]
        )
        self.assertNotIn(secret, result.stdout)
        self.assertNotIn(secret, replayed.stdout)
        self.assertRegex(payload["action_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(payload["expires_at"], r"^\d{4}-")
        self.assertEqual(payload["consequence"], "migration")
        self.assertTrue(payload["consent_required"])
        self.assertFalse(payload["repository_writes_applied"])
        self.assertEqual(
            payload["repository_identity"]["github_repository_id"],
            123456789,
        )
        self.assertRegex(
            payload["bindings"]["gsd_pin_digest"], r"^sha256:[0-9a-f]{64}$"
        )
        self.assertRegex(
            payload["bindings"]["gsd_interface_digest"],
            r"^sha256:[0-9a-f]{64}$",
        )
        self.assertEqual(
            [row["path"] for row in payload["writes"]],
            [".planning/doc-warden.json"],
        )
        self.assertEqual(payload["writes"][0]["preimage"], "absent")
        self.assertEqual(
            payload["record_paths"]["event"],
            (
                "_ops/doc-warden/state/v2/events/"
                f"{payload['event_id']}.json"
            ),
        )
        self.assertEqual(
            payload["record_paths"]["receipt"],
            (
                "_ops/doc-warden/state/v2/receipts/"
                f"{payload['operation_id']}.json"
            ),
        )
        self.assertEqual(payload["rollback"]["strategy"], "git_revert")
        self.assertEqual(
            subprocess.check_output(
                ["git", "-C", str(self.fixture.repo), "status", "--porcelain"],
                text=True,
            ),
            before,
        )
        operation = (
            self.machine_root
            / "xdg-state/doc-warden/operations"
            / f"{payload['operation_id']}.json"
        )
        self.assertTrue(operation.is_file())
        self.assertNotIn(secret, operation.read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc)
        consent = self.machine_root / "consent.json"
        consent.write_bytes(
            canonical_json(
                {
                    "schema": "doc-warden/consent-envelope/v1",
                    "operation_id": payload["operation_id"],
                    "repository_key": payload["repository_key"],
                    "canonical_root": payload["canonical_root"],
                    "source_revision": payload["source_revision"],
                    "action_digest": payload["action_digest"],
                    "consequence_class": "migration",
                    "nonce": str(uuid.uuid4()),
                    "issued_at": now.isoformat(),
                    "expires_at": (now + timedelta(minutes=5)).isoformat(),
                    "choice": "apply",
                }
            )
        )
        refused = self.run_cli(
            "apply",
            "--operation-id",
            payload["operation_id"],
            "--action-digest",
            "sha256:" + "0" * 64,
            "--consent-envelope",
            str(consent),
            check=False,
            extra_env={
                "BASH_ENV": "/dev/null",
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            },
        )
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(
            json.loads(refused.stdout)["code"],
            "operation_specification_mismatch",
        )
        self.assertFalse(
            (self.fixture.repo / ".planning/doc-warden.json").exists()
        )
        applied = self.run_cli(
            "apply",
            "--operation-id",
            payload["operation_id"],
            "--action-digest",
            payload["action_digest"],
            "--consent-envelope",
            str(consent),
            extra_env={
                "BASH_ENV": "/dev/null",
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            },
        )
        applied_payload = json.loads(applied.stdout)
        self.assertNotIn(secret, applied.stdout)
        self.assertEqual(applied_payload["transition"], "migration_adoption")
        self.assertEqual(applied_payload["operation_id"], payload["operation_id"])
        self.assertNotIn(
            secret,
            (
                self.fixture.repo
                / payload["record_paths"]["receipt"]
            ).read_text(encoding="utf-8"),
        )
        self.assertTrue(
            (self.fixture.repo / ".planning/doc-warden.json").is_file()
        )

    def test_doctor_reports_write_disabled_v2_repository(self):
        path = self.fixture.repo / ".planning/doc-warden.json"
        config = json.loads(path.read_text())
        config["enabled"] = False
        path.write_bytes(canonical_json(config))
        result = self.run_cli(
            "doctor", "repo", "--repo", str(self.fixture.repo)
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["migration_status"], "write_disabled")
        self.assertFalse(payload["write_enabled"])

    def test_active_bindings_never_prefer_a_restored_draft_policy(self):
        policy = self.fixture.repo / "_ops/doc-warden/POLICY.md"
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text("active policy\n")
        draft = self.fixture.repo / "_ops/doc-warden/drafts/POLICY-v2.md"
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text("stale draft\n")
        bindings = _bindings(self.fixture.repo)
        self.assertEqual(bindings["policy_version"], "2.0.0")
        self.assertEqual(
            bindings["policy_digest"],
            digest_ref(policy.read_bytes()),
        )

    def test_draft_emits_bound_preview_without_writing(self):
        result = self.run_cli(
            "v2-preview",
            "draft",
            "prd",
            "--repo",
            str(self.fixture.repo),
            "--title",
            "Feature",
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], "doc-warden/artifact-preview/v2")
        self.assertTrue(payload["artifact_id"].startswith("PRD-"))
        self.assertFalse((self.fixture.repo / payload["artifact_path"]).exists())

    def test_runtime_install_requires_digest_bound_generic_apply(self):
        from test_live_install import live_install_repository
        repo, _qualification = live_install_repository(self.machine_root)
        home = self.machine_root / "isolated-home"
        data = self.machine_root / "isolated-data"
        proposed = self.run_cli(
            "runtime",
            "install-gsd",
            "--repo",
            str(repo),
            "--home",
            str(home),
            "--data-home",
            str(data),
            "--preview",
        )
        payload = json.loads(proposed.stdout)
        self.assertEqual(payload["consequence"], "live_runtime_install")
        self.assertTrue(payload["consent_required"])
        self.assertRegex(payload["operation_id"], r"^[0-9a-f-]{36}$")
        direct = self.run_cli(
            "runtime",
            "install-gsd",
            "--repo",
            str(repo),
            "--home",
            str(home),
            "--data-home",
            str(data),
            check=False,
        )
        self.assertEqual(
            json.loads(direct.stdout)["code"],
            "runtime_apply_requires_generic_apply",
        )

    def test_view_repo_emits_roadmap_view(self):
        result = self.run_cli(
            "v2-preview", "view", "repo", "--repo", str(self.fixture.repo), "--json"
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], "doc-warden/roadmap-view/v2")
        self.assertEqual(payload["repository_key"], self.fixture.repository_key)
        self.assertEqual(payload["items"], [])

    def test_view_canvas_writes_revision_bound_managed_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "roadmap.canvas.tsx"
            result = self.run_cli(
                "view",
                "repo",
                "--repo",
                str(self.fixture.repo),
                "--canvas",
                str(target),
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema"], "doc-warden/canvas-render-result/v1")
            self.assertTrue(target.is_file())
            self.assertIn(payload["source_revision"], target.read_text())

    def test_doctor_reports_invalid_config_without_traceback(self):
        (self.fixture.repo / ".planning/doc-warden.json").write_text("{invalid")
        result = self.run_cli(
            "v2-preview", "doctor", "repo", "--repo", str(self.fixture.repo)
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["profile"], "invalid")
        self.assertEqual(payload["migration_status"], "blocked")
        self.assertFalse(payload["write_enabled"])

    def test_view_reports_invalid_config_as_blocked_roadmap(self):
        (self.fixture.repo / ".planning/doc-warden.json").write_text("{invalid")
        result = self.run_cli(
            "v2-preview", "view", "repo", "--repo", str(self.fixture.repo)
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema"], "doc-warden/roadmap-view/v2")
        self.assertEqual(payload["migration_status"], "blocked")
        self.assertEqual(payload["items"], [])

    def test_view_canvas_replaces_stale_copy_with_blocked_snapshot(self):
        (self.fixture.repo / ".planning/doc-warden.json").write_text("{invalid")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "roadmap.canvas.tsx"
            target.write_text("stale")
            result = self.run_cli(
                "view",
                "repo",
                "--repo",
                str(self.fixture.repo),
                "--canvas",
                str(target),
            )
            self.assertEqual(
                json.loads(result.stdout)["schema"],
                "doc-warden/canvas-render-result/v1",
            )
            self.assertNotEqual(target.read_text(), "stale")
            self.assertIn("repository_key_unreadable", target.read_text())

    def test_mutation_verb_reports_invalid_config_without_traceback(self):
        (self.fixture.repo / ".planning/doc-warden.json").write_text("{invalid")
        result = self.run_cli(
            "v2-preview",
            "draft",
            "project",
            "--repo",
            str(self.fixture.repo),
            "--title",
            "Blocked",
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["code"], "repository_key_unreadable")
        self.assertNotIn("Traceback", result.stderr)

    def test_roadmap_mutation_reports_missing_profile_as_json(self):
        self.fixture.cleanup()
        self.fixture = FixtureFactory.create("unconfigured")
        result = self.run_cli(
            "v2-preview",
            "prioritize",
            "ROAD-1",
            "P0",
            "--repo",
            str(self.fixture.repo),
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(
            json.loads(result.stdout)["code"], "v2_repository_profile_required"
        )

    def test_policy_runtime_schema_catalog_and_dispatch_activate_atomically(self):
        bare = self.run_cli("doctor", "repo", "--repo", str(self.fixture.repo))
        self.assertEqual(json.loads(bare.stdout)["schema"], "doc-warden/repo-view/v2")
        legacy = self.run_cli("legacy-v1", "check", str(self.fixture.repo), check=False)
        self.assertNotEqual(legacy.returncode, 2)
        missing_apply = self.run_cli(
            "v2-preview",
            "apply",
            "--operation-id",
            "00000000-0000-4000-8000-000000000000",
            "--action-digest",
            "sha256:" + "0" * 64,
            check=False,
        )
        self.assertEqual(missing_apply.returncode, 1)
        self.assertEqual(
            json.loads(missing_apply.stdout)["code"],
            "operation_specification_unavailable",
        )

    def test_cross_process_apply_replays_mode_0600_operation_specification(self):
        operation_id = str(uuid.uuid4())
        proposed = json.loads(
            self.run_cli(
                "draft",
                "prd",
                "--repo",
                str(self.fixture.repo),
                "--title",
                "Bound preview",
                "--operation-id",
                operation_id,
            ).stdout
        )
        now = datetime.now(timezone.utc)
        consent = {
            "schema": "doc-warden/consent-envelope/v1",
            "operation_id": operation_id,
            "repository_key": proposed["repository_key"],
            "canonical_root": proposed["canonical_root"],
            "source_revision": proposed["source_revision"],
            "action_digest": proposed["action_digest"],
            "consequence_class": "semantic",
            "nonce": str(uuid.uuid4()),
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
            "choice": "apply",
        }
        envelope = self.machine_root / "consent.json"
        envelope.write_bytes(canonical_json(consent))
        applied = self.run_cli(
            "apply",
            "--operation-id",
            operation_id,
            "--action-digest",
            proposed["action_digest"],
            "--consent-envelope",
            str(envelope),
        )
        receipt = json.loads(applied.stdout)
        self.assertEqual(receipt["operation_id"], operation_id)
        self.assertTrue((self.fixture.repo / proposed["artifact_path"]).is_file())
        replayed = self.run_cli(
            "apply",
            "--operation-id",
            operation_id,
            "--action-digest",
            proposed["action_digest"],
            "--consent-envelope",
            str(envelope),
        )
        self.assertEqual(json.loads(replayed.stdout), receipt)

    def test_validate_authoring_uses_original_frozen_bindings(self):
        frozen = self.fixture.repo / ".planning/phases/01/01-PLAN.md"
        frozen.parent.mkdir(parents=True)
        frozen.write_text("accepted\n")
        subprocess.run(["git", "-C", str(self.fixture.repo), "add", ".planning"], check=True)
        subprocess.run(
            ["git", "-C", str(self.fixture.repo), "commit", "-qm", "accepted plan"], check=True
        )
        prepared = self.run_cli(
            "v2-preview",
            "prepare-authoring",
            "--repo",
            str(self.fixture.repo),
            "--operation-id",
            str(uuid.uuid4()),
            "--frozen",
            ".planning/phases/01/01-PLAN.md",
        )
        preview_path = self.fixture.repo / "authoring-preview.json"
        preview_path.write_text(prepared.stdout)
        frozen.write_text("changed\n")
        output = self.fixture.repo / ".planning/STATE.md"
        output.write_text("state\n")
        preview = json.loads(prepared.stdout)
        result_path = self.fixture.repo / "authoring-result.json"
        result_path.write_bytes(
            canonical_json(
                {
                    "source_revision": preview["source_revision"],
                    "pin_digest": preview["pin_digest"],
                    "changed_file_digests": {
                        ".planning/STATE.md": digest_ref(output.read_bytes())
                    },
                    "checker_passed": True,
                    "commands": [],
                    "assumptions_changed": False,
                }
            )
        )
        validated = self.run_cli(
            "v2-preview",
            "validate-authoring",
            "--repo",
            str(self.fixture.repo),
            "--preview",
            str(preview_path),
            "--result",
            str(result_path),
            check=False,
        )
        self.assertEqual(validated.returncode, 1)
        self.assertEqual(json.loads(validated.stdout)["code"], "contradictory_authority")

    def test_authoring_preview_tamper_is_refused(self):
        prepared = self.run_cli(
            "v2-preview",
            "prepare-authoring",
            "--repo",
            str(self.fixture.repo),
            "--operation-id",
            str(uuid.uuid4()),
        )
        payload = json.loads(prepared.stdout)
        payload["frozen_digests"]["README.md"] = digest_ref(b"fixture\n")
        preview_path = self.fixture.repo / "tampered-preview.json"
        preview_path.write_bytes(canonical_json(payload))
        verified = self.run_cli(
            "v2-preview",
            "verify",
            "--repo",
            str(self.fixture.repo),
            "--preview",
            str(preview_path),
            check=False,
        )
        self.assertEqual(verified.returncode, 1)
        self.assertEqual(
            json.loads(verified.stdout)["code"], "authoring_preview_digest_mismatch"
        )

    def test_legacy_authoring_preview_without_active_plan_remains_valid(self):
        prepared = self.run_cli(
            "v2-preview",
            "prepare-authoring",
            "--repo",
            str(self.fixture.repo),
            "--operation-id",
            str(uuid.uuid4()),
        )
        current = json.loads(prepared.stdout)
        self.assertIsNone(current["active_plan_id"])
        legacy = dict(current)
        legacy.pop("preview_digest")
        legacy.pop("active_plan_id")
        legacy["preview_digest"] = digest_ref(canonical_json(legacy))

        for label, payload in (("current", current), ("legacy", legacy)):
            with self.subTest(label=label):
                preview_path = self.fixture.repo / f"{label}-preview.json"
                preview_path.write_bytes(canonical_json(payload))
                verified = self.run_cli(
                    "v2-preview",
                    "verify",
                    "--repo",
                    str(self.fixture.repo),
                    "--preview",
                    str(preview_path),
                    check=False,
                )
                self.assertEqual(verified.returncode, 0)
                self.assertEqual(json.loads(verified.stdout)["status"], "pass")

    def test_authoring_preview_compatibility_accepts_only_legacy_omission(self):
        prepared = self.run_cli(
            "v2-preview",
            "prepare-authoring",
            "--repo",
            str(self.fixture.repo),
            "--operation-id",
            str(uuid.uuid4()),
        )
        current = json.loads(prepared.stdout)

        def extra_key(payload):
            payload["unexpected"] = None

        def missing_older_key(payload):
            payload.pop("post_validator")

        def malformed_active_plan(payload):
            payload["active_plan_id"] = []

        def mismatched_root(payload):
            payload["canonical_root"] = str(self.fixture.repo.parent)

        for label, mutate in (
            ("extra", extra_key),
            ("missing", missing_older_key),
            ("malformed", malformed_active_plan),
            ("binding", mismatched_root),
        ):
            with self.subTest(label=label):
                payload = dict(current)
                payload.pop("preview_digest")
                mutate(payload)
                payload["preview_digest"] = digest_ref(
                    canonical_json(payload)
                )
                preview_path = self.fixture.repo / f"{label}-preview.json"
                preview_path.write_bytes(canonical_json(payload))
                verified = self.run_cli(
                    "v2-preview",
                    "verify",
                    "--repo",
                    str(self.fixture.repo),
                    "--preview",
                    str(preview_path),
                    check=False,
                )
                self.assertEqual(verified.returncode, 1)
                self.assertEqual(
                    json.loads(verified.stdout)["code"],
                    "authoring_preview_contract_invalid",
                )

    def test_missing_runtime_binding_returns_blocked_json(self):
        (
            self.fixture.repo
            / "_ops/doc-warden/runtime/gsd-core/runtime-interface.v1.json"
        ).unlink()
        prepared = self.run_cli(
            "v2-preview",
            "prepare-authoring",
            "--repo",
            str(self.fixture.repo),
            "--operation-id",
            str(uuid.uuid4()),
            check=False,
        )
        self.assertEqual(prepared.returncode, 1)
        self.assertEqual(
            json.loads(prepared.stdout)["code"], "runtime_binding_unavailable"
        )
        self.assertNotIn("Traceback", prepared.stderr)

    def test_malformed_external_json_uses_stable_error_code(self):
        state = self.fixture.repo / "bad-state.json"
        event = self.fixture.repo / "bad-event.json"
        state.write_text("{bad")
        event.write_text("{}")
        result = self.run_cli(
            "v2-preview",
            "checkpoint",
            "--repo",
            str(self.fixture.repo),
            "--state",
            str(state),
            "--event",
            str(event),
            "--operation-id",
            str(uuid.uuid4()),
            "--preview",
            check=False,
        )
        self.assertEqual(json.loads(result.stdout)["code"], "invalid_input")

    def test_missing_result_fields_report_contract_error(self):
        prepared = self.run_cli(
            "v2-preview",
            "prepare-authoring",
            "--repo",
            str(self.fixture.repo),
            "--operation-id",
            str(uuid.uuid4()),
        )
        preview = self.fixture.repo / "preview.json"
        result = self.fixture.repo / "result.json"
        preview.write_text(prepared.stdout)
        result.write_text("{}")
        validated = self.run_cli(
            "v2-preview",
            "validate-authoring",
            "--repo",
            str(self.fixture.repo),
            "--preview",
            str(preview),
            "--result",
            str(result),
            check=False,
        )
        self.assertEqual(
            json.loads(validated.stdout)["code"], "authoring_result_contract_invalid"
        )


if __name__ == "__main__":
    unittest.main()
