#!/usr/bin/env bash
# dev-remove-repo.sh — safely remove WHOLE retired checkouts under ~/dev.
#
# Thin Bash entry; the engine is the embedded Python (stdlib only, 3.9+) below. Home-specific
# control-plane utility: it never touches GitHub, PAC, DNS, launchd or any subsystem's private
# state; it composes each subsystem's own verbs and reports everything else as an operator gate.
#
# Verbs (plain language lives in _ops/skills/dev-remove-repo/SKILL.md; method in
# docs/runbooks/dev-repo-removal.md):
#   view     [PATH...] [--operation ID]       read-only: assess checkouts, or show operations
#   view     --personal-codex PATH            inspect the original personal scaffold and registrations
#   remove   PATH...                          PREVIEW: assess, plan, create an operation, print the
#                                             exact confirmation (nothing is removed)
#   remove   --operation ID --confirm TOKEN [--waive RISKS] [--attest GATES]
#                                             execute in bounded cohorts, rescanning after each
#   resume   --operation ID                   continue an interrupted/paused operation (idempotent)
#   verify   --operation ID [--exception CLASS:SCOPE:REASON]...
#                                             independent verification; closes the journal only when
#                                             every check passes or has an honest recorded exception
#   doctor   [--journal FILE]                 check the tool, its state and journals (read-only)
#
# Safety model:
#   * One preview, one operation. The confirmation token binds the operation id, the target
#     manifest, the action digest, the preimage digests, the named risk waivers and attestations.
#     Anything that changed after the preview makes the token invalid; a new preview is required.
#     The token proves the exact preview was presented back; it cannot authenticate a human
#     (docs/runbooks/dev-repo-removal.md section 15).
#   * Never follows symlinks; rejects escaping or ambiguous paths, special files, mount points;
#     removes only through a no-follow descriptor chain with identity checks (TOCTOU-safe).
#   * Names can only DENY (cpp, skills hub, MCP monorepo, chaos-scheduler); a repo name never
#     authorises deletion. Whole-checkout removal under affirm/ requires the policy exception in
#     _ops/POLICY.md and a proof that nothing is writing; otherwise it stays an operator gate.
#   * State (secret-free, append-only, hash-chained journal; preimage digests, never contents):
#       ${XDG_STATE_HOME:-$HOME/.local/state}/dev-repo-removal/<operation-id>/
#   * Offline: no network call is made. GitHub/PAC/DNS/registrar steps are operator-owned.
#
# Exit codes: 0 ok, 1 refused (explained; nothing changed or state is resumable), 2 usage,
#             69 required tool unavailable, 75 interrupted (resume).
# Test seams (system-temp only): DEV_REMOVE_REPO_FIXTURE_ROOT / _INTERRUPT / _NOW, DEV_REMOVE_REPO_PYTHON.
set -uo pipefail

SELF="${BASH_SOURCE[0]:-$0}"
SELF="$(cd "$(dirname "$SELF")" && pwd -P)/$(basename "$SELF")"
ROOT="$(cd "$(dirname "$SELF")/../.." && pwd -P)"

pick_python() {
  local cand resolved
  for cand in "${DEV_REMOVE_REPO_PYTHON:-}" python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
    [ -n "$cand" ] || continue
    resolved="$(command -v "$cand" 2>/dev/null || true)"
    [ -n "$resolved" ] || continue
    if "$resolved" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
      printf '%s\n' "$resolved"
      return 0
    fi
  done
  return 1
}

PY="$(pick_python)" || { printf 'dev-remove-repo: Python 3.9 or newer is required\n' >&2; exit 69; }
export DRR_ROOT="$ROOT" DRR_SCRIPT_PATH="$SELF" DRR_START_CWD="$PWD"
exec "$PY" -I -B - "$@" <<'PY_ENGINE'
import argparse
import errno
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from contextlib import ExitStack
from datetime import datetime, timezone

TOOL = "dev-remove-repo"
SCHEMA_OPERATION = "dev-repo-removal/operation/v1"
SCHEMA_EVENT = "dev-repo-removal/event/v1"
STATE_DIRNAME = "dev-repo-removal"
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_USAGE = 2
EXIT_UNAVAILABLE = 69
EXIT_INTERRUPTED = 75
PREVIEW_TTL_SECONDS = 3600
COHORT_MAX = 5
SCAN_MAX_BYTES = 8 * 1024 * 1024
SUBPROCESS_TIMEOUT = 120
LSOF_TIMEOUT = 90
DOCTOR_TIMEOUT = 600
OP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{5,63}$")
POLICY_MARKER = "policy:dev-remove-repo-affirm-exception/v1"
POLICY_FILE = "_ops/POLICY.md"
GIT_CHILD_ENV_DROP = re.compile(r"^(GIT_.*|BASH_ENV|ENV|CDPATH|IFS|SHELLOPTS|BASHOPTS|PS4|PROMPT_COMMAND|PYTHON.*|LD_.*|DYLD_.*)$")

# Closed vocabulary. Exceptions must pick one class and name an exact path scope.
EXCEPTION_CLASSES = (
    "immutable-evidence",
    "historical-record",
    "retained-reference",
    "shared-store",
    "external-pending",
    "subsystem-stale",
)
# Checkouts that this tool refuses to remove no matter what (names can only DENY, never authorize).
DENY_REL = {
    "affirm/src/card-platform-product": "cpp is separately governed; its checkout is never removed from the home layer",
    "capabilities/skills": "the global skills hub is shared infrastructure",
    "capabilities/mcp": "the MCP monorepo is shared infrastructure",
    "personal/chaos-scheduler": "chaos-scheduler is a permanent hard no-touch exclusion",
}


def fold_name(rel):
    """A path as a volume that ignores letter case and Unicode form sees it (the default on macOS)."""
    return unicodedata.normalize("NFC", rel).casefold()


DENY_FOLDED = {fold_name(k): v for k, v in DENY_REL.items()}
ALLOWED_PARENTS = {
    ("affirm", "src"): "affirm-src",
    ("affirm", "vendor"): "affirm-vendor",
    ("personal",): "personal",
    ("capabilities",): "capabilities",
}
COHORT_ORDER = ("affirm-vendor", "affirm-src", "personal", "capabilities")
GATE_IDS = ("pac-fleet", "github-pages", "retained-consumers", "cpp-consumers", "client-config", "generated-memory", "launchd-shell")

