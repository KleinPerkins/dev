"""Run the pinned GSD plan-structure utility on isolated draft bytes."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .canonical import canonical_json, contained_path, digest_ref, parse_json_object
from .transactions import ObservedInput, directory_input_digest


GSD_REVISION = "182f60b4c170785d96f1deb87fea8b108e9b985f"
CHECKER_DESCRIPTOR_DIGEST = "sha256:96ed829d2aedd6fb05f2288daae5f3ffc42162c74ad255d1f2a89ce9d9215f62"
# Digest of the canonical relative-path to file-digest map of the integrity-pinned npm tarball.
GSD_PACKAGE_FILES_DIGEST = "sha256:92d6c44c6cec044b8ded9754d4d9ae709ec65d054dfd924b2859153e3f131df7"
TOOLS_ENTRY = "gsd-core/bin/gsd-tools.cjs"


def _verified_package_files(package: Path) -> dict[str, str]:
    files = {}
    for path in package.rglob("*"):
        if path.is_symlink():
            raise ValueError("authoring_checker_pin_mismatch")
        if not path.is_dir():
            if not path.is_file():
                raise ValueError("authoring_checker_pin_mismatch")
            files[path.relative_to(package).as_posix()] = digest_ref(path.read_bytes())
    if (files.get("agents/gsd-plan-checker.md") != CHECKER_DESCRIPTOR_DIGEST
            or digest_ref(canonical_json(files)) != GSD_PACKAGE_FILES_DIGEST):
        raise ValueError("authoring_checker_pin_mismatch")
    return files


def run_plan_structure_checks(plans: dict[str, bytes]) -> tuple[ObservedInput, ...]:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    root = data_home.expanduser().resolve()
    metadata = f"gsd-core/releases/{GSD_REVISION}/node_modules/@opengsd/gsd-core/package.json"
    package = contained_path(root, metadata).parent
    node = shutil.which("node")
    if node is None or not package.is_dir():
        raise ValueError("authoring_checker_unavailable")
    try:
        files = _verified_package_files(package)
        executable = Path(node).resolve(strict=True)
        tool_digest = digest_ref(executable.read_bytes())
        with tempfile.TemporaryDirectory(prefix="doc-warden-plan-check-") as directory:
            work = Path(directory)
            environment = {
                "HOME": directory, "PATH": os.defpath, "TMPDIR": directory,
                "XDG_CONFIG_HOME": str(work / "config"), "XDG_DATA_HOME": str(work / "data"),
                "XDG_STATE_HOME": str(work / "state"), "XDG_CACHE_HOME": str(work / "cache"),
            }
            for relative, content in sorted(plans.items()):
                draft = contained_path(work, relative)
                draft.parent.mkdir(parents=True, exist_ok=True)
                draft.write_bytes(content)
                completed = subprocess.run(
                    [str(executable), str(package / TOOLS_ENTRY), "verify", "plan-structure", relative],
                    cwd=work, env=environment, capture_output=True, timeout=30, check=False,
                )
                if completed.returncode != 0:
                    raise ValueError("authoring_checker_failed")
                try:
                    verdict = parse_json_object(completed.stdout)
                except (UnicodeError, ValueError) as exc:
                    raise ValueError("authoring_checker_failed") from exc
                if verdict.get("valid") is not True or verdict.get("errors") != []:
                    raise ValueError("authoring_checker_failed")
        _verified_package_files(package)
        if Path(node).resolve(strict=True) != executable or digest_ref(executable.read_bytes()) != tool_digest:
            raise ValueError("authoring_checker_pin_mismatch")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("authoring_checker_unavailable") from exc
    directories = {package, *(path for path in package.rglob("*") if path.is_dir())}
    return (
        ObservedInput(str(executable), tool_digest),
        *(ObservedInput(str(path), directory_input_digest(path)) for path in sorted(directories)),
        *(ObservedInput(str(package / name), files[name]) for name in sorted(files)),
    )
