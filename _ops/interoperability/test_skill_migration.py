"""INT-008 source proof, bounded migration, recovery, and rollback tests."""

from argparse import Namespace
from contextlib import contextmanager, ExitStack, redirect_stdout
import copy
import json
import io
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import skill_migration as m


def run(*args: str, cwd: Path, input_text: str | None = None) -> str:
    result = subprocess.run(
        list(args), cwd=cwd, input=input_text, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def make_home(root: Path) -> tuple[Path, Path, Path]:
    home = root / "home"
    primary = home / "dev/capabilities/skills"
    source = root / "owner-object-source"
    source.mkdir(parents=True)
    for relative in (".agents/skills", ".codex/skills", ".cursor/skills", ".codex/plugins"):
        (home / relative).mkdir(parents=True)
    (home / ".codex/config.toml").write_text("[skills]\n")
    for name in m.SKILLS:
        skill = primary / "global/skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"# {name}\n")
        (home / ".agents/skills" / name).symlink_to(skill)
        (home / ".cursor/skills" / name).symlink_to(skill)
    (home / ".codex/skills/.system").mkdir()
    (home / ".codex/skills/.system/marker").write_text("system-owned")
    (home / ".codex/skills/unknown-owner").mkdir()
    (home / ".codex/skills/unknown-owner/marker").write_text("unknown-owned")
    (home / ".codex/plugins/marker").write_text("plugin-owned")
    return home, primary, source


@contextmanager
def operation_fixture() -> object:
    with tempfile.TemporaryDirectory(prefix="int008-operation-") as raw:
        root = Path(raw).resolve()
        home, primary, source = make_home(root)
        primary_row = {
            "path": str(primary),
            "branch": "main",
            "head": "a" * 40,
            "origin_main": "a" * 40,
            "clean": True,
            "payload_sha256": m.PAYLOAD_SHA256,
            "file_count": m.PAYLOAD_FILE_COUNT,
            "current_merged_payload": True,
        }
        object_row = {
            "repository": "KleinPerkins/skills",
            "revision": m.MERGED_REVISION,
            "tree": m.MERGED_TREE,
            "payload_sha256": m.PAYLOAD_SHA256,
            "file_count": m.PAYLOAD_FILE_COUNT,
            "qualification": {"host_build": m.QUALIFIED_HOST_BUILD},
        }
        args = Namespace(
            home=home,
            skills_source=source,
            operation_dir=root / "operation",
            source_mode="retained",
            host_build=m.QUALIFIED_HOST_BUILD,
            approve=None,
        )
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    m,
                    "object_source_proof",
                    side_effect=lambda *_: (copy.deepcopy(object_row), {}),
                )
            )
            stack.enter_context(
                patch.object(
                    m,
                    "primary_observation",
                    side_effect=lambda *_args, **_kwargs: copy.deepcopy(primary_row),
                )
            )
            yield Namespace(
                root=root,
                home=home,
                primary=primary,
                source=source,
                args=args,
                primary_row=primary_row,
                object_row=object_row,
            )


def preview(fixture) -> dict:
    result = m.preview(fixture.args)
    fixture.args.approve = result["action_sha256"]
    return result