# Credential shapes that are unmistakable. These are scrubbed from everything the tool writes or prints.
HIGH_CONFIDENCE_SECRETS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[abeoprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"A[KS]IA[0-9A-Z]{12,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"://[^/@\s]+:[^/@\s]+@"),
    re.compile(r"-----BEGIN[ A-Z]*-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
)
# Broader shapes, used where a person typed free text (exception reasons) and to tidy subprocess noise.
TOKEN_REDACTIONS = HIGH_CONFIDENCE_SECRETS + (
    re.compile(r"(?i)(token|secret|password|passwd|apikey|api_key)=\S+"),
    re.compile(r"(?<![A-Za-z0-9])(?:sk|pk|rk)-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?:glpat|npm|hf)[-_][A-Za-z0-9_-]{20,}"),
)
HIGH_ENTROPY_RE = re.compile(r"[A-Za-z0-9+_=-]{32,}")


class Refusal(Exception):
    """A deliberate, explained refusal. Nothing was changed."""

    def __init__(self, message, code=EXIT_REFUSED):
        super().__init__(message)
        self.message = message
        self.code = code


class Interrupted(Exception):
    """Fixture-only simulated crash after a durable write."""


# --------------------------------------------------------------------------- helpers

def jstr(value):
    """Make any str safe for UTF-8 JSON (surrogateescape bytes become \\xNN)."""
    if not isinstance(value, str):
        value = str(value)
    return value.encode("utf-8", "backslashreplace").decode("utf-8")


def sanitize(obj):
    if isinstance(obj, str):
        return jstr(obj)
    if isinstance(obj, dict):
        return {jstr(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    return obj


def canon(obj):
    """Canonical JSON text: sorted keys, compact separators, UTF-8, no NaN."""
    return json.dumps(sanitize(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canon_bytes(obj):
    return canon(obj).encode("utf-8")


def sha256_hex(data):
    if isinstance(data, str):
        data = data.encode("utf-8", "surrogateescape")
    return hashlib.sha256(data).hexdigest()


def digest_of(obj):
    return sha256_hex(canon_bytes(obj))


def iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def short_err(text, limit=200):
    """One redacted line of subprocess noise. Never raw logs."""
    if not text:
        return ""
    line = ""
    for candidate in str(text).splitlines():
        if candidate.strip():
            line = candidate.strip()
            break
    for pat in TOKEN_REDACTIONS:
        line = pat.sub("[redacted]", line)
    line = jstr(line)
    return line[:limit]


def scrub_secrets(text):
    """Replace unmistakable credential shapes. Applied to everything written to the journal or printed."""
    for pat in HIGH_CONFIDENCE_SECRETS:
        text = pat.sub("[redacted]", text)
    return text


def opaque_token(tok):
    """A long run of letters and digits that is not a readable kebab-case or snake_case name."""
    if not (re.search(r"[A-Za-z]", tok) and re.search(r"\d", tok)):
        return False
    segments = [sg for sg in re.split(r"[-_]", tok) if sg]
    if len(segments) >= 3 and sum(1 for sg in segments if sg.isalpha() or sg.isdigit()) / float(len(segments)) >= 0.8:
        return False
    return True


def looks_secret(text, entropy=True):
    """True when text carries a credential shape (and, with entropy, a long opaque letters-and-digits run)."""
    if any(pat.search(text) for pat in TOKEN_REDACTIONS):
        return True
    return entropy and any(opaque_token(tok) for tok in HIGH_ENTROPY_RE.findall(text))


def redact_url(url):
    """host/owner/name without credentials, query or fragment; ssh/https/scp forms; local paths stay local."""
    raw = re.split(r"[?#]", (url or "").strip(), maxsplit=1)[0]
    if not raw:
        return ""
    m = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://(?:[^/@]*@)?([^/:]+)(?::\d+)?/(.+?)(?:\.git)?/?$", raw)
    if m:
        return "%s/%s" % (m.group(1).lower(), m.group(2))
    m = re.match(r"^(?:[^@/]+@)?([^/:@]+):(?!//)(.+?)(?:\.git)?/?$", raw)
    if m and not raw.startswith("/") and "://" not in raw:
        return "%s/%s" % (m.group(1).lower(), m.group(2))
    if raw.startswith("/") or raw.startswith("file://"):
        return "local:" + raw.replace("file://", "")
    return "other:" + sha256_hex(raw)[:12]


def origin_slug(redacted):
    """owner/name from a redacted host/owner/name (github-style)."""
    parts = redacted.split("/")
    if redacted.startswith(("local:", "other:")) or len(parts) < 3:
        return ""
    return "/".join(parts[-2:])


def scrubbed_env(extra=None):
    env = {k: v for k, v in os.environ.items() if not GIT_CHILD_ENV_DROP.match(k)}
    env["LC_ALL"] = "C"
    env["GIT_TERMINAL_PROMPT"] = "0"
    if extra:
        env.update(extra)
    return env


class Result(object):
    __slots__ = ("rc", "out", "err", "error", "timed_out")

    def __init__(self, rc=None, out=b"", err=b"", error=None, timed_out=False):
        self.rc = rc
        self.out = out
        self.err = err
        self.error = error
        self.timed_out = timed_out

    @property
    def ok(self):
        return self.rc == 0 and self.error is None

    @property
    def text(self):
        return self.out.decode("utf-8", "replace")

    @property
    def errtext(self):
        return self.err.decode("utf-8", "replace")


def run(argv, timeout=SUBPROCESS_TIMEOUT, env=None, cwd=None):
    """Run an argv list (never a shell). Missing tools and timeouts are values, not crashes."""
    try:
        proc = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=env if env is not None else scrubbed_env(),
            cwd=cwd,
            shell=False,
            close_fds=True,
        )
        return Result(proc.returncode, proc.stdout, proc.stderr)
    except FileNotFoundError:
        return Result(error="not-installed")
    except PermissionError:
        return Result(error="not-executable")
    except subprocess.TimeoutExpired:
        return Result(error="timeout", timed_out=True)
    except OSError as exc:
        return Result(error="os-error:%s" % exc.errno)


def fsync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write(path, data, mode=0o600):
    """Same-directory temp + fsync + rename. Never writes through a symlink."""
    directory = os.path.dirname(path)
    tmp = os.path.join(directory, ".%s.%s.tmp" % (os.path.basename(path), secrets.token_hex(4)))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    fsync_dir(directory)


def append_durable(path, line):
    """Append one newline-terminated record; terminate any torn tail first. fsync before return.

    A journal created by this call also has its directory entry made durable.
    """
    created = not os.path.lexists(path)
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Refusal("state journal is not a regular file: %s" % path)
        payload = line if isinstance(line, bytes) else line.encode("utf-8")
        if not payload.endswith(b"\n"):
            payload += b"\n"
        if st.st_size > 0:
            os.lseek(fd, st.st_size - 1, os.SEEK_SET)
            if os.read(fd, 1) != b"\n":
                payload = b"\n" + payload
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    if created:
        fsync_dir(os.path.dirname(path) or ".")


def read_text_nofollow(path, limit=8 * 1024 * 1024):
    """Read a regular file without following a final symlink. None when unavailable."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", "replace")
    except OSError:
        return None
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- context

class Ctx(object):
    """Everything environment-dependent lives here so fixture roots can replace all of it."""

    def __init__(self):
        self.script_path = os.environ.get("DRR_SCRIPT_PATH", "")
        self.fixture = None
        self.interrupt_at = None
        self._clock = None
        self.adapter_dir = None
        fixture = os.environ.get("DEV_REMOVE_REPO_FIXTURE_ROOT", "")
        if fixture:
            fr = os.path.realpath(fixture)
            allowed = set()
            for candidate in (tempfile.gettempdir(), "/tmp", "/var/tmp"):
                allowed.add(os.path.realpath(candidate))
            inside = any(fr.startswith(a.rstrip("/") + "/") for a in allowed)
            if not os.path.isdir(fr) or fr in allowed or not inside:
                raise Refusal("fixture mode only runs under the system temporary directory", EXIT_USAGE)
            self.fixture = fr
            self.root = os.path.join(fr, "dev")
            self.home = os.path.join(fr, "home")
            self.adapter_dir = os.path.join(fr, "adapters")
            self.interrupt_at = os.environ.get("DEV_REMOVE_REPO_FIXTURE_INTERRUPT") or None
            now = os.environ.get("DEV_REMOVE_REPO_FIXTURE_NOW")
            self._clock = float(now) if now else None
            for needed in (self.root, self.home):
                if not os.path.isdir(needed):
                    raise Refusal("fixture root is missing %s" % os.path.basename(needed), EXIT_USAGE)
        else:
            root = os.environ.get("DRR_ROOT", "")
            if not root:
                raise Refusal("dev-remove-repo must be started through _ops/bin/dev-remove-repo.sh", EXIT_USAGE)
            self.root = root
            self.home = os.path.expanduser("~")
        self.root = os.path.realpath(self.root)
        self.home = os.path.realpath(self.home)
        base = os.environ.get("XDG_STATE_HOME") if not self.fixture else None
        if not base:
            base = os.path.join(self.home, ".local", "state")
        self.state_root = os.path.join(base, STATE_DIRNAME)
        self._tool_sha = None
        self._repo_head = False
        self.cache = {}
        start = os.environ.get("DRR_START_CWD") or os.getcwd()
        try:
            self.start_cwd = os.path.realpath(start)
        except OSError:
            self.start_cwd = start

    # -- time
    def now(self):
        return self._clock if self._clock is not None else time.time()

    # -- adapters (external lifecycle verbs). In fixture mode ONLY the fixture adapter dir is consulted.
    def adapter(self, name):
        if self.fixture:
            candidate = os.path.join(self.adapter_dir, name)
            return candidate if os.access(candidate, os.X_OK) and os.path.isfile(candidate) else None
        paths = {
            "worktree": [os.path.join(self.root, "_ops", "bin", "dev-worktree.sh")],
            "awa-engine": [os.path.join(self.home, ".local", "share", "awa", "current", "bin", "awa-engine.sh")],
            "local-jobs": [
                os.path.join(self.home, ".claude", "skills", "local-jobs", "scripts", "local-jobs.sh"),
                os.path.join(self.home, ".cursor", "skills", "local-jobs", "scripts", "local-jobs.sh"),
            ],
            "agent-route": [os.path.join(self.home, ".cursor", "skills", "agent-route", "scripts", "agent-route.sh")],
            "shadowsync": [os.path.join(self.root, "capabilities", "skills", "global", "tools", "dev-main-sync", "install.sh")],
            "dev-doctor": [os.path.join(self.root, "_ops", "checks", "dev-doctor.sh")],
        }
        for candidate in paths.get(name, []):
            if os.access(candidate, os.X_OK) and os.path.isfile(candidate):
                return candidate
        return None

    def tool(self, name):
        """Plain executables resolved on PATH (git, lsof, rg, claude, ps). Fixture adapters may shadow them."""
        if self.fixture:
            shadow = os.path.join(self.adapter_dir, name)
            if os.access(shadow, os.X_OK) and os.path.isfile(shadow):
                return shadow
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            if not directory:
                continue
            candidate = os.path.join(directory, name)
            if os.access(candidate, os.X_OK) and os.path.isfile(candidate):
                return candidate
        return None

    # -- source revision
    @property
    def tool_sha256(self):
        if self._tool_sha is None:
            data = None
            if self.script_path:
                try:
                    with open(self.script_path, "rb") as fh:
                        data = fh.read()
                except OSError:
                    data = None
            self._tool_sha = sha256_hex(data) if data is not None else "unknown"
        return self._tool_sha

    @property
    def repo_head(self):
        if self._repo_head is False:
            self._repo_head = None
            git = self.tool("git")
            if git and os.path.isdir(os.path.join(self.root, ".git")):
                res = run([git, "-C", self.root, "rev-parse", "HEAD"], env=git_env())
                if res.ok:
                    self._repo_head = res.text.strip() or None
        return self._repo_head

    def interrupt(self, point):
        """Simulated crash after a durable write (fixture mode only)."""
        if self.interrupt_at and self.interrupt_at == point:
            raise Interrupted(point)


def git_env():
    env = scrubbed_env(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "HOME": os.devnull,
            "XDG_CONFIG_HOME": os.devnull,
            "GIT_PAGER": "cat",
            "GIT_ASKPASS": "true",
            "GIT_EXTERNAL_DIFF": "",
        }
    )
    return env


def git_argv(ctx, repo, *args):
    git = ctx.tool("git")
    if not git:
        raise Refusal("git is not installed", EXIT_UNAVAILABLE)
    return [
        git,
        "-C",
        repo,
        "-c", "core.fsmonitor=false",
        "-c", "core.untrackedCache=false",
        "-c", "core.hooksPath=" + os.devnull,
        "-c", "protocol.allow=never",
        "-c", "advice.detachedHead=false",
        "--no-optional-locks",
    ] + list(args)



# --------------------------------------------------------------------------- state: lock, journal, pairing

def ensure_state_root(ctx, create=True):
    root = ctx.state_root
    try:
        st = os.lstat(root)
    except FileNotFoundError:
        if not create:
            return False
        parent = os.path.dirname(root)
        os.makedirs(parent, exist_ok=True)
        os.mkdir(root, 0o700)
        return True
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise Refusal("state root is not a plain directory: %s" % root)
    if st.st_uid != os.geteuid():
        raise Refusal("state root is owned by another user: %s" % root)
    return True


class WriterLock(object):
    """One writer at a time across all operations. Kernel-held (flock), so a crash releases it."""

    def __init__(self, ctx, operation_id=None):
        self.ctx = ctx
        self.operation_id = operation_id
        self.fd = None

    def __enter__(self):
        ensure_state_root(self.ctx)
        path = os.path.join(self.ctx.state_root, ".writer.lock")
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            os.close(fd)
            raise Refusal("writer lock is not a regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            owner = ""
            try:
                owner = os.pread(fd, 512, 0).decode("utf-8", "replace").strip()
            except OSError:
                pass
            os.close(fd)
            detail = ""
            try:
                info = json.loads(owner)
                detail = " (process %s, operation %s)" % (info.get("pid"), info.get("operation_id") or "none")
            except ValueError:
                pass
            raise Refusal("another dev-remove-repo run is writing state right now%s; wait for it or run doctor" % detail)
        os.ftruncate(fd, 0)
        os.write(fd, (canon({"pid": os.getpid(), "operation_id": self.operation_id or "", "since": iso(self.ctx.now())}) + "\n").encode())
        self.fd = fd
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = None
        return False


def lock_probe(ctx):
    """Read-only: is a writer holding the lock right now?"""
    path = os.path.join(ctx.state_root, ".writer.lock")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return "free"
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            return "held"
        fcntl.flock(fd, fcntl.LOCK_UN)
        return "free"
    finally:
        os.close(fd)


class JournalView(object):
    def __init__(self):
        self.events = []
        self.phys = []          # physical lines (bytes, newline-terminated where present)
        self.bad = []           # [(physical_index, reason)]
        self.torn = False       # final line has no newline or does not parse
        self.chain_ok = True
        self.chain_break = None
        self.legacy = False

    @property
    def count(self):
        return len(self.events)

    @property
    def closed(self):
        return bool(self.events) and self.events[-1].get("kind") == "close"

    @property
    def head_sha(self):
        return sha256_hex(self.phys[-1]) if self.phys else "0" * 64


def parse_journal_bytes(data):
    view = JournalView()
    if not data:
        return view
    lines = data.split(b"\n")
    tail_unterminated = lines[-1] != b""
    if not tail_unterminated:
        lines = lines[:-1]
    phys = [ln + b"\n" for ln in lines]
    if tail_unterminated:
        phys[-1] = phys[-1][:-1]
    prev_digest = "0" * 64
    pending_bad = None
    for idx, raw in enumerate(phys):
        text = raw.rstrip(b"\n")
        parsed = None
        if text.strip():
            try:
                parsed = json.loads(text.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                parsed = None
        if not isinstance(parsed, dict):
            if text.strip():
                view.bad.append((idx, "unparseable"))
                pending_bad = (idx, sha256_hex(text))
                if idx == len(phys) - 1:
                    view.torn = True
            prev_digest = sha256_hex(raw if raw.endswith(b"\n") else raw + b"\n")
            continue
        if tail_unterminated and idx == len(phys) - 1:
            view.torn = True
        if "prev" in parsed:
            if parsed.get("prev") != prev_digest:
                if view.chain_ok:
                    view.chain_ok = False
                    view.chain_break = parsed.get("seq")
        else:
            view.legacy = True
        if pending_bad is not None:
            recovered = parsed.get("torn_recovered")
            if recovered == pending_bad[1]:
                view.bad = [b for b in view.bad if b[0] != pending_bad[0]]
            pending_bad = None
        view.events.append(parsed)
        prev_digest = sha256_hex(raw if raw.endswith(b"\n") else raw + b"\n")
    view.phys = phys
    return view


def load_journal_file(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return JournalView()
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Refusal("journal is not a regular file: %s" % path)
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        return parse_journal_bytes(b"".join(chunks))
    finally:
        os.close(fd)


class Journal(object):
    def __init__(self, ctx, operation_id):
        if not OP_ID_RE.match(operation_id or ""):
            raise Refusal("not a valid operation id")
        self.ctx = ctx
        self.operation_id = operation_id
        self.dir = os.path.join(ctx.state_root, operation_id)
        self.path = os.path.join(self.dir, "events.jsonl")
        self.op_path = os.path.join(self.dir, "operation.json")

    def exists(self):
        return os.path.isfile(self.op_path)

    def load(self):
        return load_journal_file(self.path)

    def append(self, kind, **fields):
        view = self.load()
        if view.closed:
            raise Refusal("operation %s is closed; start a new preview if more work is needed" % self.operation_id)
        if view.bad and not (view.torn and len(view.bad) == 1 and view.bad[0][0] == len(view.phys) - 1):
            raise Refusal("journal for %s has unreadable records; run doctor before continuing" % self.operation_id)
        if not view.chain_ok:
            raise Refusal("journal for %s fails its integrity chain; run doctor before continuing" % self.operation_id)
        prev = "0" * 64
        extra = {}
        if view.phys:
            last = view.phys[-1]
            prev = sha256_hex(last if last.endswith(b"\n") else last + b"\n")
            if view.torn:
                extra["torn_recovered"] = sha256_hex(last.rstrip(b"\n"))
        event = {
            "seq": view.count + 1,
            "ts": iso(self.ctx.now()),
            "operation_id": self.operation_id,
            "kind": kind,
            "prev": prev,
        }
        event.update(extra)
        event.update(fields)
        append_durable(self.path, scrub_secrets(canon(event)).encode("utf-8"))
        return event


def journal_problems(view, operation_id):
    """Every reason this journal cannot be trusted. Empty list means it is intact (a torn tail is recoverable)."""
    problems = []
    if not view.events:
        return ["the journal is empty or missing"]
    if view.legacy:
        problems.append("it is not a native journal (its records lack the integrity chain)")
    if not view.chain_ok:
        problems.append("the integrity chain breaks at record %s" % view.chain_break)
    recoverable_tail = view.torn and len(view.bad) == 1 and view.bad[0][0] == len(view.phys) - 1 and not view.closed
    if view.bad and not recoverable_tail:
        problems.append("%d record(s) cannot be read" % len(view.bad))
    if [e.get("seq") for e in view.events] != list(range(1, len(view.events) + 1)):
        problems.append("the record numbers are not contiguous")
    if any(e.get("operation_id") != operation_id for e in view.events):
        problems.append("some records belong to another operation")
    if view.events[0].get("kind") != "open" or view.events[0].get("schema") != SCHEMA_EVENT:
        problems.append("it does not begin with a valid opening record")
    if view.closed:
        last = view.events[-1]
        n, want = last.get("events"), last.get("events_sha256")
        if not (isinstance(n, int) and isinstance(want, str) and n == len(view.events) - 1 and n <= len(view.phys)):
            problems.append("the closing record does not account for the journal")
        else:
            blob = b"".join(ln if ln.endswith(b"\n") else ln + b"\n" for ln in view.phys[:n])
            if sha256_hex(blob) != want:
                problems.append("the journal changed after it was closed")
    return problems


def pair_intents(events):
    """Pair every intent with its outcome. Corrections and reopenings are explicit fields."""
    closers = {}
    voided = set()
    reopened = {}
    for ev in events:
        kind = ev.get("kind")
        seq = ev.get("seq")
        if kind in ("complete", "failure", "exception", "refusal") and isinstance(ev.get("closes"), int):
            closers.setdefault(ev["closes"], []).append(ev)
        elif kind == "surprise":
            for target in ev.get("invalidates") or []:
                voided.add(target)
            for target in ev.get("reopens") or []:
                reopened.setdefault(target, []).append(seq)
    outcome_for = {"complete": "completed", "failure": "failed", "exception": "excepted", "refusal": "refused"}
    pairs = []
    for ev in events:
        if ev.get("kind") != "intent" or not isinstance(ev.get("seq"), int):
            continue
        seq = ev["seq"]
        marks = reopened.get(seq, [])
        last_reopen = max(marks) if marks else 0
        every = closers.get(seq, [])
        valid = [c for c in every if isinstance(c.get("seq"), int) and c["seq"] not in voided and c["seq"] > last_reopen]
        status = outcome_for[valid[-1]["kind"]] if valid else "open"
        pairs.append(
            {
                "intent": seq,
                "step": ev.get("step") or ev.get("plan_step"),
                "subsystem": ev.get("subsystem"),
                "status": status,
                "outcomes": [c["seq"] for c in every],
                "final_outcome": valid[-1]["seq"] if valid else None,
                "corrected": any(c["seq"] in voided for c in every),
                "reopened": bool(marks),
            }
        )
    return pairs


def step_states(events, step_ids):
    """Latest intent per step defines its state. pending = never started."""
    pairs = pair_intents(events)
    latest = {}
    for pair in pairs:
        if pair["step"]:
            latest[pair["step"]] = pair
    states = {}
    for sid in step_ids:
        pair = latest.get(sid)
        states[sid] = "pending" if pair is None else pair["status"]
    return states, latest


def inspect_journal_file(path):
    """Read-only structural report for a native, legacy, or sanitized replay journal."""
    view = load_journal_file(path)
    report = {
        "events": view.count,
        "format": "empty",
        "contiguous": False,
        "operation_ids": [],
        "closed": False,
        "close_digest_ok": None,
        "chain_ok": view.chain_ok,
        "unreadable_records": len(view.bad),
        "pairs": [],
        "unpaired_completes": 0,
        "intents": 0,
        "pairing": "explicit",
        "kinds": {},
    }
    if not view.events:
        return report
    has_prev = any("prev" in e for e in view.events)
    has_relations = any(("closes" in e or "invalidates" in e or "reopens" in e) for e in view.events)
    report["format"] = "native" if has_prev else ("replay" if has_relations else "legacy")
    seqs = [e.get("seq") for e in view.events]
    report["contiguous"] = seqs == list(range(1, len(seqs) + 1))
    report["operation_ids"] = sorted({str(e["operation_id"]) for e in view.events if e.get("operation_id")})
    for ev in view.events:
        report["kinds"][ev.get("kind")] = report["kinds"].get(ev.get("kind"), 0) + 1
    last = view.events[-1]
    if last.get("kind") == "close":
        report["closed"] = True
        n = last.get("events")
        want = last.get("events_sha256")
        if want is None:
            report["close_digest_ok"] = None
        elif isinstance(n, int) and isinstance(want, str) and n <= len(view.phys):
            blob = b"".join(ln if ln.endswith(b"\n") else ln + b"\n" for ln in view.phys[:n])
            report["close_digest_ok"] = sha256_hex(blob) == want
        else:
            report["close_digest_ok"] = False
    report["intents"] = sum(1 for e in view.events if e.get("kind") == "intent")
    if report["format"] == "legacy":
        report["pairing"] = "implicit"
        report["unpaired_completes"] = None
        return report
    report["pairs"] = pair_intents(view.events)
    closed_seqs = {p_out for p in report["pairs"] for p_out in p["outcomes"]}
    report["unpaired_completes"] = sum(
        1 for e in view.events if e.get("kind") == "complete" and e.get("seq") not in closed_seqs
    )
    return report


def legacy_record(ctx, op_id):
    """The structural report for a state folder this tool did not make: an events.jsonl in the older hand-run format
    (no integrity chain) and no operation.json, such as the Milestone 1 journal. None for anything else, so a damaged
    native operation is still reported as damaged."""
    journal = Journal(ctx, op_id)
    if journal.exists():
        return None
    try:
        if not stat.S_ISREG(os.lstat(journal.path).st_mode):
            return None
        report = inspect_journal_file(journal.path)
    except (OSError, Refusal):
        return None
    return report if report["format"] == "legacy" else None


def legacy_standing(report):
    """(status, words) for a record from before this tool: history that is read and never acted on."""
    sound = report["contiguous"] and report["unreadable_records"] == 0 and (not report["closed"] or report["close_digest_ok"] is not False)
    base = "a record from before this tool (older format, %d events)" % report["events"]
    if report["closed"] and sound:
        return "ok", base + ", closed and intact; it is history, read it with doctor --journal"
    if not report["closed"]:
        return "warn", base + " that was never closed; this tool cannot resume it"
    return "warn", base + " that no longer replays cleanly; this tool does not act on it"



# --------------------------------------------------------------------------- paths: validation, no-follow walk, removal

O_DIR_NOFOLLOW = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)


class PathProblem(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _open_child_dir(parent_fd, name):
    """Open a child directory without following symlinks and with an exact on-disk spelling."""
    try:
        listing = os.listdir(parent_fd)
    except OSError as exc:
        raise PathProblem("unreadable", "cannot list a parent directory (%s)" % errno.errorcode.get(exc.errno, exc.errno))
    if name not in listing:
        try:
            os.lstat(name, dir_fd=parent_fd)
        except FileNotFoundError:
            raise PathProblem("absent", "does not exist")
        except OSError:
            pass
        raise PathProblem("ambiguous-name", "the on-disk spelling of '%s' differs (case or Unicode form); use the exact name" % name)
    try:
        lst = os.lstat(name, dir_fd=parent_fd)
    except FileNotFoundError:
        raise PathProblem("absent", "does not exist")
    if stat.S_ISLNK(lst.st_mode):
        raise PathProblem("symlink", "'%s' is a symbolic link; links are never followed" % name)
    if not stat.S_ISDIR(lst.st_mode):
        raise PathProblem("not-directory", "'%s' is not a directory" % name)
    try:
        fd = os.open(name, O_DIR_NOFOLLOW, dir_fd=parent_fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise PathProblem("symlink", "'%s' changed into a link while it was being opened" % name)
        raise PathProblem("unreadable", "cannot open '%s' (%s)" % (name, errno.errorcode.get(exc.errno, exc.errno)))
    cst = os.fstat(fd)
    if (cst.st_dev, cst.st_ino) != (lst.st_dev, lst.st_ino):
        os.close(fd)
        raise PathProblem("raced", "'%s' was replaced while it was being opened" % name)
    return fd


def open_chain(ctx, comps, base=None):
    """Open base/comps[0]/.../comps[-1]; every step no-follow. Returns (fd, parent_fd). Caller closes both."""
    try:
        root_fd = os.open(base or ctx.root, O_DIR_NOFOLLOW)
    except FileNotFoundError:
        raise PathProblem("absent", "does not exist")
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise PathProblem("symlink", "the starting folder is a link or not a folder; links are never followed")
        raise PathProblem("unreadable", "cannot open the starting folder (%s)" % errno.errorcode.get(exc.errno, exc.errno))
    fd = root_fd
    parent = None
    try:
        for comp in comps:
            nxt = _open_child_dir(fd, comp)
            if parent is not None:
                os.close(parent)
            parent = fd
            fd = nxt
        return fd, parent
    except BaseException:
        for handle in (fd, parent):
            if handle is not None:
                try:
                    os.close(handle)
                except OSError:
                    pass
        raise


def classify_path(ctx, raw):
    """Pure syntax/containment check. Returns (rel, comps, root_class) or raises PathProblem."""
    if not isinstance(raw, str) or not raw:
        raise PathProblem("empty", "an empty path was given")
    if len(raw) > 4096:
        raise PathProblem("too-long", "the path is too long")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise PathProblem("control-characters", "the path contains control characters")
    if raw.startswith("-"):
        raise PathProblem("option-like", "the path starts with '-' and would be mistaken for an option")
    candidate = raw if raw.startswith("/") else ctx.root + "/" + raw
    parts = candidate.split("/")
    if any(p in ("", ".", "..") for p in parts[1:]):
        raise PathProblem("not-canonical", "the path is not in canonical form (no '.', '..', '//' or trailing '/' allowed)")
    prefix = ctx.root + "/"
    if not candidate.startswith(prefix):
        raise PathProblem("outside-root", "the path is outside the dev root (%s); give a path inside it in canonical form" % ctx.root)
    rel = candidate[len(prefix):]
    comps = rel.split("/")
    root_class = None
    for parent, klass in ALLOWED_PARENTS.items():
        if tuple(comps[: len(parent)]) == parent and len(comps) == len(parent) + 1:
            root_class = klass
            break
    if root_class is None:
        raise PathProblem(
            "not-a-checkout-location",
            "only whole checkouts are removable: affirm/src/<name>, affirm/vendor/<name>, personal/<name> or capabilities/<name> "
            "(a repository name alone is never enough)",
        )
    protected = DENY_FOLDED.get(fold_name(rel))
    if protected:
        raise PathProblem("protected", protected)
    return rel, comps, root_class


def stat_identity(st):
    return {"dev": st.st_dev, "ino": st.st_ino}


def walk_tree(root_fd, root_dev):
    """No-follow walk of a checkout (excluding .git internals). Stat-only fingerprint, never contents."""
    out = {
        "files": 0,
        "dirs": 0,
        "symlinks": 0,
        "bytes": 0,
        "specials": [],
        "sockets": [],
        "nested_git": [],
        "cross_device": [],
        "unreadable": [],
        "fingerprint": "",
    }
    lines = []
    stack = [(os.dup(root_fd), "")]
    while stack:
        fd, prefix = stack.pop()
        try:
            try:
                with os.scandir(fd) as it:
                    entries = list(it)
            except OSError as exc:
                out["unreadable"].append(prefix or ".")
                continue
            for entry in entries:
                name = entry.name
                rel = prefix + name
                if name == ".git":
                    if prefix:
                        out["nested_git"].append(rel)
                    lines.append(os.fsencode(rel) + b"\0git")
                    continue
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    out["unreadable"].append(rel)
                    continue
                mode = st.st_mode
                if stat.S_ISDIR(mode):
                    out["dirs"] += 1
                    if st.st_dev != root_dev:
                        out["cross_device"].append(rel)
                        lines.append(os.fsencode(rel) + b"\0mount")
                        continue
                    try:
                        child = os.open(name, O_DIR_NOFOLLOW, dir_fd=fd)
                    except OSError:
                        out["unreadable"].append(rel)
                        continue
                    cst = os.fstat(child)
                    if (cst.st_dev, cst.st_ino) != (st.st_dev, st.st_ino):
                        os.close(child)
                        out["unreadable"].append(rel)
                        continue
                    lines.append(os.fsencode(rel) + b"\0d\0%d\0%d" % (stat.S_IMODE(mode), st.st_ino))
                    stack.append((child, rel + "/"))
                elif stat.S_ISREG(mode):
                    out["files"] += 1
                    out["bytes"] += st.st_size
                    # ctime and inode cannot be set by a program, so a same-size, same-mtime rewrite still shows up
                    lines.append(
                        os.fsencode(rel)
                        + b"\0f\0%d\0%d\0%d\0%d\0%d" % (st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino, stat.S_IMODE(mode))
                    )
                elif stat.S_ISLNK(mode):
                    out["symlinks"] += 1
                    lines.append(os.fsencode(rel) + b"\0l\0%d\0%d\0%d" % (st.st_mtime_ns, st.st_ctime_ns, st.st_ino))
                else:
                    kind = "socket" if stat.S_ISSOCK(mode) else "fifo" if stat.S_ISFIFO(mode) else "device"
                    if kind == "socket":
                        out["sockets"].append(rel)
                    out["specials"].append("%s:%s" % (kind, rel))
                    lines.append(os.fsencode(rel) + b"\0" + kind.encode())
        finally:
            os.close(fd)
    lines.sort()
    out["fingerprint"] = sha256_hex(b"\n".join(lines))
    for key in ("specials", "sockets", "nested_git", "cross_device", "unreadable"):
        out[key] = sorted(out[key])
    return out


def _make_writable(fd, st):
    if not (st.st_mode & stat.S_IWUSR) and st.st_uid == os.geteuid():
        try:
            os.fchmod(fd, st.st_mode | stat.S_IRWXU)
        except OSError:
            pass


def _remove_failure(name, exc):
    code = errno.errorcode.get(exc.errno, str(exc.errno))
    return Refusal("cannot remove '%s' (%s); nothing outside the checkout was touched" % (jstr(name), code))


def _rm_contents(dirfd, dev, counters, hook=None, depth=0):
    if depth > 1800:
        raise Refusal("directory nesting is too deep to remove safely")
    with os.scandir(dirfd) as it:
        entries = list(it)
    for entry in entries:
        name = entry.name
        lst = os.lstat(name, dir_fd=dirfd)
        mode = lst.st_mode
        if stat.S_ISDIR(mode):
            if lst.st_dev != dev:
                raise Refusal("a mount point appeared inside the checkout; refusing to cross it")
            try:
                child = os.open(name, O_DIR_NOFOLLOW, dir_fd=dirfd)
            except OSError as exc:
                raise _remove_failure(name, exc)
            try:
                cst = os.fstat(child)
                if (cst.st_dev, cst.st_ino) != (lst.st_dev, lst.st_ino):
                    raise Refusal("a directory was swapped while removing; stopped without following it")
                _make_writable(child, cst)
                _rm_contents(child, dev, counters, hook, depth + 1)
            finally:
                os.close(child)
            try:
                os.rmdir(name, dir_fd=dirfd)
            except OSError as exc:
                raise _remove_failure(name, exc)
        elif stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            try:
                os.unlink(name, dir_fd=dirfd)
            except OSError as exc:
                raise _remove_failure(name, exc)
        else:
            raise Refusal("an unexpected special file appeared inside the checkout; stopped")
        counters["entries"] += 1
        if hook is not None:
            hook("entry", counters)


def registration_id(name, identity):
    return digest_of([sha256_hex(os.fsencode(name)), identity])


def registration_binding(name, row):
    return digest_of([registration_id(name, row["identity"]), sha256_hex(os.fsencode(row["gitdir"]))])


def registration_records(tfd, *, purging=(), allow_missing_git=False):
    """Read the selected checkout's own registration table without visiting any worktree."""
    records = {}
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        with ExitStack() as stack:
            def directory(parent, name):
                fd = os.open(name, O_DIR_NOFOLLOW, dir_fd=parent)
                stack.callback(os.close, fd)
                return fd

            try:
                git = directory(tfd, ".git")
            except FileNotFoundError:
                if allow_missing_git:
                    return {}
                raise
            try:
                table = directory(git, "worktrees")
            except FileNotFoundError:
                return {}
            names = sorted(os.listdir(table))
            for name in names:
                entry = os.open(name, O_DIR_NOFOLLOW, dir_fd=table)
                try:
                    identity = stat_identity(os.fstat(entry))
                    try:
                        fd = os.open("gitdir", flags, dir_fd=entry)
                    except FileNotFoundError:
                        # A prior purge may have unlinked the pointer and stopped before rmdir.
                        # The purge guard already checked this exact registration was inside the checkout.
                        if registration_id(name, identity) not in purging:
                            raise
                        records[name] = {"identity": identity, "gitdir": None}
                        continue
                    try:
                        if not stat.S_ISREG(os.fstat(fd).st_mode):
                            raise Refusal("a worktree registration has no regular gitdir record")
                        raw = os.read(fd, 4097)
                    finally:
                        os.close(fd)
                    path = os.fsdecode(raw[:-1] if raw.endswith(b"\n") else raw)
                    if len(raw) > 4096 or "\0" in path or os.path.basename(path) != ".git":
                        raise Refusal("a worktree registration has an incomplete gitdir path")
                    records[name] = {"identity": identity, "gitdir": path}
                finally:
                    os.close(entry)
            if sorted(os.listdir(table)) != names:
                raise Refusal("the worktree registration list changed during inspection")
    except OSError as exc:
        raise Refusal("a worktree registration could not be read (%s); inspect it before continuing" %
                      errno.errorcode.get(exc.errno, "I/O error"))
    return records


def registration_paths(records, admin):
    return [os.path.dirname(os.path.normpath(os.path.join(admin, name, row["gitdir"])))
            for name, row in records.items()]


def personal_scaffold_view(args):
    """Inspect one canonical creation record without running Git in the selected checkout."""
    from pathlib import Path
    sys.path.insert(0, os.path.join(os.environ["DRR_ROOT"], "_ops", "portability"))
    from personal_scaffold import LAYOUT, check_product_name, checkout_binding, owner_location
    from personal_scope import absolute_directory, child_directory, read_regular

    if (len(args.paths) != 1 or args.operation is not None or args.fixture_root == ""
            or os.environ.get("DEV_REMOVE_REPO_FIXTURE_ROOT")):
        raise Refusal("select one canonical product path; use --fixture-root for a personal scaffold fixture", EXIT_USAGE)
    fixture = args.fixture_root
    raw = args.paths[0]
    name = os.path.basename(raw)
    try:
        root, parts = owner_location(fixture)
        checkout = root.joinpath(*parts, name)
        if raw not in (str(checkout), str(Path(*LAYOUT, name))):
            raise Refusal("expected a canonical personal product path")
        check_product_name(name)
        with ExitStack() as stack:
            def hold(fd):
                stack.callback(os.close, fd)
                return fd

            base = hold(absolute_directory(root))
            if os.fstat(base).st_uid != os.getuid():
                raise Refusal("operator-owned root required")
            selected = hold(child_directory(base, (*parts, name)))
            fcntl.flock(selected, fcntl.LOCK_SH | fcntl.LOCK_NB)
            git = hold(child_directory(selected, (".git",)))
            state_name = "doc-warden-new-repo.json"
            saved = read_regular(git, state_name)
            state = json.loads(saved)
            slug = "KleinPerkins/" + name
            if (not isinstance(state, dict) or state.get("schema") != "dev-new-repo-operation/v2"
                    or state.get("repository") != slug or state.get("test_sharding_required") is not True
                    or "github_repository_id" not in state):
                raise Refusal("the creation record does not identify the selected personal product")
            recorded_id = state.get("github_repository_id")
            if recorded_id is not None and (type(recorded_id) is not int or recorded_id <= 0):
                raise Refusal("the creation record has an invalid repository ID")
            # Live creation binds an empty fixture ID even after GitHub assigns a repository ID.
            fixture_id = str(recorded_id) if fixture and recorded_id is not None else ""
            expected = checkout_binding(checkout, fixture, fixture_id, os.fstat(selected), os.fstat(git))
            if state.get("personal_checkout") != expected:
                raise Refusal("the creation record does not match this checkout and Git directory")
            config = read_regular(git, "config")
            origin = subprocess.run(
                ["/usr/bin/git", "config", "--no-includes", "--file", "-", "--null", "--get-all", "remote.origin.url"],
                input=config, capture_output=True, timeout=5, cwd="/",
                env={"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
            )
            if origin.returncode or origin.stdout != ("git@github.com:" + slug + ".git\0").encode():
                raise Refusal("the selected Git config must contain the single original scaffold origin")
            records = registration_records(selected)
            current = hold(absolute_directory(checkout))
            current_git = hold(child_directory(current, (".git",)))
            if (not os.path.samestat(os.fstat(current), os.fstat(selected))
                    or not os.path.samestat(os.fstat(current_git), os.fstat(git))
                    or read_regular(current_git, state_name) != saved or read_regular(current_git, "config") != config
                    or registration_records(current) != records):
                raise Refusal("the selected checkout changed during inspection")
    except (OSError, ValueError, RecursionError, subprocess.SubprocessError):
        raise Refusal("could not read a stable personal scaffold at the selected path") from None
    data = {"ok": True, "scope": "personal-scaffold", "path": str(checkout), "repository": slug,
            "recorded_repository_id": recorded_id, "creation_binding_matches": True,
            "creation_record_sha256": sha256_hex(saved), "linked_registrations": len(records),
            "registrations_sha256": digest_of(sorted(registration_binding(k, v) for k, v in records.items())),
            "removal_ready": False}
    return data, [slug + ": the creation record matches this checkout and Git directory.",
                  "Linked registrations in the primary checkout: %d." % len(records),
                  "Preserve the original directories for scaffold resume. Removal readiness is unverified."], EXIT_OK


def checked_worktree_list(ctx, path):
    """Git can omit an incomplete registration from a successful porcelain listing."""
    fd, parent = open_chain(ctx, os.path.relpath(path, ctx.root).split("/"))
    try:
        records = registration_records(fd)
        result = _git(ctx, path, "worktree", "list", "--porcelain", "-z")
        if not result.ok:
            raise Refusal("Git could not list worktrees")
        listing = parse_worktrees(result.out)
        expected = registration_paths(records, os.path.join(path, ".git", "worktrees"))
        if (not listing or listing[0].get("path") != path
                or sorted(r.get("path", "") for r in listing[1:]) != sorted(expected)
                or registration_records(fd) != records):
            raise Refusal("Git's worktree listing does not match the registration table")
        return listing, records
    finally:
        os.close(fd)
        if parent is not None:
            os.close(parent)


def tombstone_name(operation_id, step_id, rel):
    return ".drr-%s.removing" % sha256_hex("%s:%s:%s" % (operation_id, step_id, rel))[:16]


def tombstone_rel(rel, name):
    parent = rel.rsplit("/", 1)[0]
    return parent + "/" + name


def delete_tree(ctx, base, comps, expected_identity, hook=None, tombstone=None, guard=None):
    """Remove one whole directory tree through a no-follow descriptor chain.

    With a tombstone name the directory is first renamed (atomically, same parent) so the real path
    disappears at once; an interrupted run continues deleting that exact tombstone. Idempotent.
    `guard(path, fd)` runs after the directory is renamed and opened, and before anything inside it is
    deleted; it raises Refusal to stop (the marker stays so a later resume can finish the job).
    """
    try:
        parent_fd_holder = open_chain(ctx, comps[:-1], base)
    except PathProblem as exc:
        if exc.code == "absent":
            return {"absent": True, "entries": 0}
        raise Refusal("cannot reach the checkout safely: %s" % exc.message)
    parent_fd, grand = parent_fd_holder
    try:
        name = comps[-1]
        work = None
        if tombstone:
            try:
                tl = os.lstat(tombstone, dir_fd=parent_fd)
            except FileNotFoundError:
                tl = None
            if tl is not None:
                if stat.S_ISLNK(tl.st_mode) or not stat.S_ISDIR(tl.st_mode):
                    raise Refusal("a leftover removal marker is not a plain directory; refusing to touch it")
                work = tombstone
        if work is None:
            try:
                lst = os.lstat(name, dir_fd=parent_fd)
            except FileNotFoundError:
                return {"absent": True, "entries": 0}
            if stat.S_ISLNK(lst.st_mode):
                raise Refusal("the checkout path is now a symbolic link; refusing to follow it")
            if not stat.S_ISDIR(lst.st_mode):
                raise Refusal("the checkout path is no longer a directory")
            if expected_identity and (lst.st_dev, lst.st_ino) != (expected_identity["dev"], expected_identity["ino"]):
                raise Refusal("the checkout is not the directory that was previewed (its identity changed)")
            if tombstone:
                try:
                    os.rename(name, tombstone, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                except OSError as exc:
                    raise _remove_failure(name, exc)
                work = tombstone
                if hook is not None:
                    hook("renamed", {"entries": 0})
            else:
                work = name
        try:
            tfd = os.open(work, O_DIR_NOFOLLOW, dir_fd=parent_fd)
        except OSError as exc:
            raise _remove_failure(work, exc)
        try:
            st = os.fstat(tfd)
            if expected_identity and (st.st_dev, st.st_ino) != (expected_identity["dev"], expected_identity["ino"]):
                raise Refusal("the checkout is not the directory that was previewed (its identity changed)")
            if st.st_uid != os.geteuid():
                raise Refusal("the checkout is owned by another user")
            if guard is not None:
                guard(os.path.join(ctx.root, *comps[:-1], work) if base == ctx.root else work, tfd)
            _make_writable(tfd, st)
            counters = {"entries": 0}
            _rm_contents(tfd, st.st_dev, counters, hook)
        finally:
            os.close(tfd)
        try:
            os.rmdir(work, dir_fd=parent_fd)
        except OSError as exc:
            raise _remove_failure(work, exc)
        return {"absent": False, "entries": counters["entries"] + 1}
    finally:
        os.close(parent_fd)
        if grand is not None:
            os.close(grand)


def delete_checkout(ctx, rel, expected_identity, hook=None, tombstone=None, guard=None):
    return delete_tree(ctx, ctx.root, rel.split("/"), expected_identity, hook, tombstone, guard)


def unlink_link_nofollow(ctx, link_path, expected_readlink):
    """Remove one symbolic link under the home folder through a no-follow chain. False when it is already gone."""
    prefix = ctx.home + "/"
    if not link_path.startswith(prefix):
        raise Refusal("the link %s is outside the home folder; refusing to touch it" % link_path)
    comps = link_path[len(prefix):].split("/")
    if any(c in ("", ".", "..") for c in comps):
        raise Refusal("the link path is not in canonical form; refusing to touch it")
    try:
        fd, parent = open_chain(ctx, comps[:-1], ctx.home)
    except PathProblem as exc:
        if exc.code == "absent":
            return False
        raise Refusal("cannot reach the folder holding %s safely: %s" % (link_path, exc.message))
    try:
        name = comps[-1]
        try:
            st = os.lstat(name, dir_fd=fd)
        except FileNotFoundError:
            return False
        if not stat.S_ISLNK(st.st_mode) or os.readlink(name, dir_fd=fd) != expected_readlink:
            raise Refusal("the link %s is no longer the one that was previewed" % link_path)
        os.unlink(name, dir_fd=fd)
        return True
    finally:
        os.close(fd)
        if parent is not None:
            os.close(parent)


def lexists_nofollow(path):
    try:
        os.lstat(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True


def lexists_under(ctx, rel):
    """True when anything (even a broken link) occupies root/rel, checked without following links."""
    return lexists_nofollow(os.path.join(ctx.root, rel))


TOMBSTONE_RE = re.compile(r"^\.drr-[0-9a-f]{16}\.removing$")


def markers_beside(ctx, comps):
    """Unfinished-removal markers in the same folder as a checkout path (an interrupted removal left them)."""
    try:
        names = os.listdir(os.path.join(ctx.root, *comps[:-1]))
    except OSError:
        return []
    return sorted(name for name in names if TOMBSTONE_RE.match(name))


def marker_owners(ctx):
    """{marker name: set of checkouts} for every removal marker the delete steps of a recorded operation could have made.

    A record that cannot be read, or that no longer matches its journal, attributes nothing: its markers stay unexplained."""
    owners = {}
    for op_id in list_operation_ids(ctx):
        try:
            op, _journal, _view = load_operation(ctx, op_id, strict=False)
            steps = [s for s in op["steps"] if s["kind"] == "delete-checkout"]
            names = [(tombstone_name(op_id, s["id"], s["params"]["rel"]), s["params"]["rel"]) for s in steps]
        except (Refusal, ValueError, KeyError, TypeError):
            continue
        for name, rel in names:
            owners.setdefault(name, set()).add(rel)
    return owners


def leftover_tombstones(ctx):
    found = []
    for parent in ALLOWED_PARENTS:
        try:
            names = os.listdir(os.path.join(ctx.root, *parent))
        except OSError:
            continue
        for name in names:
            if TOMBSTONE_RE.match(name):
                found.append("/".join(parent) + "/" + name)
    return sorted(found)



# --------------------------------------------------------------------------- facts: git, writers, wiring

RISK_TEXT = {
    "dirty-tracked": "uncommitted changes to tracked files would be lost",
    "untracked-files": "untracked files that exist nowhere else would be lost",
    "ignored-data": "git-ignored files (local data, secrets, build output) would be lost",
    "unpushed-commits": "commits that are not on any remote would be lost",
    "stashes": "stashed work would be lost",
    "nested-repos": "nested repositories or submodules would be lost; their own state is not assessed here",
    "operation-in-progress": "an unfinished Git operation (merge, rebase, cherry-pick, bisect) would be abandoned",
    "linked-worktree-work": "uncommitted work in a linked worktree would be lost",
    "consumer-mentions": "other retained files reference this checkout's path and would be left dangling",
    "writer-proof-unavailable": "this machine could not prove that nothing is writing to the checkout",
    "scan-incomplete": "the search for files that mention this checkout could not read everything, so some mentions may be missing",
}
RISK_IDS = tuple(RISK_TEXT)

STATUS_UNMERGED = ("DD", "AU", "UD", "UA", "DU", "AA", "UU")
GIT_STATE_NAMES = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "rebase-merge", "rebase-apply")
LINK_DIRS_HOME = (
    ".cursor/skills",
    ".claude/skills",
    ".codex/skills",
    ".agents/skills",
    ".cursor/rules",
    ".cursor/commands",
    ".claude/commands",
    ".claude/agents",
    ".cursor/agents",
)
LINK_WALK_SECONDS = 120
CACHE_ALLOW = ("agent-tools", "assets", "canvases", "mcps", "terminals")
KEEP_PROJECT_ENTRIES = ("agent-transcripts",)


def is_under(path, base):
    return path == base or path.startswith(base.rstrip("/") + "/")


def _git(ctx, repo, *args, **kw):
    return run(git_argv(ctx, repo, *args), env=git_env(), timeout=kw.get("timeout", SUBPROCESS_TIMEOUT))


def parse_status_z(raw):
    counts = {"tracked": 0, "staged": 0, "unstaged": 0, "untracked": 0, "ignored": 0, "conflicted": 0}
    samples = {"tracked": [], "untracked": [], "ignored": []}
    toks = raw.split(b"\0")
    kept = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        i += 1
        if len(tok) < 4:
            continue
        xy = tok[:2].decode("ascii", "replace")
        path = os.fsdecode(tok[3:])
        kept.append(tok)
        if xy[0] in "RC" or xy[1] in "RC":
            if i < len(toks):
                kept.append(toks[i])
            i += 1
        if xy == "!!":
            counts["ignored"] += 1
            bucket = "ignored"
        elif xy == "??":
            counts["untracked"] += 1
            bucket = "untracked"
        else:
            counts["tracked"] += 1
            bucket = "tracked"
            if xy[0] not in " ":
                counts["staged"] += 1
            if xy[1] not in " ":
                counts["unstaged"] += 1
            if xy in STATUS_UNMERGED:
                counts["conflicted"] += 1
        if len(samples[bucket]) < 5:
            samples[bucket].append(jstr(path)[:120])
    return counts, samples, sha256_hex(b"\0".join(sorted(kept)))


def parse_worktrees(raw):
    records, cur = [], {}
    for tok in raw.split(b"\0"):
        if not tok:
            if cur:
                records.append(cur)
                cur = {}
            continue
        text = os.fsdecode(tok)
        key, _, value = text.partition(" ")
        if key == "worktree":
            if cur:
                records.append(cur)
            cur = {"path": value}
        elif cur is not None:
            if key in ("locked", "prunable", "detached", "bare"):
                cur[key] = value or True
            else:
                cur[key] = value
    if cur:
        records.append(cur)
    return records


def _count_commits(ctx, path, *args):
    res = _git(ctx, path, "rev-list", "--count", *args)
    text = res.text.strip()
    return int(text) if res.ok and text.isdigit() else None


GIT_PRIVATE_FILES = ("config", "HEAD", "shallow", "info/exclude", "info/attributes", "info/sparse-checkout")
GIT_PRIVATE_DIRS = ("hooks", "info")


def git_private_digest(gitdir):
    """Stat-only digest of the repository's own settings and scripts: never contents, never through a link.

    The working-tree fingerprint leaves .git out because Git rewrites its index, packs and logs all the
    time. These few entries change only when somebody edits them on purpose, so a change after the
    preview is a real change. Linked-worktree bookkeeping is left out: planned removals change it.
    """
    rows = []

    def entry(rel):
        try:
            st = os.lstat(os.path.join(gitdir, rel))
        except FileNotFoundError:
            return None
        except OSError as exc:
            rows.append([rel, "unreadable", exc.errno])
            return None
        rows.append([rel, stat.S_IFMT(st.st_mode), st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_ino, stat.S_IMODE(st.st_mode)])
        return st

    for rel in GIT_PRIVATE_FILES:
        entry(rel)
    for rel in GIT_PRIVATE_DIRS:
        st = entry(rel)
        if st is None or not stat.S_ISDIR(st.st_mode):
            continue
        try:
            names = sorted(os.listdir(os.path.join(gitdir, rel)))
        except OSError:
            rows.append([rel + "/", "unlistable"])
            continue
        for name in names:
            if rel == "hooks" and name.endswith(".sample"):
                continue
            entry(rel + "/" + name)
    try:
        rows.append(["modules/", sorted(os.listdir(os.path.join(gitdir, "modules")))])
    except OSError:
        pass
    return digest_of(rows)


def collect_git(ctx, path):
    """Read-only Git inventory. Counts and digests only; never contents. No network."""
    out = {"error": None}
    probe = _git(ctx, path, "rev-parse", "--absolute-git-dir")
    if not probe.ok:
        out["error"] = "git could not read the repository (%s)" % (short_err(probe.errtext) or probe.error or "unknown")
        return out
    gitdir = probe.text.strip()
    out["gitdir"] = gitdir
    head = _git(ctx, path, "rev-parse", "--verify", "-q", "HEAD")
    out["head"] = head.text.strip() if head.ok else None
    branch = _git(ctx, path, "symbolic-ref", "-q", "--short", "HEAD")
    out["branch"] = branch.text.strip() if branch.ok else None
    status = _git(ctx, path, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching")
    if not status.ok:
        out["error"] = "git status failed (%s)" % (short_err(status.errtext) or status.error or "unknown")
        return out
    counts, samples, sdigest = parse_status_z(status.out)
    out["status_counts"], out["samples"], out["status_digest"] = counts, samples, sdigest
    refs = _git(ctx, path, "for-each-ref", "--format=%(refname) %(objectname)")
    if not refs.ok:
        out["error"] = "git could not list refs"
        return out
    out["refs_digest"] = sha256_hex(refs.out)
    remotes = []
    cfg = _git(ctx, path, "config", "--local", "-z", "--get-regexp", r"^remote\..+\.url$")
    if cfg.ok:
        # With -z git prints one entry as "key\nvalue\0": a newline between key and value, a NUL after the value.
        for rec in cfg.out.split(b"\0"):
            if not rec:
                continue
            key, _, value = os.fsdecode(rec).partition("\n")
            name = key[len("remote."):-len(".url")]
            remotes.append({"name": name, "url": redact_url(value)})
    remotes.sort(key=lambda r: (r["name"], r["url"]))
    out["remotes"] = remotes
    slugs = sorted({origin_slug(r["url"]).lower() for r in remotes if origin_slug(r["url"])})
    out["slugs"] = slugs
    branch_unpushed = _count_commits(ctx, path, "--branches", "--not", "--remotes")
    tag_unpushed = _count_commits(ctx, path, "--tags", "--not", "--branches", "--remotes")
    detached = 0
    if out["head"] and not out["branch"]:
        detached = _count_commits(ctx, path, "HEAD", "--not", "--branches", "--remotes")
    if None in (branch_unpushed, tag_unpushed, detached):
        out["error"] = "git could not count unpushed commits"
        return out
    out["unpushed"] = {"branch_commits": branch_unpushed, "tag_commits": tag_unpushed, "detached_commits": detached}
    out["unpushed_total"] = branch_unpushed + tag_unpushed + detached
    stash = _git(ctx, path, "stash", "list")
    if not stash.ok:
        out["error"] = "git could not list stashes"
        return out
    out["stashes"] = len([ln for ln in stash.text.splitlines() if ln.strip()])
    try:
        listing, out["registrations"] = checked_worktree_list(ctx, path)
    except (Refusal, PathProblem) as exc:
        out["error"] = exc.message
        return out
    out["worktrees"] = listing[1:]
    state = []
    for name in GIT_STATE_NAMES:
        if lexists_nofollow(os.path.join(gitdir, name)):
            state.append(name)
    out["operation_state"] = state
    out["index_locked"] = lexists_nofollow(os.path.join(gitdir, "index.lock"))
    out["private_digest"] = git_private_digest(gitdir)
    return out


def git_aspect_digest(g):
    return digest_of(
        {
            "head": g.get("head"),
            "branch": g.get("branch"),
            "status": g.get("status_counts"),
            "status_digest": g.get("status_digest"),
            "refs": g.get("refs_digest"),
            "remotes": g.get("remotes"),
            "unpushed": g.get("unpushed"),
            "stashes": g.get("stashes"),
            "state": g.get("operation_state"),
            "private": g.get("private_digest"),
        }
    )


def classify_worktree_location(ctx, path):
    if is_under(path, os.path.join(ctx.home, ".local", "share", "awa", "worktrees")):
        return "awa"
    if is_under(path, os.path.join(ctx.home, ".cursor", "worktrees")):
        return "cursor"
    return "other"


def worktree_location_problem(ctx, path):
    """Why a linked worktree outside its checkout may not be removed automatically; None when it may.

    Git's worktree list is repository-controlled metadata, so it is never trusted on its own: the
    path must sit somewhere this home owns, must not contain home or ~/dev, and must look like a
    linked worktree (a plain .git file, never a directory that makes it a repository of its own)."""
    if not isinstance(path, str) or not os.path.isabs(path) or os.path.normpath(path) != path:
        return "its recorded path is not a clean absolute path"
    for base in (ctx.root, ctx.home, os.sep):
        if is_under(base, path):
            return "it would contain your home folder or ~/dev"
    if classify_worktree_location(ctx, path) == "other" and not is_under(path, ctx.root):
        return "it is outside ~/dev and outside the Cursor and AWA worktree folders"
    try:
        mode = os.lstat(os.path.join(path, ".git")).st_mode
    except OSError:
        return "it has no .git file, so it is not a linked worktree"
    if not stat.S_ISREG(mode):
        return "its .git is not a plain file, so it is not a linked worktree"
    return None


def worktree_state(ctx, path):
    """The facts about one linked worktree that must not change between preview and removal."""
    state = {
        "path": path,
        "exists": lexists_nofollow(path),
        "symlink": os.path.islink(path),
        "head": None,
        "dirty": 0,
        "untracked": 0,
    }
    if state["exists"] and not state["symlink"] and os.path.isdir(path):
        res = _git(ctx, path, "status", "--porcelain=v1", "-z", "--untracked-files=all")
        if res.ok:
            counts, _s, _d = parse_status_z(res.out)
            state["dirty"], state["untracked"] = counts["tracked"], counts["untracked"]
        else:
            state["unreadable"] = True
        head = _git(ctx, path, "rev-parse", "--verify", "-q", "HEAD")
        state["head"] = head.text.strip() if head.ok else None
    return state


def worktree_gitdir(ctx, path):
    """The Git directory that holds one linked worktree's own bookkeeping (where its session lock lives)."""
    res = _git(ctx, path, "rev-parse", "--absolute-git-dir")
    text = res.text.strip() if res.ok else ""
    return text if text.startswith("/") else None


def worktree_aspect_digest(state):
    return digest_of(state)


def worktree_detail(ctx, record, target_path):
    path = record.get("path", "")
    info = worktree_state(ctx, path)
    info.update(
        {
            "inside_target": is_under(path, target_path),
            "managed_by": classify_worktree_location(ctx, path),
            "branch": (record.get("branch") or "").replace("refs/heads/", "") or None,
            "locked": bool(record.get("locked")),
            "prunable": bool(record.get("prunable")),
        }
    )
    info["aspect"] = worktree_aspect_digest(worktree_state_view(info))
    return info


def worktree_state_view(info):
    keys = ("path", "exists", "symlink", "head", "dirty", "untracked", "unreadable")
    return {k: info[k] for k in keys if k in info}


# ----- writers

def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, OverflowError):
        return False


def process_ancestors(ctx):
    if "ancestors" in ctx.cache:
        return ctx.cache["ancestors"]
    found = set()
    ps = ctx.tool("ps")
    pid = os.getpid()
    if ps:
        for _ in range(64):
            found.add(pid)
            res = run([ps, "-o", "ppid=", "-p", str(pid)], timeout=10)
            text = res.text.strip() if res.ok else ""
            if not text.isdigit() or int(text) <= 1:
                break
            pid = int(text)
    else:
        found.add(pid)
    ctx.cache["ancestors"] = found
    return found


def lsof_snapshot(ctx):
    if "lsof" in ctx.cache:
        return ctx.cache["lsof"]
    tool = ctx.tool("lsof")
    snap = {"ok": False, "reason": "lsof is not installed", "rows": []}
    if tool:
        res = run([tool, "-nP", "-w", "-F", "pcfn"], timeout=LSOF_TIMEOUT)
        if res.timed_out:
            snap["reason"] = "lsof timed out"
        elif res.error:
            snap["reason"] = "lsof could not run (%s)" % res.error
        elif res.rc not in (0, 1) or (res.rc == 1 and not res.out):
            snap["reason"] = "lsof failed (exit %s)" % res.rc
        else:
            rows = []
            pid, command, fd = None, "", ""
            for line in res.out.split(b"\n"):
                if not line:
                    continue
                tag, value = chr(line[0]), line[1:]
                if tag == "p":
                    pid = int(value) if value.isdigit() else None
                    command, fd = "", ""
                elif tag == "c":
                    command = value.decode("utf-8", "replace")
                elif tag == "f":
                    fd = value.decode("utf-8", "replace")
                elif tag == "n" and pid is not None and value.startswith(b"/"):
                    rows.append((pid, command, fd, os.fsdecode(value)))
            snap = {"ok": True, "reason": "", "rows": rows}
    ctx.cache["lsof"] = snap
    return snap


def writers_for(ctx, path, also=()):
    """Processes using anything under `path` (or under any alternate spelling in `also`)."""
    snap = lsof_snapshot(ctx)
    paths = (path,) + tuple(also)
    ancestors = process_ancestors(ctx)
    me = os.getpid()
    grouped = {}
    for pid, command, fd, name in snap["rows"]:
        if pid == me or not any(is_under(name, p) for p in paths):
            continue
        entry = grouped.setdefault(pid, {"pid": pid, "command": command, "kinds": set(), "ancestor": pid in ancestors})
        entry["kinds"].add("cwd" if fd == "cwd" else "program" if fd == "txt" else "open")
    rows = []
    for pid in sorted(grouped):
        entry = grouped[pid]
        entry["kinds"] = sorted(entry["kinds"])
        rows.append(entry)
    return {"proof": snap["ok"], "reason": snap["reason"], "processes": rows}


def session_lock_state(ctx, gitdir):
    text = read_text_nofollow(os.path.join(gitdir, "cursor-session.lock"), limit=4096)
    if text is None:
        return None
    kv = {}
    for line in text.splitlines():
        key, _, value = line.partition("=")
        kv[key.strip()] = value.strip()
    pid = kv.get("pid", "")
    ts = int(kv["ts"]) if kv.get("ts", "").isdigit() else 0
    ttl = int(os.environ.get("DEV_SESSION_LOCK_TTL_SECS") or 28800)
    age = int(ctx.now()) - ts if ts else None
    alive = pid_alive(pid) if pid.isdigit() else False
    live = alive and (age is None or age < ttl)
    return {"live": bool(live), "pid": pid, "age_seconds": age, "token_kind": kv.get("token", "").split(":")[0]}


def fleet_slugs(ctx):
    text = read_text_nofollow(os.path.join(ctx.root, "_ops", "baseline", "profiles", "pr-automation", "v3", "fleet.json"))
    if text is None:
        return {"available": False, "slugs": set()}
    try:
        data = json.loads(text)
    except ValueError:
        return {"available": False, "slugs": set()}
    targets = data.get("targets") if isinstance(data, dict) else None
    if not isinstance(targets, list):
        return {"available": False, "slugs": set()}
    slugs = set()
    for row in targets:
        name = row.get("repo") if isinstance(row, dict) else None
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name):
            return {"available": False, "slugs": set()}
        slugs.add(name.lower())
    return {"available": True, "slugs": slugs}


def policy_marker_present(ctx):
    """The exception is in force only when POLICY.md carries the exact marker comment on a line of its own."""
    text = read_text_nofollow(os.path.join(ctx.root, POLICY_FILE))
    if not text:
        return False
    wanted = "<!-- %s -->" % POLICY_MARKER
    return any(line.strip() == wanted for line in text.splitlines())


# ----- wiring

def _project_dir_name(abs_path):
    return re.sub(r"[^A-Za-z0-9]+", "-", abs_path).strip("-")


def collect_links(ctx, target_paths, cov, skip_paths=None):
    """Symlinks in client skill/rule folders, in config and startup surfaces, and anywhere in the retained trees that resolve into a target.

    The retained walk covers every folder under the dev root except the folders in `skip_paths` (default: the targets
    themselves), checkouts set aside under a removal marker, the reference-only vendor clones and the dependency and
    cache folders the mention search also skips.
    A folder it cannot list, and a stop at the time limit, are recorded in `cov`, so a walk with gaps is never reported
    as complete."""
    hits = []
    skip_paths = list(target_paths if skip_paths is None else skip_paths)

    def consider(entry_path, kind):
        try:
            raw = os.readlink(entry_path)
        except OSError:
            return
        real = os.path.realpath(entry_path)
        lexical = os.path.normpath(raw if os.path.isabs(raw) else os.path.join(os.path.dirname(entry_path), raw))
        for tpath in target_paths:
            if is_under(real, tpath) or is_under(lexical, tpath):
                hits.append({"kind": kind, "link": entry_path, "readlink": jstr(raw), "target_path": tpath})
                break

    def list_dir(path):
        try:
            return list(os.scandir(path))
        except (FileNotFoundError, NotADirectoryError):
            return []
        except OSError:
            note_unreadable(cov, path)
            return []

    for sub in LINK_DIRS_HOME:
        for entry in list_dir(os.path.join(ctx.home, sub)):
            if entry.is_symlink():
                consider(entry.path, "client-link")
            elif entry.is_dir(follow_symlinks=False):
                for child in list_dir(entry.path):
                    if child.is_symlink():
                        consider(child.path, "client-link")
    for link in surface_symlinks(ctx):
        consider(link, "surface-link")
    vendor = os.path.join(ctx.root, "affirm", "vendor")
    deadline = time.monotonic() + LINK_WALK_SECONDS
    stack = [ctx.root]
    while stack:
        if time.monotonic() > deadline:
            cov["deadline"] = True
            break
        for entry in list_dir(stack.pop()):
            if entry.is_symlink():
                if not any(is_under(entry.path, sp) for sp in skip_paths):
                    consider(entry.path, "retained-link")
            elif entry.is_dir(follow_symlinks=False) and entry.name not in PY_SKIP_DIRS:
                if entry.path == vendor or TOMBSTONE_RE.match(entry.name) or any(is_under(entry.path, sp) for sp in skip_paths):
                    continue
                stack.append(entry.path)
    hits.sort(key=lambda h: (h["kind"], h["link"]))
    return hits


def link_aspect_digest(link_path):
    try:
        st = os.lstat(link_path)
    except FileNotFoundError:
        return None
    if not stat.S_ISLNK(st.st_mode):
        return digest_of({"type": "not-a-link"})
    return digest_of({"readlink": os.readlink(link_path), "ino": st.st_ino})


def local_jobs_instances(ctx):
    """Read-only inventory through the owning verb. Returns (available, instances|None)."""
    if "jobs" in ctx.cache:
        return ctx.cache["jobs"]
    adapter = ctx.adapter("local-jobs")
    result = (False, None)
    if adapter:
        res = run([adapter, "view-jobs", "--json"], timeout=SUBPROCESS_TIMEOUT)
        if res.ok:
            try:
                data = json.loads(res.text)
            except ValueError:
                raise Refusal("Local Jobs returned an unreadable inventory; repair discovery and retry.")
            if isinstance(data, dict) and data.get("overlay_errors"):
                raise Refusal("Local Jobs reported a registry overlay error; repair discovery and retry.")
            instances = data.get("instances") if isinstance(data, dict) else data
            if not isinstance(instances, list) or any(not isinstance(row, dict) for row in instances):
                raise Refusal("Local Jobs returned an invalid instance inventory; repair discovery and retry.")
            if any(row.get("role") == "error" for row in instances):
                raise Refusal("Local Jobs could not inventory a quarantined job type; repair discovery and retry.")
            # Several global schedulers may share a sentinel. A deletable ID must be unique.
            seen = {}
            for row in instances:
                job_id = row.get("id")
                if isinstance(job_id, str) and job_id:
                    global_row = row.get("role") == "global_scheduler"
                    if job_id in seen and not (seen[job_id] and global_row):
                        raise Refusal("Local Jobs reported an ambiguous instance id; repair discovery and retry.")
                    seen[job_id] = global_row
            result = (True, instances)
    ctx.cache["jobs"] = result
    return result


def job_is_dedicated_to(instance, checkout):
    """Only a single-checkout owner record can authorize a job deletion."""
    revision = instance.get("removal_revision")
    return (instance.get("role") == "instance" and instance.get("type") == "incremental-git-fetch"
            and instance.get("path") == checkout and instance.get("schedule") == "inherit"
            and isinstance(revision, str) and re.fullmatch("[0-9a-f]{64}", revision) is not None)


def job_aspect_digest(instance):
    return digest_of({k: instance.get(k) for k in sorted(instance) if k not in ("launchd_loaded", "last_run", "next_run", "status")})


def cache_aspect_digest(ctx, encoded, name):
    """Identity of one Cursor cache folder: what it is and which directory entry it is."""
    try:
        st = os.lstat(os.path.join(ctx.home, ".cursor", "projects", encoded, name))
    except OSError:
        return None
    return digest_of([name, stat.S_IFMT(st.st_mode), st.st_ino])


def project_folder_claims(ctx, target_paths):
    """Entries that stay in place whose Cursor project folder name is spelled the same as a folder's in `target_paths` could be.

    Cursor writes a path into a folder name by turning every run of other characters into one dash, so `foo-bar`,
    `foo_bar` and `foo.bar` (or `personal/x` and `personal-x`) all share one project folder. The places a lookalike
    can sit are the dev root, `affirm/` and the folders that hold checkouts. Returns {encoded name: [relative paths]}."""
    targets = set(target_paths)
    claimed = {}
    for parent in [(), ("affirm",)] + sorted(ALLOWED_PARENTS):
        try:
            listing = os.listdir(os.path.join(ctx.root, *parent))
        except OSError:
            continue
        for name in listing:
            path = os.path.join(ctx.root, *parent, name)
            if path in targets or TOMBSTONE_RE.match(name):
                continue
            claimed.setdefault(_project_dir_name(path), []).append("/".join(parent + (name,)))
    return claimed


def collect_project_dirs(ctx, target_paths):
    """Cursor project caches named exactly after a target path (no fuzzy matching).

    The folder holding them is reached through a no-follow chain, so a symlinked ~/.cursor or
    ~/.cursor/projects is skipped rather than followed. A project folder that a checkout staying in place also
    maps to (see `project_folder_claims`) is reported as shared and none of its caches are planned for removal."""
    base = os.path.join(ctx.home, ".cursor", "projects")
    found = []
    try:
        fd, parent = open_chain(ctx, [".cursor", "projects"], ctx.home)
    except PathProblem:
        return found
    try:
        names = set(os.listdir(fd))
    except OSError:
        names = set()
    finally:
        os.close(fd)
        if parent is not None:
            os.close(parent)
    claims = project_folder_claims(ctx, target_paths)
    seen = set()
    for tpath in target_paths:
        encoded = _project_dir_name(tpath)
        if encoded not in names or encoded in seen:
            continue
        seen.add(encoded)  # two targets that share one folder are both being removed: it is planned once
        pdir = os.path.join(base, encoded)
        try:
            lst = os.lstat(pdir)
        except OSError:
            continue
        if stat.S_ISLNK(lst.st_mode) or not stat.S_ISDIR(lst.st_mode):
            continue
        try:
            entries = sorted(os.listdir(pdir))
        except OSError:
            entries = []
        shared = sorted(claims.get(encoded, []))
        caches = [] if shared else [e for e in entries if e in CACHE_ALLOW]
        found.append(
            {
                "target_path": tpath,
                "encoded": encoded,
                "path": pdir,
                "shared_with": shared,
                "caches": caches,
                "cache_aspects": {name: cache_aspect_digest(ctx, encoded, name) for name in caches},
                "kept": [e for e in entries if e in KEEP_PROJECT_ENTRIES],
                "other": [e for e in entries if e not in CACHE_ALLOW and e not in KEEP_PROJECT_ENTRIES],
            }
        )
    return found



# --------------------------------------------------------------------------- scan: mentions of removed checkouts

SURFACE_FILES = (
    (".cursor/mcp.json", "client-config"),
    (".cursor/hooks.json", "client-config"),
    (".claude.json", "client-config"),
    (".claude/settings.json", "client-config"),
    (".claude/settings.local.json", "client-config"),
    (".codex/config.toml", "client-config"),
    ("AGENTS.md", "generated-memory"),
    ("agent-learnings.md", "generated-memory"),
    (".zshrc", "launchd-shell"),
    (".zprofile", "launchd-shell"),
    (".zshenv", "launchd-shell"),
    (".bashrc", "launchd-shell"),
    (".bash_profile", "launchd-shell"),
    (".profile", "launchd-shell"),
    (".gitconfig", "git-config"),
    (".config/git/config", "git-config"),
    (".agent-route/index.json", "agent-route"),
)
SURFACE_DIRS = (
    ("Library/LaunchAgents", "launchd-shell", "*.plist"),
    (".local-jobs", "local-jobs", None),
    (".local/state/dev-main-sync", "shadowsync", None),
)
PY_SKIP_DIRS = frozenset([".git", "node_modules", ".venv", "venv", "__pycache__", ".tox"])
RG_CHUNK = 400
SCAN_DEADLINE_SECONDS = 600


def new_coverage():
    """What the search could not read. A search with gaps is reported as incomplete, never as clean."""
    return {"unreadable": [], "unreadable_total": 0, "oversized": 0, "deadline": False, "seen": set()}


def note_unreadable(cov, path):
    """Record a path the search could not read, once however many parts of the search hit it (the first 1000 are tracked)."""
    key = jstr(path)
    if key in cov["seen"]:
        return
    if len(cov["seen"]) < 1000:
        cov["seen"].add(key)
    cov["unreadable_total"] += 1
    if len(cov["unreadable"]) < 25:
        cov["unreadable"].append(key)


def coverage_incomplete(cov):
    return bool(cov["unreadable_total"] or cov["deadline"])


def surface_paths(ctx, classes=None):
    """The generated-config surfaces that exist under the home directory, optionally only some classes of them.

    A config or startup file that is a link to a regular file is read through the link (it is a fixed, known path, and
    skipping it would hide a reference); a link to a folder is never walked (see `scan_scope`)."""
    surface_files = []
    for rel, klass in SURFACE_FILES:
        if classes and klass not in classes:
            continue
        p = os.path.join(ctx.home, rel)
        if os.path.isfile(p):
            surface_files.append((p, klass))
    surface_dirs = []
    for rel, klass, glob in SURFACE_DIRS:
        if classes and klass not in classes:
            continue
        p = os.path.join(ctx.home, rel)
        if os.path.isdir(p) and not os.path.islink(p):
            surface_dirs.append((p, klass, glob))
    return surface_files, surface_dirs


def surface_symlinks(ctx):
    """Symbolic links among the config, startup and launch-agent surfaces (files, and entries inside the surface folders)."""
    found = []
    for rel, _klass in SURFACE_FILES:
        p = os.path.join(ctx.home, rel)
        if os.path.islink(p):
            found.append(p)
    for rel, _klass, _glob in SURFACE_DIRS:
        base = os.path.join(ctx.home, rel)
        if os.path.islink(base) or not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
            for name in dirnames + filenames:
                p = os.path.join(dirpath, name)
                if os.path.islink(p):
                    found.append(p)
    return sorted(found)


def scan_scope(ctx, exclude_paths):
    """Retained roots + generated-config surfaces. affirm/vendor is reference-only and not scanned."""
    exclude = [p for p in exclude_paths if p]
    repo_roots = []
    unreadable = []
    for parent in (("affirm", "src"), ("personal",), ("capabilities",)):
        base = os.path.join(ctx.root, *parent)
        try:
            names = sorted(os.listdir(base))
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            unreadable.append(base)
            continue
        for name in names:
            path = os.path.join(base, name)
            if os.path.islink(path) or not os.path.isdir(path):
                continue
            if TOMBSTONE_RE.match(name):
                continue  # a checkout set aside under its removal marker is already part of an approved removal, not a retained repository
            if any(is_under(path, e) for e in exclude):
                continue
            repo_roots.append(path)
    umbrella = []
    git = ctx.tool("git")
    listed = False
    if git and os.path.isdir(os.path.join(ctx.root, ".git")):
        res = run(git_argv(ctx, ctx.root, "ls-files", "-z"), env=git_env(), timeout=SUBPROCESS_TIMEOUT)
        if res.ok:
            listed = True
            for rec in res.out.split(b"\0"):
                if rec:
                    p = os.path.join(ctx.root, os.fsdecode(rec))
                    if not any(is_under(p, e) for e in exclude):
                        umbrella.append(p)
    if not listed:
        for entry in sorted(os.scandir(ctx.root), key=lambda e: e.name):
            if entry.name in (".git", "affirm", "personal", "capabilities"):
                continue
            if entry.is_file(follow_symlinks=False):
                umbrella.append(entry.path)
            elif entry.is_dir(follow_symlinks=False) and entry.name in ("_ops", "docs", "config"):
                for dirpath, dirnames, filenames in os.walk(entry.path):
                    dirnames[:] = [d for d in dirnames if d not in PY_SKIP_DIRS]
                    for fn in filenames:
                        umbrella.append(os.path.join(dirpath, fn))
    memory = []
    for cand in [os.path.join(ctx.root, "agent-learnings.md")] + [os.path.join(r, "agent-learnings.md") for r in repo_roots]:
        if os.path.isfile(cand) and not os.path.islink(cand):
            memory.append(cand)
    surface_files, surface_dirs = surface_paths(ctx)
    for rel, _klass, _glob in SURFACE_DIRS:
        p = os.path.join(ctx.home, rel)
        if os.path.islink(p) and os.path.isdir(p):
            unreadable.append(p)  # a link to a folder is never walked, so it is reported as not searched
    return {
        "repo_roots": repo_roots,
        "umbrella_files": sorted(set(umbrella)),
        "memory_files": memory,
        "surface_files": surface_files,
        "surface_dirs": surface_dirs,
        "unreadable": unreadable,
    }


def _rg_base(ctx, rg):
    # -i: candidates are a superset (remote slugs are matched case-insensitively); refine_hits is the exact judge.
    # --no-ignore: no ignore file (.gitignore and friends) may hide a file, which keeps this search equal to the built-in
    # one; both skip the same folders by name (a trailing slash means folders only, so a worktree's `.git` file is read).
    argv = [rg, "--no-config", "-F", "-i", "-l", "--hidden", "--no-messages", "--no-ignore", "--max-filesize", "8M"]
    for name in sorted(PY_SKIP_DIRS):
        argv += ["-g", "!%s/" % name]
    return argv


def _run_rg(argv):
    res = run(argv, timeout=SUBPROCESS_TIMEOUT * 5)
    if res.error or res.rc not in (0, 1):
        return None  # exit 2 means some paths could not be searched: coverage is not proven, so fall back and measure
    return [os.fsdecode(line) for line in res.out.split(b"\n") if line]


def py_candidates(needles, roots, files, dirs, cov, deadline):
    """Pure-Python fallback: same needle logic and the same files as `rg --no-ignore` (no ignore-file handling).

    Every path it cannot read, and a stop at the time limit, is recorded in `cov`."""
    needle_bytes = [n.encode("utf-8").lower() for n in needles]
    found = set()

    def out_of_time():
        if time.monotonic() > deadline:
            cov["deadline"] = True
            return True
        return False

    def check(path, follow=False):
        try:
            st = os.stat(path) if follow else os.lstat(path)
        except FileNotFoundError:
            return
        except OSError:
            note_unreadable(cov, path)
            return
        if not stat.S_ISREG(st.st_mode):
            return
        if st.st_size > SCAN_MAX_BYTES:
            cov["oversized"] += 1
            return
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except FileNotFoundError:
            return
        except OSError:
            note_unreadable(cov, path)
            return
        if b"\0" in data[:8192]:
            return
        folded = data.lower()
        if any(nb in folded for nb in needle_bytes):
            found.add(path)

    def on_error(exc):
        if not isinstance(exc, FileNotFoundError):
            note_unreadable(cov, getattr(exc, "filename", None) or "?")

    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=on_error):
            if out_of_time():
                return found
            dirnames[:] = [d for d in dirnames if d not in PY_SKIP_DIRS and not os.path.islink(os.path.join(dirpath, d))]
            for fn in filenames:
                check(os.path.join(dirpath, fn))
    for path in files:
        if out_of_time():
            return found
        check(path, follow=True)  # named files are read through a link, exactly as ripgrep reads a file it is handed
    for base, glob in dirs:
        for dirpath, dirnames, filenames in os.walk(base, followlinks=False, onerror=on_error):
            if out_of_time():
                return found
            dirnames[:] = [d for d in dirnames if d not in PY_SKIP_DIRS]
            for fn in filenames:
                if glob and not fnmatch.fnmatch(fn, glob):
                    continue
                check(os.path.join(dirpath, fn))
    return found


def scan_candidates(ctx, needles, scope, engine="auto", cov=None):
    needles = sorted(set(needles))
    cov = new_coverage() if cov is None else cov
    for unreadable_root in scope.get("unreadable", []):
        note_unreadable(cov, unreadable_root)
    if not needles:
        return {"engine": "none", "files": set(), "note": "", "coverage": cov}
    files_extra = list(scope["memory_files"]) + [p for p, _k in scope["surface_files"]]
    rg = ctx.tool("rg") if engine in ("auto", "rg") else None
    note = ""
    if rg:
        found = set()
        ok = True
        base = _rg_base(ctx, rg)
        for n in needles:
            base += ["-e", n]
        if scope["repo_roots"]:
            out = _run_rg(base + ["--"] + scope["repo_roots"])
            if out is None:
                ok = False
            else:
                found.update(out)
        for i in range(0, len(scope["umbrella_files"]), RG_CHUNK):
            if not ok:
                break
            out = _run_rg(base + ["--"] + scope["umbrella_files"][i : i + RG_CHUNK])
            if out is None:
                ok = False
            else:
                found.update(out)
        for i in range(0, len(files_extra), RG_CHUNK):
            if not ok:
                break
            out = _run_rg(base + ["--"] + files_extra[i : i + RG_CHUNK])
            if out is None:
                ok = False
            else:
                found.update(out)
        for dpath, _k, glob in scope["surface_dirs"]:
            if not ok:
                break
            argv = base + (["-g", glob] if glob else []) + ["--", dpath]
            out = _run_rg(argv)
            if out is None:
                ok = False
            else:
                found.update(out)
        if ok:
            return {"engine": "rg", "files": found, "note": "", "coverage": cov}
        note = "ripgrep could not search every path; used the slower built-in scanner"
    elif engine == "rg":
        return {"engine": "none", "files": set(), "note": "ripgrep is not installed", "coverage": cov}
    else:
        note = "ripgrep is not installed; used the slower built-in scanner"
    dirs = [(p, g) for p, _k, g in scope["surface_dirs"]]
    found = py_candidates(needles, scope["repo_roots"], list(scope["umbrella_files"]) + files_extra, dirs, cov, time.monotonic() + SCAN_DEADLINE_SECONDS)
    return {"engine": "python", "files": found, "note": note, "coverage": cov}


def compile_patterns(patterns):
    compiled = []
    for pat in patterns:
        esc = re.escape(pat["text"])
        flags = re.IGNORECASE if pat["kind"] == "slug" else 0
        rx = re.compile(r"(?<![A-Za-z0-9_-])" + esc + r"(?![A-Za-z0-9_-])", flags)
        compiled.append((pat["id"], rx))
    return compiled


def refine_hits(candidates, patterns, exclude_paths, cov=None):
    """Per-file, per-pattern counts. Counts and locations only; never the matching text."""
    compiled = compile_patterns(patterns)
    hits = {}
    for path in sorted(candidates):
        if any(is_under(path, e) for e in exclude_paths if e):
            continue
        try:
            st = os.stat(path)
            if not stat.S_ISREG(st.st_mode) or st.st_size > SCAN_MAX_BYTES:
                continue
            with open(path, "rb") as fh:
                data = fh.read()
        except FileNotFoundError:
            continue
        except OSError:
            if cov is not None:
                note_unreadable(cov, path)
            continue
        text = data.decode("utf-8", "replace")
        row = {}
        for pid, rx in compiled:
            n = len(rx.findall(text))
            if n:
                row[pid] = n
        if row:
            hits[path] = row
    return hits


def hit_surface(ctx, path):
    """Plain label for where a hit lives, used to map hits to gates and exceptions."""
    base = os.path.basename(path)
    if base == "agent-learnings.md" or path == os.path.join(ctx.home, "AGENTS.md"):
        return "generated-memory"
    for rel, klass in SURFACE_FILES:
        if path == os.path.join(ctx.home, rel):
            return klass
    for rel, klass, _g in SURFACE_DIRS:
        if is_under(path, os.path.join(ctx.home, rel)):
            return klass
    cpp = os.path.join(ctx.root, "affirm", "src", "card-platform-product")
    if is_under(path, cpp):
        return "cpp"
    if is_under(path, ctx.root):
        return "retained-repo"
    return "home-other"


def mention_patterns(entries):
    """entries: [{rel, slugs, names}] -> pattern list. Generic one-word names are never matched alone."""
    patterns = []
    for e in entries:
        patterns.append({"id": "%s|path" % e["rel"], "kind": "path", "text": e["rel"]})
        for slug in e.get("slugs", []):
            patterns.append({"id": "%s|slug" % e["rel"], "kind": "slug", "text": slug})
        for name in e.get("names", []):
            patterns.append({"id": "%s|name" % e["rel"], "kind": "name", "text": name})
    return patterns


def distinctive_name(name):
    return len(name) >= 6 and ("-" in name or "_" in name)



# --------------------------------------------------------------------------- assessment: facts -> blockers, risks, gates, plan

MAX_TARGETS = 25


def blocker(bid, message, remedy=""):
    return {"id": bid, "message": message, "remedy": remedy}


def new_target(raw):
    return {
        "input": jstr(raw),
        "rel": None,
        "root_class": None,
        "state": "invalid",
        "blockers": [],
        "risks": [],
        "gates": [],
        "notes": [],
        "wiring": {"links": [], "jobs": [], "job_rows": [], "project_dirs": []},
    }


def resolve_targets(ctx, raws):
    out, seen = [], set()
    for raw in raws:
        t = new_target(raw)
        try:
            rel, comps, klass = classify_path(ctx, raw)
        except PathProblem as exc:
            t["blockers"].append(blocker("path-invalid", exc.message))
            if exc.code == "protected":
                t["blockers"][-1]["id"] = "protected-target"
            out.append(t)
            continue
        t.update(rel=rel, comps=comps, root_class=klass, path=os.path.join(ctx.root, rel), state="unknown")
        if rel in seen:
            t["blockers"].append(blocker("duplicate-target", "the same checkout was listed twice"))
        seen.add(rel)
        out.append(t)
    if len([t for t in out if t["rel"]]) > MAX_TARGETS:
        for t in out:
            t["blockers"].append(blocker("too-many-targets", "an operation covers at most %d checkouts; split it" % MAX_TARGETS))
    return out


def inspect_fs(ctx, t):
    try:
        fd, parent = open_chain(ctx, t["comps"])
    except PathProblem as exc:
        if exc.code == "absent":
            t["state"] = "absent"
            markers = markers_beside(ctx, t["comps"])
            if markers:
                # A marker that a recorded operation made for a different checkout says nothing about this path; one nobody can explain still does.
                owners = marker_owners(ctx)
                markers = [m for m in markers if not owners.get(m) or t["rel"] in owners[m]]
            if markers:
                t["blockers"].append(
                    blocker(
                        "removal-marker-present",
                        "an unfinished removal left %s beside %s, so a checkout may be only partly deleted" % (", ".join(markers[:2]), t["rel"]),
                        "resume the interrupted operation (view lists open operations), then preview again",
                    )
                )
        else:
            t["state"] = "blocked"
            t["blockers"].append(blocker("path-unsafe", "%s: %s" % (t["rel"], exc.message)))
        return
    try:
        st = os.fstat(fd)
        root_dev = os.stat(ctx.root).st_dev
        t["state"] = "present"
        t["identity"] = stat_identity(st)
        if st.st_dev != root_dev:
            t["blockers"].append(blocker("cross-device", "the checkout is on a different filesystem than the dev root"))
        if st.st_uid != os.geteuid():
            t["blockers"].append(blocker("owner-mismatch", "the checkout is owned by another user"))
        t["git_dir_ok"] = False
        try:
            gst = os.lstat(".git", dir_fd=fd)
        except FileNotFoundError:
            t["blockers"].append(blocker("not-a-checkout", "there is no .git directory, so this is not a Git checkout", "remove it by hand if it really is disposable"))
        except OSError:
            t["blockers"].append(blocker("git-unreadable", "the .git entry could not be read"))
        else:
            if stat.S_ISLNK(gst.st_mode):
                t["blockers"].append(blocker("git-dir-symlink", ".git is a symbolic link; links are never followed"))
            elif stat.S_ISREG(gst.st_mode):
                t["blockers"].append(
                    blocker("gitfile-checkout", "this is a linked worktree or submodule (its .git is a file), not a primary checkout", "remove it through the repository that owns it")
                )
            elif stat.S_ISDIR(gst.st_mode):
                t["git_dir_ok"] = True
        tree = walk_tree(fd, st.st_dev)
    finally:
        os.close(fd)
        if parent is not None:
            os.close(parent)
    t["tree"] = {k: tree[k] for k in ("files", "dirs", "symlinks", "bytes", "fingerprint")}
    t["tree"]["nested_git"] = tree["nested_git"]
    if tree["specials"]:
        t["blockers"].append(blocker("special-files", "sockets, pipes or device files are inside the checkout (%s)" % ", ".join(tree["specials"][:3])))
    if tree["cross_device"]:
        t["blockers"].append(blocker("mount-inside", "a mount point is inside the checkout (%s)" % ", ".join(tree["cross_device"][:3])))
    if tree["unreadable"]:
        t["blockers"].append(blocker("unreadable-tree", "parts of the checkout could not be read (%s)" % ", ".join(tree["unreadable"][:3])))
    if tree["nested_git"]:
        t["risks"].append({"id": "nested-repos", "message": RISK_TEXT["nested-repos"], "detail": {"count": len(tree["nested_git"])}})
    if is_under(ctx.start_cwd, t["path"]):
        t["blockers"].append(blocker("self-inside", "the shell running this command is inside the checkout", "change directory out of it and retry"))
    t["aspects"] = {"tree:" + t["rel"]: digest_of({"identity": t["identity"], "tree": t["tree"]["fingerprint"], "counts": [tree["files"], tree["dirs"], tree["symlinks"]]})}


def tree_aspect_now(ctx, rel):
    comps = rel.split("/")
    try:
        fd, parent = open_chain(ctx, comps)
    except PathProblem:
        return None
    try:
        st = os.fstat(fd)
        tree = walk_tree(fd, st.st_dev)
    finally:
        os.close(fd)
        if parent is not None:
            os.close(parent)
    return digest_of({"identity": stat_identity(st), "tree": tree["fingerprint"], "counts": [tree["files"], tree["dirs"], tree["symlinks"]]})


def writer_blockers(ctx, label, path, gitdir, affirm, also=()):
    """Evidence that someone is, or might be, writing. Returns (blockers, risks).

    `also` lists other spellings of the same place to look for (a checkout set aside under its marker
    name is searched under both the marker and its original path)."""
    blockers, risks = [], []
    w = writers_for(ctx, path, also)
    if not w["proof"]:
        if affirm:
            blockers.append(
                blocker(
                    "affirm-writer-proof",
                    "cannot prove no one is writing to %s (%s); checkouts under affirm/ require that proof" % (label, w["reason"]),
                    "install or fix lsof, then retry",
                )
            )
        else:
            risks.append({"id": "writer-proof-unavailable", "message": RISK_TEXT["writer-proof-unavailable"], "detail": {"reason": w["reason"]}})
    others = [p for p in w["processes"] if not p["ancestor"]]
    mine = [p for p in w["processes"] if p["ancestor"]]
    if others:
        names = ", ".join("%s (pid %s)" % (p["command"], p["pid"]) for p in others[:3])
        blockers.append(blocker("active-writer", "%s is in use by %s" % (label, names), "close those programs or agent sessions first"))
    if mine:
        blockers.append(blocker("self-inside", "the shell or agent running this command is using %s" % label, "change directory out of it and retry"))
    if gitdir:
        lock = session_lock_state(ctx, gitdir)
        if lock and lock["live"]:
            blockers.append(blocker("active-writer", "a live editing session holds the session lock on %s" % label, "release it with the session-lock tool, or end that session"))
    if lexists_nofollow(os.path.join(path, ".awa", "lease.json")):
        blockers.append(blocker("awa-lease-present", "an AWA lease file is present in %s" % label, "finish the AWA workspace through its own flow first"))
    return blockers, risks


def collect_core(ctx, t, fleet, slug_index, op_rels):
    """Git, writers, policy and fleet facts for one present checkout."""
    path, rel = t["path"], t["rel"]
    affirm = t["root_class"] in ("affirm-src", "affirm-vendor")
    if affirm and not policy_marker_present(ctx):
        t["blockers"].append(
            blocker(
                "affirm-policy-gate",
                "removing a whole checkout under affirm/ needs the policy exception in _ops/POLICY.md, which is not in force on this machine",
                "this stays an operator decision until that policy change is merged",
            )
        )
    if not t.get("git_dir_ok"):
        wbl, wrisk = writer_blockers(ctx, rel, path, None, affirm)
        t["blockers"].extend(wbl)
        t["risks"].extend(wrisk)
        return
    g = collect_git(ctx, path)
    t["git"] = g
    if g["error"]:
        t["blockers"].append(blocker("git-unreadable", "Git could not be assessed (%s); safety cannot be judged" % g["error"], "fix the repository or remove it by hand"))
        return
    t["aspects"]["git:" + rel] = git_aspect_digest(g)
    counts = g["status_counts"]
    if g["index_locked"]:
        t["blockers"].append(blocker("git-index-locked", "a Git operation is running or crashed here (index.lock exists)", "finish or clear it first"))
    if counts["tracked"]:
        t["risks"].append({"id": "dirty-tracked", "message": RISK_TEXT["dirty-tracked"], "detail": {"files": counts["tracked"], "conflicted": counts["conflicted"]}})
    if counts["untracked"]:
        t["risks"].append({"id": "untracked-files", "message": RISK_TEXT["untracked-files"], "detail": {"files": counts["untracked"]}})
    if counts["ignored"]:
        t["risks"].append({"id": "ignored-data", "message": RISK_TEXT["ignored-data"], "detail": {"entries": counts["ignored"]}})
    if g["unpushed_total"]:
        detail = dict(g["unpushed"])
        if not g["remotes"]:
            detail["no_remote_configured"] = True
        t["risks"].append({"id": "unpushed-commits", "message": RISK_TEXT["unpushed-commits"], "detail": detail})
    elif not g["remotes"] and g["head"]:
        t["notes"].append("no remote is configured, so nothing here can be confirmed as backed up")
    if g["stashes"]:
        t["risks"].append({"id": "stashes", "message": RISK_TEXT["stashes"], "detail": {"count": g["stashes"]}})
    if g["operation_state"]:
        t["risks"].append({"id": "operation-in-progress", "message": RISK_TEXT["operation-in-progress"], "detail": {"state": g["operation_state"]}})
    wbl, wrisk = writer_blockers(ctx, rel, path, g["gitdir"], affirm)
    t["blockers"].extend(wbl)
    t["risks"].extend(wrisk)
    wts = []
    for record in g["worktrees"]:
        info = worktree_detail(ctx, record, path)
        wts.append(info)
        if not info["exists"]:
            t["blockers"].append(blocker("worktree-unavailable", "a registered worktree is missing at %s" % info["path"],
                                         "locate the worktree and reconcile its registration with its owner"))
            continue
        if info["symlink"]:
            t["blockers"].append(blocker("worktree-path-symlink", "linked worktree path %s is a symbolic link" % info["path"]))
            continue
        if not info["inside_target"]:
            problem = worktree_location_problem(ctx, info["path"])
            if problem:
                t["blockers"].append(
                    blocker(
                        "worktree-unsafe-location",
                        "linked worktree %s will not be removed automatically: %s" % (info["path"], problem),
                        "check it yourself and remove or move it (git worktree remove), then preview again",
                    )
                )
                continue
        if info["locked"] and not info["inside_target"]:
            t["blockers"].append(
                blocker(
                    "linked-worktree-locked",
                    "linked worktree %s is locked, and this tool never overrides a lock" % info["path"],
                    "if the lock is stale, run `git worktree unlock` on it yourself, then preview again",
                )
            )
        if info.get("unreadable"):
            t["blockers"].append(blocker("git-unreadable", "linked worktree %s could not be assessed" % info["path"]))
        if info["dirty"] or info["untracked"]:
            t["risks"].append(
                {
                    "id": "linked-worktree-work",
                    "message": RISK_TEXT["linked-worktree-work"],
                    "detail": {"path": info["path"], "dirty": info["dirty"], "untracked": info["untracked"]},
                }
            )
        if not info["inside_target"]:
            wbl2, _r = writer_blockers(ctx, info["path"], info["path"], worktree_gitdir(ctx, info["path"]), affirm)
            t["blockers"].extend(wbl2)
            if is_under(ctx.start_cwd, info["path"]):
                t["blockers"].append(blocker("self-inside", "the shell running this command is inside linked worktree %s" % info["path"]))
    t["worktrees"] = wts
    for slug in g["slugs"]:
        if slug in fleet["slugs"]:
            t["blockers"].append(
                blocker(
                    "pac-fleet-enrolled",
                    "%s is still enrolled in the PR automation fleet" % slug,
                    "retire it from the PAC fleet first (operator gate: fleet config and the GitHub App's repository scope)",
                )
            )
        elif not fleet["available"] and slug.startswith("kleinperkins/") and not any(b["id"] == "pac-fleet-unknown" for b in t["blockers"]):
            # Fail closed: without the fleet list, enrollment cannot be ruled out for a fleet-eligible remote.
            t["blockers"].append(
                blocker(
                    "pac-fleet-unknown",
                    "the PR automation fleet list could not be read, so enrollment of %s cannot be ruled out" % slug,
                    "restore _ops/baseline/profiles/pr-automation/v3/fleet.json (it is tracked in this repo), then preview again",
                )
            )
        for other in slug_index.get(slug, []):
            if other != rel and other not in op_rels:
                t["notes"].append("another local clone of %s remains at %s" % (slug, other))
    # Pages / DNS hints cannot be verified offline; they need an explicit attestation.
    hint = False
    cname = os.path.join(path, "CNAME")
    if lexists_nofollow(cname):
        hint = True
    wf = os.path.join(path, ".github", "workflows")
    try:
        for name in os.listdir(wf):
            if "pages" in name.lower():
                hint = True
    except OSError:
        pass
    if hint:
        t["gates"].append(
            {
                "id": "github-pages",
                "kind": "attest",
                "message": "this checkout looks like it publishes GitHub Pages or a custom domain; the tool cannot verify Pages, DNS or registrar state offline",
                "remedy": "disable Pages and settle DNS yourself, then pass --attest github-pages",
            }
        )


def slug_index_for(ctx):
    """slug -> [rel, ...] for local clones, read straight from .git/config (no subprocess)."""
    index = {}
    for parent in (("affirm", "src"), ("affirm", "vendor"), ("personal",), ("capabilities",)):
        base = os.path.join(ctx.root, *parent)
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            text = read_text_nofollow(os.path.join(base, name, ".git", "config"), limit=1 << 20)
            if not text:
                continue
            for m in re.finditer(r"^\s*url\s*=\s*(\S+)\s*$", text, re.M):
                slug = origin_slug(redact_url(m.group(1))).lower()
                if slug:
                    index.setdefault(slug, []).append("/".join(parent + (name,)))
    return index


def surface_reference_blockers(t, by_surface):
    """The two kinds of reference that break a live tool the moment the checkout is gone."""
    out = []
    if by_surface.get("client-config"):
        out.append(
            blocker(
                "client-config-reference",
                "an AI-client config file still points at %s (%d file%s)" % (t["rel"], len(by_surface["client-config"]), "" if len(by_surface["client-config"]) == 1 else "s"),
                "remove the entry through the owning client (for example `claude mcp remove`); Cursor's mcp.json is guarded",
            )
        )
    if by_surface.get("launchd-shell"):
        out.append(
            blocker(
                "launchd-shell-reference",
                "a launch agent or shell startup file still points at %s" % t["rel"],
                "unload and remove it yourself, then retry",
            )
        )
    return out


LIVE_REFERENCE_CLASSES = ("client-config", "launchd-shell")


def live_reference_blockers(ctx, t, op_paths=()):
    """Seconds before a deletion: look again where a new reference breaks something live.

    The full search of retained files runs at confirmation, after every group and when a run resumes. This is the
    cheap check for what fails loudly: the few config, startup and launch-agent files that name the checkout, symbolic
    links into it, and scheduler entries that name it. The detach steps have already run by now, so any link or
    entry still there is new. `op_paths` are all the operation's checkouts, whose own folders are not walked."""
    surface_files, surface_dirs = surface_paths(ctx, LIVE_REFERENCE_CLASSES)
    scope = {"repo_roots": [], "umbrella_files": [], "memory_files": [], "surface_files": surface_files, "surface_dirs": surface_dirs, "unreadable": []}
    patterns = mention_patterns([{"rel": t["rel"], "slugs": [], "names": []}])
    cand = scan_candidates(ctx, [p["text"] for p in patterns], scope)
    hits = refine_hits(cand["files"], patterns, [t["path"]], cand["coverage"])
    by_surface = {}
    for path, row in hits.items():
        if "%s|path" % t["rel"] in row:
            by_surface.setdefault(hit_surface(ctx, path), []).append(path)
    out = surface_reference_blockers(t, by_surface)
    for hit in collect_links(ctx, [t["path"]], new_coverage(), list(op_paths) or None):
        out.append(blocker("retained-link", "a symbolic link at %s points into %s" % (hit["link"], t["rel"]), "remove or retarget that link, then preview again"))
    ctx.cache.pop("jobs", None)
    avail, instances = local_jobs_instances(ctx)
    if avail:
        rx = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(t["rel"]) + r"(?![A-Za-z0-9_-])")
        for inst in instances:
            if rx.search(canon(inst)):
                out.append(blocker("local-jobs-row", "scheduler entry '%s' now names %s" % (inst.get("id"), t["rel"]), "remove or update it with the local-jobs verbs, then preview again"))
    return out


def attach_wiring(ctx, targets, engine="auto"):
    live = [t for t in targets if t["rel"]]
    paths = [t["path"] for t in live]
    if not live:
        return {"engine": "none", "note": ""}
    cov = new_coverage()  # one record of what the whole search (links, then mentions) could not read
    # symlinks into the targets
    for hit in collect_links(ctx, paths, cov):
        for t in live:
            if t["path"] == hit["target_path"]:
                if hit["kind"] == "client-link":
                    t["wiring"]["links"].append(hit)
                else:
                    remedy = "remove or retarget that link yourself first" if hit["kind"] == "surface-link" else "remove or retarget the link in its owning repository first"
                    t["blockers"].append(blocker("retained-link", "a symbolic link at %s points into %s" % (hit["link"], t["rel"]), remedy))
    # scheduled jobs (through the owning verb)
    avail, instances = local_jobs_instances(ctx)
    for t in live:
        rx = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(t["rel"]) + r"(?![A-Za-z0-9_-])")
        if avail:
            for inst in instances:
                if rx.search(canon(inst)):
                    row = {"id": str(inst.get("id")), "role": inst.get("role"), "aspect": job_aspect_digest(inst)}
                    if not isinstance(inst.get("id"), str) or not inst["id"] or not job_is_dedicated_to(inst, t["path"]):
                        t["wiring"]["job_rows"].append(row)
                    else:
                        row["removal_revision"] = inst["removal_revision"]
                        t["wiring"]["jobs"].append(row)
        else:
            t["notes"].append("the local-jobs tool is unavailable, so scheduled jobs were checked only by file search")
    for t in live:
        for row in t["wiring"]["job_rows"]:
            t["blockers"].append(
                blocker(
                    "local-jobs-row",
                    "scheduler entry '%s' mentions this checkout without a revision for safe, exclusive removal" % row["id"],
                    "inspect the job with local-jobs and update or retire it through its owner first",
                )
            )
    for pd in collect_project_dirs(ctx, paths):
        for t in live:
            if t["path"] == pd["target_path"]:
                t["wiring"]["project_dirs"].append(pd)
                if pd["shared_with"]:
                    t["notes"].append(
                        "Cursor's project folder for this path is also the one for %s (the names differ only in punctuation), so its caches are left alone"
                        % ", ".join(pd["shared_with"][:3])
                    )
                if pd["kept"]:
                    t["notes"].append("Cursor chat history (%s) is kept, not deleted" % ", ".join(pd["kept"]))
                if pd["other"]:
                    t["notes"].append("unrecognised entries in the Cursor project folder are left alone (%d)" % len(pd["other"]))
    # text mentions of the checkout's path in retained files and config surfaces
    # Path references are the ones that can dangle (they drive consumer-mentions). Remote slugs and distinctive
    # names are scanned too, but only to report how many files name the repository that way, so verify (which
    # looks for all three) holds no surprises.
    entries = [
        {
            "rel": t["rel"],
            "slugs": sorted(set((t.get("git") or {}).get("slugs") or [])),
            "names": [n for n in [os.path.basename(t["rel"])] if distinctive_name(n)],
        }
        for t in live
    ]
    exclude = paths
    scope = scan_scope(ctx, exclude)
    patterns = mention_patterns(entries)
    cand = scan_candidates(ctx, [p["text"] for p in patterns], scope, engine, cov)
    hits = refine_hits(cand["files"], patterns, exclude, cov)
    incomplete = coverage_incomplete(cov)
    for t in live:
        if incomplete:
            t["risks"].append(
                {
                    "id": "scan-incomplete",
                    "message": RISK_TEXT["scan-incomplete"],
                    "detail": {"unreadable": cov["unreadable_total"], "stopped_at_time_limit": cov["deadline"]},
                }
            )
        by_surface = {}
        for path, row in hits.items():
            if "%s|path" % t["rel"] not in row:
                continue
            by_surface.setdefault(hit_surface(ctx, path), []).append(path)
        t["mentions"] = {k: len(v) for k, v in sorted(by_surface.items())}
        t["_mention_files"] = {k: sorted(v) for k, v in by_surface.items()}
        remote_only = [
            path for path, row in hits.items() if "%s|slug" % t["rel"] in row and "%s|path" % t["rel"] not in row
        ]
        if remote_only:
            t["remote_mentions"] = len(remote_only)
            t["notes"].append(
                "%d other file%s name this repository by its remote rather than a path; nothing dangles, but expect each to need cleanup or an exception at verify"
                % (len(remote_only), "" if len(remote_only) == 1 else "s")
            )
        name_only = [
            path
            for path, row in hits.items()
            if "%s|name" % t["rel"] in row and "%s|path" % t["rel"] not in row and "%s|slug" % t["rel"] not in row
        ]
        if name_only:
            t["name_mentions"] = len(name_only)
            t["notes"].append(
                "%d other file%s name this repository by its name only; nothing dangles, but expect each to need cleanup or an exception at verify"
                % (len(name_only), "" if len(name_only) == 1 else "s")
            )
        t["blockers"].extend(surface_reference_blockers(t, by_surface))
        if by_surface.get("local-jobs") and not t["wiring"]["jobs"] and not t["wiring"]["job_rows"]:
            t["blockers"].append(
                blocker("local-jobs-row", "local-jobs registry files still mention %s" % t["rel"], "remove those rows with the local-jobs verbs first")
            )
        consumers = (by_surface.get("retained-repo") or []) + (by_surface.get("cpp") or [])
        if consumers:
            t["risks"].append(
                {
                    "id": "consumer-mentions",
                    "message": RISK_TEXT["consumer-mentions"],
                    "detail": {
                        "files": len(consumers),
                        "cpp_files": len(by_surface.get("cpp") or []),
                        "digest": sha256_hex("\n".join(sorted(consumers))),
                    },
                }
            )
        for surface in ("generated-memory", "agent-route", "shadowsync", "git-config", "home-other"):
            if by_surface.get(surface):
                t["notes"].append("%d %s file%s mention it (resolved at verify, not by this tool)" % (len(by_surface[surface]), surface, "" if len(by_surface[surface]) == 1 else "s"))
    return {
        "engine": cand["engine"],
        "note": cand["note"],
        "coverage": {
            "complete": not incomplete,
            "unreadable": cov["unreadable_total"],
            "unreadable_paths": sorted(cov["unreadable"])[:10],
            "stopped_at_time_limit": cov["deadline"],
            "size_limit_bytes": SCAN_MAX_BYTES,
            # Files above the limit are not searched. Only the built-in search counts them; ripgrep skips them silently.
            "oversized_skipped": cov["oversized"] if cand["engine"] == "python" else None,
        },
    }


def assess_targets(ctx, raws, engine="auto"):
    targets = resolve_targets(ctx, raws)
    op_rels = {t["rel"] for t in targets if t["rel"]}
    if not op_rels:
        return targets, {"engine": "none", "note": ""}
    fleet = fleet_slugs(ctx)
    slugs = slug_index_for(ctx)
    for t in targets:
        if not t["rel"]:
            continue
        t.setdefault("aspects", {})
        inspect_fs(ctx, t)
        if t["state"] == "present":
            collect_core(ctx, t, fleet, slugs, op_rels)
    info = attach_wiring(ctx, targets, engine)
    for t in targets:
        if t["state"] == "present":
            a = t.setdefault("aspects", {})
            for lk in t["wiring"]["links"]:
                a["link:" + lk["link"]] = link_aspect_digest(lk["link"])
            for jb in t["wiring"]["jobs"]:
                a["job:" + jb["id"]] = jb["aspect"]
            for pd in t["wiring"]["project_dirs"]:
                for name, digest in pd["cache_aspects"].items():
                    a["cache:%s/%s" % (pd["encoded"], name)] = digest
            for wt in t.get("worktrees", []):
                if wt["exists"] and not wt["inside_target"]:
                    a["worktree:" + wt["path"]] = wt["aspect"]
        elif t["state"] == "absent":
            a = t.setdefault("aspects", {})
            for lk in t["wiring"]["links"]:
                a["link:" + lk["link"]] = link_aspect_digest(lk["link"])
            for jb in t["wiring"]["jobs"]:
                a["job:" + jb["id"]] = jb["aspect"]
            for pd in t["wiring"]["project_dirs"]:
                for name, digest in pd["cache_aspects"].items():
                    a["cache:%s/%s" % (pd["encoded"], name)] = digest
    return targets, info


def recompute_aspect(ctx, aspect_id):
    kind, _, key = aspect_id.partition(":")
    if kind == "tree":
        return tree_aspect_now(ctx, key)
    if kind == "git":
        path = os.path.join(ctx.root, key)
        if not os.path.isdir(os.path.join(path, ".git")):
            return None
        g = collect_git(ctx, path)
        return None if g["error"] else git_aspect_digest(g)
    if kind == "link":
        return link_aspect_digest(key)
    if kind == "job":
        ctx.cache.pop("jobs", None)
        avail, instances = local_jobs_instances(ctx)
        if not avail:
            return "unavailable"
        for inst in instances:
            if str(inst.get("id")) == key:
                return job_aspect_digest(inst)
        return None
    if kind == "cache":
        encoded, _, name = key.partition("/")
        return cache_aspect_digest(ctx, encoded, name)
    if kind == "worktree":
        return worktree_aspect_digest(worktree_state(ctx, key))
    return "unknown-aspect"


# ----- plan

def cohorts_for(targets, cohort_size):
    ordered = sorted(
        [t for t in targets if t["state"] in ("present", "absent")],
        key=lambda t: (COHORT_ORDER.index(t["root_class"]), t["rel"]),
    )
    cohorts, current, cls = [], [], None
    for t in ordered:
        if cls is not None and (t["root_class"] != cls or len(current) >= cohort_size):
            cohorts.append(current)
            current = []
        cls = t["root_class"]
        current.append(t)
    if current:
        cohorts.append(current)
    return cohorts


def build_plan(ctx, targets, cohort_size, agent_route_available):
    cohorts = cohorts_for(targets, cohort_size)
    steps = []

    def add(kind, cohort, target, params, aspects, expect, conditions=()):
        steps.append(
            {
                "id": "s%02d" % (len(steps) + 1),
                "kind": kind,
                "cohort": cohort,
                "target": target,
                "params": params,
                "requires": {"aspects": aspects, "conditions": list(conditions)},
                "expect": expect,
            }
        )

    cohort_rows = []
    for idx, cohort in enumerate(cohorts, 1):
        cid = "c%d" % idx
        cohort_rows.append({"id": cid, "targets": [t["rel"] for t in cohort], "root_class": cohort[0]["root_class"]})
        for t in cohort:
            for lk in t["wiring"]["links"]:
                add("unlink-link", cid, t["rel"], {"link": lk["link"], "readlink": lk["readlink"]}, {"link:" + lk["link"]: t["aspects"]["link:" + lk["link"]]}, "symlink %s is gone" % lk["link"])
            for jb in t["wiring"]["jobs"]:
                add("local-job-delete", cid, t["rel"], {"id": jb["id"], "removal_revision": jb["removal_revision"]}, {"job:" + jb["id"]: jb["aspect"]}, "scheduled job %s is deleted" % jb["id"])
            for pd in t["wiring"]["project_dirs"]:
                for name in sorted(pd["caches"]):
                    key = "%s/%s" % (pd["encoded"], name)
                    add(
                        "cache-remove",
                        cid,
                        t["rel"],
                        {"encoded": pd["encoded"], "cache": name},
                        {"cache:" + key: pd["cache_aspects"][name]},
                        "the Cursor %s cache for this checkout is deleted (chat history is kept)" % name,
                    )
        for t in cohort:
            if t["state"] != "present":
                continue
            for wt in t.get("worktrees", []):
                if wt["exists"] and not wt["inside_target"]:
                    add(
                        "worktree-remove",
                        cid,
                        t["rel"],
                        {"path": wt["path"], "managed_by": wt["managed_by"], "dirty": wt["dirty"], "untracked": wt["untracked"]},
                        {"worktree:" + wt["path"]: wt["aspect"]},
                        "linked worktree %s is removed" % wt["path"],
                    )
        for t in cohort:
            if t["state"] != "present":
                continue
            add(
                "delete-checkout",
                cid,
                t["rel"],
                {"rel": t["rel"], "identity": t["identity"]},
                {"tree:" + t["rel"]: t["aspects"]["tree:" + t["rel"]], "git:" + t["rel"]: t["aspects"].get("git:" + t["rel"])},
                "%s no longer exists" % t["rel"],
                ("no-writer", "path-chain", "affirm-gate", "fleet", "worktrees-gone"),
            )
    if steps and agent_route_available:
        add("refresh-index", cohort_rows[-1]["id"] if cohort_rows else "c1", None, {}, {}, "the agent-route index is regenerated")
    return cohort_rows, steps


def manifest_of(targets):
    rows = []
    for t in sorted([t for t in targets if t["rel"]], key=lambda t: t["rel"]):
        g = t.get("git") or {}
        rows.append(
            {
                "rel": t["rel"],
                "root_class": t["root_class"],
                "state": t["state"],
                "identity": t.get("identity"),
                "registrations": sorted(registration_binding(name, row) for name, row in g.get("registrations", {}).items()),
                "slugs": g.get("slugs", []),
                "names": [os.path.basename(t["rel"])],
            }
        )
    return rows


def required_waivers(targets):
    ids = set()
    for t in targets:
        if t["state"] == "present":
            for r in t["risks"]:
                ids.add(r["id"])
    return sorted(ids)


def required_attests(targets):
    ids = set()
    for t in targets:
        if t["state"] == "present":
            for g in t["gates"]:
                if g.get("kind") == "attest":
                    ids.add(g["id"])
    return sorted(ids)


def has_blockers(targets):
    return any(t["blockers"] for t in targets)


def confirmation_token(op, waived, attested, preimages):
    payload = {
        "operation": op["operation_id"],
        "targets": digest_of(op["targets"]),
        "action": op["action_digest"],
        "preimages": digest_of(preimages),
        "waived": sorted(waived),
        "attested": sorted(attested),
    }
    return "confirm-%s-%s" % (op["operation_id"].split("-", 1)[-1], digest_of(payload)[:20])



# --------------------------------------------------------------------------- operations: persistence, execution, health

def new_operation_id(ctx):
    stamp = datetime.fromtimestamp(ctx.now(), tz=timezone.utc).strftime("%Y%m%d-%H%M")
    return "ret-%s-%s" % (stamp, secrets.token_hex(2))


def create_operation(ctx, targets, cohort_size, info):
    cohorts, steps = build_plan(ctx, targets, cohort_size, bool(ctx.adapter("agent-route")))
    manifest = manifest_of(targets)
    preimages = {}
    for step in steps:
        preimages.update(step["requires"]["aspects"])
    op_id = new_operation_id(ctx)
    action = {"root": ctx.root, "targets": manifest, "cohorts": cohorts, "steps": steps, "cohort_size": cohort_size}
    op = {
        "schema": SCHEMA_OPERATION,
        "operation_id": op_id,
        "created": ctx.now(),
        "created_iso": iso(ctx.now()),
        "mode": "fixture" if ctx.fixture else "live",
        "root": ctx.root,
        "tool": {"name": TOOL, "sha256": ctx.tool_sha256, "source_revision": ctx.repo_head},
        "targets": manifest,
        "cohorts": cohorts,
        "steps": steps,
        "preimages": preimages,
        "required_waivers": required_waivers(targets),
        "required_attests": required_attests(targets),
        "cohort_size": cohort_size,
        "action_digest": digest_of(action),
        "scan_engine": info.get("engine"),
    }
    ensure_state_root(ctx)
    journal = Journal(ctx, op_id)
    os.mkdir(journal.dir, 0o700)
    fsync_dir(ctx.state_root)
    data = canon_bytes(op) + b"\n"
    atomic_write(journal.op_path, data)
    journal.append(
        "open",
        subsystem="journal",
        operation_sha256=sha256_hex(data),
        action_digest=op["action_digest"],
        tool_sha256=op["tool"]["sha256"],
        source_revision=op["tool"]["source_revision"],
        schema=SCHEMA_EVENT,
    )
    summary = []
    for t in targets:
        if not t["rel"]:
            continue
        summary.append(
            {
                "rel": t["rel"],
                "state": t["state"],
                "risks": sorted((r["id"], canon(r.get("detail", {}))) for r in t["risks"]),
                "gates": [g["id"] for g in t["gates"]],
            }
        )
    journal.append("preview", subsystem="targets", targets=summary, steps=len(steps), cohorts=len(cohorts), required_waivers=op["required_waivers"], required_attests=op["required_attests"])
    return op, journal


def load_operation(ctx, op_id, strict=True):
    """Load an operation and its journal. With strict=True a journal that fails its integrity checks is refused;
    read-only reports pass strict=False and read view.problems instead."""
    if not OP_ID_RE.match(op_id or ""):
        raise Refusal("that is not a valid operation id")
    journal = Journal(ctx, op_id)
    if not journal.exists():
        if legacy_record(ctx, op_id) is not None:
            raise Refusal("%s is a record from before this tool existed. It is history: view, resume, verify and remove cannot act on it. To read it: doctor --journal %s" % (op_id, journal.path))
        raise Refusal("no operation %s was found in %s" % (op_id, ctx.state_root))
    data = None
    try:
        fd = os.open(journal.op_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            data = b""
            while True:
                chunk = os.read(fd, 1 << 20)
                if not chunk:
                    break
                data += chunk
        finally:
            os.close(fd)
    except OSError:
        raise Refusal("the operation record for %s cannot be read" % op_id)
    view = journal.load()
    opened = [e for e in view.events if e.get("kind") == "open"]
    if not opened or opened[0].get("operation_sha256") != sha256_hex(data):
        raise Refusal("the operation record for %s does not match its journal (it was modified); start a new preview" % op_id)
    op = json.loads(data.decode("utf-8"))
    if op.get("schema") != SCHEMA_OPERATION or op.get("operation_id") != op_id:
        raise Refusal("the operation record for %s has an unexpected shape" % op_id)
    if op.get("root") != ctx.root:
        raise Refusal("operation %s was created for a different dev root" % op_id)
    view.problems = journal_problems(view, op_id)
    if strict and view.problems:
        raise Refusal("the journal for %s fails its integrity checks (%s); nothing was done. Run doctor, and start a new preview if needed" % (op_id, "; ".join(view.problems[:3])))
    return op, journal, view


def intact_view(journal, op_id):
    """Re-read the journal inside the writer lock and refuse to act on one that no longer verifies."""
    view = journal.load()
    problems = journal_problems(view, op_id)
    if problems:
        raise Refusal("the journal for %s fails its integrity checks (%s); nothing was done. Run doctor, and start a new preview if needed" % (op_id, "; ".join(problems[:3])))
    return view


def list_operation_ids(ctx):
    try:
        names = sorted(os.listdir(ctx.state_root))
    except OSError:
        return []
    out = []
    for name in names:
        path = os.path.join(ctx.state_root, name)
        if OP_ID_RE.match(name) and os.path.isdir(path) and not os.path.islink(path):
            out.append(name)
    return out


def operation_status(op, view, now):
    if view.closed:
        return "closed"
    kinds = [e.get("kind") for e in view.events]
    if "confirm" not in kinds:
        return "expired-preview" if now - op["created"] > PREVIEW_TTL_SECONDS else "previewed"
    ids = [s["id"] for s in op["steps"]]
    states, _l = step_states(view.events, ids)
    values = list(states.values())
    if values and all(v in ("completed", "excepted") for v in values):
        return "executed"
    if "open" in values:
        return "interrupted"
    if "failed" in values:
        return "failed"
    if "refused" in values:
        return "paused"
    last = view.events[-1] if view.events else {}
    if last.get("kind") in ("refusal", "rescan"):
        return "paused"
    return "confirmed"


def plain_aspect(aspect_id):
    kind, _, key = aspect_id.partition(":")
    return {
        "tree": "the files in %s",
        "git": "the Git state of %s",
        "link": "the link %s",
        "job": "the scheduled job %s",
        "cache": "the Cursor cache %s",
        "worktree": "the linked worktree %s",
    }.get(kind, "%s") % key


def unplanned_worktrees(op, t):
    """Linked worktrees outside the checkout that the approved plan does not cover (they appeared after the preview)."""
    planned = {s["params"]["path"] for s in op["steps"] if s["kind"] == "worktree-remove" and s["target"] == t["rel"]}
    extra = {w["path"] for w in t.get("worktrees", []) if w["exists"] and not w["inside_target"] and w["path"] not in planned}
    manifest = next(row for row in op["targets"] if row["rel"] == t["rel"])
    approved = manifest.get("registrations")
    if approved is not None:
        current = (t.get("git") or {}).get("registrations", {})
        changed = {name: row for name, row in current.items() if registration_binding(name, row) not in approved}
        extra.update(registration_paths(changed, os.path.join(t["path"], ".git", "worktrees")))
    return sorted(extra)


def stray_worktree_message(strays):
    return "a linked worktree was added after the confirmation (%s). Nothing was deleted; remove that worktree, then resume" % ", ".join(strays[:2])


class Runner(object):
    def __init__(self, ctx, op, journal):
        self.ctx, self.op, self.j = ctx, op, journal
        view = journal.load()
        confirms = [e for e in view.events if e.get("kind") == "confirm"]
        last = confirms[-1] if confirms else {}
        self.waived = set(last.get("waived", []))
        self.attested = set(last.get("attested", []))
        self.step_ids = [s["id"] for s in op["steps"]]

    # -- observation of real effects (independent of what we think we did)
    def observe(self, step):
        ctx, p, kind = self.ctx, step["params"], step["kind"]
        if kind == "unlink-link":
            return not lexists_nofollow(p["link"])
        if kind == "local-job-delete":
            ctx.cache.pop("jobs", None)
            avail, inst = local_jobs_instances(ctx)
            if not avail:
                return None  # cannot be observed right now, which is not the same as "still there"
            return all(str(i.get("id")) != p["id"] for i in inst)
        if kind == "cache-remove":
            return not lexists_nofollow(os.path.join(ctx.home, ".cursor", "projects", p["encoded"], p["cache"]))
        if kind == "worktree-remove":
            return not lexists_nofollow(p["path"])
        if kind == "delete-checkout":
            return not lexists_under(ctx, p["rel"]) and not lexists_under(ctx, tombstone_rel(p["rel"], self.tombstone(step)))
        return False

    def tombstone(self, step):
        return tombstone_name(self.op["operation_id"], step["id"], step["params"]["rel"])

    def fresh_target(self, rel):
        ctx = self.ctx
        ctx.cache.pop("lsof", None)
        t = resolve_targets(ctx, [rel])[0]
        t.setdefault("aspects", {})
        if t["rel"]:
            inspect_fs(ctx, t)
            if t["state"] == "present":
                collect_core(ctx, t, fleet_slugs(ctx), {}, {t["rel"]})
        return t

    def check_set_aside_registrations(self, step, path, fd, start_purge=False):
        rel = step["target"]
        approved = next(row for row in self.op["targets"] if row["rel"] == rel).get("registrations")
        started = next((event for event in self.j.load().events if event.get("kind") == "purge-start"
                        and event.get("step") == step["id"]), None)
        records = registration_records(fd, purging=started["registrations"] if started else (),
                                       allow_missing_git=bool(started) or approved is None)
        admin = os.path.join(path, ".git", "worktrees")
        original = os.path.join(self.ctx.root, rel)
        for name, row in records.items():
            if row["gitdir"] is None:
                continue
            folder, = registration_paths({name: row}, admin)
            if ((approved is not None and registration_binding(name, row) not in approved)
                    or (not is_under(folder, original) and not is_under(folder, path))):
                raise Refusal(stray_worktree_message([folder]))
        if start_purge and started is None:
            self.j.append("purge-start", step=step["id"], subsystem="worktrees", target=rel,
                          registrations=sorted(registration_id(name, row["identity"]) for name, row in records.items()))
            self.ctx.interrupt("after-registration-check:" + step["id"])

    def revalidate(self, step, resumed):
        kind = step["kind"]
        if kind == "delete-checkout":
            rel = step["params"]["rel"]
            tomb = os.path.join(self.ctx.root, tombstone_rel(rel, self.tombstone(step)))
            if lexists_nofollow(tomb):
                # Already renamed away under the approval, but finishing the delete still re-proves nothing is using it.
                # (lsof reports a renamed directory under its new path, so scanning the marker path is what finds users.)
                self.ctx.cache.pop("lsof", None)
                if is_under(self.ctx.start_cwd, tomb) or is_under(self.ctx.start_cwd, os.path.join(self.ctx.root, rel)):
                    return False, "the shell running this command is inside the checkout; change directory out of it and retry"
                if lexists_under(self.ctx, rel):
                    # The old checkout is safe under its marker, but the approval was for the path as it was then: look first, delete nothing.
                    return False, "something new now exists at %s while the old checkout is set aside under its removal marker; nothing more was deleted. Move the new item away, then resume" % rel
                affirm = classify_path(self.ctx, rel)[2] in ("affirm-src", "affirm-vendor")
                found, _risks = writer_blockers(self.ctx, rel, tomb, os.path.join(tomb, ".git"), affirm, (os.path.join(self.ctx.root, rel),))
                if found:
                    return False, "; ".join(b["message"] for b in found[:3])
                try:
                    fd, parent = open_chain(self.ctx, tombstone_rel(rel, self.tombstone(step)).split("/"))
                    try:
                        self.check_set_aside_registrations(step, tomb, fd)
                    finally:
                        os.close(fd)
                        if parent is not None:
                            os.close(parent)
                except (Refusal, PathProblem) as exc:
                    return False, exc.message
                # The approval covered the references that existed then. One that appears while the checkout sits under its marker means someone now wants the old path: the marker keeps the data, so stop before deleting it.
                refs = live_reference_blockers(self.ctx, {"rel": rel, "path": os.path.join(self.ctx.root, rel)}, [os.path.join(self.ctx.root, x["rel"]) for x in self.op["targets"] if x["rel"]])
                if refs:
                    return False, "; ".join(b["message"] for b in refs[:3]) + "; what is left of the old checkout stays under its removal marker and nothing more was deleted. Remove that reference, then resume"
                return True, ""
            t = self.fresh_target(rel)
            if t["state"] == "absent":
                return True, ""
            if t["blockers"]:
                return False, "; ".join(b["message"] for b in t["blockers"][:3])
            new_risks = sorted({r["id"] for r in t["risks"]} - self.waived)
            if new_risks:
                return False, "new risks appeared that were not waived: " + ", ".join(new_risks)
            mismatched = [aid for aid, expected in step["requires"]["aspects"].items() if t["aspects"].get(aid) != expected]
            if mismatched:
                return False, "changed since the preview: " + ", ".join(plain_aspect(a) for a in mismatched)
            extra = unplanned_worktrees(self.op, t)
            if extra:
                return False, "a linked worktree appeared after the preview (%s); run a new preview" % ", ".join(extra[:2])
            refs = live_reference_blockers(self.ctx, t, [os.path.join(self.ctx.root, x["rel"]) for x in self.op["targets"] if x["rel"]])
            if refs:
                return False, "; ".join(b["message"] for b in refs[:3])
            for other in self.op["steps"]:
                if other["kind"] == "worktree-remove" and other["target"] == rel and lexists_nofollow(other["params"]["path"]):
                    return False, "a linked worktree (%s) still exists" % other["params"]["path"]
            return True, ""
        if kind == "cache-remove":
            # Cursor spells two lookalike paths the same way, so a checkout that appeared after the preview can own this folder too.
            sharers = project_folder_claims(self.ctx, [os.path.join(self.ctx.root, x["rel"]) for x in self.op["targets"] if x["rel"]]).get(step["params"]["encoded"], [])
            if sharers:
                return False, "the Cursor project folder is also the one for %s (the names differ only in punctuation), so its caches are left alone; run a new preview" % ", ".join(sharers[:3])
        if kind == "worktree-remove" and lexists_nofollow(step["params"]["path"]):
            # The same proof a checkout gets: nobody is using this worktree right now, looked up fresh.
            wt = step["params"]["path"]
            self.ctx.cache.pop("lsof", None)
            affirm = classify_path(self.ctx, step["target"])[2] in ("affirm-src", "affirm-vendor")
            found, risks = writer_blockers(self.ctx, wt, wt, worktree_gitdir(self.ctx, wt), affirm)
            if found:
                return False, "; ".join(b["message"] for b in found[:3])
            new_risks = sorted({r["id"] for r in risks} - self.waived)
            if new_risks:
                return False, "new risks appeared that were not waived: " + ", ".join(new_risks)
        mismatched = []
        for aid, expected in step["requires"]["aspects"].items():
            actual = recompute_aspect(self.ctx, aid)
            if actual != expected:
                mismatched.append(aid)
        if mismatched:
            if resumed and self.observe(step):
                return True, ""
            return False, "changed since the preview: " + ", ".join(plain_aspect(a) for a in mismatched)
        return True, ""

    def perform(self, step):
        ctx, p, kind = self.ctx, step["params"], step["kind"]
        if kind == "unlink-link":
            return {"unlinked": 1} if unlink_link_nofollow(ctx, p["link"], p["readlink"]) else {"already": True}
        if kind == "local-job-delete":
            adapter = ctx.adapter("local-jobs")
            if not adapter:
                raise Refusal("the local-jobs tool is not available")
            # Recheck old journals as well as the gap between planning and dispatch.
            ctx.cache.pop("jobs", None)
            available, instances = local_jobs_instances(ctx)
            matches = [i for i in instances if i.get("id") == p["id"]] if available else []
            checkout = os.path.join(ctx.root, step["target"])
            expected = step["requires"]["aspects"].get("job:" + p["id"])
            if (len(matches) != 1 or not job_is_dedicated_to(matches[0], checkout)
                    or matches[0]["removal_revision"] != p.get("removal_revision")
                    or job_aspect_digest(matches[0]) != expected):
                raise Refusal("the previewed job is no longer uniquely bound to this checkout")
            res = run([adapter, "delete-fetch-if-current", "--id", p["id"],
                       "--if-revision", p["removal_revision"], "--confirm"], timeout=SUBPROCESS_TIMEOUT)
            if not res.ok:
                raise Refusal("local-jobs could not delete job %s (%s)" % (p["id"], short_err(res.errtext or res.text) or res.error or "failed"))
            return {"deleted": 1}
        if kind == "cache-remove":
            if p["cache"] not in CACHE_ALLOW or not re.match(r"^[A-Za-z0-9-]+$", p["encoded"]):
                raise Refusal("refusing to remove an unrecognised cache name")
            res = delete_tree(ctx, ctx.home, [".cursor", "projects", p["encoded"], p["cache"]], None)
            return {"entries": res["entries"]}
        if kind == "worktree-remove":
            return self.remove_worktree(step)
        if kind == "delete-checkout":
            sid = step["id"]

            def hook(point, counters, sid=sid):
                if point == "renamed":
                    ctx.interrupt("after-rename:" + sid)
                elif point == "entry" and counters["entries"] == 3:
                    ctx.interrupt("mid-delete:" + sid)

            affirm = classify_path(ctx, p["rel"])[2] in ("affirm-src", "affirm-vendor")

            def guard(work_path, tfd, rel=p["rel"], affirm=affirm):
                # The checkout has just been set aside under its marker name. lsof reports an open file under its
                # new path, so scanning the marker is what finds a program that started after the last check; the
                # original spelling is searched too, in case a tool still reports it that way. A worktree added
                # since the last look is found in the checkout's own Git state; nothing can add one by the old
                # path now, so after this look the set of worktrees is settled.
                ctx.cache.pop("lsof", None)
                found, _risks = writer_blockers(ctx, rel, work_path, os.path.join(work_path, ".git"), affirm, (os.path.join(ctx.root, rel),))
                if found:
                    raise Refusal("something started using the checkout after it was set aside: " + "; ".join(b["message"] for b in found[:3]))
                self.check_set_aside_registrations(step, work_path, tfd, start_purge=True)

            res = delete_checkout(ctx, p["rel"], p["identity"], hook, self.tombstone(step), guard)
            return {"entries": res["entries"], "already_absent": res["absent"]}
        if kind == "refresh-index":
            adapter = ctx.adapter("agent-route")
            if not adapter:
                raise Refusal("the agent-route tool is not available")
            res = run([adapter, "discover", "--full"], timeout=DOCTOR_TIMEOUT)
            if not res.ok:
                raise Refusal("agent-route could not refresh its index (%s)" % (short_err(res.errtext or res.text) or res.error or "failed"))
            return {"refreshed": True}
        raise Refusal("unknown step kind")

    def remove_worktree(self, step):
        ctx, p = self.ctx, step["params"]
        path = p["path"]
        target_path = os.path.join(ctx.root, step["target"])
        problem = worktree_location_problem(ctx, path)
        if problem:
            raise Refusal("refusing to remove linked worktree %s: %s" % (path, problem))
        uncommitted = bool(p["dirty"] or p["untracked"])
        waived_work = uncommitted and "linked-worktree-work" in self.waived
        adapter = ctx.adapter("worktree")
        if p["managed_by"] == "awa" and adapter:
            res = run([adapter, "clean", "--path", path], cwd=target_path, timeout=SUBPROCESS_TIMEOUT * 2)
            if res.ok and not lexists_nofollow(path):
                return {"via": "awa"}
            if uncommitted and not waived_work:
                raise Refusal("AWA would not remove %s and it holds uncommitted work (%s)" % (path, short_err(res.errtext or res.text) or res.error or "refused"))
        res = run(git_argv(ctx, target_path, "worktree", "remove", path), env=git_env(), timeout=SUBPROCESS_TIMEOUT)
        if not res.ok:
            if not waived_work:
                raise Refusal("git would not remove the linked worktree %s (%s)" % (path, short_err(res.errtext) or res.error or "refused"))
            res = run(git_argv(ctx, target_path, "worktree", "remove", "--force", "--force", path), env=git_env(), timeout=SUBPROCESS_TIMEOUT)
            if not res.ok:
                raise Refusal("git could not force-remove the linked worktree %s (%s)" % (path, short_err(res.errtext) or res.error or "refused"))
        if lexists_nofollow(path):
            raise Refusal("the linked worktree directory still exists")
        return {"via": "git"}

    def rescan(self, finished, upcoming, resume=False):
        """After a cohort (or when resuming): prove finished targets are gone and remaining ones are unchanged."""
        ctx = self.ctx
        remaining = []
        ids = self.step_ids
        view = self.j.load()
        states, _l = step_states(view.events, ids)
        pending = [s for s in self.op["steps"] if states[s["id"]] not in ("completed", "excepted")]
        remaining_rels = sorted(
            {
                s["target"]
                for s in pending
                if s["target"] and s["kind"] == "delete-checkout" and not lexists_under(ctx, tombstone_rel(s["params"]["rel"], self.tombstone(s)))
            }
        )
        changed = []
        for t in self.op["targets"]:
            for s in self.op["steps"]:
                if s["cohort"] == finished and s["kind"] == "delete-checkout" and s["target"] == t["rel"] and lexists_under(ctx, t["rel"]):
                    changed.append("%s still exists" % t["rel"])
        for s in self.op["steps"]:
            if s["kind"] == "delete-checkout" and states[s["id"]] == "completed" and lexists_under(ctx, s["params"]["rel"]):
                changed.append("%s exists again after it was removed" % s["params"]["rel"])
        if remaining_rels:
            ctx.cache.pop("lsof", None)
            ctx.cache.pop("jobs", None)
            targets, _info = assess_targets(ctx, remaining_rels)
            for t in targets:
                for b in t["blockers"]:
                    changed.append("%s: %s" % (t["rel"], b["message"]))
                extra = unplanned_worktrees(self.op, t)
                if extra:
                    changed.append("%s: a linked worktree appeared after the preview (%s)" % (t["rel"], ", ".join(extra[:2])))
            now_risks = sorted({r["id"] for t in targets for r in t["risks"]} - self.waived)
            if now_risks:
                changed.append("new risks: " + ", ".join(now_risks))
        for s in pending:
            if resume and states[s["id"]] != "pending":
                continue  # a started step reconciles itself (observe/revalidate) when it runs again
            for aid, expected in s["requires"]["aspects"].items():
                if aid.startswith(("tree:", "git:")):
                    continue
                if recompute_aspect(ctx, aid) != expected:
                    changed.append(plain_aspect(aid) + " changed")
        self.j.append("rescan", subsystem="operation", after=finished, before=upcoming, result="changed" if changed else "clean", changed=sorted(set(changed))[:20], remaining=len(remaining_rels))
        return not changed

    def execute(self, step, prior, pair):
        ctx, j = self.ctx, self.j
        sid = step["id"]
        resumed = prior == "open"
        # A step that was interrupted (open) or reported failed may in fact have taken effect: look before acting again.
        if prior in ("open", "failed") and self.observe(step):
            j.append("complete", step=sid, closes=pair["intent"], subsystem=step["kind"], target=step["target"], observed="the result was already in place when the run resumed", reconciled=True)
            return "completed"
        ok, why = self.revalidate(step, resumed)
        if not ok:
            fields = {"step": sid, "subsystem": step["kind"], "target": step["target"], "reason": jstr(why)[:400]}
            if resumed:
                fields["closes"] = pair["intent"]
            j.append("refusal", **fields)
            return "refused"
        if resumed:
            intent_seq = pair["intent"]
        else:
            ev = j.append(
                "intent",
                step=sid,
                subsystem=step["kind"],
                target=step["target"],
                cohort=step["cohort"],
                aspects=step["requires"]["aspects"],
                expect=step["expect"],
            )
            intent_seq = ev["seq"]
            ctx.interrupt("after-intent:" + sid)
        try:
            observed = self.perform(step)
        except Refusal as exc:
            j.append("failure", step=sid, closes=intent_seq, subsystem=step["kind"], target=step["target"], reason=jstr(exc.message)[:400])
            return "failed"
        except OSError as exc:
            j.append("failure", step=sid, closes=intent_seq, subsystem=step["kind"], target=step["target"], reason="operating-system error: %s" % errno.errorcode.get(exc.errno, exc.errno))
            return "failed"
        ctx.interrupt("after-action:" + sid)
        # A completion needs the effect to be observed. One that cannot be observed right now is a failure
        # (observe() returns None), and a later resume re-observes it and reconciles it as complete.
        seen = True if step["kind"] == "refresh-index" else self.observe(step)
        if not seen:
            reason = (
                "the action finished but its result could not be observed just now (the owning tool did not answer); resume checks again first"
                if seen is None
                else "the action finished but the expected result was not observed"
            )
            j.append("failure", step=sid, closes=intent_seq, subsystem=step["kind"], target=step["target"], reason=reason)
            return "failed"
        j.append("complete", step=sid, closes=intent_seq, subsystem=step["kind"], target=step["target"], observed=step["expect"], details=observed)
        ctx.interrupt("after-complete:" + sid)
        return "completed"

    def run(self, resuming=False):
        view = self.j.load()
        states, latest = step_states(view.events, self.step_ids)
        if resuming:
            first = next((s for s in self.op["steps"] if states[s["id"]] not in ("completed", "excepted")), None)
            if first is not None and not self.rescan("resume", first["cohort"], resume=True):
                return "paused"
        previous = None
        for step in self.op["steps"]:
            state = states[step["id"]]
            if state in ("completed", "excepted"):
                previous = step["cohort"]
                continue
            if previous is not None and step["cohort"] != previous:
                if not self.rescan(previous, step["cohort"]):
                    return "paused"
            previous = step["cohort"]
            result = self.execute(step, state, latest.get(step["id"]))
            if result != "completed":
                return result
        return "executed"


# ----- health

HEALTH_TOOLS = (
    ("dev-doctor", "dev-doctor", ()),
    ("local-jobs", "local-jobs", ("doctor",)),
    ("agent-route", "agent-route", ("doctor",)),
    ("shadowsync", "shadowsync", ("--doctor",)),
    ("awa", "worktree", ("doctor",)),
)
DOCTOR_SUMMARY_RE = re.compile(r"Summary:\s*(\d+)\s+repos\D+OK\s+(\d+)\D+ADVISORY\s+(\d+)\D+DRIFT\s+(\d+)\D+VIOLATION\s+(\d+)")
# One dev-doctor finding row: VERDICT, then columns separated by two or more spaces (PATH, CLASS, OWNER/REPO, ...).
DOCTOR_ROW_RE = re.compile(r"^VIOLATION\s{2,}(\S.*?)\s{2,}(\S+)\s{2,}(\S+)", re.M)
VOLATILE_RES = (
    re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2}| ?[A-Z]{3,4})?)?"),
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),
    re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|secs|seconds|min|minutes)\b"),
    re.compile(r"(?i)\bpid[ =:]*\d+\b"),
)


