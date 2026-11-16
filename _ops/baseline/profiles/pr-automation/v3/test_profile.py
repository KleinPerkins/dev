#!/usr/bin/env python3
from __future__ import annotations

import base64
import copy
import contextlib
import importlib.util
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("pr_automation_v3_profile", HERE / "profile.py")
assert SPEC and SPEC.loader
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


def _workspace_allows_exec() -> bool:
    probe = None
    try:
        with tempfile.NamedTemporaryFile(prefix="exec-probe-", suffix=".sh", delete=False) as handle:
            probe = handle.name
            handle.write(b"#!/bin/sh\n")
            handle.flush()
        os.chmod(probe, 0o755)
        subprocess.run([probe], check=True, capture_output=True, timeout=2)
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False
    finally:
        if probe is not None:
            try:
                os.unlink(probe)
            except OSError:
                pass


def controller() -> dict:
    return {
        "schema": "pr-automation-controller-binding/v3",
        "check_name": "pr-automation / verify",
        "verifier": {
            "app_id": 4274739,
            "integration_id": 4274739,
            "slug": "kleinperkins-verify-bot",
            "installation_id": 145944952,
        },
        "reviewer": {
            "app_id": 4269364,
            "integration_id": 4269364,
            "slug": "kleinperkins-review-bot",
            "installation_id": 145790860,
        },
        "release": {
            "version": "v0.4.1",
            "activation_generation": 3,
            "lock_contract_version": 1,
            "lock_compiler_digest": "sha256:" + "f" * 64,
        },
        "images": {
            "fetch": "alpine/git@sha256:" + "b" * 64,
            "execution": (
                "buildpack-deps@sha256:"
                "877e9e4d949edfbcbedabc3a2d7ab593955fee5d6d0777adf3a991eb30c750d8"
            ),
        },
        "ruleset_fingerprints": {
            "runtime_app_visible": [
                "sha256:903f1f66c4f3519378395d2c04cc31465fcc0188e07028cd8b3f9d8ad1f1e28f"
            ],
            "operator_full": [
                "sha256:4ff6db9657ebf30b8ce45d2b43060cb4c34e139df1fe277bce486146d810974e"
            ],
            "repository_overrides": {},
        },
        "hard_exclusions": ["KleinPerkins/chaos-scheduler"],
    }


def fleet() -> dict:
    return {
        "targets": [
            {
                "repo": "KleinPerkins/awa",
                "repository_id": 1289571438,
                "default_branch": "main",
                "merge_safety_ruleset_id": 18819090,
            },
            {
                "repo": "KleinPerkins/dev",
                "repository_id": 1278387789,
                "default_branch": "main",
                "merge_safety_ruleset_id": 18817500,
            },
        ]
    }


def remote_fleet() -> dict:
    value = copy.deepcopy(fleet())
    value["targets"].append(
        {
            "repo": "KleinPerkins/pr-automation-controller",
            "repository_id": 1297666445,
            "default_branch": "main",
            "merge_safety_ruleset_id": 18817498,
        }
    )
    return value


def assignment(mode: str = "local") -> dict:
    return {
        "schema": "pr-automation-coverage-assignments/v2",
        "assignments": [
            {
                "repo": "KleinPerkins/awa",
                "coverage_mode": mode,
                "catalog_repository_id": "awa",
                "profile_ref": {
                    "id": "awa-pilot.v1",
                    "digest": "sha256:" + "a" * 64,
                },
            }
        ],
    }


def _gh_contents(value: dict) -> dict:
    return {"content": base64.b64encode(json.dumps(value).encode()).decode()}


def lock_currency_fixtures() -> dict:
    return json.loads(
        (HERE / "fixtures/lock-currency-cases.json").read_text(encoding="utf-8")
    )


def _rehash_v2_lock(lock: dict) -> dict:
    value = copy.deepcopy(lock)
    payload = json.dumps(
        value["payload"], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    value["lock_digest"] = "sha256:" + hashlib.sha256(
        b"pr-automation-lock/v2\0" + payload
    ).hexdigest()
    return value


def lock_currency_case(name: str = "current_v2") -> dict:
    fixtures = lock_currency_fixtures()
    if name == "legacy_v1":
        return copy.deepcopy(fixtures["legacy_v1"])
    value = copy.deepcopy(fixtures["current_v2"])
    if name != "current_v2":
        case = next(item for item in fixtures["stale_cases"] if item["name"] == name)
        parent_name, field = case["path"].split(".", 1)
        parent = value[parent_name]
        if case.get("remove"):
            parent.pop(field)
        else:
            parent[field] = case["value"]
    return _rehash_v2_lock(value)


def merge_safety_ruleset(
    *,
    ruleset_id: int = 18819090,
    repo: str = "KleinPerkins/awa",
    default_branch: str = "main",
) -> dict:
    value = json.loads(
        (HERE / "merge-safety.ruleset.json.tmpl")
        .read_text(encoding="utf-8")
        .replace("{{DEFAULT_BRANCH}}", default_branch)
    )
    value["id"] = ruleset_id
    value["source_type"] = "Repository"
    value["source"] = repo
    return value


def repository_policy(
    repo: str,
    *,
    policy_digest: str,
    policy_generation: int,
    fingerprints: list[str] | None = None,
    repository_id: int | None = None,
) -> dict:
    if repository_id is None:
        repository_id = next(
            item["repository_id"] for item in fleet()["targets"] if item["repo"] == repo
        )
    owner, name = repo.split("/", 1)
    return {
        "version": "pr-automation/v3",
        "repository_id": repository_id,
        "owner": owner,
        "name": name,
        "default_branch": "main",
        "activation_generation": policy_generation,
        "check_name": "pr-automation / verify",
        "verifier_app_id": 4274739,
        "verifier_integration_id": 4274739,
        "reviewer_app_id": 4269364,
        "reviewer_integration_id": 4269364,
        "protected_paths": [".github", "CODEOWNERS", "_ops"],
        "ruleset_fingerprints": fingerprints
        or controller()["ruleset_fingerprints"]["runtime_app_visible"],
        "max_changed_files": 200,
        "max_total_patch_bytes": 5_000_000,
        "controller_release_digest": policy_digest,
    }


def is_ruleset_list_path(path: str, repo: str) -> bool:
    base = f"repos/{repo}/rulesets"
    return path == base or path.startswith(base + "?")


def gh_router(*, policy_digest: str, policy_generation: int = 3):
    """Route mocked read-only policy/ruleset GETs; lock proof uses the Rust validator boundary."""
    def route(path: str):
        if "/rulesets/" in path:
            repo = path.split("/rulesets/", 1)[0].removeprefix("repos/")
            ruleset_id = int(path.rsplit("/", 1)[-1])
            return merge_safety_ruleset(ruleset_id=ruleset_id, repo=repo)
        if "/rulesets?" in path or path.endswith("/rulesets"):
            repo = (
                path.split("/rulesets", 1)[0].removeprefix("repos/")
            )
            target = next(
                item for item in remote_fleet()["targets"] if item["repo"] == repo
            )
            return [
                {
                    "id": target["merge_safety_ruleset_id"],
                    "name": PROFILE.MERGE_SAFETY_NAME,
                    "target": "branch",
                    "enforcement": "active",
                }
            ]
        if PROFILE.LOCK in path:
            raise AssertionError("lock currency must use exact Rust validator/recompile evidence")
        if "/contents/" not in path:
            repo = path.removeprefix("repos/")
            target = next(
                item for item in remote_fleet()["targets"] if item["repo"] == repo
            )
            return {
                "id": target["repository_id"],
                "full_name": repo,
                "default_branch": target["default_branch"],
            }
        repo = path.split("/contents/")[0].removeprefix("repos/")
        return _gh_contents(
            repository_policy(
                repo,
                policy_digest=policy_digest,
                policy_generation=policy_generation,
                repository_id=next(
                    item["repository_id"]
                    for item in remote_fleet()["targets"]
                    if item["repo"] == repo
                ),
            )
        )

    return route


def live_bytes(mode: str = "local") -> bytes:
    value = {
        "version": "pr-automation-controller/v1",
        "account_login": "KleinPerkins",
        "activation_generation": 3,
        "repositories": [
            {
                "id": 1289571438,
                "owner": "KleinPerkins",
                "name": "awa",
                "default_branch": "main",
                "expected_ruleset_fingerprints": controller()["ruleset_fingerprints"][
                    "runtime_app_visible"
                ],
                "coverage_assignment": {
                    "coverage_mode": mode,
                    "catalog_repository_id": "awa",
                    "profile_ref": {
                        "id": "awa-pilot.v1",
                        "digest": "sha256:" + "a" * 64,
                    },
                },
            },
            {
                "id": 1278387789,
                "owner": "KleinPerkins",
                "name": "dev",
                "default_branch": "main",
                "expected_ruleset_fingerprints": controller()["ruleset_fingerprints"][
                    "runtime_app_visible"
                ],
                "coverage_assignment": None,
            },
        ],
    }
    return (json.dumps(value, indent=2) + "\n").encode()


class CoverageControlPlaneTest(unittest.TestCase):
    def test_rollout_state_reads_only_merged_history_not_deleted_recipe_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-b", "main", root], check=True, capture_output=True)
            environment = {
                **os.environ,
                "GIT_AUTHOR_NAME": "Fixture",
                "GIT_AUTHOR_EMAIL": "fixture@example.com",
                "GIT_COMMITTER_NAME": "Fixture",
                "GIT_COMMITTER_EMAIL": "fixture@example.com",
            }
            (root / "README.md").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", root, "add", "README.md"], check=True, env=environment)
            subprocess.run(
                ["git", "-C", root, "commit", "-m", "base"],
                check=True,
                env=environment,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", root, "update-ref", "refs/remotes/origin/main", "HEAD"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", root, "switch", "-c", "recipe-candidate"],
                check=True,
                capture_output=True,
            )
            recipe_path = root / ".github/pr-recipe.json"
            recipe_path.parent.mkdir()
            recipe_path.write_text(
                PROFILE.encoded(
                    PROFILE.build_repository_recipe(
                        "KleinPerkins/kp-pr-bot-canary", custom_argv=None
                    )
                ),
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", root, "add", str(recipe_path)], check=True)
            subprocess.run(
                ["git", "-C", root, "commit", "-m", "candidate"],
                check=True,
                env=environment,
                capture_output=True,
            )
            candidate = subprocess.run(
                ["git", "-C", root, "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertIsNone(PROFILE._git_file_at(root, "origin/main", PROFILE.RECIPE))
            subprocess.run(
                ["git", "-C", root, "switch", "main"], check=True, capture_output=True
            )
            subprocess.run(
                ["git", "-C", root, "branch", "-D", "recipe-candidate"],
                check=True,
                capture_output=True,
            )
            with self.assertRaises(subprocess.CalledProcessError):
                subprocess.run(
                    ["git", "-C", root, "cat-file", "-e", f"refs/heads/recipe-candidate:{PROFILE.RECIPE}"],
                    check=True,
                    capture_output=True,
                )
            self.assertNotEqual(candidate, subprocess.run(
                ["git", "-C", root, "rev-parse", "origin/main"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip())

    def test_current_projection_reuses_exact_live_bytes(self) -> None:
        raw = live_bytes()
        projected = PROFILE.project_live_config(raw, assignment(), fleet(), controller())
        self.assertFalse(projected.changed)
        self.assertEqual(projected.candidate, raw)

    def test_rehearsal_mismatch_stops_with_diff_and_never_reconciles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "live-config.json"
            original = live_bytes("shadow")
            path.write_bytes(original)
            with self.assertRaisesRegex(PROFILE.CoverageDrift, "coverage projection differs"):
                PROFILE.rehearse_live_projection(path, assignment(), fleet(), controller())
            self.assertEqual(path.read_bytes(), original)

    def test_view_surfaces_hard_exclusions_as_permanently_unpromotable(self) -> None:
        view = PROFILE.view_coverage(live_bytes(), assignment(), fleet(), controller())
        self.assertEqual(
            view["hard_exclusions"],
            [{"repo": "KleinPerkins/chaos-scheduler", "promotable": False}],
        )

    def test_sync_plan_contains_one_exact_phase_only(self) -> None:
        expected = {
            "recipe": (".github/pr-recipe.json", "KleinPerkins/awa"),
            "lock": (".github/pr-automation.lock.json", "KleinPerkins/awa"),
            "relock": (".github/pr-automation.lock.json", "KleinPerkins/awa"),
            "assignment": (
                "_ops/baseline/profiles/pr-automation/v3/coverage-assignments.json",
                "KleinPerkins/dev",
            ),
        }
        for phase, (path, repository) in expected.items():
            plan = PROFILE.build_sync_plan(
                "KleinPerkins/awa",
                phase=phase,
                operation_id=f"m3-{phase}",
            )
            self.assertEqual(len(plan["pull_requests"]), 1)
            self.assertEqual(plan["pull_requests"][0]["files"], [path])
            self.assertEqual(plan["pull_requests"][0]["repository"], repository)
            self.assertEqual(plan["pull_requests"][0]["operation_id"], f"m3-{phase}")

    def test_bootstrap_phase_is_state_specific_and_never_guesses_future_sha(self) -> None:
        self.assertEqual(
            PROFILE.rollout_phase(False, False, None, "manual_only", lock_current=False),
            "recipe",
        )
        self.assertEqual(
            PROFILE.rollout_phase(True, False, None, "manual_only", lock_current=False),
            "lock",
        )
        self.assertEqual(
            PROFILE.rollout_phase(True, True, None, "manual_only", lock_current=True),
            "assignment",
        )
        self.assertEqual(
            PROFILE.rollout_phase(True, True, "manual_only", "shadow", lock_current=True),
            "mode",
        )
        self.assertEqual(
            PROFILE.rollout_phase(True, True, "manual_only", "manual_only", lock_current=False),
            "relock",
        )
        recipe = PROFILE.build_repository_recipe("KleinPerkins/kp-pr-bot-canary", custom_argv=None)
        rendered = PROFILE.render_phase_diff("recipe", None, PROFILE.encoded(recipe).encode())
        self.assertIn(".github/pr-recipe.json", rendered)
        self.assertNotIn("recipe_base_sha", rendered)
        self.assertNotIn("pr-automation.lock", rendered)

    def test_operation_id_is_claimed_once_across_phases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = PROFILE.claim_operation(root, "m3-canary-recipe", "sync:recipe")
            self.assertEqual(receipt["status"], "claimed")
            with self.assertRaisesRegex(PROFILE.ControlPlaneError, "already used"):
                PROFILE.claim_operation(root, "m3-canary-recipe", "sync:lock")
            PROFILE.complete_operation(root, "m3-canary-recipe")
            with self.assertRaisesRegex(PROFILE.ControlPlaneError, "already used"):
                PROFILE.claim_operation(root, "m3-canary-recipe", "activate:stage")

    def test_activate_staging_and_transcription_are_separate_operations(self) -> None:
        staged = PROFILE.build_activation_plan(
            "KleinPerkins/awa",
            phase="stage",
            operation_id="m3-awa-shadow-stage",
        )
        transcribed = PROFILE.build_activation_plan(
            "KleinPerkins/awa",
            phase="transcribe",
            operation_id="m3-awa-shadow-transcribe",
        )
        self.assertEqual(
            staged["files"],
            ["_ops/baseline/profiles/pr-automation/v3/coverage-assignments.json"],
        )
        self.assertEqual(transcribed["files"], [])
        self.assertNotEqual(staged["operation_id"], transcribed["operation_id"])

    def test_phase_change_sets_reject_combined_or_stale_bootstrap(self) -> None:
        PROFILE.assert_phase_change_set("recipe", {".github/pr-recipe.json"})
        PROFILE.assert_phase_change_set("lock", {".github/pr-automation.lock.json"})
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "exactly"):
            PROFILE.assert_phase_change_set(
                "recipe",
                {".github/pr-recipe.json", ".github/pr-automation.lock.json"},
            )
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "exactly"):
            PROFILE.assert_phase_change_set("lock", {".github/pr-recipe.json"})

    def test_porcelain_paths_preserve_leading_underscore_and_reject_renames(self) -> None:
        self.assertEqual(
            PROFILE._parse_porcelain_paths(
                b" M _ops/baseline/profiles/pr-automation/v3/coverage-assignments.json\0"
                b"?? file with spaces.txt\0"
            ),
            {
                "_ops/baseline/profiles/pr-automation/v3/coverage-assignments.json",
                "file with spaces.txt",
            },
        )
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "rename/copy"):
            PROFILE._parse_porcelain_paths(b"R  destination\0source\0")

    def test_qualified_release_manifest_is_required_and_digest_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller_binary = root / "pr-automation-controller"
            compiler = root / "lock-compiler"
            controller_binary.write_bytes(b"controller")
            compiler.write_bytes(b"compiler")
            manifest = {
                "schema": "pr-automation-qualified-release/v1",
                "lifecycle_state": "qualified",
                "version": "0.4.1",
                "artifacts": [
                    {
                        "name": "pr-automation-controller",
                        "sha256": PROFILE._sha256_bytes(b"controller"),
                        "size": len(b"controller"),
                    },
                    {
                        "name": "lock-compiler",
                        "sha256": PROFILE._sha256_bytes(b"compiler"),
                        "size": len(b"compiler"),
                    },
                ],
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            configured = controller()
            configured["release"]["digest"] = PROFILE._sha256_bytes(b"controller")
            configured["release"]["lock_compiler_digest"] = PROFILE._sha256_bytes(b"compiler")
            proof = PROFILE.validate_qualified_release(manifest_path, configured)
            self.assertEqual(proof["lifecycle_state"], "qualified")
            compiler.write_bytes(b"drift")
            with self.assertRaisesRegex(PROFILE.ControlPlaneError, "size|digest"):
                PROFILE.validate_qualified_release(manifest_path, configured)

    def test_profile_reuse_requires_the_exact_qualified_runtime_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            control = root / "_ops/baseline/profiles/pr-automation/v3"
            control.mkdir(parents=True)
            entry = {
                "repo": "KleinPerkins/intent-router",
                "status": "qualified",
                "argv": PROFILE.M3_CUSTOM_COMMANDS["KleinPerkins/intent-router"],
                "image": PROFILE.EXECUTION_IMAGE_REF,
                "limits": PROFILE.STDLIB_LIMITS,
                "evidence": {"exit_code": 0},
            }
            (control / PROFILE.QUALIFICATION_LEDGER).write_text(
                json.dumps(
                    {
                        "schema": "pr-automation-m3-qualification-ledger/v1",
                        "candidates": [entry],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                PROFILE._qualified_custom_argv(root, "KleinPerkins/intent-router"),
                ["bash", "tests/run-tests.sh"],
            )
            entry["limits"] = {**PROFILE.STDLIB_LIMITS, "memory_mib": 1024}
            (control / PROFILE.QUALIFICATION_LEDGER).write_text(
                json.dumps(
                    {
                        "schema": "pr-automation-m3-qualification-ledger/v1",
                        "candidates": [entry],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PROFILE.ControlPlaneError, "does not match"):
                PROFILE._qualified_custom_argv(root, "KleinPerkins/intent-router")

    def test_local_assignment_requires_runtime_equivalent_artifact_validation(self) -> None:
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "validated recipe/lock"):
            PROFILE.propose_assignment(
                assignment("shadow"),
                fleet(),
                controller(),
                repo="KleinPerkins/awa",
                coverage_mode="local",
                profile_id="awa-pilot.v1",
                profile_digest="sha256:" + "a" * 64,
                artifacts_validated=False,
            )

    def test_activation_package_is_reversible_and_generation_preserving(self) -> None:
        proposed = PROFILE.propose_assignment(
            assignment("local"),
            fleet(),
            controller(),
            repo="KleinPerkins/awa",
            coverage_mode="shadow",
            profile_id="awa-pilot.v1",
            profile_digest="sha256:" + "a" * 64,
            artifacts_validated=True,
        )
        raw = live_bytes("local")
        package = PROFILE.build_activation_package(
            raw, proposed, fleet(), controller(), repo="KleinPerkins/awa"
        )
        self.assertNotEqual(package.candidate, raw)
        self.assertEqual(package.rollback, raw)
        self.assertEqual(package.activation_generation, 3)
        candidate = json.loads(package.candidate)
        self.assertEqual(candidate["activation_generation"], 3)
        self.assertEqual(
            candidate["repositories"][0]["coverage_assignment"]["coverage_mode"],
            "shadow",
        )

    def test_hard_exclusion_cannot_be_assigned_or_activated(self) -> None:
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "hard exclusion"):
            PROFILE.propose_assignment(
                assignment(),
                fleet(),
                controller(),
                repo="KleinPerkins/chaos-scheduler",
                coverage_mode="manual_only",
                profile_id="awa-pilot.v1",
                profile_digest="sha256:" + "a" * 64,
                artifacts_validated=True,
            )

    def test_permanent_hard_exclusion_cannot_be_removed_from_control_plane(self) -> None:
        configured = controller()
        configured["hard_exclusions"] = []
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "must preserve"):
            PROFILE.view_coverage(live_bytes(), assignment(), fleet(), configured)

    def test_promotion_cannot_skip_an_observation_stage(self) -> None:
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "cannot skip"):
            PROFILE.propose_assignment(
                assignment("manual_only"),
                fleet(),
                controller(),
                repo="KleinPerkins/awa",
                coverage_mode="local",
                profile_id="awa-pilot.v1",
                profile_digest="sha256:" + "a" * 64,
                artifacts_validated=True,
            )

    def test_activation_refuses_to_transcribe_unrelated_assignment_drift(self) -> None:
        desired = assignment("shadow")
        desired["assignments"].append(
            {
                "repo": "KleinPerkins/dev",
                "coverage_mode": "manual_only",
                "catalog_repository_id": "dev",
                "profile_ref": {
                    "id": "dev-pilot.v1",
                    "digest": "sha256:" + "b" * 64,
                },
            }
        )
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "exactly one"):
            PROFILE.build_activation_package(
                live_bytes(),
                desired,
                fleet(),
                controller(),
                repo="KleinPerkins/awa",
            )

    def test_rollback_maps_to_s30_and_validates_its_real_receipt(self) -> None:
        command = PROFILE.rollback_command("/usr/local/bin/pr-automation-controller")
        self.assertEqual(
            command,
            ["/usr/local/bin/pr-automation-controller", "roll-back", "--json"],
        )
        self.assertNotIn("roll-back-controller", command)
        before = {"activation_generation": 3}
        receipt = {
            "prior_supersede_generation": 7,
            "new_supersede_generation": 8,
            "activation_generation": 3,
            "coverage_mode": "manual_only",
            "resumed": True,
        }
        after = {"activation_generation": 3, "coverage_mode": "manual_only"}
        PROFILE.validate_rollback_receipt(before, receipt, after)
        receipt["activation_generation"] = 4
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "activation generation changed"):
            PROFILE.validate_rollback_receipt(before, receipt, after)

    def test_rollback_receipt_rejects_non_monotonic_result(self) -> None:
        before = {"activation_generation": 3}
        receipt = {
            "prior_supersede_generation": 7,
            "new_supersede_generation": 7,
            "activation_generation": 3,
            "coverage_mode": "manual_only",
            "resumed": True,
        }
        after = {"activation_generation": 3, "coverage_mode": "manual_only"}
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "did not advance"):
            PROFILE.validate_rollback_receipt(before, receipt, after)

    def test_view_plan_and_doctor_are_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "live-config.json"
            path.write_bytes(live_bytes())
            before = path.read_bytes()
            PROFILE.view_coverage(before, assignment(), fleet(), controller())
            PROFILE.plan_assignment(
                before,
                assignment(),
                fleet(),
                controller(),
                repo="KleinPerkins/awa",
                coverage_mode="shadow",
                profile_id="awa-pilot.v1",
                profile_digest="sha256:" + "a" * 64,
                artifacts_validated=True,
            )
            PROFILE.doctor_coverage(before, assignment(), fleet(), controller())
            self.assertEqual(path.read_bytes(), before)

    def test_exact_operator_verbs_are_exposed_without_validation_escape_hatch(self) -> None:
        choices = next(
            action.choices
            for action in PROFILE.parser()._actions
            if hasattr(action, "choices") and isinstance(action.choices, dict)
        )
        for verb in ("view", "plan", "sync", "activate", "doctor", "rollback"):
            self.assertIn(verb, choices)
        self.assertNotIn("--artifacts-validated", PROFILE.parser().format_help())

    def test_owner_go_is_bound_to_one_exact_operation(self) -> None:
        PROFILE._assert_owner_go("m3-awa-shadow", "m3-awa-shadow")
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "must exactly repeat"):
            PROFILE._assert_owner_go("m3-awa-shadow", "blanket-go")

    def test_assignment_validation_has_no_python_only_success_path(self) -> None:
        fixtures = lock_currency_fixtures()
        recipe = fixtures["recipe_bytes"].encode()
        lock = lock_currency_case()
        lock_bytes = json.dumps(lock).encode()
        with tempfile.TemporaryDirectory() as temporary:
            compiler = Path(temporary) / "lock-compiler"
            compiler.write_text("#!/bin/sh\nexit 41\n", encoding="utf-8")
            os.chmod(compiler, 0o755)
            configured = controller()
            configured["release"]["lock_compiler_digest"] = (
                "sha256:" + hashlib.sha256(compiler.read_bytes()).hexdigest()
            )
            kwargs = {
                "recipe_bytes": recipe,
                "lock_bytes": lock_bytes,
                "compiler": compiler,
                "controller": configured,
                "repo": "KleinPerkins/awa",
                "profile_id": "awa-pilot.v1",
                "profile_digest": "sha256:" + "a" * 64,
            }
            if _workspace_allows_exec():
                with self.assertRaisesRegex(PROFILE.ControlPlaneError, "lock-compiler failed"):
                    PROFILE.validate_artifact_bytes(**kwargs)
                return
            # Production sandbox workspaces are noexec; still prove validate_artifact_bytes
            # reaches the Rust validator instead of a Python-only success path.
            with mock.patch.object(
                PROFILE,
                "_run_checked",
                side_effect=PROFILE.ControlPlaneError("lock-compiler failed: exit 41"),
            ):
                with self.assertRaisesRegex(PROFILE.ControlPlaneError, "lock-compiler failed"):
                    PROFILE.validate_artifact_bytes(**kwargs)


