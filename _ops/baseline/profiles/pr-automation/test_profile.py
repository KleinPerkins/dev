#!/usr/bin/env python3
from __future__ import annotations

import copy
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("pr_automation_profile", HERE / "profile.py")
assert SPEC and SPEC.loader
profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile)


class RepoFixture:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "demo"
        self.path.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=self.path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "--local", "user.name", "KleinPerkins"],
            cwd=self.path,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "config",
                "--local",
                "user.email",
                "49759187+KleinPerkins@users.noreply.github.com",
            ],
            cwd=self.path,
            check=True,
        )
        subprocess.run(
            ["git", "remote", "add", "origin", "git@github.com:KleinPerkins/demo.git"],
            cwd=self.path,
            check=True,
        )
        (self.path / ".github/scripts").mkdir(parents=True)
        (self.path / ".github/scripts/baseline-verify.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
        (self.path / ".github/CODEOWNERS").write_text(profile.BASELINE_CODEOWNERS.read_text())
        (self.path / "README.md").write_text("# demo\n")
        subprocess.run(["git", "add", "."], cwd=self.path, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.path, check=True, capture_output=True)
        self.sync_remote_tracking()

    def commit(self, message: str = "profile") -> None:
        subprocess.run(["git", "add", "."], cwd=self.path, check=True)
        subprocess.run(["git", "commit", "-m", message], cwd=self.path, check=True, capture_output=True)
        self.sync_remote_tracking()

    def sync_remote_tracking(self, branch: str | None = None) -> None:
        branch = branch or subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=self.path,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.path,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "update-ref", f"refs/remotes/origin/{branch}", sha],
            cwd=self.path,
            check=True,
        )
        subprocess.run(
            ["git", "branch", "--set-upstream-to", f"origin/{branch}", branch],
            cwd=self.path,
            check=True,
            capture_output=True,
        )

    def switch_new_branch(self, branch: str) -> str:
        subprocess.run(
            ["git", "switch", "-c", branch],
            cwd=self.path,
            check=True,
            capture_output=True,
        )
        self.sync_remote_tracking(branch)
        return profile.git(self.path, "rev-parse", "HEAD")

    def close(self) -> None:
        self.tmp.cleanup()


class FakeGitHub:
    default_repo_path: Path | None = None

    def __init__(self) -> None:
        assert self.default_repo_path is not None
        self.default_sha = profile.git(self.default_repo_path, "rev-parse", "HEAD")
        self.default_branch = "main"
        self.branches = {"main": self.default_sha}
        self.settings = {
            "allow_auto_merge": False,
            "delete_branch_on_merge": False,
            "allow_update_branch": False,
        }
        self.ruleset = None
        self.ruleset_id = None
        self.next_ruleset_id = 9001
        self.fail_next_settings_patch = False
        self.fail_after_settings_patch = False
        self.fail_next_graphql = False
        self.fail_after_ruleset_create = False
        self.fail_create_with_concurrent_exact = False
        self.fail_next_ruleset_detail_after_create = False
        self.fail_before_ruleset_put_status: int | None = None
        self.fail_after_ruleset_put_status: int | None = None
        self.merge_armed_on_disable = False
        self.open_pulls: list[dict] = []
        self.calls: list[tuple[str, str]] = []
        self.paginated_calls: list[str] = []

    def api(self, endpoint: str, *, method: str = "GET", payload=None, paginate: bool = False):
        method = method.upper()
        self.calls.append((method, endpoint))
        if paginate:
            self.paginated_calls.append(endpoint)
        if endpoint == "repos/KleinPerkins/demo" and method == "GET":
            return {
                "owner": {"login": "KleinPerkins"},
                "default_branch": self.default_branch,
                **self.settings,
            }
        if endpoint.startswith("repos/KleinPerkins/demo/branches/") and method == "GET":
            branch = endpoint.rsplit("/", 1)[1]
            sha = self.branches.get(branch)
            if sha is None:
                raise profile.ProfileError(f"target branch {branch!r} not found")
            return {"name": branch, "commit": {"sha": sha}}
        if endpoint == "repos/KleinPerkins/demo" and method == "PATCH":
            if self.fail_next_settings_patch:
                self.fail_next_settings_patch = False
                raise profile.ProfileError("simulated settings API failure")
            self.settings.update(payload)
            if payload.get("allow_auto_merge") is False and self.merge_armed_on_disable:
                for pull in self.open_pulls:
                    if pull.get("state") == "open" and pull.get("auto_merge"):
                        pull["state"] = "closed"
                        pull["merged"] = True
                        pull["auto_merge"] = None
            if self.fail_after_settings_patch:
                self.fail_after_settings_patch = False
                raise profile.ProfileError("simulated lost settings response")
            return {
                "owner": {"login": "KleinPerkins"},
                "default_branch": self.default_branch,
                **self.settings,
            }
        if endpoint == "repos/KleinPerkins/demo/rulesets?per_page=100" and method == "GET":
            return [] if self.ruleset is None else [
                {"id": self.ruleset_id, "name": profile.RULESET_NAME, "enforcement": self.ruleset["enforcement"]}
            ]
        if endpoint == "repos/KleinPerkins/demo/pulls?state=open&per_page=100" and method == "GET":
            return copy.deepcopy([pull for pull in self.open_pulls if pull.get("state") == "open"])
        if endpoint.startswith("repos/KleinPerkins/demo/pulls/") and method == "GET":
            number = int(endpoint.rsplit("/", 1)[1])
            pull = next(item for item in self.open_pulls if item["number"] == number)
            return copy.deepcopy(pull)
        if endpoint == "graphql" and method == "POST":
            if self.fail_next_graphql:
                self.fail_next_graphql = False
                raise profile.ProfileError("simulated GraphQL disarm failure")
            node_id = payload["variables"]["pullRequestId"]
            pull = next(item for item in self.open_pulls if item["node_id"] == node_id)
            pull["auto_merge"] = None
            return {
                "data": {
                    "disablePullRequestAutoMerge": {
                        "pullRequest": {"id": node_id, "autoMergeRequest": None}
                    }
                }
            }
        if endpoint == "repos/KleinPerkins/demo/rulesets" and method == "POST":
            if self.fail_create_with_concurrent_exact:
                self.fail_create_with_concurrent_exact = False
                self.ruleset_id = 9900
                self.ruleset = copy.deepcopy(payload)
                raise profile.ProfileError("simulated failed create plus concurrent exact create")
            self.ruleset_id = self.next_ruleset_id
            self.next_ruleset_id += 1
            self.ruleset = copy.deepcopy(payload)
            if self.fail_after_ruleset_create:
                self.fail_after_ruleset_create = False
                raise profile.ProfileError("simulated lost create response")
            return {"id": self.ruleset_id, **self.ruleset}
        if endpoint == f"repos/KleinPerkins/demo/rulesets/{self.ruleset_id}" and method == "GET":
            if self.ruleset is None:
                raise AssertionError("missing fake ruleset")
            if self.fail_next_ruleset_detail_after_create:
                self.fail_next_ruleset_detail_after_create = False
                raise profile.ProfileError("simulated lost ruleset verification")
            return {"id": self.ruleset_id, **copy.deepcopy(self.ruleset)}
        if endpoint == f"repos/KleinPerkins/demo/rulesets/{self.ruleset_id}" and method == "PUT":
            if self.fail_before_ruleset_put_status is not None:
                status = self.fail_before_ruleset_put_status
                self.fail_before_ruleset_put_status = None
                raise profile.ProfileError(f"simulated ruleset PUT HTTP {status}")
            self.ruleset = copy.deepcopy(payload)
            if self.fail_after_ruleset_put_status is not None:
                status = self.fail_after_ruleset_put_status
                self.fail_after_ruleset_put_status = None
                raise profile.ProfileError(f"simulated lost ruleset PUT HTTP {status}")
            return {"id": self.ruleset_id, **self.ruleset}
        if endpoint == f"repos/KleinPerkins/demo/rulesets/{self.ruleset_id}" and method == "DELETE":
            self.ruleset = None
            self.ruleset_id = None
            return None
        raise AssertionError(f"unexpected fake API call: {method} {endpoint}")


class ProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = RepoFixture()
        FakeGitHub.default_repo_path = self.repo.path
        self.fetch_patch = mock.patch.object(
            profile,
            "fetch_remote_branch_sha",
            side_effect=lambda repo, branch: profile.git(
                repo, "rev-parse", f"origin/{branch}"
            ),
        )
        self.fetch_patch.start()
        self.state_tmp = tempfile.TemporaryDirectory()
        self.state_patch = mock.patch.object(profile, "STATE_DIR", Path(self.state_tmp.name))
        self.state_patch.start()

    def tearDown(self) -> None:
        self.state_patch.stop()
        self.fetch_patch.stop()
        self.state_tmp.cleanup()
        self.repo.close()

    def apply_and_commit(self) -> None:
        self.assertEqual(profile.cmd_apply(self.repo.path, dry_run=False), 0)
        self.assertEqual(profile.cmd_apply(self.repo.path, dry_run=False), 0)
        self.repo.commit()
        self.assertEqual(profile.cmd_verify(self.repo.path), 0)

    def write_canary_proof(
        self,
        fake: FakeGitHub,
        *,
        destination: str = "main",
        mutate=None,
    ) -> Path:
        state = profile.read_state("KleinPerkins/demo")
        assert state and fake.ruleset_id and fake.ruleset
        scenarios = []
        mocked_allowed = {"conflict", "draft", "rollback"}
        for scenario_id in profile.CANARY_SCENARIOS:
            scenarios.append(
                {
                    "id": scenario_id,
                    "mode": "mocked" if scenario_id in mocked_allowed else "live",
                    "outcome": "pass",
                    "api_observation": f"verified {scenario_id} outcome",
                }
            )
        proof = {
            "schema": "pr-automation-canary-proof/v1",
            "owner_repo": "KleinPerkins/demo",
            "generation": state["ruleset_generation"],
            "owned_ruleset_id": fake.ruleset_id,
            "canary_branch": state["target_branch"],
            "canary_sha": state["target_sha"],
            "destination_branch": destination,
            "ruleset_fingerprint": profile.fingerprint(
                profile.normalize_ruleset(fake.ruleset)
            ),
            "settings_fingerprint": profile.fingerprint(fake.settings),
            "required_context": "required / ci",
            "integration_id": 15368,
            "observed_at": profile.dt.datetime.now(profile.dt.timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "scenarios": scenarios,
        }
        if mutate is not None:
            mutate(proof)
        path = Path(self.state_tmp.name) / f"proof-{len(list(Path(self.state_tmp.name).glob('proof-*')))}.json"
        path.write_text(json.dumps(proof))
        return path

    def prepare_recreated_canary(self, fake: FakeGitHub) -> Path:
        profile.cmd_enforce(
            self.repo.path, dry_run=False, target_branch="canary"
        )
        profile.cmd_rollback(self.repo.path, dry_run=False)
        profile.cmd_enforce(
            self.repo.path, dry_run=False, target_branch="canary"
        )
        return self.write_canary_proof(fake)

    def exercise_retarget_http_recovery(self, status: int, *, after_apply: bool) -> None:
        self.apply_and_commit()
        canary_sha = self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        fake.branches["canary"] = canary_sha
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            proof_path = self.prepare_recreated_canary(fake)
            subprocess.run(
                ["git", "switch", "main"],
                cwd=self.repo.path,
                check=True,
                capture_output=True,
            )
            if after_apply:
                fake.fail_after_ruleset_put_status = status
            else:
                fake.fail_before_ruleset_put_status = status
            with self.assertRaisesRegex(profile.ProfileError, f"HTTP {status}"):
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=False,
                    retarget="main",
                    canary_proof=str(proof_path),
                )
            state = profile.read_state("KleinPerkins/demo")
            assert state
            transition = state["pending_retarget"]
            self.assertEqual(transition["ruleset_id"], fake.ruleset_id)
            self.assertEqual(
                transition["preimage_fingerprint"],
                profile.fingerprint(transition["preimage"]),
            )
            self.assertEqual(
                transition["desired_fingerprint"],
                profile.fingerprint(transition["desired_postimage"]),
            )
            state_before_status = copy.deepcopy(state)
            status_output = io.StringIO()
            with contextlib.redirect_stdout(status_output):
                profile.cmd_status(self.repo.path)
            self.assertIn("proof gate:  READY", status_output.getvalue())
            self.assertEqual(
                profile.read_state("KleinPerkins/demo"),
                state_before_status,
            )
            puts_before_retry = sum(1 for method, _ in fake.calls if method == "PUT")
            self.assertEqual(
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=False,
                    retarget="main",
                ),
                0,
            )
            puts_after_retry = sum(1 for method, _ in fake.calls if method == "PUT")
            self.assertEqual(
                puts_after_retry,
                puts_before_retry if after_apply else puts_before_retry + 1,
            )
            state = profile.read_state("KleinPerkins/demo")
            self.assertEqual(state["target_stage"], "promoted")
            self.assertNotIn("pending_retarget", state)

    @staticmethod
    def armed_pull(number: int = 42, head_sha: str = "a" * 40) -> dict:
        return {
            "number": number,
            "node_id": f"PR_node_{number}",
            "html_url": f"https://github.com/KleinPerkins/demo/pull/{number}",
            "state": "open",
            "head": {"sha": head_sha},
            "auto_merge": {"enabled_by": {"login": "another-actor"}},
        }

    def test_schema_and_exact_literals(self) -> None:
        schema = json.loads(profile.SCHEMA_SOURCE.read_text())
        proof_schema = json.loads(profile.CANARY_PROOF_SCHEMA_SOURCE.read_text())
        config = profile.load_config()
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(proof_schema["additionalProperties"])
        self.assertEqual(
            proof_schema["properties"]["schema"]["const"],
            "pr-automation-canary-proof/v1",
        )
        self.assertEqual(
            proof_schema["properties"]["scenarios"]["minItems"],
            len(profile.CANARY_SCENARIOS),
        )
        self.assertEqual(config["required_check"]["integration_id"], 15368)
        self.assertEqual(config["required_check"]["context"], "required / ci")
        self.assertEqual(config["settings"], {key: True for key in profile.MANAGED_SETTINGS})

    def test_ruleset_is_separate_strict_and_squash_only(self) -> None:
        ruleset = profile.desired_ruleset("trunk")
        self.assertEqual(ruleset["name"], profile.RULESET_NAME)
        self.assertNotEqual(ruleset["name"], profile.HISTORY_RULESET_NAME)
        self.assertEqual(ruleset["conditions"]["ref_name"]["include"], ["refs/heads/trunk"])
        self.assertEqual(ruleset["bypass_actors"], [])
        pull = next(rule for rule in ruleset["rules"] if rule["type"] == "pull_request")
        checks = next(rule for rule in ruleset["rules"] if rule["type"] == "required_status_checks")
        self.assertEqual(pull["parameters"]["required_approving_review_count"], 0)
        self.assertTrue(pull["parameters"]["require_code_owner_review"])
        self.assertTrue(pull["parameters"]["required_review_thread_resolution"])
        self.assertEqual(pull["parameters"]["required_reviewers"], [])
        self.assertEqual(pull["parameters"]["allowed_merge_methods"], ["squash"])
        self.assertTrue(checks["parameters"]["strict_required_status_checks_policy"])
        self.assertEqual(
            checks["parameters"]["required_status_checks"],
            [{"context": "required / ci", "integration_id": 15368}],
        )

    def test_yaml_aggregator_and_full_sha(self) -> None:
        errors = profile.validate_aggregator(profile.WORKFLOW_SOURCE)
        self.assertEqual(errors, [])
        text = profile.WORKFLOW_SOURCE.read_text()
        self.assertNotIn("paths:", text)
        self.assertNotIn("branches:", text)

    def test_aggregator_adversarial_refusals(self) -> None:
        source = profile.WORKFLOW_SOURCE.read_text()
        cases = {
            "empty-needs": (
                source.replace(
                    "needs:\n      - discover\n      - baseline-source",
                    "needs:",
                ),
                "aggregator must have one non-empty static needs list",
            ),
            "missing-always": (
                source.replace("if: ${{ always() }}", "if: ${{ success() }}"),
                "aggregator must use exact if: ${{ always() }}",
            ),
            "skipped-assertion-step": (
                source.replace(
                    "        env:\n          DISCOVER_RESULT:",
                    "        if: github.actor == ''\n        env:\n          DISCOVER_RESULT:",
                ),
                "aggregator assertion step must not have a step-level if",
            ),
            "extra-unnamed-assertion-bypass": (
                source.replace(
                    "      - name: Require literal success",
                    "      - run: echo 'set +e' >> \"$BASH_ENV\"\n"
                    "      - name: Require literal success",
                ),
                "aggregator must contain exactly one total step",
            ),
            "filtered-trigger": (
                source.replace("  pull_request:\n", "  pull_request:\n    paths: ['src/**']\n"),
                "pull_request trigger must have no paths/branches filters",
            ),
            "continue-on-error": (
                source.replace("    runs-on: ubuntu-latest\n", "    continue-on-error: true\n    runs-on: ubuntu-latest\n", 1),
                "continue-on-error is forbidden anywhere in the required workflow",
            ),
            "missing-result-check": (
                source.replace('          test "$DISCOVER_RESULT" = "success"\n', ""),
                "dependency discover is not tested for exact literal success",
            ),
            "success-test-bypass": (
                source.replace(
                    '          test "$DISCOVERY_COUNT" -gt 0\n',
                    '          test "$DISCOVERY_COUNT" -gt 0\n          exit 0\n',
                ),
                "aggregator run script must contain only exact success and positive-count tests",
            ),
            "missing-positive-count": (
                source.replace('          test "$DISCOVERY_COUNT" -gt 0\n', ""),
                "discovery count is not explicitly tested as positive",
            ),
            "unsafe-expression": (
                source.replace(
                    "${{ needs.discover.outputs.count }}",
                    "${{ github.event.pull_request.number }}",
                    1,
                ),
                "unsafe/dynamic expressions in aggregator",
            ),
            "step-tag-pin": (
                source.replace(
                    "actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5",
                    "actions/checkout@v4",
                ),
                "uses target is not pinned to a full SHA",
            ),
            "local-unpinned-use": (
                source.replace(
                    "      - id: discover\n",
                    "      - uses: ./.github/actions/discover\n      - id: discover\n",
                ),
                "uses target lacks immutable full-SHA ref",
            ),
            "job-workflow-tag-pin": (
                source + "\n  reusable:\n    uses: owner/repo/.github/workflows/reuse.yml@main\n",
                "uses target is not pinned to a full SHA",
            ),
            "duplicate-required-name": (
                source + "\n  duplicate:\n    name: required / ci\n    runs-on: ubuntu-latest\n",
                "expected exactly one unambiguous 'required / ci' job; found 2",
            ),
            "duplicate-job-id": (
                source + "\n  ci:\n    name: harmless duplicate\n    runs-on: ubuntu-latest\n",
                "duplicate job id: ci",
            ),
            "duplicate-top-level-jobs": (
                source + "\njobs:\n  extra:\n    runs-on: ubuntu-latest\n",
                "expected exactly one top-level jobs mapping; found 2",
            ),
            "quoted-filter-key": (
                source.replace("  pull_request:\n", "  pull_request:\n    'paths': ['src/**']\n"),
                "quoted critical workflow keys are not allowed",
            ),
            "legal-flow-job-with-nested-tag-use": (
                source + (
                    "\n  supply-chain: {name: required / ci, runs-on: ubuntu-latest, "
                    "steps: [{uses: actions/checkout@v4}]}\n"
                ),
                "flow-style/inline YAML is unsupported",
            ),
            "flow-step-full-sha-still-unsupported": (
                source.replace(
                    "      - id: discover\n",
                    "      - {uses: actions/checkout@"
                    "34e114876b0b11c390a56381ad16ebd13914f8d5}\n"
                    "      - id: discover\n",
                ),
                "unsupported or inline step entry",
            ),
            "unicode-escaped-shell-exit-bypass": (
                source.replace(
                    "        env:\n",
                    '        shell: "bash \\u007b0\\u007d || true"\n        env:\n',
                    1,
                ),
                "custom shell is forbidden",
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, (content, expected) in cases.items():
                broken = Path(tmp) / f"{name}.yml"
                broken.write_text(content)
                self.assertTrue(
                    any(expected in error for error in profile.validate_aggregator(broken)),
                    msg=f"{name}: {profile.validate_aggregator(broken)}",
                )

    def test_actionlint_valid_unicode_shell_bypass_is_rejected(self) -> None:
        if not shutil.which("actionlint"):
            self.skipTest("actionlint unavailable")
        fixture = profile.WORKFLOW_SOURCE.read_text().replace(
            "        env:\n",
            '        shell: "bash \\u007b0\\u007d || true"\n        env:\n',
            1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unicode-shell.yml"
            path.write_text(fixture)
            lint = subprocess.run(["actionlint", str(path)], text=True, capture_output=True)
            self.assertEqual(lint.returncode, 0, msg=lint.stderr or lint.stdout)
            errors = profile.validate_aggregator(path)
            self.assertTrue(any("custom shell is forbidden" in error for error in errors))

    def test_second_flow_style_required_producer_is_detected_and_rejected(self) -> None:
        self.apply_and_commit()
        second = self.repo.path / ".github/workflows/second.yml"
        second.write_text(
            "name: second producer\n"
            "on:\n"
            "  pull_request:\n"
            "jobs:\n"
            "  supply-chain: {name: required / ci, runs-on: ubuntu-latest, "
            "steps: [{run: 'true'}]}\n"
        )
        errors, aggregator = profile.local_status(self.repo.path)
        self.assertIsNone(aggregator)
        self.assertTrue(any("multiple workflows can produce" in error for error in errors))
        self.assertTrue(any(
            "second.yml" in error and "flow-style/inline YAML is unsupported" in error
            for error in errors
        ))

    def test_unicode_decoded_required_producer_is_not_invisible(self) -> None:
        self.apply_and_commit()
        second = self.repo.path / ".github/workflows/decoded.yml"
        second.write_text(
            "name: decoded producer\n"
            "on:\n"
            "  pull_request:\n"
            "jobs:\n"
            "  decoded:\n"
            '    name: "required \\u002f ci"\n'
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: 'true'\n"
        )
        self.assertTrue(profile.workflow_mentions_required_job(second))
        errors, aggregator = profile.local_status(self.repo.path)
        self.assertIsNone(aggregator)
        self.assertTrue(any("multiple workflows can produce" in error for error in errors))

    def test_actionlint_accepts_legal_flow_fixture_that_profile_refuses(self) -> None:
        if not shutil.which("actionlint"):
            self.skipTest("actionlint unavailable")
        fixture = profile.WORKFLOW_SOURCE.read_text() + (
            "\n  supply-chain: {name: supply chain, runs-on: ubuntu-latest, "
            "steps: [{uses: actions/checkout@v4}]}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "flow.yml"
            path.write_text(fixture)
            result = subprocess.run(
                ["actionlint", str(path)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
            self.assertTrue(any(
                "flow-style/inline YAML is unsupported" in error
                for error in profile.validate_aggregator(path)
            ))

    def test_semantic_normalization_and_fingerprint(self) -> None:
        left = profile.desired_ruleset("main")
        right = copy.deepcopy(left)
        right["id"] = 12
        right["created_at"] = "volatile"
        right["rules"].reverse()
        right["bypass_actors"].reverse()
        self.assertEqual(profile.normalize_ruleset(left), profile.normalize_ruleset(right))
        self.assertEqual(
            profile.fingerprint(profile.normalize_ruleset(left)),
            profile.fingerprint(profile.normalize_ruleset(right)),
        )

    def test_apply_is_local_only_idempotent_and_replaces_broad_baseline_owner(self) -> None:
        with mock.patch.object(profile, "gh_api", side_effect=AssertionError("network call")):
            self.assertEqual(profile.cmd_apply(self.repo.path, dry_run=True), 0)
            self.assertFalse((self.repo.path / profile.CONFIG_REL).exists())
            self.assertEqual(profile.cmd_apply(self.repo.path, dry_run=False), 0)
            self.assertEqual(profile.cmd_apply(self.repo.path, dry_run=False), 0)
        codeowners = (self.repo.path / profile.CODEOWNERS_REL).read_text()
        self.assertNotIn("\n* @KleinPerkins\n", "\n" + codeowners)
        self.assertIn("/.github/workflows/** @KleinPerkins", codeowners)

    def test_apply_refuses_conflicts_and_dirty_mutation(self) -> None:
        destination = self.repo.path / profile.WORKFLOW_REL
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("name: custom\n")
        with self.assertRaises(profile.ProfileError):
            profile.cmd_apply(self.repo.path, dry_run=False)
        destination.unlink()
        (self.repo.path / "README.md").write_text("dirty\n")
        with self.assertRaises(profile.ProfileError):
            profile.cmd_apply(self.repo.path, dry_run=False)

    def test_remote_lifecycle_preimages_drift_refusal_and_rollback(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            self.assertEqual(profile.cmd_enforce(self.repo.path, dry_run=True), 0)
            self.assertFalse(any(method in profile.MUTATING_METHODS for method, _ in fake.calls))
            fake.calls.clear()
            self.assertEqual(profile.cmd_enforce(self.repo.path, dry_run=False), 0)
            state = profile.read_state("KleinPerkins/demo")
            self.assertIsNotNone(state)
            assert state
            self.assertEqual(state["rollback_preimage"]["settings"], {
                "allow_auto_merge": False,
                "delete_branch_on_merge": False,
                "allow_update_branch": False,
            })
            self.assertEqual(state["ruleset_id"], 9001)
            self.assertEqual(len(state["managed_post_fingerprints"]["ruleset"]), 64)
            before = len(fake.calls)
            self.assertEqual(profile.cmd_enforce(self.repo.path, dry_run=False), 0)
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[before:]
            ))
            self.assertEqual(profile.cmd_pause(self.repo.path, dry_run=False), 0)
            self.assertEqual(fake.ruleset["enforcement"], "active")
            self.assertFalse(fake.settings["allow_auto_merge"])
            before = len(fake.calls)
            self.assertEqual(profile.cmd_pause(self.repo.path, dry_run=False), 0)
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[before:]
            ))
            self.assertEqual(profile.cmd_repair(self.repo.path, dry_run=False), 0)
            self.assertEqual(fake.ruleset["enforcement"], "active")
            self.assertTrue(fake.settings["allow_auto_merge"])
            before = len(fake.calls)
            self.assertEqual(profile.cmd_repair(self.repo.path, dry_run=False), 0)
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[before:]
            ))
            self.assertEqual(profile.cmd_rollback(self.repo.path, dry_run=False), 0)
            self.assertIsNone(fake.ruleset)
            self.assertEqual(fake.settings["allow_auto_merge"], False)
            before = len(fake.calls)
            self.assertEqual(profile.cmd_rollback(self.repo.path, dry_run=False), 0)
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[before:]
            ))
            self.assertTrue(all(profile.HISTORY_RULESET_NAME not in endpoint for _, endpoint in fake.calls))

    def test_optimistic_drift_refuses_out_of_band_change(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            fake.settings["allow_update_branch"] = False
            before = len(fake.calls)
            with self.assertRaises(profile.ProfileError):
                profile.cmd_pause(self.repo.path, dry_run=False)
            mutating = [call for call in fake.calls[before:] if call[0] in profile.MUTATING_METHODS]
            self.assertEqual(mutating, [])

    def test_partial_enforce_failure_advances_managed_postimage_for_safe_retry(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        fake.fail_next_settings_patch = True
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            with self.assertRaises(profile.ProfileError):
                profile.cmd_enforce(self.repo.path, dry_run=False)
            state = profile.read_state("KleinPerkins/demo")
            self.assertIsNotNone(state)
            assert state
            self.assertEqual(state["last_operation"], "enforce-ruleset")
            self.assertEqual(fake.ruleset["enforcement"], "active")
            self.assertFalse(fake.settings["allow_auto_merge"])
            self.assertEqual(profile.cmd_enforce(self.repo.path, dry_run=False), 0)
            self.assertTrue(fake.settings["allow_auto_merge"])

    def test_enforce_settings_response_loss_resumes_exact_postimage(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        fake.fail_after_settings_patch = True
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            with self.assertRaisesRegex(profile.ProfileError, "lost settings response"):
                profile.cmd_enforce(self.repo.path, dry_run=False)
            state = profile.read_state("KleinPerkins/demo")
            assert state
            self.assertEqual(state["enforce_phase"], "settings_pending")
            self.assertEqual(
                state["pending_settings_transition"]["desired"],
                profile.load_config()["settings"],
            )
            patches = sum(1 for method, endpoint in fake.calls if method == "PATCH")
            fake.settings["allow_update_branch"] = False
            before = len(fake.calls)
            with self.assertRaisesRegex(profile.ProfileError, "neither stored preimage"):
                profile.cmd_enforce(self.repo.path, dry_run=False)
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[before:]
            ))
            fake.settings["allow_update_branch"] = True
            self.assertEqual(profile.cmd_enforce(self.repo.path, dry_run=False), 0)
            self.assertEqual(
                sum(1 for method, endpoint in fake.calls if method == "PATCH"),
                patches,
            )
            self.assertEqual(profile.read_state("KleinPerkins/demo")["lifecycle"], "active")

    def test_pause_closes_gate_before_disarming_and_keeps_ruleset_active(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            fake.open_pulls = [self.armed_pull()]
            before = len(fake.calls)
            self.assertEqual(profile.cmd_pause(self.repo.path, dry_run=True), 0)
            self.assertTrue(fake.settings["allow_auto_merge"])
            self.assertIsNotNone(fake.open_pulls[0]["auto_merge"])
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[before:]
            ))
            fake.calls.clear()
            self.assertEqual(profile.cmd_pause(self.repo.path, dry_run=False), 0)
            self.assertEqual(fake.ruleset["enforcement"], "active")
            self.assertFalse(fake.settings["allow_auto_merge"])
            self.assertIsNone(fake.open_pulls[0]["auto_merge"])
            mutating = [call for call in fake.calls if call[0] in profile.MUTATING_METHODS]
            self.assertEqual(mutating[0], ("PATCH", "repos/KleinPerkins/demo"))
            self.assertEqual(mutating[1], ("POST", "graphql"))
            self.assertLess(
                fake.calls.index(("PATCH", "repos/KleinPerkins/demo")),
                fake.calls.index(
                    ("GET", "repos/KleinPerkins/demo/pulls?state=open&per_page=100")
                ),
            )
            self.assertFalse(any(
                method == "PUT" and "/rulesets/" in endpoint for method, endpoint in mutating
            ))

    def test_pause_disarm_failure_is_resumable_without_weakening_ruleset(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            fake.open_pulls = [self.armed_pull()]
            fake.fail_next_graphql = True
            with self.assertRaisesRegex(profile.ProfileError, "simulated GraphQL disarm failure"):
                profile.cmd_pause(self.repo.path, dry_run=False)
            state = profile.read_state("KleinPerkins/demo")
            assert state
            self.assertEqual(state["lifecycle"], "pausing")
            self.assertEqual(state["pause_phase"], "disarming")
            self.assertFalse(fake.settings["allow_auto_merge"])
            self.assertEqual(fake.ruleset["enforcement"], "active")
            self.assertEqual(profile.cmd_pause(self.repo.path, dry_run=False), 0)
            self.assertIsNone(fake.open_pulls[0]["auto_merge"])
            self.assertEqual(fake.ruleset["enforcement"], "active")

    def test_pause_may_observe_eligible_pr_merge_during_safe_transition(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            fake.open_pulls = [self.armed_pull()]
            fake.merge_armed_on_disable = True
            self.assertEqual(profile.cmd_pause(self.repo.path, dry_run=False), 0)
            self.assertTrue(fake.open_pulls[0]["merged"])
            self.assertFalse(fake.settings["allow_auto_merge"])
            self.assertEqual(fake.ruleset["enforcement"], "active")
            self.assertEqual(profile.open_armed_auto_merges("KleinPerkins/demo"), [])

    def test_pause_disarm_refuses_exact_head_change(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        exact_reads = 0

        def racing_api(endpoint: str, **kwargs):
            nonlocal exact_reads
            if endpoint == "repos/KleinPerkins/demo/pulls/42":
                exact_reads += 1
                if exact_reads == 1:
                    fake.open_pulls[0]["head"]["sha"] = "b" * 40
            return fake.api(endpoint, **kwargs)

        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=racing_api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            fake.open_pulls = [self.armed_pull()]
            with self.assertRaisesRegex(profile.ProfileError, "identity/head/armed state changed"):
                profile.cmd_pause(self.repo.path, dry_run=False)
            self.assertFalse(fake.settings["allow_auto_merge"])
            self.assertEqual(fake.ruleset["enforcement"], "active")
            self.assertIsNotNone(fake.open_pulls[0]["auto_merge"])

    def test_pause_fails_closed_when_pull_listing_omits_auto_merge_state(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            pull = self.armed_pull()
            del pull["auto_merge"]
            fake.open_pulls = [pull]
            before = len(fake.calls)
            with self.assertRaisesRegex(profile.ProfileError, "omitted auto_merge state"):
                profile.cmd_pause(self.repo.path, dry_run=False)
            self.assertFalse(fake.settings["allow_auto_merge"])
            self.assertEqual(fake.ruleset["enforcement"], "active")
            self.assertEqual(
                [call for call in fake.calls[before:] if call[0] in profile.MUTATING_METHODS],
                [("PATCH", "repos/KleinPerkins/demo")],
            )

    def test_pause_dry_run_does_not_advance_resumable_state(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            state = profile.read_state("KleinPerkins/demo")
            assert state
            state["lifecycle"] = "pausing"
            state["pause_phase"] = "settings_pending"
            profile.write_state("KleinPerkins/demo", state)
            fake.settings["allow_auto_merge"] = False
            path = profile.state_path("KleinPerkins/demo")
            before = path.read_text()
            call_index = len(fake.calls)
            self.assertEqual(profile.cmd_pause(self.repo.path, dry_run=True), 0)
            self.assertEqual(path.read_text(), before)
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[call_index:]
            ))

    def test_rollback_second_mutation_failure_is_resumable(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            fake.fail_next_settings_patch = True
            with self.assertRaisesRegex(profile.ProfileError, "simulated settings API failure"):
                profile.cmd_rollback(self.repo.path, dry_run=False)
            state = profile.read_state("KleinPerkins/demo")
            assert state
            self.assertEqual(state["lifecycle"], "rolling_back")
            self.assertEqual(state["rollback_phase"], "settings_pending")
            self.assertIsNone(fake.ruleset)
            self.assertTrue(fake.settings["allow_auto_merge"])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                profile.cmd_status(self.repo.path)
            self.assertIn("lifecycle:   rolling_back:settings_pending", output.getvalue())
            self.assertIn("managed:     CURRENT", output.getvalue())
            self.assertEqual(profile.cmd_rollback(self.repo.path, dry_run=False), 0)
            state = profile.read_state("KleinPerkins/demo")
            assert state
            self.assertEqual(state["lifecycle"], "rolled_back")
            self.assertEqual(state["rollback_phase"], "complete")
            self.assertFalse(fake.settings["allow_auto_merge"])

    def test_rollback_from_paused_postimage_restores_original_state(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            profile.cmd_pause(self.repo.path, dry_run=False)
            state = profile.read_state("KleinPerkins/demo")
            assert state
            self.assertEqual(
                state["managed_postimage"]["settings"],
                {
                    "allow_auto_merge": False,
                    "delete_branch_on_merge": True,
                    "allow_update_branch": True,
                },
            )
            self.assertEqual(
                state["managed_postimage"]["ruleset"]["enforcement"],
                "active",
            )
            self.assertEqual(profile.cmd_rollback(self.repo.path, dry_run=False), 0)
            self.assertIsNone(fake.ruleset)
            self.assertEqual(fake.settings, {
                "allow_auto_merge": False,
                "delete_branch_on_merge": False,
                "allow_update_branch": False,
            })

    def test_repair_settings_response_loss_resumes_exact_postimage(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            profile.cmd_pause(self.repo.path, dry_run=False)
            fake.fail_after_settings_patch = True
            with self.assertRaisesRegex(profile.ProfileError, "lost settings response"):
                profile.cmd_repair(self.repo.path, dry_run=False)
            state = profile.read_state("KleinPerkins/demo")
            assert state
            self.assertEqual(state["lifecycle"], "repairing")
            self.assertEqual(state["repair_phase"], "settings_pending")
            patches = sum(1 for method, endpoint in fake.calls if method == "PATCH")
            self.assertEqual(profile.cmd_repair(self.repo.path, dry_run=False), 0)
            self.assertEqual(
                sum(1 for method, endpoint in fake.calls if method == "PATCH"),
                patches,
            )
            self.assertEqual(profile.read_state("KleinPerkins/demo")["lifecycle"], "active")

    def test_rollback_treats_already_absent_task_created_ruleset_as_completed_phase(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            state = profile.read_state("KleinPerkins/demo")
            assert state
            state["lifecycle"] = "rolling_back"
            state["rollback_phase"] = "ruleset_pending"
            profile.write_state("KleinPerkins/demo", state)
            fake.ruleset = None
            fake.ruleset_id = None
            self.assertEqual(profile.cmd_rollback(self.repo.path, dry_run=False), 0)
            self.assertFalse(fake.settings["allow_auto_merge"])
            state = profile.read_state("KleinPerkins/demo")
            assert state
            self.assertEqual(state["rollback_phase"], "complete")

    def test_rollback_settings_phase_refuses_out_of_band_drift(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            fake.fail_next_settings_patch = True
            with self.assertRaises(profile.ProfileError):
                profile.cmd_rollback(self.repo.path, dry_run=False)
            fake.settings["delete_branch_on_merge"] = False
            before = len(fake.calls)
            with self.assertRaisesRegex(profile.ProfileError, "stored managed postimage"):
                profile.cmd_rollback(self.repo.path, dry_run=False)
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[before:]
            ))
            fake.settings["delete_branch_on_merge"] = True
            self.assertEqual(profile.cmd_rollback(self.repo.path, dry_run=False), 0)

    def test_resource_id_replacement_is_refused_even_with_same_semantics(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            fake.ruleset_id = 9999
            before = len(fake.calls)
            with self.assertRaisesRegex(profile.ProfileError, "stored ruleset id 9001 != live id 9999"):
                profile.cmd_pause(self.repo.path, dry_run=False)
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[before:]
            ))

    def test_immediate_prewrite_reread_refuses_create_race(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        ruleset_lists = 0

        def racing_api(endpoint: str, **kwargs):
            nonlocal ruleset_lists
            if endpoint == "repos/KleinPerkins/demo/rulesets?per_page=100":
                ruleset_lists += 1
                if ruleset_lists == 3:
                    fake.ruleset_id = 7777
                    fake.ruleset = profile.desired_ruleset("main")
            return fake.api(endpoint, **kwargs)

        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=racing_api),
        ):
            with self.assertRaisesRegex(profile.ProfileError, "expected ruleset id None, found 7777"):
                profile.cmd_enforce(self.repo.path, dry_run=False)
        self.assertFalse(any(method in profile.MUTATING_METHODS for method, _ in fake.calls))

    def test_initial_enforce_reread_failure_retries_from_initializing_state(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            with mock.patch.object(
                profile,
                "expect_ruleset_now",
                side_effect=profile.ProfileError("simulated first reread failure"),
            ):
                with self.assertRaisesRegex(profile.ProfileError, "simulated first reread failure"):
                    profile.cmd_enforce(self.repo.path, dry_run=False)
            state = profile.read_state("KleinPerkins/demo")
            assert state
            self.assertEqual(state["lifecycle"], "initializing")
            self.assertEqual(state["enforce_phase"], "pre_mutation")
            self.assertEqual(
                state["managed_post_fingerprints"]["settings"],
                profile.fingerprint(profile.normalize_settings(fake.settings)),
            )
            self.assertFalse(any(method in profile.MUTATING_METHODS for method, _ in fake.calls))
            self.assertEqual(profile.cmd_enforce(self.repo.path, dry_run=False), 0)
            self.assertTrue(fake.settings["allow_auto_merge"])

    def test_create_committed_response_lost_is_ownership_ambiguous(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        fake.fail_after_ruleset_create = True
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            with self.assertRaisesRegex(profile.ProfileError, "ownership is ambiguous"):
                profile.cmd_enforce(self.repo.path, dry_run=False)
            state = profile.read_state("KleinPerkins/demo")
            assert state
            self.assertEqual(state["lifecycle"], "ownership_ambiguous")
            self.assertEqual(state["enforce_phase"], "ruleset_create_ambiguous")
            self.assertIsNone(state["ruleset_id"])
            self.assertIsNone(state["owned_ruleset_id"])
            self.assertEqual(fake.ruleset_id, 9001)
            before = len(fake.calls)
            with self.assertRaisesRegex(profile.ProfileError, "refusing adoption"):
                profile.cmd_enforce(self.repo.path, dry_run=False)
            with self.assertRaisesRegex(profile.ProfileError, "will never delete"):
                profile.cmd_rollback(self.repo.path, dry_run=False)
            self.assertFalse(any(
                method == "DELETE" for method, _ in fake.calls[before:]
            ))
            self.assertIsNotNone(fake.ruleset)

    def test_failed_create_plus_concurrent_exact_create_is_never_adopted(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        fake.fail_create_with_concurrent_exact = True
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            with self.assertRaisesRegex(profile.ProfileError, "ownership is ambiguous"):
                profile.cmd_enforce(self.repo.path, dry_run=False)
            state = profile.read_state("KleinPerkins/demo")
            assert state
            self.assertEqual(state["lifecycle"], "ownership_ambiguous")
            self.assertIsNone(state["owned_ruleset_id"])
            self.assertEqual(fake.ruleset_id, 9900)
            with self.assertRaisesRegex(profile.ProfileError, "will never delete"):
                profile.cmd_rollback(self.repo.path, dry_run=False)
            self.assertIsNotNone(fake.ruleset)

    def test_returned_create_id_allows_postverification_retry(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        fake.fail_next_ruleset_detail_after_create = True
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            with self.assertRaisesRegex(profile.ProfileError, "lost ruleset verification"):
                profile.cmd_enforce(self.repo.path, dry_run=False)
            state = profile.read_state("KleinPerkins/demo")
            assert state
            self.assertEqual(state["ruleset_id"], 9001)
            self.assertEqual(state["owned_ruleset_id"], 9001)
            self.assertEqual(state["enforce_phase"], "ruleset_pending")
            self.assertEqual(profile.cmd_enforce(self.repo.path, dry_run=False), 0)
            self.assertEqual(profile.read_state("KleinPerkins/demo")["lifecycle"], "active")

    def test_ruleset_and_pull_discovery_are_paginated(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            profile.cmd_pause(self.repo.path, dry_run=True)
        self.assertIn("repos/KleinPerkins/demo/rulesets?per_page=100", fake.paginated_calls)
        self.assertIn("repos/KleinPerkins/demo/pulls?state=open&per_page=100", fake.paginated_calls)

    def test_status_reports_lifecycle_managed_and_desired_separately(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            profile.cmd_pause(self.repo.path, dry_run=False)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                profile.cmd_status(self.repo.path)
        rendered = output.getvalue()
        self.assertIn("lifecycle:   paused", rendered)
        self.assertIn("managed:     CURRENT", rendered)
        self.assertIn("desired:     PAUSED", rendered)

    def test_status_is_strictly_read_only(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            self.assertEqual(profile.cmd_status(self.repo.path), 0)
        self.assertTrue(fake.calls)
        self.assertTrue(all(method == "GET" for method, _ in fake.calls))

    def test_enforce_refuses_non_default_local_branch(self) -> None:
        self.apply_and_commit()
        subprocess.run(["git", "switch", "-c", "feature"], cwd=self.repo.path, check=True, capture_output=True)
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            with self.assertRaises(profile.ProfileError):
                profile.cmd_enforce(self.repo.path, dry_run=True)
        self.assertTrue(all(method == "GET" for method, _ in fake.calls))

    def test_remote_mutation_refuses_local_head_ahead_of_upstream(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "local ahead"],
            cwd=self.repo.path,
            check=True,
            capture_output=True,
        )
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            before = len(fake.calls)
            with self.assertRaisesRegex(profile.ProfileError, "must match exactly"):
                profile.cmd_enforce(self.repo.path, dry_run=False)
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[before:]
            ))

    def test_remote_mutation_refuses_stale_head_behind_upstream_and_github(self) -> None:
        self.apply_and_commit()
        old_sha = profile.git(self.repo.path, "rev-parse", "HEAD")
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", "remote ahead"],
            cwd=self.repo.path,
            check=True,
            capture_output=True,
        )
        new_sha = profile.git(self.repo.path, "rev-parse", "HEAD")
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", new_sha],
            cwd=self.repo.path,
            check=True,
        )
        subprocess.run(
            ["git", "reset", "--hard", old_sha],
            cwd=self.repo.path,
            check=True,
            capture_output=True,
        )
        fake = FakeGitHub()
        fake.default_sha = new_sha
        fake.branches["main"] = new_sha
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            with self.assertRaisesRegex(profile.ProfileError, "must match exactly"):
                profile.cmd_enforce(self.repo.path, dry_run=False)
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls
            ))

    def test_remote_mutation_refuses_github_head_newer_than_tracking_ref(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        fake.default_sha = "f" * 40
        fake.branches["main"] = fake.default_sha
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            with self.assertRaisesRegex(profile.ProfileError, "must match exactly"):
                profile.cmd_enforce(self.repo.path, dry_run=False)
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls
            ))

    def test_canary_target_missing_branch_refuses_without_mutation(self) -> None:
        self.apply_and_commit()
        self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            with self.assertRaisesRegex(profile.ProfileError, "not found"):
                profile.cmd_enforce(
                    self.repo.path, dry_run=False, target_branch="canary"
                )
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls
            ))

    def test_canary_target_stale_local_head_refuses_without_mutation(self) -> None:
        self.apply_and_commit()
        canary_sha = self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        fake.branches["canary"] = "f" * 40 if canary_sha != "f" * 40 else "e" * 40
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            with self.assertRaisesRegex(profile.ProfileError, "must match exactly"):
                profile.cmd_enforce(
                    self.repo.path, dry_run=False, target_branch="canary"
                )
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls
            ))

    def test_canary_target_stale_fetched_ref_refuses_without_mutation(self) -> None:
        self.apply_and_commit()
        canary_sha = self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        fake.branches["canary"] = canary_sha
        stale_fetch = "f" * 40 if canary_sha != "f" * 40 else "e" * 40
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
            mock.patch.object(profile, "fetch_remote_branch_sha", return_value=stale_fetch),
        ):
            with self.assertRaisesRegex(profile.ProfileError, "must match exactly"):
                profile.cmd_enforce(
                    self.repo.path, dry_run=False, target_branch="canary"
                )
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls
            ))

    def test_non_head_and_wildcard_targets_are_rejected(self) -> None:
        for target in (
            "refs/heads/canary",
            "origin/canary",
            "release/*",
            "HEAD",
            "a" * 40,
        ):
            with self.subTest(target=target), self.assertRaises(profile.ProfileError):
                profile.validate_head_branch(target)

    def test_managed_lifecycle_refuses_default_branch_identity_change(self) -> None:
        self.apply_and_commit()
        fake = FakeGitHub()
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            profile.cmd_enforce(self.repo.path, dry_run=False)
            fake.default_branch = "trunk"
            fake.branches["trunk"] = fake.branches["main"]
            before = len(fake.calls)
            with self.assertRaisesRegex(profile.ProfileError, "default branch changed"):
                profile.cmd_pause(self.repo.path, dry_run=False)
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[before:]
            ))

    def test_canary_same_name_unowned_ruleset_is_never_adopted(self) -> None:
        self.apply_and_commit()
        canary_sha = self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        fake.branches["canary"] = canary_sha
        fake.ruleset_id = 8800
        fake.ruleset = profile.desired_ruleset("canary")
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            with self.assertRaisesRegex(profile.ProfileError, "not owned"):
                profile.cmd_enforce(
                    self.repo.path, dry_run=False, target_branch="canary"
                )
            self.assertEqual(fake.ruleset_id, 8800)
            self.assertFalse(any(method == "PUT" for method, _ in fake.calls))

    def test_canary_rollback_reenforce_and_same_id_promotion(self) -> None:
        self.apply_and_commit()
        canary_sha = self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        fake.branches["canary"] = canary_sha
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            initial_dry_run = io.StringIO()
            with contextlib.redirect_stdout(initial_dry_run):
                self.assertEqual(profile.cmd_enforce(
                    self.repo.path, dry_run=True, target_branch="canary"
                ), 0)
            self.assertIn("target branch: canary", initial_dry_run.getvalue())
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls
            ))
            self.assertEqual(profile.cmd_enforce(
                self.repo.path, dry_run=False, target_branch="canary"
            ), 0)
            first_id = fake.ruleset_id
            self.assertEqual(
                profile.read_state("KleinPerkins/demo")["target_stage"], "canary"
            )
            subprocess.run(
                ["git", "switch", "main"],
                cwd=self.repo.path,
                check=True,
                capture_output=True,
            )
            with self.assertRaisesRegex(profile.ProfileError, "prior exact rollback"):
                profile.cmd_enforce(
                    self.repo.path, dry_run=True, retarget="main"
                )
            subprocess.run(
                ["git", "switch", "canary"],
                cwd=self.repo.path,
                check=True,
                capture_output=True,
            )
            generation_one_state = profile.read_state("KleinPerkins/demo")
            generation_one_state["canary_proof"] = {
                "schema": "pr-automation-canary-proof-summary/v1",
                "digest": "f" * 64,
                "generation": 1,
            }
            profile.write_state("KleinPerkins/demo", generation_one_state)
            self.assertEqual(profile.cmd_rollback(self.repo.path, dry_run=False), 0)
            state = profile.read_state("KleinPerkins/demo")
            self.assertEqual(state["target_stage"], "canary_rolled_back")
            self.assertEqual(state["last_deleted_ruleset_id"], first_id)
            rollback_proof = state["rollback_proofs"][0]
            self.assertEqual(rollback_proof["generation"], 1)
            self.assertEqual(rollback_proof["ruleset_id"], first_id)
            self.assertEqual(
                rollback_proof["restored_preimage"],
                state["rollback_preimage"],
            )
            self.assertEqual(
                rollback_proof["digest"],
                profile.rollback_proof_digest(rollback_proof),
            )
            self.assertTrue(all(
                len(value) == 64
                for value in rollback_proof["managed_pre_fingerprints"].values()
            ))
            self.assertTrue(all(
                len(value) == 64
                for value in rollback_proof["restored_post_fingerprints"].values()
            ))
            self.assertEqual(profile.cmd_enforce(
                self.repo.path, dry_run=False, target_branch="canary"
            ), 0)
            second_id = fake.ruleset_id
            self.assertNotEqual(second_id, first_id)
            self.assertEqual(
                profile.read_state("KleinPerkins/demo")["target_stage"],
                "canary_recreated",
            )
            self.assertIsNone(
                profile.read_state("KleinPerkins/demo")["canary_proof"]
            )
            proof_path = self.write_canary_proof(fake)
            subprocess.run(
                ["git", "switch", "main"],
                cwd=self.repo.path,
                check=True,
                capture_output=True,
            )
            before = len(fake.calls)
            with self.assertRaisesRegex(profile.ProfileError, "--canary-proof"):
                profile.cmd_enforce(
                    self.repo.path, dry_run=True, retarget="main"
                )
            retarget_dry_run = io.StringIO()
            with contextlib.redirect_stdout(retarget_dry_run):
                self.assertEqual(profile.cmd_enforce(
                    self.repo.path,
                    dry_run=True,
                    retarget="main",
                    canary_proof=str(proof_path),
                ), 0)
            self.assertIn("promotion gate READY", retarget_dry_run.getvalue())
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[before:]
            ))
            self.assertEqual(profile.cmd_enforce(
                self.repo.path,
                dry_run=False,
                retarget="main",
                canary_proof=str(proof_path),
            ), 0)
            self.assertEqual(fake.ruleset_id, second_id)
            self.assertEqual(
                fake.ruleset["conditions"]["ref_name"]["include"],
                ["refs/heads/main"],
            )
            state = profile.read_state("KleinPerkins/demo")
            self.assertEqual(state["target_branch"], "main")
            self.assertEqual(state["target_stage"], "promoted")
            self.assertEqual(state["ruleset_id"], second_id)
            self.assertEqual(
                [entry["generation"] for entry in state["owned_ruleset_history"]],
                [1, 2],
            )
            self.assertEqual(
                [entry["ruleset_id"] for entry in state["owned_ruleset_history"]],
                [first_id, second_id],
            )
            self.assertNotIn("api_observation", json.dumps(state["canary_proof"]))
            self.assertNotIn("evidence_url", json.dumps(state["canary_proof"]))
            promoted_status = io.StringIO()
            with contextlib.redirect_stdout(promoted_status):
                profile.cmd_status(self.repo.path)
            self.assertIn("proof gate:  COMPLETE", promoted_status.getvalue())

    def test_retarget_refuses_ruleset_id_replacement(self) -> None:
        self.apply_and_commit()
        canary_sha = self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        fake.branches["canary"] = canary_sha
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            proof_path = self.prepare_recreated_canary(fake)
            subprocess.run(
                ["git", "switch", "main"],
                cwd=self.repo.path,
                check=True,
                capture_output=True,
            )
            fake.ruleset_id = 9901
            before = len(fake.calls)
            with self.assertRaisesRegex(profile.ProfileError, "ruleset id"):
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=False,
                    retarget="main",
                    canary_proof=str(proof_path),
                )
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[before:]
            ))

    def test_retarget_refuses_drift_between_read_and_write(self) -> None:
        self.apply_and_commit()
        canary_sha = self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        fake.branches["canary"] = canary_sha
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            proof_path = self.prepare_recreated_canary(fake)
            subprocess.run(
                ["git", "switch", "main"],
                cwd=self.repo.path,
                check=True,
                capture_output=True,
            )
            original_expect = profile.expect_ruleset_now
            calls = 0

            def drift_on_second_read(*args, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    fake.ruleset["bypass_actors"] = [{"actor_id": 5}]
                return original_expect(*args, **kwargs)

            before = len(fake.calls)
            with (
                mock.patch.object(
                    profile,
                    "expect_ruleset_now",
                    side_effect=drift_on_second_read,
                ),
                self.assertRaisesRegex(profile.ProfileError, "changed"),
            ):
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=False,
                    retarget="main",
                    canary_proof=str(proof_path),
                )
            self.assertFalse(any(
                method == "PUT" for method, _ in fake.calls[before:]
            ))

    def test_retarget_recovers_http_404_before_apply(self) -> None:
        self.exercise_retarget_http_recovery(404, after_apply=False)

    def test_retarget_recovers_http_422_before_apply(self) -> None:
        self.exercise_retarget_http_recovery(422, after_apply=False)

    def test_retarget_recovers_http_500_before_apply(self) -> None:
        self.exercise_retarget_http_recovery(500, after_apply=False)

    def test_retarget_recovers_http_404_after_apply(self) -> None:
        self.exercise_retarget_http_recovery(404, after_apply=True)

    def test_retarget_recovers_http_422_after_apply(self) -> None:
        self.exercise_retarget_http_recovery(422, after_apply=True)

    def test_retarget_recovers_response_loss_after_apply(self) -> None:
        self.exercise_retarget_http_recovery(500, after_apply=True)

    def test_applied_retarget_finalizes_after_proof_expiry_and_destination_advance(self) -> None:
        self.apply_and_commit()
        canary_sha = self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        fake.branches["canary"] = canary_sha
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            proof_path = self.prepare_recreated_canary(fake)
            subprocess.run(
                ["git", "switch", "main"],
                cwd=self.repo.path,
                check=True,
                capture_output=True,
            )
            old_destination_sha = fake.branches["main"]
            fake.fail_after_ruleset_put_status = 500
            with self.assertRaises(profile.ProfileError):
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=False,
                    retarget="main",
                    canary_proof=str(proof_path),
                )
            state = profile.read_state("KleinPerkins/demo")
            state["canary_proof"]["observed_at"] = (
                profile.dt.datetime.now(profile.dt.timezone.utc)
                - profile.dt.timedelta(days=2)
            ).isoformat()
            pending_digest = state["pending_retarget"]["canary_proof_digest"]
            profile.write_state("KleinPerkins/demo", state)
            fake.branches["main"] = "f" * 40
            puts_before = sum(1 for method, _ in fake.calls if method == "PUT")
            self.assertEqual(
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=False,
                    retarget="main",
                ),
                0,
            )
            self.assertEqual(
                sum(1 for method, _ in fake.calls if method == "PUT"),
                puts_before,
            )
            state = profile.read_state("KleinPerkins/demo")
            self.assertEqual(state["target_sha"], old_destination_sha)
            self.assertEqual(
                state["target_history"][-1]["canary_proof_digest"],
                pending_digest,
            )

    def test_preimage_retry_replaces_expired_proof_and_advanced_destination(self) -> None:
        self.apply_and_commit()
        canary_sha = self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        fake.branches["canary"] = canary_sha
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            proof_path = self.prepare_recreated_canary(fake)
            subprocess.run(
                ["git", "switch", "main"],
                cwd=self.repo.path,
                check=True,
                capture_output=True,
            )
            fake.fail_before_ruleset_put_status = 500
            with self.assertRaises(profile.ProfileError):
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=False,
                    retarget="main",
                    canary_proof=str(proof_path),
                )
            state = profile.read_state("KleinPerkins/demo")
            old_pending = copy.deepcopy(state["pending_retarget"])
            state["canary_proof"]["observed_at"] = (
                profile.dt.datetime.now(profile.dt.timezone.utc)
                - profile.dt.timedelta(days=2)
            ).isoformat()
            profile.write_state("KleinPerkins/demo", state)
            subprocess.run(
                ["git", "commit", "--allow-empty", "-m", "destination advanced"],
                cwd=self.repo.path,
                check=True,
                capture_output=True,
            )
            self.repo.sync_remote_tracking("main")
            new_destination_sha = profile.git(self.repo.path, "rev-parse", "HEAD")
            fake.branches["main"] = new_destination_sha
            fresh_time = (
                profile.dt.datetime.now(profile.dt.timezone.utc)
                + profile.dt.timedelta(seconds=1)
            ).replace(microsecond=0).isoformat()
            fresh_proof = self.write_canary_proof(
                fake,
                mutate=lambda proof: proof.update(observed_at=fresh_time),
            )
            fresh_digest = profile.fingerprint(json.loads(fresh_proof.read_text()))
            fake.fail_before_ruleset_put_status = 422
            with self.assertRaisesRegex(profile.ProfileError, "HTTP 422"):
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=False,
                    retarget="main",
                    canary_proof=str(fresh_proof),
                )
            state = profile.read_state("KleinPerkins/demo")
            self.assertEqual(
                state["pending_retarget"]["to_target_sha"],
                new_destination_sha,
            )
            self.assertNotEqual(
                state["pending_retarget"]["to_target_sha"],
                old_pending["to_target_sha"],
            )
            self.assertEqual(
                state["pending_retarget"]["canary_proof_digest"],
                fresh_digest,
            )
            self.assertEqual(
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=False,
                    retarget="main",
                ),
                0,
            )

    def test_retarget_recovery_refuses_concurrent_third_state(self) -> None:
        self.apply_and_commit()
        canary_sha = self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        fake.branches["canary"] = canary_sha
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            proof_path = self.prepare_recreated_canary(fake)
            subprocess.run(
                ["git", "switch", "main"],
                cwd=self.repo.path,
                check=True,
                capture_output=True,
            )
            fake.fail_before_ruleset_put_status = 500
            with self.assertRaises(profile.ProfileError):
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=False,
                    retarget="main",
                    canary_proof=str(proof_path),
                )
            fake.ruleset["bypass_actors"] = [{"actor_id": 5}]
            before = len(fake.calls)
            with self.assertRaisesRegex(profile.ProfileError, "neither exact preimage"):
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=False,
                    retarget="main",
                )
            self.assertFalse(any(
                method == "PUT" for method, _ in fake.calls[before:]
            ))

    def test_retarget_recovery_refuses_resource_id_change(self) -> None:
        self.apply_and_commit()
        canary_sha = self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        fake.branches["canary"] = canary_sha
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            proof_path = self.prepare_recreated_canary(fake)
            subprocess.run(
                ["git", "switch", "main"],
                cwd=self.repo.path,
                check=True,
                capture_output=True,
            )
            fake.fail_before_ruleset_put_status = 500
            with self.assertRaises(profile.ProfileError):
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=False,
                    retarget="main",
                    canary_proof=str(proof_path),
                )
            fake.ruleset_id = 9901
            before = len(fake.calls)
            with self.assertRaisesRegex(profile.ProfileError, "ruleset id"):
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=False,
                    retarget="main",
                )
            self.assertFalse(any(
                method == "PUT" for method, _ in fake.calls[before:]
            ))

    def test_canary_proof_adversarial_bindings_and_scenarios(self) -> None:
        self.apply_and_commit()
        canary_sha = self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        fake.branches["canary"] = canary_sha
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            self.prepare_recreated_canary(fake)
            state = profile.read_state("KleinPerkins/demo")
            assert state
            first_id = state["rollback_proofs"][0]["ruleset_id"]
            subprocess.run(
                ["git", "switch", "main"],
                cwd=self.repo.path,
                check=True,
                capture_output=True,
            )

            def remove_scenario(proof):
                proof["scenarios"] = proof["scenarios"][:-1]

            def mock_mandatory(proof):
                next(
                    entry for entry in proof["scenarios"] if entry["id"] == "direct_push"
                )["mode"] = "mocked"

            def credentialed_url(proof):
                entry = proof["scenarios"][0]
                entry.pop("api_observation")
                entry["evidence_url"] = "https://user:password@example.com/evidence"

            cases = {
                "owned_ruleset_id": lambda proof: proof.update(owned_ruleset_id=first_id),
                "generation": lambda proof: proof.update(generation=1),
                "canary_sha": lambda proof: proof.update(canary_sha="f" * 40),
                "ruleset_fingerprint": lambda proof: proof.update(
                    ruleset_fingerprint="e" * 64
                ),
                "settings_fingerprint": lambda proof: proof.update(
                    settings_fingerprint="d" * 64
                ),
                "missing scenario": remove_scenario,
                "mocked mandatory": mock_mandatory,
                "credentialed URL": credentialed_url,
                "stale": lambda proof: proof.update(
                    observed_at=(
                        profile.dt.datetime.now(profile.dt.timezone.utc)
                        - profile.dt.timedelta(days=2)
                    ).isoformat()
                ),
                "generation-1 replay": lambda proof: proof.update(
                    generation=1, owned_ruleset_id=first_id
                ),
            }
            for label, mutate in cases.items():
                with self.subTest(label=label):
                    proof_path = self.write_canary_proof(fake, mutate=mutate)
                    before = len(fake.calls)
                    with self.assertRaises(profile.ProfileError):
                        profile.cmd_enforce(
                            self.repo.path,
                            dry_run=True,
                            retarget="main",
                            canary_proof=str(proof_path),
                        )
                    self.assertFalse(any(
                        method in profile.MUTATING_METHODS
                        for method, _ in fake.calls[before:]
                    ))

    def test_canary_proof_refuses_changed_live_state_and_status_is_read_only(self) -> None:
        self.apply_and_commit()
        canary_sha = self.repo.switch_new_branch("canary")
        fake = FakeGitHub()
        fake.branches["canary"] = canary_sha
        with (
            mock.patch.object(profile, "require_gh"),
            mock.patch.object(profile, "gh_api", side_effect=fake.api),
        ):
            proof_path = self.prepare_recreated_canary(fake)
            status_before = profile.read_state("KleinPerkins/demo")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                profile.cmd_status(self.repo.path)
            self.assertIn("AWAITING_BUNDLE", output.getvalue())
            self.assertEqual(
                profile.read_state("KleinPerkins/demo"),
                status_before,
            )
            subprocess.run(
                ["git", "switch", "main"],
                cwd=self.repo.path,
                check=True,
                capture_output=True,
            )
            fake.settings["allow_update_branch"] = False
            before = len(fake.calls)
            with self.assertRaises(profile.ProfileError):
                profile.cmd_enforce(
                    self.repo.path,
                    dry_run=True,
                    retarget="main",
                    canary_proof=str(proof_path),
                )
            self.assertFalse(any(
                method in profile.MUTATING_METHODS for method, _ in fake.calls[before:]
            ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
