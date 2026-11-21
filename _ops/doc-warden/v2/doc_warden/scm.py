"""Exact local/GitHub repository identity observation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse


@dataclass(frozen=True)
class RepositoryIdentity:
    repository: str
    github_repository_id: int

    def binding(self) -> dict[str, object]:
        return {
            "github_repository": self.repository,
            "github_repository_id": self.github_repository_id,
        }


def _origin_url(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "remote", "get-url", "origin"],
        check=False,
        capture_output=True,
        text=True,
    )
    value = result.stdout
    if value.endswith("\n"):
        value = value[:-1]
    if result.returncode != 0 or not value:
        raise ValueError("github_origin_unavailable")
    return value


def _github_slug(origin_url: str) -> str:
    if any(character.isspace() for character in origin_url):
        raise ValueError("github_origin_unsupported")
    scp = re.fullmatch(r"git@github\.com:(.+)", origin_url)
    if scp is not None:
        value = scp.group(1)
    else:
        parsed = urlparse(origin_url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("github_origin_unsupported") from exc
        if (
            parsed.hostname != "github.com"
            or parsed.scheme not in {"https", "ssh", "git"}
            or port is not None
            or parsed.params
            or parsed.query
            or parsed.fragment
            or (
                parsed.scheme in {"ssh", "git"}
                and parsed.username not in {None, "git"}
            )
        ):
            raise ValueError("github_origin_unsupported")
        value = parsed.path.lstrip("/")
    value = value.removesuffix(".git").rstrip("/")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) is None:
        raise ValueError("github_origin_unsupported")
    return value


def _fixture_github_cli(repo: Path) -> str:
    github_cli = os.environ.get("DOC_WARDEN_GH_BIN", "gh")
    if github_cli == "gh":
        return github_cli
    candidate = Path(github_cli)
    temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
    git_dir_result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--absolute-git-dir"],
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        candidate = candidate.resolve(strict=True)
        repo.relative_to(temporary_root)
        candidate.relative_to(
            Path(git_dir_result.stdout.strip()).resolve(strict=True)
        )
    except (OSError, ValueError):
        raise ValueError("github_repository_identity_unavailable") from None
    if git_dir_result.returncode or not candidate.is_file() or not os.access(
        candidate, os.X_OK
    ):
        raise ValueError("github_repository_identity_unavailable")
    return str(candidate)


def github_bytes(endpoint: str, *, github_cli: str, unavailable: str, parameters: tuple[str, ...] = ()) -> bytes:
    try:
        result = subprocess.run(
            [github_cli, "api", endpoint, *parameters], check=False, capture_output=True, timeout=20,
        )
        if result.returncode != 0 or len(result.stdout) > 2_000_000:
            raise ValueError(unavailable)
        return result.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(unavailable) from exc


def github_json(endpoint: str, *, github_cli: str, unavailable: str, parameters: tuple[str, ...] = ()) -> object:
    try:
        return json.loads(github_bytes(endpoint, github_cli=github_cli, unavailable=unavailable, parameters=parameters))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(unavailable) from exc


def _github_metadata(repository: str, *, github_cli: str = "gh") -> dict[str, object]:
    value = github_json(f"repos/{quote(repository, safe='/')}", github_cli=github_cli,
                        unavailable="github_repository_identity_unavailable")
    if not isinstance(value, dict):
        raise ValueError("github_repository_identity_unavailable")
    return value


def observe_repository_identity(repo: Path) -> RepositoryIdentity:
    root = repo.resolve(strict=True)
    origin_url = _origin_url(root)
    requested = _github_slug(origin_url)
    metadata = _github_metadata(
        requested,
        github_cli=_fixture_github_cli(root),
    )
    repository = metadata.get("full_name")
    github_repository_id = metadata.get("id")
    if (
        not isinstance(repository, str)
        or repository.casefold() != requested.casefold()
        or type(github_repository_id) is not int
        or github_repository_id <= 0
    ):
        raise ValueError("github_repository_identity_mismatch")
    return RepositoryIdentity(
        repository=repository,
        github_repository_id=github_repository_id,
    )