class LockCurrencyContractTest(unittest.TestCase):
    @staticmethod
    def _assignment_lock(lock: dict, entry: dict) -> dict:
        value = copy.deepcopy(lock)
        payload = value["payload"]
        payload["repository_id"] = entry["catalog_repository_id"]
        payload["profile_id"] = entry["profile_ref"]["id"]
        payload["profile_digest"] = entry["profile_ref"]["digest"]
        for job in payload.get("jobs", []):
            job["profile_ref"] = copy.deepcopy(entry["profile_ref"])
        return _rehash_v2_lock(value) if value["schema_version"].endswith("/v2") else value

    @staticmethod
    def _artifact_validation(lock: dict | None = None) -> dict:
        payload = (lock or lock_currency_case())["payload"]
        return {
            "validated": True,
            "schema_version": "pr-automation-lock/v2",
            "lock_contract_version": 1,
            "covered_digests": {
                field: payload[field]
                for field in (
                    "catalog_digest",
                    "profile_digest",
                    "image_digest",
                    "recipe_digest",
                    "assignment_digest",
                )
            },
            "validator": "valid lock_digest=fixture jobs=1",
        }

    def _validate_fixture_artifact(self, name: str) -> dict:
        fixtures = lock_currency_fixtures()
        recipe = fixtures["recipe_bytes"].encode()
        lock = lock_currency_case(name)
        current_payload = lock_currency_case()["payload"]
        with tempfile.TemporaryDirectory() as temporary:
            compiler = Path(temporary) / "lock-compiler"
            compiler.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            os.chmod(compiler, 0o755)
            configured = controller()
            configured["release"]["lock_compiler_digest"] = PROFILE._sha256_bytes(
                compiler.read_bytes()
            )

            def rust_validator(command: list[str], **_: object) -> subprocess.CompletedProcess[bytes]:
                lock_path = Path(command[command.index("--lock") + 1])
                observed = json.loads(lock_path.read_text(encoding="utf-8"))
                for field in ("catalog_digest", "recipe_digest", "assignment_digest"):
                    if observed["payload"].get(field) != current_payload[field]:
                        raise PROFILE.ControlPlaneError(
                            f"lock-compiler failed: validate failed: {field} mismatch"
                        )
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=b"valid lock_digest=fixture jobs=1\n",
                    stderr=b"",
                )

            with mock.patch.object(PROFILE, "_run_checked", side_effect=rust_validator):
                return PROFILE.validate_artifact_bytes(
                    recipe,
                    json.dumps(lock, sort_keys=True, separators=(",", ":")).encode(),
                    compiler,
                    configured,
                    repo="KleinPerkins/awa",
                    profile_id="awa-pilot.v1",
                    profile_digest="sha256:" + "a" * 64,
                )

    @staticmethod
    def _git_fixture(root: Path) -> tuple[dict, Path]:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "fixture@example.com"],
            check=True,
        )
        recipe = lock_currency_fixtures()["recipe_bytes"].encode()
        recipe_path = root / PROFILE.RECIPE
        recipe_path.parent.mkdir(parents=True)
        recipe_path.write_bytes(recipe)
        subprocess.run(["git", "-C", str(root), "add", PROFILE.RECIPE], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-qm", "add recipe"],
            check=True,
        )
        base = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        lock = lock_currency_case()
        lock["payload"]["recipe_base_sha"] = base
        lock["payload"]["recipe_blob_sha"] = PROFILE._git_blob_sha(recipe)
        lock = _rehash_v2_lock(lock)
        (root / PROFILE.LOCK).write_text(json.dumps(lock), encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", PROFILE.LOCK], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-qm", "add lock"],
            check=True,
        )
        compiler = root / "lock-compiler"
        compiler.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        compiler.chmod(0o755)
        return lock, compiler

    @staticmethod
    def _validate_repository_fixture(root: Path, compiler: Path, *, at_ref: bool) -> dict:
        configured = controller()
        configured["release"]["lock_compiler_digest"] = PROFILE._sha256_bytes(
            compiler.read_bytes()
        )
        kwargs = {
            "compiler": compiler,
            "controller": configured,
            "repo": "KleinPerkins/awa",
            "profile_id": "awa-pilot.v1",
            "profile_digest": "sha256:" + "a" * 64,
        }
        if at_ref:
            return PROFILE.validate_repository_artifacts_at_ref(root, "HEAD", **kwargs)
        return PROFILE.validate_repository_artifacts(root, **kwargs)

    def test_local_and_ref_currency_reject_current_recipe_changed_after_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, compiler = self._git_fixture(root)
            (root / PROFILE.RECIPE).write_text(
                '{"schema":"fixture-recipe/v2","changed":true}\n',
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", str(root), "add", PROFILE.RECIPE], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-qm", "change recipe"],
                check=True,
            )
            for at_ref in (False, True):
                with self.subTest(at_ref=at_ref), self.assertRaisesRegex(
                    PROFILE.ControlPlaneError, "current recipe"
                ):
                    self._validate_repository_fixture(root, compiler, at_ref=at_ref)

    def test_local_and_ref_currency_allow_later_unrelated_commit_with_same_recipe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, compiler = self._git_fixture(root)
            (root / "README.md").write_text("unrelated\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
            subprocess.run(
                ["git", "-C", str(root), "commit", "-qm", "unrelated change"],
                check=True,
            )
            for at_ref in (False, True):
                with self.subTest(at_ref=at_ref):
                    proof = self._validate_repository_fixture(
                        root, compiler, at_ref=at_ref
                    )
                    self.assertTrue(proof["validated"])

    def test_controller_authority_and_schema_bind_epoch_one(self) -> None:
        configured = json.loads((HERE / "controller.json").read_text(encoding="utf-8"))
        schema = json.loads((HERE / "controller.schema.json").read_text(encoding="utf-8"))
        epoch_schema = schema["properties"]["release"]["properties"]["lock_contract_version"]
        self.assertEqual(configured["release"]["lock_contract_version"], 1)
        self.assertIn("lock_contract_version", schema["properties"]["release"]["required"])
        self.assertEqual(epoch_schema, {"const": 1, "type": "integer"})
        self.assertEqual(PROFILE.LOCK_SCHEMA, "pr-automation-lock/v2")
        self.assertEqual(PROFILE.LOCK_CONTRACT_VERSION, 1)

    def test_awa_runtime_envelope_and_profile_authority_are_closed(self) -> None:
        configured = json.loads((HERE / "controller.json").read_text(encoding="utf-8"))
        schema = json.loads((HERE / "controller.schema.json").read_text(encoding="utf-8"))
        coverage = json.loads(
            (HERE / "coverage-assignments.json").read_text(encoding="utf-8")
        )
        runtime_schema = schema["properties"]["runtime"]
        systemd_schema = runtime_schema["properties"]["systemd"]
        self.assertIn("runtime", schema["required"])
        self.assertFalse(runtime_schema["additionalProperties"])
        self.assertFalse(systemd_schema["additionalProperties"])
        self.assertEqual(configured["runtime"], PROFILE.AWA_RUNTIME_ENVELOPE)
        self.assertEqual(
            runtime_schema["properties"]["poll_timeout_seconds"],
            {"const": 8100, "type": "integer"},
        )
        self.assertEqual(
            systemd_schema["properties"],
            {
                "timeout_start_seconds": {"const": 8400, "type": "integer"},
                "timeout_stop_seconds": {"const": 180, "type": "integer"},
                "kill_mode": {"const": "control-group", "type": "string"},
            },
        )
        PROFILE.validate_awa_authoritative_verify_authority(configured, coverage)

        runtime_mutations = {
            "poll timeout": lambda value: value["runtime"].update(
                poll_timeout_seconds=900
            ),
            "start timeout": lambda value: value["runtime"]["systemd"].update(
                timeout_start_seconds=1200
            ),
            "stop timeout": lambda value: value["runtime"]["systemd"].update(
                timeout_stop_seconds=90
            ),
            "kill mode": lambda value: value["runtime"]["systemd"].update(
                kill_mode="process"
            ),
            "extra runtime field": lambda value: value["runtime"].update(extra=True),
        }
        for label, mutate in runtime_mutations.items():
            candidate = copy.deepcopy(configured)
            mutate(candidate)
            with self.subTest(schema=label), self.assertRaises(
                PROFILE.ControlPlaneError
            ):
                PROFILE.validate_json_schema_instance(
                    schema,
                    candidate,
                    source=f"controller runtime {label}",
                )
            with self.subTest(authority=label), self.assertRaisesRegex(
                PROFILE.ControlPlaneError, "runtime envelope"
            ):
                PROFILE.validate_awa_authoritative_verify_authority(
                    candidate, coverage
                )

        image_candidate = copy.deepcopy(configured)
        image_candidate["images"]["profile_overrides"][
            "awa-authoritative-verify.v1"
        ] = "ghcr.io/kleinperkins/awa-authoritative-verify@sha256:" + "0" * 64
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "image override"):
            PROFILE.validate_awa_authoritative_verify_authority(
                image_candidate, coverage
            )

        awa_index = next(
            index
            for index, assignment in enumerate(coverage["assignments"])
            if assignment["repo"] == "KleinPerkins/awa"
        )
        for label, key, value in (
            ("profile", "id", "awa-pilot.v1"),
            ("digest", "digest", "sha256:" + "0" * 64),
        ):
            coverage_candidate = copy.deepcopy(coverage)
            coverage_candidate["assignments"][awa_index]["profile_ref"][key] = value
            with self.subTest(assignment=label), self.assertRaisesRegex(
                PROFILE.ControlPlaneError, "profile, digest"
            ):
                PROFILE.validate_awa_authoritative_verify_authority(
                    configured, coverage_candidate
                )

    def test_legacy_wrong_and_missing_epoch_fixtures_are_stale(self) -> None:
        configured = controller()
        for name, expected in (
            ("legacy_v1", "schema_version"),
            ("wrong_epoch", "lock_contract_version"),
            ("missing_epoch", "lock_contract_version"),
        ):
            with self.subTest(name=name):
                errors = PROFILE.lock_metadata_errors(
                    lock_currency_case(name),
                    configured,
                    repo="KleinPerkins/awa",
                    profile_id="awa-pilot.v1",
                    profile_digest="sha256:" + "a" * 64,
                )
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_stale_covered_fixtures_fail_closed_and_current_v2_has_rust_evidence(self) -> None:
        proof = self._validate_fixture_artifact("current_v2")
        self.assertTrue(proof["validated"])
        self.assertEqual(proof["schema_version"], "pr-automation-lock/v2")
        self.assertEqual(proof["lock_contract_version"], 1)
        self.assertEqual(
            set(proof["covered_digests"]),
            {
                "catalog_digest",
                "profile_digest",
                "image_digest",
                "recipe_digest",
                "assignment_digest",
            },
        )
        fixtures = lock_currency_fixtures()
        for case in fixtures["stale_cases"]:
            with self.subTest(name=case["name"]), self.assertRaisesRegex(
                PROFILE.ControlPlaneError, case["expected_failure"]
            ):
                self._validate_fixture_artifact(case["name"])

    def test_current_v2_requires_exact_rust_validator_recompile_evidence(self) -> None:
        fixtures = lock_currency_fixtures()
        recipe = fixtures["recipe_bytes"].encode()
        lock = lock_currency_case()
        with tempfile.TemporaryDirectory() as temporary:
            compiler = Path(temporary) / "lock-compiler"
            compiler.write_text("#!/bin/sh\nexit 41\n", encoding="utf-8")
            os.chmod(compiler, 0o755)
            configured = controller()
            configured["release"]["lock_compiler_digest"] = PROFILE._sha256_bytes(
                compiler.read_bytes()
            )
            with mock.patch.object(
                PROFILE,
                "_run_checked",
                side_effect=PROFILE.ControlPlaneError("lock-compiler failed: exit 41"),
            ), self.assertRaisesRegex(PROFILE.ControlPlaneError, "lock-compiler failed"):
                PROFILE.validate_artifact_bytes(
                    recipe,
                    json.dumps(lock, sort_keys=True, separators=(",", ":")).encode(),
                    compiler,
                    configured,
                    repo="KleinPerkins/awa",
                    profile_id="awa-pilot.v1",
                    profile_digest="sha256:" + "a" * 64,
                )

    @staticmethod
    def _plan_args(entry: dict) -> object:
        return PROFILE.argparse.Namespace(
            dev_root="/fixture/dev",
            target_root=f"/fixture/{entry['catalog_repository_id']}",
            repo=entry["repo"],
            coverage_mode=entry["coverage_mode"],
            profile_id=entry["profile_ref"]["id"],
            lock_compiler="/fixture/lock-compiler",
            release_manifest="/fixture/release-manifest.json",
        )

    def test_command_plan_emits_one_final_15_repository_v1_to_v2_migration(self) -> None:
        assignments = json.loads((HERE / "coverage-assignments.json").read_text(encoding="utf-8"))
        fleet_value = json.loads((HERE / "fleet.json").read_text(encoding="utf-8"))
        configured = controller()
        self.assertEqual(len(fleet_value["targets"]), 15)
        self.assertEqual(len(assignments["assignments"]), 15)

        migration_plans: list[dict] = []
        for entry in assignments["assignments"]:
            legacy = self._assignment_lock(lock_currency_case("legacy_v1"), entry)
            current = self._assignment_lock(lock_currency_case(), entry)

            def git_file(_: Path, __: str, path: str) -> bytes | None:
                if path == PROFILE.RECIPE:
                    return lock_currency_fixtures()["recipe_bytes"].encode()
                if path == PROFILE.LOCK:
                    return json.dumps(legacy).encode()
                raise AssertionError(path)

            emitted: list[dict] = []
            with mock.patch.object(PROFILE, "_assert_origin"), mock.patch.object(
                PROFILE, "_assert_origin_default_fresh"
            ), mock.patch.object(
                PROFILE,
                "_authorities",
                return_value=(assignments, fleet_value, configured),
            ), mock.patch.object(
                PROFILE,
                "fetch_live_repository_metadata",
                return_value=(
                    {
                        "repository_id": next(
                            target["repository_id"]
                            for target in fleet_value["targets"]
                            if target["repo"] == entry["repo"]
                        ),
                        "full_name": entry["repo"],
                        "default_branch": "main",
                    },
                    next(
                        target
                        for target in fleet_value["targets"]
                        if target["repo"] == entry["repo"]
                    ),
                ),
            ), mock.patch.object(
                PROFILE, "_git_file_at", side_effect=git_file
            ), mock.patch.object(
                PROFILE, "validate_qualified_release", return_value={"qualified": True}
            ), mock.patch.object(
                PROFILE,
                "compile_repository_lock_at_ref",
                return_value=(json.dumps(current).encode(), entry["profile_ref"]["digest"]),
            ), mock.patch.object(
                PROFILE, "_emit", side_effect=emitted.append
            ):
                PROFILE.command_plan(self._plan_args(entry))
            self.assertEqual(len(emitted), 1)
            migration_plans.append(emitted[0])

        self.assertEqual(len(migration_plans), 15)
        self.assertEqual({plan["phase"] for plan in migration_plans}, {"relock"})
        self.assertEqual(
            {plan["repo"] for plan in migration_plans},
            {target["repo"] for target in fleet_value["targets"]},
        )

    def test_command_plan_release_only_change_needs_no_fleet_relock(self) -> None:
        assignments = json.loads((HERE / "coverage-assignments.json").read_text(encoding="utf-8"))
        fleet_value = json.loads((HERE / "fleet.json").read_text(encoding="utf-8"))
        configured = controller()
        configured["release"].update(lock_currency_fixtures()["release_only_change"]["after"])
        recipe = lock_currency_fixtures()["recipe_bytes"].encode()
        phases: list[str] = []
        for entry in assignments["assignments"]:
            current = self._assignment_lock(lock_currency_case(), entry)
            lock_bytes = json.dumps(current).encode()

            def git_file(_: Path, __: str, path: str) -> bytes | None:
                if path == PROFILE.RECIPE:
                    return recipe
                if path == PROFILE.LOCK:
                    return lock_bytes
                raise AssertionError(path)

            emitted: list[dict] = []
            with mock.patch.object(PROFILE, "_assert_origin"), mock.patch.object(
                PROFILE, "_assert_origin_default_fresh"
            ), mock.patch.object(
                PROFILE,
                "_authorities",
                return_value=(assignments, fleet_value, configured),
            ), mock.patch.object(
                PROFILE,
                "fetch_live_repository_metadata",
                return_value=(
                    {
                        "repository_id": next(
                            target["repository_id"]
                            for target in fleet_value["targets"]
                            if target["repo"] == entry["repo"]
                        ),
                        "full_name": entry["repo"],
                        "default_branch": "main",
                    },
                    next(
                        target
                        for target in fleet_value["targets"]
                        if target["repo"] == entry["repo"]
                    ),
                ),
            ), mock.patch.object(
                PROFILE, "_git_file_at", side_effect=git_file
            ), mock.patch.object(
                PROFILE,
                "_git",
                return_value=current["payload"]["recipe_blob_sha"],
            ), mock.patch.object(
                PROFILE, "_assert_compiler"
            ), mock.patch.object(
                PROFILE,
                "_run_checked",
                return_value=subprocess.CompletedProcess(
                    ["lock-compiler", "validate"],
                    0,
                    stdout=b"valid lock_digest=fixture jobs=1\n",
                    stderr=b"",
                ),
            ), mock.patch.object(
                PROFILE, "validate_qualified_release", return_value={"qualified": True}
            ), mock.patch.object(
                PROFILE, "compile_repository_lock_at_ref"
            ) as compile_lock, mock.patch.object(
                PROFILE, "_emit", side_effect=emitted.append
            ):
                PROFILE.command_plan(self._plan_args(entry))
            self.assertEqual(len(emitted), 1)
            phases.append(emitted[0]["phase"])
            compile_lock.assert_not_called()
        self.assertEqual(phases, ["current"] * 15)

    def test_bare_release_only_change_requires_policy_rebind_and_deploy_not_relock(self) -> None:
        fixture = lock_currency_fixtures()["release_only_change"]
        before = controller()
        after = copy.deepcopy(before)
        before["release"].update(fixture["before"])
        after["release"].update(fixture["after"])
        lock_bytes = json.dumps(lock_currency_case()).encode()
        kwargs = {
            "repo": "KleinPerkins/awa",
            "profile_id": "awa-pilot.v1",
            "profile_digest": "sha256:" + "a" * 64,
            "artifact_validation": self._artifact_validation,
        }
        self.assertTrue(PROFILE.lock_is_current(lock_bytes, before, **kwargs))
        self.assertTrue(PROFILE.lock_is_current(lock_bytes, after, **kwargs))
        self.assertEqual(
            PROFILE.rollout_phase(
                True, True, "local", "local", lock_current=True
            ),
            "current",
        )
        stale_policy = repository_policy(
            "KleinPerkins/awa",
            policy_digest=fixture["before"]["digest"],
            policy_generation=3,
        )
        rebound_policy = repository_policy(
            "KleinPerkins/awa",
            policy_digest=fixture["after"]["digest"],
            policy_generation=3,
        )
        with mock.patch.object(PROFILE, "RELEASE_DIGEST", fixture["after"]["digest"]):
            with self.assertRaisesRegex(SystemExit, "controller release digest"):
                PROFILE.validate_policy(
                    stale_policy,
                    "release-only stale policy",
                    assignments=assignment(),
                    fleet=fleet(),
                    controller=after,
                )
            PROFILE.validate_policy(
                rebound_policy,
                "release-only rebound policy",
                assignments=assignment(),
                fleet=fleet(),
                controller=after,
            )
        self.assertTrue(fixture["expected"]["policy_rebind"])
        self.assertTrue(fixture["expected"]["deployment"])
        self.assertNotEqual(
            (
                fixture["before"]["version"],
                fixture["before"]["digest"],
                fixture["before"]["lock_compiler_digest"],
            ),
            (
                fixture["after"]["version"],
                fixture["after"]["digest"],
                fixture["after"]["lock_compiler_digest"],
            ),
        )
        self.assertFalse(fixture["expected"]["relock"])

    def test_profile_image_override_is_lock_currency_authority(self) -> None:
        configured = controller()
        configured["images"]["profile_overrides"] = PROFILE.PROFILE_IMAGE_OVERRIDES
        lock = lock_currency_case()
        payload = lock["payload"]
        payload["profile_id"] = "awa-authoritative-verify.v1"
        payload["profile_digest"] = "sha256:" + "c" * 64
        payload["image_digest"] = PROFILE.PROFILE_IMAGE_OVERRIDES[
            "awa-authoritative-verify.v1"
        ]
        lock = _rehash_v2_lock(lock)
        kwargs = {
            "repo": "KleinPerkins/awa",
            "profile_id": "awa-authoritative-verify.v1",
            "profile_digest": "sha256:" + "c" * 64,
            "artifact_validation": lambda: self._artifact_validation(lock),
        }
        self.assertTrue(PROFILE.lock_is_current(json.dumps(lock).encode(), configured, **kwargs))

        stale = copy.deepcopy(lock)
        stale["payload"]["image_digest"] = configured["images"]["execution"]
        stale = _rehash_v2_lock(stale)
        self.assertFalse(
            PROFILE.lock_is_current(json.dumps(stale).encode(), configured, **kwargs)
        )