def normalize_health_text(text):
    """A tool's report with timestamps, durations and process ids removed, so equal problems compare equal."""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        for rx in VOLATILE_RES:
            line = rx.sub("~", line)
        lines.append(re.sub(r"\s+", " ", line))
    return "\n".join(lines)


def doctor_violation_ids(text):
    """Stable identities (short digests) of each violation row dev-doctor reported."""
    return sorted({sha256_hex("|".join(m.groups()))[:12] for m in DOCTOR_ROW_RE.finditer(text)})[:200]


def health_snapshot(ctx):
    rows = {}
    for name, adapter_name, args in HEALTH_TOOLS:
        adapter = ctx.adapter(adapter_name)
        if not adapter:
            rows[name] = {"status": "unavailable", "summary": "not installed on this machine", "metrics": {}}
            continue
        res = run([adapter] + list(args), timeout=DOCTOR_TIMEOUT, cwd=ctx.root)
        if res.timed_out:
            rows[name] = {"status": "timeout", "summary": "did not finish in time", "metrics": {}}
            continue
        if res.error:
            rows[name] = {"status": "unavailable", "summary": res.error, "metrics": {}}
            continue
        text = res.text + "\n" + res.errtext
        metrics = {}
        summary = short_err(res.text) or short_err(res.errtext) or ""
        m = DOCTOR_SUMMARY_RE.search(text)
        if m:
            metrics = {"repos": int(m.group(1)), "ok": int(m.group(2)), "advisory": int(m.group(3)), "drift": int(m.group(4)), "violation": int(m.group(5))}
            summary = "%s repos; OK %s, advisory %s, drift %s, violation %s" % m.groups()
        rows[name] = {
            "status": "ok" if res.rc == 0 else "nonok",
            "rc": res.rc,
            "summary": summary,
            "summary_digest": sha256_hex(summary)[:12],
            "output_digest": sha256_hex(normalize_health_text(text))[:16],
            "violations": doctor_violation_ids(text),
            "metrics": metrics,
        }
    return rows


