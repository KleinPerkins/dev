#!/usr/bin/env python3
"""Conservative personal-source reconstruction for a fresh macOS host.

The manifest is intentionally data-only.  This program clones and verifies pinned
KleinPerkins sources; it never runs repository code, legacy bootstrap entrypoints,
capability installers, or host-configuration writers.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence
import unicodedata
import uuid


MANIFEST_SCHEMA = "personal-portability/manifest/v1"
REPORT_SCHEMA = "personal-portability/report/v1"
JOURNAL_SCHEMA = "personal-portability/journal/v1"
PROFILE = "personal-codex"
EXPECTED_PLATFORM = {"os": "Darwin", "architecture": "arm64"}
PERSONAL_NAME = "KleinPerkins"
PERSONAL_EMAIL = "49759187+KleinPerkins@users.noreply.github.com"

TOP_KEYS = frozenset(
    {"schema", "profile", "platform", "repositories", "capabilities", "local_state"}
)
REPOSITORY_KEYS = frozenset(
    {"id", "path", "revision", "disposition", "reason", "required"}
)
CAPABILITY_KEYS = frozenset({"id", "owner", "disposition", "reason", "required"})
LOCAL_STATE_KEYS = frozenset({"id", "disposition", "reason", "required"})
REPOSITORY_DISPOSITIONS = frozenset(
    {"clone", "source-only", "excluded-work", "blocked-protected", "blocked-review"}
)
ACTIVE_REPOSITORY_DISPOSITIONS = frozenset({"clone", "source-only"})
CAPABILITY_DISPOSITIONS = frozenset(
    {"blocked-owner-gate", "source-only", "excluded-work", "account-reconnect"}
)
LOCAL_STATE_DISPOSITIONS = frozenset({"recreate", "blocked-review", "excluded-work"})
HEX_REVISION = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_ID = re.compile(r"^KleinPerkins/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
REMOTE_SCP = re.compile(r"^git@github\.com:KleinPerkins/([A-Za-z0-9][A-Za-z0-9._-]{0,99})\.git$")
REMOTE_HTTPS = re.compile(r"^https://github\.com/KleinPerkins/([A-Za-z0-9][A-Za-z0-9._-]{0,99})\.git$")
REMOTE_SSH = re.compile(r"^ssh://git@github\.com/KleinPerkins/([A-Za-z0-9][A-Za-z0-9._-]{0,99})\.git$")
WORK_REPOSITORIES = frozenset({"cpp", "aianalyticscontext"})
PROTECTED_REPOSITORY = "chaosscheduler"
MIXED_REPOSITORIES = frozenset({"dev", "chaoslabs"})
WORK_BRIDGE_REPOSITORY = "ecosystemorchestrator"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_GIT_INVENTORY_ENTRIES = 250_000
MAX_GIT_INVENTORY_BYTES = 8 * 1024 * 1024 * 1024


class PortabilityError(Exception):
    """A controlled failure safe to surface without raw process output."""


class ManifestError(PortabilityError):
    pass


class SafetyError(PortabilityError):
    pass


class GitError(PortabilityError):
    def __init__(self, operation: str, returncode: int | None = None):
        suffix = "" if returncode is None else f" (exit {returncode})"
        super().__init__(f"Git {operation} failed{suffix}; no raw Git output was retained")
        self.operation = operation
        self.returncode = returncode


class _DuplicateKey(ValueError):
    pass


def _closed_object(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ManifestError(f"{label} must be an object")
    actual = frozenset(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unknown:
            details.append("unknown=" + ",".join(unknown))
        raise ManifestError(f"{label} has a non-closed schema ({'; '.join(details)})")
    return value


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _nonempty_string(value: Any, label: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ManifestError(f"{label} must be a non-empty, trimmed string")
    if any(ord(character) < 32 for character in value):
        raise ManifestError(f"{label} contains a control character")
    return value


def _normalized_alias(value: str) -> str:
    return "".join(character for character in unicodedata.normalize("NFKC", value).casefold() if character.isalnum())


def _path_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _validate_relative_path(value: Any, label: str) -> str:
    value = _nonempty_string(value, label)
    if value == ".":
        return value
    if "\\" in value or value.startswith("/") or value.endswith("/") or "//" in value:
        raise ManifestError(f"{label} must be a normalized POSIX relative path")
    path = PurePosixPath(value)
    if str(path) != value or any(part in {"", ".", ".."} for part in path.parts):
        raise ManifestError(f"{label} must not contain empty, dot, or parent segments")
    for part in path.parts:
        lowered = unicodedata.normalize("NFC", part).casefold()
        if lowered == ".git" or lowered.startswith(".portability-"):
            raise ManifestError(f"{label} contains a reserved internal path component")
    return value


def _validate_required(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise ManifestError(f"{label} must be a boolean")
    return value


def _validate_id(value: Any, label: str) -> str:
    value = _nonempty_string(value, label)
    if not REPOSITORY_ID.fullmatch(value):
        raise ManifestError(f"{label} must be a KleinPerkins repository identity")
    if value.endswith(".") or value.endswith(".git"):
        raise ManifestError(f"{label} has an unsafe repository name")
    return value


def _active_identity_is_forbidden(repository_id: str, path: str) -> str | None:
    name = _normalized_alias(repository_id.split("/", 1)[1])
    segments = {_normalized_alias(part) for part in PurePosixPath(path).parts if part != "."}
    if name.startswith(PROTECTED_REPOSITORY) or any(
        segment.startswith(PROTECTED_REPOSITORY) for segment in segments
    ):
        return "protected chaos-scheduler identity/path"
    if any(name.startswith(work_name) for work_name in WORK_REPOSITORIES) or any(
        segment.startswith(work_name) for segment in segments for work_name in WORK_REPOSITORIES
    ):
        return "known work repository identity"
    if any(segment.startswith("affirm") for segment in segments):
        return "Affirm path segment"
    if any(segment in MIXED_REPOSITORIES for segment in segments):
        return "mixed-work repository path"
    if WORK_BRIDGE_REPOSITORY in segments:
        return "work bridge repository path"
    return None


def validate_manifest(document: Any) -> dict[str, Any]:
    """Validate and return the closed personal-portability manifest object."""
    manifest = _closed_object(document, TOP_KEYS, "manifest")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise ManifestError(f"manifest.schema must equal {MANIFEST_SCHEMA}")
    if manifest["profile"] != PROFILE:
        raise ManifestError(f"manifest.profile must equal {PROFILE}")
    platform_value = _closed_object(manifest["platform"], frozenset({"os", "architecture"}), "platform")
    if platform_value != EXPECTED_PLATFORM:
        raise ManifestError("platform must be exactly Darwin/arm64")

    repositories = manifest["repositories"]
    if type(repositories) is not list or not repositories:
        raise ManifestError("repositories must be a non-empty list")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, value in enumerate(repositories):
        label = f"repositories[{index}]"
        row = _closed_object(value, REPOSITORY_KEYS, label)
        repository_id = _validate_id(row["id"], f"{label}.id")
        path = _validate_relative_path(row["path"], f"{label}.path")
        disposition = row["disposition"]
        if disposition not in REPOSITORY_DISPOSITIONS:
            raise ManifestError(f"{label}.disposition is not supported")
        revision = row["revision"]
        if disposition in ACTIVE_REPOSITORY_DISPOSITIONS:
            if type(revision) is not str or not HEX_REVISION.fullmatch(revision):
                raise ManifestError(f"{label}.revision must be 40 lowercase hex for {disposition}")
            forbidden = _active_identity_is_forbidden(repository_id, path)
            if forbidden:
                raise ManifestError(f"{label} cannot reconstruct a {forbidden}")
        elif revision is not None and (type(revision) is not str or not HEX_REVISION.fullmatch(revision)):
            raise ManifestError(f"{label}.revision must be null or 40 lowercase hex")
        name_alias = _normalized_alias(repository_id.split("/", 1)[1])
        if name_alias in WORK_REPOSITORIES and disposition != "excluded-work":
            raise ManifestError(f"{label} must classify the known work repository as excluded-work")
        if name_alias == WORK_BRIDGE_REPOSITORY and disposition != "excluded-work":
            raise ManifestError(f"{label} must classify the work bridge repository as excluded-work")
        if name_alias in MIXED_REPOSITORIES and disposition != "blocked-review":
            raise ManifestError(f"{label} must keep the mixed-work repository blocked-review")
        if name_alias == PROTECTED_REPOSITORY and disposition not in {"blocked-protected", "excluded-work"}:
            raise ManifestError(f"{label} must keep chaos-scheduler blocked or excluded")
        _nonempty_string(row["reason"], f"{label}.reason")
        _validate_required(row["required"], f"{label}.required")
        id_key = repository_id.casefold()
        path_key = _path_key(path)
        if id_key in seen_ids:
            raise ManifestError(f"duplicate repository id: {repository_id}")
        if path_key in seen_paths:
            raise ManifestError(f"duplicate/colliding repository path: {path}")
        seen_ids.add(id_key)
        seen_paths.add(path_key)

    non_root_paths = [
        tuple(unicodedata.normalize("NFC", part).casefold() for part in PurePosixPath(row["path"]).parts)
        for row in repositories
        if row["path"] != "."
    ]
    for index, left in enumerate(non_root_paths):
        for right in non_root_paths[index + 1 :]:
            shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
            if longer[: len(shorter)] == shorter:
                raise ManifestError("non-root repository paths must not overlap")

    capabilities = manifest["capabilities"]
    if type(capabilities) is not list:
        raise ManifestError("capabilities must be a list")
    capability_ids: set[str] = set()
    for index, value in enumerate(capabilities):
        label = f"capabilities[{index}]"
        row = _closed_object(value, CAPABILITY_KEYS, label)
        capability_id = _nonempty_string(row["id"], f"{label}.id")
        _nonempty_string(row["owner"], f"{label}.owner")
        if row["disposition"] not in CAPABILITY_DISPOSITIONS:
            raise ManifestError(f"{label}.disposition is not supported")
        _nonempty_string(row["reason"], f"{label}.reason")
        _validate_required(row["required"], f"{label}.required")
        key = unicodedata.normalize("NFC", capability_id).casefold()
        if key in capability_ids:
            raise ManifestError(f"duplicate capability id: {capability_id}")
        capability_ids.add(key)

    local_state = manifest["local_state"]
    if type(local_state) is not list:
        raise ManifestError("local_state must be a list")
    state_ids: set[str] = set()
    for index, value in enumerate(local_state):
        label = f"local_state[{index}]"
        row = _closed_object(value, LOCAL_STATE_KEYS, label)
        state_id = _nonempty_string(row["id"], f"{label}.id")
        if row["disposition"] not in LOCAL_STATE_DISPOSITIONS:
            raise ManifestError(f"{label}.disposition is not supported")
        _nonempty_string(row["reason"], f"{label}.reason")
        _validate_required(row["required"], f"{label}.required")
        key = unicodedata.normalize("NFC", state_id).casefold()
        if key in state_ids:
            raise ManifestError(f"duplicate local_state id: {state_id}")
        state_ids.add(key)
    return manifest


class LoadedManifest:
    def __init__(self, path: Path, raw: bytes, document: dict[str, Any]):
        self.path = path
        self.raw = raw
        self.document = document
        self.digest = "sha256:" + hashlib.sha256(raw).hexdigest()


def load_manifest(path: str | os.PathLike[str]) -> LoadedManifest:
    manifest_path = Path(path)
    try:
        info = manifest_path.lstat()
    except OSError as error:
        raise ManifestError("manifest is unavailable") from error
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise ManifestError("manifest must be a regular, non-symlink file")
    if info.st_size > MAX_MANIFEST_BYTES:
        raise ManifestError("manifest exceeds the bounded size limit")
    try:
        raw = manifest_path.read_bytes()
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs_without_duplicates)
    except (_DuplicateKey, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError("manifest must be duplicate-free UTF-8 JSON") from error
    return LoadedManifest(manifest_path, raw, validate_manifest(document))


def canonical_remote(repository_id: str) -> str:
    _validate_id(repository_id, "repository id")
    return f"git@github.com:{repository_id}.git"


def remote_identity(remote: str) -> str | None:
    for expression in (REMOTE_SCP, REMOTE_HTTPS, REMOTE_SSH):
        match = expression.fullmatch(remote)
        if match:
            return "KleinPerkins/" + match.group(1)
    return None


class GitRunner:
    """Git subprocess boundary. Tests inject a local transport at this seam."""

    def __init__(self, executable: str = "git"):
        self.executable = executable

    def _environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        for key in tuple(environment):
            if key.startswith("GIT_") or key in {"SSH_ASKPASS", "SSH_ASKPASS_REQUIRE"}:
                environment.pop(key, None)
        environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_SSH_COMMAND": (
                    "/usr/bin/ssh -F /dev/null -o BatchMode=yes -o StrictHostKeyChecking=yes "
                    "-o UpdateHostKeys=no -o ConnectTimeout=15 -o ServerAliveInterval=15 "
                    "-o ServerAliveCountMax=2"
                ),
                "GCM_INTERACTIVE": "Never",
                "LC_ALL": "C",
            }
        )
        return environment

    def _run(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path | None = None,
        operation: str,
        check: bool = True,
        timeout: float = 30.0,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [self.executable, *arguments],
                cwd=None if cwd is None else os.fspath(cwd),
                env=self._environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=timeout,
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            raise GitError(operation) from error
        if check and result.returncode != 0:
            raise GitError(operation, result.returncode)
        return result

    @staticmethod
    def _safe_options() -> list[str]:
        return [
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "submodule.recurse=false",
        ]

    def check_available(self) -> None:
        if not os.access("/usr/bin/ssh", os.X_OK):
            raise GitError("SSH prerequisite check")
        self._run(["--version"], operation="availability check")

    def probe(self, remote: str) -> str:
        output = self._run(
            [*self._safe_options(), "ls-remote", "--symref", remote, "HEAD", "refs/heads/main"],
            operation="access probe",
            timeout=45.0,
        ).stdout.splitlines()
        head_is_main = any(line == "ref: refs/heads/main\tHEAD" for line in output)
        main_revisions = [line.split("\t", 1)[0] for line in output if line.endswith("\trefs/heads/main")]
        if not head_is_main or len(main_revisions) != 1 or not HEX_REVISION.fullmatch(main_revisions[0]):
            raise GitError("default-main provenance probe")
        return main_revisions[0]

    def clone(self, remote: str, destination: Path) -> None:
        self._run(
            [
                *self._safe_options(),
                "-c",
                "init.templateDir=",
                "clone",
                "--no-checkout",
                "--no-recurse-submodules",
                "--origin",
                "origin",
                "--",
                remote,
                os.fspath(destination),
            ],
            operation="clone",
            timeout=600.0,
        )

    def remote_urls(self, repository: Path) -> dict[str, str]:
        result = self._run(
            [
                *self._safe_options(),
                "-C",
                os.fspath(repository),
                "config",
                "--local",
                "--no-includes",
                "--get-regexp",
                r"^remote\..*\.url$",
            ],
            operation="remote identity read",
            check=False,
        )
        if result.returncode not in {0, 1}:
            raise GitError("remote identity read", result.returncode)
        remotes: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if " " not in line:
                raise GitError("remote identity read")
            key, value = line.split(" ", 1)
            match = re.fullmatch(r"remote\.([^.]+)\.url", key)
            if not match or match.group(1) in remotes:
                raise GitError("remote identity read")
            remotes[match.group(1)] = value
        return remotes

    def local_identity(self, repository: Path) -> tuple[str | None, str | None]:
        values: list[str | None] = []
        for key in ("user.name", "user.email"):
            result = self._run(
                [
                    *self._safe_options(),
                    "-C",
                    os.fspath(repository),
                    "config",
                    "--local",
                    "--no-includes",
                    "--get",
                    key,
                ],
                operation="local identity read",
                check=False,
            )
            if result.returncode not in {0, 1}:
                raise GitError("local identity read", result.returncode)
            values.append(result.stdout.strip() if result.returncode == 0 else None)
        return values[0], values[1]

    def local_config(self, repository: Path) -> dict[str, str]:
        result = self._run(
            [
                *self._safe_options(),
                "-C",
                os.fspath(repository),
                "config",
                "--local",
                "--no-includes",
                "--null",
                "--list",
            ],
            operation="local config safety read",
        )
        values: dict[str, str] = {}
        for record in result.stdout.split("\0"):
            if not record:
                continue
            if "\n" not in record:
                raise GitError("local config safety read")
            key, value = record.split("\n", 1)
            if key in values:
                raise GitError("local config safety read")
            values[key] = value
        return values

    def has_commit(self, repository: Path, revision: str) -> None:
        self._run(
            [*self._safe_options(), "-C", os.fspath(repository), "cat-file", "-e", f"{revision}^{{commit}}"],
            operation="revision verification",
        )

    def verify_main_ancestry(self, repository: Path, revision: str, main_revision: str) -> None:
        observed = self._run(
            [
                *self._safe_options(),
                "-C",
                os.fspath(repository),
                "rev-parse",
                "refs/remotes/origin/main",
            ],
            operation="default-main revision read",
        ).stdout.strip()
        if observed != main_revision:
            raise GitError("default-main revision changed during reconstruction")
        result = self._run(
            [
                *self._safe_options(),
                "-C",
                os.fspath(repository),
                "merge-base",
                "--is-ancestor",
                revision,
                "refs/remotes/origin/main",
            ],
            operation="default-main ancestry verification",
            check=False,
        )
        if result.returncode != 0:
            raise GitError("default-main ancestry verification", result.returncode)

    def configure_identity(self, repository: Path) -> None:
        for key, value in (("user.name", PERSONAL_NAME), ("user.email", PERSONAL_EMAIL)):
            self._run(
                [*self._safe_options(), "-C", os.fspath(repository), "config", "--local", key, value],
                operation="local identity configuration",
            )

    def checkout(self, repository: Path, revision: str) -> None:
        self._run(
            [
                *self._safe_options(),
                "-C",
                os.fspath(repository),
                "-c",
                "advice.detachedHead=false",
                "checkout",
                "--detach",
                revision,
            ],
            operation="pinned checkout",
        )

    def head(self, repository: Path) -> str:
        return self._run(
            [*self._safe_options(), "-C", os.fspath(repository), "rev-parse", "HEAD"],
            operation="HEAD verification",
        ).stdout.strip()

    def status(self, repository: Path, *, include_ignored: bool = False) -> list[str]:
        arguments = [
            *self._safe_options(),
            "-C",
            os.fspath(repository),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ]
        if include_ignored:
            arguments.append("--ignored")
        output = self._run(arguments, operation="cleanliness verification").stdout
        return [line for line in output.splitlines() if line]

    def refs(self, repository: Path) -> dict[str, str]:
        output = self._run(
            [
                *self._safe_options(),
                "-C",
                os.fspath(repository),
                "for-each-ref",
                "--format=%(refname)%00%(objectname)",
            ],
            operation="reference verification",
        ).stdout
        refs: dict[str, str] = {}
        for line in output.splitlines():
            if "\x00" not in line:
                raise GitError("reference verification")
            name, revision = line.split("\x00", 1)
            refs[name] = revision
        return refs


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def _lexists(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def _regular_private_file(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise SafetyError("owned state file is missing") from error
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise SafetyError("owned state path must be a regular non-symlink file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise SafetyError("owned state file must belong to the current user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise SafetyError("owned state file permissions are not private")
    return info


def _atomic_write(path: Path, content: bytes, mode: int = 0o600, *, replace: bool) -> None:
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise SafetyError("atomic-write parent must be an existing non-symlink directory")
    if replace:
        _regular_private_file(path)
    elif _lexists(path):
        raise SafetyError("refusing to overwrite a pre-existing unowned state file")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError as error:
                raise SafetyError("state target appeared during no-clobber publish") from error
            temporary.unlink()
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _git_inventory(repository: Path) -> dict[str, Any]:
    git_directory = repository / ".git"
    info = git_directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise SafetyError("Git metadata inventory requires an ordinary .git directory")
    digest = hashlib.sha256()
    entries = 0
    total_bytes = 0
    for current_text, directories, files in os.walk(git_directory, topdown=True, followlinks=False):
        current = Path(current_text)
        directories.sort()
        files.sort()
        for name, kind in [(name, "directory") for name in directories] + [
            (name, "file") for name in files
        ]:
            path = current / name
            path_info = path.lstat()
            relative = path.relative_to(git_directory).as_posix()
            entries += 1
            if entries > MAX_GIT_INVENTORY_ENTRIES:
                raise SafetyError("Git metadata inventory exceeds the entry bound")
            if kind == "directory":
                if not stat.S_ISDIR(path_info.st_mode) or stat.S_ISLNK(path_info.st_mode):
                    raise SafetyError("Git metadata contains an unsupported directory entry")
                content_digest = "-"
                size = 0
            else:
                if not stat.S_ISREG(path_info.st_mode) or stat.S_ISLNK(path_info.st_mode):
                    raise SafetyError("Git metadata contains an unsupported file entry")
                size = path_info.st_size
                total_bytes += size
                if total_bytes > MAX_GIT_INVENTORY_BYTES:
                    raise SafetyError("Git metadata inventory exceeds the byte bound")
                content_digest = _sha256_file(path)
            record = (
                f"{kind}\0{relative}\0{stat.S_IMODE(path_info.st_mode):o}\0{size}\0"
                f"{path_info.st_nlink}\0{content_digest}\n"
            )
            digest.update(record.encode("utf-8"))
    return {
        "sha256": "sha256:" + digest.hexdigest(),
        "entries": entries,
        "bytes": total_bytes,
    }


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically install a directory without replacing a concurrent target."""
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(source)
    destination_bytes = os.fsencode(destination)
    system = platform.system()
    result: int
    if system == "Darwin" and hasattr(libc, "renamex_np"):
        result = libc.renamex_np(source_bytes, destination_bytes, 0x00000004)  # RENAME_EXCL
    elif hasattr(libc, "renameat2"):
        result = libc.renameat2(-100, source_bytes, -100, destination_bytes, 1)  # RENAME_NOREPLACE
    else:
        raise SafetyError("atomic no-clobber directory install is unavailable on this host")
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise SafetyError("target appeared during atomic install; it was preserved")
        raise SafetyError("atomic no-clobber directory install failed")


