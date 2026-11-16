#!/usr/bin/env python3
"""Validate the exact AWA release binding consumed by the ~/dev host overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any


PIN = "cfe9437739d2928014c2156532d1986a8511fd30"
VERSION = "1.8.2"
POLICY_MODULE_SHA256 = "e149896d854254550765aa1f42e78a83bf17b7a2f49f24bacf96425ebc6c0219"
SOURCE = "github.com/KleinPerkins/awa"
HOOK_OWNER_V2_SHA256 = (
    "0c2753a3ced8be7d47b3a6613db0ba59dd55830cb6efa2fa801a0aeb0c0cd22b"
)
SCHEDULE_SHA256 = (
    "d6cdfef9b1e240290cbea678d49795fcdced80d9f0099627f579bdf5a98804a6"
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "_ops" / "tests" / "fixtures" / "awa-v1.8.1"
HOOK_OWNER_V2_FIXTURE = FIXTURE_DIR / "awa-hook-owner.v2.json"
SCHEDULE_FIXTURE = FIXTURE_DIR / "awa-integrity-schedule.v1.json"


class BindingError(ValueError):
    """One release-binding invariant failed."""


def _path_from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default.resolve()


def _path_from_envs(names: tuple[str, ...], default: Path) -> Path:
    for name in names:
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser().resolve()
    return default.resolve()


def _read_bytes(path: Path, *, maximum: int = 1_000_000) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise BindingError(f"required file is unavailable: {path}") from exc
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise BindingError(f"required path is not a regular file: {path}")
    if info.st_size > maximum:
        raise BindingError(f"required file exceeds size bound: {path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise BindingError(f"required file cannot be read: {path}") from exc


def _read_json(path: Path) -> dict[str, Any]:
    raw = _read_bytes(path)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BindingError(f"required JSON is malformed: {path}") from exc
    if type(value) is not dict:
        raise BindingError(f"required JSON root is not an object: {path}")
    return value


def _digest(path: Path) -> str:
    return hashlib.sha256(_read_bytes(path)).hexdigest()


def _flat_meta(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in _read_bytes(path).decode("utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _validate_static(*, require_gcb: bool = False) -> None:
    if _digest(HOOK_OWNER_V2_FIXTURE) != HOOK_OWNER_V2_SHA256:
        raise BindingError("source hook-owner v2 fixture digest drifted")
    if _digest(SCHEDULE_FIXTURE) != SCHEDULE_SHA256:
        raise BindingError("source integrity schedule fixture digest drifted")

    hook_owner = _read_json(HOOK_OWNER_V2_FIXTURE)
    expected_roles = {
        "worktree.shell-guard-composite": (
            "beforeShellExecution",
            "kernel/hooks/worktree-guard-with-integrity.sh",
        ),
        "worktree.stop-observer": (
            "stop",
            "kernel/hooks/awa-integrity-observer.sh",
        ),
        "worktree.session-handoff": (
            "sessionStart",
            "kernel/hooks/awa-session-handoff.sh",
        ),
    }
    if (
        hook_owner.get("schema") != "awa-hook-owner/v2"
        or hook_owner.get("version") != 2
        or hook_owner.get("successor_of") != "awa-hook-owner/v1"
        or hook_owner.get("supersedes_roles") != ["worktree.shell-guard"]
        or hook_owner.get("external_real_hook_file_writes") is not False
        or type(hook_owner.get("roles")) is not list
    ):
        raise BindingError("source hook-owner v2 fixture shape drifted")
    observed_roles = {
        role.get("id"): (role.get("event"), role.get("direct_command_role"))
        for role in hook_owner["roles"]
        if type(role) is dict
    }
    if observed_roles != expected_roles:
        raise BindingError("source hook-owner v2 role matrix drifted")

    schedule = _read_json(SCHEDULE_FIXTURE)
    if schedule != {
        "schema": "awa-integrity-schedule/v1",
        "label": "com.kleinperkins.awa-integrity",
        "interval_seconds": 21600,
        "minimum_interval_seconds": 3600,
        "maximum_interval_seconds": 43200,
        "profile": "deep",
        "trigger": "launchd",
        "executable": "kernel/bin/awa-integrity-sweep.sh",
        "host_owner": "local-jobs",
        "ships_plist": False,
        "exit_codes_verbatim": True,
    }:
        raise BindingError("source integrity schedule fixture shape drifted")

    shelf = _path_from_env(
        "DEV_AWA_GCB_DIR",
        ROOT / "capabilities" / "skills" / "global" / "tools" / "awa",
    )
    if not (shelf / "meta.yml").is_file() or not (shelf / "install.sh").is_file():
        if require_gcb:
            raise BindingError("AWA global-capability binding shelf is unavailable")
        return
    meta = _flat_meta(shelf / "meta.yml")
    meta_mismatch = (
        meta.get("schema") != "kp-capability/v1"
        or meta.get("id") != "awa"
        or meta.get("kind") != "tool"
        or meta.get("flavor") != "2"
        or meta.get("scope") != "global"
        or meta.get("provenance_source") != SOURCE
        or meta.get("provenance_ref") != PIN
    )
    if meta_mismatch and require_gcb:
        raise BindingError("AWA global-capability binding descriptor is not the exact pin")
    if meta_mismatch:
        return
    installer = shelf / "install.sh"
    if not installer.is_file() or not os.access(installer, os.X_OK):
        raise BindingError("AWA global-capability binding installer is unavailable")


def _validate_runtime() -> tuple[dict[str, Any], dict[str, Any]]:
    _validate_static(require_gcb=True)
    home = Path(os.environ.get("HOME", "~")).expanduser().resolve()
    data_home = _path_from_env("XDG_DATA_HOME", home / ".local" / "share")
    config_home = _path_from_env("XDG_CONFIG_HOME", home / ".config")
    runtime = _path_from_env("AWA_HOME", data_home / "awa" / "current")
    release_pointer_path = _path_from_envs(
        ("DEV_AWA_RELEASE_POINTER", "AWA_RELEASE_POINTER"),
        data_home / "awa" / "release-pointer.json",
    )
    gcb_pointer_path = _path_from_envs(
        ("DEV_AWA_GCB_POINTER", "AWA_GCB_POINTER"),
        data_home / "awa" / "gcb-pointer.json",
    )
    owner_selection_path = _path_from_envs(
        ("DEV_AWA_OWNER_SELECTION", "AWA_HOOK_OWNER_SELECTION"),
        config_home / "awa" / "hook-owner.json",
    )
    shelf = _path_from_env(
        "DEV_AWA_GCB_DIR",
        ROOT / "capabilities" / "skills" / "global" / "tools" / "awa",
    )

    gcb = _read_json(gcb_pointer_path)
    if set(gcb) != {
        "schema",
        "id",
        "kind",
        "source",
        "ref",
        "clone_url",
        "checkout",
        "shelf",
        "release_pointer",
    }:
        raise BindingError("AWA GCB pointer is not a closed v1 document")
    if (
        gcb.get("schema") != "awa-gcb-pointer/v1"
        or gcb.get("id") != "awa"
        or gcb.get("kind") != "global-capability-binding"
        or gcb.get("source") != SOURCE
        or gcb.get("ref") != PIN
    ):
        raise BindingError("AWA GCB pointer release identity is mismatched")
    if gcb.get("shelf") != str(shelf):
        raise BindingError("AWA GCB pointer shelf is stale")
    if gcb.get("release_pointer") != str(release_pointer_path):
        raise BindingError("AWA GCB pointer release-pointer path is stale")
    if (
        type(gcb.get("checkout")) is not str
        or not Path(gcb["checkout"]).is_absolute()
    ):
        raise BindingError("AWA GCB checkout path is malformed")

    pointer = _read_json(release_pointer_path)
    required_pointer = {
        "schema",
        "version",
        "source",
        "commit",
        "runtime",
        "policy",
        "hook_owner_contract",
        "hook_owner_mode",
        "hook_owner_contract_sha256",
        "installed_at",
    }
    if not required_pointer.issubset(pointer):
        raise BindingError("AWA release pointer is incomplete")
    if (
        pointer.get("schema") != "awa-release-pointer/v1"
        or pointer.get("version") != VERSION
        or pointer.get("source") != gcb["checkout"]
        or pointer.get("commit") != PIN
        or pointer.get("runtime") != str(runtime)
        or pointer.get("policy")
        != str(runtime / "kernel" / "policy" / "default-worktree-policy.yml")
        or pointer.get("hook_owner_contract") != "awa-hook-owner/v1"
        or pointer.get("hook_owner_mode") != "external"
        or type(pointer.get("installed_at")) is not str
        or re.fullmatch(r"[0-9a-f]{40}", str(pointer.get("commit"))) is None
    ):
        raise BindingError("AWA release pointer identity is stale or mismatched")

    owner = _read_json(owner_selection_path)
    if owner != {
        "schema": "awa-hook-owner-selection/v1",
        "contract": "awa-hook-owner/v1",
        "mode": "external",
    }:
        raise BindingError("AWA hook-owner selection is not closed external mode")

    v1_contract_path = runtime / "contracts" / "awa-contract.v1.json"
    v1_contract = _read_json(v1_contract_path)
    hook_ownership = v1_contract.get("hook_ownership")
    if (
        type(hook_ownership) is not dict
        or hook_ownership.get("schema") != "awa-hook-owner/v1"
        or hook_ownership.get("external_real_hook_file_writes") is not False
        or type(hook_ownership.get("roles")) is not list
        or _digest(v1_contract_path)
        != pointer.get("hook_owner_contract_sha256")
    ):
        raise BindingError("installed AWA hook-owner v1 contract is mismatched")

    installed_contracts = {
        runtime / "contracts" / "awa-hook-owner.v2.json": HOOK_OWNER_V2_FIXTURE,
        runtime / "contracts" / "awa-integrity-schedule.v1.json": SCHEDULE_FIXTURE,
    }
    for installed, fixture in installed_contracts.items():
        if _read_bytes(installed) != _read_bytes(fixture):
            raise BindingError(f"installed AWA contract bytes are mismatched: {installed.name}")

    required_executables = (
        "kernel/bin/dev-worktree.sh",
        "kernel/bin/awa-integrity-sweep.sh",
        "kernel/hooks/worktree-session.sh",
        "kernel/hooks/worktree-guard.sh",
        "kernel/hooks/worktree-guard-with-integrity.sh",
        "kernel/hooks/awa-integrity-observer.sh",
        "kernel/hooks/awa-session-handoff.sh",
        "kernel/hooks/awa-recovery-maintenance.sh",
        "kernel/hooks/before-submit-prompt.sh",
    )
    for relative in required_executables:
        path = runtime / relative
        if not path.is_file() or not os.access(path, os.X_OK):
            raise BindingError(f"installed AWA executable is unavailable: {relative}")
    return pointer, gcb


def _validate_source_checkout(pointer: dict[str, Any], gcb: dict[str, Any]) -> Path:
    """Bind development evidence to the same release, without sibling discovery."""
    source = Path(pointer["source"])
    if not source.is_absolute() or not source.is_dir():
        raise BindingError("release-bound AWA source is unavailable")
    source = source.resolve()
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_")}

    def git(*arguments: str) -> str:
        try:
            return subprocess.run(
                ["git", "-C", str(source), *arguments], env=environment,
                capture_output=True, text=True, check=True, timeout=30,
            ).stdout.rstrip("\n")
        except (OSError, subprocess.SubprocessError) as exc:
            raise BindingError("release-bound AWA source verification failed") from exc

    if (git("rev-parse", "--show-toplevel") != str(source)
            or git("rev-parse", "HEAD") != pointer["commit"]
            or git("remote", "get-url", "--all", "origin") != gcb["clone_url"]
            or git("status", "--porcelain=v1", "--untracked-files=all")):
        raise BindingError("release-bound AWA source identity or cleanliness differs")
    if any(not entry.startswith("H ") for entry in git("ls-files", "-v", "-z").split("\0")
           if entry):
        raise BindingError("release-bound AWA source index hides worktree changes")
    for relative in ("engine/tests", "hook-probe/RESULTS-2026-07-05.md",
                     "hook-probe/RESULTS-CLOUD-2026-07-05.md"):
        path = source / relative
        if path.is_symlink() or (not path.is_dir() if relative == "engine/tests"
                                else not path.is_file()):
            raise BindingError("release-bound AWA source evidence is unavailable")
        git("cat-file", "-e", f"{pointer['commit']}:{relative}")
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--static", action="store_true")
    modes.add_argument("--runtime", action="store_true")
    modes.add_argument("--source-root", action="store_true",
                       help="print the verified full source checkout for installed-release evidence")
    args = parser.parse_args()
    try:
        if args.source_root:
            print(_validate_source_checkout(*_validate_runtime()))
            return 0
        if args.runtime:
            _validate_runtime()
            mode = "runtime"
        else:
            _validate_static(
                require_gcb=os.environ.get("DEV_AWA_REQUIRE_GCB") == "1"
            )
            mode = "static"
    except BindingError as exc:
        print(f"AWA release binding: FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"AWA release binding: PASS ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
