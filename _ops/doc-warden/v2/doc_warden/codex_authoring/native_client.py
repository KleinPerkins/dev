"""Inspect the named Codex client without starting a model turn."""

from __future__ import annotations

from pathlib import Path
import subprocess
import time

from ..canonical import digest_ref, parse_json_object
from .host_projection import PROJECTION_PATHS, SKILL_PURPOSE
from .native_authoring_transport import NativeAuthoringChannel


CLIENT_BUILD = "0.171.0-alpha.13"
CLIENT_DIGEST = "sha256:3b6d00deea5fabc50ad34be1872b8e4ead1638d23c68fabb7837edc07f0cf1e0"


def client_identity(binary: Path, *, cwd: Path, environment: dict[str, str]) -> dict:
    client = binary.resolve(strict=True)
    if not client.is_file() or digest_ref(client.read_bytes()) != CLIENT_DIGEST:
        raise ValueError("native_authoring_client_unqualified")
    version = subprocess.run(
        [str(client), "--version"], cwd=cwd, env=environment, capture_output=True,
        timeout=10, check=False, text=True,
    )
    if (version.returncode != 0 or version.stdout.strip() != "codex-cli " + CLIENT_BUILD
            or digest_ref(client.read_bytes()) != CLIENT_DIGEST):
        raise ValueError("native_authoring_client_unqualified")
    return {"binary": str(client), "version": CLIENT_BUILD, "binary_digest": CLIENT_DIGEST}


def observe_skills(project: Path, *, client: dict, environment: dict[str, str]) -> dict[str, str]:
    """Read back the four project paths from actual native discovery."""
    deadline = time.monotonic() + 25
    with NativeAuthoringChannel(
        binary=Path(client["binary"]), binary_digest=client["binary_digest"], cwd=project,
        configuration=("-c", "features.plugins=false"), environment=environment,
    ) as channel:
        channel.request("initialize", {
            "clientInfo": {"name": "doc_warden_skill_discovery", "version": "1"},
            "capabilities": {"experimentalApi": True},
        }, deadline)
        channel.notify("initialized", deadline)
        result = channel.request("skills/list", {"cwds": [str(project)], "forceReload": True}, deadline)
    data = result.get("data")
    if not channel.reaped or not isinstance(data, list) or len(data) != 1:
        raise ValueError("native_authoring_discovery_unavailable")
    record = data[0]
    if not isinstance(record, dict) or record.get("cwd") != str(project):
        raise ValueError("native_authoring_discovery_target_changed")
    skills = record.get("skills")
    if not isinstance(skills, list):
        raise ValueError("native_authoring_discovery_unavailable")
    found = {}
    for skill in skills:
        if not isinstance(skill, dict) or skill.get("name") not in SKILL_PURPOSE:
            continue
        name = skill["name"]
        expected = project / f".agents/skills/{name}/SKILL.md"
        if (name in found or skill.get("path") != str(expected)
                or skill.get("enabled") is not True):
            raise ValueError("native_authoring_discovery_foreign")
        found[name] = digest_ref(expected.read_bytes())
    if len(found) != len(PROJECTION_PATHS):
        raise ValueError("native_authoring_discovery_incomplete")
    return found
