import copy
import json
import shutil
import sys
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from doc_warden.canonical import canonical_json, digest_ref
from doc_warden.receipts import (
    prepare_remote_identity_observation,
    runnerless_delivery_preview,
)
from doc_warden.scm import RepositoryIdentity
from doc_warden.transactions import apply_transaction, confirmation_for
from doc_warden.validators import read_repository_config
from fixture_factory import FixtureFactory, ROOT


ASSIGNMENTS = (
    ROOT
    / "_ops/baseline/profiles/pr-automation/v3/coverage-assignments.json"
)
QUALIFICATION = (
    ROOT
    / "_ops/baseline/profiles/pr-automation/v3/qualification-ledger.json"
)
CONTROLLER = ROOT / "_ops/baseline/profiles/pr-automation/v3/controller.json"
FLEET = ROOT / "_ops/baseline/profiles/pr-automation/v3/fleet.json"
RECIPE = ROOT / ".github/pr-recipe.json"
LOCK = ROOT / ".github/pr-automation.lock.json"
AUTHORITIES = {
    "coverage_assignments": ASSIGNMENTS,
    "qualification_ledger": QUALIFICATION,
    "controller": CONTROLLER,
    "fleet": FLEET,
    "recipe": RECIPE,
    "lock": LOCK,
}


def _authority_blob_at(root: Path, revision: str, authority: Path) -> bytes:
    relative = authority.relative_to(ROOT)
    return subprocess.check_output(
        ["git", "-C", str(root), "show", f"{revision}:{relative}"]
    )


