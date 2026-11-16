#!/usr/bin/env python3
"""Bounded INT-008 isolation for three wrong-host imported utilities.

The transaction adds path-specific ``skills.config`` rows with
``enabled = false`` for exactly three imported ``SKILL.md`` files.  It never
edits or removes those imports, never scans for same-name skills, and never
touches Cursor, plugin, system, project, or other Codex configuration.

Preview stores the exact config preimage only in the caller-selected private
operation directory.  The action digest is not consequence approval.  TOML
parse success and filesystem verification do not establish native discovery,
effective precedence, reload behavior, or independent-writer exclusion.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tomllib
import uuid


ROOT = Path(__file__).resolve().parents[2]
SKILL_NAMES = ("sdk", "update-cli-config", "create-subagent")
# Frozen source preimages from the reviewed 2026-10-28 installed-skill inventory.
EXPECTED_SHA256 = {
    "sdk": "ef1a19b9b99e5200ddeefc105f1c7c7285472e28872fac2c305d27db9cd818e2",
    "update-cli-config": "7ab23cb1feadd3d0aedf5bf06d479f17606a7610de558d89a2de1ece75123874",
    "create-subagent": "8874e78acaa6ae74e4252ba63cb6374eb6bfa47a324ff0542d0e28f9c01fb56a",
}
SCHEMA = "interoperability/imported-skill-isolation-operation/v1"
RECEIPT_SCHEMA = "interoperability/imported-skill-isolation-preview-receipt/v1"
PREIMAGE_NAME = "config.preimage"
BEGIN_MARKER = "# BEGIN KleinPerkins/dev INT-008 imported-utility isolation"
END_MARKER = "# END KleinPerkins/dev INT-008 imported-utility isolation"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def explicit_absolute(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ValueError(f"{label} must be an explicit absolute path")
    return path


def no_symlink_components(path: Path) -> None:
    current = path
    while True:
        try:
            if current.is_symlink():
                raise ValueError(f"symlinked path component refused: {current}")
        except OSError as exc:
            raise ValueError(f"path component unavailable: {current}") from exc
        if current == current.parent:
            return
        current = current.parent


def directory_state(path: Path) -> dict:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"real directory required: {path}")
    return {
        "kind": "directory",
        "mode": stat.S_IMODE(info.st_mode),
        "device": info.st_dev,
        "inode": info.st_ino,
        "uid": info.st_uid,
        "gid": info.st_gid,
    }


def read_regular(path: Path) -> tuple[dict, bytes]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError(f"regular unshared file required: {path}")
        data = stream.read()
        after = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ValueError(f"file changed while reading: {path}")
    return {
        "kind": "file",
        "mode": stat.S_IMODE(info.st_mode),
        "device": info.st_dev,
        "inode": info.st_ino,
        "uid": info.st_uid,
        "gid": info.st_gid,
        "nlink": info.st_nlink,
        "size": len(data),
        "mtime_ns": info.st_mtime_ns,
        "sha256": sha(data),
    }, data


def content_state(data: bytes, mode: int) -> dict:
    return {"kind": "file", "mode": mode, "size": len(data), "sha256": sha(data)}


def current_content(path: Path) -> tuple[dict, bytes, dict]:
    observed, data = read_regular(path)
    return content_state(data, observed["mode"]), data, observed


def selector_path(host_root: Path, name: str) -> Path:
    if name not in SKILL_NAMES:
        raise ValueError("selector escaped the fixed imported-skill allowlist")
    return host_root / ".agents/skills" / name / "SKILL.md"


def source_preimages(host_root: Path) -> tuple[list[dict], list[dict]]:
    no_symlink_components(host_root)
    parents = []
    for role, path in (
        ("host-root", host_root),
        ("codex-config-parent", host_root / ".codex"),
        ("import-root", host_root / ".agents"),
        ("import-skills-root", host_root / ".agents/skills"),
    ):
        no_symlink_components(path)
        parents.append({"role": role, "path": str(path), "state": directory_state(path)})

    sources = []
    for name in SKILL_NAMES:
        directory = host_root / ".agents/skills" / name
        path = selector_path(host_root, name)
        no_symlink_components(path)
        parents.append(
            {
                "role": "import-skill-directory",
                "path": str(directory),
                "state": directory_state(directory),
            }
        )
        observed, _data = read_regular(path)
        expected = EXPECTED_SHA256[name]
        if observed["sha256"] != expected:
            raise ValueError(f"approved inventory hash changed for imported skill: {name}")
        sources.append(
            {
                "name": name,
                "selector": str(path),
                "expected_sha256": expected,
                "state": observed,
            }
        )
    return sources, parents


def normalize_configured_path(raw: str, host_root: Path) -> Path:
    if raw == "~":
        candidate = host_root
    elif raw.startswith("~/"):
        candidate = host_root / raw[2:]
    else:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = host_root / candidate
    return Path(os.path.abspath(candidate))


def same_existing_path(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def config_policy(data: bytes, host_root: Path) -> dict:
    try:
        text = data.decode("utf-8")
        parsed = tomllib.loads(text)
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError("Codex config is malformed; no isolation attempted") from exc

    skills = parsed.get("skills", {})
    if not isinstance(skills, dict):
        raise ValueError("Codex skills config has an unsupported shape")
    configured = skills.get("config", [])
    if not isinstance(configured, list):
        raise ValueError("Codex skills config has an unsupported shape")

    exact = {name: selector_path(host_root, name) for name in SKILL_NAMES}
    protected_ancestors = {
        "import-root": host_root / ".agents",
        "import-skills-root": host_root / ".agents/skills",
        **{f"{name}-directory": path.parent for name, path in exact.items()},
    }
    matched: dict[str, dict] = {}
    for index, row in enumerate(configured):
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("Codex skills config row has an unsupported shape")
        enabled = row.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            raise ValueError("Codex skill enablement override must be boolean")
        lexical = normalize_configured_path(row["path"], host_root)

        for role, ancestor in protected_ancestors.items():
            if lexical == ancestor or same_existing_path(lexical, ancestor):
                raise ValueError(
                    f"ancestor selector conflicts with approved SKILL.md selectors: {role}"
                )
        for name, selector in exact.items():
            if lexical != selector and same_existing_path(lexical, selector):
                raise ValueError(f"same-file alias conflicts with approved selector: {name}")
            if lexical != selector:
                continue
            if name in matched:
                raise ValueError(f"duplicate exact imported-skill selector: {name}")
            extra_fields = sorted(set(row) - {"path", "enabled"})
            if extra_fields:
                raise ValueError(
                    f"exact selector has unsupported override fields and is preserved: {name}"
                )
            if enabled is not False:
                raise ValueError(
                    f"explicit conflicting imported-skill override is preserved: {name}"
                )
            matched[name] = {
                "name": name,
                "selector": str(selector),
                "row_index": index,
                "enabled": False,
                "fields": sorted(row),
            }

    missing = [name for name in SKILL_NAMES if name not in matched]
    begin_count = sum(line.strip() == BEGIN_MARKER for line in text.splitlines())
    end_count = sum(line.strip() == END_MARKER for line in text.splitlines())
    if begin_count or end_count:
        if begin_count != 1 or end_count != 1 or missing:
            raise ValueError("managed isolation marker is partial, duplicated, or inconsistent")
    return {
        "schema": "interoperability/imported-skill-config-policy/v1",
        "existing_disabled": [matched[name] for name in SKILL_NAMES if name in matched],
        "missing": missing,
        "effective_native_discovery": "unqualified",
    }


def newline_for(data: bytes) -> bytes:
    without_crlf = data.replace(b"\r\n", b"")
    if b"\r\n" in data and b"\n" not in without_crlf:
        return b"\r\n"
    return b"\n"


def toml_string(value: str) -> str:
    # JSON basic strings use the escape forms accepted by TOML basic strings.
    return json.dumps(value, ensure_ascii=True)


def rendered_append(data: bytes, host_root: Path, missing: list[str]) -> bytes:
    if not missing:
        return b""
    if any(name not in SKILL_NAMES for name in missing) or len(set(missing)) != len(missing):
        raise ValueError("missing selector set escaped the fixed allowlist")
    if missing != [name for name in SKILL_NAMES if name in set(missing)]:
        raise ValueError("missing selector order changed")
    newline = newline_for(data)
    lines = [BEGIN_MARKER]
    for name in missing:
        lines.extend(
            [
                "[[skills.config]]",
                f"path = {toml_string(str(selector_path(host_root, name)))}",
                "enabled = false",
            ]
        )
    lines.append(END_MARKER)
    separator = b"" if not data or data.endswith(b"\n") else newline
    return separator + newline.join(line.encode("utf-8") for line in lines) + newline


def private_operation_path(raw: Path, host_root: Path) -> Path:
    operation = explicit_absolute(raw, "operation directory")
    if operation.exists():
        raise ValueError("operation directory already exists")
    no_symlink_components(operation)
    resolved = operation.resolve(strict=False)
    for protected in (ROOT.resolve(), host_root.resolve()):
        if resolved == protected or resolved.is_relative_to(protected):
            raise ValueError("private operation storage must be outside source and host roots")
    ancestor = resolved.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    for candidate in (ancestor, *ancestor.parents):
        if candidate.name == ".git" or os.path.lexists(candidate / ".git") or (
            os.path.lexists(candidate / "HEAD")
            and any(
                os.path.lexists(candidate / name) for name in ("objects", "refs", "config")
            )
        ):
            raise ValueError("private operation storage must be outside Git metadata")
    outside = subprocess.run(
        ["git", "-C", str(ancestor), "rev-parse", "--absolute-git-dir"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_DISCOVERY_ACROSS_FILESYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "LANG": "C",
            "LC_ALL": "C",
        },
    )
    expected = "fatal: not a git repository (or any of the parent directories): .git"
    diagnostics = [line for line in outside.stderr.splitlines() if line.strip()]
    known_confstr = all(
        line.startswith("git: warning: confstr() failed with code 5:")
        for line in diagnostics[:-1]
    )
    if not (
        outside.returncode == 128
        and not outside.stdout
        and diagnostics
        and diagnostics[-1] == expected
        and known_confstr
    ):
        raise ValueError("private operation storage could not be proven outside Git")
    return resolved


def implementation_digest() -> str:
    return sha(Path(__file__).read_bytes() + (ROOT / "capabilities/bootstrap.sh").read_bytes())


def write_private(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def remove_private_tree(path: Path) -> None:
    for parent, directories, files in os.walk(path, topdown=True, followlinks=False):
        parent_path = Path(parent)
        parent_path.chmod(0o700)
        for name in directories:
            child = parent_path / name
            if not child.is_symlink():
                child.chmod(0o700)
        for name in files:
            child = parent_path / name
            if not child.is_symlink():
                child.chmod(0o600)
    shutil.rmtree(path)


def validate_host_build(value: str | None) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("preview requires an explicit bounded native host build")
    return value


def preview(args: argparse.Namespace) -> dict:
    host_root = explicit_absolute(args.host_root, "host root")
    operation = private_operation_path(args.operation_dir, host_root)
    host_build = validate_host_build(args.host_build)
    sources, parents = source_preimages(host_root)
    config_path = host_root / ".codex/config.toml"
    no_symlink_components(config_path)
    config_observed, config_data = read_regular(config_path)
    policy = config_policy(config_data, host_root)
    operation_id = str(uuid.uuid4())
    stage_path = config_path.parent / f".int008-imported-skill-{operation_id}.tmp"
    if stage_path.exists() or stage_path.is_symlink():
        raise ValueError("operation staging path already exists")
    append = rendered_append(config_data, host_root, policy["missing"])
    postimage = config_data + append
    post_policy = config_policy(postimage, host_root)
    if post_policy["missing"]:
        raise ValueError("rendered isolation rows did not cover the fixed selectors")

    operation.mkdir(mode=0o700)
    try:
        operation_root = directory_state(operation)
        if operation_root["mode"] != 0o700:
            raise ValueError("private operation root must be mode 0700")
        write_private(operation / PREIMAGE_NAME, config_data)
        before = content_state(config_data, config_observed["mode"])
        after = content_state(postimage, config_observed["mode"])
        plan = {
            "schema": SCHEMA,
            "operation_id": operation_id,
            "operation_dir": str(operation),
            "operation_root": operation_root,
            "host_root": str(host_root),
            "host_build": host_build,
            "config": {
                "path": str(config_path),
                "private_preimage": PREIMAGE_NAME,
                "observed_preimage": config_observed,
                "before": before,
                "after": after,
                "append_sha256": sha(append),
                "append_size": len(append),
                "stage_path": str(stage_path),
            },
            "policy": policy,
            "source_preimages": sources,
            "parent_preimages": parents,
            "actions": (
                [
                    {
                        "operation": "append-disabled-SKILL.md-selectors",
                        "path": str(config_path),
                        "selectors": [
                            str(selector_path(host_root, name)) for name in policy["missing"]
                        ],
                    }
                ]
                if append
                else []
            ),
            "implementation_sha256": implementation_digest(),
            "affected_sessions": (
                "Any Codex session using this explicit host root may require a separately approved "
                "reload before discovery changes; existing contexts may retain prior discovery."
            ),
            "native_effect": "unqualified-until-separate-discovery-canary",
            "writer_exclusion": (
                "Preimage rechecks and an advisory file lock serialize this executor only; they do "
                "not exclude non-cooperating writers."
            ),
            "rollback": (
                "Restore the exact private config preimage only while live bytes and mode match the "
                "bound postimage; refuse later edits."
            ),
            "cleanup": (
                "After verified rollback, remove only this exact private operation directory in a "
                "separately reviewed cleanup step; this executor has no delete operation."
            ),
            "production_rollout": False,
            "source_ownership_adopted": False,
        }
        action_sha256 = sha(canonical(plan))
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "operation_id": operation_id,
            "action_sha256": action_sha256,
            "config_preimage_sha256": before["sha256"],
            "config_postimage_sha256": after["sha256"],
            "source_preimages_sha256": sha(canonical(sources)),
            "parent_preimages_sha256": sha(canonical(parents)),
            "policy_sha256": sha(canonical(policy)),
            "implementation_sha256": plan["implementation_sha256"],
        }
        record = {
            **plan,
            "action_sha256": action_sha256,
            "receipt_sha256": sha(canonical(receipt)),
        }
        write_private(operation / "operation.json", canonical(record) + b"\n")
        write_private(operation / "preview-receipt.json", canonical(receipt) + b"\n")
        return {
            "status": "previewed",
            "operation_id": operation_id,
            "operation_dir": str(operation),
            "action_sha256": action_sha256,
            "changed": bool(append),
            "selectors_to_add": policy["missing"],
            "already_disabled": [row["name"] for row in policy["existing_disabled"]],
            "actions": plan["actions"],
            "config": {
                "path": str(config_path),
                "mode": before["mode"],
                "before_sha256": before["sha256"],
                "after_sha256": after["sha256"],
                "append_sha256": plan["config"]["append_sha256"],
                "append_size": plan["config"]["append_size"],
            },
            "source_preimages": [
                {"selector": row["selector"], "sha256": row["expected_sha256"]}
                for row in sources
            ],
            "native_effect": plan["native_effect"],
            "affected_sessions": plan["affected_sessions"],
            "writer_exclusion": plan["writer_exclusion"],
            "rollback": plan["rollback"],
            "cleanup": plan["cleanup"],
            "production_rollout": False,
        }
    except Exception:
        try:
            remove_private_tree(operation)
        except OSError:
            pass
        raise


def load_operation(operation_raw: Path, host_root_raw: Path) -> tuple[dict, dict, bytes, bytes]:
    operation = explicit_absolute(operation_raw, "operation directory")
    host_root = explicit_absolute(host_root_raw, "host root")
    no_symlink_components(operation)
    root_state = directory_state(operation)
    if root_state["mode"] != 0o700:
        raise ValueError("private operation root must be mode 0700")
    documents = {}
    for name in ("operation.json", "preview-receipt.json"):
        observed, data = read_regular(operation / name)
        if observed["mode"] != 0o600:
            raise ValueError("private operation record must be mode 0600")
        documents[name] = json.loads(data)
    preimage_observed, preimage = read_regular(operation / PREIMAGE_NAME)
    if preimage_observed["mode"] != 0o600:
        raise ValueError("private config preimage must be mode 0600")

    record = documents["operation.json"]
    receipt = documents["preview-receipt.json"]
    if not isinstance(record, dict) or not isinstance(receipt, dict):
        raise ValueError("operation records must be JSON objects")
    action_sha256 = record.get("action_sha256")
    receipt_sha256 = record.get("receipt_sha256")
    plan = {
        key: value
        for key, value in record.items()
        if key not in {"action_sha256", "receipt_sha256"}
    }
    if sha(canonical(plan)) != action_sha256:
        raise ValueError("operation action changed")
    if sha(canonical(receipt)) != receipt_sha256:
        raise ValueError("preview receipt changed")
    if plan.get("schema") != SCHEMA or receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError("unknown operation schema")
    if plan.get("operation_dir") != str(operation) or plan.get("host_root") != str(host_root):
        raise ValueError("operation identity, host root, or location changed")
    if plan.get("operation_root") != root_state:
        raise ValueError("private operation root identity changed")
    if str(uuid.UUID(plan["operation_id"])) != plan["operation_id"]:
        raise ValueError("operation identity changed")
    validate_host_build(plan.get("host_build"))

    config_path = host_root / ".codex/config.toml"
    expected_sources = [str(selector_path(host_root, name)) for name in SKILL_NAMES]
    sources = plan.get("source_preimages", [])
    if [row.get("name") for row in sources] != list(SKILL_NAMES) or [
        row.get("selector") for row in sources
    ] != expected_sources:
        raise ValueError("operation escaped the fixed selector allowlist")
    if any(row.get("expected_sha256") != EXPECTED_SHA256[row["name"]] for row in sources):
        raise ValueError("approved selector hashes changed")
    if any(row.get("state", {}).get("sha256") != row.get("expected_sha256") for row in sources):
        raise ValueError("bound selector source hash changed")
    expected_parents = [
        ("host-root", str(host_root)),
        ("codex-config-parent", str(host_root / ".codex")),
        ("import-root", str(host_root / ".agents")),
        ("import-skills-root", str(host_root / ".agents/skills")),
        *[
            ("import-skill-directory", str(host_root / ".agents/skills" / name))
            for name in SKILL_NAMES
        ],
    ]
    parents = plan.get("parent_preimages", [])
    if [(row.get("role"), row.get("path")) for row in parents] != expected_parents:
        raise ValueError("operation escaped the fixed parent allowlist")
    config = plan.get("config", {})
    expected_stage = config_path.parent / f".int008-imported-skill-{plan['operation_id']}.tmp"
    if (
        config.get("path") != str(config_path)
        or config.get("private_preimage") != PREIMAGE_NAME
        or config.get("stage_path") != str(expected_stage)
    ):
        raise ValueError("operation escaped the fixed config path")
    if content_state(preimage, config["before"]["mode"]) != config.get("before"):
        raise ValueError("private config preimage changed")
    observed_preimage = config.get("observed_preimage", {})
    if any(
        observed_preimage.get(key) != config["before"].get(key)
        for key in ("kind", "mode", "size", "sha256")
    ):
        raise ValueError("observed config preimage binding changed")
    policy = config_policy(preimage, host_root)
    if policy != plan.get("policy"):
        raise ValueError("bound config policy changed")
    append = rendered_append(preimage, host_root, policy["missing"])
    postimage = preimage + append
    if sha(append) != config.get("append_sha256") or len(append) != config.get("append_size"):
        raise ValueError("bound config append changed")
    if content_state(postimage, config["before"]["mode"]) != config.get("after"):
        raise ValueError("bound config postimage changed")
    expected_actions = (
        [
            {
                "operation": "append-disabled-SKILL.md-selectors",
                "path": str(config_path),
                "selectors": [str(selector_path(host_root, name)) for name in policy["missing"]],
            }
        ]
        if append
        else []
    )
    if plan.get("actions") != expected_actions:
        raise ValueError("operation action set changed")
    checks = {
        "operation_id": plan["operation_id"],
        "action_sha256": action_sha256,
        "config_preimage_sha256": config["before"]["sha256"],
        "config_postimage_sha256": config["after"]["sha256"],
        "source_preimages_sha256": sha(canonical(sources)),
        "parent_preimages_sha256": sha(canonical(plan["parent_preimages"])),
        "policy_sha256": sha(canonical(policy)),
        "implementation_sha256": plan["implementation_sha256"],
    }
    if any(receipt.get(key) != value for key, value in checks.items()):
        raise ValueError("preview receipt no longer binds the operation")
    plan["action_sha256"] = action_sha256
    plan["receipt_sha256"] = receipt_sha256
    return plan, receipt, preimage, postimage


def parents_current(plan: dict, *, config_only: bool = False) -> None:
    no_symlink_components(Path(plan["host_root"]))
    no_symlink_components(Path(plan["config"]["path"]))
    allowed_roles = {"host-root", "codex-config-parent"} if config_only else None
    for row in plan["parent_preimages"]:
        if allowed_roles is not None and row["role"] not in allowed_roles:
            continue
        if directory_state(Path(row["path"])) != row["state"]:
            raise ValueError("bound parent directory changed")


def sources_current(plan: dict) -> None:
    host_root = Path(plan["host_root"])
    sources, parents = source_preimages(host_root)
    if sources != plan["source_preimages"] or parents != plan["parent_preimages"]:
        raise ValueError("approved imported-skill preimages changed")


def private_records_current(plan: dict) -> None:
    operation = Path(plan["operation_dir"])
    if directory_state(operation) != plan["operation_root"]:
        raise ValueError("private operation root identity changed")
    for name in (PREIMAGE_NAME, "operation.json", "preview-receipt.json"):
        observed, _data = read_regular(operation / name)
        if observed["mode"] != 0o600:
            raise ValueError("private operation file mode changed")


def stage_state(path: Path) -> dict:
    try:
        observed, data = read_regular(path)
    except FileNotFoundError:
        return {"kind": "absent"}
    return content_state(data, observed["mode"])


def staging_absent(plan: dict) -> None:
    if stage_state(Path(plan["config"]["stage_path"])) != {"kind": "absent"}:
        raise ValueError("operation has an interrupted staging file")


def write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short config staging write")
        view = view[written:]


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_replace_config(
    plan: dict,
    expected: dict,
    expected_data: bytes,
    target: bytes,
    *,
    drift_reason: str,
) -> bool:
    path = Path(plan["config"]["path"])
    stage = Path(plan["config"]["stage_path"])
    target_state = content_state(target, expected["mode"])
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    locked_descriptor = os.open(path, flags)
    created_stage = False
    try:
        fcntl.flock(locked_descriptor, fcntl.LOCK_EX)
        current, _data, observed = current_content(path)
        locked = os.fstat(locked_descriptor)
        if (locked.st_dev, locked.st_ino) != (observed["device"], observed["inode"]):
            raise ValueError("config path changed while acquiring advisory lock")
        if current == target_state and _data == target:
            staged = stage_state(stage)
            if staged != {"kind": "absent"}:
                if staged not in (expected, target_state):
                    raise ValueError("interrupted staging file is not a bound config image")
                stage.unlink()
                fsync_directory(path.parent)
            return False
        if current != expected or _data != expected_data:
            raise ValueError(drift_reason)

        staged = stage_state(stage)
        if staged == expected:
            stage.unlink()
            fsync_directory(path.parent)
            staged = {"kind": "absent"}
        if staged == {"kind": "absent"}:
            stage_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                stage_flags |= os.O_NOFOLLOW
            stage_descriptor = os.open(stage, stage_flags, 0o600)
            created_stage = True
            try:
                os.fchmod(stage_descriptor, target_state["mode"])
                write_all(stage_descriptor, target)
                os.fsync(stage_descriptor)
            finally:
                os.close(stage_descriptor)
            staged = stage_state(stage)
        if staged != target_state:
            raise ValueError("interrupted staging file is not the bound target image")
        latest, _latest_data, latest_observed = current_content(path)
        if (
            latest != expected
            or _latest_data != expected_data
            or (latest_observed["device"], latest_observed["inode"])
            != (locked.st_dev, locked.st_ino)
        ):
            raise ValueError("config preimage changed during staging")
        os.replace(stage, path)
        created_stage = False
        fsync_directory(path.parent)
    finally:
        os.close(locked_descriptor)
        if created_stage:
            try:
                stage.unlink()
            except FileNotFoundError:
                pass
    current, _data, _observed = current_content(path)
    if current != target_state or _data != target:
        raise ValueError("config postimage mismatch")
    return True


def apply_operation(args: argparse.Namespace, *, rollback: bool = False) -> dict:
    plan, _receipt, preimage, postimage = load_operation(args.operation_dir, args.host_root)
    if args.approve != plan["action_sha256"]:
        raise ValueError("exact preview action digest required")
    private_records_current(plan)
    config_path = Path(plan["config"]["path"])
    before = plan["config"]["before"]
    after = plan["config"]["after"]

    if rollback:
        parents_current(plan, config_only=True)
        changed = atomic_replace_config(
            plan,
            after,
            postimage,
            preimage,
            drift_reason="config changed after apply; rollback refused",
        )
        if not changed:
            return {"status": "already-rolled-back", "operation_id": plan["operation_id"]}
        return {
            "status": "rolled-back",
            "operation_id": plan["operation_id"],
            "native_effect": "not re-observed by filesystem rollback",
            "cleanup": plan["cleanup"],
        }

    if implementation_digest() != plan["implementation_sha256"]:
        raise ValueError("isolation implementation changed")
    sources_current(plan)
    private_records_current(plan)
    if not plan["actions"]:
        staging_absent(plan)
        current, current_data, _observed = current_content(config_path)
        if current != before or current_data != preimage:
            raise ValueError("config preimage changed")
        return {
            "status": "already-satisfied",
            "operation_id": plan["operation_id"],
            "native_effect": plan["native_effect"],
        }
    changed = atomic_replace_config(
        plan,
        before,
        preimage,
        postimage,
        drift_reason="config preimage changed",
    )
    if not changed:
        return {
            "status": "already-applied",
            "operation_id": plan["operation_id"],
            "native_effect": plan["native_effect"],
        }
    return {
        "status": "applied",
        "operation_id": plan["operation_id"],
        "selectors": [row["name"] for row in plan["source_preimages"]],
        "native_effect": plan["native_effect"],
        "production_rollout": False,
    }


def verify_operation(args: argparse.Namespace) -> dict:
    plan, _receipt, preimage, postimage = load_operation(args.operation_dir, args.host_root)
    if implementation_digest() != plan["implementation_sha256"]:
        raise ValueError("isolation implementation changed")
    sources_current(plan)
    private_records_current(plan)
    staging_absent(plan)
    current, data, _observed = current_content(Path(plan["config"]["path"]))
    if current == plan["config"]["after"] and data == postimage:
        status = "verified-applied" if plan["actions"] else "verified-satisfied"
        if config_policy(data, Path(plan["host_root"]))["missing"]:
            raise ValueError("fixed selectors are not represented in the config postimage")
    elif current == plan["config"]["before"] and data == preimage:
        status = "verified-preimage"
    else:
        raise ValueError("config is neither the bound preimage nor postimage")
    return {
        "status": status,
        "operation_id": plan["operation_id"],
        "native_effect": "not established by filesystem verification",
        "production_rollout": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preview", "apply", "verify", "rollback"))
    parser.add_argument("--host-root", type=Path, required=True)
    parser.add_argument("--operation-dir", type=Path, required=True)
    parser.add_argument("--host-build")
    parser.add_argument("--approve")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.operation == "preview":
            result = preview(args)
        elif args.operation == "verify":
            result = verify_operation(args)
        else:
            result = apply_operation(args, rollback=args.operation == "rollback")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
