import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location("personal_package", Path(__file__).with_name("package.py"))
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


sys.path.insert(0, str(Path(__file__).resolve().parent))
import personal_core


class PersonalCoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.codex = self.home / ".codex"
        self.slot = self.codex / "skills/capability"
        self.release = self.home / ".local/share/personal-portability/releases" / (
            "capability-" + personal_core.REVISION) / "capability"
        self.payload = {name: f"fixture {name}".encode() for name in personal_core.FILES}
        files = {name: (len(raw), hashlib.sha256(raw).hexdigest(), name == "install.sh")
                 for name, raw in self.payload.items()}
        self.addCleanup(patch.stopall)
        patch.object(personal_core, "FILES", files).start()
        self.fetch = patch.object(personal_core, "fetch_file",
                                  side_effect=lambda name, length: self.payload[name]).start()

    def run_action(self, action):
        return personal_core.configure(self.home, self.codex, action)

    def test_clean_configuration_repeat_offline_and_recovery(self):
        with self.assertRaises(ValueError):
            self.run_action("check")
        self.assertFalse(self.codex.exists())
        self.run_action("install")
        self.assertEqual(self.fetch.call_count, 3)
        self.assertEqual(self.slot.resolve(), self.release)
        before = self.slot.lstat()
        self.run_action("install")
        self.run_action("check")
        self.assertTrue(os.path.samestat(before, self.slot.lstat()))
        self.run_action("withdraw")
        self.run_action("withdraw")
        self.assertFalse(os.path.lexists(self.slot))
        self.run_action("install")
        self.assertEqual(self.fetch.call_count, 3)
        self.assertEqual((self.slot / "SKILL.md").read_bytes(), self.payload["SKILL.md"])

    def test_occupied_and_replaced_entries_are_preserved(self):
        self.slot.mkdir(parents=True)
        with self.assertRaises(ValueError):
            self.run_action("install")
        self.assertEqual(self.fetch.call_count, 0)
        self.slot.rmdir()
        self.run_action("install")
        self.slot.unlink()
        self.slot.symlink_to(self.release)
        self.run_action("install")
        with self.assertRaises(ValueError):
            self.run_action("withdraw")
        self.assertTrue(self.slot.is_symlink())

    def test_failed_download_and_modified_existing_release(self):
        self.fetch.side_effect = lambda name, length: b"wrong"
        with self.assertRaises(ValueError):
            self.run_action("install")
        self.assertFalse(self.release.parent.exists())
        self.assertFalse(os.path.lexists(self.slot))
        self.fetch.side_effect = lambda name, length: self.payload[name]
        self.run_action("install")
        (self.release / "meta.yml").write_text("changed")
        for action in ("install", "check"):
            with self.assertRaises(ValueError):
                self.run_action(action)
        self.assertEqual((self.release / "meta.yml").read_text(), "changed")

    def test_interrupted_withdrawal_and_alternative_home(self):
        self.codex = self.home / "selected" / "codex"
        self.slot = self.codex / "skills/capability"
        self.run_action("install")
        control = self.codex / "dev-personal-core"
        pending = control / "withdrawals/withdraw-fixture"
        pending.mkdir(parents=True)
        os.link(control / "capability", pending / "witness", follow_symlinks=False)
        self.slot.rename(pending / "entry")
        self.run_action("withdraw")
        self.assertFalse(os.path.lexists(self.slot))
        self.assertFalse((self.home / ".codex").exists())
        self.run_action("install")
        self.run_action("check")

    def test_release_modes_admit_git_and_private_files_only(self):
        self.run_action("install")
        script = self.release / "install.sh"
        descriptor = self.release / "SKILL.md"
        for script_mode, descriptor_mode in ((0o755, 0o644), (0o700, 0o600)):
            script.chmod(script_mode)
            descriptor.chmod(descriptor_mode)
            self.run_action("check")
        for path, mode in ((script, 0o777), (script, 0o1755), (descriptor, 0o666)):
            old_mode = path.stat().st_mode & 0o7777
            path.chmod(mode)
            with self.subTest(mode=oct(mode)), self.assertRaises(ValueError):
                self.run_action("check")
            path.chmod(old_mode)

    def test_concurrent_slot_substitutions_have_recoverable_paths(self):
        self.run_action("install")
        history = self.codex / "dev-personal-core/withdrawals"
        rename = personal_core._rename_noreplace

        def race(src, dst):
            if src == self.slot:
                self.slot.unlink()
                self.slot.mkdir()
                (self.slot / "draft").write_text("first writer")
                rename(src, dst)
                self.slot.write_text("second writer")
            else:
                rename(src, dst)

        with patch.object(personal_core, "_rename_noreplace", side_effect=race):
            with self.assertRaisesRegex(ValueError, str(history)):
                self.run_action("withdraw")
        parked, = history.glob("withdraw-*/entry")
        self.assertEqual(self.slot.read_text(), "second writer")
        self.assertEqual((parked / "draft").read_text(), "first writer")
        with self.assertRaisesRegex(ValueError, "preserved"):
            self.run_action("withdraw")
        second = self.home / "preserved-second"
        self.slot.rename(second)
        with self.assertRaisesRegex(ValueError, "Restored"):
            self.run_action("withdraw")
        self.assertEqual((self.slot / "draft").read_text(), "first writer")
        self.assertEqual(second.read_text(), "second writer")
        self.assertFalse(parked.exists())

    def test_replacements_after_the_last_identity_check_are_never_unlinked(self):
        self.run_action("install")
        check = personal_core.owns_slot

        def substitute(slot, witness, release):
            matches = check(slot, witness, release)
            if matches and slot.name == "entry":
                slot.unlink()
                slot.write_text("replaced capture")
                witness.unlink()
                witness.write_text("replaced witness")
            return matches

        with patch.object(personal_core, "owns_slot", side_effect=substitute):
            self.run_action("withdraw")
        operation, = (self.codex / "dev-personal-core/withdrawals").iterdir()
        self.assertFalse(os.path.lexists(self.slot))
        self.assertEqual((operation / "entry").read_text(), "replaced capture")
        self.assertEqual((operation / "witness").read_text(), "replaced witness")
        self.run_action("install")
        self.assertEqual((operation / "entry").read_text(), "replaced capture")
        self.assertEqual((operation / "witness").read_text(), "replaced witness")

    def test_unowned_recovery_path_stays_in_place(self):
        self.run_action("install")
        parked = self.codex / "dev-personal-core/withdrawals/withdraw-foreign/entry"
        parked.parent.mkdir(parents=True)
        parked.write_text("other operation")
        with self.assertRaisesRegex(ValueError, "unowned withdrawal record"):
            self.run_action("withdraw")
        self.assertTrue(self.slot.is_symlink())
        self.assertEqual(parked.read_text(), "other operation")

    def test_release_link_or_discovery_parent_alias_is_refused(self):
        self.slot.parent.parent.mkdir(parents=True)
        peer = self.home / "peer"
        peer.mkdir()
        self.slot.parent.symlink_to(peer)
        with self.assertRaises(ValueError):
            self.run_action("install")
        self.assertEqual(list(peer.iterdir()), [])
        self.slot.parent.unlink()
        self.release.parent.mkdir(parents=True)
        self.release.symlink_to(peer)
        with self.assertRaises(ValueError):
            self.run_action("install")
        self.assertFalse(os.path.lexists(self.slot))