class MigrationOperations(unittest.TestCase):
    def test_preview_apply_verify_reapply_and_exact_rollback(self):
        with operation_fixture() as f:
            config_before = (f.home / ".codex/config.toml").read_bytes()
            protected = {
                path: path.read_bytes()
                for path in (
                    f.home / ".codex/skills/.system/marker",
                    f.home / ".codex/skills/unknown-owner/marker",
                    f.home / ".codex/plugins/marker",
                )
            }
            cursor = {
                name: os.readlink(f.home / ".cursor/skills" / name) for name in m.SKILLS
            }
            result = preview(f)
            self.assertEqual(len(result["actions"]), 4)
            self.assertFalse(result["production_rollout"])
            self.assertEqual(stat.S_IMODE(f.args.operation_dir.stat().st_mode), 0o700)
            self.assertEqual(
                stat.S_IMODE((f.args.operation_dir / "operation.json").stat().st_mode), 0o600
            )
            self.assertTrue(all((f.home / ".agents/skills" / name).is_symlink() for name in m.SKILLS))
            self.assertTrue(all(not (f.home / ".codex/skills" / name).exists() for name in m.SKILLS))

            self.assertEqual(m.apply_operation(f.args)["status"], "applied")
            self.assertEqual(m.verify_operation(f.args)["status"], "verified-applied")
            self.assertEqual(m.verify_operation(f.args)["status"], "verified-applied")
            self.assertEqual(m.apply_operation(f.args)["status"], "already-applied")
            for name in m.SKILLS:
                self.assertFalse((f.home / ".agents/skills" / name).exists())
                self.assertEqual(
                    os.readlink(f.home / ".codex/skills" / name),
                    str(f.primary / "global/skills" / name),
                )
                self.assertEqual(os.readlink(f.home / ".cursor/skills" / name), cursor[name])
            self.assertEqual((f.home / ".codex/config.toml").read_bytes(), config_before)
            for path, data in protected.items():
                self.assertEqual(path.read_bytes(), data)

            self.assertEqual(m.apply_operation(f.args, rollback=True)["status"], "rolled-back")
            self.assertEqual(m.verify_operation(f.args)["status"], "verified-preimage")
            self.assertEqual(
                m.apply_operation(f.args, rollback=True)["status"], "already-rolled-back"
            )
            for name in m.SKILLS:
                self.assertEqual(
                    os.readlink(f.home / ".agents/skills" / name),
                    str(f.primary / "global/skills" / name),
                )
                self.assertFalse((f.home / ".codex/skills" / name).exists())

    def test_foreign_dangling_real_and_modified_aliases_refuse_all_paths(self):
        cases = ("foreign-agent", "dangling-agent", "real-codex", "foreign-codex")
        for case in cases:
            with self.subTest(case=case), operation_fixture() as f:
                agent = f.home / ".agents/skills" / m.SKILLS[0]
                codex = f.home / ".codex/skills" / m.SKILLS[0]
                foreign = f.root / "foreign"
                foreign.mkdir()
                if case == "foreign-agent":
                    agent.unlink()
                    agent.symlink_to(foreign)
                elif case == "dangling-agent":
                    agent.unlink()
                    agent.symlink_to(f.root / "missing")
                elif case == "real-codex":
                    codex.mkdir()
                else:
                    codex.symlink_to(foreign)
                with self.assertRaises(ValueError):
                    m.preview(f.args)
                self.assertFalse(f.args.operation_dir.exists())
                self.assertTrue((f.home / ".agents/skills" / m.SKILLS[1]).is_symlink())
                self.assertFalse((f.home / ".codex/skills" / m.SKILLS[1]).exists())

        with operation_fixture() as f:
            preview(f)
            changed = f.home / ".agents/skills" / m.SKILLS[1]
            changed.unlink()
            foreign = f.root / "later-foreign"
            foreign.mkdir()
            changed.symlink_to(foreign)
            with self.assertRaises(ValueError):
                m.apply_operation(f.args)
            self.assertTrue(all(not (f.home / ".codex/skills" / name).exists() for name in m.SKILLS))
            self.assertEqual(os.readlink(changed), str(foreign))

    def test_operation_storage_cannot_overlap_managed_or_system_roots(self):
        cases = (
            ".codex/skills/prompt-architect",
            ".codex/skills/.system/private-operation",
            ".agents/private-operation",
            ".cursor/private-operation",
        )
        for relative in cases:
            with self.subTest(relative=relative), operation_fixture() as f:
                f.args.operation_dir = f.home / relative
                with self.assertRaisesRegex(ValueError, "outside source roots"):
                    m.preview(f.args)
                self.assertFalse(f.args.operation_dir.exists())

    def test_parent_directory_identity_replacement_refuses_apply(self):
        with operation_fixture() as f:
            preview(f)
            managed_parent = f.home / ".codex/skills"
            original = f.root / "original-codex-skills"
            managed_parent.rename(original)
            managed_parent.mkdir(mode=stat.S_IMODE(original.stat().st_mode))
            with self.assertRaisesRegex(ValueError, "preserved path changed"):
                m.apply_operation(f.args)
            self.assertTrue(
                all(not (managed_parent / name).exists() for name in m.SKILLS)
            )

    def test_private_operation_modes_and_root_identity_are_bound(self):
        with operation_fixture() as f:
            preview(f)
            f.args.operation_dir.chmod(0o755)
            with self.assertRaisesRegex(ValueError, "mode 0700"):
                m.load_operation(f.args.operation_dir)
            f.args.operation_dir.chmod(0o700)
            record = f.args.operation_dir / "operation.json"
            record.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "mode 0600"):
                m.load_operation(f.args.operation_dir)
            record.chmod(0o600)

        with operation_fixture() as f:
            preview(f)
            original = f.root / "original-operation"
            f.args.operation_dir.rename(original)
            shutil.copytree(original, f.args.operation_dir, copy_function=shutil.copy2)
            with self.assertRaisesRegex(ValueError, "root identity changed"):
                m.load_operation(f.args.operation_dir)

    def test_symlink_mode_failure_leaves_no_live_or_staged_partial(self):
        with operation_fixture() as f:
            preview(f)
            first = f.args.operation_dir / "operation.json"
            plan = json.loads(first.read_text())
            action = plan["actions"][0]
            with patch.object(m, "set_symlink_mode", side_effect=ValueError("mode failure")):
                with self.assertRaisesRegex(ValueError, "mode failure"):
                    m.apply_operation(f.args)
            self.assertEqual(m.state(Path(action["path"])), action["before"])
            self.assertEqual(m.state(Path(action["staging_path"])), {"kind": "absent"})
            self.assertEqual(m.apply_operation(f.args)["status"], "applied")
            self.assertEqual(m.apply_operation(f.args, rollback=True)["status"], "rolled-back")

        with operation_fixture() as f:
            preview(f)
            plan = json.loads((f.args.operation_dir / "operation.json").read_text())
            action = plan["actions"][0]
            os.symlink(action["after"]["target"], action["staging_path"])
            self.assertEqual(m.apply_operation(f.args)["status"], "applied")
            self.assertEqual(m.state(Path(action["staging_path"])), {"kind": "absent"})
            self.assertEqual(m.apply_operation(f.args, rollback=True)["status"], "rolled-back")

    def test_atomic_publish_refuses_concurrent_target_without_clobber(self):
        with operation_fixture() as f:
            preview(f)
            plan = json.loads((f.args.operation_dir / "operation.json").read_text())
            action = plan["actions"][0]
            target = Path(action["path"])
            foreign = f.root / "concurrent-user-target"
            foreign.mkdir()
            real_link = os.link

            def inject_concurrent_target(source, destination, **kwargs):
                Path(destination).symlink_to(foreign)
                return real_link(source, destination, **kwargs)

            with patch.object(m.os, "link", side_effect=inject_concurrent_target):
                with self.assertRaises(FileExistsError):
                    m.apply_operation(f.args)
            self.assertEqual(os.readlink(target), str(foreign))
            self.assertEqual(m.state(Path(action["staging_path"])), {"kind": "absent"})

    def test_relevant_config_drift_refuses_but_unrelated_bytes_survive(self):
        with operation_fixture() as f:
            preview(f)
            config = f.home / ".codex/config.toml"
            config.write_text(config.read_text() + "\n[features]\nexample = true\n")
            unrelated = config.read_bytes()
            self.assertEqual(m.apply_operation(f.args)["status"], "applied")
            self.assertEqual(config.read_bytes(), unrelated)
            m.apply_operation(f.args, rollback=True)

        with operation_fixture() as f:
            preview(f)
            config = f.home / ".codex/config.toml"
            config.write_text(
                config.read_text()
                + f'\n[[skills.config]]\npath = "{f.home / ".codex/skills" / m.SKILLS[0]}"\nenabled = false\n'
            )
            with self.assertRaisesRegex(ValueError, "policy changed"):
                m.apply_operation(f.args)
            self.assertTrue(all(not (f.home / ".codex/skills" / name).exists() for name in m.SKILLS))

    def test_alias_specific_native_opt_out_refuses_preview(self):
        with operation_fixture() as f:
            path = f.home / ".agents/skills" / m.SKILLS[0]
            (f.home / ".codex/config.toml").write_text(
                f'[skills]\n[[skills.config]]\npath = "{path}"\nenabled = false\n'
            )
            with self.assertRaisesRegex(ValueError, "retiring .agents alias"):
                m.preview(f.args)
            self.assertFalse(f.args.operation_dir.exists())

    def test_action_receipt_and_source_tampering_refuse(self):
        with operation_fixture() as f:
            preview(f)
            path = f.args.operation_dir / "operation.json"
            row = json.loads(path.read_text())
            row["affected_sessions"] = "tampered"
            path.chmod(0o600)
            path.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, "action changed"):
                m.load_operation(f.args.operation_dir)

        with operation_fixture() as f:
            preview(f)
            path = f.args.operation_dir / "preview-receipt.json"
            row = json.loads(path.read_text())
            row["extra"] = True
            path.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, "receipt changed"):
                m.load_operation(f.args.operation_dir)

        with operation_fixture() as f:
            preview(f)
            with patch.object(m, "current_source_proof", side_effect=ValueError("source changed")):
                with self.assertRaisesRegex(ValueError, "source changed"):
                    m.apply_operation(f.args)
            self.assertTrue(all(not (f.home / ".codex/skills" / name).exists() for name in m.SKILLS))

    def test_rollback_refuses_later_user_edit(self):
        with operation_fixture() as f:
            preview(f)
            m.apply_operation(f.args)
            path = f.home / ".codex/skills" / m.SKILLS[0]
            path.unlink()
            later = f.root / "later-user-target"
            later.mkdir()
            path.symlink_to(later)
            with self.assertRaisesRegex(ValueError, "recoverable operation sequence"):
                m.apply_operation(f.args, rollback=True)
            self.assertEqual(os.readlink(path), str(later))

    def test_interruption_after_each_apply_and_rollback_mutation_recovers(self):
        for point in range(1, 5):
            with self.subTest(phase="apply", point=point), operation_fixture() as f:
                preview(f)
                original = m.mutate
                calls = 0

                def interrupt(row, *, reverse=False):
                    nonlocal calls
                    original(row, reverse=reverse)
                    calls += 1
                    if calls == point:
                        raise OSError("injected interruption")

                with patch.object(m, "mutate", side_effect=interrupt):
                    with self.assertRaises(OSError):
                        m.apply_operation(f.args)
                self.assertIn(
                    m.apply_operation(f.args)["status"], {"recovered-applied", "already-applied"}
                )
                self.assertEqual(m.verify_operation(f.args)["status"], "verified-applied")

            with self.subTest(phase="rollback", point=point), operation_fixture() as f:
                preview(f)
                m.apply_operation(f.args)
                original = m.mutate
                calls = 0

                def interrupt_rollback(row, *, reverse=False):
                    nonlocal calls
                    original(row, reverse=reverse)
                    calls += 1
                    if calls == point:
                        raise OSError("injected interruption")

                with patch.object(m, "mutate", side_effect=interrupt_rollback):
                    with self.assertRaises(OSError):
                        m.apply_operation(f.args, rollback=True)
                self.assertIn(
                    m.apply_operation(f.args, rollback=True)["status"],
                    {"recovered-rolled-back", "already-rolled-back"},
                )
                self.assertEqual(m.verify_operation(f.args)["status"], "verified-preimage")