def compare_health(base, now):
    """A subsystem passes when it is no worse than before: healthy stays healthy, and a pre-existing problem is
    unchanged (same report, same violations). Anything else needs a person's eyes or a recorded exception."""
    out = []
    for name in sorted(set(base) | set(now)):
        b, n = base.get(name), now.get(name)
        if not b or b["status"] in ("unavailable", "timeout"):
            if n and n["status"] == "nonok":
                out.append({"subsystem": name, "verdict": "no-baseline", "pass": False, "detail": "it reports a problem now and had no baseline to compare with: %s" % n["summary"]})
            else:
                out.append({"subsystem": name, "verdict": "no-baseline", "pass": True, "detail": "nothing to compare against"})
            continue
        if not n or n["status"] in ("unavailable", "timeout"):
            out.append({"subsystem": name, "verdict": "unverifiable", "pass": False, "detail": "could not be re-checked (%s)" % (n or {}).get("summary", "missing")})
            continue
        if b["status"] == "ok" and n["status"] == "nonok":
            out.append({"subsystem": name, "verdict": "regression", "pass": False, "detail": "was healthy before, now reports a problem: %s" % n["summary"]})
            continue
        bm, nm = b.get("metrics", {}), n.get("metrics", {})
        if nm.get("violation", 0) > bm.get("violation", 0):
            out.append({"subsystem": name, "verdict": "regression", "pass": False, "detail": "violations rose from %s to %s" % (bm.get("violation", 0), nm.get("violation", 0))})
            continue
        new_violations = sorted(set(n.get("violations") or []) - set(b.get("violations") or []))
        if new_violations:
            out.append({"subsystem": name, "verdict": "regression", "pass": False, "detail": "%d violation(s) appeared that were not there before" % len(new_violations)})
            continue
        if b["status"] == "ok":
            out.append({"subsystem": name, "verdict": "ok", "pass": True, "detail": n["summary"]})
        elif n["status"] == "ok":
            out.append({"subsystem": name, "verdict": "improved", "pass": True, "detail": n["summary"]})
        elif "violations" in b and "violations" in n and (b.get("violations") or n.get("violations")) and not nm.get("violation", 0) > bm.get("violation", 0):
            # dev-doctor: the same (or fewer) violations as before; its other lines move with the clock and the fetch state
            out.append({"subsystem": name, "verdict": "unchanged-nonok", "pass": True, "detail": "pre-existing violations, none new: %s" % n["summary"]})
        elif b.get("output_digest") is not None and b.get("output_digest") == n.get("output_digest"):
            out.append({"subsystem": name, "verdict": "unchanged-nonok", "pass": True, "detail": "pre-existing problem, unchanged: %s" % n["summary"]})
        else:
            out.append({"subsystem": name, "verdict": "changed-nonok", "pass": False, "detail": "a pre-existing problem changed, so it needs a human look (accept it with a subsystem-stale exception if unrelated): %s" % n["summary"]})
    return out