class FleetAuthorityTest(unittest.TestCase):
    AWA_ID = 1289571438
    AWA_REPO = "KleinPerkins/awa"
    AWA_RULESET_ID = 18819090

    @staticmethod
    def _authoritative_fleet() -> dict:
        return {
            "schema": "pr-automation-fleet/v3",
            "targets": [
                {
                    "repo": "KleinPerkins/awa",
                    "repository_id": 1289571438,
                    "default_branch": "main",
                    "merge_safety_ruleset_id": 18819090,
                },
                {
                    "repo": "KleinPerkins/dev",
                    "repository_id": 1278387789,
                    "default_branch": "main",
                    "merge_safety_ruleset_id": 18817500,
                },
            ],
        }

    def test_committed_awa_authority_binds_exact_live_ruleset_id(self) -> None:
        configured = json.loads((HERE / "fleet.json").read_text(encoding="utf-8"))
        target = PROFILE.resolve_fleet_target(
            configured,
            repository_id=self.AWA_ID,
            repo=self.AWA_REPO,
        )
        self.assertEqual(target["default_branch"], "main")
        self.assertEqual(target["merge_safety_ruleset_id"], self.AWA_RULESET_ID)

    def test_explicit_creation_atomically_promotes_one_null_ruleset_identity(self) -> None:
        configured = json.loads((HERE / "fleet.json").read_text(encoding="utf-8"))
        awa = next(item for item in configured["targets"] if item["repo"] == self.AWA_REPO)
        awa["merge_safety_ruleset_id"] = None
        with tempfile.TemporaryDirectory() as temporary:
            fleet_path = Path(temporary) / "fleet.json"
            fleet_path.write_text(json.dumps(configured), encoding="utf-8")
            PROFILE.record_created_ruleset_identity(
                fleet_path,
                repository_id=self.AWA_ID,
                repo=self.AWA_REPO,
                ruleset_id=self.AWA_RULESET_ID,
            )
            recorded = json.loads(fleet_path.read_text(encoding="utf-8"))
            self.assertEqual(
                next(
                    item["merge_safety_ruleset_id"]
                    for item in recorded["targets"]
                    if item["repo"] == self.AWA_REPO
                ),
                self.AWA_RULESET_ID,
            )
            with self.assertRaisesRegex(PROFILE.ControlPlaneError, "already has"):
                PROFILE.record_created_ruleset_identity(
                    fleet_path,
                    repository_id=self.AWA_ID,
                    repo=self.AWA_REPO,
                    ruleset_id=777,
                )

    def test_zero_multiple_or_mismatched_fleet_matches_fail_closed(self) -> None:
        configured = self._authoritative_fleet()
        cases = {
            "zero": (999, "KleinPerkins/not-enrolled", configured),
            "mismatched name": (self.AWA_ID, "KleinPerkins/dev", configured),
            "mismatched id": (1278387789, self.AWA_REPO, configured),
            "multiple": (
                self.AWA_ID,
                self.AWA_REPO,
                {
                    **configured,
                    "targets": [
                        *configured["targets"],
                        copy.deepcopy(configured["targets"][0]),
                    ],
                },
            ),
        }
        for label, (repository_id, repo, candidate) in cases.items():
            with self.subTest(label=label), self.assertRaisesRegex(
                PROFILE.ControlPlaneError,
                "exactly one enrolled|identity|unique",
            ):
                PROFILE.resolve_fleet_target(
                    candidate,
                    repository_id=repository_id,
                    repo=repo,
                )

    def test_unenrolled_projection_cannot_inherit_base_fingerprints(self) -> None:
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "exactly one enrolled"):
            PROFILE.resolve_repository_projection(
                assignment(),
                self._authoritative_fleet(),
                controller(),
                repository_id=999,
                repo="KleinPerkins/not-enrolled",
                default_branch="main",
            )

    def test_projection_rejects_default_branch_drift_from_fleet_authority(self) -> None:
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "default branch"):
            PROFILE.resolve_repository_projection(
                assignment(),
                self._authoritative_fleet(),
                controller(),
                repository_id=self.AWA_ID,
                repo=self.AWA_REPO,
                default_branch="release",
            )

    def test_remote_controls_bind_one_metadata_read_and_exact_ruleset_id(self) -> None:
        configured = self._authoritative_fleet()
        paths: list[str] = []

        def route(path: str) -> dict:
            paths.append(path)
            if path == f"repos/{self.AWA_REPO}":
                return {
                    "id": self.AWA_ID,
                    "full_name": self.AWA_REPO,
                    "default_branch": "main",
                }
            if path == "repos/KleinPerkins/dev":
                return {
                    "id": 1278387789,
                    "full_name": "KleinPerkins/dev",
                    "default_branch": "main",
                }
            if "/contents/" in path:
                repo = path.split("/contents/", 1)[0].removeprefix("repos/")
                return _gh_contents(
                    repository_policy(
                        repo,
                        policy_digest=PROFILE.RELEASE_DIGEST,
                        policy_generation=3,
                    )
                )
            if is_ruleset_list_path(path, self.AWA_REPO):
                return [
                    {
                        "id": self.AWA_RULESET_ID,
                        "name": PROFILE.MERGE_SAFETY_NAME,
                        "target": "branch",
                        "enforcement": "active",
                    }
                ]
            if is_ruleset_list_path(path, "KleinPerkins/dev"):
                return [
                    {
                        "id": 18817500,
                        "name": PROFILE.MERGE_SAFETY_NAME,
                        "target": "branch",
                        "enforcement": "active",
                    }
                ]
            if path == f"repos/{self.AWA_REPO}/rulesets/{self.AWA_RULESET_ID}":
                return {
                    **merge_safety_ruleset(ruleset_id=self.AWA_RULESET_ID),
                    "source_type": "Repository",
                    "source": self.AWA_REPO,
                }
            if path == "repos/KleinPerkins/dev/rulesets/18817500":
                return {
                    **merge_safety_ruleset(ruleset_id=18817500),
                    "source_type": "Repository",
                    "source": "KleinPerkins/dev",
                }
            raise AssertionError(f"unexpected API path: {path}")

        with mock.patch.object(PROFILE, "_gh_json", side_effect=route):
            controls = PROFILE.fetch_remote_repository_controls(configured)

        self.assertEqual(
            controls[self.AWA_REPO]["metadata"],
            {
                "repository_id": self.AWA_ID,
                "full_name": self.AWA_REPO,
                "default_branch": "main",
            },
        )
        self.assertIn(
            f"repos/{self.AWA_REPO}/rulesets?per_page=100&page=1",
            paths,
        )
        self.assertEqual(paths.count(f"repos/{self.AWA_REPO}"), 1)
        self.assertIn(
            f"repos/{self.AWA_REPO}/contents/{PROFILE.POLICY}?ref=main",
            paths,
        )

    def test_remote_controls_reject_duplicate_same_named_managed_rulesets(self) -> None:
        configured = {
            **self._authoritative_fleet(),
            "targets": [self._authoritative_fleet()["targets"][0]],
        }

        def route(path: str):
            if path == f"repos/{self.AWA_REPO}":
                return {
                    "id": self.AWA_ID,
                    "full_name": self.AWA_REPO,
                    "default_branch": "main",
                }
            if "/contents/" in path:
                return _gh_contents(
                    repository_policy(
                        self.AWA_REPO,
                        policy_digest=PROFILE.RELEASE_DIGEST,
                        policy_generation=3,
                    )
                )
            if is_ruleset_list_path(path, self.AWA_REPO):
                return [
                    {
                        "id": self.AWA_RULESET_ID,
                        "name": PROFILE.MERGE_SAFETY_NAME,
                        "target": "branch",
                        "enforcement": "active",
                    },
                    {
                        "id": 999999,
                        "name": PROFILE.MERGE_SAFETY_NAME,
                        "target": "branch",
                        "enforcement": "disabled",
                    },
                ]
            if path == f"repos/{self.AWA_REPO}/rulesets/{self.AWA_RULESET_ID}":
                return {
                    **merge_safety_ruleset(ruleset_id=self.AWA_RULESET_ID),
                    "source_type": "Repository",
                    "source": self.AWA_REPO,
                }
            raise AssertionError(f"unexpected API path: {path}")

        with mock.patch.object(PROFILE, "_gh_json", side_effect=route), self.assertRaisesRegex(
            PROFILE.ControlPlaneError,
            "exactly one|duplicate|managed ruleset",
        ):
            PROFILE.fetch_remote_repository_controls(configured)

    def test_remote_controls_reject_managed_duplicate_on_second_page(self) -> None:
        configured = {
            **self._authoritative_fleet(),
            "targets": [self._authoritative_fleet()["targets"][0]],
        }
        first_page = [
            {
                "id": self.AWA_RULESET_ID,
                "name": PROFILE.MERGE_SAFETY_NAME,
                "target": "branch",
                "enforcement": "active",
            },
            *[
                {
                    "id": 20000000 + index,
                    "name": f"unrelated-{index}",
                    "target": "branch",
                    "enforcement": "active",
                }
                for index in range(99)
            ],
        ]
        paths: list[str] = []

        def route(path: str):
            paths.append(path)
            if path == f"repos/{self.AWA_REPO}":
                return {
                    "id": self.AWA_ID,
                    "full_name": self.AWA_REPO,
                    "default_branch": "main",
                }
            if "/contents/" in path:
                return _gh_contents(
                    repository_policy(
                        self.AWA_REPO,
                        policy_digest=PROFILE.RELEASE_DIGEST,
                        policy_generation=3,
                    )
                )
            if path in {
                f"repos/{self.AWA_REPO}/rulesets",
                f"repos/{self.AWA_REPO}/rulesets?per_page=100&page=1",
            }:
                return first_page
            if path == f"repos/{self.AWA_REPO}/rulesets?per_page=100&page=2":
                return [
                    {
                        "id": 999999,
                        "name": PROFILE.MERGE_SAFETY_NAME,
                        "target": "branch",
                        "enforcement": "disabled",
                    }
                ]
            if path == f"repos/{self.AWA_REPO}/rulesets/{self.AWA_RULESET_ID}":
                return {
                    **merge_safety_ruleset(ruleset_id=self.AWA_RULESET_ID),
                    "source_type": "Repository",
                    "source": self.AWA_REPO,
                }
            raise AssertionError(f"unexpected API path: {path}")

        with mock.patch.object(PROFILE, "_gh_json", side_effect=route), self.assertRaisesRegex(
            PROFILE.ControlPlaneError,
            "exactly one",
        ):
            PROFILE.fetch_remote_repository_controls(configured)
        self.assertIn(
            f"repos/{self.AWA_REPO}/rulesets?per_page=100&page=2",
            paths,
        )

    def test_live_repository_metadata_uses_controller_default_branch_contract(self) -> None:
        for label, branch in {
            "empty": "",
            "slash": "release/next",
            "non-ascii": "café",
            "over-100-bytes": "a" * 101,
        }.items():
            configured = self._authoritative_fleet()
            configured["targets"][0]["default_branch"] = branch
            with self.subTest(label=label), mock.patch.object(
                PROFILE,
                "_gh_json",
                return_value={
                    "id": self.AWA_ID,
                    "full_name": self.AWA_REPO,
                    "default_branch": branch,
                },
            ), self.assertRaises(PROFILE.ControlPlaneError):
                PROFILE.fetch_live_repository_metadata(configured, self.AWA_REPO)

        exact = self._authoritative_fleet()
        exact["targets"][0]["default_branch"] = "a" * 100
        with mock.patch.object(
            PROFILE,
            "_gh_json",
            return_value={
                "id": self.AWA_ID,
                "full_name": self.AWA_REPO,
                "default_branch": "a" * 100,
            },
        ):
            metadata, target = PROFILE.fetch_live_repository_metadata(
                exact,
                self.AWA_REPO,
            )
        self.assertEqual(metadata["default_branch"], "a" * 100)
        self.assertEqual(target["default_branch"], "a" * 100)

    def test_remote_controls_reject_metadata_and_ruleset_identity_drift(self) -> None:
        configured = {
            **self._authoritative_fleet(),
            "targets": [self._authoritative_fleet()["targets"][0]],
        }
        drifts = {
            "repository id": {
                "metadata": {
                    "id": 7,
                    "full_name": self.AWA_REPO,
                    "default_branch": "main",
                }
            },
            "full name": {
                "metadata": {
                    "id": self.AWA_ID,
                    "full_name": "KleinPerkins/not-awa",
                    "default_branch": "main",
                }
            },
            "default branch": {
                "metadata": {
                    "id": self.AWA_ID,
                    "full_name": self.AWA_REPO,
                    "default_branch": "release",
                }
            },
            "ruleset id": {"ruleset": {"id": 7}},
            "ruleset name": {"ruleset": {"name": "renamed"}},
            "ruleset target": {"ruleset": {"target": "tag"}},
            "ruleset source": {"ruleset": {"source": "KleinPerkins/dev"}},
        }
        for label, drift in drifts.items():
            metadata = {
                "id": self.AWA_ID,
                "full_name": self.AWA_REPO,
                "default_branch": "main",
                **drift.get("metadata", {}),
            }
            ruleset = {
                **merge_safety_ruleset(ruleset_id=self.AWA_RULESET_ID),
                "source_type": "Repository",
                "source": self.AWA_REPO,
                **drift.get("ruleset", {}),
            }

            def route(path: str, *, metadata: dict = metadata, ruleset: dict = ruleset) -> dict:
                if path == f"repos/{self.AWA_REPO}":
                    return metadata
                if "/contents/" in path:
                    return _gh_contents(
                        repository_policy(
                            self.AWA_REPO,
                            policy_digest=PROFILE.RELEASE_DIGEST,
                            policy_generation=3,
                        )
                    )
                if is_ruleset_list_path(path, self.AWA_REPO):
                    return [
                        {
                            "id": self.AWA_RULESET_ID,
                            "name": PROFILE.MERGE_SAFETY_NAME,
                            "target": "branch",
                            "enforcement": "active",
                        }
                    ]
                if path == f"repos/{self.AWA_REPO}/rulesets/{self.AWA_RULESET_ID}":
                    return ruleset
                raise AssertionError(f"unexpected API path: {path}")

            with self.subTest(label=label), mock.patch.object(
                PROFILE,
                "_gh_json",
                side_effect=route,
            ), self.assertRaisesRegex(
                PROFILE.ControlPlaneError,
                "identity|default branch|ruleset",
            ):
                PROFILE.fetch_remote_repository_controls(configured)