class SourceRepositoryFixture:
    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.repo = self.home / "dev/capabilities/skills"
        self.repo.mkdir(parents=True)
        run("git", "init", "-q", "-b", "main", cwd=self.repo)
        run("git", "config", "user.name", "Fixture", cwd=self.repo)
        run("git", "config", "user.email", "fixture@example.test", cwd=self.repo)
        run("git", "remote", "add", "origin", "git@github.com:KleinPerkins/skills.git", cwd=self.repo)
        for name in m.SKILLS:
            skill = self.repo / "global/skills" / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(f"# {name}\n")
        evidence = self.repo / m.EVIDENCE_PATH
        evidence.parent.mkdir(parents=True)
        rows = []
        for check in ("SKL-01-native-discovery-and-use", "ROL-01-native-canary-rollback"):
            rows.append(
                {
                    "schema": "interoperability/qualification/v1",
                    "capability": "required-skills-codex-discovery",
                    "owner": "KleinPerkins/skills",
                    "source_revision": "a" * 40,
                    "adapter_revision": "a" * 40,
                    "payload_sha256": "placeholder",
                    "host": "codex",
                    "surface": "local-macos-desktop",
                    "host_build": "test-build",
                    "check": check,
                    "outcome": "pass",
                    "limitations": ["not-activation"],
                }
            )
        # Payload does not include this evidence file, so compute it before the commit.
        digest_map = {}
        for name in m.SKILLS:
            path = self.repo / "global/skills" / name / "SKILL.md"
            digest_map[f"{name}/SKILL.md"] = m.sha(path.read_bytes())
        self.payload = m.sha(m.canonical(digest_map))
        for row in rows:
            row["payload_sha256"] = self.payload
        evidence.write_text(json.dumps(rows) + "\n")
        run("git", "add", ".", cwd=self.repo)
        run("git", "commit", "-qm", "fixture", cwd=self.repo)
        self.commit = run("git", "rev-parse", "HEAD", cwd=self.repo)
        self.tree = run("git", "rev-parse", "HEAD^{tree}", cwd=self.repo)
        run("git", "update-ref", "refs/remotes/origin/main", self.commit, cwd=self.repo)
        for relative in (".agents/skills", ".codex/skills", ".cursor/skills"):
            (self.home / relative).mkdir(parents=True)
        (self.home / ".codex/config.toml").write_text("[skills]\n")
        for name in m.SKILLS:
            skill = self.repo / "global/skills" / name
            (self.home / ".agents/skills" / name).symlink_to(skill)
            (self.home / ".cursor/skills" / name).symlink_to(skill)

    @contextmanager
    def constants(self):
        with ExitStack() as stack:
            for name, value in (
                ("MERGED_REVISION", self.commit),
                ("IMPLEMENTATION_REVISION", "a" * 40),
                ("MERGED_TREE", self.tree),
                ("PAYLOAD_SHA256", self.payload),
                ("PAYLOAD_FILE_COUNT", 2),
                ("QUALIFIED_HOST_BUILD", "test-build"),
            ):
                stack.enter_context(patch.object(m, name, value))
            yield