class StandardDevSkillTests(unittest.TestCase):
    def setUp(self):
        import subprocess
        import personal_dev_skills as dev

        self.home_context = tempfile.TemporaryDirectory()
        self.addCleanup(self.home_context.cleanup)
        self.home = Path(self.home_context.name).resolve()
        self.codex = self.home / "selected-codex"
        self.source = self.home / "source"
        self.source.mkdir()
        git = ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
               "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false"]
        git_env = dev.GitRunner()._environment()

        def run(*args):
            return subprocess.check_output([*git, *args], cwd=self.source, env=git_env, text=True).strip()

        run("init", "--quiet", "--template=")
        releases = {}
        for name in ("dev-doctor", "dev-new-repo"):
            key = f"_ops/skills/personal/{name}/SKILL.md"
            file = self.source / key
            file.parent.mkdir(parents=True)
            payload = f"---\nname: {name}\n---\n".encode()
            file.write_bytes(payload)
            run("add", "--", key)
            run("commit", "--quiet", "-m", name)
            releases[name] = {"revision": run("rev-parse", "HEAD"),
                              "files": {key: ["100644", len(payload), hashlib.sha256(payload).hexdigest()]}}
        self.addCleanup(patch.stopall)
        patch.object(dev, "DEV_SOURCE", self.source).start()
        patch.object(dev, "RELEASES", releases).start()
        core = b"fixture core"
        patch.object(personal_core, "FILES", {"SKILL.md": (len(core), hashlib.sha256(core).hexdigest(), False)}).start()
        self.download = patch.object(personal_core, "fetch_file", return_value=core).start()
        self.bundles = {name: dev.DevSkillRelease(name, self.home) for name in releases}
        self.slots = self.codex / "skills"

    def configure(self, action):
        return personal_core.configure_profile(self.home, self.codex, action)

    def test_clean_profile_repeat_withdraw_and_offline_reinstall(self):
        self.configure("install")
        self.assertEqual(sorted(p.name for p in self.slots.iterdir()), ["capability", "dev-doctor", "dev-new-repo"])
        originals = {p.name: p.lstat() for p in self.slots.iterdir()}
        self.configure("check")
        self.configure("install")
        self.assertTrue(all(os.path.samestat(info, (self.slots / name).lstat()) for name, info in originals.items()))
        # Each sparse checkout contains its own runtime, even if the commit also contains the other one.
        creator = self.bundles["dev-new-repo"]
        self.assertFalse(creator.skill.with_name("dev-doctor").exists())
        self.configure("withdraw")
        self.assertEqual(list(self.slots.iterdir()), [])
        self.source.rename(self.home / "source-offline")
        self.configure("install")
        self.configure("check")
        self.assertEqual(self.download.call_count, 1)
        self.assertFalse((self.home / ".cursor").exists())

    def test_published_runtime_protects_its_top_level_directory(self):
        self.configure("install")
        for bundle in self.bundles.values():
            with self.subTest(skill=bundle.name):
                self.assertEqual(bundle.root.stat().st_mode & 0o777, 0o500)
                if os.geteuid() != 0:
                    with self.assertRaises(PermissionError):
                        (bundle.root / "_ops").rename(bundle.root / "replaced")
                bundle.verify()

    def test_preexisting_doctor_export_is_checked_and_preserved(self):
        import shutil
        doctor = self.bundles["dev-doctor"]
        doctor.prepare()
        doctor.root.chmod(0o700)  # Recreate the earlier standalone export.
        shutil.rmtree(doctor.root / ".git")
        self.slots.mkdir(parents=True)
        slot = self.slots / doctor.name
        slot.symlink_to(doctor.skill)
        original = slot.lstat()
        self.configure("install")
        self.configure("check")
        self.configure("withdraw")
        self.assertEqual(list(self.slots.iterdir()), [slot])
        self.assertTrue(os.path.samestat(original, slot.lstat()))

    def test_foreign_last_slot_stops_before_new_entries_are_published(self):
        self.slots.mkdir(parents=True)
        occupant = self.slots / "dev-new-repo"
        occupant.write_text("other installer")
        with self.assertRaisesRegex(ValueError, "occupied"):
            self.configure("install")
        self.assertEqual(list(self.slots.iterdir()), [occupant])
        self.assertEqual(occupant.read_text(), "other installer")
        self.download.assert_not_called()

    def test_runtime_or_authority_drift_stops_before_publication(self):
        creator = self.bundles["dev-new-repo"]
        creator.prepare()
        metadata = creator.root / ".git"
        creator.root.chmod(0o700)  # Simulate a separately modified installation.
        metadata.rename(self.home / "saved-metadata")
        with self.assertRaisesRegex(ValueError, "authority"):
            self.configure("install")
        self.assertFalse(self.slots.exists())
        (self.home / "saved-metadata").rename(metadata)
        file = creator.skill / "SKILL.md"
        file.chmod(0o600)
        data = file.read_bytes()
        file.write_bytes(data[:-1] + b"x")
        with self.assertRaisesRegex(ValueError, "differs"):
            self.configure("install")
        self.assertFalse(self.slots.exists())
        file.write_bytes(data)
        self.configure("install")

    def test_changed_entry_preserved_while_other_owned_entries_are_withdrawn(self):
        self.configure("install")
        picked = self.slots / "dev-doctor"
        picked.unlink()
        picked.write_text("replacement")
        with self.assertRaisesRegex(ValueError, "dev-doctor"):
            self.configure("withdraw")
        self.assertEqual(list(self.slots.iterdir()), [picked])
        self.assertEqual(picked.read_text(), "replacement")


