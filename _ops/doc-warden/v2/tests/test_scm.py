import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from doc_warden.canonical import canonical_json
from doc_warden.scm import _github_slug, observe_repository_identity


class RepositoryIdentityTests(unittest.TestCase):
    def test_supported_remotes_reduce_to_credential_free_slug(self):
        expected = "KleinPerkins/example"
        for remote in (
            "https://github.com/KleinPerkins/example.git",
            "https://oauth2:secret-token@github.com/KleinPerkins/example.git",
            "ssh://git@github.com/KleinPerkins/example.git",
            "git@github.com:KleinPerkins/example.git",
            "git://github.com/KleinPerkins/example.git",
        ):
            with self.subTest(remote=remote):
                self.assertEqual(_github_slug(remote), expected)

    def test_malformed_or_unsupported_remotes_fail_closed(self):
        for remote in (
            "http://github.com/KleinPerkins/example.git",
            "https://example.com/KleinPerkins/example.git",
            "https://github.com/KleinPerkins",
            "https://github.com/KleinPerkins/example.git?token=secret",
            "git@example.com:KleinPerkins/example.git",
            "git@github.com:KleinPerkins/example/extra.git",
        ):
            with self.subTest(remote=remote):
                with self.assertRaisesRegex(
                    ValueError, "github_origin_unsupported"
                ):
                    _github_slug(remote)

    def test_observed_binding_never_contains_remote_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "remote",
                    "add",
                    "origin",
                    (
                        "https://oauth2:secret-token@github.com/"
                        "KleinPerkins/example.git"
                    ),
                ],
                check=True,
            )
            with mock.patch(
                "doc_warden.scm._github_metadata",
                return_value={
                    "full_name": "KleinPerkins/example",
                    "id": 123456789,
                },
            ):
                identity = observe_repository_identity(repo)
            self.assertEqual(
                identity.binding(),
                {
                    "github_repository": "KleinPerkins/example",
                    "github_repository_id": 123456789,
                },
            )
            self.assertNotIn(
                b"secret-token", canonical_json(identity.binding())
            )

    def test_fixture_github_binary_is_confined_to_temporary_git_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "remote",
                    "add",
                    "origin",
                    "git@github.com:KleinPerkins/example.git",
                ],
                check=True,
            )
            outside_git_state = root / "gh"
            outside_git_state.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            outside_git_state.chmod(0o755)
            with mock.patch.dict(
                os.environ,
                {"DOC_WARDEN_GH_BIN": str(outside_git_state)},
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "github_repository_identity_unavailable",
                ):
                    observe_repository_identity(repo)


if __name__ == "__main__":
    unittest.main()
