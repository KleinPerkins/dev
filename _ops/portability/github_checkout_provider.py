"""Read GitHub checkout authority by immutable repository ID."""

from dataclasses import dataclass
import json
import re
import subprocess
import time
from urllib.parse import quote, unquote

from personal_checkout_inventory import Refused


MAX_RESPONSE_BYTES = 256 * 1024
READ_ROUTE = re.compile(r"/repositories/[1-9][0-9]*(?:/branches/([A-Za-z0-9_.~%-]+))?")
TRANSPORT_RETRY_DELAYS = (2, 5)
# curl: DNS, connect, partial transfer, timeout, empty response, send, receive, and HTTP/2 stream errors.
TRANSIENT_TRANSPORT_STATUSES = frozenset({6, 7, 18, 28, 52, 55, 56, 92})


class TransientProviderRead(Refused):
    """The fixed endpoint could not complete a transport exchange."""


@dataclass(frozen=True)
class GitHubRepositoryObservation:
    repository_id: int
    full_name: str
    default_branch: str
    default_head: str
    private: bool
    branch_protected: bool
    identity_observed_at: int
    ref_observed_at: int


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON field")
        obj[key] = value
    return obj


def _branch_name(value):
    if (not isinstance(value, str) or not value or len(value) > 1024
            or any(ord(char) < 33 or ord(char) == 127 for char in value)
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise Refused("GitHub returned an invalid default branch")
    return value


def public_github_get(path, *, deadline):
    """Use the fixed GitHub HTTPS endpoint without borrowing account credentials."""
    route = READ_ROUTE.fullmatch(path) if isinstance(path, str) else None
    if route is None:
        raise Refused("the GitHub request is outside the repository read interface")
    encoded_branch = route[1]
    if encoded_branch and quote(_branch_name(unquote(encoded_branch)), safe="") != encoded_branch:
        raise Refused("the GitHub branch request is outside the repository read interface")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Refused("the GitHub repository read exceeded its deadline")
    command = [
        "/usr/bin/curl", "-q", "--silent", "--fail", "--noproxy", "*", "--proto", "=https",
        "--request", "GET", "--max-time", f"{max(0.001, remaining):.3f}",
        "--max-filesize", str(MAX_RESPONSE_BYTES), "--write-out", "%{http_code}",
        "--header", "Accept: application/vnd.github+json",
        "--header", "Cache-Control: no-cache",
        "--header", "X-GitHub-Api-Version: 2022-11-28",
        "--user-agent", "KleinPerkins-dev-checkout-authority",
        "https://api.github.com" + path,
    ]
    try:
        response = subprocess.run(command, env={"PATH": "/usr/bin:/bin"}, capture_output=True,
                                  timeout=remaining, check=True)
        payload, status = response.stdout[:-3], response.stdout[-3:]
        if status != b"200" or len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("unaccepted GitHub response")
        return json.loads(payload, object_pairs_hook=_unique_object)
    except subprocess.CalledProcessError as error:
        status = (error.stdout or b"")[-3:]
        if error.returncode in TRANSIENT_TRANSPORT_STATUSES and status in {b"", b"000", b"200"}:
            raise TransientProviderRead("the GitHub transport did not complete the repository read") from error
        if len(status) == 3 and status.isdigit() and status >= b"400":
            raise Refused(f"the GitHub repository response is unavailable (HTTP {status.decode('ascii')})") from error
        raise Refused("the GitHub repository response is unavailable") from error
    except (OSError, ValueError, RecursionError, subprocess.SubprocessError) as error:
        raise Refused("the GitHub repository response is unavailable") from error


def _identity(reply, repository_id):
    if not isinstance(reply, dict) or type(reply.get("id")) is not int or reply["id"] != repository_id:
        raise Refused("GitHub did not confirm the admitted repository ID")
    full_name = reply.get("full_name")
    if (not isinstance(full_name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", full_name)
            or any(part in {".", ".."} for part in full_name.split("/"))):
        raise Refused("GitHub returned an invalid repository name")
    default = _branch_name(reply.get("default_branch"))
    private = reply.get("private")
    if type(private) is not bool:
        raise Refused("GitHub did not report the repository visibility")
    return full_name, default, private


def read_github_repository(repository_id, *, deadline, get=public_github_get):
    """Read the repository and ref using one immutable GitHub ID.

    For private repositories the caller supplies the owner-authorized GitHub
    GET transport for the same endpoint. Confirm the default branch selection
    after reading the branch without trusting a potentially reused slug.
    """
    if type(repository_id) is not int or not 0 < repository_id < 2**63:
        raise Refused("an immutable GitHub repository ID is required")
    for delay in (*TRANSPORT_RETRY_DELAYS, None):
        try:
            return _read_repository_once(repository_id, deadline, get)
        except TransientProviderRead:
            if delay is None or delay >= deadline - time.monotonic():
                raise
            time.sleep(delay)


def _read_repository_once(repository_id, deadline, get):
    # Re-read the entire identity/ref/identity tuple after a transient failure.
    # A partially observed tuple does not carry across attempts.

    def fetch(path):
        if time.monotonic() >= deadline:
            raise Refused("the GitHub repository read exceeded its deadline")
        reply = get(path, deadline=deadline)
        if time.monotonic() >= deadline:
            raise Refused("the GitHub repository read exceeded its deadline")
        return reply

    root = f"/repositories/{repository_id}"
    full_name, default, private = _identity(fetch(root), repository_id)
    try:
        branch_path = f"{root}/branches/{quote(default, safe='')}"
    except UnicodeError as error:
        raise Refused("GitHub returned an invalid default branch") from error
    branch = fetch(branch_path)
    ref_time = int(time.time())
    if not isinstance(branch, dict) or branch.get("name") != default:
        raise Refused("GitHub did not confirm the selected default branch")
    commit = branch.get("commit")
    head = commit.get("sha") if isinstance(commit, dict) else None
    protected = branch.get("protected")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head) or type(protected) is not bool:
        raise Refused("GitHub returned invalid default branch evidence")
    if _identity(fetch(root), repository_id) != (full_name, default, private):
        raise Refused("the GitHub repository changed during the default branch read")
    return GitHubRepositoryObservation(repository_id, full_name, default, head, private, protected,
                                       int(time.time()), ref_time)
