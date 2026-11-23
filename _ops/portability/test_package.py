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
        self.slot.rename(self.codex / ".dev-personal-core/withdrawn")
        self.run_action("withdraw")
        self.assertFalse(os.path.lexists(self.slot))
        self.assertFalse((self.home / ".codex").exists())
        self.run_action("install")
        self.run_action("check")

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
