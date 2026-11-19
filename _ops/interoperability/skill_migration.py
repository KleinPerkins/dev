#!/usr/bin/env python3
"""Bounded INT-008 migration for the two required Codex skill projections.

This is a source-owned preview/apply/verify/rollback transaction.  It never
clones, updates, reconciles, prunes, authenticates, or changes Codex config.
Private operation directories contain exact local link preimages and must stay
outside Git.  A preview action digest is not human approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tomllib
import uuid

import inventory
import original_sources


ROOT = Path(__file__).resolve().parents[2]
SKILLS = ("prompt-architect", "verification-before-completion")
MERGED_REVISION = "f646697751e41f01894187f1a4e7470df67a60c4"
IMPLEMENTATION_REVISION = "be481379a91c7c4efc26d5c2731afb1dbbc60700"
MERGED_TREE = "1604fd7217ca2fe54a0d2c539ef62f3b77405738"
PAYLOAD_SHA256 = "d4f67c26afd1ef87b2363d8a4a3cdc150b401184ccfde27798c17d43fbaf9893"
PAYLOAD_FILE_COUNT = 65
QUALIFIED_HOST_BUILD = "21828"
EVIDENCE_PATH = "docs/evidence/int005-int006/observations.json"
ADDITIONAL_QUALIFICATIONS = {
    "23880": {
        "revision": "acfa04128c9451f66f7d1bad18c71d32b895ee1e",
        "path": "docs/evidence/int005-int006/build-23880-observations.json",
    },
}
PORTABILITY_MANIFEST_SHA256 = "e6e9bf948d1f664367456fffe06e408a08b50933466022b8b7dc2e30a35bf725"
PORTABILITY_SKILLS_REVISION = "f2301ce13d50e471ff1e8ae51fb5a41bf47eaf0a"
SCHEMA = "interoperability/skill-migration-operation/v1"
RECEIPT_SCHEMA = "interoperability/skill-migration-preview-receipt/v1"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    # This is also the accepted INT-005/006 payload-map encoding.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def git_bytes(root: Path, *args: str) -> bytes:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    return subprocess.check_output(
        ["git", "-C", str(root), *args], stderr=subprocess.DEVNULL, env=env
    )


def git_text(root: Path, *args: str) -> str:
    return git_bytes(root, *args).decode("utf-8").strip()


def regular_bytes(path: Path, *, missing: bool = False) -> bytes | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing:
            return None
        raise
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"regular unshared file required: {path}")
    return path.read_bytes()


def no_symlink_components(path: Path) -> None:
    current = path
    while True:
        try:
            if current.is_symlink():
                raise ValueError(f"symlinked path component refused: {current}")
        except OSError as exc:
            raise ValueError(f"path component unavailable: {current}") from exc
        if current == current.parent:
            break
        current = current.parent


def repository_owner(path: Path) -> None:
    owner, reason = inventory.repository(path)
    if owner not in ("KleinPerkins/skills", "KleinPerkins/skills-private-original") or reason is not None:
        raise ValueError("Skills source identity unavailable, excluded, or mismatched")
    original_sources.verify_repository(path, "KleinPerkins/skills", revision=MERGED_REVISION)


def git_payload(root: Path, revision: str) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    prefixes = [f"global/skills/{name}" for name in SKILLS]
    rows = git_bytes(root, "ls-tree", "-r", "-z", revision, "--", *prefixes)
    digest_map: dict[str, str] = {}
    blobs: dict[str, tuple[str, bytes]] = {}
    for raw in rows.split(b"\0"):
        if not raw:
            continue
        try:
            metadata, raw_path = raw.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split()
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise ValueError("malformed Skills Git tree") from exc
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("required skill payload must contain regular Git blobs only")
        prefix = "global/skills/"
        if not path.startswith(prefix) or path in digest_map:
            raise ValueError("required skill payload path is invalid or duplicated")
        relative = path[len(prefix) :]
        if not any(relative == name or relative.startswith(name + "/") for name in SKILLS):
            raise ValueError("required skill payload escaped the fixed allowlist")
        data = git_bytes(root, "cat-file", "blob", object_id)
        digest_map[relative] = sha(data)
        blobs[relative] = (mode, data)
    return digest_map, blobs


def validate_qualification(root: Path, host_build: str) -> dict:
    if host_build == QUALIFIED_HOST_BUILD:
        location = {"revision": MERGED_REVISION, "path": EVIDENCE_PATH}
    else:
        location = ADDITIONAL_QUALIFICATIONS.get(host_build)
        if location is None:
            raise ValueError("current host build lacks the exact merged INT-005/006 discovery proof")
    data = git_bytes(root, "show", f"{location['revision']}:{location['path']}")
    try:
        rows = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("merged native discovery evidence is malformed") from exc
    required = {
        "SKL-01-native-discovery-and-use",
        "ROL-01-native-canary-rollback",
    }
    matched: dict[str, dict] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("check") not in required:
            continue
        if row.get("check") in matched:
            raise ValueError("merged native discovery evidence is duplicated")
        expected = {
            "schema": "interoperability/qualification/v1",
            "capability": "required-skills-codex-discovery",
            "owner": "KleinPerkins/skills",
            "source_revision": IMPLEMENTATION_REVISION,
            "adapter_revision": IMPLEMENTATION_REVISION,
            "payload_sha256": PAYLOAD_SHA256,
            "host": "codex",
            "surface": "local-macos-desktop",
            "host_build": host_build,
            "outcome": "pass",
        }
        if any(row.get(key) != value for key, value in expected.items()):
            raise ValueError("merged native discovery evidence is stale or mismatched")
        limitations = row.get("limitations")
        if not isinstance(limitations, list) or "not-activation" not in limitations:
            raise ValueError("native discovery evidence must retain its non-activation limit")
        matched[row["check"]] = row
    if set(matched) != required:
        raise ValueError("current host build lacks the exact merged INT-005/006 discovery proof")
    return {
        "revision": location["revision"],
        "path": location["path"],
        "sha256": sha(data),
        "host_build": host_build,
        "checks": sorted(required),
        "activation_authority": False,
    }


def object_source_proof(root: Path, host_build: str) -> tuple[dict, dict[str, tuple[str, bytes]]]:
    no_symlink_components(root)
    repository_owner(root)
    if git_text(root, "rev-parse", f"{MERGED_REVISION}^{{commit}}") != MERGED_REVISION:
        raise ValueError("merged Skills revision is unavailable")
    if git_text(root, "rev-parse", f"{MERGED_REVISION}^{{tree}}") != MERGED_TREE:
        raise ValueError("merged Skills tree changed")
    digest_map, blobs = git_payload(root, MERGED_REVISION)
    payload = sha(canonical(digest_map))
    if len(digest_map) != PAYLOAD_FILE_COUNT or payload != PAYLOAD_SHA256:
        raise ValueError("merged required-skill payload changed")
    proof = {
        "repository": "KleinPerkins/skills",
        "revision": MERGED_REVISION,
        "tree": MERGED_TREE,
        "payload_sha256": payload,
        "file_count": len(digest_map),
        "qualification": validate_qualification(root, host_build),
    }
    return proof, blobs


def filesystem_payload(root: Path) -> tuple[str, int]:
    digest_map: dict[str, str] = {}
    observed_dirs: set[str] = set()
    base = root / "global/skills"
    for name in SKILLS:
        skill = base / name
        if skill.is_symlink() or not skill.is_dir():
            raise ValueError(f"required source skill is missing or linked: {name}")
        observed_dirs.add(str(skill.relative_to(base)))
        for parent, dirs, files in os.walk(skill, followlinks=False):
            parent_path = Path(parent)
            for directory in dirs:
                path = parent_path / directory
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    raise ValueError("linked directory in required source payload")
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError("required source payload contains a non-directory")
                observed_dirs.add(str(path.relative_to(base)))
            for filename in files:
                path = parent_path / filename
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise ValueError("required source payload contains a non-regular file")
                relative = str(path.relative_to(base))
                digest_map[relative] = sha(path.read_bytes())
    expected_dirs = set(SKILLS)
    for relative in digest_map:
        parent = Path(relative).parent
        while parent != Path("."):
            expected_dirs.add(str(parent))
            parent = parent.parent
    if observed_dirs != expected_dirs:
        raise ValueError("required source payload contains unexpected directories")
    return sha(canonical(digest_map)), len(digest_map)


def verify_export_path(export: Path, blobs: dict[str, tuple[str, bytes]]) -> None:
    expected_files = {
        f"global/skills/{relative}": 0o500 if mode == "100755" else 0o400
        for relative, (mode, _data) in blobs.items()
    }
    expected_dirs = {".", "global", "global/skills"}
    for relative in expected_files:
        parent = Path(relative).parent
        while parent != Path("."):
            expected_dirs.add(str(parent))
            parent = parent.parent
    observed_dirs: dict[str, int] = {}
    observed_files: dict[str, int] = {}
    for parent, directories, files in os.walk(export, followlinks=False):
        parent_path = Path(parent)
        relative_parent = str(parent_path.relative_to(export)) or "."
        parent_info = parent_path.lstat()
        if not stat.S_ISDIR(parent_info.st_mode):
            raise ValueError("private source export contains a non-directory")
        observed_dirs[relative_parent] = stat.S_IMODE(parent_info.st_mode)
        for name in directories:
            path = parent_path / name
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError("private source export contains a linked or special directory")
        for name in files:
            path = parent_path / name
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("private source export contains a non-regular file")
            observed_files[str(path.relative_to(export))] = stat.S_IMODE(info.st_mode)
    if set(observed_dirs) != expected_dirs or set(observed_files) != set(expected_files):
        raise ValueError("private source export path set changed")
    if any(mode != 0o500 for mode in observed_dirs.values()) or observed_files != expected_files:
        raise ValueError("private source export privacy mode changed")
    payload, count = filesystem_payload(export)
    if payload != PAYLOAD_SHA256 or count != PAYLOAD_FILE_COUNT:
        raise ValueError("private source export changed")


def primary_observation(home: Path, *, require_current: bool) -> dict:
    expected = (home / "dev/capabilities/skills").absolute()
    no_symlink_components(expected)
    if not expected.is_dir() or not (expected / ".git").is_dir():
        raise ValueError("durable primary Skills checkout is required")
    if Path(git_text(expected, "rev-parse", "--show-toplevel")) != expected:
        raise ValueError("durable primary Skills checkout root mismatched")
    repository_owner(expected)
    branch = git_text(expected, "branch", "--show-current")
    head = git_text(expected, "rev-parse", "HEAD")
    origin_main = git_text(expected, "rev-parse", "origin/main")
    status = git_text(expected, "status", "--porcelain", "--untracked-files=all")
    payload, count = filesystem_payload(expected)
    observation = {
        "path": str(expected),
        "branch": branch,
        "head": head,
        "origin_main": origin_main,
        "clean": not bool(status),
        "payload_sha256": payload,
        "file_count": count,
        "current_merged_payload": False,
    }
    if not observation["clean"]:
        raise ValueError("durable primary Skills checkout must be clean")
    if require_current:
        ancestor = subprocess.run(
            ["git", "-C", str(expected), "merge-base", "--is-ancestor", MERGED_REVISION, head],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
        if (
            branch != "main"
            or head != origin_main
            or ancestor.returncode != 0
            or payload != PAYLOAD_SHA256
            or count != PAYLOAD_FILE_COUNT
        ):
            raise ValueError("durable primary Skills checkout is stale or not at the merged payload")
        observation["current_merged_payload"] = True
    return observation


def portability_manifest_proof(raw_path: Path) -> dict:
    path = raw_path.expanduser().absolute()
    no_symlink_components(path)
    data = regular_bytes(path)
    if sha(data) != PORTABILITY_MANIFEST_SHA256:
        raise ValueError("pinned-retained requires the exact approved portability manifest")
    manifest = json.loads(data)
    repositories = manifest.get("repositories", [])
    selected = [row for row in repositories if row.get("id") == "KleinPerkins/skills"]
    if (
        manifest.get("schema") != "personal-portability/manifest/v1"
        or manifest.get("profile") != "personal-codex"
        or len(selected) != 1
        or selected[0].get("revision") != PORTABILITY_SKILLS_REVISION
        or selected[0].get("path") != "capabilities/skills"
        or selected[0].get("disposition") != "source-only"
        or selected[0].get("required") is not True
    ):
        raise ValueError("approved portability source binding is inconsistent")
    return {
        "schema": "interoperability/pinned-retained-source/v1",
        "manifest_path": str(path),
        "manifest_sha256": sha(data),
        "repository": "KleinPerkins/skills",
        "revision": PORTABILITY_SKILLS_REVISION,
        "relative_path": "capabilities/skills",
    }


def pinned_primary_observation(home: Path, binding: dict) -> dict:
    observation = primary_observation(home, require_current=False)
    primary = Path(observation["path"])
    ancestor = subprocess.run(
        ["git", "-C", str(primary), "merge-base", "--is-ancestor", MERGED_REVISION, observation["head"]],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if (
        binding.get("manifest_sha256") != PORTABILITY_MANIFEST_SHA256
        or binding.get("revision") != PORTABILITY_SKILLS_REVISION
        or observation["branch"] != ""
        or observation["head"] != PORTABILITY_SKILLS_REVISION
        or observation["payload_sha256"] != PAYLOAD_SHA256
        or observation["file_count"] != PAYLOAD_FILE_COUNT
        or ancestor.returncode != 0
    ):
        raise ValueError("pinned-retained requires the exact clean detached approved Skills pin and payload")
    return {**observation, "approved_pinned_payload": True, "portability_manifest_sha256": PORTABILITY_MANIFEST_SHA256}


def export_payload(operation: Path, blobs: dict[str, tuple[str, bytes]]) -> Path:
    export = operation / "source-export"
    base = export / "global/skills"
    base.mkdir(parents=True)
    created_dirs = {export, export / "global", base}
    for relative, (mode, data) in sorted(blobs.items()):
        path = base / relative
        if not path.is_relative_to(base):
            raise ValueError("source export path escaped the operation")
        path.parent.mkdir(parents=True, exist_ok=True)
        created_dirs.update([path.parent, *path.parent.parents])
        with path.open("xb") as stream:
            os.fchmod(stream.fileno(), 0o500 if mode == "100755" else 0o400)
            stream.write(data)
    # Make the exported owner payload read-only.  The operation root remains
    # private and writable for its immutable preview records.
    for directory in sorted(
        (item for item in created_dirs if item == export or item.is_relative_to(export)),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        directory.chmod(0o500)
    verify_export_path(export, blobs)
    return export


def state(path: Path) -> dict:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"kind": "absent"}
    mode = stat.S_IMODE(info.st_mode)
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(path)
        if path.is_dir():
            target_kind = "directory"
        elif path.exists():
            target_kind = "other"
        else:
            target_kind = "missing"
        return {"kind": "symlink", "target": target, "mode": mode, "target_kind": target_kind}
    if stat.S_ISDIR(info.st_mode):
        return {
            "kind": "directory",
            "mode": mode,
            "device": info.st_dev,
            "inode": info.st_ino,
        }
    if stat.S_ISREG(info.st_mode):
        return {"kind": "file", "mode": mode}
    return {"kind": "special", "mode": mode}


def default_symlink_mode() -> int:
    current = os.umask(0)
    os.umask(current)
    return 0o777 & ~current


def symlink_state(target: Path, mode: int | None = None) -> dict:
    return {
        "kind": "symlink",
        "target": str(target),
        "mode": default_symlink_mode() if mode is None else mode,
        "target_kind": "directory",
    }


def require_real_directory(path: Path, *, optional: bool = False) -> dict:
    observed = state(path)
    if optional and observed["kind"] == "absent":
        return observed
    if observed["kind"] != "directory":
        raise ValueError(f"real directory required: {path}")
    return observed


def normalize_config_path(raw: str, home: Path) -> Path:
    if raw == "~":
        return home
    if raw.startswith("~/"):
        return home / raw[2:]
    path = Path(raw)
    return path if path.is_absolute() else home / path


def relevant_config_policy(home: Path, primary: Path, desired: Path) -> dict:
    config = home / ".codex/config.toml"
    if not config.exists():
        rows: list[dict] = []
    else:
        data = regular_bytes(config)
        try:
            parsed = tomllib.loads(data.decode("utf-8"))
        except (UnicodeError, tomllib.TOMLDecodeError) as exc:
            raise ValueError("Codex config is malformed; no migration attempted") from exc
        skills = parsed.get("skills", {})
        if not isinstance(skills, dict):
            raise ValueError("Codex skills config has an unsupported shape")
        configured = skills.get("config", [])
        if not isinstance(configured, list):
            raise ValueError("Codex skills config has an unsupported shape")
        rows = []
        for row in configured:
            if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                raise ValueError("Codex skills config row has an unsupported shape")
            enabled = row.get("enabled")
            if enabled is not None and not isinstance(enabled, bool):
                raise ValueError("Codex skill enablement override must be boolean")
            lexical = normalize_config_path(row["path"], home).absolute()
            resolved = lexical.resolve(strict=False)
            candidates: list[tuple[str, Path]] = []
            for name in SKILLS:
                candidates.extend(
                    [
                        ("agents-alias", home / ".agents/skills" / name),
                        ("codex-alias", home / ".codex/skills" / name),
                        ("primary-source", primary / "global/skills" / name),
                        ("desired-source", desired / "global/skills" / name),
                    ]
                )
            classification = None
            for label, candidate in candidates:
                if lexical in {candidate, candidate / "SKILL.md"}:
                    classification = label
                    break
            if classification is None:
                for label, candidate in candidates:
                    resolved_candidate = candidate.resolve(strict=False)
                    if resolved in {resolved_candidate, resolved_candidate / "SKILL.md"}:
                        classification = label
                        break
            if classification is None:
                continue
            if classification == "agents-alias":
                raise ValueError("native skill override targets a retiring .agents alias")
            if classification == "primary-source" and primary != desired:
                raise ValueError("canary would detach a native source override from its target")
            rows.append(
                {
                    "path_sha256": sha(str(lexical).encode("utf-8")),
                    "path_class": classification,
                    "enabled": enabled,
                }
            )
    rows.sort(key=lambda row: (row["path_sha256"], str(row["enabled"])))
    return {
        "schema": "interoperability/relevant-codex-skill-policy/v1",
        "rows": rows,
        "effective_enablement": "explicit-overrides-preserved" if rows else "unknown-no-relevant-override",
    }


def target_plan(
    home: Path, primary: Path, desired: Path, operation_id: str
) -> tuple[list[dict], list[dict], list[dict]]:
    parents = [
        {
            "role": "managed-parent",
            "path": str(home / ".codex"),
            "state": require_real_directory(home / ".codex"),
        },
        {
            "role": "managed-parent",
            "path": str(home / ".codex/skills"),
            "state": require_real_directory(home / ".codex/skills"),
        },
        {
            "role": "managed-parent",
            "path": str(home / ".agents/skills"),
            "state": require_real_directory(home / ".agents/skills", optional=True),
        },
    ]
    managed: list[dict] = []
    conflicts: list[str] = []
    link_mode = default_symlink_mode()
    for name in SKILLS:
        agent = home / ".agents/skills" / name
        codex = home / ".codex/skills" / name
        agent_stage = agent.parent / f".int008-{operation_id}-{name}"
        codex_stage = codex.parent / f".int008-{operation_id}-{name}"
        primary_target = primary / "global/skills" / name
        desired_target = desired / "global/skills" / name
        agent_before = state(agent)
        codex_before = state(codex)
        exact_agent = symlink_state(primary_target, agent_before.get("mode", link_mode))
        exact_codex = symlink_state(desired_target, codex_before.get("mode", link_mode))
        if agent_before["kind"] not in {"absent", "symlink"} or (
            agent_before["kind"] == "symlink" and agent_before != exact_agent
        ):
            conflicts.append(str(agent))
        if codex_before["kind"] not in {"absent", "symlink"} or (
            codex_before["kind"] == "symlink" and codex_before != exact_codex
        ):
            conflicts.append(str(codex))
        for staging in (agent_stage, codex_stage):
            if state(staging)["kind"] != "absent":
                conflicts.append(str(staging))
        managed.extend(
            [
                {
                    "path": str(codex),
                    "staging_path": str(codex_stage),
                    "before": codex_before,
                    "after": exact_codex,
                    "operation": "create-symlink" if codex_before["kind"] == "absent" else "none",
                },
                {
                    "path": str(agent),
                    "staging_path": str(agent_stage),
                    "before": agent_before,
                    "after": {"kind": "absent"},
                    "operation": "remove-symlink" if agent_before["kind"] == "symlink" else "none",
                },
            ]
        )
    if conflicts:
        raise ValueError("managed-path conflict; preserving every path: " + ", ".join(conflicts))
    preserved = []
    for name in SKILLS:
        path = home / ".cursor/skills" / name
        preserved.append({"role": "preserved-cursor", "path": str(path), "state": state(path)})
    actions = [row for row in managed if row["operation"] != "none"]
    return managed, actions, parents + preserved


def private_operation_path(raw: Path, roots: tuple[Path, ...]) -> Path:
    operation = raw.expanduser().absolute()
    if operation.exists():
        raise ValueError("operation directory already exists")
    no_symlink_components(operation)
    resolved = operation.resolve(strict=False)
    for root in roots:
        protected = root.expanduser().resolve(strict=False)
        if resolved == protected or resolved.is_relative_to(protected):
            raise ValueError("private operation storage must be outside source roots")
    ancestor = resolved.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    inside = subprocess.run(
        ["git", "-C", str(ancestor), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if inside.returncode == 0 and inside.stdout.strip() == "true":
        raise ValueError("private operation storage must be outside Git worktrees")
    return resolved


def implementation_digest() -> str:
    files = (
        Path(__file__),
        Path(__file__).with_name("inventory.py"),
        Path(__file__).with_name("original_sources.py"),
        ROOT / "capabilities/bootstrap.sh",
    )
    return sha(b"".join(path.read_bytes() for path in files))


def remove_private_tree(path: Path) -> None:
    # Canary exports are intentionally read-only.  Normalize only this exact
    # private root before its separately authorized cleanup; never follow links.
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


def preview(args: argparse.Namespace) -> dict:
    home = args.home.expanduser().resolve()
    no_symlink_components(home)
    primary = (home / "dev/capabilities/skills").absolute()
    source = args.skills_source.expanduser().resolve()
    operation = private_operation_path(
        args.operation_dir,
        (ROOT, source, primary, home / ".codex", home / ".agents", home / ".cursor"),
    )
    manifest_path = getattr(args, "portability_manifest", None)
    if args.source_mode == "pinned-retained":
        if manifest_path is None:
            raise ValueError("pinned-retained requires --portability-manifest")
        binding = portability_manifest_proof(manifest_path)
    else:
        if manifest_path is not None:
            raise ValueError("--portability-manifest is only valid with pinned-retained")
        binding = None
    object_proof, blobs = object_source_proof(source, args.host_build)
    primary_proof = (
        pinned_primary_observation(home, binding)
        if binding is not None
        else primary_observation(home, require_current=args.source_mode == "retained")
    )
    desired = operation / "source-export" if args.source_mode == "canary" else primary
    policy = relevant_config_policy(home, primary, desired)
    operation_id = str(uuid.uuid4())
    managed, actions, preserved = target_plan(home, primary, desired, operation_id)

    operation.mkdir(mode=0o700)
    try:
        operation_root = state(operation)
        if operation_root.get("kind") != "directory" or operation_root.get("mode") != 0o700:
            raise ValueError("private operation root must be an exact 0700 directory")
        if args.source_mode == "canary":
            export_payload(operation, blobs)
        source_proof = {
            "mode": args.source_mode,
            "git_source": str(source),
            "object": object_proof,
            "primary": primary_proof,
            "desired": str(desired),
        }
        if binding is not None:
            source_proof["portability_manifest"] = binding
        plan = {
            "schema": SCHEMA,
            "operation_id": operation_id,
            "operation_dir": str(operation),
            "operation_root": operation_root,
            "home": str(home),
            "source_mode": args.source_mode,
            "host_build": args.host_build,
            "source_proof": source_proof,
            "policy": policy,
            "policy_sha256": sha(canonical(policy)),
            "managed": managed,
            "actions": actions,
            "preserved": preserved,
            "implementation_sha256": implementation_digest(),
            "affected_sessions": (
                "All Codex sessions scanning the shared .agents/.codex skill roots; "
                "existing contexts may retain earlier discovery."
            ),
            "rollback": "Restore exact .agents aliases and remove only matching .codex links; refuse later path edits.",
            "cleanup": (
                "After verified rollback, remove only this exact private operation directory "
                "under its separately reviewed cleanup step."
            ),
            "production_rollout": False,
            "retained_installation": args.source_mode in {"retained", "pinned-retained"},
        }
        action_sha256 = sha(canonical(plan))
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "operation_id": plan["operation_id"],
            "action_sha256": action_sha256,
            "source_proof_sha256": sha(canonical(source_proof)),
            "preimages_sha256": sha(canonical({"managed": managed, "preserved": preserved})),
            "policy_sha256": plan["policy_sha256"],
            "implementation_sha256": plan["implementation_sha256"],
        }
        record = {
            **plan,
            "action_sha256": action_sha256,
            "receipt_sha256": sha(canonical(receipt)),
        }
        for name, payload in (
            ("operation.json", canonical(record) + b"\n"),
            ("preview-receipt.json", canonical(receipt) + b"\n"),
        ):
            path = operation / name
            with path.open("xb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(payload)
        return {
            "status": "previewed",
            "operation_id": plan["operation_id"],
            "operation_dir": str(operation),
            "action_sha256": action_sha256,
            "source_mode": args.source_mode,
            "changed": bool(actions),
            "actions": [{"operation": row["operation"], "path": row["path"]} for row in actions],
            "effective_enablement": policy["effective_enablement"],
            "affected_sessions": plan["affected_sessions"],
            "production_rollout": False,
        }
    except Exception:
        # Preview is the only command allowed to create the operation.  A failed
        # preview leaves no partial private authority or export behind.
        try:
            remove_private_tree(operation)
        except OSError:
            # Preserve the original preview failure; a cleanup failure is still
            # visible because the exact operation root remains present.
            pass
        raise


def load_operation(operation: Path) -> tuple[dict, dict]:
    operation = operation.expanduser().absolute()
    no_symlink_components(operation)
    root_observed = state(operation)
    if root_observed.get("kind") != "directory" or root_observed.get("mode") != 0o700:
        raise ValueError("private operation root changed or is not mode 0700")
    for name in ("operation.json", "preview-receipt.json"):
        observed = state(operation / name)
        if observed.get("kind") != "file" or observed.get("mode") != 0o600:
            raise ValueError("private operation record changed or is not mode 0600")
    record_data = regular_bytes(operation / "operation.json")
    receipt_data = regular_bytes(operation / "preview-receipt.json")
    record = json.loads(record_data)
    receipt = json.loads(receipt_data)
    if not isinstance(record, dict) or not isinstance(receipt, dict):
        raise ValueError("operation records must be JSON objects")
    action_sha256 = record.pop("action_sha256", None)
    receipt_sha256 = record.pop("receipt_sha256", None)
    if sha(canonical(record)) != action_sha256:
        raise ValueError("operation action changed")
    if sha(canonical(receipt)) != receipt_sha256:
        raise ValueError("preview receipt changed")
    record["action_sha256"] = action_sha256
    record["receipt_sha256"] = receipt_sha256
    if record.get("schema") != SCHEMA or receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError("unknown operation schema")
    if record.get("operation_dir") != str(operation) or receipt.get("operation_id") != record.get("operation_id"):
        raise ValueError("operation identity/location changed")
    if str(uuid.UUID(record["operation_id"])) != record["operation_id"]:
        raise ValueError("operation identity changed")
    if record.get("operation_root") != root_observed:
        raise ValueError("private operation root identity changed")
    checks = {
        "action_sha256": action_sha256,
        "source_proof_sha256": sha(canonical(record["source_proof"])),
        "preimages_sha256": sha(canonical({"managed": record["managed"], "preserved": record["preserved"]})),
        "policy_sha256": record["policy_sha256"],
        "implementation_sha256": record["implementation_sha256"],
    }
    if any(receipt.get(key) != value for key, value in checks.items()):
        raise ValueError("preview receipt no longer binds the operation")
    if record["source_mode"] not in {"retained", "canary", "pinned-retained"}:
        raise ValueError("unsupported source mode")
    home = Path(record["home"])
    allowed = {
        str(home / root / "skills" / name)
        for root in (".agents", ".codex")
        for name in SKILLS
    }
    managed = record.get("managed", [])
    managed_paths = {row.get("path") for row in managed}
    if managed_paths != allowed or len(managed) != len(allowed):
        raise ValueError("operation escaped the fixed skill/path allowlist")
    for row in managed:
        path = Path(row["path"])
        expected_staging = path.parent / f".int008-{record['operation_id']}-{path.name}"
        if row.get("staging_path") != str(expected_staging):
            raise ValueError("operation staging path is invalid")
    expected_actions = [row for row in managed if row.get("operation") != "none"]
    if record.get("actions") != expected_actions:
        raise ValueError("operation action sequence is invalid")
    action_paths = [row.get("path") for row in expected_actions]
    if len(action_paths) != len(set(action_paths)) or not set(action_paths) <= allowed:
        raise ValueError("operation action set is invalid")
    return record, receipt


def verify_export(plan: dict) -> None:
    desired = Path(plan["source_proof"]["desired"])
    source = Path(plan["source_proof"]["git_source"])
    _proof, blobs = object_source_proof(source, plan["host_build"])
    verify_export_path(desired, blobs)


def current_source_proof(plan: dict) -> None:
    source = Path(plan["source_proof"]["git_source"])
    object_proof, blobs = object_source_proof(source, plan["host_build"])
    if object_proof != plan["source_proof"]["object"]:
        raise ValueError("merged source proof changed")
    if plan["source_mode"] == "pinned-retained":
        previous_binding = plan["source_proof"]["portability_manifest"]
        binding = portability_manifest_proof(Path(previous_binding["manifest_path"]))
        if binding != previous_binding:
            raise ValueError("approved portability manifest binding changed")
        primary = pinned_primary_observation(Path(plan["home"]), binding)
    else:
        primary = primary_observation(Path(plan["home"]), require_current=plan["source_mode"] == "retained")
    if primary != plan["source_proof"]["primary"]:
        raise ValueError("durable primary source changed")
    if plan["source_mode"] == "canary":
        verify_export_path(Path(plan["source_proof"]["desired"]), blobs)


def current_policy(plan: dict) -> None:
    home = Path(plan["home"])
    primary = home / "dev/capabilities/skills"
    desired = Path(plan["source_proof"]["desired"])
    policy = relevant_config_policy(home, primary, desired)
    if sha(canonical(policy)) != plan["policy_sha256"]:
        raise ValueError("relevant Codex skill policy changed")


def expected_stage(plan: dict, prefix: int) -> dict[str, dict]:
    expected = {row["path"]: row["before"] for row in plan["managed"]}
    for row in plan["actions"][:prefix]:
        expected[row["path"]] = row["after"]
    return expected


def current_managed(plan: dict) -> dict[str, dict]:
    return {row["path"]: state(Path(row["path"])) for row in plan["managed"]}


def prefix_state(plan: dict) -> int:
    observed = current_managed(plan)
    matches = [index for index in range(len(plan["actions"]) + 1) if observed == expected_stage(plan, index)]
    if len(matches) != 1:
        raise ValueError("managed paths changed outside the recoverable operation sequence")
    return matches[0]


def preserved_current(plan: dict) -> None:
    for row in plan["preserved"]:
        if state(Path(row["path"])) != row["state"]:
            raise ValueError("preserved path changed before apply")


def managed_parents_current(plan: dict) -> None:
    for row in plan["preserved"]:
        if row.get("role") == "managed-parent" and state(Path(row["path"])) != row["state"]:
            raise ValueError("managed parent directory changed")


def private_operation_current(plan: dict) -> None:
    operation = Path(plan["operation_dir"])
    no_symlink_components(operation)
    if state(operation) != plan["operation_root"]:
        raise ValueError("private operation root identity or mode changed")
    for name in ("operation.json", "preview-receipt.json"):
        observed = state(operation / name)
        if observed.get("kind") != "file" or observed.get("mode") != 0o600:
            raise ValueError("private operation record changed or is not mode 0600")


def staged_symlink(row: dict) -> dict:
    symlinks = [candidate for candidate in (row["before"], row["after"]) if candidate["kind"] == "symlink"]
    if not symlinks or any(candidate["target"] != symlinks[0]["target"] for candidate in symlinks):
        raise ValueError("operation staging target is invalid")
    return symlinks[0]


def clear_interrupted_staging(plan: dict) -> None:
    for row in plan["managed"]:
        staging = Path(row["staging_path"])
        observed = state(staging)
        if observed["kind"] == "absent":
            continue
        expected = staged_symlink(row)
        if observed["kind"] != "symlink" or observed.get("target") != expected["target"]:
            raise ValueError("operation staging path changed")
        staging.unlink()


def staging_absent(plan: dict) -> None:
    if any(state(Path(row["staging_path"]))["kind"] != "absent" for row in plan["managed"]):
        raise ValueError("operation has an interrupted staging symlink")


def set_symlink_mode(path: Path, mode: int) -> None:
    current = stat.S_IMODE(path.lstat().st_mode)
    if current == mode:
        return
    try:
        if hasattr(os, "lchmod"):
            os.lchmod(path, mode)
        else:
            os.chmod(path, mode, follow_symlinks=False)
    except (NotImplementedError, OSError) as exc:
        raise ValueError("could not restore exact symlink mode") from exc


def mutate(row: dict, *, reverse: bool = False) -> None:
    path = Path(row["path"])
    staging = Path(row["staging_path"])
    before = row["after"] if reverse else row["before"]
    after = row["before"] if reverse else row["after"]
    if state(path) != before:
        raise ValueError("mutation preimage changed")
    if state(staging)["kind"] != "absent":
        raise ValueError("operation staging path is not absent")
    if after["kind"] == "absent":
        path.unlink()
    elif after["kind"] == "symlink":
        if not path.parent.is_dir() or path.parent.is_symlink():
            raise ValueError("managed link parent changed")
        target = Path(after["target"])
        if not target.is_dir() or target.is_symlink():
            raise ValueError("managed link source changed")
        os.symlink(after["target"], staging)
        try:
            set_symlink_mode(staging, after["mode"])
            if state(staging) != after:
                raise ValueError("staged symlink postimage mismatch")
            if state(path) != before:
                raise ValueError("mutation preimage changed during staging")
            # A hard link to the staged symlink is an atomic no-clobber publish:
            # a concurrent later path wins with FileExistsError and is preserved.
            os.link(staging, path, follow_symlinks=False)
            staging.unlink()
        except BaseException:
            observed = state(staging)
            if observed["kind"] == "symlink" and observed.get("target") == after["target"]:
                staging.unlink()
            raise
    else:
        raise ValueError("unsupported mutation postimage")
    if state(staging)["kind"] != "absent":
        raise ValueError("operation staging path was not cleared")
    if state(path) != after:
        raise ValueError("mutation postimage mismatch")


def apply_operation(args: argparse.Namespace, *, rollback: bool = False) -> dict:
    plan, _ = load_operation(args.operation_dir)
    if args.approve != plan["action_sha256"]:
        raise ValueError("exact preview action digest required")
    private_operation_current(plan)
    clear_interrupted_staging(plan)
    start = prefix_state(plan)
    if rollback:
        if start == 0:
            return {"status": "already-rolled-back", "operation_id": plan["operation_id"]}
        for index in range(start - 1, -1, -1):
            if prefix_state(plan) != index + 1:
                raise ValueError("managed paths changed during rollback")
            private_operation_current(plan)
            managed_parents_current(plan)
            mutate(plan["actions"][index], reverse=True)
        if prefix_state(plan) != 0:
            raise ValueError("rollback did not restore the exact preimage")
        return {
            "status": "recovered-rolled-back" if start < len(plan["actions"]) else "rolled-back",
            "operation_id": plan["operation_id"],
            "cleanup": plan["cleanup"],
        }

    if implementation_digest() != plan["implementation_sha256"]:
        raise ValueError("migration implementation changed")
    current_source_proof(plan)
    current_policy(plan)
    preserved_current(plan)
    if start == len(plan["actions"]):
        return {"status": "already-applied", "operation_id": plan["operation_id"]}
    for index in range(start, len(plan["actions"])):
        if prefix_state(plan) != index:
            raise ValueError("managed paths changed during apply")
        current_source_proof(plan)
        current_policy(plan)
        preserved_current(plan)
        private_operation_current(plan)
        mutate(plan["actions"][index])
    if prefix_state(plan) != len(plan["actions"]):
        raise ValueError("apply did not reach the exact postimage")
    return {
        "status": "recovered-applied" if start else "applied",
        "operation_id": plan["operation_id"],
        "source_mode": plan["source_mode"],
        "native_behavior": "requires separate bounded observation",
        "production_rollout": False,
    }


def verify_operation(args: argparse.Namespace) -> dict:
    plan, _ = load_operation(args.operation_dir)
    if implementation_digest() != plan["implementation_sha256"]:
        raise ValueError("migration implementation changed")
    private_operation_current(plan)
    staging_absent(plan)
    prefix = prefix_state(plan)
    if prefix == len(plan["actions"]):
        current_source_proof(plan)
        current_policy(plan)
        preserved_current(plan)
        status = "verified-applied"
    elif prefix == 0:
        preserved_current(plan)
        status = "verified-preimage"
    else:
        raise ValueError("operation is interrupted at a recoverable partial prefix")
    return {
        "status": status,
        "operation_id": plan["operation_id"],
        "source_mode": plan["source_mode"],
        "effective_enablement": plan["policy"]["effective_enablement"],
        "native_behavior": "not established by filesystem verification",
        "production_rollout": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preview", "apply", "verify", "rollback"))
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--operation-dir", type=Path, required=True)
    parser.add_argument("--source-mode", choices=("retained", "canary", "pinned-retained"), default="retained")
    parser.add_argument("--portability-manifest", type=Path,
                        help="Exact approved personal portability manifest; required only for pinned-retained")
    parser.add_argument("--skills-source", type=Path)
    parser.add_argument("--host-build")
    parser.add_argument("--approve")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.skills_source is None:
        args.skills_source = args.home.expanduser() / "dev/capabilities/skills"
    try:
        if args.operation == "preview":
            if not args.host_build:
                raise ValueError("preview requires the current native host build")
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
        subprocess.CalledProcessError,
    ) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