# --------------------------------------------------------------------------- commands

WRAPPER = "bash _ops/bin/dev-remove-repo.sh"


def split_csv(value):
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def public_target(t):
    g = t.get("git") or {}
    out = {
        "input": t["input"],
        "rel": t["rel"],
        "root_class": t["root_class"],
        "state": t["state"],
        "blockers": t["blockers"],
        "risks": t["risks"],
        "gates": t["gates"],
        "notes": t["notes"],
        "mentions": t.get("mentions", {}),
        "remote_mentions": t.get("remote_mentions", 0),
        "name_mentions": t.get("name_mentions", 0),
        "wiring": {
            "client_links": [{"link": l["link"]} for l in t["wiring"]["links"]],
            "jobs": [{"id": j["id"]} for j in t["wiring"]["jobs"]],
            "job_rows": [{"id": j["id"]} for j in t["wiring"]["job_rows"]],
            "project_dirs": [{"encoded": p["encoded"], "caches": p["caches"], "kept": p["kept"], "shared_with": p["shared_with"]} for p in t["wiring"]["project_dirs"]],
        },
    }
    if t.get("tree"):
        out["tree"] = {k: t["tree"][k] for k in ("files", "dirs", "symlinks", "bytes")}
    if g and not g.get("error"):
        out["git"] = {
            "head": (g.get("head") or "")[:12] or None,
            "branch": g.get("branch"),
            "status": g.get("status_counts"),
            "unpushed": g.get("unpushed"),
            "stashes": g.get("stashes"),
            "remotes": g.get("remotes"),
            "samples": g.get("samples"),
        }
        out["worktrees"] = [
            {"path": w["path"], "managed_by": w["managed_by"], "exists": w["exists"], "inside_target": w["inside_target"], "dirty": w["dirty"], "untracked": w["untracked"]}
            for w in t.get("worktrees", [])
        ]
    return out


