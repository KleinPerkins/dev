#!/usr/bin/env python3
"""Build a curated, deterministic personal entry kit from merged Git objects.

The work-oriented dev tree and its Git history are deliberately not in the kit.
No host config, credentials, repository payloads, or local work are exported.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile


PREFIX = "_ops/portability/"
PAYLOAD = (
    "engine.py", "manifest.json", "START-HERE.md", "DESTINATION-PROMPT.txt",
    "MANUAL-ACTIONS.md", "README.md",
)
SCHEMA = "personal-portability/package/v1"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
CANONICAL_REMOTE = "git@github.com:KleinPerkins/dev.git"


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unique_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest key")
        result[key] = value
    return result


def git(root: Path, *args: str) -> bytes:
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_") and key not in {"SSH_ASKPASS", "SSH_ASKPASS_REQUIRE"}}
    environment.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
                        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_NO_REPLACE_OBJECTS": "1",
                        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=yes"})
    result = subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.hooksPath=" + os.devnull,
         "-c", "core.fsmonitor=false", "-c", "init.templateDir=", "-C", str(root), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, env=environment,
    )
    if result.returncode:
        raise ValueError("Git source/provenance check failed; no package written")
    return result.stdout


def collect(root: Path, revision: str) -> dict[str, bytes]:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("a full lowercase source commit is required")
    allowed = {"git@github.com:KleinPerkins/dev.git", "https://github.com/KleinPerkins/dev.git"}
    origin = git(root, "config", "--local", "--no-includes", "--get", "remote.origin.url").decode().strip()
    if origin not in allowed:
        raise ValueError("source repository identity is not KleinPerkins/dev")
    # Local grafts, replacement refs, alternates and URL rewrites are not provenance.
    # Fetch in a private fresh object database, never the caller's mutable graph.
    with tempfile.TemporaryDirectory(prefix="personal-package-source-") as directory:
        clean = Path(directory).resolve()
        git(clean, "init", "--bare")
        git(clean, "fetch", "--no-tags", "--no-recurse-submodules", CANONICAL_REMOTE,
            "refs/heads/main:refs/heads/source-main")
        git(clean, "merge-base", "--is-ancestor", revision, "refs/heads/source-main")
        result = {}
        total = 0
        for name in PAYLOAD:
            path = PREFIX + name
            row = git(clean, "ls-tree", revision, "--", path).decode().strip()
            if not row.startswith(("100644 blob ", "100755 blob ")):
                raise ValueError("package source must be a regular tracked blob")
            size = int(git(clean, "cat-file", "-s", revision + ":" + path))
            total += size
            if size > MAX_FILE_BYTES or total > MAX_PAYLOAD_BYTES:
                raise ValueError("curated payload exceeds its size bound")
            result[name] = git(clean, "show", revision + ":" + path)
        return result


def build(files: dict[str, bytes], revision: str, destination: Path) -> dict:
    if set(files) != set(PAYLOAD) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("closed package payload or source revision invalid")
    if any(type(data) is not bytes or len(data) > MAX_FILE_BYTES for data in files.values()) or sum(map(len, files.values())) > MAX_PAYLOAD_BYTES:
        raise ValueError("curated payload exceeds its size bound")
    if destination.exists() or destination.is_symlink():
        raise ValueError("output already exists; preserve it and choose a new path")
    for parent in [destination.parent, *destination.parent.parents]:
        if parent.is_symlink():
            raise ValueError("symlinked output parent refused")
    manifest = json.loads(files["manifest.json"], object_pairs_hook=unique_pairs)
    # Validate using this trusted builder checkout's validator, never execute downloaded payload.
    spec = importlib.util.spec_from_file_location("personal_package_validator", Path(__file__).with_name("engine.py"))
    validator = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = validator
    spec.loader.exec_module(validator)
    try:
        validator.validate_manifest(manifest)
    except validator.PortabilityError as exc:
        raise ValueError("manifest validation failed") from exc
    # The full mixed dev repository must not be cloned by this curated entry kit.
    dev = [r for r in manifest.get("repositories", []) if r.get("id") == "KleinPerkins/dev"]
    if len(dev) != 1 or dev[0].get("disposition") != "blocked-review":
        raise ValueError("mixed dev source must retain its review boundary")
    by_id = {row["id"]: row for row in manifest["repositories"]}
    for repository, disposition in (("KleinPerkins/dev", "blocked-review"),
                                    ("KleinPerkins/chaos-labs", "blocked-review"),
                                    ("KleinPerkins/chaos-scheduler", "blocked-protected")):
        row = by_id.get(repository)
        if not row or row["disposition"] != disposition or row["required"] is not True:
            raise ValueError("required mixed/protected source boundary changed")
    if by_id["KleinPerkins/chaos-scheduler"]["revision"] is not None:
        raise ValueError("protected source must not acquire a revision pin")
    for repository in ("KleinPerkins/ecosystem-orchestrator", "KleinPerkins/cpp", "KleinPerkins/ai-analytics-context"):
        row = by_id.get(repository)
        if not row or row["disposition"] != "excluded-work" or row["required"] is not False:
            raise ValueError("known work source exclusion changed")
    manifest["repositories"] = [
        {**r, "revision": revision} if r.get("id") == "KleinPerkins/dev" else r
        for r in manifest["repositories"]
    ]
    output = dict(files)
    output["manifest.json"] = canonical(manifest)
    # Resolve the only generation token from the immutable source revision.
    for name in ("START-HERE.md", "DESTINATION-PROMPT.txt"):
        if output[name].count(b"@@SOURCE_REVISION@@") != 1:
            raise ValueError("source revision token must occur exactly once in each instruction file")
        output[name] = output[name].replace(b"@@SOURCE_REVISION@@", revision.encode())
        if re.search(rb"@@[^\s@]+@@", output[name]):
            raise ValueError("unresolved instruction generation token")
    hashes = {name: sha(content) for name, content in sorted(output.items())}
    provenance = {
        "schema": SCHEMA, "repository": "KleinPerkins/dev", "source_revision": revision,
        "source_paths": {name: PREFIX + name for name in PAYLOAD},
        "source_blob_sha256": {name: sha(content) for name, content in sorted(files.items())},
        "transformations": [
            {"file": "manifest.json", "operation": "canonical-json-and-set-dev-revision", "revision": revision},
            {"file": "START-HERE.md", "operation": "replace-source-revision-token-once", "revision": revision},
            {"file": "DESTINATION-PROMPT.txt", "operation": "replace-source-revision-token-once", "revision": revision},
        ],
        "payload_sha256": hashes, "includes_git_history": False,
        "includes_host_state": False, "operational_complete": False,
        "limitations": ["Required owner and local-state blockers remain in manifest.",
                        "Actual destination qualification has not occurred."],
    }
    output["PROVENANCE.json"] = canonical(provenance)
    output["SHA256SUMS"] = "".join(
        f"{sha(content)}  {name}\n" for name, content in sorted(output.items())
    ).encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".personal-package-", dir=destination.parent)
    try:
        os.close(fd)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, content in sorted(output.items()):
                item = zipfile.ZipInfo("personal-bootstrap/" + name, (2020, 1, 1, 0, 0, 0))
                item.compress_type = zipfile.ZIP_STORED
                item.external_attr = 0o100600 << 16
                archive.writestr(item, content)
        # Hard-link creation is exclusive; no race can overwrite a new user file.
        os.link(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"path": str(destination), "sha256": sha(destination.read_bytes()),
            "source_revision": revision, "files": sorted(output),
            "operational_complete": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build(collect(args.source_root, args.revision), args.revision, args.output.absolute())
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, UnicodeError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc) if isinstance(exc, ValueError)
                          else "source or output operation failed"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
