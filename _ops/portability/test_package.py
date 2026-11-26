import hashlib
import io
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location("personal_package", Path(__file__).with_name("package.py"))
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


sys.path.insert(0, str(Path(__file__).resolve().parent))
import personal_core
import personal_index_package


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


class SaveGameReleaseTests(unittest.TestCase):
    def test_standard_engine_matches_doc_warden_pin(self):
        pin_path = Path(__file__).resolve().parents[1] / "doc-warden/runtime/save-game-pin.json"
        pin = json.loads(pin_path.read_bytes())
        release = personal_core.SAVE_GAME_RELEASE
        self.assertEqual(release["revision"], pin["revision"])
        files = release["skills"]["save-game"]
        runtime = {name: "sha256:" + digest for name, (_, _, digest) in files.items()
                   if name == "scripts/save-game.sh" or Path(name).match("engine/*.py")
                   or Path(name).match("engine/schemas/*.schema.json")}
        self.assertEqual(runtime, pin["files"])


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
        for name in ("dev-doctor", "dev-new-repo", "dev-remove-repo"):
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
        published = personal_core.DESIGN_RELEASE
        public = f"https://raw.githubusercontent.com/KleinPerkins/skills/{published['revision']}/global/"
        self.notice = published["notice"]["name"]
        responses = {public + self.notice: b"fixture notice"}
        notice = {"name": self.notice, "length": 14, "sha256": hashlib.sha256(b"fixture notice").hexdigest()}
        for variable in ("DESIGN_RELEASE", "AUTHORING_RELEASE", "PR_STEWARD_RELEASE",
                         "SAVE_GAME_RELEASE", "LOCAL_JOBS_RELEASE"):
            release = dict(getattr(personal_core, variable))
            if "notice" in release:
                release["notice"] = notice
            skills = {}
            source = f"https://raw.githubusercontent.com/KleinPerkins/skills/{release['revision']}/global/"
            for name, files in release["skills"].items():
                skills[name] = {}
                for relative, (mode, _, _) in files.items():
                    key = f"skills/{name}/{relative}"
                    data = key.encode()
                    responses[source + key] = data
                    skills[name][relative] = [mode, len(data), hashlib.sha256(data).hexdigest()]
            if variable == "LOCAL_JOBS_RELEASE":
                runtime = {"yaml/__init__.py": b'__version__ = "6.0.3"\ndef safe_load(s): return {"active": True}\n',
                           "PyYAML-LICENSE.txt": b"fixture license"}
                archive = io.BytesIO()
                with tarfile.open(fileobj=archive, mode="w:gz") as tar:
                    for name, data in runtime.items():
                        source = "LICENSE" if name == "PyYAML-LICENSE.txt" else "lib/" + name
                        member = tarfile.TarInfo("pyyaml-6.0.3/" + source)
                        member.size = len(data)
                        tar.addfile(member, io.BytesIO(data))
                raw = archive.getvalue()
                responses["fixture://pyyaml"] = raw
                release["pyyaml"] = {
                    "archive": "fixture://pyyaml", "length": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                    "independent_native": {}, "files": {
                        name: ["100644", len(data), hashlib.sha256(data).hexdigest()]
                        for name, data in runtime.items()}}
            patch.object(personal_core, variable, dict(release, skills=skills)).start()
        # Model the separate Skills installer and its one locked npm package.
        iso = personal_core.ISOKIT_RELEASE
        url = f"https://raw.githubusercontent.com/KleinPerkins/skills/{iso['revision']}/local/skills/isokit/"
        key = "node_modules/playwright-core"
        metadata = {"version": "1.64.1", "resolved": "fixture", "integrity": "fixture",
                    "bin": {"playwright-core": "cli.js"}}
        lock = json.dumps({"packages": {key: metadata}}).encode()
        self.iso_source = {"SKILL.md": b"# IsoKit", "install.sh": b"fixture", "package-lock.json": lock}
        runtime = {"cli.js": b"export const chromium = {launch() {}};",
                   "package.json": b'{"name":"playwright-core","type":"module","main":"cli.js"}'}
        def manifest(contents, executable):
            return {path: ["100755" if path == executable else "100644", len(data), hashlib.sha256(data).hexdigest()]
                    for path, data in contents.items()}
        for path, data in self.iso_source.items():
            responses[url + path] = data
        patch.object(personal_core, "ISOKIT_RELEASE",
                     {"revision": iso["revision"], "skills": {"isokit": manifest(self.iso_source, "install.sh")},
                      "runtime": manifest(runtime, "cli.js")}).start()

        def provision(directory):
            modules = directory / "node_modules"
            commands = modules / ".bin"
            commands.mkdir(parents=True)
            (commands / "playwright-core").symlink_to("../playwright-core/cli.js")
            (modules / ".package-lock.json").write_bytes(lock)
            (modules / "playwright-core").mkdir()
            for relative, data in runtime.items():
                path = modules / "playwright-core" / relative
                path.write_bytes(data)
                path.chmod(0o755 if relative == "cli.js" else 0o644)
        self.provision = patch.object(personal_core, "provision_isokit", side_effect=provision).start()
        index = personal_index_package.RELEASE
        index_url = ("https://raw.githubusercontent.com/KleinPerkins/skills/"
                     f"{index['revision']}/global/tools/ecosystem-index/")
        index_files = {}
        for name in index["index_files"]:
            data = b"# fixture runtime\n"
            responses[index_url + name] = data
            index_files[name] = ["100644", len(data), hashlib.sha256(data).hexdigest()]
        fixture_parser = personal_core.LOCAL_JOBS_RELEASE["pyyaml"]
        patch.object(personal_index_package, "RELEASE", {
            "revision": index["revision"], "index_files": index_files, "pyyaml": fixture_parser,
        }).start()
        self.design_read = patch.object(personal_core, "read_url", side_effect=lambda url, length: responses[url]).start()
        self.bundles = {name: dev.DevSkillRelease(name, self.home) for name in releases}
        self.slots = self.codex / "skills"

    def configure(self, action):
        return personal_core.configure_profile(self.home, self.codex, action)

    def test_retirement_inspection_keeps_a_sealed_release(self):
        self.configure("install")
        self.configure("check")
        retirement = self.bundles["dev-remove-repo"]
        slot = self.slots / "dev-remove-repo"
        before = slot.lstat()
        self.assertEqual(slot.readlink(), retirement.skill)
        retirement.root.chmod(0o700)
        with self.assertRaisesRegex(ValueError, "dev-remove-repo requires sealed runtime directories"):
            self.configure("check")
        self.assertTrue(os.path.samestat(slot.lstat(), before))

    def test_index_runtime_uses_owned_profile_slot_and_restores_offline(self):
        entry = personal_core.index_runtime_entry(self.home, self.codex)
        self.assertFalse(self.codex.exists())
        self.configure("install")
        self.configure("check")
        self.assertNotIn(entry.slot.name, {p.name for p in self.slots.iterdir()})
        self.assertTrue(personal_core.owns_slot(entry.slot, entry.control / entry.slot.name, entry.release))
        ordinary_slots = {p.name: p.lstat().st_ino for p in self.slots.iterdir()}
        entry.slot.unlink()
        entry.slot.symlink_to(entry.release)
        foreign = entry.slot.lstat()
        with self.assertRaisesRegex(ValueError, "belongs to another installer"):
            self.configure("install")
        self.assertTrue(os.path.samestat(foreign, entry.slot.lstat()))
        self.assertEqual(ordinary_slots, {p.name: p.lstat().st_ino for p in self.slots.iterdir()})
        entry.slot.unlink()
        os.link(entry.control / entry.slot.name, entry.slot, follow_symlinks=False)
        self.configure("withdraw")
        self.assertFalse(os.path.lexists(entry.slot))
        self.assertTrue(entry.release.is_dir())
        self.design_read.side_effect = AssertionError("offline restore attempted to download")
        self.configure("install")
        self.configure("check")
        self.assertTrue(personal_core.owns_slot(entry.slot, entry.control / entry.slot.name, entry.release))

    def select_new_doctor(self):
        import personal_dev_skills as dev
        previous = dev.RELEASES["dev-doctor"]
        name, = previous["files"]
        new = (self.source / name).read_bytes() + b"New diagnostic\n"
        (self.source / name).write_bytes(new)
        git = ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
               "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false"]
        env = dev.GitRunner()._environment()
        subprocess.run([*git, "commit", "-qm", "Doctor update", "--", name], cwd=self.source, env=env, check=True)
        revision = subprocess.check_output([*git, "rev-parse", "HEAD"], cwd=self.source, env=env, text=True).strip()
        release = {"revision": revision, "previous": previous,
                   "files": {name: ["100644", len(new), hashlib.sha256(new).hexdigest()]}}
        selected = patch.dict(dev.RELEASES, {"dev-doctor": release})
        selected.start()
        self.addCleanup(selected.stop)
        return dev.DevSkillRelease("dev-doctor", self.home)

    def test_upgrade_keeps_old_witness_and_can_resume_or_restore(self):
        import personal_dev_skills as dev
        self.configure("install")
        slot = self.slots / "dev-doctor"
        original = slot.lstat()
        others = {p: p.lstat().st_ino for p in self.slots.iterdir() if p != slot}
        updated = self.select_new_doctor()
        prior_control = self.codex / "dev-personal-core/dev-doctor"
        with self.assertRaisesRegex(ValueError, "does not expose the pinned dev-doctor"):
            self.configure("check")
        self.assertTrue(os.path.samestat(original, slot.lstat()))
        self.assertFalse((prior_control / "withdrawals").exists())

        with patch.object(dev.DevSkillRelease, "prepare", side_effect=OSError("download interrupted")):
            with self.assertRaisesRegex(OSError, "download interrupted"):
                self.configure("install")
        self.assertTrue(os.path.samestat(original, slot.lstat()))
        apply = personal_core.change_entry

        def interrupted(entry, action):
            if action == "install" and entry.release == updated.skill:
                raise OSError("publication interrupted")
            return apply(entry, action)

        with patch.object(personal_core, "change_entry", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "publication interrupted"):
                self.configure("install")
        self.assertFalse(os.path.lexists(slot))
        parked, = (self.codex / "dev-personal-core/dev-doctor/withdrawals").glob("withdraw-*/entry")
        self.assertTrue(os.path.samestat(original, parked.lstat()))
        self.configure("install")
        self.configure("check")
        self.assertEqual(slot.readlink(), updated.skill)
        self.assertEqual(others, {p: p.lstat().st_ino for p in self.slots.iterdir() if p != slot})
        self.configure("withdraw")
        with patch.dict(dev.RELEASES, {"dev-doctor": updated.previous}):
            self.configure("install")
            self.configure("check")
        self.assertTrue(os.path.samestat(original, slot.lstat()))

    def test_upgrade_preserves_independently_installed_previous_doctor(self):
        original = self.bundles["dev-doctor"]
        original.prepare()
        self.slots.mkdir(parents=True)
        slot = self.slots / "dev-doctor"
        slot.symlink_to(original.skill)
        identity = slot.lstat()
        self.select_new_doctor()
        with self.assertRaisesRegex(ValueError, "independently installed earlier dev-doctor preserved"):
            self.configure("install")
        self.assertEqual(list(self.slots.iterdir()), [slot])
        self.configure("withdraw")
        self.assertTrue(os.path.samestat(identity, slot.lstat()))

    def test_profile_check_verifies_the_independently_installed_current_doctor(self):
        updated = self.select_new_doctor()
        updated.prepare()
        self.slots.mkdir(parents=True)
        slot = self.slots / "dev-doctor"
        slot.symlink_to(updated.skill)
        identity = slot.lstat()
        self.configure("install")
        self.configure("check")
        witness = self.codex / "dev-personal-core/dev-doctor/releases" / updated.revision / "dev-doctor"
        self.assertFalse(os.path.lexists(witness))

        relative, = updated.files
        selected = updated.root / relative
        original = selected.read_bytes()
        mode = selected.stat().st_mode & 0o777
        selected.chmod(0o600)
        selected.write_bytes(original + b"Corruption")
        with self.assertRaisesRegex(ValueError, "differs from its released file"):
            self.configure("check")
        self.assertTrue(os.path.samestat(identity, slot.lstat()))

        selected.write_bytes(original)
        selected.chmod(mode)
        self.configure("check")
        self.configure("withdraw")
        self.assertTrue(os.path.samestat(identity, slot.lstat()))
        self.assertFalse(os.path.lexists(witness))

    def test_clean_profile_repeat_withdraw_and_offline_reinstall(self):
        self.configure("install")
        self.assertEqual(sorted(p.name for p in self.slots.iterdir()), [
            "capability", "dev-doctor", "dev-new-repo", "dev-remove-repo", "frontend-design",
            "isokit", "local-jobs", "plan-refine",
            "pr-steward", "prompt-architect",
            "save-game", "verification-before-completion", "web-artifacts-builder"])
        originals = {p.name: p.lstat() for p in self.slots.iterdir()}
        index = personal_core.index_runtime_entry(self.home, self.codex)
        with patch.object(personal_core, "FileLock", side_effect=AssertionError("check acquired a write lock")):
            self.assertEqual(len(self.configure("check")), len(originals) + 1)
        self.assertTrue(index.slot.is_symlink())
        self.assertTrue(all(os.path.samestat(info, (self.slots / name).lstat()) for name, info in originals.items()))
        self.configure("install")
        self.assertTrue(all(os.path.samestat(info, (self.slots / name).lstat()) for name, info in originals.items()))
        # Each sparse checkout contains its own runtime, even if the commit also contains the other one.
        creator = self.bundles["dev-new-repo"]
        self.assertFalse(creator.skill.with_name("dev-doctor").exists())
        self.configure("withdraw")
        self.assertEqual(list(self.slots.iterdir()), [])
        self.source.rename(self.home / "source-offline")
        self.design_read.side_effect = AssertionError("design package fetched on offline reinstall")
        self.configure("install")
        self.configure("check")
        self.assertEqual(self.download.call_count, 1)
        self.assertFalse((self.home / ".cursor").exists())

    def test_profile_preserves_an_independent_pr_steward(self):
        independent = self.home / "independent-pr-steward"
        independent.mkdir()
        descriptor = independent / "SKILL.md"
        descriptor.write_text("Independent operator package")
        self.slots.mkdir(parents=True)
        slot = self.slots / "pr-steward"
        slot.symlink_to(independent)
        before = slot.lstat()

        with self.assertRaisesRegex(ValueError, "pr-steward slot is occupied"):
            self.configure("install")
        self.assertTrue(os.path.samestat(before, slot.lstat()))
        self.assertEqual(list(self.slots.iterdir()), [slot])
        self.assertEqual(descriptor.read_text(), "Independent operator package")

    def test_isokit_preserves_independent_checkout_and_checks_installed_runtime(self):
        self.configure("install")
        slot = self.slots / "isokit"
        release = slot.resolve()
        checkout = self.home / "dev/capabilities/skills/local/skills/isokit"
        checkout.parent.mkdir(parents=True)
        shutil.copytree(release, checkout, symlinks=True)
        slot.unlink()
        slot.symlink_to(checkout)
        original = slot.lstat()
        self.configure("check")
        self.configure("install")
        library = checkout / "node_modules/playwright-core/cli.js"
        library.chmod(0o700)
        library.write_text("changed by its owner")
        with self.assertRaisesRegex(ValueError, "cli.js"):
            self.configure("check")
        self.configure("withdraw")
        self.assertTrue(os.path.samestat(original, slot.lstat()))
        self.assertEqual(library.read_text(), "changed by its owner")
        slot.unlink()
        self.configure("install")
        self.configure("check")
        self.assertEqual(slot.resolve(), release)
        self.assertEqual(self.provision.call_count, 1)

    def test_save_game_preserves_independent_package_and_checkpoint(self):
        self.configure("install")
        slot = self.slots / "save-game"
        revision = personal_core.SAVE_GAME_RELEASE["revision"]
        package = self.home / ".local/share/save-game/source" / revision / "global/skills/save-game"
        package.parent.mkdir(parents=True)
        shutil.copytree(slot.resolve(), package)
        slot.unlink()
        slot.symlink_to(package)
        independent = slot.lstat()
        checkpoint = self.home / ".local/state/save-game/v1/checkpoints/fixture.json"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b"private saved state")
        self.configure("check")
        self.configure("install")
        engine = package / "engine/index.py"
        engine.chmod(0o600)
        engine.write_bytes(b"independent edit")
        with self.assertRaisesRegex(ValueError, "index.py"):
            self.configure("check")
        self.configure("withdraw")
        self.assertTrue(os.path.samestat(independent, slot.lstat()))
        self.assertEqual(engine.read_bytes(), b"independent edit")
        self.assertEqual(checkpoint.read_bytes(), b"private saved state")

    def test_local_jobs_validates_runtime_and_keeps_generated_dashboard_and_job_state(self):
        self.configure("install")
        slot = self.slots / "local-jobs"
        original = slot.lstat()
        canvas = slot / personal_core.personal_local_jobs.CANVAS
        canvas.write_text("my dashboard")
        state = self.home / ".local-jobs/events.jsonl"
        state.parent.mkdir()
        state.write_text("my job history")
        self.configure("check")
        self.configure("withdraw")
        self.design_read.side_effect = AssertionError("offline restore attempted to download")
        self.configure("install")
        self.assertTrue(os.path.samestat(original, slot.lstat()))
        self.assertEqual(canvas.read_text(), "my dashboard")
        self.assertEqual(state.read_text(), "my job history")
        module, = slot.glob("_ops/.venv/lib/python*/site-packages/yaml/__init__.py")
        module.chmod(0o600)
        module.write_text("other code")
        with self.assertRaisesRegex(ValueError, "__init__.py"):
            self.configure("check")

    def test_local_jobs_refuses_a_linked_output_and_preserves_an_independent_install(self):
        self.configure("install")
        slot = self.slots / "local-jobs"
        rev = personal_core.LOCAL_JOBS_RELEASE["revision"]
        checkout = self.home / ".local/share/local-jobs/releases" / rev / "global/skills/local-jobs"
        checkout.parent.mkdir(parents=True)
        shutil.copytree(slot.resolve(), checkout, symlinks=True)
        slot.unlink()
        slot.symlink_to(checkout)
        independent = slot.lstat()
        self.configure("check")
        self.configure("install")
        canvas = slot / personal_core.personal_local_jobs.CANVAS
        canvas.parent.chmod(0o700)
        canvas.unlink()
        canvas.symlink_to(self.home / "private-output")
        with self.assertRaisesRegex(ValueError, "owner-controlled output"):
            self.configure("check")
        self.configure("withdraw")
        self.assertTrue(os.path.samestat(independent, slot.lstat()))
        self.assertFalse((self.home / "private-output").exists())

    def test_local_jobs_checks_independent_bytecode_without_changing_the_installation(self):
        self.configure("install")
        slot = self.slots / "local-jobs"
        revision = personal_core.LOCAL_JOBS_RELEASE["revision"]
        independent = self.home / ".local/share/local-jobs/releases" / revision / "global/skills/local-jobs"
        independent.parent.mkdir(parents=True)
        shutil.copytree(slot.resolve(), independent, symlinks=True)
        slot.unlink()
        slot.symlink_to(independent)
        module, = independent.glob("_ops/.venv/lib/python*/site-packages/yaml/__init__.py")
        module.parent.chmod(0o700)
        interpreter = (independent / "_ops/.venv/bin/python3").resolve()
        for options in ([], ["-O"]):
            subprocess.run([interpreter, "-ISB", *options, "-m", "py_compile", module],
                           check=True, env={"PATH": os.defpath})
        self.configure("check")
        cache, = module.parent.glob("__pycache__/*.opt-1.pyc")
        before = cache.read_bytes()
        cache.chmod(0o600)
        changed = before[:-1] + bytes([before[-1] ^ 1])
        cache.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "pyc"):
            self.configure("check")
        self.assertEqual(cache.read_bytes(), changed)
        self.assertEqual(slot.resolve(), independent)

    def test_isokit_dependency_failure_keeps_new_profile_unexposed(self):
        self.provision.side_effect = ValueError("dependency unavailable")
        with self.assertRaisesRegex(ValueError, "dependency unavailable"):
            self.configure("install")
        self.assertFalse(self.slots.exists())
        self.assertFalse((self.home / ".claude").exists())
        self.assertFalse((self.home / ".cursor").exists())

    def test_checkout_backed_authoring_skills_are_verified_and_preserved(self):
        self.slots.mkdir(parents=True)
        releases = personal_core.AUTHORING_RELEASE
        original = {}
        for name, files in releases["skills"].items():
            checkout = self.home / "dev/capabilities/skills/global/skills" / name
            for relative, (mode, _, _) in files.items():
                file = checkout / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(f"skills/{name}/{relative}".encode())
                file.chmod(0o755 if mode == "100755" else 0o644)
            slot = self.slots / name
            slot.symlink_to(checkout)
            original[name] = slot.lstat()
        self.configure("withdraw")
        self.configure("install")
        self.configure("check")
        for name in original:
            self.assertFalse((self.codex / "dev-personal-core" / name / name).is_symlink())
            self.assertFalse((self.home / ".local/share/personal-portability/releases"
                              / f"{name}-{releases['revision']}").exists())
        altered = self.slots / "prompt-architect/scripts/framework_analyzer.py"
        altered.write_bytes(b"modified independently")
        for action in ("check", "install"):
            with self.assertRaisesRegex(ValueError, "framework_analyzer"):
                self.configure(action)
        self.configure("withdraw")
        self.assertEqual({p.name for p in self.slots.iterdir()}, set(original))
        self.assertTrue(all(os.path.samestat(info, (self.slots / name).lstat()) for name, info in original.items()))
        self.assertEqual(altered.read_bytes(), b"modified independently")

    def test_checkout_replacing_profile_entry_survives_withdrawal_and_offline_restore(self):
        self.configure("install")
        name = "verification-before-completion"
        slot = self.slots / name
        anchor = self.codex / "dev-personal-core" / name / name
        release = slot.resolve()
        original = anchor.lstat()
        self.assertTrue(os.path.samestat(slot.lstat(), original))
        checkout = self.home / "dev/capabilities/skills/global/skills" / name
        checkout.parent.mkdir(parents=True)
        shutil.copytree(release, checkout)
        slot.unlink()
        slot.symlink_to(checkout)
        replacement = slot.lstat()

        for _ in range(2):
            messages = self.configure("withdraw")
            self.assertIn(f"preserved independently installed {name}; verified cached profile release for reuse", messages)
            self.assertTrue(os.path.samestat(slot.lstat(), replacement))
            self.assertTrue(os.path.samestat(anchor.lstat(), original))

        saved = anchor.with_name("saved-witness")
        anchor.rename(saved)
        anchor.symlink_to(checkout)
        with self.assertRaisesRegex(ValueError, "ownership record changed"):
            self.configure("withdraw")
        self.assertTrue(os.path.samestat(slot.lstat(), replacement))
        anchor.unlink()
        saved.rename(anchor)
        file = release / "SKILL.md"
        raw = file.read_bytes()
        file.chmod(0o600)
        file.write_bytes(b"changed release")
        with self.assertRaisesRegex(ValueError, "SKILL.md"):
            self.configure("withdraw")
        self.assertTrue(os.path.samestat(slot.lstat(), replacement))
        file.write_bytes(raw)
        file.chmod(0o400)

        slot.unlink()
        self.design_read.side_effect = AssertionError("offline restore attempted to download")
        self.configure("install")
        self.configure("check")
        self.assertTrue(os.path.samestat(slot.lstat(), original))
        self.assertEqual((checkout / "SKILL.md").read_bytes(), raw)

    def test_design_notice_and_nested_files_are_both_required(self):
        self.configure("install")
        folder = (self.slots / "web-artifacts-builder").resolve()
        notice = folder.parent / self.notice
        self.assertEqual(notice.read_bytes(), b"fixture notice")
        notice.chmod(0o600)  # Earlier standalone notices used this mode.
        self.configure("check")
        notice.write_bytes(b"altered notice")
        with self.assertRaisesRegex(ValueError, self.notice):
            self.configure("check")
        notice.write_bytes(b"fixture notice")
        nested = folder / "scripts/shadcn-components.tar.gz"
        nested.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "shadcn-components"):
            self.configure("install")
        nested.chmod(0o400)
        folder.chmod(0o700)
        (folder / "scripts").chmod(0o700)
        (folder / "scripts").rename(self.home / "external-scripts")
        (self.home / "external-scripts").chmod(0o500)
        (folder / "scripts").symlink_to(self.home / "external-scripts")
        folder.chmod(0o500)
        with self.assertRaisesRegex(ValueError, "read-only skill directories"):
            self.configure("check")

    def test_failed_design_download_leaves_discovery_empty_and_can_retry(self):
        read = self.design_read.side_effect
        self.design_read.side_effect = lambda url, size: b"" if url.endswith(".tar.gz") else read(url, size)
        with self.assertRaisesRegex(ValueError, "shadcn-components"):
            self.configure("install")
        self.assertFalse(self.slots.exists())
        self.design_read.side_effect = read
        self.configure("install")
        # A standalone owner previously installed a link to this same release.
        slot = self.slots / "frontend-design"
        destination = slot.resolve()
        self.configure("withdraw")
        slot.symlink_to(destination)
        original = slot.lstat()
        self.configure("install")
        # An existing profile ownership witness belongs to the original link.
        with self.assertRaisesRegex(ValueError, "frontend-design"):
            self.configure("withdraw")
        self.assertEqual(list(self.slots.iterdir()), [slot])
        self.assertTrue(os.path.samestat(slot.lstat(), original))

    def test_published_runtime_protects_its_top_level_directory(self):
        import personal_dev_skills as dev
        publish = dev._rename_noreplace

        def rename_on_older_macos(source, destination):
            self.assertTrue(source.stat().st_mode & 0o200)
            self.assertEqual((source / "runtime").stat().st_mode & 0o777, 0o500)
            publish(source, destination)

        with patch.object(dev, "_rename_noreplace", side_effect=rename_on_older_macos):
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
        legacy = self.home / ".local/share/dev-personal-skills/releases" / doctor.revision
        shutil.copytree(doctor.root, legacy)
        legacy.chmod(0o700)  # Recreate the earlier standalone export.
        self.assertFalse((legacy / ".git").exists())
        self.slots.mkdir(parents=True)
        slot = self.slots / doctor.name
        slot.symlink_to(legacy / "_ops/skills/personal/dev-doctor")
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

    def test_conflicting_last_ownership_record_stops_before_publication(self):
        control = self.codex / "dev-personal-core/dev-new-repo"
        control.mkdir(parents=True)
        anchor = control / "dev-new-repo"
        anchor.write_text("earlier owner")
        with self.assertRaisesRegex(ValueError, "ownership record changed"):
            self.configure("install")
        self.assertFalse(self.slots.exists())
        self.assertEqual(anchor.read_text(), "earlier owner")
        self.download.assert_not_called()

    def test_authority_refuses_a_valid_unreachable_git_object(self):
        import zlib
        bundle = self.bundles["dev-new-repo"]
        bundle.prepare()
        raw = b"blob 7\0fixture"
        oid = hashlib.sha1(raw).hexdigest()
        objects = bundle.root / ".git/objects"
        objects.chmod(0o700)
        folder = objects / oid[:2]
        folder.mkdir(exist_ok=True)
        folder.chmod(0o700)
        extra = folder / oid[2:]
        self.assertFalse(extra.exists())
        extra.write_bytes(zlib.compress(raw))
        extra.chmod(0o400)
        folder.chmod(0o500)
        objects.chmod(0o500)
        with self.assertRaisesRegex(ValueError, "outside the pinned Dev authority"):
            bundle.verify()

    def test_runtime_or_authority_drift_stops_before_publication(self):
        creator = self.bundles["dev-new-repo"]
        creator.prepare()
        metadata = creator.root / ".git"
        creator.root.chmod(0o700)  # Simulate a separately modified installation.
        metadata.chmod(0o700)
        metadata.rename(self.home / "saved-metadata")
        creator.root.chmod(0o500)
        with self.assertRaisesRegex(ValueError, "authority"):
            self.configure("install")
        self.assertFalse(self.slots.exists())
        creator.root.chmod(0o700)
        (self.home / "saved-metadata").rename(metadata)
        metadata.chmod(0o500)
        creator.root.chmod(0o500)
        file = creator.skill / "SKILL.md"
        file.chmod(0o600)
        data = file.read_bytes()
        file.write_bytes(data[:-1] + b"x")
        with self.assertRaisesRegex(ValueError, "differs"):
            self.configure("install")
        self.assertFalse(self.slots.exists())
        file.write_bytes(data)
        file.chmod(0o400)
        self.configure("install")

    def test_check_rejects_missing_and_corrupt_authority_objects(self):
        self.configure("install")
        bundle = self.bundles["dev-new-repo"]
        objects = bundle.root / ".git" / "objects"
        parked = self.home / "saved-objects"
        objects.parent.chmod(0o700)
        objects.chmod(0o700)
        objects.rename(parked)
        objects.mkdir(mode=0o500)
        objects.parent.chmod(0o500)
        self.assertEqual(bundle.git.head(bundle.root), bundle.revision)
        with self.assertRaisesRegex(ValueError, "authority object"):
            self.configure("check")
        objects.parent.chmod(0o700)
        objects.rmdir()
        parked.rename(objects)
        objects.chmod(0o500)
        objects.parent.chmod(0o500)
        tree_id = bundle.git._run(["rev-parse", "HEAD^{tree}"], cwd=bundle.root,
                                  operation="fixture tree identity").stdout.strip()
        tree = objects / tree_id[:2] / tree_id[2:]
        objects.chmod(0o700)
        tree.parent.mkdir(exist_ok=True)
        tree.parent.chmod(0o700)
        saved = self.home / "saved-tree"
        if tree.exists():
            tree.rename(saved)
        tree.write_bytes(b"invalid fixture tree")
        tree.chmod(0o400)
        tree.parent.chmod(0o500)
        objects.chmod(0o500)
        with self.assertRaisesRegex(ValueError, "authority object"):
            self.configure("check")
        tree.parent.chmod(0o700)
        tree.unlink()
        if saved.exists():
            saved.rename(tree)
        tree.parent.chmod(0o500)
        self.configure("check")

    def test_creator_rejects_extra_metadata_before_invoking_git(self):
        bundle = self.bundles["dev-new-repo"]
        bundle.prepare()
        metadata = bundle.root / ".git"
        config = metadata / "config"
        clean = config.read_bytes()
        with patch.object(bundle.git, "_run", side_effect=AssertionError("Git ran before metadata validation")):
            config.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "authority"):
                bundle.verify()
            config.write_bytes(clean + b"[core]\n\tlogallrefupdates = true\n")
            config.chmod(0o400)
            with self.assertRaisesRegex(ValueError, "authority contents"):
                bundle.verify()
            config.chmod(0o600)
            config.write_bytes(clean)
            config.chmod(0o400)
            metadata.chmod(0o700)
            (metadata / "hooks").mkdir()
            metadata.chmod(0o500)
            with self.assertRaisesRegex(ValueError, "authority entry"):
                bundle.verify()

    def test_earlier_creator_with_writable_metadata_is_preserved(self):
        import shutil
        creator = self.bundles["dev-new-repo"]
        creator.prepare()
        legacy = self.home / ".local/share/dev-personal-skills/releases" / creator.revision
        shutil.copytree(creator.root, legacy)
        self.slots.mkdir(parents=True)
        slot = self.slots / creator.name
        slot.symlink_to(legacy / "_ops/skills/personal/dev-new-repo")
        original = slot.lstat()
        metadata = legacy / ".git"
        metadata.chmod(0o700)
        with self.assertRaisesRegex(ValueError, "sealed Dev authority"):
            self.configure("install")
        self.configure("withdraw")
        self.assertTrue(os.path.samestat(original, slot.lstat()))
        self.assertEqual(metadata.stat().st_mode & 0o777, 0o700)

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
