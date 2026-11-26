"""Read GitHub checkout authority by immutable repository ID."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from math import ceil
import re
import subprocess
import time
from urllib.parse import quote, unquote

from personal_checkout_inventory import Refused


MAX_RESPONSE_BYTES = 256 * 1024
READ_ROUTE = re.compile(r"/repositories/[1-9][0-9]*(?:/branches/([A-Za-z0-9_.~%-]+))?")
FORBIDDEN_REF_CHARACTERS = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")
TRANSPORT_RETRY_DELAYS = (2, 5)
PUBLIC_REQUEST_TIMEOUT_SECONDS = 15
PUBLIC_RESPONSE_FOOTER = (
    "\n%{http_code}\n%header{x-ratelimit-remaining}\n%header{x-ratelimit-reset}\n%header{retry-after}"
)
# curl: DNS, connect, partial transfer, timeout, empty response, send, receive, and HTTP/2 stream errors.
TRANSIENT_TRANSPORT_STATUSES = frozenset({6, 7, 18, 28, 52, 55, 56, 92})


class TransientProviderRead(Refused):
    """The fixed endpoint could not complete a transport exchange."""


class GitHubRateLimited(Refused):
    """GitHub throttled an admitted repository read."""

    def __init__(self, status, retry_at):
        self.retry_at = retry_at
        message = f"GitHub rate limit reached for this public repository read (HTTP {status})."
        if retry_at is None:
            message += " GitHub supplied no usable reset time."
        else:
            reset = datetime.fromtimestamp(retry_at, timezone.utc)
            message += f" Retry after {reset:%Y-%m-%d %H:%M:%S UTC}."
        super().__init__(message)


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


def validate_branch_name(value):
    """Validate a literal GitHub branch name without resolving revision syntax."""
    # The branch API reads a literal name under refs/heads/. Branch creation
    # rules and CLI shorthand rules do not apply to this read.
    if (not isinstance(value, str) or not value or len(value) > 1024
            or value.endswith(".") or ".." in value or "@{" in value or FORBIDDEN_REF_CHARACTERS.search(value)
            or any(not part or part.startswith(".") or part.endswith(".lock") for part in value.split("/"))):
        raise Refused("GitHub returned an invalid default branch")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeError as error:
        raise Refused("GitHub returned an invalid default branch") from error
    if length > 1024:
        raise Refused("GitHub returned an invalid default branch")
    return value


def _public_response(output):
    # curl appends four bounded fields after the response body, including on
    # HTTP errors. Split from the end so formatted JSON stays intact.
    fields = (output or b"").rsplit(b"\n", 4)
    if len(fields) != 5 or re.fullmatch(rb"[0-9]{3}", fields[1]) is None:
        return b"", b"", b"", b"", b""
    return fields


def _rate_limit(status, remaining, reset, retry_after):
    if status not in {b"403", b"429"}:
        return None
    retry_seconds = int(retry_after) if re.fullmatch(rb"[0-9]{1,9}", retry_after) else None
    exhausted = remaining == b"0"
    if status != b"429" and not exhausted and retry_seconds is None:
        return None
    now = ceil(time.time())
    times = []
    if exhausted and re.fullmatch(rb"[0-9]{1,10}", reset) and int(reset) >= now:
        times.append(int(reset))
    if retry_seconds is not None:
        times.append(now + retry_seconds)
    if status == b"429" and not times and not exhausted:
        # GitHub's minimum wait for throttling with no reported reset.
        times.append(now + 60)
    return GitHubRateLimited(status.decode("ascii"), max(times) if times else None)


def public_github_get(path, *, deadline):
    """Use the fixed GitHub HTTPS endpoint without borrowing account credentials."""
    route = READ_ROUTE.fullmatch(path) if isinstance(path, str) else None
    if route is None:
        raise Refused("the GitHub request is outside the repository read interface")
    encoded_branch = route[1]
    if encoded_branch and quote(validate_branch_name(unquote(encoded_branch)), safe="") != encoded_branch:
        raise Refused("the GitHub branch request is outside the repository read interface")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Refused("the GitHub repository read exceeded its deadline")
    # Leave time in the overall budget to retry a stalled exchange.
    timeout = min(PUBLIC_REQUEST_TIMEOUT_SECONDS, remaining)
    command = [
        "/usr/bin/curl", "-q", "--silent", "--fail", "--noproxy", "*", "--proto", "=https",
        "--request", "GET", "--max-time", f"{max(0.001, timeout):.3f}",
        "--max-filesize", str(MAX_RESPONSE_BYTES), "--write-out", PUBLIC_RESPONSE_FOOTER,
        "--header", "Accept: application/vnd.github+json",
        "--header", "Cache-Control: no-cache",
        "--header", "X-GitHub-Api-Version: 2022-11-28",
        "--user-agent", "KleinPerkins-dev-checkout-authority",
        "https://api.github.com" + path,
    ]
    try:
        response = subprocess.run(command, env={"PATH": "/usr/bin:/bin"}, capture_output=True,
                                  timeout=timeout, check=True)
        payload, status, _, _, _ = _public_response(response.stdout)
        if status != b"200" or len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("unaccepted GitHub response")
        return json.loads(payload, object_pairs_hook=_unique_object)
    except subprocess.TimeoutExpired as error:
        raise TransientProviderRead("the GitHub transport timed out during the repository read") from error
    except subprocess.CalledProcessError as error:
        _, status, remaining, reset, retry_after = _public_response(error.stdout)
        limited = _rate_limit(status, remaining, reset, retry_after)
        if limited is not None:
            raise limited from error
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
    default = validate_branch_name(reply.get("default_branch"))
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
        except (TransientProviderRead, GitHubRateLimited) as error:
            if delay is None:
                raise
            if isinstance(error, GitHubRateLimited):
                if error.retry_at is None:
                    raise
                delay = max(delay, error.retry_at - time.time())
            if delay >= deadline - time.monotonic():
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
    branch_path = f"{root}/branches/{quote(default, safe='')}"
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