def describe_detail(detail):
    if not detail:
        return ""
    bits = []
    for k in sorted(detail):
        v = detail[k]
        if k in ("digest",):
            continue
        bits.append("%s %s" % (k.replace("_", " "), v))
    return " (%s)" % ", ".join(bits) if bits else ""


def target_lines(t):
    head = "%s  [%s]" % (t["rel"] or t["input"], t["state"])
    lines = [head]
    for b in t["blockers"]:
        line = "  BLOCKED  %s" % b["message"]
        if b.get("remedy"):
            line += " -> %s" % b["remedy"]
        lines.append(line)
    for r in t["risks"]:
        lines.append("  RISK     %s%s" % (r["message"], describe_detail(r.get("detail"))))
    for g in t["gates"]:
        lines.append("  GATE     %s -> %s" % (g["message"], g.get("remedy", "")))
    wiring = t["wiring"]
    parts = []
    if wiring["links"]:
        parts.append("%d client link%s" % (len(wiring["links"]), "" if len(wiring["links"]) == 1 else "s"))
    if wiring["jobs"]:
        parts.append("%d scheduled job%s" % (len(wiring["jobs"]), "" if len(wiring["jobs"]) == 1 else "s"))
    for pd in wiring["project_dirs"]:
        if pd["caches"]:
            parts.append("Cursor caches (%s)" % ", ".join(pd["caches"]))
    if parts:
        lines.append("  CLEANUP  " + "; ".join(parts))
    for w in t.get("worktrees", []):
        if w["exists"]:
            lines.append("  WORKTREE %s (%s)%s" % (w["path"], w["managed_by"], "" if not (w["dirty"] or w["untracked"]) else " with uncommitted work"))
    for n in t["notes"]:
        lines.append("  note     " + n)
    g = t.get("git")
    if g and not g.get("error"):
        c = g["status_counts"]
        lines.append(
            "  facts    branch %s; %d changed, %d untracked, %d ignored; %d unpushed; %d stash"
            % (g.get("branch") or "(detached)", c["tracked"], c["untracked"], c["ignored"], g["unpushed_total"], g["stashes"])
        )
    return lines