class PackageTests(unittest.TestCase):
    def payload(self):
        result = {name: b"safe fixture\n" for name in package.PAYLOAD}
        result["manifest.json"] = Path(__file__).with_name("manifest.json").read_bytes()
        result["DESTINATION-PROMPT.txt"] = b"source @@SOURCE_REVISION@@\n"
        result["START-HERE.md"] = b"source @@SOURCE_REVISION@@\n"
        return result

    def test_deterministic_closed_archive_and_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            one, two = Path(directory).resolve() / "one.zip", Path(directory).resolve() / "two.zip"
            package.build(self.payload(), "b" * 40, one)
            package.build(self.payload(), "b" * 40, two)
            self.assertEqual(one.read_bytes(), two.read_bytes())
            with zipfile.ZipFile(one) as archive:
                names = archive.namelist()
                self.assertEqual(len(names), len(package.PAYLOAD) + 2)
                self.assertTrue(all(n.startswith("personal-bootstrap/") for n in names))
                hashes = archive.read("personal-bootstrap/SHA256SUMS").decode().splitlines()
                for row in hashes:
                    digest, name = row.split("  ", 1)
                    self.assertEqual(hashlib.sha256(archive.read("personal-bootstrap/" + name)).hexdigest(), digest)
                prompt = archive.read("personal-bootstrap/DESTINATION-PROMPT.txt")
                self.assertNotIn(b"@@", prompt)
                self.assertIn(b"b" * 40, prompt)
                provenance = json.loads(archive.read("personal-bootstrap/PROVENANCE.json"))
                self.assertEqual(provenance["source_blob_sha256"]["DESTINATION-PROMPT.txt"],
                                 hashlib.sha256(self.payload()["DESTINATION-PROMPT.txt"]).hexdigest())
                self.assertEqual(len(provenance["transformations"]), 3)

    def test_unknown_file_and_existing_output_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory).resolve() / "kit.zip"
            files = self.payload()
            files["auth.json"] = b"must not export"
            with self.assertRaises(ValueError):
                package.build(files, "a" * 40, dest)
            self.assertFalse(dest.exists())
            dest.write_bytes(b"user data")
            with self.assertRaises(ValueError):
                package.build(self.payload(), "a" * 40, dest)
            self.assertEqual(dest.read_bytes(), b"user data")

    def test_mixed_source_cannot_be_changed_to_clone(self):
        files = self.payload()
        manifest = json.loads(files["manifest.json"])
        manifest["repositories"][0]["disposition"] = "clone"
        files["manifest.json"] = json.dumps(manifest).encode()
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            package.build(files, "a" * 40, Path(directory).resolve() / "kit.zip")

    def test_collect_uses_merged_objects_and_excludes_working_changes(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            def git(*args):
                return subprocess.check_output(
                    ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=Fixture",
                     "-c", "user.email=fixture@example.invalid", "-C", str(root), *args],
                    stderr=subprocess.DEVNULL,
                ).decode().strip()
            git("init", "-b", "main")
            git("remote", "add", "origin", "https://github.com/KleinPerkins/dev.git")
            source = root / package.PREFIX
            source.mkdir(parents=True)
            expected = self.payload()
            for name, data in expected.items():
                (source / name).write_bytes(data)
            git("add", ".")
            git("commit", "-m", "fixture source")
            merged = git("rev-parse", "HEAD")
            original_git = package.git
            def isolated_git(path, *args):
                if args and args[0] == "fetch":
                    args = tuple(str(root) if arg == package.CANONICAL_REMOTE else arg for arg in args)
                return original_git(path, *args)
            with patch.object(package, "git", side_effect=isolated_git):
                (source / "engine.py").write_bytes(b"uncommitted data must stay local")
                (source / "auth.json").write_bytes(b"excluded private fixture")
                self.assertEqual(package.collect(root, merged), expected)
                git("switch", "-c", "unmerged")
                git("add", "_ops/portability/engine.py")
                git("commit", "-m", "unmerged fixture")
                unmerged = git("rev-parse", "HEAD")
                with self.assertRaises(ValueError):
                    package.collect(root, unmerged)
                git("remote", "set-url", "origin", "https://github.com/foreign/source.git")
                with self.assertRaises(ValueError):
                    package.collect(root, merged)

    def test_checked_in_manifest_boundaries_and_payload_size_limit(self):
        files = self.payload()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            package.build(files, "a" * 40, root / "valid.zip")
            for repository in ("KleinPerkins/dev", "KleinPerkins/chaos-labs", "KleinPerkins/chaos-scheduler"):
                manifest = json.loads(files["manifest.json"])
                next(row for row in manifest["repositories"] if row["id"] == repository)["required"] = False
                invalid = {**files, "manifest.json": json.dumps(manifest).encode()}
                with self.assertRaises(ValueError):
                    package.build(invalid, "a" * 40, root / "invalid.zip")
            with self.assertRaises(ValueError):
                package.build({**files, "engine.py": b"x" * (package.MAX_FILE_BYTES + 1)}, "a" * 40, root / "large.zip")
            duplicate = files["manifest.json"].replace(b'"schema":', b'"schema":"invalid","schema":', 1)
            with self.assertRaises(ValueError):
                package.build({**files, "manifest.json": duplicate}, "a" * 40, root / "duplicate.zip")
            with self.assertRaises(ValueError):
                package.build({**files, "START-HERE.md": b"missing source token"}, "a" * 40, root / "token.zip")

    def test_symlink_output_parent_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            real = root / "real"
            real.mkdir()
            alias = root / "alias"
            alias.symlink_to(real, target_is_directory=True)
            with self.assertRaises(ValueError):
                package.build(self.payload(), "a" * 40, alias / "kit.zip")
            self.assertFalse((real / "kit.zip").exists())

    def test_no_legacy_bootstrap_dispatch(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bootstrap.sh").write_bytes(Path(__file__).resolve().parents[2].joinpath("bootstrap.sh").read_bytes())
            target = root / "_ops/portability"
            target.mkdir(parents=True)
            (target / "engine.py").write_text("import sys; print('PERSONAL_ONLY'); sys.exit(19)\n")
            run = subprocess.run(["bash", str(root / "bootstrap.sh"), "--profile", "personal-codex", "plan"], capture_output=True, text=True)
            self.assertEqual(run.returncode, 19)
            self.assertEqual(run.stdout.strip(), "PERSONAL_ONLY")
            self.assertNotIn("1/8", run.stdout)
            for args in (["--profile", "unknown"], ["--profile=personal-codex"], ["personal-codex"], ["--profile"]):
                unknown = subprocess.run(["bash", str(root / "bootstrap.sh"), *args], capture_output=True, text=True)
                self.assertEqual(unknown.returncode, 2)
                self.assertNotIn("1/8", unknown.stdout)


if __name__ == "__main__":
    unittest.main()