class DeliveryContractTests(unittest.TestCase):
    def setUp(self):
        # Historic protocol coverage uses fresh, explicitly synthetic Git objects.
        from doc_warden.receipts import _QUALIFICATION_RELEASE
        temporary = tempfile.TemporaryDirectory(prefix="historical-delivery-fixture-")
        self.addCleanup(temporary.cleanup)
        source = ROOT
        self.source_root = source
        root = Path(temporary.name) / "repo"
        root.mkdir()
        for relative in ("_ops/doc-warden/POLICY.md", "_ops/doc-warden/triggers.v2.json", "_ops/doc-warden/schemas/v2", "_ops/doc-warden/runtime/gsd-core/gsd-core-pin.json", "_ops/doc-warden/runtime/gsd-core/runtime-interface.v1.json", "_ops/bin", "_ops/hooks", "_ops/baseline/template", "_ops/baseline/README.md"):
            src=source/relative;dest=root/relative;dest.parent.mkdir(parents=True,exist_ok=True)
            if src.is_dir():shutil.copytree(src,dest)
            else:shutil.copy2(src,dest)
        digest="sha256:"+"a"*64
        argv=["run-literal","bash","_ops/checks/doc-warden-verify.sh","--sandbox"]
        job="repo.dev.m3-verify"
        relative={key:path.relative_to(source) for key,path in AUTHORITIES.items()}
        values={
          "coverage_assignments":{"assignments":[{"repo":"KleinPerkins/dev","profile_ref":{"id":"synthetic.v1","digest":digest},"required_checks":{"job_id":job}}]},
          "qualification_ledger":{"candidates":[{"repo":"KleinPerkins/dev","status":"canned_only"}]},
          "controller":{"release":{**_QUALIFICATION_RELEASE,"activation_generation":1,"lock_compiler_digest":digest},"verifier":{"app_id":4274739,"integration_id":4274739,"slug":"synthetic-verifier"},"images":{"execution":"fixture.invalid/image@"+digest},"hard_exclusions":["KleinPerkins/chaos-scheduler"]},
          "fleet":{"targets":[{"repo":"KleinPerkins/dev","repository_id":1278387789}],"excluded":[{"repo":"KleinPerkins/chaos-scheduler","reason":"hard no-touch; independently governed automation"}]},
          "recipe":{"repository_id":"dev","custom_jobs":[{"id":job,"argv":argv}]},
        }
        def write(name,value):
            path=root/relative[name];path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,indent=2)+"\n")
        for name,value in values.items():write(name,value)
        subprocess.run(["git","init","-q","-b","main",str(root)],check=True)
        blob=subprocess.check_output(["git","-C",str(root),"hash-object",str(relative["recipe"])],text=True).strip()
        values["lock"]={"lock_digest":digest,"payload":{"repository_id":"dev","profile_id":"synthetic.v1","profile_digest":digest,"recipe_digest":digest,"recipe_blob_sha":blob,"image_digest":"fixture.invalid/image@"+digest,"activation_generation":1,"jobs":[{"source_ref":{"custom_id":job,"recipe_digest":digest,"blob_sha":blob},"provenance_kind":"protected_recipe","runtime":{"argv":argv,"image":"fixture.invalid/image@"+digest}}]}}
        write("lock",values["lock"])
        subprocess.run(["git","-C",str(root),"add","."],check=True)
        subprocess.run(["git","-C",str(root),"-c","user.name=Fixture","-c","user.email=fixture@example.invalid","commit","-qm","synthetic historical protocol"],check=True)
        names={"ROOT":root,"AUTHORITIES":{key:root/path for key,path in relative.items()}}
        names.update({name:root/globals()[name].relative_to(source) for name in ("ASSIGNMENTS","QUALIFICATION","CONTROLLER","FLEET","RECIPE","LOCK")})
        patcher=patch.dict(globals(),names);patcher.start();self.addCleanup(patcher.stop)

    def _qualification_authority(
        self,
        *,
        receipt_mutator=None,
        duplicate: bool = False,
        stale: bool = False,
    ):
        temporary = tempfile.TemporaryDirectory(
            prefix="doc-warden-qualification-receipt-"
        )
        self.addCleanup(temporary.cleanup)
        authority = Path(temporary.name) / "authority"
        subprocess.run(
            ["git", "clone", "-q", str(ROOT), str(authority)],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(authority), "config", "user.name", "Fixture"],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(authority),
                "config",
                "user.email",
                "fixture@example.invalid",
            ],
            check=True,
        )
        revision = subprocess.check_output(
            ["git", "-C", str(authority), "rev-parse", "HEAD"],
            text=True,
        ).strip()
        assignments = json.loads(
            (authority / ASSIGNMENTS.relative_to(ROOT)).read_text(
                encoding="utf-8"
            )
        )
        assignment = next(
            row
            for row in assignments["assignments"]
            if row["repo"] == "KleinPerkins/dev"
        )
        recipe = json.loads(
            (authority / RECIPE.relative_to(ROOT)).read_text(encoding="utf-8")
        )
        recipe_job = next(
            job
            for job in recipe["custom_jobs"]
            if job["id"] == assignment["required_checks"]["job_id"]
        )
        lock = json.loads(
            (authority / LOCK.relative_to(ROOT)).read_text(encoding="utf-8")
        )
        controller = json.loads(
            (authority / CONTROLLER.relative_to(ROOT)).read_text(
                encoding="utf-8"
            )
        )
        receipt = {
            "schema": "pr-automation-controller-qualification/v1",
            "qualification_id": "",
            "authority": "validated_protected_recipe",
            "repository": "KleinPerkins/dev",
            "revision": revision,
            "job_id": assignment["required_checks"]["job_id"],
            "argv": recipe_job["argv"][1:],
            "recipe_digest": lock["payload"]["recipe_digest"],
            "lock_digest": lock["lock_digest"],
            "profile_id": lock["payload"]["profile_id"],
            "profile_digest": lock["payload"]["profile_digest"],
            "image_digest": lock["payload"]["image_digest"],
            "controller_release_digest": controller["release"]["digest"],
            "check_name": "pr-automation / qualify",
            "check_run_id": 987654321,
            "conclusion": "success",
            "exit_code": 0,
            "supersedes_legacy_m3_candidate": True,
        }
        identity = {
            key: receipt[key]
            for key in (
                "repository",
                "revision",
                "job_id",
                "recipe_digest",
                "lock_digest",
                "profile_digest",
                "image_digest",
                "controller_release_digest",
            )
        }
        receipt["qualification_id"] = digest_ref(
            b"pr-automation-qualification/v1\0"
            + canonical_json(identity)[:-1]
        )
        if receipt_mutator is not None:
            receipt_mutator(receipt)
        ledger_path = authority / QUALIFICATION.relative_to(ROOT)
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["controller_qualifications"] = [
            receipt,
            *([copy.deepcopy(receipt)] if duplicate else []),
        ]
        ledger_path.write_text(
            json.dumps(ledger, indent=2) + "\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "-C", str(authority), "add", str(QUALIFICATION.relative_to(ROOT))],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(authority), "commit", "-qm", "receipt fixture"],
            check=True,
        )
        if stale:
            assignment_path = authority / ASSIGNMENTS.relative_to(ROOT)
            assignment_path.write_text(
                json.dumps(assignments, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(authority),
                    "add",
                    str(ASSIGNMENTS.relative_to(ROOT)),
                ],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(authority), "commit", "-qm", "stale authority fixture"],
                check=True,
            )
        summary = "\n".join(
            (
                "authority=validated_protected_recipe",
                f"repository={receipt['repository']}",
                f"revision={receipt['revision']}",
                f"job_id={receipt['job_id']}",
                f"recipe_digest={receipt['recipe_digest']}",
                f"lock_digest={receipt['lock_digest']}",
                (
                    "controller_release_digest="
                    f"{receipt['controller_release_digest']}"
                ),
                "conclusion=success",
            )
        )
        check = {
            "id": receipt["check_run_id"],
            "name": "pr-automation / qualify",
            "head_sha": receipt["revision"],
            "status": "completed",
            "conclusion": "success",
            "external_id": receipt["qualification_id"],
            "app": {
                "id": controller["verifier"]["app_id"],
                "slug": controller["verifier"]["slug"],
            },
            "output": {
                "title": "Protected recipe qualification passed",
                "summary": summary,
            },
        }
        return authority, receipt, check

    def _qualification_preview(self, authority, check):
        return runnerless_delivery_preview(
            authority,
            repository="KleinPerkins/dev",
            github_repository_id=1278387789,
            qualification_check_observer=lambda repository, check_run_id: (
                check
                if (
                    repository == "KleinPerkins/dev"
                    and check_run_id == check["id"]
                )
                else (_ for _ in ()).throw(AssertionError("unexpected Check lookup"))
            ),
        )

    def test_remote_identity_observation_preserves_stable_ids_and_replays(self):
        fixture = FixtureFactory.create()
        try:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(fixture.repo),
                    "remote",
                    "add",
                    "origin",
                    "git@github.com:KleinPerkins/remote-identity-fixture.git",
                ],
                check=True,
            )
            config_before = read_repository_config(fixture.repo)
            artifact = fixture.repo / ".planning/artifacts/stable-id.txt"
            artifact.parent.mkdir(parents=True)
            artifact.write_text(
                f"PROJECT-{config_before['repository_key']}-{uuid.uuid4()}\n"
            )
            subprocess.run(
                ["git", "-C", str(fixture.repo), "add", "."], check=True
            )
            subprocess.run(
                ["git", "-C", str(fixture.repo), "commit", "-qm", "stable artifact"],
                check=True,
            )
            artifact_before = artifact.read_bytes()
            operation_id = "f568954f-a667-4bdf-a56f-1fcdfe2a70ad"
            preview = prepare_remote_identity_observation(
                fixture.repo,
                repository="KleinPerkins/remote-identity-fixture",
                github_repository_id=123456789,
                authority_root=ROOT,
                operation_id=operation_id,
            )
            with patch(
                "doc_warden.transactions.observe_repository_identity",
                return_value=RepositoryIdentity(
                    "KleinPerkins/remote-identity-fixture",
                    123456789,
                ),
            ) as observe_identity:
                receipt = apply_transaction(preview, confirmation_for(preview))
                observe_identity.assert_called_once_with(fixture.repo.resolve())
            replay = prepare_remote_identity_observation(
                fixture.repo,
                repository="KleinPerkins/remote-identity-fixture",
                github_repository_id=123456789,
                authority_root=ROOT,
                operation_id=operation_id,
            )

            self.assertEqual(replay.action_digest, preview.action_digest)
            with patch(
                "doc_warden.transactions.observe_repository_identity",
                return_value=RepositoryIdentity(
                    "KleinPerkins/remote-identity-fixture",
                    123456789,
                ),
            ):
                self.assertEqual(
                    apply_transaction(replay, confirmation_for(replay)),
                    receipt,
                )
            config_after = read_repository_config(fixture.repo)
            self.assertEqual(
                config_after["repository_key"], config_before["repository_key"]
            )
            self.assertEqual(config_after["github_repository_id"], 123456789)
            self.assertEqual(artifact.read_bytes(), artifact_before)
            self.assertEqual(receipt["github_repository_id"], 123456789)
            self.assertEqual(
                receipt["bindings"]["repository_identity"],
                {
                    "github_repository": "KleinPerkins/remote-identity-fixture",
                    "github_repository_id": 123456789,
                },
            )
        finally:
            fixture.cleanup()

    def test_remote_identity_mismatch_is_refused_without_rewriting_key(self):
        fixture = FixtureFactory.create()
        try:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(fixture.repo),
                    "remote",
                    "add",
                    "origin",
                    "git@github.com:KleinPerkins/remote-identity-fixture.git",
                ],
                check=True,
            )
            before = read_repository_config(fixture.repo)
            first = prepare_remote_identity_observation(
                fixture.repo,
                repository="KleinPerkins/remote-identity-fixture",
                github_repository_id=123456789,
                authority_root=ROOT,
                operation_id="28ecbc5d-e11f-4f72-bb4c-6225fdf501b4",
            )
            with patch(
                "doc_warden.transactions.observe_repository_identity",
                return_value=RepositoryIdentity(
                    "KleinPerkins/remote-identity-fixture",
                    123456789,
                ),
            ):
                apply_transaction(first, confirmation_for(first))
            with self.assertRaisesRegex(
                ValueError, "github_repository_id_mismatch"
            ):
                prepare_remote_identity_observation(
                    fixture.repo,
                    repository="KleinPerkins/remote-identity-fixture",
                    github_repository_id=987654321,
                    authority_root=ROOT,
                    operation_id="5ea7b1fc-d7d2-4f0d-8870-bb5e3be3d273",
                )
            self.assertEqual(
                read_repository_config(fixture.repo)["repository_key"],
                before["repository_key"],
            )
        finally:
            fixture.cleanup()

    def test_runnerless_preview_binds_live_authorities_and_stays_honest(self):
        before = subprocess.check_output(
            ["git", "-C", str(ROOT), "status", "--porcelain"], text=True
        )
        preview = runnerless_delivery_preview(
            ROOT,
            repository="KleinPerkins/doc-warden-v2-qualification-canary",
            github_repository_id=None,
        )

        self.assertEqual(preview["schema"], "doc-warden/delivery-preview/v1")
        self.assertEqual(preview["qualification_state"], "waiting_external")
        self.assertFalse(preview["ac_049_closed"])
        source_revision = preview["source_revision"]
        self.assertEqual(
            source_revision,
            subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                text=True,
            ).strip(),
        )
        committed = {
            name: _authority_blob_at(ROOT, source_revision, path)
            for name, path in AUTHORITIES.items()
        }
        matches_committed = {
            name: (
                path.is_file()
                and not path.is_symlink()
                and path.read_bytes() == committed[name]
            )
            for name, path in AUTHORITIES.items()
        }
        expected_drift = sorted(
            name for name, matches in matches_committed.items() if not matches
        )
        self.assertEqual(
            preview["authority_observation"]["worktree_drift"],
            expected_drift,
        )
        self.assertEqual(
            preview["warnings"],
            (
                [
                    {
                        "authorities": expected_drift,
                        "code": "runnerless_authority_worktree_drift",
                        "effect": "runnerless_staging_disallowed",
                    }
                ]
                if expected_drift
                else []
            ),
        )
        self.assertEqual(preview["source_lane"]["repository"], "KleinPerkins/dev")
        self.assertEqual(
            preview["source_lane"]["qualification_disposition"], "canned_only"
        )
        self.assertFalse(preview["source_lane"]["qualified"])
        self.assertEqual(
            preview["source_lane"]["controller_qualification"]["reason"],
            "controller_qualification_receipt_missing",
        )
        self.assertEqual(
            preview["source_lane"]["required_job_id"], "repo.dev.m3-verify"
        )
        self.assertFalse(preview["target_staging"]["assigned"])
        self.assertFalse(preview["target_staging"]["identity_bound"])
        self.assertEqual(preview["target_staging"]["state"], "inert")
        self.assertFalse(preview["auto_merge_armed"])
        self.assertEqual(preview["actions_taken"], [])
        self.assertEqual(preview["workflow_files"], [])
        for name, content in committed.items():
            binding = preview["authority_bindings"][name]
            self.assertEqual(binding["source_revision"], source_revision)
            self.assertEqual(binding["digest"], digest_ref(content))
            self.assertEqual(
                binding["worktree_matches_committed"],
                matches_committed[name],
            )
        self.assertEqual(
            subprocess.check_output(
                ["git", "-C", str(ROOT), "status", "--porcelain"], text=True
            ),
            before,
        )

    def test_staged_authority_uses_committed_bytes_and_blocks_staging(self):
        with tempfile.TemporaryDirectory(
            prefix="doc-warden-authority-drift-"
        ) as directory:
            authority = Path(directory) / "authority"
            subprocess.run(
                ["git", "clone", "-q", str(ROOT), str(authority)],
                check=True,
            )
            relative = QUALIFICATION.relative_to(ROOT)
            qualification = authority / relative
            source_revision = subprocess.check_output(
                ["git", "-C", str(authority), "rev-parse", "HEAD"],
                text=True,
            ).strip()
            committed_digest = digest_ref(
                _authority_blob_at(authority, source_revision, QUALIFICATION)
            )
            dirty = json.loads(qualification.read_text(encoding="utf-8"))
            candidate = next(
                row
                for row in dirty["candidates"]
                if row["repo"] == "KleinPerkins/dev"
            )
            candidate["status"] = "qualified"
            qualification.write_text(
                json.dumps(dirty, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "-C", str(authority), "add", str(relative)],
                check=True,
            )

            preview = runnerless_delivery_preview(
                authority,
                repository="KleinPerkins/doc-warden-v2-qualification-canary",
                github_repository_id=None,
            )

            self.assertEqual(
                subprocess.check_output(
                    [
                        "git",
                        "-C",
                        str(authority),
                        "diff",
                        "--cached",
                        "--name-only",
                    ],
                    text=True,
                ).splitlines(),
                [str(relative)],
            )
            self.assertEqual(preview["source_revision"], source_revision)
            self.assertEqual(
                preview["source_lane"]["qualification_disposition"],
                "canned_only",
            )
            self.assertFalse(preview["target_staging"]["allowed"])
            self.assertEqual(
                preview["authority_observation"],
                {
                    "trusted_source": "committed_revision",
                    "worktree_drift": ["qualification_ledger"],
                },
            )
            self.assertEqual(
                preview["warnings"],
                [
                    {
                        "authorities": ["qualification_ledger"],
                        "code": "runnerless_authority_worktree_drift",
                        "effect": "runnerless_staging_disallowed",
                    }
                ],
            )
            binding = preview["authority_bindings"]["qualification_ledger"]
            self.assertFalse(binding["worktree_matches_committed"])
            self.assertEqual(
                binding["digest"],
                committed_digest,
            )

    def test_additive_controller_receipt_and_exact_verifier_check_qualify_source(self):
        authority, receipt, check = self._qualification_authority()
        preview = self._qualification_preview(authority, check)

        self.assertTrue(preview["source_lane"]["qualified"])
        self.assertTrue(preview["ac_049_closed"])
        self.assertEqual(preview["qualification_state"], "qualified")
        evidence = preview["source_lane"]["controller_qualification"]
        self.assertEqual(evidence["qualification_id"], receipt["qualification_id"])
        self.assertEqual(evidence["check_run_id"], check["id"])
        self.assertEqual(evidence["check_app_id"], 4274739)
        legacy = json.loads(
            (authority / QUALIFICATION.relative_to(ROOT)).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            next(
                row
                for row in legacy["candidates"]
                if row["repo"] == "KleinPerkins/dev"
            )["status"],
            "canned_only",
        )

    def test_worktree_drift_explains_block_after_valid_qualification(self):
        authority, _receipt, check = self._qualification_authority()
        recipe = authority / RECIPE.relative_to(ROOT)
        recipe.write_bytes(recipe.read_bytes() + b"\n")

        preview = self._qualification_preview(authority, check)

        qualification = preview["source_lane"]["controller_qualification"]
        self.assertTrue(qualification["qualified"])
        self.assertFalse(preview["source_lane"]["qualified"])
        self.assertEqual(
            preview["external_gate"]["reason"],
            "runnerless_authority_worktree_drift",
        )

    def test_duplicate_controller_receipt_is_rejected(self):
        authority, _receipt, check = self._qualification_authority(duplicate=True)
        preview = self._qualification_preview(authority, check)
        self.assertFalse(preview["source_lane"]["qualified"])
        self.assertEqual(
            preview["source_lane"]["controller_qualification"]["reason"],
            "controller_qualification_receipt_duplicate",
        )

    def test_stale_controller_receipt_is_rejected_after_authority_changes(self):
        authority, _receipt, check = self._qualification_authority(stale=True)
        preview = self._qualification_preview(authority, check)
        self.assertFalse(preview["source_lane"]["qualified"])
        self.assertEqual(
            preview["source_lane"]["controller_qualification"]["reason"],
            "controller_qualification_receipt_stale",
        )

    def test_malformed_controller_receipt_is_rejected(self):
        authority, _receipt, check = self._qualification_authority(
            receipt_mutator=lambda receipt: receipt.update({"unexpected": True})
        )
        preview = self._qualification_preview(authority, check)
        self.assertFalse(preview["source_lane"]["qualified"])
        self.assertEqual(
            preview["source_lane"]["controller_qualification"]["reason"],
            "controller_qualification_receipt_malformed",
        )

    def test_mismatched_controller_receipt_is_rejected(self):
        authority, _receipt, check = self._qualification_authority(
            receipt_mutator=lambda receipt: receipt.update(
                {"profile_digest": f"sha256:{'0' * 64}"}
            )
        )
        preview = self._qualification_preview(authority, check)
        self.assertFalse(preview["source_lane"]["qualified"])
        self.assertEqual(
            preview["source_lane"]["controller_qualification"]["reason"],
            "controller_qualification_receipt_mismatch",
        )

    def test_foreign_app_qualification_check_is_rejected(self):
        authority, _receipt, check = self._qualification_authority()
        check["app"]["id"] = 1
        preview = self._qualification_preview(authority, check)
        self.assertFalse(preview["source_lane"]["qualified"])
        self.assertEqual(
            preview["source_lane"]["controller_qualification"]["reason"],
            "qualification_check_foreign_app",
        )

    def test_unsuccessful_qualification_check_is_rejected(self):
        authority, _receipt, check = self._qualification_authority()
        check["conclusion"] = "failure"
        preview = self._qualification_preview(authority, check)
        self.assertFalse(preview["source_lane"]["qualified"])
        self.assertEqual(
            preview["source_lane"]["controller_qualification"]["reason"],
            "qualification_check_identity_mismatch",
        )

    def test_valid_looking_hand_authored_receipt_is_rejected(self):
        authority, _receipt, _check = self._qualification_authority(
            receipt_mutator=lambda receipt: receipt.update(
                {"qualification_id": f"sha256:{'0' * 64}"}
            )
        )

        def unexpected_lookup(_repository, _check_run_id):
            raise AssertionError("untrusted receipt must not trigger a Check lookup")

        preview = runnerless_delivery_preview(
            authority,
            repository="KleinPerkins/dev",
            github_repository_id=1278387789,
            qualification_check_observer=unexpected_lookup,
        )
        self.assertFalse(preview["source_lane"]["qualified"])
        self.assertEqual(
            preview["source_lane"]["controller_qualification"]["reason"],
            "controller_qualification_receipt_untrusted",
        )

    def test_chaos_scheduler_is_documentation_only_and_never_staged(self):
        preview = runnerless_delivery_preview(
            ROOT,
            repository="KleinPerkins/chaos-scheduler",
            github_repository_id=1202219494,
        )
        self.assertEqual(preview["qualification_state"], "documentation_only")
        self.assertFalse(preview["target_staging"]["allowed"])
        self.assertFalse(preview["target_staging"]["assigned"])
        self.assertEqual(
            preview["target"]["exclusion_reason"],
            "hard no-touch; independently governed automation",
        )
        self.assertEqual(preview["actions_taken"], [])

    def test_dry_run_has_exact_order_rollback_and_no_writes(self):
        name = "doc-warden-v2-qualification-canary"
        target = self.source_root / "personal" / name
        self.assertFalse(target.exists())
        result = subprocess.run(
            [str(self.source_root / "_ops/bin/dev-new-repo.sh"), name, "--dry-run"],
            check=True,
            capture_output=True,
            text=True,
        )
        ordered = [
            "1. validate request and preview",
            "2. create local main repository",
            "3. apply local noreply identity",
            "4. install identity/session/data guards",
            "5. apply workflow-free baseline",
            "6. mint stable repository key and scaffold v2",
            "7. verify and create first guarded commit",
            "8. create private GitHub remote",
            "9. observe remote ID and create second guarded commit",
            "10. keep delivery unenrolled; retired controller staging is refused",
        ]
        positions = [result.stdout.index(step) for step in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(
            "remote deletion requires an explicit external gate",
            result.stdout,
        )
        self.assertIn("no .github/workflows files", result.stdout)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
