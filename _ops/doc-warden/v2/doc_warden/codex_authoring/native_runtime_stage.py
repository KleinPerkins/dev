"""Stage the lockfile-pinned GSD runtime without touching client discovery."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess

from ..canonical import contained_path, digest_ref, parse_json_object
from ..gsd_plan_check import GSD_REVISION, _verified_package_files


LOCK_DIGEST = "sha256:8a451d875ddd9156254cf592fc6a1df9be353d99450648292dd062cf6544b7bf"
PACKAGE_PATH = "node_modules/@opengsd/gsd-core/package.json"


@dataclass(frozen=True)
class StagedRuntime:
    package: Path
    installed_files: dict[str, str]
    lock_digest: str
    source_revision: str


def stage_runtime(
    *, source: Path, staging: Path, node: Path, npm: Path,
    tool_digests: dict[str, str],
) -> StagedRuntime:
    """Build into a private empty operation directory for later admission."""
    source, staging = source.resolve(strict=True), staging.resolve(strict=True)
    if not staging.is_dir() or any(staging.iterdir()):
        raise ValueError("native_runtime_stage_invalid")
    if staging.stat().st_mode & 0o077:
        raise ValueError("native_runtime_stage_not_private")
    lock = contained_path(source, "package-lock.json").read_bytes()
    package_meta = contained_path(source, "package.json").read_bytes()
    if digest_ref(lock) != LOCK_DIGEST:
        raise ValueError("native_runtime_lock_changed")
    if parse_json_object(package_meta).get("dependencies") != {"@opengsd/gsd-core": "1.11.0"}:
        raise ValueError("native_runtime_package_changed")
    node, npm = node.resolve(strict=True), npm.resolve(strict=True)
    before = {name: digest_ref(path.read_bytes()) for name, path in (("node", node), ("npm", npm))}
    if before != tool_digests:
        raise ValueError("native_runtime_toolchain_changed")
    (staging / "package.json").write_bytes(package_meta)
    (staging / "package-lock.json").write_bytes(lock)
    user_config = staging / "user.npmrc"
    global_config = staging / "global.npmrc"
    for config in (user_config, global_config):
        config.touch(mode=0o600, exist_ok=False)
    shell = {
        "HOME": str(staging),
        "PATH": os.pathsep.join((str(node.parent), os.defpath)),
        "TMPDIR": str(staging),
        "npm_config_registry": "https://registry.npmjs.org/",
        "npm_config_userconfig": str(user_config),
        "npm_config_globalconfig": str(global_config),
        "npm_config_cache": str(staging / "npm-cache"),
        "npm_config_update_notifier": "false",
    }
    finished = subprocess.run(
        [str(node), str(npm), "ci", "--ignore-scripts", "--omit=dev", "--no-audit", "--no-fund"],
        cwd=staging, env=shell, capture_output=True, timeout=180, check=False,
    )
    if finished.returncode != 0:
        raise ValueError("native_runtime_stage_failed")
    metadata = contained_path(staging, PACKAGE_PATH)
    value = parse_json_object(metadata.read_bytes())
    if value.get("name") != "@opengsd/gsd-core" or value.get("version") != "1.11.0":
        raise ValueError("native_runtime_package_changed")
    if (digest_ref((staging / "package-lock.json").read_bytes()) != LOCK_DIGEST
            or (staging / "package.json").read_bytes() != package_meta
            or before != {name: digest_ref(path.read_bytes()) for name, path in (("node", node), ("npm", npm))}):
        raise ValueError("native_runtime_install_inputs_changed")
    return StagedRuntime(metadata.parent, _verified_package_files(metadata.parent), LOCK_DIGEST, GSD_REVISION)