class SourceProofAndCanary(unittest.TestCase):
    def test_exact_owner_objects_and_current_primary_are_required(self):
        with tempfile.TemporaryDirectory(prefix="int008-source-") as raw:
            fixture = SourceRepositoryFixture(Path(raw).resolve())
            with fixture.constants():
                proof, blobs = m.object_source_proof(fixture.repo, "test-build")
                self.assertEqual(proof["payload_sha256"], fixture.payload)
                self.assertEqual(len(blobs), 2)
                self.assertTrue(
                    m.primary_observation(fixture.home, require_current=True)[
                        "current_merged_payload"
                    ]
                )

                commit2 = run(
                    "git",
                    "commit-tree",
                    fixture.tree,
                    "-p",
                    fixture.commit,
                    cwd=fixture.repo,
                    input_text="remote descendant\n",
                )
                run("git", "update-ref", "refs/remotes/origin/main", commit2, cwd=fixture.repo)
                with self.assertRaisesRegex(ValueError, "stale"):
                    m.primary_observation(fixture.home, require_current=True)

    def test_nonprimary_source_refused(self):
        with tempfile.TemporaryDirectory(prefix="int008-linked-") as raw:
            root = Path(raw).resolve()
            source = root / "source"
            source.mkdir()
            run("git", "init", "-q", "-b", "main", cwd=source)
            run("git", "config", "user.name", "Fixture", cwd=source)
            run("git", "config", "user.email", "fixture@example.test", cwd=source)
            (source / "file").write_text("x")
            run("git", "add", ".", cwd=source)
            run("git", "commit", "-qm", "fixture", cwd=source)
            target = root / "home/dev/capabilities/skills"
            target.parent.mkdir(parents=True)
            run("git", "worktree", "add", "-q", "-b", "linked", str(target), cwd=source)
            self.assertTrue((target / ".git").is_file())
            with self.assertRaisesRegex(ValueError, "durable primary"):
                m.primary_observation(root / "home", require_current=False)

    def test_canary_uses_private_exact_export_and_source_tamper_refuses(self):
        with tempfile.TemporaryDirectory(prefix="int008-canary-") as raw:
            fixture = SourceRepositoryFixture(Path(raw).resolve())
            args = Namespace(
                home=fixture.home,
                skills_source=fixture.repo,
                operation_dir=fixture.root / "operation",
                source_mode="canary",
                host_build="test-build",
                approve=None,
            )
            with fixture.constants():
                result = m.preview(args)
                args.approve = result["action_sha256"]
                plan, _ = m.load_operation(args.operation_dir)
                export = Path(plan["source_proof"]["desired"])
                self.assertNotEqual(export, fixture.repo)
                self.assertEqual(m.filesystem_payload(export), (fixture.payload, 2))
                path = export / "global/skills" / m.SKILLS[0] / "SKILL.md"
                path.chmod(0o600)
                path.write_text("tampered")
                path.chmod(0o400)
                with self.assertRaisesRegex(ValueError, "export changed"):
                    m.apply_operation(args)
                self.assertTrue(
                    all(not (fixture.home / ".codex/skills" / name).exists() for name in m.SKILLS)
                )
                self.assertEqual(
                    m.apply_operation(args, rollback=True)["status"], "already-rolled-back"
                )
                m.remove_private_tree(args.operation_dir)
                self.assertFalse(args.operation_dir.exists())

    def test_canary_refuses_mode_only_export_tamper(self):
        with tempfile.TemporaryDirectory(prefix="int008-canary-mode-") as raw:
            fixture = SourceRepositoryFixture(Path(raw).resolve())
            args = Namespace(
                home=fixture.home,
                skills_source=fixture.repo,
                operation_dir=fixture.root / "operation",
                source_mode="canary",
                host_build="test-build",
                approve=None,
            )
            with fixture.constants():
                result = m.preview(args)
                args.approve = result["action_sha256"]
                plan, _ = m.load_operation(args.operation_dir)
                path = (
                    Path(plan["source_proof"]["desired"])
                    / "global/skills"
                    / m.SKILLS[0]
                    / "SKILL.md"
                )
                path.chmod(0o600)
                with self.assertRaisesRegex(ValueError, "privacy mode changed"):
                    m.apply_operation(args)
                self.assertEqual(
                    m.apply_operation(args, rollback=True)["status"], "already-rolled-back"
                )
                m.remove_private_tree(args.operation_dir)
                self.assertFalse(args.operation_dir.exists())

    def test_canary_refuses_empty_directory_tamper(self):
        with tempfile.TemporaryDirectory(prefix="int008-canary-dir-") as raw:
            fixture = SourceRepositoryFixture(Path(raw).resolve())
            args = Namespace(
                home=fixture.home,
                skills_source=fixture.repo,
                operation_dir=fixture.root / "operation",
                source_mode="canary",
                host_build="test-build",
                approve=None,
            )
            with fixture.constants():
                result = m.preview(args)
                args.approve = result["action_sha256"]
                plan, _ = m.load_operation(args.operation_dir)
                skill = Path(plan["source_proof"]["desired"]) / "global/skills" / m.SKILLS[0]
                skill.chmod(0o700)
                (skill / "unexpected-empty").mkdir()
                skill.chmod(0o500)
                with self.assertRaisesRegex(ValueError, "path set changed"):
                    m.apply_operation(args)
                self.assertEqual(
                    m.apply_operation(args, rollback=True)["status"], "already-rolled-back"
                )
                m.remove_private_tree(args.operation_dir)
                self.assertFalse(args.operation_dir.exists())

    def test_canary_refuses_primary_bound_native_override(self):
        with tempfile.TemporaryDirectory(prefix="int008-canary-config-") as raw:
            fixture = SourceRepositoryFixture(Path(raw).resolve())
            target = fixture.repo / "global/skills" / m.SKILLS[0]
            (fixture.home / ".codex/config.toml").write_text(
                f'[skills]\n[[skills.config]]\npath = "{target}"\nenabled = false\n'
            )
            args = Namespace(
                home=fixture.home,
                skills_source=fixture.repo,
                operation_dir=fixture.root / "operation",
                source_mode="canary",
                host_build="test-build",
                approve=None,
            )
            with fixture.constants(), self.assertRaisesRegex(ValueError, "detach"):
                m.preview(args)
            self.assertFalse(args.operation_dir.exists())


