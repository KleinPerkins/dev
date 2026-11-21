"""Destination-bound evidence for the current Dev runtime installer."""

from __future__ import annotations

import platform
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .canonical import atomic_write, canonical_json, contained_path, digest_ref, parse_json_object
from .gsd_adapter import CENTRAL_REPOSITORY_ID, CENTRAL_REPOSITORY_KEY
from .operation_store import private_state_root
from .scm import observe_repository_identity
from .validators import read_repository_config


QUALIFICATION = "doc-warden/gsd-host-qualification/v1"
RUNTIME = "_ops/doc-warden/runtime/gsd-core"
VERIFIER = "tests/verify-binding.sh"


def _toolchain() -> dict:
    executables = {}
    for name in ("node", "npm", "python3", "bash"):
        selected = shutil.which(name)
        if selected is None:
            raise ValueError("runtime_toolchain_unavailable")
        path = Path(selected).resolve(strict=True)
        before = digest_ref(path.read_bytes())
        version = subprocess.check_output([str(path), "--version"], stderr=subprocess.DEVNULL,
                                          text=True, timeout=10).splitlines()[0].strip()
        if Path(selected).resolve(strict=True) != path or digest_ref(path.read_bytes()) != before:
            raise ValueError("runtime_toolchain_changed")
        executables[name] = {"path": str(path), "digest": before, "version": version}
    return {"executables": executables, "platform": platform.system(), "machine": platform.machine()}


def installation_context(repo: Path, home: Path, data_home: Path) -> dict:
    profile = read_repository_config(repo)
    identity = observe_repository_identity(repo)
    if (profile is None or not profile["enabled"]
            or profile["repository_key"] != CENTRAL_REPOSITORY_KEY
            or profile["github_repository_id"] != CENTRAL_REPOSITORY_ID
            or identity.github_repository_id != CENTRAL_REPOSITORY_ID
            or identity.repository.casefold() != "kleinperkins/dev"):
        raise ValueError("runtime_install_repository_identity_mismatch")
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    return {
        "repository_key": CENTRAL_REPOSITORY_KEY, "github_repository_id": CENTRAL_REPOSITORY_ID,
        "source_revision": revision, "canonical_root": str(repo), "home": str(home), "data_home": str(data_home),
        "host_digest": digest_ref(socket.gethostname().encode()), "toolchain": _toolchain(),
    }


def _qualification_path(context: dict) -> Path:
    root = private_state_root()
    filename = "gsd-host-" + digest_ref(canonical_json(context))[7:] + ".json"
    return contained_path(root, f"runtime/{filename}")


def _runtime_source(repo: Path) -> dict[str, str]:
    from .live_install import QUALIFICATION_DIGEST_PATHS

    return {name: digest_ref(contained_path(repo, f"{RUNTIME}/{path}").read_bytes())
            for name, path in QUALIFICATION_DIGEST_PATHS.items()}


def qualify_destination(repo: Path, *, home: Path, data_home: Path) -> dict:
    from .live_install import QUALIFICATION_DIGEST_PATHS

    repo, home, data_home = (path.expanduser().resolve() for path in (repo, home, data_home))
    context = installation_context(repo, home, data_home)
    before = _runtime_source(repo)
    verifier = contained_path(repo, f"{RUNTIME}/{VERIFIER}")
    verifier_digest = digest_ref(verifier.read_bytes())
    source = {path: before[name] for name, path in QUALIFICATION_DIGEST_PATHS.items()} | {VERIFIER: verifier_digest}
    for relative, digest in source.items():
        content = subprocess.check_output(
            ["git", "-C", str(repo), "show", f"{context['source_revision']}:{RUNTIME}/{relative}"],
            stderr=subprocess.DEVNULL, timeout=15,
        )
        if digest_ref(content) != digest:
            raise ValueError("runtime_qualification_source_drift")
    completed = subprocess.run(["bash", str(verifier)], cwd=repo, capture_output=True, timeout=240, check=False)
    if completed.returncode != 0:
        raise ValueError("runtime_destination_qualification_failed")
    if (before != _runtime_source(repo) or verifier_digest != digest_ref(verifier.read_bytes())
            or context != installation_context(repo, home, data_home)):
        raise ValueError("runtime_qualification_source_drift")
    record = {
        "schema": QUALIFICATION, "context": context, "runtime_digests": before,
        "verifier_digest": verifier_digest, "transcript_digest": digest_ref(completed.stdout),
        "qualified_at": datetime.now(timezone.utc).isoformat(), "outcome": "passed",
    }
    destination = _qualification_path(context)
    raw = canonical_json(record)
    atomic_write(destination.parent.parent, destination.relative_to(destination.parent.parent).as_posix(), raw)
    if destination.read_bytes() != raw:
        raise ValueError("runtime_qualification_readback_failed")
    return {"schema": QUALIFICATION, "status": "qualified", "source_revision": context["source_revision"],
            "qualification_digest": digest_ref(raw)}


def read_destination_qualification(repo: Path, *, home: Path, data_home: Path) -> tuple[dict, str, dict, Path]:
    context = installation_context(repo, home, data_home)
    path = _qualification_path(context)
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("runtime_destination_qualification_required")
    content = path.read_bytes()
    value = parse_json_object(content)
    observed = _runtime_source(repo)
    if (set(value) != {"schema", "context", "runtime_digests", "verifier_digest", "transcript_digest",
                      "qualified_at", "outcome"}
            or content != canonical_json(value) or value["schema"] != QUALIFICATION
            or value["context"] != context or value["outcome"] != "passed"
            or value["runtime_digests"] != observed
            or value["verifier_digest"] != digest_ref(contained_path(repo, f"{RUNTIME}/{VERIFIER}").read_bytes())):
        raise ValueError("runtime_destination_qualification_changed")
    return context, digest_ref(content), observed, path
