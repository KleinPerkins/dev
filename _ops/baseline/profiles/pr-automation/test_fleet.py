#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("phase_b_fleet", HERE / "fleet.py")
assert SPEC and SPEC.loader
fleet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fleet)


class RepoFixture:
    def __init__(self, name: str = "kp-mcp") -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / name
        self.path.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=self.path, check=True, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", f"git@github.com:KleinPerkins/{name}.git"],
            cwd=self.path,
            check=True,
        )
        subprocess.run(
            ["git", "config", "--local", "user.name", "KleinPerkins"],
            cwd=self.path,
            check=True,
        )
        subprocess.run(
            [
                "git", "config", "--local", "user.email",
                "49759187+KleinPerkins@users.noreply.github.com",
            ],
            cwd=self.path,
            check=True,
        )
        (self.path / ".github/scripts").mkdir(parents=True)
        (self.path / ".github/scripts/baseline-verify.sh").write_text("#!/bin/sh\nexit 0\n")
        (self.path / ".github/CODEOWNERS").write_text(fleet.phase_a.BASELINE_CODEOWNERS.read_text())
        (self.path / "README.md").write_text("# fixture\n")
        subprocess.run(["git", "add", "."], cwd=self.path, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.path, check=True, capture_output=True)

    def close(self) -> None:
        self.tmp.cleanup()


class FleetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = RepoFixture()

    def tearDown(self) -> None:
        self.repo.close()

    def test_policy_manifest_and_closed_schemas(self) -> None:
        config = fleet.policy()
        manifest = fleet.fleet()
        for schema_path in (
            fleet.CONFIG_SCHEMA,
            fleet.FLEET_SCHEMA,
            fleet.EVIDENCE_SCHEMA,
            fleet.STATE_SCHEMA,
        ):
            schema = json.loads(schema_path.read_text())
            self.assertFalse(schema["additionalProperties"])
        self.assertEqual(config["hard_exclusions"], ["KleinPerkins/chaos-scheduler"])
        self.assertIn("KleinPerkins/dev", config["self_enrollment"])
        targets = [entry["repo"] for entry in manifest["targets"]]
        self.assertEqual(len(targets), 12)
        self.assertNotIn("KleinPerkins/chaos-scheduler", targets)
        self.assertTrue(
            any(
                item["repo"] == "KleinPerkins/chaos-scheduler"
                for item in manifest["excluded"]
            )
        )

    def test_ruleset_pair_has_exact_safety_split(self) -> None:
        pair = fleet.render_rulesets("main")
        safety = pair["merge_safety"]
        review = pair["review_gate"]
        self.assertEqual(safety["bypass_actors"], [])
        self.assertEqual(
            review["bypass_actors"],
            [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}],
        )
        review_pr = next(rule for rule in review["rules"] if rule["type"] == "pull_request")
        self.assertEqual(review_pr["parameters"]["required_approving_review_count"], 1)
        self.assertTrue(review_pr["parameters"]["dismiss_stale_reviews_on_push"])
        self.assertTrue(review_pr["parameters"]["require_last_push_approval"])
        self.assertTrue(review_pr["parameters"]["require_code_owner_review"])
        safety_pr = next(rule for rule in safety["rules"] if rule["type"] == "pull_request")
        checks = next(rule for rule in safety["rules"] if rule["type"] == "required_status_checks")
        self.assertEqual(safety_pr["parameters"]["allowed_merge_methods"], ["squash"])
        self.assertTrue(safety_pr["parameters"]["required_review_thread_resolution"])
        self.assertEqual(
            checks["parameters"]["required_status_checks"],
            [{"context": "required / ci", "integration_id": 15368}],
        )
        self.assertTrue(checks["parameters"]["strict_required_status_checks_policy"])
        self.assertTrue({"required_linear_history", "deletion", "non_fast_forward"} <= {
            rule["type"] for rule in safety["rules"]
        })

    def test_controller_hardening_contract(self) -> None:
        config = fleet.render_policy("KleinPerkins/demo", "main")
        controller = fleet.render_controller(config)
        required_literals = (
            "workflow_run:",
            "vars.AUTOMERGE_ENABLED == 'true'",
            ".check_suite_id",
            "check-suites/$suite_id/check-runs",
            '[ "$total" = "1" ]',
            ".previous_filename // empty",
            '[ "$fetched_count" = "$changed_files" ]',
            "PR exceeds GitHub changed-file inspection limit",
            "kleinperkins-review-bot[bot]",
            "assert_controls",
            "actions/variables/AUTOMERGE_ENABLED",
            "live controller activation changed",
            "assert_pr_tuple",
            "expectedHeadOid",
            '-f sha="$EXPECT"',
            "permission-contents: write",
            "permission-pull-requests: write",
            "permission-administration: read",
            "cleanup_auto_merge",
            "disablePullRequestAutoMerge",
        )
        for literal in required_literals:
            self.assertIn(literal, controller)
        self.assertNotIn("pull_request_target", controller)
        self.assertNotIn("actions/checkout@", controller)
        self.assertNotRegex(controller, r"\{\{[A-Z0-9_]+\}\}")
        uses = re.findall(r"(?m)^\s*uses:\s*([^ #]+)", controller)
        self.assertTrue(uses)
        self.assertTrue(all(re.search(r"@[0-9a-f]{40}$", item) for item in uses))

    def test_apply_is_inert_idempotent_and_locally_verifiable(self) -> None:
        self.assertEqual(
            fleet.cmd_apply(
                self.repo.path,
                dry_run=True,
                base_branch="main",
                workflow_name=None,
                workflow_path=None,
            ),
            0,
        )
        self.assertFalse((self.repo.path / fleet.CONFIG_REL).exists())
        self.assertEqual(
            fleet.cmd_apply(
                self.repo.path,
                dry_run=False,
                base_branch="main",
                workflow_name=None,
                workflow_path=None,
            ),
            0,
        )
        self.assertEqual(fleet.verify_local(self.repo.path), [])
        before = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.repo.path,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        # The second apply accepts the profile's own uncommitted writes only after a commit.
        subprocess.run(["git", "add", "."], cwd=self.repo.path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "phase b"],
            cwd=self.repo.path,
            check=True,
            capture_output=True,
        )
        self.assertEqual(
            fleet.cmd_apply(
                self.repo.path,
                dry_run=False,
                base_branch="main",
                workflow_name=None,
                workflow_path=None,
            ),
            0,
        )
        self.assertEqual(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo.path,
                text=True,
                capture_output=True,
                check=True,
            ).stdout,
            "",
        )
        self.assertTrue(before)
        codeowners = (self.repo.path / fleet.CODEOWNERS_REL).read_text()
        self.assertNotIn("\n* @KleinPerkins\n", "\n" + codeowners)
        self.assertIn("/.github/pr-automation.json @KleinPerkins", codeowners)

    def test_apply_renders_custom_required_workflow_name(self) -> None:
        self.assertEqual(
            fleet.cmd_apply(
                self.repo.path,
                dry_run=False,
                base_branch="main",
                workflow_name="phase-b-required",
                workflow_path=".github/workflows/phase-b-required.yml",
            ),
            0,
        )
        workflow = (
            self.repo.path / ".github/workflows/phase-b-required.yml"
        ).read_text()
        self.assertTrue(workflow.startswith("name: phase-b-required\n"))
        self.assertEqual(fleet.verify_local(self.repo.path), [])

    def test_remote_default_binding_uses_production_policy(self) -> None:
        fleet.cmd_apply(
            self.repo.path,
            dry_run=False,
            base_branch="phase-b-canary",
            workflow_name=None,
            workflow_path=None,
        )
        canary = fleet.phase_b_config(self.repo.path)
        production = fleet.policy_for_branch(canary, "main")
        expected = {
            str(fleet.CONFIG_REL): (
                json.dumps(production, indent=2, sort_keys=True) + "\n"
            ).encode(),
            str(fleet.CONTROLLER_REL): fleet.render_controller(production).encode(),
        }
        with mock.patch.object(
            fleet,
            "remote_file_bytes",
            side_effect=lambda _owner, path, _ref: expected[path],
        ):
            fleet.assert_remote_managed_files(
                self.repo.path,
                "KleinPerkins/kp-mcp",
                "main",
                include_required=False,
                expected_config=production,
            )

    def test_workflow_state_transition_is_idempotent(self) -> None:
        with mock.patch.object(
            fleet,
            "gh_api",
            return_value={"state": "disabled_manually"},
        ) as api:
            fleet.set_workflow_enabled("KleinPerkins/kp-mcp", False)
        self.assertEqual(api.call_count, 1)

        responses = iter(
            [
                {"state": "disabled_manually"},
                None,
                {"state": "active"},
            ]
        )
        with mock.patch.object(
            fleet,
            "gh_api",
            side_effect=lambda *_args, **_kwargs: next(responses),
        ) as api:
            fleet.set_workflow_enabled("KleinPerkins/kp-mcp", True)
        self.assertEqual(api.call_count, 3)

    def test_apply_refuses_unmanaged_controller(self) -> None:
        controller = self.repo.path / fleet.CONTROLLER_REL
        controller.parent.mkdir(parents=True, exist_ok=True)
        controller.write_text("name: unrelated\n")
        subprocess.run(["git", "add", "."], cwd=self.repo.path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "unmanaged controller"],
            cwd=self.repo.path,
            check=True,
            capture_output=True,
        )
        with self.assertRaisesRegex(fleet.FleetError, "unmanaged"):
            fleet.cmd_apply(
                self.repo.path,
                dry_run=False,
                base_branch="main",
                workflow_name=None,
                workflow_path=None,
            )

    def test_hard_exclusion_is_enforced_before_mutation(self) -> None:
        excluded = RepoFixture("chaos-scheduler")
        try:
            with self.assertRaisesRegex(fleet.FleetError, "hard-excluded"):
                fleet.validate_target(excluded.path, clean=True)
            # The CLI takes a local lifecycle lock before target validation. Keep
            # this refusal fixture from touching the developer's live lock store.
            with mock.patch.object(fleet, "remote_repo_lock") as remote_lock, mock.patch.object(
                fleet.Path, "home", return_value=Path(excluded.tmp.name) / "test-home"
            ):
                self.assertEqual(fleet.main(["pause", str(excluded.path)]), 1)
                remote_lock.assert_not_called()
        finally:
            excluded.close()

    def test_unsafe_branch_placeholders_are_rejected(self) -> None:
        with self.assertRaisesRegex(fleet.FleetError, "branch name"):
            fleet.render_rulesets("$(touch-pwned)")

    def test_credential_upload_uses_stdin_and_preserves_existing_secret(self) -> None:
        metadata = {
            "variable": None,
            "activation": None,
            "secret": {
                "name": "AUTOMERGE_APP_PRIVATE_KEY",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        }
        after = {
            "variable": {
                "name": "AUTOMERGE_APP_ID",
                "updated_at": "now",
                "value": "4269364",
            },
            "activation": {
                "name": "AUTOMERGE_ENABLED",
                "updated_at": "now",
                "value": "false",
            },
            "secret": metadata["secret"],
        }
        with tempfile.TemporaryDirectory() as state_tmp, tempfile.NamedTemporaryFile() as key:
            key_path = Path(key.name)
            key_path.chmod(0o600)
            calls = 0
            gh_commands = []
            original_run = fleet.run

            def meta(_ownerrepo):
                nonlocal calls
                calls += 1
                return metadata if calls == 1 else after

            def safe_run(args, **kwargs):
                if args[0] == "gh":
                    gh_commands.append(args)
                    return subprocess.CompletedProcess(args, 0, "", "")
                return original_run(args, **kwargs)

            with (
                mock.patch.object(fleet, "require_gh"),
                mock.patch.object(fleet, "credential_metadata", side_effect=meta),
                mock.patch.object(fleet, "require_exact_head", return_value="a" * 40),
                mock.patch.object(fleet, "run", side_effect=safe_run),
                mock.patch.object(fleet, "STATE_DIR", Path(state_tmp)),
            ):
                credential_state = fleet.state_seed(
                    "KleinPerkins/kp-mcp",
                    "main",
                    "canary",
                    "a" * 40,
                    {key: False for key in fleet.policy()["settings"]},
                )
                credential_state["lifecycle"] = "canary"
                fleet.write_state("KleinPerkins/kp-mcp", credential_state)
                fleet.cmd_credential_provision(
                    self.repo.path,
                    key_file=key_path,
                    preserve_existing_secret=True,
                )
                state = fleet.read_state("KleinPerkins/kp-mcp")
                assert state
                self.assertFalse(state["credentials"]["secret"]["owned"])
            self.assertFalse(
                any(command[:3] == ["gh", "secret", "set"] for command in gh_commands)
            )

    def test_remote_mutation_lock_is_atomic_and_owner_checked(self) -> None:
        calls = []
        lock_value = None

        def api(endpoint, *, method="GET", payload=None, paginate=False):
            nonlocal lock_value
            calls.append((endpoint, method, payload, paginate))
            if method == "POST":
                lock_value = payload["value"]
                return {"name": fleet.REMOTE_LOCK_VARIABLE}
            if method == "GET":
                return {"name": fleet.REMOTE_LOCK_VARIABLE, "value": lock_value}
            if method == "DELETE":
                lock_value = None
                return None
            raise AssertionError(method)

        with (
            mock.patch.object(fleet, "gh_api", side_effect=api),
            mock.patch.object(
                fleet,
                "run",
                return_value=subprocess.CompletedProcess([], 1, "", ""),
            ),
        ):
            with fleet.remote_repo_lock("KleinPerkins/kp-mcp", "activate"):
                self.assertIsNotNone(lock_value)
        self.assertIsNone(lock_value)
        self.assertEqual([item[1] for item in calls], ["POST", "GET", "DELETE"])

    def test_remote_state_marker_refuses_stale_local_state(self) -> None:
        state = fleet.state_seed(
            "KleinPerkins/kp-mcp",
            "main",
            "canary",
            "a" * 40,
            {key: False for key in fleet.policy()["settings"]},
        )
        remote_value = None

        def state_run(args, **_kwargs):
            nonlocal remote_value
            if args[:3] == ["gh", "variable", "set"]:
                remote_value = args[args.index("--body") + 1]
            elif args[:3] == ["gh", "variable", "delete"]:
                remote_value = None
            return subprocess.CompletedProcess(args, 0, "", "")

        with tempfile.TemporaryDirectory() as state_tmp:
            with (
                mock.patch.object(fleet, "STATE_DIR", Path(state_tmp)),
                mock.patch.object(
                    fleet,
                    "run",
                    side_effect=state_run,
                ),
                mock.patch.object(
                    fleet,
                    "gh_api",
                    side_effect=lambda *_args, **_kwargs: {"value": remote_value},
                ),
            ):
                fleet._REMOTE_LOCK_CONTEXT = {
                    "owner_repo": "KleinPerkins/kp-mcp",
                    "state_marker": None,
                }
                fleet.write_state("KleinPerkins/kp-mcp", state)
                fleet._REMOTE_LOCK_CONTEXT["state_marker"] = "stale"
                with self.assertRaisesRegex(fleet.FleetError, "durable remote revision"):
                    fleet.write_state("KleinPerkins/kp-mcp", state)
            fleet._REMOTE_LOCK_CONTEXT = None

    def test_qualification_requires_live_drained_generation_two(self) -> None:
        desired = fleet.render_rulesets("canary")
        state = fleet.state_seed(
            "KleinPerkins/kp-mcp",
            "main",
            "canary",
            "a" * 40,
            {key: False for key in fleet.policy()["settings"]},
        )
        canary_config = fleet.render_policy("KleinPerkins/kp-mcp", "canary")
        state["controller_digest"] = fleet.digest(
            fleet.render_controller(canary_config)
        )
        state["generation"] = 2
        state["lifecycle"] = "paused"
        state["history"].append(
            {"operation": "activate-canary", "generation": 2, "at": fleet.now()}
        )
        required_file = self.repo.path / ".github/workflows/required.yml"
        required_file.parent.mkdir(parents=True, exist_ok=True)
        required_file.write_text("name: required\n")
        subprocess.run(["git", "add", "."], cwd=self.repo.path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "required fixture"],
            cwd=self.repo.path,
            check=True,
            capture_output=True,
        )
        for index, key in enumerate(("merge_safety", "review_gate"), start=101):
            fingerprint = fleet.digest(fleet.normalize_ruleset(desired[key]))
            state["pair"][key] = {
                "id": index,
                "fingerprint": fingerprint,
                "owned": True,
            }
        proof = {
            "generation": 1,
            "pair_ids": {"merge_safety": 1, "review_gate": 2},
            "pair_fingerprints": {
                "merge_safety": "b" * 64,
                "review_gate": "c" * 64,
            },
            "target_branch": "canary-one",
            "target_sha": "e" * 40,
            "restored_settings_fingerprint": "f" * 64,
            "completed_at": fleet.now(),
        }
        proof["digest"] = fleet.digest(proof)
        state["rollback_proofs"] = [proof]
        evidence = {
            "schema": "pr-automation-evidence/v2",
            "owner_repo": state["owner_repo"],
            "generation": 2,
            "canary_branch": "canary",
            "canary_sha": "a" * 40,
            "destination_branch": "main",
            "controller_digests": {
                "canary": state["controller_digest"],
                "production": state["production_controller_digest"],
            },
            "policy_digest": state["policy_digest"],
            "ruleset_template_digests": state["template_digests"],
            "ruleset_ids": {
                key: state["pair"][key]["id"]
                for key in ("merge_safety", "review_gate")
            },
            "ruleset_fingerprints": {
                key: state["pair"][key]["fingerprint"]
                for key in ("merge_safety", "review_gate")
            },
            "required_check": {
                "context": "required / ci",
                "integration_id": 15368,
                "workflow_path": ".github/workflows/required.yml",
                "workflow_run_id": 88,
                "check_suite_id": 99,
                "check_run_id": 77,
                "head_sha": "d" * 40,
            },
            "observed_at": fleet.now(),
            "scenarios": [
                {
                    "id": item,
                    "mode": "live",
                    "outcome": "pass",
                    "evidence": "https://github.com/KleinPerkins/kp-mcp/actions/runs/88",
                }
                for item in fleet.SCENARIOS
            ],
        }
        live = {
            key: {
                "id": state["pair"][key]["id"],
                "fingerprint": state["pair"][key]["fingerprint"],
                "value": desired[key],
            }
            for key in ("merge_safety", "review_gate")
        }
        with tempfile.TemporaryDirectory() as state_tmp, tempfile.NamedTemporaryFile(
            mode="w", suffix=".json"
        ) as evidence_file:
            json.dump(evidence, evidence_file)
            evidence_file.flush()
            with (
                mock.patch.object(fleet, "STATE_DIR", Path(state_tmp)),
                mock.patch.object(fleet, "verify_local", return_value=[]),
                mock.patch.object(
                    fleet, "phase_b_config", return_value=canary_config
                ),
                mock.patch.object(fleet, "require_exact_head", return_value="a" * 40),
                mock.patch.object(fleet, "assert_remote_managed_files"),
                mock.patch.object(
                    fleet,
                    "gh_api",
                    side_effect=lambda endpoint, **_kwargs: (
                        {
                            "path": ".github/workflows/required.yml",
                            "name": "required",
                            "event": "pull_request",
                            "status": "completed",
                            "conclusion": "success",
                            "check_suite_id": 99,
                            "head_sha": "d" * 40,
                            "updated_at": evidence["observed_at"],
                            "pull_requests": [{"number": 12}],
                        }
                        if "/actions/runs/" in endpoint
                        else {
                            "base": {"ref": "canary"},
                            "head": {"sha": "d" * 40},
                        }
                        if "/pulls/" in endpoint
                        else {
                            "check_runs": [
                                {
                                    "id": 77,
                                    "name": "required / ci",
                                    "app": {"id": 15368},
                                    "conclusion": "success",
                                }
                            ]
                        }
                    ),
                ),
                mock.patch.object(fleet, "pair_live", return_value=live),
                mock.patch.object(
                    fleet,
                    "remote_file_bytes",
                    return_value=required_file.read_bytes(),
                ),
                mock.patch.object(
                    fleet,
                    "credential_metadata",
                    return_value={
                        "activation": {"name": "AUTOMERGE_ENABLED", "value": "false"}
                    },
                ),
                mock.patch.object(
                    fleet, "controller_workflow_state", return_value="disabled_manually"
                ),
                mock.patch.object(fleet, "armed_pulls", return_value=[]),
                mock.patch.object(fleet, "open_pulls", return_value=[]),
                mock.patch.object(fleet, "controller_runs", return_value=[]),
            ):
                fleet.write_state("KleinPerkins/kp-mcp", state)
                self.assertEqual(
                    fleet.cmd_qualify(
                        self.repo.path, evidence=Path(evidence_file.name)
                    ),
                    0,
                )
                qualified = fleet.read_state("KleinPerkins/kp-mcp")
                self.assertEqual(qualified["lifecycle"], "qualified")
                evidence["scenarios"][0]["mode"] = "mocked"
                Path(evidence_file.name).write_text(json.dumps(evidence))
                with self.assertRaisesRegex(fleet.FleetError, "must be live"):
                    fleet.validate_evidence(
                        Path(evidence_file.name),
                        state,
                        self.repo.path,
                        canary_config,
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
