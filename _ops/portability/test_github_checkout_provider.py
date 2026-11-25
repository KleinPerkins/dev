import json
import subprocess
from types import SimpleNamespace
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote

from github_checkout_provider import (
    Refused, TransientProviderRead, public_github_get, read_github_repository,
)


def deadline():
    return time.monotonic() + 10


REPO = {"id": 902, "full_name": "FixtureOwner/same.name", "default_branch": "main", "private": True}
BRANCH = {"name": "main", "commit": {"sha": "b"*40}, "protected": True}


class GitHubProviderTests(unittest.TestCase):
    def get(self, *replies):
        return Mock(side_effect=replies)

    def observation(self, backend):
        return read_github_repository(REPO["id"], deadline=deadline(), get=backend)

    def test_default_ref_and_both_identity_reads_share_one_immutable_id(self):
        backend = self.get(REPO, BRANCH, REPO)
        with patch("github_checkout_provider.time.time", side_effect=[20, 22]):
            received = self.observation(backend)
        self.assertEqual(received.repository_id, 902)
        self.assertEqual(received.default_head, "b"*40)
        self.assertTrue(received.private)
        self.assertEqual((received.ref_observed_at, received.identity_observed_at), (20, 22))
        self.assertEqual([c.args[0] for c in backend.call_args_list],
                         ["/repositories/902", "/repositories/902/branches/main", "/repositories/902"])

    def test_slash_in_a_real_branch_name_is_an_encoded_single_parameter(self):
        repo = REPO | {"default_branch": "release/next"}
        backend = self.get(repo, BRANCH | {"name": "release/next", "protected": False}, repo)
        self.assertFalse(self.observation(backend).branch_protected)
        self.assertEqual(backend.call_args_list[1].args[0], "/repositories/902/branches/release%2Fnext")

    def test_invalid_git_branch_is_refused_before_branch_lookup(self):
        for name in ("main..evil", "feature~1", "name.lock", "dir.lock/next", "dir/.private",
                     "main?", "main*", "main[", "main\\", "main^", "main:", "main@{oops}",
                     "trail.", "space bar", "main//broken", "-option", "HEAD", "refs/heads/main",
                     "c" * 40, "\ud800", "é" * 513):
            with self.subTest(name=name):
                backend = self.get(REPO | {"default_branch": name}, BRANCH | {"name": name},
                                   REPO | {"default_branch": name})
                with self.assertRaisesRegex(Refused, "invalid default branch"):
                    self.observation(backend)
                backend.assert_called_once()

    def test_valid_git_branch_characters_are_encoded_once_and_preserved(self):
        for name in ("@", "café/next", "release/-pilot", "topic/HEAD", "topic/v1.+@preview", "percent%20literal"):
            with self.subTest(name=name):
                repo = REPO | {"default_branch": name}
                backend = self.get(repo, BRANCH | {"name": name}, repo)
                self.assertEqual(self.observation(backend).default_branch, name)
                self.assertEqual(backend.call_args_list[1].args[0], "/repositories/902/branches/" + quote(name, safe=""))

    def test_literal_at_sign_branch_is_valid_as_a_fully_qualified_git_ref(self):
        subprocess.run(["/usr/bin/git", "check-ref-format", "refs/heads/@"],
                       check=True, capture_output=True, timeout=5)
        with self.assertRaises(subprocess.CalledProcessError):
            subprocess.run(["/usr/bin/git", "check-ref-format", "--allow-onelevel", "@"],
                           check=True, capture_output=True, timeout=5)
        with patch("github_checkout_provider.subprocess.run",
                   return_value=SimpleNamespace(stdout=b'{"name":"@"}200')) as runner:
            self.assertEqual(public_github_get("/repositories/902/branches/%40", deadline=deadline()), {"name": "@"})
        self.assertEqual(runner.call_args.args[0][-1], "https://api.github.com/repositories/902/branches/%40")

    def test_same_slug_on_a_different_id_refuses_before_branch_lookup(self):
        backend = self.get(REPO | {"id": 903})
        with self.assertRaisesRegex(Refused, "did not confirm the admitted repository ID"):
            self.observation(backend)
        self.assertEqual(backend.call_count, 1)

    def test_rename_during_read_requires_current_identity(self):
        backend = self.get(REPO, BRANCH, REPO | {"full_name": "OtherOwner/same.name"})
        with self.assertRaisesRegex(Refused, "changed during the default branch read"):
            self.observation(backend)

    def test_change_to_default_branch_during_read_requires_reconciliation(self):
        backend = self.get(REPO, BRANCH, REPO | {"default_branch": "next"})
        with self.assertRaisesRegex(Refused, "changed during the default branch read"):
            self.observation(backend)

    def test_malformed_branch_ref_never_becomes_authority(self):
        for changed in ({"name": "different"}, {"commit": {"sha":"short"}}, {"protected": "yes"}):
            with self.subTest(changed=changed):
                backend = self.get(REPO, BRANCH | changed)
                with self.assertRaises(Refused):
                    self.observation(backend)
                self.assertEqual(backend.call_count, 2)

    def test_invalid_or_preexpired_repository_selection_makes_no_requests(self):
        backend = self.get(REPO)
        with self.assertRaisesRegex(Refused, "immutable GitHub repository ID"):
            read_github_repository(True, deadline=deadline(), get=backend)
        with self.assertRaisesRegex(Refused, "exceeded its deadline"):
            read_github_repository(902, deadline=time.monotonic() - 1, get=backend)
        backend.assert_not_called()

    def test_read_finished_after_budget_cannot_create_source_observation(self):
        backend = self.get(REPO)
        with (patch("github_checkout_provider.time.monotonic", side_effect=[1, 4]),
              self.assertRaisesRegex(Refused, "exceeded its deadline")):
            read_github_repository(902, deadline=3, get=backend)
        self.assertEqual(backend.call_count, 1)

    def test_public_transport_accepts_only_exact_HTTPS_GET(self):
        response = SimpleNamespace(stdout=b'{"id":902}200')
        with patch("github_checkout_provider.subprocess.run", return_value=response) as runner:
            value = public_github_get("/repositories/902/branches/release%2Fnext", deadline=deadline())
        self.assertEqual(value, {"id": 902})
        command = runner.call_args.args[0]
        self.assertEqual(command[-1], "https://api.github.com/repositories/902/branches/release%2Fnext")
        self.assertEqual(command[command.index("--request")+1], "GET")
        self.assertIn("--noproxy", command)
        self.assertNotIn("--location", command)
        self.assertEqual(runner.call_args.kwargs["env"], {"PATH": "/usr/bin:/bin"})

    def test_public_transport_rejects_other_routes_before_starting_a_process(self):
        with patch("github_checkout_provider.subprocess.run") as runner:
            for path in ("https://example.invalid/", "/repos/FixtureOwner/same.name",
                         "/repositories/902/branches/%2E%2E", "/repositories/902/branches/x?y",
                         "/repositories/902/branches/x..y", "/repositories/902/branches/release%2Fname.lock", None):
                with self.subTest(path=path), self.assertRaises(Refused):
                    public_github_get(path, deadline=deadline())
            runner.assert_not_called()

    def test_public_transport_refuses_redirect_responses_and_ambiguous_JSON(self):
        for content in (b'{"id":902}301', b'{"id":902,"id":903}200'):
            with self.subTest(content=content), patch("github_checkout_provider.subprocess.run",
                 return_value=SimpleNamespace(stdout=content)), self.assertRaisesRegex(Refused, "unavailable"):
                public_github_get("/repositories/902", deadline=deadline())

    def test_failed_final_transport_discards_first_tuple_and_reads_all_three_again(self):
        def response(value):
            return SimpleNamespace(stdout=json.dumps(value).encode() + b"200")

        lost_connection = subprocess.CalledProcessError(56, "/usr/bin/curl")
        later_branch = BRANCH | {"commit": {"sha": "c" * 40}}
        replies = [response(REPO), response(BRANCH), lost_connection,
                   response(REPO), response(later_branch), response(REPO)]
        with (patch("github_checkout_provider.subprocess.run", side_effect=replies) as runner,
              patch("github_checkout_provider.time.sleep") as sleep):
            result = read_github_repository(902, deadline=deadline())
        self.assertEqual(result.default_head, "c" * 40)
        self.assertEqual([entry.args[0][-1] for entry in runner.call_args_list],
                         ["https://api.github.com" + path for path in
                          ("/repositories/902", "/repositories/902/branches/main", "/repositories/902") * 2])
        sleep.assert_called_once_with(2)

    def test_transport_retries_stop_after_two_delays(self):
        backend = Mock(side_effect=TransientProviderRead("temporary"))
        with (patch("github_checkout_provider.time.sleep") as sleep,
              self.assertRaises(TransientProviderRead)):
            self.observation(backend)
        self.assertEqual(backend.call_count, 3)
        self.assertEqual([entry.args[0] for entry in sleep.call_args_list], [2, 5])

    def test_transport_retries_skip_a_pause_that_consumes_the_deadline(self):
        backend = Mock(side_effect=TransientProviderRead("temporary"))
        with (patch("github_checkout_provider.time.monotonic", return_value=10),
              patch("github_checkout_provider.time.sleep") as sleep,
              self.assertRaises(TransientProviderRead)):
            read_github_repository(902, deadline=12, get=backend)
        sleep.assert_not_called()
        backend.assert_called_once_with("/repositories/902", deadline=12)

    def test_subprocess_timeout_leaves_time_to_retry_the_whole_repository_read(self):
        def response(value):
            return SimpleNamespace(stdout=json.dumps(value).encode() + b"200")

        def request(command, *, timeout, **_options):
            self.assertEqual(timeout, 15)
            self.assertEqual(command[command.index("--max-time") + 1], "15.000")
            result = next(responses)
            if result is None:
                raise subprocess.TimeoutExpired(command, timeout)
            return response(result)

        responses = iter([REPO, BRANCH, None, REPO, BRANCH | {"commit": {"sha": "c" * 40}}, REPO])
        with (patch("github_checkout_provider.time.monotonic", return_value=10),
              patch("github_checkout_provider.subprocess.run", side_effect=request) as runner,
              patch("github_checkout_provider.time.sleep") as sleep):
            result = read_github_repository(902, deadline=100)
        self.assertEqual(result.default_head, "c" * 40)
        self.assertEqual([call.args[0][-1] for call in runner.call_args_list],
                         ["https://api.github.com" + path for path in
                          ("/repositories/902", "/repositories/902/branches/main", "/repositories/902") * 2])
        sleep.assert_called_once_with(2)

    def test_subprocess_timeout_at_the_total_deadline_never_retries(self):
        now = [10.0]

        def request(command, *, timeout, **_options):
            self.assertEqual(timeout, 1.5)
            self.assertEqual(command[command.index("--max-time") + 1], "1.500")
            now[0] += timeout
            raise subprocess.TimeoutExpired(command, timeout)

        with (patch("github_checkout_provider.time.monotonic", side_effect=lambda: now[0]),
              patch("github_checkout_provider.subprocess.run", side_effect=request) as runner,
              patch("github_checkout_provider.time.sleep") as sleep,
              self.assertRaisesRegex(TransientProviderRead, "timed out")):
            read_github_repository(902, deadline=11.5)
        runner.assert_called_once()
        sleep.assert_not_called()

    def test_http_denial_and_changed_identity_stop_without_retry(self):
        for status, code in ((403, 22), (403, 56), (429, 56)):
            http_refusal = subprocess.CalledProcessError(code, "/usr/bin/curl", output=str(status).encode())
            with (self.subTest(status=status, code=code),
                  patch("github_checkout_provider.subprocess.run", side_effect=http_refusal) as runner,
                  patch("github_checkout_provider.time.sleep") as sleep,
                  self.assertRaisesRegex(Refused, f"HTTP {status}") as raised):
                read_github_repository(902, deadline=deadline())
            self.assertNotIsInstance(raised.exception, TransientProviderRead)
            runner.assert_called_once()
            sleep.assert_not_called()
        backend = self.get(REPO, BRANCH, REPO | {"id": 903})
        with (patch("github_checkout_provider.time.sleep") as sleep,
              self.assertRaisesRegex(Refused, "did not confirm the admitted repository ID")):
            self.observation(backend)
        sleep.assert_not_called()
        self.assertEqual(backend.call_count, 3)
