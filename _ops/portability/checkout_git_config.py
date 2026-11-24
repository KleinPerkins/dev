"""Verify the Git configuration layers that participate in checkout authority."""

from dataclasses import dataclass
from hashlib import sha256
import re
import subprocess
import time

from personal_checkout_inventory import Refused


CONFIG_LIMIT = 65536
CONFIG_PROOF_FIELDS = {"git_config_sha256", "worktree_git_config_enabled", "worktree_git_config_sha256"}
SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class GitConfigProof:
    common_sha256: str
    worktree_enabled: bool | None = None
    worktree_sha256: str | None = None

    def fields(self):
        return {
            "git_config_sha256": self.common_sha256,
            "worktree_git_config_enabled": self.worktree_enabled,
            "worktree_git_config_sha256": self.worktree_sha256,
        }

    def matches(self, current):
        if self.worktree_enabled is None:
            return current.common_sha256 == self.common_sha256 and current.worktree_enabled is False
        return self == current


def config_proof(row):
    common = row.get("git_config_sha256")
    if not isinstance(common, str) or not SHA256.fullmatch(common):
        raise Refused("the owner record has invalid shared Git configuration evidence")
    if "worktree_git_config_enabled" not in row and "worktree_git_config_sha256" not in row:
        return GitConfigProof(common)
    enabled = row.get("worktree_git_config_enabled")
    digest = row.get("worktree_git_config_sha256")
    if (type(enabled) is not bool or "worktree_git_config_sha256" not in row
            or (digest is not None and (not enabled or not isinstance(digest, str) or not SHA256.fullmatch(digest)))):
        raise Refused("the owner record has invalid worktree Git configuration evidence")
    return GitConfigProof(common, enabled, digest)


def _git_config(raw, args, expires):
    remaining = expires - time.monotonic()
    if remaining <= 0:
        raise Refused("the owner checkout inspection exceeded its budget")
    try:
        return subprocess.run(
            ["/usr/bin/git", "config", "--no-includes", "--file", "-", *args],
            input=raw, capture_output=True, timeout=remaining, check=False,
            env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                 "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_ALLOW_PROTOCOL": "file", "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise Refused("the declared checkout configuration could not be read safely") from error


def _uses_worktree_config(raw, expires):
    result = _git_config(raw, ["--type=bool", "--get", "extensions.worktreeConfig"], expires)
    if result.returncode == 1 and not result.stdout:
        return False
    if result.returncode == 0 and result.stdout in (b"true\n", b"false\n"):
        return result.stdout == b"true\n"
    raise Refused("the checkout has an invalid worktree configuration setting")


def _checkout_settings(raw, expires):
    result = _git_config(raw, ["--null", "--list"], expires)
    if result.returncode:
        raise Refused("the declared checkout configuration could not be read safely")
    settings = {}
    try:
        for entry in result.stdout.decode("utf-8").split("\x00"):
            if not entry:
                continue
            key, separator, value = entry.partition("\n")
            # Git normalizes section and variable names but preserves the case
            # of subsections, including remote names such as "Origin".
            if key.startswith(("url.", "include.", "includeif.")):
                raise Refused("the checkout has local Git endpoint rewrites or includes")
            if (key == "remote.pushdefault" or (
                    key.startswith("branch.") and key.endswith((".pushremote", ".remote")))):
                if not separator or value != "origin":
                    raise Refused("the checkout's configured default remote differs from origin")
            settings.setdefault(key, []).append(value if separator else None)
    except UnicodeError as error:
        raise Refused("the declared checkout configuration could not be read safely") from error
    return settings


def _common_config(binding, reader):
    return reader.read_file(binding.common_directory + "/config", CONFIG_LIMIT)


def _worktree_proof(common, enabled, worktree):
    return GitConfigProof(sha256(common).hexdigest(), enabled,
                          sha256(worktree).hexdigest() if worktree is not None else None)


def observe_git_config(binding, reader, github_name, expires):
    """Verify local remote selection and origin endpoints for both configuration layers."""
    common = _common_config(binding, reader)
    shared = _checkout_settings(common, expires)
    enabled = _uses_worktree_config(common, expires) if "extensions.worktreeconfig" in shared else False
    worktree = reader.read_worktree_config(CONFIG_LIMIT) if enabled else None
    local = _checkout_settings(worktree, expires) if worktree is not None else {}
    fetch = shared.get("remote.origin.url", [])
    push = shared.get("remote.origin.pushurl", fetch)
    endpoints = {
        (transport + github_name + suffix).casefold()
        for transport in ("https://github.com/", "git@github.com:", "ssh://git@github.com/")
        for suffix in ("", ".git")
    }
    worktree_routes = local.get("remote.origin.url", []) + local.get("remote.origin.pushurl", [])
    if (len(fetch) != 1 or len(push) != 1
            or any(url is None or url.casefold() not in endpoints for url in fetch + push + worktree_routes)):
        raise Refused("the checkout's selected fetch or push endpoint differs from the GitHub record")
    return _worktree_proof(common, enabled, worktree)


def verify_git_config(binding, reader, expected):
    """Confirm the same exact Git configuration before consuming or publishing evidence."""
    if isinstance(expected, str):
        expected = config_proof({"git_config_sha256": expected})
    common = _common_config(binding, reader)
    if sha256(common).hexdigest() == expected.common_sha256:
        enabled = expected.worktree_enabled
        if enabled is None:
            enabled = _uses_worktree_config(common, reader.expires)
        worktree = reader.read_worktree_config(CONFIG_LIMIT) if enabled else None
        if expected.matches(_worktree_proof(common, enabled, worktree)):
            return
    raise Refused("the checkout Git configuration changed after the owner evidence was prepared")