class FileLock:
    def __init__(self, path: Path):
        self.path = path
        self._file: Any = None

    def __enter__(self) -> "FileLock":
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if not nofollow:
            raise SafetyError("non-following lock creation is unavailable")
        try:
            descriptor = os.open(
                self.path,
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | nofollow,
                0o600,
            )
        except OSError as error:
            raise SafetyError("lock path is unsafe or unavailable") from error
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or (hasattr(os, "getuid") and info.st_uid != os.getuid())
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            os.close(descriptor)
            raise SafetyError("lock path must be a private regular file owned by the current user")
        self._file = os.fdopen(descriptor, "a+", encoding="utf-8")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self._file.close()
            raise SafetyError("another portability operation owns the target lock") from error
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._file is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            self._file.close()


class Engine:
    def __init__(
        self,
        manifest: str | os.PathLike[str],
        root: str | os.PathLike[str],
        state_dir: str | os.PathLike[str],
        report: str | os.PathLike[str] | None = None,
        *,
        git: GitRunner | None = None,
        platform_probe: Callable[[], tuple[str, str]] | None = None,
        now: Callable[[], dt.datetime] | None = None,
    ):
        self.loaded = load_manifest(manifest)
        self.manifest = self.loaded.document
        self.root = self._bound_path(root, "root")
        self.state_dir = self._bound_path(state_dir, "state-dir")
        if self.root == Path(self.root.anchor):
            raise SafetyError("root cannot be a filesystem root")
        home = Path.home().resolve()
        if self.root == home or self._is_within(home, self.root):
            raise SafetyError("root must not be the home directory or one of its ancestors")
        if self.state_dir == self.root or self._is_within(self.state_dir, self.root):
            raise SafetyError("state-dir must be outside the reconstruction root")
        if self._git_metadata_ancestor(self.state_dir) is not None:
            raise SafetyError("state-dir must be outside every Git worktree")
        self.explicit_report = report is not None
        self.report_path = self._bound_path(report, "report") if report is not None else self.state_dir / "report.json"
        if self.report_path.parent != self.state_dir:
            raise SafetyError("report must be a direct child of state-dir")
        if self.report_path.name in {"journal.json", "operation.lock", ".report-owner.json"} or (
            self.report_path.name.startswith("target-") and self.report_path.name.endswith(".lock")
        ):
            raise SafetyError("report name collides with reserved portability state")
        self.journal_path = self.state_dir / "journal.json"
        self.report_owner_path = self.state_dir / ".report-owner.json"
        self.engine_digest = _sha256_file(Path(__file__))
        self._journal_recovered = False
        self.git = git or GitRunner()
        self.platform_probe = platform_probe or (lambda: (platform.system(), platform.machine()))
        self.now = now or (lambda: dt.datetime.now(dt.timezone.utc))

    @staticmethod
    def _bound_path(value: str | os.PathLike[str] | None, label: str) -> Path:
        if value is None:
            raise SafetyError(f"{label} is required")
        original = Path(value).expanduser()
        if not original.is_absolute():
            raise SafetyError(f"{label} must be absolute")
        try:
            info = original.lstat()
            if stat.S_ISLNK(info.st_mode):
                raise SafetyError(f"{label} must not be a symlink")
        except FileNotFoundError:
            pass
        return Path(os.path.realpath(original))

    @staticmethod
    def _is_within(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    @staticmethod
    def _git_metadata_ancestor(path: Path) -> Path | None:
        candidates = (path, *path.parents)
        for candidate in candidates:
            if _lexists(candidate / ".git"):
                return candidate
        return None

    def _assert_root_mutation_boundary(self) -> None:
        active_root = any(
            row["path"] == "." and row["disposition"] in ACTIVE_REPOSITORY_DISPOSITIONS
            for row in self.manifest["repositories"]
        )
        git_owner = self._git_metadata_ancestor(self.root)
        if git_owner is not None and not (git_owner == self.root and active_root):
            raise SafetyError("reconstruction root is inside a pre-existing Git worktree")

    def _ensure_state_dir(self) -> None:
        try:
            info = self.state_dir.lstat()
        except FileNotFoundError:
            try:
                self.state_dir.mkdir(mode=0o700, parents=True)
            except OSError as error:
                raise SafetyError("state-dir parent chain is unavailable") from error
            info = self.state_dir.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise SafetyError("state-dir must be a private, non-symlink directory")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise SafetyError("state-dir must be owned by the current user")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise SafetyError("state-dir permissions must exclude group and other access")

    def _target(self, row: Mapping[str, Any]) -> Path:
        if row["path"] == ".":
            return self.root
        target = self.root.joinpath(*PurePosixPath(row["path"]).parts)
        if not self._is_within(target, self.root):
            raise SafetyError("repository path escapes root")
        return target

    def _check_target_components(self, target: Path, *, allow_missing: bool = True) -> None:
        if target != self.root and not self._is_within(target, self.root):
            raise SafetyError("target escapes root")
        start = self.root
        components: Iterable[Path]
        if target == self.root:
            components = (self.root,)
        else:
            relative = target.relative_to(self.root)
            current = start
            built: list[Path] = [current]
            for part in relative.parts:
                current = current / part
                built.append(current)
            components = built
        for component in components:
            try:
                info = component.lstat()
            except FileNotFoundError:
                if allow_missing:
                    return
                raise SafetyError("target path is missing")
            if stat.S_ISLNK(info.st_mode):
                raise SafetyError("target path contains a symlink")
            if component != target and not stat.S_ISDIR(info.st_mode):
                raise SafetyError("target ancestor is not a directory")

    def _validate_remotes(self, repository: Path, repository_id: str) -> dict[str, str]:
        git_entry = repository / ".git"
        try:
            git_info = git_entry.lstat()
        except FileNotFoundError as error:
            raise SafetyError("repository lacks ordinary Git metadata") from error
        if not stat.S_ISDIR(git_info.st_mode) or stat.S_ISLNK(git_info.st_mode):
            raise SafetyError("repository Git metadata must be a non-symlink directory")
        remotes = self.git.remote_urls(repository)
        if frozenset(remotes) != frozenset({"origin"}):
            raise SafetyError("repository must have exactly one origin remote before content inspection")
        observed = remote_identity(remotes["origin"])
        if observed is None or observed.casefold() != repository_id.casefold():
            raise SafetyError("repository origin is not the expected sanitized KleinPerkins remote")
        return remotes

    def _validate_safe_local_config(self, repository: Path) -> None:
        config = self.git.local_config(repository)
        fixed_allowed = {
            "core.repositoryformatversion",
            "core.filemode",
            "core.bare",
            "core.logallrefupdates",
            "core.ignorecase",
            "core.precomposeunicode",
            "remote.origin.url",
            "remote.origin.fetch",
            "user.name",
            "user.email",
        }
        for key in config:
            if key in fixed_allowed:
                continue
            if re.fullmatch(r"branch\.[A-Za-z0-9._/-]+\.(remote|merge)", key):
                continue
            raise SafetyError("repository local Git config contains executable or unsupported routing")
        if config.get("remote.origin.fetch") != "+refs/heads/*:refs/remotes/origin/*":
            raise SafetyError("repository origin fetch routing is not the expected personal mapping")

    def _validate_local_identity(self, repository: Path) -> None:
        if self.git.local_identity(repository) != (PERSONAL_NAME, PERSONAL_EMAIL):
            raise SafetyError("repository local Git identity is not the required personal identity")

    def _inspect_repository(
        self,
        row: Mapping[str, Any],
        *,
        include_ignored: bool = False,
        main_revision: str | None = None,
    ) -> dict[str, Any]:
        target = self._target(row)
        self._check_target_components(target)
        try:
            info = target.lstat()
        except FileNotFoundError:
            return {"state": "absent", "source_ready": False}
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            return {"state": "conflict", "source_ready": False, "detail": "target is not a regular directory"}
        try:
            self._validate_remotes(target, row["id"])
            self._validate_safe_local_config(target)
            self._validate_local_identity(target)
            head = self.git.head(target)
            if head != row["revision"]:
                return {"state": "conflict", "source_ready": False, "detail": "HEAD differs from the manifest revision"}
            if main_revision is not None:
                self.git.verify_main_ancestry(target, row["revision"], main_revision)
            status = self.git.status(target, include_ignored=include_ignored)
            if status:
                return {
                    "state": "conflict",
                    "source_ready": False,
                    "detail": "repository has dirty, untracked, or ignored content" if include_ignored else "repository has dirty or untracked content",
                }
            return {"state": "verified", "source_ready": True, "head": head}
        except PortabilityError as error:
            return {"state": "conflict", "source_ready": False, "detail": str(error)}

    def _postimage(self, repository: Path, row: Mapping[str, Any], main_revision: str) -> dict[str, Any]:
        self._validate_remotes(repository, row["id"])
        self._validate_safe_local_config(repository)
        self._validate_local_identity(repository)
        head = self.git.head(repository)
        if head != row["revision"]:
            raise SafetyError("cloned HEAD differs from the manifest revision")
        self.git.verify_main_ancestry(repository, row["revision"], main_revision)
        if self.git.status(repository):
            raise SafetyError("new clone is not clean")
        config = repository / ".git" / "config"
        if not config.is_file() or config.is_symlink():
            raise SafetyError("new clone does not have an ordinary private Git config")
        repository_info = repository.lstat()
        return {
            "head": head,
            "refs": self.git.refs(repository),
            "remotes": self.git.remote_urls(repository),
            "config_sha256": _sha256_file(config),
            "device": repository_info.st_dev,
            "inode": repository_info.st_ino,
            "qualified_main": main_revision,
            "git_inventory": _git_inventory(repository),
        }

    def _postimage_matches(self, repository: Path, row: Mapping[str, Any], postimage: Mapping[str, Any], *, strict_files: bool) -> tuple[bool, str | None]:
        try:
            repository_info = repository.lstat()
            if (
                not stat.S_ISDIR(repository_info.st_mode)
                or stat.S_ISLNK(repository_info.st_mode)
                or repository_info.st_dev != postimage.get("device")
                or repository_info.st_ino != postimage.get("inode")
            ):
                return False, "repository directory changed after installation"
            if _git_inventory(repository) != postimage.get("git_inventory"):
                return False, "Git metadata changed after installation"
            self._validate_remotes(repository, row["id"])
            self._validate_safe_local_config(repository)
            self._validate_local_identity(repository)
            if self.git.head(repository) != postimage.get("head") or postimage.get("head") != row["revision"]:
                return False, "HEAD changed after installation"
            qualified_main = postimage.get("qualified_main")
            if type(qualified_main) is not str or not HEX_REVISION.fullmatch(qualified_main):
                return False, "default-main provenance is missing from the postimage"
            self.git.verify_main_ancestry(repository, row["revision"], qualified_main)
            if self.git.refs(repository) != postimage.get("refs"):
                return False, "Git references changed after installation"
            if self.git.remote_urls(repository) != postimage.get("remotes"):
                return False, "Git remotes changed after installation"
            config = repository / ".git" / "config"
            if not config.is_file() or config.is_symlink() or _sha256_file(config) != postimage.get("config_sha256"):
                return False, "Git config changed after installation"
            if self.git.status(repository, include_ignored=strict_files):
                return False, "repository content changed after installation"
        except PortabilityError as error:
            return False, str(error)
        return True, None

    def _base_report(self, command: str) -> dict[str, Any]:
        return {
            "schema": REPORT_SCHEMA,
            "command": command,
            "observed_at": self.now().isoformat(),
            "manifest_digest": self.loaded.digest,
            "manifest": copy.deepcopy(self.manifest),
            "root": os.fspath(self.root),
            "source_ready": False,
            "operational_complete": False,
            "result": "incomplete",
            "repositories": [],
            "capabilities": [],
            "local_state": [],
            "required_blockers": [],
            "errors": [],
        }

    def _static_rows(self, report: dict[str, Any]) -> None:
        for row in self.manifest["capabilities"]:
            source_ready = row["disposition"] == "source-only"
            operational = False
            entry = {
                **copy.deepcopy(row),
                "status": row["disposition"].replace("-", "_"),
                "source_ready": source_ready,
                "operational_complete": operational,
            }
            report["capabilities"].append(entry)
            if row["required"] and not operational:
                report["required_blockers"].append(
                    {"kind": "capability", "id": row["id"], "reason": row["reason"], "axis": "operational"}
                )
        for row in self.manifest["local_state"]:
            entry = {
                **copy.deepcopy(row),
                "status": row["disposition"].replace("-", "_"),
                "source_ready": row["disposition"] == "recreate",
                "operational_complete": False,
            }
            report["local_state"].append(entry)
            if row["required"]:
                report["required_blockers"].append(
                    {"kind": "local_state", "id": row["id"], "reason": row["reason"], "axis": "operational"}
                )

    def _finalize_report(self, report: dict[str, Any]) -> dict[str, Any]:
        required_sources_ready = True
        operational = True
        for group in (report["repositories"], report["capabilities"], report["local_state"]):
            for row in group:
                if row["required"]:
                    required_sources_ready = required_sources_ready and bool(row["source_ready"])
                    operational = operational and bool(row["operational_complete"])
        report["source_ready"] = required_sources_ready
        report["operational_complete"] = required_sources_ready and operational and not report["errors"]
        if report["errors"]:
            report["result"] = "refused"
        elif report["required_blockers"]:
            report["result"] = "incomplete"
        else:
            report["result"] = "complete"
        return report

    def _repository_entry(self, row: Mapping[str, Any], assessment: Mapping[str, Any]) -> dict[str, Any]:
        source_ready = bool(assessment.get("source_ready", False))
        operational = source_ready and row["disposition"] == "clone"
        return {
            **copy.deepcopy(dict(row)),
            "status": assessment["state"],
            "source_ready": source_ready,
            "operational_complete": operational,
            **({"detail": assessment["detail"]} if assessment.get("detail") else {}),
        }

    def _blocked_repository_entry(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            **copy.deepcopy(dict(row)),
            "status": row["disposition"].replace("-", "_"),
            "source_ready": False,
            "operational_complete": False,
        }

    def _assess(self, command: str, *, probe: bool) -> dict[str, Any]:
        report = self._base_report(command)
        os_name, architecture = self.platform_probe()
        if (os_name, architecture) != ("Darwin", "arm64"):
            report["errors"].append("host platform must be Darwin arm64")
        try:
            self.git.check_available()
        except PortabilityError as error:
            report["errors"].append(str(error))
        for row in self.manifest["repositories"]:
            if row["disposition"] not in ACTIVE_REPOSITORY_DISPOSITIONS:
                entry = self._blocked_repository_entry(row)
            else:
                access_error: str | None = None
                main_revision: str | None = None
                if probe and not report["errors"]:
                    try:
                        main_revision = self.git.probe(canonical_remote(row["id"]))
                    except PortabilityError as error:
                        access_error = str(error)
                assessment = self._inspect_repository(row, main_revision=main_revision)
                if access_error:
                    assessment = {"state": "blocked_access", "source_ready": False, "detail": access_error}
                entry = self._repository_entry(row, assessment)
            report["repositories"].append(entry)
            if row["required"] and not entry["operational_complete"]:
                report["required_blockers"].append(
                    {"kind": "repository", "id": row["id"], "reason": entry.get("detail", row["reason"]), "axis": "operational"}
                )
        self._static_rows(report)
        return self._finalize_report(report)

    def _write_report(self, report: Mapping[str, Any], *, required: bool) -> None:
        if not required and not self.explicit_report:
            return
        self._ensure_state_dir()
        content = _json_bytes(report)
        owner = {
            "schema": "personal-portability/report-owner/v1",
            "engine_digest": self.engine_digest,
            "manifest_digest": self.loaded.digest,
            "root": os.fspath(self.root),
            "report": os.fspath(self.report_path),
            "report_sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "state": "complete",
        }
        if not _lexists(self.report_owner_path):
            if _lexists(self.report_path):
                raise SafetyError("refusing to adopt a pre-existing unowned report")
            pending = {**owner, "state": "pending"}
            _atomic_write(self.report_owner_path, _json_bytes(pending), 0o600, replace=False)
            _atomic_write(self.report_path, content, 0o600, replace=False)
            _atomic_write(self.report_owner_path, _json_bytes(owner), 0o600, replace=True)
            return
        _regular_private_file(self.report_owner_path)
        try:
            previous = json.loads(self.report_owner_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SafetyError("report ownership record is unreadable") from error
        expected_keys = frozenset(owner)
        if (
            type(previous) is not dict
            or frozenset(previous) != expected_keys
            or previous["schema"] != owner["schema"]
            or previous["engine_digest"] != self.engine_digest
            or previous["manifest_digest"] != self.loaded.digest
            or previous["root"] != os.fspath(self.root)
            or previous["report"] != os.fspath(self.report_path)
            or previous["state"] not in {"pending", "complete"}
        ):
            raise SafetyError("report ownership or preimage binding changed")
        if previous["state"] == "pending" and not _lexists(self.report_path):
            _atomic_write(self.report_path, content, 0o600, replace=False)
            _atomic_write(self.report_owner_path, _json_bytes(owner), 0o600, replace=True)
            return
        _regular_private_file(self.report_path)
        if previous["report_sha256"] != _sha256_file(self.report_path):
            raise SafetyError("report ownership or preimage binding changed")
        if previous["state"] == "pending":
            previous["state"] = "complete"
            _atomic_write(self.report_owner_path, _json_bytes(previous), 0o600, replace=True)
        _atomic_write(self.report_path, content, 0o600, replace=True)
        _atomic_write(self.report_owner_path, _json_bytes(owner), 0o600, replace=True)

    def preflight(self) -> dict[str, Any]:
        report = self._assess("preflight", probe=True)
        self._write_report(report, required=False)
        return report

    def plan(self) -> dict[str, Any]:
        report = self._assess("plan", probe=True)
        for entry in report["repositories"]:
            if entry["disposition"] in ACTIVE_REPOSITORY_DISPOSITIONS and entry["status"] == "absent":
                entry["status"] = "planned_clone"
        self._write_report(report, required=False)
        return report

    def _root_observation(self) -> dict[str, Any]:
        try:
            info = self.root.lstat()
        except FileNotFoundError:
            return {"state": "absent", "device": None, "inode": None}
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise SafetyError("root binding requires an absent or ordinary directory")
        return {"state": "directory", "device": info.st_dev, "inode": info.st_ino}

    def _new_journal(self) -> dict[str, Any]:
        root_observation = self._root_observation()
        return {
            "schema": JOURNAL_SCHEMA,
            "operation_id": str(uuid.uuid4()),
            "engine_digest": self.engine_digest,
            "manifest_digest": self.loaded.digest,
            "root": os.fspath(self.root),
            "root_binding": {"preimage": root_observation, "current": root_observation},
            "actions": {
                row["id"]: {
                    "id": row["id"],
                    "path": row["path"],
                    "revision": row["revision"],
                    "status": "pending",
                    "created": False,
                    "staging": None,
                    "postimage": None,
                    "detail": None,
                }
                for row in self.manifest["repositories"]
                if row["disposition"] in ACTIVE_REPOSITORY_DISPOSITIONS
            },
            "owned_directories": [],
        }

    def _validate_journal(self, journal: Any) -> dict[str, Any]:
        journal_keys = frozenset(
            {
                "schema",
                "operation_id",
                "engine_digest",
                "manifest_digest",
                "root",
                "root_binding",
                "actions",
                "owned_directories",
            }
        )
        if type(journal) is not dict or frozenset(journal) != journal_keys or journal.get("schema") != JOURNAL_SCHEMA:
            raise SafetyError("journal has an unsupported schema")
        if (
            journal.get("engine_digest") != self.engine_digest
            or journal.get("manifest_digest") != self.loaded.digest
            or journal.get("root") != os.fspath(self.root)
        ):
            raise SafetyError("journal is bound to different engine, manifest, or root bytes")
        try:
            if str(uuid.UUID(journal["operation_id"])) != journal["operation_id"]:
                raise ValueError
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise SafetyError("journal operation id is invalid") from error
        root_binding = journal.get("root_binding")
        if type(root_binding) is not dict or frozenset(root_binding) != frozenset({"preimage", "current"}):
            raise SafetyError("journal root binding is invalid")
        for name in ("preimage", "current"):
            observation = root_binding[name]
            if (
                type(observation) is not dict
                or frozenset(observation) != frozenset({"state", "device", "inode"})
                or type(observation["state"]) is not str
                or observation["state"] not in {"absent", "directory"}
                or observation["state"] == "absent"
                and (observation["device"] is not None or observation["inode"] is not None)
                or observation["state"] == "directory"
                and (type(observation["device"]) is not int or type(observation["inode"]) is not int)
            ):
                raise SafetyError("journal root observation is invalid")
        if type(journal.get("actions")) is not dict or type(journal.get("owned_directories")) is not list:
            raise SafetyError("journal structure is invalid")
        observed_root = self._root_observation()
        if root_binding["current"] != observed_root:
            recoverable_absent_root = (
                root_binding["preimage"]["state"] == "absent"
                and root_binding["current"]["state"] == "absent"
                and observed_root["state"] == "directory"
                and not any(self.root.iterdir())
            )
            if not recoverable_absent_root:
                raise SafetyError("root directory binding changed since the journal was written")
            root_binding["current"] = observed_root
            journal["owned_directories"].append(
                {
                    "path": os.fspath(self.root),
                    "device": observed_root["device"],
                    "inode": observed_root["inode"],
                }
            )
            self._journal_recovered = True
        expected = {
            row["id"]
            for row in self.manifest["repositories"]
            if row["disposition"] in ACTIVE_REPOSITORY_DISPOSITIONS
        }
        if set(journal["actions"]) != expected:
            raise SafetyError("journal action set differs from the manifest")
        rows_by_id = {
            row["id"]: row
            for row in self.manifest["repositories"]
            if row["disposition"] in ACTIVE_REPOSITORY_DISPOSITIONS
        }
        action_keys = frozenset(
            {"id", "path", "revision", "status", "created", "staging", "postimage", "detail"}
        )
        statuses = frozenset(
            {"pending", "staging", "ready_to_install", "installed", "preexisting", "conflict", "failed", "rolled_back"}
        )
        postimage_keys = frozenset(
            {"head", "refs", "remotes", "config_sha256", "device", "inode", "qualified_main", "git_inventory"}
        )
        for repository_id, action in journal["actions"].items():
            row = rows_by_id[repository_id]
            if (
                type(action) is not dict
                or frozenset(action) != action_keys
                or action["id"] != repository_id
                or action["path"] != row["path"]
                or action["revision"] != row["revision"]
                or type(action["status"]) is not str
                or action["status"] not in statuses
                or type(action["created"]) is not bool
                or (action["created"] and action["status"] not in {"installed", "rolled_back"})
                or (action["status"] in {"installed", "rolled_back"} and not action["created"])
                or (action["detail"] is not None and type(action["detail"]) is not str)
            ):
                raise SafetyError("journal action record is invalid")
            staging = action["staging"]
            if action["status"] in {"staging", "ready_to_install"} and staging is None:
                raise SafetyError("journal action is missing its required staging binding")
            if action["status"] in {"pending", "preexisting", "conflict", "rolled_back"} and staging is not None:
                raise SafetyError("journal action has an unexpected staging binding")
            if staging is not None:
                if type(staging) is not dict or frozenset(staging) != frozenset(
                    {"container", "nonce", "device", "inode"}
                ):
                    raise SafetyError("journal staging record is invalid")
                target = self._target(row)
                try:
                    container = Path(staging["container"])
                except TypeError as error:
                    raise SafetyError("journal staging path is invalid") from error
                if (
                    container.parent != target.parent
                    or not container.name.startswith(".portability-stage-")
                    or type(staging["nonce"]) is not str
                    or not re.fullmatch(r"[0-9a-f]{32}", staging["nonce"])
                    or not (
                        staging["device"] is None
                        and staging["inode"] is None
                        or type(staging["device"]) is int
                        and type(staging["inode"]) is int
                        and staging["device"] >= 0
                        and staging["inode"] > 0
                    )
                ):
                    raise SafetyError("journal staging record escapes its action target")
            postimage = action["postimage"]
            if action["status"] in {"ready_to_install", "installed"} and postimage is None:
                raise SafetyError("journal action is missing its required postimage")
            if action["status"] in {"pending", "staging", "preexisting", "conflict", "rolled_back"} and postimage is not None:
                raise SafetyError("journal action has an unexpected postimage")
            if postimage is not None:
                inventory = postimage.get("git_inventory") if type(postimage) is dict else None
                if (
                    type(postimage) is not dict
                    or frozenset(postimage) != postimage_keys
                    or postimage["head"] != row["revision"]
                    or type(postimage["refs"]) is not dict
                    or not all(
                        type(name) is str and type(revision) is str and HEX_REVISION.fullmatch(revision)
                        for name, revision in postimage["refs"].items()
                    )
                    or type(postimage["remotes"]) is not dict
                    or not all(type(name) is str and type(url) is str for name, url in postimage["remotes"].items())
                    or type(postimage["config_sha256"]) is not str
                    or not re.fullmatch(r"sha256:[0-9a-f]{64}", postimage["config_sha256"])
                    or type(postimage["device"]) is not int
                    or type(postimage["inode"]) is not int
                    or type(postimage["qualified_main"]) is not str
                    or not HEX_REVISION.fullmatch(postimage["qualified_main"])
                    or type(inventory) is not dict
                    or frozenset(inventory) != frozenset({"sha256", "entries", "bytes"})
                    or type(inventory["sha256"]) is not str
                    or not re.fullmatch(r"sha256:[0-9a-f]{64}", inventory["sha256"])
                    or type(inventory["entries"]) is not int
                    or type(inventory["bytes"]) is not int
                ):
                    raise SafetyError("journal postimage record is invalid")
        allowed_owned_directories = {self.root}
        for row in self.manifest["repositories"]:
            if row["disposition"] not in ACTIVE_REPOSITORY_DISPOSITIONS:
                continue
            target = self._target(row)
            parent = target.parent
            while parent != self.root.parent:
                allowed_owned_directories.add(parent)
                if parent == self.root:
                    break
                parent = parent.parent
        seen_owned_directories: set[Path] = set()
        for record in journal["owned_directories"]:
            if type(record) is not dict or frozenset(record) != frozenset({"path", "device", "inode"}):
                raise SafetyError("journal owned-directory record is invalid")
            try:
                directory = Path(record["path"])
            except TypeError as error:
                raise SafetyError("journal owned-directory path is invalid") from error
            if (
                not directory.is_absolute()
                or directory not in allowed_owned_directories
                or directory in seen_owned_directories
                or type(record["device"]) is not int
                or type(record["inode"]) is not int
                or record["device"] < 0
                or record["inode"] <= 0
            ):
                raise SafetyError("journal owned-directory record escapes its permitted target parents")
            if _lexists(directory):
                info = directory.lstat()
                if (
                    not stat.S_ISDIR(info.st_mode)
                    or stat.S_ISLNK(info.st_mode)
                    or info.st_dev != record["device"]
                    or info.st_ino != record["inode"]
                ):
                    raise SafetyError("journal owned-directory binding changed")
            seen_owned_directories.add(directory)
        return journal

    def _load_or_create_journal(self) -> dict[str, Any]:
        if _lexists(self.journal_path):
            _regular_private_file(self.journal_path)
            try:
                journal = json.loads(self.journal_path.read_text(encoding="utf-8"), object_pairs_hook=_pairs_without_duplicates)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, _DuplicateKey) as error:
                raise SafetyError("journal is unreadable") from error
            try:
                validated = self._validate_journal(journal)
            except SafetyError:
                raise
            except (TypeError, KeyError, ValueError, AttributeError) as error:
                raise SafetyError("journal contains a malformed primitive value") from error
            if self._journal_recovered:
                self._save_journal(validated)
                self._journal_recovered = False
            return validated
        journal = self._new_journal()
        self._save_journal(journal)
        return journal

    def _save_journal(self, journal: Mapping[str, Any]) -> None:
        replace = _lexists(self.journal_path)
        _atomic_write(self.journal_path, _json_bytes(journal), 0o600, replace=replace)

    def _record_owned_directory(self, journal: dict[str, Any], directory: Path) -> None:
        info = directory.lstat()
        journal["owned_directories"].append(
            {"path": os.fspath(directory), "device": info.st_dev, "inode": info.st_ino}
        )
        if directory == self.root:
            journal["root_binding"]["current"] = self._root_observation()
        self._save_journal(journal)

    def _ensure_target_parent(self, target: Path, journal: dict[str, Any]) -> None:
        self._assert_root_mutation_boundary()
        if target == self.root:
            parent = self.root.parent
            if not parent.is_dir() or parent.is_symlink():
                raise SafetyError("root parent must be an existing non-symlink directory")
            return
        if not self.root.exists():
            self.root.mkdir(mode=0o700)
            self._record_owned_directory(journal, self.root)
        elif self.root.is_symlink() or not self.root.is_dir():
            raise SafetyError("root container is not a regular directory")
        current = self.root
        relative_parent = target.parent.relative_to(self.root)
        for part in relative_parent.parts:
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                current.mkdir(mode=0o700)
                self._record_owned_directory(journal, current)
                continue
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise SafetyError("target parent contains a symlink or non-directory")

    def _target_lock(self, target: Path) -> FileLock:
        digest = hashlib.sha256(os.fsencode(target)).hexdigest()
        return FileLock(self.state_dir / f"target-{digest}.lock")

    def _marker_payload(self, journal: Mapping[str, Any], row: Mapping[str, Any], target: Path, nonce: str) -> dict[str, Any]:
        return {
            "schema": "personal-portability/staging-owner/v1",
            "operation_id": journal["operation_id"],
            "manifest_digest": self.loaded.digest,
            "repository_id": row["id"],
            "target": os.fspath(target),
            "nonce": nonce,
        }

    def _staging_owned(self, staging: Mapping[str, Any], journal: Mapping[str, Any], row: Mapping[str, Any], target: Path) -> bool:
        try:
            container = Path(staging["container"])
            expected_parent = target.parent
            if container.parent != expected_parent or not container.name.startswith(".portability-stage-"):
                return False
            info = container.lstat()
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                return False
            if staging.get("device") is None and staging.get("inode") is None:
                entries = list(container.iterdir())
                if not entries:
                    return True
                if entries != [container / ".portability-owner.json"]:
                    return False
            elif info.st_dev != staging.get("device") or info.st_ino != staging.get("inode"):
                return False
            marker_path = container / ".portability-owner.json"
            try:
                marker_info = marker_path.lstat()
            except FileNotFoundError:
                return not any(container.iterdir())
            if not stat.S_ISREG(marker_info.st_mode) or stat.S_ISLNK(marker_info.st_mode):
                return False
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            return marker == self._marker_payload(journal, row, target, staging["nonce"])
        except (KeyError, OSError, ValueError, json.JSONDecodeError, TypeError):
            return False

    def _cleanup_staging(self, action: dict[str, Any], journal: dict[str, Any], row: Mapping[str, Any], target: Path) -> None:
        staging = action.get("staging")
        if not staging:
            return
        container = Path(staging["container"])
        if not container.exists():
            action["staging"] = None
            self._save_journal(journal)
            return
        if not self._staging_owned(staging, journal, row, target):
            raise SafetyError("interrupted staging directory ownership cannot be proven")
        shutil.rmtree(container)
        action["staging"] = None
        self._save_journal(journal)

    def _stage_clone(
        self,
        row: Mapping[str, Any],
        action: dict[str, Any],
        journal: dict[str, Any],
        target: Path,
        main_revision: str,
    ) -> None:
        nonce = uuid.uuid4().hex
        container = target.parent / f".portability-stage-{hashlib.sha256(row['id'].encode()).hexdigest()[:12]}-{nonce}"
        action.update(
            {
                "status": "staging",
                "staging": {"container": os.fspath(container), "nonce": nonce, "device": None, "inode": None},
                "detail": None,
            }
        )
        self._save_journal(journal)
        container.mkdir(mode=0o700)
        info = container.lstat()
        action["staging"].update({"device": info.st_dev, "inode": info.st_ino})
        marker = container / ".portability-owner.json"
        _atomic_write(
            marker,
            _json_bytes(self._marker_payload(journal, row, target, nonce)),
            0o600,
            replace=False,
        )
        self._save_journal(journal)

        repository = container / "repository"
        remote = canonical_remote(row["id"])
        self.git.clone(remote, repository)
        self._validate_remotes(repository, row["id"])
        self.git.has_commit(repository, row["revision"])
        self.git.verify_main_ancestry(repository, row["revision"], main_revision)
        self.git.configure_identity(repository)
        self.git.checkout(repository, row["revision"])
        postimage = self._postimage(repository, row, main_revision)
        action.update({"status": "ready_to_install", "postimage": postimage})
        self._save_journal(journal)
        try:
            target.lstat()
        except FileNotFoundError:
            pass
        else:
            raise SafetyError("target appeared before atomic install; it was preserved")
        _rename_noreplace(repository, target)
        if target == self.root:
            journal["root_binding"]["current"] = self._root_observation()
            self._save_journal(journal)
        postimage = self._postimage(target, row, main_revision)
        action["postimage"] = postimage
        matches, detail = self._postimage_matches(target, row, postimage, strict_files=False)
        if not matches:
            raise SafetyError(detail or "installed repository does not match its postimage")
        action.update({"status": "installed", "created": True, "detail": None})
        self._save_journal(journal)
        self._cleanup_staging(action, journal, row, target)

    def _recover_or_apply_row(
        self,
        row: Mapping[str, Any],
        action: dict[str, Any],
        journal: dict[str, Any],
        main_revision: str,
    ) -> dict[str, Any]:
        target = self._target(row)
        with self._target_lock(target):
            status = action["status"]
            if status == "installed":
                matches, detail = self._postimage_matches(target, row, action["postimage"], strict_files=False)
                if matches:
                    self._cleanup_staging(action, journal, row, target)
                    return {"state": "verified", "source_ready": True}
                return {"state": "conflict", "source_ready": False, "detail": detail}
            if status == "preexisting":
                return self._inspect_repository(row, main_revision=main_revision)
            if status in {"staging", "ready_to_install", "failed"}:
                if action.get("postimage") and target.exists():
                    matches, detail = self._postimage_matches(target, row, action["postimage"], strict_files=False)
                    if matches:
                        action.update({"status": "installed", "created": True, "detail": None})
                        self._save_journal(journal)
                        self._cleanup_staging(action, journal, row, target)
                        return {"state": "verified", "source_ready": True}
                    if detail:
                        return {"state": "conflict", "source_ready": False, "detail": detail}
                self._cleanup_staging(action, journal, row, target)
                action.update({"status": "pending", "postimage": None, "detail": None})
                self._save_journal(journal)

            assessment = self._inspect_repository(row, main_revision=main_revision)
            if assessment["state"] == "verified":
                action.update({"status": "preexisting", "created": False, "detail": None})
                self._save_journal(journal)
                return assessment
            if assessment["state"] != "absent":
                action.update({"status": "conflict", "detail": assessment.get("detail")})
                self._save_journal(journal)
                return assessment
            self._ensure_target_parent(target, journal)
            try:
                self._stage_clone(row, action, journal, target, main_revision)
            except PortabilityError as error:
                action.update({"status": "failed", "detail": str(error)})
                self._save_journal(journal)
                return {"state": "failed", "source_ready": False, "detail": str(error)}
            return {"state": "verified", "source_ready": True}

    def apply(self, command: str = "apply") -> dict[str, Any]:
        self._ensure_state_dir()
        with FileLock(self.state_dir / "operation.lock"):
            report = self._base_report(command)
            os_name, architecture = self.platform_probe()
            prerequisites_ok = (os_name, architecture) == ("Darwin", "arm64")
            if not prerequisites_ok:
                report["errors"].append("host platform must be Darwin arm64")
            try:
                self.git.check_available()
            except PortabilityError as error:
                prerequisites_ok = False
                report["errors"].append(str(error))
            access: dict[str, tuple[str | None, str | None]] = {}
            if prerequisites_ok:
                for row in self.manifest["repositories"]:
                    if row["disposition"] not in ACTIVE_REPOSITORY_DISPOSITIONS:
                        continue
                    try:
                        access[row["id"]] = (self.git.probe(canonical_remote(row["id"])), None)
                    except PortabilityError as error:
                        access[row["id"]] = (None, str(error))
            journal = self._load_or_create_journal()
            rows = sorted(
                self.manifest["repositories"],
                key=lambda row: (row["path"] != ".", len(PurePosixPath(row["path"]).parts), row["path"]),
            )
            for row in rows:
                if row["disposition"] not in ACTIVE_REPOSITORY_DISPOSITIONS:
                    entry = self._blocked_repository_entry(row)
                elif not prerequisites_ok:
                    entry = self._repository_entry(
                        row, {"state": "blocked_prerequisite", "source_ready": False, "detail": "host prerequisites failed"}
                    )
                else:
                    main_revision, access_error = access[row["id"]]
                    if access_error is not None or main_revision is None:
                        assessment = {"state": "blocked_access", "source_ready": False, "detail": access_error}
                    else:
                        try:
                            assessment = self._recover_or_apply_row(
                                row,
                                journal["actions"][row["id"]],
                                journal,
                                main_revision,
                            )
                        except PortabilityError as error:
                            assessment = {"state": "failed", "source_ready": False, "detail": str(error)}
                    entry = self._repository_entry(row, assessment)
                report["repositories"].append(entry)
                if row["required"] and not entry["operational_complete"]:
                    report["required_blockers"].append(
                        {"kind": "repository", "id": row["id"], "reason": entry.get("detail", row["reason"]), "axis": "operational"}
                    )
            self._static_rows(report)
            self._finalize_report(report)
            self._write_report(report, required=True)
            return report

    def resume(self) -> dict[str, Any]:
        return self.apply("resume")

    def verify(self) -> dict[str, Any]:
        report = self._assess("verify", probe=False)
        if _lexists(self.journal_path):
            try:
                journal = self._load_or_create_journal()
            except PortabilityError as error:
                report["errors"].append(str(error))
            else:
                by_id = {row["id"]: row for row in self.manifest["repositories"]}
                entries = {entry["id"]: entry for entry in report["repositories"]}
                for repository_id, action in journal["actions"].items():
                    if action["status"] == "installed" and action.get("postimage"):
                        target = self._target(by_id[repository_id])
                        matches, detail = self._postimage_matches(
                            target, by_id[repository_id], action["postimage"], strict_files=False
                        )
                        entries[repository_id]["postimage_intact"] = matches
                        if detail:
                            entries[repository_id]["postimage_detail"] = detail
                            entries[repository_id]["source_ready"] = False
                            entries[repository_id]["operational_complete"] = False
                            report["errors"].append(f"{repository_id}: installed postimage is not intact")
                            if entries[repository_id]["required"]:
                                report["required_blockers"].append(
                                    {
                                        "kind": "repository",
                                        "id": repository_id,
                                        "reason": detail,
                                        "axis": "operational",
                                    }
                                )
        self._finalize_report(report)
        self._write_report(report, required=self.state_dir.exists())
        return report

    def _rollback_action(
        self,
        row: Mapping[str, Any],
        action: dict[str, Any],
        journal: dict[str, Any],
    ) -> tuple[str, str | None, bool]:
        target = self._target(row)
        with self._target_lock(target):
            self._cleanup_staging(action, journal, row, target)
            if action["status"] == "preexisting" and not action["created"]:
                assessment = self._inspect_repository(row)
                if assessment["state"] == "verified":
                    return "preserved_preexisting", None, True
                return "preserved_preexisting_changed", assessment.get("detail"), False
            if action["status"] == "rolled_back":
                return "already_rolled_back", None, False
            if not action["created"]:
                if not _lexists(target):
                    return "not_created", None, False
                return "preserved_unowned_target", "unowned target was preserved", False
            if row["path"] == ".":
                return "blocked_root", "rollback never removes root '.'", False
            if action["status"] != "installed" or not action.get("postimage"):
                return "blocked_unproven", "created target lacks an exact installed postimage", False
            if not _lexists(target):
                action.update({"status": "rolled_back", "detail": None, "postimage": None})
                self._save_journal(journal)
                return "already_removed_after_interruption", None, False
            matches, detail = self._postimage_matches(target, row, action["postimage"], strict_files=True)
            if not matches:
                return "blocked_changed", detail, False
            self._check_target_components(target, allow_missing=False)
            try:
                shutil.rmtree(target)
            except OSError as error:
                raise SafetyError("owned repository removal failed") from error
            action.update({"status": "rolled_back", "detail": None, "postimage": None})
            self._save_journal(journal)
            return "removed_owned_clone", None, False

    def _rollback_owned_directories(self, journal: dict[str, Any]) -> list[str]:
        blocked: list[str] = []
        for record in reversed(journal["owned_directories"]):
            directory = Path(record["path"])
            if directory == self.root:
                continue
            try:
                info = directory.lstat()
            except FileNotFoundError:
                continue
            if (
                stat.S_ISDIR(info.st_mode)
                and not stat.S_ISLNK(info.st_mode)
                and info.st_dev == record["device"]
                and info.st_ino == record["inode"]
            ):
                try:
                    directory.rmdir()
                except OSError:
                    blocked.append(os.fspath(directory))
            else:
                blocked.append(os.fspath(directory))
        return blocked

    def rollback(self) -> dict[str, Any]:
        self._ensure_state_dir()
        with FileLock(self.state_dir / "operation.lock"):
            report = self._base_report("rollback")
            if not _lexists(self.journal_path):
                report["errors"].append("rollback requires a bound journal")
                self._static_rows(report)
                self._finalize_report(report)
                self._write_report(report, required=True)
                return report
            try:
                journal = self._load_or_create_journal()
            except PortabilityError as error:
                report["errors"].append(str(error))
                self._static_rows(report)
                self._finalize_report(report)
                self._write_report(report, required=True)
                return report
            row_by_id = {row["id"]: row for row in self.manifest["repositories"]}
            for row in self.manifest["repositories"]:
                if row["disposition"] not in ACTIVE_REPOSITORY_DISPOSITIONS:
                    entry = self._blocked_repository_entry(row)
                else:
                    status, detail, source_ready = self._rollback_action(
                        row, journal["actions"][row["id"]], journal
                    )
                    entry = {
                        **copy.deepcopy(row),
                        "status": status,
                        "source_ready": source_ready,
                        "operational_complete": source_ready and row["disposition"] == "clone",
                    }
                    if detail:
                        entry["detail"] = detail
                        report["errors"].append(f"{row['id']}: {detail}")
                report["repositories"].append(entry)
                if row["required"] and not entry["operational_complete"]:
                    report["required_blockers"].append(
                        {"kind": "repository", "id": row["id"], "reason": entry.get("detail", row["reason"]), "axis": "operational"}
                    )
            blocked_directories = self._rollback_owned_directories(journal)
            if blocked_directories:
                report["errors"].append("owned parent directories are no longer empty and were preserved")
            self._static_rows(report)
            self._finalize_report(report)
            self._write_report(report, required=True)
            return report

    def run(self, command: str) -> dict[str, Any]:
        operations = {
            "preflight": self.preflight,
            "plan": self.plan,
            "apply": self.apply,
            "verify": self.verify,
            "resume": self.resume,
            "rollback": self.rollback,
        }
        try:
            operation = operations[command]
        except KeyError as error:
            raise SafetyError("unsupported command") from error
        return operation()


def _exit_code(report: Mapping[str, Any]) -> int:
    if report.get("errors"):
        return 3
    if report.get("required_blockers"):
        return 4
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "plan", "apply", "verify", "resume", "rollback"))
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        engine = Engine(arguments.manifest, arguments.root, arguments.state_dir, arguments.report)
        report = engine.run(arguments.command)
    except PortabilityError as error:
        print(json.dumps({"result": "refused", "error": str(error)}, sort_keys=True))
        return 2
    except OSError:
        print(json.dumps({"result": "refused", "error": "filesystem operation failed safely"}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "result": report["result"],
                "source_ready": report["source_ready"],
                "operational_complete": report["operational_complete"],
                "required_blockers": len(report["required_blockers"]),
                "errors": len(report["errors"]),
            },
            sort_keys=True,
        )
    )
    return _exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