def cmd_view(ctx, args):
    if args.operation:
        op, j, view = load_operation(ctx, args.operation, strict=False)
        states, _l = step_states(view.events, [s["id"] for s in op["steps"]])
        status = operation_status(op, view, ctx.now())
        exc = [{"class": e.get("class"), "scope": e.get("scope"), "reason": e.get("reason")} for e in view.events if e.get("kind") == "exception"]
        steps = [{"id": s["id"], "kind": s["kind"], "target": s["target"], "cohort": s["cohort"], "state": states[s["id"]]} for s in op["steps"]]
        data = {"ok": True, "operation": op["operation_id"], "status": status, "targets": [t["rel"] for t in op["targets"]], "cohorts": op["cohorts"], "steps": steps, "events": view.count, "exceptions": exc, "journal_chain_ok": view.chain_ok, "journal_problems": view.problems}
        lines = ["Operation %s: %s" % (op["operation_id"], status), "  targets: " + ", ".join(t["rel"] for t in op["targets"])]
        if view.problems:
            lines.append("  JOURNAL PROBLEM: " + "; ".join(view.problems[:3]))
        for s in steps:
            lines.append("  %s  %-16s %-10s %s" % (s["id"], s["kind"], s["state"], s["target"] or ""))
        if exc:
            lines.append("  exceptions recorded: %d" % len(exc))
        return data, lines, EXIT_OK
    if args.paths:
        targets, info = assess_targets(ctx, args.paths, args.scan_engine)
        data = {"ok": True, "readonly": True, "targets": [public_target(t) for t in targets], "scan": info, "required_waivers": required_waivers(targets), "required_attests": required_attests(targets)}
        lines = ["Read-only assessment (nothing was changed or recorded)."]
        for t in targets:
            lines += target_lines(t)
        if info.get("note"):
            lines.append("scan: " + info["note"])
        return data, lines, EXIT_OK
    ids = list_operation_ids(ctx)
    rows = []
    lines = ["%d operation%s in %s" % (len(ids), "" if len(ids) == 1 else "s", ctx.state_root)]
    for op_id in ids:
        legacy = legacy_record(ctx, op_id)
        if legacy is not None:
            rows.append({"operation": op_id, "status": "legacy-record", "events": legacy["events"], "closed": legacy["closed"], "problem": legacy_standing(legacy)[1]})
            continue
        try:
            op, j, view = load_operation(ctx, op_id, strict=False)
            rows.append({"operation": op_id, "status": "damaged" if view.problems else operation_status(op, view, ctx.now()), "targets": len(op["targets"])})
        except Refusal as exc:
            rows.append({"operation": op_id, "status": "unreadable", "problem": exc.message})
    for r in rows:
        lines.append("  %-28s %-16s %s" % (r["operation"], r["status"], ("%d target(s)" % r["targets"]) if "targets" in r else r.get("problem", "")))
    return {"ok": True, "operations": rows}, lines, EXIT_OK


