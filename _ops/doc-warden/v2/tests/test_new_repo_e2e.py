import fcntl
import json
import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from doc_warden.canonical import digest_ref, parse_artifact
from fixture_factory import ROOT


SCRIPT = ROOT / "_ops/bin/dev-new-repo.sh"
RUNTIME = ROOT / "_ops/doc-warden/runtime/gsd-core"
FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
remote = Path(os.environ["DOC_WARDEN_FIXTURE_REMOTE"])
calls = Path(os.environ["DOC_WARDEN_FIXTURE_GH_CALLS"])
calls.parent.mkdir(parents=True, exist_ok=True)
with calls.open("a") as handle:
    handle.write(" ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    raise SystemExit(0)
if args[:2] == ["repo", "create"]:
    visibility = "public" if "--public" in args else "private"
    payload = {
        "id": int(os.environ["DOC_WARDEN_FIXTURE_REPOSITORY_ID"]),
        "full_name": args[2],
        "visibility": visibility,
        "description": args[args.index("--description") + 1]
            if "--description" in args else None,
        "homepage": args[args.index("--homepage") + 1],
    }
    descriptor = os.open(remote, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(payload, handle)
    raise SystemExit(0)
if args and args[0] == "api":
    if "--method" in args and args[args.index("--method") + 1] == "PATCH":
        payload = json.loads(remote.read_text())
        payload["homepage"] = ""
        remote.write_text(json.dumps(payload))
    elif not remote.is_file():
        print("gh: Not Found (HTTP 404)", file=sys.stderr)
        raise SystemExit(1)
    print(remote.read_text(), end="")
    raise SystemExit(0)
raise SystemExit(2)
"""


class NewRepositoryEndToEndTests(unittest.TestCase):
    def setUp(self):
        # Repeated calls model one writer resuming its own fixture operation.
        # A fresh explicit ID is a different owner and must not inherit this
        # process's ancestry after the INT-011 writer-isolation correction.
        self.session_id = f"doc-warden-m4-test-{uuid.uuid4()}"

    def run_scaffold(
        self,
        root: Path,
        name: str,
        *arguments: str,
        check: bool = True,
        extra_env=None,
    ) -> subprocess.CompletedProcess[str]:
        fake_gh = root / ".doc-warden-fixture-gh"
        fake_gh.write_text(FAKE_GH)
        fake_gh.chmod(0o700)
        return subprocess.run(
            [str(SCRIPT), name, "--fixture-root", str(root), *arguments],
            check=check,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "DEV_SESSION_ID": self.session_id,
                "DOC_WARDEN_FIXTURE_GH_SOURCE": str(fake_gh),
                **(extra_env or {}),
            },
        )

    @staticmethod
    def result(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
        return json.loads(result.stdout.splitlines()[-1])

    @staticmethod
    def git(target: Path, *arguments: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(target), *arguments], text=True
        ).strip()

    @classmethod
    def operation(cls, target: Path) -> dict[str, object]:
        return json.loads(
            (Path(cls.git(target, "rev-parse", "--absolute-git-dir"))
             / "doc-warden-new-repo.json").read_text()
        )

    @staticmethod
    def fake_remote(root: Path, name: str, repository_id: int, homepage: str) -> Path:
        path = root / ".doc-warden-fixture-remotes" / f"{name}.json"
        path.write_text(json.dumps({
            "id": repository_id,
            "full_name": f"KleinPerkins/{name}",
            "visibility": "private",
            "description": None,
            "homepage": homepage,
        }) + "\n")
        return path

    def test_clean_room_uses_real_shared_sequence_in_one_guarded_commit(
        self,
    ):
        with tempfile.TemporaryDirectory(
            prefix="doc-warden-m4-cleanroom-"
        ) as directory:
            root = Path(directory)
            name = "born-v2-cleanroom"
            result = self.run_scaffold(root, name)
            target = root / name
            payload = self.result(result)

            self.assertEqual(payload["schema"], "dev-new-repo-result/v2")
            self.assertEqual(payload["status"], "waiting_external")
            self.assertEqual(payload["commit_count"], 1)
            self.assertIsNone(payload["github_repository_id"])
            self.assertEqual(
                payload["inventory_observation"]["status"],
                "pending_repository_owned_admission",
            )
            self.assertEqual(
                payload["maintenance_enrollment"]["status"],
                "pending_repository_owned_admission",
            )
            self.assertTrue(payload["doctor"]["read_only"])
            self.assertEqual(payload["doctor"]["repository_writes"], [])
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(target), "rev-list", "--count", "HEAD"],
                    text=True,
                ).strip(),
                "1",
            )
            committed = set(
                subprocess.check_output(
                    [
                        "git",
                        "-C",
                        str(target),
                        "show",
                        "--format=",
                        "--name-only",
                        "HEAD",
                    ],
                    text=True,
                ).splitlines()
            )
            self.assertIn(".planning/doc-warden.json", committed)
            self.assertIn(".planning/PROJECT.md", committed)
            self.assertIn(".planning/ROADMAP.md", committed)
            self.assertIn(".planning/STATE.md", committed)
            self.assertIn("AGENTS.md", committed)
            self.assertIn("SECURITY.md", committed)
            self.assertIn(".github/CODEOWNERS", committed)

            config = json.loads((target / ".planning/doc-warden.json").read_text())
            self.assertTrue(config["enabled"])
            self.assertIsNone(config["github_repository_id"])
            self.assertEqual(
                config["gsd_pin_digest"],
                digest_ref((RUNTIME / "gsd-core-pin.json").read_bytes()),
            )
            self.assertEqual(
                config["gsd_interface_digest"],
                digest_ref((RUNTIME / "runtime-interface.v1.json").read_bytes()),
            )
            projects = sorted((target / ".planning/artifacts").glob("PROJECT-*.md"))
            self.assertEqual(len(projects), 1)
            metadata = parse_artifact(projects[0]).metadata
            self.assertEqual(metadata["repository_key"], config["repository_key"])
            self.assertIn(config["repository_key"], metadata["id"])

            git_dir = Path(
                subprocess.check_output(
                    ["git", "-C", str(target), "rev-parse", "--absolute-git-dir"],
                    text=True,
                ).strip()
            )
            for guard in (
                "identity-guard",
                "session-lock",
                "data-guard",
                "registration-guard",
            ):
                self.assertEqual(
                    (git_dir / "hooks" / guard).read_bytes(),
                    (ROOT / "_ops/hooks" / guard).read_bytes(),
                )
            self.assertIn(
                "managed-by: KleinPerkins/dev identity-guard",
                (git_dir / "hooks/pre-commit").read_text(),
            )
            self.assertFalse(
                (git_dir / "doc-warden-operation-state").exists()
            )
            self.assertEqual(list((target / ".github").glob("workflows/*.y*ml")), [])
            for heavyweight in ("PRD.md", "SPEC.md", "UI-SPEC.md"):
                self.assertFalse((target / ".planning" / heavyweight).exists())
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(target), "status", "--porcelain"],
                    text=True,
                ),
                "",
            )

    def test_personal_product_scaffold_resumes_the_exact_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            owner = root / "personal/src/KleinPerkins"
            owner.mkdir(parents=True)
            name = "sample.product"
            initial = self.run_scaffold(root, name, "--personal-codex",
                                        "--fixture-interrupt-after", "initial-committed", check=False)
            self.assertEqual(initial.returncode, 75, initial.stderr)
            checkout = owner / name
            first = self.git(checkout, "rev-parse", "HEAD")
            self.assertTrue((checkout / ".git/hooks/pre-commit").is_file())
            self.assertTrue((checkout / ".planning/doc-warden.json").is_file())
            self.assertTrue((checkout / ".github/test-sharding-required.json").is_file())
            self.assertFalse((root / name).exists())
            # A simultaneous retry by this same explicit writer cannot enter the operation.
            fd = os.open(checkout, os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                busy = self.run_scaffold(root, name, "--personal-codex", "--resume", check=False)
                self.assertNotEqual(busy.returncode, 0)
            finally:
                os.close(fd)
            out = self.result(self.run_scaffold(root, name, "--personal-codex", "--resume"))
            self.assertTrue(out["resumed"])
            self.assertIsNone(out["github_repository_id"])
            self.assertEqual(first, self.git(checkout, "rev-parse", "HEAD"))
            self.assertEqual(self.git(checkout, "status", "--porcelain"), "")
            occupied = self.run_scaffold(root, name, "--personal-codex", check=False)
            self.assertNotEqual(occupied.returncode, 0)
            self.git(checkout, "remote", "set-url", "origin", "https://github.com/Other/sample.product")
            foreign = self.run_scaffold(root, name, "--personal-codex", "--resume", check=False)
            self.assertNotEqual(foreign.returncode, 0)
            self.assertIn("origin or push URL changed", foreign.stderr)

    def test_personal_create_requires_the_selected_parent_as_cwd(self):
        helper = ROOT / "_ops/portability/personal_scaffold.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            owner = root / "personal/src/KleinPerkins"
            owner.mkdir(parents=True)
            args = ["python3", "-I", "-B", str(helper), "acquire", "sample", str(root), "0"]
            refused = subprocess.run(args, cwd=root, capture_output=True, text=True)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("selected owner directory changed", refused.stderr)
            self.assertEqual(list(owner.iterdir()), [])
            for protected in ("chaos-scheduler", "CHAOS-SCHEDULER", "server-guard",
                              "chaos-labs", "pr-automation-controller", "sterling.io"):
                with self.subTest(protected=protected):
                    denied = [*args[:5], protected, *args[6:]]
                    result = subprocess.run(denied, cwd=owner, text=True, capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Dev policy", result.stderr)
                    self.assertEqual(list(owner.iterdir()), [])
            selected = subprocess.check_output(args, cwd=owner, text=True).strip()
            info = (owner / "sample").stat()
            self.assertEqual(selected, f"{info.st_dev}:{info.st_ino}")

            # The checkout-location guard checks the acquired inode and inherited checkout descriptor.
            checkout = owner / "sample"
            check = ["bash", "-c", 'exec 9<.; exec python3 -I -B "$1" check "$2" "$3" ""',
                     "check", str(helper), str(checkout)]
            subprocess.run([*check, selected], cwd=checkout, check=True)
            mismatch = subprocess.run([*check, "wrong-inode"], cwd=checkout, capture_output=True, text=True)
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("selected checkout location changed", mismatch.stderr)
            self.assertEqual(list(checkout.iterdir()), [])

    def test_personal_remote_replay_preserves_unrelated_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            owner = root / "personal/src/KleinPerkins"
            owner.mkdir(parents=True)
            args = ("--personal-codex", "--fixture-repository-id", "81357", "--no-push")
            name = "remote-replay"
            initial = self.run_scaffold(root, name, *args, "--fixture-interrupt-after",
                                        "remote-created", check=False)
            self.assertEqual(initial.returncode, 75, initial.stderr)
            target = owner / name
            first = self.git(target, "rev-parse", "HEAD")
            note = target / "local-notes.txt"
            note.write_text("unrelated work")
            attempt = self.run_scaffold(root, name, *args, "--resume", check=False)
            self.assertNotEqual(attempt.returncode, 0)
            self.assertIn("unrelated work", attempt.stderr)
            self.assertEqual(note.read_text(), "unrelated work")
            self.assertEqual(self.git(target, "rev-parse", "HEAD"), first)
            note.rename(root / "saved-notes.txt")
            replay = self.result(self.run_scaffold(root, name, *args, "--resume"))
            self.assertEqual(replay["commit_count"], 2)
            self.assertEqual(replay["github_repository_id"], 81357)
            calls = (root / ".doc-warden-fixture-remotes/remote-replay.calls").read_text().splitlines()
            self.assertEqual(sum(line.startswith("repo create ") for line in calls), 1)

    def test_personal_product_refuses_excluded_names_and_linked_owners(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "personal/src").mkdir(parents=True)
            other = root / "other"
            other.mkdir()
            (root / "personal/src/KleinPerkins").symlink_to(other, target_is_directory=True)
            for name in ("chaos-scheduler", "server-guard", "chaos-labs",
                         "pr-automation-controller", "..", "repo-platform", "sample.product"):
                with self.subTest(name=name):
                    result = self.run_scaffold(root, name, "--personal-codex", check=False)
                    self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(other.iterdir()), [])

    def test_personal_capability_preview_uses_the_born_v2_owner_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            capabilities = root / "capabilities"
            capabilities.mkdir()
            (root / "personal/src/KleinPerkins").mkdir(parents=True)
            arguments = ("--personal-codex", "--capability", "--kind", "tool",
                         "--shape", "release-descriptor", "--public")
            result = self.run_scaffold(root, "repo-platform", *arguments, "--dry-run")
            self.assertIn("dev-new-repo born-v2 preview", result.stdout)
            self.assertIn(str(capabilities / "repo-platform"), result.stdout)
            self.assertIn("governed capability enrollment is required", result.stdout)
            self.assertIn("sharding required", result.stdout)
            self.assertEqual(list(capabilities.iterdir()), [])
            for options in (arguments, (*arguments, "--resume"),
                            ("--personal-codex", "--dry-run")):
                with self.subTest(options=options):
                    refused = self.run_scaffold(root, "repo-platform", *options, check=False)
                    self.assertNotEqual(refused.returncode, 0)
            self.assertFalse((root / ".doc-warden-fixture-remotes").exists())

    def test_personal_capability_preview_refuses_foreign_and_excluded_destinations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            owner = root / "capabilities"
            owner.mkdir()
            existing = owner / "sample-tool"
            existing.mkdir()
            (existing / "unshared.txt").write_text("preserve this\n")
            arguments = ("--personal-codex", "--capability", "--dry-run")
            occupied = self.run_scaffold(root, "sample-tool", *arguments, check=False)
            self.assertIn("target already occupied", occupied.stderr)
            excluded = self.run_scaffold(root, "chaos-scheduler", *arguments, check=False)
            self.assertIn("retired/excluded repository", excluded.stderr)
            other = root / "other"
            owner.rename(other)
            owner.symlink_to(other, target_is_directory=True)
            linked = self.run_scaffold(root, "repo-platform", *arguments, check=False)
            self.assertNotEqual(linked.returncode, 0)
            self.assertEqual((other / "sample-tool/unshared.txt").read_text(), "preserve this\n")
            self.assertEqual([path.name for path in other.iterdir()], ["sample-tool"])
            self.assertFalse((root / ".doc-warden-fixture-remotes").exists())

    def test_personal_capability_foundation_prepares_exact_local_tree_without_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "capabilities").mkdir()
            provider_fence = root / "provider-fence"
            provider_fence.mkdir()
            github = provider_fence / "gh"
            github.write_text('#!/bin/sh\nprintf invoked > "$FOUNDATION_GH_OBSERVATION"\nexit 1\n')
            github.chmod(0o700)
            observation = root / "gh-called"
            env = {"PATH": f"{provider_fence}:{os.environ['PATH']}",
                   "FOUNDATION_GH_OBSERVATION": str(observation)}
            name = "repo-platform"
            arguments = ("--personal-codex", "--capability", "--kind", "tool",
                         "--shape", "release-descriptor", "--public", "--no-push",
                         "--fixture-repository-id", "931885", "--desc", "Disposable foundation")
            resume = (*arguments, "--prepare-foundation", "--resume")

            preview = self.run_scaffold(root, name, *arguments, "--prepare-foundation", "--dry-run",
                                        extra_env=env)
            self.assertIn("local checkout and operation journal only", preview.stdout)
            target = root / "capabilities" / name
            self.assertFalse(target.exists())
            interrupted = self.run_scaffold(root, name, *arguments, "--prepare-foundation",
                                             "--fixture-interrupt-after", "initial-committed",
                                             check=False, extra_env=env)
            self.assertEqual(interrupted.returncode, 75, interrupted.stderr)
            prepared = self.result(self.run_scaffold(root, name, *resume, extra_env=env))
            self.assertEqual(prepared["initial_head"], self.git(target, "rev-parse", "HEAD"))
            self.assertEqual(prepared["initial_tree"], self.git(target, "rev-parse", "HEAD^{tree}"))
            self.assertIsNone(prepared["github_repository_id"])
            self.assertEqual(prepared, self.result(self.run_scaffold(root, name, *resume, extra_env=env)))
            self.assertEqual(self.operation(target)["phase"], "initial-committed")
            self.assertFalse(observation.exists())
            self.assertFalse((root / ".doc-warden-fixture-remotes").exists())

            wrong_head = self.run_scaffold(root, name, *arguments, "--resume", "--foundation-head",
                                           "0" * 40, check=False, extra_env=env)
            self.assertEqual(wrong_head.returncode, 2, wrong_head.stderr)
            self.assertIn("the exact reviewed foundation head has changed", wrong_head.stderr)
            self.assertFalse((root / ".doc-warden-fixture-remotes").exists())
            observed = (*arguments, "--resume", "--foundation-head", prepared["initial_head"])
            provider_attempt = self.run_scaffold(root, name, *observed,
                                                 "--fixture-interrupt-after", "remote-create-attempted",
                                                 check=False)
            self.assertEqual(provider_attempt.returncode, 75, provider_attempt.stderr)
            too_late = self.run_scaffold(root, name, *resume, check=False, extra_env=env)
            self.assertEqual(too_late.returncode, 2, too_late.stderr)
            self.assertIn("cannot resume after provider creation begins", too_late.stderr)
            self.assertFalse(observation.exists())
            self.assertEqual(self.git(target, "rev-parse", "HEAD"), prepared["initial_head"])
            result = self.result(self.run_scaffold(root, name, *observed))
            self.assertEqual(result["github_repository_id"], 931885)
            self.assertEqual(self.git(target, "rev-parse", "HEAD^"), prepared["initial_head"])
            self.assertEqual(self.git(target, "status", "--porcelain"), "")
            repeated = self.result(self.run_scaffold(root, name, *observed))
            self.assertEqual(repeated["github_repository_id"], 931885)
            calls = root / f".doc-warden-fixture-remotes/{name}.calls"
            self.assertEqual(sum(row.startswith("repo create ") for row in calls.read_text().splitlines()), 1)

    def test_personal_capability_fixture_replays_both_provider_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            owner = root / "capabilities"
            owner.mkdir()
            name = "repo-platform"
            repository_id = 901284
            arguments = ("--personal-codex", "--capability", "--kind", "tool",
                         "--shape", "release-descriptor", "--public", "--no-push",
                         "--fixture-repository-id", str(repository_id))
            before = self.run_scaffold(root, name, *arguments,
                                       "--fixture-interrupt-after", "remote-create-attempted", check=False)
            self.assertEqual(before.returncode, 75, before.stderr)
            target = owner / name
            first = self.git(target, "rev-parse", "HEAD")
            self.assertTrue((target / ".git/hooks/pre-commit").is_file())
            self.assertTrue((target / ".github/test-sharding-required.json").is_file())
            self.assertEqual(self.git(target, "config", "--local", "user.email"),
                             "49759187+KleinPerkins@users.noreply.github.com")
            calls = root / f".doc-warden-fixture-remotes/{name}.calls"
            self.assertEqual(sum(row.startswith("repo create ") for row in calls.read_text().splitlines()), 0)

            landed = self.run_scaffold(root, name, *arguments, "--resume",
                                       "--fixture-interrupt-after", "remote-create-landed", check=False)
            self.assertEqual(landed.returncode, 75, landed.stderr)
            self.assertEqual(self.operation(target)["phase"], "remote-create-attempted")
            calls_before = calls.read_bytes()
            wrong_id = self.run_scaffold(root, name, *arguments[:-1], str(repository_id + 1),
                                         "--resume", check=False)
            self.assertNotEqual(wrong_id.returncode, 0)
            self.assertIn("operation belongs to a different checkout or scaffold profile", wrong_id.stderr)
            self.assertEqual(calls.read_bytes(), calls_before)
            self.assertEqual(self.git(target, "rev-parse", "HEAD"), first)

            cleared = self.run_scaffold(root, name, *arguments, "--resume",
                                        "--fixture-interrupt-after", "remote-marker-cleared", check=False)
            self.assertEqual(cleared.returncode, 75, cleared.stderr)
            result = self.result(self.run_scaffold(root, name, *arguments, "--resume"))
            self.assertEqual(result["github_repository_id"], repository_id)
            self.assertTrue(result["resumed"])
            self.assertEqual(self.git(target, "rev-parse", "HEAD^"), first)
            final = self.git(target, "rev-parse", "HEAD")
            duplicate = self.result(self.run_scaffold(root, name, *arguments, "--resume"))
            self.assertEqual(duplicate["github_repository_id"], repository_id)
            self.assertEqual(self.git(target, "rev-parse", "HEAD"), final)
            self.assertEqual(self.git(target, "status", "--porcelain"), "")
            self.assertEqual(sum(row.startswith("repo create ") for row in calls.read_text().splitlines()), 1)

    def test_remote_observation_is_second_guarded_commit_and_resume_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="doc-warden-m4-remote-") as directory:
            root = Path(directory)
            name = "born-v2-remote"
            repository_id = 24681012
            result = self.run_scaffold(
                root,
                name,
                "--fixture-repository-id",
                str(repository_id),
            )
            target = root / name
            payload = self.result(result)
            config = json.loads(
                (target / ".planning/doc-warden.json").read_text()
            )
            projects = sorted(
                (target / ".planning/artifacts").glob("PROJECT-*.md")
            )
            project_before = projects[0].read_bytes()
            head_before = subprocess.check_output(
                ["git", "-C", str(target), "rev-parse", "HEAD"], text=True
            ).strip()

            self.assertEqual(payload["commit_count"], 2)
            self.assertEqual(payload["github_repository_id"], repository_id)
            self.assertEqual(config["github_repository_id"], repository_id)
            self.assertIn(config["repository_key"], projects[0].name)
            remote_receipts = [
                json.loads(path.read_text())
                for path in (
                    target / "_ops/doc-warden/state/v2/receipts"
                ).glob("*.json")
                if json.loads(path.read_text())["github_repository_id"] == repository_id
            ]
            self.assertEqual(len(remote_receipts), 1)
            self.assertEqual(
                remote_receipts[0]["bindings"]["repository_identity"],
                {
                    "github_repository": f"KleinPerkins/{name}",
                    "github_repository_id": repository_id,
                },
            )

            replay = self.run_scaffold(
                root,
                name,
                "--fixture-repository-id",
                str(repository_id),
                "--resume",
            )
            replay_payload = self.result(replay)
            self.assertTrue(replay_payload["resumed"])
            self.assertEqual(replay_payload["repository_key"], config["repository_key"])
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(target), "rev-parse", "HEAD"], text=True
                ).strip(),
                head_before,
            )
            self.assertEqual(projects[0].read_bytes(), project_before)
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(target), "status", "--porcelain"],
                    text=True,
                ),
                "",
            )

    def test_interrupted_post_remote_sequence_resumes_without_automatic_deletion(self):
        with tempfile.TemporaryDirectory(prefix="doc-warden-m4-resume-") as directory:
            root = Path(directory)
            name = "born-v2-resume"
            interrupted = self.run_scaffold(
                root,
                name,
                "--fixture-repository-id",
                "1357911",
                "--fixture-interrupt-after",
                "remote-created",
                check=False,
            )
            target = root / name
            self.assertEqual(interrupted.returncode, 75)
            self.assertIn("explicit external deletion gate", interrupted.stderr)
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(target), "rev-list", "--count", "HEAD"],
                    text=True,
                ).strip(),
                "1",
            )
            config = json.loads((target / ".planning/doc-warden.json").read_text())
            repository_key = config["repository_key"]
            self.assertIsNone(config["github_repository_id"])

            resumed = self.run_scaffold(
                root,
                name,
                "--fixture-repository-id",
                "1357911",
                "--resume",
            )
            payload = self.result(resumed)
            config = json.loads((target / ".planning/doc-warden.json").read_text())
            self.assertEqual(payload["commit_count"], 2)
            self.assertEqual(config["repository_key"], repository_key)
            self.assertEqual(config["github_repository_id"], 1357911)
            self.assertFalse(payload["rollback"]["remote_deleted"])
            self.assertTrue(payload["rollback"]["remote_delete_requires_gate"])

    def test_resume_refuses_non_closed_operation_state(self):
        with tempfile.TemporaryDirectory(prefix="doc-warden-m4-state-") as directory:
            root = Path(directory)
            name = "born-v2-state"
            self.run_scaffold(root, name)
            target = root / name
            git_dir = Path(
                subprocess.check_output(
                    ["git", "-C", str(target), "rev-parse", "--absolute-git-dir"],
                    text=True,
                ).strip()
            )
            state_path = git_dir / "doc-warden-new-repo.json"
            state = json.loads(state_path.read_text())
            state["phase"] = "remote-created-marked"
            state_path.write_text(json.dumps(state))
            head = subprocess.check_output(
                ["git", "-C", str(target), "rev-parse", "HEAD"],
                text=True,
            ).strip()

            resumed = self.run_scaffold(
                root,
                name,
                "--resume",
                check=False,
            )
            self.assertNotEqual(resumed.returncode, 0)
            self.assertIn("operation state is invalid", resumed.stderr)
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(target), "rev-parse", "HEAD"],
                    text=True,
                ).strip(),
                head,
            )

    def test_pre_remote_interruption_retains_verified_local_resume_point(self):
        with tempfile.TemporaryDirectory(
            prefix="doc-warden-m4-pre-remote-"
        ) as directory:
            root = Path(directory)
            name = "born-v2-pre-remote"
            interrupted = self.run_scaffold(
                root,
                name,
                "--fixture-interrupt-after",
                "initial-committed",
                check=False,
            )
            target = root / name

            self.assertEqual(interrupted.returncode, 75)
            self.assertIn("no remote was created", interrupted.stderr)
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(target), "rev-list", "--count", "HEAD"],
                    text=True,
                ).strip(),
                "1",
            )
            config = json.loads(
                (target / ".planning/doc-warden.json").read_text()
            )
            self.assertIsNone(config["github_repository_id"])

            resumed = self.run_scaffold(
                root,
                name,
                "--fixture-repository-id",
                "97531",
                "--resume",
            )
            payload = self.result(resumed)
            self.assertTrue(payload["resumed"])
            self.assertEqual(payload["commit_count"], 2)
            self.assertEqual(payload["github_repository_id"], 97531)

    def test_resume_after_initial_commit_before_state_advance_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="doc-warden-initial-window-") as directory:
            root = Path(directory)
            name = "born-v2-initial-commit-window"
            interrupted = self.run_scaffold(
                root, name, "--fixture-interrupt-after", "initial-commit-landed",
                check=False
            )
            target = root / name
            self.assertEqual(interrupted.returncode, 75)
            operation = self.operation(target)
            self.assertEqual(operation["phase"], "baseline-ready")
            self.assertEqual(operation["replay_intent"], {
                "repository": f"KleinPerkins/{name}",
                "name": name,
                "visibility": "private",
                "description": "",
                "origin": f"git@github.com:KleinPerkins/{name}.git",
                "marker": (
                    "https://doc-warden.invalid/operations/"
                    f"{operation['remote_operation_id']}"
                ),
                "initial_commit_message": f"init: scaffold KleinPerkins/{name} (born v2)",
            })
            initial_head = self.git(target, "rev-parse", "HEAD")
            wrong_name = self.run_scaffold(
                root, f"{name}-other", "--resume", check=False
            )
            self.assertEqual(wrong_name.returncode, 1)
            self.assertIn("persisted_replay_intent_mismatch", wrong_name.stderr)
            self.assertEqual(self.git(target, "rev-parse", "HEAD"), initial_head)
            payload = self.result(self.run_scaffold(root, name, "--resume"))
            self.assertTrue(payload["resumed"])
            self.assertEqual(payload["commit_count"], 1)
            self.assertEqual(
                self.git(target, "log", "--format=%s").splitlines(),
                [f"init: scaffold KleinPerkins/{name} (born v2)"],
            )
            self.assertEqual(self.git(target, "rev-parse", "HEAD"), initial_head)

    def test_initial_commit_recovery_refuses_unrelated_root_head(self):
        with tempfile.TemporaryDirectory(prefix="doc-warden-unrelated-head-") as directory:
            root = Path(directory)
            name = "born-v2-unrelated-head"
            interrupted = self.run_scaffold(
                root, name, "--fixture-repository-id", "753159",
                "--fixture-interrupt-after", "initial-commit-landed", check=False
            )
            target = root / name
            empty_tree = subprocess.check_output(
                ["git", "-C", str(target), "mktree"], input="", text=True
            ).strip()
            unrelated = self.git(
                target, "commit-tree", empty_tree, "-m", "unrelated root"
            )
            subprocess.run(
                ["git", "-C", str(target), "update-ref", "HEAD", unrelated],
                check=True,
            )

            self.assertEqual(interrupted.returncode, 75)
            resumed = self.run_scaffold(
                root, name, "--fixture-repository-id", "753159", "--resume",
                check=False
            )
            calls = root / ".doc-warden-fixture-remotes" / f"{name}.calls"
            self.assertEqual(resumed.returncode, 1)
            self.assertIn("initial_commit_recovery_inconsistent", resumed.stderr)
            self.assertEqual(self.git(target, "rev-parse", "HEAD"), unrelated)
            self.assertFalse(calls.exists())

    def test_resume_after_remote_create_before_state_advance_does_not_recreate(self):
        with tempfile.TemporaryDirectory(prefix="doc-warden-remote-window-") as directory:
            root = Path(directory)
            name = "born-v2-remote"
            interrupted = self.run_scaffold(
                root, name, "--fixture-repository-id", "86420", "--desc",
                "resume fixture", "--fixture-interrupt-after",
                "remote-create-landed", check=False
            )
            target = root / name
            config = json.loads((target / ".planning/doc-warden.json").read_text())
            fixture_remote = root / ".doc-warden-fixture-remotes" / f"{name}.json"
            fixture_calls = fixture_remote.with_suffix(".calls")

            self.assertEqual(interrupted.returncode, 75)
            remote_before = json.loads(fixture_remote.read_text())
            self.assertEqual(self.operation(target)["phase"], "remote-create-attempted")
            calls_before = fixture_calls.read_bytes()
            for conflict in (("--public",), ("--desc", "different")):
                refused = self.run_scaffold(
                    root, name, "--fixture-repository-id", "86420",
                    *conflict, "--resume", check=False
                )
                self.assertEqual(refused.returncode, 1)
                self.assertIn("persisted_replay_intent_mismatch", refused.stderr)
                self.assertEqual(fixture_calls.read_bytes(), calls_before)
            payload = self.result(
                self.run_scaffold(
                    root, name, "--fixture-repository-id", "86420", "--resume"
                )
            )
            current = json.loads((target / ".planning/doc-warden.json").read_text())
            self.assertTrue(payload["resumed"])
            self.assertEqual(payload["commit_count"], 2)
            self.assertEqual(current["repository_key"], config["repository_key"])
            self.assertEqual(current["github_repository_id"], 86420)
            self.assertEqual(
                sum(
                    line.startswith(f"repo create KleinPerkins/{name} ")
                    for line in fixture_calls.read_text().splitlines()
                ),
                1,
            )
            self.assertEqual(
                json.loads(fixture_remote.read_text())["homepage"],
                "",
            )
            self.assertEqual(
                payload["remote_creation_evidence"],
                {
                    "operation_id": self.operation(target)["remote_operation_id"],
                    "marker": remote_before["homepage"],
                    "repository_id": 86420,
                    "marker_cleared": True,
                },
            )

    def test_resume_after_marker_clear_before_state_advance_is_idempotent(self):
        with tempfile.TemporaryDirectory(prefix="doc-warden-marker-clear-") as directory:
            root = Path(directory)
            name = "born-v2-marker-clear"
            interrupted = self.run_scaffold(
                root, name, "--fixture-repository-id", "975310",
                "--fixture-interrupt-after", "remote-marker-cleared", check=False
            )
            target = root / name
            remote = root / ".doc-warden-fixture-remotes" / f"{name}.json"
            calls_path = remote.with_suffix(".calls")
            state = self.operation(target)

            self.assertEqual(interrupted.returncode, 75)
            self.assertEqual(state["phase"], "remote-created-marked")
            self.assertEqual(state["github_repository_id"], 975310)
            self.assertEqual(json.loads(remote.read_text())["homepage"], "")
            calls_before = calls_path.read_text().splitlines()

            payload = self.result(self.run_scaffold(
                root, name, "--fixture-repository-id", "975310", "--resume"
            ))
            calls_after = calls_path.read_text().splitlines()
            self.assertEqual(payload["github_repository_id"], 975310)
            self.assertEqual(sum(line.startswith("repo create ") for line in calls_after), 1)
            self.assertEqual(sum("--method PATCH" in line for line in calls_after), 1)
            self.assertEqual(len(calls_after) - len(calls_before), 2)
            self.assertEqual(json.loads(remote.read_text())["homepage"], "")

    def test_preexisting_remote_before_attempt_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="doc-warden-preexisting-") as directory:
            root = Path(directory)
            name = "born-v2-preexisting"
            interrupted = self.run_scaffold(
                root, name, "--fixture-repository-id", "112233",
                "--fixture-interrupt-after", "initial-committed", check=False
            )
            target = root / name
            fixture_remote = self.fake_remote(root, name, 112233, "")

            self.assertEqual(interrupted.returncode, 75)
            resumed = self.run_scaffold(
                root, name, "--fixture-repository-id", "112233", "--resume",
                check=False
            )
            config = json.loads((target / ".planning/doc-warden.json").read_text())
            self.assertEqual(resumed.returncode, 1)
            self.assertIn("remote_creation_preexisting_refused", resumed.stderr)
            self.assertIsNone(config["github_repository_id"])
            self.assertNotIn("repo create", fixture_remote.with_suffix(".calls").read_text())

    def test_unrelated_remote_after_attempt_marker_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="doc-warden-racing-") as directory:
            root = Path(directory)
            name = "born-v2-racing"
            interrupted = self.run_scaffold(
                root, name, "--fixture-repository-id", "445566",
                "--fixture-interrupt-after", "remote-create-attempted",
                check=False
            )
            target = root / name
            fixture_remote = self.fake_remote(
                root, name, 445566, "https://unrelated.invalid/repository"
            )

            self.assertEqual(interrupted.returncode, 75)
            resumed = self.run_scaffold(
                root, name, "--fixture-repository-id", "445566", "--resume",
                check=False
            )
            config = json.loads((target / ".planning/doc-warden.json").read_text())
            calls = fixture_remote.with_suffix(".calls").read_text()
            self.assertEqual(resumed.returncode, 1)
            self.assertIn("remote_creation_recovery_inconsistent", resumed.stderr)
            self.assertEqual(self.operation(target)["phase"], "remote-create-attempted")
            self.assertIsNone(config["github_repository_id"])
            self.assertNotIn("repo create", calls)
            self.assertNotIn("--method PATCH", calls)

    def test_verified_transaction_replays_before_initial_commit(self):
        with tempfile.TemporaryDirectory(
            prefix="doc-warden-m4-transaction-"
        ) as directory:
            root = Path(directory)
            name = "born-v2-transaction"
            interrupted = self.run_scaffold(
                root,
                name,
                "--fixture-interrupt-after",
                "scaffold-verified",
                check=False,
            )
            target = root / name

            self.assertEqual(interrupted.returncode, 75)
            self.assertIn("exact --resume replay is available", interrupted.stderr)
            self.assertNotEqual(
                subprocess.run(
                    ["git", "-C", str(target), "rev-parse", "--verify", "HEAD"],
                    check=False,
                    capture_output=True,
                ).returncode,
                0,
            )

            resumed = self.run_scaffold(root, name, "--resume")
            payload = self.result(resumed)
            self.assertTrue(payload["resumed"])
            self.assertEqual(payload["commit_count"], 1)
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(target), "status", "--porcelain"],
                    text=True,
                ),
                "",
            )

    def test_unenrolled_post_push_and_resume_never_apply_retired_settings(self):
        """Source push is idempotent; settings admission remains pending on resume."""
        with tempfile.TemporaryDirectory(
            prefix="doc-warden-m4-unenrolled-"
        ) as directory:
            root = Path(directory)
            name = "born-v2-unenrolled"
            repository_id = 98765

            # Local bare repo absorbs git push without SSH.
            bare_remote = root / "bare-remote.git"
            subprocess.run(
                ["git", "init", "--bare", str(bare_remote)],
                check=True, capture_output=True,
            )

            # Faithful git-push invocation counter: a confined git wrapper that
            # logs each `git push` call then delegates to the exact real binary.
            # post-receive cannot detect no-op pushes (same commit, no ref update);
            # this wrapper counts the actual subprocess invocation unconditionally.
            import shutil as _shutil
            real_git = _shutil.which("git")
            git_spy_dir = root / ".git-spy-bin"
            git_spy_dir.mkdir()
            push_log = root / "push-invocations.log"
            (git_spy_dir / "git").write_text(
                '#!/usr/bin/env bash\n'
                'for arg in "$@"; do\n'
                f'  [ "$arg" = "push" ] && {{ printf "push\\n" >> {push_log}; break; }}\n'
                'done\n'
                f'exec {real_git} "$@"\n'
            )
            (git_spy_dir / "git").chmod(0o755)

            # Mode-switched fake baseline: reads a mode file to decide pass/fail,
            # delegates all other verbs to the real baseline unchanged.
            real_baseline = str(ROOT / "_ops/bin/repo-baseline.sh")
            mode_file = root / "baseline-mode"
            mode_file.write_text("fail")
            fake_baseline = root / "fake-repo-baseline.sh"
            fake_baseline.write_text(
                '#!/usr/bin/env bash\n'
                'verb="${1:-}"\n'
                f'mode="$(cat {mode_file} 2>/dev/null || echo fail)"\n'
                'case "$verb" in\n'
                '    enforce|reconcile-merge-safety)\n'
                f'        touch {root / "settings-called"}\n'
                '        [ "$mode" = "fail" ] || exit 0\n'
                '        printf "repo-baseline %s: REFUSING (fixture)\\n" "$verb" >&2\n'
                '        exit 1\n'
                '        ;;\n'
                '    *)\n'
                f'        exec {real_baseline} "$@"\n'
                '        ;;\n'
                'esac\n'
            )
            fake_baseline.chmod(0o700)

            spy_path = f"{git_spy_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"
            fixture_env = {
                "DOC_WARDEN_FIXTURE_REPO_BASELINE": str(fake_baseline),
                "DOC_WARDEN_FIXTURE_PUSH_REMOTE": str(bare_remote),
                "PATH": spy_path,
            }

            # ── Phase 1: forbidden settings stub must not run ────────────────────────────────────────────
            result = self.run_scaffold(
                root, name, "--fixture-repository-id", str(repository_id),
                check=False, extra_env=fixture_env,
            )
            target = root / name

            # Must not abort under set -e.
            self.assertEqual(result.returncode, 0, result.stderr)

            # Truthful waiting_external shape.
            payload = self.result(result)
            self.assertEqual(payload["schema"], "dev-new-repo-result/v2")
            self.assertEqual(payload["status"], "waiting_external")
            self.assertEqual(payload["github_repository_id"], repository_id)

            # Failures surfaced in stderr (diagnostic wording is neutral, not "unenrolled").
            self.assertFalse((root / "settings-called").exists())
            self.assertFalse(payload["delivery"]["controller_enrollment"])

            # Pending scaffold has no CI workflows.
            self.assertEqual(list((target / ".github").glob("workflows/*.y*ml")), [])
            self.assertEqual(payload["doctor"]["repository_writes"], [])

            # Pending admission is durable; resume cannot turn it into enforcement.
            self.assertEqual(self.operation(target)["phase"], "waiting-external")

            # Push count = 1 after first run.
            self.assertEqual(push_log.read_text().strip().count("push"), 1)
            head_before = self.git(target, "rev-parse", "HEAD")

            # ── Phase 2: resume still cannot invoke settings ───────────────────────────
            mode_file.write_text("ok")
            result_ok = self.run_scaffold(
                root, name, "--fixture-repository-id", str(repository_id), "--resume",
                extra_env=fixture_env,
            )
            payload_ok = self.result(result_ok)

            self.assertEqual(result_ok.returncode, 0, result_ok.stderr)
            self.assertEqual(payload_ok["status"], "waiting_external")
            self.assertTrue(payload_ok["resumed"])

            # Phase remains waiting-external; no settings success is inferred.
            self.assertEqual(self.operation(target)["phase"], "waiting-external")

            # Push count still 1: the idempotent skip check prevented a re-push.
            self.assertEqual(push_log.read_text().strip().count("push"), 1)

            # HEAD unchanged: no recommit during resume.
            self.assertEqual(self.git(target, "rev-parse", "HEAD"), head_before)

            self.assertFalse((root / "settings-called").exists())
            # No failure messages in resume stderr.
            self.assertNotIn("failed", result_ok.stderr)

            # Working tree clean after both runs.
            self.assertEqual(
                subprocess.check_output(
                    ["git", "-C", str(target), "status", "--porcelain"], text=True,
                ),
                "",
            )


if __name__ == "__main__":
    unittest.main()
