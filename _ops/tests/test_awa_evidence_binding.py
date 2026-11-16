"""Release-bound source evidence must never fall back to another checkout."""
import importlib.util
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "awa_binding", ROOT / "_ops/bin/check-awa-release-binding.py")
binding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(binding)


class EvidenceSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="awa-evidence-binding-")
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name).resolve()
        self.environment = {
            key: value for key, value in os.environ.items()
            if key not in {"BASH_ENV", "ENV"}
            and not key.startswith(("BASH_FUNC_", "GIT_", "GH_", "GITHUB_", "AWS_"))
            and not any(term in key.upper() for term in ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
        }
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "core.hooksPath", str(self.source / "empty-hooks"))
        self.origin = "https://github.com/example/awa-evidence-fixture.git"
        self.git("remote", "add", "origin", self.origin)
        for relative in ("engine/tests/__init__.py", "hook-probe/RESULTS-2026-07-05.md",
                         "hook-probe/RESULTS-CLOUD-2026-07-05.md"):
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# disposable evidence fixture\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.pointer = {"source": str(self.source), "commit": self.git("rev-parse", "HEAD")}
        self.gcb = {"clone_url": self.origin}

    def git(self, *arguments):
        return subprocess.check_output(
            ["git", "-C", str(self.source), *arguments], env=self.environment,
            text=True).rstrip("\n")

    def test_exact_clean_checkout_is_accepted(self):
        self.assertEqual(binding._validate_source_checkout(self.pointer, self.gcb), self.source)

    def test_wrong_head_origin_and_nested_root_are_rejected(self):
        candidates = [({**self.pointer, "commit": "0" * 40}, self.gcb),
                      (self.pointer, {"clone_url": self.origin + "-other"}),
                      ({**self.pointer, "source": str(self.source / "engine")}, self.gcb)]
        for pointer, gcb in candidates:
            with self.subTest(pointer=pointer, gcb=gcb), self.assertRaises(binding.BindingError):
                binding._validate_source_checkout(pointer, gcb)

    def test_dirty_and_untracked_evidence_are_rejected(self):
        target = self.source / "hook-probe/RESULTS-2026-07-05.md"
        target.write_text("changed\n")
        with self.assertRaises(binding.BindingError):
            binding._validate_source_checkout(self.pointer, self.gcb)
        target.write_text("# disposable evidence fixture\n")
        (self.source / "unexpected").write_text("untracked\n")
        with self.assertRaises(binding.BindingError):
            binding._validate_source_checkout(self.pointer, self.gcb)

    def test_clean_commit_missing_report_is_rejected(self):
        self.git("rm", "-q", "hook-probe/RESULTS-CLOUD-2026-07-05.md")
        self.git("commit", "-qm", "remove report")
        self.pointer["commit"] = self.git("rev-parse", "HEAD")
        with self.assertRaises(binding.BindingError):
            binding._validate_source_checkout(self.pointer, self.gcb)

    def test_hidden_index_changes_are_rejected(self):
        relative = "hook-probe/RESULTS-2026-07-05.md"
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                self.git("update-index", "--" + flag, relative)
                (self.source / relative).write_text("hidden changed evidence\n")
                self.assertEqual(self.git("status", "--porcelain=v1"), "")
                with self.assertRaises(binding.BindingError):
                    binding._validate_source_checkout(self.pointer, self.gcb)
                (self.source / relative).write_text("# disposable evidence fixture\n")
                self.git("update-index", "--no-" + flag, relative)


class SourceOnlyBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="awa-source-boundary-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.environment = {
            key: value for key, value in os.environ.items()
            if key not in {"BASH_ENV", "ENV"}
            and not key.startswith(("BASH_FUNC_", "GIT_", "AWA_", "DEV_AWA_", "GH_", "GITHUB_", "AWS_"))
            and not any(term in key.upper() for term in ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))
        }

    def test_source_sibling_resolution_refuses_even_explicit_existing_root(self):
        engine = self.root / "synthetic-engine"
        (engine / "engine").mkdir(parents=True)
        env = dict(self.environment, AWA_ENGINE_ROOT=str(engine))
        command = ["bash", str(ROOT / "_ops/bin/awa-sibling-root.sh")]
        default = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(default.stdout.strip(), str(engine))
        source = subprocess.run(command, env=dict(env, DEV_AWA_SOURCE_ONLY="1"),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(source.returncode, 1)
        self.assertEqual(source.stdout, "")

    def test_source_mode_never_resolves_binding_and_default_still_refuses(self):
        # Only a disposable synthetic root is executable. Missing overlay fixtures
        # must fail source verification; they must never cause installed fallback.
        check = self.root / "_ops/checks/worktree-verify.sh"
        check.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "_ops/checks/worktree-verify.sh", check)
        marker = self.root / "binding-called"
        binding_check = self.root / "_ops/bin/check-awa-release-binding.py"
        binding_check.parent.mkdir(parents=True)
        binding_check.write_text("from pathlib import Path\nPath(" + repr(str(marker)) +
                                 ").write_text('called')\nraise SystemExit(73)\n")
        runtime = self.root / "synthetic-runtime"
        kernel = runtime / "kernel/bin/dev-worktree.sh"
        kernel.parent.mkdir(parents=True)
        kernel.write_text("#!/bin/sh\nexit 74\n")
        kernel.chmod(0o755)
        env = dict(self.environment, AWA_HOME=str(runtime), AWA_ENGINE_HOME=str(runtime),
                   AWA_ENGINE_ROOT=str(runtime), DEV_AWA_SOURCE_ONLY="1")
        default = subprocess.run(["bash", str(check)], env=env,
                                 capture_output=True, text=True, timeout=20)
        self.assertEqual(default.returncode, 1)
        self.assertTrue(marker.exists(), default.stdout + default.stderr)
        marker.unlink()
        source = subprocess.run(["bash", str(check), "--source-only"], env=env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(source.returncode, 1)  # omitted source fixtures fail closed
        self.assertIn("SOURCE ONLY", source.stdout)
        self.assertIn("installed engine smoke intentionally withheld", source.stdout)
        self.assertFalse(marker.exists())
        invalid = subprocess.run(["bash", str(check), "--unknown"], env=env,
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(invalid.returncode, 2)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