def check_confirmation(ctx, op, view, args):
    """Every condition under which a confirmation is accepted. Raises Refusal with the first failure."""
    if view.closed:
        raise Refusal("operation %s is already closed" % op["operation_id"])
    if any(e.get("kind") == "confirm" for e in view.events):
        raise Refusal("operation %s was already confirmed; use resume to continue it" % op["operation_id"])
    if ctx.now() - op["created"] > PREVIEW_TTL_SECONDS:
        raise Refusal("the preview for %s expired (previews last %d minutes); run a new preview" % (op["operation_id"], PREVIEW_TTL_SECONDS // 60))
    if not args.confirm:
        raise Refusal("confirmation needs --confirm with the exact token from the preview")
    waived = sorted(set(split_csv(args.waive)))
    attested = sorted(set(split_csv(args.attest)))
    need_w, need_a = op["required_waivers"], op["required_attests"]
    missing = [w for w in need_w if w not in waived]
    extra = [w for w in waived if w not in need_w]
    if missing:
        raise Refusal("each risk must be waived by name; missing: --waive %s" % ",".join(missing))
    if extra:
        raise Refusal("these waivers do not match any risk in the preview: %s" % ",".join(extra))
    if [a for a in need_a if a not in attested] or [a for a in attested if a not in need_a]:
        raise Refusal("this operation needs exactly these attestations: %s" % (",".join(need_a) or "none"))
    expected = confirmation_token(op, waived, attested, op["preimages"])
    if not hmac_equal(args.confirm.strip(), expected):
        raise Refusal("the confirmation token does not match this operation, its targets, its plan and its waivers; copy it exactly from the preview")
    changed = []
    for aid, want in sorted(op["preimages"].items()):
        if recompute_aspect(ctx, aid) != want:
            changed.append(aid)
    if changed:
        raise Refusal("things changed after the preview: %s; nothing was done, run a new preview" % ", ".join(plain_aspect(a) for a in changed[:6]))
    return waived, attested


def hmac_equal(a, b):
    import hmac as _hmac

    return _hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def cmd_remove(ctx, args):
    if args.operation:
        return remove_confirm(ctx, args)
    if args.confirm or args.waive or args.attest:
        raise Refusal("--confirm, --waive and --attest belong with --operation ID", EXIT_USAGE)
    if not args.paths:
        raise Refusal("give at least one checkout path to preview, or --operation ID --confirm TOKEN", EXIT_USAGE)
    cohort_size = COHORT_MAX if args.cohort_size is None else args.cohort_size
    if not 1 <= cohort_size <= COHORT_MAX:
        raise Refusal("cohort size must be between 1 and %d" % COHORT_MAX, EXIT_USAGE)
    targets, info = assess_targets(ctx, args.paths, args.scan_engine)
    lines = ["Preview (nothing has been removed)."]
    for t in targets:
        lines += target_lines(t)
    data = {"ok": True, "stage": "preview", "targets": [public_target(t) for t in targets], "scan": info}
    if has_blockers(targets):
        data.update(ok=False, stage="blocked")
        lines.append("Nothing can be confirmed until every BLOCKED item is resolved. No operation was created.")
        return data, lines, EXIT_REFUSED
    cohorts, steps = build_plan(ctx, targets, cohort_size, bool(ctx.adapter("agent-route")))
    if not [s for s in steps if s["kind"] != "refresh-index"]:
        data.update(stage="nothing-to-do")
        lines.append("Nothing to do: every listed checkout is already absent and no wiring remains.")
        return data, lines, EXIT_OK
    with WriterLock(ctx):
        op, journal = create_operation(ctx, targets, cohort_size, info)
    token = confirmation_token(op, op["required_waivers"], op["required_attests"], op["preimages"])
    cmd = "%s remove --operation %s --confirm %s" % (WRAPPER, op["operation_id"], token)
    if op["required_waivers"]:
        cmd += " --waive " + ",".join(op["required_waivers"])
    if op["required_attests"]:
        cmd += " --attest " + ",".join(op["required_attests"])
    lines.append("Plan: %d step%s in %d cohort%s (at most %d checkouts each)." % (len(steps), "" if len(steps) == 1 else "s", len(cohorts), "" if len(cohorts) == 1 else "s", cohort_size))
    for s in steps:
        lines.append("  %s  %-16s %s" % (s["id"], s["kind"], s["expect"]))
    if op["required_waivers"]:
        lines.append("Risks that must each be waived by name: " + ", ".join(op["required_waivers"]))
    if op["required_attests"]:
        lines.append("Attestations required (the tool cannot verify these offline): " + ", ".join(op["required_attests"]))
    lines.append("The preview is valid for %d minutes and only for the state shown above." % (PREVIEW_TTL_SECONDS // 60))
    lines.append("To proceed, with the operator's explicit approval of the items above:")
    lines.append("  " + cmd)
    data.update(
        operation=op["operation_id"],
        action_digest=op["action_digest"],
        steps=[{"id": s["id"], "kind": s["kind"], "target": s["target"], "cohort": s["cohort"], "expect": s["expect"]} for s in steps],
        cohorts=cohorts,
        required_waivers=op["required_waivers"],
        required_attests=op["required_attests"],
        confirm_token=token,
        confirm_command=cmd,
        expires_in_seconds=PREVIEW_TTL_SECONDS,
    )
    return data, lines, EXIT_OK


def run_and_report(ctx, op, journal, header_lines, resuming=False):
    runner = Runner(ctx, op, journal)
    outcome = runner.run(resuming)
    view = journal.load()
    states, _l = step_states(view.events, runner.step_ids)
    counts = {}
    for v in states.values():
        counts[v] = counts.get(v, 0) + 1
    lines = list(header_lines)
    lines.append("Outcome: %s (%s)" % (outcome, ", ".join("%d %s" % (n, k) for k, n in sorted(counts.items()))))
    if outcome == "executed":
        lines.append("All steps finished. Next: %s verify --operation %s" % (WRAPPER, op["operation_id"]))
    else:
        last = [e for e in view.events if e.get("kind") in ("failure", "refusal", "rescan")][-1:]
        if last:
            reason = last[0].get("reason") or "; ".join(last[0].get("changed", [])) or ""
            lines.append("Stopped: %s" % reason)
        lines.append("Safe to continue after fixing that: %s resume --operation %s (or preview again if the state changed)" % (WRAPPER, op["operation_id"]))
    data = {"ok": outcome == "executed", "operation": op["operation_id"], "outcome": outcome, "steps": counts}
    return data, lines, EXIT_OK if outcome == "executed" else EXIT_REFUSED


def remove_confirm(ctx, args):
    op, journal, view = load_operation(ctx, args.operation)
    with WriterLock(ctx, op["operation_id"]):
        view = intact_view(journal, op["operation_id"])
        waived, attested = check_confirmation(ctx, op, view, args)
        targets, _info = assess_targets(ctx, [t["rel"] for t in op["targets"]], args.scan_engine)
        blockers = [(t["rel"], b["message"]) for t in targets for b in t["blockers"]]
        if blockers:
            raise Refusal("a blocker appeared after the preview: %s: %s" % blockers[0])
        for t in targets:
            extra_wt = unplanned_worktrees(op, t) if t["state"] == "present" else []
            if extra_wt:
                raise Refusal("a linked worktree appeared after the preview (%s); nothing was done, run a new preview" % ", ".join(extra_wt[:2]))
        for saved, current in zip(op["targets"], manifest_of(targets)):
            if "registrations" in saved and saved["registrations"] != current["registrations"]:
                raise Refusal("worktree registrations changed after the preview; start a new preview")
        extra = sorted({r["id"] for t in targets if t["state"] == "present" for r in t["risks"]} - set(waived))
        if extra:
            raise Refusal("a new risk appeared after the preview: %s; run a new preview" % ", ".join(extra))
        baseline = health_snapshot(ctx)
        journal.append("baseline", subsystem="doctors", health=baseline)
        journal.append("confirm", subsystem="operation", token_sha256=sha256_hex(args.confirm.strip()), waived=waived, attested=attested)
        return run_and_report(ctx, op, journal, ["Confirmed %s. Running %d steps." % (op["operation_id"], len(op["steps"]))])


def cmd_resume(ctx, args):
    if not args.operation:
        raise Refusal("resume needs --operation ID", EXIT_USAGE)
    op, journal, view = load_operation(ctx, args.operation)
    with WriterLock(ctx, op["operation_id"]):
        view = intact_view(journal, op["operation_id"])
        status = operation_status(op, view, ctx.now())
        if status in ("previewed", "expired-preview"):
            raise Refusal("operation %s has not been confirmed; nothing to resume (use remove --operation ... --confirm ...)" % op["operation_id"])
        if status == "closed":
            raise Refusal("operation %s is closed" % op["operation_id"])
        if status == "executed":
            raise Refusal("operation %s already finished all steps; run verify" % op["operation_id"])
        # resuming=True makes the runner re-assess every pending checkout (blockers, new risks, wiring,
        # recorded preimages) and stop with a rescan entry before it takes the first step.
        return run_and_report(ctx, op, journal, ["Resuming %s (was %s)." % (op["operation_id"], status)], resuming=True)


# ----- verify

HEALTH_NAMES = tuple(h[0] for h in HEALTH_TOOLS)
PATH_SCOPE_RE = re.compile(r"^[A-Za-z0-9._~@+ ()/-]+$")
DECLARATIVE_CLASSES = ("external-pending",)  # records something outside this machine that verify cannot see


def exception_scope_abs(ctx, ex):
    scope = ex["scope"]
    if scope.startswith("~/"):
        return os.path.join(ctx.home, scope[2:])
    return scope if scope.startswith("/") else os.path.join(ctx.root, scope)


def too_broad_scope(ctx, scope_abs):
    """A scope that is, or contains, the home folder, the dev root or a whole container of checkouts."""
    broad = [ctx.root, ctx.home, os.path.dirname(ctx.root), os.path.join(ctx.root, "affirm")]
    broad += [os.path.join(ctx.root, *parent) for parent in ALLOWED_PARENTS]
    broad += [os.path.join(ctx.home, d) for d in (".cursor", ".claude", ".codex", ".agents", ".local", ".config", "Library")]
    return any(is_under(b, scope_abs) for b in broad)


def parse_exception(ctx, spec):
    parts = spec.split(":", 2)
    if len(parts) != 3:
        raise Refusal("an exception looks like CLASS:SCOPE:REASON", EXIT_USAGE)
    klass, scope, reason = parts[0].strip(), parts[1].strip(), parts[2].strip()
    if klass not in EXCEPTION_CLASSES:
        raise Refusal("exception class must be one of: %s" % ", ".join(EXCEPTION_CLASSES), EXIT_USAGE)
    if not scope or not PATH_SCOPE_RE.match(scope):
        raise Refusal("the exception scope must be a clear path or subsystem name (letters, digits and . _ ~ @ + ( ) / - only)", EXIT_USAGE)
    if looks_secret(scope, entropy=False):
        raise Refusal("the scope looks like it contains a secret; name a path instead", EXIT_USAGE)
    if klass == "subsystem-stale":
        if scope not in HEALTH_NAMES:
            raise Refusal("a subsystem-stale exception names one subsystem: %s" % ", ".join(HEALTH_NAMES), EXIT_USAGE)
    else:
        if scope in HEALTH_NAMES:
            raise Refusal("%s names a subsystem; use the subsystem-stale class for it" % scope, EXIT_USAGE)
        if scope.startswith("~") and not scope.startswith("~/"):
            raise Refusal("write a home-folder scope as ~/path/inside/home", EXIT_USAGE)
        if scope.startswith("/") and not (is_under(scope, ctx.root) or is_under(scope, ctx.home)):
            raise Refusal("an absolute exception scope must be inside the dev root or the home folder", EXIT_USAGE)
        walk = scope[2:] if scope.startswith("~/") else scope.lstrip("/")
        if not walk or any(c in ("", ".", "..") for c in walk.split("/")):
            raise Refusal("the exception scope must be a canonical path (no '.', '..', '//' or trailing '/')", EXIT_USAGE)
        if too_broad_scope(ctx, exception_scope_abs(ctx, {"scope": scope})):
            raise Refusal("that scope is too broad; name the specific repository, file or folder that is left over", EXIT_USAGE)
    if len(reason) < 12 or len(reason) > 300:
        raise Refusal("an exception needs an honest reason of 12 to 300 characters", EXIT_USAGE)
    if any(ord(c) < 32 or ord(c) == 127 for c in reason):
        raise Refusal("the reason must be a single line of plain text", EXIT_USAGE)
    if looks_secret(reason):
        raise Refusal("the reason looks like it contains a secret or token; describe it without the value", EXIT_USAGE)
    return {"class": klass, "scope": scope, "reason": jstr(reason)}


def match_exception(ctx, path, exceptions):
    for ex in exceptions:
        if ex["class"] == "subsystem-stale":
            continue
        if is_under(path, exception_scope_abs(ctx, ex)):
            return ex
    return None


def retained_git_repos(ctx):
    repos = [ctx.root] if os.path.isdir(os.path.join(ctx.root, ".git")) else []
    for parent in (("affirm", "src"), ("affirm", "vendor"), ("personal",), ("capabilities",)):
        base = os.path.join(ctx.root, *parent)
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            p = os.path.join(base, name)
            if TOMBSTONE_RE.match(name):
                continue
            if not os.path.islink(p) and os.path.isdir(os.path.join(p, ".git")):
                repos.append(p)
    return repos


def cmd_verify(ctx, args):
    if not args.operation:
        raise Refusal("verify needs --operation ID", EXIT_USAGE)
    op, journal, view = load_operation(ctx, args.operation)
    new_exceptions = [parse_exception(ctx, spec) for spec in (args.exception or [])]
    with WriterLock(ctx, op["operation_id"]):
        view = intact_view(journal, op["operation_id"])
        if view.closed:
            outcome = view.events[-1].get("outcome")
            return (
                {"ok": True, "operation": op["operation_id"], "stage": "already-closed", "outcome": outcome},
                ["Operation %s is already closed (%s). Its journal is intact; verify reports the outcome recorded when it closed and does not re-check a closed operation." % (op["operation_id"], outcome)],
                EXIT_OK,
            )
        confirmed = any(e.get("kind") == "confirm" for e in view.events)
        if not confirmed:
            if args.discard_preview:
                n = view.count
                blob = b"".join(ln if ln.endswith(b"\n") else ln + b"\n" for ln in view.phys[:n])
                journal.append("close", subsystem="operation", outcome="unused-preview", events=n, events_sha256=sha256_hex(blob))
                return {"ok": True, "operation": op["operation_id"], "stage": "closed", "outcome": "unused-preview"}, ["Closed the unused preview %s. Nothing had been changed." % op["operation_id"]], EXIT_OK
            return (
                {"ok": False, "operation": op["operation_id"], "stage": "not-confirmed"},
                ["Operation %s was never confirmed, so nothing was executed. Close it with: %s verify --operation %s --discard-preview" % (op["operation_id"], WRAPPER, op["operation_id"])],
                EXIT_REFUSED,
            )
        # Exceptions are judged first and recorded only if they matched something verify actually found.
        ledger = [{"class": e["class"], "scope": e["scope"], "reason": e["reason"]} for e in view.events if e.get("kind") == "exception"]
        known = {digest_of(ex) for ex in ledger}
        fresh = []
        for ex in new_exceptions:
            if digest_of(ex) not in known:
                known.add(digest_of(ex))
                fresh.append(ex)
        exceptions = ledger + fresh
        used = set()
        ids = [s["id"] for s in op["steps"]]
        states, _l = step_states(view.events, ids)
        checks = []

        def add(cid, ok, message, items=None, excepted=0):
            checks.append({"id": cid, "status": "pass" if ok else ("excepted" if excepted and not items else "fail"), "message": message, "items": (items or [])[:25], "excepted": excepted})

        incomplete = [sid for sid in ids if states[sid] not in ("completed", "excepted")]
        add("steps", not incomplete, "every planned step finished" if not incomplete else "%d step(s) not finished: %s" % (len(incomplete), ", ".join(incomplete)), incomplete)
        removed = sorted({s["params"]["rel"] for s in op["steps"] if s["kind"] == "delete-checkout"} | {t["rel"] for t in op["targets"] if t["state"] == "absent"})
        runner0 = Runner(ctx, op, journal)
        markers = [tombstone_rel(s["params"]["rel"], runner0.tombstone(s)) for s in op["steps"] if s["kind"] == "delete-checkout"]
        still = [rel for rel in removed + markers if lexists_under(ctx, rel)]
        add("paths-absent", not still, "every removed checkout path is gone" if not still else "paths still exist", still)
        wt_paths = [os.path.join(ctx.root, rel) for rel in removed] + [s["params"]["path"] for s in op["steps"] if s["kind"] == "worktree-remove"]
        bad, unreadable = [], []
        for repo in retained_git_repos(ctx):
            try:
                listing, _registrations = checked_worktree_list(ctx, repo)
            except (Refusal, PathProblem):
                unreadable.append(os.path.relpath(repo, ctx.root))
                continue
            for rec in listing:
                if any(is_under(rec.get("path", ""), wp) for wp in wt_paths):
                    bad.append("%s lists %s" % (os.path.relpath(repo, ctx.root), rec.get("path")))
        add("worktrees-absent", not bad and not unreadable, "no repository still lists a removed worktree" if not (bad or unreadable) else "worktree listings are not clean", bad + ["could not read %s" % r for r in unreadable])
        # mentions
        entries = []
        for t in op["targets"]:
            names = [n for n in t.get("names", []) if distinctive_name(n)]
            entries.append({"rel": t["rel"], "slugs": t.get("slugs", []), "names": names})
        patterns = mention_patterns(entries)
        scope = scan_scope(ctx, [])
        cand = scan_candidates(ctx, [p["text"] for p in patterns], scope, args.scan_engine)
        cov = cand["coverage"]
        hits = refine_hits(cand["files"], patterns, [], cov)
        unmapped, mapped = [], 0

        def label_of(path):
            return os.path.relpath(path, ctx.root) if is_under(path, ctx.root) else path.replace(ctx.home, "~", 1)

        for path, row in sorted(hits.items()):
            ex = match_exception(ctx, path, exceptions)
            if ex:
                mapped += 1
                used.add(digest_of(ex))
            else:
                unmapped.append("%s (%s)" % (label_of(path), hit_surface(ctx, path)))
        # A search that could not read something has not proven the mentions are gone: say so, never "clean".
        for path in cov["unreadable"]:
            ex = match_exception(ctx, path, exceptions)
            if ex:
                mapped += 1
                used.add(digest_of(ex))
            else:
                unmapped.append("%s (could not be searched)" % label_of(path))
        if cov["unreadable_total"] > len(cov["unreadable"]):
            unmapped.append("%d more file(s) could not be searched" % (cov["unreadable_total"] - len(cov["unreadable"])))
        if cov["deadline"]:
            unmapped.append("the search stopped at its time limit, so it is incomplete")
        add("mentions", not unmapped, "no unexplained mentions remain (%d mapped to exceptions)" % mapped if not unmapped else "%d finding(s) still unexplained: files that mention a removed checkout, or files that could not be searched" % len(unmapped), unmapped, mapped)

        def refuse_unmatched(candidates):
            if candidates:
                raise Refusal(
                    "these exceptions match nothing that verify found, so none was recorded: %s. An exception is only for a specific leftover that verify reports"
                    % "; ".join("%s:%s" % (ex["class"], ex["scope"]) for ex in candidates[:3])
                )

        # Path exceptions can only apply to what the mention search found: refuse before the slow health checks run.
        refuse_unmatched([ex for ex in fresh if ex["class"] not in DECLARATIVE_CLASSES and ex["class"] != "subsystem-stale" and digest_of(ex) not in used])
        # effects of completed steps, observed again
        runner = Runner(ctx, op, journal)
        regressed, unobservable = [], []
        for s in op["steps"]:
            if states[s["id"]] != "completed" or s["kind"] == "refresh-index":
                continue
            seen = runner.observe(s)
            if seen is None:
                unobservable.append(s["id"])
            elif not seen:
                regressed.append(s["id"])
        if unobservable and not regressed:
            add("effects", False, "could not re-check some completed steps because the tool that owns them is not available now; restore it and verify again", unobservable)
        else:
            add("effects", not regressed, "every completed step still holds" if not regressed else "some completed steps no longer hold", regressed)
        # health versus the baseline taken just before the first change
        base_events = [e for e in view.events if e.get("kind") == "baseline"]
        base = base_events[-1].get("health", {}) if base_events else {}
        rows = compare_health(base, health_snapshot(ctx))
        failing, excused = [], 0
        for r in rows:
            if r["pass"]:
                continue
            stale = next((ex for ex in exceptions if ex["class"] == "subsystem-stale" and ex["scope"] == r["subsystem"]), None)
            if stale:
                excused += 1
                used.add(digest_of(stale))
                continue
            failing.append("%s: %s" % (r["subsystem"], r["detail"]))
        add("health", not failing, "no subsystem is worse than its baseline" if not failing else "a subsystem is worse than its baseline", failing, excused)
        refuse_unmatched([ex for ex in fresh if ex["class"] == "subsystem-stale" and digest_of(ex) not in used])
        for ex in fresh:
            journal.append("exception", subsystem="ledger", recorded_by="operator-supplied", **{"class": ex["class"], "scope": ex["scope"], "reason": ex["reason"]})
        passed = all(c["status"] in ("pass", "excepted") for c in checks)
        journal.append("verify", subsystem="verify", passed=passed, checks=[{"id": c["id"], "status": c["status"], "items": len(c["items"]), "excepted": c["excepted"]} for c in checks], health=[{"subsystem": r["subsystem"], "verdict": r["verdict"]} for r in rows])
        lines = ["Verification of %s:" % op["operation_id"]]
        for c in checks:
            lines.append("  %-9s %-16s %s" % (c["status"].upper(), c["id"], c["message"]))
            for item in c["items"]:
                lines.append("              - %s" % item)
        if passed:
            view = journal.load()
            n = view.count
            blob = b"".join(ln if ln.endswith(b"\n") else ln + b"\n" for ln in view.phys[:n])
            outcome = "verified-with-exceptions" if exceptions else "verified"
            journal.append("close", subsystem="operation", outcome=outcome, events=n, events_sha256=sha256_hex(blob), exceptions=len(exceptions))
            lines.append("All checks passed or are covered by a recorded exception. Operation closed (%s)." % outcome)
            if exceptions:
                lines.append("Accepted exceptions:")
                for ex in exceptions:
                    lines.append("  - [%s] %s: %s" % (ex["class"], ex["scope"], ex["reason"]))
        else:
            lines.append("Not closed. Fix the failing items, or record an honest exception: verify --operation %s --exception CLASS:SCOPE:REASON" % op["operation_id"])
        data = {"ok": passed, "operation": op["operation_id"], "stage": "closed" if passed else "open", "checks": checks, "exceptions": exceptions, "scan_engine": cand["engine"]}
        return data, lines, EXIT_OK if passed else EXIT_REFUSED


# ----- doctor

def cmd_doctor(ctx, args):
    if args.journal:
        report = inspect_journal_file(args.journal)
        lines = ["Journal %s" % args.journal, "  format: %s; events: %d; contiguous: %s" % (report["format"], report["events"], report["contiguous"])]
        lines.append("  operation ids: %s; closed: %s; close digest ok: %s; chain ok: %s" % (",".join(report["operation_ids"]), report["closed"], report["close_digest_ok"], report["chain_ok"]))
        by = {}
        for p in report["pairs"]:
            by[p["status"]] = by.get(p["status"], 0) + 1
        if report["pairing"] == "implicit":
            lines.append("  intents: %d (this older format pairs outcomes implicitly; pairing is not derived); completions: %d" % (report["intents"], report["kinds"].get("complete", 0)))
        else:
            lines.append("  intents: %d (%s); unpaired completions: %d" % (report["intents"], ", ".join("%d %s" % (n, k) for k, n in sorted(by.items())), report["unpaired_completes"]))
        ok = report["contiguous"] and report["chain_ok"] and report["unreadable_records"] == 0 and (not report["closed"] or report["close_digest_ok"] is not False)
        return dict(report, ok=ok), lines, EXIT_OK if ok else EXIT_REFUSED
    rows = []

    def row(cid, status, message):
        rows.append({"id": cid, "status": status, "message": message})

    row("python", "ok" if sys.version_info >= (3, 9) else "fail", "Python %d.%d.%d" % sys.version_info[:3])
    git = ctx.tool("git")
    if git:
        res = run([git, "--version"], timeout=20)
        row("git", "ok", short_err(res.text) or "git present")
    else:
        row("git", "fail", "git is not installed")
    rg = ctx.tool("rg")
    row("scan-engine", "ok" if rg else "warn", "ripgrep present" if rg else "ripgrep missing: the slower built-in scanner will be used")
    snap = lsof_snapshot(ctx)
    row("writer-proof", "ok" if snap["ok"] else "warn", "lsof can prove who is writing" if snap["ok"] else "%s: removals under affirm/ will be refused" % snap["reason"])
    row("affirm-policy", "ok" if policy_marker_present(ctx) else "info", "the affirm/ whole-checkout exception is in force" if policy_marker_present(ctx) else "the affirm/ exception is not in force: affirm/ targets stay operator gates")
    try:
        st = os.lstat(ctx.state_root)
        mode = stat.S_IMODE(st.st_mode)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            row("state-dir", "fail", "the state folder is not a plain directory")
        elif st.st_uid != os.geteuid():
            row("state-dir", "fail", "the state folder belongs to another user")
        elif mode & 0o022:
            row("state-dir", "warn", "the state folder is writable by others (mode %o)" % mode)
        else:
            row("state-dir", "ok", "state folder present")
    except FileNotFoundError:
        row("state-dir", "info", "no state yet (nothing has been previewed)")
    row("writer-lock", "warn" if lock_probe(ctx) == "held" else "ok", "another run is writing now" if lock_probe(ctx) == "held" else "no run is writing")
    left = leftover_tombstones(ctx)
    row("leftover-removals", "warn" if left else "ok", ("an interrupted removal left %s; run resume on its operation" % ", ".join(left)) if left else "no half-finished removals")
    for op_id in list_operation_ids(ctx):
        legacy = legacy_record(ctx, op_id)
        if legacy is not None:
            row("operation:" + op_id, *legacy_standing(legacy))
            continue
        try:
            op, j, view = load_operation(ctx, op_id, strict=False)
        except Refusal as exc:
            row("operation:" + op_id, "fail", exc.message)
            continue
        status = operation_status(op, view, ctx.now())
        if view.problems:
            row("operation:" + op_id, "fail", "journal integrity problem: " + "; ".join(view.problems[:3]))
        elif view.torn:
            row("operation:" + op_id, "warn", "its last record was cut short by an interruption; the next write recovers and records that")
        elif status == "interrupted":
            row("operation:" + op_id, "warn", "interrupted; run resume --operation %s" % op_id)
        elif status in ("failed", "paused"):
            row("operation:" + op_id, "warn", "%s; see view --operation %s" % (status, op_id))
        elif status == "executed":
            row("operation:" + op_id, "warn", "finished but not verified; run verify --operation %s" % op_id)
        elif status == "expired-preview":
            row("operation:" + op_id, "info", "unused preview expired; close it with verify --discard-preview")
        else:
            row("operation:" + op_id, "ok", status)
    for name in ("worktree", "awa-engine", "local-jobs", "agent-route", "shadowsync", "dev-doctor"):
        row("adapter:" + name, "ok" if ctx.adapter(name) else "info", "available" if ctx.adapter(name) else "not installed on this machine")
    ok = not [r for r in rows if r["status"] == "fail"]
    lines = ["dev-remove-repo doctor (%s)" % ("fixture" if ctx.fixture else "live")]
    for r in rows:
        lines.append("  %-5s %-34s %s" % (r["status"].upper(), r["id"], r["message"]))
    return {"ok": ok, "checks": rows, "mode": "fixture" if ctx.fixture else "live"}, lines, EXIT_OK if ok else EXIT_REFUSED


# ----- entry

def build_parser():
    parser = argparse.ArgumentParser(prog="dev-remove-repo", description="Safely remove whole retired checkouts under ~/dev with a preview, an exact confirmation, a journal and verification.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, paths=False):
        p.add_argument("--json", action="store_true", help="machine-readable output")
        p.add_argument("--scan-engine", choices=("auto", "rg", "python"), default="auto", help=argparse.SUPPRESS)
        if paths:
            p.add_argument("paths", nargs="*", help="checkout paths (affirm/src/NAME, affirm/vendor/NAME, personal/NAME, capabilities/NAME)")

    v = sub.add_parser("view", help="read-only: assess checkouts, or show operations")
    common(v, True)
    v.add_argument("--operation")
    v.add_argument("--personal-codex", action="store_true", help="inspect one canonical personal scaffold")
    v.add_argument("--fixture-root", help="personal scaffold fixture under the system temporary directory")
    r = sub.add_parser("remove", help="preview a removal (default) or confirm one")
    common(r, True)
    r.add_argument("--operation")
    r.add_argument("--confirm")
    r.add_argument("--waive", help="comma-separated risk ids, each named explicitly")
    r.add_argument("--attest", help="comma-separated external steps you completed")
    r.add_argument("--cohort-size", type=int)
    s = sub.add_parser("resume", help="continue an interrupted or paused operation")
    common(s)
    s.add_argument("--operation")
    ve = sub.add_parser("verify", help="independently verify and close an operation")
    common(ve)
    ve.add_argument("--operation")
    ve.add_argument("--exception", action="append", help="CLASS:SCOPE:REASON, an honest accepted leftover")
    ve.add_argument("--discard-preview", action="store_true")
    d = sub.add_parser("doctor", help="check this tool, its state and its journals")
    common(d)
    d.add_argument("--journal", help="inspect one journal file read-only")
    return parser


def emit(args, data, lines, code):
    if getattr(args, "json", False):
        out = dict(data)
        out["exit"] = code
        sys.stdout.write(scrub_secrets(json.dumps(sanitize(out), indent=2, sort_keys=True, ensure_ascii=False)) + "\n")
    else:
        for line in lines:
            sys.stdout.write(scrub_secrets(jstr(line)) + "\n")
    sys.stdout.flush()


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.setrecursionlimit(5000)
    try:
        personal = getattr(args, "personal_codex", False)
        if not personal and getattr(args, "fixture_root", None) is not None:
            raise Refusal("--fixture-root requires view --personal-codex", EXIT_USAGE)
        ctx = None if personal else Ctx()
    except Refusal as exc:
        if getattr(args, "json", False):
            emit(args, {"ok": False, "refused": exc.message}, [], exc.code)
        else:
            sys.stderr.write("dev-remove-repo: %s\n" % scrub_secrets(exc.message))
        return exc.code
    handlers = {"view": cmd_view, "remove": cmd_remove, "resume": cmd_resume, "verify": cmd_verify, "doctor": cmd_doctor}
    try:
        if personal:
            data, lines, code = personal_scaffold_view(args)
        else:
            data, lines, code = handlers[args.command](ctx, args)
    except Refusal as exc:
        data, lines, code = {"ok": False, "refused": exc.message}, ["Refused: " + exc.message], exc.code
    except Interrupted as exc:
        data = {"ok": False, "interrupted": str(exc)}
        lines = ["Interrupted at %s. The journal is intact; run resume to continue." % exc]
        code = EXIT_INTERRUPTED
    except KeyboardInterrupt:
        data = {"ok": False, "interrupted": "keyboard"}
        if args.command in ("view", "doctor"):
            lines = ["Interrupted. This command only reads; nothing was changed."]
        elif args.command == "verify":
            lines = ["Interrupted. The journal is intact; run verify again."]
        elif args.command == "resume" or getattr(args, "operation", None):
            lines = ["Interrupted. The journal is intact; run resume --operation ID to continue (view lists operations)."]
        else:
            lines = ["Interrupted while previewing. Any half-written preview is harmless; view lists operations and doctor checks them."]
        code = EXIT_INTERRUPTED
    emit(args, data, lines, code)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

PY_ENGINE
