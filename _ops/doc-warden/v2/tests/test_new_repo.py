import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from fixture_factory import ROOT


class NewRepositoryTests(unittest.TestCase):
    def test_fixture_root_refuses_missing_flag_value_and_relative_path(self):
        script = str(ROOT / "_ops/bin/dev-new-repo.sh")
        for arguments in (
            ["born-v2", "--fixture-root", "--dry-run"],
            ["born-v2", "--fixture-root", "relative"],
        ):
            result = subprocess.run(
                [script, *arguments],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires an absolute path", result.stderr)

    def test_fixture_root_refuses_absolute_path_outside_system_temp(self):
        result = subprocess.run(
            [
                str(ROOT / "_ops/bin/dev-new-repo.sh"),
                "born-v2",
                "--fixture-root",
                str(ROOT / "not-a-temporary-fixture"),
                "--dry-run",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "--fixture-root is test-only and must resolve under the system temporary directory",
            result.stderr,
        )
        self.assertFalse((ROOT / "not-a-temporary-fixture").exists())

    def test_new_repo_fixture_starts_enabled_without_heavy_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run(
                [
                    str(ROOT / "_ops/bin/dev-new-repo.sh"),
                    "born-v2",
                    "--fixture-root",
                    str(root),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            target = root / "born-v2"
            output = json.loads(result.stdout.splitlines()[-1])
            config = json.loads((target / ".planning/doc-warden.json").read_text())
            self.assertTrue(output["enabled"])
            self.assertTrue(config["enabled"])
            self.assertTrue((target / ".planning/PROJECT.md").is_file())
            self.assertTrue((target / ".planning/ROADMAP.md").is_file())
            self.assertTrue((target / ".planning/STATE.md").is_file())
            self.assertTrue((target / ".planning/SKILL.md").is_file())
            self.assertTrue((target / ".planning/guards.json").is_file())
            self.assertTrue((target / ".github/CODEOWNERS").is_file())
            self.assertTrue((target / ".git/hooks/pre-commit").is_file())
            self.assertFalse((target / ".planning/PRD.md").exists())
            self.assertFalse((target / ".planning/SPEC.md").exists())
            status = subprocess.check_output(
                ["git", "-C", str(target), "status", "--porcelain"], text=True
            )
            self.assertEqual(status, "")

    def test_fixture_push_remote_is_gated_on_fixture_root_in_source(self):
        """
        Structural guard: the sole `remote set-url origin $DOC_WARDEN_FIXTURE_PUSH_REMOTE`
        rewrite must be directly governed by the exact safe compound:

            [ -n "${FIXTURE_ROOT:-}" ] && [ -n "${DOC_WARDEN_FIXTURE_PUSH_REMOTE:-}" ]

        Each of these mutations must break this test:
          - replacing && with ||       (rewrite allowed when only one var is set)
          - either -n with -z          (rewrite allowed when the var is absent)
          - a second rewrite site      (gate enforcement becomes ambiguous)
        Does not add a production-path seam.
        """
        script = (ROOT / "_ops/bin/dev-new-repo.sh").read_text()
        lines = script.splitlines()

        # Exactly one line rewrites origin using DOC_WARDEN_FIXTURE_PUSH_REMOTE.
        rewrite_idxs = [
            i for i, ln in enumerate(lines)
            if "remote set-url" in ln and "DOC_WARDEN_FIXTURE_PUSH_REMOTE" in ln
        ]
        self.assertEqual(
            len(rewrite_idxs), 1,
            "Expected exactly one remote set-url … DOC_WARDEN_FIXTURE_PUSH_REMOTE line; "
            "a second rewrite site would make gate enforcement ambiguous",
        )
        ri = rewrite_idxs[0]

        # The line immediately above the rewrite is the inner gate condition.
        gate_line = lines[ri - 1]

        # Positive -n for FIXTURE_ROOT (mutation: -z breaks assertIn below).
        self.assertIn('-n "${FIXTURE_ROOT:-}"', gate_line,
            "Gate must use positive -n for FIXTURE_ROOT (not -z inversion)")
        self.assertNotIn('-z "${FIXTURE_ROOT:-}"', gate_line,
            "Gate must not invert FIXTURE_ROOT with -z")

        # Positive -n for DOC_WARDEN_FIXTURE_PUSH_REMOTE (mutation: -z breaks assertIn).
        self.assertIn('-n "${DOC_WARDEN_FIXTURE_PUSH_REMOTE:-}"', gate_line,
            "Gate must use positive -n for DOC_WARDEN_FIXTURE_PUSH_REMOTE (not -z inversion)")
        self.assertNotIn('-z "${DOC_WARDEN_FIXTURE_PUSH_REMOTE:-}"', gate_line,
            "Gate must not invert DOC_WARDEN_FIXTURE_PUSH_REMOTE with -z")

        # Conditions joined by && not || (mutation: || breaks assertNotIn below).
        self.assertIn('&&', gate_line,
            "Gate must join conditions with && (not ||)")
        self.assertNotIn('||', gate_line,
            "Gate must not use || (would allow rewrite when only one condition holds)")


if __name__ == "__main__":
    unittest.main()
