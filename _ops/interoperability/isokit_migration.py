#!/usr/bin/env python3
"""Exact-pin, Codex-only Isokit canary. Source acceptance and human consent are external.

Only one absent ~/.codex/skills/isokit link may be published. This interface
neither runs a native worker nor authorizes retention. Rollback removes only
the exact inode recorded before atomic no-clobber publication.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import stat
import subprocess
import sys
import tomllib
import uuid

HERE = Path(__file__).absolute().parent
HELPERS = {
    "original_sources.py": "6e0725f4013c022f0790ee52d01e1b2a2533065d3df4632d3b825594526d7c64",
    "skill_migration.py": "63338247bd1af57f492a46a1d8a20fc2585ecf826da0a37b3ac1bfe553300b11",
    "inventory.py": "5414d384788924f66f7ed324aa2c0092c5367a58ac914c36532c85a5fcd9f64e",
}
for _name, _digest in HELPERS.items():
    _path = HERE / _name
    if _path.is_symlink() or hashlib.sha256(_path.read_bytes()).hexdigest() != _digest:
        raise ValueError("accepted transaction helper changed")
sys.path.insert(0, str(HERE))
import skill_migration as shared

SCHEMA = "interoperability/isokit-canary/v1"
PIN = "f2301ce13d50e471ff1e8ae51fb5a41bf47eaf0a"
PREFIX = "local/skills/isokit"
PAYLOAD = "b63d4dd9332d6f6b87c7f879e7efbb1f0f73930f75e2eb2bf35ffe7ba76fce62"
RUNTIME = "bae8e853c1ba7ef0dfbce9d7755979838a4c386faa4c7eaf70de1779c152fc2f"
BROWSER_FILES = {
    "chromium_headless_shell-1248/chrome-headless-shell-mac-arm64/chrome-headless-shell":
        "77d8278b1ac9d0687fad4e817ea83023ede09b1deef36e1864b49ba194ac9634",
    "ffmpeg-1013/ffmpeg-mac": "e71dd6610cbc984022ff51b07a95f8d2526aba120406d8cdd0686f6421c464ac",
}
HOST_BUILD = "23880"
LINK_MODE = 0o700
canonical = shared.canonical
sha = shared.sha


def regular(path: Path) -> bytes:
    shared.no_symlink_components(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("unshared regular file required")
    return path.read_bytes()


def observation(path: Path) -> dict:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"kind": "absent"}
    if stat.S_ISLNK(info.st_mode):
        return {"kind": "symlink", "target": os.readlink(path), "device": info.st_dev,
                "inode": info.st_ino, "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid}
    result = {"kind": "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "special",
              "device": info.st_dev, "inode": info.st_ino, "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid}
    if result["kind"] == "file":
        result["sha256"] = sha(regular(path))
    return result


def directory(path: Path) -> dict:
    shared.no_symlink_components(path)
    value = observation(path)
    if value["kind"] != "directory" or value["uid"] != os.getuid():
        raise ValueError("real operator-owned directory required")
    return value


def implementation() -> str:
    rows = {"isokit_migration.py": sha(regular(Path(__file__).absolute()))}
    for name, digest in HELPERS.items():
        if sha(regular(HERE / name)) != digest:
            raise ValueError("accepted transaction helper changed")
        rows[name] = digest
    return sha(canonical(rows))


def host_observation() -> dict:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        raise ValueError("this canary is qualified for the explicit macOS arm64 host only")
    # This build's signed bundle is named ChatGPT.app but identifies as Codex.
    app = Path("/Applications/ChatGPT.app/Contents/Info.plist")
    data = plistlib.loads(regular(app))
    if data.get("CFBundleIdentifier") != "com.openai.codex" or str(data.get("CFBundleVersion")) != HOST_BUILD:
        raise ValueError("current Codex build differs from this canary contract")
    return {"host": "codex", "surface": "local-macos-desktop", "build": HOST_BUILD,
            "architecture": "arm64", "app_metadata_sha256": sha(regular(app))}


def tree_digest(root: Path) -> tuple[str, int]:
    directory(root)
    rows = {}
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            directory(Path(parent) / name)
        for name in files:
            path = Path(parent) / name
            rows[str(path.relative_to(root))] = sha(regular(path))
    return sha(canonical(rows)), len(rows)


def source_proof(home: Path, manifest: Path) -> dict:
    binding = shared.portability_manifest_proof(manifest)
    primary = shared.pinned_primary_observation(home, binding)
    root = home / "dev/capabilities/skills"
    rows = []
    for raw in shared.git_bytes(root, "ls-tree", "-rz", PIN, "--", PREFIX).split(b"\0"):
        if not raw:
            continue
        meta, raw_path = raw.split(b"\t", 1)
        mode, kind, blob = meta.decode().split()
        path = raw_path.decode()
        if kind != "blob" or mode not in {"100644", "100755"} or not path.startswith(PREFIX + "/"):
            raise ValueError("Isokit source escaped its fixed regular-file payload")
        payload = regular(root / path)
        if hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest() != blob:
            raise ValueError("Isokit tracked source changed")
        rows.append({"path": path, "mode": mode, "blob": blob, "sha256": sha(payload)})
    if len(rows) != 123 or sha(canonical(rows)) != PAYLOAD:
        raise ValueError("Isokit source does not match the exact approved pin")
    observed = set()
    desired = root / PREFIX
    expected_dirs = {"."}
    for row in rows:
        relative = Path(row["path"]).relative_to(PREFIX)
        parent = relative.parent
        while parent != Path("."):
            expected_dirs.add(str(parent))
            parent = parent.parent
    actual_dirs = set()
    for parent, dirs, files in os.walk(desired, followlinks=False):
        location = Path(parent)
        directory(location)
        actual_dirs.add(str(location.relative_to(desired)))
        if location == desired and "node_modules" in dirs:
            dirs.remove("node_modules")
        for name in dirs:
            directory(location / name)
        for name in files:
            path = location / name
            regular(path)
            observed.add(str(path.relative_to(root)))
    if observed != {row["path"] for row in rows} or actual_dirs != expected_dirs:
        raise ValueError("unreviewed file or directory in Isokit source")
    runtime = root / PREFIX / "node_modules/playwright-core"
    digest, count = tree_digest(runtime)
    if digest != RUNTIME or count != 115:
        raise ValueError("qualified Playwright runtime changed")
    browsers = home / ".local/share/personal-portability/playwright-browsers"
    directory(browsers)
    if any(sha(regular(browsers / path)) != digest for path, digest in BROWSER_FILES.items()):
        raise ValueError("approved browser bundle changed")
    return {"primary": primary, "manifest": binding, "isokit_payload_sha256": PAYLOAD,
            "isokit_file_count": len(rows), "runtime_sha256": RUNTIME,
            "runtime_file_count": count, "browser_files": BROWSER_FILES,
            "browser_root": str(browsers), "desired": str(root / PREFIX)}


def policy(home: Path, desired: Path) -> dict:
    config = home / ".codex/config.toml"
    row = observation(config)
    if row["kind"] == "absent":
        return {"config": row, "enablement": "unknown-no-override"}
    if row["kind"] != "file":
        raise ValueError("unsupported Codex configuration path")
    parsed = tomllib.loads(regular(config).decode())
    skills = parsed.get("skills", {})
    if not isinstance(skills, dict) or not isinstance(skills.get("config", []), list):
        raise ValueError("unsupported skill policy shape")
    targets = {home / ".codex/skills/isokit", home / ".agents/skills/isokit", desired}
    matched = []
    for item in skills.get("config", []):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("unsupported skill policy row")
        enabled = item.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            raise ValueError("unsupported skill enablement value")
        lexical = shared.normalize_config_path(item["path"], home).absolute()
        resolved = lexical.resolve(strict=False)
        if any(lexical in {p, p / "SKILL.md"} or resolved in {p.resolve(strict=False), (p / "SKILL.md").resolve(strict=False)} for p in targets):
            if enabled is False:
                raise ValueError("Isokit is explicitly disabled; preserve the owner opt-out")
            matched.append({"path_sha256": sha(str(lexical).encode()), "enabled": enabled})
    return {"config": row, "rows": matched, "enablement": "explicit-overrides-preserved" if matched else "unknown-no-override"}


def preserved(home: Path) -> list[dict]:
    paths = [home / ".codex", home / ".codex/skills"]
    for name in ("prompt-architect", "verification-before-completion"):
        paths.append(home / ".codex/skills" / name)
    for tool in (".agents", ".cursor", ".claude"):
        paths.extend([home / tool, home / tool / "skills", home / tool / "skills/isokit"])
    result = []
    for path in paths:
        shared.no_symlink_components(path.parent)
        result.append({"path": str(path), "state": observation(path)})
    if observation(home / ".agents/skills/isokit")["kind"] != "absent":
        raise ValueError("existing native Isokit alias needs separate owner reconciliation")
    return result


def write_once(path: Path, value: dict) -> None:
    with path.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(canonical(value) + b"\n")


def preview(args) -> dict:
    home = args.home.expanduser().absolute()
    directory(home)
    if os.environ.get("CODEX_HOME", str(home / ".codex")) != str(home / ".codex"):
        raise ValueError("non-default CODEX_HOME needs a separate owner contract")
    desired = home / "dev/capabilities/skills" / PREFIX
    source = source_proof(home, args.portability_manifest)
    target = home / ".codex/skills/isokit"
    parent = directory(target.parent)
    if observation(target)["kind"] != "absent":
        raise ValueError("canary requires an absent target; no existing path is adopted or replaced")
    kept = preserved(home)
    config = policy(home, desired)
    host = host_observation()
    operation = shared.private_operation_path(args.operation_dir, (home / "dev", home / ".codex", home / ".agents", home / ".cursor", home / ".claude"))
    directory(operation.parent)
    operation.mkdir(mode=0o700)
    try:
        identifier = str(uuid.uuid4())
        stage = target.parent / (".isokit-canary-" + identifier)
        if observation(stage)["kind"] != "absent":
            raise ValueError("canary staging conflict")
        plan = {"schema": SCHEMA, "mode": "canary", "operation_id": identifier,
                "operation_dir": str(operation), "operation_root": directory(operation),
                "home": str(home), "source": source, "host": host, "policy": config,
                "target": str(target), "parent": parent, "staging": str(stage),
                "preserved": kept, "implementation_sha256": implementation(),
                "retention_authorized": False, "native_qualified": False,
                "affected_sessions": "All Codex sessions scanning the shared skill root; existing contexts may retain prior discovery.",
                "native_worker": "Separate exact approval required; one fresh worker with a 120-second deadline, followed by exact rollback. This interface starts none."}
        digest = sha(canonical(plan))
        write_once(operation / "operation.lock", {})
        write_once(operation / "operation.json", {**plan, "action_sha256": digest})
        return {"status": "previewed", "operation_dir": str(operation), "action_sha256": digest,
                "target": str(target), "desired": str(desired), "retention_authorized": False}
    except BaseException:
        # Only preview-owned files may be removed; preserve unexpected concurrent content.
        for name in ("operation.json", "operation.lock"):
            path = operation / name
            if path.is_file() and not path.is_symlink():
                path.unlink()
        operation.rmdir()
        raise


def load(operation: Path) -> dict:
    operation = operation.expanduser().absolute()
    if directory(operation)["mode"] != 0o700:
        raise ValueError("operation root is not private")
    path = operation / "operation.json"
    if stat.S_IMODE(path.lstat().st_mode) != 0o600 or path.lstat().st_uid != os.getuid():
        raise ValueError("operation record is not private and operator-owned")
    plan = json.loads(regular(path))
    digest = plan.pop("action_sha256")
    if sha(canonical(plan)) != digest or plan.get("schema") != SCHEMA or plan.get("mode") != "canary":
        raise ValueError("operation digest or schema changed")
    plan["action_sha256"] = digest
    home = Path(plan["home"])
    expected_target = home / ".codex/skills/isokit"
    identifier = str(uuid.UUID(plan["operation_id"]))
    if (plan["operation_dir"] != str(operation) or directory(operation) != plan["operation_root"]
            or plan["target"] != str(expected_target)
            or plan["staging"] != str(expected_target.parent / (".isokit-canary-" + identifier))
            or plan["source"]["desired"] != str(home / "dev/capabilities/skills" / PREFIX)
            or plan["retention_authorized"] is not False or plan["native_qualified"] is not False
            or implementation() != plan["implementation_sha256"]):
        raise ValueError("operation escaped its fixed identity, paths or implementation")
    return plan


@contextmanager
def operation_lock(operation: Path):
    operation = operation.expanduser().absolute()
    shared.no_symlink_components(operation)
    path = operation / "operation.lock"
    info = path.lstat()
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        current = os.fstat(descriptor)
        if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                or stat.S_IMODE(current.st_mode) != 0o600 or current.st_uid != os.getuid()
                or (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino)):
            raise ValueError("private operation lock changed")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def unchanged(plan: dict, *, source: bool = True) -> None:
    home = Path(plan["home"])
    target = Path(plan["target"])
    if directory(target.parent) != plan["parent"]:
        raise ValueError("managed parent identity changed")
    if source and (source_proof(home, Path(plan["source"]["manifest"]["manifest_path"])) != plan["source"]
                   or host_observation() != plan["host"] or policy(home, Path(plan["source"]["desired"])) != plan["policy"]
                   or preserved(home) != plan["preserved"]):
        raise ValueError("source, host, policy or preserved path changed")


def ownership(plan: dict) -> dict | None:
    path = Path(plan["operation_dir"]) / "link-owner.json"
    if observation(path)["kind"] == "absent":
        return None
    if stat.S_IMODE(path.lstat().st_mode) != 0o600 or path.lstat().st_uid != os.getuid():
        raise ValueError("link-owner receipt is not private and operator-owned")
    row = json.loads(regular(path))
    link = row.get("link", {})
    if (set(row) != {"action_sha256", "link"} or row["action_sha256"] != plan["action_sha256"]
            or link.get("kind") != "symlink" or link.get("target") != plan["source"]["desired"]
            or link.get("uid") != os.getuid() or not isinstance(link.get("inode"), int)
            or not isinstance(link.get("device"), int) or link.get("mode") != LINK_MODE):
        raise ValueError("link-owner receipt changed")
    return link


def apply(args, *, rollback: bool = False) -> dict:
    plan = load(args.operation_dir)
    if args.approve != plan["action_sha256"]:
        raise ValueError("exact action digest and external operator approval required")
    unchanged(plan, source=not rollback)
    target, stage = Path(plan["target"]), Path(plan["staging"])
    owned = ownership(plan)
    if rollback:
        for path in (target, stage):
            observed = observation(path)
            if observed["kind"] != "absent" and (owned is None or observed != owned):
                raise ValueError("later path edits are preserved; exact rollback refused")
        for path in (target, stage):
            if observation(path)["kind"] != "absent":
                path.unlink()
        marker = Path(plan["operation_dir"]) / "rolled-back.json"
        if observation(marker)["kind"] == "absent":
            write_once(marker, {"action_sha256": plan["action_sha256"]})
        return {"status": "rolled-back", "retention_authorized": False}
    if observation(Path(plan["operation_dir"]) / "rolled-back.json")["kind"] != "absent":
        raise ValueError("rolled-back canary cannot be replayed; prepare a new exact operation")
    if owned is not None and observation(target) == owned:
        if observation(stage)["kind"] != "absent":
            if observation(stage) != owned:
                raise ValueError("later staging edits are preserved")
            stage.unlink()
        return {"status": "already-applied", "native_qualified": False, "retention_authorized": False}
    if observation(target)["kind"] != "absent":
        raise ValueError("canary target changed; no replacement permitted")
    if owned is None:
        if observation(stage)["kind"] != "absent":
            raise ValueError("unowned staging path preserved")
        os.symlink(plan["source"]["desired"], stage)
        shared.set_symlink_mode(stage, LINK_MODE)
        owned = observation(stage)
        write_once(Path(plan["operation_dir"]) / "link-owner.json", {"action_sha256": plan["action_sha256"], "link": owned})
    if observation(stage) != owned:
        raise ValueError("owned staging identity changed")
    unchanged(plan)
    os.link(stage, target, follow_symlinks=False)
    stage.unlink()
    if observation(target) != owned:
        raise ValueError("published link identity mismatch")
    return {"status": "applied-canary", "native_qualified": False, "retention_authorized": False}


def verify(args) -> dict:
    plan = load(args.operation_dir)
    unchanged(plan, source=False)
    target, stage = Path(plan["target"]), Path(plan["staging"])
    if observation(stage)["kind"] != "absent":
        raise ValueError("interrupted staging requires exact apply or rollback")
    value = observation(target)
    if value["kind"] == "absent":
        home = Path(plan["home"])
        if (preserved(home) != plan["preserved"]
                or observation(home / ".codex/config.toml") != plan["policy"]["config"]):
            raise ValueError("target preimage restored but preserved path or config drift remains")
        return {"status": "verified-preimage", "native_qualified": False,
                "retention_authorized": False, "preserved_unchanged": True}
    if value != ownership(plan):
        raise ValueError("published link is not the exact operation-owned inode")
    unchanged(plan)
    return {"status": "verified-canary", "native_qualified": False, "retention_authorized": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("preview", "apply", "verify", "rollback"))
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--operation-dir", type=Path, required=True)
    parser.add_argument("--portability-manifest", type=Path)
    parser.add_argument("--approve")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        if args.operation == "preview":
            if args.portability_manifest is None or args.approve is not None:
                raise ValueError("preview requires the exact manifest and is not approval")
            result = preview(args)
        else:
            with operation_lock(args.operation_dir):
                result = verify(args) if args.operation == "verify" else apply(args, rollback=args.operation == "rollback")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "refused", "reason": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