class RequiredCheckProjectionTest(unittest.TestCase):
    AWA_ID = 1289571438
    AWA_REPO = "KleinPerkins/awa"
    DEV_ID = 1278387789
    DEV_REPO = "KleinPerkins/dev"
    ECOSYSTEM_ORCHESTRATOR_ID = 1281300995
    ECOSYSTEM_ORCHESTRATOR_REPO = "KleinPerkins/ecosystem-orchestrator"
    INTENT_ROUTER_ID = 1294651532
    INTENT_ROUTER_REPO = "KleinPerkins/intent-router"
    KP_MCP_ID = 1271164179
    KP_MCP_REPO = "KleinPerkins/kp-mcp"
    KP_PR_BOT_CANARY_ID = 1297059298
    KP_PR_BOT_CANARY_REPO = "KleinPerkins/kp-pr-bot-canary"
    LOCAL_JOBS_ID = 1284625858
    LOCAL_JOBS_REPO = "KleinPerkins/local-jobs"
    OPERATOR_VOICE_ID = 1317232260
    OPERATOR_VOICE_REPO = "KleinPerkins/operator-voice"
    PR_AUTOMATION_CONTROLLER_ID = 1297666445
    PR_AUTOMATION_CONTROLLER_REPO = "KleinPerkins/pr-automation-controller"
    SKILLS_ID = 1275604090
    SKILLS_REPO = "KleinPerkins/skills"
    JOB_ID = "repo.awa.engine-tests"
    NODE_CONTEXT = "pr-automation / job:repo.awa.engine-tests"
    DEV_JOB_ID = "repo.dev.m3-verify"
    ECOSYSTEM_ORCHESTRATOR_JOB_ID = "repo.ecosystem-orchestrator.m3-verify"
    INTENT_ROUTER_JOB_ID = "repo.intent-router.m3-verify"
    KP_MCP_JOB_ID = "repo.kp-mcp.m3-verify"
    KP_PR_BOT_CANARY_JOB_ID = "repo.kp-pr-bot-canary.m3-verify"
    LOCAL_JOBS_JOB_ID = "repo.local-jobs.m3-verify"
    OPERATOR_VOICE_JOB_ID = "repo.operator-voice.m3-verify"
    PR_AUTOMATION_CONTROLLER_JOB_ID = "repo.pr-automation-controller.m3-verify"
    SKILLS_JOB_ID = "repo.skills.m3-verify"

    @staticmethod
    def _real_authorities() -> tuple[dict, dict, dict]:
        assignments = json.loads((HERE / "coverage-assignments.json").read_text(encoding="utf-8"))
        assignments["schema"] = "pr-automation-coverage-assignments/v2"
        fleet_value = json.loads((HERE / "fleet.json").read_text(encoding="utf-8"))
        controller_value = json.loads((HERE / "controller.json").read_text(encoding="utf-8"))
        controller_value["ruleset_fingerprints"].setdefault("repository_overrides", {})
        return assignments, fleet_value, controller_value

    def _aggregate_only_authorities(self) -> tuple[dict, dict, dict]:
        assignments, fleet_value, controller_value = self._real_authorities()
        for item in assignments["assignments"]:
            item.pop("required_checks", None)
        controller_value["ruleset_fingerprints"]["repository_overrides"] = {}
        return assignments, fleet_value, controller_value

    def _candidate_authorities(self) -> tuple[dict, dict, dict]:
        assignments, fleet_value, controller_value = self._aggregate_only_authorities()
        awa = next(item for item in assignments["assignments"] if item["repo"] == self.AWA_REPO)
        awa["required_checks"] = {
            "schema": "pr-automation-required-checks/v1",
            "job_id": self.JOB_ID,
        }
        draft = PROFILE.resolve_repository_projection(
            assignments,
            fleet_value,
            controller_value,
            repository_id=self.AWA_ID,
            repo=self.AWA_REPO,
            default_branch="main",
            enforce_fingerprint_pins=False,
        )
        controller_value["ruleset_fingerprints"]["repository_overrides"] = {
            str(self.AWA_ID): {
                "runtime_app_visible": draft.runtime_app_visible_fingerprints,
                "operator_full": draft.operator_full_fingerprints,
            }
        }
        return assignments, fleet_value, controller_value

    @staticmethod
    def _complete_live_config(
        assignments: dict,
        fleet_value: dict,
        configured: dict,
    ) -> bytes:
        assignment_by_repo = {
            item["repo"]: {
                key: copy.deepcopy(value)
                for key, value in item.items()
                if key != "repo"
            }
            for item in assignments["assignments"]
        }
        repositories = []
        for target in fleet_value["targets"]:
            owner, name = target["repo"].split("/", 1)
            projection = PROFILE.resolve_repository_projection(
                assignments,
                fleet_value,
                configured,
                repository_id=target["repository_id"],
                repo=target["repo"],
                default_branch=target["default_branch"],
            )
            repositories.append(
                {
                    "id": target["repository_id"],
                    "owner": owner,
                    "name": name,
                    "default_branch": target["default_branch"],
                    "policy_path": ".github/pr-automation.json",
                    "manifest_path": ".github/pr-verification.json",
                    "protected_paths": [".github", "CODEOWNERS", "_ops"],
                    "expected_ruleset_fingerprints": (
                        projection.runtime_app_visible_fingerprints
                    ),
                    "max_changed_files": 200,
                    "max_total_patch_bytes": 5_000_000,
                    "coverage_assignment": copy.deepcopy(
                        assignment_by_repo.get(target["repo"])
                    ),
                }
            )
        value = {
            "version": "pr-automation-controller/v1",
            "account_login": "KleinPerkins",
            "check_name": "pr-automation / verify",
            "activation_generation": configured["release"]["activation_generation"],
            "controller_release_digest": configured["release"]["digest"],
            "verifier": {
                "app_id": 4274739,
                "integration_id": 4274739,
                "installation_id": 145944952,
                "slug": "kleinperkins-verify-bot",
                "app_node_id": "A_verifier",
                "bot_login": "kleinperkins-verify-bot[bot]",
                "key_path": "/secure/verifier.pem",
                "repository_selection": "selected",
                "permissions": {
                    "administration": "read",
                    "checks": "write",
                    "contents": "read",
                    "metadata": "read",
                    "pull_requests": "read",
                    "statuses": "write",
                },
            },
            "reviewer": {
                "app_id": 4269364,
                "integration_id": 4269364,
                "installation_id": 145790860,
                "slug": "kleinperkins-review-bot",
                "app_node_id": "A_reviewer",
                "bot_login": "kleinperkins-review-bot[bot]",
                "key_path": "/secure/reviewer.pem",
                "repository_selection": "all",
                "permissions": {
                    "contents": "write",
                    "metadata": "read",
                    "pull_requests": "write",
                },
            },
            "installation_repositories": [
                {"id": target["repository_id"], "name": target["repo"].split("/", 1)[1]}
                for target in fleet_value["targets"]
            ],
            "repositories": repositories,
            "exclusions": ["chaos-scheduler"],
            "runtime": {
                "max_open_pull_requests_per_repository": 20,
                "poll_timeout_seconds": 600,
                "fetch_profile": "pr-auto-fetch",
                "execution_profile": "pr-auto-exec",
                "fetch_image": configured["images"]["fetch"],
            },
        }
        return (json.dumps(value, indent=2) + "\n").encode()

    def test_assignment_schema_v2_is_closed_and_committed_source_is_inert(self) -> None:
        schema = json.loads(
            (HERE / "coverage-assignments.schema.json").read_text(encoding="utf-8")
        )
        source = json.loads((HERE / "coverage-assignments.json").read_text(encoding="utf-8"))
        configured = json.loads((HERE / "controller.json").read_text(encoding="utf-8"))
        controller_schema = json.loads(
            (HERE / "controller.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["schema"]["const"], "pr-automation-coverage-assignments/v2")
        assignment_schema = schema["properties"]["assignments"]["items"]
        self.assertFalse(assignment_schema["additionalProperties"])
        self.assertIn("required_checks", assignment_schema["properties"])
        job_schema = assignment_schema["properties"]["required_checks"]["properties"]["job_id"]
        self.assertEqual(
            job_schema["pattern"],
            r"^repo\.[a-z0-9._-]+$",
        )
        self.assertEqual(
            job_schema["maxLength"],
            100 - len("pr-automation / job:".encode("ascii")),
        )
        self.assertEqual(
            set(assignment_schema["properties"]["required_checks"]["type"]),
            {"object", "null"},
        )
        self.assertIn(
            "repository_overrides",
            controller_schema["properties"]["ruleset_fingerprints"]["properties"],
        )
        for schema_name, document in (
            ("coverage-assignments.schema.json", schema),
            ("controller.schema.json", controller_schema),
        ):
            stack = [document]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    if "pattern" in node:
                        self.assertEqual(
                            node.get("type"),
                            "string",
                            f"{schema_name} pattern lacks explicit string type: {node}",
                        )
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
        PROFILE.validate_json_schema_instance(
            schema,
            source,
            source="coverage-assignments.json",
        )
        PROFILE.validate_json_schema_instance(
            controller_schema,
            configured,
            source="controller.json",
        )
        self.assertEqual(source["schema"], "pr-automation-coverage-assignments/v2")
        awa = next(item for item in source["assignments"] if item["repo"] == self.AWA_REPO)
        dev = next(item for item in source["assignments"] if item["repo"] == self.DEV_REPO)
        ecosystem_orchestrator = next(
            item
            for item in source["assignments"]
            if item["repo"] == self.ECOSYSTEM_ORCHESTRATOR_REPO
        )
        intent_router = next(
            item for item in source["assignments"] if item["repo"] == self.INTENT_ROUTER_REPO
        )
        kp_mcp = next(
            item for item in source["assignments"] if item["repo"] == self.KP_MCP_REPO
        )
        kp_pr_bot_canary = next(
            item
            for item in source["assignments"]
            if item["repo"] == self.KP_PR_BOT_CANARY_REPO
        )
        local_jobs = next(
            item for item in source["assignments"] if item["repo"] == self.LOCAL_JOBS_REPO
        )
        operator_voice = next(
            item for item in source["assignments"] if item["repo"] == self.OPERATOR_VOICE_REPO
        )
        pr_automation_controller = next(
            item
            for item in source["assignments"]
            if item["repo"] == self.PR_AUTOMATION_CONTROLLER_REPO
        )
        skills = next(
            item for item in source["assignments"] if item["repo"] == self.SKILLS_REPO
        )
        self.assertEqual(
            awa["required_checks"],
            {
                "job_id": self.JOB_ID,
                "schema": "pr-automation-required-checks/v1",
            },
        )
        self.assertEqual(
            dev["required_checks"],
            {
                "job_id": self.DEV_JOB_ID,
                "schema": "pr-automation-required-checks/v1",
            },
        )
        self.assertEqual(
            ecosystem_orchestrator["required_checks"],
            {
                "job_id": self.ECOSYSTEM_ORCHESTRATOR_JOB_ID,
                "schema": "pr-automation-required-checks/v1",
            },
        )
        self.assertEqual(
            intent_router["required_checks"],
            {
                "job_id": self.INTENT_ROUTER_JOB_ID,
                "schema": "pr-automation-required-checks/v1",
            },
        )
        self.assertEqual(
            kp_mcp["required_checks"],
            {
                "job_id": self.KP_MCP_JOB_ID,
                "schema": "pr-automation-required-checks/v1",
            },
        )
        self.assertEqual(
            kp_pr_bot_canary["required_checks"],
            {
                "job_id": self.KP_PR_BOT_CANARY_JOB_ID,
                "schema": "pr-automation-required-checks/v1",
            },
        )
        self.assertEqual(
            local_jobs["required_checks"],
            {
                "job_id": self.LOCAL_JOBS_JOB_ID,
                "schema": "pr-automation-required-checks/v1",
            },
        )
        self.assertEqual(
            operator_voice["required_checks"],
            {
                "job_id": self.OPERATOR_VOICE_JOB_ID,
                "schema": "pr-automation-required-checks/v1",
            },
        )
        self.assertEqual(
            pr_automation_controller["required_checks"],
            {
                "job_id": self.PR_AUTOMATION_CONTROLLER_JOB_ID,
                "schema": "pr-automation-required-checks/v1",
            },
        )
        self.assertEqual(
            skills["required_checks"],
            {
                "job_id": self.SKILLS_JOB_ID,
                "schema": "pr-automation-required-checks/v1",
            },
        )
        self.assertEqual(
            configured["ruleset_fingerprints"]["repository_overrides"],
            {
                str(self.KP_MCP_ID): {
                    "operator_full": [
                        "sha256:e1454004b8dea2dd071ae4a6417acfaa5de1fd05f9e9212680921ca395b033bf"
                    ],
                    "runtime_app_visible": [
                        "sha256:a2c29466611d4f73471e7cc437f7eef8be0ec6d79126f6bfa9903e87c4235ee1"
                    ],
                },
                str(self.SKILLS_ID): {
                    "operator_full": [
                        "sha256:0edbcbac4b41827dc87b007b8e27c1ea6455a361d9820591eaeda934620658d5"
                    ],
                    "runtime_app_visible": [
                        "sha256:1ed526a60d5b67008c5d532a78b8374991a50108ad37c7d7556e6e4a9a1800fa"
                    ],
                },
                str(self.DEV_ID): {
                    "operator_full": [
                        "sha256:1e2bc2245d980fdd4b2cc6a393dfed2f2f35f914c7d089f87104f154dcb85216"
                    ],
                    "runtime_app_visible": [
                        "sha256:9d576bc9683055249964b3d3a48a2bd3dd5c4768b1f63059c8324ea2c3eac2b4"
                    ],
                },
                str(self.ECOSYSTEM_ORCHESTRATOR_ID): {
                    "operator_full": [
                        "sha256:b1b7a3d69f8c88f09d85f771beb0a857799de8cba7829b75f898d09b99346be1"
                    ],
                    "runtime_app_visible": [
                        "sha256:c8fde1f50a0a277c838f172edfc47297a2bd15d7fc3ded7458aef346f26ea1e8"
                    ],
                },
                str(self.LOCAL_JOBS_ID): {
                    "operator_full": [
                        "sha256:a2065286a4e489b7b0eca276957c49c486d5d275ed97c3a0ee2f8c4745c36c85"
                    ],
                    "runtime_app_visible": [
                        "sha256:d122ca2f135b072192a9f9f67928569c94fd93ab095dd720490738998de2aa07"
                    ],
                },
                str(self.AWA_ID): {
                    "operator_full": [
                        "sha256:536bca2e9fa1f6beb2afef4bf55e5ee2705cc5c595587a80cf4c2c8ed3b9abb5"
                    ],
                    "runtime_app_visible": [
                        "sha256:9c7331fbd34c4d2631258d8c1217e65024c0b4e1d43e3946f6a25193199050ee"
                    ],
                },
                str(self.INTENT_ROUTER_ID): {
                    "operator_full": [
                        "sha256:67398c3db5ccac5aefef58bf4a2aafcad41896a0d17f9e07b15a7a901c77515a"
                    ],
                    "runtime_app_visible": [
                        "sha256:18d01ea71496cc25315073a85f5e221c7b36b8d88e8d26439cf039cb6c1395fd"
                    ],
                },
                str(self.KP_PR_BOT_CANARY_ID): {
                    "operator_full": [
                        "sha256:1d7edf56d65cee0fb9fea5876f43b3927a66c5e2b20a4c39ee31212a258fc77d"
                    ],
                    "runtime_app_visible": [
                        "sha256:d934ec23260a9e4c6e6ab80d9a3a4ce8700c082b0931d9b35aba50059e44d80a"
                    ],
                },
                str(self.PR_AUTOMATION_CONTROLLER_ID): {
                    "operator_full": [
                        "sha256:2374e55ef18a65b111630251717c10a05eb8ed353c292fb6ffda59b456deb318"
                    ],
                    "runtime_app_visible": [
                        "sha256:59bab03df9a20422fe8a29b13c3c2a4655003ede4c681e4a17853428a2df7517"
                    ],
                },
                str(self.OPERATOR_VOICE_ID): {
                    "operator_full": [
                        "sha256:72c5277681b5f2296f8210f5ac29010df95fe0607215b64a41d0f0836ffad5b3"
                    ],
                    "runtime_app_visible": [
                        "sha256:f5e80627ca1c737f333837dc68059dc758201e98a9bea2f2b8e00e72dcbffc50"
                    ],
                },
            },
        )

    def test_schema_validator_enforces_maximum_and_rejects_unknown_assertions(self) -> None:
        PROFILE.validate_json_schema_instance(
            {"type": "integer", "maximum": 100},
            100,
            source="maximum exact bound",
        )
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "maximum"):
            PROFILE.validate_json_schema_instance(
                {"type": "integer", "maximum": 100},
                101,
                source="maximum overflow",
            )
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "unsupported schema keyword"):
            PROFILE.validate_json_schema_instance(
                {"type": "integer", "unknownAssertion": True},
                4,
                source="unknown assertion",
            )

    def test_schema_validator_rejects_malformed_supported_keyword_values(self) -> None:
        malformed = {
            "required": ({"type": "object", "required": "name"}, {}),
            "additionalProperties": (
                {"type": "object", "additionalProperties": "false"},
                {},
            ),
            "minimum": ({"type": "number", "minimum": "0"}, 1),
            "maximum": ({"type": "number", "maximum": True}, 1),
            "minLength": ({"type": "string", "minLength": -1}, "x"),
            "maxItems": ({"type": "array", "maxItems": -1}, []),
            "uniqueItems": ({"type": "array", "uniqueItems": "true"}, []),
            "enum": ({"enum": "value"}, "value"),
        }
        for keyword, (schema, instance) in malformed.items():
            with self.subTest(keyword=keyword), self.assertRaisesRegex(
                PROFILE.ControlPlaneError,
                keyword,
            ):
                PROFILE.validate_json_schema_instance(
                    schema,
                    instance,
                    source=f"malformed {keyword}",
                )

        PROFILE.validate_json_schema_instance(
            {"type": "number", "minimum": 0, "maximum": 10},
            0,
            source="numeric lower bound",
        )
        PROFILE.validate_json_schema_instance(
            {"type": "number", "minimum": 0, "maximum": 10},
            10,
            source="numeric upper bound",
        )
        for value in (-1, 11):
            with self.subTest(numeric=value), self.assertRaises(
                PROFILE.ControlPlaneError
            ):
                PROFILE.validate_json_schema_instance(
                    {"type": "number", "minimum": 0, "maximum": 10},
                    value,
                    source="numeric outside bound",
                )

    def test_schema_validator_distinguishes_null_applicators_from_absence(self) -> None:
        cases = {
            "items": ({"type": "array", "items": None}, []),
            "contains": ({"type": "array", "contains": None}, []),
            "if": ({"if": None}, {}),
            "then": ({"if": {}, "then": None}, {}),
            "else": ({"if": {}, "else": None}, {}),
            "propertyNames": ({"type": "object", "propertyNames": None}, {}),
            "additionalProperties": (
                {"type": "object", "additionalProperties": None},
                {},
            ),
        }
        for keyword, (schema, instance) in cases.items():
            with self.subTest(keyword=keyword), self.assertRaisesRegex(
                PROFILE.ControlPlaneError,
                keyword,
            ):
                PROFILE.validate_json_schema_instance(
                    schema,
                    instance,
                    source=f"null {keyword}",
                )

    def test_schema_validator_rejects_non_schema_applicator_values(self) -> None:
        cases = {
            "items": ({"type": "array", "items": "schema"}, []),
            "contains": ({"type": "array", "contains": []}, []),
            "if": ({"if": 1}, {}),
            "then": ({"if": {}, "then": "schema"}, {}),
            "else": ({"if": {}, "else": []}, {}),
            "propertyNames": ({"type": "object", "propertyNames": 0}, {}),
        }
        for keyword, (schema, instance) in cases.items():
            with self.subTest(keyword=keyword), self.assertRaisesRegex(
                PROFILE.ControlPlaneError,
                keyword,
            ):
                PROFILE.validate_json_schema_instance(
                    schema,
                    instance,
                    source=f"malformed {keyword}",
                )

    def test_schema_validator_rejects_null_schema_maps_and_combinators(self) -> None:
        for keyword in ("$defs", "definitions", "properties", "allOf", "type"):
            with self.subTest(keyword=keyword), self.assertRaises(
                PROFILE.ControlPlaneError
            ):
                PROFILE.validate_json_schema_instance(
                    {keyword: None},
                    {},
                    source=f"null {keyword}",
                )

    def test_schema_validator_supports_boolean_applicator_schemas(self) -> None:
        accepted = [
            ({"type": "array", "items": True}, [1]),
            ({"type": "array", "contains": True}, [1]),
            ({"type": "object", "propertyNames": True}, {"name": 1}),
            ({"type": "object", "additionalProperties": True}, {"extra": 1}),
            ({"if": False, "then": False}, "value"),
            ({"if": True, "else": False}, "value"),
            ({"allOf": [True, {}]}, "value"),
            ({"$defs": {"allowed": True}, "$ref": "#/$defs/allowed"}, "value"),
        ]
        for schema, instance in accepted:
            with self.subTest(accepted=schema):
                PROFILE.validate_json_schema_instance(
                    schema,
                    instance,
                    source="boolean applicator accepted",
                )

        rejected = [
            ({"type": "array", "items": False}, [1]),
            ({"type": "array", "contains": False}, [1]),
            ({"type": "object", "propertyNames": False}, {"name": 1}),
            ({"type": "object", "additionalProperties": False}, {"extra": 1}),
            ({"if": True, "then": False}, "value"),
            ({"if": False, "else": False}, "value"),
            ({"allOf": [True, False]}, "value"),
            ({"$defs": {"denied": False}, "$ref": "#/$defs/denied"}, "value"),
        ]
        for schema, instance in rejected:
            with self.subTest(rejected=schema), self.assertRaises(
                PROFILE.ControlPlaneError
            ):
                PROFILE.validate_json_schema_instance(
                    schema,
                    instance,
                    source="boolean applicator rejected",
                )

    def test_schema_validator_eagerly_rejects_refs_in_unused_definitions(self) -> None:
        for definitions_keyword in ("$defs", "definitions"):
            with self.subTest(
                definitions=definitions_keyword,
                kind="unresolved",
            ), self.assertRaisesRegex(PROFILE.ControlPlaneError, "unresolved schema reference"):
                PROFILE.validate_json_schema_instance(
                    {
                        "type": "object",
                        definitions_keyword: {
                            "unused": {"$ref": f"#/{definitions_keyword}/missing"}
                        },
                    },
                    {},
                    source="unused unresolved definition",
                )
            with self.subTest(
                definitions=definitions_keyword,
                kind="unsupported",
            ), self.assertRaisesRegex(
                PROFILE.ControlPlaneError,
                "unsupported non-local schema reference",
            ):
                PROFILE.validate_json_schema_instance(
                    {
                        "type": "object",
                        definitions_keyword: {
                            "unused": {"$ref": "https://example.invalid/schema"}
                        },
                    },
                    {},
                    source="unused unsupported definition",
                )

    def test_default_branch_contract_matches_controller_atom_grammar_and_byte_bound(self) -> None:
        schema = json.loads((HERE / "fleet.schema.json").read_text(encoding="utf-8"))
        committed = json.loads((HERE / "fleet.json").read_text(encoding="utf-8"))
        cases = {
            "empty": "",
            "slash": "release/next",
            "non-ascii": "café",
            "over-100-bytes": "a" * 101,
        }
        for label, branch in cases.items():
            candidate = copy.deepcopy(committed)
            candidate["targets"][0]["default_branch"] = branch
            with self.subTest(runtime=label), self.assertRaises(
                PROFILE.ControlPlaneError
            ):
                PROFILE._validated_fleet_targets(candidate)
            with self.subTest(schema=label), self.assertRaises(
                PROFILE.ControlPlaneError
            ):
                PROFILE.validate_json_schema_instance(
                    schema,
                    candidate,
                    source=f"default branch {label}",
                )

        exact = copy.deepcopy(committed)
        exact["targets"][0]["default_branch"] = "a" * 100
        PROFILE._validated_fleet_targets(exact)
        PROFILE.validate_json_schema_instance(
            schema,
            exact,
            source="default branch exact bound",
        )

    def test_schema_and_runtime_reject_wrong_types_in_pattern_fields(self) -> None:
        assignment_schema = json.loads(
            (HERE / "coverage-assignments.schema.json").read_text(encoding="utf-8")
        )
        controller_schema = json.loads(
            (HERE / "controller.schema.json").read_text(encoding="utf-8")
        )
        assignments, fleet_value, _ = self._real_authorities()
        configured = json.loads((HERE / "controller.json").read_text(encoding="utf-8"))
        assignment_mutations = {
            "repo": lambda entry: entry.update(repo=7),
            "catalog_repository_id": lambda entry: entry.update(catalog_repository_id=7),
            "profile digest": lambda entry: entry["profile_ref"].update(digest=7),
        }
        for label, mutate in assignment_mutations.items():
            candidate = copy.deepcopy(assignments)
            mutate(candidate["assignments"][0])
            with self.subTest(authority="assignment", field=label), self.assertRaises(
                PROFILE.ControlPlaneError
            ):
                PROFILE.validate_json_schema_instance(
                    assignment_schema,
                    candidate,
                    source="candidate assignment",
                )
            with self.subTest(runtime="assignment", field=label), self.assertRaises(SystemExit):
                PROFILE.validate_coverage_assignments(
                    candidate,
                    [item["repo"] for item in fleet_value["targets"]],
                    "candidate assignment",
                )

        configured["ruleset_fingerprints"]["repository_overrides"] = {
            str(self.AWA_ID): {
                "runtime_app_visible": [7],
                "operator_full": ["sha256:" + "0" * 64],
            }
        }
        with self.assertRaises(PROFILE.ControlPlaneError):
            PROFILE.validate_json_schema_instance(
                controller_schema,
                configured,
                source="candidate controller",
            )
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "runtime_app_visible"):
            PROFILE.resolve_repository_projection(
                assignments,
                fleet_value,
                configured,
                repository_id=self.AWA_ID,
                repo=self.AWA_REPO,
                default_branch="main",
            )

    def test_required_check_manifest_is_closed_local_and_repository_namespaced(self) -> None:
        assignments, fleet_value, _ = self._real_authorities()
        awa = next(item for item in assignments["assignments"] if item["repo"] == self.AWA_REPO)
        awa["required_checks"] = {
            "schema": "pr-automation-required-checks/v1",
            "job_id": self.JOB_ID,
        }
        PROFILE.validate_coverage_assignments(
            assignments,
            [item["repo"] for item in fleet_value["targets"]],
            "candidate",
        )
        mutations = {
            "unknown schema": lambda value: value["required_checks"].update(
                schema="pr-automation-required-checks/v2"
            ),
            "extra field": lambda value: value["required_checks"].update(context="free-form"),
            "non-local": lambda value: value.update(coverage_mode="shadow"),
            "wrong namespace": lambda value: value["required_checks"].update(
                job_id="repo.dev.engine-tests"
            ),
            "uppercase job": lambda value: value["required_checks"].update(
                job_id="repo.awa.Engine-tests"
            ),
            "multibyte job": lambda value: value["required_checks"].update(
                job_id="repo.awa.café"
            ),
            "over-bound rendered name": lambda value: value["required_checks"].update(
                job_id="repo.awa."
                + "a"
                * (
                    101
                    - len("pr-automation / job:".encode("ascii"))
                    - len("repo.awa.".encode("ascii"))
                )
            ),
        }
        for label, mutate in mutations.items():
            candidate = copy.deepcopy(assignments)
            entry = next(
                item for item in candidate["assignments"] if item["repo"] == self.AWA_REPO
            )
            mutate(entry)
            with self.subTest(label=label), self.assertRaises(SystemExit):
                PROFILE.validate_coverage_assignments(
                    candidate,
                    [item["repo"] for item in fleet_value["targets"]],
                    "candidate",
                )

    def test_required_checks_null_is_canonical_absence(self) -> None:
        assignments, fleet_value, configured = self._real_authorities()
        awa = next(item for item in assignments["assignments"] if item["repo"] == self.AWA_REPO)
        awa["required_checks"] = None
        configured["ruleset_fingerprints"]["repository_overrides"] = {}
        PROFILE.validate_coverage_assignments(
            assignments,
            [item["repo"] for item in fleet_value["targets"]],
            "candidate",
        )
        projection = PROFILE.resolve_repository_projection(
            assignments,
            fleet_value,
            configured,
            repository_id=self.AWA_ID,
            repo=self.AWA_REPO,
            default_branch="main",
        )
        self.assertNotIn("required_checks", projection.assignment)
        self.assertEqual(
            projection.required_status_checks,
            [{"context": "pr-automation / verify", "integration_id": 4274739}],
        )

    def test_required_check_grammar_matches_controller_without_suffix_tightening(self) -> None:
        assignments, fleet_value, _ = self._real_authorities()
        awa = next(item for item in assignments["assignments"] if item["repo"] == self.AWA_REPO)
        for job_id in ("repo.awa.", "repo.awa..", "repo.awa.-_"):
            candidate = copy.deepcopy(assignments)
            entry = next(
                item for item in candidate["assignments"] if item["repo"] == self.AWA_REPO
            )
            entry["required_checks"] = {
                "schema": "pr-automation-required-checks/v1",
                "job_id": job_id,
            }
            with self.subTest(job_id=job_id):
                PROFILE.validate_coverage_assignments(
                    candidate,
                    [item["repo"] for item in fleet_value["targets"]],
                    "candidate",
                )

    def test_required_check_manifest_accepts_exact_100_byte_rendered_name(self) -> None:
        assignments, fleet_value, _ = self._real_authorities()
        awa = next(item for item in assignments["assignments"] if item["repo"] == self.AWA_REPO)
        prefix = "pr-automation / job:"
        namespace = "repo.awa."
        awa["required_checks"] = {
            "schema": "pr-automation-required-checks/v1",
            "job_id": namespace
            + "a" * (100 - len(prefix.encode("ascii")) - len(namespace.encode("ascii"))),
        }

        PROFILE.validate_coverage_assignments(
            assignments,
            [item["repo"] for item in fleet_value["targets"]],
            "candidate",
        )
        self.assertEqual(
            len((prefix + awa["required_checks"]["job_id"]).encode("ascii")),
            100,
        )

    def test_manifest_requires_matching_repository_fingerprint_override(self) -> None:
        assignments, fleet_value, configured = self._candidate_authorities()
        configured["ruleset_fingerprints"]["repository_overrides"] = {}
        with self.assertRaisesRegex(PROFILE.ControlPlaneError, "override|fingerprint"):
            PROFILE.resolve_repository_projection(
                assignments,
                fleet_value,
                configured,
                repository_id=self.AWA_ID,
                repo=self.AWA_REPO,
                default_branch="main",
            )

    def test_box_projection_uses_each_live_repository_default_branch(self) -> None:
        assignments = assignment()
        fleet_value = fleet()
        next(
            item for item in fleet_value["targets"] if item["repository_id"] == self.AWA_ID
        )["default_branch"] = "release"
        configured = controller()
        release_projection = PROFILE.resolve_repository_projection(
            assignments,
            fleet_value,
            configured,
            repository_id=self.AWA_ID,
            repo=self.AWA_REPO,
            default_branch="release",
            enforce_fingerprint_pins=False,
        )
        configured["ruleset_fingerprints"]["repository_overrides"] = {
            str(self.AWA_ID): {
                "runtime_app_visible": release_projection.runtime_app_visible_fingerprints,
                "operator_full": release_projection.operator_full_fingerprints,
            }
        }
        live = json.loads(live_bytes())
        next(
            item for item in live["repositories"] if item["id"] == self.AWA_ID
        ).update(
            {
                "default_branch": "release",
                "expected_ruleset_fingerprints": (
                    release_projection.runtime_app_visible_fingerprints
                ),
            }
        )

        projected = PROFILE.project_live_config(
            (json.dumps(live, indent=2) + "\n").encode(),
            assignments,
            fleet_value,
            configured,
        )

        self.assertFalse(projected.changed)

    def test_box_projection_moves_manifest_and_runtime_pin_atomically_both_directions(self) -> None:
        base_assignments, fleet_value, base_controller = self._aggregate_only_authorities()
        candidate_assignments, _, candidate_controller = self._candidate_authorities()
        base_live = self._complete_live_config(
            base_assignments,
            fleet_value,
            base_controller,
        )

        forward = PROFILE.build_activation_package(
            base_live,
            candidate_assignments,
            fleet_value,
            candidate_controller,
            repo=self.AWA_REPO,
        )
        forward_config = json.loads(forward.candidate)
        forward_awa = next(
            item for item in forward_config["repositories"] if item["id"] == self.AWA_ID
        )
        candidate_projection = PROFILE.resolve_repository_projection(
            candidate_assignments,
            fleet_value,
            candidate_controller,
            repository_id=self.AWA_ID,
            repo=self.AWA_REPO,
            default_branch="main",
        )
        self.assertEqual(
            forward_awa["coverage_assignment"]["required_checks"]["job_id"],
            self.JOB_ID,
        )
        self.assertEqual(
            forward_awa["expected_ruleset_fingerprints"],
            candidate_projection.runtime_app_visible_fingerprints,
        )

        reverse = PROFILE.build_activation_package(
            forward.candidate,
            base_assignments,
            fleet_value,
            base_controller,
            repo=self.AWA_REPO,
        )
        reverse_config = json.loads(reverse.candidate)
        reverse_awa = next(
            item for item in reverse_config["repositories"] if item["id"] == self.AWA_ID
        )
        base_projection = PROFILE.resolve_repository_projection(
            base_assignments,
            fleet_value,
            base_controller,
            repository_id=self.AWA_ID,
            repo=self.AWA_REPO,
            default_branch="main",
        )
        self.assertNotIn("required_checks", reverse_awa["coverage_assignment"])
        self.assertEqual(
            reverse_awa["expected_ruleset_fingerprints"],
            base_projection.runtime_app_visible_fingerprints,
        )
        self.assertEqual(json.loads(reverse.candidate), json.loads(base_live))

    def test_only_awa_candidate_changes_ruleset_and_fingerprint_pair(self) -> None:
        base_assignments, fleet_value, base_controller = self._aggregate_only_authorities()
        candidate_assignments, _, candidate_controller = self._candidate_authorities()
        changed: list[str] = []
        for target in fleet_value["targets"]:
            kwargs = {
                "repository_id": target["repository_id"],
                "repo": target["repo"],
                "default_branch": "main",
            }
            base = PROFILE.resolve_repository_projection(
                base_assignments, fleet_value, base_controller, **kwargs
            )
            candidate = PROFILE.resolve_repository_projection(
                candidate_assignments, fleet_value, candidate_controller, **kwargs
            )
            if target["repository_id"] == self.AWA_ID:
                changed.append(target["repo"])
                self.assertEqual(
                    candidate.required_status_checks,
                    [
                        {"context": "pr-automation / verify", "integration_id": 4274739},
                        {"context": self.NODE_CONTEXT, "integration_id": 4274739},
                    ],
                )
                self.assertNotEqual(PROFILE.encoded(candidate.ruleset), PROFILE.encoded(base.ruleset))
                self.assertNotEqual(
                    candidate.runtime_app_visible_fingerprints,
                    base.runtime_app_visible_fingerprints,
                )
                self.assertNotEqual(
                    candidate.operator_full_fingerprints,
                    base.operator_full_fingerprints,
                )
            else:
                self.assertEqual(
                    PROFILE.encoded(candidate.ruleset),
                    PROFILE.encoded(base.ruleset),
                    target["repo"],
                )
                self.assertEqual(
                    candidate.runtime_app_visible_fingerprints,
                    base.runtime_app_visible_fingerprints,
                    target["repo"],
                )
                self.assertEqual(
                    candidate.operator_full_fingerprints,
                    base.operator_full_fingerprints,
                    target["repo"],
                )
        self.assertEqual(changed, [self.AWA_REPO])
        self.assertEqual(len(fleet_value["targets"]) - len(changed), 14)

    def test_context_or_integration_change_moves_both_fingerprint_layers(self) -> None:
        assignments, fleet_value, configured = self._candidate_authorities()
        projection = PROFILE.resolve_repository_projection(
            assignments,
            fleet_value,
            configured,
            repository_id=self.AWA_ID,
            repo=self.AWA_REPO,
            default_branch="main",
        )
        baseline = PROFILE.ruleset_fingerprint_pair(projection.ruleset)
        for field, replacement in (
            ("context", self.NODE_CONTEXT + "-renamed"),
            ("integration_id", 1),
        ):
            changed = copy.deepcopy(projection.ruleset)
            checks = next(
                rule["parameters"]["required_status_checks"]
                for rule in changed["rules"]
                if rule["type"] == "required_status_checks"
            )
            checks[1][field] = replacement
            pair = PROFILE.ruleset_fingerprint_pair(changed)
            self.assertNotEqual(
                pair["runtime_app_visible"], baseline["runtime_app_visible"], field
            )
            self.assertNotEqual(pair["operator_full"], baseline["operator_full"], field)

    def test_unordered_array_reordering_changes_neither_fingerprint(self) -> None:
        assignments, fleet_value, configured = self._candidate_authorities()
        projection = PROFILE.resolve_repository_projection(
            assignments,
            fleet_value,
            configured,
            repository_id=self.AWA_ID,
            repo=self.AWA_REPO,
            default_branch="main",
        )
        baseline = copy.deepcopy(projection.ruleset)
        baseline["bypass_actors"].append(
            {"actor_id": 99, "actor_type": "Integration", "bypass_mode": "pull_request"}
        )
        baseline["conditions"]["ref_name"]["include"].append("refs/heads/release")
        baseline["conditions"]["ref_name"]["exclude"].append("refs/heads/archive")
        next(rule for rule in baseline["rules"] if rule["type"] == "pull_request")[
            "parameters"
        ]["allowed_merge_methods"].append("merge")
        reordered = copy.deepcopy(baseline)
        reordered["rules"].reverse()
        reordered["bypass_actors"].reverse()
        reordered["conditions"]["ref_name"]["include"].reverse()
        reordered["conditions"]["ref_name"]["exclude"].reverse()
        next(
            rule for rule in reordered["rules"] if rule["type"] == "required_status_checks"
        )["parameters"]["required_status_checks"].reverse()
        next(rule for rule in reordered["rules"] if rule["type"] == "pull_request")[
            "parameters"
        ]["allowed_merge_methods"].reverse()
        self.assertEqual(
            PROFILE.ruleset_fingerprint_pair(reordered),
            PROFILE.ruleset_fingerprint_pair(baseline),
        )

    def test_app_visible_fingerprint_is_fresh_bypass_redacted_derivation(self) -> None:
        assignments, fleet_value, configured = self._candidate_authorities()
        projection = PROFILE.resolve_repository_projection(
            assignments,
            fleet_value,
            configured,
            repository_id=self.AWA_ID,
            repo=self.AWA_REPO,
            default_branch="main",
        )
        changed_bypass = copy.deepcopy(projection.ruleset)
        changed_bypass["bypass_actors"][0]["bypass_mode"] = "always"
        original = PROFILE.ruleset_fingerprint_pair(projection.ruleset)
        changed = PROFILE.ruleset_fingerprint_pair(changed_bypass)
        self.assertEqual(changed["runtime_app_visible"], original["runtime_app_visible"])
        self.assertNotEqual(changed["operator_full"], original["operator_full"])
        self.assertEqual(
            original["runtime_app_visible"],
            [PROFILE.fingerprint(PROFILE.normalize_app_visible_ruleset(projection.ruleset))],
        )

    def test_forward_and_reverse_render_preserve_ruleset_identity_and_non_required_rules(self) -> None:
        # This is an AWA-only transition fixture; keep the base free of all committed
        # required_check bindings, including intent-router's later binding.
        base_assignments, fleet_value, base_controller = self._aggregate_only_authorities()
        candidate_assignments, _, candidate_controller = self._candidate_authorities()
        kwargs = {
            "repository_id": self.AWA_ID,
            "repo": self.AWA_REPO,
            "default_branch": "main",
        }
        base = PROFILE.resolve_repository_projection(
            base_assignments, fleet_value, base_controller, **kwargs
        )
        candidate = PROFILE.resolve_repository_projection(
            candidate_assignments, fleet_value, candidate_controller, **kwargs
        )
        live = copy.deepcopy(base.ruleset)
        live["id"] = 18819090
        live["source_type"] = "Repository"
        live["source"] = self.AWA_REPO
        forward = PROFILE.render_ruleset_transition(
            live,
            candidate.ruleset,
            expected_ruleset_id=18819090,
            expected_repo=self.AWA_REPO,
        )
        reverse = PROFILE.render_ruleset_transition(
            forward,
            base.ruleset,
            expected_ruleset_id=18819090,
            expected_repo=self.AWA_REPO,
        )
        self.assertEqual(forward["id"], 18819090)
        self.assertEqual(reverse["id"], 18819090)
        self.assertEqual(reverse, live)
        for key in ("name", "target", "enforcement", "bypass_actors", "conditions"):
            self.assertEqual(forward[key], live[key], key)
        for rule_type in ("pull_request", "required_linear_history", "deletion", "non_fast_forward"):
            self.assertEqual(
                next(rule for rule in forward["rules"] if rule["type"] == rule_type),
                next(rule for rule in live["rules"] if rule["type"] == rule_type),
                rule_type,
            )

    def test_doctor_fails_closed_on_assignment_policy_or_live_ruleset_disagreement(self) -> None:
        assignments, fleet_value, configured = self._candidate_authorities()
        raw = self._complete_live_config(assignments, fleet_value, configured)
        controls: dict[str, dict] = {}
        for target in fleet_value["targets"]:
            projection = PROFILE.resolve_repository_projection(
                assignments,
                fleet_value,
                configured,
                repository_id=target["repository_id"],
                repo=target["repo"],
                default_branch="main",
            )
            controls[target["repo"]] = {
                "metadata": {
                    "repository_id": target["repository_id"],
                    "full_name": target["repo"],
                    "default_branch": target["default_branch"],
                },
                "policy": repository_policy(
                    target["repo"],
                    policy_digest=PROFILE.RELEASE_DIGEST,
                    policy_generation=3,
                    fingerprints=projection.runtime_app_visible_fingerprints,
                    repository_id=target["repository_id"],
                ),
                "ruleset": {
                    **copy.deepcopy(projection.ruleset),
                    "id": target["merge_safety_ruleset_id"],
                    "source_type": "Repository",
                    "source": target["repo"],
                },
            }
        for drift in ("assignment", "policy", "ruleset"):
            drift_assignments = copy.deepcopy(assignments)
            drift_controls = copy.deepcopy(controls)
            if drift == "assignment":
                next(
                    item
                    for item in drift_assignments["assignments"]
                    if item["repo"] == self.AWA_REPO
                ).pop("required_checks")
            elif drift == "policy":
                drift_controls[self.AWA_REPO]["policy"]["ruleset_fingerprints"] = [
                    "sha256:" + "0" * 64
                ]
            else:
                drift_controls[self.AWA_REPO]["ruleset"] = merge_safety_ruleset(
                    ruleset_id=18819090
                )
            with self.subTest(drift=drift), self.assertRaisesRegex(
                PROFILE.ControlPlaneError, "assignment|coverage|policy|ruleset|fingerprint"
            ):
                PROFILE.doctor_coverage(
                    raw,
                    drift_assignments,
                    fleet_value,
                    configured,
                    remote_controls=drift_controls,
                )

    def _remote_controls_for(
        self,
        assignments: dict,
        fleet_value: dict,
        configured: dict,
    ) -> dict[str, dict]:
        controls: dict[str, dict] = {}
        for target in fleet_value["targets"]:
            projection = PROFILE.resolve_repository_projection(
                assignments,
                fleet_value,
                configured,
                repository_id=target["repository_id"],
                repo=target["repo"],
                default_branch=target["default_branch"],
            )
            controls[target["repo"]] = {
                "metadata": {
                    "repository_id": target["repository_id"],
                    "full_name": target["repo"],
                    "default_branch": target["default_branch"],
                },
                "policy": repository_policy(
                    target["repo"],
                    policy_digest=PROFILE.RELEASE_DIGEST,
                    policy_generation=3,
                    fingerprints=projection.runtime_app_visible_fingerprints,
                    repository_id=target["repository_id"],
                ),
                "ruleset": {
                    **copy.deepcopy(projection.ruleset),
                    "id": target["merge_safety_ruleset_id"],
                    "source_type": "Repository",
                    "source": target["repo"],
                },
            }
        return controls

    def test_requiredness_noop_transcribe_cannot_complete_before_final_parity(self) -> None:
        assignments, fleet_value, configured = self._candidate_authorities()
        # Remote controls intentionally model the pre-requiredness aggregate-only state.
        base_assignments, _, base_controller = self._aggregate_only_authorities()
        staged_live = self._complete_live_config(assignments, fleet_value, configured)
        stale_controls = self._remote_controls_for(base_assignments, fleet_value, base_controller)

        args = PROFILE.argparse.Namespace(
            dev_root="/tmp/dev",
            controller_root="/tmp/controller",
            host="hetzner-pr-controller",
            repo=self.AWA_REPO,
            phase="transcribe",
            coverage_mode="local",
            lock_compiler="/tmp/lock-compiler",
            release_manifest="/tmp/manifest.json",
            operation_id="requiredness-finalize",
            owner_go="requiredness-finalize",
        )
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            root = Path(temporary)
            with (
                mock.patch.object(PROFILE, "OPERATION_ROOT", root),
                mock.patch.object(PROFILE, "_assert_owner_go"),
                mock.patch.object(PROFILE, "_assert_origin"),
                mock.patch.object(PROFILE, "_run_bind_guard", return_value={"ok": True}),
                mock.patch.object(
                    PROFILE,
                    "_authorities",
                    return_value=(assignments, fleet_value, configured),
                ),
                mock.patch.object(
                    PROFILE,
                    "fetch_remote_repository_controls",
                    return_value=stale_controls,
                ),
                mock.patch.object(
                    PROFILE,
                    "_assert_control_plane_merged",
                ),
                mock.patch.object(PROFILE, "verify_test_sharding_activation"),
                mock.patch.object(
                    PROFILE,
                    "validate_qualified_release",
                    return_value={"lifecycle_state": "qualified"},
                ),
                mock.patch.object(
                    PROFILE,
                    "validate_remote_repository_artifacts",
                    return_value={"status": "validated"},
                ),
                mock.patch.object(PROFILE, "read_box_live_config", return_value=staged_live),
            ):
                with self.assertRaisesRegex(
                    PROFILE.ControlPlaneError,
                    "policy|ruleset|fingerprint|final parity",
                ):
                    PROFILE.command_activate(args)
            receipt = json.loads((root / "requiredness-finalize.json").read_text(encoding="utf-8"))
            self.assertNotEqual(receipt["status"], "completed")

    def test_requiredness_transcribe_refuses_changed_candidate_before_remote_write(self) -> None:
        assignments, fleet_value, configured = self._candidate_authorities()
        base_assignments, _, base_controller = self._aggregate_only_authorities()
        base_live = self._complete_live_config(base_assignments, fleet_value, base_controller)
        controls = self._remote_controls_for(assignments, fleet_value, configured)

        args = PROFILE.argparse.Namespace(
            dev_root="/tmp/dev",
            controller_root="/tmp/controller",
            host="hetzner-pr-controller",
            repo=self.AWA_REPO,
            phase="transcribe",
            coverage_mode="local",
            lock_compiler="/tmp/lock-compiler",
            release_manifest="/tmp/manifest.json",
            operation_id="requiredness-transcribe",
            owner_go="requiredness-transcribe",
        )
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            root = Path(temporary)
            with (
                mock.patch.object(PROFILE, "OPERATION_ROOT", root),
                mock.patch.object(PROFILE, "_assert_owner_go"),
                mock.patch.object(PROFILE, "_assert_origin"),
                mock.patch.object(PROFILE, "_run_bind_guard", return_value={"ok": True}),
                mock.patch.object(
                    PROFILE,
                    "_authorities",
                    return_value=(assignments, fleet_value, configured),
                ),
                mock.patch.object(
                    PROFILE,
                    "fetch_remote_repository_controls",
                    return_value=controls,
                ),
                mock.patch.object(PROFILE, "_assert_control_plane_merged"),
                mock.patch.object(PROFILE, "verify_test_sharding_activation"),
                mock.patch.object(
                    PROFILE,
                    "validate_qualified_release",
                    return_value={"lifecycle_state": "qualified"},
                ),
                mock.patch.object(
                    PROFILE,
                    "validate_remote_repository_artifacts",
                    return_value={"status": "validated"},
                ),
                mock.patch.object(PROFILE, "read_box_live_config", return_value=base_live),
                mock.patch.object(
                    PROFILE,
                    "transcribe_box_config",
                    side_effect=AssertionError("ordinary transcribe must not run"),
                ),
            ):
                with self.assertRaisesRegex(
                    PROFILE.ControlPlaneError,
                    "stage-requiredness/finalize-requiredness",
                ):
                    PROFILE.command_activate(args)
            receipt = json.loads((root / "requiredness-transcribe.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "claimed")

    def test_requiredness_staging_remains_paused_drained_and_records_staged_receipt(self) -> None:
        assignments, fleet_value, configured = self._candidate_authorities()
        base_assignments, _, base_controller = self._aggregate_only_authorities()
        before = self._complete_live_config(base_assignments, fleet_value, base_controller)
        package = PROFILE.build_activation_package(
            before,
            assignments,
            fleet_value,
            configured,
            repo=self.AWA_REPO,
        )
        captured: dict[str, object] = {}

        def fake_ssh(host: str, script: str, *, input_bytes: bytes, timeout: int):
            captured["host"] = host
            captured["script"] = script
            captured["input_bytes"] = input_bytes
            return subprocess.CompletedProcess(
                args=["ssh"],
                returncode=0,
                stdout=(
                    b'{"paused":true,"drain":true,"recovery_candidates":0,'
                    b'"operator_floor":{"driver":{"healthy":true,"state":"running"},'
                    b'"queue_depth":{"in_flight_attempts":0,"owed_runs":0,"state":"known"},'
                    b'"stage_duration":{"state":"idle"}}}\n'
                ),
                stderr=b"",
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            PROFILE.claim_operation(root, "requiredness-stage", "activate:requiredness-stage")
            with mock.patch.object(PROFILE, "_ssh", side_effect=fake_ssh):
                result = PROFILE.stage_requiredness_box_config(
                    "hetzner-pr-controller",
                    package.candidate,
                    operation_id="requiredness-stage",
                    operation_root=root,
                    recovery_operation_id="requiredness-restore",
                )

            script = str(captured["script"])
            self.assertIn("pause --drain", script)
            self.assertNotIn(" resume", script)
            self.assertEqual(captured["input_bytes"], package.candidate)
            self.assertTrue(result["status"]["paused"])
            self.assertTrue(result["status"]["drain"])
            receipt = json.loads((root / "requiredness-stage.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "staged")
            self.assertEqual(receipt["candidate_digest"], PROFILE._sha256_bytes(package.candidate))
            self.assertEqual(receipt["recovery_operation_id"], "requiredness-restore")
            self.assertIn("rollback_config", receipt)
            self.assertTrue(receipt["stage_written_status"]["paused"])
            self.assertTrue(receipt["staged_status"]["paused"])

    def test_requiredness_post_write_validation_failure_keeps_staged_receipt(self) -> None:
        assignments, fleet_value, configured = self._candidate_authorities()
        base_assignments, _, base_controller = self._aggregate_only_authorities()
        before = self._complete_live_config(base_assignments, fleet_value, base_controller)
        package = PROFILE.build_activation_package(
            before,
            assignments,
            fleet_value,
            configured,
            repo=self.AWA_REPO,
        )

        calls: list[str] = []

        def fake_ssh(host: str, script: str, **kwargs):
            calls.append(script)
            if len(calls) == 2:
                return subprocess.CompletedProcess(
                    args=["ssh"],
                    returncode=0,
                    stdout=(
                        b'{"paused":true,"drain":true,"recovery_candidates":0,'
                        b'"operator_floor":{"queue_depth":{"in_flight_attempts":0,"owed_runs":0}}}\n'
                    ),
                    stderr=b"",
                )
            return subprocess.CompletedProcess(
                args=["ssh"],
                returncode=0,
                stdout=b'{"paused":false,"drain":false,"operator_floor":{"queue_depth":{"in_flight_attempts":0,"owed_runs":0}}}\n',
                stderr=b"",
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            PROFILE.claim_operation(root, "requiredness-stage", "activate:requiredness-stage")
            with mock.patch.object(PROFILE, "_ssh", side_effect=fake_ssh):
                with self.assertRaisesRegex(PROFILE.ControlPlaneError, "paused and drained"):
                    PROFILE.stage_requiredness_box_config(
                        "hetzner-pr-controller",
                        package.candidate,
                        operation_id="requiredness-stage",
                        operation_root=root,
                        recovery_operation_id="requiredness-restore",
                    )
            receipt = json.loads((root / "requiredness-stage.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "restored")
            self.assertEqual(receipt["candidate_digest"], PROFILE._sha256_bytes(package.candidate))
            self.assertFalse(receipt["stage_written_status"]["paused"])
            self.assertTrue(receipt["restore_status"]["paused"])
            self.assertIn("install --source \"$backup\"", calls[1])
            self.assertIn("pause --drain", calls[1])

    def test_requiredness_restore_failure_records_restore_failed_receipt(self) -> None:
        assignments, fleet_value, configured = self._candidate_authorities()
        base_assignments, _, base_controller = self._aggregate_only_authorities()
        before = self._complete_live_config(base_assignments, fleet_value, base_controller)
        package = PROFILE.build_activation_package(
            before,
            assignments,
            fleet_value,
            configured,
            repo=self.AWA_REPO,
        )

        calls = 0

        def fake_ssh(host: str, script: str, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise PROFILE.ControlPlaneError("restore failed")
            return subprocess.CompletedProcess(
                args=["ssh"],
                returncode=0,
                stdout=b'{"paused":false,"drain":false,"operator_floor":{"queue_depth":{"in_flight_attempts":0,"owed_runs":0}}}\n',
                stderr=b"",
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            PROFILE.claim_operation(root, "requiredness-stage", "activate:requiredness-stage")
            with mock.patch.object(PROFILE, "_ssh", side_effect=fake_ssh):
                with self.assertRaisesRegex(PROFILE.ControlPlaneError, "restore failed"):
                    PROFILE.stage_requiredness_box_config(
                        "hetzner-pr-controller",
                        package.candidate,
                        operation_id="requiredness-stage",
                        operation_root=root,
                        recovery_operation_id="requiredness-restore",
                    )
            receipt = json.loads((root / "requiredness-stage.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "restore_failed")
            self.assertIn("paused and drained", receipt["restore_reason"])
            self.assertIn("restore failed", receipt["restore_error"])

    def test_requiredness_completion_requires_resume_and_healthy_status_first(self) -> None:
        healthy = {
            "paused": False,
            "drain": False,
            "recovery_candidates": 0,
            "operator_floor": {
                "driver": {"healthy": True, "state": "running"},
                "queue_depth": {
                    "in_flight_attempts": 0,
                    "owed_runs": 0,
                    "state": "known",
                },
                "stage_duration": {"state": "idle"},
            },
        }
        unhealthy = {**healthy, "paused": True, "drain": True}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            PROFILE.claim_operation(root, "requiredness-finalize", "activate:requiredness-stage")
            PROFILE.mark_operation_staged(
                root,
                "requiredness-finalize",
                candidate_digest="sha256:" + "1" * 64,
                rollback_config="/backup/prior.json",
                recovery_operation_id="requiredness-restore",
                status_snapshot={"paused": True, "drain": True},
            )
            with self.assertRaisesRegex(PROFILE.ControlPlaneError, "healthy|unpaused|undrained"):
                PROFILE.complete_requiredness_operation(root, "requiredness-finalize", unhealthy)
            self.assertEqual(
                json.loads((root / "requiredness-finalize.json").read_text(encoding="utf-8"))[
                    "status"
                ],
                "staged",
            )
            PROFILE.complete_requiredness_operation(root, "requiredness-finalize", healthy)
            self.assertEqual(
                json.loads((root / "requiredness-finalize.json").read_text(encoding="utf-8"))[
                    "status"
                ],
                "completed",
            )

    def test_requiredness_resume_failure_repauses_before_raising(self) -> None:
        calls: list[str] = []

        def fake_ssh(host: str, script: str, **kwargs):
            calls.append(script)
            if len(calls) == 1:
                return subprocess.CompletedProcess(
                    args=["ssh"],
                    returncode=0,
                    stdout=(
                        b'{"paused":false,"drain":false,"recovery_candidates":1,'
                        b'"operator_floor":{"driver":{"healthy":false,"state":"running"},'
                        b'"queue_depth":{"in_flight_attempts":0,"owed_runs":0}}}\n'
                    ),
                    stderr=b"",
                )
            return subprocess.CompletedProcess(
                args=["ssh"],
                returncode=0,
                stdout=(
                    b'{"paused":true,"drain":true,"recovery_candidates":0,'
                    b'"operator_floor":{"queue_depth":{"in_flight_attempts":0,"owed_runs":0}}}\n'
                ),
                stderr=b"",
            )

        with mock.patch.object(PROFILE, "_ssh", side_effect=fake_ssh):
            with self.assertRaisesRegex(PROFILE.ControlPlaneError, "healthy|idle|debt-free"):
                PROFILE.resume_box_controller("hetzner-pr-controller")
        self.assertIn(" resume", calls[0])
        self.assertNotIn("systemctl start", calls[0])
        self.assertIn("systemctl stop", calls[1])
        self.assertIn("pause --drain", calls[1])

    def test_requiredness_resume_starts_timer_only_after_healthy_status(self) -> None:
        calls: list[str] = []

        def fake_ssh(host: str, script: str, **kwargs):
            calls.append(script)
            return subprocess.CompletedProcess(
                args=["ssh"],
                returncode=0,
                stdout=(
                    b'{"paused":false,"drain":false,"recovery_candidates":0,'
                    b'"operator_floor":{"driver":{"healthy":true,"state":"running"},'
                    b'"queue_depth":{"in_flight_attempts":0,"owed_runs":0}}}\n'
                ),
                stderr=b"",
            )

        with mock.patch.object(PROFILE, "_ssh", side_effect=fake_ssh):
            status = PROFILE.resume_box_controller("hetzner-pr-controller")
        self.assertFalse(status["paused"])
        self.assertIn(" resume", calls[0])
        self.assertNotIn("systemctl start", calls[0])
        self.assertIn("systemctl start", calls[1])

    def test_requiredness_timer_start_failure_repauses_before_raising(self) -> None:
        calls: list[str] = []

        def fake_ssh(host: str, script: str, **kwargs):
            calls.append(script)
            if len(calls) == 1:
                return subprocess.CompletedProcess(
                    args=["ssh"],
                    returncode=0,
                    stdout=(
                        b'{"paused":false,"drain":false,"recovery_candidates":0,'
                        b'"operator_floor":{"driver":{"healthy":true,"state":"running"},'
                        b'"queue_depth":{"in_flight_attempts":0,"owed_runs":0}}}\n'
                    ),
                    stderr=b"",
                )
            if len(calls) == 2:
                raise PROFILE.ControlPlaneError("timer start failed")
            return subprocess.CompletedProcess(
                args=["ssh"],
                returncode=0,
                stdout=(
                    b'{"paused":true,"drain":true,"recovery_candidates":0,'
                    b'"operator_floor":{"queue_depth":{"in_flight_attempts":0,"owed_runs":0}}}\n'
                ),
                stderr=b"",
            )

        with mock.patch.object(PROFILE, "_ssh", side_effect=fake_ssh):
            with self.assertRaisesRegex(PROFILE.ControlPlaneError, "timer start failed"):
                PROFILE.resume_box_controller("hetzner-pr-controller")
        self.assertIn(" resume", calls[0])
        self.assertIn("systemctl start", calls[1])
        self.assertIn("systemctl stop", calls[2])
        self.assertIn("pause --drain", calls[2])

    def test_requiredness_finalize_requires_paused_drained_status_before_resume(self) -> None:
        assignments, fleet_value, configured = self._candidate_authorities()
        staged_live = self._complete_live_config(assignments, fleet_value, configured)
        controls = self._remote_controls_for(assignments, fleet_value, configured)
        args = PROFILE.argparse.Namespace(
            dev_root="/tmp/dev",
            controller_root="/tmp/controller",
            host="hetzner-pr-controller",
            repo=self.AWA_REPO,
            phase="finalize-requiredness",
            coverage_mode="local",
            lock_compiler="/tmp/lock-compiler",
            release_manifest="/tmp/manifest.json",
            operation_id="requiredness-finalize",
            recovery_operation_id="requiredness-restore",
            owner_go="requiredness-finalize",
        )
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            root = Path(temporary)
            with (
                mock.patch.object(PROFILE, "OPERATION_ROOT", root),
                mock.patch.object(PROFILE, "_assert_owner_go"),
                mock.patch.object(PROFILE, "_assert_origin"),
                mock.patch.object(PROFILE, "_run_bind_guard", return_value={"ok": True}),
                mock.patch.object(
                    PROFILE,
                    "_authorities",
                    return_value=(assignments, fleet_value, configured),
                ),
                mock.patch.object(
                    PROFILE,
                    "fetch_remote_repository_controls",
                    return_value=controls,
                ),
                mock.patch.object(PROFILE, "_assert_control_plane_merged"),
                mock.patch.object(PROFILE, "verify_test_sharding_activation"),
                mock.patch.object(
                    PROFILE,
                    "validate_qualified_release",
                    return_value={"lifecycle_state": "qualified"},
                ),
                mock.patch.object(
                    PROFILE,
                    "validate_remote_repository_artifacts",
                    return_value={"status": "validated"},
                ),
                mock.patch.object(PROFILE, "read_box_live_config", return_value=staged_live),
                mock.patch.object(
                    PROFILE,
                    "read_box_status",
                    return_value={
                        "paused": False,
                        "drain": False,
                        "operator_floor": {
                            "queue_depth": {"in_flight_attempts": 0, "owed_runs": 0}
                        },
                    },
                ),
                mock.patch.object(
                    PROFILE,
                    "resume_box_controller",
                    side_effect=AssertionError("must not resume before staged-status preflight"),
                ),
            ):
                with self.assertRaisesRegex(PROFILE.ControlPlaneError, "paused and drained"):
                    PROFILE.command_activate(args)
            receipt = json.loads((root / "requiredness-finalize.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "claimed")

    def test_requiredness_finalize_parity_failure_leaves_receipt_claimed(self) -> None:
        assignments, fleet_value, configured = self._candidate_authorities()
        staged_live = self._complete_live_config(assignments, fleet_value, configured)
        controls = self._remote_controls_for(assignments, fleet_value, configured)
        args = PROFILE.argparse.Namespace(
            dev_root="/tmp/dev",
            controller_root="/tmp/controller",
            host="hetzner-pr-controller",
            repo=self.AWA_REPO,
            phase="finalize-requiredness",
            coverage_mode="local",
            lock_compiler="/tmp/lock-compiler",
            release_manifest="/tmp/manifest.json",
            operation_id="requiredness-finalize",
            recovery_operation_id="requiredness-restore",
            owner_go="requiredness-finalize",
        )
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            root = Path(temporary)
            with (
                mock.patch.object(PROFILE, "OPERATION_ROOT", root),
                mock.patch.object(PROFILE, "_assert_owner_go"),
                mock.patch.object(PROFILE, "_assert_origin"),
                mock.patch.object(PROFILE, "_run_bind_guard", return_value={"ok": True}),
                mock.patch.object(
                    PROFILE,
                    "_authorities",
                    return_value=(assignments, fleet_value, configured),
                ),
                mock.patch.object(
                    PROFILE,
                    "fetch_remote_repository_controls",
                    return_value=controls,
                ),
                mock.patch.object(PROFILE, "_assert_control_plane_merged"),
                mock.patch.object(
                    PROFILE,
                    "validate_qualified_release",
                    return_value={"lifecycle_state": "qualified"},
                ),
                mock.patch.object(PROFILE, "verify_test_sharding_activation"),
                mock.patch.object(
                    PROFILE,
                    "validate_remote_repository_artifacts",
                    return_value={"status": "validated"},
                ),
                mock.patch.object(PROFILE, "read_box_live_config", return_value=staged_live),
                mock.patch.object(
                    PROFILE,
                    "read_box_status",
                    return_value={
                        "paused": True,
                        "drain": True,
                        "recovery_candidates": 0,
                        "operator_floor": {
                            "queue_depth": {"in_flight_attempts": 0, "owed_runs": 0}
                        },
                    },
                ),
                mock.patch.object(
                    PROFILE,
                    "doctor_coverage",
                    side_effect=PROFILE.ControlPlaneError("final parity failed"),
                ),
                mock.patch.object(
                    PROFILE,
                    "resume_box_controller",
                    side_effect=AssertionError("must not resume before final parity"),
                ),
            ):
                with self.assertRaisesRegex(PROFILE.ControlPlaneError, "final parity failed"):
                    PROFILE.command_activate(args)
            receipt = json.loads((root / "requiredness-finalize.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "claimed")

    def test_verify_fleet_remote_fails_closed_on_assignment_policy_or_live_ruleset_disagreement(
        self,
    ) -> None:
        assignments, _, configured = self._candidate_authorities()
        configured["release"]["digest"] = PROFILE.RELEASE_DIGEST
        assignment_value = {
            "schema": assignments["schema"],
            "assignments": [
                copy.deepcopy(
                    next(item for item in assignments["assignments"] if item["repo"] == self.AWA_REPO)
                )
            ],
        }
        fleet_value = {
            "schema": "pr-automation-fleet/v3",
            "targets": [
                {
                    "repo": self.AWA_REPO,
                    "repository_id": self.AWA_ID,
                    "default_branch": "main",
                    "merge_safety_ruleset_id": 18819090,
                }
            ],
        }
        projection = PROFILE.resolve_repository_projection(
            assignment_value,
            fleet_value,
            configured,
            repository_id=self.AWA_ID,
            repo=self.AWA_REPO,
            default_branch="main",
        )
        current_policy = repository_policy(
            self.AWA_REPO,
            policy_digest=PROFILE.RELEASE_DIGEST,
            policy_generation=3,
            fingerprints=projection.runtime_app_visible_fingerprints,
        )
        current_ruleset = {
            **copy.deepcopy(projection.ruleset),
            "id": 18819090,
            "source_type": "Repository",
            "source": self.AWA_REPO,
        }

        for drift in ("assignment", "policy", "ruleset"):
            drift_assignments = copy.deepcopy(assignment_value)
            policy = copy.deepcopy(current_policy)
            ruleset = copy.deepcopy(current_ruleset)
            if drift == "assignment":
                drift_assignments["assignments"][0].pop("required_checks")
            elif drift == "policy":
                policy["ruleset_fingerprints"] = ["sha256:" + "0" * 64]
            else:
                ruleset = merge_safety_ruleset(ruleset_id=18819090)

            def fake_load_json(
                path: Path,
                *,
                drift_assignments: dict = drift_assignments,
            ) -> dict:
                if path.name == "controller.json":
                    return configured
                if path.name == "coverage-assignments.json":
                    return drift_assignments
                return fleet_value

            def route(path: str, *, policy: dict = policy, ruleset: dict = ruleset):
                if path == f"repos/{self.AWA_REPO}":
                    return {
                        "id": self.AWA_ID,
                        "full_name": self.AWA_REPO,
                        "default_branch": "main",
                    }
                if PROFILE.POLICY in path:
                    return _gh_contents(policy)
                if PROFILE.LOCK in path:
                    raise AssertionError(
                        "lock currency must use exact Rust validator/recompile evidence"
                    )
                if "/rulesets/" in path:
                    return ruleset
                if is_ruleset_list_path(path, self.AWA_REPO):
                    return [
                        {
                            "id": 18819090,
                            "name": PROFILE.MERGE_SAFETY_NAME,
                            "target": "branch",
                            "enforcement": "active",
                        }
                    ]
                raise AssertionError(f"unexpected API path: {path}")

            with self.subTest(drift=drift), mock.patch.object(
                PROFILE, "load_json", side_effect=fake_load_json
            ), mock.patch.object(
                PROFILE, "_gh_json", side_effect=route
            ), mock.patch.object(
                PROFILE, "_assert_compiler"
            ), self.assertRaisesRegex(SystemExit, "policy|ruleset|fingerprint"):
                PROFILE.verify_fleet_remote(Path("/fixture/lock-compiler"))


class FleetActionsPausedTest(unittest.TestCase):
    """A4 (gen3-m4-actions-retirement-steady-state-v3.md §5): check_fleet_actions_paused fetches
    scripts/check-fleet-actions-paused.sh live from the controller repo and executes it. These
    tests mock only the live-fetch boundary (_fetch_github_file) with a small fixture script that
    honors the real script's PR_AUTOMATION_FLEET_REPOS contract -- they prove the fetch/execute/
    report wiring, not the shipped script's own PASS/FAIL logic (that is independently covered by
    the controller repo's own test-check-fleet-actions-paused.sh). `bash <tempfile>` is invoked
    directly (never the temp file itself as an executable), so this needs no noexec-sandbox guard."""

    FIXTURE_SCRIPT = (
        b"#!/usr/bin/env bash\n"
        b"set -euo pipefail\n"
        b'if [[ "${PR_AUTOMATION_FLEET_REPOS:-}" == *fail-me* ]]; then\n'
        b'  printf "FAIL: fixture drift for %s\\n" "$PR_AUTOMATION_FLEET_REPOS" >&2\n'
        b"  exit 1\n"
        b"fi\n"
        b'printf "PASS: fixture fleet %s\\n" "$PR_AUTOMATION_FLEET_REPOS"\n'
    )
    FAILURE_SCRIPT = b"#!/usr/bin/env bash\nprintf 'FAIL: fixture drift\\n' >&2\nexit 1\n"

    def test_reports_ok_and_fetches_from_the_verified_controller_default_branch(self) -> None:
        with mock.patch.object(
            PROFILE, "_fetch_github_file", return_value=self.FIXTURE_SCRIPT
        ) as fetch:
            result = PROFILE.check_fleet_actions_paused(
                ["KleinPerkins/awa", "KleinPerkins/dev"],
                controller_default_branch="release",
            )
        fetch.assert_called_once_with(
            PROFILE.CONTROLLER_REPO,
            PROFILE.ACTIONS_PAUSED_SCRIPT,
            "release",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["source"],
            f"{PROFILE.CONTROLLER_REPO}@release:{PROFILE.ACTIONS_PAUSED_SCRIPT}",
        )
        self.assertIn("PASS: fixture fleet KleinPerkins/awa KleinPerkins/dev", result["stdout"])
        self.assertEqual(result["stderr"], "")

    def test_reports_not_ok_on_nonzero_exit(self) -> None:
        with mock.patch.object(
            PROFILE, "_fetch_github_file", return_value=self.FIXTURE_SCRIPT
        ):
            result = PROFILE.check_fleet_actions_paused(
                ["KleinPerkins/fail-me"],
                controller_default_branch="main",
            )
        self.assertFalse(result["ok"])
        self.assertIn("FAIL: fixture drift", result["stderr"])

    def test_never_leaks_an_offline_fixture_env_var_into_the_live_run(self) -> None:
        with mock.patch.dict(
            os.environ, {"PR_AUTOMATION_FLEET_FIXTURE": "/should/not/be/used"}
        ):
            with mock.patch.object(
                PROFILE, "_fetch_github_file", return_value=self.FIXTURE_SCRIPT
            ):
                result = PROFILE.check_fleet_actions_paused(
                    ["KleinPerkins/awa"],
                    controller_default_branch="main",
                )
        self.assertTrue(result["ok"])
        self.assertIn("PASS: fixture fleet KleinPerkins/awa", result["stdout"])

    def test_verify_fleet_remote_fails_closed_on_actions_paused_drift(self) -> None:
        """Even when policy-digest parity is fully green, a drifted Actions-pause state must
        still hard-fail verify-fleet-remote (A4 wired into the same live gate as digest parity)."""
        green_controller = controller()
        green_controller["release"]["digest"] = PROFILE.RELEASE_DIGEST
        # Policy parity and the manual-only lock cohort are green so the failure can only come from
        # Actions-pause drift.
        router = gh_router(policy_digest=PROFILE.RELEASE_DIGEST)

        def fake_load_json(path: Path) -> dict:
            if path.name == "controller.json":
                return green_controller
            if path.name == "coverage-assignments.json":
                return assignment("manual_only")
            return remote_fleet()

        with mock.patch.object(
            PROFILE, "load_json", side_effect=fake_load_json
        ), mock.patch.object(
            PROFILE, "_gh_json", side_effect=router
        ), mock.patch.object(
            PROFILE, "_assert_compiler"
        ), mock.patch.object(
            PROFILE, "_fetch_github_file", return_value=self.FAILURE_SCRIPT
        ) as fetch:
            with self.assertRaisesRegex(SystemExit, "Actions-pause drift"):
                PROFILE.verify_fleet_remote(Path("/fixture/lock-compiler"))
        fetch.assert_called_once_with(
            PROFILE.CONTROLLER_REPO,
            PROFILE.ACTIONS_PAUSED_SCRIPT,
            "main",
        )


class FleetLockCurrencyTest(unittest.TestCase):
    """The live gate requires v2/epoch-1 plus exact Rust recompile evidence for covered inputs."""

    def _run(
        self,
        *,
        case: str = "current_v2",
        current_recipe: bytes | None = None,
        mode: str = "local",
        missing_lock: bool = False,
    ) -> tuple[str, mock.Mock, list[list[str]]]:
        green_controller = controller()
        green_controller["release"]["digest"] = PROFILE.RELEASE_DIGEST
        router = gh_router(policy_digest=PROFILE.RELEASE_DIGEST)
        lock = lock_currency_case(case)
        lock_bytes = json.dumps(lock).encode()
        historical_recipe = lock_currency_fixtures()["recipe_bytes"].encode()
        if current_recipe is None:
            current_recipe = historical_recipe

        def fake_load_json(path: Path) -> dict:
            if path.name == "controller.json":
                return green_controller
            if path.name == "coverage-assignments.json":
                return assignment(mode)
            return remote_fleet()

        def fetch_file(repo: str, path: str, ref: str = "main") -> bytes:
            if repo == PROFILE.CONTROLLER_REPO and path == PROFILE.ACTIONS_PAUSED_SCRIPT:
                return FleetActionsPausedTest.FIXTURE_SCRIPT
            if repo != "KleinPerkins/awa":
                raise AssertionError(f"unexpected remote file repo: {repo}")
            if path == PROFILE.LOCK and ref == "main":
                if missing_lock:
                    raise PROFILE.ControlPlaneError(f"{repo}: missing lock fixture")
                return lock_bytes
            if path == PROFILE.RECIPE and ref == "main":
                return current_recipe
            if path == PROFILE.RECIPE and ref == lock["payload"].get("recipe_base_sha"):
                return historical_recipe
            raise AssertionError(f"unexpected remote file: {repo} {path} {ref}")

        compiler_calls: list[list[str]] = []
        with tempfile.TemporaryDirectory() as temporary:
            compiler = Path(temporary) / "lock-compiler"
            compiler.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            compiler.chmod(0o755)
            green_controller["release"]["lock_compiler_digest"] = PROFILE._sha256_bytes(
                compiler.read_bytes()
            )
            current_payload = lock_currency_case()["payload"]

            def run_compiler(
                command: list[str], **_: object
            ) -> subprocess.CompletedProcess[bytes]:
                self.assertEqual(command[0], str(compiler))
                compiler_calls.append(command)
                observed = json.loads(
                    Path(command[command.index("--lock") + 1]).read_text(encoding="utf-8")
                )
                for field in ("catalog_digest", "recipe_digest", "assignment_digest"):
                    if observed["payload"].get(field) != current_payload[field]:
                        raise PROFILE.ControlPlaneError(
                            f"lock-compiler failed: validate failed: {field} mismatch"
                        )
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=b"valid lock_digest=fixture jobs=1\n",
                    stderr=b"",
                )

            buffer = io.StringIO()
            with mock.patch.object(
                PROFILE, "load_json", side_effect=fake_load_json
            ), mock.patch.object(
                PROFILE, "_gh_json", side_effect=router
            ), mock.patch.object(
                PROFILE, "_fetch_github_file", side_effect=fetch_file
            ) as file_fetch, mock.patch.object(
                PROFILE, "_run_checked", side_effect=run_compiler
            ), contextlib.redirect_stdout(buffer):
                PROFILE.verify_fleet_remote(compiler)
        return buffer.getvalue(), file_fetch, compiler_calls

    def test_legacy_epoch_and_stale_covered_fixtures_fail_closed(self) -> None:
        cases = [
            ("legacy_v1", "schema_version"),
            *[
                (case["name"], case["expected_failure"])
                for case in lock_currency_fixtures()["stale_cases"]
            ],
        ]
        for name, expected in cases:
            with self.subTest(name=name), self.assertRaisesRegex(
                SystemExit, "lock currency"
            ):
                self._run(case=name)

    def test_current_v2_epoch_one_lock_passes_through_remote_fetch_and_rust_evidence(self) -> None:
        output, file_fetch, compiler_calls = self._run()
        self.assertIn("OK: fleet lock currency — 1/1", output)
        self.assertIn("OK: fleet remote parity", output)
        self.assertRegex(output, r"lock=v2/epoch=1\s+KleinPerkins/awa")
        self.assertNotIn("controller_release", output)
        self.assertEqual(len(compiler_calls), 1)
        fetched = [call.args for call in file_fetch.mock_calls]
        self.assertIn(("KleinPerkins/awa", PROFILE.LOCK, "main"), fetched)
        self.assertIn(("KleinPerkins/awa", PROFILE.RECIPE, "main"), fetched)
        self.assertIn(
            (
                "KleinPerkins/awa",
                PROFILE.RECIPE,
                lock_currency_case()["payload"]["recipe_base_sha"],
            ),
            fetched,
        )

    def test_remote_currency_rejects_recipe_changed_on_current_default_branch(self) -> None:
        with self.assertRaisesRegex(SystemExit, "lock currency"):
            self._run(
                current_recipe=b'{"schema":"fixture-recipe/v2","changed":true}\n'
            )

    def test_manual_only_repo_is_not_lock_validated(self) -> None:
        output, file_fetch, compiler_calls = self._run(mode="manual_only")
        self.assertIn("OK: fleet lock currency — 0/0", output)
        self.assertIn("lock n/a", output)
        self.assertEqual(compiler_calls, [])
        self.assertNotIn(
            ("KleinPerkins/awa", PROFILE.LOCK),
            [call.args for call in file_fetch.mock_calls],
        )

    def test_missing_lock_or_validator_evidence_fails_closed(self) -> None:
        with self.assertRaisesRegex(SystemExit, "lock currency"):
            self._run(missing_lock=True)

    def test_verify_fleet_remote_cli_requires_a_qualified_lock_compiler(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            PROFILE.parser().parse_args(["verify-fleet-remote"])
        parsed = PROFILE.parser().parse_args(
            ["verify-fleet-remote", "--lock-compiler", "/retained/lock-compiler"]
        )
        self.assertEqual(parsed.lock_compiler, "/retained/lock-compiler")


class TestNewRepositoryShardingActivation(unittest.TestCase):
    def test_coverage_authority_must_match_merged_owner_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);directory=root/'_ops/baseline/profiles/pr-automation/v3'
            directory.mkdir(parents=True)
            names=['coverage-assignments.json','fleet.json','controller.json','test-sharding-coverage.json']
            for name in names:(directory/name).write_bytes(b'local')
            def fetched(repo,path,ref):
                return b'unmerged' if path.endswith('test-sharding-coverage.json') else b'local'
            with mock.patch.object(PROFILE,'_fetch_github_file',side_effect=fetched):
                PROFILE._assert_control_plane_merged(root,'main')
                with self.assertRaisesRegex(PROFILE.ControlPlaneError,'test-sharding-coverage.json'):
                    PROFILE._assert_control_plane_merged(root,'main',include_sharding=True)

    def test_new_required_target_checks_merged_coverage_before_qualification(self):
        module=mock.Mock();module.validate_remote.return_value={'required':True}
        spec=mock.Mock()
        with (mock.patch.object(PROFILE.importlib.util,'spec_from_file_location',return_value=spec),
              mock.patch.object(PROFILE.importlib.util,'module_from_spec',return_value=module),
              mock.patch.object(PROFILE,'_assert_control_plane_merged',side_effect=PROFILE.ControlPlaneError('unmerged')),
              mock.patch.object(PROFILE,'load_json',return_value={})):
            with self.assertRaisesRegex(PROFILE.ControlPlaneError,'unmerged'):
                PROFILE.verify_test_sharding_activation(Path('/fixture/dev'),'fixture-owner/product',123,'main',{}, {},authority_branch='main')
        module.controller_coverage.assert_not_called()

    def test_legacy_target_does_not_require_new_coverage_or_execute_commands(self):
        module=mock.Mock();module.validate_remote.return_value={'required':False}
        spec=mock.Mock()
        with (mock.patch.object(PROFILE.importlib.util,'spec_from_file_location',return_value=spec),
              mock.patch.object(PROFILE.importlib.util,'module_from_spec',return_value=module),
              mock.patch.object(PROFILE,'_assert_control_plane_merged') as merged,
              mock.patch.object(PROFILE,'load_json') as loaded):
            PROFILE.verify_test_sharding_activation(Path('/fixture/dev'),'fixture-owner/legacy',123,'main',{}, {},authority_branch='main')
        merged.assert_not_called();loaded.assert_not_called();module.controller_coverage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