class BootstrapRouting(unittest.TestCase):
    def test_explicit_route_exits_before_clone_or_full_reconcile(self):
        with tempfile.TemporaryDirectory(prefix="int008-bootstrap-") as raw:
            root = Path(raw).resolve()
            dev = root / "dev"
            script = dev / "capabilities/bootstrap.sh"
            script.parent.mkdir(parents=True)
            shutil.copyfile(m.ROOT / "capabilities/bootstrap.sh", script)
            migration = dev / "_ops/interoperability/skill_migration.py"
            migration.parent.mkdir(parents=True)
            migration.write_text(
                "import json,sys\nprint(json.dumps({'route': sys.argv[1], 'args': sys.argv[2:]}))\n"
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            git_marker = root / "git-invoked"
            fake_git = fake_bin / "git"
            fake_git.write_text(f'#!/bin/sh\ntouch "{git_marker}"\nexit 99\n')
            fake_git.chmod(0o755)
            env = {
                **os.environ,
                "HOME": str(root / "home"),
                "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
            }
            result = subprocess.run(
                [
                    "bash",
                    str(script),
                    "--codex-skill-migration",
                    "verify",
                    "--operation-dir",
                    str(root / "operation"),
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["route"], "verify")
            self.assertFalse(git_marker.exists(), "full bootstrap/clone path invoked git")
            self.assertFalse((dev / "capabilities/skills").exists())


class CurrentBuildAndPinnedRetention(unittest.TestCase):
    @contextmanager
    def pinned_fixture(self):
        with tempfile.TemporaryDirectory(prefix="int008-pinned-") as raw:
            f = SourceRepositoryFixture(Path(raw).resolve())
            manifest = f.root / "portability.json"
            manifest.write_text(json.dumps({
                "schema": "personal-portability/manifest/v1", "profile": "personal-codex",
                "repositories": [{"id": "KleinPerkins/skills", "path": "capabilities/skills",
                                  "revision": f.commit, "disposition": "source-only", "required": True}],
            }) + "\n")
            # Preserve the reviewed detached source while origin/main advances.
            descendant = run("git", "commit-tree", f.tree, "-p", f.commit,
                             cwd=f.repo, input_text="remote descendant\n")
            run("git", "update-ref", "refs/remotes/origin/main", descendant, cwd=f.repo)
            run("git", "checkout", "-q", "--detach", f.commit, cwd=f.repo)
            args = Namespace(home=f.home, skills_source=f.repo, operation_dir=f.root / "operation",
                             source_mode="pinned-retained", host_build="test-build", approve=None,
                             portability_manifest=manifest)
            with f.constants(), patch.object(m, "PORTABILITY_SKILLS_REVISION", f.commit), \
                    patch.object(m, "PORTABILITY_MANIFEST_SHA256", m.sha(manifest.read_bytes())):
                yield Namespace(source=f, args=args, manifest=manifest, remote=descendant)

    def test_pinned_retained_roundtrip_preserves_pin_and_origin(self):
        with self.pinned_fixture() as f:
            result = m.preview(f.args)
            f.args.approve = result["action_sha256"]
            record, _ = m.load_operation(f.args.operation_dir)
            self.assertTrue(record["retained_installation"])
            self.assertTrue(record["source_proof"]["primary"]["approved_pinned_payload"])
            self.assertFalse(record["source_proof"]["primary"]["current_merged_payload"])
            self.assertEqual(m.apply_operation(f.args)["status"], "applied")
            self.assertEqual(m.verify_operation(f.args)["status"], "verified-applied")
            self.assertEqual(m.apply_operation(f.args)["status"], "already-applied")
            self.assertEqual(run("git", "rev-parse", "HEAD", cwd=f.source.repo), f.source.commit)
            self.assertEqual(run("git", "branch", "--show-current", cwd=f.source.repo), "")
            self.assertEqual(run("git", "rev-parse", "origin/main", cwd=f.source.repo), f.remote)
            self.assertEqual(run("git", "status", "--porcelain", cwd=f.source.repo), "")
            for name in m.SKILLS:
                self.assertEqual(os.readlink(f.source.home / ".codex/skills" / name),
                                 str(f.source.repo / "global/skills" / name))
            self.assertEqual(m.apply_operation(f.args, rollback=True)["status"], "rolled-back")
            self.assertEqual(m.verify_operation(f.args)["status"], "verified-preimage")

    def test_manifest_required_and_not_accepted_by_other_modes(self):
        with self.pinned_fixture() as f:
            f.args.portability_manifest = None
            with self.assertRaisesRegex(ValueError, "requires --portability-manifest"):
                m.preview(f.args)
            f.args.portability_manifest = f.manifest
            f.args.source_mode = "retained"
            with self.assertRaisesRegex(ValueError, "only valid with pinned-retained"):
                m.preview(f.args)
            self.assertFalse(f.args.operation_dir.exists())

    def test_cli_requires_explicit_pinned_mode_and_manifest(self):
        with self.pinned_fixture() as f:
            output = io.StringIO()
            with redirect_stdout(output):
                code = m.main(["preview", "--home", str(f.source.home),
                               "--skills-source", str(f.source.repo),
                               "--operation-dir", str(f.args.operation_dir),
                               "--host-build", "test-build", "--source-mode", "pinned-retained",
                               "--portability-manifest", str(f.manifest)])
            self.assertEqual(code, 0, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["source_mode"], "pinned-retained")
            record, _ = m.load_operation(f.args.operation_dir)
            self.assertEqual(record["source_proof"]["portability_manifest"]["manifest_sha256"],
                             m.sha(f.manifest.read_bytes()))

    def test_manifest_drift_before_apply_preserves_all_preimages(self):
        with self.pinned_fixture() as f:
            result = m.preview(f.args)
            f.args.approve = result["action_sha256"]
            f.manifest.write_bytes(f.manifest.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "exact approved portability manifest"):
                m.apply_operation(f.args)
            for name in m.SKILLS:
                self.assertTrue((f.source.home / ".agents/skills" / name).is_symlink())
                self.assertFalse((f.source.home / ".codex/skills" / name).exists())

    def test_wrong_pin_and_attached_pin_are_refused(self):
        for kind in ("different-detached-head", "attached-approved-head"):
            with self.subTest(kind=kind), self.pinned_fixture() as f:
                if kind == "different-detached-head":
                    run("git", "checkout", "-q", "--detach", f.remote, cwd=f.source.repo)
                else:
                    run("git", "checkout", "-q", "main", cwd=f.source.repo)
                with self.assertRaisesRegex(ValueError, "exact clean detached approved"):
                    m.preview(f.args)
                self.assertFalse(f.args.operation_dir.exists())

    def test_pin_change_after_preview_refuses_apply_before_mutation(self):
        with self.pinned_fixture() as f:
            result = m.preview(f.args)
            f.args.approve = result["action_sha256"]
            run("git", "checkout", "-q", "--detach", f.remote, cwd=f.source.repo)
            with self.assertRaisesRegex(ValueError, "exact clean detached approved"):
                m.apply_operation(f.args)
            for name in m.SKILLS:
                self.assertTrue((f.source.home / ".agents/skills" / name).is_symlink())
                self.assertFalse((f.source.home / ".codex/skills" / name).exists())

    def test_dirty_pin_is_refused_without_replacing_user_file(self):
        with self.pinned_fixture() as f:
            user_file = f.source.repo / "untracked-user-work"
            user_file.write_text("preserve me")
            with self.assertRaisesRegex(ValueError, "must be clean"):
                m.preview(f.args)
            self.assertEqual(user_file.read_text(), "preserve me")
            self.assertFalse(f.args.operation_dir.exists())

    def test_manifest_symlink_and_hardlink_are_refused(self):
        for kind in ("symlink", "hardlink"):
            with self.subTest(kind=kind), self.pinned_fixture() as f:
                alias = f.source.root / "alias.json"
                if kind == "symlink": alias.symlink_to(f.manifest)
                else: os.link(f.manifest, alias)
                f.args.portability_manifest = alias
                with self.assertRaises(ValueError): m.preview(f.args)
                self.assertFalse(f.args.operation_dir.exists())

    def test_default_retained_does_not_inherit_pinned_exception(self):
        with self.pinned_fixture() as f:
            with self.assertRaisesRegex(ValueError, "stale"):
                m.primary_observation(f.source.home, require_current=True)

    def test_manifest_semantic_binding_is_checked_after_digest(self):
        with self.pinned_fixture() as f:
            data = json.loads(f.manifest.read_text())
            data["repositories"][0]["required"] = False
            f.manifest.write_text(json.dumps(data))
            with patch.object(m, "PORTABILITY_MANIFEST_SHA256", m.sha(f.manifest.read_bytes())):
                with self.assertRaisesRegex(ValueError, "source binding is inconsistent"):
                    m.preview(f.args)

    def test_unknown_build_cannot_reuse_old_proof(self):
        with self.pinned_fixture() as f:
            with self.assertRaisesRegex(ValueError, "exact merged.*proof"):
                m.validate_qualification(f.source.repo, "unqualified-build")

    def test_new_build_selects_immutable_separate_evidence(self):
        with self.pinned_fixture() as f:
            rows = json.loads((f.source.repo / m.EVIDENCE_PATH).read_text())
            for row in rows: row["host_build"] = "test-new-build"
            path = "docs/evidence/new-build.json"
            (f.source.repo / path).write_text(json.dumps(rows))
            run("git", "add", path, cwd=f.source.repo)
            run("git", "commit", "-qm", "new-build evidence", cwd=f.source.repo)
            revision = run("git", "rev-parse", "HEAD", cwd=f.source.repo)
            with patch.dict(m.ADDITIONAL_QUALIFICATIONS, {"test-new-build": {"revision": revision, "path": path}}, clear=True):
                proof = m.validate_qualification(f.source.repo, "test-new-build")
                self.assertEqual(proof["revision"], revision)
                self.assertEqual(proof["path"], path)
                self.assertEqual(m.validate_qualification(f.source.repo, "test-build")["revision"], f.source.commit)
                rows[0]["payload_sha256"] = "0" * 64
                (f.source.repo / path).write_text(json.dumps(rows))
                run("git", "add", path, cwd=f.source.repo)
                run("git", "commit", "-qm", "mismatched evidence", cwd=f.source.repo)
                wrong = run("git", "rev-parse", "HEAD", cwd=f.source.repo)
                with patch.dict(m.ADDITIONAL_QUALIFICATIONS, {"test-new-build": {"revision": wrong, "path": path}}, clear=True):
                    with self.assertRaisesRegex(ValueError, "stale or mismatched"):
                        m.validate_qualification(f.source.repo, "test-new-build")


if __name__ == "__main__":
    unittest.main()
