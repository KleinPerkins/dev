#!/usr/bin/env python3
"""The canonical dispatcher preserves hook routing in disposable repositories."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "_ops/bin/install-identity-guard.sh"
DISPATCHER = ROOT / "_ops/hooks/pre-commit-dispatcher"


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dispatcher-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.environment = {k: v for k, v in os.environ.items()
                            if not k.startswith("GIT_") and k != "DEV_SESSION_ID"}
        self.git("init", "-q", str(self.root))
        self.git("config", "core.hooksPath", str(self.root / "hooks"))
        self.git("remote", "add", "origin", "https://github.com/KleinPerkins/dispatcher-fixture.git")
        self.hooks = self.root / "hooks"
        self.hooks.mkdir()

    def git(self, *arguments):
        return subprocess.check_output(["git", *arguments], cwd=self.root,
                                       env=self.environment, text=True).strip()

    def install(self):
        return subprocess.run(["bash", str(INSTALLER), str(self.root)], cwd=self.root,
                              env=self.environment, capture_output=True, text=True, timeout=15)

    def test_copies_canonical_dispatcher_and_is_idempotent(self):
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        installed = self.hooks / "pre-commit"
        self.assertEqual(installed.read_bytes(), DISPATCHER.read_bytes())
        self.assertTrue(os.access(installed, os.X_OK))
        before = {p.name: (p.stat().st_ino, p.read_bytes()) for p in self.hooks.iterdir()}
        second = self.install()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(before, {p.name: (p.stat().st_ino, p.read_bytes()) for p in self.hooks.iterdir()})

    def test_preserves_and_chains_existing_hook_once(self):
        prior = b"#!/bin/sh\n# unrelated fixture hook\nexit 0\n"
        (self.hooks / "pre-commit").write_bytes(prior)
        (self.hooks / "pre-commit").chmod(0o755)
        inode = (self.hooks / "pre-commit").stat().st_ino
        self.assertEqual(self.install().returncode, 0)
        saved = self.hooks / "pre-commit.local"
        self.assertEqual(saved.read_bytes(), prior)
        self.assertEqual(saved.stat().st_ino, inode)
        self.assertEqual(self.install().returncode, 0)
        self.assertEqual(saved.read_bytes(), prior)
        self.assertEqual(saved.stat().st_ino, inode)

    def test_conflicting_prior_hooks_are_never_clobbered(self):
        for name in ("pre-commit", "pre-commit.local"):
            (self.hooks / name).write_bytes(name.encode())
        result = self.install()
        self.assertEqual(result.returncode, 3)
        for name in ("pre-commit", "pre-commit.local"):
            self.assertEqual((self.hooks / name).read_bytes(), name.encode())

    def test_foreign_framework_refuses_before_writing_hooks(self):
        self.git("config", "core.hooksPath", ".husky")
        result = self.install()
        self.assertEqual(result.returncode, 4)
        self.assertFalse((self.root / ".husky").exists())
        self.assertEqual(list(self.hooks.iterdir()), [])

    def test_dispatcher_preserves_guard_order_and_prior_hook(self):
        self.assertEqual(self.install().returncode, 0)
        log = self.root / "calls"
        for name in ("session-lock", "identity-guard", "data-guard", "registration-guard", "pre-commit.local"):
            script = self.hooks / name
            script.write_text('#!/bin/sh\nprintf "%s\\n" "' + name + ':$*" >> "$DISPATCH_FIXTURE_LOG"\n')
            script.chmod(0o755)
        result = subprocess.run([str(self.hooks / "pre-commit"), "fixture-argument"], cwd=self.root,
                                env=dict(self.environment, DISPATCH_FIXTURE_LOG=str(log)), timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(log.read_text().splitlines(), ["session-lock:check", "identity-guard:",
                         "data-guard:", "registration-guard:", "pre-commit.local:"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
